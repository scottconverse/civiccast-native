<!-- SPDX-License-Identifier: CC-BY-4.0 -->

# Stage Completion Gate

The fixed, non-discretionary verification gate for declaring a stage (or any
"DONE" milestone) complete. Defined after the Stage B+D audit (TEST-003/W-9):
a hand-picked pytest subset scoped to touched files let two Blockers ship —
a forked migration graph (11 failing tests the gate never ran) and a worker no
deployment ever started. The gate's contents are not chosen by the person
being gated.

## Tiers

**Interim commits** (inside a stage): targeted test subsets are fine for the
inner loop. Run what you touched plus anything your change plausibly reaches.

**Stage completion** (before a result file says DONE / "Tests: PASS"): all of
the following, every time. `scripts/run_stage_gate.ps1` runs the mechanical
checks and fails loudly on any miss.

1. **Full `pytest` — 0 failures.** Named exclusions only, listed in the result
   file with the reason (e.g. `tests/platform/test_nats_broker_real.py` and
   `tests/schedule/test_schedule_conflict_properties.py` error at collection
   when `testcontainers`/`hypothesis` are absent from the venv). The result
   file's "Tests: PASS" line **must cite the full-suite count** (passed /
   failed / skipped).
2. **`alembic heads` returns exactly one head.** (Also enforced by
   `tests/db/test_migration_graph_guards.py` inside the full suite.)
3. **Repo-wide `ruff check .`** and **`ruff format --check`** on the stage's
   touched files.
4. **`mypy`** scoped to at least every file the stage touched.
5. **OpenAPI artifact check** — `python scripts/generate-openapi-artifacts.py
   --check` (generated artifacts match the app).
6. **`git diff --check`** (no whitespace damage).
7. **Runtime walkthrough** — boot the deployed app (uvicorn factory, real DB,
   real env config) and drive the stage's headline flow over HTTP. Library
   tests do not satisfy this: "tested in isolation" is not "wired into running
   software". A present-tense deployed-behavior claim in any doc requires this
   step.
8. **Declared environment gaps** — an explicit section in the result file
   naming what could NOT be verified in this environment and where it will be
   (e.g. no Docker → real-Postgres behavior deferred to the clean-room pass;
   no Node.js → portal typecheck/build deferred). Unverifiable claims are
   declared, never silently passed.
9. **Stage report artifact** — write the machine-readable and Markdown stage
   envelope with `scripts/stage_report.py`. The report ties source state,
   release artifacts, clean Windows proof, and required check evidence together
   and fails closed when clean install proof or release artifacts are missing.

## Running the mechanical checks

```powershell
# from the repo root, with the project venv's python on PATH or via full path
powershell -ExecutionPolicy Bypass -File scripts/run_stage_gate.ps1 `
    -Python C:\CivicCastTester\tools\venvs\audit-sprint-1\Scripts\python.exe `
    -MypyTargets "civiccast/live civiccast/app.py"
```

The script prints PASS/FAIL per check and exits non-zero on any failure.
Checks 7 and 8 are human steps; the script reminds you of them.

## Writing the stage report

Use `scripts/stage_report.py` after the required checks and runtime evidence
exist. The command writes `stage-report.json` and `stage-report.md` under the
chosen artifact root and exits non-zero unless every required check and required
evidence item passed.

For Stage 1, use the release-gate orchestrator so the full test stack, release
artifact build, clean Windows proof runner, and fail-closed stage report stay in
one repeatable command:

```powershell
uv run python scripts/run_stage1_release_gate.py
```

Use `--dry-run` to print the commands without executing them. The final command
still fails closed through `scripts/stage_report.py` if any earlier step fails or
if the release manifest / clean Windows proof artifacts are missing or blocked.

```powershell
uv run python scripts/stage_report.py `
    --stage-id 3.3 `
    --stage-name "Install, First Run, Local Gate Foundation" `
    --artifact-root artifacts/stage-reports/3.3-stage1-final `
    --release-manifest artifacts/release/v3.3.0-stage1/civiccast-3.3.0-release-artifacts-manifest.json `
    --clean-windows-evidence artifacts/clean-windows/3.3-stage1-final/clean-windows-install.json `
    --check "full-stack|Full stack baseline|passed|powershell -ExecutionPolicy Bypass -File scripts/run_full_test_stack.ps1|artifacts/test-runs/<final-source-bound-run-id>" `
    --check "first-run-attestation|Isolated first-run attestation|passed|uv run python scripts/run_isolated_first_run_attestation.py --artifact-root artifacts/first-run/3.3-stage1-final --profile-root artifacts/first-run/3.3-stage1-final/profile|artifacts/first-run/3.3-stage1-final" `
    --check "stage1-lifecycle-proof|Stage 1 installer lifecycle proof|passed|uv run python scripts/run_stage1_lifecycle_proof.py --artifact-root artifacts/stage1-lifecycle/3.3-stage1-final --clean-windows-evidence artifacts/clean-windows/3.3-stage1-final/clean-windows-install.json --first-run-evidence artifacts/first-run/3.3-stage1-final/first-run-attestation.json --release-manifest artifacts/release/v3.3.0-stage1/civiccast-3.3.0-release-artifacts-manifest.json|artifacts/stage1-lifecycle/3.3-stage1-final/stage1-installer-lifecycle-proof.json" `
    --check "gauntletgate-all|GauntletGate all lanes|passed|gauntletgate all|artifacts/gauntletgate/3.3-stage1-final"
```

A `passed` stage report is not a replacement for the actual logs. It is the
index that points to those logs and keeps advancement claims tied to current
evidence.
