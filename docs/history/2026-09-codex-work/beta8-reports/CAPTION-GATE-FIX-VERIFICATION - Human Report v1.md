# CivicCast beta.9 caption-gate fix: verification report (v1)
## Mountain Time, 2026-09-19

## The fix
Commit 43faca1e on branch fix/caption-phase-timing:
"fix(captions): take the first retention sweep off the scan thread's path"

## The defect it fixes
The FIRST retention verification ran SYNCHRONOUSLY on the caption scan thread
"by design", on the documented rationale that it happens at session start
"before this session has live captions to lose". Measured live with the opt-in
phase timing (commit e8631746): that first sweep runs at WORKER CONSTRUCTION
against an existing 13,550-candidate archive and took 16,750 ms in ONE call --
more than three times the 5 s segment cadence. So 3+ settled segments
accumulated before the first scan reached the max-2 backlog gate, and the gate
tripped at construction.

Phase breakdown of that one sweep (verbatim, pid 45776):
    retention_dispatch             count 2, total 16,750.0 ms, max 16,750.0 ms
    retention_sweep_work           count 1, total 16,750.0 ms, max 16,750.0 ms
    scan_settle_and_backlog_gate   count 6, total      0.0 ms, max      0.0 ms
    wait_session_lock              count 6, total      0.0 ms, max      0.0 ms
=> WORK, not lock WAITING. And retention_dispatch == retention_sweep_work means
the dispatch call did not return until the sweep finished.
Cost inside the call: an N+1 database pattern (retention.py:248-249 --
review_store.list() then a fresh session + row lookup PER ROW via
persistence.py:214). Superlinear: 8,105 candidates -> 4.1-5.6 s,
13,550 candidates -> 16.75 s. File hashing is NOT the cost (1.01+0.19 s).

## The fix
First sweep now runs on the same daemon thread every later sweep already uses,
and the scan waits at most _RETENTION_FIRST_VERDICT_WAIT_SECONDS = 1.0 s
(chosen because it is far below the 5 s segment cadence). If the verdict is not
in, the scan proceeds in the EXISTING PENDING state, which already fails closed
(_retention_ready stays False, refusal stays retention-verification-pending), so
no ASR runs into an unverified store and no WAV is retained; the verdict is
applied when the thread publishes it. The 120 s base pause, the 120/240/480/900
backoff ladder, the max-2 threshold, the retention policy and the gate are ALL
unchanged.

## RED/GREEN (real behavioural failures, not API errors)
RED on pre-fix code:
  test_first_sweep_does_not_block_the_scan_thread -- dispatch blocked for the
    whole 3 s sweep.
  test_slow_first_sweep_still_fails_closed_until_the_verdict_lands -- old code
    blocked until verified, so _retention_ready was already True and the pending
    state never existed.
GREEN: both pass; test_caption_tap_worker.py 70 passed.
Regression: phase_timing + tap_worker + tap_backoff + retention = 123 passed,
1 xfailed (the pending backoff-contract reconciliation from b7a7c869).
ruff check/format clean, mypy clean.

## Reconciliation (not overwrite)
Checked whether any pre-existing test asserts the first sweep must be
SYNCHRONOUS. NONE does. The two fail-closed tests assert only the CONSEQUENCE
(refusal/failure => not ready, nothing consumed), and
test_initial_retention_refusal_blocks_asr_before_any_verdict's own docstring
already anticipates async sweeps. test_retention_cleanup_latency_does_not_cause_a_false_overload
asserts "slow.calls == 1" -- retention VERIFIED BEFORE ASR, an ORDERING
guarantee still satisfied by the bounded wait. All three pass unchanged. Only
docstring prose said "synchronous".

## LIVE VERIFICATION -- on the real installed service, not a harness
The fix was staged into the installed runtime (tap_worker.py + phase_timing.py,
hashes verified) and CivicCastSupervisor was restarted. All three channels
brought ON_AIR with real program.

Result since the restart:
    gate trips:              0
    bounded-wait notice:     1  (fired exactly as designed)
    retention failures:      0
    captions:                public 4,715 / government 4,869 / education 4,912 bytes
                             at 02:33:54 MT -- all three carrying cue text
Compare pre-fix: 111 gate trips in 103 minutes, and all three active.vtt at
7 bytes (bare WEBVTT) with a ~6-minute simultaneous three-channel blackout.

## What is NOT proven
- This is a ~15-minute post-restart observation, NOT the 2/4/8/25/72-hour rungs.
  Scott's ladder requires 30 min on three channels before climbing; this window
  has not yet reached 30 minutes.
- The N+1 evidence lookup is UNFIXED and logged as a separate backlog item. It
  makes the sweep faster but does not remove the block, so it is not the gate fix.
- The backoff-contract xfail from b7a7c869 is still UNRESOLVED (marked xfail,
  not rewritten).
- Installed-service provenance: the fix is staged and the service was restarted,
  so the loaded process matches the committed fix, but this is a staged
  development install, not a signed release candidate.

## Boundary notes carried forward
- The in-process phase timing that DIAGNOSED this ran the same code path, same
  cuda/float16 resolution, same scan loop, gate and retention policy, but under
  a DIFFERENT parent process than the supervised service.
- A non-elevated process cannot write the service-owned egress sidecars
  (WinError 5), which is why the diagnostic run used a scratch sidecar dir.
- Enabling the opt-in switch on the supervised service still needs the switch
  forwarded into the child env: a one-line product change or a human elevation
  click. The fix in this report does NOT depend on that.

## Evidence files (this directory)
phase-run-N3d.log, phase-summary-N3d.jsonl (the diagnostic phase breakdown)
n3e-log-offset.txt (the live-verification log window)
metrics-N1/N2/N3/N3b.csv, latency-N1/N2/N3b.csv, gate-trips-*.jsonl,
rung-comparison.json (the capacity-vs-gate ladder)
CAPTION-GATE-LADDER-COMPARISON - Human Report v1.md
