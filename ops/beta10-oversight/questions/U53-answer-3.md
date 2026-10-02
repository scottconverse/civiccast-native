# U53 round 4 - coordinator answer to Part III (engineering call, final)

Part III audit: diagnosis accepted (yield at daemon.py:2388 makes SLATE_FIRST unreachable under async prep); RED on
installed bytes and GREEN on candidate accepted.

## Decision on III.4: option (A). The slate must be ON AIR within seconds. It is not a preparation.
The owner goal is "3 channels airing"; a dark channel is the failure. The slate-fill is an already-rendered airing
artifact, and its conform cannot change what airs (your III.2: silent_asset forces normalized=False; the 3600 vs
3601.56 s gate means it never caches). So the six pinned tests encode the defect. Rewrite them to the new contract,
KEEPING each test's behavioural intent:
1. `test_u47_a_crash_relaunch_airs_the_fallback_slate_before_the_program_is_prepared` - assert the slate WORKER is
   started before the program is prepared, and the slate is never submitted to the preparer.
2. `test_u47_a_relaunch_airs_the_slate_while_a_slow_program_preparation_is_in_flight` - slate started; program prep
   in flight; program started after it completes.
3. `test_u47_a_failed_hand_off_preparation_keeps_the_live_slate_on_air` - KEEP THE INTENT EXACTLY: a failed
   PROGRAM preparation leaves the slate worker on air (no dark). Re-key the future lookup to the program's prep.
4. `test_u53_a_restart_recovery_start_airs_the_slate_before_the_program_is_prepared` - same as 1 for recovery.
5. `test_u53_a_stale_starting_claim_also_airs_the_slate_before_the_program` - same for STARTING.
6. `test_held_prepared_restart_plan_is_released_when_the_exit_takes_no_pending_reload` - find what "held plan"
   means under the new shape; the release guarantee must still hold. If the test's premise no longer exists, say
   so with the line that removed it, and replace it with the nearest real guarantee. Do not just delete it.
Each rewrite must FAIL against the pre-fix (C2 installed) daemon for the right reason, or explain why it cannot.

## Also required in this round
7. **Crash relaunch on a real worker.** The fix changes the U47 crash-relaunch path too (tests 1-3). Extend the
   u53b real-worker proof with a crash-relaunch case: slate output within 15 s, program airs after its prep. RED
   on installed bytes is not required for this one if installed already passes it; GREEN on candidate is.
8. **Item 3 is inert on the station** (the addenda in `questions\U53-C2-dark.md` you have not read - read them):
   ```
   21:36:55,262 automation: Channel automation computed the rollover lead for education: lead=690s (no asset duration available for the boundary; the timeout-derived floor stands).
   21:48:39,605 automation: ... lead=690s (no asset duration available for the boundary; the timeout-derived floor stands).
   ```
   Every live rollover since C2 has had no asset duration. Trace why the caller passes None for real scheduled
   programmes (the schedule items do have media), fix RED-first, stage it with the daemon change.
9. `_last_loudness_lufs.pop` in the new arm: keep it only if you can show a reader that would otherwise report the
   pre-restart programme's loudness as the slate's; otherwise remove it. Say which.
10. The parked pipe-accept leak (III.7): file it in `POST-BETA10-BACKLOG.md`-style text at the end of your report
    (a short entry: symptom, lines, trigger). Do not fix it in this round.

Stage ONE combined `staging\U53b\` from LIVE bytes (C2 bases: daemon e10a5663, automation df12d148, source_plan
82dcccbf, models e7e774a6, preparer aafb0b5d). Report Part IV, receipt at the end. Targeted tests only; the 8 h rung
owns the box - real-worker runs `start /low`, each <= 10 min. Do not touch the station.
