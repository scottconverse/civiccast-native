# U45 (U25 session) - live loudness FAIL in the 8 h rung: public -17.6 LUFS over 240 s. Measure first.

OBSERVED:
- Rung `evidence\rung-8h-pre-u44-20260926-101439\loudness-01.json`: public window 10:17:00-10:21:00 local,
  integrated -17.6 LUFS, LRA 11.9 LU, TP -0.5 -> FAIL (-16 +/- 1). Education -16.2 and government -16.0 PASS.
- Public was airing `Parks and Recreation Advisory Board - August 2026.mp4` (reload accepted 09:58:46 for the plan
  starting then). The full-asset ride log at 09:34:48: "the kept attempt misses the loudness gate (worst 4-minute
  stretch 5.86 LU, whole program -0.09 LU)". The window-path ride at 09:01:34 (in=0 dur=1800) passed.

## Work (worktree `civiccast-ds-u25fix` @ acd76c03 = installed; station ffmpeg first; one ffmpeg at a time, BELOW_NORMAL)
1. Locate the asset position that aired 10:17:00-10:21:00 (from the plan/reload in the control-plane log and the
   worker's running time) and the full-asset ride's worst window. Measure both from the SOURCE and from the cached
   artifact (conform-cache entry for this asset - read only): short-term loudness per 3 s, speech vs non-speech
   (recess, silence, room tone, music), and what the ride's curve did there (gain, gap cap, slew limits).
2. Report the root cause with file:line and the numbers. Classify: (a) a ride defect on speech (then fix it: tests
   red/green, re-run this asset's full-asset ride and the 7-cell panel's worst cell, stage `staging\U45` like U43;
   the cache version must be bumped only if nominal output changes - say which); or (b) the window is genuinely
   non-speech (recess/room tone) that the ride correctly refuses to boost - then STOP with the measurements; that
   is a product question on how the -16 +/- 1 criterion treats non-speech windows, and I will take it to the owner.
Do not install. Report in `reports\U45.md`.
