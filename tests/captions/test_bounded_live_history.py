# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Continuous live sessions retain a rolling window, not their entire history."""

import pytest

from civiccast.captions.models import AudioChunk, CaptionHypothesis, CaptionWord
from civiccast.captions.pipeline import CaptionPipeline
from civiccast.captions.stabilize import CaptionStabilizer
from civiccast.egress.caption_feed import CaptionFeedWorker


def hypothesis(start, text="next item", *, duration=5):
    return CaptionHypothesis(
        source_id="fake", start_seconds=start, end_seconds=start + duration, text=text
    )


def test_age_and_count_bounds_keep_new_commits_and_unique_ids():
    stabilizer = CaptionStabilizer(live=True)
    stabilizer.history_seconds = 20
    stabilizer.max_history_cues = 3
    ids = []
    for number in range(1000):
        cues = stabilizer.observe(hypothesis(number * 5))
        assert len(cues) == 1
        ids.append(cues[0].cue_id)
        assert len(stabilizer.committed()) <= 3
        assert not stabilizer._pending
        assert not stabilizer.expired_unconfirmed()
    assert not stabilizer._bucket_ordinals
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
    assert [cue.start_seconds for cue in stabilizer.committed()] == [4985, 4990, 4995]
    stabilizer.observe(hypothesis(6000))
    assert [cue.start_seconds for cue in stabilizer.committed()] == [6000]


def test_silence_prunes_history_and_old_audio_still_cannot_replay():
    stabilizer = CaptionStabilizer(live=True, history_seconds=20, max_history_cues=3)
    stabilizer.observe(hypothesis(0, "motion carries"))
    assert not stabilizer.observe(hypothesis(100, "   "))
    assert stabilizer.committed() == []
    assert not stabilizer.observe(hypothesis(0, "motion carries"))
    cues = stabilizer.observe(hypothesis(102, "motion carries next item"))
    assert [cue.text for cue in cues] == ["motion carries next item"]


def test_same_phrase_after_silence_is_new_speech_not_a_repeat():
    stabilizer = CaptionStabilizer(live=True, history_seconds=20, max_history_cues=3)
    assert stabilizer.observe(hypothesis(0, "motion carries"))
    assert not stabilizer.observe(hypothesis(100, "   "))
    cues = stabilizer.observe(hypothesis(102, "motion carries"))
    assert [cue.text for cue in cues] == ["motion carries"]


def test_age_eviction_still_deduplicates_adjacent_untimed_speech():
    stabilizer = CaptionStabilizer(live=True, history_seconds=1, max_history_cues=1)
    stabilizer.observe(hypothesis(0, "opening motion carries", duration=10))
    cues = stabilizer.observe(hypothesis(5, "motion carries next item", duration=10))
    assert [cue.text for cue in cues] == ["next item"]


def test_count_eviction_does_not_break_untimed_overlap():
    stabilizer = CaptionStabilizer(live=True, history_seconds=20, max_history_cues=1)
    stabilizer.observe(hypothesis(0, "opening motion carries", duration=10))
    cues = stabilizer.observe(hypothesis(5, "motion carries next item", duration=10))
    assert [cue.text for cue in cues] == ["next item"]
    assert stabilizer.committed() == cues


def test_age_eviction_preserves_word_overlap_and_low_confidence_publication():
    stabilizer = CaptionStabilizer(live=True, history_seconds=1, max_history_cues=1)
    first = hypothesis(0, "motion", duration=10).model_copy(
        update={
            "words": [CaptionWord(text="motion", start_seconds=9.5, end_seconds=10)],
        }
    )
    stabilizer.observe(first)
    later = hypothesis(5, "motion carries", duration=10).model_copy(
        update={
            "confidence": 0.2,
            "words": [
                CaptionWord(text="motion", start_seconds=9.5, end_seconds=10.3),
                CaptionWord(text="carries", start_seconds=11, end_seconds=12),
            ],
        }
    )
    cues = stabilizer.observe(later)
    assert [cue.text for cue in cues] == ["carries"]
    assert cues[0].low_confidence
    # The cue itself is already outside this deliberately tiny delivery
    # window, but the caller still receives the new commit exactly once.
    assert stabilizer.committed() == []
    assert not stabilizer.observe(later)


def test_offline_defaults_preserve_full_recording_and_review_items():
    stabilizer = CaptionStabilizer(stable_windows=1)
    for number in range(100):
        stabilizer.observe(hypothesis(number * 5))
    assert len(stabilizer.committed()) == 100


@pytest.mark.parametrize(
    "options",
    [
        {"history_seconds": 0},
        {"history_seconds": float("nan")},
        {"history_seconds": float("inf")},
        {"max_history_cues": 0},
        {"max_history_cues": True},
        {"max_history_cues": 1.5},
    ],
)
def test_invalid_history_bounds_rejected(options):
    with pytest.raises(ValueError):
        CaptionStabilizer(live=True, **options)


def test_history_bounds_cannot_accidentally_truncate_recording_pipeline():
    with pytest.raises(ValueError):
        CaptionStabilizer(history_seconds=300, max_history_cues=512)


class FakeRuntime:
    def transcribe(self, chunks, *, vocabulary=None):
        for chunk in chunks:
            yield hypothesis(chunk.start_seconds)


def test_live_pipeline_prepares_no_review_objects(monkeypatch):
    def unexpected_review(**kwargs):
        raise AssertionError("live captioning must not construct review records")

    monkeypatch.setattr("civiccast.captions.pipeline.CaptionReviewItemCreate", unexpected_review)
    pipeline = CaptionPipeline(
        FakeRuntime(),
        stabilizer=CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512),
        prepare_review_items=False,
    )
    result = pipeline.process(
        [
            AudioChunk(
                chunk_id="one",
                start_seconds=0,
                end_seconds=5,
                sample_rate_hz=16000,
                pcm_s16le=b"\x00\x00",
            )
        ],
        asset_id="public",
    )
    assert len(result.committed_cues) == 1
    assert result.review_items == []
    assert pipeline.flush(asset_id="public").review_items == []


def test_month_timestamps_do_not_increase_retained_live_state():
    stabilizer = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    for day in (0, 1, 7, 30, 90):
        for number in range(2000):
            stabilizer.observe(hypothesis(day * 86400 + number * 5))
            assert len(stabilizer._committed) <= 61
    assert len(stabilizer.committed()) == 61
    assert not stabilizer._bucket_ordinals
    assert not stabilizer._pending


def test_dense_hypotheses_are_bounded_even_before_age_expiry():
    stabilizer = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    for number in range(2000):
        assert stabilizer.observe(hypothesis(number / 1024, duration=1 / 1024))
        assert len(stabilizer._committed) <= 512
    assert len(stabilizer.committed()) == 512


def test_independent_live_sessions_never_reuse_cue_ids():
    first = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    second = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    first_cue = first.observe(hypothesis(0, "first session"))[0]
    second_cue = second.observe(hypothesis(0, "second session"))[0]
    assert first_cue.cue_id != second_cue.cue_id


def test_feed_delivers_new_session_while_channel_remains_on_air(tmp_path):
    first = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    current = first.observe(hypothesis(0, "first session"))
    delivered = []

    def send(_channel, _directory, **kwargs):
        delivered.append((kwargs["delivery_id"], kwargs["text"]))
        return True

    feed = CaptionFeedWorker(
        work_dir=tmp_path,
        on_air_channels=lambda: ["public"],
        caption_cue_provider=lambda _channel: current,
        send_caption_cue=send,
    )
    assert feed.run_once().cues_sent == 1
    second = CaptionStabilizer(live=True, history_seconds=300, max_history_cues=512)
    current[:] = second.observe(hypothesis(0, "second session"))
    assert feed.run_once().cues_sent == 1
    assert [text for _, text in delivered] == ["first session", "second session"]
    assert delivered[0][0] != delivered[1][0]
    assert feed.run_once().cues_sent == 0
