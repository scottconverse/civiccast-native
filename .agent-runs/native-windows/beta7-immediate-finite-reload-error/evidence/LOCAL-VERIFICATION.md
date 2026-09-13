# beta.7 immediate finite fallback retirement verification - 2026-09-13

## Scope and identity

- Branch: `fix/beta7-immediate-finite-reload-error`
- Base and rejected-candidate source:
  `8bcf012db69a306bf6e163322ed25f2c671e93e4`
- Rejected signed build: `34745799145`
- Rejected installer SHA-256:
  `11ed7e9bd63d627103f45bfdeb500840b991569793a939a15e303da024c4eb27`
- Rejected whole-kit `SHA256SUMS.txt` SHA-256:
  `8cfa72de1f83509e15b89eeed0e4375f63793cfaac5537c5b9b6db735afcf1b2`
- Rejected-kit Sandbox evidence:
  `sandbox-lab/soak-output/soak-8bcf012-20260913-081856Z/`
- Current `civiccast/egress/gst/engine.py` Git blob:
  `414e0c95706801f49a78134c00d643e204a5f73d`
- Current `tests/egress/test_gst_engine_wsl.py` Git blob:
  `35da6b217ed9558642048dc0abd9755492b19feb`
- Current deterministic ordering-test Git blob:
  `2b4325cbbc99dc5b2652a0ad24c5c5f201e15273`

No repaired installer or kit exists at this checkpoint. This record is local
source/runtime proof. It is not installed Sandbox, Gate A, physical tester, or
publication acceptance for the repaired source.

## Rejected-candidate finding

The official 15-minute interval in the `8bcf012` Sandbox evidence completed 93
reloads, 31 on each channel. All three channels remained ON_AIR during that
interval, PIDs stayed stable, and the TSDuck measurements recorded zero
continuity discontinuities, invalid syncs, or transport errors.

The full log window from first channel start through the end of the run exposes
one worker error and relaunch on each channel before `SOAK-START`. Each initial
fallback-to-due-programme switch reached selector handoff. A `tsdemux` in the
retiring fallback then reported `Internal data stream error`, flow reason `-5`.
The generic bus-error path ended the worker before old-leg disposal and reload
commit. The daemon relaunched the worker and all channels recovered, but any
worker replacement fails candidate qualification. The `8bcf012` kit is
therefore rejected even though the narrower official interval graded PASS.

Production's fallback slate is a 12-subchain finite MPEG-TS playlist. It creates
`decodebin0` through `decodebin11` before the incoming programme is built. The
Sandbox failures from the `decodebin11`, `decodebin6`, and `decodebin4` families
therefore belong to the outgoing old leg.

## Repair boundary

`GstPlayoutEngine._on_bus()` contains and logs an ERROR only when all three
conditions hold:

1. A reload commit is in progress.
2. Selector handoff has started.
3. The error source or one of its parents is in the transaction's
   `old_elements` collection.

Errors from the selected replacement, the shared encoder/mux/output path, and
the old leg before selector handoff keep the existing fatal worker-recovery
path. No API, persistence, or operator workflow contract changes.

## Native Windows reproduction

Working directory for every command:

`C:\Users\scott\Documents\Codex\2026-09-10\openai-multi-agent-c-users-scott\work\beta7-r6-product-fix`

Runtime:

`C:\CivicCastTester\candidates\8bcf012db69a306bf6e163322ed25f2c671e93e4\candidate\trust-bridge-install\runtime\python.exe`

Common PowerShell prefix:

```powershell
$runtimeRoot = 'C:\CivicCastTester\candidates\8bcf012db69a306bf6e163322ed25f2c671e93e4\candidate\trust-bridge-install\runtime'
$env:CIVICCAST_GSTREAMER_RUNTIME_ROOT = $runtimeRoot
& "$runtimeRoot\python.exe" .agent-runs\run_pytest312.py
```

Baseline command suffix, run before the engine repair:

```text
tests/egress/test_gst_engine_wsl.py::test_immediate_finite_playlist_reload_holds_rebases_and_stays_on_air -q -s -p no:cacheprovider -p no:timeout --basetemp .agent-runs/pytest-baseline-slate12-user
```

Result: `1 failed in 43.61s`. The retained worker log is
`.agent-runs/pytest-baseline-slate12-user/test_immediate_finite_playlist0/worker.log`.
It records fatal `decodebin11/tsdemux4` flow error `-5`, no reload commit, and a
`WORKER_RESULT` with the error set.

Final repaired command suffix:

```text
tests/egress/test_gst_engine_wsl.py::test_immediate_finite_playlist_reload_holds_rebases_and_stays_on_air -q -s -p no:cacheprovider -p no:timeout --basetemp .agent-runs/pytest-fixed-slate12-user-r3
```

Result: `1 passed in 15.06s`. The retained worker log is
`.agent-runs/pytest-fixed-slate12-user-r3/test_immediate_finite_playlist0/worker.log`.
It records eight contained retiring-old-leg `tsdemux` errors, followed by old
leg disposal, holds released, `committed (elements=36)`, and
`WORKER_RESULT {'error': None, 'teardown_clean': True}`.

Neighboring deferred reload command suffix:

```text
tests/egress/test_gst_engine_wsl.py::test_deferred_rollover_switches_at_the_boundary_without_eos tests/egress/test_gst_engine_wsl.py::test_deferred_rollover_commits_with_a_multi_segment_concat_playlist_reload -q -s -p no:cacheprovider -p no:timeout --basetemp .agent-runs/pytest-neighbor-native
```

Result: `2 passed in 15.77s`. Both worker logs record clean commits and
`error: None`.

## Deterministic and focused checks

```powershell
.\.venv\Scripts\python.exe -m pytest tests\egress\test_gst_engine_reload_commit_ordering.py -q -p no:cacheprovider --basetemp .agent-runs\pytest-bus-unit-final
```

Result: `52 passed in 1.52s`. The suite proves that an old-leg descendant error
after handoff is contained and that old pre-handoff, new post-handoff, and
shared-path errors remain fatal.

```powershell
.\.venv\Scripts\python.exe -m pytest tests\egress\test_gst_engine_reload_commit_ordering.py tests\egress\test_gst_engine_reload_concat_naming.py tests\egress\test_gst_engine_preroll_timeout.py tests\egress\test_gst_engine_first_output_timeout.py tests\egress\test_gst_worker_reload_ack.py tests\egress\test_gst_worker_preroll_timeout_exit.py tests\egress\test_gst_worker_first_output_timeout_exit.py tests\egress\test_daemon_reload_commit_timeout_relaunch.py -q -p no:cacheprovider --basetemp .agent-runs\pytest-immediate-reload-focused
```

Result: `141 passed in 2.34s`.

Additional checks passed:

- Ruff check and format check on the engine and both changed test files.
- Mypy on `civiccast/egress/gst/engine.py` with no issues.
- Python compileall on `civiccast/egress/gst/engine.py`.
- `git diff --check`.
- Independent hostile GStreamer review: GO, no release-blocking correctness
  issue in the repair boundary.

## Remaining release gates

After required PR CI and merge, build a new signed candidate from the exact
merge SHA. Run corrected captions-OFF and captions-ON Sandbox qualifications
whose error window begins before the first channel start. Only after both pass,
run Gate A and the exact-hash-bound dedicated tester soak for four hours with
captions ON and four hours with captions OFF. Publication remains blocked until
all of those gates pass.
