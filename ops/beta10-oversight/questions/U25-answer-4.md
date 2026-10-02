# U25 - coordinator answer 4 (engineering; final shape)

Round 4 accepted: the closed loop works (5 of 6 cells in +/-0.8, whole program in +/-0.5), 4D36 misses at -1.04 on the
+16 dB clamp, the loop is not converged at 2 iterations, the panel is 4 recordings, and the asendcmd ride is far too
slow on long assets. Good catches, all of them.

## Decisions
1. **Apply the ride in Python, not with asendcmd.** Decode the (already conformed-rate) audio to raw float32 PCM
   through an ffmpeg pipe in chunks, multiply by the gain curve interpolated per sample (numpy), apply the trim, then
   pipe into the rest of the chain (alimiter level=0 -> AAC) and mux with the video exactly as the preparer does
   today. The curve itself is computed from the ebur128 series as now. This must run at decode speed (your §53c
   baseline: ~88 s for 9000 s with ebur128 alone). Measure it. Memory must stay bounded (chunked, never the whole
   file in RAM).
2. **Iterate to convergence, max 4 iterations**, stopping when no 240 s window (aligned or 120 s-offset) moves by
   more than 0.1 LU. With the fast ride this is affordable; report the iteration count per source and the time.
3. **G_max = +18 dB, with a gap cap.** In blocks whose momentary loudness (source + current gain) is below the
   ebur128 absolute gate or more than 20 LU under the window's gated loudness (i.e. between speakers), the applied gain
   is capped at min(curve, +8 dB) with the same slew limit. This is what keeps room tone from being ridden up; report
   the quiet-gap check again (source vs emitted short-term in each source's quietest 10 s) and flag anything ending
   above -35 LUFS.
4. **Selection gate:** worst window (aligned and 120 s-offset) within -16 +/- 0.9 LU on all six cells (the acceptance
   gate is +/-1.0; 0.1 margin), whole program within +/-0.5, emitted TP reported. Report per recording (4) as well as
   per cell (6), per your §52.
5. **Timing gate:** the full chain for the 2.5 h Sustainability asset must finish inside U29's warm budget
   (`max(300, duration/8 x 1.5)` = 1691 s) at BELOW_NORMAL priority with the station live, and a 30-minute segment's
   on-demand path inside 300 s. Measure both.

## If it passes
Implement (both preparer paths; pure unit-tested functions for curve, gap cap, slew, gating, loop, and the chunked
PCM ride), bump `_LOUDNORM_METHOD_VERSION`, keep decision 1 (measurement failure -> old single-pass + one WARNING,
not cached under the new key), gates, small commits on `beta10-ds`, every hunk listed (U29 changed the warm
scheduling in the same file). Do not stage.

## If it does not pass
STOP with the table, per-recording, and the residual split. This is the last loudness round before I take the
remaining gap to the owner, so make the table decision-ready.
