# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Production wiring tests for scheduled recording.

These pin the beta-readiness gap where the app factory exposed scheduled
recording routes but constructed ``RecordingService`` without its capture,
asset-finalizer, and alert seams.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base, reset_engine
from civiccast.live.models import RecordingTarget
from civiccast.live.recording_paths import (
    DEFAULT_RECORDING_TARGET_DIR_NAME,
    DEFAULT_RECORDING_TARGET_ID,
    REHEARSAL_RECORDING_TARGET_ID,
)
from civiccast.live.router import get_recording_target_store
from civiccast.recording.models import (
    RecordingJob,
    RecordingSchedule,
    RecordingSource,
    RecurrenceSpec,
)
from civiccast.recording.router import get_recording_input_catalog, get_recording_service
from civiccast.recording.runtime import (
    FfmpegScheduledCapturePipeline,
    RecordingAlertSink,
    ScheduledRecordingAssetFinalizer,
    ScheduledRecordingSettings,
    ScheduledRecordingWorker,
)
from civiccast.recording.service import RecordingService
from civiccast.recording.store import RecordingStore
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import Asset

_NOW = datetime(2026, 6, 23, 17, 0, tzinfo=UTC)


def _quiet_unrelated_workers(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_RETENTION_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_WEBHOOK_RETRY", "off")
    monkeypatch.setenv("CIVICCAST_PROGRAM_LOG", "off")
    monkeypatch.setenv("CIVICCAST_AUTOSCHEDULE", "off")
    monkeypatch.setenv("CIVICCAST_ALERTING", "off")
    monkeypatch.setenv("CIVICCAST_BULLETIN_EXPIRY", "off")


def _scheduled_supervisor(app):
    return next(
        supervisor
        for supervisor in app.state.background_supervisors
        if getattr(supervisor, "_name", None) == "civiccast-scheduled-recording"
    )


def test_create_app_wires_scheduled_recording_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_RETENTION_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_WEBHOOK_RETRY", "off")
    monkeypatch.setenv("CIVICCAST_PROGRAM_LOG", "off")
    monkeypatch.setenv("CIVICCAST_AUTOSCHEDULE", "off")
    monkeypatch.setenv("CIVICCAST_ALERTING", "off")
    monkeypatch.setenv("CIVICCAST_BULLETIN_EXPIRY", "off")
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING", "off")
    # State/lock/upload roots are redirected by the autouse hermetic fixture in
    # tests/conftest.py, which also fails this test if it touches real state.

    from civiccast.app import create_app

    app = create_app()
    service = app.dependency_overrides[get_recording_service]()
    catalog = app.dependency_overrides[get_recording_input_catalog]()

    assert isinstance(service, RecordingService)
    assert isinstance(service._pipeline, FfmpegScheduledCapturePipeline)
    assert service._pipeline._hardware_input_args_resolver == catalog.resolve_args
    assert isinstance(service._finalizer, ScheduledRecordingAssetFinalizer)
    assert isinstance(service._alert_sink, RecordingAlertSink)
    assert app.state.scheduled_recording_worker is not None
    scheduled = _scheduled_supervisor(app)
    assert scheduled.running is False


def test_scheduled_recording_worker_starts_with_app_lifespan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    _quiet_unrelated_workers(monkeypatch)
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING", "inline")
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING_POLL_SECONDS", "0.01")

    started = threading.Event()

    def fake_run_forever(self, *, poll_seconds: float, stop_event: threading.Event) -> None:
        started.set()
        stop_event.wait(5)

    monkeypatch.setattr(ScheduledRecordingWorker, "run_forever", fake_run_forever)

    from civiccast.app import create_app

    app = create_app()
    scheduled = _scheduled_supervisor(app)
    with TestClient(app):
        assert started.wait(2)
        assert scheduled.running is True
    assert scheduled.running is False


def test_managed_storage_boot_seeds_default_recording_target(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING", "off")
    _quiet_unrelated_workers(monkeypatch)

    from civiccast.installer.storage import ensure_managed_storage

    ensure_managed_storage()

    assert "CIVICCAST_ALLOW_EPHEMERAL_STORES" not in os.environ
    from civiccast.app import create_app

    try:
        app = create_app()
        target_store = app.dependency_overrides[get_recording_target_store]()
        targets = {target.recording_target_id: target for target in target_store.list()}
    finally:
        reset_engine()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("CIVICCAST_UPLOAD_DIR", None)

    target = targets[DEFAULT_RECORDING_TARGET_ID]
    assert target.target_uri == (tmp_path / "managed" / "uploads" / "recordings").as_uri()


def _station_engine(db_path: Path) -> Engine:
    """A SQLite engine shaped like the app's own durable-store engine.

    ``civiccast.app._create_database_engine`` folds the ``civiccast`` schema
    into SQLite's ``main`` with a schema-translate map; DDL written without the
    same map lands in the per-connection in-memory ATTACH instead of the file,
    so the app would see no tables at all.
    """

    return create_engine(f"sqlite:///{db_path}").execution_options(
        schema_translate_map={"civiccast": None}
    )


def _native_control_plane_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Env of a native control-plane child, and a schema-ready SQLite file.

    ``control_plane_child_spec`` sets ``CIVICCAST_UPLOAD_DIR`` unconditionally on
    every native launch, so ``_ensure_default_local_recording_target`` runs on a
    station that never went through the managed-storage/installer flow. These
    tests reproduce exactly that shape: upload dir pre-set, DATABASE_URL pointing
    at a real schema, no managed storage.
    """

    db_path = tmp_path / "station.db"
    engine = _station_engine(db_path)
    Base.metadata.create_all(engine)
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING", "off")
    monkeypatch.setenv("CIVICCAST_SCHEDULED_RECORDING", "off")
    _quiet_unrelated_workers(monkeypatch)
    for name in (
        "CIVICCAST_FINALIZATION_WORKER",
        "CIVICCAST_ACTIVITYPUB_WORKER",
        "CIVICCAST_RETENTION_WORKER",
        "CIVICCAST_WEBHOOK_RETRY",
        "CIVICCAST_PROGRAM_LOG",
        "CIVICCAST_AUTOSCHEDULE",
        "CIVICCAST_ALERTING",
        "CIVICCAST_BULLETIN_EXPIRY",
    ):
        monkeypatch.setenv(name, "off")
    return db_path


def test_native_station_boot_seeds_default_recording_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The seed is intentional on a native station, not only under managed storage.

    ``preflight.py``'s ``recording_target`` check is REQUIRED and the operator
    console ships no create-target screen, so without this row a station cannot
    go on air and cannot fix that from the UI.
    """

    _native_control_plane_env(monkeypatch, tmp_path)

    from civiccast.app import create_app

    try:
        app = create_app()
        target_store = app.dependency_overrides[get_recording_target_store]()
        targets = {target.recording_target_id: target for target in target_store.list()}
    finally:
        reset_engine()

    expected_dir = (tmp_path / "uploads" / "recordings").resolve()
    assert targets[DEFAULT_RECORDING_TARGET_ID].target_uri == expected_dir.as_uri()
    assert expected_dir.is_dir()


def test_native_station_boot_defers_to_an_existing_production_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An operator-configured target is never displaced by the seed."""

    db_path = _native_control_plane_env(monkeypatch, tmp_path)
    operator_dir = tmp_path / "operator-choice"
    engine = _station_engine(db_path)
    with Session(bind=engine) as session:
        session.add(
            RecordingTarget(
                recording_target_id="operator-nas",
                name="Operator NAS",
                target_uri=operator_dir.as_uri(),
                created_at=_NOW,
            )
        )
        session.commit()
    engine.dispose()

    from civiccast.app import create_app

    try:
        app = create_app()
        target_store = app.dependency_overrides[get_recording_target_store]()
        target_ids = {target.recording_target_id for target in target_store.list()}
    finally:
        reset_engine()

    assert target_ids == {"operator-nas"}
    assert not (tmp_path / "uploads" / "recordings").exists()


def test_create_app_survives_an_unwritable_recording_target_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An OSError from the seed's mkdir must never stop the control plane.

    Before the guard, ``mkdir`` sat outside the function's try, so an OSError
    propagated out of ``create_app`` -- the control plane never started, /health
    never answered, and every downstream product-exercise row failed.
    """

    _native_control_plane_env(monkeypatch, tmp_path)

    real_mkdir = Path.mkdir

    def refuse_recordings_dir(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == DEFAULT_RECORDING_TARGET_DIR_NAME:
            raise OSError(13, "Access is denied")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_recordings_dir)

    from civiccast.app import create_app

    try:
        with caplog.at_level(logging.WARNING, logger="civiccast.app"):
            app = create_app()
        target_store = app.dependency_overrides[get_recording_target_store]()
        target_ids = {target.recording_target_id for target in target_store.list()}
    finally:
        reset_engine()

    assert app.state.durable_storage_active is True
    assert target_ids == set()
    assert any(
        "Could not create the default recording directory" in record.getMessage()
        for record in caplog.records
    )


_ENGINES_TO_DISPOSE: list = []


@pytest.fixture(autouse=True)
def _dispose_test_engines() -> Iterator[None]:
    """Dispose throwaway SQLite engines at each test's end.

    The inline engine below is trapped in a factory closure; undisposed, its
    sqlite3.Connection lingers until GC finalizes it, raising an
    "Exception ignored in" unraisable that the filterwarnings=error policy turns
    into a failure pinned to a random unrelated test.
    """
    yield
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


def test_record_now_stop_creates_file_backed_recorded_asset(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    _ENGINES_TO_DISPOSE.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    target_dir = tmp_path / "recordings"
    rehearsal_dir = tmp_path / "private-rehearsals"
    with factory() as session:
        session.add_all(
            [
                RecordingTarget(
                    recording_target_id=REHEARSAL_RECORDING_TARGET_ID,
                    name="Installer rehearsal recordings",
                    target_uri=rehearsal_dir.as_uri(),
                    created_at=_NOW - timedelta(minutes=2),
                ),
                RecordingTarget(
                    recording_target_id="local",
                    name="Local recordings",
                    target_uri=target_dir.as_uri(),
                    created_at=_NOW - timedelta(minutes=1),
                ),
            ]
        )
        session.commit()

    class FakeHandle:
        def __init__(self, output_path: Path) -> None:
            self.output_path = output_path
            self.returncode = None

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self, *, grace_seconds: float = 5.0) -> int:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_bytes(b"civiccast-recording-bytes")
            self.returncode = 0
            return 0

        def close(self) -> None:
            return None

    captured_ffmpeg_args: list[str] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> FakeHandle:
        captured_ffmpeg_args.extend(args)
        return FakeHandle(Path(args[-1]))

    monkeypatch.setattr(
        "civiccast.recording.runtime.run_ffprobe",
        lambda _path: FfprobeResult(
            duration_seconds=12,
            codec_video="h264",
            codec_audio="aac",
            width_px=1920,
            height_px=1080,
            bitrate_bps=4_000_000,
            format_name="mpegts",
        ),
    )

    store = RecordingStore(factory)
    service = RecordingService(
        store,
        capture_pipeline=FfmpegScheduledCapturePipeline(
            factory,
            settings=ScheduledRecordingSettings(mode="off"),
            ffmpeg_starter=fake_start_ffmpeg,
        ),
        asset_finalizer=ScheduledRecordingAssetFinalizer(factory),
        alert_sink=RecordingAlertSink(factory),
        clock=lambda: _NOW,
    )
    schedule = store.upsert_schedule(
        RecordingSchedule(
            station_id="civiccast-station",
            schedule_id="council-now",
            name="Council Now",
            source=RecordingSource(kind="hls", uri="https://example.test/live.m3u8"),
            recurrence=RecurrenceSpec(kind="one_shot", start=_NOW + timedelta(hours=1)),
            duration_seconds=60,
            encoder_profile="hw-h264-720p",
            loudness_regime="ebu-r128",
            target_series="council",
            custom_field_values={"body": "council"},
            enabled=True,
        )
    )

    job = service.record_now(schedule.schedule_id)
    assert job.state == "recording"
    assert "scale=-2:720" in captured_ffmpeg_args
    assert "loudnorm=I=-23:TP=-2:LRA=7" in captured_ffmpeg_args
    assert Path(captured_ffmpeg_args[-1]).is_relative_to(target_dir)

    done = service.stop_job(job.job_id)
    assert done.state == "done"
    assert done.asset_id
    assert done.bytes_written == len(b"civiccast-recording-bytes")

    with factory() as session:
        asset = session.get(Asset, done.asset_id)
        assert asset is not None
        assert asset.state == "recorded"
        assert asset.file_path is not None
        assert Path(asset.file_path).exists()
        assert asset.duration_seconds == 12
        assert asset.codec_video == "h264"


def test_app_startup_reconciles_a_job_orphaned_by_a_prior_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """BLOCKER regression: reconcile_orphans() existed but was never called
    from production.

    ``RecordingStore.reconcile_orphaned_active_jobs`` /
    ``RecordingService.reconcile_orphans`` fail a job stuck in an active
    state (``arming``/``recording``/``finalizing``) past its planned end --
    the trace of an unclean process exit. Before this fix, only the unit
    tests in ``test_service.py`` / ``test_models_and_store.py`` ever called
    it; a real service restart mid-recording left the DB row "recording"
    forever, and because "recording" is an overlap-blocking state
    (``RecordingStore.find_overlapping_jobs``), every future recording on
    that source was silently skipped, permanently, with no operator-visible
    error.

    This test seeds a job stuck in "recording" with a planned_end in the
    past directly into the app's own database file, boots the real app
    (``create_app`` + the ``TestClient`` lifespan, exactly like a service
    restart), and asserts the job is failed by the time startup completes --
    proving the production lifespan, not just a unit test, now calls the
    reconciler.
    """

    db_path = _native_control_plane_env(monkeypatch, tmp_path)

    engine = _station_engine(db_path)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    stuck_start = _NOW - timedelta(hours=3)
    stuck_end = _NOW - timedelta(hours=2)
    store = RecordingStore(factory)
    store.create_job(
        RecordingJob(
            job_id="zombie-restart-1",
            station_id="civiccast-station",
            schedule_id=None,
            planned_start=stuck_start,
            planned_end=stuck_end,
            state="scheduled",
            source_snapshot=RecordingSource(kind="rtsp", uri="rtsp://example.local/stream"),
            encoder_profile="hw-h264-1080p",
        )
    )
    # Drive it into "recording" the same way a real capture does, so the
    # seeded row is indistinguishable from one orphaned mid-capture.
    store.set_job_state("zombie-restart-1", "arming")
    store.set_job_state("zombie-restart-1", "recording")
    engine.dispose()

    from civiccast.app import create_app

    try:
        app = create_app()
        with TestClient(app):
            pass  # lifespan startup (and its one-shot reconcile hook) runs on enter/exit.

        recovery_engine = _station_engine(db_path)

        @contextmanager
        def recovery_factory() -> Iterator[Session]:
            with Session(bind=recovery_engine) as session:
                yield session

        job = RecordingStore(recovery_factory).get_job("zombie-restart-1")
        recovery_engine.dispose()
    finally:
        reset_engine()

    assert job is not None
    assert job.state == "failed"
    assert job.failure_reason
