# U38 - coordinator answer 3: U39 is INSTALLED (19:48:15). Now merge U25 and stage one more carry (staging\U40).

Live now: engine.py = `beta10-int` @ `e1189cae` minus the 52-line STALL_DIAG carve (sha256 D9665887...); the other
U38 files as staged in U38.

Do now, on `beta10-int`:
1. `git merge --no-ff beta10-ds` (tip `e4392af2`; base `8e9c2ed7`, an ancestor of int). Sources:
   `civiccast/egress/preparer.py` (ride wiring, `_LOUDNORM_METHOD_VERSION` -> `loudnorm-v3-ride`, the `-t` placement
   fix) and NEW `civiccast/egress/loudness_ride.py`, plus tests. `preparer.py` on int already carries U20 + U29
   (warm) + U36 (segment rejection): resolve every conflict keeping all four behaviours; show each hunk and why.
   Check specifically that U29's warm and U36's rejection both still run on the ride path (the ride replaces the
   loudnorm stage only), and that the ride's measurement-failure fallback lands on U20's two-pass.
2. Gates on the merged HEAD (check no other full suite is running first): `tests/egress tests/stream` full; U25's
   ride tests incl. `test_preparer_ride_real_ffmpeg.py` with the STATION's ffmpeg on PATH (it needs soxr - say how
   you pointed it there); U29 warm and U36 rejection tests. ruff/mypy on changed sources.
3. Stage `staging\U40\` against the LIVE `preparer.py` (hash it yourself; expect AF99E0DB...), candidate = merged HEAD
   `preparer.py`; `loudness_ride.py` is an ADDED file (listed separately, no base line). Prefixed
   `installed-base.sha256`, proofs 1-5 (py_compile with the installed runtime, import smoke of preparer +
   loudness_ride inside the installed runtime incl. numpy import - say whether numpy is present in the installed
   runtime; if it is NOT, STOP and ask), differential tests, hash table, INSTALL-NOTE incl. the cache-key change
   (every asset re-conforms on first airing again) and the expected first-airing cost. No `__pycache__` in
   `candidate\`. STOP after staging.
