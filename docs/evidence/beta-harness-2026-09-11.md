# Beta candidate harness corrections - September 11, 2026

Candidate source: `39e7ec3cbb4ccbeb3009ff3257dfc314010151f3`.
Successful build: [34633364038](https://github.com/scottconverse/civiccast-native/actions/runs/34633364038).
Installer SHA256: `906d64eda23731a9ca7160734e2bca5727e35d1bb6997b45a35f01e8a343f63e`.
Its 20-file kit manifest matched and Authenticode status was Valid.

The measured Sandbox run lasted 120.09 minutes, from 1:39 PM to 3:39 PM Mountain.
Each channel's final worker log has 241 commits, all with matching transaction
preroll and the stable caption-OFF topology count of 33. Zero worker exits,
commit timeouts, stalls, restarts or aborted reloads were recorded.

The original soak verdict incorrectly failed with a blank channel name. Empty
pipeline output assigned without an array capture becomes null; the verdict's
`@($null).Count` is one. Root reconstructed the missing-commit set using all three
channels and their raw counts, captured it as an array, and reran the unchanged
grader on all 116 saved cycles. It passed 113 evaluated cycles after three warmup
cycles. Passing a real missing channel still failed. Luna independently executed
the same reconstruction under Windows PowerShell 5.1. Original evidence remains
unchanged under `sandbox-lab/soak-output/soak-39e7ec3-20260911-192316Z` in the
coordinator's canonical checkout. Regrade receipts are in the task's `outputs/`.

[Gate A 34651334966](https://github.com/scottconverse/civiccast-native/actions/runs/34651334966)
then passed installation, activation, rendering, clerk loop, caption generation,
and its health soak. It failed T4: `/openapi.json` returned 401 because the harness
omitted its existing staff token. That prevented egress route discovery and
triggered an FFmpeg fallback, correctly rejected by the product-engine gate.
Upgrade and download-only lanes did not run.

This patch supplies the existing token to both schema-discovery requests and
preserves the soak caller's array result. It changes no installer/runtime bytes,
API access policy, gate thresholds or verdict requirements. The next Gate A run
uses the corrected harness revision and the same candidate build/source above.
Physical-host caption ON/OFF timing and lifetime checks remain outstanding.

## Focused verification

- New Windows PowerShell 5.1 regression executes the actual API helper and both
  discovery call sites with a transport that requires authorization. It also
  executes the actual soak assignment for zero, one and two missing channels.
  Before the fix it failed both requests and empty/single-item captures; after
  the fix it passed. It checks that the generated test token is absent from logs.
- Existing SoakVerdict tests: 70/70 passed under Windows PowerShell 5.1.
- Existing Gate A Python contracts: 98 passed in 3.77 seconds using the frozen
  project environment. These checks do not substitute for a new Gate A run.
- Independent Luna review executed both PowerShell suites and recommended MERGE.

## Five-lens self-audit

- Engineering: PASS; both existing bearer variables reach the existing helper.
- UX: PASS; no operator UI changes; release status remains explicitly pending.
- Tests: PASS; executable regressions failed before and passed after the fix.
- Docs: PASS; README, CHANGELOG and HANDOFF identify candidate and harness scope.
- QA: PASS; original failure evidence preserved, candidate identity unchanged,
  Gate A and physical-host acceptance remain outstanding.
- Artifact-state: PASS for this harness diff; no publication claim is made.
