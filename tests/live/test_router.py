# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP contract tests for civiccast.live.router.

Sprint 0.4 Slice 1 Commit 6. Locks the staff API surface for the live
module:

* POST   /api/staff/live/sessions                                201/409/422/503
* GET    /api/staff/live/sessions/{id}                           200/404/503
* POST   /api/staff/live/sessions/{id}/start-preflight           200/404/409/503
* POST   /api/staff/live/sessions/{id}/preflight                 200/422/503
* POST   /api/staff/live/sessions/{id}/go-on-air                 200/404/409/503
* POST   /api/staff/live/sessions/{id}/end-broadcast             200/404/409/503
* POST   /api/staff/live/sources                                 201/409/422/503
* GET    /api/staff/live/sources?channel_id=                     200/503
* GET    /api/staff/live/sources/{id}                            200/404/503
* POST   /api/staff/live/recording-targets                       201/409/422/503
* GET    /api/staff/live/recording-targets                       200/503
* GET    /api/staff/live/recording-targets/{id}                  200/404/503

Tests use FastAPI's TestClient with dependency overrides pointing at
SQLite-backed in-process stores. Real-Postgres concurrency proofs for
the underlying state machine live in :mod:`tests.live.test_real_postgres`;
this module exercises the HTTP-contract surface.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

# Importing live + schedule modules registers their SA classes against
# Base.metadata before create_all runs. The schedule import is load-
# bearing on SQLite (it owns the connect-time ATTACH ':memory:' AS
# civiccast hook that lets the schema-qualified CREATE TABLE
# civiccast.live_sessions resolve).
import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.app import create_app
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.router import get_egress_store
from civiccast.egress.store import InMemoryEgressStore
from civiccast.live.finalization_worker import LiveFinalizationWorker
from civiccast.live.models import LiveFinalizationJob
from civiccast.live.preflight import (
    PREFLIGHT_CHECK_LIVE_SOURCE,
    PREFLIGHT_CHECK_OPERATOR_CONFIRM,
    PREFLIGHT_CHECK_RECORDING_TARGET,
    PREFLIGHT_STATUS_FAIL,
    PREFLIGHT_STATUS_PASS,
    PreflightEvaluator,
)
from civiccast.live.router import (
    get_live_finalization_worker,
    get_live_relay_config_store,
    get_live_session_store,
    get_live_source_store,
    get_preflight_evaluator,
    get_recording_target_store,
)
from civiccast.live.store import (
    LiveRelayConfigStore,
    LiveSessionStore,
    LiveSourceStore,
    RecordingTargetStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Per-test ephemeral SQLite engine shared across TestClient threads.

    FastAPI's TestClient runs synchronous handlers on a thread pool;
    sharing a SQLite ``:memory:`` engine across threads requires
    ``check_same_thread=False`` plus ``StaticPool`` so all sessions
    reuse the single connection where ``Base.metadata.create_all`` ran
    and where the schedule module's connect-time ATTACH listener
    registered the ``civiccast`` schema. Without this, request threads
    get fresh empty connections and the schema-qualified tables are
    invisible (the SQLite ``:memory:`` database is per-connection).
    """
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
    """A context-managed session factory bound to the per-test engine."""

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A TestClient with the four live-router DI seams overridden to real
    SQLite-backed stores.

    The umbrella ``create_app()`` wires the schedule + vod routers too;
    those use their own DI seams and are exercised in their own test
    suites. This fixture only overrides the four live seams; the others
    fall through to their defaults (which return None and surface as
    503 for any caller -- not relevant to live-router tests).
    """
    app = create_app()

    live_session_store = LiveSessionStore(session_factory)
    live_source_store = LiveSourceStore(session_factory)
    relay_config_store = LiveRelayConfigStore(session_factory)
    recording_target_store = RecordingTargetStore(session_factory)
    preflight_evaluator = PreflightEvaluator(
        session_factory,
        source_probe=lambda source: (True, f"Source {source.live_source_id!r} delivered media."),
    )
    finalization_worker = LiveFinalizationWorker(session_factory)

    app.dependency_overrides[get_live_session_store] = lambda: live_session_store
    app.dependency_overrides[get_live_source_store] = lambda: live_source_store
    app.dependency_overrides[get_live_relay_config_store] = lambda: relay_config_store
    app.dependency_overrides[get_recording_target_store] = lambda: recording_target_store
    app.dependency_overrides[get_preflight_evaluator] = lambda: preflight_evaluator
    app.dependency_overrides[get_live_finalization_worker] = lambda: finalization_worker

    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


# Helpers -------------------------------------------------------------------


def _session_payload(
    live_session_id: str = "council-2026-05-15",
    *,
    channel_id: str = "gov-ch12",
    title: str = "City Council Meeting",
) -> dict[str, object]:
    return {
        "live_session_id": live_session_id,
        "channel_id": channel_id,
        "title": title,
    }


def _source_payload(
    live_source_id: str = "rtmp-cam-01",
    *,
    channel_id: str = "gov-ch12",
    source_type: str = "rtmp",
    endpoint_url: str = "rtmp://encoder.local/live/stream",
) -> dict[str, object]:
    return {
        "live_source_id": live_source_id,
        "channel_id": channel_id,
        "name": f"{live_source_id} (test)",
        "source_type": source_type,
        "endpoint_url": endpoint_url,
    }


def _target_payload(
    recording_target_id: str = "fs-primary",
    *,
    target_uri: str = "file:///srv/civiccast/recordings",
) -> dict[str, object]:
    return {
        "recording_target_id": recording_target_id,
        "name": f"{recording_target_id} (test)",
        "target_uri": target_uri,
    }


def _relay_payload(
    relay_config_id: str = "project-relay",
    *,
    channel_id: str = "gov-ch12",
    mode: str = "cloud_rtmp_relay",
    endpoint_url: str = "rtmps://relay.example/live/gov",
    provider: str | None = "project-hosted",
    enabled: bool = True,
) -> dict[str, object]:
    return {
        "relay_config_id": relay_config_id,
        "channel_id": channel_id,
        "name": f"{relay_config_id} (test)",
        "mode": mode,
        "endpoint_url": endpoint_url,
        "provider": provider,
        "enabled": enabled,
    }


def _seed_session(client: TestClient, **overrides: object) -> str:
    """Create a session via the API and return its id."""
    payload = _session_payload(**overrides)  # type: ignore[arg-type]
    r = client.post("/api/staff/live/sessions", json=payload)
    assert r.status_code == 201, r.text
    return str(payload["live_session_id"])


def _seed_source_and_target(
    client: TestClient,
    *,
    channel_id: str = "gov-ch12",
    live_source_id: str = "rtmp-cam-01",
    seed_target: bool = True,
) -> None:
    """Prime a LiveSource + RecordingTarget so the pre-flight evaluator passes."""
    r = client.post(
        "/api/staff/live/sources",
        json=_source_payload(live_source_id=live_source_id, channel_id=channel_id),
    )
    assert r.status_code == 201, r.text
    if seed_target:
        r = client.post("/api/staff/live/recording-targets", json=_target_payload())
        assert r.status_code == 201, r.text


def _all_pass_inputs(
    live_session_id: str,
    *,
    live_source_id: str = "rtmp-cam-01",
    operator_confirmed: bool = True,
) -> dict[str, object]:
    return {
        "live_session_id": live_session_id,
        "live_source_id": live_source_id,
        "network_reachable": True,
        "storage_free_bytes": 200 * (1024**3),
        "ai_runtime_ready": True,
        "operator_confirmed": operator_confirmed,
    }


# ===========================================================================
# Session create + read
# ===========================================================================


class TestCreateSession:
    """Locks: POST /sessions creates at state 'idle' and rejects duplicates + invalid slugs."""

    def test_201_returns_canonical_session(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/sessions", json=_session_payload())
        assert r.status_code == 201
        body = r.json()
        assert body["live_session_id"] == "council-2026-05-15"
        assert body["state"] == "idle"
        assert body["started_at"] is None
        assert body["ended_at"] is None

    def test_409_on_duplicate_id(self, client: TestClient) -> None:
        _seed_session(client)
        r = client.post("/api/staff/live/sessions", json=_session_payload())
        assert r.status_code == 409
        assert "council-2026-05-15" in r.json()["detail"]

    def test_422_on_invalid_slug(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/sessions",
            json=_session_payload(live_session_id="UPPERCASE-NOT-ALLOWED"),
        )
        assert r.status_code == 422

    def test_422_on_missing_required_field(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/sessions",
            json={"channel_id": "gov-ch12", "title": "x"},
        )
        assert r.status_code == 422


class TestGetSession:
    """Locks: GET /sessions/{id} returns 200 or 404."""

    def test_200_returns_session(self, client: TestClient) -> None:
        _seed_session(client)
        r = client.get("/api/staff/live/sessions/council-2026-05-15")
        assert r.status_code == 200
        assert r.json()["live_session_id"] == "council-2026-05-15"

    def test_404_when_missing(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/sessions/missing")
        assert r.status_code == 404
        assert "missing" in r.json()["detail"]


class TestPublicCurrentLive:
    """Locks: residents see the current on-air session and no staff-only fields."""

    def test_offline_when_no_on_air_session(self, client: TestClient) -> None:
        r = client.get("/api/public/live/current")
        assert r.status_code == 200
        assert r.json() == {
            "state": "offline",
            "live_session_id": None,
            "channel_id": None,
            "title": None,
            "started_at": None,
            "manifest_url": None,
        }

    def test_returns_newest_on_air_session_with_optional_manifest_url(
        self, client: TestClient
    ) -> None:
        _seed_source_and_target(client)
        _seed_session(client, live_session_id="council-older", title="Older meeting")
        _seed_session(client, live_session_id="council-newer", title="Newer meeting")
        for session_id in ("council-older", "council-newer"):
            assert (
                client.post(f"/api/staff/live/sessions/{session_id}/start-preflight").status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/staff/live/sessions/{session_id}/go-on-air",
                    json=_all_pass_inputs(session_id),
                ).status_code
                == 200
            )

        r = client.get(
            "/api/public/live/current",
            params={"manifest_url": "https://cdn.example/live/playlist.m3u8"},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "on_air"
        assert body["live_session_id"] == "council-newer"
        assert body["title"] == "Newer meeting"
        assert body["manifest_url"] == "https://cdn.example/live/playlist.m3u8"
        assert "notes" not in body

    def test_defaults_to_local_live_url_when_hls_sink_configured(self, client: TestClient) -> None:
        egress_store = InMemoryEgressStore()
        egress_store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="hls", label="Web", uri="/var/civiccast/live/gov-ch12")],
            )
        )
        client.app.dependency_overrides[get_egress_store] = lambda: egress_store  # type: ignore[attr-defined]

        _seed_source_and_target(client)
        _seed_session(client)
        assert (
            client.post("/api/staff/live/sessions/council-2026-05-15/start-preflight").status_code
            == 200
        )
        assert (
            client.post(
                "/api/staff/live/sessions/council-2026-05-15/go-on-air",
                json=_all_pass_inputs("council-2026-05-15"),
            ).status_code
            == 200
        )

        r = client.get("/api/public/live/current")

        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "on_air"
        assert body["manifest_url"] == "http://127.0.0.1:8000/media/live/gov-ch12/playlist.m3u8"

    def test_explicit_manifest_url_param_still_wins_over_local_default(
        self, client: TestClient
    ) -> None:
        egress_store = InMemoryEgressStore()
        egress_store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="hls", label="Web", uri="/var/civiccast/live/gov-ch12")],
            )
        )
        client.app.dependency_overrides[get_egress_store] = lambda: egress_store  # type: ignore[attr-defined]

        _seed_source_and_target(client)
        _seed_session(client)
        assert (
            client.post("/api/staff/live/sessions/council-2026-05-15/start-preflight").status_code
            == 200
        )
        assert (
            client.post(
                "/api/staff/live/sessions/council-2026-05-15/go-on-air",
                json=_all_pass_inputs("council-2026-05-15"),
            ).status_code
            == 200
        )

        r = client.get(
            "/api/public/live/current",
            params={"manifest_url": "https://cdn.example/live/playlist.m3u8"},
        )

        assert r.status_code == 200
        assert r.json()["manifest_url"] == "https://cdn.example/live/playlist.m3u8"

    def test_dangerous_manifest_url_override_is_rejected(self, client: TestClient) -> None:
        # /current is public + unauthenticated; a javascript:/data:/relative/
        # malformed override must NOT be echoed in the resident-facing
        # manifest_url field. It is dropped and resolution falls through to the
        # local media-router URL (fail safe, not an error).
        egress_store = InMemoryEgressStore()
        egress_store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="hls", label="Web", uri="/var/civiccast/live/gov-ch12")],
            )
        )
        client.app.dependency_overrides[get_egress_store] = lambda: egress_store  # type: ignore[attr-defined]

        _seed_source_and_target(client)
        _seed_session(client)
        assert (
            client.post("/api/staff/live/sessions/council-2026-05-15/start-preflight").status_code
            == 200
        )
        assert (
            client.post(
                "/api/staff/live/sessions/council-2026-05-15/go-on-air",
                json=_all_pass_inputs("council-2026-05-15"),
            ).status_code
            == 200
        )

        for bad in ("javascript:alert(1)", "data:text/html,x", "not a url", "/relative.m3u8"):
            r = client.get("/api/public/live/current", params={"manifest_url": bad})
            assert r.status_code == 200
            resolved = r.json()["manifest_url"]
            assert resolved != bad, f"dangerous override {bad!r} was echoed back"
            assert resolved.endswith("/media/live/gov-ch12/playlist.m3u8")  # fell through to local

    def test_no_hls_sink_configured_leaves_manifest_url_null(self, client: TestClient) -> None:
        egress_store = InMemoryEgressStore()
        egress_store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="file", label="CI", uri="build/out.ts")],
            )
        )
        client.app.dependency_overrides[get_egress_store] = lambda: egress_store  # type: ignore[attr-defined]

        _seed_source_and_target(client)
        _seed_session(client)
        assert (
            client.post("/api/staff/live/sessions/council-2026-05-15/start-preflight").status_code
            == 200
        )
        assert (
            client.post(
                "/api/staff/live/sessions/council-2026-05-15/go-on-air",
                json=_all_pass_inputs("council-2026-05-15"),
            ).status_code
            == 200
        )

        r = client.get("/api/public/live/current")

        assert r.status_code == 200
        assert r.json()["manifest_url"] is None

    def test_channel_filter_limits_current_session(self, client: TestClient) -> None:
        _seed_source_and_target(client, channel_id="gov", live_source_id="gov-camera")
        _seed_source_and_target(
            client,
            channel_id="schools",
            live_source_id="schools-camera",
            seed_target=False,
        )
        _seed_session(
            client,
            live_session_id="general-meeting",
            channel_id="gov",
            title="Government meeting",
        )
        _seed_session(
            client,
            live_session_id="school-meeting",
            channel_id="schools",
            title="School board",
        )
        for session_id in ("general-meeting", "school-meeting"):
            assert (
                client.post(f"/api/staff/live/sessions/{session_id}/start-preflight").status_code
                == 200
            )
            assert (
                client.post(
                    f"/api/staff/live/sessions/{session_id}/go-on-air",
                    json=_all_pass_inputs(
                        session_id,
                        live_source_id=(
                            "gov-camera" if session_id == "general-meeting" else "schools-camera"
                        ),
                    ),
                ).status_code
                == 200
            )

        r = client.get("/api/public/live/current", params={"channel_id": "gov"})

        assert r.status_code == 200
        assert r.json()["live_session_id"] == "general-meeting"


# ===========================================================================
# State transitions
# ===========================================================================


class TestStartPreflight:
    """Locks: POST /sessions/{id}/start-preflight advances idle -> preflight."""

    def test_200_idle_to_preflight(self, client: TestClient) -> None:
        sid = _seed_session(client)
        r = client.post(f"/api/staff/live/sessions/{sid}/start-preflight")
        assert r.status_code == 200
        assert r.json()["state"] == "preflight"

    def test_404_when_session_missing(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/sessions/nope/start-preflight")
        assert r.status_code == 404

    def test_409_when_already_in_preflight(self, client: TestClient) -> None:
        sid = _seed_session(client)
        client.post(f"/api/staff/live/sessions/{sid}/start-preflight")
        r = client.post(f"/api/staff/live/sessions/{sid}/start-preflight")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["current_state"] == "preflight"
        assert detail["attempted_transition"] == "start_preflight"
        assert detail["live_session_id"] == sid


class TestGoOnAir:
    """Locks: POST /sessions/{id}/go-on-air advances preflight -> on_air + stamps started_at."""

    def test_200_preflight_to_on_air_stamps_started_at(self, client: TestClient) -> None:
        sid = _seed_session(client)
        _seed_source_and_target(client)
        client.post(f"/api/staff/live/sessions/{sid}/start-preflight")
        r = client.post(
            f"/api/staff/live/sessions/{sid}/go-on-air",
            json=_all_pass_inputs(sid),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "on_air"
        assert body["started_at"] is not None

    def test_404_when_session_missing(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/sessions/nope/go-on-air",
            json=_all_pass_inputs("nope"),
        )
        assert r.status_code == 404

    def test_409_when_session_in_idle(self, client: TestClient) -> None:
        sid = _seed_session(client)
        r = client.post(
            f"/api/staff/live/sessions/{sid}/go-on-air",
            json=_all_pass_inputs(sid),
        )
        assert r.status_code == 409
        assert r.json()["detail"]["current_state"] == "idle"

    def test_409_when_server_cannot_probe_source_media(
        self, client: TestClient, session_factory
    ) -> None:  # type: ignore[no-untyped-def]
        client.app.dependency_overrides[get_preflight_evaluator] = lambda: PreflightEvaluator(
            session_factory
        )
        sid = _seed_session(client, live_session_id="unprobed-source")
        _seed_source_and_target(client)
        client.post(f"/api/staff/live/sessions/{sid}/start-preflight")

        response = client.post(
            f"/api/staff/live/sessions/{sid}/go-on-air",
            json=_all_pass_inputs(sid),
        )

        assert response.status_code == 409
        assert "server-side media probe" in str(response.json()["detail"])
        current = client.get(f"/api/staff/live/sessions/{sid}")
        assert current.json()["state"] == "preflight"

    def test_requires_a_fresh_successful_source_bound_preflight(
        self, client: TestClient, session_factory
    ) -> None:  # type: ignore[no-untyped-def]
        probe_results = iter([(True, "frames detected"), (False, "source stopped")])
        client.app.dependency_overrides[get_preflight_evaluator] = lambda: PreflightEvaluator(
            session_factory,
            source_probe=lambda _source: next(probe_results),
        )
        sid = _seed_session(client, live_session_id="source-stops-before-air")
        _seed_source_and_target(client)
        client.post(f"/api/staff/live/sessions/{sid}/start-preflight")

        advisory = client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json=_all_pass_inputs(sid),
        )
        assert advisory.status_code == 200
        assert advisory.json()["ready"] is True

        response = client.post(
            f"/api/staff/live/sessions/{sid}/go-on-air",
            json=_all_pass_inputs(sid),
        )

        assert response.status_code == 409
        assert "source stopped" in str(response.json()["detail"])
        assert client.get(f"/api/staff/live/sessions/{sid}").json()["state"] == "preflight"


class TestEndBroadcast:
    """Locks: POST /sessions/{id}/end-broadcast advances on_air -> ending + stamps ended_at."""

    def test_200_on_air_to_ending_stamps_ended_at(self, client: TestClient) -> None:
        sid = _seed_session(client)
        _seed_source_and_target(client)
        client.post(f"/api/staff/live/sessions/{sid}/start-preflight")
        client.post(
            f"/api/staff/live/sessions/{sid}/go-on-air",
            json=_all_pass_inputs(sid),
        )
        r = client.post(f"/api/staff/live/sessions/{sid}/end-broadcast")
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == "ending"
        assert body["ended_at"] is not None

    def test_404_when_session_missing(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/sessions/nope/end-broadcast")
        assert r.status_code == 404

    def test_409_when_session_not_on_air(self, client: TestClient) -> None:
        sid = _seed_session(client)
        # Still in idle.
        r = client.post(f"/api/staff/live/sessions/{sid}/end-broadcast")
        assert r.status_code == 409
        assert r.json()["detail"]["attempted_transition"] == "end_broadcast"


# ===========================================================================
# Finalization worker status
# ===========================================================================


class TestFinalizationStatus:
    """Locks: staff can query persisted finalization worker states."""

    def test_list_finalization_statuses(self, client: TestClient, engine: Engine) -> None:
        with Session(bind=engine) as session:
            session.add(LiveFinalizationJob(live_session_id="pending-session"))
            session.add(
                LiveFinalizationJob(
                    live_session_id="failed-session",
                    state="failed",
                    attempts=3,
                    failure_reason="encode failed",
                )
            )
            session.commit()

        r = client.get("/api/staff/live/finalizations")

        assert r.status_code == 200
        by_id = {row["live_session_id"]: row for row in r.json()}
        assert by_id["pending-session"]["state"] == "pending"
        assert by_id["failed-session"]["state"] == "failed"
        assert by_id["failed-session"]["failure_reason"] == "encode failed"

    def test_get_one_finalization_status(self, client: TestClient, engine: Engine) -> None:
        with Session(bind=engine) as session:
            session.add(LiveFinalizationJob(live_session_id="completed-session", state="completed"))
            session.commit()

        r = client.get("/api/staff/live/sessions/completed-session/finalization")

        assert r.status_code == 200
        assert r.json()["state"] == "completed"

    def test_get_one_finalization_status_404_when_missing(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/sessions/missing/finalization")

        assert r.status_code == 404


# ===========================================================================
# Pre-flight evaluator
# ===========================================================================


class TestEvaluatePreflight:
    """Locks: POST /sessions/{id}/preflight runs the evaluator without
    touching the LiveSession state machine."""

    def test_200_all_pass_returns_ready_true(self, client: TestClient) -> None:
        sid = _seed_session(client)
        _seed_source_and_target(client)
        r = client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json=_all_pass_inputs(sid),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["live_session_id"] == sid
        # Required checks pass.
        by_name = {c["name"]: c for c in body["checks"]}
        assert by_name[PREFLIGHT_CHECK_LIVE_SOURCE]["status"] == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_RECORDING_TARGET]["status"] == PREFLIGHT_STATUS_PASS
        assert by_name[PREFLIGHT_CHECK_OPERATOR_CONFIRM]["status"] == PREFLIGHT_STATUS_PASS

    def test_200_operator_not_confirmed_returns_ready_false(self, client: TestClient) -> None:
        sid = _seed_session(client)
        _seed_source_and_target(client)
        r = client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json=_all_pass_inputs(sid, operator_confirmed=False),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is False
        by_name = {c["name"]: c for c in body["checks"]}
        assert by_name[PREFLIGHT_CHECK_OPERATOR_CONFIRM]["status"] == PREFLIGHT_STATUS_FAIL

    def test_evaluator_does_not_advance_state(self, client: TestClient) -> None:
        sid = _seed_session(client)
        _seed_source_and_target(client)
        client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json=_all_pass_inputs(sid),
        )
        r = client.get(f"/api/staff/live/sessions/{sid}")
        assert r.json()["state"] == "idle"

    def test_422_when_path_id_mismatches_body_id(self, client: TestClient) -> None:
        sid = _seed_session(client)
        r = client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json=_all_pass_inputs("different-id"),
        )
        assert r.status_code == 422
        assert "does not match" in r.json()["detail"]

    def test_422_on_invalid_inputs_payload(self, client: TestClient) -> None:
        sid = _seed_session(client)
        # ``storage_free_bytes`` must be non-negative.
        r = client.post(
            f"/api/staff/live/sessions/{sid}/preflight",
            json={
                "live_session_id": sid,
                "network_reachable": True,
                "storage_free_bytes": -1,
                "ai_runtime_ready": True,
                "operator_confirmed": True,
            },
        )
        assert r.status_code == 422


# ===========================================================================
# LiveSource CRUD
# ===========================================================================


class TestCreateSource:
    """Locks: POST /sources creates and rejects duplicates."""

    def test_201_returns_canonical_source(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/sources", json=_source_payload())
        assert r.status_code == 201
        body = r.json()
        assert body["live_source_id"] == "rtmp-cam-01"
        assert body["source_type"] == "rtmp"

    def test_409_on_duplicate_id(self, client: TestClient) -> None:
        client.post("/api/staff/live/sources", json=_source_payload())
        r = client.post("/api/staff/live/sources", json=_source_payload())
        assert r.status_code == 409

    def test_422_on_invalid_source_type(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/sources",
            json=_source_payload(source_type="hdmi"),
        )
        assert r.status_code == 422


class TestListSources:
    """Locks: GET /sources lists every source, supports ?channel_id= filter."""

    def test_empty_returns_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/sources")
        assert r.status_code == 200
        assert r.json() == []

    def test_no_filter_returns_every_row(self, client: TestClient) -> None:
        client.post("/api/staff/live/sources", json=_source_payload("cam-a"))
        client.post(
            "/api/staff/live/sources",
            json=_source_payload("cam-b", channel_id="gov-ch14"),
        )
        r = client.get("/api/staff/live/sources")
        assert {row["live_source_id"] for row in r.json()} == {"cam-a", "cam-b"}

    def test_channel_filter_limits_results(self, client: TestClient) -> None:
        client.post("/api/staff/live/sources", json=_source_payload("cam-a"))
        client.post(
            "/api/staff/live/sources",
            json=_source_payload("cam-b", channel_id="gov-ch14"),
        )
        r = client.get("/api/staff/live/sources", params={"channel_id": "gov-ch12"})
        ids = [row["live_source_id"] for row in r.json()]
        assert ids == ["cam-a"]


class TestGetSource:
    """Locks: GET /sources/{id} returns 200 or 404."""

    def test_200_returns_source(self, client: TestClient) -> None:
        client.post("/api/staff/live/sources", json=_source_payload())
        r = client.get("/api/staff/live/sources/rtmp-cam-01")
        assert r.status_code == 200
        assert r.json()["live_source_id"] == "rtmp-cam-01"

    def test_404_when_missing(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/sources/missing")
        assert r.status_code == 404


# ===========================================================================
# Remote ingest / relay target CRUD
# ===========================================================================


class TestGetIngestPlan:
    """Locks: GET /ingest-plan preserves local default and optional relay paths."""

    def test_local_default_when_no_relay_configs(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/ingest-plan", params={"channel_id": "gov-ch12"})
        assert r.status_code == 200
        body = r.json()
        assert body["channel_id"] == "gov-ch12"
        assert body["recommended_path_id"] == "gov-ch12:local"
        assert body["local_default"]["mode"] == "local_rtmp"
        assert body["local_default"]["requires_inbound_firewall"] is False
        assert body["relay_paths"] == []

    def test_ready_relay_appears_as_outbound_only_path(self, client: TestClient) -> None:
        client.post("/api/staff/live/relay-configs", json=_relay_payload())
        client.post(
            "/api/staff/live/relay-configs/project-relay/health",
            json={"health_state": "ready"},
        )

        r = client.get("/api/staff/live/ingest-plan", params={"channel_id": "gov-ch12"})

        assert r.status_code == 200
        body = r.json()
        assert body["recommended_path_id"] == "project-relay"
        assert body["relay_paths"][0]["outbound_only"] is True
        assert body["relay_paths"][0]["requires_inbound_firewall"] is False
        assert "credentials_handle" not in body["relay_paths"][0]


class TestCreateRelayConfig:
    """Locks: POST /relay-configs creates optional remote ingest targets."""

    def test_201_returns_canonical_relay_config(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/relay-configs", json=_relay_payload())
        assert r.status_code == 201
        body = r.json()
        assert body["relay_config_id"] == "project-relay"
        assert body["mode"] == "cloud_rtmp_relay"
        assert body["health_state"] == "not_configured"
        assert body["enabled"] is True

    def test_409_on_duplicate_id(self, client: TestClient) -> None:
        client.post("/api/staff/live/relay-configs", json=_relay_payload())
        r = client.post("/api/staff/live/relay-configs", json=_relay_payload())
        assert r.status_code == 409

    def test_422_on_invalid_mode(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/relay-configs",
            json=_relay_payload(mode="vpn_required"),
        )
        assert r.status_code == 422


class TestListRelayConfigs:
    """Locks: GET /relay-configs lists and filters optional relay targets."""

    def test_empty_returns_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/relay-configs")
        assert r.status_code == 200
        assert r.json() == []

    def test_channel_and_enabled_filters(self, client: TestClient) -> None:
        client.post("/api/staff/live/relay-configs", json=_relay_payload("active-gov"))
        client.post(
            "/api/staff/live/relay-configs",
            json=_relay_payload("disabled-gov", enabled=False),
        )
        client.post(
            "/api/staff/live/relay-configs",
            json=_relay_payload("active-school", channel_id="schools"),
        )

        r = client.get(
            "/api/staff/live/relay-configs",
            params={"channel_id": "gov-ch12", "enabled": "true"},
        )

        assert r.status_code == 200
        assert [row["relay_config_id"] for row in r.json()] == ["active-gov"]


class TestGetRelayConfig:
    """Locks: GET /relay-configs/{id} returns 200 or 404."""

    def test_200_returns_relay_config(self, client: TestClient) -> None:
        client.post("/api/staff/live/relay-configs", json=_relay_payload())
        r = client.get("/api/staff/live/relay-configs/project-relay")
        assert r.status_code == 200
        assert r.json()["provider"] == "project-hosted"

    def test_404_when_missing(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/relay-configs/missing")
        assert r.status_code == 404


class TestUpdateRelayHealth:
    """Locks: station probes can update relay health through staff API."""

    def test_200_updates_health(self, client: TestClient) -> None:
        client.post("/api/staff/live/relay-configs", json=_relay_payload())

        r = client.post(
            "/api/staff/live/relay-configs/project-relay/health",
            json={"health_state": "ready", "notes": "Probe OK"},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["health_state"] == "ready"
        assert body["last_heartbeat_at"] is not None
        assert body["notes"] == "Probe OK"

    def test_404_when_missing(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/relay-configs/missing/health",
            json={"health_state": "offline"},
        )
        assert r.status_code == 404


# ===========================================================================
# RecordingTarget CRUD
# ===========================================================================


class TestCreateRecordingTarget:
    """Locks: POST /recording-targets creates and rejects duplicates."""

    def test_201_returns_canonical_target(self, client: TestClient) -> None:
        r = client.post("/api/staff/live/recording-targets", json=_target_payload())
        assert r.status_code == 201
        body = r.json()
        assert body["recording_target_id"] == "fs-primary"

    def test_409_on_duplicate_id(self, client: TestClient) -> None:
        client.post("/api/staff/live/recording-targets", json=_target_payload())
        r = client.post("/api/staff/live/recording-targets", json=_target_payload())
        assert r.status_code == 409

    def test_201_accepts_windows_drive_path(self, client: TestClient) -> None:
        r = client.post(
            "/api/staff/live/recording-targets",
            json=_target_payload(
                recording_target_id="fs-windows",
                target_uri="C:\\recordings",
            ),
        )
        assert r.status_code == 201

    @pytest.mark.parametrize(
        "bad_uri",
        [
            "s3://civiccast-archive/2026/",
            "http://example.org/recordings",
            "relative/path",
            "not a uri",
        ],
    )
    def test_422_for_uris_the_worker_cannot_resolve(self, client: TestClient, bad_uri: str) -> None:
        """QA-007/QA-003: unusable target_uri values fail loudly at create
        time with copy pointing at the file:// form, instead of silently
        wedging finalization at scan time."""

        r = client.post(
            "/api/staff/live/recording-targets",
            json=_target_payload(recording_target_id="bad-target", target_uri=bad_uri),
        )
        assert r.status_code == 422
        assert "file://" in r.text


class TestListRecordingTargets:
    """Locks: GET /recording-targets returns every row."""

    def test_empty_returns_empty_list(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/recording-targets")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_every_row(self, client: TestClient) -> None:
        client.post(
            "/api/staff/live/recording-targets",
            json=_target_payload(recording_target_id="fs-primary"),
        )
        client.post(
            "/api/staff/live/recording-targets",
            json=_target_payload(
                recording_target_id="fs-archive",
                target_uri="file:///srv/civiccast/archive/2026/",
            ),
        )
        r = client.get("/api/staff/live/recording-targets")
        ids = {row["recording_target_id"] for row in r.json()}
        assert ids == {"fs-primary", "fs-archive"}


class TestGetRecordingTarget:
    """Locks: GET /recording-targets/{id} returns 200 or 404."""

    def test_200_returns_target(self, client: TestClient) -> None:
        client.post("/api/staff/live/recording-targets", json=_target_payload())
        r = client.get("/api/staff/live/recording-targets/fs-primary")
        assert r.status_code == 200
        assert r.json()["recording_target_id"] == "fs-primary"

    def test_404_when_missing(self, client: TestClient) -> None:
        r = client.get("/api/staff/live/recording-targets/missing")
        assert r.status_code == 404


# ===========================================================================
# 503 surface (DI seam returns None when DB not configured)
# ===========================================================================


class TestDatabaseNotConfigured:
    """Locks: each /api/staff/live/* endpoint returns 503 when its store
    dependency resolves to None (the import-time default before the app
    factory overrides the seam).

    A separate TestClient is built without dependency overrides so the
    default ``get_*_store`` callables (which return None) reach the
    handler unmodified.
    """

    @pytest.fixture
    def bare_client(self) -> Iterator[TestClient]:
        # Build the app under a working-tree posture where DATABASE_URL
        # is intentionally unset. ``create_app()`` reads the env var; an
        # unset DATABASE_URL means no dependency overrides for the live
        # seams, so the default get_*_store() callables (None) reach
        # the handler.
        import os

        prior_url = os.environ.pop("DATABASE_URL", None)
        try:
            app = create_app()
            with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
                yield c
        finally:
            if prior_url is not None:
                os.environ["DATABASE_URL"] = prior_url

    def test_503_on_create_session(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/sessions", json=_session_payload())
        assert r.status_code == 503
        assert "Durable storage is not ready" in r.json()["detail"]

    def test_503_on_get_session(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/sessions/any-id")
        assert r.status_code == 503

    def test_503_on_start_preflight(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/sessions/any-id/start-preflight")
        assert r.status_code == 503

    def test_503_on_evaluate_preflight(self, bare_client: TestClient) -> None:
        r = bare_client.post(
            "/api/staff/live/sessions/any-id/preflight",
            json=_all_pass_inputs("any-id"),
        )
        assert r.status_code == 503

    def test_503_on_go_on_air(self, bare_client: TestClient) -> None:
        r = bare_client.post(
            "/api/staff/live/sessions/any-id/go-on-air",
            json=_all_pass_inputs("any-id"),
        )
        assert r.status_code == 503

    def test_503_on_end_broadcast(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/sessions/any-id/end-broadcast")
        assert r.status_code == 503

    def test_503_on_list_finalizations(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/finalizations")
        assert r.status_code == 503

    def test_503_on_get_finalization(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/sessions/any-id/finalization")
        assert r.status_code == 503

    def test_503_on_create_source(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/sources", json=_source_payload())
        assert r.status_code == 503

    def test_503_on_list_sources(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/sources")
        assert r.status_code == 503

    def test_503_on_get_source(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/sources/any")
        assert r.status_code == 503

    def test_503_on_get_ingest_plan(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/ingest-plan", params={"channel_id": "gov-ch12"})
        assert r.status_code == 503

    def test_503_on_create_relay_config(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/relay-configs", json=_relay_payload())
        assert r.status_code == 503

    def test_503_on_list_relay_configs(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/relay-configs")
        assert r.status_code == 503

    def test_503_on_get_relay_config(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/relay-configs/any")
        assert r.status_code == 503

    def test_503_on_update_relay_health(self, bare_client: TestClient) -> None:
        r = bare_client.post(
            "/api/staff/live/relay-configs/any/health",
            json={"health_state": "offline"},
        )
        assert r.status_code == 503

    def test_503_on_create_recording_target(self, bare_client: TestClient) -> None:
        r = bare_client.post("/api/staff/live/recording-targets", json=_target_payload())
        assert r.status_code == 503

    def test_503_on_list_recording_targets(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/recording-targets")
        assert r.status_code == 503

    def test_503_on_get_recording_target(self, bare_client: TestClient) -> None:
        r = bare_client.get("/api/staff/live/recording-targets/any")
        assert r.status_code == 503
