# BETA.10 LIVE FINDING - rollover / stall / post-restart wedge

**Recorded:** 2026-09-21 ~10:54 MT
**By:** coder session (thread 01a0bdd6-b74a-7bf2-b09b-f96218493a8d)
**State under test:** repo HEAD a64907ac (main), 18 tracked files modified, installed runtime = HEAD for engine.py, service env restored to the 7-entry baseline this session.

This file is written BEFORE any code change, per the project rule.

---

## 1. Live station state (authoritative)

Read from the control-plane log and the `civiccast.egress_states` / `egress_health_samples` tables, NOT from `/api/health`.

| channel | egress_states.state | recorded pid | pid alive? | last updated |
|---|---|---|---|---|
| public | STOPPED | (none) | - | 2026-09-21T16:19:29Z |
| government | STOPPED | (none) | - | 2026-09-21T10:59:10Z |
| education | FALLBACK_SLATE | 45860 | **NO** | 2026-09-21T16:51:39Z |

Last `ON_AIR` on any channel: **2026-09-21 02:00:27 MT** (~8.9 h before this writing).
Published schedule items ahead of now: **0 on all three channels** (schedule is dry).

## 2. Defect B reproduced live (reloads accepted, never settle)

Three consecutive accepted seamless reloads on education, each `switch_at_end_of_current=True`, and NONE produced any later settlement/commit/abort line:

    10:34:08  Seamless content-reload accepted for education (reload_id=df1bfca6-737f-49d6-85e4-8395ecaaa476, switch_at_end_of_current=True); awaiting settlement.
    10:40:09  Seamless content-reload accepted for education (reload_id=c62af81d-07ee-4d40-8e1b-cd4a82af7999, switch_at_end_of_current=True); awaiting settlement.
    10:46:11  Seamless content-reload accepted for education (reload_id=2b023435-0609-4780-9e42-a8c49468614d, switch_at_end_of_current=True); awaiting settlement.

Grep for those three reload_ids returns **only the accept line** - no `settled`, no `commit`, no `did not land`, no `discarded`. Source prep was fast (2.1-3.1 s for 12 segments), so this is NOT a preparation-timeout case.

## 3. Defect A is recurring, not dormant

19 `CTRL stall` lines total, three of them fresh today (10:23:40, 10:25:13, 10:27:42). Each shows the documented shape on the SLATE path:

    CTRL output: 801 (+799) | 1188 (+1186) | 1570 (+1568) | 1954 (+1952) | 3729 (+3727) | 3764 (+3762) | 3764 (+3762)
    CTRL stall: no output for 10s - quitting for daemon restart

Buffers climb, then flatline at a round total, then the 10 s watchdog fires. So the budget asymmetry is biting on the slate path too, not only at programme rollover.

## 4. PRIMARY NEW FINDING - the restarted control plane's egress automation is DEAD

After the clean Step-2 restart at 10:52:

- service `CivicCastSupervisor` Running, service pid 16380
- control plane pid **4248**, started 2026-09-21 10:52:12 MT, 45 threads, endpoint `/api/health` 200 in 188 ms, `/api/public/channels` 200 in 12 ms - **the HTTP layer is healthy and responsive**
- `control_plane-app.log` last write **10:52:37**; **zero log lines after 10:52:37**
- `egress_health_samples` newest row **16:51:39Z** (= 10:51:39 MT) - i.e. one second BEFORE the restart; **no sample from the new process at all**
- `egress_states.education` still claims pid **45860**, which is **not a running process**

Interpretation: the process is up and serving HTTP, but the egress daemon loop is **not ticking** - it writes no log, emits no health samples, and has left a stale state row pointing at a dead pid. This is a wedge, distinct from both A and B, and it is the state the station is in right now.

**Ruled in:** a wedge of the egress automation after restart.
**Ruled out:** process death (pid alive, HTTP 200), service failure (Running), simple slow start (30+ s with zero ticks and zero samples).

## 5. Third live defect - caption overload trips on a cold start

Education tripped the caption backlog gate **2 seconds after restart, with no programme airing**:

    10:52:37  Caption tap overload for channel education: 4 settled segments exceeds the maximum 2. Live captions are PAUSED for 120s (overload #1)

Repeated earlier at 10:18/10:22/10:23/10:25/10:27 with 6-7 segments, every one reported as **overload #1** (no escalation between them). Settled audio is accumulating faster than the gate drains at startup.

Also live: `Caption retention first verification is still running after 1.0s; the scan proceeds FAIL-CLOSED` - the same 1 s-wait vs ~15 s-sweep mismatch that holds captions at `retention-verification-pending`.

## 6. What this changes in the plan

1. The immediate blocker list is longer than the handoff's two defects: A (recurring), B (reproducing), **C (post-restart egress wedge - NEW, currently active)**, plus the caption-overload/retention-pending gate.
2. Priority: establish why the egress automation loop does not tick after restart (C), because until it ticks, nothing airs regardless of A/B.
3. The schedule is already dry on all three channels, so the loop work is a hard prerequisite for any run.

## 7. Evidence pointers

- Log: `C:\ProgramData\CivicCast\logs\control_plane-app.log`
- Tables: `civiccast.egress_states`, `civiccast.egress_health_samples`, `civiccast.schedule_items`
- Repo: `civiccast/egress/gst/engine.py` (reload/stall), `civiccast/egress/daemon.py`, `civiccast/egress/automation.py`
- Service env restored (7 entries) via helper job `beta10-restore-env-20260921-1052`

---

## 8. CORRECTION (same session, 10:57 MT) - the egress loop is ALIVE, not dead

Section 4 above was wrong on the mechanism. I verified with a live py-spy stack dump of pid 4248 (captured via the elevated helper, saved at `work\beta10-pyspy-defectC-20260921.txt`, 13,346 bytes):

- **All 22 threads are `(idle)`.** No thread is spinning, blocked on a lock, or stuck in GStreamer.
- The thread named `civiccast-channel-automation` is sitting in `run_forever` at `civiccast\egress\automation.py:546` -> `stop_event.wait(poll_seconds)`. That is the normal end-of-pass poll sleep. The loop is ticking.
- `MainThread` is in the uvicorn/asyncio selector loop (normal).
- `civiccast-caption-tap-worker` is idle at `tap_worker.py:610` (normal poll wait).

So the earlier "egress automation is DEAD" reading was **wrong**: the loop is alive and simply has nothing to do (no enabled/airing channel, zero published schedule items). The absence of new log lines is because nothing changed - not because the loop stopped.

**What is still true and unexplained** (and now needs a different explanation):

- `egress_health_samples` newest row is 16:51:39Z, i.e. ~5 minutes stale, with **no new sample from pid 4248**.
- `egress_states.education` still claims `pid=45860`, which is **not running**.
- `PercentProcessorTime` for pid 4248 reads 97% from `Win32_PerfFormattedData_PerfProc_Process`, while all Python threads are idle. This is almost certainly a **counter artifact** for a freshly-started process (ElapsedTime 347 s) rather than real CPU burn; the machine-wide CPU is only ~24% and pid 4248 is not among the top CPU consumers. The `psutil.threads()` returning an empty list is a separate quirk (access/rights), not evidence of a wedge.

**Why this matters:** the health-sample gap is real and is the thing to chase, but the cause is NOT a stuck automation thread. Candidate explanations now: the sample writer runs on a different cadence/path (`alerting` evaluator "runs off each egress health sample"), or the sampler is gated on an on-air/state transition that is not occurring. This must be pinned down before blaming the loop.

**Discipline note:** this is the same failure mode the project keeps hitting - naming a cause before proving it. Section 4 named one; this correction retracts it with evidence. Both are retained deliberately.

---

## 9. SECOND CORRECTION + ROOT CAUSE OF THE DARK STATION (10:59 MT)

Two more corrections, both from authoritative state:

### 9a. The health-sample gap is EXPECTED, not a wedge
`_append_health` (`daemon.py:1853`) is called only from **state-transition** sites (`daemon.py:1300, 1389, 1416, 1764, 1778, 1787, 2225, 2371, 2406, 2520, 2675, 2798, 3517, 3823, 3842`). It is **not** on a timer. So a channel sitting in a steady state correctly produces no new samples. The "no new sample since 16:51:39" is the signature of a channel that is NOT transitioning - not evidence of a stalled writer. Retract any reading of 16:51:39 as a heartbeat failure.

### 9b. Reload `2b023435` DID apply
`C:\ProgramData\CivicCast\data\egress\education\reload-status.json` reads:
    {"id": "2b023435-0609-4780-9e42-a8c49468614d", "result": "applied", "ts": 1790009191.936374}
So the third accepted reload settled as `applied` on disk even though no `settled` line appears in the app log. **The app log is NOT a complete record of reload outcomes.** Any future evidence gathering must read `reload-status.json` per channel, not just grep the log. This weakens the earlier "reloads never settle" claim: at least one of the three did.

### 9c. ROOT CAUSE of the dark station - auto_start is OFF on all three channels
From `civiccast.egress_configs`:

| channel | enabled | auto_start |
|---|---|---|
| education | True | **False** |
| government | True | **False** |
| public | True | **False** |

`automation.py:616-631`: a channel is auto-started only `elif config.auto_start:`. With `auto_start=False`, the automation loop will **never** bring a dark channel up - it only calls `daemon.process_once`, which supervises an already-running channel. This is **by design** ("safe: with no auto_start channels and an empty schedule, nothing happens" - automation.py:27).

So the station is dark for an ordinary, fully-explained reason: **nothing ever issued a start, and no one has started the channels since the restart.** This is not a new defect. It is the documented behavior, and the fix is an explicit operator start (or turning auto_start on for soak purposes).

### 9d. The schedule is genuinely dry
`civiccast.schedule_items`, published premiere, per channel: 113-118 rows, max `scheduled_at_end` = **2026-09-21 07:49:01Z** (01:49 MT). Now is 16:58Z. Every published item is in the past; **zero items ahead**. The schedule ran dry at 01:49 MT, exactly as the handoff predicted. `CIVICAST_SCHEDULE_LOOP=1` is present in the environment but has produced no new items - so it is inert, confirming the handoff's warning.

## 10. Revised picture

| item | status |
|---|---|
| Station dark | EXPLAINED: `auto_start=False` on all 3, plus schedule dry since 01:49 MT |
| Health samples stale | EXPLAINED: transition-driven writer, steady state emits none |
| Reloads never settle | PARTLY RETRACTED: `2b023435` = `applied` on disk; app log incomplete |
| Education caption overload | REAL: trips on cold start, ~2 s after restart, always "#1" |
| Retention verification pending | REAL: 1 s wait vs ~15 s sweep |
| CTRL stall (Defect A) | REAL and recurring (19 total, 3 today) |
| Schedule loop inert | REAL: env var set, zero effect, queue dry |

---

## 11. THIRD CORRECTION + THE REAL SCHEDULE-LOOP DEFECT (11:05 MT)

### 11a. Retraction: the loop is NOT inert
My section 9d said `CIVICAST_SCHEDULE_LOOP=1` "is present but has produced no new items - so it is inert." **That was wrong.** The loop IS implemented and IS installed:

- `civiccast/egress/source_plan.py:108` `schedule_loop_enabled_from_env()`
- `civiccast/egress/source_plan.py:379-380` calls `_repeat_schedule_cycle(playable_items, current_time)` when enabled
- `civiccast/egress/source_plan.py:440-464` `_repeat_schedule_cycle`
- wired through `civiccast/egress/automation.py:1783, 1841` (`loop_schedule=schedule_loop_enabled_from_env()`)
- **installed runtime == repo** for both files:
  - `source_plan.py`  installed `6E31FB863041BAB6B6F0A11CC3D06AFB7B8CC32BC804C648CF7B0420BDECA038` == repo
  - `automation.py`   installed `FDCAA3D6069B7C7E1DC3B071BBB6970A98E79D57E8F67D79BDB5C24C55ECEF45` == repo
  - loop references present in the installed copy: 7

So the feature exists and is running. It just **does not solve the problem it was written to solve.**

### 11b. THE REAL DEFECT: the loop wraps a *sparse* schedule, so "now" lands in a coverage gap and the channel stays on slate

Measured against live data (education, published premiere rows, at now = 2026-09-21T17:04Z):

**Raw published window (as stored):**
    first start : 2026-09-16 00:05:00Z
    last end    : 2026-09-21 07:49:01.1Z
    total media : 167,134 s
    wall span   : 459,841 s
    media coverage: **36.3% of the wall window**

So the schedule is **sparse by construction** - it only fills about a third of its own wall-clock window. 63.7% of the window is inter-item gaps.

**After `_repeat_schedule_cycle` shifts it to the current cycle:**
    new cycle window: 2026-09-21 07:49:01.1Z -> 2026-09-26 15:33:02.2Z
    now             : 2026-09-21 17:04:25Z
    ANY item covering now?  **False**
    nearest item ended  : 2026-09-21 15:33:01.1Z
    next item starts    : **2026-09-24 08:20:40.1Z**   <- ~2 days 15 hours away

Largest gap in one shifted cycle: **233,019 s (~2.7 days)**, from 2026-09-21 15:37:01.1Z to 2026-09-24 08:20:40.1Z. There are 18 gaps totalling 292,707 s per cycle.

**Mechanism:** `_repeat_schedule_cycle` (source_plan.py:440) shifts the entire finite sequence by whole cycle periods so the cycle *anchor* lands near now, but it preserves every inter-item gap verbatim ("Gaps between items remain gaps - the normal filler/slate policy owns them"). Because the published schedule covers only 36.3% of its period, a shifted "now" very often falls in a gap - and then `_current_item_index` (source_plan.py:436) returns None, `build_source_plan_from_schedule` returns None, and the daemon falls back to FALLBACK_SLATE. That is exactly what all three channels are doing right now.

**So the loop cannot guarantee a run-dry-proof station.** For a 2/4/8-hour rung that needs *continuous real speech*, wrapping a 36%-dense schedule still leaves multi-hour dark gaps.

### 11c. Two separate things are needed (do not conflate)
1. **Coverage**: for a soak, the schedule must be dense enough to cover the full wall window with media (or the fill policy must supply speech-bearing content, not slate). The current 113-row published set does not.
2. **Wrapping**: `_repeat_schedule_cycle` works arithmetically (verified: cycle_index 1, offset 5.3222 days, now inside the shifted *window*) but is the wrong tool for a sparse schedule. Either the schedule must be made dense, or the loop must fill gaps with real content.

`build_source_plan_from_schedule()` takes `current_time` **positionally**, not as a keyword (`current_time` is the 4th parameter) - noting for my own test authoring.

### 11d. Current live state (11:05 MT)
    public     : STARTING     (slate)  - worker exited, relaunching
    government : FALLBACK_SLATE (slate)
    education  : FALLBACK_SLATE (slate)
    VTT: all three 7 bytes
    CTRL stall count: 20 | tap overload: 107 | worker exits: 110
    live pids: government 34748, education 43160, public relaunching

---

## 12. QUANTIFIED: the schedule density defect, and what the soak actually needs (11:07 MT)

Per-channel coverage of the published schedules (source: `civiccast.schedule_items`, state=published, mode=premiere):

| channel | rows | media hours | wall span hours | coverage | gaps | max gap |
|---|---|---|---|---|---|---|
| public | 118 | 48.26 | 127.73 | **37.8%** | 22 | **35.31 h** |
| government | 113 | 46.43 | 127.73 | **36.3%** | 18 | **64.73 h** |
| education | 113 | 46.43 | 127.73 | **36.3%** | 18 | **64.73 h** |

So every channel's published schedule fills roughly **one third** of its own wall-clock window, with single gaps of **35-65 hours**.

### Why this makes the 2h/4h/8h rungs impossible as-is
The rung requires per-channel ON_AIR with **real speech** for the whole run. With a 36%-dense schedule, a random 2-hour slice has roughly a 64% chance of landing in a gap; and the specific current position is a gap whose next item is ~2 days 15 h away. `_repeat_schedule_cycle` preserves gaps by design, so looping does not close them. The channel therefore sits on `FALLBACK_SLATE`, which is exactly what is on air now.

### The fix has two independent halves - both required
1. **Density (schedule side):** build a schedule whose media covers the full wall window for the run duration, with no gap larger than the intended run. Available media is sufficient: **30 validated assets, 35.47 hours total**. A 2h rung needs 2h of contiguous speech per channel; 4h needs 4h; 8h needs 8h. One channel's 8h rung is well inside the 35.47 h pool, and can be assembled by repeating assets with `repeat_prevention_days` (an existing `auto_schedule_rules` column) disabled or by explicit rows.
2. **Wrapping (code side, already present):** `_repeat_schedule_cycle` is correct for its stated contract; it is simply not a gap-filler. If a soak wants "never run dry", either the schedule must be dense, or gap-filling must supply real speech. I recommend fixing the **schedule**, not changing the loop, because the loop's documented contract ("gaps remain gaps; the fill policy owns them") is deliberate and changing it would alter broadcast semantics for all customers.

### Recommended soak construction (not yet executed)
- Build a dedicated dense schedule per channel for the soak window (e.g. 3 h of contiguous programme for a 2 h rung, giving margin), using the existing validated `lpmrot-*` assets.
- Keep the loop ON as a second line of defence.
- Verify with the same `_repeat_schedule_cycle` / coverage probe used here that **no gap exists inside the rung window** BEFORE opening the rung.
- Do not weaken the backlog gate or any threshold to achieve this.

### Correction log for this file
- S4 "egress automation is DEAD" -> RETRACTED (py-spy: all 22 threads idle, loop parked normally at automation.py:546)
- S4 "health samples stale = wedge" -> RETRACTED (transition-driven writer; steady state emits none)
- S2 "reloads never settle" -> PARTLY RETRACTED (`reload-status.json` shows 2b023435 = applied)
- S9d "schedule loop is inert" -> RETRACTED (loop is implemented and installed; it is a coverage problem, not a missing feature)

---

## 13. FIX VALIDATED ON PRODUCTION CODE (11:10 MT)

Ran the real production planner against the live database, using the production asset resolver (`PostgresAssetStore.get_staff_row`, the same object `automation.py:1839` passes) via `build_source_plan_from_schedule`.

    SPARSE (live published rows) + loop_schedule=True  ->  None        (slate; no content)
    DENSE  (3 h contiguous from validated assets)       ->  6 segments  (real programme)

This is the decisive A/B. The schedule loop is working exactly as written; it simply cannot rescue a 36%-dense schedule, because `_repeat_schedule_cycle` deliberately preserves inter-item gaps. **Building a dense schedule fixes it; the loop does not.**

Notes captured for implementation:
- `build_source_plan_from_schedule` is keyword-only, requires `asset_resolver`, and `ScheduleItemResponse.id` must be a valid UUID string.
- SQLAlchemy against this DB needs the psycopg3 driver: `postgresql+psycopg://...` (psycopg2 is not installed in the repo venv).
- Segment `duration_seconds` are visible (1500/1800...); `start_seconds`/`asset_id` are not plain attributes on the segment model and need the model's own accessor - to check when writing tests.

### Status of the four obstacles to "3 channels with real speech"
1. **Channel start** - DONE: explicit start issued; all three now hold slate with live pids. (`auto_start=False` explains why they were dark.)
2. **Schedule density** - ROOT-CAUSED AND FIX VALIDATED: build a dense schedule. Not yet built.
3. **Defect A (10 s stall budget)** - recurring, 20 occurrences, not yet diagnosed (stall diagnostic still unstaged).
4. **Caption path** - 107 overload trips + `retention-verification-pending`; captions stay off even with audio.

---

## 14. FOURTH CORRECTION + PRECISE ROOT CAUSE OF THE LOOP FAILURE (11:12 MT)

### 14a. Retraction of my own density analysis
Section 12 said "coverage 36.3%, gaps up to 64.7 h" and concluded the schedule is "sparse by construction". That framing was **misleading**, and I am correcting it. The schedule is NOT uniformly sparse. It is **five separate contiguous passes** with large gaps BETWEEN them:

    contiguous runs by item count: [45, 12, 11, 27, 18]
    last run: 18 items, 2026-09-20 04:33:28Z -> 2026-09-21 07:49:01.1Z
    last run: media 27.26 h over a span of 27.26 h  ->  **100% dense, zero internal gaps**

The 36.3% figure is an artefact of averaging across all five passes plus the inter-pass gaps. Within any single pass the schedule is fully contiguous.

### 14b. THE ACTUAL DEFECT
`_repeat_schedule_cycle` (`source_plan.py:440`) takes the WHOLE `playable_items` list and uses:

    anchor    = items[0].scheduled_at          # earliest item in the entire history
    cycle_end = max(scheduled_at + duration)   # end of the entire history

So the "cycle" it repeats is the **entire 127.73-hour, 113-item, five-pass history** - including the multi-day gaps between passes. `period_seconds` = 5.3222 days. Shifting that whole span by whole periods places `now` in one of the inter-pass gaps, `_current_item_index` returns None, and the channel falls to slate. That is exactly what is on air.

### 14c. PROOF that looping the single contiguous pass FIXES it
Repeating ONLY the last contiguous 18-item run (one real pass), at now = 2026-09-21T17:07Z:

| channel | last-run items | period | item covering now |
|---|---|---|---|
| public | 18 | 27.26 h | `lpmrot-03-senior` |
| government | 18 | 27.26 h | `lpmrot-07-parks` |
| education | 18 | 27.26 h | `lpmrot-02-city` |

All three: **inside_now = 1** (an actual programme item covers the current instant). Cycle window for education lands at 2026-09-21 07:49:01Z -> 2026-09-22 11:04:34Z, and now (17:07Z) is inside it with `lpmrot-02-city` airing.

### 14d. Consequence for the fix
The bug is **not** that the schedule needs to be denser, and **not** that the loop is missing. The bug is that **the loop's cycle boundary is computed over the whole published history instead of over one contiguous playable pass.** The fix is to make the cycle boundary derive from the contiguous run, not from `items[0]..max(end)`. That is a real code change in `_repeat_schedule_cycle` / its caller, and it is far better than hand-building a new schedule because it fixes the product for every operator, not just this soak.

Also note: each pass is ~27.26 h of contiguous media, so a 2 h / 4 h / 8 h rung is comfortably coverable once the cycle is computed correctly.

### 14e. Test to write (RED first)
A unit test that: takes items in two contiguous passes separated by a large gap, calls `_repeat_schedule_cycle` with a `current_time` inside the *repeated last pass*, and asserts an item covers `current_time`. That must FAIL on the current implementation and PASS after the boundary is fixed.

---

## 15. FIX IMPLEMENTED - RED FIRST, GREEN AFTER (11:20 MT)

### The change
`civiccast/egress/source_plan.py`:
- added `_contiguous_schedule_run(items, gap_tolerance)` - returns the LAST contiguous run of a sorted schedule (a break is "next start > previous end + tolerance").
- `_repeat_schedule_cycle` now computes its anchor/cycle_end/period from that contiguous run instead of the whole history, and returns only the cycle's items.

Net effect: the loop repeats one real pass (27.26 h of contiguous programme) instead of the entire 127.73 h five-pass history.

### RED (before the fix) - new test `test_looping_provider_covers_now_when_history_has_multiple_passes`
    E   AssertionError: no plan at 2026-06-05 00:00:30+00:00: the loop's cycle includes the inter-pass gap
    E   assert None is not None
    tests\egress\test_source_plan.py:704: AssertionError
    1 failed, 46 deselected

### GREEN (after the fix)
    1 passed, 46 deselected
    (full file) 47 passed in 1.75s

### Production-data verification (real DB + real PostgresAssetStore resolver, now = 2026-09-21T17:1xZ)
    public      plan -> 8 segments  first_label=Senior Citizens Advisory Board - June 2026.mp4
    government  plan -> 8 segments  first_label=Parks & Recreation Advisory Board - April 2026.mp4
    education   plan -> 7 segments  first_label=City Council Regular Session - September 8, 2026.mp4

All three channels produce REAL PROGRAMME PLANS where they previously produced None (slate). This is the difference between a dark station and a captioning one.

### What is NOT yet done
- The fix is in the **working tree only**; it is NOT staged into the installed runtime, so the live station still returns slate. Staging + restart is the next step and will be done via the elevated helper with pre/post hashes and a receipt.
- The schedule itself still holds five passes with multi-day gaps; the loop now correctly repeats the last pass, which is sufficient for rungs up to 27.26 h. A run longer than one pass would wrap onto the same pass again, which is the intended loop semantic.
- Defect A (10 s stall) and the caption overload / retention-pending gates are still open.

---

## 16. LOOP FIX STAGED AND LIVE - BUT STILL SLATE; NEW OPEN QUESTION (11:22 MT)

### Done this turn
- Staged `civiccast/egress/source_plan.py` into the installed runtime via the elevated helper (`beta10-stage-loopfix-20260921`):
  - pre `6E31FB863041BAB6B6F0A11CC3D06AFB7B8CC32BC804C648CF7B0420BDECA038`
  - post `8D1DC211A6C868A8FB8276DC2DAC1A5D9F54EB7FE6F3292923FAD62D53A2CD4B` == repo (match true)
  - `_contiguous_schedule_run` present in installed: 2 refs
  - backup: `C:\CivicCastTester\beta10-runtime-backup-loopfix-20260921\source_plan.py.pre-loopfix`
- Restarted `CivicCastSupervisor` via the helper (`beta10-restart-for-loopfix-20260921`): ok, health 200, new control-plane pid 38788.
- Re-issued explicit starts for all three channels (202 each).

### Result: still FALLBACK_SLATE
All three channels hold slate with live pids; daemon `last_error` reads:
    No valid source plan is available; generated fallback slate.
(count of that line in the log: growing).

### The critical discrepancy
The SAME query path the live provider uses DOES produce a plan when driven directly:
    store.list(channel_id, states=(Published,)) -> public 118 / government 113 / education 113
    build_source_plan_from_schedule(..., loop_schedule=True, max_segment_seconds=1800.0, max_segments=1)
      -> public 1 seg / government 1 seg / education 1 seg

Yet live it returns None. **So the code is correct and the live provider is not passing the loop flag (or not reaching this code).**

Verified so far:
- registry `CIVICAST_SCHEDULE_LOOP=1` present (7-entry baseline)
- installed `automation.py` DOES call `schedule_loop_enabled_from_env()` at :1841 (2 refs)
- running control-plane pid 38788 was opened with full handle (handle 376, err 0) under admin

NOT yet proven: whether pid 38788's own environment block actually contains `CIVICAST_SCHEDULE_LOOP`. The service was restarted by `Restart-Service`, which should re-read the service Environment MultiString - but that is an assumption I have not measured, and this project has been burned by exactly that assumption before. Next step: dump the running process' environment block and assert the variable is present, then if present, trace the live provider call (temporary debug log or pyspy) to see the actual `loop_schedule` value and the actual item count returned.

### Do not claim
Do not claim the loop fix works in the live station. It is staged and unit-proven, and it produces plans under direct invocation, but the live product still returns slate. The remaining gap is between "installed code" and "code path actually executed", which is the same class of gap this project already has a scar from.

---

## 17. ROOT CAUSE FOUND AND FIXED: ONE-CHARACTER ENV VAR TYPO (16:05 MT)

### The defect
The service registry had the environment variable misspelled by ONE character, and the code reads the correct spelling. They could never match:

    CODE reads : CIVICCAST_SCHEDULE_LOOP   (23 chars)
                 bytes 67,73,86,73,67,67,65,83,84,95,...   <- CIVIC C AST
    REGISTRY had: CIVICAST_SCHEDULE_LOOP  (22 chars)
                 bytes 67,73,86,73,67,65,83,84,95,...      <- CIVIC A ST  (missing C)

So `schedule_loop_enabled_from_env()` always returned False -> `loop_schedule=False` at
`automation.py:1841` -> provider returned None -> `daemon.py:1406-1421` -> FALLBACK_SLATE.
That was the entire live blocker, and it was a typo in configuration, not a code defect.

### Proof (ordinal-built names, immune to string corruption)
    registry spelling (22) -> schedule_loop_enabled_from_env() == False
    code     spelling (23) -> schedule_loop_enabled_from_env() == True

### Fix applied
Rewrote the service `Environment` MultiString via the elevated helper, constructing every
name from ordinal character codes so the typo could not recur in transit
(job `beta10-fix-loop-env-ordinals-20260921`, exit 0):
    loop_name  : CIVICAST_SCHEDULE_LOOP
    loop_len   : 23
    loop_bytes : 67,73,86,73,67,67,65,83,84,95,83,67,72,69,68,85,76,69,95,76,79,79,80
Then restarted the service (job `beta10-restart-after-loopfix-20260921`, exit 0),
health 200, new control-plane pid 10540.

### RESULT: THE STATION IS AIRING REAL PROGRAMME
After issuing explicit starts (auto_start=False), first time in this whole effort:

    public     ON_AIR  Library Advisory Board - May 2026.mp4           (32s on air)
    government ON_AIR  Serving Locally, with Michelle? SMART Recovery  (172s)
    education  ON_AIR  Senior Citizens Advisory Board - June 2026      (172s)

And captions began flowing: public active.vtt 586 B (was 7 B for days).

### IMPORTANT CORRECTION TO MY OWN EARLIER CLAIMS
For several turns I described this as an inexplicable interpreter/module anomaly
("identical bytecode, different result") and recommended handing the thread off.
**That was wrong.** The apparent paradox was caused by MY instrument mangling string
literals in transit: the names I *typed* were not always the names that *reached* Python.
The underlying reality was a simple one-character config typo. The correct response would
have been to suspect the measurement channel far earlier. Lesson recorded.

### New blocker observed (next work item)
Captions are now flowing but the tap is tripping on the caption backlog gate:
    government / education: state=paused, consecutive_overloads=1, resume_in_seconds~85
    public: within-capacity
So the backlog gate (max 2 settled segments) pauses a channel shortly after speech starts.
This is the caption-overload defect, and it is now the binding constraint on
"captions stay up". It is a separate defect from the env typo and from Defect A.

---

## 18. STATION AIRING WITH CAPTIONS + WATCHER BUILT (16:19 MT)

### THE MILESTONE: three channels ON_AIR with real speech AND real captions
    public     ON_AIR  Library Advisory Board - May 2026.mp4        vtt 5689 B
    government ON_AIR  Serving Locally, with Michelle? SMART Recovery  vtt 4285 B
    education  ON_AIR  Senior Citizens Advisory Board - June 2026    vtt 4064 B
Cue timestamps counted in the live sidecars: 45 / 30 / 28. These VTTs had been
exactly 7 bytes for days. Captions are flowing on all three channels.

Caption recovery detail: government and education were briefly PAUSED by the
backlog gate (overload #1, resume_in_seconds~85) right after speech began. They
RESUMED automatically when the pause expired and captions then grew steadily
(7 B -> 199/228 B -> 394/436 B -> ... -> 2872/2805 B over 3 minutes). So the gate
pause is self-clearing, not a permanent stall - important, and different from
what the earlier "paused" reading suggested.

### WATCHER BUILT AND RUNNING (first time in this project)
    C:\CivicCastTester\soak-beta9-2h-20260921\channel_watch.py
    ledger    : watch-ledger.jsonl      (append-only JSONL, one sample / 15 s)
    heartbeat : watch-heartbeat.json    (machine-readable, outside observers can read)
    logs      : watch-stdout.log / watch-stderr.log
Running as pid 45800 (background). Live sample:
    {"public": ON_AIR vtt 5689, "government": ON_AIR vtt 4285, "education": ON_AIR vtt 4064}
    alerts: []   health: 200   control_plane_pid: 10540   state: "healthy"

Detectors, ALL PROVEN CAPABLE OF FIRING (an instrument that cannot fail is not one):
    A stopped channel   -> alert not_on_air(STOPPED)      [fired in proof]
    B empty 7-byte VTT  -> alert vtt_empty(7)             [fired in proof]
    C missing VTT       -> alert vtt_missing              [fired in proof]
    D stagnant VTT x4   -> alert vtt_stagnant(4)          [fired in proof]
    E healthy/growing   -> no alert                       [confirmed]
Live ledger alert count so far: 0 (genuinely healthy, not a broken detector).

### Status vs the plan's step list
  1. Orient ................................. done
  2. Restore service env .................... done (and then the typo fix below)
  3. Root-cause Defect B .................... superseded: the real blocker was a config typo
  4. Findings written before code changes ... done (this file, sections 1-18)
  5. Stage stall diagnostic ................. NOT DONE (engine.py needs gi; see below)
  6. Env switch + restart ................... done for the loop var; stall-diag var not added
  7. Fix red-first .......................... done for the loop-boundary bug
  8. Focused tests + installed-app proof .... unit tests done; live proof now REAL
  9. Three channels airing with captions .... ACHIEVED (this section)
 10. Verify schedule loop ................... in progress (channels are on programme)
 11. Rungs .................................. not started; watcher now exists

---

## 19. ROLLOVER VERIFIED + WATCHER CAUGHT A REAL OUTAGE (16:35 MT)

### Step 10 satisfied: a REAL schedule rollover committed
Observed live on government:
    16:26:46  channel government: reload source preparation queued
and the channel's on-air label then CHANGED between watcher samples:
    "Serving Locally, with Michelle? SMART Recovery.mp4"
 -> "Serving Locally, with Michelle? Wildlands Restoration Volunteers.mp4"
A label change mid-run is the observable proof that the seamless reload committed and
advanced the schedule, rather than dying or repeating the same item. All three channels
stayed ON_AIR across it. No `did not land`, no `discarded`, no re-slate.

### The watcher caught a real caption outage - and that is the point
Ledger fired 8 consecutive `vtt_empty` alerts on education, ~2 minutes:
    22:25:12, 22:25:29, 22:25:45, 22:26:02, 22:26:18, 22:26:34, 22:26:51, 22:27:07
    each: {"kind": "vtt_empty", "channel": "education", "bytes": 7}
Education's captions dropped to the empty 7-byte document and stayed there for ~2 min
while the channel remained ON_AIR. The watcher recorded it in the ledger in real time.
THIS IS EXACTLY THE FAILURE MODE THAT WENT UNNOTICED FOR TWO NIGHTS. It is now visible,
timestamped, and countable.

Post-outage, education recovered on its own and climbed back to 9,784 B by 22:34.

### Current steady state (watcher heartbeat, 22:34:51Z)
    public      ON_AIR  vtt 21,465 B
    government  ON_AIR  vtt 22,831 B   (new programme after rollover)
    education   ON_AIR  vtt  9,784 B   (recovered after the 2-min empty)
    control_plane_pid 10540, health 200, watcher uptime 960 s, alert_count_this_sample 0

### Phase-timing evidence on where caption CPU actually goes (from the tap summary)
Per 600 s window, 3 channels, 109 ASR batches:
    runtime_transcribe : 375,610 ms total, max 8,500 ms   <- the overwhelming cost
    pipeline_process   : 375,688 ms total, max 8,500 ms
    retention_dispatch :   1,422 ms total, max 1,219 ms
    review_store_create:   2,922 ms total, max 1,922 ms
    scan_settle_and_backlog_gate: 7,146 ms total, max 2,078 ms
So ASR transcription dominates; the backlog gate and retention are small by comparison.
Worth noting for any future "is captions CPU-bound" question - it is ASR-bound, on the GPU
path, not gate-bound.

### Status
 9.  Three channels airing with captions .... ACHIEVED and STABLE
10.  Schedule loop / real rollover ......... VERIFIED (label advanced live)
     Watcher ............................... RUNNING and has caught a real outage
11.  Rungs ................................. READY TO OPEN - prerequisites now met
     Defect A stall diagnostic .............. still not staged (engine.py needs gi)

---

## 20. FIRST LEGITIMATE RUNG EXECUTED - RESULT: FAIL (17:06 MT)

### Run
30-minute three-channel rung, captions ON, real programme. Window 16:36:02 -> 17:06:10 MT,
1800 s, 116 samples @15 s. Recorder `C:\CivicCastTester\soak-beta9-2h-20260921\rung_30m.py`.
Independent observer: the channel watcher (pid 45800) ran for the whole window.

### VERDICT: FAIL
| channel    | ON_AIR  | off-air | VTT>7B | empty | VTT grew          | pass |
|------------|---------|---------|--------|-------|-------------------|------|
| public     | 100/116 | 16      | 94     | 22    | no 22843->19133   | F    |
| government | 112/116 | 4       | 77     | 39    | no 24145->5794    | F    |
| education  | 116/116 | 0       | 91     | 25    | yes 11310->17778  | F    |

Pass required ON_AIR every sample AND VTT>7B every sample AND net growth. None met all three.

### What the run actually showed (honest characterisation)
NOT a blackout: all three channels aired real speech and captions flowed most of the time.
But NOT clean: three captured interruptions -
 1. ~t+405 s  all three VTTs dropped to 7 B at once; public -> STARTING; recovered by t+755 s
 2. ~t+1484 s government -> STARTING with VTT 7 B; recovered by t+1655 s
 3. public off-air for 16 samples (~4 min across the window)
Recovery each time, but interruptions recur. That is the failure mode to fix.

### Evidence written beside the artifacts (per handoff rule)
`C:\CivicCastTester\soak-beta9-2h-20260921\RUNG-30M-VERDICT-HUMAN-REPORT-v1.md`
plus `rung-30m-ledger.jsonl` (116 raw samples), `rung-30m-verdict.json`, and the
independent `watch-ledger.jsonl`.

### Decision
DO NOT advance to 2 h. Fix the recurring interruption (worker restart / caption clear at
rollover and on the 10 s stall watchdog) and RE-RUN the 30-minute rung first.

This is the first time this project has produced an honest rung measurement instead of a
claim, and it correctly reports FAIL.

---

## 21. RUNG FAILURE ROOT-CAUSED: gate trips at 3 segments; ASR exceeds cadence (17:10 MT)

Correlated the three captured interruptions against the daemon log for the exact rung window
(16:36:00-17:06:30). In-window counts: worker_exited=4 (2 unique events), CTRL stall=0,
overload=6, did not land=0, STARTING=8, FALLBACK_SLATE=4, reload accepted=4.

### Cause 1 (dominant): the caption backlog gate trips at 3 settled segments
   16:40:51  education  overload 3 > max 2  -> PAUSED 120s (overload #1)
   16:40:51  government overload 3 > max 2  -> PAUSED 120s (overload #1)
   16:42:40  public     overload 3 > max 2  -> PAUSED 120s (overload #1)
   16:43:57  government overload 3 > max 2  -> PAUSED 120s (overload #1)
   16:44:01  education  overload 3 > max 2  -> PAUSED 240s (overload #2)
   16:46:28  government overload 3 > max 2  -> PAUSED 240s (overload #2)
Every trip is at EXACTLY 3 against a max of 2. Six trips in 30 minutes, and the pause CLEARS
the active captions each time ("active captions were cleared and the stale audio was discarded") -
which is exactly the 7-byte VTT drops the rung recorder captured. This is the main cause of the
FAIL. Note it DOES escalate (#1 120s -> #2 240s), so the old "ladder never escalates" claim is
doubly wrong.

Arithmetic (from the tap's own phase timing, same window, 3 channels, 600s):
    runtime_transcribe: count=109, total=375,610 ms, max=8,500 ms  -> mean 3,446 ms
    segment cadence   : 5.0 s
    gate max backlog  : 2 settled segments
So a normal batch (3.4s) fits inside the 5s cadence, but a slow batch (up to 8.5s, i.e. 1.7x the
cadence) lets a SECOND and THIRD segment settle while the first is still transcribing. The gate
then trips at 3 - the threshold is simply too tight for the observed ASR tail.

### Cause 2 (secondary): clean worker exits while ON_AIR
   16:44:03  public     worker exited (exit_code=0, state=ON_AIR, desired=ACTIVE) -> STARTING
   17:00:01  government worker exited (exit_code=0, state=ON_AIR, desired=ACTIVE) -> STARTING
Exit code ZERO while the channel was expected to stay on air. This is the long-documented
"clean exit clears captions" defect, now with timestamps and state attached.

### Not the cause
CTRL stall = 0 in the window. did not land = 0. So Defect A's 10s stall watchdog did NOT fire
during the 30-minute rung. The rung failure is caption-gate + clean-exit, not the stall watchdog.

### What would fix it (not yet applied - needs a decision)
The gate is the binding constraint and the fix is a threshold change, which is EXACTLY the kind
of change the standing rules forbid me from making unilaterally ("never weaken a threshold or a
test to make a run pass"). Options, for the owner/coordinator to choose:
  a. raise `CIVICAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS` (env-configurable; currently 2) so the
     gate tolerates the observed 3-segment transient - an OPERATIONAL tuning change, not a test
     change, but it is still a threshold and needs explicit approval;
  b. increase the segment cadence (`CIVICAST_CAPTION_TAP_SEGMENT_SECONDS`, currently 5.0) so
     backlog accrues more slowly relative to ASR;
  c. reduce ASR tail latency (GPU/kernel/model tuning) so a batch never exceeds the cadence.
(a) and (b) are env-only and reversible; (c) is the only one that makes the system genuinely
faster rather than more tolerant.

I will NOT apply any of these without explicit direction, because all three are threshold or
performance changes and the rules are explicit.
