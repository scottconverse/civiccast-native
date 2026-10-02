# U26 - coordinator answer 2 (2026-09-25 MDT)

Option B: not queued. The remaining case has a direct fix at plan-build time, and it is in the code you already
touched. Found by the coordinator:

`civiccast/egress/automation.py` ~2089-2096 (your worktree):
```
# A final schedule window commonly resolves to the same item with
# less time remaining. It cannot extend the live horizon, so roll
# seamlessly onto filler instead of allowing EOS.
force_fallback = fresh_end <= plan_end_at and fresh_seconds < planned_seconds
```
That is the live incidents exactly: the programme's media ends about 10 s before its scheduled slot ends, the
boundary resolution returns the SAME item with ~10 s left, and the rollover rolls onto FILLER (the 12-subchain slate).
Seconds later the next item is due, and the slate -> program immediate reload hits F3(b).

## Decision
In that branch, when the same closing item resolves with a remainder at or below `_SCHEDULE_TAIL_FLOOR_SECONDS`
(30 s), resolve the boundary provider again at the closing item's scheduled END (the next item's start) and, if
that answers a real next item, roll seamlessly (deferred, `switch_at_end_of_current=True`) onto THAT item, started
at `plan_end_at`, i.e. early by at most the remainder. Log it at INFO naming both items and the seconds pulled
forward. Keep filler for a remainder above the floor, for no next item, and under manual override. Reuse one
shared constant (do not duplicate 30.0 in automation; import or move it and say where it lives).

## Proof
1. Red then green at the unit level with the live shapes: remainder 9.6 s and 11.0 s -> rollover target is the
   next item, not filler; remainder 45 s -> filler (unchanged); no next item -> filler.
2. Rerun your deferred harness in the new shape: program A whose media ends ~10 s before its slot ends, program B
   next. Show one worker pid throughout, no slate leg, `mode=deferred`, exit 0.
3. Gates as before. Small commits, never amend. Update `reports\U26.md` with a section for this answer.
4. Then stage the U26 backport: `staging\U26\` against the LIVE installed `daemon.py`, `automation.py`,
   `source_plan.py` (whatever your commits touch), base hashes measured by you, proofs 1-5 as in U18/U19.
   NOTE: the U24 unit is also staging `daemon.py` (relay rebind + stderr drain). Stage yours against the LIVE file
   anyway and list every hunk; the coordinator will merge the two stagings.
