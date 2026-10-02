# U35 - coordinator answer: A. This is engineering, and the merged behaviour is the one we want. Stage all three.

Good stop and a precise finding. Decision: **Option A**.

Why: the merged behaviour (worker restart -> U21 rebind -> fresh relay child) is exactly the manual cure the
coordinator has applied to all four live freezes today (`Recover-RelayStall.ps1 -Mode RestartOne`, which restarts
the worker AND the relay) - it is the proven cure, so the escalation doing the same thing is desirable, not a
regression. The storm guard's purpose is "bounded", and the bound now comes from two tested budgets (one heal per
relay incarnation; <=3 escalation restarts per channel per rolling hour, then CRITICAL and stop). Worst case ~7
relay spawns/hour on a permanently frozen channel is acceptable.

## Do
1. Rewrite `test_daemon_tick_sequence_no_restart_storm_with_frozen_playlist` to assert the bounded property:
   (a) with NO escalation (worker never restarted) the count stays at 2 exactly as before - keep that case
   verbatim so the original invariant is still pinned; (b) with escalation: at most one heal per relay
   incarnation, total relay children <= 1 + budget x 2 over a long tick run spanning the budget (drive the fake
   clock past 3 escalations and show the 4th is refused with the CRITICAL and the count stops growing).
   Red/green: show (b) fails if the budget check is removed.
2. Update U30's docstring in `test_daemon_freeze_escalation.py` (and any code comment) that says the relaunch
   leaves the relay alone end to end: U30 does not stop the relay itself, but on beta10-int the relaunch rebinds it
   via U21's `new_session=True`. Say so accurately. Add one short note to the hls_relay finding-4 comment.
3. Keep `40fe9edd` (the test-double repair) as its own commit. Small commits, never amend.
4. Then Work 3 and Work 4 as briefed, for all three branches (U31 + U33 + U30) in ONE staging. Gates re-run on
   the final HEAD.
