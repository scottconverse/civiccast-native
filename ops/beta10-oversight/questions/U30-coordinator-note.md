# U30 - coordinator note (2026-09-25 08:40 MDT): a THIRD live case

government 08:38: the same post-commit output stall. Deferred program -> program reload (reload_id=3,
`applied_offset=4074.606`, audio new-leg first buffer `pts=0.000`), stages through `stage=committed elements=52`,
then the worker's stderr has no further `CTRL output` progress lines; relay self-heal (spawn=10, reason=self-heal)
could not help. Full channel restart cured it (ok 08:40:05).
Evidence: `evidence\government-freeze-0839\` (worker stdout/stderr, the relay's own stderr log, control-plane log
08:20-08:39). Note the new-leg first buffer pts here is 0.000 (the 06:27 education case had pts=0.700).
Three live cases in ~7.5 hours on a 3-channel station: this is the top remaining defect. The escalation (item 1)
must ship; the diagnosis (item 2) should use all three evidence sets.

## Case 4 - public, 2026-09-25 10:04 (added by coordinator)
Same signature: deferred program->program reload reload_id=6 (applied_offset 9209.210), `stage=old-leg-disposed`,
`stage=committed elements=52`, then no `CTRL output` lines; relay window stopped advancing, relay self-restart did not
help; RestartOne cured it at 10:05:32. Logs: `evidence\public-freeze-1004\` (worker stderr/stdout, relay stderr,
control_plane 09:40-10:05). Four cases in ~9 h on three channels: the escalation (budgeted worker restart) must ship.
