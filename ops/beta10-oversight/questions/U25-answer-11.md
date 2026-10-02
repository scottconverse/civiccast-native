# U25 - coordinator answer 11 (Q19, Q20): final shape. Implement now.

Loudness + hard TP 7/7 with worst window 0.565 LU and 0 samples over 0 dBFS is the product result. The nominal
path meets the incremental budgets (4D36 79.4 s <= 90; BIG 369.3 s <= 600). The only failing part is a guard that
chases an AAC codec overshoot the ceiling barely controls (your BIG step-law finding). Decisions:

1. **Q20: hard TP is the guarantee; the -1.0 dBTP target is best effort.** Guard = at most ONE re-encode-only round:
   when the emitted TP is above -1.0 dBTP, re-run only the limiter + AAC + mux from the already-correct ride PCM with
   the ceiling lowered by (emitted - (-1.0)) + 0.3 dB (no re-convergence, no model step), measure, keep-best by the
   existing selector (hard TP first, then loudness gates, then lowest TP). If the target is still missed, ship the
   best attempt with one WARNING naming both TPs. If NO attempt meets the hard TP (a decoded sample > 0 dBFS or
   emitted TP > 0.0 dBTP), emit once more at a -4.0 dBTP ceiling and ship that with an ERROR line (last resort;
   report how often this happened on the panel - expected 0).
2. **Q19: (C).** Gate = the increment over the incumbent product path, measured on the box. Nominal increment:
   on-demand <= 90 s, warm BIG <= 600 s (both already measured as passing). Guard round: <= 35 s on a 30-min cell,
   <= 240 s on BIG. Reconcile the harness budgets (`r5/cell7.py:61-67`) to these numbers.
3. Measure once more on the 7 cells + 2 timing cells with the final guard; before each timing run check that no
   `pytest` or other unit's ffmpeg is running (wait up to 10 min for quiet; if never quiet, run anyway and label
   the run CONTENDED). Then IMPLEMENT per answers 5/7/8/9 (wire both preparer paths on top of the CURRENT
   `beta10-ds` HEAD, `loudnorm-v3-ride`, measurement failure -> old two-pass + one WARNING not cached under the new
   key, pure unit-tested functions incl. guard selection and the last-resort branch, tests red then green incl. one
   real short-file end-to-end, gates after checking no other full suite is running, small commits, every
   `preparer.py` hunk listed; do not stage). Only a loudness-gate or hard-TP failure on the panel is a STOP.
