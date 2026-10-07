# HANDOFF

This file is a pointer, not a log.

- Latest compaction checkpoint, October 7 about 05:00 MDT: `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-COMPACTION-HANDOFF-2026-10-07.md`. Station and independent 20-minute monitor remain running; 51 eligible completed caption checks passed. Read that checkpoint for owner-directed gaming exclusion, current evidence locations and unresolved whole-drive disk attribution; re-query runtime before reporting fresh status.

- October 6 at 18:01 MDT: owner accepted a **successful eight-hour three-station caption soak**. All 66 sampled channel checks passed; no supervisor restart or logged caption-audio loss/pauses/fallback. Record: [eight-hour dev7 soak](docs/ops/beta11-dev7-eight-hour-caption-soak-2026-10-06.md). Leave the station and monitor running; owner plans to check again tomorrow. This supersedes the earlier four-hour outcome as the latest caption milestone, while preserving its historical defects and current non-caption limitations.

- Owner-directed continuous observation is active from October 6: leave the station running until the owner ends it. Windows task `CivicCast-beta11-readonly-20minute-observer` records every20minutes indefinitely, with no service control or model inference. Measurements and instructions: `C:\Users\scott\Documents\Codex\2026-10-04\rea\work\station-observer\README.md`. First checkpoint completed10:48:38MDT, task result0 and caption checks passed. When the owner ends observation, use these records to write the full performance report; stopping the monitor alone does not authorize stopping the station.

- October 6 bounded-live implementation supersedes the earlier "not implemented" diagnosis below: local dev7 is installed; automatic live review/evidence and retention readiness gates are removed; history is bounded to 300 seconds/512 cues and waiting audio to 12 completed chunks plus owned/writer inputs. Descriptor cleanup is fixed; disposable beta caption tables and files were reset. Whistle primary, Whisper backup and the global inference lock are preserved. Current verification report: `C:\Users\scott\Documents\Codex\2026-10-04\rea\outputs\CivicCast-beta11-bounded-live-implementation-2026-10-06.md`. The 15-minute comparison completed at 10:10:25: 543 Whistle calls, zero logged discards/fallback/pauses, six successful sampled caption-delivery checks; no long-term reliability or public-release claim is made.

- Current beta.11 caption decision and local candidate: [`docs/ops/beta11-whistle-test-candidate.md`](docs/ops/beta11-whistle-test-candidate.md). Whistle primary, Whisper backup/GPU option; dev6 global lock restored; four-hour soak completed October 6 at 02:07 MDT: no fallback; 23/23 output checks passed, but 85s caption audio loss and unresolved loudness/I/O findings prevent a clean pass.

- Historical October 6 overnight diagnosis is recorded in that candidate document: full-table retention reconstruction (1,023,540 review rows; only 24,592 with audio evidence) dominates two captured Python/GIL profiles; stale descriptor cleanup was independently reproduced. At 08:35, that earlier run had discarded 2,480 seconds across three stations. Its repair proposals have now been implemented in local dev7 as described above.

- Current project status: [`PROJECT-STATUS.md`](PROJECT-STATUS.md).
- Current coordinator handoff (decisions, rules, how to resume):
  [`ops/beta10-oversight/HANDOFF-2026-10-01.md`](ops/beta10-oversight/HANDOFF-2026-10-01.md).
- Release evidence: [`docs/releases/v1.0.0-beta.10-verification.md`](docs/releases/v1.0.0-beta.10-verification.md).

`v1.0.0-beta.10` is the current published release (a GitHub pre-release,
published 2026-10-02; Gate A clean-install lane passed 10 of 10, upgrade and
download-only lanes not run, waived by the owner); `v1.0.0-beta.7` is
superseded; `v1.0.0-beta.8` and `v1.0.0-beta.9` were never published.

The long beta.5 to beta.8 handoff log that used to live here is kept, for the
record only, in
[`docs/history/HANDOFF-2026-09.md`](docs/history/HANDOFF-2026-09.md).
