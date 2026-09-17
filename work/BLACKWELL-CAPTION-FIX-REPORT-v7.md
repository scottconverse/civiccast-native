# Blackwell beta.8 caption-runtime fix - human report v7 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v6. v6's verdict overclaimed the handoff's acceptance criteria.
v6, v5 and v4 are retained with banners and are NOT the verdict.

## VERDICT (two distinct claims - do not merge them)

1. OUTPUT-PATH SUCCESS PROVEN (narrow, before overload):
   Real caption text reached the emitted transport stream.  A 7-entry decode-back
   from the contemporaneous TS, re-derived independently from capture.ts, yields
   real speech text.  This proves the caption pipeline can get text onto the wire
   on this Blackwell host with the patched installed runtime.

2. FULL HANDOFF ACCEPTANCE / RELEASE READINESS: NOT PROVEN - STILL BLOCKED.

   The authoritative handoff requires, among other things:
   - outgoing TS **AND VTT** preserved before/after,
   - ONE run-specific expected cue rather than whole-VTT counts,
   - overload/backlog/stale state measured before AND after recovery,
   - repository-relative durable evidence + manifest.

   Accept3 does NOT satisfy these.  Specifically:
   - the committed active.vtt is only 7 bytes (bare "WEBVTT"): the tap CLEARED it,
     so the run's cue text is not preserved in a VTT.  A run-specific expected cue
     was observed live (cue-003113, recorded in expected-cue.json) but only via a
     monitor record, not via a preserved sidecar.
   - the run hit a hard overload and PAUSED captions (see below).  No
     after-recovery acceptance evidence was recorded.

## The overload that v6 mis-described (corrected)

At 2026-09-16 20:59:51,229 MT - about 89 seconds after ON_AIR - the log reads,
verbatim:

  "Caption tap overload for channel public: 3 settled segments exceeds the maximum
   2. Live captions are PAUSED for 120s (overload #1) so playout keeps the CPU;
   active captions were cleared and the stale audio was discarded."

v6 described this only as "sidecar cleared after cues", which hid a 120-second
caption pause.  Corrected here and preserved in overload-during-run.json.  The
7 decoded entries were produced BEFORE this pause; they therefore prove the
output path, not sustained operation.

## What the decode-back proves (with the parser bug disclosed)

- work/accept3-20260917/decodeback-full.srt holds 816 bytes
  (sha256 147dc290c0d1da236179830c1b70d67f3f9fe9766ce0cb94c77b000da2f8e12f) with 7 numbered entries and real text, e.g.
  "from I think 72% up to 75% for precipitation so a little uptick".
- Re-decoding capture.ts reproduces all 7 entries.
- An earlier "zero text" claim was MY bug: I walked the A/53 cc_data triplets
  from offset +6 instead of +7, so I read the ff fc marker and saw only fd80.
  The real decoder was right.

## Corrected capture chronology (from actual timestamps)

- capture: 20:58:49 -> 21:00:17 MT
- fresh cue already present at 20:58:44 (cue-003113)
- cue count grew 1 -> 5 between 20:58:52 and 20:59:38 (inside the window)
- OVERLOAD + PAUSE + VTT CLEAR: 20:59:51 (inside the window)
- decode-back originally created 21:01:07 MT, after the capture ended; the tracked
  file was later normalized (one trailing blank line removed; content unchanged)

## Retracted root cause (BOM) - still withdrawn

The service runs as LocalSystem with no CIVICCAST_STATION_STATE_PATH and no
service Environment value, so it reads the systemprofile state file, which has no
BOM (leading bytes 7b 0d 0a) and has live_captions_enabled=true.  Scott's
user-level BOM file is not the service input.  Not a root cause.

## Genuinely fixed (four defects, proven RED/GREEN)

1. stale-session publish race -> generation-stamped publish
2. sidecar-reset exception blocking Start -> best-effort hook
3. ~20 s short-restart PTS lag -> lead bounded against pipeline uptime
4. tiny-overlap false corroboration -> substantive-overlap fraction (0.4, from 4/9)

Honest split on exact candidate 41ec3dda (source untouched): 11 failed, 1 passed
across ALL new tests; at HEAD 12 of 12 pass.

## Live runtime provenance

Four fixed modules staged into the installed runtime BEFORE a supervisor restart
(PID 34716 -> 6696); installed hashes equal branch source.  Canonical receipt:
work/accept-20260917/loaded-process-identity.json (identical copy also under
accept2-20260917).

## Gate status

- ruff check / ruff format --check: clean
- git diff --check 41ec3dda..HEAD: clean
- focused suite: 632 passed, 7 skipped
- DCO: every commit after 41ec3dda is signed; resolve the count with
  `git rev-list --count 41ec3dda..HEAD` (deliberately not hard-coded - earlier
  hard-coded counts went stale three times)
- no PR / merge / tag / publish

## Evidence (repository-relative; text committed, binary TS on local disk)

- work/accept3-20260917/decodeback-full.srt    7 decoded entries (real text)
- work/accept3-20260917/expected-cue.json      the one run-specific cue, and its limit
- work/accept3-20260917/overload-during-run.json  verbatim 120s pause + VTT clear
- work/accept3-20260917/cue-timeline.jsonl     cue count vs time
- work/accept3-20260917/active.vtt             7-byte cleared sidecar (the limitation)
- work/accept3-20260917/validation-result.json run record; capture path/size/hash
- work/accept-20260917/loaded-process-identity.json  restart/hash receipt
- work/accept3-20260917/capture.ts             11269472 bytes, sha256
  a13e130c37a8612d6351e137297b9f8b695f6048ac1f7399d692caa0d4e7be56  (binary TS kept on local disk per CONTRIBUTING.md)

## Remaining work before any release claim

- A controlled captions-ON run that preserves the actual VTT before clearing,
  records one expected cue, and observes overload RECOVERY (no threshold changes,
  no killing GPU workloads).
- Overload/backlog/stale measured before AND after recovery.
- Then, and only then, a full acceptance verdict.
