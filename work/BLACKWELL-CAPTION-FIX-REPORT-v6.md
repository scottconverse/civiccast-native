# Blackwell beta.8 caption-runtime fix - human report v6 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v5 (BLOCKED/BOM - incorrect) and v4 (PASSED - based on a
non-overlapping run). Both are retained with banners and are not the verdict.

## VERDICT: ACCEPTANCE PROVEN (with an explicit proof boundary)

An acceptance capture whose interval demonstrably OVERLAPS fresh cue creation
decoded SEVEN caption entries of real speech text from the emitted transport
stream. The earlier "zero text" claim was a bug in MY heuristic parser, not a
product defect.

## The decisive correction

- The preserved tracked decode-back work/accept3-20260917/decodeback-full.srt
  (CURRENT: 816 bytes, sha256 147dc290c0d1da236179830c1b70d67f3f9fe9766ce0cb94c77b000da2f8e12f) holds
  7 numbered SRT entries with real text, e.g. entry 1:
  "from I think 72% up to 75% for precipitation so a little uptick".
- I re-ran the exact decode myself and reproduced all 7 entries.
- WHY MY EARLIER PARSER DISAGREED: I walked the A/53 triplets from offset +6,
  but the cc_data triplets begin at +7 (the header is 03 54 then the ff fc
  marker). Reading from +6 sampled the marker bytes, so the only "pair" I saw was
  fd80. With the correct offset the capture yields 116 distinct field-1 pairs and
  34 text-like pairs (an, d , 2%, up, ay, ...), consistent with the decoder.
  The real ffmpeg/product decoder outranks my heuristic - it was right, I was wrong.

## Overlap proof (accept3)

- capture: 20:58:49 MT -> 21:00:17 MT
- a fresh cue already existed at 20:58:44 (cue-003113, real weather text)
- cue count grew 1 -> 5 between 20:58:52 and 20:59:38 - INSIDE the window
- sidecar cleared at 20:59:51, AFTER those cues
- decode-back ORIGINALLY created 21:01:07 MT (file creation time), after the capture
  ended; the tracked file was later normalized to strip one trailing blank line,
  so its current mtime/bytes/hash are as stated above and its content is unchanged

## Capture identity (exact)

- path: work/accept3-20260917/capture.ts
- bytes: 11269472
- sha256: a13e130c37a8612d6351e137297b9f8b695f6048ac1f7399d692caa0d4e7be56
- decode-back entries: 7
- decode-back file: work/accept3-20260917/decodeback-full.srt
  (CURRENT: 816 bytes, sha256 147dc290c0d1da236179830c1b70d67f3f9fe9766ce0cb94c77b000da2f8e12f)

## Retracted root cause (BOM)

The v5 BOM claim is withdrawn. CivicCastSupervisor runs as LocalSystem with NO
service Environment value and NO CIVICAST_STATION_STATE_PATH, so
station_state_path() resolves to %LOCALAPPDATA%\CivicCast\station-state.json =
C:\Windows\System32\config\systemprofile\AppData\Local\CivicCast\station-state.json.
That file has NO BOM (leading bytes 7b 0d 0a) and persists
station.live_captions_enabled = true. Scott's user-level file with the BOM is not
the service's input and cannot be the root cause, so the caption feed was never
gated off by it.

## What is genuinely fixed (four defects, proven RED/GREEN)

1. stale-session publish race -> generation-stamped publish
2. sidecar-reset exception blocking Start -> best-effort hook
3. ~20 s short-restart PTS lag -> lead bounded against pipeline uptime
4. tiny-overlap false corroboration -> substantive-overlap fraction (0.4, from 4/9 geometry)

Honest split on exact candidate 41ec3dda (source untouched): 11 failed, 1 passed
across ALL new tests; at HEAD 12 of 12 pass. The earlier "5 failed / 5 passed" was
a selected subset and is retracted.

## Live runtime provenance

- four fixed modules staged into the installed runtime BEFORE a supervisor
  restart (PID 34716 -> 6696); installed hashes equal branch source.
- receipt: work/accept-20260917/loaded-process-identity.json (canonical; an identical
  copy also exists at work/accept2-20260917/loaded-process-identity.json)
- caption runtime resolved to CUDA / float16 on this host.

## Gate status

- ruff check / ruff format --check: clean
- git diff --check 41ec3dda..HEAD: clean
- focused suite: 632 passed, 7 skipped
- branch: 9 DCO-signed commits after 41ec3dda (git rev-list --count 41ec3dda..HEAD == 9; all 9 carry Signed-off-by). v5 said 7 and my earlier v6 said 8 - both corrected.
- no PR / merge / tag / publish

## Proof boundary (do not overclaim)

The 7 decoded entries prove caption text reached the emitted output during an
overlapping captions-ON run on the patched installed runtime. This report does
NOT prove long-run stability, nor that every cue is error-free; it proves the
acceptance criterion (fresh cue + contiguous TS/VTT + bounded decode-back with
real text) for this run. My two prior verdicts (PASSED, then BLOCKED) were both
wrong and are superseded here.

## Evidence (repository-relative; text committed, binary TS on local disk)

- work/accept3-20260917/decodeback-full.srt       7 decoded entries (real text)
- work/accept3-20260917/validation-result.json    run record; capture path/size/hash
- work/accept3-20260917/cue-timeline.jsonl        cue count vs time (overlap proof)
- work/accept3-20260917/active.vtt                sidecar snapshot
- work/accept-20260917/loaded-process-identity.json  restart/hash receipt (canonical path)
- work/accept3-20260917/capture.ts                binary TS kept on local disk per CONTRIBUTING.md
