# U43 - coordinator answer 2: the pad round gets the ride's own trim correction. Q1 stays loudness-first. Q2: variants at the pad round's settings.

Cell A's pad round hit the bound and missed whole-program loudness by 0.03 LU (+0.53): raising the drive by the full
pad over-compensates because harder limiting removes less loudness than the pad. The ride already has the tool for
this (answer 10 step 2): render the limited PCM, measure its whole-program loudness, correct the pre-limiter trim by
the measured error. Decisions (engineering, final):

1. **Pad round = render at (ceiling - pad, trim + pad) -> measure PCM whole-program loudness (no encode) -> correct
   trim by the measured error (constant gain, pre-limiter) -> re-render once -> encode + measure as today.** At most
   one correction; the same correction the nominal path uses, same code path if it exists (reuse, do not duplicate).
2. **Q1: loudness-first stays.** The selector is unchanged; with (1) the pad round should pass both. Fix the guard's
   WARNING wording so it no longer says the hard gate "must hold" - it is enforced by selection and reported.
3. **Q2: the encoder variants run at the pad round's final (ceiling, trim)** when the pad round still misses the bound;
   if the pad round failed loudness, they run at the nominal settings as today. Keep-best over all.
4. Re-run the 3-cell sweep (A, B, C). Pass = loudness gates + hard bound on all three. If A still fails, STOP with the
   table. Otherwise: tests red then green (add: the pad round's trim correction; A-shaped synthetic where the
   uncorrected pad round misses loudness and the corrected one passes), gates (check no other full suite running),
   small commits, stage `staging\U43` (bases 403C8C78... / 798923B3...; candidate == HEAD; no __pycache__). Do not
   install. Append Part V to `reports\U42.md`.
