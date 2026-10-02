# Coordinator audit of U04 - two fixes required, then finish the unit

Your three commits (bae25c3e, aca9dd4b, d228a4f1) are otherwise accepted. Coordinator re-ran from Git Bash:
`python -m pytest tests/egress -q -p no:randomly` -> 1 failed (known GStreamer env test), 1661 passed,
40 skipped; the watchdog test module against the parent `automation.py` -> 1 error (collection), i.e. red.

## Fix 1 (defect): wrong env-var spelling
The brief specified `CIVICCAST_AUTOMATION_PASS_WATCHDOG_SECONDS` and
`CIVICCAST_AUTOMATION_PASS_WATCHDOG_REPEAT_SECONDS` (two C's). You shipped the ONE-C spelling
(`automation.py:259-260`, and the module docstring at `automation.py:20`), which is exactly the class of
bug U03 just fixed: the station's registry uses two C's. These variables are brand new, so there is NO
legacy spelling to keep - just use the two-C names everywhere (code, docstrings, tests).
Red then green: a test that sets the two-C threshold variable and asserts it is honoured must fail
before your fix and pass after.

## Fix 2 (behavior): first report lands up to threshold + repeat late
Your own docstring (R5) says a stall is first reported up to ~90 s after it starts at 30 s / 60 s.
Make the first report land within a few seconds of the threshold: the watcher should wake on a short
fixed tick (use `min(threshold, repeat, 5.0)` seconds), report a pass the first time it is over the
threshold, and then re-report it only when `repeat` seconds have passed since that pass's LAST report.
Keep every other property (no daemon locks, no store, all logging on the watcher thread, never raises).
Red then green: a test with threshold 0.3 s / repeat 5 s whose pass blocks ~1 s must see the first stack
dump before the pass ends (fails today because the second check would land at 5.3 s), and must see only
ONE dump in that second.

## Then
- `python -m pytest tests/egress -q -p no:randomly` numbers, ruff + mypy on automation.py.
- Separate small commits for Fix 1 and Fix 2; `git status --porcelain` before each; never amend.
- Append a section "## Coordinator fixes" to `reports\U04.md` with the commits and raw proof output.
