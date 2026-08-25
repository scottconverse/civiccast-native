# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This repository begins on 2026-08-20 with the native-Windows product extracted
from [`scottconverse/civiccast`](https://github.com/scottconverse/civiccast) at
**fresh history**. Entries before that date live in that repository's own
CHANGELOG; nothing was deleted there. See [`BRANCHES.md`](BRANCHES.md) for what
came across and what deliberately did not.

## [Unreleased]

### Added

- **S3/S11 — CEA-708 commissioning decode-back verification.** Closes the gap
  PR #22 left honest but open: the S3 commissioning wizard's Screen 10 output
  proof previously always reported `cea708_verified: null` with a blocker when
  CEA-708 passthrough was requested, because no decode-back check existed. New
  module `civiccast/installer/cea708_verification.py` writes a deterministic
  test caption, embeds it through the product's real GStreamer sidecar
  caption-embed leg (`egress/gst/graph.py caption_embed_leg_from_sidecar`, run
  via `egress/gst/worker.py` over the same D2 control seam
  `scripts/prove_native_live_caption_transport.py`'s code already assembles
  this way for the live appsrc leg), then decodes the emitted stream back
  with the existing engine-agnostic
  `civiccast.egress.caption_proof.decode_embedded_captions` and compares.
  `run_output_proof` (`civiccast/installer/commissioning.py`) now calls this
  after the main test-pattern/TSDuck window (injectable via a new
  `caption_verifier` parameter) and reports a real `True`/`False`
  `cea708_verified` with detail — it stays `None` only when the check itself
  could not run. Standalone: `civiccast egress verify-captions` runs the same
  check outside commissioning. Along the way, found and fixed a real latent bug
  in `civiccast/egress/caption_embed.py`'s `_clean_caption_text`: it had never
  been exercised against real ffmpeg-decoded closed-caption output before
  (only hand-written SRT text in tests), so the ASS position tag
  (`{\an7}`) ffmpeg's `eia_608`/`cc_dec` decoder always wraps real decoded text
  in would have made every genuine decode-back text comparison mismatch, even
  when captions embedded and decoded correctly — fixed and covered by a
  regression test. New test fixtures
  `tests/egress/fixtures/cea708_{test_caption,no_captions}.mpegts` are real,
  tiny (~18 KB) MPEG-TS captures with genuine hand-built ATSC A/53
  CEA-608-in-708 SEI data, verified against the actual production decode path
  while building this; `tests/installer/test_cea708_verification.py`,
  `tests/installer/test_commissioning.py`, `tests/egress/test_caption_proof.py`,
  and `tests/egress/test_caption_embed.py` gained new/updated coverage. **What
  remains honestly unverified in this dev/CI sandbox**: the real GStreamer
  embed-subprocess round trip (no `gi`/GStreamer runtime here) — covered by an
  `@pytest.mark.integration` test that skips without the bundled bindings; a
  native Windows box with the packaged runtime (or the WSL/system-GStreamer dev
  tier) is required to exercise it for real. See
  `docs/spec/3.0/sections/S3-commissioning-wizard.md`'s 2026-08-25 banner.
- **S27 (Agenda Import Bridge) Phase 4 — `js_portal` source for JS-hydrated
  agenda portals.** `civiccast/agenda_import/` already bridged Legistar,
  PrimeGov, and CivicClerk (each with a documented, anonymous, plain-HTTP
  endpoint — re-verified this pass, unchanged) into a draft S25
  `MeetingAgenda`; this phase adds a fourth adapter,
  `civiccast/agenda_import/js_portal.py`'s `JsPortalSource`, for the vendor
  family that has no such endpoint — CivicPlus AgendaCenter, Granicus, and
  JS-hydrated Legistar public pages — using
  [crawl4ai](https://github.com/unclecode/crawl4ai) (Apache-2.0) with a
  headless Playwright Chromium browser plus a confidence-scored text
  heuristic (reuses `AgendaItem.confidence` from the PR #21 PDF-import
  path; net-new `ExternalAgendaItem.confidence` threads it through the
  shared mapper). Bounded and sandboxed: same-origin only, robots.txt
  fetched and respected before any navigation, at most two pages per call,
  a wall-clock timeout, and no auth flow of any kind. Config is per-import
  (`portal_url` + `portal_vendor_hint`, validated via new
  `civiccast.agenda_import.config.validate_portal_url`) rather than a new
  migration — none was needed.
  crawl4ai + Playwright ship as the new, optional `civiccast[agenda-js-import]`
  extra, pinned to `crawl4ai>=0.9.2,<0.10` — **not** the first floor this
  extra was drafted against (`0.7.4`): that version pins `lxml~=5.3`, which
  collided with `pikepdf`/`sacrebleu`'s own `lxml` floor and forced uv's
  universal resolver to downgrade the whole project's `lxml` to 5.4.0,
  reintroducing PYSEC-2026-87 (fixed in 6.1.0) into `uv.lock` — caught via
  `pip-audit` against the resulting lock during this pass, before it ever
  reached a commit. `crawl4ai>=0.9.2` relaxed its own constraint to
  `lxml<7,>=5.3`; re-locked and re-verified clean (`lxml` stays at 6.1.2,
  `pip-audit` reports no known vulnerabilities). Not bundled by the native
  Windows installer by default
  (excluded from `requirements-native-app.txt`'s `uv pip compile` extras,
  mirroring `captions-runtime`'s existing pattern); absent, the adapter
  lazy-imports and raises a new `AgendaSourceDependencyMissingError` →
  HTTP 503, and a new, always-reachable `GET
  /api/staff/agenda-sources/js-portal/posture` route reports the honest
  install posture without raising. Also closes a real gap found while
  implementing this: an import into an **already-published** agenda now
  reopens it to draft (mirrors `AgendaService.import_from_doc`'s existing
  PDF-import behavior) — applied to all four vendors, not just
  `js_portal`, since AI/agenda non-negotiables §4.2 ("operator approves
  before publish") is equally about a Legistar/PrimeGov/CivicClerk fetch,
  not only heuristic content. Operator console: `AgendasScreen.tsx` gains
  an "External agenda import" section (source picker, discover-then-import
  flow, `js_portal`'s not-installed/loading/installed posture states) —
  the vendor-bridge API had no console consumer at all before this phase.
  62 new backend tests (`tests/agenda_import/test_js_portal.py`
  plus router/mapper additions) against synthetic CivicPlus/Granicus-shaped
  fixtures (no live-site CI dependency) and 14 new frontend tests; ruff/
  mypy --strict/tsc/eslint clean. Live-smoke-tested by hand against a real
  CivicPlus tenant (`friscotexas.gov/AgendaCenter`) — the crawl pipeline
  itself works end to end, but that tenant's real meeting rows only render
  after an interactive category-selection step this v1 does not perform,
  so today's extraction is an honest low-yield miss on that shape of
  tenant, not a silent wrong answer — see `js_portal.py`'s module
  docstring for the full live-verification ledger. See
  `docs/spec/3.0/sections/S27-agenda-import-bridge.md` (net-new — no
  spec section existed for this module before this phase) for the full
  design and status.
- **S14 (Analytics / Audience Measurement) — durable viewership store.**
  Migration `0076_analytics_viewership` (three tables: `viewership_events`,
  `viewership_rollups`, `analytics_report_snapshots`) promotes the
  playback-beacon → aggregate-report chain from a single JSON file
  (`analytics-events.json`) to a durable Postgres-backed store —
  `PostgresAnalyticsStore` plus a periodic `AnalyticsRollupWorker` that folds
  raw events into VOD-24h and Live-30-min/hourly rollup buckets. Idempotent
  one-time backfill migrates any pre-existing JSON events on first durable-
  storage boot. Net-new role-gated (`support_admin`/`publish_operator`) staff
  API: `GET /api/staff/analytics/rollups`, `GET .../export.csv`,
  `POST .../reports/board-pdf` (a one-click board-ready PDF — totals, top
  content, year-over-year, live-event peaks — via `reportlab`); `GET
  .../reports/overview` extended with `stream_type`/`metric` params and
  `vod_rollups`/`live_rollups`/`year_over_year`/`ingest_configured` fields.
  Operator console: `AnalyticsScreen` gains a four-panel dashboard (toolbar,
  bar + time-series charts via a new dependency-free SVG `RollupChart`
  component, stats + expandable rollup table) and an honest "telemetry is
  off" empty state when public analytics ingest isn't configured. As-run /
  proof-of-performance reporting (Schedule Report + Shows Report parity) is
  served by the existing `civiccast/reporting` surface (S18/S23) rather than
  duplicated. See `docs/spec/3.0/sections/S14-analytics-audience-measurement.md`
  for the full build-vs-spec status and known gaps (OTT/embedded beacon
  parity and the master soak run are not yet done).
- **S1 StationBoxProfile — cable/PEG appliance-readiness capability model.**
  `civiccast/platform/station_box_profile.py` extends `hardware.probe()`
  with a full readiness report: GStreamer playout-engine prerequisite
  detection per S15 tier (`EngineReadiness`/`EngineTierVerdict`), a
  RAM-keyed AI-default table (`select_ai_defaults`, `gemma4:12b` at ≥16GB
  system RAM), the fail-closed `PegReadinessRollup`, and the
  soak-pending `CableOsVerdict` (never prints a green single-Windows-PC
  cable certification before MASTER §13.1 resolves). Computed, no DB
  table. `civiccast doctor --profile` renders it (human + `--json`); the
  plain `doctor`/`doctor --json` output is unchanged for back-compat.
  `GET /api/staff/station-box-profile[/readiness]`, role-gated. New
  `GET`/`PUT /api/staff/station/profile` exposes the mutable station
  identity (name, timezone, storage roots) with an env-override-first
  precedence loader (`resolve_station_timezone`/`resolve_station_display_name`/
  `resolve_station_storage_locations` in `installer/station_state.py`);
  `app.py`'s `_station_tz` now delegates to the shared loader instead of
  re-implementing the precedence chain inline. New operator-console
  **Station Profile** screen. 40 + 13 + 11 new tests.
- **S3 commissioning wizard (screens 8-11).**
  `civiccast/installer/commissioning.py` implements the post-first-admin
  cable commissioning flow: first-run cable checks (11 checks, reusing S1's
  `StationBoxProfile` and the existing durable-storage/NATS health probes —
  no re-implemented probes), channel-setup validation against the S2
  `HeadendProfile` catalog, a bounded output-proof run (a real ffmpeg
  SMPTE-bars+tone generator driven concurrently with the existing TSDuck
  compliance prober, fail-closed), and the final commissioning report.
  State persists to station-state JSON (`CommissioningState`, one
  namespaced key, no DB table) so a restart mid-commissioning resumes
  from the last completed step. New `POST /api/staff/cable/commissioning/
  {checks,channel-setup,output-proof,report}` + `GET .../state`. New CLI:
  `cable doctor`/`commission`/`support-bundle`, `output sdi-readiness`,
  `egress output test-pattern`. New operator-console **Cable
  Commissioning** screen (4 server-state-gated panels). Every proof run
  carries an explicit `not_claimed` boundary: this is a headend/format
  proof via ffmpeg + TSDuck, not a physical SDI/DeckLink hardware proof
  (rung 3 remains gated on real DeckLink hardware, MASTER §13.2); a
  requested CEA-708 passthrough check is always reported unverified
  (`cea708_verified: null`), never faked. 23 + 11 + 6 new tests.
- **S10 field-certification amendment.** Dated 2026-08-21 amendment atop
  `docs/spec/3.0/sections/S10-field-certification-and-proof-ladder.md`:
  field certification for the native-Windows line is proven by Gate A
  (`docs/ops/gate-a.md`) and Gate B (the real-hardware 24h reboot soak),
  not by the rung-runner pipeline S10 originally specified (never built;
  the *legacy* pre-Gate-A rung-numbered pipeline that did exist was
  removed in PR #12, commit `ef27958`). The rest of S10 is kept intact as
  a historical design record.
- **S7 media lifecycle & readiness (real build; corrects a false `status:
  built` in `ROADMAP.status.yaml`).** The five net-new S7 entities
  (`MediaIngestJob`, `TranscodeJob`, `AssetReadiness`, `WatchFolderConfig`,
  `AssetRetentionPolicy`) plus `AssetArchiveProof` and an append-only
  `media_lifecycle_audit_log` land in one migration
  (`0079_media_lifecycle`, chained after PR #21's `0078_agenda_item_confidence`
  — renumbered from an original chain onto S14's `0076_analytics_viewership`
  when `0078` merged to `main` ahead of this branch),
  backed by `civiccast/schedule/
  media_lifecycle_{models,worker,store,router}.py`. The worker (mirrors
  `retention_worker.py`'s inline/off + poll-seconds + dry-run shape)
  recomputes each asset's readiness badge, seeds and dispatches ingest-time
  transcode jobs through an injectable `TranscodeExecutor` (production:
  `FfmpegTranscodeExecutor`; tests: a stub), and verifies archival. Staff
  API: `GET /api/staff/assets/readiness-dashboard`,
  `GET /api/staff/assets/{asset_id}/readiness`,
  `PUT /api/staff/assets/{asset_id}/replace-source` (old file archived, not
  deleted), `PUT /api/staff/assets/{asset_id}/legal-hold`, and CRUD +
  storage-budget + missing-media + audit-log routes under
  `/api/staff/media-lifecycle/*`. Operator console: a Readiness column on
  the Assets screen, a Media Lifecycle detail panel on the asset editor
  (loudness gate, archive tiers, legal hold, replace-source), a new
  Missing Media screen, and a new Media Lifecycle Settings screen
  (watch folders, retention automation, storage budget).
  Also closes a previously-unflagged gap behind CLAUDE.md's §4.6 archival
  non-negotiable ("nothing is marked archive-complete unless portal + IA +
  local NAS copies are verified"): nothing persisted `ArchiveProof` values
  before this, and `public_archive_complete` was an operator-settable bool
  with no verification behind it. `AssetReadiness.archive_complete` is now
  computed by the worker from verified, non-simulated `AssetArchiveProof`
  rows only. New `Asset.legal_hold` / `legal_hold_reason` columns;
  `retention_worker.py` now skips held assets outright, regardless of how
  far past `retention_until` they are.
- **This repository.** 2,090 files, ~24 MB, copied from the native-Windows
  release line. The old (private, not archived) repository's 286 MB of
  packed history — WSL-era churn plus roughly 640 MB of historical Git-LFS
  tester binaries — does not transfer, by construction.
- **S12 OTT apps — de-duplicated, CI-built on hosted runners.**
  `.github/workflows/ci-ott-apps.yml` is the first machine build for any of
  the `civiccast/apps/ott-native/` app sources: Roku gets a real
  BrightScript static check (`brighterscript`/`bsc`) + zip package; Android
  gets a real `gradle assemble*Debug` build (checked-in wrapper —
  `android/gradle/wrapper/gradle-wrapper.jar` was missing before this);
  Apple gets a real `xcodebuild build-for-testing` (unsigned, simulator) on
  `macos-latest`; LG webOS gets a real `ares-package` build
  (`@webosose/ares-cli`, no device needed); Samsung Tizen attempts a real
  `tizen package` build and honestly falls back to a static `config.xml`
  contract validation when the ~260 MB license-gated Tizen Studio CLI can't
  complete headlessly on the runner (see `tizen/README.md`). Also
  de-duplicated the source trees: `android-tv/` and `fire-tv/` (two entire
  copied Gradle projects differing only in `applicationId` and a few
  manifest lines) are now one module, `android/tv-app`, built as the `tv`
  and `firetv` product flavors; `ios/` and `tvos/` no longer each carry
  their own copy of `CivicCastApp.swift`/`CivicCastCore.swift` — both
  Xcode projects reference the single copy in the new `apple-shared/`.
  Added the two platforms that had no source at all: `tizen/` and
  `webos/`, both thin wrappers around one canonical playback client,
  `web-shared/civiccast-player.js`. Every native target now calls the real
  `StationAppConfig`/`LiveState` app-platform contract (fetch config,
  resolve the default channel, fetch its `live_state_url`, play
  `playback_url`) instead of a flattened per-platform stand-in JSON shape.
- `docs/design/` — six design records (supervisor, installer lifecycle,
  migration contract, dual-runtime guard, native-beta recovery, the sub-300 MB
  bootstrap plan) hand-carried out of the otherwise-scratch `.agent-runs/` tree.
- `docs/evidence/` — the proof documents `docs/claims/claims.yaml` binds, also
  rescued from `.agent-runs/`.
- `scripts/wp5_lifecycle_driver.py` — the WP-5 clean-venue lifecycle proof
  driver, previously marooned in `.agent-runs/` and imported by
  `tests/native/test_wp5_lifecycle_driver.py`.
- `scripts/policy/check_workflow_timeouts.py` — fails the build when a workflow
  job declares no `timeout-minutes` (GitHub's default is 360) or exceeds the
  180-minute cap without a written exemption.
- **Gate A — automated station-acceptance release gate.** Replaces
  builder-authored "it works" claims with a machine verdict: a clean Windows
  Sandbox install of a native-beta candidate kit, K1 activation, runtime
  health, both UIs rendered, the clerk loop (upload → publish → captions),
  the product egress engine verified with TSDuck, and a bounded soak —
  judged fail-closed by `scripts/gate_a_verdict.py` against files a harness
  wrote, never from prose. `sandbox-lab/` imports a standalone, manually-
  proven harness (`Host-Launch-Sandbox-Test.ps1` + `In-Sandbox-Report.ps1`)
  plus the v3.0 tester-handoff `soak-4h/` kit; `sandbox-lab/Run-GateA.ps1` is
  the host orchestrator (kit resolution from a `native-beta-candidate-artifacts`
  run, fresh install every run, evidence preservation); `.github/workflows/
  gate-a-station-acceptance.yml` runs it after every successful candidate
  build on a new `[self-hosted, windows, sandbox-lab]` runner
  (`sandbox-lab/runner/Install-GateARunner.ps1`, an interactive-logon
  scheduled task — Windows Sandbox cannot launch from a Session-0 service).
  Informational only until 3 consecutive green runs; promotion to a required
  check is owner-only. See `docs/ops/gate-a.md` for the full verdict-criteria
  table with §12 citations, including the documented `t4_engine` policy
  (`PASS_FFMPEG_FALLBACK` is a FAIL now that GStreamer is the default engine)
  and the known Aug-19 reference-run harness quirk (that historical run has
  no `DONE.json`, so its own fixture judges FAIL on `completion` alone — not
  a bug, see the doc's "Known harness quirk" section).

### Removed

- **The legacy pre-Gate-A "rung-numbered" release-gate pipeline.** CLAUDE.md
  already stated "there is no rung ladder and no time-boxed altitude
  schedule" and that verification is layered by change type, not a fixed
  cadence — this cleared out the Stage 1-7 (release-plan rungs 3.3-to-4.0)
  script family that the statement had already superseded. Gate A (sandbox-
  lab station acceptance, `docs/ops/gate-a.md`) is the live machine-gate
  replacement; Gate B (24h reboot soak) is separate, tracked on its own.
  36 files removed, ~7,650 lines:
  - Runner scripts: `scripts/run_stage1_release_gate.py` (the named Stage 1
    orchestrator, `STAGE_ID="3.3"`) and its 12 siblings
    (`run_stage1_lifecycle_proof.py`, `run_stage2_completion_report.py`,
    `run_stage2_operator_workflow_proof.py`, `run_stage3_completion_report.py`,
    `run_stage3_control_room_adapter_proof.py`, `run_stage4_completion_report.py`,
    `run_stage4_virtual_lab_proof.py`, `run_stage5_completion_report.py`,
    `run_stage5_migration_records_proof.py`, `run_stage6_completion_report.py`,
    `run_stage7_completion_report.py`, `run_stage7_final_readiness_proof.py`),
    plus their two shared helpers `scripts/stage_report.py` and
    `scripts/run_stage_gate.ps1`.
  - Their 14 dedicated tests (`tests/test_stage1_release_gate.py` through
    `tests/test_stage7_final_readiness_proof.py`, plus `test_stage_report.py`).
  - Their 7 dedicated runbooks under `docs/ops/` (`stage-completion-gate.md`,
    `stage1-installer-lifecycle-verification.md`, `stage2-operator-workflow.md`,
    `stage4-virtual-media-studio.md`, `stage5-migration-archive-records.md`,
    `stage6-resilience-compliance.md`, `stage7-final-readiness.md`).
  - No `.github/workflows/*` ever invoked this family — it was CI-dead,
    manually run only. `docs/ops/stage3-audio-mixer-device-layer.md` and
    `docs/ops/stage3-control-room-device-adapters.md` were kept: despite the
    "Stage 3" filename pattern, they are real operator-facing device
    reference docs (Allen & Heath SQ MIDI protocol, vMix/OBS/ATEM adapter
    behavior) that live product code
    (`civiccast/control_room/lpm_lab_stage45.py`) still points operators to.
    `docs/spec/3.0/sections/S10-field-certification-and-proof-ladder.md`
    (the master §5 proof-ladder spec text) was left untouched: it already
    states its release-gate checklist is "missing" / implementation
    readiness "TBD" rather than claiming the deleted machinery exists.

- **The WSL2/Ubuntu bootstrap lane, finished.** CLAUDE.md and BRANCHES.md
  already declared the WSL2 lane retired (2026-08-19) and "not present
  here"; this cleared out the leftover code, tests, and documentation that
  still built, tested, or described it as if it were.
  - `civiccast/apps/installer/src-tauri/src/main.rs`: the entire WSL2/Ubuntu
    installer lane — `is_wsl_bootstrap_lane` and its dispatch branch, the
    `StartupBranch` native-vs-WSL split (collapsed to native-only, since
    every Windows control plane this binary produces IS the native one),
    the WSL2/Ubuntu feature-enable and provisioning pipeline
    (`launch_wsl_ubuntu_install`, `install_wsl_ubuntu_for_current_user`,
    `run_wsl_health_sequence`), and the headless runtime-bootstrap pipeline
    built around the already-deleted `headless-bootstrap.ps1` resource
    script (`run_headless_bootstrap`,
    `bootstrap_civiccast_runtime[_headless]/_via_script`, the
    `--civiccast-bootstrap-unattended` CLI flag). ~2,530 net lines removed.
    Two real leftover bugs fixed in the same pass, not just dead code: the
    "Open installer log" button pointed at two files that no longer exist
    (now points at the native runtime host's own `runtime-host.log`), and
    the "repair"/"retry"/"continue" installer actions on the runtime-family
    lanes called into the deleted headless-bootstrap pipeline (now start
    and re-verify the native runtime host process, reusing the same
    primitives the startup path already used). The runtime-host watchdog
    (`run_civiccast_runtime_host`, `--civiccast-runtime-host`) no longer
    spawns or monitors a companion `wsl.exe` process or shells into a WSL
    distro to restart `civiccast.service` — `CivicCastSupervisor` is a real
    Windows service with its own SCM restart-on-failure actions, so the
    watchdog's job for native is honest health observation, not a second
    recovery path.
  - `civiccast/apps/installer/src-tauri/nsis-hooks.nsh` — the retired WSL2
    product's NSIS hook file (distro autostart/terminate/unregister). The
    base `tauri.conf.json` no longer declares `installerHooks` referencing
    it; nothing in this repository's build scripts or CI ever built that
    base config directly (they always pass
    `--config tauri.native.conf.json`), so nothing that ships changed.
  - The installer frontend's dead WSL2 lane UI: `wsl-affordances.ts`
    (renamed `lane-affordances.ts` with the WSL predicates removed — the
    prior retirement pass had already hardcoded them to always return
    `false` rather than deleting the branches that read them),
    `keyboard-activation.ts`/`.test.ts` (its entire purpose was arming a
    shortcut on the WSL bootstrap lane, always-false and therefore dead),
    `progress-visual.ts`'s `isWindowsBootstrapProgress`/
    `windowsBootstrapProgressIsIndeterminate`, `installer-transition.ts`'s
    `markWindowsBootstrapResultPending`, and every WSL-only branch in
    `App.tsx` (the `WindowsSetupActivity` component, the WSL half of
    `continueLane`, the dead keyboard-shortcut effect).
  - `civiccast.installer.platform`/`civiccast.installer.service` (Python):
    the *backend* twin of the same leftover, and a live one —
    `/api/staff/installer/summary` (the endpoint the installer frontend
    actually polls) could still produce `platform="windows-wsl2"` and "Set
    up Windows helper" wording under real, reachable conditions, not just
    from a legacy state file. `PlatformBootstrapPlan`'s `os_family` no
    longer accepts `"windows"` (Windows readiness is decided entirely by
    this process's own native-station activation signals now); the
    Windows-drive-to-WSL-mount path translation in
    `_backup_destination_path` is gone; the support bundle's log collector
    no longer looks for `bootstrap-wsl2-ubuntu.log` under
    `%LOCALAPPDATA%\CivicCast` (a path nothing writes to anymore) and now
    reads the native runtime host's own log instead.
  - `civiccast/installer/contribution_install.py`: coturn's Windows
    guidance no longer says "run it under WSL" — coturn has no native
    Windows build, so it is now a documented **external** TURN server
    (`CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT` point at one;
    `CIVICCAST_COTURN_COMMAND` stays unset).
  - `scripts/policy/check_release_artifacts.py`'s cross-platform installer
    policy check had the WSL retirement backwards: it FAILED any doc that
    claimed "native windows service" or "without wsl2", instructing the
    author to rewrite Windows claims as WSL2-only bootstrap support. It now
    rejects the opposite — a doc that still claims the Windows installer
    requires or bootstraps WSL2. Running the corrected check immediately
    surfaced a real violation: `INSTALL-WINDOWS.md` was written entirely
    for "the public WSL2 line (`main`, `v1.0.0-rc18`)" and linked to three
    release-verification docs and a GitHub release page that belong to the
    old, private `scottconverse/civiccast` repository and do not exist or
    resolve here. Marked the WSL2-line content historical (kept, not
    deleted — rewriting a historical beta's own record would be
    revisionist) and did the same for `docs/installer/
    cross-platform-installer.md`, `docs/installer/beta-tester-handoff.md`,
    and `docs/adoption/early-adopter-quickstart.md`.
  - `tests/policy/test_windows_wsl_bootstrap_script.py` (deleted) and
    `tests/installer/test_uninstall_residuals.py` (deleted): of the former's
    ~45 tests, 32 tested the deleted WSL2 pipeline or NSIS macros; the
    other ~13 tested genuinely shared infrastructure (IPC capability,
    blocking-pool dispatch, the local installer-state read/write path) and
    were carried into the newly added
    `tests/policy/test_native_installer_runtime_infra.py`. The latter's
    tests entirely exercised the deleted `nsis-hooks.nsh` macro and a
    disposable WSL clean-machine verifier; the native hooks file
    (`nsis-hooks-bootstrap.nsh`) already has its own dedicated coverage in
    `tests/installer/test_nsis_bootstrap_hooks.py`.
  - `tests/policy/test_native_installer_identity.py`: replaced its
    "native and WSL product identities are disjoint" assertions (moot once
    there is only one product) with a positive assertion that the native
    hooks file is the only one wired and the base config declares no
    `installerHooks` of its own.
  - `tests/installer/test_platform_bootstrap.py`: rewritten to cover only
    Linux/macOS — one deleted test asserted that a *native* Windows service
    plan gets **rejected**, the exact opposite of current reality.
  - Stale "WSL2 is the primary/current/public" framing corrected in
    `README.md`, `ARCHITECTURE.md`, `FAQ.md`, `SUPPORT.md`,
    `CONTRIBUTING.md` (its base-branch instruction pointed contributors at
    a `release/native-beta-1.0.0-beta.1-rc1` branch that does not exist in
    this repository), `SECURITY.md`, `CLAUDE.md` (the old repository is
    private, not archived — two instances), and
    `civiccast/platform/hardware.py`'s `OSKind` doc (cited the
    now-superseded ADR-0003 and called native Windows "not a supported
    deployment"). `.github/ISSUE_TEMPLATE/bug-report.yml`'s deployment
    dropdown no longer offers "Windows 11 + WSL2 (Ubuntu 24.04)" or
    "Docker" as options.
  - `civiccast/native/*` and `civiccast_native_uninstall.rs`'s
    `native`/`wsl`/`absent` `ActiveRuntime` selector, cutover/rollback
    commands, and dual-runtime start guard are **unchanged, deliberately**.
    This is real coexistence-safety logic for a machine that may still
    carry a live WSL CivicCast install or registry ownership marker from
    before the retirement — it protects against a native install/repair
    silently clobbering that other product's ownership state, which is a
    different concern from installing or running CivicCast on WSL.
- **The WSL2/Ubuntu leftovers wave 1 held back, finished (wave 2).**
  - `scripts/build_release_artifacts.py` (~1,540 lines) — the WSL2-target
    release-artifact pipeline (Linux wheelhouse build for the retired
    WSL2 install target, a WSL clean-machine preflight script generator).
    Not wired into any live workflow after `release-artifacts.yml` was
    deleted; its only in-repo callers (`scripts/run_stage1_release_gate.py`,
    `scripts/run_stage7_final_readiness_proof.py`, `scripts/stage_report.py`)
    are themselves pre-Gate-A, pre-native-repo legacy orchestrators
    (rung-numbered `3.3`→`4.0`, superseded by Gate A) that only embed its
    path as a subprocess command string in unit tests, never execute it in
    CI. Deleted with its dedicated test coverage
    (`TestReleaseArtifactBuilderContracts` and the WSL clean-windows-verifier
    test in `tests/installer/test_package_artifacts.py`, the release-manifest
    coherence test in `tests/installer/test_beta_handoff.py`). Docstring/
    comment references in `civiccast/installer/packages.py`,
    `scripts/policy/check_sidecar_attestation_integrity.py`, and
    `civiccast/installer/handoff.py`'s operator-facing guidance updated to
    stop pointing at the deleted script.
  - `scripts/run_airgap_vm_proof.py` and
    `scripts/prove_native_inventory_reconciliation.py` — both required a
    WSL2 VM / an extracted WSL installer's bootstrap+wheelhouse as
    mandatory inputs that do not exist in this repository (the WSL backend
    was already purged). Deleted with their tests
    (`tests/integration/test_airgap_vm_proof.py`,
    `tests/native/test_inventory_reconciliation.py`); the collection-count
    floor in `tests/policy/test_native_caption_workflow_policy.py` re-derived
    accordingly.
  - `scripts/run_clean_windows_install_proof.py` — a genuinely native-Windows
    proof runner; kept, with its `wsl2-fresh-distro`/`wsl2-fresh-user`
    isolation strategies and their WSL-detection helpers
    (`_detect_ubuntu_wsl_distro`, `_wsl_python312_ready`, `_to_wsl_path`,
    the `partial` proof status they produced) removed, and its VirtualBox
    report validator's dependency-absent first-run check fixed: it required
    a `current_lane_id: "wsl2"` / "Set up Windows helper" installer state
    that the installer can no longer produce at all (the whole "blocked,
    needs a Windows helper" first-run status was retired with the WSL2
    lane), which meant the check could never pass on a real report. Its
    test suite (`tests/integration/test_clean_windows_install_proof.py`)
    updated to match.
  - `civiccast/apps/installer/scripts/verify-bundle-resources.mjs` — the
    Tauri bundle-resource guard required a Linux wheelhouse and a Linux
    GStreamer runtime tarball (for the retired WSL2 hand-off) that nothing
    in the shipped app reads at runtime, and its error message pointed at
    the now-deleted `build_release_artifacts.py`. `scripts/build_native_installer.py`
    already bypassed this exact guard for that reason (see its updated
    `run_tauri_build` docstring); the guard itself now only requires
    `bootstrap-manifest.json`, the one resource `main.rs` actually reads.
  - `civiccast/egress/gst/{engine,worker,graph,control}.py` — WSL-specific
    docstring/comment wording (`"WSL/Linux"`, `"WSL/LPM-validated"`)
    generalized to POSIX/Linux-macOS, since the dual-platform logic itself
    (Windows named-pipe vs. POSIX FIFO control channel) was never
    WSL-specific — it is unchanged. `docs/claims/claims.yaml` re-bound to
    the new blob hashes for all four files (two claim entries plus the
    `graph.py` fixtures entry); `audio_tap.py` had no WSL text and was not
    touched.
  - Rewrote `docs/USER-MANUAL.md`'s WSL2/Ubuntu install-flow claims (the
    installer bootstrapping a WSL2 helper and SQLite storage, GStreamer
    under `/opt/civiccast/gstreamer`, TSDuck installed into WSL2 Ubuntu,
    provisioning "inside Ubuntu WSL2") to describe the real native install
    (Windows service via SCM, bundled runtime tree, on-demand per-user
    TSDuck fetch) and repointed all 41 `scottconverse/civiccast` blob/tree
    links to `scottconverse/civiccast-native`; regenerated
    `USER-MANUAL.pdf`/`.docx`/`.render.json` (`--check-current` PASS).
    `docs/technical-ops-reference.md`'s stale WSL2 wheelhouse air-gap
    instruction removed (the paragraph already disclosed the claim as
    unproven for native).
  - `civiccast/apps/installer/README.md`'s "Current Posture" section
    described the retired WSL2 Ubuntu/systemd/`/opt/civiccast` runtime
    wholesale; rewritten to describe the real native Windows service.
  - Added historical banners (matching the existing pattern in
    `docs/installer/beta-tester-handoff.md` and
    `docs/installer/cross-platform-installer.md`) to
    `docs/tester/known-limitations.md`'s WSL Public-Beta Line section and
    `docs/tester/station-implementation-walkthrough.md`, both of which
    described the retired rc-numbered WSL2 line's setup/release process
    without any such disclaimer. Removed the WSL2 support-bundle caveat
    from `docs/tester/support-bundle-instructions.md` and corrected its
    claimed log source to the real native runtime-host log; removed the
    WSL2 Ubuntu distro field from `docs/tester/bug-report-template.md`.
  - `Makefile`'s `cleanroom`/`cleanroom-build`/`cleanroom-run`/
    `cleanroom-shell` targets referenced `docker/cleanroom.Dockerfile`,
    which does not exist in this repository (`docker/` was excluded with
    the retired lane). Removed; `.pipelines/roles/pre-push-verifier.md`'s
    matching "run `make cleanroom`" step rewritten to say plainly that no
    automated clean-box gate exists here, per the same rule already stated
    in this file's "Verification that actually gates this repo" section.
  - Fixed `gh api repos/scottconverse/civiccast/...` commands that should
    have targeted this repository in `docs/ops/branch-protection.md`,
    `docs/ops/self-hosted-ci.md`, and this file's own cross-agent audit
    protocol section — each would have queried or modified the wrong
    (private, old) repository if actually run.
  - `.github/ISSUE_TEMPLATE/config.yml`'s security-report and release-plan
    contact links repointed to this repository (both exist here); its
    Discussions link left pointing at the old repository with an honest
    note, since `scottconverse/civiccast-native` does not have Discussions
    enabled. `SUPPORT.md`'s GitHub Issues link repointed the same way.
  - Three `TODO`/`FIXME`/`HACK` markers `scripts/policy/check_no_todos.py`
    flags as blockers (`civiccast/captions/router.py`,
    `civiccast/egress/router.py`, `civiccast/native/upgrade/seams.py`)
    moved into a new `next-cleanup.md` and reworded in place per that
    policy's own stated design; `docs/openapi.json` regenerated (the routes'
    descriptions changed).

- **NATS JetStream, removed entirely (2026-08-20, owner decision).** NATS
  never did real production work in this codebase — the platform
  event-broker substrate always defaulted to an in-process adapter — so it
  is cut from the product: the supervised child process, the
  `civiccast.platform.nats_broker` module, NATS provisioning, the
  installer's NATS/JetStream mTLS readiness check, the Rust installer's
  NATS references, the `nats` certificate identity
  (`civiccast/certs/authority.py`), and the corresponding tests. ADR 0023
  records the reversal and supersedes ADR 0001 (ADRs are immutable once
  Accepted — ADR 0001's own text is untouched; the supersession is recorded
  one-directionally in ADR 0023). `civiccast.platform.broker.InProcessBrokerClient` is the only
  broker adapter for every deployment mode; `civiccast.platform.broker_config`
  no longer has a "production" mode, NATS URL/stream/mTLS settings, or a
  JetStream readiness gate. This closes out the size, process, port, config,
  and health-gate cost NATS carried without ever being load-bearing.

### Changed

- **Egress default engine flipped to GStreamer (S15).** `civiccast/egress/engine_select.py`'s
  `_DEFAULT` moves from `"ffmpeg-concat"` to `"gstreamer"` -- an unset
  `CIVICCAST_EGRESS_ENGINE` now selects the persistent-pipeline GStreamer engine,
  matching the native station bootstrap's own runtime contract
  (`civiccast/native/station_runtime.py`'s `EXPECTED_RUNTIME_CONTRACT`) and fixing
  the class of bug that continuity bug #151 belonged to (per-segment ffmpeg
  relaunches resetting the MPEG-TS continuity counter) for every caller that
  builds an `EncoderStrategy` without an explicit engine. `CIVICCAST_EGRESS_ENGINE=
  ffmpeg-concat` remains a live, fully-supported override for deployments that
  still need the legacy engine; the GStreamer -> self-repair -> FFmpeg ->
  fallback-slate degraded-mode chain (`station_runtime._resolve_gstreamer_egress_
  environment`, `egress.daemon.EgressDaemon`) is unchanged. Also fixes a latent
  edge case surfaced while flipping the default: a present-but-blank
  `CIVICCAST_EGRESS_ENGINE=` now resolves to the same engine as an unset one,
  instead of silently pinning ffmpeg-concat via its old membership in
  `_FFMPEG_ALIASES`.
- **Windows-only by decision.** No `docker/`, no systemd units, no WSL2 install
  target, no Linux GStreamer container build. The native product uses the
  pinned `gstreamer-*==1.28.5` PyPI wheels.
- `civiccast/egress/{service_unit,recovery,soak}.py` and the `.deb`/`.rpm`
  builders are gone, with `civiccast/cli.py`'s `egress enable` and
  `egress recovery-proof` subcommands. **`egress recovery-proof` was an
  operator-visible command** — it measured egress recovery against a systemd
  unit; the native equivalent is the supervisor plus
  `civiccast/native/gstreamer_repair.py`.
- Type checking (`ci-lint`) runs on `windows-latest`. The same commit reports
  112 mypy errors on Linux and 23 on Windows; the extra 89 are artifacts of
  checking Windows-only code on a platform this product never runs on.
- Artifact retention is **1 day** everywhere, at both the workflow and
  repository level.
- **Sigstore/cosign attestation requirement removed (ADR 0022).** Evaluated
  and denied by the owner: this release chain's only supply-chain provenance
  is Azure Trusted Signing (Authenticode) for the Windows installer plus
  ed25519 pack signing for native distribution packs
  (`civiccast/installer/native_packs.py`). `civiccast.installer.packages
  .verify_package_artifact` no longer requires a `*.sigstore.json` bundle —
  nothing in the native chain ever produced one — and instead checks real
  embedded Authenticode certificate-table evidence for a Windows `.exe`
  claiming `signed: true`; a `signed: true` claim for any non-Windows package
  kind is rejected outright, since this product line has no signing
  mechanism for those. `scripts/policy/check_sidecar_attestation_integrity.py`
  and `scripts/policy/check_release_artifacts.py` follow the same rule; package
  sidecars now always carry a null `attestation` field. `CODE_SIGNING_POLICY.md`,
  `docs/install/windows-release-trust.md`, and
  `docs/installer/cross-platform-installer.md` describe the Authenticode +
  ed25519 chain instead of Sigstore.

### Fixed

- **Self-hosted native-beta candidate build — `_work\_temp` scratch dirs
  from a failed run blocked the next run, starting with `civiccast-build-
  venv`.** Candidate run 32810709045 failed "Bootstrap the reviewed Python
  build environment": `uv sync` refused `civiccast-build-venv` as "not a
  valid Python environment (no Python executable was found)" because the
  PREVIOUS self-hosted run (32806127399, a different bug, fixed separately)
  died mid-`uv sync` and left a half-created venv at that exact path — a
  hosted runner's `RUNNER_TEMP` is always fresh, so this class of bug never
  surfaces there. Inventoried every `RUNNER_TEMP`-scoped scratch dir across
  both build jobs against the workflow and the scripts it calls and found
  the same shape twice more, both latent: `build_native_app_payload.py`'s
  `build()`, `build_native_pyav_wheel.py`'s `build()`, and
  `build_native_runtime_closure.py`'s `build()` all refuse to write into a
  non-empty output directory. The "Bootstrap the reviewed Python build
  environment" step now clears an invalid `civiccast-build-venv` (missing
  `Scripts\python.exe`) before `uv sync` runs, relocating to a uniquely
  suffixed sibling path if it cannot be removed (still in use by
  something) rather than failing the job; a complete, valid venv is left
  untouched and reused. A new self-hosted-only step, "Ensure a clean
  self-hosted scratch tree before the pack build", clears
  `civiccast-app-payload`, `civiccast-app-payload-scratch`, and
  `civiccast-gstreamer-closure` before every self-hosted pack build (hard
  failure with a clear diagnostic if a leftover genuinely cannot be
  removed — none of these are known to be held open by a long-running
  process the way MSVC's own toolchain is) and best-effort clears
  `civiccast-gstreamer-stage` (non-fatal; its own `build()` does not
  require an empty directory). `civiccast-msvc-build-tools` gets a
  different fix, since a real MSVC Build Tools install is expensive to
  redo (~1.8 GB, real minutes): `provision_native_build_toolchain.py`'s
  `install_msvc()` now re-verifies a pre-existing install with the same
  real `cl.exe`/`link.exe` launch-and-version check a fresh install already
  trusted before reuse, and reinstalls only when that fails. A live
  follow-up on this exact candidate found that the runner's own attempt to
  clear an invalid MSVC tree by hand left an undeletable, unknown-
  completeness 1.8 GB leftover (`vctip.exe`/`mspdbsrv.exe` still holding
  files open) — `install_msvc()` now falls back to a uniquely suffixed
  sibling directory rather than failing the job when an invalid tree
  cannot be removed, and `main()` re-exports the actual resolved path to
  `GITHUB_ENV` so every later step that reads
  `$env:CIVICCAST_MSVC_INSTALLATION_PATH` as a fixed literal (the Tauri
  build's `vcvars64.bat` import, the pack build's own env block) picks it
  up automatically. Checked (not assumed) that the toolchain/pack-build
  download caches and the Ollama-model/captions-floor caches were already
  safe: every one downloads to a `.partial` file, hash-verifies it, and
  only then atomically renames it into place, so a killed download can
  never leave a cache entry a later run would wrongly trust — no change
  needed there. `tests/native/test_build_toolchain_provisioner.py`: +5
  tests for `install_msvc()`'s reuse/replace/relocate paths and `main()`'s
  `GITHUB_ENV` re-export. `actionlint` and the full policy suite pass;
  hosted-lane behavior is unchanged in every case (a hosted runner's
  `RUNNER_TEMP` never pre-exists, so every new reuse/relocate branch is
  unreachable there and each fix falls straight through to its pre-fix
  behavior).
- **Self-hosted native-beta candidate build — the advisory PyAV wheel hash
  never reached the install step, so run 32806127399 failed
  `uv pip install --require-hashes` with "Failed to download `av==18.0.0` /
  Hash mismatch" right after the advisory build had already accepted that
  same wheel with only a `::warning::`.** `--advisory-pyav-wheel-hash`
  (`docs/process/pyav-wheel-reproducibility.md`) was wired into
  `build_native_pyav_wheel.py`'s own `verify_artifact()` check on the
  compiled wheel, but `build_native_app_payload.py`'s
  `install_pinned_dependencies()` still ran a single unconditional
  `uv pip install --require-hashes -r requirements-native-app.txt`, which
  re-enforces that exact same hosted-reviewed hash for `av==18.0.0` —
  self-hosted physically cannot produce byte-identical MSVC output (see the
  doc), so the install always failed on that lane regardless of a clean
  build. Not an index/resolver miss: `--no-index --find-links` correctly
  found the locally built wheel; it failed the hash check against the
  requirements lock. `install_pinned_dependencies()` now takes the same
  `advisory_pyav_wheel_hash` flag `build()` receives: when set, `av`
  installs from the wheelhouse by its verified-unique filename with no hash
  check of its own (a second, unconditional `--require-hashes` install still
  covers every OTHER pinned dependency against the unmodified lock); when
  unset (the hosted lane, unchanged), a single `--require-hashes` install of
  the full lock runs exactly as before. `tests/native/test_app_payload_builder.py`
  covers both the unchanged hosted-lane invocation and the new advisory
  split-install path.
- **Gate A run 7 — the evidence shipper was starving the installer of the
  shared VSMB transport.** Every mapped folder in the sandbox VM
  (`C:\CivicCastPayload`, `C:\CivicCastHostStore`, `C:\CivicCastOutput`)
  rides one Windows Sandbox VSMB transport. Run 7, the first run on the
  shipper architecture below, failed at `d4-activate-station` with *"a signed
  station bundle (station-index.json and its packs) was not found"* — on the
  same staged kit that run 6 had activated cleanly. Comparing the installer's
  own `install-progress.log` across four runs, the two steps that never cross
  VSMB are flat to the second (`vc-redist` 4m04/4m04/4m04 → 4m05;
  `d4-provision` 25s/25s/28s → 28s) while every step that does is 1.6–4.2×
  slower in run 7 alone: `stage-packs` 6m39/6m47/7m21 → 11m26,
  `d2-verify-server-binaries` 6s/5s/5s → 21s, `d2-verify-app-payload`
  1m09/1m14/1m19 → 3m16, `d4-activate-station` 14m13/14m37/15m44 (all
  succeeding) → 35m09 and exit 67. The only new thing running underneath run
  7 was the shipper's 25-second `robocopy` tick. `In-Sandbox-Report.ps1` now
  quiesces the shipper to `-ShipQuiesceIntervalSeconds` (default 300) for the
  duration of the install via `_SHIPPER-QUIESCE.marker`, raised before the
  installer and cleared in a `finally`; the marker carries its own
  `quiesce_until_utc` expiry so a removal that never happens degrades to
  "shipping speeds back up", never to "shipping stopped". 300s stays far
  inside the host's 15-minute quiet-share bound, which
  `tests/gate_a/test_gate_a_harness_contract.py` now asserts. The mechanism
  behind the slowdown is not proven — the correlation, the clean controls,
  and the absence of any other self-hosted job on the box in that window are.
- **Gate A — the kit reached the sandbox through a two-hop junction chain.**
  `Resolve-Path` does not follow reparse points, so `Run-GateA.ps1` pointed
  `kit-download` at `sandbox-lab/kit-staging/<sha>` — itself already a
  junction to `C:\CivicCastTester\kit-staging\<sha>` after the workflow's
  reuse step — and the `.wsb` handed that two-hop chain to VSMB.
  `Host-Launch-Sandbox-Test.ps1` now resolves every `<HostFolder>` through
  reparse points to the physical directory before rendering, and
  `Run-GateA.ps1` junctions `kit-download` at the physical kit. Explicitly
  **not** the cause of run 7's failure: run 6 passed with the byte-identical
  chain, and `git clean -ffdx` recursing through such a junction was measured
  on this host and does not touch the target's contents. This is hardening.
  `Run-GateA.ps1` additionally logs the station bundle's file count and total
  bytes before launch — run 7's installer failed on "station-index.json *and
  its packs*" and the harness had only ever asserted the index file existed.
- **Gate A — the finalization path is instrumented per statement, and the
  installer breadcrumb capture moved out of it.** Runs 4, 6 and 7 all stopped
  advancing in the same three or four unlabelled statements after
  `station-diag-captured-after-t3t5`, and because the two surrounding
  `Save-Summary` calls were the only instrumentation, no post-mortem can name
  the operation. Run 7 narrows it (the complete 6844-byte copy reached the
  host, so `Copy-Item`'s handle closed) but does not close it: on this host,
  against run 7's own file, the remaining `Get-Content -Tail 80` measures
  8 ms. So the capture now runs immediately after the installer returns
  instead — a single forward read of the source into memory (16 MB cap), a
  write from memory, and the tail sliced in memory, replacing the old
  copy-then-re-read-with-`-Tail` shape — with the finalization call kept only
  as a guarded second attempt. Every statement in the path records its own
  step. Note that 8 minutes is the staleness watchdog's floor: run 7 proves
  "≥8 min", where run 6 proved "≥47 min", and they may not be the same
  failure.
- **Gate A — a run that ends via the watchdog lost its entire transcript.**
  Run 7 shipped a 686-byte `sandbox-transcript.log` — header only — despite
  150 failed station-up polls that each log a terminating error. Reproduced
  on this host: a Windows PowerShell 5.1 child that logged 100+ caught
  terminating errors still had a 689-byte header-only transcript on disk, and
  it was still 689 bytes after being killed without reaching
  `Stop-Transcript`. The transcript writer buffers in user space, and every
  watchdog-terminated Gate A run therefore loses the body. `Sync-Transcript`
  (`Stop-Transcript` + `Start-Transcript -Append`) now runs after the
  install, at the station-up verdict, and immediately before the finalization
  path.
- **Gate A — the harness stalled forever on the Windows Sandbox mapped
  folder, and its own staleness watchdog could not catch it.** Three runs
  hung late with the VM alive and the driver writing nothing further: run3
  (`8579e66`) between two consecutive ~30-byte `Add-Content` appends to
  `T3T5-RESULT.txt`; run4 (`8579e66`) and run6 (`f31618f`) both in the
  four-statement window between `Save-Summary 'station-diag-captured-after-t3t5'`
  and `Save-Summary 'install-progress-log-copied'`. Run6 had *passed every
  product check* — `T3_LOOP=PASS`, `CAPTIONS=PASS`, `T4_RESULT=PASS_PRODUCT_ENGINE`,
  `T5_RESULT=PASS beats=4 unhealthy=0` — and was then failed closed 47
  minutes later by the coarse whole-script watchdog. Run6 also disproves the
  obvious theory: 42 minutes into that stall the *separate* watchdog process
  created two brand-new files in the same mapped folder, so the share was
  alive; what was wedged was the driver's own in-flight synchronous I/O
  against it, on the single thread carrying the entire run.
  `sandbox-lab/scripts/In-Sandbox-Report.ps1` now writes everything to a
  local `C:\CivicCastLocalOut` and a separate shipper process mirrors it into
  `C:\CivicCastOutput` every ~25s, one disposable child process per tick
  (plus a heartbeat file), additive `robocopy /E` with an explicit retraction
  list rather than `/MIR`. DONE.json is written locally last, excluded from
  the bulk mirror and copied across on its own afterwards, then flushed
  through a bounded final tick — so the harness's oldest contract survives
  the new channel: DONE.json appearing on the host still means everything
  else already arrived (robocopy does not copy in write order, and the host
  tears the VM down within 10s of seeing that file). The two remaining places the driver itself touches
  the share — a one-time inbound seed for host-provided
  `SOAK_MINUTES.txt`/`SKIP_MODE.txt`, and that final flush — go through a new
  bounded `Invoke-BoundedProcess` that kills the child instead of waiting
  forever.
- **Gate A staleness watchdog never armed on the run it was written for.**
  It armed by string-matching the *current* value of
  `summary.json.last_completed_step` against three names while polling every
  30s. Every one of those names is momentary: run6's `runtime-check-*` steps
  occupied `summary.json` for ~1 second and `t5-soak-complete` for ~2, so a
  30s poller missed the whole ~3s window and the staleness bound stayed
  disarmed for the entire run. Arming is now a sticky file the driver writes
  once at the station-up verdict (`_VERDICT-STAGE.marker`) — `Test-Path`
  cannot be raced — with the (widened) step-name predicate kept only as a
  redundant second path. Stall detection now keys on a new monotonic
  `summary.json.step_seq` instead of step-name equality, and the watchdog
  reads and writes the local directory so it can no longer be blocked by the
  surface it exists to bound.
- **Gate A timeout budgets were mutually inconsistent.**
  `In-Sandbox-Report.ps1 -MaxScriptMinutes` 100 → 150 (run6 proved a healthy
  full run needs more headroom), and with it `-TimeoutMinutes` 30 → 170
  (`Host-Launch-Sandbox-Test.ps1`), 120 → 170 (`Run-GateA.ps1`) and 150 → 170
  (the explicit override in `gate-a-station-acceptance.yml`, which is the one
  that actually governs every CI run — fixing only the script defaults would
  have looked correct and changed nothing). The in-sandbox watchdog is now
  always the first bound to fire, rather than the host giving up before the
  watchdog it depends on. `tests/gate_a/test_gate_a_harness_contract.py` is a
  new static contract suite that reads all four literals and fails the build
  if that ordering drifts again, alongside checks that the driver never
  writes to the mapped folder on its own thread, that the staleness watchdog
  arms on the sticky marker, and that the quiet-share filename agrees between
  PowerShell and the Python judge.
- **A broken Gate A evidence channel was reported as a product FAIL.**
  `Host-Launch-Sandbox-Test.ps1` gains a quiet-share detector: no change
  anywhere under `output\` for `-QuietShareMinutes` (default 15) while *its
  own* sandbox VM is alive (by the PIDs the shared-sandbox busy guard already
  records) means the guest-to-host channel is wedged, so it writes
  `HOST-QUIET-SHARE.txt` and exits 4 instead of burning the rest of the
  timeout. Exit 4, not 3: 3 already means "gave up waiting for a busy sandbox
  and never launched", and "never started" is a different condition from
  "started and went dark". `scripts/gate_a_verdict.py` reports such a run as
  `HARNESS_ERROR` (exit 2), never `FAIL` — the second non-verdict alongside
  the existing `BUSY`, and unlike `BUSY` it keeps the full per-check
  breakdown as forensics rather than short-circuiting, since a partially
  shipped run really does carry results. A run whose evidence never reached
  the host supports no conclusion about the candidate.
- **`sandbox-lab/scripts/Watch-Run.ps1` could not be parsed by Windows
  PowerShell 5.1 at all.** A single U+2014 em dash in a double-quoted string
  decodes under 5.1's default ANSI codepage as `â€"`, whose embedded quote
  terminates the string early (5 cascading parse errors). Replaced with
  `--`. Pre-existing since the file was added in `bb00170`; found by the PS
  5.1 AST parse sweep run for the mapped-folder fix above.

- **B2 — a real station could never take a live meeting on air.**
  `civiccast/app.py`'s `_resolve_preflight_evaluator` built the go-on-air
  `PreflightEvaluator` with no `source_probe` at all
  (`PreflightEvaluator(_session_factory)`), so the `live_source` pre-flight
  check fell into `REASON_LIVE_SOURCE_NOT_PROBED` unconditionally and every
  `POST /go-on-air` 409'd — even against a correctly configured RTMP/RTSP/
  SRT/NDI source. The only working `source_probe` in the tree was the
  installer's private System Health rehearsal, which validates a local
  recorded sample file and was never wired into the running service (spec
  §12 station-acceptance: "schedules a day and commits to air; interrupts
  with live and returns safely" — unreachable from the product UI). New
  `civiccast/live/source_probe.py` (`probe_live_source` /
  `build_source_probe`) asks `ffprobe` to open the configured source and
  confirms a real video or audio stream before the station commits to air,
  bounded by `CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS` (default 8s) so
  a hung encoder can't hang the request. `_resolve_preflight_evaluator` now
  wires it in; the installer rehearsal's sample-file probe still overrides
  it per-call via `source_probe_override`, unchanged. A failed probe's
  message now names the source and the concrete failure (e.g. "rtmp source
  'Council Room A RTMP' (room-a-rtmp) ... Connection refused"), which flows
  verbatim into the go-on-air 409's `failed_checks` detail. Credential-
  bearing sources (`LiveSource.credentials_handle`, spec §15's OS
  credential store reference) are not yet resolved by the probe — no
  resolver exists anywhere in this codebase yet; stated as a known
  limitation in the module docstring rather than silently glossed over.
- **Coturn posture (documented external TURN, PR #9) didn't read correctly
  end to end.** `civiccast/installer/contribution_install.py`'s honest
  Windows guidance ("coturn has no native Windows build... point
  `CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT` at a documented external TURN
  server") was correct, but two real gaps kept it from actually reaching an
  operator or doing its job: (1) `civiccast/live/contribution/coprocess.py`'s
  TURN-reachability probe and its unreachable-alert were both gated on a
  LOCAL coturn co-process being `"running"` — which can never happen once
  `CIVICCAST_COTURN_COMMAND` is intentionally left unset, so the probe (and
  the alert) silently never ran under the exact posture PR #9 declared
  supported; `diagnostics()` also always reported the station as unhealthy
  ("one or more co-processes are not running") in that posture, a
  permanent false negative. (2) `ContributionInstallReport`'s
  `coturn_action` guidance text had zero frontend consumer — no screen ever
  fetched `GET /api/staff/installer/remote-contribution`.
  Fixed: the probe now runs whenever a local coturn is up OR none is
  configured at all, `VdoDiagnostics` gained `turn_host`/`turn_port` (the
  effective, currently-configured target) and reports the station healthy
  once TURN is reachable regardless of whether a local process is
  supervised, and a new `POST /api/staff/contribution/diagnostics/turn-test`
  runs an on-demand probe (not the last background poll). The Remote
  Contribution screen's Diagnostics drawer now shows the configured
  TURN target, a **Test TURN connectivity** button (confirm-free since it's
  read-only; loading/success/error states), and a collapsible "How to point
  this station at coturn" section carrying the install report's platform-
  aware guidance verbatim. `docs/USER-MANUAL.md`'s env-var reference for
  `CIVICCAST_TURN_HOST`/`CIVICCAST_TURN_PORT`/`CIVICCAST_COTURN_COMMAND`
  expanded from a one-line stub to the same guidance.
- **GPI / serial control-room device kinds mislabeled as hardware support.**
  `tsr_service/index.mjs`'s `DEVICE_TYPE` map routes `gpi` and `serial`
  `ProductionDevice` kinds through TSR's generic `TCPSEND` adapter — there
  is no GPI contact-closure or RS-232/422 serial hardware driver, and none
  is faked. Labeled honestly everywhere the capability is surfaced:
  `ProductionDevice.kind`'s field description (feeds the OpenAPI schema and
  `docs/API-REFERENCE.md`), the operator console's device-kind picker
  (`ControlRoomSetupScreen`, relabeled "GPI (network relay)" / "Serial
  (network relay)" with an inline note when either is selected, plus the
  `gpi_pulse`/`serial_send` cue-action descriptions), `CAPABILITIES.md`,
  the S18 incumbent-parity spec section's gap-8 status line and detail
  section, and the `civiccast/control_room/`
  package/module docstrings. A station needing real hardware fronts it
  with its own TCP-to-GPI or TCP-to-serial relay box — the existing TCP
  payload path already reaches it. No behavior change (the TCPSEND routing
  was already correct); this closes the honesty gap between what the UI/
  docs implied and what the code does.
- **Two working backend routes had no operator console button.** Both
  `civiccast/captions/router.py`'s offline-caption-job retry
  (`POST /api/staff/captions/offline-jobs/{job_id}/retry`) and
  `civiccast/egress/router.py`'s GStreamer runtime repair
  (`POST /api/staff/egress/repair-gstreamer`) worked end to end but were
  backend-only, flagged in `next-cleanup.md` as waiting on console wiring.
  Added `OfflineCaptionJobsPanel` (`civiccast/apps/portal-operator/src/
  screens/OfflineCaptionJobsPanel.tsx`), mounted as a per-asset drawer
  section in `AssetDetailScreen`, listing offline caption jobs for that
  recording with a `records_clerk`-gated Retry button (confirm, loading,
  success, and per-row error states) on failed jobs. Added
  `GstreamerRepairPanel` to `SystemHealthScreen`'s egress health surface,
  gated on `setup_admin`/`support_admin`, with a confirm dialog and a
  result banner naming the remedy (`already-healthy` /
  `restage-launched` / `installer-missing` / `launch-failed`), the live
  closure-health state, and the re-stage PID when one launched. Both wire
  to the real routes via new `civiccast/apps/portal-operator/src/api/
  client.ts` functions (`listOfflineCaptionJobs`, `retryOfflineCaptionJob`,
  `repairGstreamerRuntime`); vitest coverage in
  `OfflineCaptionJobsPanel.test.tsx` and
  `SystemHealthGstreamerRepair.test.tsx`.
- **PDF agenda import — operator-upload path was a stub.**
  `AgendaService.import_from_doc` (`civiccast/agenda/service.py`) raised
  `NotImplementedError` for any non-`text/plain` upload, so an operator
  uploading a PDF agenda (the common case — municipal agendas ship as PDF,
  not plain text) always hit a 415 with no real parsing behind it. Added a
  heuristic text-layer extractor (`civiccast/agenda/pdf_import.py`, `pypdf`
  — already a repo dependency) that recognizes numbered/lettered items
  (`1.`, `3.a`, `A.`, `IV.`), ALL-CAPS section headings, and standalone
  clock-time markers, and scores each recognized line with a `confidence`
  (new nullable `AgendaItem.confidence` field, migration
  `0078_agenda_item_confidence`). `confidence` is always `None` for
  operator-authored items and exact plain-text imports — only the PDF
  heuristic path produces a score. Because PDF extraction is a guess, not a
  literal transcription, importing PDF items onto an agenda that is
  currently `published` reopens it to `draft` (AI/agenda non-negotiables
  spec §4.2 — operator approval before publish); a PDF with no recognizable
  lines now returns 422 instead of either a 415 or a silently empty import.
  The operator console's agenda screen gained a PDF file-upload control
  alongside the existing paste-text import, a per-item confidence badge in
  the items table, and a published-agenda-will-reopen-to-draft notice.
- **nanoid 3.3.17 → 3.3.18** (GHSA-2v37-7h3g-55p8, high) in both the operator
  console and the public portal.
- **pypdf 6.14.2 → 6.16.1** (PYSEC-2026-3655, PYSEC-2026-3656) — resource
  exhaustion reachable through PDF parsing, which matters because this product
  ingests operator- and contributor-supplied agenda PDFs.
- Non-HTTP control-plane URLs are refused before `urlopen`. The base is
  operator-overridable via `CIVICCAST_CONTROL_PLANE_URL`, so a mis-set value
  could turn a health probe into a local file read whose contents were then
  parsed as a health body.
- Release signing derives its cosign certificate identity from
  `GITHUB_REPOSITORY`. It was hard-coded to the old (private, not archived)
  repository, so verification would have rejected this repository's own
  signatures.
- The GStreamer playout engine's module docstrings no longer claim
  "WSL/Linux-only" — the Windows named-pipe transport ships and its suite runs
  natively.
- **Station timezone now reaches the running service (M3).** First-admin
  setup persisted the operator's chosen `station_timezone` into station-state
  JSON, but nothing propagated it to the running service — S18 daypart
  auto-scheduling silently ran on UTC for every station, corrupting
  scheduling, as-run logs, and program guides for any station not in UTC.
  `civiccast/app.py`'s `_station_tz()` now reads the persisted value (via the
  new `civiccast.installer.station_state.read_station_timezone()`) when
  `CIVICCAST_STATION_TZ` is unset; the env var still works as an explicit
  override.
- **C1 — a fresh station install could never call for help.**
  `civiccast/alerting/evaluator.py`'s dispatch path silently `return`ed with
  no record at all when an `AlertRule` had zero live channels — the exact
  state every migration-`0039`-seeded default rule ships in (an install
  cannot fabricate operator SMTP/SMS/webhook credentials). The alert event
  itself still fired, but the delivery attempt vanished without a trace: no
  suppressed-delivery row, nothing for the deliveries drawer to show, no way
  to tell "nowhere to send it" from "alerting is broken." Fixed to log a
  visible suppressed `AlertEventDelivery` on the no-channel gap (fire and
  resolve paths), per spec §6.2's "never a silent drop" contract.
- **Every fresh native install was dead on arrival — postgres never started
  (Gate A run #4, candidate SHA `8579e66`).** Installer exit 0, activation
  self-test + `station-set.json` written, `CivicCastSupervisor` running as
  LocalSystem — but nothing ever listened on 127.0.0.1:8000 across 20
  minutes / 150 health polls. `supervisor.log` showed a `postgres`
  readiness-budget exhaustion / restart loop; `postgres.log` showed, every
  attempt: `waiting for server to start....The process cannot access the
  file because it is being used by another process. / stopped waiting /
  pg_ctl: could not start server` — no postmaster output ever appeared.
  Root cause: an earlier diagnosability fix (2026-08-12, TESTER2 b5
  evidence) had `postgres_child_spec` pass `pg_ctl start -l
  <child_log_path("postgres")>` while `_file_backed_popen_factory`
  *independently* opened that SAME `postgres.log` path for `pg_ctl`'s own
  inherited stdout/stderr. On Windows, `pg_ctl -l` relaunches through
  `cmd /c "... >> <file> 2>&1"` (`src/bin/pg_ctl/pg_ctl.c`,
  `start_postmaster`); a third process reopening a file the supervisor's own
  process already has open hits `ERROR_SHARING_VIOLATION` deterministically,
  so the postmaster was never spawned — reproduced locally against the real
  `pg_ctl.exe` from the failing Gate A kit (same-file: exit 1, identical
  error text; split-file: exit 0, clean startup). `nats_child_spec` does
  NOT share this defect (`nats-server` opens its own `-l` file directly, no
  `cmd.exe` relaunch) and is unchanged. Fixed via a new
  `ChildSpec.stdio_log_name` field: when `postgres_child_spec` is given a
  `log_path` (its `-l` target), it now points the generic stdio capture at a
  separate `postgres-launcher.log` instead, so nothing ever opens
  `postgres.log` twice. `postgres.log` keeps carrying the durable postmaster
  log at the name operators and tooling already expect.
  `civiccast/native/supervisor/children.py`,
  `civiccast/native/supervisor/service.py`.
- **Gate A could hang indefinitely and gave no diagnosis when the station
  never came up.** A real run (candidate `8579e66`) polled three endpoints
  sequentially at up to 180s each (~9.5 min total), then the in-sandbox
  script hung for 30+ minutes past `t2-render-assert` with no forward
  progress and no `DONE.json` — and the station's own logs (postgres/nats/
  control-plane/supervisor) were never captured, so there was no way to
  tell why the station never listened on `:8000`. `In-Sandbox-Report.ps1`
  now waits on `/api/health` alone with a single bounded 20-minute
  deadline, captures bounded station diagnostics (logs, config, service
  state, listening ports, filtered process list, Event Log) at three
  points including unconditionally at the end, explicitly skips
  T3/T4/T5 the moment the station is confirmed down instead of falling
  through into whatever ran next, and carries a separate-process watchdog
  that force-completes the run after `-MaxScriptMinutes` (default 100) so
  the host can never wait on a zombie. `scripts/gate_a_verdict.py`'s
  `completion` check now gates on a dedicated `harness_completed` flag
  instead of a `last_completed_step` string that could never actually
  match on a real completed run.
- **BUG C2 — the as-run log (the station's legal proof-of-performance
  record) could silently lose entries on a DB hiccup during playout.**
  `civiccast/reporting/asrun_recorder.py`'s `StoreAsRunRecorder` wrote
  every as-run transition straight to the durable `ReportingStore` inside a
  bare `except Exception: log and continue` — a connection drop, a
  disk-full write, or a brief network partition during a source transition
  silently dropped that segment from the franchise-compliance ledger with
  nobody told, the exact failure §12's full-disk scenario and S23's
  "franchise operators must prove what aired" claim exist to prevent. Fixed
  with a durable transactional outbox: every as-run write now journals
  first to a local, fsync'd SQLite file (independent of the app's main DB
  connection) before it ever reaches the real store; an opportunistic drain
  makes the common case behaviorally identical to before, and a store
  failure leaves the row safely journaled instead of dropped, retried every
  `ChannelAutomationService` poll tick until the store recovers. A
  persistent drain failure now raises a visible `asrun-outbox-degraded`
  condition on the existing alert hub instead of only a log line, and
  resolves itself once the backlog clears. Exactly-once via a stable
  per-transition event id plus the store's existing idempotent
  upsert/guarded-update writes; a startup replay drains anything a prior
  crash left mid-drain, so nothing is lost across a crash either. New
  `civiccast/reporting/asrun_outbox.py`; `civiccast/reporting/
  asrun_recorder.py`, `civiccast/egress/automation.py`,
  `civiccast/alerting/models.py` (new `asrun-outbox-degraded`
  `AlertConditionKind`) updated; see `docs/adr/0023-asrun-durable-outbox.md`
  for the full design and rejected alternatives.

### Known gaps

- No per-PR gate on `civiccast/egress/gst/*`. The suite runs natively but needs
  a provisioned runtime tree (`CIVICCAST_GSTREAMER_RUNTIME_ROOT`), which CI does
  not build yet.
- The packager → HLS → real-browser playback path lost its automated gate with
  the Docker cleanroom. The Windows Sandbox harness covers more, on real
  Windows, but is not wired as a CI gate here.
- The Tauri installer still carries an inert WSL2 bootstrap branch in
  `src-tauri/src/main.rs`. It never fires on a native station; removing it is
  tracked separately.

## [1.0.0-rc18] - 2026-08-02

Inherited release identity, recorded here because `civiccast/_version.py` and
this repository's release-identity checks still track it.

`v1.0.0-rc18` is the **WSL line's** published beta. It was built, released and
documented in `scottconverse/civiccast`, not here, and this repository does not
produce it. Its full entry is in that repository's CHANGELOG.

The native product line carries its own separate version in
`civiccast/_native_version.py` — currently `1.0.0-beta.1`, owner-held and
unpublished. Whether a native-only repository should keep tracking the retired
line's identity at all is an open decision for the owner; until it is made,
both are recorded honestly rather than one being quietly retyped as the other.
