# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Numeric stage outcomes are not transcript or aired-caption evidence."""

from contextlib import nullcontext

import pytest

from civiccast.captions.models import CaptionHypothesis
from civiccast.captions.pipeline import CaptionPipeline
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.tap_batch_diagnostic import BatchDiagnosticCollector
from civiccast.captions.worker import LiveCaptionWorker


class Runtime:
    def __init__(self, hypotheses):
        self.hypotheses = hypotheses

    def transcribe(self, chunks, vocabulary=None):
        return iter(self.hypotheses)


def hypothesis():
    return CaptionHypothesis(
        source_id="test",
        start_seconds=0,
        end_seconds=5,
        text="private spoken words",
        confidence=0.9,
    )


def test_true_empty_and_pending_then_confirmed_are_distinct():
    runtime = Runtime([])
    worker = LiveCaptionWorker(
        runtime, InMemoryCaptionReviewStore(), asset_id="test", stage_diagnostics=True
    )
    empty = worker.process_batch([])
    assert empty.hypotheses == []
    assert (empty.pending_before, empty.pending_after, empty.confirmed_cues) == (0, 0, 0)
    runtime.hypotheses = [hypothesis()]
    pending = worker.process_batch([])
    assert len(pending.hypotheses) == 1
    assert (pending.pending_before, pending.pending_after, pending.confirmed_cues) == (0, 1, 0)
    confirmed = worker.process_batch([])
    assert (confirmed.pending_before, confirmed.pending_after, confirmed.confirmed_cues) == (
        1,
        0,
        1,
    )
    assert len(confirmed.committed_review_items) == 1


def test_review_refusal_is_not_asr_empty_or_published():
    worker = LiveCaptionWorker(
        Runtime([hypothesis()]),
        InMemoryCaptionReviewStore(),
        asset_id="test",
        persistence_guard=lambda: nullcontext("refused"),
        stage_diagnostics=True,
    )
    worker.process_batch([])
    result = worker.process_batch([])
    assert len(result.hypotheses) == 1
    assert result.confirmed_cues == 1
    assert result.refused_review_items == 1
    assert result.committed_review_items == []


@pytest.mark.parametrize("enabled", [False, True])
def test_refused_review_counter_fault_is_unknown_and_never_changes_product(enabled):
    from types import SimpleNamespace

    class FaultyLength(list):
        def __len__(self):
            if not enabled:
                pytest.fail("default-off evaluated refused-review counter")
            raise RuntimeError("diagnostic counter failure")

    class Pipeline:
        def process(self, *args, **kwargs):
            return SimpleNamespace(
                hypotheses=[],
                committed_cues=[],
                review_items=FaultyLength(),
                expired_unconfirmed_cues=[],
            )

    worker = LiveCaptionWorker(
        None,
        InMemoryCaptionReviewStore(),
        asset_id="test",
        pipeline=Pipeline(),
        persistence_guard=lambda: nullcontext("refused"),
        stage_diagnostics=enabled,
    )
    result = worker.process_batch([])
    assert result.committed_review_items == []
    assert result.duplicate_review_item_ids == []
    assert result.refused_review_items is None


def test_expired_review_is_not_confirmed_caption():
    runtime = Runtime([hypothesis()])
    worker = LiveCaptionWorker(
        runtime, InMemoryCaptionReviewStore(), asset_id="test", stage_diagnostics=True
    )
    worker.process_batch([])
    runtime.hypotheses = [hypothesis().model_copy(update={"start_seconds": 30, "end_seconds": 35})]
    result = worker.process_batch([])
    assert len(result.expired_unconfirmed_cues) == 1
    assert len(result.committed_review_items) == 1
    assert result.confirmed_cues == 0
    assert result.pending_after == 1


def test_duplicate_review_remains_distinct_from_refusal_and_asr_empty():
    pipeline = CaptionPipeline(Runtime([hypothesis()]))
    pipeline.process([], asset_id="test")
    confirmed = pipeline.process([], asset_id="test")

    class ReplayPipeline:
        def process(self, *args, **kwargs):
            return confirmed

    worker = LiveCaptionWorker(
        Runtime([]),
        InMemoryCaptionReviewStore(),
        asset_id="test",
        pipeline=ReplayPipeline(),
        stage_diagnostics=True,
    )
    first = worker.process_batch([])
    duplicate = worker.process_batch([])
    assert len(first.committed_review_items) == 1
    assert duplicate.committed_review_items == []
    assert len(duplicate.duplicate_review_item_ids) == 1
    assert duplicate.refused_review_items == 0
    assert duplicate.confirmed_cues == 1
    assert len(duplicate.hypotheses) == 1


def test_timed_word_pending_is_visible_without_text_logging():
    from civiccast.captions.models import CaptionWord
    from civiccast.captions.stabilize import CaptionStabilizer

    timed = hypothesis().model_copy(
        update={
            "audio_window_start_seconds": 0,
            "audio_window_end_seconds": 5,
            "words": [CaptionWord(text="private", start_seconds=1, end_seconds=2, confidence=0.9)],
        }
    )
    pipeline = CaptionPipeline(
        Runtime([timed]), stabilizer=CaptionStabilizer(live=True), stage_diagnostics=True
    )
    result = pipeline.process([], asset_id="test")
    assert (result.pending_before, result.pending_after) == (0, 1)
    assert result.committed_cues == []


def test_pending_counter_failure_does_not_change_stabilization():
    from civiccast.captions.stabilize import CaptionStabilizer

    class BrokenCounter(CaptionStabilizer):
        @property
        def pending_count(self):
            raise RuntimeError("diagnostic failure")

    pipeline = CaptionPipeline(
        Runtime([hypothesis()]), stabilizer=BrokenCounter(), stage_diagnostics=True
    )
    first = pipeline.process([], asset_id="test")
    second = pipeline.process([], asset_id="test")
    assert first.pending_before is None and first.pending_after is None
    assert second.pending_before is None and second.pending_after is None
    assert len(second.committed_cues) == 1


def test_default_off_never_reads_optional_pending_counter():
    from civiccast.captions.stabilize import CaptionStabilizer

    class MustNotRead(CaptionStabilizer):
        @property
        def pending_count(self):
            pytest.fail("default-off accessed diagnostic pending state")

    result = CaptionPipeline(Runtime([]), stabilizer=MustNotRead()).process([], asset_id="test")
    assert result.pending_before is None and result.pending_after is None


@pytest.mark.parametrize("inactive", ["expiry", "cap"])
def test_existing_tap_worker_stops_optional_reads_after_collector_inactive(tmp_path, inactive):
    from civiccast.captions.stabilize import CaptionStabilizer
    from civiccast.captions.tap_worker import CaptionTapWorker

    class MustNotRead(CaptionStabilizer):
        @property
        def pending_count(self):
            pytest.fail("inactive collector read optional pending state")

    collector = BatchDiagnosticCollector()
    tap = CaptionTapWorker(
        tap_root=tmp_path / "tap",
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime([]),
        review_store=InMemoryCaptionReviewStore(),
        batch_diagnostic=collector,
    )
    worker = tap._worker_for("public")
    worker._pipeline._stabilizer = MustNotRead()
    if inactive == "expiry":
        collector._expires_at = -1
    else:
        collector._exhausted = True
    assert collector.enabled is False
    result = worker.process_batch([])
    assert result.pending_before is None and result.pending_after is None
    assert result.confirmed_cues is None and result.refused_review_items is None


def test_publication_diagnostic_failure_preserves_original_return_and_delegate(monkeypatch):
    from civiccast.captions.tap_worker import CaptionTapWorker

    tap = object.__new__(CaptionTapWorker)
    calls = []

    def publish(channel, generation, cues):
        calls.append((channel, generation, cues))
        return True

    class BrokenAcceptance:
        def append(self, value):
            raise RuntimeError("diagnostic append failure")

    monkeypatch.setattr(tap, "publish_for_current_session", publish)
    assert tap._publish_cues("public", 2, []) is None
    assert tap._publish_cues("public", 2, [], _diagnostic_acceptance=BrokenAcceptance()) is None
    assert calls == [("public", 2, []), ("public", 2, [])]


@pytest.mark.parametrize("sentinel", ["https://secret.invalid/token", True, -1, 2**63])
def test_collector_retains_only_closed_nonnegative_numeric_stage_fields(sentinel):
    collector = BatchDiagnosticCollector()
    collector.begin_batch(
        channel="public",
        generation=2,
        batch_id="test",
        segment_indices=[1],
        segment_names=["chunk-000001.wav"],
        queue_depth=1,
        oldest_queue_age_seconds=0,
    )
    collector.finish_batch(
        batch_id="test",
        outcome="no-commit",
        reason="asr-completed-no-committed-items",
        consumed_segments=1,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0,
        stage_counts={
            "hypotheses": sentinel,
            "asr_empty_batches": 1,
            "arbitrary_secret": "credential sentinel",
        },
    )
    record = collector.summarise(force=True)["batches"][0]
    assert record["stage_counts"]["asr_empty_batches"] == 1
    assert "hypotheses" not in record["stage_counts"]
    assert "arbitrary_secret" not in record["stage_counts"]


@pytest.mark.parametrize(
    "nonempty,reset,reject",
    [(False, False, False), (True, False, False), (True, True, False), (True, False, True)],
)
def test_actual_tap_reports_asr_and_actual_publication_fences(
    tmp_path, monkeypatch, nonempty, reset, reject
):
    import wave

    from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
    from civiccast.captions.tap_worker import CaptionTapWorker

    collector = BatchDiagnosticCollector()
    tap = CaptionTapWorker(
        tap_root=tmp_path / "tap",
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime([hypothesis()] if nonempty else []),
        review_store=InMemoryCaptionReviewStore(),
        atomic_segments=True,
        segment_seconds=5,
        batch_diagnostic=collector,
    )
    tap._sweep_retention()
    assert tap.wait_for_retention_sweep(timeout=5)
    if reset:
        original = tap._runtime.transcribe

        def reset_during_asr(chunks, vocabulary=None):
            tap.begin_channel_session("public")
            return original(chunks, vocabulary=vocabulary)

        monkeypatch.setattr(tap._runtime, "transcribe", reset_during_asr)
    if reject:
        monkeypatch.setattr(tap, "publish_for_current_session", lambda *args: False)
    segment = tmp_path / "tap" / "public" / "chunk-000000.wav"
    segment.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(segment), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TAP_SAMPLE_RATE_HZ)
        handle.writeframes(b"\x01\x00" * TAP_SAMPLE_RATE_HZ * 5)
    tap.run_once()
    record = collector.summarise(force=True)["batches"][0]
    assert record["outcome"] == "no-commit"
    counters = record["stage_counts"]
    assert counters["asr_batches"] == 1
    assert counters["asr_empty_batches"] == int(not nonempty)
    assert counters["asr_nonempty_batches"] == int(nonempty)
    assert counters["hypotheses"] == int(nonempty)
    assert counters["publish_accepted_batches"] == int(not reset and not reject)
    assert counters["publish_rejected_batches"] == int(reset or reject)
    assert counters["generation_discarded_segments"] == int(reset)


@pytest.mark.parametrize("next_outcome", ["accepted", "rejected", "reset", "storage-refused"])
def test_unknown_publication_count_never_interrupts_later_segments(
    tmp_path, monkeypatch, next_outcome
):
    import wave

    from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
    from civiccast.captions.tap_worker import CaptionTapWorker

    tap = CaptionTapWorker(
        tap_root=tmp_path / "tap",
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime([hypothesis()]),
        review_store=InMemoryCaptionReviewStore(),
        atomic_segments=True,
        segment_seconds=5,
        batch_diagnostic=BatchDiagnosticCollector(),
    )
    tap._sweep_retention()
    assert tap.wait_for_retention_sweep(timeout=5)
    channel_dir = tmp_path / "tap" / "public"
    channel_dir.mkdir(parents=True)
    segments = []
    for index in range(2):
        segment = channel_dir / f"chunk-{index:06d}.wav"
        with wave.open(str(segment), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TAP_SAMPLE_RATE_HZ)
            handle.writeframes(b"\x01\x00" * TAP_SAMPLE_RATE_HZ * 5)
        segments.append((index, segment))
    publications = []
    original_publish = tap._publish_cues

    def publish(channel, generation, cues, *, _diagnostic_acceptance=None):
        publications.append((channel, generation, cues))
        # Actual publication still runs; only its first diagnostic receipt is absent.
        return original_publish(
            channel,
            generation,
            cues,
            _diagnostic_acceptance=(_diagnostic_acceptance if len(publications) > 1 else None),
        )

    monkeypatch.setattr(tap, "_publish_cues", publish)
    original_transcribe = tap._runtime.transcribe
    transcriptions = []

    def transcribe(chunks, vocabulary=None):
        transcriptions.append(chunks)
        if len(transcriptions) == 2:
            if next_outcome == "reset":
                tap.begin_channel_session("public")
            elif next_outcome == "storage-refused":
                tap._retention_ready = False
            elif next_outcome == "rejected":
                monkeypatch.setattr(tap, "publish_for_current_session", lambda *args: False)
        return original_transcribe(chunks, vocabulary=vocabulary)

    monkeypatch.setattr(tap._runtime, "transcribe", transcribe)
    result = tap._process_channel("public", channel_dir, segments, batch_id="test")
    assert len(transcriptions) == 2
    assert len(publications) == (2 if next_outcome in {"accepted", "rejected"} else 1)
    if next_outcome in {"accepted", "rejected"}:
        assert len(publications[1][2]) == 1
        assert publications[1][2][0].text == hypothesis().text
    assert result.stage_counts["publish_accepted_batches"] is None
    assert result.stage_counts["publish_rejected_batches"] is None
    assert result.consumed_segments == (2 if next_outcome in {"accepted", "rejected"} else 1)
