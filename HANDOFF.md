# HANDOFF

This file is a pointer, not a log.

## Active development checkpoint - 2026-10-04

- Packaged candidate source is `84a283077f4ba9359113c7bbf4189095393c08bc`,
  verified remotely on PR 232; original self-hosted build 37204600121 is
  running. Its signed station bundle passed; installer/package proof is pending.
  Candidate CI: installer compile 37204558280 and docs 37204558277 passed;
  lint 37204558284 failed and tests 37204558265 are still pending overall
  with the Windows job failed. No merge or release claim.
- Next-source copy checkpoint `32fbee33` corrects the activation step-67
  dialog: disk/extraction/missing-file failures are possible, and full child
  details are in the setup window, not the step log. Existing NSIS checks
  passed 40 tests; independent copy review accepted. Not in the active build.
- Four old guard tests called ceiling-search APIs explicitly retired by U43.
  They now assert the settled decoded-peak pad, cap, variant order and measured
  trim correction without restoring old product behavior. Author run passed
  42 tests in 7.10s; independent root rerun passed 42 in 7.34s. Three wrong-pad/
  trim inverse assertions failed. One earlier three-second child startup miss
  passed unchanged in isolation and both final runs; no deadline was widened.
  Evidence: oversight `evidence/u87-recorder-product/guard-reconcile-*.log`.
- Two watchdog tests now exceed the actual platform wait ceiling instead of
  hard-coding a value that Linux legitimately permits. Runtime is unchanged;
  all 30 affected checks passed independently in 7.38s, and disabling the bound
  in memory made both corrected assertions fail. No timeout was widened.
- Previous remote checkpoint is `f9f210c03f375b318a5d2edc7e76eab2e07e1b57`,
  verified on draft PR 232. Its test run 37202959271 was pending; installer
  compile 37202959249 and docs 37202959261 passed. Lint 37202959246 failed.
  The 7b8a0edd results below are historical. Audio repair commits
  `6951bcf8` and `1ddc6da7` join the next packaged candidate; they are not
  installed-station evidence. Exact build identity is recorded by the workflow.
- The caption-proof lifespan fixture now implements the actual health-owner
  start contract and asserts start/run/close ordering. Baseline failed on its
  obsolete request-only fake (1 failed, 33 passed in 13.48s); the same three
  caption/lifecycle/outbox files pass 34 checks in 11.71s after correction.
  No runtime behavior or assertion was removed by this fixture correction.
- Speech-level run_ride cancellation now interrupts blocked reads, writes and
  final child waits. Closed output pipes cannot certify a successful render;
  Windows stop-related I/O errors preserve the typed cancellation result.
  Independent focused run: 13 passed, 21 deselected in 5.11s. Four inherited
  closed-algorithm expectations remain red. Peak-scan cancellation is also
  repaired: root independently passed 21 focused checks in 6.49s, including
  actual blocked reads/waits, peak calculation and stop/error distinctions.
  Preparation loudness probes now receive their base or warm per-call budget,
  including warm calls without a cancellation event. Owned output cleanup is
  bounded and preserves timeout versus cancellation. Real blocked-child REDs
  became GREEN; author and independent focused runs both passed 56 checks.
  Full affected run: 213 passed, two cache-fixture failures also reproduced on
  unchanged HEAD. No whole-preparation or installed cancellation claim.
  Probe evidence: oversight `evidence/u87-recorder-product/probe-receipt.md`.
  Evidence: oversight `evidence/u87-recorder-product/ride-cancel-receipt-v2.md`.
- Background reload refusal now carries the original airing-program horizon
  into restart recovery (A-006). A two-hour program previously entered recovery
  after 1952 simulated seconds because that horizon was lost. The reproduction
  now passes; daemon/watchdog tests pass 206 checks and command isolation passes
  3 checks. Independent review passed 10 recovery checks with no material
  finding; not installed in the frozen v20 run.
- Take live now admits a stale enabled configured source to a fresh check,
  instead of disabling the action before verification. Ready sources retain
  priority; failed, unknown and disabled sources remain blocked. Both ready
  and stale configured sources require matched source proof before an audit
  row or command is written, including deletion and endpoint-change races.
  Independent final verification: 60 affected checks pass (10.69s), scoped
  Ruff passes. Built-in help and PDF/DOCX are regenerated and current checks
  pass. Evidence: oversight `evidence/u87-stale-takeover/receipt-v2.md`.
  This is source verification, not an installed live-takeover claim.
- The asynchronous program-change watchdog gap (historical audit A-001) is
  repaired in source: pending background preparation and a later refusal retain
  the same failed hand-off's retry budget. A successful arm or cleared pin ends
  that episode; outstanding preparation is never killed by this watchdog.
  The reproduced async failure had 2 failing assertions before correction;
  all 207 affected daemon/isolation/recovery checks pass after it. Independent
  review passed the 9 recovery tests and 3 adversarial checks, including work
  held beyond the grace and a new pin receiving a new full budget. This repair
  is not part of the v20 installed selection or a packaged/runtime claim.
  Local evidence: `u87-recorder-product/watchdog-{red,green,affected}.log`;
  review: `reports/audit-lite-watchdog-async-2026-10-04.md` in oversight.
- Local source checkpoint `d6965139` contains the reviewed lifecycle fixtures
  and playout typing cleanup below. The next source change fixes Paywall Save:
  ordinary saves use the existing PATCH route, omit blank write-only secrets,
  and create via PUT only after an actual missing-row 404. The old behavior
  reproduced erased data; exact-lock Vitest 4.1.11 passes 42 UI/API checks
  independently, and 26 existing backend contract checks pass. TypeScript/Vite
  build and scoped lint pass. No real credentials or payments were exercised.
  The feature remains unfinished and off by default; this is not live-payment
  acceptance. Source chapters, built-in manual and PDF/DOCX were regenerated;
  both current-source artifact checks pass. Evidence is in the local oversight
  folder `evidence/u87-paywall-save/receipt.md`.
- Previous remote checkpoint: `7b8a0eddf53997fdd23e614ca773f47e163c333a`,
  pushed to draft PR 232. Installer compile 37198987646, docs 37198987589,
  policy 37198987576, egress and accessibility checks passed. Test 37198987580
  completed red: unit 106 failed/11331 passed/78 skipped/5 deselected;
  randomized 105 failed/11336 passed/79 skipped. Its Windows native job
  failed (7 failed/2126 passed/2 skipped/3 deselected: missing FFmpeg and a
  capacity fixture failure). Lint also failed. No green-CI or release claim.
  Prior run IDs below remain historical anchors, not current-source passes.
- Latest health repair anchor: `58c3aca174b9d15ca479dca0bbd2bd6700ac9789`.
  The explicit app lifespan now keeps one schema-refresh worker alive and
  refreshes before the unchanged five-second expiry. Blocked actual reads
  remain owned; stale results still become unknown and close rejects late
  publication. Request-only inverse tests fail the intended assertions;
  69 affected checks and an independent 35 owner/lifecycle checks pass.
  Live sustained acceptance is still pending.
- Selected v20 runtime attempt FAILED on October 4 at 06:45:39 MDT after
  242 samples, not a completed two-hour acceptance. First regular sample was
  05:42:37 MDT after reader invocation/identity-query errors; the initial gap
  is not sampled acceptance. Public caption cue times stopped advancing for
  63 seconds while public HLS and VTT writes, government/education captions,
  and healthy/current health continued. Silence versus missing speech remains
  unproven because final candidate audio was not preserved reliably.
  Candidate PID 3860, birth 05:34:04.556294 MDT, supervisor PID 24736;
  actual health (34 anchors) and caption code identity checks passed.
  This was only the frozen 16-file selection, not the full branch or a package.
  All 16 original files and proof state were restored, service was running,
  and 06:49:20-06:49:35 MDT samples verified all three channels progressing.
  Evidence: oversight `reports/U87-V20-FUNCTIONAL-RESULT-2026-10-04.md`.
- Reviewed local fixture reconciliation preserves the recording target,
  unwritable-directory and worker shutdown assertions, but observes actual
  lifespan activation rather than constructor-only state (18 independent passes).
  Three HLS fixtures now emit their simulated new-child output after intentional
  startup cleanup; 21 affected checks and 3 independent focused checks pass.
  These are test corrections, not newly fixed recording or playout behavior.
- Playout typing cleanup preserves instance-owned diagnostic defaults and makes
  the GStreamer nanosecond unit explicitly integral. Scoped mypy and Ruff pass;
  independent source-extracted checks cover instance isolation and span values.
  The adjacent two-file run has the same 13 failures, 119 passes and 2 skips on
  both HEAD and this cleanup; no broad playout-suite pass is claimed.
- Earlier repair anchor: `8b7034e29154b73274aebedf88a42ca7d8b5e328`.
  Optional schema diagnostics no longer block readiness on synchronous disk
  logging. A stalled-handler reproduction failed before correction; 64 affected
  checks and a separate 19-check review passed. This does not establish that
  logging caused every historical readiness delay.
- The two-hour attempt beginning 04:21 MDT FAILED around 04:28 MDT when health
  did not become ready within its existing five-second check. All three HLS
  and caption outputs were fresh at failure. Exact original files, settings,
  and advancing three-channel operation were restored by 04:33 MDT. The next
  bounded run started at 04:55 MDT and FAILED at 05:03 MDT after 31 successful
  samples, again at the unchanged five-second health-poll limit. All three
  HLS/caption outputs were fresh. Candidate PID 32184; original 16 files and
  proof state are restored, with healthy advancing three-channel operation
  verified at 05:10 MDT. The reader discards the last HTTP reply when its
  aggregate budget expires: this is a readiness-poll miss, not a proven HTTP
  outage. The snapshot-only logging fix did not close sustained readiness.
  No successful two-hour claim. An earlier 0-16 ms database benchmark used
  the interactive user's SQLite source, not station PostgreSQL; it is not
  evidence ruling out station DB connection/query cost.
  A subsequent read-only elevated check of the exact service PostgreSQL source
  completed three schema reads in 446.300, 42.832 and 39.513 ms. This baseline
  measurement does not explain the earlier candidate's transient delay.
- First-install GUI/handoff and exact-candidate download assembly have scoped
  source acceptance: 11 native, 33 UI/API, 19 distribution and 62 combined
  packaging/station/workflow checks passed (overlapping suites, not a total).
  The actual 13.5 MB native GUI opened and refused an invalid authority without
  Setup or installed-service activity. Root independently repeated the 11 native
  and 33 UI/API checks and inspected the rendered refusal. Two Rust warnings
  remain: existing CatalogRoots visibility and unused build_signed_pack helper.
  No clean-machine download, WebView2, UAC/NSIS, Authenticode or lifecycle verdict.
  Current delivery still lacks a verified public host for
  complete model packs larger than GitHub's 2 GiB asset limit. Do not call this
  a working online installer. Contributor-time source repair is independently
  accepted and committed at `0a615ae1`. Its manual artifacts and the current
  first-install development guidance were regenerated; both manual current-source
  checks pass. PDF pages 174-175 were visually checked, not all 497 pages or DOCX.
  Earlier entries
  below are historical proof anchors, not current release acceptance.

- Branch: `codex/u73-caption-measurements`.
- Current integration PR: [draft #232](https://github.com/scottconverse/civiccast-native/pull/232),
  opened at source checkpoint `4817d6eb198c82e617cf4baa6cb817bfc1355523`.
  Existing remote CI is running and has unresolved failures; no merge or release
  approval. Initial failures include the oversized generated manual, stale
  PDF/DOCX manifest, lint, egress/native tests and three operator browser cases.
  Each needs product-versus-fixture reconciliation; no checks were relaxed.
- The selected installed health/caption candidate completed its bounded local
  functional window on October 4, 03:25 MDT. All 66 regular samples showed
  current/healthy responses and advancing public, government and education
  HLS/captions on the same verified process. Regular saved samples cover
  17 minutes 51 seconds, not a fully sampled 20-minute soak. Retained logs show
  no ongoing audio-shedding event; startup discards, quality refusals and
  unconfirmed-word expiry are disclosed, not counted as proof of complete speech.
  This selection included the live fallback cap and rejected-region preservation,
  not every change on the branch. Exact original files/settings and healthy
  three-channel baseline operation were restored at 03:32 MDT. Full-caption,
  packaged-install and sustained release acceptance remain open.
- Product checkpoints: the installer selected-plan repair now has independent
  source acceptance, including two witnessed stale-completion regressions.
  The illustrated offline manual packaging repair is committed as `74d2a621`,
  with independent containment review. Both preserve existing trust checks.
  PDF/DOCX regeneration and current-source checks passed. A tall screenshot's
  caption/footer overlap was corrected and the affected PDF page visually
  checked. Whole-manual visual review and DOCX rendering remain unaccepted. Do not expand
  the diagnostic harness or change CI limits to hide these failures.
- Reconciled inherited playout/stream-end fixtures in `fe818cf3`: the current
  U51 restart intentionally clears stale HLS, rollover records carry four
  fields, crash recovery may air a fresh slate without reusing an abandoned
  prepared program, and live caption audio arrives after startup cleanup.
  Existing checks now pass (196 daemon; 7 stream-end), with a separate 10-test
  independent focused review. No product runtime behavior changed in this
  checkpoint and no failed scenario was deleted.
- Browser fixture reconciliation is committed as `96984445`; existing Chrome
  scenarios passed 15 locally and 15 in independent review. No production
  approval, publication or export protection changed.
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
- A concrete caption-loss defect is now corrected in source: one quality-refused
  model segment previously erased independent accepted speech in the same window.
  Accepted words retain actual timings and explicit rejected-region boundaries;
  confirmation, active VTT/feed cues and review rows cannot bridge those gaps.
  Independent runtime policy checks passed28 tests; final downstream/gap checks
  passed22, including actual three-channel WAV-to-VTT/feed output and the original
  partial-commit review failure. Quality gates and model settings are unchanged.
  Model responses were injected; real inference/station acceptance remains pending.
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
