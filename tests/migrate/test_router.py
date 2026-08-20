# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""0.4.0 migration staff API: role gating, 503 unwired, dry-run/apply/rollback/batches.

A minimal FastAPI app mounts the real staff router and overrides the
``get_migration_service`` DI seam with a SQLite-backed
:class:`MigrationService`. ``dry-run`` talks to a mocked Cablecast server
via ``httpx.MockTransport`` (no real network) — same golden fixture reused
from ``test_adapters_cablecast.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.migrate.adapters as adapters_module
from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.migrate.router import get_migration_service, staff_router
from civiccast.migrate.service import MigrationService
from tests.migrate.test_adapters_cablecast import _golden_handler

_SETUP_ADMIN = ("setup_admin",)
_FIXTURES = Path(__file__).parent / "fixtures"


def _build(
    *, scopes: tuple[str, ...] | None = _SETUP_ADMIN, wire_service: bool = True
) -> tuple[FastAPI, MigrationService]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    service = MigrationService(factory)
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
    if wire_service:
        app.dependency_overrides[get_migration_service] = lambda: service
    return app, service


_DRY_RUN_BODY = {
    "connection": {
        "source_system": "cablecast",
        "base_url": "https://access-sacramento.cablecast.tv/cablecastapi/v1",
    }
}


def test_dry_run_requires_setup_admin_role() -> None:
    app, _ = _build(scopes=("meeting_operator",))
    client = TestClient(app)
    resp = client.post("/api/staff/migrate/dry-run", json=_DRY_RUN_BODY)
    assert resp.status_code == 403


def test_dry_run_requires_identity() -> None:
    app, _ = _build(scopes=None)
    client = TestClient(app)
    resp = client.post("/api/staff/migrate/dry-run", json=_DRY_RUN_BODY)
    assert resp.status_code == 401


def test_dry_run_503_when_service_unwired() -> None:
    app, _ = _build(wire_service=False)
    client = TestClient(app)
    resp = client.post("/api/staff/migrate/dry-run", json=_DRY_RUN_BODY)
    assert resp.status_code == 503


def test_dry_run_502_on_unreachable_source() -> None:
    app, _ = _build()
    client = TestClient(app)

    def _boom(self: adapters_module.CablecastAdapter) -> httpx.Client:
        raise httpx.ConnectError("no route to host")

    original = adapters_module.CablecastAdapter._client
    adapters_module.CablecastAdapter._client = _boom  # type: ignore[method-assign]
    try:
        resp = client.post("/api/staff/migrate/dry-run", json=_DRY_RUN_BODY)
    finally:
        adapters_module.CablecastAdapter._client = original  # type: ignore[method-assign]
    assert resp.status_code == 502


def _dry_run_against_mocked_cablecast(client: TestClient) -> dict[str, Any]:
    """POST /dry-run with ``CablecastAdapter._client`` swapped for a
    ``MockTransport`` over the golden fixtures (no real network)."""
    original = adapters_module.CablecastAdapter._client

    def _mocked(self: adapters_module.CablecastAdapter) -> httpx.Client:
        return httpx.Client(
            base_url=self._conn.base_url.rstrip("/"),
            transport=httpx.MockTransport(_golden_handler),
        )

    adapters_module.CablecastAdapter._client = _mocked  # type: ignore[method-assign]
    try:
        resp = client.post("/api/staff/migrate/dry-run", json=_DRY_RUN_BODY)
    finally:
        adapters_module.CablecastAdapter._client = original  # type: ignore[method-assign]
    assert resp.status_code == 200
    result: dict[str, Any] = resp.json()
    return result


def test_dry_run_returns_a_plan_against_a_mocked_cablecast_server() -> None:
    app, _ = _build()
    client = TestClient(app)
    body = _dry_run_against_mocked_cablecast(client)
    assert {s["source_ref"] for s in body["shows_to_create"]} == {"73411", "73410"}


def test_apply_then_rollback_then_batches_round_trip() -> None:
    app, _ = _build()
    client = TestClient(app)

    plan_body = _dry_run_against_mocked_cablecast(client)

    apply_resp = client.post("/api/staff/migrate/apply", json={"plan": plan_body})
    assert apply_resp.status_code == 201
    batch = apply_resp.json()
    assert batch["shows_created"] == 2
    assert batch["schedule_items_created"] == 2

    batches_resp = client.get("/api/staff/migrate/batches")
    assert batches_resp.status_code == 200
    assert any(b["import_batch_id"] == batch["import_batch_id"] for b in batches_resp.json())

    rollback_resp = client.post(
        "/api/staff/migrate/rollback", json={"import_batch_id": batch["import_batch_id"]}
    )
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["status"] == "rolled_back"

    again = client.post(
        "/api/staff/migrate/rollback", json={"import_batch_id": batch["import_batch_id"]}
    )
    assert again.status_code == 409


def test_rollback_unknown_batch_is_404() -> None:
    app, _ = _build()
    client = TestClient(app)
    resp = client.post("/api/staff/migrate/rollback", json={"import_batch_id": "does-not-exist"})
    assert resp.status_code == 404


def test_apply_requires_setup_admin_role() -> None:
    app, _ = _build(scopes=("meeting_operator",))
    client = TestClient(app)
    resp = client.post(
        "/api/staff/migrate/apply",
        json={"plan": {"source_system": "cablecast"}},
    )
    assert resp.status_code == 403


def test_batches_requires_setup_admin_role() -> None:
    app, _ = _build(scopes=("meeting_operator",))
    client = TestClient(app)
    resp = client.get("/api/staff/migrate/batches")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 0.4.0-formats: the extended source_system enum (telvue/castus/leightronix)
# -- these are FILE-based, so dry-run parses ``schedule_file`` text instead
# of hitting a network mock.
# ---------------------------------------------------------------------------


def test_dry_run_accepts_the_extended_telvue_source_system() -> None:
    app, _ = _build()
    client = TestClient(app)
    body = {
        "connection": {
            "source_system": "telvue",
            "schedule_file": (_FIXTURES / "telvue_schedule.csv").read_text(encoding="utf-8"),
        }
    }
    resp = client.post("/api/staff/migrate/dry-run", json=body)
    assert resp.status_code == 200
    plan = resp.json()
    assert {s["source_ref"] for s in plan["shows_to_create"]} == {"4210", "parksrec_promo.mpg"}


def test_dry_run_400s_on_a_malformed_telvue_file() -> None:
    app, _ = _build()
    client = TestClient(app)
    body = {
        "connection": {
            "source_system": "telvue",
            # Missing the required "Duration" column.
            "schedule_file": (
                "Output,Date,Time,Type,Source ID,Source Name,Offset,Title\n"
                "1,07/10/2026,20:00:00,PLAYOUT,4210,x.mpg,0,Title\n"
            ),
        }
    }
    resp = client.post("/api/staff/migrate/dry-run", json=body)
    assert resp.status_code == 400
    assert "Duration" in resp.json()["detail"]


def test_dry_run_accepts_castus_and_leightronix_source_systems() -> None:
    app, _ = _build()
    client = TestClient(app)
    for source_system, fixture in (
        ("castus", "castus_schedule.csv"),
        ("leightronix", "leightronix_schedule.csv"),
    ):
        body = {
            "connection": {
                "source_system": source_system,
                "schedule_file": (_FIXTURES / fixture).read_text(encoding="utf-8"),
            }
        }
        resp = client.post("/api/staff/migrate/dry-run", json=body)
        assert resp.status_code == 200, (source_system, resp.text)
        assert len(resp.json()["shows_to_create"]) == 3


def test_connection_info_rejects_cablecast_without_base_url() -> None:
    app, _ = _build()
    client = TestClient(app)
    resp = client.post(
        "/api/staff/migrate/dry-run", json={"connection": {"source_system": "cablecast"}}
    )
    assert resp.status_code == 422


def test_connection_info_rejects_telvue_without_schedule_file() -> None:
    app, _ = _build()
    client = TestClient(app)
    resp = client.post(
        "/api/staff/migrate/dry-run", json={"connection": {"source_system": "telvue"}}
    )
    assert resp.status_code == 422
