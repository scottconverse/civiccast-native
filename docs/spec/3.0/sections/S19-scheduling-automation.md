# S19 — Scheduling Automation (Saved Searches → Auto-Schedule + Block/Daypart)

**Status:** Build spec for CivicCast 3.0 · Authored 2026-06-14 · Closes S18 gaps 1 + 4 (migration `0043` — shipped; reconciled to disk 2026-06-18)
**Scope:** Query-driven auto-scheduling of the cable program log + block/daypart scheduling
**Functional target:** incumbent PEG platform **Autoschedule** ("Saved Search" → auto-fill recurring slots; 14–60-day rolling window; Top/Random/Newest pick) + the periodic auto-schedule compile
**Owning sections:** extends S4 (program log / commit-to-air) and S5 (force-matrix arbitration)
**Key claim boundary:** auto-materialization is gated by the existing OnAirLock commit gate (S4) — nothing reaches air without a committed schedule.

---

## 1. Goal & PEG automation rationale

the incumbent PEG platform's Autoschedule lets a station bind a recurring timeslot to a **Saved Search** (a query over show metadata) rather than a fixed file. When new content matching the query is ingested, the schedule auto-populates — "Tuesday 7 PM = newest *City Council* recording" fills itself. This is the single biggest day-to-day labor saver for a minimally-staffed PEG station and the #1 confirmed capability gap (Gemini-validated; the feature page is incumbent public documentation Saved-Search/Autoschedule docs).

**CivicCast today** binds a **static `asset_id` per slot** in the program log (`programlog/` — `ProgramLogMaterializer` materializes recurring `ProgramSlot`s into `schedule_items` with a fixed asset). There is **no query-driven slot, no rolling-window auto-fill, no block/daypart construct** (verified: `saved_search` / `auto_schedule` / `daypart` = 0 hits in code). This section closes that.

**Not deferred because:** auto-scheduling is the core automation value of a PEG automation system; a station that must hand-place every file will not switch.

---

## 2. Current state (code grounding)

| Component | File:Line (main @ 69cc676) | Status |
|---|---|---|
| `ProgramSlot` (recurring slot → asset binding) | `civiccast/programlog/models.py` | shipped (static asset only) |
| `ProgramLogMaterializer` (slots → `schedule_items`, 72 h rolling, idempotent) | `civiccast/programlog/` | shipped |
| `ScheduleItem` / schedule store | `civiccast/programlog/` | shipped |
| OnAirLock commit gate | S4 (`commit_to_air`) | shipped/spec |
| Saved-search / query-driven slot | — | **absent (net-new)** |
| Block / daypart construct | — | **absent (net-new)** |
| OTT smart-playlists (NOT this) | `civiccast/app_platform/router.py` (`_smart_playlists`) | shipped — OTT-only; does NOT drive the cable program log |

> Note: `SmartPlaylistDefinition` exists for OTT apps but is unrelated to the cable program log; do not conflate. S19 is the *linear-schedule* query engine.

---

## 3. Entities & migration `0043_scheduling_automation`

```python
class SavedSearch(BaseModel):
    """A named, reusable query over asset metadata."""
    saved_search_id: Slug
    station_id: Slug
    name: str
    # Query is a structured, validated filter (NOT raw SQL) over Asset fields +
    # custom fields (S22). Resolves to an ordered list of asset_ids at runtime.
    query: SavedSearchQuery            # {all_of:[...], any_of:[...], order_by, limit}
    created_by: str
    created_at: datetime

class AutoScheduleRule(BaseModel):
    """Binds a SavedSearch to a recurring timeslot + pick strategy."""
    rule_id: Slug
    station_id: Slug
    channel_id: Slug
    saved_search_id: Slug
    recurrence: RecurrenceSpec         # reuse ProgramSlot recurrence (RRULE-like)
    pick: Literal["top", "random", "newest", "least_recently_aired"]
    rolling_window_days: int = 14      # 14..60 (PEG automation coverage)
    avoid_repeat_within_days: int | None = None   # don't re-air same asset within N days
    enabled: bool = True
    priority: int = 0                  # tie-break vs other rules on the same slot

class ScheduleBlock(BaseModel):
    """A daypart/seasonal block constraining when rules + slots may place content."""
    block_id: Slug
    station_id: Slug
    channel_id: Slug
    name: str                          # "Prime", "Overnight", "Election Season"
    daypart: DaypartSpec               # days-of-week + start/end time-of-day
    start_date: date | None = None     # seasonal window (None = always)
    end_date: date | None = None
    allow_rules: list[Slug] = []       # rule_ids permitted in this block (empty = all)
```

Migration `0043_scheduling_automation` adds `saved_searches`, `auto_schedule_rules`, `schedule_blocks`. Single global chain, sequenced after `0042_takeover_audit_and_command_action` (on disk). No change to existing `schedule_items` schema (rules *produce* normal schedule_items, so downstream playout is unchanged).

---

## 4. API surface

```
# Saved searches
GET/POST       /api/staff/scheduling/saved-searches
GET/PATCH/DEL  /api/staff/scheduling/saved-searches/{id}
POST           /api/staff/scheduling/saved-searches/{id}/preview   # returns resolved assets (dry-run)

# Auto-schedule rules
GET/POST       /api/staff/scheduling/rules
GET/PATCH/DEL  /api/staff/scheduling/rules/{id}
POST           /api/staff/scheduling/rules/{id}/simulate           # show what would materialize over the window

# Blocks
GET/POST       /api/staff/scheduling/blocks
GET/PATCH/DEL  /api/staff/scheduling/blocks/{id}
```
Roles: `require_any_role("setup_admin", "meeting_operator")` for write; `support_admin` read-only. Rule/search edits do **not** auto-commit — they feed the materializer, whose output still passes the S4 OnAirLock commit gate.

---

## 5. Operator UI

- **Saved Search builder** (`/portal-operator/scheduling/searches`): visual filter builder over metadata + custom fields (S22); live preview of matching assets.
- **Auto-Schedule rules** (`/portal-operator/scheduling/rules`): bind a saved search to a slot + pick strategy + window; "Simulate" shows the next N days the rule would fill.
- **Block/daypart editor** (`/portal-operator/scheduling/blocks`): define dayparts + seasonal windows; assign which rules may run in each.
- Phone-first, ≥800 px desktop-optimized (matches existing operator-console conventions).

---

## 6. Behavior / algorithm

**Auto-schedule compiler** (runs on the same cadence as the existing materializer; matches the periodic auto-schedule compile):

1. For each enabled `AutoScheduleRule`, expand its `recurrence` across the `rolling_window_days` horizon to candidate slot instances.
2. For each candidate slot, **resolve** the `SavedSearch.query` → ordered asset list (filtered to ready/published assets; honors `avoid_repeat_within_days` against as-run history).
3. **Pick** an asset by strategy (`top`/`random`/`newest`/`least_recently_aired`).
4. **Block constraint:** if `ScheduleBlock`s apply to the slot's channel/time, only place rules permitted by the block; skip (with a logged reason) otherwise.
5. **Materialize** the chosen asset into a normal `schedule_item` for that slot — identical shape to today's static-slot output, so playout (S4/S15) is unchanged.
6. **Idempotency:** re-running the compiler over the same window must not duplicate or thrash committed items; a slot already committed (OnAirLock) is never overwritten.
7. **Conflict / empty-result handling:** a slot whose query resolves to *zero* assets is left for filler (S6 CG/bulletin) with a logged `no_match` reason surfaced to S8 alerting; overlapping rules resolve by `priority` then `rule_id`.

**Boundary with S4:** the compiler produces *proposed* schedule_items; the operator's commit (OnAirLock) is still the gate to air. Auto-scheduling removes the *placement* labor, not the *commit* control.

---

## 7. Proof tier + testable DONE-criteria

| # | Done-criterion (testable) | Proof |
|---|---|---|
| DC-1 | A SavedSearch with a metadata filter resolves to the correct ordered asset list (unit + API `preview`). | contract |
| DC-2 | An AutoScheduleRule on a recurring slot materializes the **expected** asset for each instance across a 14-day window, per pick strategy (deterministic test for `top`/`newest`; seeded for `random`). | contract |
| DC-3 | Re-running the compiler is **idempotent** — no duplicate `schedule_items`, committed slots untouched. | contract |
| DC-4 | `avoid_repeat_within_days` prevents re-airing the same asset inside the window (as-run-aware). | contract |
| DC-5 | A `ScheduleBlock` restricts placement to permitted rules/dayparts; disallowed placements are skipped with a logged reason. | contract |
| DC-6 | A zero-match slot yields filler + a `no_match` alert (S8), never a black slot. | contract |
| DC-7 | Materialized items flow through the **unchanged** S4 commit gate and play out via S15 with no schedule-shape change. | lab (runtime, against the engine once Stage 1 lands) |
| DC-8 | `simulate` endpoint shows the operator the next N days a rule would fill, matching what the compiler actually produces. | contract |

Proof tier: **contract → lab**. (No SDI/rung-3; this is scheduling logic.)

---

## 8. Test plan

- **Unit:** query resolution, each pick strategy, recurrence expansion, block constraints, idempotency, avoid-repeat, empty-result→filler.
- **API:** all endpoints happy-path + error (invalid query, unknown saved_search, role gating).
- **E2E (Playwright):** build a saved search → bind a rule → simulate → see materialized items in the program-log view.
- **Coverage:** >80% on the new scheduling module.
- **Audit:** 0/0/0/0/0 (audit-lite per slice; audit-team + walkthrough at stage close).

---

## 9. Dependencies & cross-references

- **S4** (program log / commit-to-air): the compiler writes `schedule_items`; commit gate unchanged.
- **S5** (force-matrix): runtime arbitration unaffected — S19 is a *planning* layer.
- **S22** (custom metadata fields): saved-search queries can filter on custom fields (`0054` is shipped on disk; chain HEAD is now `0060_recording_paywall_merge` after S21 + S26 shipped 2026-06-18 and the merge revision unified the heads); queries also cover the fixed Asset schema.
- **S6** (CG/filler): zero-match slots fall to filler.
- **S8** (alerting): `no_match`, rule-conflict, and over-window failures are alert conditions.
- **S7** (media lifecycle): "ready/published" asset state gates eligibility.

## 10. DONE when

DC-1…DC-8 pass; migration `0043` on the single global chain (shipped on disk); operator UI complete + responsive; audit 0/0/0/0/0; master §11 index + RECONCILIATION migration table reference S19/`0043`.

Estimated implementation effort: **~2 engineer-weeks** (models + migration + compiler + API + UI + tests).
