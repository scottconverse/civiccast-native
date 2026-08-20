# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Property-based tests for schedule-conflict semantics.

Uses hypothesis (per spec §19 / CLAUDE.md tooling) to generate randomized
schedule-item pairs and verify the spec's invariants:

  P1. Two events on DIFFERENT channels never conflict.
  P2. Two events on the SAME channel with NON-OVERLAPPING time ranges
      never conflict.
  P3. Two events on the SAME channel with OVERLAPPING time ranges DO
      conflict — but only if both are time-range modes. ``live`` was
      retired in migration 0005 (audit-team v0.3.0 ENG-004), so the
      only time-range mode in v0.3.1+ is ``premiere``. The strategy
      ``_time_range_modes`` reflects this.
  P4. Embargo entries never participate in conflict detection (spec §1070).

The conflict-detection contract itself is enforced by the Postgres
btree_gist EXCLUDE constraint (migration 0003); this module tests the
*pure logic* of overlap detection — the same logic the EXCLUDE clause
encodes — to lock the semantics independent of the DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from civiccast.schedule.models import (
    SCHEDULE_MODE_EMBARGO,
    SCHEDULE_MODE_PREMIERE,
)

# ---------------------------------------------------------------------------
# Pure overlap-detection logic mirrored from the SQL the EXCLUDE encodes.
#
# The Postgres constraint says (in essence):
#   tstzrange(a.start, a.start + a.duration) && tstzrange(b.start, b.start + b.duration)
# where && is "ranges overlap." Two half-open intervals [a, a+da) and
# [b, b+db) overlap iff a < b+db AND b < a+da.
# ---------------------------------------------------------------------------


def _overlaps(a_start: datetime, a_duration: int, b_start: datetime, b_duration: int) -> bool:
    a_end = a_start + timedelta(seconds=a_duration)
    b_end = b_start + timedelta(seconds=b_duration)
    return a_start < b_end and b_start < a_end


def _conflicts(
    a_channel: str,
    a_mode: str,
    a_start: datetime,
    a_duration: int | None,
    b_channel: str,
    b_mode: str,
    b_start: datetime,
    b_duration: int | None,
) -> bool:
    """Return True iff the EXCLUDE constraint would reject these two rows."""
    # Different channels never conflict (constraint partitions by channel_id =).
    if a_channel != b_channel:
        return False
    # Embargo never conflicts (WHERE clause filters embargo out).
    if a_mode == SCHEDULE_MODE_EMBARGO or b_mode == SCHEDULE_MODE_EMBARGO:
        return False
    # Time-range overlap on the same channel + both time-range modes.
    assert a_duration is not None
    assert b_duration is not None
    return _overlaps(a_start, a_duration, b_start, b_duration)


# Strategies — bounded so hypothesis explores quickly.
_channels = st.sampled_from(["gov-ch12", "edu-ch14", "peg-ch7"])
_time_range_modes = st.sampled_from([SCHEDULE_MODE_PREMIERE])
_durations = st.integers(min_value=60, max_value=4 * 3600)  # 1 min to 4 hr
_starts = st.integers(min_value=0, max_value=24 * 3600).map(
    lambda secs: datetime(2026, 5, 15, 0, 0, 0, tzinfo=UTC) + timedelta(seconds=secs)
)


# ---------------------------------------------------------------------------
# P1: different channels never conflict
# ---------------------------------------------------------------------------


class TestPropertyDifferentChannelsNeverConflict:
    @staticmethod
    @given(
        a_channel=_channels,
        b_channel=_channels,
        a_start=_starts,
        a_duration=_durations,
        b_start=_starts,
        b_duration=_durations,
    )
    @settings(max_examples=200)
    def test_invariant(
        a_channel: str,
        b_channel: str,
        a_start: datetime,
        a_duration: int,
        b_start: datetime,
        b_duration: int,
    ) -> None:
        if a_channel == b_channel:
            return  # not the property we're checking
        assert not _conflicts(
            a_channel,
            SCHEDULE_MODE_PREMIERE,
            a_start,
            a_duration,
            b_channel,
            SCHEDULE_MODE_PREMIERE,
            b_start,
            b_duration,
        )


# ---------------------------------------------------------------------------
# P2: same-channel non-overlapping times never conflict
# ---------------------------------------------------------------------------


class TestPropertyNonOverlappingTimesNeverConflict:
    @staticmethod
    @given(
        channel=_channels,
        a_start=_starts,
        a_duration=_durations,
        gap=st.integers(min_value=1, max_value=24 * 3600),
        b_duration=_durations,
    )
    @settings(max_examples=200)
    def test_invariant(
        channel: str,
        a_start: datetime,
        a_duration: int,
        gap: int,
        b_duration: int,
    ) -> None:
        b_start = a_start + timedelta(seconds=a_duration + gap)
        # By construction, [a_start, a_start + a_duration) ends before
        # b_start; non-overlapping. The constraint must not flag.
        assert not _conflicts(
            channel,
            SCHEDULE_MODE_PREMIERE,
            a_start,
            a_duration,
            channel,
            SCHEDULE_MODE_PREMIERE,
            b_start,
            b_duration,
        )


# ---------------------------------------------------------------------------
# P3: same-channel overlapping times DO conflict (when both are time-range modes)
# ---------------------------------------------------------------------------


class TestPropertyOverlappingTimesDoConflict:
    @staticmethod
    @given(
        channel=_channels,
        a_start=_starts,
        a_duration=_durations,
        # Place b inside [a_start, a_end) — guaranteed overlap.
        offset_inside=st.integers(min_value=0, max_value=3600),
        b_duration=_durations,
        a_mode=_time_range_modes,
        b_mode=_time_range_modes,
    )
    @settings(max_examples=200)
    def test_invariant(
        channel: str,
        a_start: datetime,
        a_duration: int,
        offset_inside: int,
        b_duration: int,
        a_mode: str,
        b_mode: str,
    ) -> None:
        # Bound offset_inside so b_start lies strictly inside a's window.
        offset_inside = min(offset_inside, max(a_duration - 1, 1))
        b_start = a_start + timedelta(seconds=offset_inside)
        assert _conflicts(
            channel,
            a_mode,
            a_start,
            a_duration,
            channel,
            b_mode,
            b_start,
            b_duration,
        )


# ---------------------------------------------------------------------------
# P4: embargo never conflicts (regardless of channel + time)
# ---------------------------------------------------------------------------


class TestPropertyEmbargoNeverConflicts:
    @staticmethod
    @given(
        a_channel=_channels,
        b_channel=_channels,
        a_start=_starts,
        b_start=_starts,
        a_duration=_durations,
    )
    @settings(max_examples=200)
    def test_embargo_vs_anything_does_not_conflict(
        a_channel: str,
        b_channel: str,
        a_start: datetime,
        b_start: datetime,
        a_duration: int,
    ) -> None:
        # Embargo on either side → no conflict, period.
        assert not _conflicts(
            a_channel,
            SCHEDULE_MODE_EMBARGO,
            a_start,
            None,
            b_channel,
            SCHEDULE_MODE_PREMIERE,
            b_start,
            a_duration,
        )
        assert not _conflicts(
            a_channel,
            SCHEDULE_MODE_PREMIERE,
            a_start,
            a_duration,
            b_channel,
            SCHEDULE_MODE_EMBARGO,
            b_start,
            None,
        )
        assert not _conflicts(
            a_channel,
            SCHEDULE_MODE_EMBARGO,
            a_start,
            None,
            b_channel,
            SCHEDULE_MODE_EMBARGO,
            b_start,
            None,
        )


def test_property_invariants_do_not_bind_instance_executors() -> None:
    """Keep @given tests re-entrant for runners such as mutmut."""
    for property_test, method_name in (
        (TestPropertyDifferentChannelsNeverConflict, "test_invariant"),
        (TestPropertyNonOverlappingTimesNeverConflict, "test_invariant"),
        (TestPropertyOverlappingTimesDoConflict, "test_invariant"),
        (TestPropertyEmbargoNeverConflicts, "test_embargo_vs_anything_does_not_conflict"),
    ):
        assert isinstance(property_test.__dict__[method_name], staticmethod)
