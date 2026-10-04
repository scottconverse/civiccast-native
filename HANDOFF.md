# HANDOFF

This file is a pointer, not a log.

## Active development checkpoint - 2026-10-04

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
- The subsequent nine-sample diagnostic reproduced a readiness failure after
  entering migration-graph inspection. Original runtime files, proof settings
  and three-channel readiness were restored and verified. A source-only repair
  now skips that graph when a fresh database revision exactly matches expected
  head; 52 independent checks passed and the original held-graph negative control
  failed as intended. Installed verification remains pending. A broader shutdown test failed
  identically on baseline and patch; its separate test correction is not part
  of this product-fix checkpoint.
- The separate drain-all test now waits for asynchronous startup and still
  asserts channels drain before automation stops. Independent verification:
  six module tests passed; reversing shutdown order failed the intended
  assertion. This is test correction evidence, not installed lifecycle proof.
- Numeric caption stage diagnostics have source-only independent acceptance:
  20 focused tests plus five independent fault/privacy checks passed. Review
  persistence is not aired-caption success; counts distinguish empty ASR,
  pending/confirmed stabilization, expiry, duplicate/refused review and existing
  generation/publication decisions. Two review defects are closed: refusal
  counting cannot alter the product path, and optional reads stop at collector
  expiry/cap. No live acceptance is claimed. The native stream-end flush fixture
  fails identically on baseline and candidate and remains unchanged; future
  observer numeric-key selection is still separate from frozen trials.
- Proof-worker native prewarm has independent source-only acceptance: 42 focused
  dispatch/lifecycle tests passed, including delayed-start and actual-handoff
  sensitivity. Actual executing-frame capture and the 100ms trial stop remain;
  startup creates only the same three one-shot workers with finite unused waits
  and nonjoining close. A bounded immutable-code dead-slot retention race is a
  cleanup watch item, not false proof. The preceding local trial stopped on a
  102.4ms instrumentation caller-cost receipt; baseline restoration was verified,
  and this was not a product readiness or caption-completeness failure.
  Two outdated native-startup fixtures were separately corrected to honor owner
  admission; two tests pass and reversed startup order still fails both. The
  closed twelve-counter observer selection also passed native independent checks.
  These changes are not yet installed or evidence of a successful soak.
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
