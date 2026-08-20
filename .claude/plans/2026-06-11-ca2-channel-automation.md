# CA-2: 24/7 Channel Automation Driver — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md).

**Goal:** The app itself drives cable channels 24/7 — no CLI babysitting. Channels marked for automation come back on air after an app/machine restart, an app restart mid-program rejoins the program at the right offset (no drift against the log), and gaps re-plan automatically.

**Verified current state (deep-read 2026-06-11):**
- The loop exists (`EgressService.run` → `daemon.process_once`, civiccast/egress/service.py:52) but ONLY the CLI (`civiccast egress run`, cli.py:817-844) ever runs it — nothing in the app lifespan.
- Encoder crash auto-restart already works inside `_poll_process` (daemon.py:455-469); slate fallback + exit already work; the command queue is durable (`egress_commands`).
- **Gap A — no app-lifespan driver.** **Gap B — no durable "this channel should be running" intent**: the consumed start command is gone after restart, so a reboot leaves channels dark until an operator re-clicks Start. **Gap C — no join-in-progress**: `build_source_plan_from_schedule` (source_plan.py:111-159) starts the current item from its trim start, not from `now - scheduled_at`, so a restart mid-program replays from the top and the channel drifts off its published log.

**Design (locked):**
1. **Migration `0032_channel_automation`** (parent 0031): add `auto_start` Boolean NOT NULL default false to `egress_configs` + model/API surface (`EgressConfigDb`, config Pydantic models, config PUT endpoint). Operator meaning: "this channel runs 24/7; bring it back after restarts."
2. **`civiccast/egress/automation.py`**:
   - `ChannelAutomationSettings.from_env()`: `CIVICCAST_CHANNEL_AUTOMATION=inline|off` (default **inline** — safe: with no `auto_start` channels and an empty command queue, each poll is a cheap DB read; no encoder ever spawns uncommanded), `CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS` (default 2.0), `CIVICCAST_EGRESS_WORK_DIR` (default managed-storage subdir).
   - `ChannelAutomationService`: constructed from a session factory (mirror cli `_run_egress_service` wiring: PostgresEgressStore + ScheduleSourcePlanProvider(PostgresScheduleStore asset resolver) + SlateSourceGenerator + SourcePreparer + env secret resolver). `run_forever(poll_seconds, stop_event)`:
     a. enumerate channels from `store.list_configs()` (enabled);
     b. **auto-start pass**: channel has `auto_start`, daemon has no live process, and no pending stop/drain → enqueue a `start` command (`issued_by="channel-automation"`) — once per dark period, not per tick (track in-memory per-channel "start issued" latch cleared when a process appears);
     c. `daemon.process_once(channel_id)` per channel;
     d. **slate re-plan check**: if daemon state is FALLBACK_SLATE and the source-plan provider now returns a real plan → enqueue `reload` so the due program takes over (latched per due-item to avoid reload storms).
   - Wired as `ThreadSupervisor(name="civiccast-channel-automation")` in app.py next to the Stage F workers (only when durable storage is active).
3. **Join-in-progress** in `build_source_plan_from_schedule`: for the CURRENT item only, compute `elapsed = now - item.scheduled_at`; effective inpoint = `(asset trim_in or 0) + elapsed`, capped: if effective inpoint >= effective outpoint/duration → treat the item as finished (advance to next). Segment duration shrinks accordingly. Future items unchanged. This makes restart-mid-program rejoin at the wall-clock-correct offset.

**Tests (TDD):**
- `tests/egress/test_source_plan.py` additions: join-in-progress offset math (10 min into a 60-min program → inpoint +600s, duration -600s; elapsed past end → item skipped → next item; trim respected).
- New `tests/egress/test_automation.py`: settings validation; auto-start enqueues exactly one start for a dark `auto_start` channel (and none for non-auto channels / when a process is live); slate re-plan enqueues one reload when a plan becomes available; run_forever stop_event honored. Fake daemon/store doubles in the existing test style.
- Migration: head-pin advance to `0032_channel_automation`; config API round-trip with `auto_start`.

**Steps:** branch `work/ca2-channel-automation` → failing tests → migration+model+API → automation module → app wiring → docs (background-workers.md + channel-egress-runbook.md) → OpenAPI regen → full gate → PR → merge.

**Honest boundary:** CA-2 makes the engine self-driving; continuous *content* between programs is still slate-only until CA-3 (bulletin filler). The 24/7 claim gets proven in CA-8, not asserted here.
