# U62 round 2 - the fix is live on C13 and cut the gap from 3.0 s to 0.085 s; the residue is not zero

U62 ACCEPTED (coordinator 08:25; re-ran RED/GREEN; merged with U59e into engine 931390b1; installed as C13 at
08:26:38, service pid 37792). Live test on C13 (fixture copy: fixtures\C13-public-0831\, segs 100-118 + relay log):

- public, post-restart slate 08:30:48 -> program, reload_id=1 committed 08:31:39. Worker stderr:
  `new-leg-first-buffer stream=video|audio reload_id=1 applied_offset=220.381 pts=0.700`.
- AUDIO: seg000000109 audio ends 221.752411, seg000000110 audio starts 221.837744 -> 0.085 s gap
  (was 3.008 s on C12 06:43).
- VIDEO: seg109 ends 221.835933; seg110 starts 221.835944, 221.835956, 221.847656, 221.881000, 221.914322 ... ->
  three frames inside 12 ms at the frontier, then a 1/30 grid offset by ~11.7 ms from the outgoing grid.
  The station's own continuity check calls this `VIDEO_HOLE(seg000000110.ts, 0.033s at +0.012s)` and it made
  C13 loudness #1 for public an INSTRUMENT_ERROR (the window could not be scored).
- RELAY: 7 new `Invalid timestamps` (dts pinned ~0.078 s ahead of pts: e.g. stream=0 pts=343834290 dts=343841317).
  Was 232 on C12.

## Work (worktree civiccast-ds-u62; base = C13 LIVE engine 931390b1, NOT fe5a5306; C13 8 h rung live until
## ~16:29; no station action; tests small, low priority, <= 10 min; U59 round 8 is running in civiccast-ds -
## do not touch it)
1. Explain the residue from the fixture + your mechanism: why the new leg's first video frames are clamped onto
   the frontier (221.835944 / .835956) instead of landing on the grid, where the 11.7 ms grid offset comes from,
   why audio starts 0.085 s after the outgoing audio end, and why DTS is still pinned for ~7 packets.
2. Smallest fix that makes a slate->program immediate switch land with audio gap <= 0.050 s, no clamped/duplicate
   video frames, and zero relay invalid timestamps; no change to the seamless (non-slate) changeover path.
   RED/GREEN in tests against 931390b1; stage staging\U62b (engine on 931390b1, installed-base.sha256 row
   `931390b11decd696490db8cacd30b68d9d11648f939cd4178588be8170f006e3 *civiccast/egress/gst/engine.py`; test
   files NOT in candidate\).
3. If a zero-residue switch is not reachable at this point in the graph, say what the floor is and why.
Report "Round 2" appended to reports\U62.md, plain English first, receipt last.
