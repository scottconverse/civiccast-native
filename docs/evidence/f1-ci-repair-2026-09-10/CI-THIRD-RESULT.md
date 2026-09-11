# PR #219: third CI cycle complete, mutation campaign incomplete

Recorded 2026-09-10 Mountain. The authorized one-file count correction was
applied, locally verified and pushed once. All 12 workflows finished:
11 succeeded; deterministic-detectors ended cancelled because mutation-report
exceeded its two-hour limit. PR checks: **20 SUCCESS, 3 SKIPPED, 1 CANCELLED**.
The PR check UI categorizes that cancellation as a failed check.
This is not an entirely green CI cycle, although ci-test and claims passed.

- Pushed remote PR / CI SHA: `8653b56f8623cb5fa8e3855f26b64296e814526f`.
- Count-correction source/local-proof anchor:
  `104e722f9e15d19828736a10090e8b508778faef`.
- Branch: `fix/f1-reload-readiness-20260910`.
- PR: https://github.com/scottconverse/civiccast-native/pull/219 (OPEN).
- Main remains `d77b634e3685de8fb077956b8099fc92c3927243`.
- Third-cycle runs began 2026-09-11T03:28:10Z; the last job completed
  2026-09-11T05:28:31Z (9:28 PM to 11:28 PM Mountain on September 10).

## Correction and local proof

Only `tests/policy/test_native_caption_workflow_policy.py` changed source in
this repair: the exact tuple (1819, 2020) became (1823, 2024), accounting for
four new launcher regression cases. Workflow minimum floors remain unchanged.
Fresh collection reproduced the old failure before editing. After editing,
the full policy suite passed: **1935 passed, 5 skipped in 255.56s**.
Separate real collections returned 1823 pure, 2024 total, 2021 Windows filtered.
Floor slack remains 49 and 50, within the existing allowed margin of 50.
Ruff check/format passed for 1541 files; mypy passed for 675 source files.
Sol independently accepted the actual one-file diff and checked other count
and claims bindings. See `COUNT-LOCAL-VERIFICATION.md` and its raw archive.

## Same-SHA CI results

- [ci-test 34558549832](https://github.com/scottconverse/civiccast-native/actions/runs/34558549832):
  **PASS**. Unit job 103136324941: 10145 passed, 68 skipped, 5 deselected in
  2466.20s; coverage 80.15%. Dedicated native pure lane: 1823 passed,
  201 deselected in 45.37s. JUnit confirms all 125 claims-policy cases,
  all 7 state-guard cases and the corrected inventory assertion passed.
  Claims verifier job 103144168781 reports PASS with a successful producer
  bound to this SHA, run ID and run attempt 1.
- Windows job 103136324836 in the same ci-test run: **2021 passed, zero skipped,
  3 deselected in 196.27s**. The actual relocated launcher execution and all
  four new cleanup cases ran and passed. Three integration cases are filtered
  by the workflow; the unfiltered count 2024 is not this job's expected count.
- [deterministic-detectors 34558549841](https://github.com/scottconverse/civiccast-native/actions/runs/34558549841):
  randomized-suite job 103136324907 **PASS**, seed 2673792843. Main suite:
  10149 passed, 69 skipped in 2165.46s. Native pure: 1823 passed,
  201 deselected in 110.46s. Mutation-report timed out; details below.
- [Windows reproducibility 34558549734](https://github.com/scottconverse/civiccast-native/actions/runs/34558549734):
  **PASS**, clean source at the pushed SHA. Two workspace builds matched
  9633 files / 482655736 bytes. Downloaded manifests and checksum lists also
  match. Tree SHA-256:
  `f7d6833b78702f0ee681215e4d22c743ed18de7cb90579f01653083f6b49bc72`.
  This is app-payload CI proof, not installed-candidate or soak acceptance.
- Lint/types, policy, security, docs, operator build, both accessibility checks,
  egress virtual headend, roadmap and blob guard passed. Three native-beta
  build/pack/PR checks took their configured skips; no release-candidate kit was built here.

## Mutation timeout: what is proved and what is not

Job 103136324760 ended CANCELLED at 05:28:31Z. Its annotation explicitly says
the job exceeded the maximum execution time of 2h0m0s. The agent did not cancel
it. No further push or rerun occurred.

The selected changed non-test Python scope against main was:

- civiccast/egress/daemon.py
- civiccast/egress/gst/engine.py
- scripts/build_native_app_payload.py
- scripts/ops/check_reload_preroll.py

The log records mutant generation completed at 03:59:22.6921499Z; the clean-test
phase began at 03:59:26.5193179Z and completed at 04:27:49.5703182Z; the forced-fail
control completed at 04:28:45.3094369Z; mutation testing began immediately after.
This cycle therefore progressed beyond the earlier baseline failures.
The included guard regression no longer prevented the instrumented clean-test
phase from completing. That is baseline-level evidence, not a named per-node
receipt or proof of the guard running against every mutant.

The final recorded progress counter at 05:28:22.3455995Z was **8932/9795**.
This is a partial status counter, not a count of successful tests. The job was
cancelled before its final results/completeness gates finished. There is
**no complete mutation result set or score**. No numeric score is inferred
from the partial categories. The workflow is informational and does not enforce
zero survivors or a minimum score even when it completes successfully.
An independent Sol review confirmed these evidence distinctions.

Raw job logs, annotations, JUnit, producer metadata, final run/PR snapshots,
reproducibility records and independent interpretation are preserved in
`ci-third-cycle-evidence.zip`. `verified-results.json` indexes the receipts.
The earlier unavailable-log request returned HTTP 404 while the job was active;
that request result is not a CI test failure.

## Audit, authority and next proposed work

Five-lens SELF_REVIEW before the authorized push passed for the local correction.
The post-push review now records:

- Engineering: pass for the exact count repair and unchanged prior source.
- UX: pass for this scope; no operator UI or API changed.
- Tests: count/claims/harness/runtime checks passed; finding remains that the
  mutation campaign did not complete within its two-hour budget.
- Docs: pass; PR, handoff, status, changelog and verification entry points
  distinguish exact local proof, pushed CI source, completed checks and timeout.
- QA: the count blocker is cleared in local, unit and randomized runs. The
  mutation result is incomplete; F-1 release acceptance and F-2 remain open.

Artifact-state: final SHA/run/result propagation is recorded. Historical proof
anchors are retained deliberately. This local documentation checkpoint follows
8653b56f and is not another push. Get its own HEAD with `git rev-parse HEAD`;
the external final report records it after commit. No release finding was
newly marked closed. Main and the existing 795cdab5 kit are unchanged.

The openai-multi-agent skill was used in OPENAI_ONLY mode: earlier Luna claims
work, Terra launcher work and Sol review are preserved; this small correction
used lead implementation plus independent Sol review. Sol also reviewed the
mutation result semantics. No Claude or local-model calls were used.

Proposed next local ticket, requiring the owner's next per-action authorization:
the existing F-2 three-channel regression with a blocked preparation callback
and five-minute boundaries including :25/:50/:55. First prove whether one
channel blocks the others, and record exactly which gate defers each due reload.
The mutation campaign's runtime/completeness issue remains tracked separately.
No F-2 implementation has started. No merge, new kit, Gate A, soak, service
restart, tag or publication occurred. **The existing beta.6 kit must not be published.**
