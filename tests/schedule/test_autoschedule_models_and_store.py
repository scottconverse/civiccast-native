# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 slice 1 — auto-scheduling data layer: model round-trip + store CRUD.

Covers civiccast.schedule.autoschedule_models (AssetQuery validators,
SavedSearch / ScheduleBlock / AutoScheduleRule Pydantic <-> SA round-trip with
UTC normalization) and civiccast.schedule.autoschedule_store.AutoScheduleStore
(upsert insert + update-in-place preserving created_at, get, list filters +
ordering, delete True/False). SQLite-backed; the live-Postgres head + namespace
checks live in tests/live/test_real_postgres.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_models import (
    AssetQuery,
    AutoScheduleRule,
    SavedSearch,
    ScheduleBlock,
)
from civiccast.schedule.autoschedule_store import AutoScheduleStore

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AutoScheduleStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'autosched.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield AutoScheduleStore(factory)
    finally:
        eng.dispose()


def _saved_search(sid: str = "ss_news", **query_kwargs: object) -> SavedSearch:
    return SavedSearch(
        saved_search_id=sid,
        name="Council meetings",
        description="Recent council recordings",
        query=AssetQuery(meeting_body="City Council", **query_kwargs),  # type: ignore[arg-type]
        created_at=_T0,
        updated_at=_T0,
    )


def _block(bid: str = "sb_prime", channel_id: str = "public", **kwargs: object) -> ScheduleBlock:
    base: dict[str, object] = {
        "block_id": bid,
        "channel_id": channel_id,
        "name": "Prime time",
        "start_minute": 18 * 60,
        "end_minute": 22 * 60,
        "days_of_week": [2, 0, 4],  # deliberately unsorted with a dup-free set
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kwargs)
    return ScheduleBlock(**base)  # type: ignore[arg-type]


def _rule(rid: str = "asr_news", channel_id: str = "public", **kwargs: object) -> AutoScheduleRule:
    base: dict[str, object] = {
        "rule_id": rid,
        "name": "Fill prime with council",
        "saved_search_id": "ss_news",
        "channel_id": channel_id,
        "schedule_block_id": "sb_prime",
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kwargs)
    return AutoScheduleRule(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AssetQuery validators
# ---------------------------------------------------------------------------


def test_asset_query_defaults_match_everything_newest_first() -> None:
    q = AssetQuery()
    assert q.states == []
    assert q.order_by == "published_at"
    assert q.order_desc is True


def test_asset_query_rejects_inverted_duration_range() -> None:
    with pytest.raises(ValueError, match="max_duration_seconds"):
        AssetQuery(min_duration_seconds=600, max_duration_seconds=300)


def test_asset_query_rejects_inverted_published_window() -> None:
    with pytest.raises(ValueError, match="published_before"):
        AssetQuery(
            published_after=datetime(2026, 2, 1, tzinfo=UTC),
            published_before=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_asset_query_forbids_unknown_keys() -> None:
    with pytest.raises(ValueError):
        AssetQuery.model_validate({"not_a_field": 1})


# ---------------------------------------------------------------------------
# Model round-trip (in-memory, no store) — UTC normalization + JSON fidelity
# ---------------------------------------------------------------------------


def test_schedule_block_canonicalizes_days_of_week() -> None:
    block = _block(days_of_week=[4, 0, 2, 0])
    assert block.days_of_week == [0, 2, 4]


def test_schedule_block_rejects_empty_days() -> None:
    with pytest.raises(ValueError, match="at least one weekday"):
        _block(days_of_week=[])


def test_schedule_block_rejects_out_of_range_day() -> None:
    with pytest.raises(ValueError, match="must be 0"):
        _block(days_of_week=[7])


def test_schedule_block_rejects_inverted_active_dates() -> None:
    with pytest.raises(ValueError, match="active_until"):
        _block(active_from=date(2026, 3, 1), active_until=date(2026, 2, 1))


# ---------------------------------------------------------------------------
# SavedSearch store CRUD
# ---------------------------------------------------------------------------


def test_saved_search_upsert_insert_then_get(store: AutoScheduleStore) -> None:
    stored = store.upsert_saved_search(_saved_search())
    assert stored.saved_search_id == "ss_news"
    assert stored.query.meeting_body == "City Council"
    fetched = store.get_saved_search("ss_news")
    assert fetched is not None
    assert fetched.query.meeting_body == "City Council"
    # UTC re-attached on the SQLite round-trip.
    assert fetched.created_at.tzinfo is not None


def test_saved_search_get_missing_returns_none(store: AutoScheduleStore) -> None:
    assert store.get_saved_search("nope") is None


def test_saved_search_upsert_update_preserves_created_at(store: AutoScheduleStore) -> None:
    store.upsert_saved_search(_saved_search())
    updated = _saved_search()
    updated.name = "Renamed"
    updated.query = AssetQuery(title_contains="budget")
    # A new updated_at sentinel that the store must override with "now".
    updated.updated_at = datetime(2030, 1, 1, tzinfo=UTC)
    result = store.upsert_saved_search(updated)
    assert result.name == "Renamed"
    assert result.query.title_contains == "budget"
    assert result.query.meeting_body is None
    # created_at preserved from the original insert, not the update payload.
    assert result.created_at == _T0
    # updated_at is the store's write instant, not the caller's 2030 sentinel.
    assert result.updated_at.year != 2030


def test_saved_search_list_orders_by_name(store: AutoScheduleStore) -> None:
    store.upsert_saved_search(_saved_search(sid="ss_b"))
    s_a = _saved_search(sid="ss_a")
    s_a.name = "Alpha"
    store.upsert_saved_search(s_a)
    names = [s.name for s in store.list_saved_searches()]
    assert names == sorted(names)


def test_saved_search_delete(store: AutoScheduleStore) -> None:
    store.upsert_saved_search(_saved_search())
    assert store.delete_saved_search("ss_news") is True
    assert store.delete_saved_search("ss_news") is False
    assert store.get_saved_search("ss_news") is None


# ---------------------------------------------------------------------------
# ScheduleBlock store CRUD
# ---------------------------------------------------------------------------


def test_schedule_block_round_trip_through_store(store: AutoScheduleStore) -> None:
    stored = store.upsert_schedule_block(
        _block(active_from=date(2026, 1, 1), active_until=date(2026, 12, 31))
    )
    assert stored.days_of_week == [0, 2, 4]
    fetched = store.get_schedule_block("sb_prime")
    assert fetched is not None
    assert fetched.start_minute == 18 * 60
    assert fetched.end_minute == 22 * 60
    assert fetched.active_from == date(2026, 1, 1)
    assert fetched.enabled is True


def test_schedule_block_list_filters(store: AutoScheduleStore) -> None:
    store.upsert_schedule_block(_block(bid="sb_a", channel_id="public"))
    store.upsert_schedule_block(
        _block(bid="sb_b", channel_id="gov", start_minute=6 * 60, enabled=False)
    )
    assert {b.block_id for b in store.list_schedule_blocks()} == {"sb_a", "sb_b"}
    assert [b.block_id for b in store.list_schedule_blocks(channel_id="gov")] == ["sb_b"]
    assert [b.block_id for b in store.list_schedule_blocks(enabled_only=True)] == ["sb_a"]


def test_schedule_block_update_in_place(store: AutoScheduleStore) -> None:
    store.upsert_schedule_block(_block())
    changed = _block(name="Overnight", start_minute=0, end_minute=6 * 60, enabled=False)
    result = store.upsert_schedule_block(changed)
    assert result.name == "Overnight"
    assert result.enabled is False
    assert result.created_at == _T0


def test_schedule_block_delete(store: AutoScheduleStore) -> None:
    store.upsert_schedule_block(_block())
    assert store.delete_schedule_block("sb_prime") is True
    assert store.delete_schedule_block("sb_prime") is False


# ---------------------------------------------------------------------------
# AutoScheduleRule store CRUD
# ---------------------------------------------------------------------------


def test_auto_schedule_rule_round_trip(store: AutoScheduleStore) -> None:
    stored = store.upsert_auto_schedule_rule(
        _rule(pick_strategy="random_result", rolling_window_days=45, repeat_prevention_days=7)
    )
    assert stored.pick_strategy == "random_result"
    assert stored.rolling_window_days == 45
    assert stored.repeat_prevention_days == 7
    assert stored.last_materialized_at is None
    fetched = store.get_auto_schedule_rule("asr_news")
    assert fetched is not None
    assert fetched.priority == 100
    assert fetched.enabled is True


def test_auto_schedule_rule_window_fences() -> None:
    # Fence values around the 14..60 rolling-window bounds (step-6 audit TEST-005);
    # 5/90 would also pass a wrong `gt=14` validator — the fences catch that.
    _rule(rolling_window_days=14)  # floor — valid
    _rule(rolling_window_days=60)  # ceiling — valid
    with pytest.raises(ValueError):
        _rule(rolling_window_days=13)  # one below the floor
    with pytest.raises(ValueError):
        _rule(rolling_window_days=61)  # one above the ceiling


def test_auto_schedule_rule_rejects_negative_repeat_window() -> None:
    # repeat_prevention_days must be >= 0 (step-6 audit TEST-006); a negative
    # value would invert the planner's exclusion window.
    _rule(repeat_prevention_days=0)  # disabled — valid
    with pytest.raises(ValueError):
        _rule(repeat_prevention_days=-1)


def test_auto_schedule_rule_list_orders_by_priority(store: AutoScheduleStore) -> None:
    store.upsert_auto_schedule_rule(_rule(rid="asr_low", priority=200))
    store.upsert_auto_schedule_rule(_rule(rid="asr_high", priority=10))
    store.upsert_auto_schedule_rule(_rule(rid="asr_off", channel_id="gov", enabled=False))
    rules = store.list_auto_schedule_rules(channel_id="public")
    assert [r.rule_id for r in rules] == ["asr_high", "asr_low"]
    enabled = store.list_auto_schedule_rules(enabled_only=True)
    assert "asr_off" not in {r.rule_id for r in enabled}


def test_auto_schedule_rule_update_stamps_last_materialized(store: AutoScheduleStore) -> None:
    store.upsert_auto_schedule_rule(_rule())
    changed = _rule(last_materialized_at=datetime(2026, 6, 1, tzinfo=UTC))
    result = store.upsert_auto_schedule_rule(changed)
    assert result.last_materialized_at == datetime(2026, 6, 1, tzinfo=UTC)
    assert result.created_at == _T0


def test_auto_schedule_rule_delete(store: AutoScheduleStore) -> None:
    store.upsert_auto_schedule_rule(_rule())
    assert store.delete_auto_schedule_rule("asr_news") is True
    assert store.delete_auto_schedule_rule("asr_news") is False
