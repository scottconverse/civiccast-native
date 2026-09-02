# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the live-takeover endpoints (S5 slice 2).

A minimal app mounts the egress staff router, sets the operator identity via
middleware (so the real require_any_role gate runs with controlled scopes), and
overrides get_takeover_service with a real TakeoverService on thread-safe
SQLite + the in-memory egress store. Covers the role split, takeover/handback,
state, audit, and 409/404.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.egress.models  # noqa: F401 - register takeover_audit
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.router import get_takeover_service, staff_router
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.takeover_service import TakeoverService
from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
from civiccast.live.models import LiveSourceResponse
from civiccast.live.relay import build_ingest_plan


def _ready_source(channel_id: str) -> LiveSourceResponse:
    """A configured LiveSource, standing in for what an operator would add
    via Run Meeting.

    Bug B5: build_ingest_plan's local_default no longer claims ready for an
    address nothing serves, so takeover tests need a real configured source in
    the plan the same way production does. WP-07: it also needs a recent
    successful observation, because the plan now derives health from the
    persisted probe result rather than from the row existing.
    """
    observed_at = datetime.now(UTC)
    return LiveSourceResponse(
        live_source_id=f"{channel_id}-encoder",
        channel_id=channel_id,
        name="Council Room Encoder",
        source_type="srt",
        endpoint_url="srt://0.0.0.0:9000?mode=listener",
        credentials_handle=None,
        created_at=datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC),
        probe_state="ready",
        probe_observed_at=observed_at,
        probe_last_success_at=observed_at,
    )


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


def _make_service(engine: Engine) -> tuple[TakeoverService, InMemoryEgressStore]:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    egress = InMemoryEgressStore()
    service = TakeoverService(
        PostgresTakeoverAuditStore(factory),
        egress,
        lambda channel_id: build_ingest_plan(
            channel_id, [], live_sources=[_ready_source(channel_id)]
        ),
        id_factory=lambda: "tok",
    )
    return service, egress


def _build_app(
    engine: Engine, *, scopes: tuple[str, ...] | None
) -> tuple[FastAPI, InMemoryEgressStore]:
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

    app.include_router(staff_router)
    service, egress = _make_service(engine)
    app.dependency_overrides[get_takeover_service] = lambda: service
    return app, egress


def _client(
    engine: Engine, *, scopes: tuple[str, ...] | None = ("meeting",)
) -> tuple[TestClient, InMemoryEgressStore]:
    app, egress = _build_app(engine, scopes=scopes)
    return TestClient(app), egress


_BASE = "/api/staff/egress/channels/public"


class TestTakeoverEndpoints:
    def test_take_201_and_queues_command(self, engine: Engine) -> None:
        client, egress = _client(engine)
        resp = client.post(f"{_BASE}/takeover", json={"reason": "Emergency session"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["session_id"] == "takeover-tok"
        assert body["returned_at"] is None
        assert body["operator_id"] == "dana"
        assert len(egress.pop_pending_commands("public")) == 1

    def test_take_409_when_already_live(self, engine: Engine) -> None:
        client, _egress = _client(engine)
        assert client.post(f"{_BASE}/takeover", json={}).status_code == 201
        assert client.post(f"{_BASE}/takeover", json={}).status_code == 409

    def test_take_422_when_source_not_ready(self, engine: Engine) -> None:
        client, _egress = _client(engine)
        resp = client.post(f"{_BASE}/takeover", json={"path_id": "no-such-path"})
        assert resp.status_code == 422

    def test_handback_200(self, engine: Engine) -> None:
        client, _egress = _client(engine)
        client.post(f"{_BASE}/takeover", json={})
        resp = client.request("DELETE", f"{_BASE}/takeover", json={"notes": "handed back"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["returned_at"] is not None
        assert resp.json()["notes"] == "handed back"

    def test_handback_404_when_not_live(self, engine: Engine) -> None:
        client, _egress = _client(engine)
        assert client.request("DELETE", f"{_BASE}/takeover").status_code == 404

    def test_state_reflects_live(self, engine: Engine) -> None:
        client, _egress = _client(engine)
        before = client.get(f"{_BASE}/takeover-state").json()
        assert before["can_return"] is False
        client.post(f"{_BASE}/takeover", json={})
        after = client.get(f"{_BASE}/takeover-state").json()
        assert after["can_return"] is True
        assert after["active_session"]["session_id"] == "takeover-tok"


class TestRoleGate:
    def test_records_clerk_cannot_take_over(self, engine: Engine) -> None:
        client, _egress = _client(engine, scopes=("records",))
        assert client.post(f"{_BASE}/takeover", json={}).status_code == 403

    def test_no_identity_is_unauthorized(self, engine: Engine) -> None:
        client, _egress = _client(engine, scopes=None)
        assert client.post(f"{_BASE}/takeover", json={}).status_code == 401

    def test_audit_requires_setup_admin(self, engine: Engine) -> None:
        # A meeting operator may take over + read state, but NOT the audit log.
        client, _egress = _client(engine, scopes=("meeting",))
        assert client.get(f"{_BASE}/takeover-state").status_code == 200
        assert client.get(f"{_BASE}/takeover-audit").status_code == 403

    def test_setup_admin_may_read_audit(self, engine: Engine) -> None:
        client, _egress = _client(engine, scopes=("setup",))
        client.post(f"{_BASE}/takeover", json={})
        resp = client.get(f"{_BASE}/takeover-audit")
        assert resp.status_code == 200
        assert resp.json()[0]["session_id"] == "takeover-tok"
