# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 23 producer-ops API: role gating, 503 unwired, and CRUD for
series applications, volunteer roster, call sheets, equipment + checkouts,
and training badges.

Mirrors the paywall/contribute router harness: a minimal FastAPI app mounts
the real staff router, installs an operator-identity middleware (so
``require_any_role`` runs), and overrides the DI seam with a SQLite-backed
``ProducerOpsStore``.
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

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.producer_ops.router import get_producer_ops_store, staff_router
from civiccast.producer_ops.store import ProducerOpsStore

_TEST_ENGINES: list[Engine] = []


@pytest.fixture(autouse=True)
def _dispose_engines() -> Iterator[None]:
    yield
    while _TEST_ENGINES:
        _TEST_ENGINES.pop().dispose()


def _build(
    *,
    scopes: tuple[str, ...] | None = ("publish_operator",),
    wire_store: bool = True,
) -> tuple[FastAPI, ProducerOpsStore]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _TEST_ENGINES.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    store = ProducerOpsStore(factory)

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
        app.dependency_overrides[get_producer_ops_store] = lambda: store

    return app, store


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


# --- role gating + unwired store -------------------------------------------


class TestRoleGatingAndWiring:
    def test_no_identity_is_401(self) -> None:
        app, _ = _build(scopes=None)
        resp = _client(app).get("/api/staff/producer-ops/volunteers")
        assert resp.status_code == 401

    def test_wrong_role_is_403(self) -> None:
        app, _ = _build(scopes=("records_clerk",))
        resp = _client(app).get("/api/staff/producer-ops/volunteers")
        assert resp.status_code == 403

    def test_unwired_store_is_503(self) -> None:
        app, _ = _build(wire_store=False)
        resp = _client(app).get("/api/staff/producer-ops/volunteers")
        assert resp.status_code == 503

    def test_support_admin_role_allowed(self) -> None:
        app, _ = _build(scopes=("support_admin",))
        resp = _client(app).get("/api/staff/producer-ops/volunteers")
        assert resp.status_code == 200


# --- series applications ---------------------------------------------------


class TestSeriesApplicationRoutes:
    def _payload(self, **overrides: object) -> dict:
        base = {
            "application_id": "app-1",
            "contributor_id": "contrib-1",
            "series_title": "Weekly Roundtable",
            "proposed_cadence": "every Tuesday",
            "description": "A weekly civic roundtable.",
        }
        base.update(overrides)
        return base

    def test_create_and_list(self) -> None:
        app, _ = _build()
        client = _client(app)
        created = client.post("/api/staff/producer-ops/series-applications", json=self._payload())
        assert created.status_code == 201
        assert created.json()["state"] == "submitted"

        listed = client.get("/api/staff/producer-ops/series-applications")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    def test_review_approve(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.post("/api/staff/producer-ops/series-applications", json=self._payload())
        resp = client.post(
            "/api/staff/producer-ops/series-applications/app-1/review",
            json={"state": "approved", "series_id": "series-42"},
        )
        assert resp.status_code == 200
        assert resp.json()["state"] == "approved"
        assert resp.json()["series_id"] == "series-42"

    def test_review_missing_is_404(self) -> None:
        app, _ = _build()
        resp = _client(app).post(
            "/api/staff/producer-ops/series-applications/missing/review",
            json={"state": "approved"},
        )
        assert resp.status_code == 404

    def test_read_missing_is_404(self) -> None:
        app, _ = _build()
        resp = _client(app).get("/api/staff/producer-ops/series-applications/missing")
        assert resp.status_code == 404

    def test_duplicate_application_id_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        first = client.post("/api/staff/producer-ops/series-applications", json=self._payload())
        assert first.status_code == 201
        second = client.post("/api/staff/producer-ops/series-applications", json=self._payload())
        assert second.status_code == 409


# --- volunteer roster -----------------------------------------------------


class TestVolunteerRoutes:
    def test_upsert_and_read(self) -> None:
        app, _ = _build()
        client = _client(app)
        payload = {
            "volunteer_id": "vol-1",
            "display_name": "Alex Volunteer",
            "role_name": "camera",
        }
        resp = client.put("/api/staff/producer-ops/volunteers/vol-1", json=payload)
        assert resp.status_code == 200
        read = client.get("/api/staff/producer-ops/volunteers/vol-1")
        assert read.status_code == 200
        assert read.json()["display_name"] == "Alex Volunteer"

    def test_mismatched_path_and_body_id_is_422(self) -> None:
        app, _ = _build()
        resp = _client(app).put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-2", "display_name": "x", "role_name": "camera"},
        )
        assert resp.status_code == 422

    def test_read_missing_is_404(self) -> None:
        app, _ = _build()
        resp = _client(app).get("/api/staff/producer-ops/volunteers/missing")
        assert resp.status_code == 404


# --- call sheets ------------------------------------------------------------


class TestCallSheetRoutes:
    def test_create_call_sheet_and_assign(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        created = client.post(
            "/api/staff/producer-ops/call-sheets",
            json={
                "call_sheet_id": "cs-1",
                "title": "City Council Live Shoot",
                "shoot_date": "2026-08-01T18:00:00Z",
            },
        )
        assert created.status_code == 201

        assigned = client.post(
            "/api/staff/producer-ops/call-sheets/cs-1/assignments",
            json={
                "assignment_id": "asn-1",
                "call_sheet_id": "cs-1",
                "volunteer_id": "vol-1",
                "role_name": "camera",
            },
        )
        assert assigned.status_code == 201

        listed = client.get("/api/staff/producer-ops/call-sheets/cs-1/assignments")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    def test_assign_unknown_volunteer_is_404(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.post(
            "/api/staff/producer-ops/call-sheets",
            json={
                "call_sheet_id": "cs-1",
                "title": "x",
                "shoot_date": "2026-08-01T18:00:00Z",
            },
        )
        resp = client.post(
            "/api/staff/producer-ops/call-sheets/cs-1/assignments",
            json={
                "assignment_id": "asn-1",
                "call_sheet_id": "cs-1",
                "volunteer_id": "missing",
                "role_name": "camera",
            },
        )
        assert resp.status_code == 404

    def test_duplicate_call_sheet_id_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        payload = {
            "call_sheet_id": "cs-1",
            "title": "City Council Live Shoot",
            "shoot_date": "2026-08-01T18:00:00Z",
        }
        first = client.post("/api/staff/producer-ops/call-sheets", json=payload)
        assert first.status_code == 201
        second = client.post("/api/staff/producer-ops/call-sheets", json=payload)
        assert second.status_code == 409

    def test_duplicate_assignment_id_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        client.post(
            "/api/staff/producer-ops/call-sheets",
            json={
                "call_sheet_id": "cs-1",
                "title": "x",
                "shoot_date": "2026-08-01T18:00:00Z",
            },
        )
        payload = {
            "assignment_id": "asn-1",
            "call_sheet_id": "cs-1",
            "volunteer_id": "vol-1",
            "role_name": "camera",
        }
        first = client.post("/api/staff/producer-ops/call-sheets/cs-1/assignments", json=payload)
        assert first.status_code == 201
        second = client.post("/api/staff/producer-ops/call-sheets/cs-1/assignments", json=payload)
        assert second.status_code == 409


# --- equipment + checkouts --------------------------------------------------


class TestEquipmentCheckoutRoutes:
    def _seed_volunteer_and_equipment(self, client: TestClient) -> None:
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        client.put(
            "/api/staff/producer-ops/equipment/cam-1",
            json={"equipment_id": "cam-1", "name": "Camera 1", "category": "camera"},
        )

    def test_checkout_and_return_round_trip(self) -> None:
        app, _ = _build()
        client = _client(app)
        self._seed_volunteer_and_equipment(client)

        checkout = client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-1", "equipment_id": "cam-1", "volunteer_id": "vol-1"},
        )
        assert checkout.status_code == 201
        assert checkout.json()["state"] == "checked_out"

        returned = client.post("/api/staff/producer-ops/checkouts/co-1/return")
        assert returned.status_code == 200
        assert returned.json()["state"] == "returned"

    def test_double_checkout_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        self._seed_volunteer_and_equipment(client)
        client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-1", "equipment_id": "cam-1", "volunteer_id": "vol-1"},
        )
        resp = client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-2", "equipment_id": "cam-1", "volunteer_id": "vol-1"},
        )
        assert resp.status_code == 409

    def test_checkout_without_required_badge_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        self._seed_volunteer_and_equipment(client)
        client.put(
            "/api/staff/producer-ops/equipment/cam-1/access-rule",
            json={"rule_id": "rule-1", "equipment_id": "cam-1", "required_badge_name": "camera-1"},
        )
        resp = client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-1", "equipment_id": "cam-1", "volunteer_id": "vol-1"},
        )
        assert resp.status_code == 409

    def test_checkout_with_badge_succeeds(self) -> None:
        app, _ = _build()
        client = _client(app)
        self._seed_volunteer_and_equipment(client)
        client.put(
            "/api/staff/producer-ops/equipment/cam-1/access-rule",
            json={"rule_id": "rule-1", "equipment_id": "cam-1", "required_badge_name": "camera-1"},
        )
        client.post(
            "/api/staff/producer-ops/volunteers/vol-1/badges",
            json={"badge_id": "badge-1", "volunteer_id": "vol-1", "badge_name": "camera-1"},
        )
        resp = client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-1", "equipment_id": "cam-1", "volunteer_id": "vol-1"},
        )
        assert resp.status_code == 201

    def test_checkout_unknown_equipment_is_404(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        resp = client.post(
            "/api/staff/producer-ops/checkouts",
            json={"checkout_id": "co-1", "equipment_id": "missing", "volunteer_id": "vol-1"},
        )
        assert resp.status_code == 404

    def test_return_missing_checkout_is_404(self) -> None:
        app, _ = _build()
        resp = _client(app).post("/api/staff/producer-ops/checkouts/missing/return")
        assert resp.status_code == 404


# --- training badges ---------------------------------------------------------


class TestTrainingBadgeRoutes:
    def test_grant_and_list(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        granted = client.post(
            "/api/staff/producer-ops/volunteers/vol-1/badges",
            json={"badge_id": "badge-1", "volunteer_id": "vol-1", "badge_name": "camera-1"},
        )
        assert granted.status_code == 201

        listed = client.get("/api/staff/producer-ops/volunteers/vol-1/badges")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    def test_grant_unknown_volunteer_is_404(self) -> None:
        app, _ = _build()
        resp = _client(app).post(
            "/api/staff/producer-ops/volunteers/missing/badges",
            json={"badge_id": "badge-1", "volunteer_id": "missing", "badge_name": "camera-1"},
        )
        assert resp.status_code == 404

    def test_duplicate_badge_id_is_409(self) -> None:
        app, _ = _build()
        client = _client(app)
        client.put(
            "/api/staff/producer-ops/volunteers/vol-1",
            json={"volunteer_id": "vol-1", "display_name": "Alex", "role_name": "camera"},
        )
        payload = {"badge_id": "badge-1", "volunteer_id": "vol-1", "badge_name": "camera-1"}
        first = client.post("/api/staff/producer-ops/volunteers/vol-1/badges", json=payload)
        assert first.status_code == 201
        second = client.post("/api/staff/producer-ops/volunteers/vol-1/badges", json=payload)
        assert second.status_code == 409
