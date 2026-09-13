# beta.7 R7 selector handoff repair - local verification

Date: 2026-09-13

Branch: `fix/beta7-quiescence-deadlock`

Base `main`: `ad17971df5360c87ed10f52f3d2978f9da2dcf53`

Implementation and local-proof anchor:
`ffbc1bdaa157ca4f1c9f20af79e6e45e2b83e899`

This is source and local native-runtime evidence. It is not a replacement
signed installer, Sandbox qualification, Gate A result, physical tester soak,
or publication authorization.

## Rejected candidate carried into this repair

The exact signed build #81 candidate at base `ad17971` remains rejected.
GitHub build run `34751773391` produced installer SHA-256
`d10157ab7ba37fb7cb761b30f264f77e86f97706dfdb19f9f6814fa6ab555110`.
The quarantined kit is
`C:\CivicCastTester\kit-safe\ad17971df5360c87ed10f52f3d2978f9da2dcf53`.

The captions-OFF Sandbox run passed 12 evaluated cycles with 96 reload commits,
zero worker exits, and zero relaunches. That result does not qualify the
candidate because the captions-ON run failed. The captions-ON run recorded
three post-start worker exits/relaunches across public and education, including
two nonzero exits, one clean exit, and a maximum 41.2 second recovery gap.
Compact copies of both raw harness summaries, verdicts, and restart-event lists
are under `rejected-ad17971/` in this evidence directory.

## Failure mechanism and source basis

GStreamer 1.28.5 `input-selector` applies `active-pad` in two phases. Setter
return can leave a pending pad; a later buffer or serialized event commits it.
The rejected implementation blocked both outgoing A/V tails while both new
tails remained held, removing every event that could complete the pending
switch and allowing the coupled A/V and mux path to deadlock.

The repair requests both selectors while the old leg can still flow, releases
both replacement holds, and requires notification plus exact `active-pad`
readback for both streams before publishing the new role or retiring the old
leg. For finite replacements it first installs nonblocking DROP probes on both
old selector sink pads, then samples the outgoing timestamp edge and applies one
common offset. A buffer already beyond those probes has already crossed the
timestamp observer; later buffers are dropped before entering the selector.
After confirmed handoff, source-peer DROP probes remain in place while both old
selector request pads are released and the old elements reach NULL. No IDLE
barrier, manual peer unlink, or synchronous flush enters the selector path.

The staged runtime reports `GStreamer 1.28.5`. The inspected upstream tag
`1.28.5` peels to `727ceb91886862d200f423baf36cde2bb7ce5b4d`.
Local source-copy hashes:

- `gstinputselector-1.28.5.c`: `8c6771fc98f7662c118fdb469062003fffbe2fb875954ddf7361ca4299697eea`
- `gstpad-1.28.5.c`: `ea6f6f134e58f0ab2e51997d5e2b47ad9ac50384b7f44bc8409d1321c5174130`

Final governed Git blob bindings:

- `civiccast/egress/gst/engine.py`: `be31cf9b80b474682aafe2fe8d5ea244c5bb60a9`
- `tests/egress/test_gst_engine_wsl.py`: `07bb5dfae1a281db3e17768e547d21031f9c1945`

## Deterministic and focused results

The complete concise outputs are committed beside this file as
`pytest-deterministic.txt` and `pytest-focused.txt`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests\egress\test_gst_engine_reload_commit_ordering.py
```

Result: `56 passed in 1.58s`.

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\egress\test_gst_engine_reload_commit_ordering.py `
  tests\egress\test_gst_engine_reload_concat_naming.py `
  tests\egress\test_gst_engine_preroll_timeout.py `
  tests\egress\test_gst_engine_first_output_timeout.py `
  tests\egress\test_gst_worker_reload_ack.py `
  tests\egress\test_gst_worker_preroll_timeout_exit.py `
  tests\egress\test_gst_worker_first_output_timeout_exit.py `
  tests\egress\test_daemon_reload_commit_timeout_relaunch.py `
  -q -p no:cacheprovider
```

Result: `145 passed in 2.36s`.

The deterministic suite includes a two-phase coupled A/V selector model,
partial confirmation and stale callback rejection, peerless request-pad
release, pre-selector rollback, and an interleaving guard that proves both
old-sink cutoff probes arm before the timestamp snapshot and both selector
requests precede replacement hold release.

## Native Windows GStreamer results

The tests used the byte-verified staged payload at
`C:\CivicCastTester\runtime-test-ad179-r7\payload`. Its embedded CPython 3.12
loaded the current checkout from the implementation commit above while using
the staged GStreamer closure. No product installer was rebuilt for these local
tests.

The immediate finite rollover and three-channel production-pressure captions
test passed together: `2 passed in 80.10s`. The immediate worker committed once
with one confirmed selector handoff, no `ERROR:` line, and clean teardown. Each
of public, education, and government completed six programme changes with six
`selector-handoff-confirmed` receipts, six `old-tail-detached` receipts,
constant `elements=77`, zero `ERROR:` lines, zero stalls, and clean teardown.
The test also asserted MPEG-TS continuity, audio PID presence, caption command
delivery, audio-tap output, and no partial tap files.

Two adjacent deferred rollover cases passed: `2 passed in 15.59s`. Each worker
committed once with confirmed selector handoff, zero `ERROR:` lines, and clean
teardown. The copied final worker logs and reload receipts are under
`native-final/`.

## Static checks

- Ruff check passed for the engine and both changed test files.
- Ruff format check reported all three files already formatted.
- Mypy reported no issues in `civiccast/egress/gst/engine.py`.
- Python `compileall` passed for the engine.
- Claims blob drift was `[]`.
- `git diff --check` passed.

## Independent review

Two read-only agent reviews examined the integrated source and tests. The
test/evidence lens returned GO on the core repair. The concurrency lens found
the first-buffer limitation in `drop-backwards`, required the selector-sink
cutoff, then reviewed its actual implementation and returned GO with no
remaining release blocker.

## Release boundary

No candidate has been built from `ffbc1bda`. Required next steps are PR CI and
merge, a fresh signed build from the exact merged SHA, captions-OFF and
captions-ON Sandbox runs from first start, Gate A, and a dedicated physical
tester soak. beta.7 may be published only after those exact-candidate gates
pass.
