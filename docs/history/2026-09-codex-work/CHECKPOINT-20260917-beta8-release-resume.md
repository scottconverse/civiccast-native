# CHECKPOINT - CivicCast beta.8 RELEASE resume (written 2026-09-17, pre-compaction)

Resume point. Read this FIRST. Do NOT treat as acceptance or completion.

## Role and goal

You are the IMPLEMENTATION CODER (not auditor). Owner goal: a RELEASABLE
beta.8 - captions ON on this Blackwell 16 GB GPU - docs updated, then the real
release process (push/merge/tag/publish) and a soak of the EXACT public
distributable. No shortened tests, fabricated acceptance, threshold relaxation
or CPU substitution.

The authorizing handoff is:
  C:\Users\scott\Documents\Codex\2026-08-12\tes\CivicCast Beta 8 - CODER HANDOFF - v1.md
Read it in full on resume. It says the state was PAUSED by Scott and is not
permission to resume before he says so - Scott has since said to pick up where
it leaves off.

## Current checkout (verified just now)

Branch: fix/blackwell-caption-runtime
HEAD  : a1b377a2c73bbfd638fafed798d884ea48a0a4ae
Base  : 41ec3dda7f5c5cf678e815ac103fd7e99d85294f
PR    : https://github.com/scottconverse/civiccast-native/pull/231
Tree  : 6 modified tracked files + ~656 untracked (mostly my own work/ scratch)

### Modified tracked files (inherited uncommitted work - INSPECT, do not assume)
  civiccast/captions/tap_worker.py                      sha256 99c58f1e3edfd8e2e59ec519e910f45cad7b180cc1c3b81f979181a26347ab67
  CHANGELOG.md                                          sha256 c1aa610699380c21b531a19a264858d5da01f50dadc999fe87bbd9cb1c1d7840
  HANDOFF.md                                            sha256 4874ce06897e992c957488d5b0a16dfc7d284c4b4ed2a1555f0372a4d0124945
  docs/ops/background-workers.md                        sha256 bc3c66387d15d1aab9bcb4cd9deeccbe61b8cf2aa21f805f02a66ea7b72b61e2
  docs/releases/v1.0.0-beta.8-verification.md           sha256 1baff40db6b3e9a4d93ea9a32ca79608c9d293892abd26e518d9c8581c4ba5a1
  work/release-beta8-startup-investigation/Startup Overload Investigation - Human Report v1.md

### Key untracked file
  tests/captions/test_startup_diagnostics.py            sha256 8a7d8d5a650cec5fc520b59edb21fb3f8ef8171df756eb5dfd2714e6a1499c5e

BOTH hashes match the handoff exactly -> the inherited work is UNMODIFIED since
the handoff was written.

## What the inherited diagnostic is (and is NOT)

Opt-in startup diagnostic logging in civiccast/captions/tap_worker.py.
  switch: CIVICCAST_CAPTION_STARTUP_DIAGNOSTICS=1, DEFAULT OFF
  logs initial retention, reset (incl. zero discards), preparation, backlog and
  batch boundaries, monotonic timestamps + PID/thread/session metadata
  bounds: 300 s from worker construction, 512 attempted records, first 16 indices
  metadata only; no speech/audio/paths/credentials/exception messages
  no new locks; no intentional policy change
  LIMITS: logging can perturb timing incl. within existing locks; caps/handler
  failures may lose phase ENDS (missing end != stall proof); default-off call/
  context overhead still exists.
  -> DO NOT CALL THIS AN OVERLOAD FIX.

FINAL INDEPENDENT SOURCE REVIEW WAS INTERRUPTED. No approval established.

Also present: work/release-beta8-startup-investigation/watch_tap_metadata.py +
test (watcher, independently approved for trusted-path DIAGNOSTIC use; 10 fixtures
+ real Windows junction negative test passed; NOT yet run against the live
station). Committed test_startup_probe.py = SYNTHETIC scheduling probes, NOT
installed reproduction or historical causal proof.

## Startup overload - what is actually established

- Automation and caption tap start on INDEPENDENT THREADS.
- A genuine channel Start resets the caption session and discards old numbered
  chunks BEFORE its new encoder starts; fresh chunks can then arrive while the
  tap is busy.
- Initial retention verification is SYNCHRONOUS per worker lifetime; later
  sweeps are ASYNC. Failed initial verification retries as initial.
- THE BACKLOG GATE RUNS BEFORE MODEL PREPARATION, so cold preparation can cause
  the NEXT scan's backlog, not the gate already passed.
- Three old pauses occurred 13-14 s after TAP-THREAD startup. That is NOT
  measured retention time and NOT measured time since fresh writer start.
- A 4-5 s sweep ALONE CANNOT explain three new complete 5 s chunks from an EMPTY
  directory. Historical atomic-file mode is NOT established.

=> Causation is UNPROVEN. Do not declare an explanation.

### Recommended next diagnostic (subject to engineering judgment)
One controlled COLD startup using UNCHANGED operational settings and existing
GPU workloads, preserving phase timings + fresh file inventory, to distinguish:
  (a) actual retention delay, (b) cold preparation / first batch,
  (c) inherited chunks.
If it does not reproduce, SAY SO; do not declare historical causation. A
practical fix must be measurement-supported and verified at the installed/output
layer.

## Bannered / superseded - do not resurrect

- my v9 "no release blocker" verdict is BANNERED HISTORICAL.
- accept6 (text only), accept8 (arrival-anchored recovery), accept9 (loaded GPU
  identity) are SEPARATE SHORT RUNS ON OLDER BYTES. Do not combine them into one
  in-window proof, and do not call them long-run reliability or final-installer
  acceptance.
- Release review already found and repaired REAL issues through d89e7e93
  (atomic session reset/publication/file movement, bounded PTS lead after
  restart, FAILED-RESET CAPTION INHIBITION, retention permission at the point of
  persistence, ACTUAL TIMED-WORD CORROBORATION, proportional CEA page timing).
  Default overlap is now FIVE seconds; explicit overrides and two-window
  confirmation intact.
- Backlog limit 2 and the 120 s pause policy were NOT relaxed - keep it that way.

## CI status (LAST OBSERVATION ONLY - re-verify, do not trust)

For a1b377a2: unit 35259698510; deterministic 35259698487; lint 35259698442;
docs 35259698741; accessibility 35259698589; Windows reproducibility 35259698499.
At ~12:50 MDT unit/randomized/mutation/reproducibility were STILL RUNNING;
shorter checks had passed. Retrieve ACTUAL results on resume.

## Boundaries / prohibitions

- Do NOT blanket-add, reset or stash work/. Preserve unrelated untracked
  historical work.
- Do NOT replay work/air7.py or work/air_gpu.py (they cancel schedules and create
  replacement programming).
- The old instrumented harness INJECTED SYNTHETIC VTT -> not product acceptance.
- Do NOT expose, guess or reset credentials.
- Coordinate before changing shared files.
- No oversized hosted artifact workaround, no new spending.

## External prerequisites - were UNRESOLVED at handoff

- HALO-gate-a: OFFLINE at last check; Scott was asked to bring it online.
- Staff API: 401, NO usable shell token. Browser tool init FAILED. Scott was
  asked for the staff-token file path OR explicit temporary-token authorization;
  unanswered.
- No service/runtime/config/schedule/GPU-workload change had been made.

## Release finish line (after actual repair + green applicable PR checks)

1. Merge; build and sign EXACT release source via the existing candidate workflow.
2. Gate A clean-install, cross-version and download-only for THAT SAME source.
3. Verify beta.7 upgrade baseline (checked-in baseline was beta.5).
4. scripts/release/publish_beta_candidate.py DRY-RUN first, then guarded
   publication. Do not manually move or fabricate tags/receipts.
5. Verify public assets, hashes, signatures, release truth and deployed docs.
6. Soak the EXACT PUBLIC DISTRIBUTABLE with captions ON, GPU, all intended
   channels. Proposed soak = 24 HOURS unless Scott changes it BEFORE start; do not
   shorten after failures. Preserve VTT BEFORE clearing, real TS decode/cue
   correspondence, arrival times, loaded GPU identity, contention,
   backlog/overload/stale/recovery, and EVERY failure.

Every milestone needs an honest, versioned PLAIN-ENGLISH report beside its
evidence, with MOUNTAIN TIME for Scott. A green source suite or merged PR is NOT
the finish line.

## First actions on resume

1. Re-verify checkout HEAD, PR state and ACTUAL CI results (do not trust the
   numbers above).
2. Inspect the inherited uncommitted diagnostic work; decide retain/simplify/
   remove, preserving an identifiable copy first. It has NO independent approval.
3. Run the bounded controlled cold-startup diagnostic (unchanged settings,
   phase timings + fresh-file inventory); report honestly if it does not
   reproduce.
4. Surface the credential/HALO blockers rather than improvising around them.

Prepared at 2026-09-17T13:45:24.936752 (America/Denver).
