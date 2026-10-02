# U59 (prep-spread) round 2 - C10 (your preparer 7f2fcef6) is LIVE, and live data contradicts the mechanism

C10 = staging\U59-install installed 20:45:51, service pid 34440, rung 8h-post-c10 running since 20:51:50.
Coordinator re-run of your RED/GREEN reproduced your numbers exactly (evidence\coord-u59-rerun-2015.txt). But the
RED is arithmetic over container/packet spans; the engine's leg-end spread was never executed. Live says:

## Observed (coordinator, OBSERVED)
1. C10 public reload_id=2 retiring leg = `public\prepared\8a016bd6d9ad` (prepared 20:47:41 BY YOUR PASS; leg length
   1198.567-114.367 = 1084.2 s = 592 + 493 pieces). Probe: seg1 audio start 1.406333 dur 591.893 / video 1.401 dur 592.0;
   seg2 audio 1.4/493.013, video 1.4/493.0. Aligned pieces. Engine: `switch-at-shorter-leg reload_id=2
   video_end=1198.567 audio_end=1199.364 spread=0.797 trimmed=audio:0.797` - the SAME 0.6-0.8 s as every C9 leg.
2. C9 education reload_id=14 retiring leg `education\prepared\508abec6bbba` (2 pieces; seg1 video start 2.253 vs audio
   1.400, dur 593.0 vs 593.813 = 0.853 audio-long; seg2 aligned): spread 0.801. Your model predicts baseline + 0.853.
3. Every single-piece leg today: spread 0.57-0.80, whatever its piece's A/V start offset.
So per-piece A/V asymmetry does NOT show up in the engine's leg-end spread: neither adds (2) nor removes (1). The
~0.7 s baseline comes from somewhere else, and the government 19:15 extra ~4.4 s is still unexplained.
4. Source `C:\ProgramData\CivicCast\data\uploads\lpmrot-02-city\City_Council_Regular_Session_-_September_8__2026.mp4`:
   14998.58 s video / 14998.61 s audio, last video pkt 14998.517+0.033, last audio 14998.594+0.020 -> the source
   ends aligned; the 18:28 leg was a mid-file slice (earlier airings of the title were 1800 s slices).

## Work
1. Measure the engine's leg-end spread by EXECUTING it: run the installed C10 engine (or your worktree with the live
   engine bytes) on filesrc with a 2-piece leg from real prepared pieces, and read its `switch-at-shorter-leg` line.
   Do it for (a) two aligned pieces (8a016bd6d9ad-shaped), (b) a piece with 0.85 s video start lag. Report the spread.
2. Find what makes the ~0.7 s baseline, and what could add ~4.4 s on the government leg. Candidates to test, not
   assume: the Council conform's A/V drift over a 4 h 10 m file (slice at a late in-point, compare video vs audio
   packet timelines around the in-point and at the slice end); pieces whose video EOS arrives early (decoder drop at
   piece end); per-piece concat behaviour for a piece whose video ends before its audio.
3. If U59's pass is not the fix, say so plainly. It stays installed only if it is harmless: prove the video is
   untouched and no picture is lost on real 1800 s pieces. Report in reports\U59.md under a new heading
   "Round 2", plain English first, receipt last. No station action. Rules and paths as in briefs\U59.md.
