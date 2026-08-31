# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 1 (deferred from PR #100): the shutdown drain for in-flight recordings.

``_app_lifespan``'s ``finally`` block drains the egress daemon
(``stop_all_channels(deadline_seconds=...)``) but, before this fix, did NOT
drain in-flight ``RecordingService`` jobs — a shutdown mid-recording was torn
down by process exit instead of a graceful stop that produces a valid asset.

These tests prove the gap and the fix at the service layer:

* a recording job in flight at shutdown is finalized to a real asset
  (``done`` + a finalizer call) rather than left orphaned;
* the deadline is honoured (a zero budget drains nothing and leaves the jobs
  for the next boot's ``reconcile_orphans``, i.e. never worse than today);
* a per-job stop that raises is caught and counted, never aborting the drain;
* the drain runs through the capture pipeline's per-job lock and so does NOT
  deadlock a concurrently-running scheduler poll thread, and produces exactly
  one uncorrupted asset when it races that thread.

The lifespan wiring itself is covered in ``tests/test_app_lifespan_drain_all.py``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.live.models import RecordingTarget
from civiccast.recording.models import (
    RecordingSchedule,
    RecordingSource,
    RecurrenceSpec,
)
from civiccast.recording.runtime import (
    FfmpegScheduledCapturePipeline,
    ScheduledRecordingAssetFinalizer,
    ScheduledRecordingSettings,
)
from civiccast.recording.service import (
    CaptureResult,
    RecordingDrainResult,
    RecordingService,
)
from civiccast.recording.store import RecordingStore
from civiccast.schedule.ingest import FfprobeResult

_STATION = "civiccast-station"
_NOW = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Stubs (mirror tests/recording/test_service.py's shape)
# ---------------------------------------------------------------------------


class _StubPipeline:
    """Records stop calls; a job is 'live' once armed/started."""

    def __init__(self, *, raise_on_stop: BaseException | None = None) -> None:
        self.live: set[str] = set()
        self.stop_calls: list[str] = []
        self._raise_stop = raise_on_stop

    def arm(self, *, job_id, source, encoder_profile, loudness_regime) -> None:
        self.live.add(job_id)

    def start(self, job_id) -> None:
        pass

    def finalize(self, job_id) -> CaptureResult:
        return self.stop(job_id)

    def stop(self, job_id) -> CaptureResult:
        self.stop_calls.append(job_id)
        if self._raise_stop is not None:
            raise self._raise_stop
        self.live.discard(job_id)
        return CaptureResult(
            bytes_written=524_288,
            capture_path=f"/var/lib/civiccast/captures/{job_id}-partial.ts",
            sha256=None,
        )


class _StubFinalizer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def finalize_to_asset(
        self, *, station_id, capture_path, target_series, custom_field_values, sha256
    ) -> str:
        self.calls.append(capture_path)
        return f"asset-{len(self.calls)}"


@contextmanager
def _factory_for(engine) -> Iterator[Session]:
    with Session(bind=engine) as session:
        yield session


def _make_store(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'drain.db'}")
    Base.metadata.create_all(engine)

    def factory():
        return _factory_for(engine)

    return engine, factory, RecordingStore(factory)


def _frozen_clock():
    def _now() -> datetime:
        return _NOW

    return _now


def _schedule(schedule_id: str) -> RecordingSchedule:
    return RecordingSchedule(
        schedule_id=schedule_id,
        station_id=_STATION,
        name=f"Schedule {schedule_id}",
        source=RecordingSource(kind="rtsp", uri=f"rtsp://example.test/{schedule_id}"),
        recurrence=RecurrenceSpec(kind="one_shot", start=_NOW + timedelta(minutes=5)),
        duration_seconds=3600,
        encoder_profile="hw-h264-1080p",
        loudness_regime="atsc-a85",
        target_series="council",
        custom_field_values={},
        enabled=True,
    )


# ---------------------------------------------------------------------------
# Service-layer drain behaviour
# ---------------------------------------------------------------------------


def test_drain_finalizes_an_in_flight_recording_to_a_real_asset(tmp_path: Path) -> None:
    """The gap PR #100 deferred: a recording in flight at shutdown must be
    stopped-and-finalized to a real asset, not left orphaned to the next
    boot's reconcile."""
    engine, _factory, store = _make_store(tmp_path)
    try:
        pipeline = _StubPipeline()
        finalizer = _StubFinalizer()
        svc = RecordingService(
            store,
            capture_pipeline=pipeline,
            asset_finalizer=finalizer,
            clock=_frozen_clock(),
        )
        store.upsert_schedule(_schedule("sch-1"))
        job = svc.record_now("sch-1")
        assert job.state == "recording"

        result = svc.drain_in_flight(_STATION, deadline_seconds=15.0)

        assert result == RecordingDrainResult(considered=1, finalized=1, failed=0, not_drained=0)
        assert pipeline.stop_calls == [job.job_id]
        assert len(finalizer.calls) == 1
        drained = store.get_job(job.job_id)
        assert drained is not None
        assert drained.state == "done"
        assert drained.asset_id == "asset-1"
    finally:
        engine.dispose()


def test_drain_zero_deadline_drains_nothing_and_is_never_worse_than_today(
    tmp_path: Path,
) -> None:
    """A zero budget must not touch any job — they stay ``recording`` for the
    next boot's reconcile_orphans, exactly the pre-drain behaviour."""
    engine, _factory, store = _make_store(tmp_path)
    try:
        pipeline = _StubPipeline()
        finalizer = _StubFinalizer()
        svc = RecordingService(
            store,
            capture_pipeline=pipeline,
            asset_finalizer=finalizer,
            clock=_frozen_clock(),
        )
        store.upsert_schedule(_schedule("sch-1"))
        job = svc.record_now("sch-1")

        result = svc.drain_in_flight(_STATION, deadline_seconds=0.0)

        assert result == RecordingDrainResult(considered=1, finalized=0, failed=0, not_drained=1)
        assert pipeline.stop_calls == []
        still = store.get_job(job.job_id)
        assert still is not None
        assert still.state == "recording"
    finally:
        engine.dispose()


def test_drain_deadline_is_checked_between_jobs(tmp_path: Path) -> None:
    """With two in-flight jobs and a monotonic clock that jumps past the
    deadline after the first stop, the second job is left ``not_drained`` —
    proving the budget bounds how many jobs are drained."""
    engine, _factory, store = _make_store(tmp_path)
    try:
        pipeline = _StubPipeline()
        finalizer = _StubFinalizer()
        svc = RecordingService(
            store,
            capture_pipeline=pipeline,
            asset_finalizer=finalizer,
            clock=_frozen_clock(),
        )
        store.upsert_schedule(_schedule("sch-a"))
        store.upsert_schedule(_schedule("sch-b"))
        svc.record_now("sch-a")
        svc.record_now("sch-b")

        # 0.0 (start), 0.5 (before job#1, under deadline 1.0), 5.0 (before
        # job#2, over deadline) -> exactly one job drained.
        ticks = iter([0.0, 0.5, 5.0])
        result = svc.drain_in_flight(_STATION, deadline_seconds=1.0, monotonic=lambda: next(ticks))

        assert result.considered == 2
        assert result.finalized == 1
        assert result.not_drained == 1
        assert len(pipeline.stop_calls) == 1
    finally:
        engine.dispose()


def test_drain_counts_a_raising_stop_as_failed_and_keeps_going(tmp_path: Path) -> None:
    """A per-job stop that raises (e.g. a concurrent poll-thread finalize
    already drove the job terminal) must be caught and counted, never abort
    the drain or block shutdown."""
    engine, _factory, store = _make_store(tmp_path)
    try:
        pipeline = _StubPipeline(raise_on_stop=RuntimeError("stop boom"))
        finalizer = _StubFinalizer()
        svc = RecordingService(
            store,
            capture_pipeline=pipeline,
            asset_finalizer=finalizer,
            clock=_frozen_clock(),
        )
        store.upsert_schedule(_schedule("sch-1"))
        svc.record_now("sch-1")

        result = svc.drain_in_flight(_STATION, deadline_seconds=15.0)

        # stop_job catches the pipeline raise, transitions the job to failed,
        # and re-raises RecordingPipelineFailureError, which the drain catches.
        assert result.considered == 1
        assert result.finalized == 0
        assert result.failed == 1
        assert result.not_drained == 0
    finally:
        engine.dispose()


def test_drain_no_in_flight_jobs_is_all_zeros(tmp_path: Path) -> None:
    engine, _factory, store = _make_store(tmp_path)
    try:
        svc = RecordingService(
            store,
            capture_pipeline=_StubPipeline(),
            asset_finalizer=_StubFinalizer(),
            clock=_frozen_clock(),
        )
        result = svc.drain_in_flight(_STATION, deadline_seconds=15.0)
        assert result == RecordingDrainResult(considered=0, finalized=0, failed=0, not_drained=0)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# _job_lock: the drain must not race / deadlock the scheduler poll thread
# ---------------------------------------------------------------------------


class _ScriptedHandle:
    """A fake ffmpeg child (mirrors test_dropout_detection) writing a real,
    growing file so the REAL FfmpegScheduledCapturePipeline.stop() concat/stat
    path runs against real bytes."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.returncode: int | None = None
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"x" * 4096)

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def close(self) -> None:
        return None


def _make_capture_store_and_target(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cap.db'}")
    Base.metadata.create_all(engine)

    def factory():
        return _factory_for(engine)

    with factory() as session:
        session.add(
            RecordingTarget(
                recording_target_id="local",
                name="Local recordings",
                target_uri=(tmp_path / "recordings").as_uri(),
                created_at=_NOW,
            )
        )
        session.commit()
    return engine, factory


def test_drain_stop_does_not_deadlock_a_concurrent_check_dropout(tmp_path: Path) -> None:
    """The real capture pipeline's per-job lock serializes the drain's stop()
    against the scheduler poll thread's check_dropout(): the two must not
    deadlock, and exactly one uncorrupted asset must result. This is the seam
    the shutdown drain relies on to be safe against the still-live poll
    thread."""
    engine, factory = _make_capture_store_and_target(tmp_path)
    try:

        def fake_start_ffmpeg(args, **_kwargs) -> _ScriptedHandle:
            return _ScriptedHandle(Path(args[-1]))

        pipeline = FfmpegScheduledCapturePipeline(
            factory,
            settings=ScheduledRecordingSettings(mode="off"),
            ffmpeg_starter=fake_start_ffmpeg,
        )
        source = RecordingSource(kind="rtsp", uri="rtsp://example.test/cam1")
        pipeline.arm(
            job_id="job-1", source=source, encoder_profile="copy", loudness_regime="inherit"
        )
        pipeline.start("job-1")

        errors: list[BaseException] = []
        stop_result: list[CaptureResult] = []
        barrier = threading.Barrier(2)

        def _poll() -> None:
            try:
                barrier.wait(timeout=5)
                # Hammer check_dropout while the drain stop() runs; the alive
                # handle keeps growing so no reconnect fires — this exercises
                # the lock contention, not the dropout path.
                for _ in range(200):
                    pipeline.check_dropout("job-1")
            except BaseException as exc:
                errors.append(exc)

        def _drain() -> None:
            try:
                barrier.wait(timeout=5)
                stop_result.append(pipeline.stop("job-1"))
            except BaseException as exc:
                errors.append(exc)

        poll_thread = threading.Thread(target=_poll)
        drain_thread = threading.Thread(target=_drain)
        poll_thread.start()
        drain_thread.start()
        poll_thread.join(timeout=15)
        drain_thread.join(timeout=15)

        assert not poll_thread.is_alive(), "poll thread hung — possible deadlock"
        assert not drain_thread.is_alive(), "drain thread hung — possible deadlock"
        assert errors == []
        # stop() won the job once; the capture file exists and is non-empty.
        assert len(stop_result) == 1
        assert stop_result[0].bytes_written > 0
        assert Path(stop_result[0].capture_path).stat().st_size > 0
    finally:
        engine.dispose()


def test_drain_finalizes_through_real_finalizer(tmp_path: Path, monkeypatch) -> None:
    """End-to-end at the service layer with the REAL capture pipeline + REAL
    asset finalizer (ffprobe faked): a mid-recording drain yields a valid,
    finalized asset row — the concrete proof the deferred gap is closed."""
    engine, factory = _make_capture_store_and_target(tmp_path)
    try:
        from civiccast.recording import runtime as runtime_mod

        def _fake_ffprobe(_path: Path) -> FfprobeResult:
            return FfprobeResult(
                duration_seconds=30,
                codec_video="h264",
                codec_audio="aac",
                width_px=1920,
                height_px=1080,
                bitrate_bps=4_000_000,
                format_name="mpegts",
            )

        monkeypatch.setattr(runtime_mod, "run_ffprobe", _fake_ffprobe)
        monkeypatch.setattr(runtime_mod, "validate_ingest", lambda _probe: None)

        def fake_start_ffmpeg(args, **_kwargs) -> _ScriptedHandle:
            return _ScriptedHandle(Path(args[-1]))

        pipeline = FfmpegScheduledCapturePipeline(
            factory,
            settings=ScheduledRecordingSettings(mode="off"),
            ffmpeg_starter=fake_start_ffmpeg,
        )
        store = RecordingStore(factory)
        svc = RecordingService(
            store,
            capture_pipeline=pipeline,
            asset_finalizer=ScheduledRecordingAssetFinalizer(factory),
            clock=_frozen_clock(),
        )
        store.upsert_schedule(_schedule("sch-1"))
        job = svc.record_now("sch-1")
        assert job.state == "recording"

        result = svc.drain_in_flight(_STATION, deadline_seconds=15.0)

        assert result.considered == 1
        assert result.finalized == 1
        drained = store.get_job(job.job_id)
        assert drained is not None
        assert drained.state == "done"
        assert drained.asset_id is not None
    finally:
        engine.dispose()
