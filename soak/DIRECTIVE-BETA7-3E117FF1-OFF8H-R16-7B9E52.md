# Beta.7 eight-hour physical soak R16

Status: candidate-specific tester execution order. This is the final physical
soak gate before the authorized beta.7 release decision.

## Exact candidate and tester

- Candidate source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- Version: `1.0.0-beta.7`
- Build run: `34762831824` (`success`)
- Gate A run: `34772707033` (`PASS`)
- Tester: `DESKTOP-VBMA6O5`
- Captions: `OFF`
- Measured duration: eight hours after admission and controlled-transition proof
- Mission: `BETA7-3E117FF1-OFF8H-R16-7B9E52`
- Task: `CivicCast-Beta7-3e117ff1-OFF8H-R16-7B9E52`
- Package source anchor: `e84b7a3a43e17b851476549df1d55ba87406dff5`
- Package binding commit: `8eec10107839e76e1bffa5a2fe5eaec728501481`
- Harness manifest SHA-256:
  `b839d948fa21be1d3054bbe3561c240f81be204b968685e9ab3d9e9a6acb7baf`

## Prior gate result

R15 completed its full four-hour measured clock. Independent posthoc grading
of its preserved terminal logs establishes a product-gate PASS: 4,320/4,320
ON_AIR state samples, stable worker PIDs, 144/144 programme changes, 480/480
healthy service samples, 24/24 clean transport probes, and zero worker exits,
partial graph commits, transaction failures, or output stalls. The original
R15 job receipt remains FAIL because its collector mistook normal 10 MiB log
rotation for truncation. The exact re-derived proof is recorded in
`physical-soak-off4h-r15-4f9b22/R15-POSTHOC-VERIFICATION.md`.

## Required execution

Run once:

`soak/autorun/AUTORUN-BETA7-3E117FF1-OFF8H-R16-7B9E52.ps1`

The order adopts the already installed, byte-verified candidate. It does not
rebuild or reinstall CivicCast. It must refuse a different host, source, build,
Gate A result, package, manifest, mission, task, prior invalidation receipt, or
evidence path. It must refuse replay and any concurrently running beta physical
task. It may return success only after the physical job publishes its exact
STARTED receipt and verifies the remote blob on the tester evidence branch.

R16 keeps the R15 product checks and fixes only the proven collector defect.
It binds the premeasurement generation by length and SHA-256 prefix, follows
normal `control_plane-app.log` rotation across the retained generations, and
fails closed for a missing, ambiguous, truncated, gapped, or evicted checkpoint.
Its preflight exercises no rotation, one rotation, two rotations, regrown active
log, truncation, eviction, and a failure marker spanning rotation under Windows
PowerShell 5.1 and PowerShell 7.

## Gate behavior

The harness must:

1. Keep captions OFF and software fallback disabled.
2. Require all three channels ON_AIR on stable worker PIDs for 30 seconds before
   serialized TSDuck admission.
3. Require a complete controlled programme change on every channel, including
   preroll, finite rebase, selector handoff, old-tail detach, a bound healthy
   topology (`elements=33` programme or `elements=132` slate), and later output.
4. Start the eight-hour clock only after admission and topology proof.
5. Sample state every ten seconds and run sixteen serialized transport rounds
   at 30-minute offsets from minute 0 through minute 450.
6. Fail on a worker exit, PID change, stopped channel, partial graph, incomplete
   transaction, output stall, invalid sync, transport error, or discontinuity.
7. Remove every mission-owned schedule row, stop all three channels, preserve
   evidence, and publish PASS only after the archive, job, and completion blobs
   are committed, pushed, fetched, and remotely verified.

Any missing or ambiguous evidence is a failure. Preserve failed mission data
and use a new nonce for any corrected rerun.

## Release boundary

A passing R16 run completes the remaining physical soak gate for the exact
beta.7 candidate. Release publication still requires verifying the returned
evidence and the exact source, build, Gate A, manifest, installer, and tag
bindings before publishing.
