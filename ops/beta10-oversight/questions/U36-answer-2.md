# U36 - coordinator answer 2: accepted; one more item - read questions\U36-coordinator-note-2.md (written 15:59, after your last read)

Accepted at c3df08c7 (coordinator red/green: your 4 test files 440 passed at HEAD; with the 1fdeaae6 sources
7 failed + 111 errors). Now the relaunch replay (note 2), in this unit, on the same branch:
1. Establish the in-point of the two post-escalation relaunch plans on public (15:24 and 15:56, both "City Council
   Regular Session - August 11, 2026", plan dir `public\prepared\9a975f75dd84`) from the logs, the live DB (read
   only) and the plan-dir naming code. Is the relaunch restarting the program from a fixed in-point (e.g. 0 or the
   item's first segment) instead of from the schedule position? If yes: fix it so a relaunch resolves item and
   in-point from the schedule at the relaunch instant (your `_resolve_schedule_tail` applies), red then green.
2. Why was a 1.2 GB segment for the same plan hash re-conformed (~100 s start preparation both times) instead of
   reused? If the prepared-segment cache is being invalidated or the plan dir deleted between uses, name where
   and fix it so an identical prepared segment is reused (a relaunch should be seconds, not 100 s). Red then green.
3. Education 14:51 (worker exited on a reload error while on slate): a reload that fails before commit must keep
   the current leg (slate) playing, never exit the worker. Check `WORKER_RESULT {'error': (gerror=...
   decodebin14 ... all streams without buffers)}` in `evidence\education-exit1-1451\gst-worker.stdout.log`: which
   code path turned a pre-commit reload error into a worker exit? If clear, fix red then green; else report.
Gates as before (check no other full suite is running first). Small commits, never amend. Append to the report.
