# Slice A - egress engine audit (civiccast/egress/, tests/egress/)

Repo: civiccast-release @ release/beta10, HEAD 657d8438. Read-only. Tests were run one at a time at BelowNormal.
Whole `tests/egress` run: 74 failed in total (60 in the first pass that stopped at `--maxfail=60` after test_hls_sink_captions, 14 more in the remaining 43 files). The "10 known failures" figure is wrong; see A-003.

### A-001 Major: Reload-stall watchdog never reaches its restart rung when the re-issue declines through the async preparation path
**Dimension:** Correctness
**Evidence:** daemon.py:6099-6105 (`if self.has_pending_reload_settlement(channel_id): ... self._reload_stall_rungs.pop(channel_id, None)`) and daemon.py:1360 (`self._fall_back_to_restart_reload(channel_id)` in `_poll_preparation`, which calls `_arm_pending_reload` at 6220 and resets since/bound/rung at 6054-6056). Automation enables async preparation in production (automation.py:1179). test_u67_reload_stall_recovery.py has no async case.
**Why it matters:** Rung 0 re-issues the reload. In async mode that queues a preparation, so the watchdog stands down every tick and pops the rung. If the arm then declines, `_arm_pending_reload` restarts the clock from zero. The channel re-issues about every 1650 s plus preparation time and never gets the rung-2 terminate. The synchronous no-plan decline (the 2026-09-30 incident shape) does escalate correctly. Any second decline that happens after a plan is prepared recreates the 34 h wedge.
**Fix path:** Keep the stall episode identity separate from the pin. Carry the rung and the episode start through `_arm_pending_reload` when the pin is re-armed by the watchdog's own re-issue, for example a `_reload_stall_episode_since` that only the watchdog clears. Do not pop the rung while a preparation is pending. Add an async-mode test: enable_async_preparation, a reload_content that returns False, and assert the worker is terminated after the grace.
**Blast radius:** n/a (Major)

### A-002 Major: The U62 round-2 fix (bound the fallback's mux-tail fence) is absent from HEAD, but its tests are in the tree and fail
**Dimension:** Correctness
**Evidence:** `git show ce71c40a -- civiccast/egress/gst/engine.py` deletes the 30-line `else:` branch ("U62 round 2: a leg with no measured end still has a bound") after engine.py:7168 `pending.setdefault("mux_tail_target", {})[pad_name] = int(seed["end"])`. test_gst_engine_reload_commit_ordering.py::test_u62b_the_fallback_fence_targets_the_switch_point and ::test_u62b_the_fallback_fence_holds_instead_of_releasing_at_the_mutation fail at HEAD (`pending.get('mux_tail_target')` is None). The same two tests pass when the tree is rebuilt at 66ebd435 (git archive to scratch, run).
**Why it matters:** The commit message of 66ebd435 describes a live-measured defect (C13: `mux-tail-armed ... target=None`, so the fence disarms at the first selector mutation on a slate-to-program fallback). HEAD ships the engine bytes that still have it. The reset to the station's installed bytes may be intentional, but nothing in the tree says so.
**Fix path:** Owner decision, recorded in the repo. Either re-apply the 30 lines from 66ebd435 and ship them, or mark the two tests xfail/skip with a reason pointing at the decision, and list the defect as a known beta.10 limitation.
**Blast radius:** n/a (Major)

### A-003 Major: tests/egress is red with 74 failures, not 10; 64 are undocumented and the engine reload-commit suite is dark
**Dimension:** Tests
**Evidence:** Full runs of tests/egress. By cause:
- test_gst_engine_reload_commit_ordering x13 (11 already fail at 66ebd435, the commit that last edited the file: fakes lack `get_clock` / `teardown_timeout_s`, `pending["probe_id"]` KeyError at engine.py:6914, diagnostic text drift; 2 are A-002).
- test_gst_worker_{preroll,first_output}_timeout_exit x9 (fake `run_forever()` lacks the `hold_slate_at_plan_eos` kwarg that worker.py:750 passes).
- test_automation x9 (U53 adaptive-lead probe samples the boundary provider before the trigger, test_automation.py:208 `assert sampled == []`; U41 `min_plan_seconds` kwarg makes a stub `record_rollover_plan_end` raise TypeError, so the pass fails at 2599/2674).
- test_automation_plan_warm_lookahead x5 (U63 defect B warms the first collapsed boundary; tests expect item-5, get item-3).
- U51 mux-playlist/spawn-wipe family x15: test_contracts x2, test_sinks_windows_paths x1, test_hls_sink_captions x2, test_hls_sink_live_playability x1, test_hls_relay_progress x4, test_hls_relay_video_lock x4, test_daemon_output_av_guard x1. (The 2 test_daemon HLS tests are in the known 10; see A-007.)
- test_loudness_ride_guard x4 (tests the removed answer-11 API `TP_GUARD_MAX_ROUNDS`, `guard_ceiling_dbtp`, `guard_next_ceiling`), test_loudness_ride_window x6 (fake `reencode()` lacks `variant`, loudness_ride.py:2507).
- test_gst_graph x3 (U56 removed `videorate`; tests index `specs[4]`).
- plus the 10 known, see the verdict table at the end.
**Why it matters:** A red suite cannot be a release gate, and new real regressions hide among 74 known-bad. The highest-risk code (engine reload commit, rollover lead and warm look-ahead, ride guard) has the most failing tests.
**Fix path:** One pass per cause family above. Each is a mechanical test update to the current contract; none needs a product decision except A-002. Then make the suite green and gate on it.
**Blast radius:** n/a (Major)

### A-004 Major: The speech-leveling ride's timeout and cancel cannot fire while the decoder read blocks
**Dimension:** Runtime
**Evidence:** loudness_ride.py:1303-1310: the `cancel_event` and `timeout_s` checks sit at the top of the loop, then `raw = decoder.stdout.read(bytes_per_chunk)` blocks with no way to wake it. `sink.stdin.write(payload)` has the same shape.
**Why it matters:** A decoder that stalls without exiting (an input on a stalled share or sync folder) keeps the preparation thread, the daemon's per-channel `_preparation_channel_locks` entry and one of 8 executor slots busy. `_cancel_preparation` only sets an Event. `shutdown_preparation` calls `executor.shutdown(wait=True)` (daemon.py:1238-1239), so service stop can hang behind it.
**Fix path:** Read from a helper thread or reader pipe and poll with a short deadline, or run a watchdog thread that kills `decoder` and `sink` when `cancel_event` is set or `timeout_s` elapses. Add a test with a decoder double that never writes.
**Blast radius:** n/a (Major)

### A-005 Minor: The preparation loudness probe is not bound by the preparation timeout
**Dimension:** Runtime
**Evidence:** stream/loudness.py:134-137 calls `run_ffmpeg(args, cancel_event=...)` with no `timeout`, so `_DEFAULT_TIMEOUT_SECONDS = 6 * 3600` (stream/_ffmpeg.py:494). `SourcePreparer._check_loudness` (preparer.py:2467-2478) passes no timeout. preparer.py:327-329 and the automation lead docstring (U05 note) both assume every preparation ffmpeg call is bounded by 300 s.
**Why it matters:** The rollover lead (690 s) and the fail-closed air-path claim hold only if the probe is short. It usually is (120 s window), but a wedged probe costs hours, not minutes.
**Fix path:** Thread `timeout=self._preparation_timeout_seconds` through `check_streaming_loudness`/`check_loudness` and map `TimeoutExpired` to `SourcePrepareError` as `_run_ffmpeg` does.
**Blast radius:** n/a (Minor)

### A-006 Minor: The async decline path drops the rollover horizon, so the stall bound is never stretched
**Dimension:** Correctness
**Evidence:** daemon.py:1360 calls `_fall_back_to_restart_reload(channel_id)` with no `plan_end_at`; the sync and settlement paths pass it (daemon.py:5684, 5964-6006). `_reload_stall_bound_seconds` (daemon.py:6860) then returns the flat 1650 s.
**Why it matters:** The watchdog docstring promises "a declined reload against a long plan is never judged early". With 1650 s plus the 300 s grace, a healthy channel with more than about 1950 s of plan left would be terminated mid-programme. The station's 1800 s slices stay under that; a larger `max_segment_seconds` would not.
**Fix path:** Store `rollover_plan_end_at` on `_PendingPreparation` when the steps are queued and pass it at 1360.
**Blast radius:** n/a (Minor)

### A-007 Minor: HLS comments and two daemon tests still describe a carried-forward manifest that U51 removed
**Dimension:** Docs
**Evidence:** daemon.py:2121 and 2228 ("the manifest survives an encoder crash-relaunch") and daemon.py:1963 ("Segments are left for the next writer's own rolling window"), against hls_relay.py:363-411 `_clear_hls_window`, run at every relay spawn (hls_relay.py:1514), including `apply(new_session=True)` on every crash relaunch. test_daemon.py:931 and :1051 fail on exactly this (playlist gone after relaunch); test_daemon_output_av_guard.py:556 fails because the fixture's playlist is wiped at relay start, so the guard finds no segment.
**Why it matters:** The `hls_relay_was_alive` branch in `_start` is now behaviourally redundant, and the comments contradict the code. If "residents keep a manifest across a relaunch" is still a requirement, the code violates it; if U51 superseded it, the comments and tests are stale.
**Fix path:** Decide, then either remove the carry-forward comments and branch and update the two tests, or make `_clear_hls_window` skip a session rebind.
**Blast radius:** n/a (Minor)

### A-008 Minor: 60 GB conform-cache default, no free-space guard
**Dimension:** Runtime
**Evidence:** preparer.py:91 `_DEFAULT_CACHE_GB = 60.0`; no `disk_usage`/`free` check anywhere under civiccast/egress/*.py (grep). Docs only say "leave room" (docs/ops/channel-egress-runbook.md:243, INSTALL-WINDOWS.md:131). ops/beta10-oversight/reports/U20.md:499 records 128 GB free on C: for the station.
**Why it matters:** 60 GB of cache plus prepared plan directories (5 GB per channel) plus HLS on a small data drive fills the disk, and a full disk stops every channel.
**Fix path:** Clamp the budget to a fraction of free space at eviction time, and log when clamped.
**Blast radius:** n/a (Minor)

### A-009 Minor: SQL `pop_pending_commands` is read-then-update, not an atomic claim
**Dimension:** Correctness
**Evidence:** store.py:436-458: SELECT of unconsumed rows, then `UPDATE ... WHERE command_id IN (ids)` with no `consumed_at IS NULL` condition and no rowcount check.
**Why it matters:** Two consumers (an old service process that outlives a restart, or a second daemon) can both read the same rows and both execute them. Stop/reload would run twice.
**Fix path:** `UPDATE ... WHERE consumed_at IS NULL AND command_id IN (...)` and return only the rows actually claimed (RETURNING, or compare rowcount).
**Blast radius:** n/a (Minor)

### A-010 Nit: A watchdog restart is logged as an honored pending reload and counted as an encoder crash
**Dimension:** Runtime
**Evidence:** daemon.py:6172 pops the pin before `_note_deliberate_kill` (6178), so `_poll_process` logs "that non-zero exit was a deliberate kill ... the pending reload is honored" (3903) while `pending_reload` is None, then takes `_relaunch_after_crash`, which appends an encoder-child-failure event and advances the crash streak.
**Why it matters:** The log line is false, and repeated watchdog restarts can feed the crash-loop escalation.
**Fix path:** Reword the deliberate-kill message when no pin exists, or pass a distinct reason code.
**Blast radius:** n/a (Nit)

### A-011 Nit: The ride's stderr temp file leaks on an unexpected exception
**Dimension:** Runtime
**Evidence:** loudness_ride.py:1285-1352: `err_path.unlink` runs only after `decoder.wait()` on the normal path; an exception other than `BrokenPipeError` (for example a numpy error) leaves `civiccast-ride-*.log` in the temp dir.
**Why it matters:** Small, but it accumulates, and 2.5 h assets write about 10 MB of ebur128 lines.
**Fix path:** Move the unlink into a `finally` that wraps the whole function.
**Blast radius:** n/a (Nit)

## Verdict on the 10 known failing tests

| Test | Verdict | Basis |
|---|---|---|
| test_preparer::test_evict_cache_over_budget_reaps_orphaned_tmp_and_meta | STALE TEST | `_ORPHAN_CACHE_TMP_MAX_AGE_S` was renamed `_ORPHAN_CACHE_SCRATCH_MAX_AGE_S` (preparer.py:154); test at 2397 uses the old name. The rest of its logic matches the code. |
| test_preparer::test_evict_cache_over_budget_counts_live_tmp_bytes_toward_budget | STALE TEST | Uses `aaaa.ts` and `bbbb.ts.tmp`; U53 classifies by `^[0-9a-f]{32}\.ts$` (preparer.py:2179), so `aaaa.ts` counts as scratch and is never evicted. Needs a 32-hex key. |
| test_daemon::test_start_leaves_the_playlist_alone_while_the_hls_relay_is_still_alive | STALE TEST (code comments also stale, A-007) | U51 wipes the window at every relay spawn. |
| test_daemon::test_crash_relaunch_rebinds_the_channels_hls_relay_to_the_new_worker_session | STALE TEST (same) | Same cause. Its relay-rebind assertions pass; only the playlist-exists line fails. |
| test_daemon::test_stop_clears_the_recorded_rollover_plan_end | STALE TEST | `_rollover_plan_end_at` tuple grew a 4th field (`min_plan_seconds`, U41; daemon.py:1063). Test compares a 3-tuple. |
| test_daemon::test_drain_with_no_live_process_clears_the_recorded_rollover_plan_end | STALE TEST | Same tuple shape. |
| test_daemon::test_unscoped_record_never_matches_a_real_queued_reload_and_needs_an_off_air_pop | STALE TEST | Same tuple shape. |
| test_daemon::test_command_id_scoping_closes_the_immediate_crash_relaunch_leak | STALE TEST | Same tuple shape. |
| test_daemon::test_retry_collision_a_stalled_retry_that_overwrites_the_recorded_value_still_cuts | STALE TEST | Same tuple shape. |
| test_daemon::test_held_prepared_restart_plan_is_released_when_the_exit_takes_no_pending_reload | STALE TEST | Plan release assertions pass. The final `started_labels == []` fails because U47 slate-first now relaunches onto "Fallback slate" and hands the program in (daemon.py:4857 log). |

None of the 10 shows wrong code. The wrong-code failures are the two U62b tests in A-002, outside the known 10.

## What's working
- Preparer cache eviction is correct against its own spec: name-based classification (preparer.py:150-170, 2171-2186), scratch liveness window, 24 h orphan-meta sweep, oldest-first with a Windows-safe unlink (an OSError leaves the entry and continues, 2208-2214).
- U67 re-resolve past plan end (daemon.py `_try_content_reload`, boundary + 1 s) mirrors automation's `_resolve_rollover_tail` (automation.py:1827) and is strictly a recovery; it logs both the success and the decline.
- U67 watchdog synchronous path: the rung-restoring block after the re-issue (daemon.py:6150-6153) is correct, and `test_u67_reload_stall_recovery.py` passes (run together with the engine file: 13 failed, all in the engine file, 119 passed).
- `process_once` isolates each poll and command in try/except, so one failing poll cannot take down a channel's pass (daemon.py:1444-1458).
- RLock on `_preparation_guard` is required and correct for the `_poll_preparation` -> `_request_reload` -> `_cancel_preparation` re-entry (daemon.py:838).
- hls_relay teardown order (child, then log writer, then manifest publisher) is bounded and documented (hls_relay.py:1789-1815); a FileNotFound or Windows-locked file never fails a relay start (`_clear_hls_window`).
- Rollover adaptive-lead probe is cached once per boundary and fails open (automation.py:1661-1701).

## Not checked
- gst/engine.py (8436 lines), gst/bridge.py, gst/worker.py, strategy.py beyond the commit-ordering test failures and the A-002 diff. No review of locking in the GStreamer thread model.
- hls_relay.py beyond spawn/teardown/publisher (stall heal, stream-restore probing, ts_relay, ndi/sdi relays).
- headend.py, compliance.py, continuity.py, bulletin_filler.py, caption_*.py, health.py, supervisor.py, takeover_service.py, router.py, models.py, migrations.
- The correctness of source_plan.py's join-in-progress and slot-clip time math beyond reading `build_source_plan_from_schedule`; no off-by-one found, but no property testing either.
- loudness_ride.py math (gain curve, limiter, keep-best window leveler); only its subprocess and tempfile handling.
- Whether operator takeover/forced-slate channels interact badly with the watchdog (re-issue and terminate while `has_manual_override`); the code does not consult the override but I did not trace whether a pin can exist during one.
- Real-ffmpeg and real-GStreamer tests were skipped on this host (no packaged runtime, no soxr ffmpeg), so none of those paths ran.
- The first full pass stopped at `--maxfail=60` inside test_hls_sink_captions; any tests after the 60th failure in that one file were not run (the remaining 43 files were run).
