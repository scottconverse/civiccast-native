# Stage 2 Operator Workflow

Audience: playback operators, meeting operators, and station admins validating the Stage 2 daily station path.

## Daily Three-Channel Station Check

Use this pass before a station treats the day as ready:

1. Open the operator console and confirm System Health is safe to broadcast.
2. Confirm the public, government, and education channel rows are present.
3. Confirm each channel has current schedule material and a filler fallback.
4. Confirm the media library shows every scheduled item as validated.
5. Confirm the program guide and channel operation screens agree on now/next.
6. Create or refresh the support bundle after any blocked state.

The local proof runner models this as a three-channel station with public,
government, and education channels, 18 scheduled items, validated media library
entries, and filler coverage.

## Every-Screen Walkthrough

Stage 2 completion requires an every-screen walkthrough artifact, not just a
modeled station JSON. The walkthrough evidence covers desktop, mobile, keyboard,
role-limited, empty/seeded, loading, and error-copy observations for the operator
health, channel operations, program guide, media library, recording, and reports
surfaces.

Keep `every-screen-walkthrough.json` with the Stage 2 support bundle. Treat the
stage as incomplete if the walkthrough does not list route-by-route observations.

## Live Workflow Rehearsal

The local Stage 2 proof also records a live workflow rehearsal through the
operator UI/API boundary. It must show channel creation or refresh, generated
media ingest, schedule placement, conflict detection, record-now, stop recording,
output verification, and as-run emission.

Keep `live-workflow-rehearsal.json` with the Stage 2 support bundle. A
deterministic proof without this live workflow rehearsal is not enough to close
Stage 2.

## Media Library And Playout

Every scheduled item must have an asset that is present, validated, and has
basic FFprobe-style video and audio metadata. If media is missing, replace the
slot with filler or relink the file before air. Do not treat an item as ready
because it appears on the calendar; the media library state has to agree.

## Recording Source Coverage

Stage 2 recording source checks cover the source families a PEG station is
likely to use:

- SDI
- HDMI
- NDI
- RTSP
- SRT
- HLS
- RTMP
- MPEG-TS

Use labels that match real equipment names. Operators should not need to decode
transport acronyms during a meeting or live event.

## As-Run And Proof

After scheduled playout or recording, export or inspect the as-run proof. It
should identify the station, channel, schedule item, asset, scheduled time,
actual start/end, duration, source kind, and verification status.

Keep the proof with the daily evidence folder when testing a release candidate.
If the as-run ledger is absent, treat the workflow as incomplete even if the
viewer preview looked correct.

The record-now and stop recording path must also leave a generated media output
that can be verified by the proof runner. Missing output verification blocks
Stage 2.

## Failure Handling

Stage 2 requires these operator-visible failure states:

| Failure | Surface | Operator action |
| --- | --- | --- |
| Missing media | Program Guide | Relink the file or replace the slot with filler. |
| Source-dropout | Recording | Reconnect the source; keep the partial capture and retry. |
| Destination-failure | Channel Ops | Retry the destination while local recording and portal output remain visible. |
| App restart | Support Bundle | Export the latest workflow, as-run, and recording state. |

Failures must leave local media and partial recordings intact unless the
operator explicitly deletes them under station policy.

The Stage 2 support bundle includes `failure-drills.json`, which records the
failure drill trigger, operator surface, recovery expectation, and result for
each required failure scenario.

## Support Bundle

Create a support bundle whenever a Stage 2 station path is blocked or degraded.
The bundle should include the station workflow, as-run ledger, recording jobs,
every-screen walkthrough, live workflow rehearsal, failure drills, failure
matrix, operator action list, and proof summary. It must redact secrets and must
not include provider credentials, tokens, passwords, private keys, database
passwords, subscriber data, or private meeting content.
