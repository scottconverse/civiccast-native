# beta.7 startup control-readiness repair: local verification

Date: 2026-09-12

## Identity

- Source proof commit: `362fc48ed8dff20f41dde703285d8773ff6326c5`
- Parent / rejected candidate source: `cd54767bc3c3cd3fcacf6aa5642f1df459a4fdea`
- Branch: `fix/beta7-control-ready-v2`
- Release status: source correction only. A replacement installer and kit do
  not exist yet; Sandbox, Gate A, physical tester soak, and publication remain.

The rejected `cd54767` candidate is build run `34699190826`, candidate artifact
ID `10299893320`, candidate artifact digest
`sha256:56cc1884de546860ea04f227ff5bf186d18945a3a50746c05877e1e434fd2b50`,
installer SHA-256
`b9a327094706f7dc07a75432ffa3875e84339b78afeb6e2d8eb9422df9dced08`,
and manifest SHA-256
`d28e74b41bb0cfdc22631fac5a14322e746cc819b76fb52ba129c3e73bf16d8c`.
It must not be reused or published.

## Reproduced failure

The exact `cd54767` kit passed byte verification, installed successfully in a
fresh Windows Sandbox, and brought all three channels ON_AIR with captions off.
The 15-minute seamless-reload soak then failed: education's first automatic
programme reload arrived before PID 9876 connected its Windows control pipe,
so the daemon aborted the reload and performed one planned restart. PID 1884
recovered in 20.4 seconds. The remaining run recorded 94 successful reload
commits, zero worker stalls, and zero unplanned relaunches.

Exact grader result: 15 cycles total, 3 warmup, 12 evaluated,
`planned_restart_count=1`, `reload_aborted_count=1`,
`unplanned_relaunch_count=0`, verdict FAIL. The committed raw evidence is under
`rejected-cd54767/` in this directory.

## Correction

Initial schedule resolution now starts a monotonic deadline. After preparation,
the daemon refuses to launch the plan when its originally selected first
programme segment has already expired. It releases that unused prepared plan
once and starts one separately prepared fallback plan; fallback is excluded
from the expiry check, so the recovery cannot recurse or chase schedule rows.
This avoids comparing asset IDs, which cannot distinguish adjacent schedule
occurrences of the same asset.

Both automatic reload paths wait until the Windows worker's initial control
connection has been observed before they call the provider or consume reload,
retry, or cooldown state. The observation is a one-way startup latch. Existing
ACK failure and worker-exit recovery continue to handle later disconnects.
FFmpeg, non-reload, and POSIX behavior is unchanged.

## Executed verification

```text
py -3.13 -m pytest -q -p no:cacheprovider --basetemp=<writable-temp> \
  tests/egress/test_automation.py tests/egress/test_daemon.py \
  tests/egress/test_gst_strategy.py tests/egress/test_worker_pipe_seam.py
336 passed, 7 skipped in 12.67s

py -3.13 -m ruff check <seven touched source/test files>
All checks passed!

py -3.13 -m ruff format --check <seven touched source/test files>
7 files already formatted

py -3.13 -m mypy --ignore-missing-imports --no-warn-unused-ignores \
  civiccast/egress/automation.py civiccast/egress/daemon.py \
  civiccast/egress/gst/strategy.py
Success: no issues found in 3 source files

git diff --check
PASS (no output)
```

The seven skips are expected on this Windows host: six POSIX FIFO contracts and
one native-GStreamer `gi` import. Independent adversarial review first rejected
the pipe-only draft, required expired-start handling and truthful one-way latch
naming, then accepted the final integrated correction with no blocking findings.

## Remaining release gates

Open and pass required PR CI, merge to `main`, build a fresh exact-source kit,
pass a fresh Sandbox soak, pass Gate A, pass the dedicated physical tester
overnight soak, and only then publish beta.7. No result from `cd54767` or any
older candidate carries forward.
