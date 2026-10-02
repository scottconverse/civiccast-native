# U25 - coordinator answer 5: IMPLEMENT

Round 5 passes the actual acceptance gate: every 240 s window, both families, on all seven cells, within -16 +/- 1.0
(worst 0.899). Timing gates pass with 2.7x / 2.9x headroom. That is what beta.10 needs. Build it.

## Decisions
- **Q12: option (b)**, in scope: slope-corrected trim `trim1 = trim0 + (TARGET - I_B) / max(slope, 0.4)` with the slope
  measured each iteration, and the stop rule changed to "emitted whole-program error <= 0.1 LU, or no improvement
  between iterations, or max iterations". Run the one-run test from your section 71.1 on 4D36 and BIG first; keep it
  only if it moves both toward -16 without making any window worse than 0.9. If it does not, ship without it and
  say so.
- **Q11 (room tone): accepted as a known beta.10 limitation.** Keep the gap cap code as is (it is harmless), record
  the measured lifts in the report; the coordinator takes it to the owner as a known limitation.
- **Q10 (summed-curve slew up to 2x):** accepted; clamp the SUMMED curve's slew to the specified limit in the
  implementation (cheap) and note any window effect.
- **Q13 (the single corrupted AAC frame):** before implementing, check whether the production encode path (the same
  ffmpeg + AAC flags the preparer uses, fed by your ride's PCM pipe) can emit it: run the 4D36 and BIG emits 5 times
  each from the implemented code path and scan every output for decode errors / a frame with |peak| > 0 dBFS
  (`ffmpeg -v error -i out -f null -` plus a per-frame peak scan). Report the count. If it reproduces, stop and
  report; if 0 of 10, note it as a harness artifact.

## Implement
In `civiccast/egress/preparer.py`, both paths (segment + whole-asset conform): the chunked PCM ride (bounded memory),
curve + gap cap + slew + gating + loop as pure, unit-tested functions (put them in a new small module, e.g.
`civiccast/egress/loudness_ride.py`, to keep `preparer.py` hunks small for the U29 merge), trim with limiter
`alimiter=level=0`, AAC as today. Bump `_LOUDNORM_METHOD_VERSION`. Keep decision 1 (a measurement failure degrades
to the old single-pass with one WARNING, not cached under the new key). Tests red then green (unit + one real
short-file end-to-end through the preparer). Gates: `python -m pytest tests/egress -q -p no:randomly` (name
pre-existing failures proven at `8e9c2ed7`), ruff, mypy. Small commits on `beta10-ds`, every hunk in `preparer.py`
listed (U29 changes the warm scheduling in the same file; the coordinator will merge the two and stage once).
Do not stage.
