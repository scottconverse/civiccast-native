# Current-source claims review, 2026-10-04

This is a D2 source-review receipt, not installed release acceptance. The July
native decision-gate and session-0 observations remain historical. Their original
prose, timing and limitations are not reclassified as current results.

The committed 2fd8a22a source was archived separately from the dirty checkout.
The two existing registry-bound real-worker tests ran with that source and the
exact extracted eb94 package's Python 3.12.10 / GStreamer 1.28.5 runtime: two
passed, zero skipped. Actual generated transport streams had zero continuity
counter errors and backward PCRs (build: 2485 packets / 150 PCR samples; swap:
1062 / 22). Actual child commands used the archived worker source and unique
private named pipes. This is current-source/old-packaged-runtime integration,
not next-package or installed service proof. Separate import hashes are not a
live-loaded-module attestation.

Current engine SHA256 is
`95F7F05AD06047A4A03D1E357A2343F510EBEEFE321F33251BD1BAD53B260E0B`,
different from eb94's engine. Worker, graph, reload-policy and strategy bytes
match eb94. The bounded fallback audio-tail correction has sensitive source
RED/GREEN and independent ordering review. These two real-worker cases generate
video-only output and do not prove that audio correction. Next-package audio
transition, installed boot/pre-login and representative sustained soak remain
pending. Neither historical spike nor this source check supplies those results.

The workflow binding was reviewed separately: locked Windows FFmpeg acquisition
and native collection floors changed; the main same-run producer, exact artifact
routing and evidence contracts did not. Raw eb94 CI JUnit contains all six bound
Postgres backup/restore, SQLite positive/falsification and release-truth
positive/unknown-live nodes passing without skips. That overall unit job still
failed other cases. Every new head must produce its own same-run evidence; these
results do not mark a new CI run or release green.

Raw private engineering evidence is retained under the oversight workspace:
`evidence/u87-current-registry-worker/` (source archive, JUnit, actual worker
logs/argv transcript and TS outputs), `evidence/u87-ci-eb94-37230256695/`, and
the corresponding U87 current-worker, audio-tail and relay-tail reports. No
historical evidence bytes or unfinished rollback bindings were modified.
