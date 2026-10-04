# HANDOFF

This file is a pointer, not a log.

## Active development checkpoint - 2026-10-03

- Branch: `codex/u73-caption-measurements`.
- Earlier help proof anchor: `2e4db2b61a36179d55bf4a15dd0f2ce954e206de`
  (help links, operator guidance, source illustrations and regenerated built-in
  manual, including continued numbered lists). This is the code checkpoint,
  not a self-reference to the later documentation commit containing this note.
- Verification at that checkpoint: 99 affected UI tests, 49 affected backend
  checks, and an independent final 73-test docsite run passed. These counts
  describe overlapping scoped suites, not a full-product acceptance run.
- No PR or CI run existed for that checkpoint when checked. The test and docs
  workflows run on pull requests; a branch push is not evidence of green CI.
- Candidate PDF/DOCX files remain unaccepted and were not included in that
  checkpoint. Installed help and the full operator workflows still need proof.
- Live meeting recovery now uses explicit channel/session selection and unique
  meeting IDs. Read-only staff and failed authoritative reads cannot enable
  finalization retry. Independent corrected-snapshot checks passed: 42 focused
  UI tests, both prior failing review assertions, four affected isolated browser
  cases, build and manual reproducibility. These are not installed-station tests.
- The latest local diagnostic stopped after two samples when responsive HTTP
  health reported unknown schema readiness. Automatic recovery hit a helper
  task wake-up race; explicit same-request recovery subsequently verified the
  original files, proof settings and three-channel readiness. Health refresh
  phase timing remains under investigation. Opt-in refresh phase diagnostics
  now have independent source-only acceptance: both original diagnostic-failure
  assertions, 47 affected checks and three additional in-flight epoch fences
  passed. The diagnostics do not change readiness rules or prove the live cause.
  No successful soak or caption-fix claim follows.
- Still required before a final recommendation: complete health and caption
  runtime proof, repository/product reconciliation, material operator workflow
  repairs, the exact-package installation lifecycle, and sustained three-channel
  acceptance. No new release, tag, publication or production cutover is implied.

## Published release pointers

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
