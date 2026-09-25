# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for the opt-in per-batch caption-tap diagnostic.

The beta.9/beta.10 field episodes are rotating 1-4 minute caption-empty windows
and max-2 queued-segment overloads.  Phase timing answers "where did scan time
go" but cannot answer "what happened to THIS batch": whether a settled batch ran
ASR or was discarded, how deep the queue was when the decision was made, how old
the audio was, and which channel/session it belonged to.

These tests pin that contract, and pin that the switch is default-off and
metadata-only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from civiccast.captions import tap_batch_diagnostic as tbd


def test_switch_is_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(tbd.BATCH_DIAGNOSTIC_ENV_VAR, raising=False)
    assert isinstance(tbd.batch_diagnostic_from_env(), tbd.NullBatchDiagnostic)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_non_enabling_values_stay_inert(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(tbd.BATCH_DIAGNOSTIC_ENV_VAR, value)
    assert isinstance(tbd.batch_diagnostic_from_env(), tbd.NullBatchDiagnostic)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_enabling_values_build_the_real_collector(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(tbd.BATCH_DIAGNOSTIC_ENV_VAR, value)
    assert isinstance(tbd.batch_diagnostic_from_env(), tbd.BatchDiagnosticCollector)


def test_off_reads_no_clock_and_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_clock() -> float:
        pytest.fail("default-off batch diagnostic read the wall clock")

    monkeypatch.setattr(tbd.time, "monotonic", forbidden_clock)
    collector = tbd.NullBatchDiagnostic()
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-batch-000001",
        segment_indices=(1,),
        segment_names=("chunk-000001.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=5.0,
    )
    assert collector.summarise(force=True) == {}


def test_records_one_batch_per_outcome_with_queue_and_age() -> None:
    collector = tbd.BatchDiagnosticCollector()
    collector.begin_batch(
        channel="public",
        generation=3,
        batch_id="public-batch-000007",
        segment_indices=(7, 8),
        segment_names=("chunk-000007.wav", "chunk-000008.wav"),
        queue_depth=4,
        oldest_queue_age_seconds=12.5,
    )
    collector.finish_batch(
        batch_id="public-batch-000007",
        outcome="overloaded",
        reason="max-backlog-exceeded",
        consumed_segments=0,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0.75,
        queue_depth_after=4,
    )

    batches = collector.summarise(force=True)["batches"]
    assert len(batches) == 1
    record = batches[0]
    assert record["channel"] == "public"
    assert record["generation"] == 3
    assert record["batch_id"] == "public-batch-000007"
    assert record["segment_indices"] == [7, 8]
    assert record["segment_names"] == ["chunk-000007.wav", "chunk-000008.wav"]
    assert record["queue_depth"] == 4
    assert record["queue_depth_after"] == 4
    assert record["oldest_queue_age_seconds"] == 12.5
    assert record["outcome"] == "overloaded"
    assert record["reason"] == "max-backlog-exceeded"
    assert record["elapsed_seconds"] == 0.75


def test_unfinished_batch_is_reported_with_age_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rotating empty window can leave a batch queued for minutes.

    The summary must show it as unfinished with its age, or the diagnostic
    cannot explain the episode.
    """

    clock = {"t": 1000.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    collector = tbd.BatchDiagnosticCollector()
    collector.begin_batch(
        channel="education",
        generation=1,
        batch_id="education-batch-000042",
        segment_indices=(42,),
        segment_names=("chunk-000042.wav",),
        queue_depth=2,
        oldest_queue_age_seconds=3.0,
    )
    clock["t"] = 1060.0
    record = collector.summarise(force=True)["batches"][0]
    assert record["channel"] == "education"
    assert record["outcome"] == "unfinished"
    assert record["queue_depth"] == 2
    assert record["oldest_queue_age_seconds"] == 3.0
    assert record["age_seconds"] == 60.0


def test_records_are_bounded() -> None:
    """Retention is capped AND the cap freezes further emission."""

    collector = tbd.BatchDiagnosticCollector(max_batches=2)
    for index in range(2):
        collector.begin_batch(
            channel="public",
            generation=1,
            batch_id=f"public-batch-{index:06d}",
            segment_indices=(index,),
            segment_names=(f"chunk-{index:06d}.wav",),
            queue_depth=1,
            oldest_queue_age_seconds=0.0,
        )
        collector.finish_batch(
            batch_id=f"public-batch-{index:06d}",
            outcome="committed",
            reason="asr-committed",
            consumed_segments=1,
            committed_review_items=1,
            expired_unconfirmed_cues=0,
            elapsed_seconds=0.1,
        )
    first = collector.summarise(force=True)
    assert len(first["batches"]) == 2

    # Further activity past the cap is dropped, and the frozen set is not
    # re-emitted forever.
    for index in range(2, 5):
        collector.begin_batch(
            channel="public",
            generation=1,
            batch_id=f"public-batch-{index:06d}",
            segment_indices=(index,),
            segment_names=(f"chunk-{index:06d}.wav",),
            queue_depth=1,
            oldest_queue_age_seconds=0.0,
        )
    assert collector.enabled is False
    assert collector.summarise(force=True) == {}


def test_records_carry_no_speech_text_or_audio_bytes() -> None:
    collector = tbd.BatchDiagnosticCollector()
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-batch-000001",
        segment_indices=(1,),
        segment_names=("chunk-000001.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )
    collector.finish_batch(
        batch_id="public-batch-000001",
        outcome="committed",
        reason="asr-completed",
        consumed_segments=1,
        expired_unconfirmed_cues=1,
        elapsed_seconds=0.2,
    )
    serialised = json.dumps(collector.summarise(force=True))
    assert "the council" not in serialised
    assert "pcm" not in serialised
    assert serialised.count("chunk-000001.wav") == 1


def test_broken_logging_cannot_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = tbd.BatchDiagnosticCollector()
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-batch-000001",
        segment_indices=(1,),
        segment_names=("chunk-000001.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )

    def broken(*_a: object, **_k: object) -> None:
        raise OSError("handler failed")

    monkeypatch.setattr(tbd._LOG, "info", broken)
    assert collector.summarise(force=True)


def test_worker_records_overload_outcome_with_queue_and_reason(tmp_path: Path, caplog) -> None:
    """End-to-end seam: the worker must emit a batch record for a gate discard.

    This is the sensitive test: without the collector wired into the overload
    gate, the rotating empty-window overload has no per-batch record and the
    diagnostic cannot correlate queue depth/age with the discard.
    """

    import wave

    from civiccast.captions.review import InMemoryCaptionReviewStore
    from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
    from civiccast.captions.tap_worker import CaptionTapWorker

    class Runtime:
        def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
            return []

    def write_wav(path: Path, seconds: float = 5.0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TAP_SAMPLE_RATE_HZ)
            handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

    tap_root = tmp_path / "tap"

    collector = tbd.BatchDiagnosticCollector()
    worker = CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime(),  # type: ignore[arg-type]
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=5.0,
        atomic_segments=True,
        max_backlog_segments=2,
        # This test is about what the OVERLOAD DISCARD records, not about how
        # long an overshoot must persist before the gate discards (U11 B2 sets
        # that window to 15 scans and covers it in test_caption_tap_worker.py).
        # 1 restores the single-scan discard so the record under test exists.
        overload_persistence_scans=1,
        # This test pins what the pre-U23 FAIL-CLOSED discard records, so U23's
        # catch-up is switched off explicitly with its documented 0 setting.
        catch_up_shed_limit=0,
        batch_diagnostic=collector,
    )
    worker._sweep_retention()
    assert worker.wait_for_retention_sweep(timeout=5.0)

    # Written AFTER construction: audio that already exists when the worker
    # starts belongs to a previous session and is discarded at startup (U11 B1).
    for index in range(4):
        write_wav(tap_root / "public" / f"chunk-{index:06d}.wav")

    caplog.set_level(logging.INFO)
    result = worker.run_once()

    assert result.overloaded_channels == ("public",)
    batches = collector.summarise(force=True).get("batches", [])
    assert batches, "the overload gate emitted no per-batch diagnostic record"
    record = batches[0]
    assert record["channel"] == "public"
    assert record["outcome"] == "overloaded"
    assert record["reason"] == "max-backlog-exceeded"
    assert record["queue_depth"] == 4
    assert record["segment_indices"] == [0, 1, 2, 3]


def test_default_off_never_stats_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1: the off path must not stat files or compute queue age.

    A hot-path ``Path.stat``/clock read per batch is exactly the overhead the
    default-off contract promises not to add.
    """

    import wave

    from civiccast.captions.review import InMemoryCaptionReviewStore
    from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
    from civiccast.captions.tap_worker import CaptionTapWorker

    stat_calls: list[str] = []
    real_stat = Path.stat

    def counting_stat(self: Path, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        stat_calls.append(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counting_stat)

    class Runtime:
        def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
            return []

    def write_wav(path: Path, seconds: float = 5.0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TAP_SAMPLE_RATE_HZ)
            handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

    tap_root = tmp_path / "tap"

    worker = CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=tmp_path / "egress",
        runtime=Runtime(),  # type: ignore[arg-type]
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=5.0,
        atomic_segments=True,
        max_backlog_segments=2,
        # default: no batch_diagnostic -> inert collector
    )
    worker._sweep_retention()
    assert worker.wait_for_retention_sweep(timeout=5.0)

    # Written AFTER construction: audio that already exists when the worker
    # starts belongs to a previous session and is discarded at startup (U11 B1).
    # Without this the scan below would examine nothing and the "no stat on the
    # off path" assertion would pass for the wrong reason.
    for index in range(4):
        write_wav(tap_root / "public" / f"chunk-{index:06d}.wav")

    # Direct seam assertion: on the off path the queue-age helper must not run,
    # so no Path.stat (and no clock read) can happen for the diagnostic.
    age_calls: list[object] = []
    monkeypatch.setattr(
        worker,
        "_oldest_queue_age_seconds",
        lambda segments: age_calls.append(segments) or 0.0,
    )

    stat_calls.clear()
    worker.run_once()

    # The worker stats files for its OWN settle/scan logic; what must be absent
    # is the DIAGNOSTIC's queue-age computation. Assert that seam directly.
    assert age_calls == [], "off path computed queue age (would stat every segment)"
    assert isinstance(worker._batch_diagnostic, tbd.NullBatchDiagnostic)
    assert worker._batch_diagnostic.enabled is False


def test_window_expiry_stops_recording_and_emitting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 2: past window_seconds the collector must stop both.

    The pre-fix collector kept every record and re-logged the full cumulative
    list every summary interval forever, i.e. unbounded log volume.
    """

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    collector = tbd.BatchDiagnosticCollector(window_seconds=10.0)
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-g1-b000000-n1",
        segment_indices=(0,),
        segment_names=("chunk-000000.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )
    collector.finish_batch(
        batch_id="public-g1-b000000-n1",
        outcome="committed",
        reason="asr-committed",
        consumed_segments=1,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0.1,
    )
    assert collector.enabled is True
    first = collector.summarise(force=True)
    assert len(first["batches"]) == 1

    clock["t"] = 11.0  # past the 10s window
    assert collector.enabled is False
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-g1-b000001-n1",
        segment_indices=(1,),
        segment_names=("chunk-000001.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )
    collector.finish_batch(
        batch_id="public-g1-b000001-n1",
        outcome="committed",
        reason="asr-committed",
        consumed_segments=1,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0.1,
    )

    # No new records after expiry, and the FIRST forced summary after expiry
    # already emits nothing -- the cumulative set is not re-logged (bounded
    # emission), rather than the old behaviour of emitting forever.
    assert collector.summarise(force=True) == {}
    assert collector.summarise(force=True) == {}


def test_empty_asr_is_not_reported_as_committed(tmp_path: Path) -> None:
    """Finding 3: a consumed segment with no committed cues is not a commit."""

    import wave

    from civiccast.captions.models import CaptionHypothesis
    from civiccast.captions.review import InMemoryCaptionReviewStore
    from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
    from civiccast.captions.tap_worker import CaptionTapWorker

    class EmptyRuntime:
        """Transcribes to a VALID hypothesis that is filtered before commit.

        A hypothesis with ``text=""`` is rejected by ``CaptionHypothesis``
        validation (``text`` has ``min_length=1``).  That raised before the
        committed/no-commit decision and the batch was recorded as
        ``outcome="failed"``; the original assertion ``outcome != "committed"``
        then passed for the wrong reason and could not detect a mutation that
        always reported ``committed``.  Use valid, low-confidence text that the
        stabilizer/review path drops so the batch genuinely reaches the
        no-commit branch and is reported as ``no-commit``, not ``failed``.
        """

        def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
            for _chunk in chunks:
                yield CaptionHypothesis(
                    source_id="empty",
                    start_seconds=0.0,
                    end_seconds=5.0,
                    text="um",
                    confidence=0.0,
                )

    def write_wav(path: Path, seconds: float = 5.0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(TAP_SAMPLE_RATE_HZ)
            handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

    tap_root = tmp_path / "tap"

    collector = tbd.BatchDiagnosticCollector()
    worker = CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=tmp_path / "egress",
        runtime=EmptyRuntime(),  # type: ignore[arg-type]
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=5.0,
        atomic_segments=True,
        batch_diagnostic=collector,
    )
    worker._sweep_retention()
    assert worker.wait_for_retention_sweep(timeout=5.0)

    # Written AFTER construction: audio that already exists when the worker
    # starts belongs to a previous session and is discarded at startup (U11 B1).
    write_wav(tap_root / "public" / "chunk-000000.wav")
    worker.run_once()

    records = collector.summarise(force=True).get("batches", [])
    assert records
    assert all(record["outcome"] != "committed" for record in records), (
        f"a batch with no committed cues reported a commit: {records}"
    )
    # The batch must have genuinely reached the no-commit outcome.  Recording it
    # as "failed" (e.g. because the hypothesis was invalid) would satisfy the
    # negative assertion above while never exercising the branch under test.
    assert all(record["outcome"] != "failed" for record in records), (
        f"the batch failed instead of reaching the no-commit path: {records}"
    )
    assert records[0]["outcome"] == "no-commit", records
    assert records[0]["reason"] == "asr-completed-no-committed-items", records
    assert all(record.get("committed_review_items", 0) == 0 for record in records)


def test_inflight_summary_preserves_real_batch_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 4: an unfinished batch must keep its real id for correlation."""

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    collector = tbd.BatchDiagnosticCollector()
    collector.begin_batch(
        channel="education",
        generation=2,
        batch_id="education-g2-b000042-n1",
        segment_indices=(42,),
        segment_names=("chunk-000042.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )
    clock["t"] = 5.0
    record = collector.summarise(force=True)["batches"][0]
    assert record["outcome"] == "unfinished"
    assert record["batch_id"] == "education-g2-b000042-n1"

    # Its later completion still correlates to the same id.
    collector.finish_batch(
        batch_id="education-g2-b000042-n1",
        outcome="committed",
        reason="asr-committed",
        consumed_segments=1,
        committed_review_items=1,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0.4,
    )
    finished = collector.summarise(force=True)["batches"][-1]
    assert finished["batch_id"] == "education-g2-b000042-n1"
    assert finished["outcome"] == "committed"


def _make_record(collector: tbd.BatchDiagnosticCollector, index: int, clock) -> str:
    batch_id = f"public-g1-b{index:06d}-n1"
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id=batch_id,
        segment_indices=(index,),
        segment_names=(f"chunk-{index:06d}.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )
    collector.finish_batch(
        batch_id=batch_id,
        outcome="committed",
        reason="asr-committed",
        consumed_segments=1,
        committed_review_items=1,
        expired_unconfirmed_cues=0,
        elapsed_seconds=0.1,
    )
    return batch_id


def test_no_duplicate_payload_when_no_new_activity(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """(a) Identical cumulative payload must not be re-logged every interval.

    With a 10MB rotating log, re-emitting 2000 records every 30s erases the
    evidence it was meant to preserve.
    """

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    caplog.set_level(logging.INFO)
    collector = tbd.BatchDiagnosticCollector(summary_interval_seconds=30.0)

    _make_record(collector, 0, clock)
    clock["t"] = 31.0
    first = collector.summarise()
    assert first and len(first["batches"]) == 1

    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 1

    # No new activity across several intervals: no second payload.
    clock["t"] = 62.0
    assert collector.summarise() == {}
    clock["t"] = 93.0
    assert collector.summarise() == {}
    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 1, f"duplicate cumulative payloads emitted: {len(lines)}"

    # A genuinely new record is reported -- and only the NEW one.
    _make_record(collector, 1, clock)
    clock["t"] = 124.0
    second = collector.summarise()
    assert len(second["batches"]) == 1
    assert second["batches"][0]["segment_indices"] == [1]
    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 2


def test_final_post_window_report_once_includes_unreported_and_inflight(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """(b) The window-closing report must surface what was never reported.

    Records since the prior summary AND in-flight state must appear in exactly
    one final report; the old code returned {} and dropped them.
    """

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    caplog.set_level(logging.INFO)
    collector = tbd.BatchDiagnosticCollector(window_seconds=100.0)

    _make_record(collector, 0, clock)
    clock["t"] = 31.0
    assert len(collector.summarise()["batches"]) == 1  # b0 reported

    _make_record(collector, 1, clock)  # b1 NOT yet reported
    collector.begin_batch(  # b2 still in flight
        channel="education",
        generation=2,
        batch_id="education-g2-b000002-n1",
        segment_indices=(2,),
        segment_names=("chunk-000002.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )

    clock["t"] = 101.0  # past the window
    final = collector.summarise(force=True)
    assert final, "the window-closing summary dropped unreported activity"
    ids = [record["batch_id"] for record in final["batches"]]
    assert ids == ["public-g1-b000001-n1", "education-g2-b000002-n1"], ids
    assert final["exhausted"] is True
    assert [r["outcome"] for r in final["batches"]] == ["committed", "unfinished"]

    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 2


def test_no_emission_after_final_post_window_report(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """(c) After the single window-closing report the collector is silent."""

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    caplog.set_level(logging.INFO)
    collector = tbd.BatchDiagnosticCollector(window_seconds=50.0)

    _make_record(collector, 0, clock)
    clock["t"] = 51.0
    assert collector.summarise(force=True)

    for later in (80.0, 110.0, 140.0):
        clock["t"] = later
        assert collector.summarise(force=True) == {}
        assert collector.summarise() == {}

    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 1, f"emitted after final report: {len(lines)}"
    assert collector.enabled is False


def test_hung_inflight_batch_does_not_reemit_after_window_closing_report(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """The closing report includes in-flight work ONCE, even if it never ends.

    A hung ASR call must not re-log the same 'unfinished' record every interval
    after expiry. The previous no-emission test used only completed records, so
    it could not catch this.
    """

    clock = {"t": 0.0}
    monkeypatch.setattr(tbd.time, "monotonic", lambda: clock["t"])
    caplog.set_level(logging.INFO)
    collector = tbd.BatchDiagnosticCollector(window_seconds=50.0)

    # One batch still in flight when the window expires -- and never finished.
    collector.begin_batch(
        channel="public",
        generation=1,
        batch_id="public-g1-b000000-n1",
        segment_indices=(0,),
        segment_names=("chunk-000000.wav",),
        queue_depth=1,
        oldest_queue_age_seconds=0.0,
    )

    clock["t"] = 51.0
    final = collector.summarise(force=True)
    assert final, "the closing report dropped the in-flight batch"
    assert final["exhausted"] is True
    assert [r["batch_id"] for r in final["batches"]] == ["public-g1-b000000-n1"]
    assert [r["outcome"] for r in final["batches"]] == ["unfinished"]

    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 1

    # Second and third post-expiry calls, with the SAME batch still in flight:
    # the at-most-once contract must hold.
    for later in (81.0, 111.0):
        clock["t"] = later
        assert collector.summarise(force=True) == {}
        assert collector.summarise() == {}

    lines = [r.message for r in caplog.records if r.message.startswith("Caption tap batch")]
    assert len(lines) == 1, f"hung in-flight batch re-emitted {len(lines)} payloads"
    assert collector.enabled is False


class TestOverloadCarriesPrecedingBatchDuration:
    """Coordinator audit HOLD (2026-09-24): an actual overload discard happens
    AFTER the in-flight batch completes (``_channel_has_inflight`` skips the
    gate while a batch runs). So a field sampled from the *live* in-flight map
    is 0 exactly when the overload trips, and the completed record's own
    ``elapsed_seconds`` is already there. What the report actually needs is the
    DURATION OF THE BATCH THAT JUST FINISHED AND PUSHED THE QUEUE OVER THE GATE.

    These tests drive a real held ASR batch to completion, then let the next
    scan discard the backlog, and assert the discard carries the preceding
    batch's measured duration as a NONZERO, meaningful value.
    """

    def test_overload_discard_records_prior_batch_duration_nonzero(self, tmp_path: Path) -> None:
        import threading
        import time as _time
        import wave

        from civiccast.captions.review import InMemoryCaptionReviewStore
        from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
        from civiccast.captions.tap_worker import CaptionTapWorker

        class _HeldRuntime:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
                self.started.set()
                assert self.release.wait(timeout=10.0), "test runtime was not released"
                return []

        def write_wav(path: Path, seconds: float = 5.0) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(TAP_SAMPLE_RATE_HZ)
                handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

        tap_root = tmp_path / "tap"
        channel = tap_root / "public"

        runtime = _HeldRuntime()
        collector = tbd.BatchDiagnosticCollector()
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tmp_path / "egress",
            runtime=runtime,  # type: ignore[arg-type]
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=5.0,
            atomic_segments=True,
            max_backlog_segments=2,
            # What the DISCARD records is the subject here, not how long an
            # overshoot must persist first (U11 B2). 1 restores the single-scan
            # discard so this test's overload actually happens; the shipped
            # window is covered in test_caption_tap_worker.py.
            overload_persistence_scans=1,
            # This test pins the pre-U23 FAIL-CLOSED discard record itself, so
            # U23's catch-up is switched off explicitly with its documented 0
            # setting: the first persistent overshoot pauses, exactly as before
            # this unit. U23's shed record is covered in
            # test_caption_tap_worker.py::TestCaptionTapCatchUp.
            catch_up_shed_limit=0,
            batch_diagnostic=collector,
        )
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5.0)

        # Written AFTER construction: audio that already exists when the worker
        # starts belongs to a previous session and is discarded at startup
        # (U11 B1).
        for index in range(2):
            write_wav(channel / f"chunk-{index:06d}.wav")

        first = worker.run_once(wait_for_results=False)
        assert first.overloaded_channels == ()
        assert runtime.started.wait(timeout=2.0), "the first batch never entered ASR"

        # Hold that batch for a measurable wall-clock duration while fresh
        # segments settle behind it.
        _time.sleep(0.5)
        for index in range(2, 5):
            write_wav(channel / f"chunk-{index:06d}.wav")

        # Mid-flight scan must NOT fabricate an overload.
        mid = worker.run_once(wait_for_results=False)
        assert mid.overloaded_channels == ()
        assert mid.dropped_overload_segments == 0

        # Let the held batch finish; it is the batch whose duration explains
        # the queue that the NEXT scan will find over the max-2 gate.
        runtime.release.set()
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and worker._channel_futures:
            _time.sleep(0.02)
        assert not worker._channel_futures

        # The overload DISCARD now happens with no in-flight batch at all.
        overload_scan = worker.run_once(wait_for_results=False)
        assert overload_scan.overloaded_channels == ("public",), overload_scan
        assert overload_scan.dropped_overload_segments == 3

        records = list(collector._records)
        discards = [record for record in records if record.get("outcome") == "overloaded"]
        assert discards, f"the overload discard was never recorded: {records}"
        record = discards[0]
        assert "preceding_batch_seconds" in record, (
            "the overload discard must carry the duration of the batch that "
            f"pushed the queue over the gate; fields={sorted(record)}"
        )
        assert record["preceding_batch_seconds"] >= 0.4, (
            "the recorded preceding-batch duration must be the REAL held-batch "
            f"duration, not 0.0 or a placeholder: {record}"
        )

    def test_overload_has_no_prior_batch_records_zero_not_fabricated(self, tmp_path: Path) -> None:
        """Negative control: a cold backlog with no preceding batch stays 0.0.

        If nothing ran before the overload, the field must be an honest 0.0
        rather than inventing a duration.
        """

        import wave

        from civiccast.captions.review import InMemoryCaptionReviewStore
        from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
        from civiccast.captions.tap_worker import CaptionTapWorker

        class _FastRuntime:
            def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
                return []

        def write_wav(path: Path, seconds: float = 5.0) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(TAP_SAMPLE_RATE_HZ)
                handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

        tap_root = tmp_path / "tap"
        channel = tap_root / "public"

        collector = tbd.BatchDiagnosticCollector()
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tmp_path / "egress",
            runtime=_FastRuntime(),  # type: ignore[arg-type]
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=5.0,
            atomic_segments=True,
            max_backlog_segments=2,
            # The subject is the recorded 0.0, not the persistence window
            # (U11 B2); 1 restores the single-scan discard.
            overload_persistence_scans=1,
            # This test pins the pre-U23 FAIL-CLOSED discard record itself, so
            # U23's catch-up is switched off explicitly with its documented 0
            # setting: the first persistent overshoot pauses, exactly as before
            # this unit. U23's shed record is covered in
            # test_caption_tap_worker.py::TestCaptionTapCatchUp.
            catch_up_shed_limit=0,
            batch_diagnostic=collector,
        )
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5.0)

        # Written AFTER construction: audio that already exists when the worker
        # starts belongs to a previous session and is discarded at startup
        # (U11 B1). Four settled segments on a COLD channel: the very first scan
        # overloads before any batch has ever run.
        for index in range(4):
            write_wav(channel / f"chunk-{index:06d}.wav")

        result = worker.run_once()
        assert result.overloaded_channels == ("public",), result
        records = list(collector._records)
        discards = [record for record in records if record.get("outcome") == "overloaded"]
        assert discards, records
        assert discards[0].get("preceding_batch_seconds") == 0.0, (
            "a cold overload with no preceding batch must report 0.0, not "
            f"fabricate a duration: {discards[0]}"
        )

    def test_default_off_never_stamps_or_reads_the_new_batch_clocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The new correlation plumbing must be INERT on the default-off path.

        ``_submit_channel`` and ``_channel_future_done`` only touch the new
        start clock / last-duration maps when the diagnostic is enabled, so a
        station that never opts in pays no extra clock read and gets no new
        map entries -- the strongest form of the default-off promise.
        """

        import wave

        from civiccast.captions.review import InMemoryCaptionReviewStore
        from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
        from civiccast.captions.tap_worker import CaptionTapWorker

        class _FastRuntime:
            def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
                return []

        def write_wav(path: Path, seconds: float = 5.0) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(TAP_SAMPLE_RATE_HZ)
                handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

        tap_root = tmp_path / "tap"
        channel = tap_root / "public"

        # Default: no batch_diagnostic injected -> NullBatchDiagnostic.
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tmp_path / "egress",
            runtime=_FastRuntime(),  # type: ignore[arg-type]
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=5.0,
            atomic_segments=True,
            max_backlog_segments=2,
        )
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5.0)
        assert worker._batch_diagnostic.enabled is False

        # Written AFTER construction: audio that already exists when the worker
        # starts belongs to a previous session and is discarded at startup (U11
        # B1). Without this the scan below would find nothing to dispatch and the
        # inert-clock assertion would pass for the wrong reason.
        for index in range(2):
            write_wav(channel / f"chunk-{index:06d}.wav")

        worker.run_once()

        assert worker._channel_batch_started_at == {}, (
            "the default-off path stamped the new batch start clock"
        )
        assert worker._channel_last_batch_seconds == {}, (
            "the default-off path recorded a new last-batch duration"
        )

        # The read path must be inert too: no executor lock, no retained-value
        # access, no clock. Forge a value and prove the disabled read ignores it.
        worker._channel_last_batch_seconds["public"] = 9.5
        locked: list[str] = []

        real_lock = worker._channel_executor_lock

        class _SpyLock:
            def __enter__(self) -> object:
                locked.append("acquired")
                return real_lock.__enter__()

            def __exit__(self, *exc: object) -> bool:
                return bool(real_lock.__exit__(*exc))

        worker._channel_executor_lock = _SpyLock()  # type: ignore[assignment]
        try:
            assert worker._last_batch_seconds("public") == 0.0, (
                "the disabled read returned a retained value"
            )
            assert locked == [], "the disabled _last_batch_seconds took the executor lock"
            worker._forget_last_batch_duration("public")
            assert locked == [], "the disabled _forget_last_batch_duration took the executor lock"
        finally:
            worker._channel_executor_lock = real_lock  # type: ignore[assignment]


class TestPrecedingBatchSessionScoping:
    """Coordinator rev2 audit: ``_channel_last_batch_seconds`` is keyed only by
    channel, so WITHOUT a reset it would let a COLD new broadcast session report
    the PRIOR session's completed duration as its own overload cause. The value
    must be cleared whenever the channel's session/generation is reset
    (``_begin_channel_session_locked`` / ``_clear_channel_captions``).
    """

    def test_prior_session_duration_does_not_leak_into_a_new_session(self, tmp_path: Path) -> None:
        import threading
        import time as _time
        import wave

        from civiccast.captions.review import InMemoryCaptionReviewStore
        from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
        from civiccast.captions.tap_worker import CaptionTapWorker

        class _HeldRuntime:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
                self.started.set()
                assert self.release.wait(timeout=10.0), "test runtime was not released"
                return []

        def write_wav(path: Path, seconds: float = 5.0) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(TAP_SAMPLE_RATE_HZ)
                handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

        tap_root = tmp_path / "tap"
        channel = tap_root / "public"

        runtime = _HeldRuntime()
        collector = tbd.BatchDiagnosticCollector()
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tmp_path / "egress",
            runtime=runtime,  # type: ignore[arg-type]
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=5.0,
            atomic_segments=True,
            max_backlog_segments=2,
            # Session 2's COLD overload is the subject, not the persistence
            # window (U11 B2); 1 restores the single-scan discard.
            overload_persistence_scans=1,
            # This test pins the pre-U23 FAIL-CLOSED discard record itself, so
            # U23's catch-up is switched off explicitly with its documented 0
            # setting: the first persistent overshoot pauses, exactly as before
            # this unit. U23's shed record is covered in
            # test_caption_tap_worker.py::TestCaptionTapCatchUp.
            catch_up_shed_limit=0,
            batch_diagnostic=collector,
        )
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5.0)

        # Written AFTER construction: audio that already exists when the worker
        # starts belongs to a previous session and is discarded at startup
        # (U11 B1).
        for index in range(2):
            write_wav(channel / f"chunk-{index:06d}.wav")

        # Session 1: a real held batch runs ~0.5 s and completes, so the
        # last-batch duration is a meaningful nonzero number.
        assert worker.run_once(wait_for_results=False).overloaded_channels == ()
        assert runtime.started.wait(timeout=2.0)
        _time.sleep(0.5)
        runtime.release.set()
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and worker._channel_futures:
            _time.sleep(0.02)
        assert not worker._channel_futures
        assert worker._last_batch_seconds("public") >= 0.4, (
            "session 1 did not record its completed-batch duration"
        )

        # Session 2: the broadcast restarts. A cold new session must NOT inherit
        # session 1's duration as the explanation for its own overload.
        worker.begin_channel_session("public")
        assert worker._last_batch_seconds("public") == 0.0, (
            "a prior session's completed duration leaked into the new session"
        )

        # And a cold overload in session 2 must report 0.0, not the stale value.
        for index in range(100, 104):
            write_wav(channel / f"chunk-{index:06d}.wav")
        result = worker.run_once()
        assert result.overloaded_channels == ("public",), result
        discards = [
            record for record in collector._records if record.get("outcome") == "overloaded"
        ]
        assert discards, collector._records
        assert discards[0]["preceding_batch_seconds"] == 0.0, (
            f"a new session's cold overload reported the prior session's duration: {discards[0]}"
        )

    def test_clear_channel_captions_resets_the_last_batch_duration(self, tmp_path: Path) -> None:
        """The overload fail-closed clear must also drop the stale duration."""

        import threading
        import time as _time
        import wave

        from civiccast.captions.review import InMemoryCaptionReviewStore
        from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
        from civiccast.captions.tap_worker import CaptionTapWorker

        class _HeldRuntime:
            def __init__(self) -> None:
                self.started = threading.Event()
                self.release = threading.Event()

            def transcribe(self, chunks, vocabulary=None):  # type: ignore[no-untyped-def]
                self.started.set()
                assert self.release.wait(timeout=10.0), "test runtime was not released"
                return []

        def write_wav(path: Path, seconds: float = 5.0) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(TAP_SAMPLE_RATE_HZ)
                handle.writeframes(b"\x01\x00" * int(TAP_SAMPLE_RATE_HZ * seconds))

        tap_root = tmp_path / "tap"
        channel = tap_root / "public"

        runtime = _HeldRuntime()
        collector = tbd.BatchDiagnosticCollector()
        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tmp_path / "egress",
            runtime=runtime,  # type: ignore[arg-type]
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=5.0,
            atomic_segments=True,
            max_backlog_segments=2,
            batch_diagnostic=collector,
        )
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5.0)

        # Written AFTER construction: audio that already exists when the worker
        # starts belongs to a previous session and is discarded at startup
        # (U11 B1).
        for index in range(2):
            write_wav(channel / f"chunk-{index:06d}.wav")

        assert worker.run_once(wait_for_results=False).overloaded_channels == ()
        assert runtime.started.wait(timeout=2.0)
        _time.sleep(0.4)
        runtime.release.set()
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and worker._channel_futures:
            _time.sleep(0.02)
        assert worker._last_batch_seconds("public") >= 0.3

        worker._clear_channel_captions("public")
        assert worker._last_batch_seconds("public") == 0.0, (
            "the fail-closed caption clear left the prior batch duration behind"
        )
