# U37 - coordinator: new live defect in the switch path you hardened. Unit U44 (resume of your session).

Installed now: U37 drain gate + U41 (plan-EOS hold, persistent flag, deferred-rollover runway) + U40/U42 preparer.
Live engine.py = beta10-u41 `b38e5a3b` minus the 52-line STALL_DIAG carve
(`C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\egress\gst\engine.py`, sha256 1A25BC21...).

OBSERVED, government, 06:02 (evidence `evidence\government-exit1-0602\`: worker stderr tail, stdout tail, control
plane): deferred reload id=4 at running time 6900.968 s went cleanly through rebase-drain (waited 1.281 s),
selector switch, holds released, handoff confirmed, old tail released/detached; the new leg's first video AND audio
buffers reached the selector (sink_5, running_time 6900.968); the rebase observer disarmed for AUDIO (sink_66,
arrived=49) but NEVER for VIDEO (sink_65); `stage=committed elements=61`; then
`CTRL stall: no video buffers for 10s (last reload id=4 stage=committed) - quitting for daemon restart` -> exit 1,
relaunch, on air again ~3 s later (so ~13 s of frozen video, then a cold restart of the programme).

So after a clean commit, video stops reaching the mux while audio flows. Find where the video path stops between the
selector and the mux-side rebase observer (sink_65), with file:line: candidates to rule in/out with measurements -
the drain gate's hold/probe on the video pad not removed on this path, a DTS/running-time mismatch on the first new
video buffer (pts 0.700 vs audio), queue/selector blocking, a leftover pad probe from the old leg. Reproduce with a
real worker (runtime root `C:\Program Files\CivicCast (Native)\runtime`) on a deferred reload at a long running time
if the shape needs it. Fix, tests red then green (unit + one real-worker run), full egress suite after checking no
other `pytest tests/egress` is running, ruff, mypy. Worktree: create `civiccast-ds-u44` from `beta10-u41`
(`git worktree add -b beta10-u44 ..\civiccast-ds-u44 b38e5a3b` from the `civiccast-ds-u41` checkout), own `.venv`.
Stage `staging\U44` like U41 (bases = live sha256s; engine.py candidate = HEAD minus the STALL_DIAG carve, proven
hunk-for-hunk). Do not install. Report `reports\U44.md`. STOP only on a product question.
