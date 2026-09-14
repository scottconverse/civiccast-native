# Finalize beta.7 R5 invalidation publication

Status: implementation order; execution is not authorized by this file alone.

## Exact target

- Tester: `DESKTOP-VBMA6O5`
- Repository: `https://github.com/scottconverse/civiccast-native.git`
- Branch: `tester/soak8-e1acfe6-DESKTOP-VBMA6O5`
- Directive commit: the exact committed HEAD containing this directive and the
  recovery autorun; the autorun refuses modified or untracked order bytes and
  records that HEAD in `INVALIDATED.json`
- Candidate source: `3e117ff1fa9e06873ecec5b5b07f1360bc8b228d`
- Invalid mission nonce: `BETA7-3E117FF1-OFF4H-R5-E27A91`
- Existing task: `CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91`
- Recovery order:
  `soak/autorun/AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91.ps1`
- Remote job:
  `soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/job.json`
- Remote invalidation receipt:
  `soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/INVALIDATED.json`

The earlier order
`AUTORUN-00-BETA7-INVALIDATE-R5-E27A91.ps1` already has its once-only `.done`
marker. Preserve that marker. This is a new once-only order with a distinct
filename and marker; it exists only to recover the failed receipt publication.

## Allowed work

The recovery order may perform read-only inspection of Task Scheduler,
processes, CivicCast GET endpoints, exact R5 local files, and Git state. After
every verification passes, it may overwrite only the two remote evidence paths
listed above, make one signed-off evidence commit, pull/rebase as needed, push,
fetch, and compare the exact staged blobs with the remote blobs.

It must not restart a service, write a channel config, issue a channel command,
stop or kill a process, cancel a schedule row, remove either autorun marker,
launch R5 or R6, change `LATEST-TEST-DIRECTIVE.md`, install a candidate, or
alter any file outside the two named evidence paths.

## Required read-only verification

Before writing either evidence path, halt unless all of these are true:

1. The first invalidation order's exact `.done` marker exists and is hashed
   into the recovery receipt.
2. The exact R5 scheduled task exists and its state is `Disabled`.
3. No process command line matches the exact R5 mission root together with the
   R5 output or task identity.
4. `public`, `education`, and `government` each read back
   `enabled=true` and `auto_start=false`.
5. All three channel states are exactly `STOPPED` with no worker PID.
6. The local installed R5 identity, local job, one physical run identity,
   published plan, run verdict, captions-OFF profile, and
   `STOP-VERIFIED.json` exist and bind the exact candidate, mission,
   240-minute duration, and captions-OFF phase. `STOP-FAILED.json` must be
   absent, and both the local job and run verdict must be `FAIL`.
7. No live `scheduled` or `published` row on any owned channel has either the
   exact R5 notes (`Owned <R5 run_id>`) or an ID from the preserved R5
   published plan.
8. The tester directives checkout is on `soak8-e1acfe6-directives` with the
   exact GitHub origin, and the recovery script and this directive are tracked,
   clean HEAD bytes. The separate evidence checkout is on the exact tester
   return branch and has no unrelated change.

Any failed or unavailable check is a halt. Absence of evidence is not success.
The order must not publish `INVALIDATED` after a verification failure.

## Publication contract

The recovered `INVALIDATED.json` must contain every read-only verification,
the exact source and mission identities, the invalid-reason list, the directive
commit, script and directive SHA-256 proofs, the full set of preserved R5
schedule IDs, and a SHA-256 of its verification payload.

The recovered `job.json` must retain the exact R5 source and mission, set
`job_state` to `INVALIDATED`, state that R5 is not release evidence, and record
the final invalidation receipt SHA-256 and verification-payload SHA-256.

Git calls must use a native process wrapper with stdout and stderr captured
separately. Normal Git progress on stderr is evidence text, not a PowerShell
terminating error. Pull/rebase and push are limited to three attempts, and each
native Git process has a time bound. Success requires a fetch of the return
branch followed by exact equality between both staged local blob IDs and both
remote blob IDs.

The autorun result printed into the coordinator log must record:

- `status=R5_INVALIDATION_PUBLISHED_AND_VERIFIED`
- invalidation receipt SHA-256
- invalidated job SHA-256
- staged and remote blob IDs for both files
- exact remote commit
- exact directive commit
- verification time

## Dry-run and acceptance

`-DryRun` is safe on the coordinator. It performs no tester API call, no Git
invocation, and no mutation. It validates the exact constants, parses the full
PowerShell AST, checks the required recovery functions, and rejects service,
task, process, schedule, or tester-API mutation commands.

Acceptance requires both Windows PowerShell 5.1 and PowerShell 7 to parse the
script without errors and to return `DRYRUN_VERIFIED`. Execution on the tester
is a separate authorization and must use the committed order bytes.

After a live execution, R5 may be described only as **invalidated evidence**.
This order supplies no R6 authorization, no physical acceptance result, and no
release or shipment claim.
