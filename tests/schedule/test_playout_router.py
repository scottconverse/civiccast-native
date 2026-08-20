# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for the Commit-to-Air staff router (S4 slice 4).

A minimal FastAPI app mounts the real router, sets the operator identity via
middleware (so the real require_any_role gate runs), and overrides
get_commit_service with a real CommitService on SQLite + the in-memory egress
store. Covers role-gating, the prepare/commit happy paths, and 404/409/422/503.
"""

from __future__ import annotations

import contextlib
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
from civiccast.egress.dispatcher import PlayoutDispatcher
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.commit_models import CommitToAirReport
from civiccast.schedule.commit_service import CommitDryRunService, CommitService
from civiccast.schedule.models import Asset, ScheduleItem, ScheduleItemCreate
from civiccast.schedule.playout_router import get_commit_service, staff_router
from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore

_FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
_AIR = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


@pytest.fixture
def playout_factory() -> Iterator[Callable[[], Session]]:
    """Thread-safe SQLite session factory for TestClient.

    FastAPI's TestClient runs sync handlers on a threadpool, so the engine
    needs ``check_same_thread=False`` + ``StaticPool`` (one shared connection)
    and the ``civiccast`` schema ATTACHed on it — mirrors the canonical
    ``sqlite_router_client`` fixture in test_schedule_router.py.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        ScheduleItem.metadata.create_all(conn)
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


def _seed_asset(factory, asset_id="prog-1", *, state="validated", file_path="/m/x.ts"):  # type: ignore[no-untyped-def]
    with factory() as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title="A Program",
                state=state,
                file_path=file_path,
                duration_seconds=3600,
            )
        )
        session.commit()


def _create_item(
    store, *, asset_id="prog-1", channel_id="public", scheduled_at, duration_seconds=1800
):  # type: ignore[no-untyped-def]
    return store.create(
        ScheduleItemCreate(
            asset_id=asset_id,
            channel_id=channel_id,
            mode="premiere",
            scheduled_at=scheduled_at,
            duration_seconds=duration_seconds,
        )
    )


def _make_commit_service(factory):  # type: ignore[no-untyped-def]
    schedule_store = PostgresScheduleStore(factory)
    asset_store = PostgresAssetStore(factory)
    dry_run = CommitDryRunService(
        schedule_store, asset_store, clock=lambda: _FIXED_NOW, token_factory=lambda: "tok"
    )
    dispatcher = PlayoutDispatcher(
        InMemoryEgressStore(), clock=lambda: _FIXED_NOW, id_factory=lambda: "cmd"
    )
    return CommitService(
        dry_run,
        schedule_store,
        dispatcher,
        clock=lambda: _FIXED_NOW,
        report_id_factory=lambda: "rep",
    )


def _build_app(factory, *, scopes: tuple[str, ...] | None = ("publish",), wire: bool = True):  # type: ignore[no-untyped-def]
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
        service = _make_commit_service(factory)
        app.dependency_overrides[get_commit_service] = lambda: service
    return app


def _client(factory, **kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_app(factory, **kwargs))


class TestRoleGate:
    def test_non_publish_operator_is_forbidden(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory, scopes=("meeting",))
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 403

    def test_missing_identity_is_unauthorized(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory, scopes=None)
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 401

    def test_setup_admin_is_allowed(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        client = _client(playout_factory, scopes=("setup_admin",))
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        assert resp.status_code == 200


class TestPrepare:
    def test_prepare_happy(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run_passed"] is True
        assert body["title"] == "A Program"
        assert body["plan_id"] == "ctap_tok"

    def test_prepare_missing_item_404(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 404

    def test_prepare_unplayable_is_200_with_reason_not_422(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        # An unairable asset surfaces as passed=False in the plan, not a 422 —
        # the operator must see WHY it cannot air.
        _seed_asset(playout_factory, state="pending_ingest")
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run_passed"] is False
        assert "pending_ingest" in (body["missing_media_detail"] or "")

    def test_503_when_service_not_wired(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory, wire=False)
        resp = client.post(
            "/api/staff/playout/prepare-commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 503


class TestCommit:
    def test_commit_happy_201_queued(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
                "operator_notes": "airing tonight",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["report_id"] == "ctar_rep"
        assert body["dispatch_status"] == "queued"
        assert body["operator_notes"] == "airing tonight"
        assert body["approved_by_operator_id"] == "dana"

    def test_commit_conflict_409(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory, "prog-1")
        _seed_asset(playout_factory, "prog-2")
        store = PostgresScheduleStore(playout_factory)
        _create_item(store, asset_id="prog-2", scheduled_at=_AIR, duration_seconds=1800)
        proposed = _create_item(
            store,
            asset_id="prog-1",
            scheduled_at=_AIR + timedelta(minutes=10),
            duration_seconds=1800,
        )
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(proposed.id),
            },
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["conflicts"]

    def test_commit_unplayable_422(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        # Asset vanished between review and commit → unplayable, no conflict.
        from sqlalchemy import delete

        with playout_factory() as session:
            session.execute(delete(Asset).where(Asset.asset_id == "prog-1"))
            session.commit()
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        assert resp.status_code == 422

    def test_commit_conflict_for_cancelled_target_item(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        # Legacy finding: operator A prepares a commit; before A commits, a
        # different (unrelated) write cancels the same item. Re-running the
        # dry run inside commit() must now fail — the item is 'cancelled',
        # not 'scheduled' — instead of persisting a queued report for an item
        # that source_plan.py will never actually air.
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        store.cancel(item.id)
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        assert resp.status_code == 422
        assert "cancelled" in resp.json()["detail"].lower()

    def test_commit_missing_item_404(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory)
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 404

    def test_commit_forbidden_for_non_publish_operator(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory, scopes=("records",))
        resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        )
        assert resp.status_code == 403


def _seed_report(factory, report_id, *, channel_id="public", approved_at=_FIXED_NOW):  # type: ignore[no-untyped-def]
    PostgresScheduleStore(factory).upsert_commit_report(
        CommitToAirReport(
            report_id=report_id,
            channel_id=channel_id,
            occurrence_id=f"occ-{report_id}",
            schedule_item_id="550e8400-e29b-41d4-a716-446655440000",
            asset_id="prog-1",
            title="A Program",
            scheduled_at=_AIR,
            duration_seconds=1800,
            approved_by_operator_id="dana",
            approved_at=approved_at,
            dispatch_status="queued",
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
    )


class TestListAndDetail:
    def test_list_filters_by_channel(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a", channel_id="public")
        _seed_report(playout_factory, "ctar_b", channel_id="gov")
        client = _client(playout_factory)
        resp = client.get("/api/staff/playout/commits", params={"channel_id": "public"})
        assert resp.status_code == 200
        assert [r["report_id"] for r in resp.json()] == ["ctar_a"]

    def test_list_requires_channel_id(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory)
        resp = client.get("/api/staff/playout/commits")
        assert resp.status_code == 422  # missing required query param

    def test_support_admin_may_read_the_list(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a")
        client = _client(playout_factory, scopes=("support",))
        resp = client.get("/api/staff/playout/commits", params={"channel_id": "public"})
        assert resp.status_code == 200

    def test_detail_200_and_404(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a")
        client = _client(playout_factory)
        ok = client.get("/api/staff/playout/commits/ctar_a")
        assert ok.status_code == 200
        assert ok.json()["report_id"] == "ctar_a"
        missing = client.get("/api/staff/playout/commits/ctar_nope")
        assert missing.status_code == 404

    def test_meeting_operator_cannot_read(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a")
        client = _client(playout_factory, scopes=("meeting",))
        resp = client.get("/api/staff/playout/commits", params={"channel_id": "public"})
        assert resp.status_code == 403


class TestRollback:
    def test_rollback_happy(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(playout_factory)
        store = PostgresScheduleStore(playout_factory)
        item = _create_item(store, scheduled_at=_AIR)
        client = _client(playout_factory)
        commit_resp = client.post(
            "/api/staff/playout/commit",
            json={
                "channel_id": "public",
                "occurrence_id": "occ-1",
                "schedule_item_id": str(item.id),
            },
        )
        report_id = commit_resp.json()["report_id"]
        rb = client.post(
            f"/api/staff/playout/rollback/{report_id}",
            json={"reason": "wrong meeting aired"},
        )
        assert rb.status_code == 200
        body = rb.json()
        assert body["dispatch_status"] == "cancelled"
        assert body["rollback_reason"] == "wrong meeting aired"
        assert body["rolled_back_at"] is not None
        # The linked schedule item is now cancelled.
        assert store.get(item.id).state == "cancelled"

    def test_rollback_missing_report_404(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(playout_factory)
        resp = client.post("/api/staff/playout/rollback/ctar_nope", json={"reason": "x"})
        assert resp.status_code == 404

    def test_rollback_requires_reason(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a")
        client = _client(playout_factory)
        resp = client.post("/api/staff/playout/rollback/ctar_a", json={})
        assert resp.status_code == 422  # reason is required

    def test_support_admin_cannot_rollback(self, playout_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_report(playout_factory, "ctar_a")
        client = _client(playout_factory, scopes=("support",))
        resp = client.post("/api/staff/playout/rollback/ctar_a", json={"reason": "x"})
        assert resp.status_code == 403
