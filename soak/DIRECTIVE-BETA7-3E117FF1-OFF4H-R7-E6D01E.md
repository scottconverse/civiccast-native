# Beta.7 four-hour physical soak R7

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
- Mission: `BETA7-3E117FF1-OFF4H-R7-E6D01E`
- Task: `CivicCast-Beta7-3e117ff1-OFF4H-R7-E6D01E`
- Package source anchor: `9b4c3201a950231d0a1a3584447480a99d87a1e9`
- Package binding commit: `4b4be0b5e29ce3a4d377f4b750b033e4f4cb037c`
- Harness manifest SHA-256:
  `41203fb96115b72655d67a21338ed2ca428aceb7a1f915a642de1a6eb0938954`
- R5 invalidation remote commit:
  `0c90c8bce3f0cbe36af9671a5bbea91116d832a6`
- R5 tester working-byte receipt SHA-256:
  `413005ba893e81bc847d49b645bb5ae518c4101b0ed1b1b7a9e22903f79d0a7e`

## Required execution

Run once:

`soak/autorun/AUTORUN-BETA7-3E117FF1-OFF4H-R7-E6D01E.ps1`

The order must refuse a different host, source, build, Gate A result, R5
invalidation receipt, package manifest, source anchor, mission, task, or
evidence path. It must refuse replay and any concurrently running CivicCast
beta physical task.

The order adopts the already installed and byte-verified beta.7 candidate. It
does not reinstall or rebuild the product. It installs the exact manifest-bound
R7 harness into a new mission root, creates one elevated once-only Scheduled
Task, and starts it. The order does not return success until the physical job's
`STARTED` receipt exists on the tester evidence branch with the exact remote
blob verified.

R6 failed in package preflight before it created a mission root or changed the
station because it required PowerShell 7 on a Windows PowerShell 5 tester. R7
runs tester preflight in the current Windows PowerShell 5 runtime. Dual-runtime
verification remains a mandatory coordinator-side test, and tester-live callers
are checked to ensure they cannot request that coordinator-only mode.

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

A passing R7 run authorizes evaluation of the four-hour gate only. It does not
publish beta.7. The eight-hour overnight soak remains required after this gate
passes, and beta.7 remains unpublished until the release evidence is complete.
