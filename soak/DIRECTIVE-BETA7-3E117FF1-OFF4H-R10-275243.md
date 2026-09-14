# Beta.7 four-hour physical soak R10

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
- Mission: `BETA7-3E117FF1-OFF4H-R10-275243`
- Task: `CivicCast-Beta7-3e117ff1-OFF4H-R10-275243`
- Package source anchor: `b865de5867f3343e1ecd70bfa989168fbeafc73b`
- Package binding commit: `149e9e3372a6b5546ab0bcfc09b0cbd801ca6152`
- Harness manifest SHA-256:
  `74ec5842ed82a84446b8fcc8fdea688ad6166d97d1425de055ac16d693144adc`
- R5 invalidation remote commit:
  `0c90c8bce3f0cbe36af9671a5bbea91116d832a6`
- R5 tester working-byte receipt SHA-256:
  `413005ba893e81bc847d49b645bb5ae518c4101b0ed1b1b7a9e22903f79d0a7e`

## Required execution

Run once:

`soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R10-275243.ps1`

The order must refuse a different host, source, build, Gate A result, R5
invalidation receipt, package manifest, source anchor, mission, task, or
evidence path. It must refuse replay and any concurrently running CivicCast
beta physical task.

The order adopts the already installed and byte-verified beta.7 candidate. It
does not reinstall or rebuild the product. It installs the exact manifest-bound
R10 harness into a new mission root, creates one elevated once-only Scheduled
Task, and starts it. The order does not return success until the physical job's
`STARTED` receipt exists on the tester evidence branch with the exact remote
blob verified.

R6 failed in package preflight before it created a mission root or changed the
station because it required PowerShell 7 on a Windows PowerShell 5 tester. R10
runs tester preflight in the current Windows PowerShell 5 runtime. Dual-runtime
verification remains a mandatory coordinator-side test, and tester-live callers
are checked to ensure they cannot request that coordinator-only mode.

R7 failed later in read-only adoption preflight at `directive-package-clean`.
It attempted to use a lone backslash as a PowerShell regular expression while
converting a Windows path to a Git path. R10 performs literal string replacement
for both package adoption and evidence archive paths. Its dual-runtime regression
fixtures execute both exact assignments parsed from the live scripts.

R8 then stopped before station mutation because it expected a running task to
change its state to `Disabled` immediately. A direct Windows Scheduled Task
reproduction showed the correct post-disable state is `Running` with
`Settings.Enabled=false`: the current invocation continues, while future
launches are disabled. R10 checks that actual property and its regression fixture
executes the production disable function with the observed Windows state.

R9 published its remote `STARTED` receipt but the outer launcher rejected it:
adoption had correctly rebound the installed identity to the final directive
commit while the launcher retained its pre-adoption source-anchor object. R10
reloads and validates the installed identity immediately after adoption, before
launching the task or checking its receipt.

## Gate behavior

The harness must:

1. Keep captions OFF and disable software fallback.
2. Require all three channels to remain ON_AIR on their original worker PIDs
   for 30 continuous seconds before serialized TSDuck admission.
3. Require one complete controlled programme change on every channel with
   `elements=146` before the measured clock begins. Counts `33`, `56`, `74`,
   any other count, incomplete transactions, worker exits, or output stalls
   fail the run.
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

A passing R10 run authorizes evaluation of the four-hour gate only. It does not
publish beta.7. The eight-hour overnight soak remains required after this gate
passes, and beta.7 remains unpublished until the release evidence is complete.
