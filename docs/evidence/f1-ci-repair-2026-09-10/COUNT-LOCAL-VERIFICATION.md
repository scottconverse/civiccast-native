# Exact native inventory correction: local verification

Recorded 2026-09-10 Mountain. Scott authorized the reviewed one-file repair,
fresh native collections, full policy verification and, conditional on passing,
one push to PR #219 for one new CI cycle. No merge or release action is authorized.

Source/proof anchor: `104e722f9e15d19828736a10090e8b508778faef`.
Changed source: `tests/policy/test_native_caption_workflow_policy.py`.
Git blob: `09989d13d26ca5fcc2e6466ab8012e160cf17ea5`.
Branch: `fix/f1-reload-readiness-20260910`. Main remains `d77b634e`.
The following documentation checkpoint changes none of the tested source.

The exact tuple advances from (1819, 2020) to (1823, 2024) for the four
platform-independent launcher regression cases introduced by the prior repair.
The applied source matches the previously reviewed proposal. The proposal file
and second-cycle result remain historical evidence, not a pending action.

## Executed local verification

Python 3.12.10, existing locked `.venv312`; commands used
`UV_PROJECT_ENVIRONMENT=.venv312 uv run --frozen --no-sync`.
All pytest sessions were serialized. No new dependencies or services were started.

- Before edit: the exact collection regression failed in 19.86s, showing actual
  (1823, 2024) against expected (1819, 2020).
- After edit: `python -m pytest tests/policy -q --tb=short` with a JUnit receipt:
  **1935 passed, 5 skipped in 255.56s**. Both collection-policy tests ran/passed.
- Five local skips: one absent installer gauntlet harness, three tests of the
  retired rc-numbered release line, and the DB normalizer self-exemption.
  These are local policy results, not installer or clean-box acceptance.
- A separate receipt script called the policy's real subprocess collection
  helper for all three selections: pure `not windows_only` = **1823**,
  unfiltered = **2024**, Windows workflow `not integration` = **2021**.
- Workflow minimums remain 1774 and 1971; slack is 49 and 50, within the
  existing allowed margin of 50. The Windows total is filtered, not 2024.
- Repository `ruff check .` passed; `ruff format --check .` reports 1541 files
  already formatted. `mypy civiccast` passed for 675 source files.
- Independent Sol agent `/root/ci_review` accepted the actual one-file diff,
  found no other active count assertion or claims binding to update, and ran
  no tests. Lead independently executed the verification above.

Raw logs, JUnit, collection receipt and helper, and independent review are in
`count-local-evidence.zip`. The four prior repaired source/registry files still
match `59ef1be6498e5a4eced081d7c412df1176fefdb0`; their earlier evidence remains
historical proof for those identical files.

## Pre-push hostile five-lens SELF_REVIEW

- Engineering: pass. The actual source diff is one tuple and its explanation;
  four added launcher cases account for the delta. Workflow floors, locks,
  runtime source and claims are unchanged. Full-PR file inventory remains F-1,
  its CI repairs, tests, evidence and status documentation only.
- UX: pass for this scope. No operator-facing behavior or UI copy changes.
  Reports distinguish collection repair, CI acceptance and release acceptance.
- Tests: pass locally. Fresh red control, complete policy suite and explicit
  three-way collections prove the new tuple and existing floor margins.
  The five local skips are disclosed. New Linux mutation/CI results are pending.
- Docs: pass locally. CHANGELOG, PROJECT-STATUS, HANDOFF and verification entry
  points link here. Earlier results remain labeled historical. README, API and
  ADRs need no update: no product interface, version or architecture changed.
- QA: pass locally. The clean proof commit identifies tested source. The remote
  second-cycle result remains red at 2dd9287c until this authorized new cycle
  runs. No F-1 release finding is newly closed; F-2 and release gates stay open.

Artifact-state: local checkpoint checked; mandatory post-push SHA/CI/handoff
propagation is pending. Historical proof anchors are retained deliberately.
Added documentation is ASCII; existing non-ASCII historical text is unchanged.
No migration, SA model, tag candidate or new cleanroom claim is introduced.
The only permitted next external mutation is the authorized push and PR status
update. The existing 795cdab5 beta.6 kit remains blocked and must not be published.
