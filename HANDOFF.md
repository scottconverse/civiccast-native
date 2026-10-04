# HANDOFF

This file is a pointer, not a log.

## Active development checkpoint - 2026-10-04

- Frozen built candidate: `eb94e465fe1f2b5335f0ad90620e1a01c041812e`.
  Reviewed development proof anchor: `404c584a`, including the separate
  constructor test correction `34a170c3` and fallback audio guard `b75444ea`.
  Remote checkpoint verified: `2fd8a22ae708c9d4f98d414781e414fc28627f02`.
  Local follow-up `6789602a` fixes only regression-test formatting (AST identical).
  Resolve later tips and CI through draft PR 232, not the frozen package SHA.
  Follow-ups reconcile tests,
  CI prerequisites and documentation policy. The subsequent fallback audio-tail
  target correction changes runtime source and requires a new package; the
  running eb94 acceptance job cannot prove that correction.
  Draft PR 232 now distinguishes the remote development source, frozen package,
  terminal original-soak FAIL and restored original baseline. Exact self-hosted
  candidate build 37230261698 completed SUCCESS in all three jobs, including
  signed artifact verification, packaged GStreamer worker smoke and final kit.
  Automatic Gate A 37232341060 is terminal FAILURE: clean-install job passed;
  cross-version validation stopped before upgrade installation because the
  default-main validator selected the failed aggregate baseline-run conclusion,
  rather than its successful original attempt. The branch already repairs that
  validator. This is not an observed upgrade-product failure or an upgrade PASS.
  Corrected exact-source build 37236684992 is active on remote 2fd8a22a;
  v13 owns its watcher and the subsequent corrected-branch Gate A dispatch.
  The prior disposable VM is gone; no duplicate lab operation is authorized.
  Large/binary uploads false; no new tag,
  release or station cutover. Current-source tests 37235135807 are active; the
  Windows native job has passed. Current docs 37235135808, installer compile
  37235135809, operator build 37235135854, accessibility 37235135825 and policy
  37235135799 passed. Lint 37235135805 failed on one test file's formatting;
  local 6789602a corrects it, not yet pushed. Historical tests 37230256695 FAILURE:
  `71 failed, 11465 passed, 79 skipped, 5 deselected in 2428.31s (0:40:28)`;
  this ran frozen eb94 before the local correction batch. Do not poll its
  terminal watch session. Local 572d119e reconciles 15 current-source claims roles
  across five reviewed source blobs, without rebinding unfinished DR source or
  rewriting historical proof. u86 is independently reviewing the secure-PG
  repaired-byte snapshot while the database and installer agents finish recovery.
  Lint
  37230256681 failed solely at Ruff formatting (23 files); docs 37230256692 and
  installer compile 37230256805 succeeded. Windows dual-runtime guard passed.
  v13 remains sole lab operator; no manual VM may overlap automatic Gate A.
- New fallback audio-tail correction supplies the published switch bound when
  no outgoing audio end was measured; an empty target previously released the
  guard immediately. Existing two sensitive tests failed in the saved baseline.
  Root independently ran five affected egress modules: `185 passed, 2 skipped
  in 9.89s` (two explicit real-GStreamer cases unrun in that interpreter), plus
  relay logging: `17 passed in 14.72s`. Engine mypy and scoped Ruff pass.
  Existing deadline/quiet behavior is checked at 290/310 ms and 19/21 ms.
  Author observed a separate logging timing failure during overlapping work:
  1.68 seconds supervised versus 1.27 seconds baseline at the unchanged 1.10x
  bound. Root's passing run does not erase that counterevidence; diagnosis
  remains open. Review: oversight reports/U87-AUDIO-TAIL-INDEPENDENT-REVIEW.md.
  Six egress fixture contracts are reconciled without restoring discarded code.
- Separate relay-log retention defect corrected: a calculated absolute offset
  was sought relative to EOF, discarding the diagnostic tail. The one-line
  seek-origin correction has an exact retained-byte RED/GREEN check, 16 adjacent
  passes (performance case excluded), independent root retained-byte PASS,
  scoped Ruff PASS and relay-module mypy PASS. Receipt: oversight reports/
  U87-RELAY-TAIL-RETENTION.md. The prior performance timing counterexample remains
  recorded; a subsequent controlled single-case run passed at 1.20 seconds
  supervised versus 1.25 seconds baseline. That does not erase the earlier
  overlapping-run failure or establish performance on an idle machine. This source
  also requires a new package; eb94 installation evidence remains historical.
- Rollback database replacement implementation is partially blocked by the
  local Agent Pipeline plugin's text-based tool guard, which rejects SQL text
  inside source patches and even read-only searches. No bypass attempted.
  Owner was asked asynchronously for a narrowly tested classification repair
  retaining destructive-execution protections. Non-destructive backup/verify
  work continues on a private loopback PostgreSQL instance. Do not call the
  unfinished database restore path complete or narrow away shared-database support.
- Local verification corrections: `61ef21d8` provisions Pandoc through the
  existing media-prerequisite script; `1bf8b739` exercises the actual public HLS
  manifest publisher; `14e00b38` selects a validated available H264 encoder;
  `53a996a8` accepts BOM-prefixed evidence JSON while retaining rejection checks
  and reconciles obsolete documentation assertions. The packaged Python/GI HLS
  case is Windows-only, not skipped for a missing Windows runtime. Generic HLS
  checks: `5 passed, 1 deselected in 10.62s`. The packaged case subsequently
  passed against exact eb94 runtime/source: `1 passed in 44.80s`, no skips.
  Receipt: oversight evidence/u87-packaged-candidate-eb94/hls-runtime/receipt.md.
  This proves short packaged-runtime HLS integration, not caption completeness
  or installation. No installer PASS claimed.
  Marker commit: 66319bfb; formatting commit: d4e8118b. The 23 CI-reported files were then run through Ruff
  format (21 changed, two already corrected), with before/after AST equality for
  every file and a passing 23-file format check. This is mechanical formatting,
  not another runtime fix; the in-flight eb94 package is unchanged.
  These commits were batched while the long CI run finished. That run is now
  terminal. The reviewed remote checkpoint includes the
  reviewed native-floor and claims-test corrections, preserve runtime evidence
  identity. Refresh PR 232 after confirming the remote SHA and new CI identities.
- Local follow-up commits: `6f224618` raises native execution floors to
  1881/2087 from isolated committed-source collection (1931 pure, 2140 total,
  2137 excluding integration). Root rerun: `34 passed in 32.03s`. `7be11a8f`
  isolates each claims-detector mutation from existing unrelated drift; root
  adjacent parser/role/drift run: `14 passed, 111 deselected in 10.77s`.
  Real current-source binding failures remain, with no historical hash refresh.
  Root reran docsite build-content, help-deep-links, router and health-outbox
  modules together: `44 passed in 29.67s`. CI's doc-render failures explicitly
  name missing Pandoc; the local prerequisite repair addresses that cause.
  The two-second constructor test failed on CI without entering either held
  model builder. It now checks constructor builder entry directly, recording
  attempts before raising so swallowed errors cannot evade the assertion.
  Root module rerun: `9 passed in 8.07s`; author direct and swallowed-entry
  mutations each fail both parameters. No product timeout was raised; other
  constructor responsiveness checks remain unchanged. Receipt: oversight
  reports/U87-CONSTRUCTOR-BOUNDARY-RECONCILIATION.md.
  Fresh CI artifacts are retained at oversight evidence/u87-ci-eb94-37230256695.
  Producer metadata binds run 37230256695 attempt 1 to exact eb94. Six registered
  PostgreSQL backup/restore, SQLite restore positive/falsification and release-
  truth positive/unknown-live nodes all passed with zero skips in its JUnit.
  This does not turn the overall CI result green or prove installer rollback.
  Detailed external receipts: U87-NATIVE-COLLECTION-FLOORS.md and
  U87-CLAIMS-DRIFT-RECONCILIATION.md in the oversight reports directory.
  Independent rollback v2 review corrected two reproduced defects: foreign
  registration-root redirection and failure to recover an absent application
  tree. Reviewed eight-file snapshot: 126 passed, 4 deselected in 7.34s,
  plus sensitive defect/staging interruption/corruption checks. This is offline
  core/primitives proof, not installed rollback. product_type_contracts now
  implements the isolated database factory; v13 owns entry/admission/NSIS wiring.
  u86 prepared guest-local existing Node/Playwright tooling for actual installed
  help/paywall/take-live actions, without a new bridge/server/harness. Guest
  invocation remains v13-owned. No authenticated installed UI PASS yet.
  Existing deb2 resource samples are analyzed in oversight reports/
  U87-DEB2-RESOURCE-OBSERVATION.md: cyclic worker working-set changes, not a
  demonstrated leak or long-run resource-stability PASS.
- Exact eb94 source/packaged-runtime worker checks passed: build/play/teardown
  and role-swap continuity, `2 passed in 8.06s`, zero skips. Root independently
  read JUnit: tests 2, failures 0, errors 0, skipped 0. Five tested source files
  matched extracted package bytes; actual worker used package Python 3.12.10,
  GStreamer 1.28.5 and private test outputs. Evidence: oversight
  evidence/u87-packaged-candidate-eb94/registry-worker. This is not service-at-
  boot or full station proof; registry evidence has not been blindly rebound.
- Buffered worker acknowledgement repair: `ade67360`.
  Root independently ran 67 affected tests (1 existing gi skip), then 274
  strategy/daemon tests (6 existing POSIX skips). Whole-tree Ruff passed and
  mypy passed 690 source files. This is source verification, not installed proof.
  CI for remote `d258e46d` is terminal FAILURE: run 37225882397, 78 failed,
  11446 passed, 79 skipped, 5 deselected in the broad unit job; Windows native
  job passed. u86 is diagnosing residual product failures and obsolete assertions.
  Do not wait on that already-finished CI job or claim the branch is green.
  Original beta.5 setup download/extraction recovered the original index hash
  `4860825284077fad4c0807cf78816b08a5be4d7c6aa4259bf92b1125d184849a`.
  Original baseline recovery and pin correction are complete (7e97d003);
  receipt: ops/beta10-oversight/reports/U87-ORIGINAL-BASELINE.md.
  product_type_contracts owns exact-committed-source native collection floors;
  u86 owns honest claims-registry reconciliation, without rebinding historical
  runtime evidence to changed source. v13 owns remaining flat-installer recovery
  wiring. Unfinished native rollback files remain excluded from candidate commits.
- Original deb2 two-hour soak is terminal FAIL, verdict at 2026-10-04
  13:36:34 MDT: 110 total cycles, 3 warmup, 107 evaluated; 1 planned restart,
  0 unplanned relaunches. Education's startup content reload timed out after
  5.0 seconds (`reissue_desired_state`) and fell back to restart; detected
  11:37:06 MDT, recorded recovery gap 22.5 seconds. This is additional to
  recurring stream continuity failures and public/government startup caption
  shedding. The earlier two-issue chat summary was incomplete and corrected.
  Evidence: `sandbox-lab/soak-output/soak-deb2adf-20261004-171539Z/VERDICT.json`,
  `restart-events.json`, `soak-log.txt`. Runner PID 34096 is now absent;
  Independent VM/lease cleanup and all 1,228 private evidence file hashes were
  verified. The buffered acknowledgement fix is in the frozen candidate; its
  installed effect remains unverified until the replacement run.
  Do not call candidate ready based on the caption/transport repairs alone.
- Existing upgrade-baseline metadata repair committed `0faddc2a`: explicit
  successful original build attempt 1, distinct reconstructed-index attempt 2
  provenance, all downstream byte/version checks retained. Root independent
  existing contract module: `98 passed in 2.40s`; actual PowerShell/remote
  attempt identity validation passed. Agent wider existing suite: 227 passed.
  The original beta.5 kit is now restored and hash-verified under
  C:\CivicCastTester\kit-staging\148c8d2172dd6b63cbbb856b429b68aa020dc421.
  Build pruning removed deb2 staging, not its retained private evidence or the
  separately protected original baseline recovery source. Actual upgrade proof
  remains pending; recovery of baseline bytes is not an upgrade PASS.
- Latest source verification (supersedes the intermediate baselines below):
  product contract repairs and the nullable caption diagnostic-counter fix
  returned `439 passed in 54.60s`; root independently ran caption stage/tap,
  relay and proof-worker modules: `158 passed in 47.76s`. Full product mypy:
  `Success: no issues found in 689 source files`; full Ruff check passed.
  These are source checks, not installed acceptance. The new counter guard
  prevents missing diagnostic receipts from interrupting later captions;
  it is not evidence that startup audio shedding is fixed.
  Live-router baseline failures were reproduced with a synthetic inherited
  staff-token setting. A module-local fixture isolates that setting without
  changing production authentication. Root independently reran the synthetic
  contaminated-environment full router module plus both secure-default cases:
  `108 passed in 68.40s (0:01:08)`, using the security-python interpreter.
  Agent result: `108 passed in 69.14s (0:01:09)`, including secure defaults.
  Auth isolation is committed as `abd8416e05855009ab3e6ad9ce30ab968b239754`.
  Root repeated full mypy (689 source files) and Ruff successfully after it.
  Product source/doc sync is now committed as
  `0f7b0014097665904a8a33049484c1c289240f67`. Independent review found no
  actionable findings, ran 90 focused tests successfully, and independently
  observed four old-counter failures followed by four fixed-source passes.
  Private review: oversight `reports/U87-TYPE-CONTRACTS-INDEPENDENT-REVIEW.md`.
  Push delta review passed all five lenses at `70659633` (two receipt-only
  ASCII corrections after the product commit). No uncommitted native rollback
  is included. Post-push CI/PR identity reconciliation remains pending.
  Next signed build must wait for original soak termination, evidence harvest
  and verified cleanup; its pruning step can remove the old deb2 kit staging.
  Gate A's pinned beta.5 build now reports failure for its latest attempt,
  while original attempt 1 succeeded. Exact attempt/reconstructed-index
  provenance is being checked before changing either existing validator.
  Broader remote CI 37225882397 is still running; do not cancel by repeated
  checkpoint pushes. Native rollback production wiring remains unfinished
  and must stay outside the next reviewed source package.
- Active ops cleanup now independently checked by root: the existing loudness,
  air-audio and caption rung modules returned `37 passed in 11.73s`; scoped
  Ruff returned `All checks passed!`, format check `18 files already formatted`.
  Root formatted seven named ops files only and compared parsed Python AST
  hashes before/after: all seven identical. No operational helper or historical
  publish wrapper was executed. The pdl credential-argv fix has separate
  synthetic RED/GREEN review; no real token was read or download performed.
  Product typing has since passed the checks above; rollback integration is
  separate ongoing work.
- Root type-check baseline: `python -m mypy civiccast` reported `Found 32
  errors in 11 files (checked 688 source files)`, including one in the separate
  unshipped flat-recovery draft. `phase_timing.py` now explicitly annotates its
  heterogeneous summary dictionary; runtime behavior is unchanged. Existing
  `tests/captions/test_caption_phase_timing.py`: `23 passed in 2.05s`;
  scoped `mypy --follow-imports=silent civiccast/captions/phase_timing.py`:
  `Success: no issues found in 1 source file`; scoped Ruff passed. Ordinary
  mypy at that intermediate checkpoint followed imports and reported the other
  product errors. The latest full-product check above supersedes that result.
- Local lint-scope reconciliation: `pyproject.toml` excludes only the preserved
  U37 `evidence/instruments` directory, whose README binds those exact scripts
  to historical results. No archived script was edited. Root compared
  `python -m ruff check --show-files .` before/after: 1643 -> 1631 files,
  exactly those twelve instruments removed; no product, active tool or test
  path removed. Archive `git diff --exit-code` and config `git diff --check`
  passed. The latest full Ruff check above includes the active ops cleanup.
- Local HEAD: `0faddc2a` (upgrade-baseline attempt repair), after
  `7065963351a01e422ac0fb7e351cbaff191a2c5a` (receipt punctuation
  after reviewed caption counter/type fixes `0f7b0014`, auth-test isolation
  `abd8416e` and ops cleanup
  `fe4a52ff` with bounded credential-safe downloader).
  Not yet pushed, to avoid
  cancelling the running broader CI job. Native rollback WIP is intentionally
  outside that commit; source typing is included.
  Remote/PR tested source: `d258e46d47226fc1ed84d6d55c44be37da670582`.
  PR 232 updated. Dedicated unicast proof-copy repair pushed with `df0808ed`
  (Windows pinned FFmpeg provisioning and changed-identity fixture); `74138634` fixes
  the new-session overload negative control and `4691a748` live VAD preparation.
  Current CI at 2026-10-04 13:00 MDT: tests 37225882397 still running;
  its Windows native job 111505457547 passed: `2137 passed, 3 deselected
  in 215.82s (0:03:35)`, with pinned FFmpeg provisioned and suite guard passed.
  The Windows command excludes integration-marked tests; real Postgres
  integration coverage belongs to the separate Ubuntu job and is not proved
  by this Windows result. Job logs carry Node action deprecation warnings.
  The broader unit job is not yet terminal. Lint 37225882300 failed;
  installer compile 37225882282 and docs 37225882324 passed. Historical
  b5d4 run 37223766740 is CANCELLED after normal workflow supersession;
  do not treat its unfinished unit job as a pass.
  Final matched isolated wildcard comparison: old capture receiver CC4,
  private-copy receiver CC0, raw mux CC0 in both, successful capture/clean exits.
  Root independently analyzed both retained receiver files with TSDuck, exit 0.
  Original deb2 soak remains unchanged and is not a clean run: cycle 73 at
  12:56:08 MDT had all channels ON_AIR and clean samples, but cycles 71/72
  repeated the public/government then education continuity failures. Original
  runner PID 34096 / birth 2026-10-04T17:15:26.6458145Z remains live;
  fixed deadline 13:36:24 MDT. This package does not contain the source repairs.
  Old receiver SHA256 E078A45A864E7D7A89269A694DE02FA33492CB6E8592446B1A2400F144F7536F;
  corrected EEA9748DCD8DA935E6096AA8D3E129AB8BB468DF427197212543C46E9FBDD4A6.
  Source publication fence now accepted through actual factory/capture path,
  with independent mutation sensitivity. Root 29 focused and 116 neighboring
  automation/relay tests passed. This is not installed sustained acceptance.
  Helper transport assignment finished; v13 now owns rollback draft plus the
  unchanged original soak, and Luna lint_cleanup owns active-ops mechanical lint.
  Root independently ran the six affected caption/runtime modules: 198 passed
  in 7.71s, exit 0; Ruff passed. This does not prove first-encoder latency fixed.
  Root independently ran the existing overload-control module: 27 passed in
  2.10s. It now seeds new-session audio after worker construction and explicitly
  selects supported immediate fail-closed settings for its negative control;
  nominal capacity defaults are unchanged.
  The dedicated relay-copy replay timed out. Its copied graph inherited host
  caption-tap paths and default relay input port 17800: verified isolation
  failure, so the replay is not valid evidence against or for the mirror fix.
  Owned replay processes exited; no further replay until all graph paths and
  ports are rebound and independently reviewed. Exact host file impact is not
  yet attributable; do not claim harmlessness or delete host data. Prior isolated
  CC observations need the same host-path qualification. Original guest soak is
  separate and unchanged. Do not accept unit-test GREEN as broadcast-safe proof.
  Helper owns that repair; u86 owns CI overload-producer failure; v13 owns
  the unchanged soak and existing HLS-verifier consistency/FFmpeg failures.
  Source preparation receipt: oversight reports/U87-CAPTION-VAD-PREPARE.md.
  Subsequent fully rebound isolated mirror replay succeeded: original media,
  real native worker/relay and private caption capture, receiver all four PIDs
  continuity zero. Root independently re-analyzed received.ts with TSDuck:
  exit 0, PID 0/32/65/66 errors zero, SHA256
  628750D9F90C0856486EB650DB1070B8C6714E2954E12FAE70C10E38BB88E59D.
  Evidence: oversight evidence/u87-recorder-product/transport-udp-copy-isolated-output.
  This is bounded isolated transport proof, not installed or caption-content
  acceptance. A source review found a stale-result publication window if relay
  identity changes during caption decoding; helper is correcting it before
  acceptance. Root verifier tests 73 passed in 5.94s, FFmpeg builder 22 passed
  in 2.50s; hosted CI provisioning execution remains pending.
  Caption recovery correction pushed; PR 232 updated. Independent tap module
  105 passed and old-policy falsification discarded four segments as expected;
  author neighboring checks 125 passed. Source-only, not installed acceptance.
  Current CI: tests 37223766740 running; lint 37223766634 failed with the same
  108 findings (no tap-worker source/test hits); installer compile 37223766659
  started. Prior 05ba tests 37220741350 were cancelled after the newer push;
  prior checkpoint CI below is historical, not current evidence.
  Isolated actual-worker UDP experiment reproduced the live conflict: adding
  caption-proof capture left raw mux continuity clean but caused receiver errors
  (PAT, PMT and audio). Dedicated loopback proof-copy repair is being implemented;
  no transport patch or live repair is yet accepted. Original deb2 soak unchanged.
- Push receipt: branch `codex/u73-caption-measurements` was independently
  verified at remote `05ba17b03aa861c872064a91a6d27446bf0f2066`; draft PR 232
  now distinguishes current source from the deb2 package. That checkpoint's CI
  started: tests 37220741350 remain running; lint 37220741446 failed with 108
  findings; docs 37220741540, installer compile 37220741556 and sandbox-lab
  checks 37220741578 passed. This is not green CI or a packaged-runtime pass.
  Failed-upgrade recovery under the existing flat layout remains incomplete;
  its draft is paused while live transport errors and caption loss are repaired.
  The current DB-only recovery cannot restore old application files.
  No production operation or new public release is authorized by this receipt.
- Live-run investigation, 2026-10-04 12:00 MDT: cycles 4/7/10/13/16 were
  clean; 5/8/11/14/17 failed for public/government, and 6/9/12/15 for education.
  Raw reports identify varying PIDs, not solely PAT. This approximately
  three-minute pattern is a reproduction lead, not proof of mux versus UDP loss.
  The saved initial playback graph is stale across reloads; its retired prepared
  path cannot establish current loaded-media identity. Original run and criteria
  remain unchanged, with the 13:36:24 MDT end unchanged.
  The retained 17:54 UTC control-plane log separately proves startup caption
  shedding: public at 11:37:20 MDT and government at 11:37:24 each discarded
  four segments/20 seconds after an initial 40.453-second ASR call. Their queue
  had decreased from eight to six segments, but the 15-scan over-limit streak
  still triggered shedding. Source diagnosis is active; no repair is proved.
  Bounded offline reproduction subsequently ran the retained 30-second prepared
  media (SHA256 55c471a177f3989541e989ca98d3e832734a6ce054ea6a67c0a9277282a0972d)
  through the native worker with the initial graph as a topology template and a
  file sink: 236.5 seconds, eight deferred reload commits, 533,060 packets,
  all-PID continuity errors zero and backwards PCR zero. Root verified the raw
  file hash against result.json. This is not exact historical loaded-graph or
  live UDP proof; the original soak failures remain. Next transport work checks
  the UDP boundary and possible competing receivers, without changing the run.
  At 12:11 MDT, same-guest sanitized process evidence confirmed caption proof
  process 7884 (`civiccast.egress.caption_proof_process`) launching FFmpeg on UDP
  9003 while the soak TSDuck receiver was also listening on 9003. This establishes
  the competing product caller; isolated packet-loss reproduction remains pending.
  The caption recovery draft independently passed the complete tap-worker module:
  `105 passed in 40.93s`. Restoring only HEAD's overload decision in memory made
  the new regression fail at four discarded segments, as intended. This is
  source-only proof; documentation/review and packaged three-channel proof remain.
- Local installer repair `e4a10af5137b207709ffe28bdc82c7db7674b10e` adds a
  read-only downgrade check before service stop and application replacement.
  It preserves the existing known-version ordering and uses the new bootstrap,
  not a potentially broken installed Python. Baseline ordering assertions failed;
  final hooks passed 43 checks including actual NSIS compilation. The compiled
  native command passed 14 deliberate SHA-bound cases and five independent
  root cases, silently. This is source/command proof, not a refused packaged
  installation or full application/database rollback proof. The tested deb2
  package does not contain this change. Generated manual synchronization is in
  `24c03584280fb0046f5c4326206964d892213666`: both artifact freshness checks
  passed independently; PDF page 195 was visually checked without clipping.
  DOCX was regenerated and hash-checked, not separately visually rendered.
  Source/help notes explicitly distinguish published beta.10 behavior.
  Evidence: oversight evidence/u87-recorder-product/preflight-receipt.md.
- Previous source checkpoint `328edfbaa69a31acb7933de17f6fa8eb9af3f162`
  on draft PR 232 had installer compile 37216841061 and docs
  37216841181 passed. Lint 37216841013 failed with 108 findings; tests
  37216841029 failed (unit: 79 failed, 11,420 passed, 78 skipped;
  native: 8 failed, 2,127 passed, 2 skipped). These are not green merge gates.
  Two constructor-responsiveness cases failed their two-second wait in the
  full Linux unit run; an independent isolated Windows rerun of their two
  modules passed all 20 in 12.87 seconds. The CI failures remain unresolved;
  that isolated pass does not establish their cause or waive them.
- Current packaged candidate is `deb2adfa9dab7e41c5d9a64fcd2bebb95b26723d`.
  Build 37211323548 passed all three jobs, independently confirmed at
  2026-10-04 09:38 MDT. Both installer executables have valid signatures.
  This candidate includes the generated-slate preparation and bounded HTTP-log
  repairs described below. Clean installation exited 0, health was healthy with
  the current schema, both Edge-rendered interfaces passed, and the real upload/
  publish/offline-caption loop passed. The actual product engine connected its
  sink in 15 seconds; transport verification passed 1,182 packets with zero sync
  errors, transport errors or discontinuities. Worker PID 5524 and its graph/log
  were captured before the existing test stopped it. No FFmpeg substitute was
  used. The unchanged 20-minute health observation passed four samples with zero
  unhealthy results in 1200.3 seconds. Clean Gate A job 111469803858 passed,
  including normal host cleanup. Workflow 37213690258 nevertheless finished
  FAILURE: its separate cross-version lane could not resolve the pinned beta.5
  baseline and did not execute installation; download-only was skipped. This is
  not an all-lanes pass. Sustained three-channel speech acceptance remains pending.
  The replacement existing 120-minute soak uses its supported 60-minute installation
  allowance because this fresh installation measured about 33 minutes; its
  actual soak duration, health, on-air, quiet and rollup limits are unchanged.
  This does not establish installation within the tool's 20-minute default.
  The first local deb2 attempt installed successfully and put all three channels
  on air, but captions were off: the runner read the default setting without
  enabling it. That attempt was cancelled, not passed. Setup-only commit
  `71038c5d` now enables captions through the existing profile API and requires
  a confirmed Boolean true before measurement; explicit captions-off is unchanged.
  Independent setup-path checks passed five cases; author verification passed
  six default-path and 22 captions-off cases. The replacement host process is
  PID 34096, born 2026-10-04T17:15:26.6458145Z, with installation started at
  17:15:39.907Z and bounded through 18:15:39.907Z. Installation exited 0 at
  17:34:41Z after 1109.7 seconds. Root independently read SOAK-START.json:
  captions_enabled is Boolean true, all three channels reached ON_AIR in
  15.3-15.5 seconds, and the sustained clock began 17:36:24.437Z with fixed
  end 19:36:24.437Z. At 17:38:12Z, captured actual VTTs contained 14 public,
  12 government and 12 education cues. Root independently confirmed all three
  contain the source-video spot anchors "working with", "businesses" and
  "building that place". This proves initial content correspondence, not full
  speech completeness or sustained acceptance. Actual logs also show seamless
  content reload accepted; SOAK-START's false seamless_reload field records the
  explicit override switch, not disabled runtime behavior.
  Raw transport reports had packet-counter discontinuities on public/government
  in cycle 2 and education in cycle 3, with zero invalid sync/transport-bit
  errors. Those samples were inside the existing 180-second warmup; cycle 4,
  the first afterward, was clean on all three. Startup/reload correlation is
  being checked; this is not yet a failed sustained verdict or proved source
  defect. Do not change thresholds or discard these original observations.
  Cycle 5, after warmup (17:40:41Z start), then failed transport checks on
  public and government: each report has one PAT/PID 0 continuity error,
  while PMT/audio/video discontinuities, invalid sync, transport-bit errors
  and PCR/PTS leaps are zero. Education passed. Stable worker PIDs and
  advancing caption cues were retained. This IS a steady-state check failure;
  source generation versus capture loss is under investigation. Do not
  conflate it with a proved audio/video dropout. Recovery implementation is
  temporarily held at its uncommitted RED/draft checkpoint while the source
  worker investigates this actual sustained-acceptance failure.
  Its package is still deb2, not the later installer source changes.
  Receipts are in oversight evidence/u87-packaged-candidate-deb2/soak-captions-on.
  The local
  test-only commits `7c1e5500` and `2afcd8a3` are not in this package: they
  reconcile the accepted U43 window and U63 immediate-warm contracts, with
  independent reruns of 29 and 8 passing tests respectively. No runtime changes
  or deleted tests are in those two commits.
  Two additional cache fixtures now use actual 32-hex cache keys and the current
  scratch-age constant, preserving their cleanup/eviction assertions. Independent
  full source-plan/preparer verification passed 211 tests in 18.15 seconds.
- Previous packaged candidate source is `84a283077f4ba9359113c7bbf4189095393c08bc`,
  verified remotely on PR 232; original self-hosted build 37204600121 passed.
  Both setup and First Install executables have valid Authenticode signatures.
  Automatic clean Gate A 37207093775 finished with a host-cleanup failure;
  database provisioning and mandatory station activation/self-tests passed.
  The installer exited 0, Edge rendered both interfaces, and the real upload/
  publish/offline-caption loop passed. T4 product-engine output did not pass:
  no worker appeared during its window while generated silent-slate preparation
  resampled loudness; the existing test substituted FFmpeg fallback. This is
  not a product-engine transport pass. The unchanged 20-minute health observation
  passed four samples with zero unhealthy results. Host teardown exceeded its
  unchanged 300-second deadline; the owned Sandbox later exited naturally and
  all five mapped-directory handle checks passed before the next build began.
  No process was killed, and the original failed workflow verdict is preserved.
  Sustained three-channel speech acceptance remains pending.
  Candidate CI: installer compile 37204558280 and docs 37204558277 passed;
  lint 37204558284 and tests 37204558265 failed. No merge or release claim.
- The current candidate's generated-slate preparation reuses verified internal canonical
  silence without program loudness analysis or re-encoding. Provenance binds
  bytes, file identity, profile and segment fields; disk names and serialized
  plans cannot claim that trust. Root independently passed 12 focused checks
  and the real-FFmpeg one-hour check (1 passed in 5.21s): generation 2.375s,
  preparation 0.969s, 3600.026622s audio/video, one continuous stream-copy output.
  Author affected run passed 208 with two unchanged-HEAD cache-fixture failures;
  final focused run including real media passed 21. Actual packaged startup now
  passes as recorded above; no timeout or test-verdict relaxation was made.
- The current candidate's supervised HTTP access/error logs rotate separately in
  `control_plane-http.log` (10 MiB plus ten backups), without forced fsync on
  each request. Existing application diagnostics retain their durable handler.
  Root independently passed 16 affected logging/spawn checks in 4.82s; the
  forced-fsync counterexample failed. Both manual artifact freshness checks
  passed. Raw startup/print/native stderr and Postgres remain unbounded;
  this is not a total process-output cap or installed-package evidence.
- Included copy checkpoint `32fbee33` corrects the activation step-67
  dialog: disk/extraction/missing-file failures are possible, and full child
  details are in the setup window, not the step log. Existing NSIS checks
  passed 40 tests; independent copy review accepted. Included in candidate deb2.
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
  closed-algorithm expectations were reconciled in the later local checkpoint
  described above; that test-only change is not in package 84a. Peak-scan cancellation is also
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
