# Successful eight-hour three-station caption soak — October 6, 2026

**Result: successful eight-hour live-caption soak**, accepted by the owner. The station remains running for a longer observation; this is a milestone, not the end of the run or a public-release approval.

The local dev7 caption overlay ran from **09:53:23 to at least 18:01:41 MDT on October 6: eight hours eight minutes**. Supervisor PID remained **28760**. Whistle was the CPU primary on all three stations, with Whisper backup, the global inference lock and first-pass publication preserved. Runtime source candidate: `01406ad794ae09138135354e0440d73a2b1ac2ad`; the base station still identifies as beta.9 rather than a complete beta.11 installer.

## Results

- **22 completed scheduled checkpoints**, each with successful caption delivery checks on all three stations: **66 successful sampled channel checks**. A fresh stream check at 18:01 also found all three streams healthy. Earlier short verification is documented separately.
- No supervisor restart, logged caption-audio discards, caption overload pauses or Whistle fallback in the observed interval.
- Review/job tables remained empty; audio-evidence directories stayed empty. Current live captions remained a rolling window rather than accumulating the entire broadcast. Working-audio snapshots stayed small.
- Recorded timing intervals through 17:47 contain **17,038 native Whistle calls**. Mean **1.178 seconds**, median **1.187**, P95 **1.359**, maximum **3.422**. These are recognition execution times, excluding global-lock waiting and end-to-end caption latency.

| Station | Calls | Mean | Median | P95 | Maximum |
|---|---:|---:|---:|---:|---:|
| Public | 5,679 | 1.180s | 1.187s | 1.344s | 3.422s |
| Government | 5,679 | 1.172s | 1.172s | 1.360s | 2.422s |
| Education | 5,680 | 1.182s | 1.187s | 1.359s | 2.266s |

## Memory and storage

First resource checkpoint: **10:47**; milestone's latest completed checkpoint: **17:47**. There is no equivalent resource baseline at the 09:53 service start.

- Available system RAM increased from **16.753 to 17.043 GiB**, about **297 MiB more available**. Persistent recognition-process memory stayed approximately steady; these measurements do not establish that total application RAM decreased by that amount or prove absence of every possible leak.
- Drive free space changed from **587,870,142,464 to 587,469,860,864 bytes**: approximately **400 MB additional drive usage**, leaving **587.5 GB free**. This is whole-drive usage, not all attributable to CivicCast.
- Monitoring records occupied about **7.3 MB** when checked shortly afterward. Temporary monitor stream captures are removed after each check; no continuous media recording is retained by the monitor.
- Empty caption-review/job relations occupied **24,576/32,768 bytes** at the latest checkpoint. Audio-evidence folders remained empty.
- A later directory inspection found approximately **48.4 GB conform cache** and **22.5 GB channel egress data**, chiefly prepared video. These are large existing media/preparation areas, not caption evidence. Their individual starting sizes were not recorded, so their contribution to the net drive change and long-term growth cannot be established from this milestone alone.

## Non-caption findings and limits

Two government boundary program-change attempts failed at 11:22 and 11:55 and triggered retries while logs reported the outgoing program kept airing. Relay stderr files reached their size caps around 14:28–14:32 and were trimmed without restarting the relay. These observations are retained for the longer-run report; they do not turn this into an all-subsystems clean pass.

Caption delivery was sampled every 20 minutes, with logs recorded between samples. A successful soak does not prove perfect transcription accuracy or exclude every brief interruption. Release-grade integrated loudness was not measured. This milestone does not establish multi-day reliability, a green full-repository suite, complete installer qualification or public-release readiness.

Content came from existing downloaded media imported under `C:\ProgramData\CivicCast\data\uploads`. The catalog held 30 assets and approximately 24.6 GB registered media. Program rollovers occurred during observation.

## Evidence

- Scheduled task: `CivicCast-beta11-readonly-20minute-observer` — indefinite 20-minute repetition, still active.
- Checkpoint records: `C:\Users\scott\Documents\Codex\2026-10-04\rea\work\station-observer`, checkpoints `20261006-104659` through `20261006-174659`.
- Frozen milestone statistics: `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-dev7-eight-hour-milestone-2026-10-06.json`. Raw per-call timing counts match their checkpoint totals.
- Tail log check through 18:01:41: `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-dev7-eight-hour-tail-events-2026-10-06.json`.
- Continuing-run instructions: checkpoint root `README.md`. Leave the station and monitor running; the owner plans to check again tomorrow.
