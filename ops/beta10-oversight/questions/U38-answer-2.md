# U38 - coordinator answer 2: U38 is INSTALLED (18:16:25). Now merge U37 and stage a second, engine-only carry.

`staging\U38` was installed at 18:16:25 (backup `backups\u38-install-20260925-181620`); the live station now runs
`beta10-int` @ `8c87694d` bytes for daemon/preparer/source_plan/_ffmpeg, and engine.py = 8c87694d minus the 52-line
STALL_DIAG carve (live sha256 BF8BA09C...).

Do now, on `beta10-int`:
1. `git merge --no-ff beta10-u37` (tip `fbf4fd6f`, base `5397c069` = U34, already merged). Source change is
   `civiccast/egress/gst/engine.py` only (+tests). Resolve any conflict keeping both behaviours (U36's aborted-leg
   containment in engine.py must survive), show it.
2. Gates on the merged HEAD (check no other full suite is running first): `tests/egress tests/stream` full, U37's
   focused pair and its real-pipeline tests with the runtime root set, U36's aborted-leg tests. ruff/mypy on
   engine.py.
3. Stage `staging\U39\` (new folder) against the LIVE engine.py (hash it yourself; expect BF8BA09C...): candidate =
   merged HEAD engine.py minus the same 52-line STALL_DIAG carve, installed-base.sha256 in the prefixed format,
   proofs 1-5 as before (py_compile with the installed runtime, import smoke, differential tests, carve proof, hash
   table), INSTALL-NOTE. Do not leave any `__pycache__` inside `candidate\`. STOP after staging.
