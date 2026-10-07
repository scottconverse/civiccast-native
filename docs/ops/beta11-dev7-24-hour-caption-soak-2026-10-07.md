# Accepted 24-hour three-station caption soak — October 7, 2026

Owner accepted the completed 24-hour soak as sufficient soak evidence for Beta 11 release on October 7. The station and independent monitor remain running; acceptance does not issue a stop command.

## Tested runtime and scope

The dev7 local overlay ran from October 6 at 09:53:23 MDT through the 24-hour milestone on October 7 at 09:53:23 MDT. A fresh check at 10:30:42 confirmed the same supervisor process (28760), with all three streams healthy, extending runtime to 24 hours 37 minutes.

Source candidate: `01406ad794ae09138135354e0440d73a2b1ac2ad`. Whistle CPU primary on all three channels, Whisper backup/CUDA option, shared inference lock, first-pass caption publication, disabled Needle telemetry, bounded live working state, and no automatic live review/evidence retention. This is the local overlay on the existing station; the health version remains beta.9. It is not proof of a packaged Beta 11 installer.

## Caption evidence through the 24-hour milestone

- 66 eligible completed checkpoints, all caption verdicts OK: 198 successful sampled channel checks.
- Four checkpoints overlapping the owner-excluded gaming interval are omitted from pass/fail and recognition totals. No gaming degradation is counted or reproduced here.
- Last completed included checkpoint before the milestone: `20261007-094700`.
- Supervisor stayed running. The previously accepted eight-hour result remains documented separately.
- Empty live caption-review and offline-job tables at the last included checkpoint.

| Station | Native calls | Mean | Median | P95 | Maximum |
|---|---:|---:|---:|---:|---:|
| Public | 15,601 | 1.179 s | 1.187 s | 1.359 s | 3.422 s |
| Government | 15,601 | 1.179 s | 1.187 s | 1.359 s | 2.515 s |
| Education | 15,600 | 1.177 s | 1.187 s | 1.360 s | 2.359 s |

Native recognition times exclude shared-lock waiting and end-to-end caption latency. Checks prove sampled caption decoding, freshness and continuity, not semantic transcription accuracy or uninterrupted coverage of every second.

## Resources and limits

Latest milestone checkpoint: available system RAM 17.84 GiB; drive free space 566.51 GB. Whole-drive space changes are not automatically attributable to CivicCast; game recordings/caches and Windows app updates were separately investigated. See the local disk-investigation report in the coordinator outputs directory.

Program-transition retries, lost acknowledgements and bounded relay-log trims have been observed during the longer run; sampled captions passed. This is caption soak acceptance, not an all-subsystems clean-pass claim. Short monitor captures do not establish release-grade loudness. Packaging, source/artifact identity, applicable installer checks and public artifact validation still need their own release evidence.

## Evidence

Raw checkpoint directories and aggregate records: `C:\Users\scott\Documents\Codex\2026-10-04\rea\work\station-observer`. Existing eight-hour record: [accepted eight-hour soak](beta11-dev7-eight-hour-caption-soak-2026-10-06.md). Candidate: [Beta 11 caption candidate](beta11-whistle-test-candidate.md).
