# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP contract for the WP-07 live-source edit + probe surface.

* ``PATCH /api/staff/live/sources/{id}``   200 / 404 / 409 / 422 / 403 / 401
* ``POST  /api/staff/live/sources/{id}/probe`` 200 / 404 / 403 / 401

Role posture mirrors the surrounding router: editing a source is a
configuration change (``setup_admin``, same as create); checking whether a
source is delivering media is something the person running the meeting must be
able to do without a configuration role (``meeting_operator`` or
``setup_admin``).

A failed probe returns 200, not an error status. "This camera is not
answering" is a result the operator needs rendered on the source card with its
reason and next action -- an error status leaves the screen showing the
previous state, which is the failure mode the readiness work exists to remove.

The identity middleware harness follows ``tests/live/test_contribution_router.py``
so the real ``require_any_role`` gate actually runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.live.models
import civiccast.schedule.models  # noqa: F401
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.readiness_service import LiveSourceReadinessService
from civiccast.live.router import (
    get_live_relay_config_store,
    get_live_source_readiness_service,
    get_live_source_store,
    staff_router,
)
from civiccast.live.source_probe import ProbeObservation
from civiccast.live.store import LiveRelayConfigStore, LiveSourceStore

_ID = "council-encoder"
_ENDPOINT = "srt://0.0.0.0:9000?mode=listener"


@pytest.fixture
def engine() -> Iterator[Engine]:
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


def _client(
    engine: Engine,
    *,
    scopes: tuple[str, ...] | None = ("setup_admin", "meeting_operator"),
    probe_ok: bool = True,
) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    store = LiveSourceStore(factory)
    readiness = LiveSourceReadinessService(
        store,
        probe=lambda source, **_: ProbeObservation(
            ok=probe_ok,
            detail=(
                f"{source.name} is delivering video; server-side media probe passed."
                if probe_ok
                else f"{source.name} did not respond to a server-side media probe: "
                "Connection refused."
            ),
            error_code=None if probe_ok else "probe_refused",
        ),
    )

    app.include_router(staff_router)
    app.dependency_overrides[get_live_source_store] = lambda: store
    app.dependency_overrides[get_live_relay_config_store] = lambda: LiveRelayConfigStore(factory)
    app.dependency_overrides[get_live_source_readiness_service] = lambda: readiness
    return TestClient(app)


def _create(client: TestClient, *, source_type: str = "srt", endpoint: str = _ENDPOINT) -> None:
    r = client.post(
        "/api/staff/live/sources",
        json={
            "live_source_id": _ID,
            "channel_id": "gov-ch12",
            "name": "Council Room Encoder",
            "source_type": source_type,
            "endpoint_url": endpoint,
        },
    )
    assert r.status_code == 201, r.text


class TestProbeEndpoint:
    def test_200_and_the_source_becomes_ready(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        r = client.post(f"/api/staff/live/sources/{_ID}/probe")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["error_code"] is None
        assert body["source"]["readiness"] == "ready"
        assert body["source"]["probe_state"] == "ready"
        assert body["source"]["observation_age_seconds"] is not None

    def test_a_failed_check_is_200_with_a_reason_and_a_next_action(self, engine: Engine) -> None:
        client = _client(engine, probe_ok=False)
        _create(client)
        r = client.post(f"/api/staff/live/sources/{_ID}/probe")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert body["error_code"] == "probe_refused"
        assert "Connection refused" in body["detail"]
        source = body["source"]
        assert source["readiness"] == "failed"
        assert "Connection refused" in source["probe_detail"]
        assert "Check source" in source["next_action"]

    def test_404_for_a_missing_source(self, engine: Engine) -> None:
        assert _client(engine).post("/api/staff/live/sources/nope/probe").status_code == 404

    def test_401_without_an_identity(self, engine: Engine) -> None:
        client = _client(engine, scopes=None)
        assert client.post(f"/api/staff/live/sources/{_ID}/probe").status_code == 401

    def test_403_for_a_role_that_does_not_run_meetings(self, engine: Engine) -> None:
        client = _client(engine, scopes=("records_clerk",))
        assert client.post(f"/api/staff/live/sources/{_ID}/probe").status_code == 403

    def test_a_meeting_operator_may_check_a_source_without_a_setup_role(
        self, engine: Engine
    ) -> None:
        admin = _client(engine)
        _create(admin)
        operator = _client(engine, scopes=("meeting_operator",))
        assert operator.post(f"/api/staff/live/sources/{_ID}/probe").status_code == 200


class TestPatchEndpoint:
    def test_200_applies_the_edit(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        r = client.patch(f"/api/staff/live/sources/{_ID}", json={"name": "Chamber Encoder"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Chamber Encoder"
        assert r.json()["row_version"] == 2

    def test_an_endpoint_edit_clears_readiness_over_http(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        assert client.post(f"/api/staff/live/sources/{_ID}/probe").json()["ok"] is True

        r = client.patch(
            f"/api/staff/live/sources/{_ID}",
            json={"endpoint_url": "srt://0.0.0.0:9100?mode=listener"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["endpoint_url"] == "srt://0.0.0.0:9100?mode=listener"
        assert body["readiness"] == "never_probed"
        assert body["observation_age_seconds"] is None
        assert "Check source" in body["next_action"]

        # And the ingest plan agrees, so takeover cannot select it.
        plan = client.get("/api/staff/live/ingest-plan", params={"channel_id": "gov-ch12"}).json()
        assert plan["relay_paths"][0]["health_state"] == "not_configured"

    def test_404_for_a_missing_source(self, engine: Engine) -> None:
        client = _client(engine)
        assert client.patch("/api/staff/live/sources/nope", json={"name": "x"}).status_code == 404

    def test_409_on_a_stale_row_version_naming_both_versions(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        client.patch(f"/api/staff/live/sources/{_ID}", json={"name": "First operator wins"})
        r = client.patch(
            f"/api/staff/live/sources/{_ID}",
            json={"name": "Second operator", "expected_row_version": 1},
        )
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["expected_row_version"] == 1
        assert detail["current_row_version"] == 2
        assert "Reload the source" in detail["message"]

    def test_422_for_an_endpoint_that_does_not_match_the_type(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        r = client.patch(
            f"/api/staff/live/sources/{_ID}",
            json={"endpoint_url": "https://encoder.example/stream.m3u8"},
        )
        assert r.status_code == 422

    def test_422_when_only_the_type_changes_and_the_stored_endpoint_no_longer_fits(
        self, engine: Engine
    ) -> None:
        # The merged-row check: the body mentions no endpoint, so a naive
        # implementation would accept this and store an unopenable row.
        client = _client(engine)
        _create(client)
        r = client.patch(f"/api/staff/live/sources/{_ID}", json={"source_type": "rtsp"})
        assert r.status_code == 422
        assert "RTSP" in str(r.json()["detail"])

    def test_422_for_a_credential_on_a_type_that_cannot_run_one(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client, source_type="rtsp", endpoint="rtsp://camera.local/stream1")
        r = client.patch(
            f"/api/staff/live/sources/{_ID}", json={"credentials_handle": "cam-password"}
        )
        assert r.status_code == 422
        assert "RTSP camera" in str(r.json()["detail"])

    def test_422_for_an_empty_body(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        assert client.patch(f"/api/staff/live/sources/{_ID}", json={}).status_code == 422

    def test_401_without_an_identity(self, engine: Engine) -> None:
        client = _client(engine, scopes=None)
        assert client.patch(f"/api/staff/live/sources/{_ID}", json={"name": "x"}).status_code == (
            401
        )

    @pytest.mark.parametrize("scopes", [("meeting_operator",), ("records_clerk",)])
    def test_403_for_a_role_without_setup_admin(
        self, engine: Engine, scopes: tuple[str, ...]
    ) -> None:
        # Running a meeting lets you CHECK a source; it does not let you
        # reconfigure the station's inputs.
        client = _client(engine, scopes=scopes)
        assert client.patch(f"/api/staff/live/sources/{_ID}", json={"name": "x"}).status_code == (
            403
        )


class TestReadinessInTheResponse:
    def test_a_new_source_reports_never_probed_with_its_ttl(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client)
        body = client.get(f"/api/staff/live/sources/{_ID}").json()
        assert body["readiness"] == "never_probed"
        assert body["readiness_ttl_seconds"] == 30
        assert body["observation_age_seconds"] is None
        assert body["credentials_supported"] is True
        assert body["credentials_unsupported_reason"] is None

    def test_an_rtsp_source_reports_why_it_cannot_hold_a_credential(self, engine: Engine) -> None:
        client = _client(engine)
        _create(client, source_type="rtsp", endpoint="rtsp://camera.local/stream1")
        body = client.get(f"/api/staff/live/sources/{_ID}").json()
        assert body["credentials_supported"] is False
        reason = body["credentials_unsupported_reason"]
        assert reason and "password" in reason
