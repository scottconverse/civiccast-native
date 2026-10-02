# U25 - coordinator answer 9 (Q17): make the loop analytic, and gate on the audio work U25 adds

Good measurement and good catches (the stale `__all__`, the patch that is constants only). Q17 is engineering;
my decisions:

## 1. The gate is the audio work U25 ADDS, not the video conform
The video conform is the incumbent stage, unchanged by U25, and its wall time on this box today is dominated by
I/O contention from other agents (your sampler). U25 is judged on its incremental cost over the incumbent audio
path: **on-demand 30-min cell: ride + converge + guard + emit + measure <= 90 s; warm BIG: <= 600 s**, both at
BELOW_NORMAL with the station live, guard included. Report the video stage separately for information.

## 2. Converge analytically, render once
Rendering the full ride three times per iteration is the cost. Replace it with a block-energy model:
- One decode pass of the source (the one you already do): compute the K-weighted mean square per 100 ms block
  (BS.1770 pre-filter + RLB, per channel, summed with the channel weights) ONCE, and keep it (a 2.5 h asset is
  90,000 blocks - trivial).
- Because the gain curve is slowly varying (slew-limited), the gated loudness of the ridden signal over any window
  is computed from those blocks times the curve's gain squared per block (momentary 400 ms / short-term 3 s /
  integrated with both gates, exactly per BS.1770-4). Iterate curve + trim + slew + gap cap on that model:
  milliseconds per iteration.
- The limiter is the one non-linear part: model it by measuring, in the same single decode pass, each block's
  sample peak (and 4x-oversampled true peak if cheap) so the model knows which blocks the limiter will touch at a
  given ceiling; if that is not accurate enough, one full render + ebur128 measurement at the end of convergence
  is the check.
- Then render + emit ONCE, measure the emitted artifact (loudness windows + TP) as today. The guard: if emitted TP
  is above -1.0, compute the new ceiling as answer 7 said, re-converge ON THE MODEL (ms), re-emit once, measure,
  keep-best as implemented.
- **Model validation (must pass before implementing):** on all 7 cells, the model's predicted per-window
  loudness (aligned and 120 s-offset 240 s windows) and whole-program loudness vs the measured emitted artifact:
  worst |error| <= 0.15 LU. Report the table.
You may use numpy/scipy (BSD) for the filters; nothing GPL.

## 3. Housekeeping
Fix `__all__` / the module docstring so only the answer-7 guard (`guard_next_ceiling` + `select_leveled_attempt`)
is exported and the re-emit-once `tp_guard` is deleted.

## Then
If the model validation passes and both incremental gates pass: implement exactly as answers 5/7/8 say (both
preparer paths wired, bump `_LOUDNORM_METHOD_VERSION` to `loudnorm-v3-ride`, measurement failure -> old single-pass
+ one WARNING not cached under the new key, tests red then green incl. one real short-file end-to-end, gates -
check no other full suite is running first, small commits on `beta10-ds`, every `preparer.py` hunk listed; do not
stage). If either fails: STOP with the numbers.
