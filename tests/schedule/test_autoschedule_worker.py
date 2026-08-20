# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 periodic-compile worker: interval gating, failure isolation, real compile.

AutoScheduleCompileWorker.tick runs compile_rules on its interval (first tick
fires immediately), swallows a failing compile so the loop survives, and — with
the real compile_rules — materializes an enabled rule's picks into schedule_items.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_materializer import MaterializeReport
from civiccast.schedule.autoschedule_models import (
    AssetQuery,
    AutoScheduleRule,
    SavedSearch,
    ScheduleBlock,
)
from civiccast.schedule.autoschedule_store import AutoScheduleStore
from civiccast.schedule.autoschedule_worker import (
    AutoScheduleCompileSettings,
    AutoScheduleCompileWorker,
)
from civiccast.schedule.models import ASSET_STATE_VALIDATED, Asset, ScheduleItem

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
_T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    eng = create_engine(f"sqlite:///{tmp_path / 'worker.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as s:
            yield s

    return factory


def _council_search() -> SavedSearch:
    return SavedSearch(
        saved_search_id="ss_council",
        name="Council",
        query=AssetQuery(meeting_body="City Council", states=[ASSET_STATE_VALIDATED]),
        created_at=_T0,
        updated_at=_T0,
    )


def _daily_block() -> ScheduleBlock:
    return ScheduleBlock(
        block_id="sb_evening",
        channel_id="public",
        name="Evening",
        start_minute=18 * 60,
        end_minute=19 * 60,
        days_of_week=[0, 1, 2, 3, 4, 5, 6],
        created_at=_T0,
        updated_at=_T0,
    )


def _rule(saved_search_id: str, block_id: str) -> AutoScheduleRule:
    return AutoScheduleRule(
        rule_id="asr_evening",
        name="Evening council",
        saved_search_id=saved_search_id,
        channel_id="public",
        schedule_block_id=block_id,
        pick_strategy="newest",
        rolling_window_days=14,
        repeat_prevention_days=0,
        created_at=_T0,
        updated_at=_T0,
    )


def test_first_tick_compiles_then_gates_until_interval(engine: Engine) -> None:
    calls: list[float] = []

    def fake_compile(_session, _store, *, now, tz) -> MaterializeReport:  # type: ignore[no-untyped-def]
        calls.append(now.timestamp())
        return MaterializeReport()

    worker = AutoScheduleCompileWorker(
        _factory(engine),
        clock=lambda: _NOW,
        settings=AutoScheduleCompileSettings(compile_interval_seconds=3600.0),
        compile_fn=fake_compile,
    )
    assert worker.tick(monotonic=0.0) is not None  # first tick fires immediately
    assert worker.tick(monotonic=100.0) is None  # within the interval -> not due
    assert worker.tick(monotonic=3700.0) is not None  # past the interval -> fires
    assert len(calls) == 2


def test_compile_failure_is_swallowed_and_does_not_hot_loop(engine: Engine) -> None:
    def boom(_session, _store, *, now, tz) -> MaterializeReport:  # type: ignore[no-untyped-def]
        raise RuntimeError("compile blew up")

    worker = AutoScheduleCompileWorker(
        _factory(engine),
        clock=lambda: _NOW,
        settings=AutoScheduleCompileSettings(compile_interval_seconds=3600.0),
        compile_fn=boom,
    )
    assert worker.tick(monotonic=0.0) is None  # no exception escapes
    assert worker.tick(monotonic=100.0) is None  # interval advanced -> no hot loop


def test_real_compile_materializes_enabled_rule(engine: Engine) -> None:
    factory = _factory(engine)
    with factory() as session:
        session.add(
            Asset(
                asset_id="a1",
                title="City Council Regular Meeting",
                meeting_body="City Council",
                state=ASSET_STATE_VALIDATED,
                retention_policy="default",
                duration_seconds=1800,
                published_at=datetime(2026, 5, 30, tzinfo=UTC),
            )
        )
        session.commit()

    store = AutoScheduleStore(factory)
    search = store.upsert_saved_search(_council_search())
    block = store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule(search.saved_search_id, block.block_id))

    worker = AutoScheduleCompileWorker(factory, store=store, clock=lambda: _NOW)
    report = worker.tick(monotonic=0.0)
    assert report is not None
    assert report.items_created == 14  # 14-day daily window, one matching asset
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(ScheduleItem))
    assert count == 14


def test_interval_gate_holds_over_the_real_compile_path(engine: Engine) -> None:
    # The gate + the real compile_rules path proven together (step-6 audit
    # TEST-003): a first tick compiles; a second tick within the interval is
    # gated, so no duplicate items are written.
    factory = _factory(engine)
    with factory() as session:
        session.add(
            Asset(
                asset_id="a1",
                title="City Council Regular Meeting",
                meeting_body="City Council",
                state=ASSET_STATE_VALIDATED,
                retention_policy="default",
                duration_seconds=1800,
                published_at=datetime(2026, 5, 30, tzinfo=UTC),
            )
        )
        session.commit()
    store = AutoScheduleStore(factory)
    search = store.upsert_saved_search(_council_search())
    block = store.upsert_schedule_block(_daily_block())
    store.upsert_auto_schedule_rule(_rule(search.saved_search_id, block.block_id))

    worker = AutoScheduleCompileWorker(factory, store=store, clock=lambda: _NOW)  # real compile_fn
    first = worker.tick(monotonic=0.0)
    assert first is not None and first.items_created == 14
    assert worker.tick(monotonic=100.0) is None  # within the default interval -> gated
    with factory() as session:
        assert (session.scalar(select(func.count()).select_from(ScheduleItem)) or 0) == 14
