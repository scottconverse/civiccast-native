# U41 - coordinator answer: (A), env-flag form. And fix the runway (section 7) - the 83 s plan is the root cause.

Good work; the premise correction stands (the worker cannot see a preparation; `_pending_reload is None` is the
honest predicate). Engineering calls, final:

1. **(A), minimal form.** The daemon's live-channel launch sets `CIVICCAST_WORKER_PERSISTENT=1` in the worker's
   environment (on the path the daemon uses for an ACTIVE channel - name the file:line); `worker.py` reads it and
   arms `_hold_slate_at_plan_eos` only when it is `1`. Default off: anything that launches a worker without it
   (the beta.5 pin, smoke mode, harnesses) keeps exit-at-plan-EOS, and the pin stays untouched and green. No new
   control verb. The daemon and worker ship together, so no older-daemon story is needed; say so in one line.
   Tests: the flag on -> hold (your real-worker test sets it); flag off -> exit (the pin, run with the runtime root
   set, passes at HEAD); a daemon-level unit test that the ACTIVE launch carries the flag.
2. **The runway (your section 7): fix it.** A deferred rollover's plan is anchored at dispatch but takes air only at
   the current item's end, so its runway is consumed while it waits (689 s planned, 83 s left at take-over). Rule:
   when a rollover is deferred (`switch_at_end_of_current`), the new plan must extend to at least
   `expected switch time + lead` (expected switch = the current item's scheduled end), i.e. build it with the
   horizon measured from the switch, not from dispatch. Show where the plan horizon is computed (file:line), fix
   it, tests red then green reproducing the incident's shape (a deferred switch ~11 min out with a 690 s lead must
   produce a plan whose remaining life at take-over is >= the lead). Do not split items or re-plan otherwise.
3. Gates as before (check no other `pytest tests/egress` is running first; U42 is active in another worktree -
   serialize the full-suite run), plus the beta.5 pin with the runtime root set. Small commits, never amend.
   Then STAGE `staging\U41` exactly as U40 staged it: base = the LIVE installed files' sha256 (read them from
   `C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\...`; the live engine.py is installed
   WITHOUT the 52-line opt-in STALL_DIAG block - the candidate engine.py must also omit it, and the carve must be
   proven hunk-for-hunk as U39 did), candidate == HEAD minus the carve, no __pycache__. Do not install.
   Append to `reports\U41.md`.
