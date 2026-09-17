# CivicCast beta.8 - Blackwell captions-ON - human report v9 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v4/v5/v6/v7/v8 (each retained with a SUPERSEDED banner). This v9 is the
current reconciled verdict.

## VERDICT

- HANDOFF ACCEPTANCE PATH: MET.  Proven across three runs (TEXT OUTPUT, then
  ARRIVAL-ANCHORED RECOVERY CORRESPONDENCE, then LOADED-MODEL GPU IDENTITY).
- RELEASE READINESS: NOT CLAIMED.  The validated window is ~7.5 minutes; long-run
  stability and the earlier start-up overloads are outside what these runs prove.

## Candidate and evidence identity (kept strictly separate)

| Role | Commit | Notes |
|---|---|---|
| accept6 + accept8 candidate | `e3a47841` | the code that SERVED both live runs |
| final logging-only candidate | `ea65dffe` | adds resolved-identity logging |
| evidence/receipt HEAD | `8061cdbfa053bbf0f8de5435467da809a3ef8cff` | docs only on top of `ea65dffe` |

BEHAVIOURAL EQUIVALENCE (substantiated, not asserted): `git diff e3a47841..8061cdbfa053bbf0f8de5435467da809a3ef8cff` touches
ONE product file, `civiccast/captions/tap_worker.py`, with **+64 lines and 0 deletions**.
Every executed addition is either a pure read-only helper
(`_resolved_runtime_identity`) or the body of `if identity != self._logged_runtime_identity:`
whose body is a single `_LOG.info(...)`. No control flow, threshold, or caption
behaviour is modified.  Evidence: identical suites at both commits -
`e3a47841` = 494 passed / 1 skipped; `ea65dffe` = 495 passed / 1 skipped (the extra
test is the new focused identity test).

Therefore accept8's live run on `e3a47841` is representative of the final caption
behaviour; accept8 is NOT relabelled as final-candidate execution.

## What was fixed (all on-branch, DCO-signed)

1. Retention cleanup removed from the caption-critical path (measured 4.1-5.6s sweep).
2. Retention verdict is fail-closed (unknown/refused/failed) and atomically published.
3. Bounded sweep shutdown; no overlapping successor sweep (measured invariant).
4. Session-start discard of the previous session's leftover segments.
5. Session-start hook fires only on a REAL launch transition (duplicate START on a
   live channel no longer runs session-scoped cleanup).
6. (final commit) resolved-runtime identity logging - observability only.

UNCHANGED ON PURPOSE: `max_backlog_segments=2` and the 120s fail-closed.

## The three live runs

### accept6 - TEXT OUTPUT ONLY (temporal mapping RETRACTED)
58 decoded caption entries with real speech from the outgoing TS.  Its wall<->media
mapping was retracted: the claimed 10.5s gap does NOT exist (entry37 ends 257.340s,
entry38 starts 258.179s, entries continue to 283.019s), and captions run straight
through the stop/start.  accept6 proves text reaches the stream; it does NOT prove
temporal correspondence.  Retained, not discarded.

### accept8 - ARRIVAL-ANCHORED RECOVERY CORRESPONDENCE (independently verified)
Run on candidate `e3a47841`.
- receiver started 06:11:44.835 while the channel was STOPPED; START 06:12:01.018
  -> 17s of ZERO datagram arrivals before enable (capture-before-enable)
- sustained 06:12:17..06:15:27: cues 0->15, within-capacity, zero overloads
- controlled STOP 06:15:44.563 / START 06:15:59.583
- post-recovery 06:16:15..06:18:22: cues 0->9, within-capacity, zero overloads
- RECOVERY BOUNDARY FROM ARRIVAL: a 27s zero-arrival interval (t+211..t+237) then
  resume at t+238 (06:16:13.480) at byte offset 26,976,308
- that offset yields a byte-accurate post-recovery TS; the FIRST post-recovery cue
  was preserved and its text MATCHES two decoded entries in that slice by the
  predeclared six-consecutive-word rule
- INDEPENDENTLY VERIFIED: arrival offsets contiguous, sum 75,403,980 == TS size,
  raw SHA matches receipt, gap 06:15:45.440040 -> 06:16:13.480381, resume offset
  26,976,308, post-recovery.ts equals raw bytes from that offset, fresh decode
  reproduces 26 entries with the first two matching.

### accept9 - LOADED-MODEL GPU IDENTITY (direct backend evidence)
Captured from the live worker on final candidate `ea65dffe`, supervisor PID 30616
(created 06:46:50), staged module hashes matching:

```
Caption runtime resolved after prepare: requested_device=cuda
requested_compute_type=float16 loaded_device=cuda loaded_compute_type=float16
on_cuda=True num_workers=3
```

`loaded_device`/`loaded_compute_type` are read from the CTranslate2 backend model
AFTER prepare(), so they are the LOADED values (not the request) and hold even for
an `auto` request.  No CPU-fallback line exists.  Live `active.vtt` held 12 cues
during the run, so ASR executed after prepare.  Change-only logging: exactly 1
emission in that process (the earlier build emitted 86).  Independently
corroborated by the reviewer.

## Outstanding issues (honest)

- Long-run stability beyond ~7.5 minutes is NOT established.
- The earlier recurring start-up overloads (13-14s after tap start, three pre-fix
  restarts) are NOT explained; post-fix restarts did not reproduce them.
  Attribution stays PROVISIONAL.
- compute_type float16 is from the backend model line; there is no separate
  per-process nvidia-smi attribution on this host.
- accept6's temporal mapping remains retracted; only its text-output result stands.

## Evidence (repository-relative; binary TS on local disk per CONTRIBUTING.md)

- work/accept8-20260917/PREDECLARED-CRITERIA.json, validation-result.json,
  run-timeline.jsonl, VTT-first-post-recovery.vtt, VTT-latest.vtt
- work/instrumented-harness/v2/accept8/: capture.ts (75403980 bytes,
  sha256 efc46c462ff77e5e9383129c718ed8e32786fd58d967b4a09ec9f619250e7c8a), arrival-index.jsonl, post-recovery.ts,
  post-recovery.srt, first-cue-correspondence.json, run-meta.json
- work/accept9-gpu/final-resolved-runtime-identity.json,
  resolved-runtime-identity.json, in-window-gpu-identity.json
- work/instrumented-harness/v2/receiver.py  (the receive-path harness)
- work/instrumented-harness/stopped-output-behaviour.json, marker-write-attempt.json

## Cleanup and gates

- ruff check clean; ruff format clean; `git diff --check 41ec3dda..HEAD` clean
- all changed modules hash-match the installed runtime
- operator-console tokens restored to 19; no token scratch; no dot-temp files
- supervisor Running, /api/health 200
- No PR, merge, tag, publish, or CI change.  No threshold relaxation, no CPU
  substitution, no unrelated GPU workload terminated, no synthetic cue injection.
