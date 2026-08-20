# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""T-1 — :class:`PostgresCommittedScheduleReader` adapter coverage.

This is the production seam that turns the real schedule store into EPG slots.
Pre-fix it had zero tests; the EPG suite only exercised
``InMemoryCommittedScheduleReader`` and the router tests bypassed the schedule
store entirely. A typo in the state filter, a misnamed title-fallback rung, or
a missing resolver guard would have slipped past CI.

The fake schedule store below mirrors ``PostgresScheduleStore.list``: returns
``ScheduleItemResponse``-shaped objects for the requested ``channel_id`` whose
``state`` is in ``states``. The real store sorts ASC by ``scheduled_at``; we
mirror that.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from civiccast.reporting.schedule_adapter import PostgresCommittedScheduleReader
from civiccast.schedule.models import (
    SCHEDULE_STATE_CANCELLED,
    SCHEDULE_STATE_PUBLISHED,
    SCHEDULE_STATE_SCHEDULED,
)


@dataclass
class _FakeScheduleItem:
    """Minimal shape matching ``ScheduleItemResponse`` for the adapter."""

    id: uuid.UUID
    asset_id: str | None
    asset_title: str | None
    channel_id: str
    scheduled_at: datetime
    duration_seconds: int | None
    state: str = SCHEDULE_STATE_PUBLISHED


class _FakeScheduleStore:
    """Duck-typed for the adapter's ``schedule_store.list(channel_id, states)``.

    The real Postgres store filters by ``states`` server-side; this fake does
    the same in-memory so we can prove the adapter passes the right filter.
    """

    def __init__(self, items: list[_FakeScheduleItem]) -> None:
        self._items = sorted(items, key=lambda it: it.scheduled_at)
        self.last_states_requested: tuple[str, ...] | None = None

    def list(self, *, channel_id: str, states: tuple[str, ...]) -> list[_FakeScheduleItem]:
        self.last_states_requested = states
        return [it for it in self._items if it.channel_id == channel_id and it.state in states]


def _item(
    *,
    schedule_id: uuid.UUID | None = None,
    asset_id: str | None = "asset-1",
    asset_title: str | None = "Council Meeting",
    channel_id: str = "ch1",
    scheduled_at: datetime,
    duration_seconds: int | None = 1800,
    state: str = SCHEDULE_STATE_PUBLISHED,
) -> _FakeScheduleItem:
    return _FakeScheduleItem(
        id=schedule_id or uuid.uuid4(),
        asset_id=asset_id,
        asset_title=asset_title,
        channel_id=channel_id,
        scheduled_at=scheduled_at,
        duration_seconds=duration_seconds,
        state=state,
    )


_BASE = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_only_published_state_is_returned() -> None:
    """The adapter narrows to published-only.

    Per spec §6 "committed schedule": EPG aggregators must NOT see draft/
    scheduled items — those would churn the TV guide. Validates the adapter
    requests the right state filter from the store.
    """
    store = _FakeScheduleStore(
        [
            _item(asset_id="published-a", scheduled_at=_BASE),
            _item(
                asset_id="scheduled-b",
                scheduled_at=_BASE + timedelta(minutes=30),
                state=SCHEDULE_STATE_SCHEDULED,
            ),
            _item(
                asset_id="cancelled-c",
                scheduled_at=_BASE + timedelta(minutes=60),
                state=SCHEDULE_STATE_CANCELLED,
            ),
        ]
    )
    reader = PostgresCommittedScheduleReader(store)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE - timedelta(hours=1),
        to_ts=_BASE + timedelta(hours=2),
    )
    assert [s.asset_id for s in slots] == ["published-a"]
    # And the state filter was exactly ``(published,)``.
    assert store.last_states_requested == (SCHEDULE_STATE_PUBLISHED,)


def test_half_open_window_excludes_to_ts() -> None:
    """A slot exactly at ``from_ts`` is INCLUDED; a slot exactly at ``to_ts``
    is EXCLUDED (half-open ``[from, to)``). The S23 window contract.
    """
    store = _FakeScheduleStore(
        [
            _item(asset_id="at-from", scheduled_at=_BASE),
            _item(asset_id="middle", scheduled_at=_BASE + timedelta(minutes=30)),
            _item(asset_id="at-to", scheduled_at=_BASE + timedelta(hours=1)),
        ]
    )
    reader = PostgresCommittedScheduleReader(store)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE,
        to_ts=_BASE + timedelta(hours=1),
    )
    assert [s.asset_id for s in slots] == ["at-from", "middle"]


def test_title_fallback_chain() -> None:
    """``asset_title`` → ``asset_id`` → ``"Untitled"``.

    Exercises every rung of the ladder: one row of each.
    """
    store = _FakeScheduleStore(
        [
            _item(asset_id="a-1", asset_title="Real Title", scheduled_at=_BASE),
            _item(asset_id="a-2", asset_title=None, scheduled_at=_BASE + timedelta(minutes=1)),
            _item(asset_id=None, asset_title=None, scheduled_at=_BASE + timedelta(minutes=2)),
        ]
    )
    reader = PostgresCommittedScheduleReader(store)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE,
        to_ts=_BASE + timedelta(hours=1),
    )
    assert [s.title for s in slots] == ["Real Title", "a-2", "Untitled"]


def test_s22_resolver_populates_category_when_present() -> None:
    """A wired ``s22_cf_resolver`` populates ``CommittedSlot.category``."""
    resolver_calls: list[str] = []

    def fake_resolver(asset_id: str) -> str | None:
        resolver_calls.append(asset_id)
        return {"asset-1": "Government", "asset-2": "Public Affairs"}.get(asset_id)

    store = _FakeScheduleStore(
        [
            _item(asset_id="asset-1", scheduled_at=_BASE),
            _item(asset_id="asset-2", scheduled_at=_BASE + timedelta(minutes=30)),
        ]
    )
    reader = PostgresCommittedScheduleReader(store, s22_cf_resolver=fake_resolver)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE,
        to_ts=_BASE + timedelta(hours=1),
    )
    assert [s.category for s in slots] == ["Government", "Public Affairs"]
    assert resolver_calls == ["asset-1", "asset-2"]


def test_resolver_not_called_for_filler_with_no_asset_id() -> None:
    """When ``asset_id is None`` (filler slot), the resolver MUST NOT be
    invoked — calling a metadata resolver with ``None`` would either crash
    or produce a meaningless lookup.
    """
    resolver_calls: list[str | None] = []

    def fake_resolver(asset_id: str) -> str | None:
        resolver_calls.append(asset_id)
        return "should-not-appear"

    store = _FakeScheduleStore(
        [
            _item(asset_id=None, asset_title="Community Bulletin", scheduled_at=_BASE),
        ]
    )
    reader = PostgresCommittedScheduleReader(store, s22_cf_resolver=fake_resolver)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE,
        to_ts=_BASE + timedelta(hours=1),
    )
    assert slots[0].category is None
    assert resolver_calls == []


def test_resolver_exception_propagates() -> None:
    """A raising resolver currently propagates the exception (locked-in
    behavior — the EPG generate route's outer guard handles it, the adapter
    intentionally does NOT swallow). If this behavior is ever changed, this
    test forces a deliberate decision rather than a silent regression.
    """

    def boom(asset_id: str) -> str | None:
        raise RuntimeError("resolver down")

    store = _FakeScheduleStore([_item(asset_id="asset-1", scheduled_at=_BASE)])
    reader = PostgresCommittedScheduleReader(store, s22_cf_resolver=boom)
    with pytest.raises(RuntimeError, match="resolver down"):
        reader.list_committed(
            station_id="civiccast-station",
            channel_id="ch1",
            from_ts=_BASE,
            to_ts=_BASE + timedelta(hours=1),
        )


def test_duration_none_coerces_to_zero() -> None:
    """A None ``duration_seconds`` on the source row → ``duration_s == 0`` on
    the slot, and ``end == start`` (the slot is a zero-length point — common
    for unsized live placeholders).
    """
    store = _FakeScheduleStore(
        [_item(asset_id="asset-1", duration_seconds=None, scheduled_at=_BASE)]
    )
    reader = PostgresCommittedScheduleReader(store)
    slots = reader.list_committed(
        station_id="civiccast-station",
        channel_id="ch1",
        from_ts=_BASE - timedelta(seconds=1),
        to_ts=_BASE + timedelta(hours=1),
    )
    assert len(slots) == 1
    assert slots[0].duration_s == 0
    assert slots[0].end == slots[0].start


def test_list_committed_returns_the_item_after_a_real_commit() -> None:
    """Commit-to-Air gate (spec test e): against the REAL
    ``PostgresScheduleStore`` (not the fake above), ``list_committed`` is a
    dead code path until something actually writes ``published`` — this
    proves the wiring end to end: create -> CommitService.commit ->
    list_committed sees it.
    """
    from sqlalchemy import create_engine

    import civiccast.schedule.models  # noqa: F401
    from civiccast.db import Base, bind_engine, reset_engine
    from civiccast.egress.dispatcher import PlayoutDispatcher
    from civiccast.egress.store import InMemoryEgressStore
    from civiccast.schedule.commit_service import CommitDryRunService, CommitService
    from civiccast.schedule.models import Asset, ScheduleItemCreate
    from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore

    engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)
    try:
        from collections.abc import Iterator
        from contextlib import contextmanager

        from sqlalchemy.orm import Session

        @contextmanager
        def factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        schedule_store = PostgresScheduleStore(factory)
        asset_store = PostgresAssetStore(factory)
        with factory() as session:
            session.add(
                Asset(
                    asset_id="council",
                    title="City Council",
                    state="validated",
                    file_path="/media/council.ts",
                    duration_seconds=1800,
                )
            )
            session.commit()
        item = schedule_store.create(
            ScheduleItemCreate(
                asset_id="council",
                channel_id="ch1",
                mode="premiere",
                scheduled_at=_BASE,
                duration_seconds=1800,
            )
        )
        service = CommitService(
            CommitDryRunService(schedule_store, asset_store, clock=lambda: _BASE),
            schedule_store,
            PlayoutDispatcher(InMemoryEgressStore(), clock=lambda: _BASE),
            clock=lambda: _BASE,
        )
        service.commit(
            channel_id="ch1", occurrence_id="occ-1", schedule_item_id=item.id, operator_id="dana"
        )

        reader = PostgresCommittedScheduleReader(schedule_store)
        slots = reader.list_committed(
            station_id="civiccast-station",
            channel_id="ch1",
            from_ts=_BASE - timedelta(minutes=1),
            to_ts=_BASE + timedelta(hours=1),
        )
        assert [s.asset_id for s in slots] == ["council"]
        assert slots[0].slot_id == str(item.id)
    finally:
        reset_engine()
        engine.dispose()


# Suppress an unused-imports warning while keeping the type for hints.
_ = Callable
