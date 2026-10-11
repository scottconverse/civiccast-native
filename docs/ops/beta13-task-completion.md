# Beta 13 — Whistle recovery and remaining installation work

Owner-authorized objective: execute `C:\Users\scott\Desktop\Goals\# CivicCast — Whistle Recovery and Task Completion.txt`. Scott selected **Beta 13** on October 11, 2026. Engagement: finite release workflow; concurrency, worker lifetime and installation are the named Critical risks.

The current host station and its observer remain running. Source work is on `codex/whistle-recovery-task-completion`, based on main `64058099`. No host cutover is authorized by this development checkpoint.

| Goal | Current state | Evidence required for completion |
| --- | --- | --- |
| 1. Recover Whistle automatically | Implementation in progress | Transient failure/fallback/recovery; failed recovery/backoff; serialized probes; no duplicate output; close invalidates outstanding recovery |
| 2. Coordinate watchdog and backlog | Implementation in progress | 10-second warning, 30-second Whistle deadline, finite backlog grace and sustained-overload bounds |
| 3. Preserve diagnostics and show recovery | Implementation in progress | Bounded error output, pre-termination counters/exit status where available, request identity and operator recovery state |
| 4. Fresh installation and startup | Pending final candidate | Exact-candidate setup, first administrator and three-channel audio/video/captions |
| 5. Post-upgrade observation | Pending final candidate | Saved state preserved and five usable observation snapshots |
| 6. Interrupted-install recovery | Pending final candidate | One controlled isolated interruption and repair with state preservation |
| 7. Deliver consistent release | In progress | Independent review, affected checks, signed candidate, applicable installation results, manuals/help/site/version consistency, publication, D kit and cleanup |

## Execution sequence

Consolidate the runtime, backlog, diagnostic, UI and installation-check corrections; obtain independent review; run the focused consolidated checks; produce the final candidate; perform the requested installation scenarios sequentially; publish and verify downloads; update the D kit and remove disposable staging. No new soak, elaborate harness or autonomous correction/check/rebuild cycle. Escalate a failed final check with its diagnosed cause rather than silently starting another cycle.

Existing Beta 12 public-download setup and activation success remain historical results. Its failed startup checker and incomplete upgrade recorder do not establish Beta 13 results. The Beta 11 48-hour/99.88% input-coverage result remains Beta 11 evidence. Target-machine sustained testing is owner-managed and outside these goals. Scott controls release acceptability; numerical caption results are not automatic release vetoes.

## Initial evidence

- Alerting status baseline: `python -m pytest tests/alerting/test_runtime_status.py -q`: 47 passed. Two new recovery-state assertions failed because the existing API parser converted them to `unknown`, before their implementation.
- Whistle baseline: `python -m pytest -q tests/captions/test_whistle_runtime.py`: 25 passed. Recovery regression failed at `recovery probe did not start after cooldown` before implementation.
- Host supervisor PID 6208 remains running at task start. C: had approximately 392 GiB free; no guest was launched or installer run.

## Consolidated review before final checks

- Independent Sol 6.1 Medium review found that the first failed recovery probe repeated the initial 30-second delay; the correction uses 60, 120, 240 and then 300 seconds. It also identified two adjacent raw error logs needing the diagnostic sanitizer. The generated API type will be regenerated after the version update.
- The review found recovery ownership, probe-result discard and close invalidation coherent, but the initial new test established only successful recovery. The requested failure, shutdown, serialization, silence and watchdog cases are being added to the existing focused test file before the consolidated check.
- Tap-worker baseline: 117 passed. Before correction, the four-case regression run had three expected failures: premature shedding after 30 seconds, a 12-file queue instead of the proposed 42-file limit, and an unbounded retained-evidence path. The sustained-overload expiry case passed.
- Whistle's 210-second backlog grace and default 42 waiting five-second WAVs are finite starting policy values. Process startup and lock scheduling can add waiting; these values do not guarantee worst-case completion or zero discarded audio. Generic Whisper behavior remains unchanged.
- Read-only host check at 10:49 MDT on October 11: supervisor PID 6208 unchanged; public, government and education each had current audio/video and VTT files.

## First consolidated check — not passed

- Python focused run: **304 passed, 26 failed in 50.31 seconds** across Whistle, tap/backoff, alerting and publisher tests. No model or native speech process was loaded.
- Two Whistle failures: the silence test fake keeps returning silence after promotion while its assertion expects speech (fixture defect); the diagnostic sanitizer misses a Windows drive path immediately following other text (implementation defect).
- Twenty-four publisher failures: historical Beta 12 fixtures inherit the newly bumped current version while retaining the old interrupted-upgrade contract. Separately, the physical-host caption-advisory predicate names only Beta 12, omitting Beta 13 (release-policy implementation defect). Saved successful note generation confirms the healthy physical cases are failing on missing advisory copy, not unsuccessful installation.
- Operator UI: **26 tests passed**; the two affected files passed ESLint. TypeScript failed because the new test indexes an optional `channels` array without narrowing it. This is a test-fixture type error.
- The first Ruff pass reported 16 style findings in the new runtime/test code; it stopped before formatting. These findings are unresolved.
- Independent Sol 6.1 Medium read-only diagnosis consolidated the minimal corrections. No failed check was rerun and no post-failure source correction was made. Scott has been asked to authorize one consolidated correction/check pass and then the signed build, in accordance with his October 10 no-loop instruction. Until that instruction arrives, build/publication remain pending.
- Scott authorized **“Finish the consolidated correction/check, then build”** at 11:00 MDT on October 11. Sol 6.1 Medium owns the consolidated runtime/publisher correction; root corrects the UI test fixture. One affected check pass follows, then the signed build if it passes.

## Authorized correction check

- Ruff formatting completed; the affected nine Python files passed Ruff.
- Python focused run: **317 passed, 13 failed in 49.25 seconds**. Whistle recovery, backlog/backoff and alerting checks passed, including the previously failing silence and sanitizer cases. All 13 remaining failures report the same manual-receipt fixture version mismatch: the historical Beta 12 publisher tests invoke a shared receipt writer that still reads the real Beta 13 source version.
- Operator TypeScript and affected-file ESLint passed. The preceding 26 successful UI tests were not repeated after the type-only fixture correction.
- No second correction was made automatically. Scott was asked whether to authorize the single remaining historical fixture correction plus publisher-only check, or start the build with this test bookkeeping deferred. Signed build and installation scenarios have not started.
- Beta 13 source/package identity is aligned (`check_release_identity.py`: PASS). Generated OpenAPI/types/API reference identify Beta 13 and the new recovery states. The in-product manual was regenerated and its existing currentness check passed; `git diff --check` passed. Published release-truth/download targets remain Beta 12 until actual Beta 13 publication.

## Installation preparation and manual finalization

- The existing workspace fresh/upgrade/repair drivers are now wired for the future exact Beta 13 candidate. The upgrade driver installs the verified Beta 11 baseline, upgrades, captures the existing five observations, interrupts once, repairs using the same candidate, and captures the required repair observations. Fresh installation uses a separate sequential guest. No installer or Sandbox guest has run.
- Windows PowerShell 5 parsed all six affected driver/checker scripts successfully. This proves syntax only; candidate binding and actual installation remain pending the signed build.
- The manual source now describes Beta 13 recovery, the 10-second warning/30-second hard watchdog and finite queue, with Beta 13 installation and verification references. Historical Beta 11/12 evidence remains identified by its original version.
- Final manual readback found one Chapter 10 helper command still using `-Install` alone. It must include explicit Beta 13 tag/version arguments in the next authorized correction. Generated manual artifacts are stale after the source edits and must be regenerated once after that correction; the earlier currentness pass does not cover these edits.
- The pending owner decision remains unchanged: authorize the shared publisher-fixture correction and publisher-only check before building, or proceed to build with historical test bookkeeping deferred. No further correction/check cycle or build was started while awaiting that decision.

## Owner-authorized final fixture check and candidate freeze

Scott selected **“Fix fixture, check publisher, then build.”** The two fixture receipt writers now bind their explicit candidate versions only during fixture generation; production verification is unchanged. The remaining Chapter 10 helper command now specifies Beta 13, and the in-product manual was regenerated from the finalized source.

Command: `.venv\Scripts\python.exe -m pytest tests/release/test_publish_beta_candidate.py -q --tb=short`
Result: **127 passed in 15.91s**. Full output: workspace `outputs/beta13-publisher-final-check.log`. No caption or UI test suites were repeated.

Pre-push five-lens review: engineering — recovery ownership/backoff/serialization and finite queue policy independently reviewed, implementation checks pass; UX — fallback-selected wording avoids claiming delivery when unavailable; tests — previously failing recovery/backlog/status cases and historical publisher cases now pass in their recorded affected runs; docs — current manual, generated help, API types and candidate identity aligned, public downloads remain Beta 12 until publication; QA/artifact state — no Beta 13 installation, artifact, signature or publication pass claimed before execution. No dependencies, credentials or migrations were added. Existing untracked oversight evidence is excluded from the commit. `git diff --check` passed. The 210-second queue policy is finite and is not a worst-case delivery guarantee.

The next step is one hosted signed candidate build, followed by the requested sequential installation scenarios against that exact package. No host cutover or soak is included.

## Limited corrections clarification and CI bookkeeping

Scott clarified October 11: limited necessary correction/check/rebuild cycles are allowed; the objection is repeated broad cycles consuming hours or days. Routine small corrections need no permission question. This supersedes the earlier blanket-cycle interpretation above.

Signed candidate remains **8053fb1cf05b989fb1f23e650893cc6abfa659d4**, workflow **38160778457**, draft PR **239**. The exact-source manual job passed. Commit **912e9771** corrected only test-file wrapping; it did not trigger another signed build.

Subsequent CI reached mypy and found its generic integer-power inference returning Any in the capped delay expression. Independent Sol review verified the exponent is clamped to 0..3 and float arithmetic returns float, added a documented suppression only for that return, and compared executable AST before/after: unchanged. Command `uv run mypy civiccast/captions/whistle.py`: **Success: no issues found in 1 source file**. No recovery tests, full-suite checks or installer build were repeated. This typing-comment follow-up does not change candidate runtime behavior; artifact provenance remains the original actual source SHA.

Five-lens review of these follow-ups: engineering — no executable expression changed; UX — unchanged; tests — existing 127-pass publisher result still applies to whitespace-only fixture change, no verification weakened; docs — this record distinguishes frozen artifact source from later bookkeeping; QA/artifact state — no new build/signature/install pass claimed and original artifacts remain bound to their actual source/run.

## Build progress and documentation reconciliation

Workflow 38160778457 completed the station-bundle and exact-source manual jobs successfully. The signed installer job remains in progress; no replacement build was started. The exact-run PDF and DOCX were copied into the tracked download locations without rerendering. Their original candidate manual receipt remains in the workspace artifact directory.

Automatic PR CI reported 11,245 passes, 87 skips and 18 failures in its randomized suite. The failures concern documentation assertions, missing explanatory text and stale generated manual downloads. A consolidated focused check of those 18 cases passed 12 and failed six; the remaining failures concern assertion normalization and the render manifest's build-output paths. Sol is correcting this bookkeeping, preserving the signed application candidate.

The copied fresh-install guest driver omits the inherited generative-summary test because that is outside the requested fresh-admin/three-channel/startup/help scope. No summary result is claimed. Both installation guests retain the existing 9,216 MiB limit and must run sequentially. At the owner's latest memory recheck, 12.49 GiB was available; no Sandbox guest was running. Recheck memory at launch. The live CivicCast service remains running and unchanged.

The focused documentation corrections finished with 12 passes in the first 18-case run, five passes in the six-case follow-up, and one pass after replacing the remaining obsolete Sigstore prose assertion with checks of the actual plain-sidecar/`attestation: null` contract. Thus all 18 previously failing cases have passed in affected checks; no full-suite pass is claimed. The local tracked manual render manifest now points to the tracked `docs/` files; its source, hashes and sizes are unchanged from the exact-run artifacts, whose original receipt is preserved separately.

Pre-push five-lens review of this documentation/bookkeeping batch: engineering — application runtime and frozen manual/quickstart sources unchanged, actual hosted manual bytes retained; UX — silent-install heartbeat and provider billing explained; tests — helper verification, candidate/published distinction, scoped historical evidence and unsigned-pack warnings remain asserted, stale retired-release prose removed; docs — current public downloads remain Beta 12 while the Beta 13 application build is unfinished; QA/artifact state — no installer success, Sandbox result or publication pass claimed. The frozen installer source remains 8053fb1cf05b989fb1f23e650893cc6abfa659d4.
