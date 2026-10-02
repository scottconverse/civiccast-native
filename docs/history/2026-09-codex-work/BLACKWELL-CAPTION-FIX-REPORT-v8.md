> **SUPERSEDED 2026-09-17.** v8 predates the accept8 arrival-anchored recovery
> verification and the accept9 loaded-model GPU identity. See
> work/BLACKWELL-CAPTION-FIX-REPORT-v9.md (current). Retained for history.

# CivicCast beta.8 - Blackwell captions-ON - human report v8 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v4 (PASSED on non-overlapping evidence), v5 (BLOCKED + a withdrawn
BOM root cause), v6 (verdict overclaim) and v7 (over-narrow). Those are retained
with banners. This v8 is the current verdict.

## VERDICT: ACCEPTANCE MET for the validated window; release readiness NOT claimed.

Two separate claims, kept apart on purpose:

1. HANDOFF ACCEPTANCE PATH - MET for this run.  One continuous capture covered
   capture-before-enable, sustained output, a controlled interruption, and
   post-recovery output, with cue text PROVEN in the outgoing stream throughout
   (including after recovery).

2. RELEASE READINESS - NOT CLAIMED.  The window is ~7 minutes.  Long-run
   stability, and the earlier recurring start-up overloads, are outside what this
   run proves.

## The validated run (all times Mountain, 2026-09-17)

Process: commit e3a47841, staged into the installed runtime BEFORE a clean
supervisor restart (PID 28132, created 05:09:17); all seven changed modules
hash-match the commit.

  capture launched   05:10:40   channel STOPPED / on slate, no writer
  START issued       05:11:10   -> TS 28.6s  (capture preceded enable by 30s)
  startup transient  05:11:20 STARTING/paused backlog=3 ; 05:11:27 paused backlog=3
                     (NOT counted as stable operation)
  stable window      05:11:34..05:14:36  (182s)  ON_AIR, within-capacity throughout,
                                    cues 0 -> 16, backlog 1, ZERO overloads
  controlled STOP    05:14:57   -> TS 255.6s
  controlled START   05:15:12   -> TS 270.6s
  post-recovery      05:15:22..05:17:28  (126s)  cues 0 -> 13, within-capacity,
                                    backlog 1, ZERO overloads
  media ends         05:17:41   (ffprobe duration 419.958589s, size 81,564,364)
  live writer        GStreamer worker PID 14136 confirmed alive during the run

Predeclared windows were satisfied on the CLEAN stable window: 182s >= 180s
(05:11:34..05:14:36, excluding the two paused start-up samples) and 126s >= 120s
post-recovery.  Elapsed spans including the start-up transient are reported
separately and are NOT presented as stable operation.

## Verification

- 58 decoded entries from the outgoing TS; media timestamps span 00:00:14 to 06:48.
- CLOCK MAPPING derived from TWO independent content boundaries (not from launch
  +1.4s): egress STOPPED 05:14:58.276 -> media 257.3s, where the decoded entry
  'winds here then west' ends and a 10.5s gap follows; new GStreamer worker
  05:15:23.223 -> media 282.2s.  The alternative origin-at-program-start mapping is
  FALSIFIED: it would place STOPPED at media 216.0s, where there are no decoded
  entries at all.
- 14 decoded entries START at or after the PROVEN resume offset (282.2s), so caption
  text reached the stream AFTER recovery, not merely before it.
- Preserved cue-bearing VTTs: first post-recovery cue (1 cue) and latest (13 cues).
- CORRECTED MATCHING: restricting the predeclared six-consecutive-word rule to the
  PROVEN post-recovery interval (>=282.2s) yields 5 of 13 preserved cues matched.
  An earlier 13/13 figure was computed across the WHOLE TS, so a cue could match a
  PRE-recovery occurrence of the same looping passage; that figure was wrong for
  the post-recovery claim and is withdrawn.  5/13 within the interval proves caption
  TEXT reaches the output after recovery; it does NOT establish one-to-one
  correspondence for every preserved cue.
- GPU: NO contemporaneous device evidence exists for the accept6 window (the runtime
  logs device identity at tap start, and this window has no such line).  A POST-RUN
  check confirms device=cuda, compute_type=float16, on_cuda=True, ctranslate2 CUDA
  devices=1 - labelled post-run in gpu-identity-postrun.json.  Binding GPU identity
  INSIDE a run window remains outstanding for a definitive run.

## Start-up overload - disposition (engineering call, attribution provisional)

Pre-fix restarts each produced an overload 13-14s after the tap started:
  03:56:56 -> 03:57:09 (5 segments); 04:22:02 -> 04:22:15 (4); 04:41:35 -> 04:41:49 (3).
Post-fix restarts produced NONE: 04:53:09 and 05:09:32, the latter then running
the clean acceptance above.

Mechanism consistent with both: the overload required >2 SETTLED segments present
in the tap's first ~13s; the session-start cleanup removes a channel's pre-existing
segments at the genuine-transition hook, which fires on the daemon's normal start
path.  This is STRONGLY SUPPORTED, not proven - it is not a controlled A/B.
Scope was not widened to chase a failure that no longer reproduces; the preserved
startup-window log and timeline are the diagnostic inputs if it recurs.

## Earlier corrections that stand (kept for the record)

- The 'zero printable text' claim was MY parser bug (A/53 triplet offset +6 vs +7);
  the real decoder was right.
- The UTF-8 BOM 'root cause' was withdrawn: the LocalSystem service reads the
  systemprofile state file, which has no BOM and had live_captions_enabled=true.
- A first-scan / restart-without-START deletion was attempted and REJECTED: the WAV
  writer is a separate per-channel GStreamer subprocess, so file timestamps cannot
  establish ownership, and a blanket first-scan delete broke fresh-audio tests.
- The duplicate-START defect WAS real and is fixed: the session-start hook now runs
  only on a genuine launch transition, so a no-op start on a live channel cannot
  discard the live session's audio.
- 'capture end 05:18:38' was a file-mtime reading, not recorded media; media is the
  authority and ends 05:17:41.

## Scope and gates

- Changes stay within captions / new-session stale state / overload-backlog
  recovery.  max_backlog_segments=2 and the 120s fail-closed are UNCHANGED.
- No threshold relaxation, no CPU substitution, no unrelated GPU workload killed.
- No PR, merge, tag, publish, or CI change.
- Focused suites green; ruff check/format clean; committed-range git diff --check clean.
- Temporary auth restored: operator-console back to 19 entries, no token scratch.

## Evidence (repository-relative; binary TS on local disk per CONTRIBUTING.md)

- work/accept6-20260917/PREDECLARED-CRITERIA.json   criteria written BEFORE the run
- work/accept6-20260917/validation-result.json      run record, media facts, windows, verdict
- work/accept6-20260917/run-timeline.jsonl          per-phase samples (wall clock)
- work/accept6-20260917/startup-window-log.txt      log covering startup
- work/accept6-20260917/decodeback.srt              58 decoded entries (6524 bytes, sha256 df39834cff8b485b5989d037ab2cf16bc350a625abd370c61d627f2c90d58746)
- work/accept6-20260917/matching-result.json        cue-vs-decode matching outcome
- work/accept6-20260917/VTT-first-post-recovery.vtt first post-recovery cue
- work/accept6-20260917/VTT-latest-post-recovery.vtt
- work/accept6-20260917/loaded-process-identity.json staged-commit / PID receipt
- work/accept6-20260917/gpu-identity-postrun.json  POST-RUN GPU identity (not contemporaneous)
- work/accept6-20260917/capture.ts                  local only; 81,564,364 bytes;
    sha256 7b457d828a62311ed06017e9e57da338611a98d3af684ab66d94ce1b9e7990f8
