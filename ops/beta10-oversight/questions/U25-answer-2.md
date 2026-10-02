# U25 - coordinator answer 2

Round 2 is good work. Accepted as measured: the exact-trim back end works (whole program -16.0..-16.7); the limiter
needs a second measurement (`trim1`) and `alimiter` needs `level=0`; the remaining term is minutes-scale spread,
which no built-in real-time leveler (memory 15-50 s) can fix.

## Decision (engineering): offline gain riding, because preparation is offline
We have the whole file before airing. So compute the gain curve from the whole file instead of a real-time leveler:
1. Pass 1: `ebur128` over the whole (resampled 48 kHz stereo) audio with per-frame metadata, giving short-term
   loudness at 100 ms steps (or momentary; say which and why).
2. In Python: compute a sliding gated loudness over a window W centred on t (start W = 60 s; gate out silence the
   way ebur128 does, -70 LUFS absolute and -10 LU relative within the window), then
   gain(t) = clamp(TARGET - L_W(t), G_min, G_max) (start G_min = -6 dB, G_max = +12 dB), then smooth gain(t) with a
   slew limit (start 1 dB per 2 s) so it never pumps. Hold the gain through silence (do not ride up noise in pauses:
   below the gate, keep the last gain).
3. Pass 2: apply gain(t) sample-accurately with FFmpeg's `volume` filter driven by commands
   (`asendcmd`/`sendcmd` with a generated command file at 100 ms to 1 s steps, linear ramps between points, or
   `volume=eval=frame` with a piecewise expression; choose what the shipped build supports robustly and prove it
   is sample-accurate enough: no zipper noise, gain error < 0.1 dB against the curve), then the exact trim
   (trim0/trim1 as you corrected it), then `alimiter=level=0` for peaks.
4. True peak: after the AAC encode, measure the emitted seek-free TP; if > -1.0 dBTP, lower the limiter limit by
   (TP + 1.0 + 0.2) dB and redo the limiter+encode ONCE (material-dependent overshoot, handled per program).
   TP is a quality target, not the acceptance gate: report it, do not block selection on the second try.
All of this is Apache/LGPL-clean (Python + built-in FFmpeg filters). No new dependency.

## Search (bounded)
Parameters: W in {45, 60, 90} s, G_max in {+9, +12} dB, slew 1 dB/2 s fixed. That is 6 settings; screen them on
4D36, 6A58 and EDU (the three worst for spread), then validate the best on all six with the full emitted
measurement. Selection: worst non-overlapping 240 s window within -16 +/- 0.8 on ALL six. Tie-break: the largest mean
whole-program LRA (least squashing). Report the quiet-gap noise check too. Also report the worst window when the 240 s
windows are offset by 120 s (the live gate samples at arbitrary times, not on file-aligned boundaries).

## If it passes
Implement in `preparer.py` for both paths (segment + whole-asset conform) as a small, testable module (envelope
computation as a pure function with unit tests: silence hold, clamp, slew, window gating), bump
`_LOUDNORM_METHOD_VERSION`, keep decision 1 (a failed measurement degrades to the old single-pass with one WARNING,
not cached under the new key), timing vs the 300 s preparation timeout on a 30-min source, gates, small commits, then
`staging\U25\` against the LIVE `preparer.py` with proofs 1-5.

## If it does not pass
STOP with the table and the per-source residual split. Do not widen the search.

## Process hygiene
The leaked "realtime pair" you saw belonged to another unit and is gone. Keep your own count: list every process you
start and confirm it stopped.
