# CivicCast beta.8 - Blackwell captions-ON - human report v9 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v4/v5/v6/v7/v8 (each bannered). This v9 is the current reconciled
verdict and covers the WHOLE branch, not only the later load-overload work.

## VERDICT

- HANDOFF ACCEPTANCE PATH: MET, proven across three live runs (text output;
  arrival-anchored recovery correspondence; direct loaded-model GPU identity).
- NO RELEASE BLOCKER is open from the defects this branch fixes. The remaining
  item is a BOUNDED NON-REPRODUCED RISK, classified below, not a blocker.

## Candidate and evidence identity (kept strictly separate)

| Role | Commit |
|---|---|
| candidate baseline | `41ec3dda` |
| original caption fixes (live mode, wiring, PTS rebase, session reset) | `71096432` + `6c668ff5` |
| accept6 + accept8 candidate (SERVED the live runs) | `e3a47841` |
| final logging-only candidate | `ea65dffe` |
| evidence/receipt HEAD | `a8e93eed46a63a00629104f53ff1a5d4c250cd40` (docs on top of `ea65dffe`) |

CORRECTED EQUIVALENCE STATEMENT. An earlier draft claimed the final delta was
"only a log call / no control flow". That was imprecise: the added branch DOES
assign `self._logged_runtime_identity` and DOES call backend properties and
`on_cuda()`. The accurate claim is:

  * `git diff e3a47841..HEAD` touches ONE product file (+64 lines, 0 deletions).
  * It introduces NO intended change to the caption ALGORITHM: no threshold, no
    stabilizer rule, no PTS rule, no fail-closed behaviour, no scheduling change.
  * Regression evidence: the captions + daemon suites are identical at both
    commits - 494 passed at `e3a47841`, 495 at `ea65dffe` (the +1 is the new
    focused identity test). A read-only helper plus a change-only assignment/log
    cannot alter cue production, and the suite results are consistent with that.
  * LIMIT: this is regression evidence for no intended behaviour change, NOT a
    mathematical proof of equivalence. A new side-effect (one instance attribute)

alone cannot change caption output, but the claim rests on the diff scope and the
  tests, not on a formal argument.

## Failing-before / passing-after for the ORIGINAL fixes (receipt: work/RED-GREEN-RECEIPT.json)

True candidate baseline `41ec3dda` verified to LACK live mode, live-stabilizer
wiring, the PTS rebase bound and `begin_channel_session`.

  RED  (isolated worktree cc-candidate-41e @ 41ec3dda, product source UNTOUCHED,
        regressions copied in): 6 failed, 0 passed -
        test_live_confirmation_commits_reworded_continuous_speech,
        test_live_confirmation_still_resets_on_a_correction,
        test_live_confirmation_never_commits_a_lone_uncorroborated_cue,
        test_varying_live_asr_text_still_reaches_the_active_sidecar,
        test_live_caption_pts_rebases_an_absolute_program_clock_cue_to_the_live_edge,
        test_start_command_runs_the_channel_session_hook_before_encoding.
        Example: `TypeError: CaptionStabilizer.__init__() got an unexpected
        keyword argument 'live'`.
  GREEN (isolated worktree cc-fix-6c668ff5 @ 6c668ff5): 5 passed; the daemon hook
        test passes where the hook is wired.

## Full branch scope - EIGHT fixes

Original four (accept6/accept8 candidate `e3a47841`):
  1. Live cue corroboration by window overlap (CaptionStabilizer live mode).
  2. Live-tap wiring of the live stabilizer.
  3. Stale-PTS rebase onto the live edge (bounded future lead).
  4. Session-boundary sidecar reset + generation-stamped publish.

Later four (post-review defects):
  5. Retention cleanup moved off the caption-critical path (measured 4.1-5.6 s sweep).
  6. Retention verdict fail-closed (unknown/refused/failed) and atomically published.
  7. Bounded sweep shutdown; no overlapping successor sweep (measured invariant).
  8. Session-start hook fires only on a REAL launch transition (duplicate START on a
     live channel no longer runs session-scoped cleanup); session-start also discards
     the previous session's leftover settled segments.

Plus, final commit: resolved-runtime identity logging (observability only).

UNCHANGED ON PURPOSE: `max_backlog_segments=2` and the 120 s fail-closed.

## The three live runs

### accept6 - TEXT OUTPUT ONLY (temporal mapping RETRACTED)
58 decoded caption entries with real speech from the outgoing TS. Its wall<->media
mapping was RETRACTED: the claimed 10.5 s gap does not exist (entry37 ends
257.340 s, entry38 starts 258.179 s, entries continue to 283.019 s) and captions run
straight through the stop/start. accept6 proves text reaches the stream; NOT temporal
correspondence. Retained.

### accept8 - ARRIVAL-ANCHORED RECOVERY (independently verified)
On candidate `e3a47841`: receiver started 06:11:44.835 while STOPPED, START
06:12:01.018 (17 s of ZERO arrivals before enable); sustained 0->15 cues,
within-capacity, zero overloads; controlled STOP 06:15:44.563 / START 06:15:59.583;
post-recovery 0->9 cues, within-capacity, zero overloads. Recovery boundary from
ARRIVAL: a 27 s zero-arrival interval (t+211..t+237), resume t+238 (06:16:13.480) at
byte offset 26,976,308 -> byte-accurate post-recovery TS; the FIRST post-recovery cue
matches two decoded entries there by the predeclared six-consecutive-word rule.
Independently verified (contiguous offsets, sum 75,403,980 == TS size, raw SHA match,
fresh decode reproduces 26 entries with the first two matching).

### accept9 - DIRECT LOADED-MODEL GPU IDENTITY
On `ea65dffe`, supervisor PID 30616:
`... requested_device=cuda requested_compute_type=float16 loaded_device=cuda
loaded_compute_type=float16 on_cuda=True num_workers=3`.
`loaded_*` are read from the CTranslate2 backend model AFTER prepare(), so they are the
LOADED values (not the request); no CPU-fallback line exists; 12 cues were produced
during the run, so ASR executed after prepare. Change-only: 1 emission vs 86 before.
Independently corroborated.

## GPU contention (receipt: work/GPU-CONTENTION-RECEIPT.json)

Host: RTX 5070 Ti, 16303 MiB. GPU state was sampled POST-RUN (07:05): 1% util,
3892 MiB used, 47 C. This is explicitly NOT a during-validation measurement.

External GPU workloads (Fortnite/Epic) were observed EARLIER in the task; their
presence then cannot establish contention during accept8/accept9, and NO
contemporaneous external-process or GPU-contention observation was recorded for
those runs. That limitation is stated rather than glossed. No GPU workload was
terminated at any point to make captions pass.

Per-process GPU-memory attribution was NOT available (nvidia-smi insufficient
permissions). GPU-EXECUTION evidence is therefore the loaded-model line
(work/accept9-gpu/final-resolved-runtime-identity.json) supported by the live
cue sidecar snapshot taken post-prepare (work/accept9-gpu/post-prepare-cue-support/).

## Stale-state before/after recovery (receipt: work/STALE-STATE-RECEIPT.json)

Before: channel STOPPED, ZERO arrivals until START, cue count 0. After: cue count 0
immediately post-recovery (session reset blanked the sidecar) then 0 -> 9, with the
preserved FIRST post-recovery cue matching decoded output - so no pre-recovery cue
persisted. Unit level: test_stale_session_publish_cannot_restore_the_previous_broadcast
and test_new_session_discards_leftover_segments_instead_of_overloading, both with
recorded RED/GREEN.

## Start-up overload - classification

Evidence: THREE pre-fix restarts each logged an overload 13-14 s after the tap started
(03:57:09/5 seg, 04:22:15/4 seg, 04:41:49/3 seg); TWO post-fix restarts did not
(04:53, 05:09), the latter running a clean acceptance. Mechanism consistent with both:
the overload required >2 SETTLED segments present in the tap's first ~13 s, and the
session-start discard removes a channel's pre-existing segments.
CLASSIFICATION: BOUNDED, NON-REPRODUCED RISK - not an open release blocker. It was
reproducible pre-fix, is not reproducible post-fix, and no defect remains identified
that would make it recur. It is NOT claimed fixed with certainty.

## Evidence (repository-relative; binary TS on local disk per CONTRIBUTING.md)

- work/RED-GREEN-RECEIPT.json, work/GPU-CONTENTION-RECEIPT.json,
  work/STALE-STATE-RECEIPT.json
- work/accept8-20260917/PREDECLARED-CRITERIA.json, validation-result.json,
  run-timeline.jsonl, VTT-first-post-recovery.vtt, VTT-latest.vtt
- work/instrumented-harness/v2/accept8/: capture.ts (75403980 bytes sha256
  efc46c462ff77e5e9383129c718ed8e32786fd58d967b4a09ec9f619250e7c8a), arrival-index.jsonl, post-recovery.ts, post-recovery.srt,
  first-cue-correspondence.json, run-meta.json
- work/accept9-gpu/final-resolved-runtime-identity.json
- work/instrumented-harness/v2/receiver.py (receive-path harness)
- work/CURRENT-REPORTS.txt (index)

## Cleanup and gates

ruff check clean; ruff format clean; `git diff --check 41ec3dda..HEAD` clean; all
changed modules hash-match the installed runtime; operator-console tokens restored to
19; no token scratch; no dot-temp; supervisor Running; /api/health 200.
No PR, merge, tag, publish, or CI change. No threshold relaxation, no CPU substitution,
no unrelated GPU workload terminated, no synthetic cue injection.
