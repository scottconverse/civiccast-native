# U25 - coordinator answer 8: the product path governs. Measure it, then implement.

Loudness + hard TP 7/7 with the target met 7/7 at 192 kbps is the result we needed. Correct call not to compare an
audio-only column with whole-path budgets.

## Decisions
1. **Q16: the product path governs.** Measure it (your offered 20-30 min): `timing5.py`-style, the real preparer
   path with video, at BELOW_NORMAL with the station live, WITH the re-converging guard, for (a) BIG as the warm
   2.5 h asset against 1687.5 s and (b) the 30-minute on-demand segment against 300 s, choosing for (b) the panel
   cell whose guard cost was highest among the 30-minute cells (say which). A guard round must re-run only the
   audio ride + AAC + mux, reusing the conformed video (answer 7 section 2); if the product path cannot do that,
   make it do that, then measure.
2. **Audio bitrate: 192 kbps** in the prep profile (the setting the 7/7 pass was measured at); cache key changes
   with it (name the key). Record that the encoder lever alone was not monotone and is not relied on.
3. If both product-path timing gates pass: implement exactly as answer 5 + answer 7 section 4 say (re-apply
   `preparer_hunks.patch`, both preparer paths, the re-converging guard with keep-best as pure unit-tested
   functions, bump `_LOUDNORM_METHOD_VERSION`, measurement failure -> old single-pass + one WARNING not cached under
   the new key, tests red then green incl. one real short-file end-to-end, gates - check no other full suite is
   running first, small commits on `beta10-ds`, every `preparer.py` hunk listed; do not stage). If either fails:
   STOP with the measured numbers.
