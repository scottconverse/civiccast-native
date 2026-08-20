# ADR 0013 -- Station timezone handling

Date: 2026-05-13

Status: Accepted for v0.4.

## Context

CivicCast stores scheduled broadcast times as timezone-aware instants. The
operator schedule drawer currently uses the browser's `datetime-local` control,
which intentionally has no timezone field. That makes the browser timezone the
source of truth for converting the operator's local input into UTC.

The audit-team v0.3.0 QA-009 finding called out the risk: daylight-saving
transitions and operators working away from the station can make a naive local
input ambiguous. The v0.4 release needed a visible operator warning plus a
documented direction for the later station-profile setting.

## Decision

For v0.4, the schedule drawer keeps the browser-timezone conversion but makes
the contract explicit beside the `datetime-local` field:

1. The drawer shows the resolved browser timezone.
2. The drawer warns operators to confirm the meeting time against the station
   calendar during daylight-saving changes.
3. The backend continues to reject naive datetimes and accepts only
   timezone-aware instants.

For a future station-settings rung, CivicCast will add an explicit station
timezone setting. At that point, schedule creation will use the station
timezone as the default conversion context, while still showing the browser
timezone when it differs from the station setting.

## Consequences

- v0.4 removes the silent ambiguity from the operator UI without changing the
  persisted API contract.
- Operators get an actionable check at the moment they enter a time.
- The future station-timezone feature has a documented migration target and
  does not need to rediscover the DST risk.
