<!-- SPDX-License-Identifier: CC-BY-4.0 -->

## Summary

<!-- One or two sentences. What does this PR change and why. -->

## Line and target

<!-- BRANCHES.md is the source of truth for which branch carries which
product line and where PRs target. -->

- **Product line:** <!-- native Windows line / WSL (main) line / cross-cutting -->
- **Base branch:** <!-- `release/native-beta-1.0.0-beta.1-rc1` for native-runtime changes; `main` for WSL/rc-line and cross-cutting changes -->
- **Spec section(s) touched:** <!-- e.g., §8.2 civiccast-stream, or "none" -->
- **ADR(s) created or updated:** <!-- e.g., ADR 0021, or "none" -->
- **Closed architectural decisions touched:** <!-- "none" or list with justification per CLAUDE.md -->

## Type of change

- [ ] `feat` — new capability
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `refactor` — internal change, no behavior change
- [ ] `test` — tests only
- [ ] `chore` — build / tooling / dependencies
- [ ] `perf` — performance improvement
- [ ] Breaking change (`!` in commit type, `BREAKING CHANGE:` footer)

## 5-lens self-audit

<!--
Mandatory before every push per CLAUDE.md; full rule at
docs/process/5-lens-self-audit.md. Paste the fixed-format report —
each lens is hostile: the diff is wrong until grep/tests/runtime
evidence proves otherwise.
-->

```
5-lens self-audit:
- Engineering: [pass | findings: ...]
- UX:          [pass | findings: ...]
- Tests:       [pass | findings: ...]
- Docs:        [pass | findings: ...]
- QA:          [pass | findings: ...]
Artifact-state: [pass | findings: ...]
```

## Verification evidence

<!--
What was actually run, not what should work. Commands, output, UI states
walked, console state. Point at durable evidence, not descriptions:

- Native-Windows Program slices: commit-bound evidence under
  `.agent-runs/native-windows/<slice-id>/evidence/`.
- Claims-evidence-governed docs (see docs/claims/claims.yaml): the
  registered evidence ids the changed claims bind to.
- Release-candidate-facing changes: the clean-box / sandbox e2e run
  (workflow run id or evidence directory).
- Everything else: the test commands run and their results, plus a
  runtime walkthrough of any user-visible change.
-->

## Pre-merge checklist

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy` passes for changed modules
- [ ] `pytest` passes (scoped to the changed area at minimum; full suite before claiming release-candidate readiness)
- [ ] `pre-commit run --all-files` passes
- [ ] Every commit is signed off (DCO — `Signed-off-by:` trailer)
- [ ] Every commit follows Conventional Commits
- [ ] CHANGELOG entry added (under `[Unreleased]`)
- [ ] Module README and module CHANGELOG updated where applicable
- [ ] No secrets, credentials, or PII in the diff
- [ ] No closed architectural decisions reopened without an RFC
- [ ] Native-line PRs: every review conversation resolved (branch protection blocks merge on open threads)

## Related issues / PRs

<!-- Closes #123, refs #456 -->
