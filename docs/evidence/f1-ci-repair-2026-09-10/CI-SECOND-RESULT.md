# F-1 PR #219: second CI cycle failed

Recorded 2026-09-10 Mountain time. Runs started 2026-09-11 00:34 UTC and the
last workflow finished after 01:09 UTC (still 2026-09-10 Mountain).

- Owner-authorized second push / CI source:
  `2dd9287c8426f21a0464f6d13fb5d5e76cb724fb`.
- Correction source/local-proof anchor:
  `59ef1be6498e5a4eced081d7c412df1176fefdb0`.
- PR: https://github.com/scottconverse/civiccast-native/pull/219 (OPEN).
- Main remains `d77b634e3685de8fb077956b8099fc92c3927243`.
- All 12 workflows finished: **17 passing, 4 failing, 3 skipped checks**.
- No third push or rerun, merge, release kit, Gate A, soak, service restart,
  tag or publication. The proposed count correction has not been applied.

## Observed failure and responsibility

The ordinary, randomized and mutation-baseline test failures all name:

`tests/policy/test_native_caption_workflow_policy.py::test_native_marker_collections_match_the_workflow_floors`

The exact assertion at line 1179 still expects `(1819, 2020)`. Actual collection
is `(1823, 2024)`, as recorded by the Linux CI subprocesses. The four newly added
platform-independent launcher cases increased both native collections by four.
The lead missed this coupled assertion in the repair and pre-push review. The
earlier Engineering/Tests/QA pass conclusions are superseded by this finding.
Local tests and independent review were too narrowly scoped to catch it.

The workflow's minimum floors are still valid and should not be changed for
this correction. The pure count is 1823 versus floor 1774 (49 slack). The
Windows job filters `not integration`, so its count is 2021 versus floor 1971
(50 slack). Both satisfy the documented 50-test margin. The unfiltered total
of 2024 is not the Windows job's filtered count of 2021.

Independent Sol review confirmed the diagnosis and prepared an unapplied
one-file patch updating the assertion and its comment. `git apply --check`
passed against the clean pushed tree. No new local tests or code correction
were performed after this push. The proposal is preserved as
`count-correction-PROPOSED.patch.txt`; it is evidence of a proposal, not applied
source. It needs owner approval, application, fresh collection/full policy
verification and a separately authorized push/CI cycle.

## Exact results

| Check | Result |
| --- | --- |
| Unit suite | 1 failed, 10144 passed, 68 skipped, 5 deselected; 2051.17s; coverage 80.12% |
| Randomized suite | 1 failed, 10148 passed, 69 skipped; 1533.17s; seed 2179285722 |
| Mutation baseline | 1 failed, 7790 passed, 289 skipped, 8 deselected; 1149.51s; no mutation score |
| Windows runtime suite | 2021 passed, 3 deselected; 241.26s; uv 0.12.13 |
| Claims verifier | FAIL: 9 violations; failed producer plus 8 missing accepted test/control observations |
| Windows reproducibility | PASS on the pushed SHA; 9633 files, 482655736 bytes |

The unit JUnit has exactly one failed node, the assertion above. All 125 tests
in `tests/policy/test_claims_evidence.py` and all seven state-guard tests passed
without skips. The claims verifier reported no stale-source blob violations.
Its producer-result rejection means individual passing tests cannot establish
an accepted producer/verifier verdict. The eight missing observations are in
the accepted producer evidence; this is not a claim that all those test nodes
were absent from the raw unit run.

The Windows JUnit confirms the actual launcher execution test and all four new
cleanup cases ran and passed, without skips. Reproducibility is now proven for
this changed builder, not merely inherited from the old cycle. Both downloaded
manifests and SHA256SUMS files match. The producer receipt binds its clean
source to the pushed SHA and reports tree SHA-256:
`cc8e8e9fd30c84666053e1836dea962e448713c3dc75a42be0917fcd239b0edb`.
This CI payload comparison is not a signed installer or tester-kit acceptance.

Mutation stopped early on the count assertion. The instrumented state-guard
test that failed in the first cycle was not reached; that original mutation
case and an actual mutation score remain unproven despite passing ordinary
Linux and local state-guard tests.

## Run identities

All rows bind `2dd9287c8426f21a0464f6d13fb5d5e76cb724fb` and are completed.
Run URL prefix: `https://github.com/scottconverse/civiccast-native/actions/runs/`.

| Workflow | Run | Conclusion |
| --- | --- | --- |
| ci-test | 34547036834 | failure |
| deterministic-detectors | 34547036853 | failure |
| Native Windows app-payload reproducibility | 34547036679 | success |
| ci-a11y | 34547036684 | success |
| ci-lint | 34547036709 | success |
| ci-policy-gates | 34547036705 | success |
| ci-security-scan | 34547036792 | success |
| ci-docs | 34547036740 | success |
| ci-operator-build | 34547036752 | success |
| egress-virtual-headend | 34547036782 | success |
| roadmap-status | 34547036737 | success |
| ci-blob-size-guard | 34547036933 | success |

Raw logs, JUnit, producer metadata, randomized seed/log, all run/check receipts,
and both reproducibility manifests/checksums are preserved in the task's
`outputs/F1-CI-second-cycle/` and the accompanying evidence archive.

F-2 remains unimplemented. The existing beta.6 kit at
`795cdab5065e3b1b1d9df69c6fc06658f481c8d4` is unchanged, unsoaked, ungated and
blocked from publication. No candidate or field acceptance is inferred from
the passing local tests, Windows job or reproducibility result.
