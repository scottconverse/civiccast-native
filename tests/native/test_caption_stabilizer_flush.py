# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""End-of-stream caption commitment (WP1 caption-integrity fix, 2026-07-29).

Reference defect: tester-handoff/native-caption-r7/evidence/controller-0003-zero-rows/
zero-rows-trace.json (branch test/native-caption-cpu-r7) -- a real live-caption run that
consumed 2 audio segments, produced 2 pending hypotheses stuck at ``stable_count`` 1, and
committed 0 rows, because :class:`CaptionStabilizer` had no end-of-stream flush and
``_expire_stale_pending`` silently deleted anything that missed re-confirmation. These tests
prove: (1) a stream that ends with pending hypotheses commits nothing until ``flush()`` is
called, and everything ``flush()`` commits is flagged low-confidence; (2) expiry is a
counted, routed drop, never a silent deletion; (3) ``flush()`` is idempotent; and (4) the
production ``CaptionTapWorker`` end-of-stream path exercises the same fix and exposes a
matching scan-stats counter.
"""

from __future__ import annotations

import wave
from collections.abc import Iterable
from pathlib import Path

from civiccast.captions.models import AudioChunk, CaptionHypothesis
from civiccast.captions.pipeline import CaptionPipeline
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.stabilize import CaptionStabilizer
from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
from civiccast.captions.tap_worker import CaptionTapWorker


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


class TestCaptionStabilizerFlush:
    def test_end_of_stream_without_flush_commits_nothing(self) -> None:
        """Documents the defect: a stream that ends mid-window commits 0 rows.

        Mirrors the R7 trace shape (two hypotheses, each observed exactly once,
        never re-confirmed because no more audio ever arrives).
        """

        stabilizer = CaptionStabilizer()
        stabilizer.observe(_hypothesis("Council meeting will come to order.", start=0.0, end=1.88))
        stabilizer.observe(_hypothesis("will come to order.", start=1.0, end=8.68))

        assert stabilizer.committed() == []

    def test_flush_commits_every_pending_cue_in_playback_order_as_low_confidence(self) -> None:
        stabilizer = CaptionStabilizer()
        stabilizer.observe(_hypothesis("Council meeting will come to order.", start=0.0, end=1.88))
        stabilizer.observe(_hypothesis("will come to order.", start=1.0, end=8.68))

        flushed = stabilizer.flush()

        assert [cue.text for cue in flushed] == [
            "Council meeting will come to order.",
            "will come to order.",
        ]
        assert all(cue.low_confidence is True for cue in flushed)
        assert stabilizer.committed() == flushed

    def test_expired_pending_is_counted_and_routed_never_silently_dropped(self) -> None:
        stabilizer = CaptionStabilizer(window_seconds=4.0, stable_windows=2)
        stabilizer.observe(_hypothesis("stuck hypothesis", start=0.0, end=1.0))
        assert stabilizer.expired_unconfirmed_count == 0

        # Push the observed horizon past 2 * window_seconds (8s) beyond the
        # stuck pending cue's end (1.0s), which is exactly the silent-delete
        # threshold in the original defect.
        stabilizer.observe(_hypothesis("far later segment", start=100.0, end=101.0))

        assert stabilizer.expired_unconfirmed_count == 1
        expired = stabilizer.expired_unconfirmed()
        assert [cue.text for cue in expired] == ["stuck hypothesis"]
        assert expired[0].low_confidence is True
        # Never active: must not be committed / must never air.
        assert "stuck hypothesis" not in [cue.text for cue in stabilizer.committed()]

    def test_flush_is_idempotent_and_only_emits_stragglers_after_normal_commits(self) -> None:
        stabilizer = CaptionStabilizer()
        stabilizer.observe(_hypothesis("motion carries", start=0.0, end=3.0))
        normal_commit = stabilizer.observe(_hypothesis("motion carries", start=0.0, end=3.0))
        assert len(normal_commit) == 1

        stabilizer.observe(_hypothesis("second motion", start=10.0, end=13.0))

        first_flush = stabilizer.flush()
        assert [cue.text for cue in first_flush] == ["second motion"]

        second_flush = stabilizer.flush()
        assert second_flush == []
        assert stabilizer.committed() == [*normal_commit, *first_flush]


class _OnceRuntime:
    """Yields exactly one hypothesis per chunk; never re-confirms on its own."""

    def __init__(self, text: str = "the council will come to order") -> None:
        self.text = text

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: object | None = None,
    ) -> Iterable[CaptionHypothesis]:
        for chunk in chunks:
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-once",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=self.text,
                confidence=0.9,
            )


class TestCaptionPipelineFlush:
    def _chunk(self, chunk_id: str, start: float, end: float) -> AudioChunk:
        return AudioChunk(
            chunk_id=chunk_id,
            start_seconds=start,
            end_seconds=end,
            sample_rate_hz=16_000,
            pcm_s16le=b"\x00\x00" * 160,
        )

    def test_pipeline_flush_commits_end_of_stream_cues_through_review_rows(self) -> None:
        pipeline = CaptionPipeline(_OnceRuntime())

        result = pipeline.process([self._chunk("chunk-0", 0.0, 4.0)], asset_id="gov-ch1")

        assert result.committed_cues == []
        assert pipeline.committed() == []

        flushed = pipeline.flush(asset_id="gov-ch1", reviewer_note="end of stream")

        assert len(flushed.committed_cues) == 1
        assert flushed.committed_cues[0].low_confidence is True
        assert flushed.committed_cues == pipeline.committed()
        assert len(flushed.review_items) == 1
        assert flushed.review_items[0].asset_id == "gov-ch1"
        assert flushed.review_items[0].cue == flushed.committed_cues[0]

        # Idempotent at the pipeline layer too.
        second_flush = pipeline.flush(asset_id="gov-ch1")
        assert second_flush.committed_cues == []
        assert second_flush.review_items == []


def _write_tap_wav(path: Path, *, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(TAP_SAMPLE_RATE_HZ * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TAP_SAMPLE_RATE_HZ)
        handle.writeframes(b"\x01\x00" * frame_count)


def _active_vtt(tap_root: Path, channel_id: str) -> Path:
    return tap_root.parent / "egress" / channel_id / "captions" / "active.vtt"


class TestCaptionTapWorkerStreamEndFlush:
    """Stream-end triggers flush; the scan stats expose a matching counter."""

    def test_flush_channel_commits_stuck_pending_and_scan_stats_expose_the_counter(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        _write_tap_wav(tap_root / "government" / "chunk-000000.wav")
        runtime = _OnceRuntime()
        store = InMemoryCaptionReviewStore()
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tap_root.parent / "egress",
            runtime=runtime,
            review_store=store,
            segment_seconds=1.0,
            atomic_segments=True,
        )

        scan = worker.run_once()

        assert scan.consumed_segments == 1
        # Documents the defect end-to-end: one observation is not enough to
        # earn re-confirmation, so nothing commits mid-scan.
        assert scan.committed_review_items == 0
        assert store.list(asset_id="government") == []

        flushed_scan = worker.flush_channel("government")

        assert flushed_scan.committed_review_items == 1
        rows = store.list(asset_id="government")
        assert len(rows) == 1
        assert rows[0].low_confidence is True
        assert rows[0].original_text == "the council will come to order"
        vtt = _active_vtt(tap_root, "government").read_text(encoding="utf-8")
        assert "the council will come to order" in vtt

        # Second flush is idempotent: nothing left to commit.
        second_flush = worker.flush_channel("government")
        assert second_flush.committed_review_items == 0
        assert len(store.list(asset_id="government")) == 1

    def test_flush_channel_on_unknown_channel_is_a_safe_no_op(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tap_root.parent / "egress",
            runtime=_OnceRuntime(),
            review_store=InMemoryCaptionReviewStore(),
        )

        result = worker.flush_channel("never-seen-channel")

        assert result.committed_review_items == 0
        assert result.expired_unconfirmed_cues == 0
