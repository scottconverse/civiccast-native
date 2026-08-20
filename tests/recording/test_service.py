# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S21 recording service layer — recurrence expansion, state-machine
progression, ad-hoc capture, orphan reconciliation, and the
``RecordingService.tick`` scheduler entrypoint.

The capture pipeline, asset finalizer, and alert sink are all injected
as in-memory stubs so the tests are fast and never touch a real
GStreamer / S7 / S8.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.recording.models import (
    RecordingJob,
    RecordingSchedule,
    RecordingSource,
    RecurrenceSpec,
)
from civiccast.recording.service import (
    CaptureResult,
    RecordingPipelineFailureError,
    RecordingPipelineUnwiredError,
    RecordingService,
    _job_id_for,
    _materialize_starts,
)
from civiccast.recording.store import (
    RecordingJobNotFoundError,
    RecordingJobStateError,
    RecordingScheduleNotFoundError,
    RecordingStore,
)

_STATION = "civiccast-station"
_FROZEN_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class StubCapturePipeline:
    """Records arm/start/finalize/stop calls; configurable raises."""

    def __init__(
        self,
        *,
        raise_on_arm: BaseException | None = None,
        raise_on_start: BaseException | None = None,
        raise_on_finalize: BaseException | None = None,
        raise_on_stop: BaseException | None = None,
        finalize_result: CaptureResult | None = None,
        stop_result: CaptureResult | None = None,
    ) -> None:
        self.arm_calls: list[dict] = []
        self.start_calls: list[str] = []
        self.finalize_calls: list[str] = []
        self.stop_calls: list[str] = []
        self._raise_arm = raise_on_arm
        self._raise_start = raise_on_start
        self._raise_finalize = raise_on_finalize
        self._raise_stop = raise_on_stop
        self._finalize_result = finalize_result or CaptureResult(
            bytes_written=1_048_576,
            capture_path="/var/lib/civiccast/captures/job.ts",
            sha256="a" * 64,
        )
        self._stop_result = stop_result or CaptureResult(
            bytes_written=524_288,
            capture_path="/var/lib/civiccast/captures/job-partial.ts",
            sha256=None,
        )

    def arm(self, *, job_id, source, encoder_profile, loudness_regime):
        self.arm_calls.append(
            {
                "job_id": job_id,
                "source": source,
                "encoder_profile": encoder_profile,
                "loudness_regime": loudness_regime,
            }
        )
        if self._raise_arm is not None:
            raise self._raise_arm

    def start(self, job_id):
        self.start_calls.append(job_id)
        if self._raise_start is not None:
            raise self._raise_start

    def finalize(self, job_id):
        self.finalize_calls.append(job_id)
        if self._raise_finalize is not None:
            raise self._raise_finalize
        return self._finalize_result

    def stop(self, job_id):
        self.stop_calls.append(job_id)
        if self._raise_stop is not None:
            raise self._raise_stop
        return self._stop_result


class StubFinalizer:
    """Records finalize_to_asset calls; returns deterministic asset ids."""

    def __init__(self, *, raise_on_finalize: BaseException | None = None) -> None:
        self.calls: list[dict] = []
        self._raise = raise_on_finalize

    def finalize_to_asset(
        self,
        *,
        station_id,
        capture_path,
        target_series,
        custom_field_values,
        sha256,
    ):
        self.calls.append(
            {
                "station_id": station_id,
                "capture_path": capture_path,
                "target_series": target_series,
                "custom_field_values": dict(custom_field_values or {}),
                "sha256": sha256,
            }
        )
        if self._raise is not None:
            raise self._raise
        return f"asset-{len(self.calls)}"


class StubAlertSink:
    """Records emit calls; configurable raise so we can prove durability."""

    def __init__(self, *, raise_on_emit: bool = False) -> None:
        self.emits: list[dict] = []
        self._raise = raise_on_emit

    def emit(self, *, severity, source, message, context):
        self.emits.append(
            {
                "severity": severity,
                "source": source,
                "message": message,
                "context": dict(context),
            }
        )
        if self._raise:
            raise RuntimeError("alert sink boom")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[RecordingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 's.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield RecordingStore(factory)
    finally:
        eng.dispose()


def _frozen_clock(at: datetime = _FROZEN_NOW):
    def _now() -> datetime:
        return at

    return _now


def _src(kind: str = "rtsp", **kw) -> RecordingSource:
    base: dict = {"kind": kind}
    if kind in ("sdi", "hdmi", "ndi"):
        base["input_id"] = kw.pop("input_id", "default-input")
    else:
        base["uri"] = kw.pop("uri", f"{kind}://example.local/stream")
    base.update(kw)
    return RecordingSource(**base)


def _weekly(weekdays: list[int], time_hhmm: str = "19:00") -> RecurrenceSpec:
    return RecurrenceSpec(kind="weekly", weekdays=weekdays, time_hhmm=time_hhmm)


def _oneshot(start: datetime) -> RecurrenceSpec:
    return RecurrenceSpec(kind="one_shot", start=start)


def _schedule(
    schedule_id: str = "sch-1",
    *,
    name: str | None = None,
    source: RecordingSource | None = None,
    recurrence: RecurrenceSpec | None = None,
    duration_seconds: int = 3600,
    loudness_regime: str = "atsc-a85",
    target_series: str | None = "council",
    enabled: bool = True,
) -> RecordingSchedule:
    return RecordingSchedule(
        schedule_id=schedule_id,
        station_id=_STATION,
        name=name or f"Schedule {schedule_id}",
        source=source or _src(),
        recurrence=recurrence or _oneshot(_FROZEN_NOW + timedelta(minutes=5)),
        duration_seconds=duration_seconds,
        encoder_profile="hw-h264-1080p",
        loudness_regime=loudness_regime,
        target_series=target_series,
        custom_field_values={"committee": "council"},
        enabled=enabled,
    )


def _build_service(
    store: RecordingStore,
    *,
    pipeline: StubCapturePipeline | None = None,
    finalizer: StubFinalizer | None = None,
    alert_sink: StubAlertSink | None = None,
    clock=None,
    arm_lead: timedelta | None = None,
) -> RecordingService:
    kwargs: dict = {}
    if pipeline is not None:
        kwargs["capture_pipeline"] = pipeline
    if finalizer is not None:
        kwargs["asset_finalizer"] = finalizer
    if alert_sink is not None:
        kwargs["alert_sink"] = alert_sink
    kwargs["clock"] = clock or _frozen_clock()
    if arm_lead is not None:
        kwargs["arm_lead"] = arm_lead
    return RecordingService(store, **kwargs)


# ---------------------------------------------------------------------------
# Pure recurrence materializer
# ---------------------------------------------------------------------------


class TestMaterializer:
    def test_oneshot_in_window_returns_one(self):
        start = _FROZEN_NOW + timedelta(hours=1)
        out = _materialize_starts(
            _oneshot(start),
            _FROZEN_NOW,
            _FROZEN_NOW + timedelta(hours=24),
        )
        assert out == [start]

    def test_oneshot_in_the_past_returns_none(self):
        start = _FROZEN_NOW - timedelta(hours=1)
        out = _materialize_starts(_oneshot(start), _FROZEN_NOW, _FROZEN_NOW + timedelta(hours=24))
        assert out == []

    def test_oneshot_past_deadline_returns_none(self):
        start = _FROZEN_NOW + timedelta(days=8)
        out = _materialize_starts(_oneshot(start), _FROZEN_NOW, _FROZEN_NOW + timedelta(days=7))
        assert out == []

    def test_weekly_covers_seven_days(self):
        rec = _weekly([0, 1, 2, 3, 4, 5, 6], "12:30")
        out = _materialize_starts(rec, _FROZEN_NOW, _FROZEN_NOW + timedelta(days=7))
        # _FROZEN_NOW is 12:00 on 2026-06-18 (Thursday). Today's 12:30
        # is in-window; then six more days through next Wednesday.
        assert len(out) == 7
        for start in out:
            assert start.hour == 12
            assert start.minute == 30
            assert start.weekday() in {0, 1, 2, 3, 4, 5, 6}

    def test_weekly_filters_to_weekday_set(self):
        # _FROZEN_NOW is Thursday (3). Use Mon (0) + Fri (4) only.
        rec = _weekly([0, 4], "10:00")
        # Note 10:00 today is BEFORE 12:00 now; the day-of would not
        # qualify even if Thursday were in the set.
        out = _materialize_starts(rec, _FROZEN_NOW, _FROZEN_NOW + timedelta(days=10))
        weekdays = {start.weekday() for start in out}
        assert weekdays.issubset({0, 4})
        # 10 days from Thursday spans both a Friday and a Monday.
        assert {0, 4}.issubset(weekdays)

    def test_weekly_time_today_in_the_past_is_filtered(self):
        # _FROZEN_NOW is 2026-06-18T12:00Z (Thursday). 08:00 today is
        # in the past — should not materialize.
        rec = _weekly([_FROZEN_NOW.weekday()], "08:00")
        out = _materialize_starts(rec, _FROZEN_NOW, _FROZEN_NOW + timedelta(hours=23))
        assert out == []

    def test_round_trip_deterministic(self):
        rec = _weekly([1, 3, 5], "20:15")
        a = _materialize_starts(rec, _FROZEN_NOW, _FROZEN_NOW + timedelta(days=14))
        b = _materialize_starts(rec, _FROZEN_NOW, _FROZEN_NOW + timedelta(days=14))
        assert a == b

    def test_job_id_for_is_slug_shaped(self):
        jid = _job_id_for("sch-council", _FROZEN_NOW)
        # Must satisfy the Slug pattern: [a-z0-9][a-z0-9_-]*
        assert jid.startswith("job-")
        assert all(c.isalnum() or c in {"-", "_"} for c in jid)
        # Same inputs → same id (idempotency).
        assert jid == _job_id_for("sch-council", _FROZEN_NOW)

    def test_job_id_for_distinguishes_underscore_and_dash(self):
        """E-1 fix — pre-fix ``sch_a`` and ``sch-a`` collapsed to the same
        job_id because the safe-form did ``.replace("_", "-")``. Both are
        valid Slug-shaped schedule_ids; they MUST produce distinct
        deterministic job ids or the materializer PK-collides between
        legitimately-distinct schedules."""
        a = _job_id_for("sch_a", _FROZEN_NOW)
        b = _job_id_for("sch-a", _FROZEN_NOW)
        assert a != b


# ---------------------------------------------------------------------------
# expand_jobs_for_horizon
# ---------------------------------------------------------------------------


class TestExpand:
    def test_oneshot_in_window_materializes_one_job(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert len(created) == 1
        assert created[0].schedule_id == sched.schedule_id
        assert created[0].state == "scheduled"
        assert created[0].source_snapshot.kind == "rtsp"

    def test_weekly_seven_day_horizon(self, store: RecordingStore):
        sched = _schedule(recurrence=_weekly([0, 1, 2, 3, 4, 5, 6], "13:00"))
        store.upsert_schedule(sched)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(days=7))
        # 13:00 today + six more days.
        assert len(created) == 7
        for job in created:
            assert job.planned_end - job.planned_start == timedelta(seconds=3600)

    def test_idempotent_on_rerun(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store)
        first = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        second = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert len(first) == 1
        assert second == []

    def test_disabled_schedule_does_not_materialize(self, store: RecordingStore):
        sched = _schedule(enabled=False, recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert created == []

    def test_overlap_at_expansion_does_not_skip(self, store: RecordingStore):
        # The materializer does NOT decide overlap (DC-5 lands at arm
        # time). Two schedules on the same source materialize fully;
        # the overlap is rejected at arm.
        sched_a = _schedule(
            schedule_id="sch-a",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
        )
        sched_b = _schedule(
            schedule_id="sch-b",
            name="Other",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=15)),
        )
        store.upsert_schedule(sched_a)
        store.upsert_schedule(sched_b)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert len(created) == 2

    def test_loudness_regime_propagates_to_job(self, store: RecordingStore):
        sched = _schedule(loudness_regime="ebu-r128")
        store.upsert_schedule(sched)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert created[0].loudness_regime == "ebu-r128"

    def test_target_series_and_custom_fields_propagate(self, store: RecordingStore):
        sched = _schedule()
        store.upsert_schedule(sched)
        svc = _build_service(store)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        assert job.target_series == "council"
        assert job.custom_field_values == {"committee": "council"}

    def test_other_station_schedules_ignored(self, store: RecordingStore):
        sched = _schedule()
        store.upsert_schedule(sched)
        svc = _build_service(store)
        out = svc.expand_jobs_for_horizon("not-this-station", timedelta(hours=2))
        assert out == []


# ---------------------------------------------------------------------------
# arm_job
# ---------------------------------------------------------------------------


class TestArmJob:
    def _setup(self, store: RecordingStore, **svc_kw):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert, **svc_kw)
        jobs = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        return svc, pipeline, alert, jobs[0]

    def test_happy_path_transitions_to_arming(self, store: RecordingStore):
        svc, pipeline, alert, job = self._setup(store)
        result = svc.arm_job(job.job_id)
        assert result.state == "arming"
        assert pipeline.arm_calls and pipeline.arm_calls[0]["job_id"] == job.job_id
        assert alert.emits == []

    def test_passes_loudness_regime_to_pipeline(self, store: RecordingStore):
        svc, pipeline, _, job = self._setup(store)
        svc.arm_job(job.job_id)
        assert pipeline.arm_calls[0]["loudness_regime"] == "atsc-a85"
        assert pipeline.arm_calls[0]["encoder_profile"] == "hw-h264-1080p"

    def test_wrong_state_raises(self, store: RecordingStore):
        svc, _, _, job = self._setup(store)
        svc.arm_job(job.job_id)
        with pytest.raises(RecordingJobStateError):
            svc.arm_job(job.job_id)  # already arming

    def test_unwired_pipeline_raises_unwired(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store)  # no pipeline
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingPipelineUnwiredError):
            svc.arm_job(job.job_id)

    def test_overlap_at_arm_transitions_to_skipped(self, store: RecordingStore):
        # Two schedules overlapping on same source.
        sched_a = _schedule(
            schedule_id="sch-a",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
        )
        sched_b = _schedule(
            schedule_id="sch-b",
            name="Other",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=15)),
        )
        store.upsert_schedule(sched_a)
        store.upsert_schedule(sched_b)
        pipeline = StubCapturePipeline()
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert)
        a, b = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        svc.arm_job(a.job_id)  # arms first
        result = svc.arm_job(b.job_id)
        assert result.state == "skipped"
        assert result.failure_reason and "overlapping" in result.failure_reason.lower()
        assert any(e["source"] == "recording.overlap" for e in alert.emits)

    def test_pipeline_raise_transitions_to_failed_and_alerts(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("source unreachable"))
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingPipelineFailureError):
            svc.arm_job(job.job_id)
        # Job is durably failed.
        failed = store.get_job(job.job_id)
        assert failed is not None
        assert failed.state == "failed"
        assert failed.failure_reason and "arm" in failed.failure_reason.lower()
        # S8 alert emitted.
        assert alert.emits
        assert alert.emits[0]["severity"] == "critical"
        assert alert.emits[0]["context"]["phase"] == "arm"

    def test_pipeline_raise_with_no_alert_sink_still_fails_job(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("boom"))
        svc = _build_service(store, pipeline=pipeline)  # no alert sink
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingPipelineFailureError):
            svc.arm_job(job.job_id)
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]

    def test_alert_sink_raise_does_not_lose_job_state(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("boom"))
        alert = StubAlertSink(raise_on_emit=True)
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingPipelineFailureError):
            svc.arm_job(job.job_id)
        # Even though the alert sink itself raised, the job is durable.
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]

    def test_missing_job_raises_not_found(self, store: RecordingStore):
        svc = _build_service(store, pipeline=StubCapturePipeline())
        with pytest.raises(RecordingJobNotFoundError):
            svc.arm_job("missing")


# ---------------------------------------------------------------------------
# start_job
# ---------------------------------------------------------------------------


class TestStartJob:
    def _armed(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        return svc, pipeline, job

    def test_happy_path_transitions_to_recording(self, store: RecordingStore):
        svc, pipeline, job = self._armed(store)
        result = svc.start_job(job.job_id)
        assert result.state == "recording"
        assert result.started_at is not None
        assert pipeline.start_calls == [job.job_id]

    def test_wrong_state_raises(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store, pipeline=StubCapturePipeline())
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingJobStateError):
            svc.start_job(job.job_id)  # scheduled, not arming

    def test_pipeline_raise_fails_job(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_start=RuntimeError("encoder died"))
        svc = _build_service(store, pipeline=pipeline)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        with pytest.raises(RecordingPipelineFailureError):
            svc.start_job(job.job_id)
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# finalize_job
# ---------------------------------------------------------------------------


class TestFinalizeJob:
    def _recording(
        self,
        store: RecordingStore,
        *,
        pipeline: StubCapturePipeline | None = None,
        finalizer: StubFinalizer | None = None,
        loudness_regime: str = "atsc-a85",
    ):
        sched = _schedule(
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
            loudness_regime=loudness_regime,
        )
        store.upsert_schedule(sched)
        pipeline = pipeline or StubCapturePipeline()
        finalizer = finalizer or StubFinalizer()
        svc = _build_service(store, pipeline=pipeline, finalizer=finalizer)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        svc.start_job(job.job_id)
        return svc, pipeline, finalizer, job

    def test_happy_path_transitions_to_done_with_asset_id(self, store: RecordingStore):
        svc, pipeline, finalizer, job = self._recording(store)
        result = svc.finalize_job(job.job_id)
        assert result.state == "done"
        assert result.asset_id == "asset-1"
        assert result.bytes_written > 0
        assert pipeline.finalize_calls == [job.job_id]
        assert len(finalizer.calls) == 1

    def test_loudness_regime_flows_to_finalizer(self, store: RecordingStore):
        svc, _, finalizer, job = self._recording(store, loudness_regime="ebu-r128")
        # The finalizer doesn't receive loudness_regime directly (it lives in
        # the engine's mux), but the asset's custom fields + the captured
        # bytes propagate. We check custom_field_values pass through.
        svc.finalize_job(job.job_id)
        assert finalizer.calls[0]["custom_field_values"] == {"committee": "council"}
        # And we re-fetch the job to confirm regime stayed put in the DB.
        stored = store.get_job(job.job_id)
        assert stored is not None and stored.loudness_regime == "ebu-r128"

    def test_target_series_and_sha_pass_to_finalizer(self, store: RecordingStore):
        svc, _, finalizer, job = self._recording(store)
        svc.finalize_job(job.job_id)
        call = finalizer.calls[0]
        assert call["target_series"] == "council"
        assert call["sha256"] == "a" * 64

    def test_pipeline_raise_during_finalize_fails(self, store: RecordingStore):
        pipeline = StubCapturePipeline(raise_on_finalize=RuntimeError("torn capture"))
        svc, _, _, job = self._recording(store, pipeline=pipeline)
        with pytest.raises(RecordingPipelineFailureError):
            svc.finalize_job(job.job_id)
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]

    def test_finalizer_raise_fails_job(self, store: RecordingStore):
        finalizer = StubFinalizer(raise_on_finalize=RuntimeError("ingest pipeline busy"))
        svc, _, _, job = self._recording(store, finalizer=finalizer)
        with pytest.raises(RecordingPipelineFailureError):
            svc.finalize_job(job.job_id)
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]

    def test_wrong_state_raises(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store, pipeline=StubCapturePipeline(), finalizer=StubFinalizer())
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingJobStateError):
            svc.finalize_job(job.job_id)


# ---------------------------------------------------------------------------
# stop_job
# ---------------------------------------------------------------------------


class TestStopJob:
    def _recording(
        self,
        store: RecordingStore,
        *,
        pipeline: StubCapturePipeline | None = None,
        finalizer: StubFinalizer | None = None,
    ):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = pipeline or StubCapturePipeline()
        finalizer = finalizer or StubFinalizer()
        svc = _build_service(store, pipeline=pipeline, finalizer=finalizer)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        svc.start_job(job.job_id)
        return svc, pipeline, finalizer, job

    def test_happy_path_partial_done(self, store: RecordingStore):
        svc, pipeline, _finalizer, job = self._recording(store)
        result = svc.stop_job(job.job_id)
        assert result.state == "done"
        assert result.bytes_written == 524_288
        assert result.asset_id == "asset-1"
        assert pipeline.stop_calls == [job.job_id]

    def test_zero_bytes_landing_is_failed(self, store: RecordingStore):
        pipeline = StubCapturePipeline(
            stop_result=CaptureResult(bytes_written=0, capture_path="/tmp/empty.ts")
        )
        svc, _, _, job = self._recording(store, pipeline=pipeline)
        result = svc.stop_job(job.job_id)
        assert result.state == "failed"
        assert result.bytes_written == 0

    def test_stop_against_terminal_raises_state_error(self, store: RecordingStore):
        svc, _, _, job = self._recording(store)
        svc.stop_job(job.job_id)  # → done
        with pytest.raises(RecordingJobStateError):
            svc.stop_job(job.job_id)

    def test_stop_against_scheduled_raises_state_error(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store, pipeline=StubCapturePipeline(), finalizer=StubFinalizer())
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingJobStateError):
            svc.stop_job(job.job_id)

    def test_stop_pipeline_raise_fails(self, store: RecordingStore):
        pipeline = StubCapturePipeline(raise_on_stop=RuntimeError("oh no"))
        svc, _, _, job = self._recording(store, pipeline=pipeline)
        result = svc.stop_job(job.job_id)
        assert result.state == "failed"
        assert result.failure_reason
        assert "Recording could not complete the stop step" in result.failure_reason
        assert "RuntimeError" not in result.failure_reason
        assert store.get_job(job.job_id).state == "failed"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# record_now / record_now_from_source
# ---------------------------------------------------------------------------


class TestRecordNow:
    def test_happy_path_arm_and_start(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(days=7)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        svc = _build_service(store, pipeline=pipeline, finalizer=finalizer)
        job = svc.record_now(sched.schedule_id)
        assert job.state == "recording"
        assert job.schedule_id == sched.schedule_id
        # Same state machine: arm + start were both called once each.
        assert len(pipeline.arm_calls) == 1
        assert len(pipeline.start_calls) == 1

    def test_missing_schedule_raises(self, store: RecordingStore):
        svc = _build_service(store, pipeline=StubCapturePipeline())
        with pytest.raises(RecordingScheduleNotFoundError):
            svc.record_now("nope")

    def test_unwired_pipeline_raises(self, store: RecordingStore):
        sched = _schedule()
        store.upsert_schedule(sched)
        svc = _build_service(store)
        with pytest.raises(RecordingPipelineUnwiredError):
            svc.record_now(sched.schedule_id)

    def test_record_now_then_finalize_produces_asset(self, store: RecordingStore):
        sched = _schedule()
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        svc = _build_service(store, pipeline=pipeline, finalizer=finalizer)
        job = svc.record_now(sched.schedule_id)
        done = svc.finalize_job(job.job_id)
        assert done.state == "done"
        assert done.asset_id == "asset-1"

    def test_record_now_from_source_does_not_require_schedule(self, store: RecordingStore):
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline)
        job = svc.record_now_from_source(
            station_id=_STATION,
            source=_src("srt", uri="srt://camera.local:9000"),
            duration_seconds=1800,
            encoder_profile="hw-h264-720p",
            loudness_regime="ebu-r128",
            target_series="planning",
        )
        assert job.state == "recording"
        assert job.schedule_id is None
        assert job.target_series == "planning"
        assert pipeline.arm_calls[0]["loudness_regime"] == "ebu-r128"

    def test_record_now_skipped_on_overlap_short_circuits(self, store: RecordingStore):
        # First record_now succeeds; second on same source is overlap-skipped.
        sched = _schedule()
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline, alert_sink=StubAlertSink())
        first = svc.record_now(sched.schedule_id)
        assert first.state == "recording"
        # Second record_now (same schedule, same source) — overlap at arm.
        second = svc.record_now(sched.schedule_id)
        assert second.state == "skipped"


# ---------------------------------------------------------------------------
# reconcile_orphans
# ---------------------------------------------------------------------------


class TestReconcileOrphans:
    def test_stale_recording_past_planned_end_fails(self, store: RecordingStore):
        # Create a job that ended an hour ago but is still "recording".
        past_start = _FROZEN_NOW - timedelta(hours=3)
        past_end = _FROZEN_NOW - timedelta(hours=2)
        job = RecordingJob(
            job_id="zombie-1",
            station_id=_STATION,
            schedule_id=None,
            planned_start=past_start,
            planned_end=past_end,
            state="scheduled",  # we'll move it forward via the store
            source_snapshot=_src(),
            encoder_profile="hw-h264-1080p",
        )
        store.create_job(job)
        store.set_job_state("zombie-1", "arming")
        store.set_job_state("zombie-1", "recording")
        svc = _build_service(store)
        count = svc.reconcile_orphans()
        assert count == 1
        assert store.get_job("zombie-1").state == "failed"  # type: ignore[union-attr]

    def test_in_window_recording_left_alone(self, store: RecordingStore):
        # planned_end is in the future — do not touch.
        future_end = _FROZEN_NOW + timedelta(hours=1)
        job = RecordingJob(
            job_id="live-1",
            station_id=_STATION,
            schedule_id=None,
            planned_start=_FROZEN_NOW - timedelta(minutes=10),
            planned_end=future_end,
            state="scheduled",
            source_snapshot=_src(),
            encoder_profile="hw-h264-1080p",
        )
        store.create_job(job)
        store.set_job_state("live-1", "arming")
        store.set_job_state("live-1", "recording")
        svc = _build_service(store)
        count = svc.reconcile_orphans()
        assert count == 0
        assert store.get_job("live-1").state == "recording"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------


class TestTick:
    def test_expand_and_arm_imminent(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(seconds=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline, arm_lead=timedelta(seconds=30))
        counters = svc.tick(_STATION, horizon=timedelta(hours=1))
        # E-14 fix: counters are now a typed TickCounters model (attribute
        # access) — pre-fix this was a raw dict.
        assert counters.expanded == 1
        assert counters.armed == 1
        # planned_start is in the future, so start_job not called yet.
        assert counters.started == 0

    def test_does_not_arm_jobs_beyond_arm_lead(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline, arm_lead=timedelta(seconds=30))
        counters = svc.tick(_STATION, horizon=timedelta(hours=1))
        assert counters.expanded == 1
        assert counters.armed == 0

    def test_starts_job_when_planned_start_in_the_past(self, store: RecordingStore):
        # planned_start = exactly now -> arm and start.
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline, arm_lead=timedelta(seconds=30))
        counters = svc.tick(_STATION, horizon=timedelta(hours=1))
        assert counters.armed == 1
        assert counters.started == 1
        assert counters.finalized == 0

    def test_tick_finalizes_record_now_after_planned_end(self, store: RecordingStore):
        now = _FROZEN_NOW
        sched = _schedule(
            recurrence=_oneshot(_FROZEN_NOW + timedelta(hours=10)),
            duration_seconds=60,
        )
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        svc = _build_service(
            store,
            pipeline=pipeline,
            finalizer=finalizer,
            clock=lambda: now,
            arm_lead=timedelta(seconds=30),
        )
        job = svc.record_now(sched.schedule_id)
        assert job.state == "recording"

        now = job.planned_end + timedelta(seconds=1)
        counters = svc.tick(_STATION, horizon=timedelta(seconds=1))

        done = store.get_job(job.job_id)
        assert counters.finalized == 1
        assert counters.failed == 0
        assert done is not None
        assert done.state == "done"
        assert done.ended_at == now
        assert done.asset_id
        assert pipeline.finalize_calls == [job.job_id]
        assert len(finalizer.calls) == 1

    def test_tick_leaves_in_window_record_now_recording(self, store: RecordingStore):
        now = _FROZEN_NOW
        sched = _schedule(
            recurrence=_oneshot(_FROZEN_NOW + timedelta(hours=10)),
            duration_seconds=60,
        )
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        svc = _build_service(
            store,
            pipeline=pipeline,
            finalizer=finalizer,
            clock=lambda: now,
            arm_lead=timedelta(seconds=30),
        )
        job = svc.record_now(sched.schedule_id)

        now = job.planned_end - timedelta(seconds=1)
        counters = svc.tick(_STATION, horizon=timedelta(seconds=1))

        active = store.get_job(job.job_id)
        assert counters.finalized == 0
        assert active is not None
        assert active.state == "recording"
        assert pipeline.finalize_calls == []
        assert finalizer.calls == []

    def test_overlap_at_tick_counts_as_skipped(self, store: RecordingStore):
        sched_a = _schedule(
            schedule_id="sch-a", recurrence=_oneshot(_FROZEN_NOW + timedelta(seconds=10))
        )
        sched_b = _schedule(
            schedule_id="sch-b",
            name="Other",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(seconds=15)),
        )
        store.upsert_schedule(sched_a)
        store.upsert_schedule(sched_b)
        svc = _build_service(
            store,
            pipeline=StubCapturePipeline(),
            alert_sink=StubAlertSink(),
            arm_lead=timedelta(seconds=30),
        )
        counters = svc.tick(_STATION, horizon=timedelta(hours=1))
        assert counters.armed == 1
        assert counters.skipped == 1


# ---------------------------------------------------------------------------
# E-1 — _job_id_for must produce distinct ids for sch_a vs sch-a (slug parity)
# ---------------------------------------------------------------------------


class TestE1JobIdSlugMismatch:
    def test_expand_produces_distinct_jobs_for_underscore_and_dash(self, store: RecordingStore):
        # Two schedules whose ids differ only by ``_`` vs ``-`` — pre-fix
        # the materializer's deterministic job_id collapsed them and
        # ``create_job`` raised an uncaught IntegrityError on the second
        # one. Post-fix both schedules materialize to distinct job ids
        # so the expand pass completes successfully.
        a = _schedule(
            schedule_id="sch_a",
            name="A",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
        )
        b = _schedule(
            schedule_id="sch-a",
            name="B",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
        )
        store.upsert_schedule(a)
        store.upsert_schedule(b)
        svc = _build_service(store)
        created = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        ids = {job.job_id for job in created}
        # Distinct job ids — no collision.
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# E-4 — stop_job from arming does NOT call pipeline.stop without a start
# ---------------------------------------------------------------------------


class TestE4StopFromArming:
    def _arming(self, store: RecordingStore, *, pipeline=None):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = pipeline or StubCapturePipeline()
        finalizer = StubFinalizer()
        svc = _build_service(store, pipeline=pipeline, finalizer=finalizer)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)  # → arming, no start
        return svc, pipeline, job

    def test_stop_from_arming_does_not_call_pipeline_stop(self, store: RecordingStore):
        svc, pipeline, job = self._arming(store)
        result = svc.stop_job(job.job_id)
        # pre-fix: pipeline.stop was called → "stop without start" UB.
        # post-fix: we never call pipeline.stop on an arming-state job.
        assert pipeline.stop_calls == []
        assert pipeline.start_calls == []
        assert result.state == "failed"
        assert result.failure_reason and "before recording started" in result.failure_reason

    def test_stop_from_arming_calls_stop_arming_hook_if_present(self, store: RecordingStore):
        class StubPipelineWithArmingHook(StubCapturePipeline):
            def __init__(self) -> None:
                super().__init__()
                self.stop_arming_calls: list[str] = []

            def stop_arming(self, job_id: str) -> None:
                self.stop_arming_calls.append(job_id)

        pipeline = StubPipelineWithArmingHook()
        svc, _, job = self._arming(store, pipeline=pipeline)
        svc.stop_job(job.job_id)
        assert pipeline.stop_arming_calls == [job.job_id]
        # pipeline.stop still untouched.
        assert pipeline.stop_calls == []

    def test_stop_from_recording_still_calls_pipeline_stop(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline()
        svc = _build_service(store, pipeline=pipeline, finalizer=StubFinalizer())
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        svc.start_job(job.job_id)
        svc.stop_job(job.job_id)
        # Recording path is unchanged.
        assert pipeline.stop_calls == [job.job_id]


# ---------------------------------------------------------------------------
# E-5 — explicit max_jobs_per_tick cap, warn + alert when exceeded
# ---------------------------------------------------------------------------


class TestE5MaxJobsPerTickCap:
    def test_cap_emits_warning_and_alert(self, store: RecordingStore):
        # Cap at a tiny value so 1 historical job triggers the cap path.
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        alert = StubAlertSink()
        svc = RecordingService(
            store,
            capture_pipeline=StubCapturePipeline(),
            alert_sink=alert,
            clock=_frozen_clock(),
            max_jobs_per_tick=1,
        )
        # Materialize once — that creates a job.
        svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        # Now there's >= 1 existing job; the next expand hits the cap.
        # We don't need a second schedule — just re-run.
        svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        # The expand cap warning fired.
        assert any(e.get("source") == "recording.expand" for e in alert.emits)


# ---------------------------------------------------------------------------
# E-9 — alert log level by severity when sink is None
# ---------------------------------------------------------------------------


class TestE9AlertLogLevel:
    def test_critical_alert_without_sink_logs_at_error_level(self, store: RecordingStore, caplog):
        import logging

        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("boom"))
        # NO alert sink → log-only path.
        svc = _build_service(store, pipeline=pipeline)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with (
            caplog.at_level(logging.ERROR, logger="civiccast.recording.service"),
            pytest.raises(RecordingPipelineFailureError),
        ):
            svc.arm_job(job.job_id)
        # The "(no sink)" critical alert message landed at ERROR.
        critical_records = [
            r
            for r in caplog.records
            if "recording.alert (no sink)" in r.getMessage() and r.levelno >= logging.ERROR
        ]
        assert critical_records, (
            "Expected the critical no-sink alert to log at ERROR level "
            "(E-9 fix); got nothing at ERROR."
        )


# ---------------------------------------------------------------------------
# E-11 — disabling a schedule cancels its still-scheduled jobs
# ---------------------------------------------------------------------------


class TestE11CancelScheduledOnDisable:
    def test_cancel_scheduled_jobs_for_schedule_skips_pending(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        svc = _build_service(store)
        # Materialize one scheduled job.
        jobs = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        assert len(jobs) == 1
        # Now cancel.
        n = svc.cancel_scheduled_jobs_for_schedule(sched.schedule_id)
        assert n == 1
        cancelled = store.get_job(jobs[0].job_id)
        assert cancelled is not None
        assert cancelled.state == "skipped"
        assert (cancelled.failure_reason or "").startswith("schedule disabled")

    def test_cancel_unknown_schedule_returns_zero(self, store: RecordingStore):
        svc = _build_service(store)
        assert svc.cancel_scheduled_jobs_for_schedule("nope") == 0


# ---------------------------------------------------------------------------
# T-2 — DC-3 alert payload carries the full context (job_id, schedule_id,
# station_id, phase, exception_type) AND a routable message/source
# ---------------------------------------------------------------------------


class TestT2AlertPayloadDepth:
    def test_arm_fail_alert_payload_complete(self, store: RecordingStore):
        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("source unreachable"))
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        with pytest.raises(RecordingPipelineFailureError):
            svc.arm_job(job.job_id)
        assert alert.emits
        emit = alert.emits[0]
        # Severity + source = routing target.
        assert emit["severity"] == "critical"
        assert emit["source"] == "recording.arm"
        # Message names the failure.
        assert "Recording job failed" in emit["message"]
        # Context: every field on-call needs to acknowledge / route.
        ctx = emit["context"]
        assert ctx["job_id"] == job.job_id
        assert ctx["schedule_id"] == sched.schedule_id
        assert ctx["station_id"] == _STATION
        assert ctx["phase"] == "arm"
        assert ctx["exception_type"] == "RuntimeError"

    def test_overlap_alert_payload_complete(self, store: RecordingStore):
        a = _schedule(
            schedule_id="sch-a",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)),
        )
        b = _schedule(
            schedule_id="sch-b",
            name="Other",
            recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=15)),
        )
        store.upsert_schedule(a)
        store.upsert_schedule(b)
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=StubCapturePipeline(), alert_sink=alert)
        ja, jb = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
        svc.arm_job(ja.job_id)
        svc.arm_job(jb.job_id)
        overlap_emits = [e for e in alert.emits if e["source"] == "recording.overlap"]
        assert overlap_emits
        emit = overlap_emits[0]
        assert emit["severity"] == "warning"
        ctx = emit["context"]
        assert ctx["job_id"] == jb.job_id
        assert ctx["schedule_id"] == jb.schedule_id
        assert ctx["station_id"] == _STATION
        assert ctx["conflicting_job_id"] == ja.job_id


# ---------------------------------------------------------------------------
# T-4 — DC-5 disk-full end-to-end
# ---------------------------------------------------------------------------


class TestT4DiskFullEndToEnd:
    def test_disk_full_at_start_fails_with_alert(self, store: RecordingStore):
        # ENOSPC = errno 28 "No space left on device" — the canonical
        # disk-full signal the engine would raise as an OSError.
        import errno

        sched = _schedule(recurrence=_oneshot(_FROZEN_NOW + timedelta(minutes=10)))
        store.upsert_schedule(sched)
        pipeline = StubCapturePipeline(
            raise_on_start=OSError(errno.ENOSPC, "No space left on device"),
        )
        alert = StubAlertSink()
        svc = _build_service(store, pipeline=pipeline, alert_sink=alert)
        job = svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))[0]
        svc.arm_job(job.job_id)
        with pytest.raises(RecordingPipelineFailureError):
            svc.start_job(job.job_id)
        failed = store.get_job(job.job_id)
        assert failed is not None
        assert failed.state == "failed"
        # The alert payload identifies the OSError type so on-call can
        # distinguish disk-full from other start-phase failures.
        assert alert.emits
        ctx = alert.emits[0]["context"]
        assert ctx["exception_type"] == "OSError"
        assert ctx["phase"] == "start"


# ---------------------------------------------------------------------------
# T-10 — idempotent expand under partial-overlap horizon (cursor advances)
# ---------------------------------------------------------------------------


class TestT10IdempotencyPartialOverlap:
    def test_advancing_clock_only_materializes_the_new_day(self, store: RecordingStore):
        # Weekly Mon-Sun schedule. First expand at day N materializes 7
        # jobs (days N..N+6). Second expand at day N+1 should ONLY
        # materialize day N+7 — the prior six days were already done.
        sched = _schedule(
            schedule_id="sch-week",
            recurrence=_weekly([0, 1, 2, 3, 4, 5, 6], "13:00"),
        )
        store.upsert_schedule(sched)
        svc_day1 = _build_service(store)
        first = svc_day1.expand_jobs_for_horizon(_STATION, timedelta(days=7))
        assert len(first) == 7
        # Advance clock by 24h and re-expand.
        svc_day2 = _build_service(store, clock=_frozen_clock(_FROZEN_NOW + timedelta(days=1)))
        second = svc_day2.expand_jobs_for_horizon(_STATION, timedelta(days=7))
        # Only one new day enters the horizon; the previously-materialized
        # six days are skipped via the (schedule_id, planned_start) probe.
        assert len(second) == 1
