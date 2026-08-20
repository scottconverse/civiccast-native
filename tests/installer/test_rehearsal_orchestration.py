# Copyright (c) The CivicCast Authors
"""Real-boundary tests for the private first-broadcast rehearsal path."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.app import create_app
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.installer.models import FirstAdminSetupRequest
from civiccast.installer.router import (
    get_live_recording_finalizer,
    get_live_session_store,
    get_live_source_store,
    get_preflight_evaluator,
    get_recording_target_store,
)
from civiccast.installer.service import (
    build_system_health_report,
    complete_first_admin_setup,
    create_sample_rehearsal_upload,
    run_private_rehearsal,
)
from civiccast.live.finalization import LiveRecordingFinalizer
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    LiveFinalizationJob,
    LiveSession,
    LiveSourceCreate,
    RecordingTarget,
)
from civiccast.live.preflight import PreflightEvaluator
from civiccast.live.recording_paths import (
    REHEARSAL_RECORDING_TARGET_ID,
    local_recording_path,
)
from civiccast.live.store import LiveSessionStore, LiveSourceStore, RecordingTargetStore
from civiccast.schedule.ingest import FfprobeError, FfprobeResult
from civiccast.schedule.media_integrity_worker import (
    MediaIntegrityWorker,
    MediaIntegrityWorkerSettings,
)
from civiccast.schedule.models import FILE_STATUS_MISSING, FILE_STATUS_OK, Asset
from civiccast.schedule.store import PostgresAssetStore
from civiccast.stream import media_router

_FFPROBE_SAMPLE = FfprobeResult(
    duration_seconds=2,
    codec_video="h264",
    codec_audio="aac",
    width_px=640,
    height_px=360,
    bitrate_bps=300_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)
_READY_DISK_USAGE = SimpleNamespace(free=100 * (1024**3))


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def resident_preview_url() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"<!doctype html><html><body><div id='root'>CivicCast resident portal</div></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _write_sample(path: Path) -> None:
    path.write_bytes(b"sample-video")


def _external_database_reports_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the stand-in ``DATABASE_URL`` answer like a healthy database.

    These tests set ``DATABASE_URL`` only to mean "this station has durable
    storage configured"; they never create or migrate that database. That used
    to be enough, because ``durable_storage_status`` returned
    ``status="ready"``, ``migrations_applied=True`` for ANY external
    ``DATABASE_URL`` with no connection attempt and no schema check. It now
    executes a bounded connectivity + schema-currency probe, so the stand-in
    has to answer like a real, migrated database -- otherwise the
    durable-storage health check correctly reports red and buries the
    rehearsal behaviour these tests exist to prove. Injected at
    ``read_db_revision``, the probe's one real connect.
    """

    from civiccast import schema_check

    monkeypatch.setattr(
        schema_check,
        "read_db_revision",
        lambda database_url: schema_check.expected_migration_head(),
    )


def _complete_station_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    preview_url: str,
) -> str:
    _external_database_reports_current(monkeypatch)
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.setenv("CIVICCAST_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'civiccast.sqlite3').as_posix()}")
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("CIVICCAST_RESIDENT_PORTAL_URL", preview_url)
    response = complete_first_admin_setup(
        FirstAdminSetupRequest(
            station_name="Pinegrove School Board",
            admin_display_name="Avery Admin",
            admin_username="avery",
            admin_password="correct horse battery staple",
            recovery_kit_destination="safe",
        )
    )
    return response.operator_console_token


def _create_live_source(source_store: LiveSourceStore) -> None:
    source_store.create(
        LiveSourceCreate(
            live_source_id="council-room-camera",
            channel_id="government",
            name="Council Room Camera",
            source_type="rtmp",
            endpoint_url="rtmp://127.0.0.1/live/council",
        )
    )


def test_private_rehearsal_never_substitutes_synthetic_media_for_a_live_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    engine: Engine,
    resident_preview_url: str,
) -> None:
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    preflight = PreflightEvaluator(
        session_factory,
        source_probe=lambda source: (True, f"Source {source.live_source_id!r} delivered media."),
    )
    finalizer = LiveRecordingFinalizer(session_factory)
    _create_live_source(live_source_store)

    with (
        patch(
            "civiccast.installer.service._write_sample_video", side_effect=_write_sample
        ) as write_sample,
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.private_session_id is None
    assert report.recording_asset_id is None
    assert report.recording_uri is None
    assert report.status == "blocked"
    assert "validated recorded sample" in report.message
    assert any("No validated recorded sample" in item for item in report.evidence)
    write_sample.assert_not_called()

    with Session(bind=engine) as session:
        assert session.execute(select(LiveSession)).scalars().all() == []
        assert session.execute(select(Asset)).scalars().all() == []


def test_bundled_sample_rehearsal_proves_and_packages_the_exact_uploaded_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    resident_preview_url: str,
) -> None:
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    postgres_store = PostgresAssetStore(session_factory)
    preflight = PreflightEvaluator(
        session_factory,
        source_probe=lambda _source: (False, "No live stream is running."),
    )
    finalizer = LiveRecordingFinalizer(session_factory)

    sample_bytes = b"validated-bundled-sample-media"

    def write_bundled_sample(path: Path) -> None:
        path.write_bytes(sample_bytes)

    with (
        patch("civiccast.installer.service._write_sample_video", side_effect=write_bundled_sample),
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        uploaded = create_sample_rehearsal_upload(
            postgres_store=postgres_store,
            live_source_store=live_source_store,
        )
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.status in {"ready", "needs_attention"}
    assert report.recording_asset_id == report.private_session_id
    assert any(uploaded.asset_id in item for item in report.evidence)
    recording_path = local_recording_path(report.recording_uri)
    assert recording_path is not None
    assert recording_path.read_bytes() == sample_bytes


def test_private_rehearsal_reports_a_corrupt_selected_sample_without_http_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    resident_preview_url: str,
) -> None:
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    postgres_store = PostgresAssetStore(session_factory)
    preflight = PreflightEvaluator(session_factory)
    finalizer = LiveRecordingFinalizer(session_factory)

    with (
        patch("civiccast.installer.service._write_sample_video", side_effect=_write_sample),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        create_sample_rehearsal_upload(
            postgres_store=postgres_store,
            live_source_store=live_source_store,
        )

    with (
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch(
            "civiccast.installer.service.run_ffprobe",
            side_effect=FfprobeError("ffprobe could not read the selected sample"),
        ),
    ):
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.status == "blocked"
    assert report.recording_asset_id is None
    assert "ffprobe could not read the selected sample" in report.message
    assert any("Rehearsal stopped" in item for item in report.evidence)


def test_private_rehearsal_without_sample_or_live_source_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    resident_preview_url: str,
) -> None:
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    preflight = PreflightEvaluator(session_factory)
    finalizer = LiveRecordingFinalizer(session_factory)

    with (
        patch("civiccast.installer.service._write_sample_video", side_effect=_write_sample),
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.status == "blocked"
    assert report.recording_asset_id is None
    assert report.message == (
        "Private rehearsal needs a validated recorded sample before it can run."
    )
    assert report.private_session_id is None
    assert report.recording_uri is None


def test_private_rehearsal_stops_when_preflight_evaluator_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    engine: Engine,
    resident_preview_url: str,
) -> None:
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    preflight = None
    finalizer = LiveRecordingFinalizer(session_factory)
    postgres_store = PostgresAssetStore(session_factory)

    with (
        patch("civiccast.installer.service._write_sample_video", side_effect=_write_sample),
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        create_sample_rehearsal_upload(
            postgres_store=postgres_store,
            live_source_store=live_source_store,
        )
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.status in {"blocked", "needs_attention"}
    assert report.recording_asset_id is None
    assert report.private_session_id is not None
    assert any(
        "required item did not pass" in item or "evaluator is not available" in item
        for item in report.evidence
    )
    assert not any("Finalized private recording" in item for item in report.evidence)

    with Session(bind=engine) as session:
        live_session = session.execute(
            select(LiveSession).where(LiveSession.live_session_id == report.private_session_id)
        ).scalar_one()
        assets = (
            session.execute(
                select(Asset).where(Asset.source_live_session_id == report.private_session_id)
            )
            .scalars()
            .all()
        )
    assert live_session.state == "preflight"
    assert assets == []


def test_system_health_does_not_count_rehearsal_target_as_production_recording(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    engine: Engine,
) -> None:
    monkeypatch.setenv("CIVICAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    rehearsal_dir = tmp_path / "uploads" / "private-rehearsals"
    rehearsal_dir.mkdir(parents=True)
    with Session(bind=engine) as session:
        session.add(
            RecordingTarget(
                recording_target_id=REHEARSAL_RECORDING_TARGET_ID,
                name="Local rehearsal recordings",
                target_uri=rehearsal_dir.as_uri(),
            )
        )
        session.commit()

    health = build_system_health_report(
        live_source_count=1,
        recording_target_count=0,
        live_preflight_ready=True,
        recording_write_probe_ready=True,
        resident_preview_confirmed=True,
    )

    check = {item.id: item for item in health.checks}["recording-path"]
    assert check.state == "not_set_up"
    assert check.color == "red"


def test_rehearsal_route_uses_durable_live_contracts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    engine: Engine,
    resident_preview_url: str,
) -> None:
    operator_token = _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CIVICAST_ALLOW_EPHEMERAL_STORES", "1")
    bind_engine(engine)
    Base.metadata.create_all(engine)
    app = create_app()
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    preflight = PreflightEvaluator(
        session_factory,
        source_probe=lambda source: (True, f"Source {source.live_source_id!r} delivered media."),
    )
    finalizer = LiveRecordingFinalizer(session_factory)
    postgres_store = PostgresAssetStore(session_factory)

    app.dependency_overrides[get_live_session_store] = lambda: live_session_store
    app.dependency_overrides[get_live_source_store] = lambda: live_source_store
    app.dependency_overrides[get_recording_target_store] = lambda: recording_target_store
    app.dependency_overrides[get_preflight_evaluator] = lambda: preflight
    app.dependency_overrides[get_live_recording_finalizer] = lambda: finalizer
    app.state.staff_token_store = None

    with (
        TestClient(app, headers={"Authorization": f"Bearer {operator_token}"}) as client,
        patch("civiccast.installer.service._write_sample_video", side_effect=_write_sample),
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        create_sample_rehearsal_upload(
            postgres_store=postgres_store,
            live_source_store=live_source_store,
        )
        response = client.post("/api/staff/installer/rehearsal")

    assert response.status_code == 200
    payload = response.json()
    assert payload["private_session_id"].startswith("rehearsal-")
    assert payload["recording_asset_id"] == payload["private_session_id"]
    assert payload["resident_preview_proof"].startswith("Resident preview loaded")
    assert any("Live preflight passed" in item for item in payload["evidence"])


def test_rehearsal_recording_survives_reload_package_and_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: Any,
    engine: Engine,
    resident_preview_url: str,
) -> None:
    """D3 end-to-end control: rehearsal -> asset RELOAD -> package -> publish.

    Locks the root-cause fix in ``civiccast.live.finalization`` at the level a
    resident's player actually depends on, not just at the point of write:

    1. ``run_private_rehearsal`` registers the asset with a real temp file.
    2. RELOAD: ``MediaIntegrityWorker`` (the real production re-check that
       runs periodically in the app) must never flag the asset ``missing`` --
       the historical bug: a raw ``file://`` string in ``assets.file_path``
       fails ``Path(...).is_file()`` even though the recording is right there.
    3. PACKAGE: the resolved local ``Path`` is a valid packager input (a
       ``file://`` string is not -- this is the exact point a real packaging
       attempt would have failed under the bug). Packager itself is faked
       (matching ``tests/live/test_finalization_worker.py``'s own
       convention) -- proving ffmpeg output is out of scope for this control.
    4. PUBLISH: the portal's real ``/media/vod`` router (API-level, no UI, no
       installed app) must serve the packaged manifest once published.
    """
    _complete_station_setup(monkeypatch, tmp_path, resident_preview_url)
    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    postgres_store = PostgresAssetStore(session_factory)
    preflight = PreflightEvaluator(
        session_factory,
        source_probe=lambda _source: (False, "No live stream is running."),
    )
    finalizer = LiveRecordingFinalizer(session_factory)

    sample_bytes = b"validated-bundled-sample-media"

    def write_bundled_sample(path: Path) -> None:
        path.write_bytes(sample_bytes)

    with (
        patch("civiccast.installer.service._write_sample_video", side_effect=write_bundled_sample),
        patch("civiccast.installer.service.shutil.disk_usage", return_value=_READY_DISK_USAGE),
        patch("civiccast.installer.service.run_ffprobe", return_value=_FFPROBE_SAMPLE),
        patch("civiccast.installer.service.validate_ingest"),
    ):
        create_sample_rehearsal_upload(
            postgres_store=postgres_store,
            live_source_store=live_source_store,
        )
        report = run_private_rehearsal(
            live_session_store=live_session_store,
            live_source_store=live_source_store,
            recording_target_store=recording_target_store,
            preflight_evaluator=preflight,
            finalizer=finalizer,
        )

    assert report.status in {"ready", "needs_attention"}
    asset_id = report.recording_asset_id
    assert asset_id is not None

    # --- 1. registration: file_path is a real local path, not file:// ---
    with Session(bind=engine) as session:
        asset = session.execute(select(Asset).where(Asset.asset_id == asset_id)).scalar_one()
        assert asset.file_path is not None
        assert not asset.file_path.startswith("file://")
        recording_path = Path(asset.file_path)
    assert recording_path.is_file()
    assert recording_path.read_bytes() == sample_bytes

    # --- 2. asset RELOAD: never missing ---
    integrity_worker = MediaIntegrityWorker(
        session_factory, settings=MediaIntegrityWorkerSettings(mode="inline")
    )
    integrity_worker.run_once()
    with Session(bind=engine) as session:
        asset = session.execute(select(Asset).where(Asset.asset_id == asset_id)).scalar_one()
        assert asset.file_status == FILE_STATUS_OK
        assert asset.file_status != FILE_STATUS_MISSING

    # --- 3. package: the normalized Path is a usable packager input ---
    output_dir = recording_path.parent / f"{asset_id}-hls"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "playlist.m3u8"
    manifest_body = "#EXTM3U\n#EXT-X-ENDLIST\n"
    # newline="" -- Path.write_text universal-newline-translates "\n" to
    # os.linesep by default (CRLF on Windows), which would make the file's
    # real bytes diverge from manifest_body and fail the byte-exact
    # response check below for a platform reason, not a product one.
    manifest_path.write_text(manifest_body, encoding="utf-8", newline="")
    manifest_url = f"http://127.0.0.1:8000/media/vod/{asset_id}/playlist.m3u8"
    with Session(bind=engine) as session:
        asset = session.execute(select(Asset).where(Asset.asset_id == asset_id)).scalar_one()
        asset.manifest_url = manifest_url
        session.add(
            LiveFinalizationJob(
                live_session_id=report.private_session_id,
                state=FINALIZATION_STATE_COMPLETED,
                asset_id=asset_id,
                local_package_manifest_path=str(manifest_path.resolve()),
            )
        )
        session.commit()
    published_at = datetime.now(UTC)
    published = postgres_store.mark_published(asset_id, published_at=published_at)
    assert published.published_at == published_at

    # --- 4. publish path reachable: the real portal media router ---
    publish_app = FastAPI()
    publish_app.include_router(media_router.router)
    with TestClient(publish_app) as client:
        response = client.get(f"/media/vod/{asset_id}/playlist.m3u8")
    assert response.status_code == 200
    assert response.text == manifest_body
