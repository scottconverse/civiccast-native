# Beta.7 four-hour physical soak R14

Status: candidate-specific tester execution order. This is not a release or
publication authorization.

## Exact candidate and tester

- Candidate source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- Version: `1.0.0-beta.7`
- Build run: `34762831824` (`success`)
- Gate A run: `34772707033` (`PASS`)
- Tester: `DESKTOP-VBMA6O5`
- Captions: `OFF`
- Measured duration: four hours, beginning only after stabilization,
  transport admission, and controlled programme-change topology proof
- Mission: `BETA7-3E117FF1-OFF4H-R14-C84E2D`
- Task: `CivicCast-Beta7-3e117ff1-OFF4H-R14-C84E2D`
- Package source anchor: `dedc03471a492a973efd73eb34d903dded2ee5ed`
- Package binding commit: `8bd7bbb236bdf4a6602bd30b44c5f2b31f0677d1`
- Harness manifest SHA-256:
  `56dea7b20562bad3a9ad8ef81c9103408310c47dc8f961c66623f7cadcb233c6`
- R5 invalidation remote commit:
  `0c90c8bce3f0cbe36af9671a5bbea91116d832a6`
- R5 tester working-byte receipt SHA-256:
  `413005ba893e81bc847d49b645bb5ae518c4101b0ed1b1b7a9e22903f79d0a7e`

## Required execution

Run once:

`soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R14-C84E2D.ps1`

The order must refuse a different host, source, build, Gate A result, R5
invalidation receipt, package manifest, source anchor, mission, task, or
evidence path. It must refuse replay and any concurrently running CivicCast
beta physical task.

The order adopts the already installed and byte-verified beta.7 candidate. It
does not reinstall or rebuild the product. It installs the exact manifest-bound
R14 harness into a new mission root, creates one elevated once-only Scheduled
Task, and starts it. The order does not return success until the physical job's
`STARTED` receipt exists on the tester evidence branch with the exact remote
blob verified.

R6 failed in package preflight before it created a mission root or changed the
station because it required PowerShell 7 on a Windows PowerShell 5 tester. R14
runs tester preflight in the current Windows PowerShell 5 runtime. Dual-runtime
verification remains a mandatory coordinator-side test, and tester-live callers
are checked to ensure they cannot request that coordinator-only mode.

R7 failed later in read-only adoption preflight at `directive-package-clean`.
It attempted to use a lone backslash as a PowerShell regular expression while
converting a Windows path to a Git path. R14 performs literal string replacement
for both package adoption and evidence archive paths. Its dual-runtime regression
fixtures execute both exact assignments parsed from the live scripts.

R8 then stopped before station mutation because it expected a running task to
change its state to `Disabled` immediately. A direct Windows Scheduled Task
reproduction showed the correct post-disable state is `Running` with
`Settings.Enabled=false`: the current invocation continues, while future
launches are disabled. R14 checks that actual property and its regression fixture
executes the production disable function with the observed Windows state.

R9 published its remote `STARTED` receipt but the outer launcher rejected it:
adoption had correctly rebound the installed identity to the final directive
commit while the launcher retained its pre-adoption source-anchor object. R14
reloads and validates the installed identity immediately after adoption, before
launching the task or checking its receipt.

R10 passed the outer remote-start gate, then stopped before measurement because
the physical job did not pass the exact IDs from the invalidated R5 schedule
plan into the driver's bounded overlap replacement path. R14 loads the R5 plan
path from the invalidation receipt, verifies its recorded SHA-256 and exactly
180 unique schedule IDs, and permits cancellation only for live overlaps whose
IDs occur in that plan. Any unrelated overlap fails before any cancellation.

R11 correctly cancelled the 21 remaining overlapping R5 rows, then its new
supervisor-restart shutdown barrier timed out and left all three channel configs
disabled. R14 removes that barrier and restores the earlier proven shutdown
sequence: recover enabled command consumption while keeping auto-start off,
preserve every other config field, issue verified stop commands until a full
four-second STOPPED/no-PID quiet window, and reject unsafe disabled-plus-auto-
start intent. Primary failures are retained if cleanup also fails.

R12 reached and completed the exact candidate's controlled programme changes,
but its gate incorrectly treated the beta.5 `elements=146` graph size as a
universal constant. The R12 archive proves the captions-OFF beta.7 graph has
two healthy shapes: `132` for the repeated twelve-segment slate and `33` for a
one-segment scheduled programme. Every 33-element commit had two first-buffer
holds, verified preroll, finite rebase, selector handoff, tail detach, and later
output on the same live channel. R14 binds that archive by SHA-256 and corrects
only this false assertion.

R13 then stopped in package preflight before creating a mission root or changing
the station because Git supplied LF text on the tester and CRLF text on the
coordinator while the harness compared raw file bytes. R14 hashes normalized
UTF-8 text for its manifest and all listed scripts. Its preflight converts a
complete package fixture to CRLF and requires the same manifest hash under both
PowerShell engines.

## Gate behavior

The harness must:

1. Keep captions OFF and disable software fallback.
2. Require all three channels to remain ON_AIR on their original worker PIDs
   for 30 continuous seconds before serialized TSDuck admission.
3. Require one complete controlled programme change on every channel with
   the bound one-segment `elements=33` programme shape before the measured
   clock begins. The bound twelve-segment slate shape `elements=132` may also
   appear. Counts `56`, `74`, or any other count, incomplete transactions,
   wrong source labels, missing live PIDs, worker exits, or output stalls fail.
4. Begin the four-hour measurement only after the three admission probes, the
   controlled transition proof, and a synchronous start receipt.
5. Sample channel state and worker identity every ten seconds, keep captions
   OFF, run eight serialized 30-second TSDuck rounds, and require all channels
   to finish ON_AIR on their original PIDs.
6. Remove every exact mission-owned scheduled or published row, including a
   row whose create request committed without returning an ID, and stop all
   three channels.
7. Publish a PASS only after `evidence.zip`, `job.json`, and `COMPLETION.json`
   are committed, pushed, fetched, and their remote blobs verified.

Any missing or ambiguous evidence is a failure. Preserve failed mission data
and use a new nonce for any corrected rerun.

## Release boundary

A passing R14 run authorizes evaluation of the four-hour gate only. It does not
publish beta.7. The eight-hour overnight soak remains required after this gate
passes, and beta.7 remains unpublished until the release evidence is complete.
