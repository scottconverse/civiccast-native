# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The publish dashboard must not issue one query per asset, forever.

GauntletGate PE-1 (Major, 2026-07-21). ``GET /api/staff/publish/assets`` calls
``asset_store.list_all()`` and then ``build_publish_dashboard()`` called
``store.get_run(asset.asset_id)`` once per row, each opening its own session and
issuing its own SELECT. Query count was O(N) over every asset the station has
EVER recorded, growing forever. This is the primary screen for verifying the
spec's three-tier publish non-negotiable, so operators load it routinely; a
station recording public meetings for years would issue thousands of sequential
round trips on every load.

These tests count REAL SQL round trips through a SQLAlchemy event hook rather
than counting method calls -- a batched method that still looped internally
would pass the latter and fail the former.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civiccast.publish.models import (
    PublishRunRecord,
    PublishSurfaceStateValue,
    PublishSurfaceStatus,
)
from civiccast.publish.service import build_publish_dashboard
from civiccast.publish.store import PUBLISH_RUN_FETCH_CHUNK, PostgresPublishStore
from civiccast.schedule.models import StaffAssetRow

APPROVED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE publish_runs ("
                "asset_id VARCHAR(160) PRIMARY KEY, "
                "operator_id VARCHAR(160) NOT NULL, "
                "operator_display_name VARCHAR(240) NOT NULL, "
                "approved_at DATETIME NOT NULL, "
                "surfaces_json TEXT NOT NULL, "
                "audit_events_json TEXT NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    maker = sessionmaker(bind=engine, future=True, expire_on_commit=False, class_=Session)

    @contextmanager
    def _factory() -> Iterator[Session]:
        with maker() as session:
            yield session

    return _factory


@contextmanager
def counted_selects(engine: Engine) -> Iterator[list[str]]:
    """Record every SELECT against publish_runs that actually reaches the DB."""

    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if "publish_runs" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _asset(asset_id: str) -> StaffAssetRow:
    """A real StaffAssetRow -- a stub would not exercise the same field reads."""

    return StaffAssetRow(
        asset_id=asset_id,
        title=f"Meeting {asset_id}",
        state="recorded",
        meeting_body="city-council",
        retention_policy="permanent",
    )


def _record(asset_id: str) -> PublishRunRecord:
    surface = PublishSurfaceStatus(
        id="portal",
        label="Portal",
        kind="canonical",
        state=cast(PublishSurfaceStateValue, "succeeded"),
        approval="approved",
        required=True,
        completed_at=APPROVED_AT,
        health="ok",
        message="Portal publish complete.",
        next_step="No action required.",
    )
    return PublishRunRecord(
        asset_id=asset_id,
        operator_id="staff-1",
        operator_display_name="Avery Operator",
        approved_at=APPROVED_AT,
        surfaces=[surface],
        audit_events=[],
    )


def _seed(store: PostgresPublishStore, count: int) -> list[StaffAssetRow]:
    assets = [_asset(f"council-{index:04d}") for index in range(count)]
    for asset in assets:
        store.upsert_run(_record(asset.asset_id))
    return assets


def test_dashboard_query_count_does_not_grow_with_the_asset_count(
    engine: Engine, session_factory
) -> None:
    """40 assets must not cost 4x what 10 assets cost."""

    store = PostgresPublishStore(session_factory)

    small = _seed(store, 10)
    with counted_selects(engine) as small_selects:
        build_publish_dashboard(small, store)

    large = _seed(store, 40)
    with counted_selects(engine) as large_selects:
        build_publish_dashboard(large, store)

    assert len(small_selects) == 1, (
        f"10 assets issued {len(small_selects)} SELECTs against publish_runs; "
        "the dashboard must batch them into one."
    )
    assert len(large_selects) == 1, (
        f"40 assets issued {len(large_selects)} SELECTs against publish_runs "
        f"(10 assets issued {len(small_selects)}). Query count is still growing "
        "with the station's history."
    )


def test_batched_fetch_returns_the_same_records_the_per_row_lookup_did(
    engine: Engine, session_factory
) -> None:
    """Batching must not change what the dashboard shows."""

    store = PostgresPublishStore(session_factory)
    assets = _seed(store, 5)
    asset_ids = [asset.asset_id for asset in assets]

    one_by_one = {asset_id: store.get_run(asset_id) for asset_id in asset_ids}
    batched = store.get_runs(asset_ids)

    assert batched == {key: value for key, value in one_by_one.items() if value is not None}
    for asset_id in asset_ids:
        assert batched[asset_id].surfaces[0].state == "succeeded"


def test_assets_with_no_publish_run_are_simply_absent(engine: Engine, session_factory) -> None:
    """A never-approved asset has no row; it must not raise or fabricate one."""

    store = PostgresPublishStore(session_factory)
    _seed(store, 2)

    batched = store.get_runs(["council-0000", "council-0001", "never-approved"])

    assert set(batched) == {"council-0000", "council-0001"}
    assert store.get_run("never-approved") is None


def test_an_empty_dashboard_issues_no_query_at_all(engine: Engine, session_factory) -> None:
    store = PostgresPublishStore(session_factory)

    with counted_selects(engine) as selects:
        result = build_publish_dashboard([], store)

    assert selects == []
    assert result.summary.total_assets == 0


def test_more_assets_than_the_chunk_size_stay_bounded_and_complete(
    engine: Engine, session_factory
) -> None:
    """SQLite and Postgres both cap bind parameters per statement.

    A single IN(...) over every asset a station has ever recorded would
    eventually exceed that cap, so the fetch chunks. The point of the chunk is
    that the query count stays bounded by chunk size, not by asset count -- and
    that no asset is silently dropped at a chunk boundary.
    """

    store = PostgresPublishStore(session_factory)
    count = PUBLISH_RUN_FETCH_CHUNK + 3
    assets = _seed(store, count)

    with counted_selects(engine) as selects:
        dashboard = build_publish_dashboard(assets, store)

    expected_queries = math.ceil(count / PUBLISH_RUN_FETCH_CHUNK)
    assert len(selects) == expected_queries
    assert expected_queries < count  # the whole point
    assert dashboard.summary.total_assets == count
    assert dashboard.summary.portal_live == count, (
        "Every seeded asset has a succeeded portal surface; a dropped chunk "
        "boundary would show up here as a missing publish state."
    )
