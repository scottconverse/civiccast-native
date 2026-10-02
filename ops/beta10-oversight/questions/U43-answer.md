# U43 - coordinator answer: (b) with the measured pad. The guard may move the drive. Implement, sweep 3 cells, stage.

Hypothesis refuted cleanly - thank you. These are engineering calls (mine), final:

1. **Shape (b), measured pad.** Replace the guard's current ceiling-drop round with a loudness-compensated round:
   `pad = kept.decoded_peak_dbfs - TP_GUARD_MAX_PEAK_DBFS + 0.5` (dB; 0.5 dB margin), then re-render from the
   ride's converged curve with `ceiling = kept.ceiling - pad` AND `trim_db = kept.trim_db + pad` (the drive rises by
   exactly the pad, so programme loudness holds), emit at the kept attempt's encoder, measure. Yes, the guard may
   move `trim_db` - only inside this round, only by the pad. At most ONE such round; then the existing encoder
   variants (256k, 256k fast) run at the NEW ceiling/trim if the bound is still missed; keep-best selects over all
   attempts as today (loudness gates first). ERROR if every attempt misses. Cap the pad at 6.0 dB (a larger
   measured need -> use 6.0 and let keep-best/ERROR report it).
2. **Three-cell sweep before staging:** Senior window in=23.7412 dur=1800; Senior full asset (the 1212 s feed on disk
   is fine for provenance, then one full-asset warm run if time allows within the scaled bound); Sustainability
   in=2469.72 dur=1800. Report per cell: every attempt row, kept row, worst window, whole-program error, render s.
   Pass = loudness gates + hard bound on all three. A cell failing loudness under keep-best is the only STOP.
3. Nominal path unchanged, so no cache-version bump. Tests red then green (unit: pad arithmetic, the cap, trim moves
   by exactly the pad, the round order pad -> variants; real-ffmpeg: a synthetic cell where the old guard misses the
   bound and the pad round meets it at unchanged loudness). Gates after checking no other `pytest tests/egress` is
   running. Small commits. Stage `staging\U43` (bases = live preparer.py `403C8C78...`, loudness_ride.py
   `798923B3...`; candidate == HEAD; no __pycache__). Do not install. Append Part IV to `reports\U42.md`.
