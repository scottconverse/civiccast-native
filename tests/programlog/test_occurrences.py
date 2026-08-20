# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Occurrence computation for recurring program slots (cable automation CA-1).

Pure-function tests: given a slot's recurrence rule and a [start, end)
horizon window, which UTC occurrence datetimes fall inside it. All math is
timezone-aware UTC — a slot scheduled at 19:00 UTC stays 19:00 UTC across
DST shifts (station-local-time recurrence is an explicit later feature).
"""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.programlog.models import ProgramSlot
from civiccast.programlog.occurrences import compute_occurrences


def _slot(
    *,
    recurrence: str,
    first_start_at: datetime,
    repeat_until: datetime | None = None,
    enabled: bool = True,
) -> ProgramSlot:
    return ProgramSlot(
        slot_id="cps_test",
        channel_id="public",
        asset_id="council-2026-06-10",
        title_override=None,
        recurrence=recurrence,  # type: ignore[arg-type]
        first_start_at=first_start_at,
        duration_seconds=3600,
        repeat_until=repeat_until,
        enabled=enabled,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


class TestComputeOccurrences:
    def test_once_inside_window(self) -> None:
        slot = _slot(recurrence="once", first_start_at=datetime(2026, 6, 12, 19, 0, tzinfo=UTC))
        window = (datetime(2026, 6, 12, 0, 0, tzinfo=UTC), datetime(2026, 6, 15, 0, 0, tzinfo=UTC))
        assert compute_occurrences(slot, window_start=window[0], window_end=window[1]) == [
            datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
        ]

    def test_once_outside_window_is_empty(self) -> None:
        slot = _slot(recurrence="once", first_start_at=datetime(2026, 6, 20, 19, 0, tzinfo=UTC))
        assert (
            compute_occurrences(
                slot,
                window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
                window_end=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
            )
            == []
        )

    def test_daily_fills_the_window(self) -> None:
        slot = _slot(recurrence="daily", first_start_at=datetime(2026, 6, 1, 19, 0, tzinfo=UTC))
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        )
        assert result == [
            datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 13, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 14, 19, 0, tzinfo=UTC),
        ]

    def test_daily_does_not_backfill_before_first_start(self) -> None:
        slot = _slot(recurrence="daily", first_start_at=datetime(2026, 6, 13, 19, 0, tzinfo=UTC))
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
        )
        assert result == [
            datetime(2026, 6, 13, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 14, 19, 0, tzinfo=UTC),
        ]

    def test_weekly_repeats_on_the_same_weekday_and_time(self) -> None:
        # 2026-06-12 is a Friday.
        slot = _slot(recurrence="weekly", first_start_at=datetime(2026, 6, 12, 19, 0, tzinfo=UTC))
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 27, 0, 0, tzinfo=UTC),
        )
        assert result == [
            datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 19, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 26, 19, 0, tzinfo=UTC),
        ]

    def test_weekdays_skips_weekends(self) -> None:
        # 2026-06-12 Friday -> Fri, Mon, Tue inside a 5-day window.
        slot = _slot(recurrence="weekdays", first_start_at=datetime(2026, 6, 12, 9, 0, tzinfo=UTC))
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 17, 0, 0, tzinfo=UTC),
        )
        assert result == [
            datetime(2026, 6, 12, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 16, 9, 0, tzinfo=UTC),
        ]

    def test_repeat_until_is_inclusive_cutoff(self) -> None:
        slot = _slot(
            recurrence="daily",
            first_start_at=datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
            repeat_until=datetime(2026, 6, 13, 19, 0, tzinfo=UTC),
        )
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 20, 0, 0, tzinfo=UTC),
        )
        assert result == [
            datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
            datetime(2026, 6, 13, 19, 0, tzinfo=UTC),
        ]

    def test_disabled_slot_yields_nothing(self) -> None:
        slot = _slot(
            recurrence="daily",
            first_start_at=datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
            enabled=False,
        )
        assert (
            compute_occurrences(
                slot,
                window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
                window_end=datetime(2026, 6, 15, 0, 0, tzinfo=UTC),
            )
            == []
        )

    def test_window_start_is_inclusive_end_exclusive(self) -> None:
        slot = _slot(recurrence="daily", first_start_at=datetime(2026, 6, 12, 0, 0, tzinfo=UTC))
        result = compute_occurrences(
            slot,
            window_start=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
            window_end=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
        )
        assert result == [datetime(2026, 6, 12, 0, 0, tzinfo=UTC)]
