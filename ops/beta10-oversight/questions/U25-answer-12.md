# U25 - coordinator answer 12: my last-resort rule was wrong. Keep-best always; bound the hard TP at measurement noise; IMPLEMENT.

Your finding stands: the -4.0 dBTP last resort shipped a strictly worse artifact on BIG, and BIG's ceiling->TP
response is adverse (AAC overshoot grows with heavier limiting). The limiter cannot guarantee a decoded sample
<= 0 dBFS after AAC; what it CAN guarantee is the best of the attempts. Decisions (engineering, final):

1. **Delete the last-resort branch.** The selector is keep-best, always: among nominal + the one re-encode round,
   prefer attempts that pass the loudness gates, then the lowest decoded sample peak, then the lowest emitted TP.
   One WARNING when the TP target is missed, naming both TPs and the peak.
2. **Hard TP gate = no decoded sample above +0.1 dBFS** (BIG's nominal +0.0036 dBFS is a single-sample codec
   overshoot of 0.04% - below audibility and far better than the incumbent's +2.8 dBFS on the same asset; this
   bound is what the product can honestly guarantee). An artifact above +0.1 dBFS on every attempt ships with an
   ERROR line (not a stop) - report how many panel cells hit that (expected 0).
3. Your panel from the killed run is complete: re-evaluate it under 1 + 2 WITHOUT re-running the encodes (you have
   every attempt's measurements), and report the table. If every cell passes loudness + the new hard bound under
   keep-best: IMPLEMENT now per answer 11 section 3 (wire both preparer paths on current `beta10-ds`,
   `loudnorm-v3-ride`, fallback + WARNING, unit tests incl. keep-best selection with the adverse-BIG shape, one real
   short-file end-to-end, gates after checking no other full suite is running, small commits, every `preparer.py`
   hunk listed; do not stage). A cell failing the LOUDNESS gates under keep-best is the only STOP.
