# U56 round 8 - C8 (U56f) is LIVE; now the unbounded fallback and the audio join residual

C8 = staging\U56f (engine 17a8bd88, graph 309ffac7, pipeline e3d7767a) installed 2026-09-27 11:50:46, service pid
19744, all 3 ON_AIR 11:52:09. Live playout-graph.json encoder = videoconvert, videoscale, capsfilter, openh264enc,
h264parse (no videorate). Rung 8h-post-c8 is running. Round 7 ACCEPTED.

## Coordinator re-run of round 7 (OBSERVED, evidence\coord-r7-rerun-1200.txt; out_shortv.ts, filesrc, 2 runs per arm)
| tree | arm | video max | audio max | verdict |
|---|---|---|---|---|
| fix13 (C7) | AF | 0.733 / 0.733 | 0.029 / 0.029 | HOLE 2/2 |
| fix13 (C7) | VF | 0.033 / 0.033 | 0.029 / 0.029 | ok 2/2 |
| ship7 (C8) | AF | 0.033 / 0.033 | 0.041 / 0.029 | 1 audio-over-0.030 / ok |
| ship7 (C8) | VF | 0.033 / 0.033 | 0.029 / 0.029 | ok 2/2 |
No rewinds in any of my 8 runs (you saw -0.093 on C7 and -0.027 on the candidate). The live C7 relay saw 0
'Invalid timestamps' at all 14 changeovers. Your harness shows audio rewinds that neither my runs nor live show; say why.

## Work
1. The unbounded fallback you found (`old_tail_cutoff_ns = switch_running_time if observed else None` ->
   `_mux_tail_drop_decision` returns OK on None, so the retiring audio airs until it drains). Prove it on filesrc on
   C8 bytes (the repo test `test_immediate_finite_playlist_reload_holds_rebases_and_stays_on_air` reds `{66: 1}`
   intermittently on both trees: make it red deterministically), then bound it. No new video holes.
2. The audio join residual (up to 0.041 s step; one AAC frame inside mpegtsmux). Only if the fix is small and does
   not touch the video path or the deferred-rollover tests; otherwise report it and leave it.
3. Stage `staging\U56g\` from LIVE bytes (base = the three C8 files). Report Part VIII, plain English first, receipt
   last. No station action. C8 live changeovers will be sent to you as addenda.

## Addendum 12:25 - RULE: never `start /b` (or any `/x` switch) from Git Bash
Your round-7 background launches (`start /low /b "" python ...`) ran in Git Bash, which rewrites `/b` to `B:/`.
Windows then tried to open drive B: and put a "cannot find B:/" OK-dialog on the owner's desktop. Launch background
work with the Bash tool's own background mode, or `cmd //c "start /low /b ..."` with doubled slashes, or PowerShell
`Start-Process -WindowStyle Hidden`. No command may put a dialog on the desktop.
