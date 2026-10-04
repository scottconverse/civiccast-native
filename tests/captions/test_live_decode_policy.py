# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live fallback/quality contracts. No model loading or native inference."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from civiccast.ai_models.runtime import build_caption_runtime
from civiccast.captions import CaptionStabilizer
from civiccast.captions.models import AudioChunk, CustomVocabulary
from civiccast.captions.runtime import FasterWhisperRuntime


def chunk(start=0):
    return AudioChunk(
        chunk_id=f"synthetic-{start}",
        start_seconds=start,
        end_seconds=start + 10,
        sample_rate_hz=16000,
        pcm_s16le=b"\x00\x00",
    )


def segment(**changes):
    fields = {
        "text": "motion carries",
        "start": 6,
        "end": 8,
        "avg_logprob": -0.1,
        "compression_ratio": 1.0,
        "no_speech_prob": 0.1,
        "words": [
            SimpleNamespace(word=" motion", start=6, end=7, probability=0.9),
            SimpleNamespace(word=" carries", start=7, end=8, probability=0.9),
        ],
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def runtime(live=True, segments=None):
    result = FasterWhisperRuntime(device="cpu", live=live)
    calls = []

    def transcribe(source, **kwargs):
        calls.append(kwargs)
        return iter(segments if segments is not None else [segment()]), None

    result._model = SimpleNamespace(transcribe=transcribe)
    return result, calls


def test_live_contract_retains_vad_words_prompt_and_attempt_cap():
    live, calls = runtime()
    list(live.transcribe([chunk()], CustomVocabulary(initial_prompt="Synthetic civic terms.")))
    options = calls[0]
    assert options.get("temperature") == (0.0,)
    assert options["word_timestamps"] is True
    assert options["vad_filter"] is True
    assert options["initial_prompt"] == "Synthetic civic terms."
    assert options["task"] == "transcribe" and options["language"] is None


def test_vod_still_uses_dependency_defaults_and_no_quality_refusal():
    vod, calls = runtime(False, [segment(compression_ratio=99, avg_logprob=-2)])
    assert list(vod.transcribe([chunk()]))
    assert "temperature" not in calls[0] and "word_timestamps" not in calls[0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("compression_ratio", 2.4001),
        ("avg_logprob", -1.0001),
        ("compression_ratio", None),
        ("avg_logprob", None),
        ("compression_ratio", float("nan")),
        ("avg_logprob", float("nan")),
        ("compression_ratio", float("inf")),
        ("avg_logprob", float("-inf")),
        ("compression_ratio", True),
        ("avg_logprob", False),
        ("compression_ratio", "1.0"),
        ("avg_logprob", "-.1"),
    ],
)
def test_live_refuses_failed_or_unproven_quality_before_aggregation(field, value):
    live, _ = runtime(segments=[segment(**{field: value})])
    assert list(live.transcribe([chunk()])) == []


@pytest.mark.parametrize("field", ["compression_ratio", "avg_logprob"])
def test_live_refuses_missing_quality(field):
    item = segment()
    delattr(item, field)
    live, _ = runtime(segments=[item])
    assert list(live.transcribe([chunk()])) == []


def test_mixed_window_cannot_bridge_refused_speech():
    def phrase(text, start):
        return segment(
            text=text,
            start=start,
            end=start + 2,
            words=[
                SimpleNamespace(
                    word=word, start=start + index, end=start + index + 1, probability=0.9
                )
                for index, word in enumerate(text.split())
            ],
        )

    live, _ = runtime(
        segments=[
            phrase("first valid", 2),
            segment(text="rejected hallucination", start=4, end=6, compression_ratio=99),
            phrase("last valid", 6),
        ]
    )
    hypotheses = list(live.transcribe([chunk()]))
    assert len(hypotheses) == 1, "independent valid speech was erased by a rejected segment"
    hypothesis = hypotheses[0]
    assert hypothesis.text == "first valid ... last valid"
    assert hypothesis.word_breaks == [2]
    assert [(word.text, word.start_seconds, word.end_seconds) for word in hypothesis.words] == [
        ("first", 2, 3),
        ("valid", 3, 4),
        ("last", 6, 7),
        ("valid", 7, 8),
    ]
    assert (hypothesis.audio_window_start_seconds, hypothesis.audio_window_end_seconds) == (0, 10)


@pytest.mark.parametrize("position", ["before", "after"])
def test_edge_refusal_does_not_erase_independent_valid_speech(position):
    good = segment()
    rejected = segment(text="rejected hallucination", compression_ratio=99)
    observations = [rejected, good] if position == "before" else [good, rejected]
    live, _ = runtime(segments=observations)
    hypothesis = next(iter(live.transcribe([chunk()])))
    assert hypothesis.text == "motion carries"
    assert hypothesis.word_breaks == []
    assert len(hypothesis.words) == 2


def test_wordless_segment_cannot_clear_a_rejected_word_gap():
    live, _ = runtime(
        segments=[
            segment(),
            segment(text="rejected hallucination", compression_ratio=99),
            segment(text="unconfirmed fragment", words=[]),
            segment(
                text="last phrase",
                words=[
                    SimpleNamespace(word=" last", start=8, end=9, probability=0.9),
                    SimpleNamespace(word=" phrase", start=9, end=10, probability=0.9),
                ],
            ),
        ]
    )
    hypothesis = next(iter(live.transcribe([chunk()])))
    assert hypothesis.word_breaks == [2]
    assert "rejected hallucination" not in hypothesis.text
    assert hypothesis.text == "motion carries ... unconfirmed fragment last phrase"


def test_valid_thresholds_and_word_alignment_remain_exact():
    live, _ = runtime(segments=[segment(compression_ratio=2.4, avg_logprob=-1)])
    h = next(iter(live.transcribe([chunk(5)])))
    assert [(w.text, w.start_seconds, w.end_seconds) for w in h.words] == [
        (" motion", 11, 12),
        (" carries", 12, 13),
    ]
    assert h.source_id == "synthetic-5-0000"
    assert (h.audio_window_start_seconds, h.audio_window_end_seconds) == (5, 15)


def test_repeated_refused_windows_never_commit_but_valid_controls_do():
    stabilizer = CaptionStabilizer(live=True)
    for start in [0, 1, 2]:
        offset = 6 - start
        live, _ = runtime(
            segments=[
                segment(
                    compression_ratio=99,
                    start=offset,
                    end=offset + 2,
                    words=[
                        SimpleNamespace(
                            word=" motion", start=offset, end=offset + 1, probability=0.9
                        ),
                        SimpleNamespace(
                            word=" carries", start=offset + 1, end=offset + 2, probability=0.9
                        ),
                    ],
                )
            ]
        )
        for h in live.transcribe([chunk(start)]):
            stabilizer.observe(h)
    assert stabilizer.flush() == []
    assert stabilizer.committed() == []
    valid = CaptionStabilizer(live=True)
    for start, offset in [(0, 6), (5, 1)]:
        item = segment(
            start=offset,
            end=offset + 2,
            words=[
                SimpleNamespace(word=" motion", start=offset, end=offset + 1, probability=0.9),
                SimpleNamespace(word=" carries", start=offset + 1, end=offset + 2, probability=0.9),
            ],
        )
        live, _ = runtime(segments=[item])
        for h in live.transcribe([chunk(start)]):
            valid.observe(h)
    assert valid.committed()


def test_factory_live_and_vod_reach_actual_adapter_policy():
    service = SimpleNamespace(effective_model_tag=lambda _: "whisper-medium")
    for live in [True, False]:
        built = build_caption_runtime(service, live=live)
        captured = []
        built._model = SimpleNamespace(
            transcribe=lambda *a, _record=captured, **k: (_record.append(k) or [], None)
        )
        list(built.transcribe([chunk()]))
        assert ("temperature" in captured[0]) is live


def test_raising_quality_metadata_is_refused_not_a_runtime_failure():
    class BrokenQuality:
        @property
        def compression_ratio(self):
            raise RuntimeError("synthetic metadata failure")

    live, _ = runtime(segments=[BrokenQuality()])
    assert list(live.transcribe([chunk()])) == []


@pytest.mark.parametrize("mutant", ["uncap", "refusal", "vod_cap", "vad"])
def test_negative_controls_fail_the_specific_contract(monkeypatch, mutant):
    import inspect
    import textwrap

    import civiccast.captions.runtime as module

    if mutant == "refusal":
        monkeypatch.setattr(module, "_live_segment_quality_refusal", lambda _: None)
        with pytest.raises(AssertionError):
            test_live_refuses_failed_or_unproven_quality_before_aggregation("compression_ratio", 99)
        return
    source = textwrap.dedent(inspect.getsource(FasterWhisperRuntime._transcribe_source))
    old, new = {
        "uncap": (
            '"temperature": LIVE_DECODE_TEMPERATURES',
            '"temperature": (0.0, .2, .4, .6, .8, 1.0)',
        ),
        "vod_cap": ("if self._live", "if True"),
        "vad": ("vad_filter=self.vad_filter", "vad_filter=False"),
    }[mutant]
    assert old in source
    scope = dict(vars(module))
    exec(compile(source.replace(old, new), "<offline-policy-mutant>", "exec"), scope)
    monkeypatch.setattr(FasterWhisperRuntime, "_transcribe_source", scope["_transcribe_source"])
    with pytest.raises(AssertionError):
        if mutant == "vod_cap":
            test_vod_still_uses_dependency_defaults_and_no_quality_refusal()
        else:
            test_live_contract_retains_vad_words_prompt_and_attempt_cap()
