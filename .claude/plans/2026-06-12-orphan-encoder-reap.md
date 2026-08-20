# Reap orphaned encoders on daemon startup (issue #161) — Implementation Plan

> Found by the CA-8 acceptance run: a server restart leaves the previous
> server's ffmpeg encoder children running; the new daemon's auto_start
> happily double-starts onto the same UDP sink port and the interleaved
> writers corrupt the stream (~1044 TSDuck discontinuities per 10s probe)
> until the orphan's plan ends. Option (a) from the issue.

## Design

The daemon already persists each channel's encoder pid in its durable state
row. A fresh daemon (no in-memory process entry) that is about to start a
channel first checks the state row's pid:

- pid running AND its process image is ffmpeg → it is our orphan: terminate
  it, append an honest proof event ("reaped orphaned encoder ... from a
  previous server process"), then start normally.
- pid running but the image is NOT ffmpeg → pid was reused by an unrelated
  program: never touch it; start normally.
- pid dead/absent → nothing to do.

Seams for tests (real implementations use psutil, already a dependency):
`orphan_probe(pid) -> str | None` (lowercase image name or None) and
`orphan_terminator(pid) -> None` (terminate + bounded wait).

The reap lives in `_start()` right after the in-memory live-process check —
every fresh start path (operator start command, auto_start recovery,
pending reload with no live process) gets it for free.

## Steps (TDD)

1. RED tests in tests/egress/test_daemon.py: reap-then-start with proof
   event; pid-reuse skip; dead-pid skip.
2. Implement seams + `_reap_orphan` + psutil defaults.
3. ruff format/check, egress suite, full gate.
4. PR `Closes #161` (note the runbook warning shipped in #162 stays as
   defense-in-depth for older builds) → merge → deploy to the soak server →
   verify a restart now yields exactly one encoder per channel and a green
   TSDuck verify (the acceptance result's recommended re-run).
