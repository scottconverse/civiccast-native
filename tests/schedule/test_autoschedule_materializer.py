# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 slice 4 — rolling-window materializer (compile rules -> schedule_items).

Exercises civiccast.schedule.autoschedule_materializer.compile_rules end to end
on SQLite: a full compile fills the daypart slots with picked assets, repeat-
prevention limits placements across the window, a second compile is idempotent
(everything already occupied), last_materialized_at is stamped, a dangling rule
is reported (not fatal), and empty / unplayable picks leave slots unfilled.

The Postgres EXCLUDE-overlap conflict-skip path (SQLite has no EXCLUDE) is
exercised by forcing an IntegrityError on the per-slot flush — see
test_insert_conflict_is_skipped_not_fatal (step-6 audit TEST-002).
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_materializer import _materialize_rule, compile_rules
from civiccast.schedule.autoschedule_models import (
    AssetQuery,
    AutoScheduleRule,
    SavedSearch,
    ScheduleBlock,
)
from civiccast.schedule.autoschedule_store import AutoScheduleStore
from civiccast.schedule.models import (
    ASSET_STATE_VALIDATED,
    SCHEDULE_STATE_PUBLISHED,
    Asset,
    ScheduleItem,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # anchor; slots start 2026-06-01


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'materialize.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@contextmanager
def _session(engine: Engine) -> Iterator[Session]:
    with Session(bind=engine) as s:
        yield s


def _store(engine: Engine) -> AutoScheduleStore:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as s:
            yield s

    return AutoScheduleStore(factory)


def _seed_assets(engine: Engine, rows: list[tuple[str, str, int | None, datetime | None]]) -> None:
    with Session(bind=engine) as s:
        for asset_id, body, duration, published in rows:
            s.add(
                Asset(
                    asset_id=asset_id,
                    title=f"{body} {asset_id}",
                    meeting_body=body,
                    state=ASSET_STATE_VALIDATED,
                    retention_policy="default",
                    duration_seconds=duration,
                    published_at=published,
                )
            )
        s.commit()


def _council_search(sid: str = "ss_council") -> SavedSearch:
    return SavedSearch(
        saved_search_id=sid,
        name="Council",
        query=AssetQuery(meeting_body="City Council", states=[ASSET_STATE_VALIDATED]),
        created_at=_T0,
        updated_at=_T0,
    )


def _daily_block(bid: str = "sb_evening", channel: str = "public") -> ScheduleBlock:
    return ScheduleBlock(
        block_id=bid,
        channel_id=channel,
        name="Evening",
        start_minute=18 * 60,
        end_minute=19 * 60,
        days_of_week=[0, 1, 2, 3, 4, 5, 6],
        created_at=_T0,
        updated_at=_T0,
    )


def _rule(**kwargs: object) -> AutoScheduleRule:
    base: dict[str, object] = {
        "rule_id": "asr_evening",
        "name": "Evening council",
        "saved_search_id": "ss_council",
        "channel_id": "public",
        "schedule_block_id": "sb_evening",
        "pick_strategy": "newest",
        "rolling_window_days": 14,
        "repeat_prevention_days": 0,
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kwargs)
    return AutoScheduleRule(**base)  # type: ignore[arg-type]


def _item_count(engine: Engine) -> int:
    with Session(bind=engine) as s:
        return s.scalar(select(func.count()).select_from(ScheduleItem)) or 0


def _compile(engine: Engine, store: AutoScheduleStore, **kw: object):  # type: ignore[no-untyped-def]
    with _session(engine) as s:
        return compile_rules(s, store, now=_NOW, rng=random.Random(0), **kw)


# ---------------------------------------------------------------------------


def test_full_compile_fills_every_daypart_slot(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())  # newest + N=0

    report = _compile(engine, store)

    # 14-day daily window -> 14 slots, all filled (newest = a1 every day, N=0).
    [result] = report.results
    assert result.slots_considered == 14
    assert result.items_created == 14
    assert _item_count(engine) == 14
    assert {f.asset_id for f in result.filled} == {"a1"}


def test_materialized_items_are_auto_approved_published_not_scheduled(engine: Engine) -> None:
    """Commit-to-Air gate (spec test c): a query-rule item is auto-approved
    because the operator approved the rule itself, so it is born
    ``published`` — it airs with no manual commit, unlike a manually-added
    schedule item which stays ``scheduled`` until committed."""
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())

    report = _compile(engine, store)

    [result] = report.results
    assert result.items_created == 14
    with Session(bind=engine) as s:
        states = {
            row[0]
            for row in s.execute(
                select(ScheduleItem.state).where(
                    ScheduleItem.id.in_([uuid.UUID(f.schedule_item_id) for f in result.filled])
                )
            )
        }
    assert states == {SCHEDULE_STATE_PUBLISHED}


def test_repeat_prevention_limits_distinct_assets(engine: Engine) -> None:
    _seed_assets(
        engine,
        [
            ("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC)),
            ("a2", "City Council", 1800, datetime(2026, 5, 20, tzinfo=UTC)),
            ("a3", "City Council", 1800, datetime(2026, 5, 10, tzinfo=UTC)),
        ],
    )
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    # N >= window -> each asset airs at most once; only 3 assets exist.
    store.upsert_auto_schedule_rule(_rule(repeat_prevention_days=30))

    report = _compile(engine, store)
    [result] = report.results
    assert result.items_created == 3
    assert {f.asset_id for f in result.filled} == {"a1", "a2", "a3"}
    assert result.skipped_no_asset == 11  # remaining slots: nothing left to pick


def test_recompile_is_idempotent(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())

    first = _compile(engine, store)
    assert first.items_created == 14
    second = _compile(engine, store)
    assert second.items_created == 0
    [result] = second.results
    assert result.skipped_occupied == 14
    assert _item_count(engine) == 14  # no duplicates


def test_last_materialized_at_is_stamped(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())

    _compile(engine, store)
    stamped = store.get_auto_schedule_rule("asr_evening")
    assert stamped is not None
    assert stamped.last_materialized_at == _NOW


def test_dangling_rule_is_reported_not_fatal(engine: Engine) -> None:
    store = _store(engine)
    # Rule references a saved search + block that were never created.
    store.upsert_auto_schedule_rule(
        _rule(saved_search_id="ss_missing", schedule_block_id="sb_missing")
    )

    report = _compile(engine, store)
    [result] = report.results
    assert result.missing_dependency is True
    assert result.items_created == 0
    assert _item_count(engine) == 0


def test_no_matching_asset_leaves_slots_empty(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "Parks Board", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())  # filters meeting_body=City Council
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())

    report = _compile(engine, store)
    [result] = report.results
    assert result.items_created == 0
    assert result.skipped_no_asset == 14


def test_unplayable_asset_without_duration_is_skipped(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "City Council", None, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule())

    report = _compile(engine, store)
    [result] = report.results
    assert result.items_created == 0
    assert result.skipped_unplayable == 14


def test_disabled_rule_is_not_compiled(engine: Engine) -> None:
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])
    store = _store(engine)
    store.upsert_saved_search(_council_search())
    store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule(enabled=False))

    report = _compile(engine, store)
    assert report.results == []
    assert _item_count(engine) == 0


def test_insert_conflict_is_skipped_not_fatal(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # SQLite has no EXCLUDE constraint, so simulate the Postgres overlap race
    # directly: force the per-slot flush to raise IntegrityError. The materializer
    # must roll back that SAVEPOINT, count skipped_conflict, and keep going — no
    # exception escapes, no items are written (step-6 audit TEST-002).
    _seed_assets(engine, [("a1", "City Council", 1800, datetime(2026, 5, 30, tzinfo=UTC))])

    def _raise_integrity(*_a: object, **_k: object) -> None:
        raise IntegrityError("INSERT", {}, Exception("simulated EXCLUDE overlap"))

    with _session(engine) as session:
        session.autoflush = False  # reads must not trip the patched flush
        monkeypatch.setattr(session, "flush", _raise_integrity)
        result = _materialize_rule(
            session,
            rule=_rule(),
            search=_council_search(),
            block=_daily_block(),
            now=_NOW,
            tz=UTC,
            rng=None,
        )
    assert result.items_created == 0
    assert result.skipped_conflict == 14  # every daily slot's insert "conflicted"
    assert _item_count(engine) == 0
