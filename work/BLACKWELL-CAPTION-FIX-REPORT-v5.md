# Blackwell beta.8 caption-runtime fix - human report v5 (2026-09-17)

Author: implementation coder (Codex), for Scott Converse.
Supersedes v4 (which claimed PASSED on non-overlapping evidence). v4 is retained
with a SUPERSEDED banner and must not be read as the current verdict.

## VERDICT: BLOCKED (not PASSED)

Live caption text does NOT reach the emitted stream. This is now proven by an
acceptance capture whose interval demonstrably OVERLAPS fresh cue creation, with
a specific, reproducible root cause. No on-air text decode-back has succeeded.

## What is proven

1. The four defects found in post-review audit are FIXED with behavioural
   failing-before / passing-after regressions:
   - stale-session publish race (generation-stamped publish)
   - sidecar-reset exception blocking Start (best-effort hook)
   - ~20 s short-restart PTS lag (lead bounded against pipeline uptime)
   - tiny-overlap false corroboration (substantive-overlap fraction from the
     measured 9 s/5 s tap geometry)

2. Honest test split on the EXACT candidate 41ec3dda (source untouched):
   11 failed, 1 passed across ALL new tests. At HEAD: 12 of 12 pass.  (The
   earlier "5 failed / 5 passed" was a selected subset and is retracted.)

3. The installed-runtime provenance gap is CLOSED: the four fixed modules were
   staged into the installed runtime BEFORE a supervisor restart
   (PID 34716 -> 6696), so the running process loads the fixed files.  Receipts:
   work/accept-20260917/loaded-process-identity.json

4. An OVERLAPPING live run (work/accept3-20260917):
   - capture start 20:58:49 MT, end 21:00:17 MT
   - a fresh cue already existed at 20:58:44, and cue count grew 1 -> 5 between
     20:58:52 and 20:59:38 - INSIDE the capture window
   - therefore the capture interval provably covers fresh cue creation
   - the sidecar was cleared at 20:59:51, AFTER those cues

5. Result of that overlapping run: ZERO decoded caption entries.  2,541 GA94
   markers present, but exactly ONE distinct CEA-608 field-1 byte pair (fd80 =
   0x7d 0x00) and ZERO printable text bytes.  The gst worker stdout contains
   ZERO caption control commands.

## Root cause of the feed -> worker -> mux break (proven)

`C:\Users\scott\AppData\Local\CivicCast\station-state.json` begins with a
UTF-8 BOM (bytes ef bb bf).  `_load_raw_state()` then raises JSONDecodeError,
SWALLOWS it, and returns `{}`.  Consequently:

- `read_live_captions_enabled()` -> None
- `resolve_live_captions_enabled()` -> LIVE_CAPTIONS_DEFAULT -> False

The caption FEED is therefore disabled, while the caption TAP is separately
enabled (activated native station sets CIVICCAST_CAPTION_TAP=inline).  Net
effect: the tap commits real cues into active.vtt, and the feed never pushes
them to the mux - exactly the observed signature (good sidecar, padding-only
A/53 on the wire).

## Evidence (repository-relative; text committed, bytes on local disk)

- work/accept3-20260917/validation-result.json   overlapping-run record + root cause + capture hash
- work/accept3-20260917/cue-timeline.jsonl       cue count vs time during the capture
- work/accept3-20260917/active.vtt               sidecar snapshot (cleared post-cues)
- work/accept3-20260917/capture.ts               11,269,472 bytes, sha256 a13e130c37a8612d6351e137297b9f8b695f6048ac1f7399d692caa0d4e7be56  (local only, per repo binary policy)
- work/accept-20260917/loaded-process-identity.json   restart + hash-correspondence receipt
- work/accept2-20260917/validation-result.json   the earlier, NON-OVERLAPPING run (superseded as proof)

## Gate status

- ruff check / ruff format --check: clean
- git diff --check 41ec3dda..HEAD: clean (was failing on two SRT EOFs)
- focused suite: 632 passed, 7 skipped
- 7 commits, all DCO-signed; no PR / merge / tag / publish

## Known gaps / remaining work

- No successful on-air text decode-back.  Acceptance criterion NOT met.
- The BOM-vs-default interaction needs a regression test and a decision:
  either tolerate a BOM in station-state.json, or fail loudly instead of
  silently reading "off", or make the tap and feed share one switch so they can
  never disagree.
- After that fix, a further OVERLAPPING acceptance run is required before any
  PASS can be claimed.
