# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-08 arithmetic: civiccast.schedule.retention_terms.

Pure-function coverage for the value/unit/forever contract's deadline
math, independent of persistence or the API layer. Mutation-check note
(see the WP-08 push report): flattening the months/years branch to a
naive ``timedelta(days=30 * value)`` breaks
``test_end_of_month_clamps_to_shorter_month``,
``test_leap_day_handled_for_february_start``, and
``test_years_uses_calendar_addition_not_365_days`` below -- that is the
intended kill for that mutant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from civiccast.schedule.retention_terms import (
    RETENTION_TERM_UNITS,
    add_calendar_months,
    compute_retention_until,
    validate_term,
)


class TestValidateTerm:
    def test_forever_rejects_a_value(self) -> None:
        with pytest.raises(ValueError, match="must be omitted"):
            validate_term("forever", 1)

    def test_forever_with_no_value_is_valid(self) -> None:
        validate_term("forever", None)

    @pytest.mark.parametrize("unit", ["days", "weeks", "months", "years"])
    def test_finite_units_require_a_positive_value(self, unit: str) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            validate_term(unit, None)
        with pytest.raises(ValueError, match="positive integer"):
            validate_term(unit, 0)
        with pytest.raises(ValueError, match="positive integer"):
            validate_term(unit, -5)
        validate_term(unit, 1)  # does not raise

    def test_unknown_unit_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be one of"):
            validate_term("fortnights", 1)

    def test_every_documented_unit_is_covered(self) -> None:
        assert set(RETENTION_TERM_UNITS) == {"days", "weeks", "months", "years", "forever"}


class TestAddCalendarMonths:
    def test_end_of_month_clamps_to_shorter_month(self) -> None:
        # Jan 31 + 1 month -> Feb 28 (non-leap year), not "spilling over"
        # into March 3.
        result = add_calendar_months(datetime(2027, 1, 31, 9, 0, tzinfo=UTC), 1)
        assert result == datetime(2027, 2, 28, 9, 0, tzinfo=UTC)

    def test_leap_day_clamp(self) -> None:
        # 2028 is a leap year: Jan 31 + 1 month -> Feb 29.
        result = add_calendar_months(datetime(2028, 1, 31, 9, 0, tzinfo=UTC), 1)
        assert result == datetime(2028, 2, 29, 9, 0, tzinfo=UTC)

    def test_ordinary_month_add_preserves_day(self) -> None:
        result = add_calendar_months(datetime(2026, 3, 15, 8, 30, tzinfo=UTC), 4)
        assert result == datetime(2026, 7, 15, 8, 30, tzinfo=UTC)

    def test_year_rollover(self) -> None:
        result = add_calendar_months(datetime(2026, 11, 10, tzinfo=UTC), 3)
        assert result == datetime(2027, 2, 10, tzinfo=UTC)


class TestComputeRetentionUntilElapsed:
    def test_days_is_elapsed_duration(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="days", value=30, station_tz_name="UTC"
        )
        assert until == anchor + timedelta(days=30)

    def test_weeks_is_elapsed_duration(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="weeks", value=2, station_tz_name="UTC"
        )
        assert until == anchor + timedelta(weeks=2)

    def test_naive_anchor_treated_as_utc(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0)  # naive
        until = compute_retention_until(
            anchor_at=anchor, unit="days", value=1, station_tz_name="UTC"
        )
        assert until == datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    def test_forever_returns_none(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        assert (
            compute_retention_until(
                anchor_at=anchor, unit="forever", value=None, station_tz_name="UTC"
            )
            is None
        )

    def test_invalid_term_raises(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        with pytest.raises(ValueError):
            compute_retention_until(
                anchor_at=anchor, unit="days", value=0, station_tz_name="UTC"
            )


class TestComputeRetentionUntilCalendar:
    def test_end_of_month_clamps_to_shorter_month(self) -> None:
        # Jan 31 2027 + 1 month, station in UTC -> Feb 28 2027 (non-leap).
        anchor = datetime(2027, 1, 31, 15, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="months", value=1, station_tz_name="UTC"
        )
        assert until == datetime(2027, 2, 28, 15, 0, tzinfo=UTC)

    def test_leap_day_handled_for_february_start(self) -> None:
        # A Feb 29 2028 anchor, +1 year (2029 is not a leap year) clamps
        # to Feb 28 2029, not an invalid date and not a March rollover.
        anchor = datetime(2028, 2, 29, 10, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="years", value=1, station_tz_name="UTC"
        )
        assert until == datetime(2029, 2, 28, 10, 0, tzinfo=UTC)

    def test_years_uses_calendar_addition_not_365_days(self) -> None:
        # 2028 is a leap year: a naive "365 days" implementation would
        # land one day short of the real anniversary date.
        anchor = datetime(2027, 3, 1, 9, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="years", value=1, station_tz_name="UTC"
        )
        assert until == datetime(2028, 3, 1, 9, 0, tzinfo=UTC)
        assert until != anchor + timedelta(days=365)

    def test_station_timezone_used_for_calendar_math(self) -> None:
        # A New York anchor at 23:30 local on Jan 31 is already Feb 1 in
        # UTC. Calendar math must add "1 month" to the STATION's Jan 31,
        # not UTC's Feb 1, so the clamp/result lands relative to the
        # station's own wall-clock date.
        anchor_utc = datetime(2027, 2, 1, 4, 30, tzinfo=UTC)  # 23:30 EST Jan 31
        until = compute_retention_until(
            anchor_at=anchor_utc,
            unit="months",
            value=1,
            station_tz_name="America/New_York",
        )
        # Station-local Jan 31 23:30 + 1 month -> station-local Feb 28
        # 23:30 EST, converted back to UTC (EST = UTC-5).
        assert until == datetime(2027, 3, 1, 4, 30, tzinfo=UTC)

    def test_dst_spring_forward_boundary(self) -> None:
        # US DST 2026 spring-forward is March 8. An anchor one calendar
        # month before it, +1 month, must land on the correct wall-clock
        # instant on the OTHER side of the transition (EST -> EDT),
        # proving the calculation re-resolves the offset for the RESULT
        # instant rather than reusing the anchor's.
        anchor_utc = datetime(2026, 2, 8, 17, 0, tzinfo=UTC)  # 12:00 EST Feb 8
        until = compute_retention_until(
            anchor_at=anchor_utc,
            unit="months",
            value=1,
            station_tz_name="America/New_York",
        )
        # Station-local Feb 8 12:00 + 1 month -> station-local Mar 8
        # 12:00 EDT (UTC-4, post-spring-forward), i.e. 16:00 UTC -- NOT
        # 17:00 UTC (which would be the stale EST offset).
        assert until == datetime(2026, 3, 8, 16, 0, tzinfo=UTC)

    def test_unresolvable_zone_falls_back_to_utc(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="months", value=1, station_tz_name="Not/AZone"
        )
        assert until == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

    def test_local_sentinel_falls_back_to_utc(self) -> None:
        anchor = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        until = compute_retention_until(
            anchor_at=anchor, unit="months", value=1, station_tz_name="local"
        )
        assert until == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
