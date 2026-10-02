# U25 - coordinator answer (2026-09-25 MDT)

Good unit. The two-defect split (window spread vs whole-program offset) is the right reading, and the U20 section 13
correction is accepted.

## Q3 - in scope, blocker
The -16 +/- 1 LU emitted gate is a beta.10 acceptance criterion. The shipped chain failing it on 5 of 6 sources is
a blocker, not a finding. Closing it is this unit's job.

## Q2 - fix the whole-program offset with a final exact trim, not by tuning loudnorm
Stop relying on loudnorm dynamic mode to land the integrated level. New chain architecture (engineering decision):

  [leveler] -> measure (pass 1, ebur128 integrated + true peak on the LEVELED audio)
            -> linear `volume=<target - measured>dB` -> `alimiter` (true-peak margin for AAC) -> AAC encode

That is: the leveler controls short-term spread; a single exact linear gain lands the whole program on -16.0;
a limiter only catches peaks. loudnorm may stay in the chain ONLY if a candidate with it beats the same candidate
without it on the same sources. Verify `alimiter` options in the shipped build (limit, attack, release, level,
asc) and choose a limit that yields emitted seek-free TP <= -1.0 dBTP after AAC (start at -2.5 dBFS; say what
`alimiter`'s sample-peak limit does to true peak and size the margin from your measured AAC overshoot).

## Q1 - bounded search, you choose inside it
Budget reset. Search on the TWO worst sources for spread (56F1 and 6A58) plus 4D36, max 12 candidates in total,
then validate the best 2 on all six. Families, in this order:
1. `dynaudnorm` in RMS mode (`targetrms`/`r` > 0; confirm the option name in the shipped build) with a long
   gaussian window (g 31..101 at f=500) and max gain m 6..12: this is a slow AGC on RMS, which is much closer to
   loudness than the peak mode C1/C2 used.
2. `speechnorm` (your suggestion): 2-3 settings.
3. Your C5 compressor (`acompressor` threshold -32 dB, ratio 4) as the comparison.
Every candidate uses the new trim + limiter back end above. Selection rule unchanged: worst non-overlapping 240 s
window of the emitted AAC within -16 +/- 0.8 on ALL six, and emitted seek-free TP <= -1.0 dBTP on all six; among
passing chains prefer the largest mean whole-program LRA. Also report the quietest-gap noise check from the brief
(a slow RMS AGC with too much max gain lifts room noise; that is why m is capped).

If nothing passes after the 12 + validation: STOP, report the best, and give me the per-source residual split
again. Do not widen the search on your own.

## Q4 - TP
Keep emitted TP <= -1.0 dBTP as a selection criterion; the limiter back end is how you meet it.

## After selection (work items 5-8 of the brief, unchanged in intent)
Implement in `preparer.py` on both paths (segment and whole-asset conform), constants named, measurement pass
measures the leveled audio, `_LOUDNORM_METHOD_VERSION` bumped, decision 1 kept (a failed measurement degrades to
leveler + limiter with no trim, one WARNING, not cached under the new key). Tests red then green, timing vs the
preparation timeout, gates, commits, then restage `staging\U25\` against the LIVE `preparer.py` with proofs 1-5.
