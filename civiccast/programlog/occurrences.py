# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure occurrence computation for recurring program slots (CA-1).

Given a slot and a half-open UTC window [window_start, window_end), return
the occurrence start datetimes that fall inside it. No I/O, no clock reads —
callers supply the window, which keeps this deterministic and testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from civiccast.programlog.models import ProgramSlot

_WEEKDAY_FRIDAY = 4  # Monday == 0


def compute_occurrences(
    slot: ProgramSlot,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[datetime]:
    """Return slot occurrence starts inside [window_start, window_end)."""

    if not slot.enabled:
        return []
    if slot.first_start_at >= window_end:
        return []

    if slot.recurrence == "once":
        candidate = slot.first_start_at
        if window_start <= candidate < window_end and _within_repeat(slot, candidate):
            return [candidate]
        return []

    step = timedelta(weeks=1) if slot.recurrence == "weekly" else timedelta(days=1)

    # Jump close to the window instead of iterating day-by-day from a
    # possibly years-old first_start_at.
    candidate = slot.first_start_at
    if candidate < window_start:
        behind = window_start - candidate
        candidate += step * (behind // step)
        while candidate < window_start:
            candidate += step

    results: list[datetime] = []
    while candidate < window_end:
        if not _within_repeat(slot, candidate):
            break
        if slot.recurrence != "weekdays" or candidate.weekday() <= _WEEKDAY_FRIDAY:
            results.append(candidate)
        candidate += step
    return results


def _within_repeat(slot: ProgramSlot, candidate: datetime) -> bool:
    return slot.repeat_until is None or candidate <= slot.repeat_until
