# U87 product type contracts - v2

Scope: CI-blocker cleanup in `C:\Dev\Claude\civiccast-u73`, branch `codex/u73-caption-measurements`. Initial HEAD `d258e46d47226fc1ed84d6d55c44be37da670582`; final checks at HEAD `fe4a52ffb355d45d7e8051df80da065934b983f3` plus the uncommitted product/test changes below. The HEAD advance was the coordinator's unrelated ops/security checkpoint. No commit/push, station/helper/VM/GPU operation, package install, download, or heavy build performed here. These are local source checks, not installer, running-station, or release proof.

## Changes and semantic boundaries

- `civiccast/captions/diagnostic_identity.py`: preserve repeated reads of mutable `_CLOSED` using `bool`, rather than deleting checks which mypy incorrectly narrows across thread startup; explicitly narrow absent elapsed-time operands to the same `None` result previously obtained by exception suppression; retain typed descriptor locals before assigning them into the heterogeneous JSON payload; construct the same three version integers explicitly. No lock, wait, dispatch, payload-field, or clock changes.
- `civiccast/captions/pipeline.py`, `worker.py`, `tap_worker.py`: structural `CaptionPhaseTiming` protocol and context-manager annotations preserve injected collectors/forwarders, optional timing, and exception propagation. `tap_shed_diagnostic.py` updates the corresponding explanatory comment only.
- `civiccast/egress/ts_relay.py`: `CaptionProofTarget` describes the existing five validated JSON fields; the narrow cast occurs only after the existing closed-key, value, ownership, and destination checks. Annotate the forbidden-port set as admitting `None`, which the existing algorithm already stores and which cannot equal a candidate integer port. No port-selection logic change.
- `civiccast/egress/caption_proof_worker.py`: use the receipt contract for fences and a narrow cast for the config whose non-None state is implied by having captured that identity. Capture freshness and current-config comparisons are unchanged.
- `civiccast/egress/caption_proof_process.py`: annotate the existing yielded SQLAlchemy `Session`; its factory/finalization is unchanged.
- `civiccast/egress/automation.py`: reuse the daemon's existing source-plan callable contracts and explicitly check the already-implied non-None plan in the non-fallback branch. No ordering, source selection, or timing policy changes.
- `civiccast/live/router.py`: narrow the existing dependency result to the production session-store contract before listing sessions. No route/auth/dependency behavior change.

One actual runtime defect was found, separately from these static-contract repairs: publish counters become `None` when a diagnostic receipt is unavailable, then later unconditional `+= 1` can interrupt caption processing. `_increment_stage_count` now preserves unknown totals without inventing counts. It is called only on the existing diagnostic paths and introduces no clock, scheduling, locking, storage, or acceptance-policy change. Four regression cases in the existing `tests/captions/test_caption_stage_outcomes.py` cover later accepted/rejected publication, session reset, and storage refusal. Accepted/rejected cases also assert that the actual nonempty committed cue reaches the original publication delegate unchanged. No new test or measurement harness was added.

Root-owned `phase_timing.py`, upgrade/installer files, HANDOFF, and pyproject were not edited by this agent.

## Exact checks and results

All commands below ran in `C:\Dev\Claude\civiccast-u73`, using `C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe`. Unless stated otherwise, no environment override was applied.

Initial static baseline:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m mypy civiccast
```

`Found 29 errors in 9 files (checked 688 source files)` (root's two phase-timing errors had already been repaired). Final command, also captured in `U87-TYPE-CONTRACTS-mypy.txt`: `Success: no issues found in 689 source files`. The source-file count increase includes parallel upgrade work, not a type-check scope reduction.

Initial focused test baseline:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_stage_outcomes.py tests/captions/test_caption_identity_prewarm.py tests/captions/test_caption_identity_dispatch.py tests/captions/test_caption_diagnostic_probe_identity.py tests/captions/test_caption_phase_timing.py tests/egress/test_ts_relay.py tests/egress/test_caption_proof_worker.py tests/egress/test_caption_proof_process.py tests/egress/test_automation.py tests/egress/test_automation_plan_warm_lookahead.py tests/live/test_router.py -q
```

`83 failed, 251 passed in 75.41s (0:01:15)`. All 83 failures were in `tests/live/test_router.py` on staff authentication. First failure: `TestCreateSession.test_201_returns_canonical_session`, line 351, `assert r.status_code == 201`, actual `401 Unauthorized`. The next seeded-session failure showed `{"detail":"Invalid staff bearer token."}`. Setup logs warned about ephemeral stores, first-party bearer auth, and missing operator/public portal dist. This agent did not establish the root cause from those messages and did not alter authentication. The coordinator's separate auth-test agent subsequently isolated an inherited `CIVICCAST_STAFF_TOKENS` environment-contamination lead in an owned child process; its clean-environment reconciliation is separate evidence, not claimed as completed here.

Runtime defect RED, before changing increments:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_stage_outcomes.py -k unknown_publication -q --tb=short
```

`4 failed, 20 deselected in 2.75s`; all four failed on `TypeError: unsupported operand type(s) for +=: 'NoneType' and 'int'` in the later publication-counter increment. The test was then strengthened to assert real nonempty cue publication.

Final sensitivity check restores old unguarded increment behavior only inside an owned test process, without modifying source files:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -c "import importlib, pytest; plugin = type('CounterSensitivity', (), {'pytest_configure': lambda self, config: setattr(importlib.import_module('civiccast.captions.tap_worker'), '_increment_stage_count', lambda counts, key: counts.__setitem__(key, counts[key] + 1))})(); raise SystemExit(pytest.main(['tests/captions/test_caption_stage_outcomes.py', '-k', 'unknown_publication', '-q', '--tb=short', '-o', 'addopts='], plugins=[plugin]))"
```

`4 failed, 20 deselected in 1.41s`, all on the same nullable increment, captured completely in `U87-TYPE-CONTRACTS-sensitivity.txt`. An earlier exploratory in-process substitution imported the module before pytest configuration and failed during bootstrap with `pytest.PytestAssertRewriteWarning: Module already imported so cannot be rewritten; anyio`; that attempt was not test evidence. The corrected plugin installs the substitution after normal pytest configuration and does not suppress warnings.

GREEN on unchanged source after sensitivity process exit:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_stage_outcomes.py -k unknown_publication -q --tb=short -o addopts=
```

`4 passed, 20 deselected in 1.91s`, captured in `U87-TYPE-CONTRACTS-regression.txt`.

Final affected-suite widening:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_stage_outcomes.py tests/captions/test_caption_identity_prewarm.py tests/captions/test_caption_identity_dispatch.py tests/captions/test_caption_diagnostic_probe_identity.py tests/captions/test_caption_phase_timing.py tests/captions/test_caption_tap_worker.py tests/captions/test_caption_tap_batch_diagnostic.py tests/captions/test_caption_tap_shed_diagnostic.py tests/egress/test_ts_relay.py tests/egress/test_caption_proof_worker.py tests/egress/test_caption_proof_process.py tests/egress/test_automation.py tests/egress/test_automation_plan_warm_lookahead.py -q -o addopts=
```

`439 passed in 54.60s`, captured in `U87-TYPE-CONTRACTS-tests.txt`. This run deliberately excludes the separately-owned auth-path reconciliation, not failing caption/egress cases. The same expanded set had previously returned `439 passed in 54.92s`; final regression assertions were strengthened and rerun.

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m ruff check .
```

`All checks passed!`, captured in `U87-TYPE-CONTRACTS-ruff.txt` and repeated after formatting. No mypy/ruff suppression was added by this agent.

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m ruff format --check civiccast/captions/diagnostic_identity.py civiccast/captions/pipeline.py civiccast/captions/worker.py civiccast/captions/tap_worker.py civiccast/captions/tap_shed_diagnostic.py civiccast/egress/automation.py civiccast/egress/ts_relay.py civiccast/egress/caption_proof_worker.py civiccast/egress/caption_proof_process.py civiccast/live/router.py tests/captions/test_caption_stage_outcomes.py
git diff --check
```

`11 files already formatted`; diff whitespace check emitted no output and passed. Initial formatter check identified three files; they were formatted with Ruff and then rechecked.

## Focused self-review and remaining proof

Engineering: callable/data contracts match existing consumers; repeated close checks, context-manager exception propagation, relay freshness, and source-plan fallback remain intact. UX: no operator-visible string or acceptance-policy change. Tests: actual four-case runtime RED/GREEN plus sensitivity against the old nullable increment and 439 affected cases passed. Docs: static contract comments updated; this versioned receipt explicitly separates the runtime defect from static changes. QA: no new runtime scheduling/storage state or checker-scope reduction; all local checks are source-level, not live installation/operation proof.

Standard lane: this unit changes a diagnostics arithmetic guard, not concurrency policy; the surrounding threading/install context is not itself a changed Critical contract. Remaining work belongs to the coordinator: auth-environment reconciliation, integrated candidate/CI/release proof, and running-station/soak acceptance. Do not call this a full working release.

proved: 439 affected tests passed; four regression cases fail under old increment and pass under fixed source; full product mypy and full Ruff check passed; lane: Standard

## v2 documentation sync

Added a narrow Unreleased/Fixed entry in `CHANGELOG.md` and a matching caption-diagnostics bullet in `civiccast/captions/README.md`. Both state that an unavailable publication aggregate remains unknown while later cues continue through the existing publication checks. Both exclude startup-backlog shedding and packaged/installed acceptance. No new setup step, link, supported-platform claim, or public API change. The existing caption module has no separate CHANGELOG.

After this docs-only edit, `git diff --check` passed with no output and the following command returned `24 passed in 2.13s`:

```powershell
& C:\Dev\Claude\security-python-f23ca5a7f58f\.venv\Scripts\python.exe -m pytest tests/captions/test_caption_stage_outcomes.py -q -o addopts=
```

The coordinator also reported an independent affected run of `158 passed in 47.76s`; that receipt belongs to the coordinator and is not substituted for this agent's checks. Files are released to the coordinator for review/commit. No commit or push performed by this agent.
