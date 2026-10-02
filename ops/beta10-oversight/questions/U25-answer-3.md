# U25 - coordinator answer 3 (engineering; not a product question)

Excellent round. The decomposition (curve term = clamp on 4D36; chain term = limiter's window-local cost that a
whole-program trim cannot repay; gate slippage refuted) is accepted and it tells us exactly what to build. Note the
acceptance gate itself is +/-1.0; W45G12 already passes it on 5 of 6 sources. The +/-0.8 selection margin stays.

## Decision: close the loop, offline, and raise the ceiling with the silence hold kept
1. **Closed-loop ride, 2 iterations.** Iteration 1 = your current W45 pipeline (ride -> trim -> alimiter
   level=0). Then measure the iteration-1 OUTPUT (after the limiter, PCM, same ebur128 M-block series and the
   same two-stage window gating), compute a correction curve c(t) = TARGET - L_W,out(t) (same window W, same slew,
   same silence hold), add it to the iteration-1 curve, clamp the SUM to [G_min, G_max], and re-render from the
   SOURCE (not from the iteration-1 output) with the summed curve -> new exact trim (measured after the limiter,
   your trim1 rule) -> limiter. This repays the limiter's window-local cost and the curve residual in one step.
   If a third iteration would change any window by more than 0.1 LU, report it but do not run it.
2. **G_max = +16 dB**, G_min = -6 dB, slew 1 dB / 2 s, W = 45 s, silence hold as now (gated blocks keep the last
   gain). Report the quiet-gap check again: the room-noise lift in the source's own quietest 10 s, per source; flag
   any gap that ends above -35 LUFS short-term.
3. **TP retry fixed:** after a limit change, re-measure and re-derive the trim (it is part of the loop); a retry
   must never reuse the stale trim.
4. **No more screening.** Run this ONE configuration end to end on all six sources with the full emitted
   measurement (AAC in MPEG-TS, aligned + 120 s-offset windows). Selection: worst window within -16 +/- 0.8 on all
   six (two-sided), emitted whole program within -16 +/- 0.5. TP stays a reported quality figure.
5. Timing: report the wall time of the full chain for a 30-minute source and a 2.5-hour source on this box (the
   on-demand path has a 300 s timeout; the whole-asset warm has U29's scaled timeout
   `max(300, duration/8 x 1.5)` - say whether each path fits).

## If it passes
Implement (both preparer paths; envelope + correction as pure, unit-tested functions: silence hold, clamp, slew,
window gating, loop correction), bump `_LOUDNORM_METHOD_VERSION`, keep decision 1 (a failed measurement degrades to
the old single-pass with one WARNING, not cached under the new key), gates, small commits on `beta10-ds`. Keep your
hunks inside the audio-chain code: U29 (branch `beta10-u29`) changed the warm scheduling/timeout/priority code in
`preparer.py` and `stream/_ffmpeg.py`; list every hunk you touch so the two merge. Do NOT stage yet - the
coordinator will have one unit merge U25 + U29 and stage `preparer.py` once.

## If it does not pass
STOP with the six-source table and the curve/chain split after the loop.
