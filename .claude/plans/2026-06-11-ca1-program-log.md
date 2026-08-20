# CA-1: Continuous Program Log — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (see 2026-06-11-cable-automation-sprint-master.md).

**Goal:** Recurring, operator-managed program slots per channel that materialize into real `schedule_items` over a rolling horizon — so the EXISTING `ScheduleSourcePlanProvider` → `PlayoutSupervisor` path plays a 24/7 program log with zero egress changes.

**Design (locked):**
- New module `civiccast/programlog/` (models, store, materializer, router) — keeps `schedule/` untouched except read/write through its existing store API.
- **`channel_program_slots`** (migration `0031_program_log`, parent `0030_webhook_retry_queue`): slot_id PK (String 120, `cps_` prefix), channel_id (String 80, indexed), asset_id (String 64), title_override (Text nullable), recurrence (`once|daily|weekly|weekdays`), first_start_at (DateTime tz), duration_seconds (Integer nullable → asset duration when null), repeat_until (DateTime tz nullable), enabled (Boolean default true), created_at/updated_at. CHECK on recurrence values.
- **`program_slot_occurrences`**: occurrence_id PK, slot_id (FK-style string, indexed), occurrence_start (DateTime tz), schedule_item_id (String 64), status (`scheduled|skipped_conflict|skipped_asset`), detail (Text default ''), created_at. UNIQUE (slot_id, occurrence_start) — the idempotency key.
- **Materializer** (`ProgramLogMaterializer`): for each enabled slot, compute occurrences from `max(now, first_start_at)` through `now + horizon` (default 72h, `CIVICCAST_PROGRAM_LOG_HORIZON_HOURS`); for each occurrence not yet in the link table: resolve the asset (must exist, validated/recorded, file_path set, duration known) → create a premiere `schedule_item` via the existing schedule store → record the occurrence. On collision (Postgres EXCLUDE raises IntegrityError) or bad asset → record `skipped_conflict`/`skipped_asset` with detail, never crash the loop. Worker shape mirrors the AP retry worker: `run_once` testable, `run_forever`, ThreadSupervisor behind `CIVICCAST_PROGRAM_LOG_WORKER=inline|off` (default inline), poll `CIVICCAST_PROGRAM_LOG_POLL_SECONDS` (default 300).
- **Cancellation rule:** disabling/deleting a slot cancels its FUTURE materialized schedule_items (state→cancelled via schedule store) and marks occurrences; past ones untouched (what aired, aired).
- **API** (staff, `/api/staff/programlog`): CRUD slots; `GET /channels/{channel_id}/log?from=&to=` — the materialized log (joined occurrence+schedule data, incl. skips with reasons); the guide editor (CA-5) consumes this.

**Tests (TDD, `tests/programlog/`):**
1. Occurrence computation pure-function tests: once/daily/weekly/weekdays, repeat_until, horizon edges, DST-safe (tz-aware UTC math).
2. Materializer with in-memory/sqlite stores: creates premiere items idempotently (run_once twice → no dupes); skips+records conflicts (simulate store raising on overlap) and missing/unpackaged assets with honest detail; disable-slot cancels future items only.
3. Store round-trips (sqlite via Base.metadata like webhook-queue tests) + Postgres-gated real-collision test (two overlapping slots on one channel → second occurrence `skipped_conflict` via the real EXCLUDE constraint).
4. API tests: CRUD, log endpoint shape, 404/422 paths.
5. Single-alembic-head test pin advance → `0031_program_log`.

**Steps:** branch `work/ca1-program-log` → failing tests → models+migration → store → materializer → app wiring (ThreadSupervisor) → router + OpenAPI regen → docs (background-workers.md section, CAPABILITIES "program log" row honest) → full gate → PR (`refs #cable-automation`, cite master plan) → merge.
