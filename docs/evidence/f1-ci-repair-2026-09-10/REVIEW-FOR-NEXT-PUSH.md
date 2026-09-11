# Review prepared for the next owner-authorized push

Current CI result: the third cycle finished at 8653b56f with 20 successful,
3 skipped and 1 cancelled check. Unit, claims, randomized, Windows runtime and
reproducibility passed. Mutation exceeded its two-hour job limit after baseline
and forced-fail completion, with a partial 8932/9795 counter; no complete score.
See `CI-THIRD-RESULT.md`. The remaining text is historical local/pre-push proof.

Latest local checkpoint: the owner approved and the lead applied the exact
native count correction. Full policy: 1935 passed, 5 skipped; fresh collections
1823 / 2024 / 2021. See `COUNT-LOCAL-VERIFICATION.md` for the current proof anchor,
five-lens audit and authorized one-push boundary. Text below is historical.

Post-push correction: the second cycle at `2dd9287c` exposed a missed exact
native collection-count assertion. The Engineering/Tests/QA pass conclusions
below are superseded by that finding. See `CI-SECOND-RESULT.md` for the actual
results and the still-unapplied correction. This file otherwise preserves the
pre-push review rather than rewriting its history.

Date: 2026-09-10. This is a local review; no second push has occurred.
Source/proof anchor: `59ef1be6498e5a4eced081d7c412df1176fefdb0`.
The following documentation checkpoint changes no verified source files.
Recheck HEAD, clean state and remote identity immediately before any authorized
push. The post-push SHA/CI propagation step is not yet applicable.

5-lens self-audit:

- Engineering: pass for the local correction scope. All four source/registry
  hashes match the tested files. The actual uv matrix disproves the initial
  inert-bytes hypothesis and proves the corrected execution path. Full-branch
  file inventory contains only F-1 implementation, CI corrections, tests,
  evidence and status documentation. Workflows, release identities and locks
  are unchanged. The four stale claim bindings omitted in the first audit are
  corrected; historical claim IDs and controls are preserved.
- UX: pass for the affected surface. No operator screen or API changed. The
  builder rejects malformed/ambiguous launcher state rather than accepting a
  wrong script. Handoff and report wording distinguish local checks from CI
  and release acceptance.
- Tests: pass for the local scope. All three affected files passed together:
  213 tests. Independent Sol rerun: 88 tests. Red controls reproduced the
  claims failures, harness dependency and uv 0.12.13 execution defect. The
  Windows execution test ran without its platform skip; the smaller cleanup
  tests also run on other platforms. Linux mutmut and full CI are outstanding.
- Docs: pass. CHANGELOG, PROJECT-STATUS, HANDOFF and both verification records
  distinguish the repaired local source from the failed remote CI. The first
  CI result remains historical evidence. A proposed PR-body update is prepared
  in task outputs; the remote PR body remains tied to its actual pushed SHA.
  README/product API/ADRs need no change because these CI corrections do not
  add a product interface, version, release or architectural decision.
- QA: pass for the local handoff. Main is clean at d77b634e; GitHub main matches.
  PR #219 is OPEN at f9b5e1aa with 16 passed, 5 failed and 3 skipped checks.
  Source/proof anchor 59ef1be6 is local only. The existing 795cdab5 kit, F-2 and
  release gates retain their blocked/open status. The prior reproducibility
  pass is not attributed to this changed builder.

Artifact-state: pass for the local checkpoint, with remote acceptance pending.
Git diff whitespace checks pass after preserving original failed-test logs in
an archive and trimming only their readable copies. Added documentation is
ASCII; historical non-ASCII prose elsewhere in the existing documents is
unchanged. Independent-review evidence and each referenced local artifact exist.
No release finding is newly marked closed. The final user report records the
documentation checkpoint SHA; tracked files cite the source/proof anchor to
avoid self-referential hashes.

The mandatory pre-push review is an engineering check, not authorization to
push. Scott's per-action approval is still required for the next push/CI cycle.
