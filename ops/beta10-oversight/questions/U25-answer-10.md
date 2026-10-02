# U25 - coordinator answer 10 (Q18): your recommendation. The model steers; one measured render corrects.

Accepted: the model (worst 0.232 LU) is good enough to steer, not to be the answer; the delivery bar is what
matters. Build it this way:
1. Converge curve + trim + slew + gap cap on the block model (ms).
2. Render the ridden, limited PCM ONCE and measure it (ebur128 on the PCM stream, not the AAC): whole-program and
   both 240 s window families. Correct the TRIM by the measured whole-program error (a constant gain; the limiter
   interaction is small at a trim change of <= 0.3 LU - if the correction exceeds 0.5 LU, do one more model step +
   render + measure, at most once).
3. Emit (render + AAC + mux) at the corrected trim, measure the artifact as today, and run the answer-7 guard on
   the model (re-converge at the new ceiling on the model, render + measure + trim-correct, emit, keep-best).
Gates, unchanged: every cell worst window <= 0.9 LU (both families), whole program <= 0.5 LU, hard TP (no decoded
sample > 0 dBFS, emitted TP <= 0.0 dBTP), target TP <= -1.0 reported; incremental audio cost on-demand 30-min
<= 90 s and warm BIG <= 600 s (guard included, BELOW_NORMAL, station live). Run the 7-cell panel + the two timing
cells. If all pass: implement (answer 5/7/8/9 terms: wire both preparer paths, `loudnorm-v3-ride`, fallback +
WARNING, tests red then green incl. one real short-file end-to-end, gates after checking no other full suite is
running, small commits on `beta10-ds`, every `preparer.py` hunk listed; do not stage). NOTE: `preparer.py` on
`beta10-int` now also carries U29 (warm) and U36 (segment rejection) on top of U20; keep your hunks minimal and
list them so the coordinator's merge is mechanical. Otherwise STOP with the numbers.
