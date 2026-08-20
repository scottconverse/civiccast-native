# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the auto-schedule staff router (S18 slice 5a — CRUD).

A minimal FastAPI app mounts the real router, sets the operator identity via
middleware (so the real require_any_role gate runs), and overrides
get_autoschedule_service with a real AutoScheduleService on SQLite. Covers
role-gating, CRUD round-trips for all three entities, 404s, 422 on an invalid
daypart, and 503 when storage is unwired.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.schedule.autoschedule_router import get_autoschedule_service, staff_router
from civiccast.schedule.autoschedule_service import AutoScheduleService
from civiccast.schedule.autoschedule_store import AutoScheduleStore


@pytest.fixture
def factory() -> Iterator[Callable[[], Session]]:
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
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    try:
        yield _factory
    finally:
        engine.dispose()


def _build_app(factory, *, scopes=("publish",), wire: bool = True):  # type: ignore[no-untyped-def]
    app = FastAPI()

    @app.middleware("http")
    async def _set_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    if wire:
        service = AutoScheduleService(AutoScheduleStore(factory), session_factory=factory)
        app.dependency_overrides[get_autoschedule_service] = lambda: service
    return app


def _client(factory, **kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_app(factory, **kwargs))


_SEARCH_BODY = {
    "name": "Council meetings",
    "description": "Recent council recordings",
    "query": {"meeting_body": "City Council", "states": ["validated"]},
}
_BLOCK_BODY = {
    "channel_id": "public",
    "name": "Prime time",
    "start_minute": 1080,
    "end_minute": 1320,
    "days_of_week": [0, 2, 4],
}


# ---------------------------------------------------------------------------
# Role gating
# ---------------------------------------------------------------------------


class TestRoleGate:
    def test_write_forbidden_for_non_write_role(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=("meeting",)).post(
            "/api/staff/auto-schedule/saved-searches", json=_SEARCH_BODY
        )
        assert resp.status_code == 403

    def test_write_forbidden_for_read_only_support_admin(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=("support_admin",)).post(
            "/api/staff/auto-schedule/saved-searches", json=_SEARCH_BODY
        )
        assert resp.status_code == 403

    def test_missing_identity_unauthorized(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=None).get("/api/staff/auto-schedule/saved-searches")
        assert resp.status_code == 401

    def test_read_allowed_for_support_admin(self, factory) -> None:  # type: ignore[no-untyped-def]
        resp = _client(factory, scopes=("support_admin",)).get(
            "/api/staff/auto-schedule/saved-searches"
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# 503 when unwired
# ---------------------------------------------------------------------------


def test_503_when_storage_unwired(factory) -> None:  # type: ignore[no-untyped-def]
    resp = _client(factory, wire=False).get("/api/staff/auto-schedule/saved-searches")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# SavedSearch CRUD round-trip
# ---------------------------------------------------------------------------


def test_saved_search_crud_round_trip(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    created = client.post("/api/staff/auto-schedule/saved-searches", json=_SEARCH_BODY)
    assert created.status_code == 201
    sid = created.json()["saved_search_id"]
    assert sid.startswith("ss_")
    assert created.json()["query"]["meeting_body"] == "City Council"

    assert client.get(f"/api/staff/auto-schedule/saved-searches/{sid}").status_code == 200
    assert len(client.get("/api/staff/auto-schedule/saved-searches").json()) == 1

    updated = client.put(
        f"/api/staff/auto-schedule/saved-searches/{sid}",
        json={"name": "Renamed", "query": {"title_contains": "budget"}},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["query"]["title_contains"] == "budget"

    assert client.delete(f"/api/staff/auto-schedule/saved-searches/{sid}").status_code == 204
    assert client.get(f"/api/staff/auto-schedule/saved-searches/{sid}").status_code == 404


def test_saved_search_get_and_update_404(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    assert client.get("/api/staff/auto-schedule/saved-searches/nope").status_code == 404
    assert (
        client.put("/api/staff/auto-schedule/saved-searches/nope", json=_SEARCH_BODY).status_code
        == 404
    )
    assert client.delete("/api/staff/auto-schedule/saved-searches/nope").status_code == 404


# ---------------------------------------------------------------------------
# ScheduleBlock CRUD + validation
# ---------------------------------------------------------------------------


def test_block_crud_round_trip(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    created = client.post("/api/staff/auto-schedule/blocks", json=_BLOCK_BODY)
    assert created.status_code == 201
    bid = created.json()["block_id"]
    assert bid.startswith("sb_")
    assert created.json()["days_of_week"] == [0, 2, 4]

    assert len(client.get("/api/staff/auto-schedule/blocks?channel_id=public").json()) == 1
    assert client.get("/api/staff/auto-schedule/blocks?channel_id=other").json() == []

    assert client.delete(f"/api/staff/auto-schedule/blocks/{bid}").status_code == 204


def test_block_empty_weekdays_is_422(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    bad = {**_BLOCK_BODY, "days_of_week": []}
    resp = client.post("/api/staff/auto-schedule/blocks", json=bad)
    assert resp.status_code == 422


def test_block_inverted_active_dates_is_422(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    bad = {**_BLOCK_BODY, "active_from": "2026-03-01", "active_until": "2026-02-01"}
    resp = client.post("/api/staff/auto-schedule/blocks", json=bad)
    assert resp.status_code == 422


def test_non_slug_channel_id_is_422(factory) -> None:  # type: ignore[no-untyped-def]
    # A rule/block must use a channel slug (so its materialized items can't hit
    # a channel id ScheduleItemCreate would reject) — slice-4 audit watch-item #2.
    client = _client(factory)
    assert (
        client.post(
            "/api/staff/auto-schedule/blocks", json={**_BLOCK_BODY, "channel_id": "Bad Channel"}
        ).status_code
        == 422
    )


# ---------------------------------------------------------------------------
# AutoScheduleRule CRUD + validation
# ---------------------------------------------------------------------------


def _rule_body(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "Fill prime",
        "saved_search_id": "ss_x",
        "channel_id": "public",
        "schedule_block_id": "sb_x",
        "pick_strategy": "newest",
        "rolling_window_days": 30,
    }
    base.update(over)
    return base


def test_rule_crud_round_trip(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    created = client.post("/api/staff/auto-schedule/rules", json=_rule_body())
    assert created.status_code == 201
    rid = created.json()["rule_id"]
    assert rid.startswith("asr_")

    updated = client.put(
        f"/api/staff/auto-schedule/rules/{rid}",
        json=_rule_body(name="Renamed", pick_strategy="random_result"),
    )
    assert updated.status_code == 200
    assert updated.json()["pick_strategy"] == "random_result"

    assert len(client.get("/api/staff/auto-schedule/rules?enabled_only=true").json()) == 1
    assert client.delete(f"/api/staff/auto-schedule/rules/{rid}").status_code == 204
    assert client.get(f"/api/staff/auto-schedule/rules/{rid}").status_code == 404


def test_rule_out_of_band_window_is_422(factory) -> None:  # type: ignore[no-untyped-def]
    client = _client(factory)
    assert (
        client.post(
            "/api/staff/auto-schedule/rules", json=_rule_body(rolling_window_days=5)
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/staff/auto-schedule/rules", json=_rule_body(pick_strategy="bogus")
        ).status_code
        == 422
    )
