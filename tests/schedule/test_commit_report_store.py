# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence tests for commit-to-air reports (S4 slice 1).

Exercises PostgresScheduleStore.upsert_commit_report / get_commit_report /
list_commit_reports against the ephemeral SQLite engine. No asset seeding is
needed — the report columns are soft string references with no FK.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from civiccast.schedule.commit_models import (
    DISPATCH_STATUS_ERROR,
    DISPATCH_STATUS_PENDING,
    DISPATCH_STATUS_QUEUED,
    CommitToAirReport,
)
from civiccast.schedule.store import PostgresScheduleStore

_BASE = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _report(
    report_id: str,
    *,
    channel_id: str = "public",
    approved_at: datetime = _BASE,
    dispatch_status: str = DISPATCH_STATUS_PENDING,
    created_at: datetime = _BASE,
    **overrides: object,
) -> CommitToAirReport:
    fields: dict[str, object] = {
        "report_id": report_id,
        "channel_id": channel_id,
        "occurrence_id": f"occ-{report_id}",
        "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
        "asset_id": "city-council-2026-06-15",
        "title": "City Council",
        "scheduled_at": datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC),
        "duration_seconds": 5400,
        "approved_by_operator_id": "dana",
        "approved_at": approved_at,
        "dispatch_status": dispatch_status,
        "created_at": created_at,
        "updated_at": created_at,
    }
    fields.update(overrides)
    return CommitToAirReport(**fields)  # type: ignore[arg-type]


class TestUpsertAndGet:
    def test_insert_then_get_round_trips(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        stored = store.upsert_commit_report(_report("ctar_1"))
        fetched = store.get_commit_report("ctar_1")
        assert fetched is not None
        assert fetched.report_id == "ctar_1"
        assert fetched.dispatch_status == DISPATCH_STATUS_PENDING
        # Stored value is what get() returns.
        assert fetched == stored

    def test_get_missing_returns_none(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        assert store.get_commit_report("nope") is None

    def test_upsert_updates_in_place_and_preserves_created_at(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        original_created = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)
        store.upsert_commit_report(_report("ctar_1", created_at=original_created))
        # Re-upsert the SAME id advancing the dispatch status, and (mischievously)
        # passing a different created_at — the store must ignore it.
        dispatch_ts = datetime(2026, 6, 15, 12, 5, 0, tzinfo=UTC)
        store.upsert_commit_report(
            _report(
                "ctar_1",
                created_at=datetime(2030, 1, 1, tzinfo=UTC),  # must NOT win
                dispatch_status=DISPATCH_STATUS_QUEUED,
                dispatch_timestamp=dispatch_ts,
            )
        )
        fetched = store.get_commit_report("ctar_1")
        assert fetched is not None
        assert fetched.dispatch_status == DISPATCH_STATUS_QUEUED
        assert fetched.dispatch_timestamp == dispatch_ts
        # created_at is preserved from the first write, not overwritten.
        assert fetched.created_at == original_created
        # Exactly one row — upsert, not a second insert.
        assert len(store.list_commit_reports(channel_id="public")) == 1

    def test_upsert_can_record_error_detail(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        store.upsert_commit_report(_report("ctar_1"))
        store.upsert_commit_report(
            _report(
                "ctar_1",
                dispatch_status=DISPATCH_STATUS_ERROR,
                dispatch_error_detail="egress daemon unreachable",
            )
        )
        fetched = store.get_commit_report("ctar_1")
        assert fetched is not None
        assert fetched.dispatch_status == DISPATCH_STATUS_ERROR
        assert fetched.dispatch_error_detail == "egress daemon unreachable"


class TestList:
    def test_filters_by_channel(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        store.upsert_commit_report(_report("ctar_a", channel_id="public"))
        store.upsert_commit_report(_report("ctar_b", channel_id="gov"))
        public = store.list_commit_reports(channel_id="public")
        assert [r.report_id for r in public] == ["ctar_a"]

    def test_orders_by_approved_at_desc(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        store.upsert_commit_report(_report("ctar_old", approved_at=_BASE))
        store.upsert_commit_report(_report("ctar_new", approved_at=_BASE + timedelta(hours=1)))
        rows = store.list_commit_reports(channel_id="public")
        assert [r.report_id for r in rows] == ["ctar_new", "ctar_old"]

    def test_date_range_is_half_open(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        t0 = _BASE
        t1 = _BASE + timedelta(hours=1)
        t2 = _BASE + timedelta(hours=2)
        store.upsert_commit_report(_report("ctar_t0", approved_at=t0))
        store.upsert_commit_report(_report("ctar_t1", approved_at=t1))
        store.upsert_commit_report(_report("ctar_t2", approved_at=t2))
        # [t0, t2): includes t0 and t1, excludes t2.
        rows = store.list_commit_reports(channel_id="public", start_at=t0, end_at=t2)
        ids = {r.report_id for r in rows}
        assert ids == {"ctar_t0", "ctar_t1"}

    def test_limit_is_clamped(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        for i in range(3):
            store.upsert_commit_report(
                _report(f"ctar_{i}", approved_at=_BASE + timedelta(minutes=i))
            )
        assert len(store.list_commit_reports(channel_id="public", limit=1)) == 1
        # 0 clamps up to 1 (no unbounded/zero scans).
        assert len(store.list_commit_reports(channel_id="public", limit=0)) == 1
        # A large limit returns everything available.
        assert len(store.list_commit_reports(channel_id="public", limit=10_000)) == 3

    def test_empty_channel_returns_empty_list(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        store = PostgresScheduleStore(session_factory)
        assert store.list_commit_reports(channel_id="nobody") == []
