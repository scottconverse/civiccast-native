# F-1 first PR CI cycle: blocked

Recorded 2026-09-10 after all jobs completed.

- PR: https://github.com/scottconverse/civiccast-native/pull/219
- Pushed HEAD / CI source: `f9b5e1aa71e8860e8fff41c1cb572b80bbbc8e2b`.
- Local implementation proof anchor: `7a468cd2e9018775926d384ac1b25ebe07ebd18d`.
- Main remains `d77b634e3685de8fb077956b8099fc92c3927243`.
- One branch push and one PR were authorized and performed. No second push,
  rerun, merge, candidate build, Gate A, soak, publication or service start.
- Final check count: **16 passed, 5 failed, 3 skipped**. CI is not green.

## Failures and attribution

1. **F-1 omitted the current-source claim bindings.** The unit suite finished
   18 failed, 10126 passed, 68 skipped, 5 deselected in 2482.69s; coverage 80.15%.
   All 18 failures are in `tests/policy/test_claims_evidence.py`. The randomized
   suite finished 18 failed, 10130 passed, 69 skipped with seed 529518886; all its
   failures are in the same policy file. Both historical claims
   `native-decision-gate` and `session0-service-broadcast` still bind the old
   engine and native-test blobs. The lead missed these four bindings in the
   pre-push audit and local test scope. The all-pass pre-push audit statement is
   superseded for Engineering, Tests, Docs and QA by this finding.

   The dependent claims verifier reported 13 violations: four blob mismatches,
   the failed test producer, and eight missing test/control observations in the
   accepted producer evidence. These must be checked again after correction;
   the failed producer cannot supply a passing claims verdict.

2. **Windows launcher normalization.** The WS4 native suite finished 1 failed,
   2016 passed, 3 deselected. The failing test is
   `tests/native/test_app_payload_builder.py::test_console_launcher_normalization_is_relative_and_non_mutating`.
   The relative interpreter path was present, but the original absolute CI
   Python path remained in the launcher. The earlier green run 34517347338,
   source `ee455b5851983b1a71b9d8d99ae089d10b1ffa36`, used uv 0.12.12 and passed
   2017 tests. This run used uv 0.12.13. The builder, test, workflow and uv.lock
   are unchanged between those sources. Launcher-format drift is a strong
   reproduction lead, not a completed causal proof or repair.

3. **Mutation harness baseline.** The mutation job failed statistics collection:
   1 failed, 10154 passed, 322 skipped, 8 deselected. No mutation score exists.
   The nested pytester process in `test_guard_fails_a_test_that_writes_real_state`
   imports mutmut-instrumented daemon code through an autouse fixture. Mutmut
   tries to discover configuration from the child's temporary directory and
   raises FileNotFoundError during setup. The child reports one setup error and
   one pass, rather than the expected two passes and deliberate teardown error.
   The child command has no `-x`; the lead rejected the initial worker
   explanation that fail-fast stopped the child early. The outer baseline's
   fail-fast behavior only stops after the failed count assertion.

## Passing checks and remaining limits

Lint/type checks, security, policy jobs, documentation rendering, both
accessibility checks, operator build, roadmap, blob guard and virtual headend
passed. Two-workspace Windows payload reproducibility passed in 19m45s.
The three skipped native-beta build/pack/PR checks remain skips; no installer
or tester kit acceptance is inferred. F-1's earlier seven local native tests
and 24 graded commits remain narrow source/runtime evidence. F-2 and all
documented release gates remain open. The old 795cdab5 kit is unchanged.

## Exact CI runs

All runs below bind the pushed HEAD above and are completed.

| Workflow | Run ID | Result |
| --- | --- | --- |
| ci-test | 34530877832 | failure |
| deterministic-detectors | 34530877848 | failure |
| Native Windows app-payload reproducibility | 34530877710 | success |
| ci-a11y | 34530878260 | success |
| egress-virtual-headend | 34530878253 | success |
| ci-blob-size-guard | 34530879371 | success |
| ci-policy-gates | 34530877948 | success |
| ci-security-scan | 34530877757 | success |
| roadmap-status | 34530877657 | success |
| ci-lint | 34530877564 | success |
| ci-operator-build | 34530878086 | success |
| ci-docs | 34530877751 | success |

Run URLs use `https://github.com/scottconverse/civiccast-native/actions/runs/<run-id>`.
Raw logs, checks/runs JSON, Windows JUnit, randomized log and the one-day-retention
reproducibility receipt were preserved under the task's `outputs/F1-CI-evidence`.

## Proposed next action, not applied

The task's `outputs/F1-claims-correction-PROPOSED.patch` contains four binding
substitutions and limiting evidence comments. Terra accepted its content and
`git apply --check` passed. It changes no historical claim text, test node,
control or acceptance status. It is unapplied and untested. After authorization,
apply and run the claims-evidence policy suite and applicable verifier path.
Separately reproduce the launcher test with uv 0.12.12 versus 0.12.13 and the
mutation baseline's nested-process configuration failure. No repair, new local
test run or extra CI cycle has been started for these findings.

This post-CI documentation checkpoint is local only. It follows the pushed
source above and does not change the source tested by CI. A subsequent push
requires the owner's next action authorization.
