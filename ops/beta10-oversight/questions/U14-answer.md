# Coordinator answer to questions\U14.md

F1 (20a0a695) and F2 (516c2dba) and the CHANGELOG commit (782598ec) are accepted pending the coordinator's test
re-run.

**Authorized: implement §3 exactly as you proposed, with option (a)** - the restart airs the plan in the prepared
report (the plan the reload was triggered for), and the state row shows the report's source label. If the
schedule horizon moved meanwhile, the next ordinary rollover corrects it; add one INFO log line when the
prepared report is reused, naming the channel, the report's source label and the plan_dir, so a moved-horizon
case would be visible in the log.

Requirements (all from your own §3, restated as acceptance):
- The stashed prepared plan_dir is included in `live_prepared_plan_dirs` while the restart is in flight and is
  released on EVERY path that does not consume it (operator stop, drain, discard, a second failure, service
  shutdown). Test each release path.
- Every other caller of `_fall_back_to_restart_reload` behaves byte-identically (default None).
- Red then green: FALLBACK_SLATE + immediate program-due reload -> no seamless reload request is sent to the
  worker; the worker is restarted; the preparer is called exactly ONCE for that reload; the restarted start uses the
  report's plan and plan_dir. ON_AIR deferred rollover unchanged (explicit assertion).
- `python -m pytest tests/egress -q -p no:randomly` -> 1 known failure only; ruff + mypy on daemon.py.
- Separate small commit(s); `git status --porcelain` before each; never amend.
- Append "## F3(b) as built" to `reports\U14.md` with the commit(s) and raw proof.
