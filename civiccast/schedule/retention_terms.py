# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-08: value/unit/forever retention-term authoring (finalization plan
section 6, work package WP-08 -- "Add retention value/unit/forever
authoring without changing enforcement").

This module is deliberately small and dependency-free: it is the pure
arithmetic + validation layer for the new authoring contract. It does not
touch persistence, the API layer, or the enforcement worker.

Data contract (finalization plan, verbatim):

* Finite: a positive integer ``value`` plus a unit of ``days``, ``weeks``,
  ``months``, or ``years``.
* Infinite: ``forever``, which carries no numeric value.
* Days/weeks are elapsed-duration arithmetic (a fixed number of seconds).
* Months/years are calendar additions performed in the station's local
  timezone, clamped at end-of-month, leap-day safe, and converted to UTC
  only for the final persisted instant -- this keeps "1 year from a March
  publish" landing in March even though the number of elapsed UTC seconds
  in a year varies with DST and leap days.

This module never invents an anchor. Anchor capture/reuse is the caller's
(``civiccast.schedule.store``) responsibility -- see
``civiccast/schedule/models.py``'s ``Asset.retention_anchor_at`` docstring
for the immutability contract.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RETENTION_TERM_UNIT_DAYS = "days"
RETENTION_TERM_UNIT_WEEKS = "weeks"
RETENTION_TERM_UNIT_MONTHS = "months"
RETENTION_TERM_UNIT_YEARS = "years"
RETENTION_TERM_UNIT_FOREVER = "forever"

RETENTION_TERM_UNITS: tuple[str, ...] = (
    RETENTION_TERM_UNIT_DAYS,
    RETENTION_TERM_UNIT_WEEKS,
    RETENTION_TERM_UNIT_MONTHS,
    RETENTION_TERM_UNIT_YEARS,
    RETENTION_TERM_UNIT_FOREVER,
)

# Units whose arithmetic is a fixed elapsed duration, independent of
# calendar/timezone.
_ELAPSED_UNITS = (RETENTION_TERM_UNIT_DAYS, RETENTION_TERM_UNIT_WEEKS)
# Units whose arithmetic is a calendar addition in station-local time.
_CALENDAR_UNITS = (RETENTION_TERM_UNIT_MONTHS, RETENTION_TERM_UNIT_YEARS)

RetentionTermUnit = Literal["days", "weeks", "months", "years", "forever"]

# Legacy-conversion prefill suggestions (finalization plan section 6, item
# 8: "Present existing state presets as prefilled value/unit suggestions,
# not as an external legal decision.") These are display-only hints for
# an operator about to convert a legacy row to the new contract -- never
# applied to a stored row automatically. The v1.0 short-hand meaning is
# code-defined (``civiccast.schedule.models.RETENTION_SHORT``'s docstring:
# "drop after 30 days"), so representing it as 30 days is not inventing a
# new duration, only restating the existing one in the new shape.
LEGACY_SHORT_SUGGESTED_VALUE = 30
LEGACY_SHORT_SUGGESTED_UNIT: RetentionTermUnit = "days"


def resolve_station_zoneinfo(tz_name: str | None) -> ZoneInfo | None:
    """Best-effort IANA zone lookup for a station timezone name.

    Returns ``None`` (caller falls back to UTC) for the empty string, the
    ``"local"`` sentinel default, or an unresolvable/invalid name -- this
    mirrors ``civiccast.app._station_tz``'s honest-fallback posture rather
    than raising on a station that has not picked a real zone yet.
    """
    if not tz_name or tz_name == "local":
        return None
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months to ``dt``, clamping at end-of-month.

    E.g. Jan 31 + 1 month -> Feb 28 (Feb 29 in a leap year), never
    "spills over" into March. Preserves ``dt``'s time-of-day and tzinfo
    (if any) unchanged; only the date fields move.
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def validate_term(unit: str, value: int | None) -> None:
    """Raise :class:`ValueError` if ``(unit, value)`` is not a valid term.

    ``forever`` must carry no value; every finite unit must carry a
    positive integer value.
    """
    if unit not in RETENTION_TERM_UNITS:
        raise ValueError(
            f"retention term unit must be one of {RETENTION_TERM_UNITS}, got {unit!r}"
        )
    if unit == RETENTION_TERM_UNIT_FOREVER:
        if value is not None:
            raise ValueError("retention term value must be omitted when unit is 'forever'")
        return
    if value is None or value <= 0:
        raise ValueError(
            f"retention term value must be a positive integer for unit {unit!r}, got {value!r}"
        )


def compute_retention_until(
    *,
    anchor_at: datetime,
    unit: str,
    value: int | None,
    station_tz_name: str | None,
) -> datetime | None:
    """Compute the UTC retention deadline for one value/unit/forever term.

    ``anchor_at`` is ``Asset.retention_anchor_at`` -- immutable once
    captured, so every call recomputes from the *same* fixed point in
    time; this function does not read or write anchor state, it is pure.

    Returns ``None`` for ``forever`` (no deadline; the caller mirrors this
    onto the legacy ``retention_policy='permanent'`` column so the
    existing, unmodified enforcement worker continues to skip it via its
    own ``retention_policy != 'permanent'`` filter).
    """
    validate_term(unit, value)

    if anchor_at.tzinfo is None:
        anchor_at = anchor_at.replace(tzinfo=UTC)
    anchor_utc = anchor_at.astimezone(UTC)

    if unit == RETENTION_TERM_UNIT_FOREVER:
        return None

    assert value is not None  # narrowed by validate_term above

    if unit == RETENTION_TERM_UNIT_DAYS:
        return anchor_utc + timedelta(days=value)
    if unit == RETENTION_TERM_UNIT_WEEKS:
        return anchor_utc + timedelta(weeks=value)

    # months / years: calendar addition in station-local wall-clock time.
    months = value if unit == RETENTION_TERM_UNIT_MONTHS else value * 12
    zone = resolve_station_zoneinfo(station_tz_name) or UTC
    anchor_local = anchor_utc.astimezone(zone)
    # Strip tzinfo, do naive calendar arithmetic, then reattach the SAME
    # zone object (not the anchor's resolved offset) so zoneinfo resolves
    # the correct standard/DST offset for the RESULT's wall-clock instant.
    # This is the DST-safe pattern for PEP 495 zoneinfo -- reusing the
    # anchor's raw utcoffset would silently apply the wrong offset across
    # a spring-forward/fall-back boundary.
    naive_result = add_calendar_months(anchor_local.replace(tzinfo=None), months)
    result_local = naive_result.replace(tzinfo=zone)
    return result_local.astimezone(UTC)
