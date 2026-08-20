# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the schedule HTTP endpoints.

Covers:

  TestNoDB                — 503 on every endpoint when DATABASE_URL is unset
  TestCreate              — 201 happy path + 422 validation
  TestList                — 200 + filters
  TestGet                 — 200 + 404
  TestCancel              — 200 transition + 404 + 503
  TestConflictResponse    — 409 shape with conflicting_item payload (mocked)
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.auth.models import OperatorIdentity
from civiccast.schedule.models import (
    SCHEDULE_MODE_EMBARGO,
    SCHEDULE_MODE_PREMIERE,
    SCHEDULE_STATE_CANCELLED,
    SCHEDULE_STATE_PUBLISHED,
    SCHEDULE_STATE_SCHEDULED,
    ScheduleItemResponse,
)
from civiccast.schedule.router import get_schedule_store, public_router, staff_router
from civiccast.schedule.store import (
    PostgresScheduleStore,
    ScheduleConflictError,
    ScheduleItemNotFoundError,
)


def _future_iso(hours: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _payload(**overrides) -> dict:  # type: ignore[no-untyped-def]
    base = {
        "asset_id": "abc-123",
        "channel_id": "gov-ch12",
        "mode": SCHEDULE_MODE_PREMIERE,
        "scheduled_at": _future_iso(),
        "duration_seconds": 3600,
    }
    base.update(overrides)
    return base


def _publish(client: TestClient, item_id: str) -> None:
    """Flip a created item scheduled -> published (Commit-to-Air approval).

    Shortcut around the full playout/occurrence commit round-trip so the
    public-widget tests can seed a committed item directly.
    """
    client.schedule_store.mark_published([uuid.UUID(item_id)])  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def no_db_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """No DI override → schedule_store dependency returns None → 503."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


@pytest.fixture
def sqlite_router_client() -> Iterator[TestClient]:
    """TestClient with FastAPI router wired to a PostgresScheduleStore
    backed by a thread-safe shared in-memory **SQLite** engine.

    Renamed from ``real_store_client`` in Slice 1 Commit 9 per audit-team
    v0.3.0 TEST-008. The previous name implied "real" backing -- but the
    engine is SQLite, not Postgres. SQLite cannot enforce the
    ``btree_gist`` EXCLUDE constraint, so conflict-detection cannot be
    asserted via this fixture (see :class:`TestConflictResponse` for
    the mocked-store version of the 409 shape lock, and
    :class:`tests.schedule.test_real_postgres.TestRealPostgresScheduleRouterConflict`
    for the real-Postgres end-to-end conflict path).

    FastAPI's TestClient runs request handlers on a thread pool; sharing
    a SQLite engine across threads requires ``check_same_thread=False``
    plus ``StaticPool`` so all sessions reuse the single connection
    where the ``civiccast`` schema was attached. Without this, request
    threads get fresh connections that haven't run the ATTACH listener
    and the schema-qualified ``civiccast.schedule_items`` table is
    invisible.

    SQLite still doesn't enforce the EXCLUDE constraint, so
    conflict-rejection behavior can't be tested here — that lives in
    :class:`TestConflictResponse` with a mocked store and in
    ``tests/schedule/test_real_postgres.py`` against real Postgres.
    """
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    # Use ScheduleItem.metadata directly rather than importing
    # ``civiccast.db.Base``. tests/db/test_session.py forces a re-import
    # of civiccast.db (sys.modules.pop + import) which creates a NEW
    # Base.metadata that does NOT have models registered against it.
    # ScheduleItem.metadata is whatever metadata ScheduleItem was
    # imported against — survives the pop trick.
    from civiccast.schedule.models import ScheduleItem

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Explicitly ATTACH the civiccast schema on first connect, then
    # create the schedule_items table on this exact connection.
    import contextlib

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

    # QA-004: pre-seed Asset rows for the asset_ids the schedule create
    # tests reference. The store's existence check (added for QA-004)
    # would otherwise 404 every payload here.
    from civiccast.schedule.models import Asset

    with _factory() as seed_sess:
        for asset_id in (
            "abc-123",
            "city-council-2026-05-08",
            "gov-1",
            "gov-2",
            "edu-1",
            "meeting-x",
            "meeting-y",
            "embargo-1",
        ):
            seed_sess.add(
                Asset(
                    asset_id=asset_id,
                    title=f"Test asset {asset_id}",
                    state="validated",
                )
            )
        seed_sess.commit()

    app = create_app()
    store = PostgresScheduleStore(_factory)
    app.dependency_overrides[get_schedule_store] = lambda: store
    try:
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            # Expose the store so tests can drive the Commit-to-Air state flip
            # (mark_published) without the full playout/occurrence round-trip.
            c.schedule_store = store  # type: ignore[attr-defined]
            yield c
    finally:
        engine.dispose()


def _build_role_app(  # type: ignore[no-untyped-def]
    factory,
    *,
    scopes: tuple[str, ...] | None = ("publish_operator",),
) -> FastAPI:
    """Minimal app mounting the real schedule routers, identity set by scopes.

    Mirrors ``test_playout_router.py``'s ``_build_app`` — the real
    ``require_any_role`` dependency runs against ``request.state.operator_identity``
    set here directly, instead of going through a bearer token.
    """
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

    app.include_router(public_router)
    app.include_router(staff_router)
    store = PostgresScheduleStore(factory)
    app.dependency_overrides[get_schedule_store] = lambda: store
    return app


def _role_client(factory, **kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_role_app(factory, **kwargs))


@pytest.fixture
def schedule_factory() -> Iterator[Callable[[], object]]:
    """Thread-safe SQLite session factory, seeded with asset ``prog-1``.

    Same shape as ``playout_factory`` in test_playout_router.py.
    """
    import contextlib

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from civiccast.schedule.models import Asset, ScheduleItem

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

    from contextlib import contextmanager

    @contextmanager
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    with _factory() as seed_sess:
        seed_sess.add(Asset(asset_id="prog-1", title="A Program", state="validated"))
        seed_sess.commit()

    try:
        yield _factory
    finally:
        engine.dispose()


class TestScheduleRoleGate:
    """Covers role-gating on schedule writes (create/cancel) and reads
    (list/get) — mirrors ``test_playout_router.py::TestRoleGate``.
    """

    def test_create_forbidden_for_non_write_role(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=("meeting_operator",))
        response = client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        assert response.status_code == 403

    def test_create_unauthorized_when_no_identity(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=None)
        response = client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        assert response.status_code == 401

    def test_create_allowed_for_publish_operator(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=("publish_operator",))
        response = client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        assert response.status_code == 201

    def test_create_allowed_for_setup_admin(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=("setup_admin",))
        response = client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        assert response.status_code == 201

    def test_cancel_forbidden_for_non_write_role(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        admin_client = _role_client(schedule_factory, scopes=("setup_admin",))
        created = admin_client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        schedule_id = created.json()["id"]

        client = _role_client(schedule_factory, scopes=("records_clerk",))
        response = client.post(f"/api/staff/schedule/{schedule_id}/cancel")
        assert response.status_code == 403

    def test_cancel_allowed_for_publish_operator(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        admin_client = _role_client(schedule_factory, scopes=("setup_admin",))
        created = admin_client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        schedule_id = created.json()["id"]

        client = _role_client(schedule_factory, scopes=("publish_operator",))
        response = client.post(f"/api/staff/schedule/{schedule_id}/cancel")
        assert response.status_code == 200

    def test_list_forbidden_for_non_read_role(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=("meeting_operator",))
        response = client.get("/api/staff/schedule")
        assert response.status_code == 403

    def test_list_allowed_for_support_admin(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        client = _role_client(schedule_factory, scopes=("support_admin",))
        response = client.get("/api/staff/schedule")
        assert response.status_code == 200

    def test_get_one_forbidden_for_non_read_role(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        admin_client = _role_client(schedule_factory, scopes=("setup_admin",))
        created = admin_client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        schedule_id = created.json()["id"]

        client = _role_client(schedule_factory, scopes=("records_clerk",))
        response = client.get(f"/api/staff/schedule/{schedule_id}")
        assert response.status_code == 403

    def test_get_one_allowed_for_support_admin(self, schedule_factory) -> None:  # type: ignore[no-untyped-def]
        admin_client = _role_client(schedule_factory, scopes=("setup_admin",))
        created = admin_client.post("/api/staff/schedule", json=_payload(asset_id="prog-1"))
        schedule_id = created.json()["id"]

        client = _role_client(schedule_factory, scopes=("support_admin",))
        response = client.get(f"/api/staff/schedule/{schedule_id}")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# TestNoDB
# ---------------------------------------------------------------------------


class TestNoDB:
    def test_post_returns_503(self, no_db_client: TestClient) -> None:
        response = no_db_client.post("/api/staff/schedule", json=_payload())
        assert response.status_code == 503
        assert "Durable storage is not ready" in response.json()["detail"]

    def test_get_list_returns_503(self, no_db_client: TestClient) -> None:
        response = no_db_client.get("/api/staff/schedule")
        assert response.status_code == 503

    def test_get_one_returns_503(self, no_db_client: TestClient) -> None:
        response = no_db_client.get(f"/api/staff/schedule/{uuid.uuid4()}")
        assert response.status_code == 503

    def test_cancel_returns_503(self, no_db_client: TestClient) -> None:
        response = no_db_client.post(f"/api/staff/schedule/{uuid.uuid4()}/cancel")
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_201_with_response_body(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post("/api/staff/schedule", json=_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["asset_id"] == "abc-123"
        assert body["mode"] == SCHEDULE_MODE_PREMIERE
        assert body["state"] == SCHEDULE_STATE_SCHEDULED
        assert "id" in body
        assert "created_at" in body

    def test_embargo_creates_without_duration(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(mode=SCHEDULE_MODE_EMBARGO, duration_seconds=None),
        )
        assert response.status_code == 201
        assert response.json()["duration_seconds"] is None

    def test_invalid_mode_returns_422(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(mode="rerun"),
        )
        assert response.status_code == 422

    def test_naive_scheduled_at_returns_422(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(scheduled_at="2026-05-15T18:00:00"),  # no tz
        )
        assert response.status_code == 422

    def test_live_without_duration_returns_422(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(duration_seconds=None),
        )
        assert response.status_code == 422

    def test_unknown_asset_id_returns_404(self, sqlite_router_client: TestClient) -> None:
        # QA-004 (audit-team v0.3.0): scheduling against a nonexistent
        # asset_id is rejected at the API surface, not silently persisted.
        response = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(asset_id="this-id-does-not-exist"),
        )
        assert response.status_code == 404
        assert "this-id-does-not-exist" in response.json()["detail"]


# ---------------------------------------------------------------------------
# TestList
# ---------------------------------------------------------------------------


class TestList:
    def test_empty_returns_empty_array(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.get("/api/staff/schedule")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_created_items(self, sqlite_router_client: TestClient) -> None:
        for hours in (1, 2, 3):
            sqlite_router_client.post(
                "/api/staff/schedule",
                json=_payload(scheduled_at=_future_iso(hours)),
            )
        response = sqlite_router_client.get("/api/staff/schedule")
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_channel_filter(self, sqlite_router_client: TestClient) -> None:
        sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(channel_id="gov-ch12", scheduled_at=_future_iso(1)),
        )
        sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(channel_id="edu-ch14", scheduled_at=_future_iso(2)),
        )
        response = sqlite_router_client.get(
            "/api/staff/schedule", params={"channel_id": "gov-ch12"}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["channel_id"] == "gov-ch12"

    def test_unknown_state_returns_422(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.get("/api/staff/schedule", params={"state": "aired"})
        assert response.status_code == 422


class TestPublicComingUp:
    """Locks: the public portal shows only committed (published) premieres.

    After Commit-to-Air enforcement, a ``scheduled`` item is an operator draft
    that has not been approved to air and only ``published`` items are resolved
    onto the channel (egress.source_plan). The public widget must match that —
    advertising ``scheduled`` items would promise programs that may never air,
    and hiding ``published`` ones would hide the actual lineup (PE-1).
    """

    def test_no_db_returns_503(self, no_db_client: TestClient) -> None:
        response = no_db_client.get("/api/public/schedule/coming-up")
        assert response.status_code == 503
        assert "Durable storage is not ready" in response.json()["detail"]

    def test_lists_only_published_premieres(self, sqlite_router_client: TestClient) -> None:
        # A committed (published) premiere: the only thing that should show.
        published = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="meeting-x",
                channel_id="gov-ch12",
                scheduled_at=_future_iso(1),
            ),
        )
        assert published.status_code == 201
        sqlite_router_client.schedule_store.mark_published(  # type: ignore[attr-defined]
            [uuid.UUID(published.json()["id"])]
        )
        # A still-scheduled (unapproved) premiere: must be EXCLUDED — this is
        # the PE-1 regression guard. Under the old (scheduled) filter this item
        # would have leaked onto the public widget.
        scheduled = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="meeting-y",
                channel_id="gov-ch12",
                scheduled_at=_future_iso(2),
            ),
        )
        assert scheduled.status_code == 201
        # An embargo entry: excluded regardless of state.
        embargo = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="embargo-1",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_EMBARGO,
                duration_seconds=None,
                scheduled_at=_future_iso(3),
            ),
        )
        assert embargo.status_code == 201

        response = sqlite_router_client.get("/api/public/schedule/coming-up")

        assert response.status_code == 200
        body = response.json()
        assert [row["id"] for row in body] == [published.json()["id"]]
        assert body[0]["mode"] == SCHEDULE_MODE_PREMIERE
        assert body[0]["state"] == SCHEDULE_STATE_PUBLISHED

    def test_channel_filter_applies(self, sqlite_router_client: TestClient) -> None:
        gov = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="gov-1",
                channel_id="gov",
                scheduled_at=_future_iso(1),
            ),
        )
        edu = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="edu-1",
                channel_id="schools",
                scheduled_at=_future_iso(2),
            ),
        )
        _publish(sqlite_router_client, gov.json()["id"])
        _publish(sqlite_router_client, edu.json()["id"])

        response = sqlite_router_client.get(
            "/api/public/schedule/coming-up",
            params={"channel_id": "schools"},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["asset_id"] == "edu-1"

    def test_excludes_past_published_premieres(self, sqlite_router_client: TestClient) -> None:
        past = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="meeting-x",
                channel_id="gov-ch12",
                scheduled_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            ),
        )
        future = sqlite_router_client.post(
            "/api/staff/schedule",
            json=_payload(
                asset_id="meeting-y",
                channel_id="gov-ch12",
                scheduled_at=_future_iso(1),
            ),
        )
        assert past.status_code == 201
        assert future.status_code == 201
        _publish(sqlite_router_client, past.json()["id"])
        _publish(sqlite_router_client, future.json()["id"])

        response = sqlite_router_client.get("/api/public/schedule/coming-up")

        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [future.json()["id"]]


class TestEphemeralScheduleStoreMarkPublished:
    """QA-1: the dev-mode/ephemeral store must support the same publish
    shortcut as the sqlite/Postgres-backed store, so a manual
    ``CIVICCAST_ALLOW_EPHEMERAL_STORES=1`` boot can exercise the full
    premiere lifecycle (including the coming-up filter) without a real
    Postgres commit-to-air round-trip.
    """

    def _seed_asset(self, asset_store, asset_id: str) -> None:  # type: ignore[no-untyped-def]
        from civiccast.vod.models import AssetMetadata

        asset_store.create(
            AssetMetadata(
                asset_id=asset_id,
                title=f"Test asset {asset_id}",
                manifest_url="https://example.gov/manifest.m3u8",
            )
        )

    def test_mark_published_flips_state_and_feeds_coming_up_filter(self) -> None:
        from civiccast.app import _EphemeralAssetStore, _EphemeralScheduleStore
        from civiccast.schedule.models import ScheduleItemCreate

        asset_store = _EphemeralAssetStore()
        schedule_store = _EphemeralScheduleStore(asset_store)
        self._seed_asset(asset_store, "meeting-x")
        self._seed_asset(asset_store, "meeting-y")

        published = schedule_store.create(
            ScheduleItemCreate(
                asset_id="meeting-x",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=datetime.now(UTC) + timedelta(hours=1),
                duration_seconds=3600,
            )
        )
        draft = schedule_store.create(
            ScheduleItemCreate(
                asset_id="meeting-y",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=datetime.now(UTC) + timedelta(hours=2),
                duration_seconds=3600,
            )
        )

        transitioned = schedule_store.mark_published([published.id])

        assert transitioned == 1
        rows = schedule_store.list(states=(SCHEDULE_STATE_PUBLISHED,))
        assert [row.id for row in rows] == [published.id]
        assert schedule_store.get(published.id).state == SCHEDULE_STATE_PUBLISHED
        # The still-scheduled draft is untouched and excluded from the filter.
        assert schedule_store.get(draft.id).state == SCHEDULE_STATE_SCHEDULED

    def test_mark_published_ignores_unknown_and_already_cancelled_ids(self) -> None:
        from civiccast.app import _EphemeralAssetStore, _EphemeralScheduleStore
        from civiccast.schedule.models import ScheduleItemCreate

        asset_store = _EphemeralAssetStore()
        schedule_store = _EphemeralScheduleStore(asset_store)
        self._seed_asset(asset_store, "meeting-x")
        cancelled = schedule_store.create(
            ScheduleItemCreate(
                asset_id="meeting-x",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=datetime.now(UTC) + timedelta(hours=1),
                duration_seconds=3600,
            )
        )
        schedule_store.cancel(cancelled.id)

        assert schedule_store.mark_published([uuid.uuid4()]) == 0
        assert schedule_store.mark_published([cancelled.id]) == 0
        assert schedule_store.mark_published([]) == 0
        assert schedule_store.get(cancelled.id).state == SCHEDULE_STATE_CANCELLED


# ---------------------------------------------------------------------------
# TestGet
# ---------------------------------------------------------------------------


class TestGet:
    def test_returns_201_then_get_returns_200(self, sqlite_router_client: TestClient) -> None:
        post = sqlite_router_client.post("/api/staff/schedule", json=_payload())
        schedule_id = post.json()["id"]
        get = sqlite_router_client.get(f"/api/staff/schedule/{schedule_id}")
        assert get.status_code == 200
        assert get.json()["id"] == schedule_id

    def test_unknown_id_returns_404(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.get(f"/api/staff/schedule/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TestCancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancels_a_scheduled_item(self, sqlite_router_client: TestClient) -> None:
        post = sqlite_router_client.post("/api/staff/schedule", json=_payload())
        schedule_id = post.json()["id"]
        cancel = sqlite_router_client.post(f"/api/staff/schedule/{schedule_id}/cancel")
        assert cancel.status_code == 200
        assert cancel.json()["state"] == SCHEDULE_STATE_CANCELLED

    def test_cancel_idempotent(self, sqlite_router_client: TestClient) -> None:
        post = sqlite_router_client.post("/api/staff/schedule", json=_payload())
        schedule_id = post.json()["id"]
        sqlite_router_client.post(f"/api/staff/schedule/{schedule_id}/cancel")
        # Second cancel returns 200 with the cancelled state.
        again = sqlite_router_client.post(f"/api/staff/schedule/{schedule_id}/cancel")
        assert again.status_code == 200
        assert again.json()["state"] == SCHEDULE_STATE_CANCELLED

    def test_unknown_id_returns_404(self, sqlite_router_client: TestClient) -> None:
        response = sqlite_router_client.post(f"/api/staff/schedule/{uuid.uuid4()}/cancel")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestConflictResponse  (mocked store — the real EXCLUDE constraint
# only fires on Postgres, so the SQLite fixture can't trigger it.
# This pins the 409 response shape end-to-end.)
# ---------------------------------------------------------------------------


class TestConflictResponse:
    def test_409_carries_conflicting_item_payload(self) -> None:
        app = create_app()

        existing = ScheduleItemResponse(
            id=uuid.uuid4(),
            asset_id="city-council-2026-05-08",
            channel_id="gov-ch12",
            mode=SCHEDULE_MODE_PREMIERE,
            state=SCHEDULE_STATE_SCHEDULED,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
            duration_seconds=3 * 3600,
            notes=None,
            created_at=datetime.now(UTC),
        )

        mock_store = MagicMock()
        mock_store.create.side_effect = ScheduleConflictError(
            "Schedule conflict on channel 'gov-ch12'.",
            conflicting_item=existing,
        )
        app.dependency_overrides[get_schedule_store] = lambda: mock_store

        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.post("/api/staff/schedule", json=_payload())

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Schedule conflict" in detail["message"]
        assert detail["conflicting_item"]["asset_id"] == "city-council-2026-05-08"
        assert detail["conflicting_item"]["channel_id"] == "gov-ch12"

    def test_404_propagates_from_store(self) -> None:
        app = create_app()
        mock_store = MagicMock()
        mock_store.cancel.side_effect = ScheduleItemNotFoundError("missing")
        app.dependency_overrides[get_schedule_store] = lambda: mock_store

        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
            response = c.post(f"/api/staff/schedule/{uuid.uuid4()}/cancel")

        assert response.status_code == 404
