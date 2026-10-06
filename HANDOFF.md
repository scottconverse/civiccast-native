# HANDOFF

This file is a pointer, not a log.

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
