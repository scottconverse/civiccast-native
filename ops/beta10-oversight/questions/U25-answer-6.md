# U25 - coordinator answer 6: Q14 is engineering, not product. (b) then (c). Build it.

Good catch on the silently-off TP gate, and good call stopping. This is my call, not the owner's: a public-record
artifact must not carry samples above full scale, and the incumbent path already promised -1.5 dBTP. Option (a) is
rejected.

## Decisions
1. **Isolate the overshoot first (measure, ~15 min total).** (i) One controlled pass: take BIG's post-limiter PCM
   (the ride output, pre-AAC) around the four offending frames (+/-30 s each), encode it with the preparer's exact AAC
   flags, decode, true-peak it: say how much of the +4.1 dB is the encoder. (ii) Re-encode BIG through the
   INCUMBENT path (`loudnorm ... TP=-1.5`) once and report its emitted true peak and frames over 0 dBFS. If the
   incumbent also breaches, say so plainly: then this is an encoder-stage defect shared by both paths and the fix
   below applies to both.
2. **The ride's output stage becomes true-peak aware.** Replace the sample-peak `alimiter` with an oversampled
   limiter: upsample 4x (`aresample=192000` with soxr if the build has it, else the default resampler; say which),
   `alimiter` at the true-peak ceiling, downsample back to 48 kHz; then AAC as today. Ceiling: -1.5 dBTP pre-AAC
   (matches the incumbent's promise), attack/release as now unless the measurement says otherwise.
3. **Emitted-TP guard (closed loop on the artifact).** After the AAC emit, measure the emitted true peak (you
   already do: `emitted_TP_seekfree`). If it is above -1.0 dBTP, lower the limiter ceiling by (emitted - (-1.0)) +
   0.3 dB and re-emit ONCE; if still above, keep the lower of the two, log one WARNING with both numbers, and cache
   it. This keeps the rare hot asset correct without paying for it on every asset. Count how often it triggers on
   the panel and the time it costs.
4. **Harness (c):** `passes` = worst window within 0.9 AND whole program within 0.5 AND emitted TP <= -1.0 dBTP.
   Re-run the round-5 acceptance on all 7 cells with the new output stage (Q12 trim kept). Report the table with the
   TP column, the guard trigger count, and the timing gates (warm for the 2.5 h asset inside 1687 s at
   BELOW_NORMAL with the station live; 30-minute on-demand inside 300 s).
5. **Q13 follow-up:** re-run the BIG emit x3 with the new stage and rescan for frames over 0 dBFS; expect 0.
6. **Q10 (summed-curve slew clamp):** now do it, inside this round, since the numbers are being re-measured anyway.

## Then
If the re-run passes all three gates on all 7 cells and both timing gates: implement exactly as answer 5 said
(re-apply your saved `preparer_hunks.patch`, both preparer paths, pure unit-tested functions, bump
`_LOUDNORM_METHOD_VERSION`, measurement failure -> old single-pass + one WARNING not cached under the new key,
tests red then green incl. one real short-file end-to-end, gates, small commits on `beta10-ds`, every
`preparer.py` hunk listed; do not stage). If a cell fails only on TP by <= 0.3 dB after the guard, implement anyway
and report it; any other failure: STOP with the table.
