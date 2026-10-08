"""Default live delivery must not create an unattended review archive."""

import wave

from civiccast.captions.models import CaptionHypothesis
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.tap_worker import CaptionTapWorker
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text


class Runtime:
    def transcribe(self, chunks, vocabulary=None):
        for chunk in chunks:
            yield CaptionHypothesis(
                source_id=chunk.chunk_id,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text="the council is meeting",
                confidence=0.9,
            )


def audio(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x01\x00" * 16000)


def test_live_default_publishes_without_retention_or_review_archive(tmp_path, monkeypatch):
    store = InMemoryCaptionReviewStore()
    tap = tmp_path / "tap"
    output = tmp_path / "egress"
    worker = CaptionTapWorker(
        tap_root=tap,
        caption_work_dir=output,
        runtime=Runtime(),
        review_store=store,
        segment_seconds=1,
        atomic_segments=True,
    )
    retention_calls = []

    def forbidden_retention(**kwargs):
        retention_calls.append(kwargs)
        raise AssertionError("live delivery must not discover review evidence")

    monkeypatch.setattr(worker._retention_policy, "enforce_discovered", forbidden_retention)
    try:
        for index in range(4):
            audio(tap / "public" / f"chunk-{index:06d}.wav")
            worker.run_once()
        assert load_caption_cues_from_timed_text(
            output / "public/captions/active.vtt", source_id="public"
        )
        assert retention_calls == []
        assert store.list() == []
        assert not list(tap.rglob("*.wav"))
        assert not list(output.rglob("evidence/*.wav"))
    finally:
        worker.wait_for_retention_sweep()


def test_waiting_live_audio_is_bounded_even_when_inference_is_busy(tmp_path):
    tap = tmp_path / "tap"
    worker = CaptionTapWorker(
        tap_root=tap,
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime(),
        review_store=InMemoryCaptionReviewStore(),
        atomic_segments=True,
    )
    for index in range(25):
        audio(tap / "public" / f"chunk-{index:06d}.wav")
    pending = worker._settled_segments(tap / "public")
    assert len(pending) <= 12
    assert len(list(tap.rglob("*.wav"))) <= 12
    assert pending[-1][0] == 24


def test_old_review_archive_does_not_discard_new_live_audio(tmp_path):
    tap = tmp_path / "tap"
    old = tap / "public/processed/chunk-000000.wav"
    audio(old)
    output = tmp_path / "egress"
    worker = CaptionTapWorker(
        tap_root=tap,
        caption_work_dir=output,
        runtime=Runtime(),
        review_store=InMemoryCaptionReviewStore(),
        atomic_segments=True,
    )
    audio(tap / "public/chunk-000000.wav")
    scan = worker.run_once()
    assert scan.consumed_segments == 1
    assert old.exists()
    assert load_caption_cues_from_timed_text(
        output / "public/captions/active.vtt", source_id="public"
    )
