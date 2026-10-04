# U87 buffered worker acknowledgement repair - v1

Scope: Critical concurrency/order unit. Source inspected at
`0faddc2a0c314ce12a20de38d872d2143e185b80`, branch
`codex/u73-caption-measurements`. Original installed soak source:
`deb2adfa9dab7e41c5d9a64fcd2bebb95b26723d`.
No station/helper/VM operation, build, dispatch, download, commit or push.
Native rollback changes were not touched.

## Observed failure and causal limits

`sandbox-lab/soak-output/soak-deb2adf-20261004-171539Z/VERDICT.json`
is FAIL: education reload acknowledgement timeout, planned restart from PID2264
to PID17356; sampled recovery gap22.5s. This verdict remains unchanged.

Exact raw first-checkpoint files under
`C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-oversight\evidence\u87-packaged-candidate-deb2\soak-captions-on\mapped-final-private\logs\checkpoint-cycle3`:

- `logs/control_plane-app.log`: education media preparation completion at
  11:36:32.043 MDT, then timeout at11:36:52.551 MDT:20.508s log gap.
  At the same timestamp, all three channels emit ASR overload diagnostics
  with21.797s in-call time. Government/public media-preparation completion
  reports22.9s, then their reload admissions succeed in milliseconds.
- `egress-per-channel/education/logs/gst-worker.stderr.log`: original worker
  reaches PLAYING and first output; output progresses through1990buffers in
  roughly5s reporting windows before the deliberate kill. No first reload
  arm receipt, stall receipt or EOS exit precedes that kill.
- `egress-per-channel/education/logs/gst-worker.stdout.log`: starts with the
  replacement worker's later successful reload; it does not prove original
  pipe acknowledgement timing.

Inference: simultaneous control-plane silence during cold ASR work is consistent
with caller scheduling/GIL starvation, not proof of a permanently wedged worker
GLib loop. The existing daemon warning makes that stronger claim without enough
evidence; this unit does not change restart recovery policy or diagnostics.
Historical receipt availability cannot be determined from these logs.

The exact deb2->inspectedHEAD diff for strategy/worker/engine is empty. Existing
startup repair4691a748 prepares cached CPU ONNX VAD before channel admission but
explicitly leaves first encoder/language-detection use cold. It plausibly removes
some first-call work; neither source inspection nor these logs prove elimination
of the20.508s pause. Unicast proof-copy correction addresses different receiver
ownership and does not repair this acknowledgement ordering defect.

## Reproduced product defect and blast radius

`_WindowsPipeChannel.send_and_wait` previously tested elapsed time before polling
the pipe. A caller suspended during write or polling could resume after5s with a
valid correlated acknowledgement already buffered, skip reading it entirely,
returnFalse and trigger daemon restart recovery. Existing fake transport plus
controlled monotonic clock reproduces this without a measurement harness.

Repair: nonblocking receipt inspection precedes expiry; an empty, malformed or
unrelated receipt expires immediately once the deadline has elapsed. No extra
sleep or waiting past expiry is added. Existing5s deadline, command identity,
accepted/applied success rules, error handling, locks and replay policy remain.
The shared pipe path also serves swap/caption/stop; their result rules remain.
Worker main-loop dispatch, caption acceptance and daemon fallback policy are
unchanged. No new state/API/schema/dependency is introduced.

Files: `civiccast/egress/gst/strategy.py`, existing
`tests/egress/test_worker_pipe_seam.py`, narrow `CHANGELOG.md` entry, this receipt
and raw evidence logs. Rollback is scoped reversal of those source/test/doc hunks,
not a worktree reset. Independent root review requested; pending at receipt time.

## Exact offline verification

All commands from `C:\Dev\Claude\civiccast-u73`, Python:
`C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe`.

Baseline:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/egress/test_gst_worker_reload_ack.py tests/egress/test_worker_pipe_seam.py -q`

`46 passed, 1 skipped in 6.91s`
Skip: existing real-gi import boundary, No module named 'gi'.

RED:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/egress/test_worker_pipe_seam.py -q -k buffered_receipt 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-BUFFERED-ACK-red.txt`

`4 failed, 34 deselected in 1.48s`
Accepted failsFalse versusTrue; other cases show zero reads. Full failures saved.

Falsification: initial partial fix inspected only after write, not after polling.
Same command with output `U87-BUFFERED-ACK-poll-red.txt`:
`4 failed, 4 passed, 34 deselected in 1.72s`
Full failures saved. Final fix handles both suspension points.

GREEN: same focused command with output `U87-BUFFERED-ACK-green.txt`:
`8 passed, 34 deselected in 1.43s`
Cases: write/poll suspension x accepted/error/empty/unrelated. Tests assert exact
reads, no added sleep after expiry, empty pending-waiter map and exact reasons.

Affected:
`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m pytest tests/egress/test_gst_worker_reload_ack.py tests/egress/test_worker_pipe_seam.py tests/egress/test_daemon_reload_commit_timeout_relaunch.py tests/egress/test_u67_reload_stall_recovery.py -q 2>&1 | Tee-Object -FilePath ops/beta10-oversight/reports/U87-BUFFERED-ACK-tests.txt`

`67 passed, 1 skipped in 6.98s`
`SKIPPED [1] tests\egress\test_worker_pipe_seam.py:389: could not import 'gi': No module named 'gi'`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m mypy civiccast/egress/gst/strategy.py`
`Success: no issues found in 1 source file`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m ruff check civiccast/egress/gst/strategy.py tests/egress/test_worker_pipe_seam.py`
`All checks passed!`

`& 'C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe' -m ruff format --check civiccast/egress/gst/strategy.py tests/egress/test_worker_pipe_seam.py`
`2 files already formatted`

`git diff --check`: exit0, no output.

Focused review: only receipt ordering changes; unknown/error identity still fails;
deadline does not extend under malformed/unrelated traffic; no new lock order;
worker state is not inferred from elapsed caller time. Documentation states
development-only bounds and excludes installed acceptance claims. No auth/secrets,
persisted migration, UI or dependency surface changes.

Independent coordinator verification: re-read production `read_line` (nonblocking
PeekNamedPipe before ReadFile), correlation handling, expiry and daemon-facing
boolean contract. Re-ran the four affected modules above: `67 passed, 1 skipped
in 6.97s`; the same existing gi import skip remains. No change to timeout,
success-result policy, replay identity or lock order was found. An initial
coordinator command named nonexistent `test_worker_ipc.py` and collected no tests;
that command is not evidence. The corrected four-module run is the result cited.
Coordinator also ran `python -m pytest tests/egress/test_gst_strategy.py
tests/egress/test_daemon.py -q`: `274 passed, 6 skipped in 7.71s`; all six skips
are existing POSIX FIFO contracts on Windows. Full-tree `python -m ruff check .`
passed; `python -m mypy civiccast` passed 690 source files in the current shared
worktree (including concurrent rollback WIP, not a packaged-candidate claim).

Not run/proved: real named-pipe installed reproduction, current candidate soak,
elimination of cold ASR scheduling pause, full repository suite/release acceptance.

proved: sensitive existing-module RED/GREEN and affected67PASS/1existingSKIP,
focused mypy/Ruff/diff clean; lane: Critical.
