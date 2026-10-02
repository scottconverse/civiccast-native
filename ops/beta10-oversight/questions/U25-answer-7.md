# U25 - coordinator answer 7: Q15 is engineering. Re-converge at the shipped ceiling; test a higher AAC bitrate; gate on real clipping.

Excellent round: the guard-off control is the decisive measurement, and 23.1(ii) settles that the overshoot is the
AAC encoder, shared with the incumbent (which ships +2.8 dBTP / 4 frames over 0 dBFS on BIG today). The new stage
is already strictly better than what is on the air. Decisions:

## 1. Measure the encoder lever first (cheap)
Report `profile.audio_bitrate_kbps` / codec / sample rate as used by the station's prep profile. Then, on EF4,
4D36 and BIG, with the new stage at the nominal -1.5 dBTP ceiling and the guard OFF (the loop converged exactly as
in 23.4), emit at the current audio bitrate and at 192 kbps (and 256 kbps if the first two finish inside 20
minutes). Report emitted TP, frames over 0 dBFS, emitted I, per cell and bitrate. If a higher bitrate brings all
three to <= -1.0 dBTP, raise the prep profile's audio bitrate to the lowest bitrate that does (one constant; the
cache key must change with it; say which key) - audio at 192 kbps is negligible next to the video bitrate.

## 2. The guard re-converges (option a), it never re-emits at an unmeasured ceiling
If the emitted TP is above -1.0 dBTP: new ceiling = current - (emitted - (-1.0)) - 0.3 dB, then RE-RUN the
convergence loop at that ceiling (curve + Q12 trim measured at the stage that ships), emit, measure. At most 2
guard rounds. Keep the attempt with the lowest emitted TP among those that pass both loudness gates; if none of the
re-converged attempts passes the loudness gates, keep the nominal attempt. One WARNING naming every attempt when
the target is missed. The loop is not monotone (Q15a): this bounded search with keep-best is the answer, no fixed-
point iteration. Q15b: nominal ceiling stays -1.5 dBTP (the incumbent's promise); the guard is the exception path.
Reuse the decoded video / mux so a guard round costs only the audio ride + AAC + mux; measure it.

## 3. Acceptance gate (replaces the -1.0 emitted hard gate)
- Loudness: worst window (aligned and 120 s-offset) within 0.9 LU, whole program within 0.5 LU - unchanged.
- True peak, HARD: 0 decoded samples over 0 dBFS AND emitted TP <= 0.0 dBTP (no clipping in the public-record
  artifact, which is the actual harm).
- True peak, TARGET: emitted TP <= -1.0 dBTP. A cell between -1.0 and 0.0 after the guard is reported as
  "target missed", not a failure. (BS.1770 / R128 true-peak limits apply to the programme feed, which the -1.5 dBTP
  pre-AAC ceiling guarantees by construction; post-codec overshoot is handled by headroom best-effort.)
- Timing: both gates as before, now including the guard's cost on the cells where it triggers.

## 4. Then
Re-run the 7-cell panel with the chosen bitrate and the re-converging guard. If every cell passes loudness + hard
TP and both timing gates pass: implement exactly as answer 5 said (re-apply `preparer_hunks.patch`, both preparer
paths, pure unit-tested functions incl. the guard's keep-best selection, bump `_LOUDNORM_METHOD_VERSION`,
measurement failure -> old single-pass + one WARNING not cached under the new key, tests red then green incl. one
real short-file end-to-end, gates, small commits on `beta10-ds`, every `preparer.py` hunk listed; do not stage).
Any cell failing loudness or hard TP: STOP with the table.
