# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S21 recording router — role gating, 503 unwired, schedule CRUD, jobs,
record-now, stop-job.

Mirrors the paywall router harness: a minimal FastAPI app mounts the
real staff router, installs an operator-identity middleware (so
``require_any_role`` runs), and overrides the DI seams with a
SQLite-backed ``RecordingStore`` + a stub-pipeline-equipped
``RecordingService``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.recording.input_presets import RecordingInputPreset, RecordingInputPresetCatalog
from civiccast.recording.models import RecordingSource
from civiccast.recording.router import (
    get_recording_input_catalog,
    get_recording_service,
    get_recording_store,
    staff_router,
)
from civiccast.recording.service import (
    RecordingService,
)
from civiccast.recording.store import RecordingStore

# Re-use the service-test stubs so we don't duplicate them.
from tests.recording.test_service import (
    StubAlertSink,
    StubCapturePipeline,
    StubFinalizer,
)

_STATION = "civiccast-station"
_FROZEN_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)
_WRITE_SCOPES = ("setup_admin", "meeting_operator")
_READ_ONLY_SCOPES = ("support_admin",)
_FORBIDDEN_SCOPES = ("publish_operator",)


def _frozen_clock(at: datetime = _FROZEN_NOW):
    def _now() -> datetime:
        return at

    return _now


_ENGINES_TO_DISPOSE: list = []


@pytest.fixture(autouse=True)
def _dispose_test_engines() -> Iterator[None]:
    """Dispose throwaway SQLite engines at each test's end.

    Each _build() call traps a fresh engine in a closure; undisposed, its
    sqlite3.Connection lingers until GC finalizes it at an arbitrary later
    point, raising an "Exception ignored in" unraisable that the
    filterwarnings=error policy turns into a failure pinned to a random
    unrelated test. Disposing here closes them deterministically.
    """
    yield
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


def _build(
    *,
    scopes: tuple[str, ...] | None = _WRITE_SCOPES,
    wire_store: bool = True,
    wire_service: bool = True,
    pipeline: StubCapturePipeline | None = None,
    finalizer: StubFinalizer | None = None,
    alert_sink: StubAlertSink | None = None,
) -> tuple[FastAPI, RecordingStore, RecordingService]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _ENGINES_TO_DISPOSE.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    store = RecordingStore(factory)
    service = RecordingService(
        store,
        capture_pipeline=pipeline,
        asset_finalizer=finalizer,
        alert_sink=alert_sink,
        clock=_frozen_clock(),
    )
    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana",
                operator_display_name="Dana",
                scopes=scopes,
            )
        return await call_next(request)

    app.include_router(staff_router)
    if wire_store:
        app.dependency_overrides[get_recording_store] = lambda: store
    if wire_service:
        app.dependency_overrides[get_recording_service] = lambda: service
    return app, store, service


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _schedule_payload(
    *,
    schedule_id: str = "sch-1",
    name: str = "Council Tuesdays",
    source_kind: str = "rtsp",
    uri: str = "rtsp://camera.local/main",
    duration_seconds: int = 3600,
) -> dict:
    source = (
        {"kind": source_kind, "uri": uri}
        if source_kind in ("rtsp", "srt", "hls", "rtmp", "mpegts")
        else {"kind": source_kind, "input_id": uri}
    )
    return {
        "schedule_id": schedule_id,
        "station_id": _STATION,
        "name": name,
        "source": source,
        "recurrence": {
            "kind": "one_shot",
            "start": (_FROZEN_NOW + timedelta(minutes=10)).isoformat(),
        },
        "duration_seconds": duration_seconds,
        "encoder_profile": "hw-h264-1080p",
        "loudness_regime": "atsc-a85",
        "target_series": "council",
        "custom_field_values": {"committee": "council"},
        "enabled": True,
    }


# ---------------------------------------------------------------------------
# 503 unwired (every endpoint)
# ---------------------------------------------------------------------------


class TestUnwired:
    def test_input_presets_503_when_catalog_missing(self):
        client = _client()
        r = client.get("/api/staff/recording/input-presets")
        assert r.status_code == 503

    def test_list_schedules_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.get("/api/staff/recording/schedules")
        assert r.status_code == 503

    def test_create_schedule_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 503

    def test_get_schedule_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.get("/api/staff/recording/schedules/sch-x")
        assert r.status_code == 503

    def test_patch_schedule_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.patch("/api/staff/recording/schedules/sch-x", json={"enabled": False})
        assert r.status_code == 503

    def test_delete_schedule_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.delete("/api/staff/recording/schedules/sch-x")
        assert r.status_code == 503

    def test_record_now_503_when_service_missing(self):
        client = _client(wire_service=False)
        r = client.post("/api/staff/recording/schedules/sch-x/record-now")
        assert r.status_code == 503

    def test_list_jobs_503_when_store_missing(self):
        client = _client(wire_store=False)
        r = client.get("/api/staff/recording/jobs")
        assert r.status_code == 503

    def test_stop_job_503_when_service_missing(self):
        client = _client(wire_service=False)
        r = client.post("/api/staff/recording/jobs/job-x/stop")
        assert r.status_code == 503

    def test_record_now_503_when_pipeline_unwired(self):
        # Store + service are wired, but the service has NO capture
        # pipeline. The router should surface 503.
        app, _store, _ = _build()  # pipeline=None
        # Plant a schedule via the store so record_now resolves it
        # before hitting the pipeline check.
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
        assert r.status_code == 503

    def test_stop_job_503_when_pipeline_unwired(self):
        # No pipeline; stop should surface 503 too. We have to plant a
        # job by reaching into the store directly because record_now is
        # the only public path to do so and it 503s without pipeline.
        from civiccast.recording.models import RecordingJob

        app, store, _ = _build()  # pipeline=None
        job = RecordingJob(
            job_id="active-1",
            station_id=_STATION,
            schedule_id=None,
            planned_start=_FROZEN_NOW - timedelta(minutes=5),
            planned_end=_FROZEN_NOW + timedelta(minutes=10),
            source_snapshot=RecordingSource(kind="rtsp", uri="rtsp://x.local/s"),
            encoder_profile="hw-h264-1080p",
        )
        store.create_job(job)
        store.set_job_state("active-1", "arming")
        store.set_job_state("active-1", "recording")
        with TestClient(app) as client:
            r = client.post("/api/staff/recording/jobs/active-1/stop")
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Role gating
# ---------------------------------------------------------------------------


class TestRoles:
    def test_support_admin_can_read_input_presets(self):
        app, _store, _service = _build(scopes=("support_admin",))
        app.dependency_overrides[get_recording_input_catalog] = lambda: RecordingInputPresetCatalog(
            [
                RecordingInputPreset(
                    preset_id="decklink-main",
                    label="DeckLink main",
                    source_kind="sdi",
                    backend="decklink",
                    device_name="DeckLink Duo 2 (1)",
                )
            ],
            ffmpeg_runner=lambda _args: None,
        )
        r = TestClient(app).get("/api/staff/recording/input-presets")
        assert r.status_code == 200
        assert r.json()[0]["preset_id"] == "decklink-main"

    def test_publish_operator_cannot_read_input_presets(self):
        app, _store, _service = _build(scopes=_FORBIDDEN_SCOPES)
        app.dependency_overrides[get_recording_input_catalog] = lambda: RecordingInputPresetCatalog(
            [], ffmpeg_runner=lambda _args: None
        )
        r = TestClient(app).get("/api/staff/recording/input-presets")
        assert r.status_code == 403

    def test_unauthenticated_is_401(self):
        client = _client(scopes=None)
        r = client.get("/api/staff/recording/schedules")
        assert r.status_code == 401

    def test_setup_admin_can_write(self):
        client = _client(scopes=("setup_admin",))
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 201

    def test_meeting_operator_can_write(self):
        client = _client(scopes=("meeting_operator",))
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 201

    def test_support_admin_can_read(self):
        client = _client(scopes=("support_admin",))
        r = client.get("/api/staff/recording/schedules")
        assert r.status_code == 200

    def test_support_admin_cannot_write(self):
        client = _client(scopes=("support_admin",))
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 403

    def test_publish_operator_cannot_write(self):
        client = _client(scopes=_FORBIDDEN_SCOPES)
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 403

    def test_publish_operator_cannot_read(self):
        # publish_operator is NOT on the read allowlist.
        client = _client(scopes=_FORBIDDEN_SCOPES)
        r = client.get("/api/staff/recording/schedules")
        assert r.status_code == 403

    def test_jobs_list_open_to_support_admin(self):
        client = _client(scopes=("support_admin",))
        r = client.get("/api/staff/recording/jobs")
        assert r.status_code == 200

    def test_stop_job_forbidden_for_support_admin(self):
        client = _client(scopes=("support_admin",))
        r = client.post("/api/staff/recording/jobs/anything/stop")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Schedule CRUD
# ---------------------------------------------------------------------------


class TestScheduleCrud:
    def test_create_get_list(self):
        client = _client()
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 201
        body = r.json()
        assert body["schedule_id"] == "sch-1"
        # Get
        r = client.get("/api/staff/recording/schedules/sch-1")
        assert r.status_code == 200
        assert r.json()["name"] == "Council Tuesdays"
        # List
        r = client.get("/api/staff/recording/schedules")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_create_duplicate_id_is_409(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        r = client.post("/api/staff/recording/schedules", json=_schedule_payload())
        assert r.status_code == 409

    def test_create_duplicate_name_is_409(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        r = client.post(
            "/api/staff/recording/schedules",
            json=_schedule_payload(schedule_id="sch-2"),  # same name, different id
        )
        assert r.status_code == 409

    def test_get_missing_is_404(self):
        client = _client()
        r = client.get("/api/staff/recording/schedules/nope")
        assert r.status_code == 404

    def test_patch_missing_is_404(self):
        client = _client()
        r = client.patch("/api/staff/recording/schedules/nope", json={"enabled": False})
        assert r.status_code == 404

    def test_patch_happy_path(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        r = client.patch(
            "/api/staff/recording/schedules/sch-1",
            json={"name": "Renamed", "duration_seconds": 1800},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"
        assert r.json()["duration_seconds"] == 1800

    def test_patch_name_conflict_is_409(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        client.post(
            "/api/staff/recording/schedules",
            json=_schedule_payload(schedule_id="sch-2", name="Planning Mondays"),
        )
        r = client.patch(
            "/api/staff/recording/schedules/sch-2",
            json={"name": "Council Tuesdays"},
        )
        assert r.status_code == 409

    def test_delete_happy_path_returns_204(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        r = client.delete("/api/staff/recording/schedules/sch-1")
        assert r.status_code == 204

    def test_delete_missing_is_404(self):
        client = _client()
        r = client.delete("/api/staff/recording/schedules/nope")
        assert r.status_code == 404

    def test_enabled_only_filter(self):
        client = _client()
        client.post("/api/staff/recording/schedules", json=_schedule_payload())
        client.post(
            "/api/staff/recording/schedules",
            json={**_schedule_payload(schedule_id="sch-2", name="Off"), "enabled": False},
        )
        r = client.get("/api/staff/recording/schedules?enabled_only=true")
        assert r.status_code == 200
        ids = {row["schedule_id"] for row in r.json()}
        assert ids == {"sch-1"}

    def test_create_bad_payload_is_422(self):
        client = _client()
        r = client.post(
            "/api/staff/recording/schedules",
            json={"schedule_id": "x"},  # missing many required fields
        )
        assert r.status_code == 422

    def test_create_network_source_without_uri_is_422(self):
        client = _client()
        bad = _schedule_payload(source_kind="rtsp")
        bad["source"] = {"kind": "rtsp", "uri": ""}  # empty uri on network source
        r = client.post("/api/staff/recording/schedules", json=bad)
        assert r.status_code == 422

    def test_extra_field_rejected(self):
        client = _client()
        payload = _schedule_payload()
        payload["mystery_field"] = "boom"
        r = client.post("/api/staff/recording/schedules", json=payload)
        assert r.status_code == 422

    # Q-5 fix — payload.station_id must match the deployed station.
    def test_create_with_mismatched_station_id_is_403(self):
        client = _client()
        payload = _schedule_payload()
        payload["station_id"] = "other-station"
        r = client.post("/api/staff/recording/schedules", json=payload)
        assert r.status_code == 403

    # E-11 fix — disabling a schedule cancels future scheduled jobs.
    def test_patch_disable_cancels_future_scheduled_jobs(self):
        pipeline = StubCapturePipeline()
        app, _store, svc = _build(pipeline=pipeline)
        with TestClient(app) as client:
            # Create schedule + materialize a scheduled job.
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            svc.expand_jobs_for_horizon(_STATION, timedelta(hours=2))
            # Confirm we have one scheduled job.
            r = client.get("/api/staff/recording/jobs?state=scheduled")
            assert r.status_code == 200
            assert len(r.json()) == 1
            # Now PATCH the schedule to disable.
            r = client.patch(
                "/api/staff/recording/schedules/sch-1",
                json={"enabled": False},
            )
            assert r.status_code == 200
            assert r.json()["enabled"] is False
            # The previously-scheduled job should now be skipped.
            r = client.get("/api/staff/recording/jobs?state=skipped")
            assert r.status_code == 200
            assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Record-now (with pipeline)
# ---------------------------------------------------------------------------


class TestRecordNow:
    def test_happy_path_returns_running_job(self):
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        app, _store, _ = _build(pipeline=pipeline, finalizer=finalizer)
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "recording"
        assert body["schedule_id"] == "sch-1"

    def test_missing_schedule_is_404(self):
        pipeline = StubCapturePipeline()
        app, _, _ = _build(pipeline=pipeline)
        with TestClient(app) as client:
            r = client.post("/api/staff/recording/schedules/nope/record-now")
        assert r.status_code == 404

    def test_pipeline_raise_is_500(self):
        pipeline = StubCapturePipeline(raise_on_arm=RuntimeError("unreachable"))
        app, _, _ = _build(pipeline=pipeline, alert_sink=StubAlertSink())
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# List jobs / state filter / limit cap
# ---------------------------------------------------------------------------


class TestListJobs:
    def test_empty_list(self):
        client = _client()
        r = client.get("/api/staff/recording/jobs")
        assert r.status_code == 200
        assert r.json() == []

    def test_state_filter(self):
        pipeline = StubCapturePipeline()
        app, _, _ = _build(pipeline=pipeline)
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            client.post("/api/staff/recording/schedules/sch-1/record-now")
            r = client.get("/api/staff/recording/jobs?state=recording")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["state"] == "recording"

    def test_schedule_id_filter(self):
        pipeline = StubCapturePipeline()
        app, _, _ = _build(pipeline=pipeline)
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            client.post("/api/staff/recording/schedules/sch-1/record-now")
            r = client.get("/api/staff/recording/jobs?schedule_id=sch-1")
            assert r.status_code == 200
            assert len(r.json()) == 1
            r = client.get("/api/staff/recording/jobs?schedule_id=other")
            assert r.status_code == 200
            assert r.json() == []

    def test_limit_clamped_at_hard_cap(self):
        client = _client()
        # 10_000 > 1_000 hard cap; the endpoint should not 422 — it
        # should clamp silently.
        r = client.get("/api/staff/recording/jobs?limit=10000")
        assert r.status_code == 200

    def test_limit_zero_is_422(self):
        client = _client()
        r = client.get("/api/staff/recording/jobs?limit=0")
        assert r.status_code == 422

    def test_limit_negative_is_422(self):
        client = _client()
        r = client.get("/api/staff/recording/jobs?limit=-1")
        assert r.status_code == 422

    # T-8 fix
    def test_invalid_state_is_422(self):
        client = _client()
        r = client.get("/api/staff/recording/jobs?state=garbage")
        assert r.status_code == 422

    # T-9 fix
    def test_limit_non_integer_is_422(self):
        client = _client()
        r = client.get("/api/staff/recording/jobs?limit=abc")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Stop job
# ---------------------------------------------------------------------------


class TestStopJob:
    def test_happy_path_returns_done(self):
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        app, _, _ = _build(pipeline=pipeline, finalizer=finalizer)
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
            job_id = r.json()["job_id"]
            r = client.post(f"/api/staff/recording/jobs/{job_id}/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "done"

    def test_missing_is_404(self):
        pipeline = StubCapturePipeline()
        app, _, _ = _build(pipeline=pipeline, finalizer=StubFinalizer())
        with TestClient(app) as client:
            r = client.post("/api/staff/recording/jobs/nope/stop")
        assert r.status_code == 404

    def test_terminal_state_is_409(self):
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        app, _, _ = _build(pipeline=pipeline, finalizer=finalizer)
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
            job_id = r.json()["job_id"]
            client.post(f"/api/staff/recording/jobs/{job_id}/stop")  # → done
            r = client.post(f"/api/staff/recording/jobs/{job_id}/stop")
        assert r.status_code == 409

    def test_pipeline_raise_during_stop_returns_failed_job_not_500(self):
        pipeline = StubCapturePipeline()
        finalizer = StubFinalizer()
        app, _store, _svc = _build(
            pipeline=pipeline, finalizer=finalizer, alert_sink=StubAlertSink()
        )
        with TestClient(app) as client:
            client.post("/api/staff/recording/schedules", json=_schedule_payload())
            r = client.post("/api/staff/recording/schedules/sch-1/record-now")
            job_id = r.json()["job_id"]
            # Swap the pipeline's stop into a raise.
            pipeline._raise_stop = RuntimeError("encoder hung")  # type: ignore[attr-defined]
            r = client.post(f"/api/staff/recording/jobs/{job_id}/stop")
        assert r.status_code == 200
        assert r.json()["state"] == "failed"
        assert r.json()["bytes_written"] == 0
        assert "Recording could not complete the stop step" in r.json()["failure_reason"]
        assert "RuntimeError" not in r.json()["failure_reason"]


# ---------------------------------------------------------------------------
# OpenAPI x-required-roles mirror
# ---------------------------------------------------------------------------


class TestOpenApi:
    def test_x_required_roles_present_on_write_routes(self):
        app, _, _ = _build()
        schema = app.openapi()
        post = schema["paths"]["/api/staff/recording/schedules"]["post"]
        assert "x-required-roles" in post
        assert set(post["x-required-roles"]) == {"setup_admin", "meeting_operator"}

    def test_x_required_roles_present_on_read_routes(self):
        app, _, _ = _build()
        schema = app.openapi()
        get = schema["paths"]["/api/staff/recording/schedules"]["get"]
        assert "x-required-roles" in get
        assert set(get["x-required-roles"]) == {
            "setup_admin",
            "meeting_operator",
            "support_admin",
        }
