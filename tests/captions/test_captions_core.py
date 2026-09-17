# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the 0.5 captions backend core."""

from __future__ import annotations

import concurrent.futures
import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import civiccast.captions.runtime as runtime_module
from civiccast.captions import (
    AudioChunk,
    CaptionHypothesis,
    CaptionPipeline,
    CaptionRuntime,
    CaptionStabilizer,
    CustomVocabulary,
    FasterWhisperRuntime,
    FasterWhisperRuntimeUnavailableError,
    InMemoryCaptionReviewStore,
    LiveCaptionWorker,
    render_webvtt,
)
from civiccast.native.caption_tiers import (
    CAPTION_TIER_REGISTRY,
    FLOOR_TIER_ID,
    LARGE_V3_TIER_ID,
)
from civiccast.stream.packager import SlateOnlyResult
from civiccast.translate import DeterministicSpanishTranslator, TranslationTarget


def _hypothesis(
    text: str,
    start: float = 0.0,
    end: float = 3.8,
    confidence: float = 0.9,
) -> CaptionHypothesis:
    return CaptionHypothesis(
        source_id="runtime-a",
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=confidence,
    )


def _word_window(start: float, words: list[tuple[str, float, float]]) -> CaptionHypothesis:
    return CaptionHypothesis.model_validate(
        {
            "source_id": f"window-{start}",
            "start_seconds": start,
            "end_seconds": start + 10,
            "text": " ".join(w[0] for w in words),
            "audio_window_start_seconds": start,
            "audio_window_end_seconds": start + 10,
            "words": [
                {"text": text, "start_seconds": a, "end_seconds": b, "confidence": 0.9}
                for text, a, b in words
            ],
        }
    )


class TestModels:
    def test_audio_window_metadata_requires_a_complete_forward_pair(self) -> None:
        for metadata in (
            {"audio_window_start_seconds": 0},
            {"audio_window_start_seconds": 2, "audio_window_end_seconds": 1},
        ):
            with pytest.raises(ValidationError):
                CaptionHypothesis(
                    source_id="x", start_seconds=0, end_seconds=1, text="speech", **metadata
                )

    def test_audio_chunk_requires_forward_time(self) -> None:
        with pytest.raises(ValidationError, match="end_seconds"):
            AudioChunk(
                chunk_id="bad",
                start_seconds=4.0,
                end_seconds=4.0,
                sample_rate_hz=16_000,
                pcm_s16le=b"",
            )

    def test_custom_vocabulary_dedupes_case_and_spacing(self) -> None:
        vocab = CustomVocabulary(
            terms=[" Councilmember Rivera ", "councilmember rivera", "Zoning Board"],
            initial_prompt="Use civic meeting vocabulary.",
        )
        assert vocab.terms == ["Councilmember Rivera", "Zoning Board"]

    def test_hypothesis_strips_internal_whitespace(self) -> None:
        h = _hypothesis("  motion   carries  ")
        assert h.text == "motion carries"


class TestCaptionStabilizer:
    def test_timed_word_preserves_first_window_low_confidence(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        first = _word_window(0, [("motion", 6, 7), ("carries", 7, 8)]).model_copy(
            update={"confidence": 0.1}
        )
        stabilizer.observe(first)
        cues = stabilizer.observe(_word_window(5, [("motion", 6, 7), ("carries", 7, 8)]))
        assert cues[0].confidence == 0.1
        assert cues[0].low_confidence

    def test_timed_word_flush_is_review_only_and_idempotent(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_word_window(0, [("once", 1, 2), ("heard", 2, 3)]))
        assert stabilizer.flush() == []
        assert stabilizer.committed() == []
        assert [cue.text for cue in stabilizer.expired_unconfirmed()] == ["once heard"]
        assert stabilizer.flush() == []
        assert len(stabilizer.expired_unconfirmed()) == 1

    def test_word_confirmation_allows_first_window_to_grow_without_new_start(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        first = _word_window(0, [("motion", 1, 2), ("carries", 2, 3)]).model_copy(
            update={"audio_window_end_seconds": 5, "end_seconds": 5}
        )
        assert stabilizer.observe(first) == []
        cues = stabilizer.observe(_word_window(0, [("motion", 1, 2), ("carries", 2, 3)]))
        assert [cue.text for cue in cues] == ["motion carries"]

    def test_live_missing_word_observations_are_visible_review_only(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        missing = _word_window(0, [("speech", 1, 2)]).model_copy(update={"words": []})
        assert stabilizer.observe(missing) == []
        assert [cue.text for cue in stabilizer.expired_unconfirmed()] == ["speech"]

    def test_word_confirmation_requires_time_and_distinct_windows(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        first = _word_window(0, [("motion", 1, 2), ("carries", 2, 3)])
        assert stabilizer.observe(first) == []
        assert stabilizer.observe(first) == []
        assert stabilizer.observe(_word_window(5, [("motion", 6, 7), ("carries", 7, 8)])) == []
        assert stabilizer.committed() == []

    def test_word_confirmation_counts_each_word_without_lending_to_new_tail(self) -> None:
        stabilizer = CaptionStabilizer(live=True, stable_windows=3)
        assert stabilizer.observe(_word_window(0, [("motion", 6, 7), ("carries", 7, 8)])) == []
        assert (
            stabilizer.observe(
                _word_window(
                    1, [("motion", 6, 7), ("carries", 7, 8), ("new", 8, 9), ("tail", 9, 10)]
                )
            )
            == []
        )
        cues = stabilizer.observe(
            _word_window(2, [("motion", 6, 7), ("carries", 7, 8), ("new", 8, 9), ("tail", 9, 10)])
        )
        assert [cue.text for cue in cues] == ["motion carries"]
        cues = stabilizer.observe(_word_window(3, [("new", 8, 9), ("tail", 9, 10)]))
        assert [cue.text for cue in cues] == ["new tail"]

    def test_zero_duration_word_is_reviewed_not_given_invented_duration(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        assert stabilizer.observe(_word_window(0, [("zero", 6, 6), ("duration", 6, 6)])) == []
        assert stabilizer.observe(_word_window(5, [("zero", 6, 6), ("duration", 6, 6)])) == []
        assert stabilizer.observe(_word_window(10, [("other", 11, 12), ("speech", 12, 13)])) == []
        assert stabilizer.committed() == []
        assert any("zero" in cue.text for cue in stabilizer.expired_unconfirmed())

    def test_live_word_alignment_confirms_interior_phrase_not_window_suffix(self) -> None:
        stabilizer = CaptionStabilizer(live=True)

        def window(start: int, words: list[tuple[str, float, float]]) -> CaptionHypothesis:
            return CaptionHypothesis.model_validate(
                {
                    "source_id": f"window-{start}",
                    "start_seconds": start,
                    "end_seconds": start + 10,
                    "text": " ".join(w[0] for w in words),
                    "audio_window_start_seconds": start,
                    "audio_window_end_seconds": start + 10,
                    "words": [
                        {"text": text, "start_seconds": a, "end_seconds": b, "confidence": 0.9}
                        for text, a, b in words
                    ],
                }
            )

        old = window(
            0, [("opening", 1, 2), ("motion", 6, 7), ("carries", 7, 8), ("hallucinated", 8, 9)]
        )
        new = window(5, [("motion", 6.1, 7.1), ("carries", 7.1, 8.1), ("next", 11, 12)])
        assert stabilizer.observe(old) == []
        cues = stabilizer.observe(new)
        assert [cue.text for cue in cues] == ["motion carries"]
        assert stabilizer.observe(new) == []
        assert cues[0].start_seconds == 6.1
        assert cues[0].end_seconds == 8

    def test_commits_after_two_stable_observations(self) -> None:
        stabilizer = CaptionStabilizer()
        assert stabilizer.observe(_hypothesis("motion carries")) == []

        committed = stabilizer.observe(_hypothesis("Motion carries"))

        assert len(committed) == 1
        assert committed[0].cue_id == "cue-000000"
        assert committed[0].text == "Motion carries"
        assert stabilizer.committed() == committed

    def test_changed_hypothesis_resets_stability_count(self) -> None:
        stabilizer = CaptionStabilizer()
        assert stabilizer.observe(_hypothesis("motion carries")) == []
        assert stabilizer.observe(_hypothesis("motion failed")) == []

        committed = stabilizer.observe(_hypothesis("motion failed"))

        assert len(committed) == 1
        assert committed[0].text == "motion failed"

    def test_committed_cue_is_not_rewritten_by_later_hypothesis(self) -> None:
        stabilizer = CaptionStabilizer()
        stabilizer.observe(_hypothesis("motion carries"))
        first = stabilizer.observe(_hypothesis("motion carries"))[0]

        later = stabilizer.observe(_hypothesis("motion failed"))

        assert later == []
        assert stabilizer.committed() == [first]

    def test_four_second_window_buckets_cues(self) -> None:
        stabilizer = CaptionStabilizer(window_seconds=4.0)
        stabilizer.observe(_hypothesis("first window", start=0.2, end=3.9))
        first = stabilizer.observe(_hypothesis("first window", start=0.3, end=3.8))[0]
        stabilizer.observe(_hypothesis("second window", start=4.1, end=7.9))
        second = stabilizer.observe(_hypothesis("second window", start=4.2, end=7.8))[0]

        assert first.cue_id == "cue-000000"
        assert second.cue_id == "cue-000001"

    def test_multiple_segments_in_one_window_stabilize_independently(self) -> None:
        """Real Whisper windows can contain multiple chronological segments.

        The second observation can also drift across the four-second bucket
        boundary. Neither fact may make one valid cue overwrite another.
        """

        stabilizer = CaptionStabilizer(window_seconds=4.0)
        assert (
            stabilizer.observe(
                _hypothesis(
                    "The council meeting will come to order.",
                    start=0.75,
                    end=3.01,
                )
            )
            == []
        )
        assert stabilizer.observe(_hypothesis("Public comment.", start=3.01, end=4.93)) == []

        council = stabilizer.observe(
            _hypothesis(
                "The council meeting will come to order.",
                start=1.0,
                end=3.02,
            )
        )
        public_comment = stabilizer.observe(_hypothesis("Public comment.", start=4.16, end=4.98))

        assert [cue.text for cue in council] == ["The council meeting will come to order."]
        assert [cue.text for cue in public_comment] == ["Public comment."]
        assert [cue.text for cue in stabilizer.committed()] == [
            "The council meeting will come to order.",
            "Public comment.",
        ]
        assert len({cue.cue_id for cue in stabilizer.committed()}) == 2

    def test_live_confirmation_commits_reworded_continuous_speech(self) -> None:
        """Only the repeated phrase may air; new surrounding words wait.

        The former assertion required the uncorroborated new suffix to air.
        That encoded the defect, not the intended two-observation contract.
        The 5-second advance/9-second window is real tap geometry, but its
        overlap alone is not evidence that either whole transcript is correct.
        """

        stabilizer = CaptionStabilizer(live=True)
        assert (
            stabilizer.observe(
                _hypothesis("Dewpoints in Arizona. We're in the 40s.", start=0.0, end=9.0)
            )
            == []
        )
        # The shared phrase is repeated; the new "and 30s" suffix is not.
        committed = stabilizer.observe(
            _hypothesis("We're in the 40s and 30s, so very much shuts down.", start=5.0, end=14.0)
        )

        assert len(committed) == 1
        assert committed[0].text == "We're in the 40s."
        assert (committed[0].start_seconds, committed[0].end_seconds) == (5.0, 9.0)

    def test_live_overlap_does_not_confirm_unrelated_text(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("the motion carries unanimously", 0, 9))
        assert stabilizer.observe(_hypothesis("aliens landed in Denver", 5, 14)) == []

    def test_live_shared_phrase_does_not_air_one_off_suffix(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("opening words the motion carries", 0, 9))
        cues = stabilizer.observe(_hypothesis("the motion carries aliens landed", 5, 14))
        assert [cue.text for cue in cues] == ["the motion carries"]
        assert stabilizer.observe(_hypothesis("entirely different later speech", 10, 19)) == []
        assert "aliens" not in " ".join(c.text for c in stabilizer.committed())

    def test_live_preserves_tail_until_next_phrase_confirmation(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("opening words the motion carries", 0, 9))
        first = stabilizer.observe(_hypothesis("the motion carries next agenda item", 5, 14))
        second = stabilizer.observe(_hypothesis("next agenda item public comment starts", 10, 19))
        assert [c.text for c in first + second] == ["the motion carries", "next agenda item"]

    def test_live_exact_text_requires_temporal_overlap(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("motion carries", 0, 1))
        assert stabilizer.observe(_hypothesis("motion carries", 3, 4)) == []

    def test_live_uses_audio_window_geometry_not_asr_segment_fraction(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        first = _hypothesis("next weekend when we get dry", 6, 13.28).model_copy(
            update={"audio_window_start_seconds": 6, "audio_window_end_seconds": 15}
        )
        second = _hypothesis("when we get dry air from north", 11.53, 18.01).model_copy(
            update={"audio_window_start_seconds": 11, "audio_window_end_seconds": 20}
        )
        stabilizer.observe(first)
        cues = stabilizer.observe(second)
        assert [cue.text for cue in cues] == ["when we get dry"]
        assert (cues[0].start_seconds, cues[0].end_seconds) == (11.53, 13.28)

    def test_live_same_audio_window_cannot_confirm_itself(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        hypothesis = _hypothesis("motion carries", 1, 4).model_copy(
            update={"audio_window_start_seconds": 0, "audio_window_end_seconds": 5}
        )
        assert stabilizer.observe(hypothesis) == []
        assert stabilizer.observe(hypothesis) == []

    def test_live_cue_is_bounded_by_shared_audio_even_when_asr_overruns(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        first = _hypothesis("motion carries", 0, 12).model_copy(
            update={"audio_window_start_seconds": 0, "audio_window_end_seconds": 9}
        )
        second = _hypothesis("motion carries", 4, 16).model_copy(
            update={"audio_window_start_seconds": 5, "audio_window_end_seconds": 14}
        )
        stabilizer.observe(first)
        cues = stabilizer.observe(second)
        assert (cues[0].start_seconds, cues[0].end_seconds) == (5, 9)

    def test_live_repeated_window_does_not_reintroduce_committed_prefix(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("alpha shared phrase", 0, 9))
        cues = stabilizer.observe(_hypothesis("shared phrase beta", 5, 14))
        cues += stabilizer.observe(_hypothesis("shared phrase beta", 5, 14))
        cues += stabilizer.observe(_hypothesis("shared phrase beta", 5, 14))
        assert [cue.text for cue in cues] == ["shared phrase", "beta"]

    def test_live_single_shared_word_does_not_confirm_changed_phrase(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("the motion", 0, 9))
        assert stabilizer.observe(_hypothesis("motion failed unanimously", 5, 14)) == []

    def test_live_confirmation_honors_three_observation_requirement(self) -> None:
        stabilizer = CaptionStabilizer(live=True, stable_windows=3)
        assert stabilizer.observe(_hypothesis("motion carries", 0, 9)) == []
        assert stabilizer.observe(_hypothesis("motion carries", 1, 10)) == []
        cues = stabilizer.observe(_hypothesis("motion carries", 2, 11))
        assert [cue.text for cue in cues] == ["motion carries"]
        assert (cues[0].start_seconds, cues[0].end_seconds) == (2, 9)

    def test_live_confirmation_preserves_lowest_confidence(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("motion carries", 0, 9, confidence=0.2))
        cues = stabilizer.observe(_hypothesis("motion carries", 1, 10, confidence=0.99))
        assert cues[0].confidence == 0.2
        assert cues[0].low_confidence

    def test_live_partial_confirmation_does_not_lend_its_count_to_new_tail(self) -> None:
        stabilizer = CaptionStabilizer(live=True, stable_windows=3)
        assert stabilizer.observe(_hypothesis("opening words motion carries", 0, 9)) == []
        assert stabilizer.observe(_hypothesis("motion carries next agenda item", 1, 10)) == []
        # The tail has appeared twice, not three times like the confirmed subset.
        assert stabilizer.observe(_hypothesis("next agenda item public comment", 2, 11)) == []
        cues = stabilizer.observe(_hypothesis("next agenda item", 3, 12))
        assert [cue.text for cue in cues] == ["next agenda item"]
        assert (cues[0].start_seconds, cues[0].end_seconds) == (3, 10)

    def test_live_unshared_prefix_is_reviewable_not_aired(self) -> None:
        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("unconfirmed introduction motion carries", 0, 9))
        stabilizer.observe(_hypothesis("motion carries next agenda item", 5, 14))
        assert [cue.text for cue in stabilizer.expired_unconfirmed()] == [
            "unconfirmed introduction"
        ]
        assert stabilizer.expired_unconfirmed()[0].low_confidence

    def test_live_confirmation_still_resets_on_a_correction(self) -> None:
        """A new reading at the SAME start is a correction, not a re-hearing."""

        stabilizer = CaptionStabilizer(live=True)
        assert stabilizer.observe(_hypothesis("motion carries", start=0.0, end=5.0)) == []
        assert stabilizer.observe(_hypothesis("motion failed", start=0.0, end=5.0)) == []

        committed = stabilizer.observe(_hypothesis("motion failed", start=0.0, end=5.0))

        assert len(committed) == 1
        assert committed[0].text == "motion failed"

    def test_live_confirmation_never_commits_a_lone_uncorroborated_cue(self) -> None:
        """One window alone must not air: live mode still needs corroboration."""

        stabilizer = CaptionStabilizer(live=True)
        assert stabilizer.observe(_hypothesis("single window speech", start=0.0, end=9.0)) == []
        assert stabilizer.committed() == []

    def test_live_confirmation_rejects_a_tiny_overlap(self) -> None:
        """A sliver of overlap must NOT corroborate an unrelated long cue.

        Regression for the live-confirmation boundary: the guard compared the
        incoming start against ``pending.hypothesis.end_seconds`` -- the ASR
        hypothesis's CLAIMED end, not the audio span actually re-heard.  A
        pending 8 s window therefore "contained" a later start that overlapped
        it by as little as one millisecond (or one microsecond), so an
        otherwise uncorroborated 8 s caption could be confirmed by a completely
        different reading.  Corroboration must require a SUBSTANTIVE overlap
        with the pending window, not mere adjacency to its claim.
        """

        stabilizer = CaptionStabilizer(live=True)
        assert (
            stabilizer.observe(_hypothesis("the quick brown fox jumps", start=0.0, end=8.0)) == []
        )
        # Only 1 ms inside the pending claim -> must NOT confirm.
        committed = stabilizer.observe(
            _hypothesis("completely different words here", start=7.999, end=15.0)
        )

        assert committed == []
        assert stabilizer.committed() == []

    def test_live_confirmation_rejects_a_sub_millisecond_overlap(self) -> None:
        """Even a 1 microsecond overlap must not corroborate an unrelated cue."""

        stabilizer = CaptionStabilizer(live=True)
        stabilizer.observe(_hypothesis("first unrelated long cue", start=0.0, end=8.0))
        committed = stabilizer.observe(
            _hypothesis("second unrelated different cue", start=7.999999, end=16.0)
        )

        assert committed == []
        assert stabilizer.committed() == []

    def test_low_confidence_flag_uses_threshold(self) -> None:
        stabilizer = CaptionStabilizer(low_confidence_threshold=0.8)
        stabilizer.observe(_hypothesis("uncertain name", confidence=0.62))
        cue = stabilizer.observe(_hypothesis("uncertain name", confidence=0.62))[0]

        assert cue.low_confidence is True


class TestRuntimeBoundary:
    def _audio_chunk(self) -> AudioChunk:
        return AudioChunk(
            chunk_id="chunk-1",
            start_seconds=10.0,
            end_seconds=14.0,
            sample_rate_hz=16_000,
            pcm_s16le=b"\x00\x00" * 160,
        )

    def test_runtime_protocol_accepts_test_runtime(self) -> None:
        class TestRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                yield _hypothesis("hello council")

        runtime: CaptionRuntime = TestRuntime()
        chunks = [
            AudioChunk(
                chunk_id="chunk-1",
                start_seconds=0.0,
                end_seconds=1.0,
                sample_rate_hz=16_000,
                pcm_s16le=b"\x00\x00",
            )
        ]
        assert [h.text for h in runtime.transcribe(chunks)] == ["hello council"]

    def test_faster_whisper_runtime_fails_actionably_when_optional_dependency_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_missing() -> Any:
            raise FasterWhisperRuntimeUnavailableError(
                "faster-whisper is not installed. Install CivicCast with "
                "`civiccast[captions-runtime]`."
            )

        monkeypatch.setattr(runtime_module, "_load_whisper_model_class", raise_missing)
        runtime = FasterWhisperRuntime()

        with pytest.raises(FasterWhisperRuntimeUnavailableError, match="captions-runtime"):
            list(runtime.transcribe([self._audio_chunk()]))

    def test_native_runtime_uses_packaged_model_path_without_alias_lookup(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        model = tmp_path / "faster-whisper-large-v3"
        model.mkdir()
        for name in runtime_module.REQUIRED_LOCAL_MODEL_FILES:
            (model / name).write_bytes(b"present")
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model))
        monkeypatch.setenv("CIVICCAST_WHISPER_DEVICE", "cpu")
        monkeypatch.setenv("CIVICCAST_WHISPER_COMPUTE_TYPE", "int8")

        runtime = FasterWhisperRuntime(model_size_or_path="large-v3")

        assert runtime.model_size_or_path == str(model.resolve())
        assert runtime.device == "cpu"
        assert runtime.compute_type == "int8"

    def test_default_compute_type_is_portable_int8_for_cpu_only_stations(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
        monkeypatch.delenv("CIVICCAST_WHISPER_COMPUTE_TYPE", raising=False)

        runtime = FasterWhisperRuntime()

        assert runtime.device == "auto"
        assert runtime.compute_type == "int8"

    def test_live_cuda_has_capacity_for_three_channel_segment_cadence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CIVICCAST_WHISPER_NUM_WORKERS", raising=False)

        gpu = FasterWhisperRuntime(live=True, device="cuda", compute_type="float16")
        cpu = FasterWhisperRuntime(live=True, device="cpu")
        batch = FasterWhisperRuntime(live=False, device="cuda", compute_type="float16")

        assert gpu.num_workers == runtime_module.LIVE_TAP_CUDA_NUM_WORKERS == 3
        assert cpu.num_workers == 1
        assert batch.num_workers == 1

    def test_batch_cpu_threads_raises_on_unparseable_env_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Round 4: ``live=False`` keeps the pre-existing fail-fast behavior
        for ``CIVICCAST_WHISPER_CPU_THREADS`` -- a batch/VOD pass is never
        constructed unguarded at control-plane startup, so a mistyped value
        should raise loudly rather than being clamped like the live tap.
        Fails if ``_resolved_whisper_cpu_threads_env`` starts clamping batch
        the same way it clamps live."""

        monkeypatch.setenv("CIVICCAST_WHISPER_CPU_THREADS", "not-a-number")

        with pytest.raises(ValueError, match="CIVICCAST_WHISPER_CPU_THREADS must be an integer"):
            FasterWhisperRuntime(live=False)

    def test_batch_cpu_threads_raises_on_negative_env_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_WHISPER_CPU_THREADS", "-1")

        with pytest.raises(ValueError, match="CIVICCAST_WHISPER_CPU_THREADS must be at least 0"):
            FasterWhisperRuntime(live=False)

    def test_batch_cpu_threads_honors_zero_as_every_core(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``0`` ("every core") stays HONOURED for the batch/VOD runtime -- a
        finalization pass is allowed to use the whole machine. Only the LIVE
        tap refuses ``0``. Fails if batch starts refusing/clamping ``0`` the
        way the live tap does."""

        monkeypatch.setenv("CIVICCAST_WHISPER_CPU_THREADS", "0")

        runtime = FasterWhisperRuntime(live=False)

        assert runtime.cpu_threads == 0

    def test_live_caps_whisper_cpu_threads_above_ceiling_with_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Round 4: the LIVE tap must never approach 'every core' again, so a
        generic ``CIVICCAST_WHISPER_CPU_THREADS`` above
        ``LIVE_TAP_CPU_THREADS_CEILING`` (2) is capped at the ceiling rather
        than honored, and the cap is visible (a WARNING), not silent. Fails
        if the live tap starts passing an oversized value straight through."""

        monkeypatch.setenv("CIVICCAST_WHISPER_CPU_THREADS", "8")
        monkeypatch.delenv("CIVICCAST_CAPTION_TAP_CPU_THREADS", raising=False)

        with caplog.at_level("WARNING", logger="civiccast.captions.runtime"):
            runtime = FasterWhisperRuntime(live=True)

        assert runtime.cpu_threads == runtime_module.LIVE_TAP_CPU_THREADS_CEILING
        assert runtime_module.LIVE_TAP_CPU_THREADS_CEILING == 2
        assert any(
            "CIVICCAST_WHISPER_CPU_THREADS" in record.message and "capping" in record.message
            for record in caplog.records
        )

    def test_live_caps_caption_tap_cpu_threads_above_ceiling_with_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Same ceiling, but through the live-only
        ``CIVICCAST_CAPTION_TAP_CPU_THREADS`` variable that feeds
        ``default_live_tap_cpu_threads()`` rather than the generic
        ``CIVICCAST_WHISPER_CPU_THREADS`` override. Uses 8 (not 2) so the
        test still fails if the ceiling stops being enforced -- asserting
        against the ceiling's own value would pass even with the cap
        deleted."""

        monkeypatch.delenv("CIVICCAST_WHISPER_CPU_THREADS", raising=False)
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_CPU_THREADS", "8")

        with caplog.at_level("WARNING", logger="civiccast.captions.runtime"):
            runtime = FasterWhisperRuntime(live=True)

        assert runtime.cpu_threads == runtime_module.LIVE_TAP_CPU_THREADS_CEILING
        assert runtime_module.LIVE_TAP_CPU_THREADS_CEILING == 2
        assert any(
            "CIVICCAST_CAPTION_TAP_CPU_THREADS" in record.message and "capping" in record.message
            for record in caplog.records
        )

    def test_faster_whisper_model_initializes_once_under_concurrent_channels(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        instances: list[object] = []

        class FakeWhisperModel:
            def __init__(self, _model_size_or_path: str, **_kwargs: Any) -> None:
                time.sleep(0.05)
                instances.append(self)

        monkeypatch.setattr(
            runtime_module,
            "_load_whisper_model_class",
            lambda: FakeWhisperModel,
        )
        runtime = FasterWhisperRuntime(model_size_or_path="tiny")

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            models = list(pool.map(lambda _index: runtime._model_instance(), range(3)))

        assert len(instances) == 1
        assert models == [instances[0], instances[0], instances[0]]

    def test_cuda_load_failure_falls_back_to_cpu_int8_instead_of_killing_captions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Owner ruling 2026-08-15 wires device=cuda from the hardware probe;
        the pinned payload does not (yet) ship cuBLAS/cuDNN, so a CUDA load
        failure must degrade to the validated cpu/int8 baseline — slower
        captions, never no captions."""

        attempts: list[dict[str, Any]] = []

        class CudaLessWhisperModel:
            def __init__(self, _model_size_or_path: str, **kwargs: Any) -> None:
                attempts.append(kwargs)
                if kwargs.get("device") == "cuda":
                    raise RuntimeError("Library cublas64_12.dll is not found")

        monkeypatch.setattr(
            runtime_module,
            "_load_whisper_model_class",
            lambda: CudaLessWhisperModel,
        )
        monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
        monkeypatch.delenv("CIVICCAST_WHISPER_COMPUTE_TYPE", raising=False)
        runtime = FasterWhisperRuntime(
            model_size_or_path="tiny", device="cuda", compute_type="float16", live=True
        )

        model = runtime._model_instance()

        assert model is not None
        assert [a.get("device") for a in attempts] == ["cuda", "cpu"]
        assert attempts[0]["num_workers"] == 3
        assert "num_workers" not in attempts[1]
        assert runtime.num_workers == 1
        assert attempts[-1]["compute_type"] == "int8"
        assert runtime.device == "cpu"
        assert runtime.compute_type == "int8"

    def test_cpu_load_failure_still_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """There is no safer tier below cpu — a cpu-device failure must
        surface, never be swallowed by the cuda fallback."""

        class BrokenWhisperModel:
            def __init__(self, _model_size_or_path: str, **_kwargs: Any) -> None:
                raise RuntimeError("model file corrupt")

        monkeypatch.setattr(
            runtime_module,
            "_load_whisper_model_class",
            lambda: BrokenWhisperModel,
        )
        monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
        runtime = FasterWhisperRuntime(model_size_or_path="tiny", device="cpu")

        with pytest.raises(RuntimeError, match="model file corrupt"):
            runtime._model_instance()

    def test_ensure_cuda_dll_directory_registers_the_staged_bin_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """TESTER4 (RTX 5070 Ti), real hardware: with both required DLLs
        staged AND on PATH, the CUDA backend still failed to load them --
        Windows' loader has ignored PATH for dependent-DLL resolution since
        Python 3.8 and needs `os.add_dll_directory` instead, the exact fix
        already proven for the staged GStreamer runtime. Also proves the
        per-directory idempotency: a second call for the SAME directory must
        not add_dll_directory again.

        Simulates Windows by REBINDING the module's own `os` reference to a
        shim namespace, never by monkeypatching the real stdlib `os` module.
        Patching the real `os.name` to "nt" on a non-Windows CI runner
        corrupts `pathlib` itself (pathlib picks its path flavour off
        `os.name` at import time and various call sites), which made
        `Path(cuda_bin).is_dir()` silently return False on Linux -- the
        function then no-op'd at the directory-exists guard for a reason
        that had nothing to do with the thing this test claims to verify.
        The shim leaves the real `os` (and therefore `pathlib`) untouched;
        only `civiccast.captions.runtime`'s own `os.name`/`os.add_dll_directory`
        lookups see the fake. `environ` is the REAL `os.environ` object
        (shared, not copied), so `monkeypatch.setenv`/`delenv` on it still
        take effect through the shim.
        """

        cuda_bin = tmp_path / "dependencies" / "cuda" / "bin"
        cuda_bin.mkdir(parents=True)
        monkeypatch.setenv("CIVICCAST_CUDA_BIN_DIR", str(cuda_bin))
        monkeypatch.setattr(runtime_module, "_CUDA_DLL_DIRECTORY_HANDLES", {})
        calls: list[str] = []

        def fake_add_dll_directory(path: str) -> object:
            calls.append(path)
            return object()

        fake_os = SimpleNamespace(
            name="nt",
            environ=os.environ,
            add_dll_directory=fake_add_dll_directory,
        )
        monkeypatch.setattr(runtime_module, "os", fake_os)

        runtime_module._ensure_cuda_dll_directory()
        runtime_module._ensure_cuda_dll_directory()

        assert calls == [str(cuda_bin)]

    def test_ensure_cuda_dll_directory_noop_when_env_var_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("CIVICCAST_CUDA_BIN_DIR", raising=False)
        monkeypatch.setattr(runtime_module, "_CUDA_DLL_DIRECTORY_HANDLES", {})
        calls: list[str] = []

        def fake_add_dll_directory(path: str) -> object:
            calls.append(path)
            return object()

        fake_os = SimpleNamespace(
            name="nt",
            environ=os.environ,
            add_dll_directory=fake_add_dll_directory,
        )
        monkeypatch.setattr(runtime_module, "os", fake_os)

        runtime_module._ensure_cuda_dll_directory()

        assert calls == []

    def test_ensure_cuda_dll_directory_noop_off_windows(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The shim has NO `add_dll_directory` attribute at all here --
        proves the `getattr(os, "add_dll_directory", None)` default path is
        safe even when the `os.name` guard did not already short-circuit
        first, without needing a call-tracking callable that would never be
        reached."""

        cuda_bin = tmp_path / "dependencies" / "cuda" / "bin"
        cuda_bin.mkdir(parents=True)
        monkeypatch.setenv("CIVICCAST_CUDA_BIN_DIR", str(cuda_bin))
        monkeypatch.setattr(runtime_module, "_CUDA_DLL_DIRECTORY_HANDLES", {})
        fake_os = SimpleNamespace(name="posix", environ=os.environ)
        monkeypatch.setattr(runtime_module, "os", fake_os)

        runtime_module._ensure_cuda_dll_directory()

        assert str(cuda_bin) not in runtime_module._CUDA_DLL_DIRECTORY_HANDLES

    def test_model_instance_registers_dll_directory_before_a_cuda_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The registration must happen on the cuda path -- and BEFORE the
        load attempt, not reactively in the except block after it has
        already failed to resolve the DLLs."""

        calls: list[None] = []
        monkeypatch.setattr(
            runtime_module, "_ensure_cuda_dll_directory", lambda: calls.append(None)
        )
        monkeypatch.setattr(
            runtime_module,
            "_load_whisper_model_class",
            lambda: lambda _model_size_or_path, **_kwargs: object(),
        )
        monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
        runtime = FasterWhisperRuntime(
            model_size_or_path="tiny", device="cuda", compute_type="float16"
        )

        runtime._model_instance()

        assert calls == [None]

    def test_model_instance_does_not_register_dll_directory_for_cpu_device(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[None] = []
        monkeypatch.setattr(
            runtime_module, "_ensure_cuda_dll_directory", lambda: calls.append(None)
        )
        monkeypatch.setattr(
            runtime_module,
            "_load_whisper_model_class",
            lambda: lambda _model_size_or_path, **_kwargs: object(),
        )
        monkeypatch.delenv("CIVICCAST_WHISPER_DEVICE", raising=False)
        runtime = FasterWhisperRuntime(model_size_or_path="tiny", device="cpu")

        runtime._model_instance()

        assert calls == []

    def test_native_runtime_refuses_missing_packaged_model_without_download(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        missing = tmp_path / "missing-model"
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(missing))

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match="packaged offline caption model",
        ):
            FasterWhisperRuntime(model_size_or_path="large-v3")

    def test_native_station_runtime_never_falls_back_to_a_model_download(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
        monkeypatch.delenv("CIVICCAST_WHISPER_MODEL_PATH", raising=False)

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match="activated native station",
        ):
            FasterWhisperRuntime(model_size_or_path="large-v3")

    def test_faster_whisper_runtime_maps_segments_to_caption_hypotheses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_init: dict[str, Any] = {}
        captured_transcribe: dict[str, Any] = {}

        class FakeWhisperModel:
            def __init__(self, model_size_or_path: str, **kwargs: Any) -> None:
                captured_init["model_size_or_path"] = model_size_or_path
                captured_init.update(kwargs)

            def transcribe(self, audio_path: str, **kwargs: Any) -> tuple[list[Any], object]:
                captured_transcribe["audio_path"] = audio_path
                captured_transcribe.update(kwargs)
                return (
                    [
                        SimpleNamespace(
                            start=0.25,
                            end=2.5,
                            text="  Motion   carries. ",
                            avg_logprob=-0.1,
                            no_speech_prob=0.2,
                        )
                    ],
                    object(),
                )

        monkeypatch.setattr(runtime_module, "_load_whisper_model_class", lambda: FakeWhisperModel)
        runtime = FasterWhisperRuntime(model_size_or_path="tiny", device="cpu", compute_type="int8")
        vocabulary = CustomVocabulary(
            terms=["Councilmember Rivera"],
            initial_prompt="Use local names.",
        )

        hypotheses = list(runtime.transcribe([self._audio_chunk()], vocabulary=vocabulary))

        assert captured_init == {
            "model_size_or_path": "tiny",
            "device": "cpu",
            "compute_type": "int8",
        }
        assert captured_transcribe["beam_size"] == 5
        assert captured_transcribe["task"] == "transcribe"
        assert captured_transcribe["vad_filter"] is True
        assert captured_transcribe["initial_prompt"] == (
            "Use local names. Prefer these civic terms and names: Councilmember Rivera."
        )
        assert captured_transcribe["audio_path"].endswith(".wav")
        assert hypotheses == [
            CaptionHypothesis(
                source_id="chunk-1-0000",
                start_seconds=10.25,
                end_seconds=12.5,
                text="Motion carries.",
                confidence=0.7239,
            )
        ]

    def test_live_runtime_groups_segments_as_one_audio_window(self) -> None:
        runtime = FasterWhisperRuntime(model_size_or_path="tiny", device="cpu", live=True)
        runtime._model = SimpleNamespace(
            transcribe=lambda *args, **kwargs: (
                [
                    SimpleNamespace(
                        start=0.25,
                        end=1.5,
                        text="motion carries",
                        avg_logprob=-0.1,
                        no_speech_prob=0.2,
                    ),
                    SimpleNamespace(
                        start=1.5,
                        end=2.5,
                        text="next agenda item",
                        avg_logprob=-0.1,
                        no_speech_prob=0.4,
                    ),
                ],
                object(),
            )
        )
        chunk = self._audio_chunk()
        hypotheses = list(runtime.transcribe([chunk]))
        assert len(hypotheses) == 1
        hypothesis = hypotheses[0]
        assert hypothesis.text == "motion carries next agenda item"
        assert hypothesis.confidence == 0.5429
        assert (hypothesis.start_seconds, hypothesis.end_seconds) == (10.25, 12.5)
        assert (hypothesis.audio_window_start_seconds, hypothesis.audio_window_end_seconds) == (
            chunk.start_seconds,
            chunk.end_seconds,
        )

    def test_live_runtime_preserves_actual_word_times_offset_once(self) -> None:
        runtime = FasterWhisperRuntime(model_size_or_path="tiny", device="cpu", live=True)
        calls = []

        def transcribe(*args: Any, **kwargs: Any) -> tuple[list[Any], object]:
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    start=0.25,
                    end=2.5,
                    text="motion carries",
                    words=[
                        SimpleNamespace(word=" motion", start=0.25, end=1.2, probability=0.8),
                        SimpleNamespace(word=" carries", start=1.2, end=2.5, probability=0.7),
                    ],
                )
            ], object()

        runtime._model = SimpleNamespace(transcribe=transcribe)
        hypothesis = next(iter(runtime.transcribe([self._audio_chunk()])))
        assert calls[0]["word_timestamps"] is True
        assert hypothesis.words is not None
        assert [
            (w.text, w.start_seconds, w.end_seconds, w.confidence) for w in hypothesis.words
        ] == [(" motion", 10.25, 11.2, 0.8), (" carries", 11.2, 12.5, 0.7)]

    def test_whisper_cpp_runtime_fails_closed_when_pack_files_are_missing(
        self,
        tmp_path: Path,
    ) -> None:
        missing_exe = tmp_path / "whisper-cli.exe"
        missing_model = tmp_path / "ggml-large-v3-q5_0.bin"

        with pytest.raises(RuntimeError, match="caption pack"):
            runtime_module.WhisperCppRuntime(
                executable=missing_exe,
                model=missing_model,
            )

    def test_whisper_cpp_runtime_maps_verified_large_v3_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executable = tmp_path / "whisper-cli.exe"
        model = tmp_path / "ggml-large-v3-q5_0.bin"
        executable.write_bytes(b"pinned runtime")
        model.write_bytes(b"pinned large-v3 model")
        captured: dict[str, object] = {}

        def fake_run(
            command: list[str],
            **kwargs: object,
        ) -> SimpleNamespace:
            captured["command"] = command
            captured["kwargs"] = kwargs
            output_base = Path(command[command.index("--output-file") + 1])
            output_base.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "model": {
                            "type": "large",
                            "multilingual": True,
                            "audio": {"state": 1280, "layer": 32},
                        },
                        "transcription": [
                            {
                                "offsets": {"from": 250, "to": 2500},
                                "text": " Motion carries. ",
                                "tokens": [
                                    {"text": " Motion", "p": 0.9},
                                    {"text": " carries", "p": 0.8},
                                    {"text": ".", "p": 0.7},
                                    {"text": "[_TT_125]", "p": 0.1},
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="whisper_backend_init_gpu: using Vulkan0 backend",
            )

        monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)
        runtime = runtime_module.WhisperCppRuntime(
            executable=executable,
            model=model,
            threads=4,
            beam_size=5,
            audio_context=512,
            language="en",
        )
        vocabulary = CustomVocabulary(
            terms=["Councilmember Rivera"],
            initial_prompt="Use local names.",
        )

        hypotheses = list(runtime.transcribe([self._audio_chunk()], vocabulary=vocabulary))

        command = captured["command"]
        assert isinstance(command, list)
        assert command[:4] == [
            str(executable.resolve()),
            "--model",
            str(model.resolve()),
            "--file",
        ]
        assert command[command.index("--audio-ctx") + 1] == "512"
        assert command[command.index("--threads") + 1] == "4"
        assert command[command.index("--beam-size") + 1] == "5"
        assert command[command.index("--max-len") + 1] == "42"
        assert "--split-on-word" in command
        assert command[command.index("--prompt") + 1] == (
            "Use local names. Prefer these civic terms and names: Councilmember Rivera."
        )
        assert hypotheses == [
            CaptionHypothesis(
                source_id="chunk-1-0000",
                start_seconds=10.25,
                end_seconds=12.5,
                text="Motion carries.",
                confidence=0.8,
            )
        ]

    def test_whisper_cpp_runtime_rejects_wrong_model_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        executable = tmp_path / "whisper-cli.exe"
        model = tmp_path / "ggml-large-v3-q5_0.bin"
        executable.write_bytes(b"pinned runtime")
        model.write_bytes(b"wrong model")

        def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
            output_base = Path(command[command.index("--output-file") + 1])
            output_base.with_suffix(".json").write_text(
                json.dumps(
                    {
                        "model": {
                            "type": "medium",
                            "multilingual": True,
                            "audio": {"state": 1024, "layer": 24},
                        },
                        "transcription": [],
                    }
                ),
                encoding="utf-8",
            )
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="whisper_backend_init_gpu: using Vulkan0 backend",
            )

        monkeypatch.setattr(runtime_module.subprocess, "run", fake_run)
        runtime = runtime_module.WhisperCppRuntime(
            executable=executable,
            model=model,
        )

        with pytest.raises(RuntimeError, match="large-v3 identity"):
            list(runtime.transcribe([self._audio_chunk()]))


class TestPackagedModelTierInventory:
    """The runtime's packaged-model gate must use EACH TIER'S OWN inventory.

    Regression cover for the beta blocker TESTER2 hit on 2026-08-13: a
    station on the owner-ratified ``medium`` FLOOR tier could not start
    captions because this gate demanded large-v3's ``preprocessor_config
    .json``/``vocabulary.json`` of a ``faster-whisper-medium`` directory that
    correctly ships ``vocabulary.txt`` and no preprocessor config. Same class
    as controller request-0006 ("the prior verifier hard-coded large-v3's
    inventory"), recurring in the RUNTIME after the adaptive-tier work fixed
    the pack builder and both installer-side verifiers.
    """

    @staticmethod
    def _materialize(model_dir: Path, tier_id: str) -> Path:
        """Create the EXACT files the pinned registry says that tier ships."""

        model_dir.mkdir(parents=True, exist_ok=True)
        for name in CAPTION_TIER_REGISTRY[tier_id].files:
            (model_dir / name).write_bytes(b"pinned model file")
        return model_dir

    def test_floor_tier_medium_model_loads_without_large_v3_only_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shipped floor pack, exactly as built, must be accepted."""

        model_dir = self._materialize(tmp_path / "faster-whisper-medium", FLOOR_TIER_ID)
        assert not (model_dir / "preprocessor_config.json").exists()
        assert not (model_dir / "vocabulary.json").exists()
        monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
        monkeypatch.setenv("CIVICCAST_CAPTION_TIER", FLOOR_TIER_ID)
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        runtime = FasterWhisperRuntime()

        assert runtime.model_size_or_path == str(model_dir.resolve())
        assert runtime._local_files_only is True

    def test_floor_tier_is_accepted_from_its_directory_name_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A floor model still validates when no tier env var is present."""

        model_dir = self._materialize(tmp_path / "faster-whisper-medium", FLOOR_TIER_ID)
        monkeypatch.delenv("CIVICCAST_CAPTION_TIER", raising=False)
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        assert FasterWhisperRuntime().model_size_or_path == str(model_dir.resolve())

    def test_required_files_are_per_tier_and_derived_from_the_pinned_registry(
        self,
    ) -> None:
        floor = runtime_module.caption_tier_required_files(FLOOR_TIER_ID)
        large_v3 = runtime_module.caption_tier_required_files(LARGE_V3_TIER_ID)

        assert floor != large_v3
        assert "vocabulary.txt" in floor
        assert "preprocessor_config.json" not in floor
        assert "vocabulary.json" not in floor
        assert {"preprocessor_config.json", "vocabulary.json"} <= set(large_v3)
        # Derived from the single source of truth, never restated here.
        for tier_id, required in ((FLOOR_TIER_ID, floor), (LARGE_V3_TIER_ID, large_v3)):
            assert set(required) <= set(CAPTION_TIER_REGISTRY[tier_id].files)

    def test_large_v3_gate_is_unchanged_by_the_per_tier_fix(self) -> None:
        """The tier that always worked keeps its exact five-file contract."""

        assert runtime_module.REQUIRED_LOCAL_MODEL_FILES == (
            "config.json",
            "model.bin",
            "preprocessor_config.json",
            "tokenizer.json",
            "vocabulary.json",
        )

    def test_incomplete_floor_model_still_fails_closed_and_loudly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-silent-swap: per-tier must not mean permissive."""

        model_dir = self._materialize(tmp_path / "faster-whisper-medium", FLOOR_TIER_ID)
        (model_dir / "model.bin").unlink()
        monkeypatch.setenv("CIVICCAST_CAPTION_TIER", FLOOR_TIER_ID)
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match=r"missing: model\.bin",
        ):
            FasterWhisperRuntime()

    def test_declared_tier_pointing_at_another_tiers_directory_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cross-tier swap must be refused even when the files are complete."""

        model_dir = self._materialize(tmp_path / "faster-whisper-large-v3", LARGE_V3_TIER_ID)
        monkeypatch.setenv("CIVICCAST_CAPTION_TIER", FLOOR_TIER_ID)
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match="silently swapped for another tier",
        ):
            FasterWhisperRuntime()

    def test_unknown_declared_tier_is_refused_rather_than_guessed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_dir = self._materialize(tmp_path / "faster-whisper-medium", FLOOR_TIER_ID)
        monkeypatch.setenv("CIVICCAST_CAPTION_TIER", "turbo")
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match="unknown caption tier",
        ):
            FasterWhisperRuntime()

    def test_unidentified_directory_must_still_satisfy_some_known_tier(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An arbitrary directory is not a caption model just because it exists."""

        model_dir = tmp_path / "some-other-model"
        model_dir.mkdir()
        (model_dir / "config.json").write_bytes(b"only this")
        monkeypatch.delenv("CIVICCAST_CAPTION_TIER", raising=False)
        monkeypatch.setenv("CIVICCAST_WHISPER_MODEL_PATH", str(model_dir))

        with pytest.raises(
            FasterWhisperRuntimeUnavailableError,
            match="packaged offline caption model",
        ):
            FasterWhisperRuntime()


class TestCaptionPipeline:
    def test_pipeline_commits_stable_runtime_output_to_review_items(self) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis(
                        "motion carries",
                        start=chunk.start_seconds,
                        end=chunk.end_seconds,
                        confidence=0.91,
                    )

        pipeline = CaptionPipeline(StableRuntime())
        first = pipeline.process(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id="asset-1",
            reviewer_note="Auto-generated by local faster-whisper.",
        )
        assert first.committed_cues == []
        assert first.review_items == []

        second = pipeline.process(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id="asset-1",
            reviewer_note="Auto-generated by local faster-whisper.",
        )

        assert len(second.hypotheses) == 1
        assert len(second.committed_cues) == 1
        assert second.review_items[0].review_item_id == "asset-1:cue-000000"
        assert second.review_items[0].asset_id == "asset-1"
        assert second.review_items[0].cue.text == "motion carries"
        assert second.review_items[0].reviewer_note == "Auto-generated by local faster-whisper."
        assert pipeline.committed() == second.committed_cues

    def test_pipeline_review_item_id_stays_within_contract_for_long_asset_id(self) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                yield _hypothesis("zoning hearing")

        pipeline = CaptionPipeline(StableRuntime())
        asset_id = "asset-" + ("x" * 154)
        pipeline.process(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id=asset_id,
        )
        result = pipeline.process(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id=asset_id,
        )

        assert len(result.review_items[0].review_item_id) <= 160
        assert ":cue-000000:" in result.review_items[0].review_item_id

    def test_pipeline_publishes_committed_cues_to_hls_package(self, tmp_path: Path) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis(
                        "welcome to the council meeting",
                        start=chunk.start_seconds,
                        end=chunk.end_seconds,
                    )

        output_dir = tmp_path / "package"
        output_dir.mkdir()
        package = SlateOnlyResult(
            manifest_path=output_dir / "playlist.m3u8",
            slate_playlist_path=output_dir / "slate" / "playlist.m3u8",
            output_dir=output_dir,
        )
        pipeline = CaptionPipeline(StableRuntime())

        first = pipeline.process_and_publish_hls(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id="asset-1",
            package=package,
        )
        assert first.hls_outputs == []
        assert not package.manifest_path.exists()

        second = pipeline.process_and_publish_hls(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ],
            asset_id="asset-1",
            package=package,
            segment_duration=4,
        )

        assert len(second.hls_outputs) == 1
        assert second.hls_outputs[0].playlist_uri == "captions/en/playlist.m3u8"
        assert (
            second.hls_outputs[0].segment_paths[0].read_text(encoding="utf-8").startswith("WEBVTT")
        )
        assert "welcome to the council meeting" in second.hls_outputs[0].segment_paths[0].read_text(
            encoding="utf-8"
        )
        manifest = package.manifest_path.read_text(encoding="utf-8")
        assert 'TYPE=SUBTITLES,GROUP-ID="subtitles"' in manifest
        assert 'NAME="English"' in manifest
        assert 'URI="captions/en/playlist.m3u8"' in manifest


class TestLiveCaptionWorker:
    def test_timed_word_flush_persists_review_without_active_caption(self) -> None:
        runtime = SimpleNamespace(
            transcribe=lambda *args, **kwargs: [_word_window(0, [("once", 1, 2), ("heard", 2, 3)])]
        )
        store = InMemoryCaptionReviewStore()
        pipeline = CaptionPipeline(runtime, stabilizer=CaptionStabilizer(live=True))
        worker = LiveCaptionWorker(runtime, store, asset_id="timed", pipeline=pipeline)
        worker.process_batch([])
        result = worker.flush()
        assert [item.cue.text for item in result.committed_review_items] == ["once heard"]
        assert [cue.text for cue in result.expired_unconfirmed_cues] == ["once heard"]
        assert worker.committed_cues() == []
        assert worker.flush().committed_review_items == []

    def test_worker_persists_stable_live_cues_to_review_queue(self) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis(
                        "motion carries",
                        start=chunk.start_seconds,
                        end=chunk.end_seconds,
                        confidence=0.91,
                    )

        store = InMemoryCaptionReviewStore()
        worker = LiveCaptionWorker(
            StableRuntime(),
            store,
            asset_id="asset-1",
            reviewer_note="Auto-generated by local faster-whisper.",
        )

        first = worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )
        assert first.committed_review_items == []

        second = worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )

        assert len(second.hypotheses) == 1
        assert len(second.committed_review_items) == 1
        assert second.committed_review_items[0].review_item_id == "asset-1:cue-000000"
        assert second.committed_review_items[0].reviewer_note == (
            "Auto-generated by local faster-whisper."
        )
        assert [item.review_item_id for item in store.list(asset_id="asset-1")] == [
            "asset-1:cue-000000"
        ]

    def test_worker_reports_duplicate_review_items_without_crashing(self) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis("same cue", start=chunk.start_seconds, end=chunk.end_seconds)

        store = InMemoryCaptionReviewStore()
        first_worker = LiveCaptionWorker(StableRuntime(), store, asset_id="asset-1")
        second_worker = LiveCaptionWorker(StableRuntime(), store, asset_id="asset-1")
        chunks = [
            AudioChunk(
                chunk_id="chunk-1",
                start_seconds=0.0,
                end_seconds=3.8,
                sample_rate_hz=16_000,
                pcm_s16le=b"\x00\x00",
            ),
            AudioChunk(
                chunk_id="chunk-2",
                start_seconds=0.0,
                end_seconds=3.8,
                sample_rate_hz=16_000,
                pcm_s16le=b"\x00\x00",
            ),
        ]

        created = first_worker.process_batch(chunks)
        duplicate = second_worker.process_batch(chunks)

        assert [item.review_item_id for item in created.committed_review_items] == [
            "asset-1:cue-000000"
        ]
        assert duplicate.committed_review_items == []
        assert duplicate.duplicate_review_item_ids == ["asset-1:cue-000000"]
        assert len(store.list(asset_id="asset-1")) == 1

    def test_worker_can_publish_hls_when_a_package_is_configured(self, tmp_path: Path) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis(
                        "welcome to the meeting",
                        start=chunk.start_seconds,
                        end=chunk.end_seconds,
                    )

        output_dir = tmp_path / "package"
        output_dir.mkdir()
        package = SlateOnlyResult(
            manifest_path=output_dir / "playlist.m3u8",
            slate_playlist_path=output_dir / "slate" / "playlist.m3u8",
            output_dir=output_dir,
        )
        worker = LiveCaptionWorker(
            StableRuntime(),
            InMemoryCaptionReviewStore(),
            asset_id="asset-1",
            package=package,
            segment_duration=4,
        )

        worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )
        result = worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )

        assert result.hls_result is not None
        assert result.hls_result.hls_outputs[0].playlist_uri == "captions/en/playlist.m3u8"
        assert "welcome to the meeting" in (
            output_dir / "captions" / "en" / "seg000.vtt"
        ).read_text(encoding="utf-8")

    def test_worker_can_publish_translated_hls_track(self, tmp_path: Path) -> None:
        class StableRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                for chunk in chunks:
                    yield _hypothesis(
                        "welcome to the council meeting",
                        start=chunk.start_seconds,
                        end=chunk.end_seconds,
                    )

        output_dir = tmp_path / "package"
        output_dir.mkdir()
        package = SlateOnlyResult(
            manifest_path=output_dir / "playlist.m3u8",
            slate_playlist_path=output_dir / "slate" / "playlist.m3u8",
            output_dir=output_dir,
        )
        worker = LiveCaptionWorker(
            StableRuntime(),
            InMemoryCaptionReviewStore(),
            asset_id="asset-1",
            package=package,
            translation_provider=DeterministicSpanishTranslator(),
            translation_targets=[TranslationTarget(target_language="es", target_name="Spanish")],
            segment_duration=4,
        )

        worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-1",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )
        result = worker.process_batch(
            [
                AudioChunk(
                    chunk_id="chunk-2",
                    start_seconds=0.0,
                    end_seconds=3.8,
                    sample_rate_hz=16_000,
                    pcm_s16le=b"\x00\x00",
                )
            ]
        )

        assert result.hls_result is not None
        assert [track.manifest_track.language for track in result.hls_result.hls_outputs] == [
            "en",
            "es",
        ]
        manifest = package.manifest_path.read_text(encoding="utf-8")
        assert 'LANGUAGE="es",NAME="Spanish",DEFAULT=NO' in manifest
        assert "bienvenidos a la reunion del consejo" in (
            output_dir / "captions" / "es" / "seg000.vtt"
        ).read_text(encoding="utf-8")


class TestWebVtt:
    def test_render_webvtt_escapes_text_and_formats_timestamps(self) -> None:
        stabilizer = CaptionStabilizer()
        stabilizer.observe(_hypothesis("A < B & C", start=65.1234, end=67.9876))
        cue = stabilizer.observe(_hypothesis("A < B & C", start=65.1234, end=67.9876))[0]

        rendered = render_webvtt([cue])

        assert rendered.startswith("WEBVTT\n\n")
        assert "00:01:05.123 --> 00:01:07.988" in rendered
        assert "A &lt; B &amp; C" in rendered
