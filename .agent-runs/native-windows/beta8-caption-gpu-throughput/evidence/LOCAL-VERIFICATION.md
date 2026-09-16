# Local verification: live-caption GPU throughput

- Date: 2026-09-15
- Branch: `fix/captions-cuda-three-channel-throughput`
- Base: `cc02cf11bf00685eff1c9c4cae5809a46ca05ed2`
- Scope: live faster-whisper and caption-tap concurrency only

## Measured defect

The Blackwell beta.7 run measured about 2.75 seconds for one GPU transcription.
Three channels produced one segment each every five seconds, but beta.7 serialized
all three calls through one CTranslate2 worker. About 8.25 seconds of work arrived
every five seconds, so backlog and the overload pause were inevitable.

## Implemented behavior

- A live CUDA faster-whisper runtime defaults to three CTranslate2 workers.
- A live CPU runtime and every batch runtime retain one worker by default.
- The caption tap follows the runtime capacity unless the operator explicitly
  sets `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`.
- Before the first multi-channel dispatch, the tap lowers its supervisor thread
  priority and prepares the model. If CUDA loading falls back to CPU, runtime and
  tap capacity both become one before the executor is created.
- No API, schema, schedule, playout, or caption-proof contract changed.

## Verification

Command:

```
.\.venv\Scripts\python.exe -m pytest tests/captions tests/ai_models/test_runtime_wiring.py tests/native/test_caption_capacity_proof.py -q
```

Result:

```
365 passed, 1 skipped in 66.96s
SKIPPED: external Postgres server not configured
```

Focused first-scan fallback regression:

```
.\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_tap_worker.py::TestCaptionTapWorker::test_first_three_channel_scan_resolves_cuda_fallback_before_dispatch -q
1 passed in 1.64s
```

Static checks:

```
.\.venv\Scripts\python.exe -m ruff check civiccast/captions/runtime.py civiccast/captions/tap_worker.py tests/captions/test_captions_core.py tests/captions/test_caption_tap_worker.py
All checks passed!

.\.venv\Scripts\python.exe -m ruff format --check civiccast/captions/runtime.py civiccast/captions/tap_worker.py tests/captions/test_captions_core.py tests/captions/test_caption_tap_worker.py
4 files already formatted

.\.venv\Scripts\python.exe -m mypy civiccast/captions/runtime.py civiccast/captions/tap_worker.py --ignore-missing-imports
Success: no issues found in 2 source files

git diff --check
PASS (no output)
```

Release identity policy after adding the missing dated beta.7 changelog
section:

```
.\.venv\Scripts\python.exe scripts/policy/check_release_identity.py
check_release_identity: PASS - release identity is aligned for v1.0.0-beta.7.

.\.venv\Scripts\python.exe -m pytest tests/policy/test_release_identity.py -q
10 passed in 1.71s
```

Independent hostile review: PASS after three concrete findings were corrected.
The final review verified priority lowering before model preparation, CUDA-to-CPU
fallback before executor creation, a tap-capacity drop from three to one, no more
than one active CPU call, and consumption of all three channel segments.

## Limits

This local proof uses a fake model loader for deterministic fallback and
concurrency assertions. The next candidate still requires the real Blackwell
captions-on run before captions-on release acceptance.

## Working-tree file hashes

- `civiccast/captions/runtime.py`: `7a8b2a2a8914df755ba0538332ebd5e243ca4fe4856697f2d5984de1d2ec755b`
- `civiccast/captions/tap_worker.py`: `c3c0197d33dff093bd812fdf38ca6b7bd7f64e7e810961d226299b5a8f8fc494`
- `tests/captions/test_captions_core.py`: `9e36882aacadf11e8956dd232a3f5f061815573cc7526517738d644052cf66af`
- `tests/captions/test_caption_tap_worker.py`: `2da663e9c003b67e3e27d6345e464223d6a6a8e34c57ad588f2090a480b125a4`
- `docs/USER-MANUAL.md`: `61b34d54b8634fb28f58464a1cfcf57951062d43a63ac4c65bfdf92a62c2a9c6`
- `docs/ops/background-workers.md`: `136060c20838c3c799b11cff5946513cf7d5fd21a30bde916dd94ecda97df533`
- `CHANGELOG.md`: `6e69826f8717c14f92db05f44ad76adc2783a638dad3d4c72a9e3af654001ee9`


## Pre-push 5-lens self-audit

- Engineering: PASS. The production app injects `FasterWhisperRuntime(live=True)`;
  CUDA capacity is resolved before executor creation, CPU and batch defaults stay
  at one, explicit operator tap overrides remain authoritative, and CUDA fallback
  updates both runtime and tap capacity before dispatch.
- UX: PASS. No UI workflow changed. The user manual now states the CPU and CUDA
  behavior in operator language and keeps the warning that live captions require
  suitable hardware.
- Tests: PASS. The final relevant suite passed 365 tests with one declared
  external-Postgres skip. The three-channel first-scan regression proves model
  preparation ordering, actual fallback, serialized CPU work, and all-channel
  consumption rather than only checking constants.
- Docs: PASS. CHANGELOG, user manual, operations reference, source comments, and
  local verification evidence agree. The captions README contained no conflicting
  default claim and required no change.
- QA: PASS. Cross-file stale-text search found only CPU-specific one-worker text,
  historical evidence, and test fixtures. Ruff, format, mypy, diff, and added-line
  ASCII checks pass.
- Artifact-state: PASS before push. There is no finding ledger, migration, release
  tag, or cleanroom claim in this slice. The changelog says candidate gates are
  outstanding, and Blackwell hardware validation remains explicitly open.
