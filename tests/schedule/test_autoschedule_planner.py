# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 slice 3 — daypart slot expansion + repeat-prevention.

Exercises civiccast.schedule.autoschedule_planner:
  * expand_block_slots — weekday mask, active-date bounds, midnight-wrap, 24:00
    end, disabled/zero-day guards, wall-clock under a non-UTC tz;
  * repeat_prevention_asset_ids — channel scoping, margin window math, cancelled
    exclusion, and the N<=0 disable.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_models import ScheduleBlock
from civiccast.schedule.autoschedule_planner import (
    expand_block_slots,
    repeat_prevention_asset_ids,
)
from civiccast.schedule.models import (
    SCHEDULE_MODE_PREMIERE,
    SCHEDULE_STATE_CANCELLED,
    SCHEDULE_STATE_SCHEDULED,
    ScheduleItem,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_MON = date(2026, 6, 1)  # used as a range anchor; weekday derived, not assumed


def _block(**kwargs: object) -> ScheduleBlock:
    base: dict[str, object] = {
        "block_id": "sb_test",
        "channel_id": "public",
        "name": "Daypart",
        "start_minute": 18 * 60,
        "end_minute": 22 * 60,
        "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kwargs)
    return ScheduleBlock(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# expand_block_slots
# ---------------------------------------------------------------------------


def test_weekday_mask_selects_matching_days_only() -> None:
    allowed = {0, 2, 4}  # Mon / Wed / Fri
    slots = expand_block_slots(_block(days_of_week=sorted(allowed)), start_date=_MON, num_days=7)
    expected = [
        _MON + timedelta(days=i)
        for i in range(7)
        if (_MON + timedelta(days=i)).weekday() in allowed
    ]
    assert [s.starts_at.date() for s in slots] == expected
    assert all(s.starts_at.hour == 18 and s.ends_at.hour == 22 for s in slots)
    assert all(s.duration_seconds == 4 * 3600 for s in slots)


def test_midnight_wrap_ends_next_day() -> None:
    block = _block(start_minute=23 * 60, end_minute=5 * 60, days_of_week=[_MON.weekday()])
    [slot] = expand_block_slots(block, start_date=_MON, num_days=1)
    assert slot.starts_at.date() == _MON
    assert slot.ends_at.date() == _MON + timedelta(days=1)
    assert slot.starts_at.hour == 23
    assert slot.ends_at.hour == 5
    assert slot.duration_seconds == 6 * 3600


def test_end_minute_1440_is_next_day_midnight() -> None:
    block = _block(start_minute=18 * 60, end_minute=24 * 60, days_of_week=[_MON.weekday()])
    [slot] = expand_block_slots(block, start_date=_MON, num_days=1)
    assert slot.ends_at == datetime.combine(
        _MON + timedelta(days=1), datetime.min.time(), tzinfo=UTC
    )
    assert slot.duration_seconds == 6 * 3600


def test_active_date_bounds_clip_the_range() -> None:
    block = _block(active_from=_MON + timedelta(days=2), active_until=_MON + timedelta(days=3))
    slots = expand_block_slots(block, start_date=_MON, num_days=7)
    assert [s.starts_at.date() for s in slots] == [
        _MON + timedelta(days=2),
        _MON + timedelta(days=3),
    ]


def test_disabled_block_and_zero_days_yield_nothing() -> None:
    assert expand_block_slots(_block(enabled=False), start_date=_MON, num_days=7) == []
    assert expand_block_slots(_block(), start_date=_MON, num_days=0) == []


def test_wall_clock_honours_non_utc_tz() -> None:
    eastern = timezone(timedelta(hours=-5))
    block = _block(days_of_week=[_MON.weekday()])
    [slot] = expand_block_slots(block, start_date=_MON, num_days=1, tz=eastern)
    assert slot.starts_at.hour == 18  # 18:00 wall-clock, not drifted
    assert slot.starts_at.utcoffset() == timedelta(hours=-5)
    assert slot.starts_at.astimezone(UTC).hour == 23


# ---------------------------------------------------------------------------
# repeat_prevention_asset_ids
# ---------------------------------------------------------------------------


def _item(asset_id: str, channel_id: str, when: datetime, state: str) -> ScheduleItem:
    return ScheduleItem(
        asset_id=asset_id,
        channel_id=channel_id,
        mode=SCHEDULE_MODE_PREMIERE,
        state=state,
        scheduled_at=when,
        duration_seconds=3600,
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    eng = create_engine(f"sqlite:///{tmp_path / 'sched.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as s:
            yield s

    with factory() as setup:
        setup.add_all(
            [
                _item("a1", "public", datetime(2026, 6, 10, tzinfo=UTC), SCHEDULE_STATE_SCHEDULED),
                _item("a2", "public", datetime(2026, 6, 20, tzinfo=UTC), SCHEDULE_STATE_SCHEDULED),
                _item("a3", "public", datetime(2026, 6, 15, tzinfo=UTC), SCHEDULE_STATE_CANCELLED),
                _item("a4", "gov", datetime(2026, 6, 10, tzinfo=UTC), SCHEDULE_STATE_SCHEDULED),
            ]
        )
        setup.commit()

    with factory() as s:
        yield s
    eng.dispose()


def test_repeat_window_gathers_channel_scheduled_excludes_cancelled(session: Session) -> None:
    ids = repeat_prevention_asset_ids(
        session,
        channel_id="public",
        window_start=datetime(2026, 6, 14, tzinfo=UTC),
        window_end=datetime(2026, 6, 16, tzinfo=UTC),
        repeat_prevention_days=7,  # window becomes [06-07, 06-23)
    )
    # a1 (06-10) + a2 (06-20) in range on public; a3 cancelled; a4 is gov.
    assert ids == {"a1", "a2"}


def test_repeat_window_margin_is_respected(session: Session) -> None:
    ids = repeat_prevention_asset_ids(
        session,
        channel_id="public",
        window_start=datetime(2026, 6, 14, tzinfo=UTC),
        window_end=datetime(2026, 6, 16, tzinfo=UTC),
        repeat_prevention_days=1,  # window becomes [06-13, 06-17); a1/a2 fall outside
    )
    assert ids == set()


def test_repeat_prevention_disabled_returns_empty(session: Session) -> None:
    ids = repeat_prevention_asset_ids(
        session,
        channel_id="public",
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
        repeat_prevention_days=0,
    )
    assert ids == set()
