# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3c — remote-contribution staff + public API.

A minimal FastAPI app mounts the real staff + public routers, sets the operator
identity via middleware (so the real require_any_role gate runs), and overrides
the single DI seam with a SQLite-backed ContributionService + a FakeBridge.
Covers role-gating (positive / 403 / 401), 503-when-unwired, 503-when-the-tier-
is-not-configured (Null bridge), the public token-gated join flow (resolve once
-> 410 on reuse, the public-comment terms gate), the no-push_url-leak guarantee,
and the operator waiting-room -> on-air flow.
"""

from __future__ import annotations

import contextlib
import itertools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.live.contribution.bridge import (
    GuestUrls,
    NullVdoNinjaBridge,
    VdoDiagnostics,
)
from civiccast.live.contribution.models import INVITE_TOKEN_MIN_LENGTH, ContributionRoom
from civiccast.live.contribution.router import (
    get_contribution_service,
    public_router,
    staff_router,
)
from civiccast.live.contribution.service import ContributionService
from civiccast.live.contribution.store import ContributionStore

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_ALL = ("setup_admin", "meeting_operator", "support_admin")


class _FakeBridge:
    def director_url(self, room: ContributionRoom) -> str:
        return f"https://vdo.test/?director={room.vdo_room_name}"

    def guest_urls(self, room: ContributionRoom, *, invite_token: str, role: str) -> GuestUrls:
        return GuestUrls(
            view_url=f"https://vdo.test/?room={room.vdo_room_name}&push={invite_token}",
            push_url=f"https://vdo.test/?view={invite_token}&solo=1",  # compositor-only
        )

    def diagnostics(self) -> VdoDiagnostics:
        return VdoDiagnostics(turn_reachable=True, vdo_process_up=True)

    def test_turn_connectivity(self) -> VdoDiagnostics:
        return VdoDiagnostics(
            turn_reachable=True, turn_host="turn.example.org", turn_port=3478, vdo_process_up=True
        )


def _build(scopes: tuple[str, ...] | None = _ALL, *, wire: bool = True, bridge=None):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()

    @contextmanager
    def factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    store = ContributionStore(factory)
    counter = itertools.count(1)
    tokens = itertools.count(1)
    service = ContributionService(
        store,
        bridge if bridge is not None else _FakeBridge(),
        clock=lambda: _T0,
        id_factory=lambda: f"{next(counter):04d}",
        token_factory=lambda: f"token-{next(tokens):0>{INVITE_TOKEN_MIN_LENGTH}}",
    )

    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.include_router(public_router)
    if wire:
        app.dependency_overrides[get_contribution_service] = lambda: service
    return app, service


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _open_room(client: TestClient, **room) -> str:
    body = {"channel_id": "ch", "name": "Chamber", **room}
    rid = client.post("/api/staff/contribution/rooms", json=body).json()["room_id"]
    client.post(f"/api/staff/contribution/rooms/{rid}/open")
    return rid


def _mint(client: TestClient, rid: str, *, role: str = "council_member") -> str:
    r = client.post(
        f"/api/staff/contribution/rooms/{rid}/invites",
        json={"guest_display_name": "Jane", "role": role},
    )
    return r.json()["invite_token"]


# --- role gate ---------------------------------------------------------------


def test_create_room_forbidden_for_meeting_operator() -> None:
    r = _client(scopes=("meeting_operator",)).post(
        "/api/staff/contribution/rooms", json={"channel_id": "ch", "name": "X"}
    )
    assert r.status_code == 403


def test_create_room_allowed_for_setup_admin() -> None:
    r = _client(scopes=("setup_admin",)).post(
        "/api/staff/contribution/rooms", json={"channel_id": "ch", "name": "X"}
    )
    assert r.status_code == 201


def test_list_rooms_forbidden_for_records_clerk_and_unauth() -> None:
    assert (
        _client(scopes=("records_clerk",)).get("/api/staff/contribution/rooms").status_code == 403
    )
    assert _client(scopes=None).get("/api/staff/contribution/rooms").status_code == 401


def test_operate_forbidden_for_support_admin() -> None:
    # support_admin can read but not run the show.
    client = _client(scopes=("support_admin",))
    assert client.get("/api/staff/contribution/rooms").status_code == 200
    assert client.post("/api/staff/contribution/rooms/x/open").status_code == 403


def test_diagnostics_requires_support_admin() -> None:
    assert (
        _client(scopes=("meeting_operator",)).get("/api/staff/contribution/diagnostics").status_code
        == 403
    )
    r = _client(scopes=("support_admin",)).get("/api/staff/contribution/diagnostics")
    assert r.status_code == 200 and r.json()["turn_reachable"] is True


def test_503_when_unwired() -> None:
    assert _client(wire=False).get("/api/staff/contribution/rooms").status_code == 503


def test_turn_connectivity_test_requires_support_admin() -> None:
    assert (
        _client(scopes=("meeting_operator",))
        .post("/api/staff/contribution/diagnostics/turn-test")
        .status_code
        == 403
    )
    r = _client(scopes=("support_admin",)).post("/api/staff/contribution/diagnostics/turn-test")
    assert r.status_code == 200
    body = r.json()
    assert body["turn_reachable"] is True
    assert body["turn_host"] == "turn.example.org"
    assert body["turn_port"] == 3478


def test_open_room_503_when_tier_not_configured() -> None:
    client = _client(bridge=NullVdoNinjaBridge())
    rid = client.post(
        "/api/staff/contribution/rooms", json={"channel_id": "ch", "name": "X"}
    ).json()["room_id"]
    r = client.post(f"/api/staff/contribution/rooms/{rid}/open")
    assert r.status_code == 503
    assert "not configured" in r.json()["detail"]


# --- public token-gated join flow -------------------------------------------


def test_public_resolve_consumes_once_then_410() -> None:
    client = _client()
    rid = _open_room(client)
    token = _mint(client, rid)

    r1 = client.get(f"/api/public/contribution/invites/{token}")
    assert r1.status_code == 200
    body = r1.json()
    assert body["needs_terms"] is False and body["session_id"]
    # The public join view must NEVER leak the compositor-facing push_url.
    assert "push_url" not in body
    assert "solo=1" not in r1.text

    # Single-use: reuse is 410 Gone.
    assert client.get(f"/api/public/contribution/invites/{token}").status_code == 410


def test_public_resolve_unknown_is_404() -> None:
    client = _client()
    r = client.get("/api/public/contribution/invites/" + "x" * INVITE_TOKEN_MIN_LENGTH)
    assert r.status_code == 404


def test_public_routes_need_no_auth_identity() -> None:
    # scopes=None => no operator identity is set, yet the public resolve works
    # (capability is the token). 404 (not 401) proves the route isn't role-gated.
    client = _client(scopes=None)
    r = client.get("/api/public/contribution/invites/" + "x" * INVITE_TOKEN_MIN_LENGTH)
    assert r.status_code == 404


def test_public_comment_terms_gate() -> None:
    client = _client()
    rid = _open_room(client)
    token = _mint(client, rid, role="public_comment")

    first = client.get(f"/api/public/contribution/invites/{token}").json()
    assert first["needs_terms"] is True and first["session_id"] is None

    acc = client.post(f"/api/public/contribution/invites/{token}/accept-terms")
    assert acc.status_code == 200 and acc.json()["accepted"] is True

    ready = client.get(f"/api/public/contribution/invites/{token}").json()
    assert ready["needs_terms"] is False and ready["session_id"]


# --- operator waiting-room -> on-air flow ------------------------------------


def test_on_air_requires_admit_then_room_goes_live() -> None:
    client = _client()
    rid = _open_room(client)
    token = _mint(client, rid)
    sid = client.get(f"/api/public/contribution/invites/{token}").json()["session_id"]

    # on-air before admit -> 409 (waiting-room gate).
    assert client.post(f"/api/staff/contribution/sessions/{sid}/on-air").status_code == 409

    assert client.post(f"/api/staff/contribution/sessions/{sid}/admit").status_code == 200
    on_air = client.post(f"/api/staff/contribution/sessions/{sid}/on-air")
    assert on_air.status_code == 200 and on_air.json()["state"] == "on_air"

    detail = client.get(f"/api/staff/contribution/rooms/{rid}").json()
    assert detail["room"]["state"] == "live"
    assert len(detail["sessions"]) == 1


def test_mint_invite_on_closed_room_409() -> None:
    client = _client()
    rid = _open_room(client)
    client.post(f"/api/staff/contribution/rooms/{rid}/close")
    r = client.post(
        f"/api/staff/contribution/rooms/{rid}/invites",
        json={"guest_display_name": "Late", "role": "presenter"},
    )
    assert r.status_code == 409


# --- app durable wiring (proves the DI override actually registers) ----------


def test_durable_wiring_registers_override_and_selects_bridge(tmp_path, monkeypatch) -> None:
    """The real create_app() durable path must register the contribution service
    override and pick Url vs Null bridge from CIVICCAST_REMOTE_CONTRIBUTION_VDO_URL
    — otherwise the live endpoints silently 503 in production."""
    from civiccast.app import create_app
    from civiccast.live.contribution.bridge import NullVdoNinjaBridge, UrlVdoNinjaBridge

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'wire.sqlite'}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")

    monkeypatch.delenv("CIVICCAST_REMOTE_CONTRIBUTION_VDO_URL", raising=False)
    app = create_app()
    resolver = app.dependency_overrides.get(get_contribution_service)
    assert resolver is not None
    assert isinstance(resolver()._bridge, NullVdoNinjaBridge)  # fail-closed by default

    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION_VDO_URL", "https://vdo.station.example")
    app2 = create_app()
    assert isinstance(
        app2.dependency_overrides[get_contribution_service]()._bridge, UrlVdoNinjaBridge
    )
