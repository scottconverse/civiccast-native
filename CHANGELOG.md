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

- **In-product operator manual (`/help` in the operator console), plus a "Generate station key" button for federation.** Field evidence from a non-technical tester (candidate #17): "In-product manual: THERE IS NONE. /docs, /help, /manual, /guide all 404"; provider setup cards told the operator to "Ask the technical admin" on a one-person station with no technical admin; ActivityPub required typing a raw `civiccast activitypub keygen ...` shell command. The manual is built from the existing `docs/USER-MANUAL.md` (the repo's canonical operator doc), not a parallel document that drifts: `scripts/render_docsite_manual.py` renders it via the same `pandoc` toolchain `scripts/render_user_manual.py` already requires for the PDF/DOCX, sanitizes the HTML through an allowlist parser (`civiccast/docsite/render.py`), and writes the committed artifact `civiccast/docsite/manual.json` plus a hash manifest (`civiccast/docsite/manual.render.json`) — the identical hash-pinning drift-gate pattern the PDF/DOCX pipeline already uses, now also enforced in `ci-docs.yml`. `civiccast/docsite/service.py` + `router.py` serve it read-only, publicly (no staff token — reachable even from the un-authenticated First Setup screen), at `GET /api/public/manual`; the operator console's new `ManualScreen.tsx` renders it as a searchable table-of-contents + content pane at `/help` (aliases `/docs`, `/manual`). Full write-up: `docs/docsite-sync.md`. The manual gained new plain-language content: a Glossary (S3 access key/secret, bucket/object store, CDN, pull-zone, OAuth client ID/secret, webhook secret, egress), a per-provider "Setting Up Providers, Plain Language" section (each provider optional, its own anchor), "Where Recordings And Backups Live", "What Each Publish Surface Means", "The CDN Cost Estimate Is A Guess, Not A Quote", and "Don't Have A GitHub Account?". Every provider readiness card (`ProviderReadinessItem.manual_section`, `civiccast/installer/service.py`) and several setup panels now carry a "Read more in the manual" link straight into the matching section. Federation: `POST /api/staff/activitypub/keygen` (`civiccast/activitypub/router.py`) generates the same RSA station key `civiccast activitypub keygen` does, server-side, behind a real button in `ActivityPubScreen.tsx` — replacing the raw CLI instruction — plus a plain-language paragraph on what federation is and that most stations don't need it. Applying the generated settings and restarting CivicCast is still a separate manual step (`load_activitypub_config` reads strictly from process environment, matching the existing beta-handoff "ask a technical administrator to restart" pattern in `civiccast/installer/handoff.py`); the CLI-typing barrier for a non-technical operator is gone regardless.

- **Assets/Library upload control, watch-folder Scan now + folder picker, and
  caption-trigger discoverability — field evidence from a non-technical
  tester (candidate #17), findings 1-6.** A tester walkthrough found the
  Assets ("Library") screen had no upload button or file input at all (only
  the six-card First Setup rehearsal picker had one, unlabeled as an
  upload); watch folders required typing an exact filesystem path with no
  "Browse..." picker and no way to force an immediate check (a fresh
  config's "Last poll: never" read as broken even when the daemon HAD
  ingested within about a minute); and nothing told an operator that
  approving publish is what starts offline caption transcription, nor that
  a running job was actually running.
  - **Assets screen upload** (`AssetUploadControl`,
    `civiccast/apps/portal-operator/src/components/assets/`): reuses the
    exact `/api/staff/assets/upload` endpoint the First Setup card already
    calls (never a second pipeline) via a new XHR-based client function,
    `uploadAssetFileWithProgress`, added alongside (not replacing) the
    existing `fetch`-based `uploadAssetFile`. Every state designed: idle
    (collapsed behind one "Upload video" button), choosing, client-side
    unsupported-type rejection naming the accepted formats before any
    network call, uploading with a real percent progress bar + a
    screen-reader `aria-live` announcement + cancel, success (asset
    appears in the table via query invalidation), and failure surfacing
    the server's plain-language reason with a "Try again" retry. Gated on
    the SAME roles the backend requires (`records_clerk`,
    `meeting_operator`, `support_admin`) — never hidden for a role that
    lacks it, only disabled with the reason stated, matching this app's
    existing "Package for playback" pattern.
  - **Watch folders** (`civiccast/schedule/media_lifecycle_router.py` +
    `MediaLifecycleSettingsScreen.tsx`): new
    `POST .../watch-folder-configs/{id}/scan-now` runs the SAME per-folder
    scan the poll daemon's own pass uses
    (`WatchFolderWorker.scan_now`, bypassing the due-check), returning what
    it found so a "Scan now" button gives real, immediate feedback instead
    of waiting out `poll_interval_seconds`. A fresh, never-polled config's
    status now reads "Not scanned yet — the next automatic check runs
    within Ns, or use Scan now" instead of a bare "Last poll: never" /
    "Last ingest: never." New `GET .../browse-folders` lists local
    directories (drive roots on Windows / `/` on POSIX when no path is
    given) for a non-technical operator to navigate instead of typing a
    path from memory — the browser cannot hand back an absolute path
    itself (the File System Access API and `<input webkitdirectory>` both
    withhold it for security), but this app's frontend and backend always
    run on the same station machine, so the backend lists directories for
    a new `FolderBrowser` modal picker instead. `monitor_path` is now
    validated server-side on create/update: a missing or unreadable
    directory 422s with a plain-language reason instead of being accepted
    and only discovered broken on the next poll.
  - **Caption-trigger discoverability** (`OfflineCaptionJobsPanel.tsx`,
    `PublishDashboardScreen.tsx`): the offline-captions panel now states
    plainly, up front, that approving a recording's portal surface on the
    Publish dashboard is what starts transcription — there is no separate
    "generate captions" control anywhere in the console, by design. The
    Publish dashboard itself now carries the same note next to "Approve and
    Publish selected" so an operator learns this before clicking, not only
    after, on the asset detail page. A running job now reads
    "Transcribing… (Xm)" with elapsed time instead of a bare "Pending"
    label indistinguishable from stalled, and sets a real-world time
    expectation (measured ~37s for 11s of audio on a 32 GB CPU-only
    reference machine — several minutes for a full meeting recording, not
    seconds). The caption engine itself is unchanged; this is copy and
    affordance only, per the tester's own note that captions already work
    end-to-end. (The AI Models screen's separately-tracked inaccurate
    "≈500 ms typical" latency claim was not touched — different screen,
    different owner.)
  - **Readiness dot vs. publish status** (`AssetsScreen.tsx`,
    `ReadinessBadge.tsx`): a tester found a packaged-and-published asset
    still showing "⚪ Not ready" and read it as broken. Investigation:
    `readiness_state` is computed purely from ingest-time transcode/proxy
    pipeline status (`civiccast/schedule/media_lifecycle_worker.py`) and
    was never meant to track publish state — `published_at`/`manifest_url`
    are a separate, already-visible column. Rather than silently
    redefining readiness semantics, the dashboard's existing (previously
    unrendered) `readiness_reason` is now shown as a tooltip +
    screen-reader text on every badge, and a published-but-not-`ready`
    asset gets an explicit note: "Already live on the portal — this dot
    tracks the optimized playback proxy, not publish status."
  - Accessibility (WCAG 2.2 AA): every new control is keyboard-operable
    with a labeled input, and upload/scan/caption progress is announced via
    `role="status" aria-live="polite"`, not conveyed by a spinner alone.
  - Tests: 3 new backend pytest classes (path validation, scan-now,
    browse-folders) in `tests/schedule/test_media_lifecycle_router.py`; new
    `AssetUploadControl.test.tsx` and `FolderBrowser.test.tsx`
    (vitest); extended `AssetsScreen.test.tsx`,
    `MediaLifecycleSettingsScreen.test.tsx`,
    `OfflineCaptionJobsPanel.test.tsx`, `PublishDashboardScreen.test.tsx`;
    new Playwright specs `e2e/assets-upload.spec.ts` and
    `e2e/media-lifecycle-watch-folders.spec.ts`, plus caption-discoverability
    coverage added to `e2e/asset-detail.spec.ts` (each with its own axe-core
    WCAG scan).
- **S7 watch-folder poll daemon (the piece PR #19 explicitly deferred).**
  PR #19 built `WatchFolderConfig`'s data model, CRUD API, and settings UI
  but shipped no daemon — nothing polled `monitor_path`, detected files, or
  called into ingest, so spec §6 DONE criterion 9 ("watch-folder hands-off;
  operator sees ingests") was unmet despite `ROADMAP.status.yaml` already
  carrying `status: built` for the section. `civiccast/schedule/
  watch_folder_worker.py`'s `WatchFolderWorker` (migration
  `0080_watch_folder_daemon`, chained after `0079_media_lifecycle`) is that
  daemon, same env-gated inline/off + poll-seconds shape as the sibling S7
  workers: polls each enabled config's `monitor_path` (local disk, USB, or
  NAS/SMB) on its own `poll_interval_seconds` (new column, spec default 5s
  — distinct from the pre-existing `settle_window_seconds`, the D13
  write-completion stability window); detects new/changed files via a
  durable per-file ledger (`watch_folder_file_state`, new table) requiring
  size+mtime unchanged across two consecutive polls before ingest (partial-
  copy safety); ingests through the SAME upload pipeline an operator's
  manual upload uses (`PostgresAssetStore.ingest_upload`) — never a
  parallel pipeline — recording provenance via `MediaIngestJob(source_kind=
  "watch_folder", source_path=<original path>)`; verifies post-copy size
  match (catches a truncated SMB copy); applies the operator's chosen
  processed-file disposition, `leave_with_ledger` (default) or
  `move_to_subfolder` (new `processed_file_mode`/`processed_subfolder_name`
  columns) — **neither mode ever deletes the source file**
  (delete-safety posture, see below); surfaces an unreachable path as a
  visible per-config degraded state (new `health_status`/`degraded_reason`/
  `degraded_since`/`last_poll_at`/`last_ingest_at` columns) rather than
  failing silently; and re-ingests a changed already-ingested file against
  the SAME asset via `MediaLifecycleStore.apply_replace_source` (now
  accepting a `source_kind` parameter so watch-folder-originated
  reprocesses are provenance-tagged correctly) instead of creating a
  duplicate asset. Concurrency: per-folder work is fully serialized; up to
  `max_concurrent_folders` (default 4) different folders may be scanned at
  once; `max_files_ingested_per_pass_per_folder` (default 25) bounds one
  pass's per-file work. Processed-file disposition, degraded-state
  visibility, and the delete-safety posture were open decisions the spec
  text itself didn't resolve — recorded in
  `docs/adr/0024-watch-folder-daemon-processed-file-and-degraded-state.md`.
  Registered as `civiccast-watch-folder-worker` in the app lifespan's
  `ThreadSupervisor` list (same RAT-001 maintenance-mode fail-closed
  posture as every other background worker). Settings screen: a new status
  column per watch folder (health, last poll, last ingest, and — when
  degraded — the reason, `role="alert"`). Tests: 10 tmp-dir-based
  end-to-end worker tests (real filesystem, real ffmpeg-generated video
  content through the real ffprobe pipeline where ffmpeg is on PATH) +
  5 app-wiring tests + 6 settings-screen vitest tests. Known gaps, called
  out in the spec file's own build note and ADR 0024 rather than silently
  claimed: no 24h unattended soak, no real-NAS/SMB field test, and the
  spec's "asynchronous retry/backoff" + "CRC" wording for SMB resilience
  is approximated (poll-interval-paced retry rather than sub-second
  backoff within a pass; size verification rather than a full source-side
  content hash, which would double read I/O over the network per file).
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

- **An `hls` egress sink was accepted by the config API with `200 OK` and crashed the channel the moment an operator started it — the product could not serve a live stream to residents at all.** Found live by an agent driving the real installed station with a real staff token: configuring an `hls` sink and issuing `start` threw `unknown sink kind: hls` inside `civiccast/egress/daemon.py`'s `_start`, logged only as `"Channel automation pass failed for government"` in `control_plane.log`. `EgressSinkKind` (`civiccast.egress.models`) has advertised `hls` since migration `0066_hls_sink_kind`, the config API validated and saved it fine, but `civiccast.egress.gst.bridge.sink_element_spec()` — the GStreamer engine's (the default engine's) config → element-graph mapper — had no `hls` branch and fell through to a bare `ValueError`, which none of `_start`'s `except` clauses (`ConfigInvalidError`/`SecretUnresolvedError`/`FfmpegNotFoundError`/`EgressError`) catch, so it propagated all the way out uncaught. Investigated rather than assumed: the shipped runtime does NOT carry an `hlssink`/`hlssink2`/`hlssink3`/`splitmuxsink` element at all (verified with `gst-inspect-1.0` against the real installed closure at `C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer\lib\gstreamer-1.0` — no `gsthls*.dll`, no `gstmultifile.dll` ships); the only HLS-shaped element present, gst-libav's `avmux_hls`, wrote **zero output files** in a live pipeline test (`avmux_hls ! filesink`, fed real video+audio, run to a clean `EOS`) — a known limitation of gst-libav's single-src-pad muxer wrapper, which cannot drive FFmpeg's own multi-file segment I/O. So a fix that just named a GStreamer element in `sink_element_spec()` would have looked done and still served nothing. Fix: new `civiccast.egress.hls_relay.HlsRelaySupervisor` (mirrors `TsRelaySupervisor`'s shape, wired into `EgressDaemon`/`PlayoutSupervisor` the same single way) supervises a real ffmpeg child that reads the GStreamer engine's ordinary MPEG-TS `udpsink` output over a loopback port and re-muxes it with FFmpeg's proven `-f hls` muxer via the EXISTING `civiccast.egress.sinks.HlsSink` — the same muxer, flags, and sliding-window (2s segments, 12s/6-segment window) the ffmpeg-concat engine already used, and `civiccast.stream.media_router`'s `/media/live/{channel_id}/...` route already served from unchanged (that router's docstring had described this exact `HlsSink`-writes/`media_router`-serves contract since before this fix — only the GStreamer engine's half was missing). `sink_element_spec()` also gets a genuine `hls` branch now (a `udpsink` at a port pure-function-derived from the sink's own configured directory, `hls_relay_uri_for`), so a bare call never raises even outside the relay's config rewrite. Proven end-to-end against the REAL installed runtime, not just unit tests: a live GStreamer pipeline (`videotestsrc`/`audiotestsrc` → `openh264enc`/`avenc_aac` → `mpegtsmux` → `udpsink`, the exact shape the daemon builds) piped into a real ffmpeg relay child running the exact args `HlsRelaySupervisor` constructs produced a real, rotating (`seg000000000-1.ts` at t≈3s → `seg000000002-8.ts` at t≈17s, old segments pruned) `playlist.m3u8` + `seg*.ts` on disk, independently confirmed playable by `ffprobe` (real H.264 640×360@30fps video + AAC audio streams). Also closed the same accept-then-crash SHAPE generally: `PUT /api/staff/egress/channels/{id}/config` now refuses a sink kind the ACTIVE engine cannot run with `422` and a message naming the supported kinds (engine-aware — `rtmp` remains genuinely unimplemented on the GStreamer engine, Stage 1 ships TS sinks only, but is still accepted when `CIVICCAST_EGRESS_ENGINE=ffmpeg-concat` is selected, since that engine's `RtmpSink` already works), instead of a config that later explodes deep inside a `start` pass. A failed channel-automation pass — or one command inside it — used to be visible ONLY as that one log line; it now raises through the existing alerting hub (`record_alert_condition`, new condition kind `channel-automation-failure`) with fire/dedupe/auto-clear semantics, and clears again once the channel completes a clean pass. Found and fixed a sibling bug in the same file while there: `_raise_egress_degraded_alert` (the existing GStreamer-degraded-to-FFmpeg operator alert) called `session_factory()` as if it returned a raw `Session` (`.commit()`/`.close()`), but production's `session_factory` (`civiccast.app._wire_stage_f_workers`'s `_session_factory`) is actually a `@contextmanager` callable — every real call has therefore always raised `AttributeError`, silently swallowed by the surrounding `except Exception`, meaning that alert has never once actually been recorded in production; fixed alongside (`with session_factory() as session:`), with a regression test — the PRE-EXISTING test for it used a fake session factory that shared the identical wrong assumption, so it never caught this. Also investigated the third live-reported symptom: after a channel's first couple of `start` commands processed, later commands (a `takeover`, then a `stop`) sat unprocessed for minutes with zero log activity. Root cause, confirmed by reading the code rather than inferred: `EgressStore.pop_pending_commands` marks the ENTIRE currently-pending batch for a channel consumed in one durable update BEFORE any of it runs, and `EgressDaemon.process_once`'s bare `for` loop meant one command raising (the `hls` crash above, or — worse — that SAME crash re-triggering on every later `takeover`/`reload` attempt for as long as the broken sink stayed configured, since those routes call back into `_start`) aborted the loop mid-batch, and every command queued alongside or after the crashing one in that batch was already marked consumed in the database — durably lost, never retried, with no trace of what happened to it. Fixed: `process_once` now isolates each command's processing (one failure can no longer take the rest of its batch down with it) and reports each failure through the same alert path above via a new `command_failure_hook`. Not fixed, and said plainly rather than papered over: the one command that actually crashes is still consumed at-most-once by design — the operator must reissue it, this change stops OTHER queued commands from being silently swept away with it. Also ruled out, not fixed: `process_once`'s `_poll_process`/`_service_backoff_relaunch` calls run BEFORE `pop_pending_commands`, so if either of those ever raised it would stall a channel's command draining without losing already-queued commands — a different and less severe failure shape; nothing in the live repro's evidence implicates that path, so it was not touched. New coverage: `tests/egress/test_hls_relay.py` (the relay supervisor's lifecycle/idempotency/config-rewrite/degraded-ffmpeg-absent behavior), additions to `tests/egress/test_gst_bridge.py` (the `hls` branch, the fallthrough error naming supported kinds), additions to `tests/egress/test_router.py` (config-time `422` rejection, engine-aware), `tests/egress/test_daemon_command_isolation.py` (the actual DEFECT D regression proof — a batch containing a raising command must still run every command after it), `tests/egress/test_automation_failure_alert.py` and additions to `tests/egress/test_automation_alert_hook.py` (the alert fire/clear contract, the wiring, and the `_raise_egress_degraded_alert` regression).
- **Provider setup, CDN cost, publish-surface, and day-one-alert copy read as if a technical admin was required and something was broken, when neither was true (field evidence, candidate #17).** Five distinct issues, one tester report: (1) Every provider card's setup steps said "Ask the technical admin to enter the keys" — on a one-person station the volunteer IS the admin. Rewrote `civiccast/installer/service.py`'s `build_provider_readiness_report()` and `_provider_item()` in first person ("Paste your own keys in yourself"), added a `manual_section` anchor per card, and reworded the not-set-up message from "is optional and not set up yet" to "is optional. Skip it for now if the station doesn't need it yet." The podcast card's undefined "Publish a local portal recording first" now explains what that means inline. (2) The Storage-and-viewing-estimate panel multiplied bandwidth by a hardcoded, unsourced `$0.005/GB` and printed it as a specific "$20.00 rough CDN estimate" — an invented number with no source. Per the owner's exact instruction, `CostForecastPanel` (`SetupScreen.tsx`) now shows "Varies by provider — Cloudflare R2 is free" and names Cloudflare R2's real, published, current $0-egress price as the one number it's willing to cite; GB storage/bandwidth math (a real function of the operator's own inputs) is unchanged. (3) The Publish Dashboard's optional "Cable file package" surface showed a red "failed: Cable file package was not created" even when it was simply never configured — indistinguishable from a real failure. `civiccast/cable/package.py` gained `CablePackageNotConfiguredError`, a subclass raised specifically for the "never turned on" case; `civiccast/publish/service.py` now maps it to the already-defined-but-unused `PublishSurfaceStateValue` of `"not_configured"` (message: "Cable file package is not set up (optional).") instead of `"failed"` — the dashboard's existing dot-color logic and `status-language.ts`'s existing `not_configured` → "Not set up yet" mapping already render this correctly with no further frontend change; a surface that WAS configured and genuinely failed (missing source file, missing caption sidecar) still reads "Failed". (4) `StationProfileScreen.tsx`'s Storage roots showed the Windows service account's raw profile path (`C:\Windows\System32\config\systemprofile\...`) with no explanation of why it isn't browsable and no way to act on it. Added a `CopyPathButton` per field, explanatory copy pointing at **Assets** as the supported way to find a recording without filesystem access, and a manual link; `civiccast/installer/service.py`'s `_backup_destination_path()` now rejects a WSL-style path (`...\mnt\c\...` or `/mnt/c/...`, matching the tester's observed `C:\mnt\c\CivicCastBackups`) with an actionable Windows-path error instead of silently accepting a location that would make "backup verified" a lie. (5) The System Health self-test panel and the Alerts screen both said "failed"/"Found a problem" in red, directly contradicting `civiccast/alerting/self_test.py`'s own deliberately-soft "did not pass" summary wording (comment tag `F-RC3-5`) shown one line below — a brand-new station's `readiness`/`backup_probe` checks are legitimately, correctly unmet on day one, not broken. `SELF_TEST_STATUS_LABEL`, the per-check pill label, and `alerts-format.ts`'s `CONDITION_LABEL['self-test-fail']` now match the backend's wording ("Did not pass yet" / "not yet" / "Automatic self-check did not pass"), and the self-test panel shows a one-line "finish Setup and Backup destination" hint specifically when those two checks are what's unmet.

- **"Report a beta issue" (operator console sidebar, First Setup's support link, resident portal) linked straight to a GitHub bug-report template, with no path for someone without a GitHub account (field evidence, candidate #17).** All three now route through the manual's new "Don't Have A GitHub Account?" section (`/help#report-without-github`) first, which explains the support-bundle-plus-forward path and, as a last resort, the maintainer email already published in `SECURITY.md` — GitHub is still offered, just no longer the only door. The identical link in `civiccast/apps/installer` (the Tauri setup wizard) was deliberately left untouched here to stay out of that surface's own active lane; same fix, same pattern, still needed there.
- **`POST /api/public/contribute/uploads` returned the internal absolute server filesystem path as `upload_ref` to an anonymous public caller** (confirmed in code and independently reported by a field tester: `"COSMETIC/PRIVACY -- path leak. The public upload response returns the internal absolute path C:\Windows\System32\config\systemprofile\...\contributor-uploads\council-speech.mp4 to the resident."`). Beyond revealing the service account's profile layout, tracing what `upload_ref` was actually used for turned up a more serious consequence of the same defect: the stored filename was the contributor's own sanitized name plus a numeric collision counter (`council-speech.mp4`, `council-speech-2.mp4`) -- guessable for anything with a predictable name (this is a civic broadcast platform; meeting recordings have exactly that) -- and `sha256` is optional in the public submission payload, so a second anonymous caller who guessed or otherwise learned another contributor's `upload_ref` could attach that stranger's pending upload to their own submission with no proof of anything. Fix: `_unique_upload_path` (`civiccast/contribute/router.py`) now names the on-disk file with a `uuid4` hex token instead of the contributor's filename, and `upload_contributor_media`'s response returns only that opaque token (`destination.name`, no directory component) as `upload_ref` -- the contributor's real filename is still returned separately in `SubmissionMediaReference.filename` for display. A new `civiccast.contribute.store.resolve_contributor_upload_path` is the single place that ever turns the opaque token back into a real path, joined onto `default_contributor_upload_dir()` -- no second storage/lookup mechanism, the contributor upload directory the store already owns IS the store. `Path.__truediv__` leaves an anchored (absolute) right-hand operand unchanged, so a submission recorded before this fix -- when `upload_ref` was still a full absolute path -- resolves to the exact same file it always did with no data migration. `_verified_media_reference`'s existing containment check (`resolved.relative_to(upload_dir)`) is unchanged and still runs on every submission, so a forged or path-traversal-style ref is rejected exactly as before. Also closed the same class of leak in three public-router error paths that echoed a raw `OSError`/`ContributorStoreError` string (which can carry a filesystem path) straight into an anonymous caller's response `detail` -- the upload directory mkdir/write failure and the submission/store dependency's persistence failure now log the real exception server-side and return a generic, safe detail. Two-step public flow (`POST /uploads` then `POST /submissions`) verified end to end with the real opaque ref (`tests/contribute/test_router.py::test_public_upload_then_submit_round_trip_succeeds_with_the_opaque_ref`); the portal's public submit form needed no change -- it already treats the whole media object as an opaque pass-through between the two calls.

- **Cable Commissioning Screen 8 reported "GStreamer runtime not detected" and DeckLink "FAIL" on a clean station whose bundled runtime was fully installed (candidate #17), bricking the whole commissioning wizard.** Confirmed live by the tester: `C:\Program Files\CivicCast (Native)\runtime\dependencies\gstreamer\bin\gst-inspect-1.0.exe` was present with its DLLs and plugins, but Screen 8's probe (`civiccast.platform.station_box_profile.probe_engine_readiness`, via `_default_gst_inspect_runner`/`_default_device_monitor_runner`) only ever did `shutil.which("gst-inspect-1.0")` — a bare PATH lookup. The control-plane service runs as LocalSystem with the stock, installer-untouched PATH (`civiccast.native.supervisor.install_layout`'s own docstring), which never carries the bundled runtime's `bin` directory, so the probe reported "not detected" against a fully installed runtime. The SAME PATH lookup also produces a FALSE PASS on a developer's own machine that happens to have a separate, user-installed GStreamer on PATH — reproduced live on Halo, where `shutil.which("gst-inspect-1.0")` resolved to `C:\Users\scott\AppData\Local\Programs\gstreamer\1.0\msvc_x86_64\bin\gst-inspect-1.0.exe`, NOT the product's own shipped runtime; a passing probe there was silently checking the wrong install. With GStreamer AND DeckLink both `FAIL`, Screen 8 offered no "Continue anyway" (only warnings get that), so Screens 9-11 (channel output setup, output proof, report) were completely unreachable — no channel could ever be configured through the wizard, and the "cable file package" publish artifact stayed permanently red because commissioning could never complete. This is NOT the same root cause as Phase 2's dead live engine, despite an initial field report linking the two: `civiccast.egress.gst.engine` (the real playout worker) already bootstraps the bundled runtime independently at import time via `civiccast.native.gstreamer_runtime.bootstrap_installed_gstreamer_runtime()` — the exact absolute-path/PATH-prepend mechanism this fix gives the commissioning probe — so egress never depended on the buggy PATH-only probe this PR fixes. The live-owning agent independently root-caused the dead live engine to a separate, concrete defect (no RTMP listener ships anywhere in the product), unrelated to this commissioning-detection bug. Two things stay worth a follow-up look in this area, reported rather than fixed here since `civiccast/egress/` is out of this change's lane: (1) `civiccast/egress/gst/engine.py`'s `bootstrap_installed_gstreamer_runtime()` call discards its `bool` return value — a bundled-runtime bootstrap failure (e.g. the child process never received `CIVICCAST_GSTREAMER_RUNTIME_ROOT`) is currently silent, falling through to an unguarded `import gi` that would import whatever GStreamer happens to be ambiently resolvable rather than the verified bundled one, or fail with a bare `ImportError` carrying no diagnostic about why the bootstrap didn't run; (2) an operator-facing repair action already exists (`POST /api/staff/repair-gstreamer` → `civiccast.native.gstreamer_repair.trigger_gstreamer_repair`, wired to `GstreamerRepairPanel` on the System Health screen) but Screen 8's `gstreamer_engine`/`decklink_sdi` checks only describe it in `next_step` text — a future pass could offer it as a one-click action on Screen 8 itself, the same way System Health already does. Fix, all in `civiccast.platform.station_box_profile`: new `_resolve_bundled_gst_tool` resolves `gst-inspect-1.0.exe`/`gst-device-monitor-1.0.exe` by ABSOLUTE path against the installed layout (`civiccast.native.supervisor.install_layout.resolve_install_root` → `<install_root>/runtime/dependencies/gstreamer/bin/...`, reusing `civiccast.native.gstreamer_runtime.installed_gstreamer_environment` for `PATH`/`GST_PLUGIN_PATH`/`GI_TYPELIB_PATH` — the SAME resolution the real playout engine already uses via `station_runtime.load_native_station_environment`, so Screen 8 now agrees with engine selection instead of running a different, PATH-only test), never a bare PATH lookup, and only falls back to PATH when no bundled closure resolves (dev/CI/system installs). Proven end-to-end on Halo by monkeypatching `resolve_install_root` at the real bundled tree: the probe correctly resolves `GStreamer 1.28.5` from the bundled path with `decklinkvideosink`/`mpegtsmux` found, and separately still reports `system-path` (not `bundled`) when only the dev GStreamer on PATH is reachable. New `EngineReadiness.runtime_source` (`"bundled" | "system-path" | "unavailable"`) makes this honest on the wire — Screen 8's `gstreamer_engine` detail now names WHICH install a passing (or failing) probe actually found, and the "not detected" `next_step` now points at the installer's repair action instead of telling the operator to install something already shipped. Also fixed: DeckLink/BMD SDK absence on a `peg-cable` station now reports `warning` ("Not installed (optional — only required for a channel that outputs via SDI)") instead of a hard `fail` — `validate_channel_commissioning_setup` already treats an SDI device as a per-channel opt-in, not a station-wide requirement, so a streaming-only/IP-only station with no capture card was being hard-blocked from a wizard step it never needed; TSDuck's existing "Not installed" warning is now explicitly labeled "(optional)" too. `civiccast.cli._doctor_check_captions` (`civiccast doctor`) gets the same bundled-first resolution so it agrees with Screen 8 instead of independently reporting "not on PATH" under the same LocalSystem service context. Not touched: the real GStreamer engine-selection/egress path (`civiccast.egress.engine_select`, `civiccast.native.station_runtime._resolve_gstreamer_egress_environment`) was already correct — it resolves the bundled closure by absolute path and was never PATH-dependent, so this was purely a commissioning-detection bug, not an engine-startup bug; the missing-live-engine symptom traces to the wizard being unable to complete, not to the engine itself failing to start. New coverage: `tests/platform/test_station_box_profile.py`'s `TestBundledGstResolution`/`TestDefaultRunnerResolutionOrder` (bundled-vs-PATH resolution order, partial-closure fail-closed, a tool absent from the closure, and the exact field-evidence "service-like environment, no bundle, nothing on PATH" case failing closed honestly) and `tests/installer/test_commissioning.py`'s new decklink/tsduck-optional and `runtime_source`-reporting tests. Regenerated `docs/openapi.json`/`api.generated.ts`/`docs/API-REFERENCE.md` for the new `runtime_source` field.

- **Operator console infinite setup loop after a successful install (candidate #16, 4eca729): clicking "Open operator console" opened First Setup's own "not set up yet" dead end, whose advice was to click the exact button just clicked.** Reproduced twice in one day on two different machines, station healthy both times (health/portal/operator all 200, postinstall SUCCESS). Root cause: the installer-handoff setup nonce lived in an ACL-hardened `HKLM\SOFTWARE\CivicCast\Native\SetupNonce` registry key (SYSTEM + Administrators only), but the Tauri setup wizard that builds the button's URL and writes `installer-state.json` ships `asInvoker` (non-elevated) by design — its own registry read always failed, and `write_installer_state`'s `preserved_operator_console_url()` bailed out before ever reaching the "no cache, but we have a live nonce" branch even on the rare occasions a nonce WAS available — so the very first `operator_console_url` a fresh install ever wrote was the bare, nonce-less constant, and every later write only preserved that same nonce-less value. OWNER DECISION: rather than patch the handoff (four separate field failures on this mechanism in two days — nonce unreadable across the elevated-installer/normal-user split, the W-2 recovery code file never written, "Get a new code" silently no-op'ing, the elevated `--civiccast-restore-setup-handoff` CLI printing nothing), retire it entirely. The control plane binds `127.0.0.1` only (verified live via `netstat`: `TCP 127.0.0.1:8000 LISTENING`, nothing on `0.0.0.0`), so `/api/setup/*` is already unreachable from the network by construction — the nonce was guarding a door inside a room the network cannot enter. First setup is now admitted by loopback peer address alone (`civiccast.installer.router._require_local_setup_request`, decided from the ASGI transport's own `request.client.host`, never a spoofable header); a configured station still refuses a second first-admin attempt with `409` (`civiccast.installer.station_state.complete_first_admin_setup`, unchanged). Removed: `civiccast.native.setup_nonce`, the `civiccast runtime setup-handoff` CLI, the `--civiccast-restore-setup-handoff` elevated-recovery flow, the W-2 in-product "I lost my setup link" / "Get a new code" recovery-code UI and its backend (`civiccast.installer.handoff_recovery`), and every nonce-URL function in the Rust installer (`resolved_operator_console_url`, `preserved_operator_console_url`, `native_setup_nonce_from_registry`, and siblings). The "Open operator console" button now always opens the plain, fixed console URL, and a caller reached from off the station gets an honest refusal ("First setup can only be done from the station computer itself") instead of circular button-click advice.

- **GUI acquisition screen showed "Local AI model" stuck on "Waiting" for
  15+ minutes on a real board-demo machine (candidate #16, 4eca729) even
  though station activation had already installed it and PR #56's
  `merged_ollama_model_store_root` fix was present and structurally
  correct.** Root-caused by re-deriving both sides of PR #56's path match
  from the actual code (`native_activation::compose_ollama_model_store`
  writes to `<install_root>\models\ollama\...`;
  `acquisition_catalog::merged_ollama_model_store_root(roots.staged)`
  resolves to the SAME path, since `roots.staged` is
  `acquisition_installer_directory()` = `current_exe().parent()`, and
  `--civiccast-activate-station --install-root "$INSTDIR"` passes that
  same directory as `install_root` -- so the original 9d4477b path miss is
  confirmed fixed, not the cause here) — this is a DIFFERENT defect. The
  real cause: `main.rs`'s `run_acquisition_components` is a strictly
  sequential, single-threaded driver over a FIXED list
  (`acquisition_catalog::PRODUCTION_CATALOG_IDS`: `app_runtime,
  server_binaries, captions_medium, captions_large, cuda_runtime,
  local_ai_model`) with no hardware- or selection-based gating at all
  (`start_acquisition` takes no arguments; `captions_large` and
  `cuda_runtime` are both `required: false` on the frontend but always run
  on the backend). On a station with poor or no internet, whichever
  optional entry ahead of `local_ai_model` was not staged offline could sit
  downloading for hours (`component_acquisition.rs`'s per-request timeout
  is `6 * 60 * 60` seconds) before the driver ever reached
  `local_ai_model` — even though that component's own offline-first check
  would have resolved in milliseconds. Fix: a `prescan_locally_satisfied_components`
  pass now runs every catalog component's existing no-network local-check
  (factored out as `component_acquisition::locally_verified_pinned_path`
  and `main.rs`'s `locally_verified_pack_path`, reused — never duplicated
  — by the real sequential driver) up front, before the sequential loop
  starts, and persists `found_locally` immediately for anything already
  satisfied — decoupling an already-installed component's GUI state from
  an unrelated, still-transferring one. No hash or signature check was
  weakened; the sequential loop still performs its own full run over every
  component afterward. Two new tests: `acquisition_catalog.rs`'s
  `local_ai_model_merged_store_candidate_names_a_file_compose_ollama_model_store_actually_writes`
  runs the REAL `compose_ollama_model_store` writer against a synthetic
  staged tree and asserts the catalog's own merged-store candidate names a
  file it actually wrote (mutation-tested: fails when the two path
  functions are made to disagree); `main.rs`'s
  `locally_satisfied_progress_rows_finds_a_satisfied_component_behind_an_unsatisfied_one`
  proves an already-satisfied component is recognized regardless of an
  earlier, unsatisfied component's state.

- **A station activated on the mandatory floor caption tier crash-looped
  forever after the operator acquired the OPTIONAL large-v3 tier through the
  post-install acquisition wizard, and the supervisor's own log never said
  why (field evidence, candidate 4eca729, 2026-08-29).** GUI install
  completed clean (health checks 200, `install-progress.log` SUCCESS); the
  coordinator then left the post-install acquisition wizard open and it
  genuinely downloaded the optional `captions-large-v3` component into
  `%PROGRAMDATA%\CivicCast\components\captions-large-v3`. From that point on,
  `CivicCastSupervisor` crash-restarted every ~33s ("terminated unexpectedly.
  It has done this 371 time(s)"); the Windows Event Log carried the real
  reason, `NativeStationConfigurationError: Native station activation
  self-test receipt does not match this distribution`, but `supervisor.log`
  held only the unconditional "supervisor logging initialized" line and
  nothing else. Root cause, traced end to end:
  `station_runtime._resolve_caption_tier` searches BOTH the install root and
  the non-elevated acquisition root for a staged caption tier and always
  prefers the HIGHEST one found (by design — large-v3 is the better engine);
  once the wizard staged large-v3 in the acquisition root, the runtime
  correctly resolved `tier_id="large-v3"` on the station's next start, but
  `activation-self-test.json` is written EXACTLY ONCE, by the elevated
  `d4-activate-station` NSIS step, and describes whichever tier was staged at
  THAT moment — almost always the floor tier alone, since large-v3 is an
  OPTIONAL component the non-elevated GUI can acquire later into a
  completely different root the elevated installer never touches (chain H1).
  `_validate_activation_receipt` was therefore, correctly, refusing a
  floor-tier receipt against a large-v3 identity every single time — the
  check itself was never wrong; nothing in the codebase ever produced a
  receipt for the tier the operator had just legitimately added. (No
  component was ever wiped or overwritten: `%PROGRAMDATA%\CivicCast\
  components` has never held anything besides `captions-large-v3` by
  design — nothing else is ever written there.) Fixed on both sides of the
  contract, without weakening the check: (1) `main.rs` gained
  `finalize_captions_large_acquisition`, run once the wizard's per-file
  pinned-hash verification for `captions_large` completes — it re-verifies
  the mandatory floor tier's own staged jfk.wav self-test fixture against
  its pinned identity, runs a REAL faster-whisper inference against the
  just-downloaded large-v3 model with the station's own embedded
  interpreter (the same live proof the elevated install path already gives
  the mandatory tiers), and on success writes a large-v3-only addendum
  receipt into the acquisition root (never touching `station-set.json` or
  the primary `activation-self-test.json` at the install root, so every
  already-activated component stays exactly as it was); an idempotency
  fast-path skips the ~300s inference re-run when a matching receipt is
  already on disk. (2) `station_runtime.load_native_station_environment`
  now reads the activation receipt from the SAME root the resolved tier's
  own model was actually found in (reusing the existing `_tier_base_root`
  two-root search that already resolves the model itself), instead of
  unconditionally reading it from the install root — a floor-only station is
  completely unaffected (its receipt root is always the install root, exactly
  as before). Separately, `service_host.SvcDoRun` now logs the real exception
  type and detail to `supervisor.log` via the new
  `civiccast.native.supervisor.start_failure_marker` BEFORE re-raising
  (behavior is otherwise unchanged: still fails loud, still exits, still lets
  the SCM's own restart policy decide what happens next), and once the SAME
  condition has recurred 3 times in a row it writes an operator-readable
  `STATION-START-FAILED.md` marker alongside `install-progress.log`, cleared
  automatically the moment a start actually succeeds again — so a crash loop
  is never silent even to an operator who never checks the Windows Event Log.
  11 new tests: 2 in `test_station_runtime.py` (the fail-closed floor with no
  addendum receipt present anywhere, and the regression proof once one is),
  7 in the new `test_start_failure_marker.py` (pure counter/marker decision
  logic), 2 in `test_supervisor_service_win.py` (the real `SvcDoRun`-driven
  crash-loop-then-marker sequence, and marker/counter clearing on a clean
  start); plus 5 new Rust tests driving the real addendum receipt writer
  directly (byte-for-byte identity match against the runtime's own pinned
  expectations, and proof that writing it never touches the primary receipt
  or any other already-activated component).

- **Setup-handoff recovery: an unhandled write failure after the challenge
  directory was already hardened could crash the request instead of ever
  reaching the "no 200 without a real file" contract, and "Get a new code"
  gave no visible feedback at all (field session 2026-08-28, candidate
  9d4477b).** On the First Setup page's "restore setup handoff" panel,
  clicking "Get a new code" produced no visible change on screen, and a
  separate live report on the same station found the countdown-carrying
  `/api/setup/handoff-recovery/start` success response with no
  `code.txt` on disk to back it up. Reading
  `civiccast.installer.handoff_recovery.start_recovery` end to end and
  reproducing it locally against a REAL (non-mocked) `win32security` ACL
  call found the actual defect: `start_recovery` hardens the challenge
  directory to SYSTEM+Administrators-only, THEN writes `code.txt`/
  `state.json` into it — so a caller whose token does not carry the
  `SY`/`BA` SIDs it just granted the directory (the *default* Windows
  token state for an administrator account running de-elevated; UAC only
  attaches the Administrators group to a genuinely elevated process) gets
  a bare `PermissionError` writing the code file it just locked itself out
  of. That exception was never caught anywhere — not in
  `handoff_recovery.py` (only `HandoffRecoveryError` was), not in
  `civiccast.installer.router`'s `public_handoff_recovery_start` — so it
  reached the HTTP layer as an unhandled 500 with no cleanup, rather than
  the module's own fail-loud `HandoffRecoveryError`/503 contract. No code
  path in this codebase can turn a real write/ACL failure into a
  fabricated 200 (every return from `start_recovery` already required the
  writes to have succeeded), so the field station's specific "live
  countdown, missing file" combination could not be conclusively
  reproduced from source alone; it is consistent with this exact
  uncaught-exception class landing on a run where the privilege assumption
  did not hold, or with the on-machine check running under different
  privileges than the control-plane process (a non-elevated `Test-Path`
  against a SYSTEM+Administrators-only directory throws Access Denied,
  which is a well-known false-negative case for that cmdlet) — reported as
  an open question rather than settled, per this repo's own
  claims-of-absence discipline. Fixed regardless: the whole
  mkdir/ACL/write sequence in `start_recovery` is now one fail-loud unit —
  ANY exception (mkdir, ACL, either write, or a new read-back-what-was-
  just-written verification) removes any file that attempt created and
  raises `HandoffRecoveryError`, so a caller of this function gets EITHER
  a fully written, fully hardened challenge, or a clean exception and no
  trace of a half-issued one; there is no partial-success return. Frontend
  fix in the same pass: `SetupScreen.tsx`'s `HandoffRecoveryPanel` now
  shows a visible pending label on both "I lost my setup link" and "Get a
  new code" while the request is in flight, an explicit
  `role="status"` confirmation on success naming the write time and, for a
  regenerate specifically, that the old code no longer works, and disables
  the stale code input while a new one is being issued — matching the
  page's existing "never a dead control" standard (see the W-2 doc
  comment above `HandoffRecoveryPanel`). Also flagged, not fixed here (out
  of scope — `civiccast/apps/installer/` is owned by a concurrent
  session): `--civiccast-restore-setup-handoff`'s recovery pass already
  prints an explicit result on every branch, but the installer binary
  compiles as a Windows GUI-subsystem executable in release builds
  (`#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]`),
  so none of that output is visible when run from an existing terminal —
  a separate, precisely diagnosed follow-up. 3 new tests in
  `tests/installer/test_handoff_recovery.py` (a write failure after
  successful hardening raises `HandoffRecoveryError` and leaves no partial
  state; a failed read-back of the just-written code also fails loud), 3
  new tests in `src/screens/SetupScreenNoNonce.test.tsx` (pending label on
  first issue, pending label + reset countdown + explicit regenerate
  confirmation on "Get a new code", visible error on a failed regenerate).
- **GUI installer re-downloaded the 7GB local AI model even after offline-kit
  activation already installed it; "Open installer log" was a no-op; no
  shortcut existed anywhere back to the running station; and the setup CLI's
  handoff-recovery flag printed nothing from a terminal (four related field
  findings, 2026-08-28, candidate 9d4477b, USB-kit GUI installer run).**
  1. **Local AI model re-download.** Station activation's
     `compose_ollama_model_store` (`native_activation.rs`) merges every
     required model component's signed pack into
     `<install_root>\models\ollama\{blobs,manifests}\registry.ollama.ai\
     library\<repo>\<tag>`, but the GUI download screen's `local_ai_model`
     catalog entries (`acquisition_catalog.rs`) only ever checked
     `<install_root>\packs\local-ai-model\models\...` — a path nothing in
     this codebase writes. `ensure_component_available` therefore always
     fell through to a live ~7GB pull from `registry.ollama.ai`, even though
     `install-progress.log` showed every pack `copied_from_offline` and
     postinstall `SUCCESS`. `local_ai_model_items` now carries a SECOND
     `staged_at` candidate at the merged station-activation store
     (`merged_ollama_model_store_root`, additive — `CatalogItem.staged_at`
     was already a `Vec<PathBuf>` checked in order, no schema change) for
     the manifest item and every blob item (config + all layers), mirroring
     the exact relative layout `native_packs::validate_ollama_model_contract`
     already encodes. `captions-floor` had the equivalent fix from day one
     (`FLOOR_STAGED_ROOT`'s special-case); `local_ai_model` never got the
     matching candidate until now. 3 new Rust tests in
     `acquisition_catalog.rs`: every item's candidate-path shape, a
     regression pinning the exact `models\ollama` path the field miss
     needed, and `ensure_component_available` accepting a hash-matching file
     staged only at the new path without a download.
  2. **"Open installer log" did nothing when clicked.** Two stacked bugs:
     `newest_installer_log_path` (`main.rs`) only ever looked for
     `runtime-host.log` under the per-user state root — written by the
     native service, which has not started yet on the download screen — and
     never for `install-progress.log` (the NSIS elevated installer's own
     transcript, written under `%PROGRAMDATA%\CivicCast` and already
     complete by the time that screen exists); and the command hardcoded
     `notepad.exe` instead of the OS default handler
     (`cmd.exe /C start ""`, the same idiom `open_operator_console` already
     uses for URLs). Frontend compounded it: `AcquisitionFlow.tsx`'s onClick
     awaited `openInstallerLog()` with no `try`/`catch`, so a rejected
     command surfaced nowhere but the devtools console — the button visibly
     did nothing. Fixed all three: `newest_installer_log_path` now checks
     both logs and returns whichever exists and was modified most recently;
     the command opens the OS default handler; the button now surfaces a
     failure through the same `role="alert"` region "Stop downloading"
     already uses. 5 new Rust tests (pure path resolution +
     real-temp-file selection logic) and 3 new frontend tests (success,
     visible failure, error clearing on a later success).
  3. **No shortcut anywhere led back to the running station.** Once the
     setup wizard's window closed, an operator had no clickable path to the
     operator console or public portal — the setup app's own finish screen
     offers "Open operator console", but that control disappears with the
     window, and this installer created no Start Menu or Desktop entry
     pointing at either surface (only Tauri's own shortcut to the setup
     wizard itself, which just re-runs first-run setup). `NSIS_HOOK_
     POSTINSTALL` now writes a `CivicCast (Native)` Start Menu folder with
     two Internet Shortcut (`.url`, no icon-resource plumbing needed) files
     — "CivicCast Operator Console" and "CivicCast Public Portal" — plus a
     Desktop "CivicCast Operator Console" shortcut, at literal URLs matching
     `main.rs`'s own `OPERATOR_CONSOLE_URL`/`RESIDENT_PORTAL_URL` constants
     (installer-state's URL isn't resolvable yet at POSTINSTALL time — the
     GUI's own first run hasn't happened). Best-effort and silent-safe: a
     write failure logs a breadcrumb but never aborts or alerts. `NSIS_HOOK_
     POSTUNINSTALL` removes all three, unconditionally — deliberately
     outside the `$R2` service-stop-confirmed gate that guards the
     `$INSTDIR` runtime/packs tree removal, since a shortcut carries none of
     that gate's still-running-process hazard. 3 new policy tests in
     `tests/policy/test_native_installer_identity.py` (creation shape +
     placement + no dialogs, a `main.rs`-constant drift guard, and
     unconditional removal), plus one pre-existing breadcrumb-tail pin
     updated to the new true tail.
  4. **`--civiccast-restore-setup-handoff` ran and printed nothing from a
     terminal.** The top-of-file `#![cfg_attr(not(debug_assertions),
     windows_subsystem = "windows")]` makes a release build GUI-subsystem,
     so the process starts with no console at all -- `run_setup_handoff_
     recovery_pass`'s exit-0/85/86/87 messages (the whole point of this CLI
     recovery flag) had nowhere to go. `run_native_restore_setup_handoff_cli`
     now calls a new `attach_or_alloc_console_for_cli_recovery` (Windows-
     only) BEFORE that function's first print: `AttachConsole
     (ATTACH_PARENT_PROCESS)` connects to the invoking terminal when one
     exists, falling back to `AllocConsole()` when it does not. Rust
     resolves stdio handles via `GetStdHandle` fresh on every write, so
     calling this before the first print -- and nowhere else in the binary
     -- is what fixes it without touching the ordinary GUI launch (which
     still never shows a console, unchanged). 1 new text-contract test
     (`attach_console_call_precedes_the_recovery_pass_in_source_order`,
     mirroring `native_service_registration.rs`'s existing self-source-read
     convention) pins the call ordering itself, since the bug is invisible
     to a normal unit test (`windows_subsystem` is unset in debug/test
     builds, so the consoleless condition never reproduces there) and every
     real code path through this function ends in `std::process::exit`.
  Full verification: `cargo test` (399 passed) + `cargo clippy` in the
  installer crate, `npm run typecheck` + `vitest run` (145 passed) in the
  installer frontend, and the repository's `pytest tests/policy` suite
  (1828 passed) all green.

- **D4 provisioning survives a reserved/excluded Windows TCP port instead of
  crashing PostgreSQL's bind (two real LPM deployment failures, 2026-08-27,
  candidate 75cc13f).** Both independent installer runs failed identically
  at `d4-provision` (installer exit 116, engine rc 75):
  `pg_ctl start` could not bind `127.0.0.1:5432` — `WSAEACCES` ("Permission
  denied"), `could not create any TCP/IP sockets` — because the port sat
  inside a Windows-administered excluded TCP port range (a Hyper-V/WSL
  `winnat` dynamic reservation, which moves across reboots). PR #51's
  `PROVISION-RECOVERY.md` correctly named the pg_ctl diagnostic but nothing
  survived it — any program asking for that exact port would have failed
  identically. New `civiccast.native.provision.port_select` module: before
  `pg_ctl start` ever runs, the CLI test-binds the intended
  `127.0.0.1:<port>` itself; on a bind refusal it reads
  `netsh int ipv4 show excludedportrange protocol=tcp`'s excluded-range
  table and falls forward through a small documented candidate list (5432,
  5433, 5434, 5435, 5544 — 5432 always tried first), skipping any candidate
  already inside an excluded range and real-bind-testing every other one.
  The first bindable candidate becomes `context.postgres_port` — the single
  field every downstream write already derives the port from (rendered
  `postgresql.conf`, the `pg_ctl start`/`stop` argv, and (via
  `resolve_database_url`) the `DatabaseUrl` handed back to the Rust caller
  and written to `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl`, this
  station's single source of truth for the port). If every candidate is
  excluded or refuses to bind, provisioning halts fail-closed (never a
  silent guess) and `PROVISION-RECOVERY.md` now names the exact cause —
  every port tried, the Windows-excluded ranges quoted verbatim, and the
  copy-paste fix commands (`net stop winnat` / `net start winnat`, `netsh
  int ipv4 show excludedportrange protocol=tcp`) — instead of a bare pg_ctl
  crash. Consumer-side gap closed in the same pass:
  `civiccast.native.supervisor.service`'s `default_dependency_provider`
  never parsed the postgres host/port out of `DATABASE_URL` at all (unlike
  `civiccast.native.upgrade.pg_lifecycle.derive_pg_lifecycle_paths`, which
  already did this correctly for the D3 upgrade engine) — the SUPERVISED
  postgres child's own launch argv silently used `Supervisor`'s
  `"127.0.0.1"`/`5432` defaults regardless of what D4 actually provisioned,
  so a station whose port fell back off 5432 would have started its
  running service pinned to the wrong port forever, even though the
  provisioning-time fix above had already worked. `build_production_service`
  gained `db_host`/`db_port` parameters (default `"127.0.0.1"`/`5432`,
  backward compatible), `ProductionDependencies` gained matching fields, and
  `default_dependency_provider` now parses `DATABASE_URL` the same way D3
  does before threading the result through. 27 new tests: 20 in
  `tests/native/test_provision_port_select.py` (excluded-range parsing
  against realistic `netsh` output, the pure fallback-selection decision
  logic with an injected bind seam, real local TCP bind-test coverage
  against genuinely free/held ports, and a regression pinned to the exact
  LPM failure signature), 2 in `tests/native/test_provision_cli.py` (the
  honest no-port-available recovery document, and the fallback port
  actually flowing into the provisioned context), and 5 in
  `tests/native/test_supervisor_service.py` (the `db_host`/`db_port`
  wiring through `build_production_service`, `default_dependency_provider`'s
  `DATABASE_URL` parsing and its unparsable-URL fallback, and the factory's
  pass-through of both fields).

- **Runtime-dependency acquisition survives upstream release pruning
  (mirror-first fetch + reviewed fallback URLs).** Candidate build run
  33094460301 failed with a 404 in `scripts/build_native_ffmpeg_pack.py`'s
  `--acquire` because BtbN/FFmpeg-Builds pruned the pinned autobuild release
  tag (BtbN keeps only recent daily tags plus one per calendar month). PR
  #52 repinned to the next surviving build, but that pin is equally
  prunable — a lock edit can never be the durable fix. `scripts/
  provision_native_runtime_dependencies.py`'s `fetch_locked_artifact` (the
  shared acquisition primitive behind the ffmpeg, server, ollama, and cuda
  pack builders) now: (1) consults a persistent, hash-addressed archive
  mirror (`CIVICCAST_RUNTIME_ARTIFACT_MIRROR` env var or `mirror=` param,
  layout `<mirror>/<sha256>/<filename>`) before touching the network,
  ignoring-then-repairing any entry that fails verification; (2) writes
  every verified download back through to the mirror, so the pinned bytes
  outlive the upstream tag; and (3) accepts an optional, reviewed
  `fallback_urls` list in the lock (same HTTPS-host allowlist, tried in
  order after the primary URL fails, with an all-sources failure report).
  The committed lock's size+SHA-256 pin stays the sole admission authority
  on every path — mirror hits and fallback downloads are verified exactly
  like a fresh primary download. Wiring:
  `.github/workflows/native-beta-candidate-artifacts.yml` restores the
  FFmpeg archive via `actions/cache` (keyed on the runtime lock file) on
  the hosted lane, and points the self-hosted lane at the box-local
  persistent mirror `C:\CivicCastTester\runtime-artifact-mirror` (outside
  the runner work/temp trees, same box-local precedent as `kit-staging`) —
  seeded with the currently pinned FFmpeg archive, hash-verified, at review
  time. 14 new tests in
  `tests/native/test_runtime_dependency_provisioner.py` cover the
  mirror-hit-with-zero-network path, env-var configuration, corrupt-entry
  repair, write-through admission, mirror-write-failure tolerance,
  primary-404-to-fallback ordering, all-sources-fail reporting, and the
  `fallback_urls` schema boundary.

- **S7 media lifecycle worker — GPL encoder literal removed from the default
  transcode seed list, resource posture made conservative.** A regression
  audit of `civiccast/schedule/media_lifecycle_worker.py` found its default
  transcode format catalog seeded, for every validated asset by default, an
  `h265_1080p_8mbps` target whose ffmpeg args carried a bare `libx265`
  (GPL) literal — never resolved through any encoder-selection seam, unlike
  H.264's `resolve_h264_encoder()`. This repo's no-GPL posture (ADR 0007's
  compliance section) forbids exactly this. `tests/policy/test_ffmpeg_h264_encoder.py`'s
  repo-wide sweep missed it because it only ever checked for the literal
  string `"libx264"`, not because of directory scope (it already walked the
  whole `civiccast/` tree) — widened to a `_FORBIDDEN_GPL_ENCODER_LITERALS`
  set (`{"libx264", "libx265"}`) and proved with a planted-literal test
  (`test_detector_flags_a_planted_libx265_literal`) shaped exactly like the
  real defect. Independently, the same worker dispatched every seeded
  format synchronously in its own thread at normal process priority under
  ffmpeg's flat 6-hour default timeout — a large amount of unsupervised,
  full-priority ffmpeg work sharing the box with operator requests, with no
  station-level off switch (the same class of "unfiltered ladder wastes
  time on rungs the source can't fill" problem PR #45 found and fixed in
  the VOD packager, here for background proxy generation instead of a
  synchronous HTTP path). Resolved S7 spec Open decision #1 ("Transcode
  format defaults... h265_1080p_8mbps (archive)... h264-only for
  simplicity?") as the named h264-only alternative:
  `DEFAULT_TRANSCODE_FORMATS` is now a single resolution-aware
  `h264_720p_5mbps` rendition that never upscales past the source's own
  probed `height_px` (mirrors PR #45's never-upscale posture, implemented
  locally); `h264_mezzanine` stays available opt-in via
  `CIVICCAST_TRANSCODE_FORMATS`, not seeded by default; a new
  `MediaLifecycleWorkerSettings.transcode_seeding_enabled` switch (default
  `True`, so first-run ingest still produces a proxy) lets a station turn
  ingest-time transcoding off entirely; `transcode_concurrency` is an
  explicit, validated field fixed at `1`, matching what the dispatch loop
  already does, rather than an unstated implementation detail; and
  `civiccast.stream._ffmpeg.run_ffmpeg` gained an opt-in `lower_priority`
  parameter (Windows `BELOW_NORMAL_PRIORITY_CLASS`, default `False` so
  live egress and the VOD packager's synchronous request path are
  unaffected) that the worker's dispatched jobs now use together with a
  per-minute-of-source timeout budget (10 min floor, 10x-realtime, 2h
  ceiling) replacing the flat 6h default. See ADR 0007's "S7 ingest-time
  transcode defaults and resource posture" amendment for the full
  rationale. Files: `civiccast/schedule/media_lifecycle_models.py`,
  `civiccast/schedule/media_lifecycle_worker.py`,
  `civiccast/stream/_ffmpeg.py`, `tests/policy/test_ffmpeg_h264_encoder.py`,
  `tests/schedule/test_media_lifecycle_worker.py`, `tests/stream/test_ffmpeg.py`,
  `docs/adr/0007-hls-packager-design.md`,
  `docs/spec/3.0/sections/S7-media-lifecycle-and-readiness.md`. No
  operator settings UI exists yet for `transcode_seeding_enabled` or any
  other worker setting — named as real follow-up, not claimed done here.
- **Asset packaging no longer upscales — the Gate A `/package` timeout.** Gate
  A's clerk loop uploaded the real 640x360 sample clip (201 Created), called
  `POST /api/staff/assets/{asset_id}/package`, and got no response at all
  within its 30 s client budget; the station's own uvicorn access log
  (`station-diag/final/logs/control_plane.log`) has **no line for the package
  request** while it does log every later request, so the handler was still
  running — not deadlocked, not blocking the event loop, just slow. No file on
  the packaging path changed in the regression window: `git log f31618f..main`
  touches neither `civiccast/stream/packager.py` nor `_ffmpeg.py`, and
  `civiccast/schedule/router.py` is byte-identical. What was actually wrong is
  older than the window and easy to miss — `pack_vod_asset` encoded all four
  ABR rungs for every source regardless of the source's resolution, so a
  640x360 clip was **upscaled to 1920x1080 and 1280x720**: pixels invented,
  4.5 Mbps spent carrying no extra detail, and the full encode cost of a large
  frame paid twice. Measured on that clip on a fast development box: 18.4 s for
  the content ladder, of which the two upscaled rungs are 14.6 s (~81%);
  end-to-end the endpoint took **~19 s steady-state and 23 s on the first call
  in a process**, against a 30 s client timeout, on hardware considerably
  faster than the 16 GB sandbox VM. The margin was always thin; it took no
  code change to cross it. New `civiccast.stream.config.select_ladder` picks
  the rungs before encoding — never taller than the source, top rung pinned to
  the source's own resolution, the ladder's top rung still a product cap so a
  4K source publishes at 1080p and below, and the **full ladder unchanged
  whenever the source dimensions cannot be read** (the packager never guesses
  its way into a smaller ladder). `pack_vod_asset` gained
  `source_width`/`source_height`, and probes the input itself when a caller
  does not supply them, so all three call sites — the staff package endpoint,
  first-run sample seeding, and the live finalization worker — get the fix
  without needing to know about it. Same clip after the change: **3.4 s of
  content-ladder encode, an 81% reduction**, and the same booted-app
  upload-then-package measurement that read 22.8 / 19.1 / 18.8 s now reads
  **4.6 / 4.1 / 3.9 s** — from ~63% of the 30 s budget down to ~14%, so the
  sandbox VM has room to be several times slower and still answer. The
  emitted manifest is `360p` (640x360, the source's own resolution) + `240p`
  + slate, with no upscaled variant. A 1080p or larger source is unaffected
  in either time or output, which is correct: nothing upscales there. ADR
  0007 carries the amendment.
  **Not fixed, stated plainly:** packaging is still a synchronous HTTP request
  whose latency is proportional to source duration. A 90-minute 1080p meeting
  still occupies the request — and the operator console's fetch — for as long
  as the encode takes. Moving it to a job-and-poll contract like the offline
  caption jobs changes the endpoint's response contract and every caller of
  it, so it needs its own ADR and an owner decision.

- **Gate A — the stalls were `ConvertTo-Json` walking a cycle in
  `Get-Content`'s note properties.** Root cause for five runs (4, 6, 7 and both
  candidate-#11 runs), found by the liveness instrument on its very first
  outing: `driver_process_alive=true driver_cpu_seconds=449.5
  driver_working_set_mb=8318.2` — alive, CPU-hot, 8.3 GB resident in a 16 GB
  VM, so not blocked I/O at all. `Get-Content` emits `PSObject`-wrapped
  strings carrying `PSPath`/`PSParentPath`/`PSChildName`/`PSDrive`/`PSProvider`/
  `ReadCount`; `PSProvider` is a `ProviderInfo` whose `.Drives` collection
  holds `PSDriveInfo` objects that each point back at it — a cycle.
  `ConvertTo-Json` serializes note properties, so `-Depth N` walks that cycle
  `N` deep. Measured here, **one** such line: 1,889 chars at depth 3;
  3,852,872 at depth 6; **98,197,802 at depth 7 (11.2 s)**; at depth 8 it never
  finished (killed at 180 s having reached 4 GB and 178 s of CPU). The driver
  serialized **eighty** of them at depth 8 via `install_progress_log_tail`.
  The same 80 lines as plain strings at depth 8: 5,314 chars in 30 ms. This
  also explains why the stall always looked positional — the assignment was
  always followed immediately by a `Save-Summary`, so relocating the capture in
  the previous change moved the explosion earlier in the run rather than
  removing it. (Run 3's `t2-render-assert` stall is *not* explained by this and
  is not claimed to be.) Fixed with two independent defences plus a source-site
  cast: `ConvertTo-PlainForSummary` rebuilds the summary from plain types
  before serialization — recursing only into arrays and dictionaries, capping
  its own depth, and rendering anything else via `ToString()` rather than
  walking its graph (a cyclic `ProviderInfo` now serializes to 59 characters) —
  and the serialization depth drops from 8 to 6, which is one more than the
  deepest real member needs. While fixing it, a second PS 5.1 trap: the
  sanitizer's first form used `System.Collections.Generic.List[object]` with
  `return @($out)`, which throws *"Argument types do not match"* in Windows
  PowerShell 5.1 and silently degraded **every array member of the summary**
  into one space-joined string; it uses `ArrayList` and
  `return , ($out.ToArray())` now, the leading comma also keeping
  single-element arrays as arrays for the judge's counted fields. Finally, when
  the watchdog fires and the driver is still alive it now also records a CPU
  delta with a verdict (verified against a real spinning process at
  `driver_busy_percent=100.8` and a real sleeping one at `0`) and, guarded by a
  working-set cap and a 120 s timeout, a MiniDump written to `$env:TEMP` —
  never to the shipped evidence directory, since a full dump of the process
  this was written for would be 8.3 GB.
- **Gate A — the remaining synchronous `C:\CivicCastHostStore` reads are now
  bounded, and the "hung or dead?" question is finally instrumented.** The
  candidate-#11 run (`831f3df`) is the first Gate A run whose install
  succeeded end to end (`installer_exit_code: 0`, `d4-activate-station:
  returned 0` — the run-7 station-bundle failure is resolved, and
  `d4-activate-station` went 35m09 ✗ → 31m13 ✓ with the shipper quiesced,
  though against a *different* kit so that is not a controlled comparison).
  It then stalled, and for the first time the per-statement instrumentation
  named the step: `stuck_step=install-progress-copied-post-install`,
  `seq:7`, 509s. That **excludes** the expected culprit rather than
  confirming it — the hoststore reads (install-dir discovery, `station-set.json`,
  ARP, service checks) are all separately recorded steps further down and
  none appeared; what remains is two in-memory assignments and a ~2 KB local
  JSON write, against a 178-line log whose longest line is 138 characters.
  Since four runs have now ended with a signature identical whether the
  driver's thread *blocked* or its process *died*, the driver records its PID
  (`_DRIVER-PID.txt`) and both watchdog triggers now call `Get-DriverLiveness`
  as they fire, writing `driver_process_alive=true|false` (plus CPU seconds
  and working set) into `STALL-TIMEOUT.txt` / `WATCHDOG-TIMEOUT.txt` and the
  placeholder `DONE.json`. Independently, the three remaining synchronous
  readers of the mapped install target — `Test-KnownPaths`, the install-tree
  listing, and `Invoke-StationDiagCapture`'s marker copies — now run through a
  new `Invoke-BoundedProbe` (a throwaway `powershell.exe` with an arguments
  file, a result file and a hard timeout), because "targeted and
  non-recursive" was never the same as "bounded". The quiesce window also
  stops being lifted when the installer returns; it now runs to the station-up
  wait, so the 25-second tick no longer resumes underneath 10,683 files of
  post-install hoststore reads. Moving the install target to a local directory
  was considered and rejected: this file already records that staging locally
  hits "os error 112 (not enough space)" on the ~40 GB virtual disk and that
  activation "REFUSES junction/symlink install-roots", and `Run-GateA.ps1`'s
  fresh-install guarantee plus `gate_a_verdict.py`'s install/activation checks
  both read that tree host-side. Also: `_SHIPPER-QUIESCE.marker` joins the
  shipper's retraction list — the additive mirror was leaving a stale copy on
  the host that told readers the run was still quiesced when it was not.
- **Self-hosted native-beta candidate build — the same persisted-cache bug
  as #41, one script over: `civiccast-ffmpeg-pack-cache`.** Candidate run
  32858543561 (main=7bf705a) got further than ever before — the PostgreSQL
  cache fix (#41) held, K1 succeeded — then failed at `build_native_ffmpeg_pack:
  FFmpeg closure seed bin/ffmpeg.exe is missing:
  ...\civiccast-ffmpeg-pack-cache\extracted\ffmpeg\bin\ffmpeg.exe`. Same
  root cause as #41 in a different cache: `acquire_ffmpeg_pack_sources()`'s
  bare `destination.exists()` check trusted a self-hosted `--cache`'s
  persisted, interrupted-mid-extraction `extracted/ffmpeg` tree instead of
  re-extracting it. Fixed the identical way: `_extracted_ffmpeg_is_complete()`
  re-verifies a pre-existing extraction against the same pinned bin/license
  file set `build_ffmpeg_pack()` itself requires (reusing the existing
  `_ffmpeg_sources()` validator) before trusting it; an incomplete tree is
  cleared and re-extracted.

  Per the pattern of each run peeling one more layer of the same job, did a
  static sweep of every remaining script `build-native-beta`'s pack-build
  step calls for the same bug classes (idempotent-cache trust, hosted-only
  assumptions, live-network fetches, tool availability, hash pins the
  self-hosted toolchain can't reproduce) rather than waiting for the next
  run to surface the next layer. Exhaustively grepped every script for both
  the "trust because it exists" and "refuse because it's non-empty"
  shapes: `build_native_ollama_pack.py`'s acquire is already immune (always
  extracts fresh into a temp dir, validates, then atomically replaces the
  destination — never trusts stale state); `build_native_cuda_pack.py`'s
  acquire already re-verifies a cached file's hash before ever reusing it,
  deleting and re-downloading on mismatch; `build_native_bootstrap.py`
  unconditionally runs `npm ci` (npm's own clean-install operation, not a
  cache-trust check) and locates NSIS via Tauri's own tool-provisioning
  cache; every remaining `X.exists() and any(X.iterdir())` refusal
  (`civiccast-app-payload`, `civiccast-app-payload-scratch`/`pyav-build`,
  `civiccast-gstreamer-closure`, `build/wp1-native-toolchain`) is either
  already pre-cleared by the self-hosted-only step #31 added, or lives
  inside the repo checkout, always fresh via `actions/checkout`, so it can
  never trigger from self-hosted persistence. No further code changes
  found necessary in this sweep.

  `tests/native/test_build_native_ffmpeg_pack.py`: +4 tests (complete
  extraction reused; incomplete extraction — missing `ffmpeg.exe`, the
  exact observed shape — cleared and re-extracted; no-cache-yet path
  unaffected; direct unit coverage of the completeness check).
- **Self-hosted native-beta candidate build — a persisted, interrupted
  PostgreSQL cache extraction, plus a live MSYS2 keyserver dependency.**
  Candidate run 32845198987 failed identically in BOTH attempts (a
  keyring-related retry did not change the outcome) at "Build and verify
  signed component packs": `pinned PostgreSQL initdb.exe is missing:
  ...\civiccast-server-pack-cache\extracted\postgres\bin\initdb.exe`.
  Root cause: `acquire_server_pack_sources()`'s bare `destination.exists()`
  check trusted a self-hosted `--cache`'s persisted `extracted/postgres`
  tree — left incomplete by an earlier interrupted run — without
  re-verifying it, the same idempotent-scratch bug class as
  `civiccast-build-venv`/`civiccast-msvc-build-tools` (#31), applied here
  to a different cache. Fixed by re-checking a pre-existing extraction
  against the same pinned bin/lib/share file set `build_server_pack()`
  itself requires (`_extracted_tree_is_complete`, reusing the existing
  `_postgres_sources`/`_tsduck_sources` validators — no duplicated
  validation logic) before trusting it; an incomplete tree is cleared and
  re-extracted from the already hash-verified archive.

  Separately investigated per the task: attempt 1's MSYS2 pacman-key
  keyserver refresh errors (`==> ERROR: Could not update key: <id>`, ~18
  minutes wasted, non-fatal that run since MSYS2's own hook tolerates the
  failure). `build_minimal_ffmpeg()` now pre-populates the pacman keyring
  itself, offline, via a non-login `bash -c` invocation (`pacman-key
  --init` + `--populate msys2`, both sourced from the pinned, hash-
  verified MSYS2 base archive already on disk — never a keyserver) before
  the first login-shell `pacman -U`; MSYS2's own `07-pacman-key.post` hook
  then sees its trust directory already populated and skips the network
  `--refresh-keys` step entirely, with no patch to MSYS2's own shipped
  script. This code has no self-hosted/hosted branch, so the fix applies
  to both lanes — hosted merely had better keyserver luck, not immunity.
  Verified locally, outside any runner tree
  (`C:\CivicCastTester\msys2-keyring-test`, deleted after), against the
  real pinned MSYS2 base: pre-populating completes in ~7s wholly offline
  (vs. the observed ~18 minutes), and a subsequent real `pacman -U`
  against the pinned `nasm` package still passes genuine PGP signature
  verification and installs successfully.

  `tests/native/test_build_native_server_pack.py`: +4 tests (a complete
  pre-existing extraction is reused; an incomplete one — missing
  `initdb.exe`, the exact observed shape — is cleared and re-extracted;
  the no-cache-yet path is unaffected; direct unit coverage of the
  completeness check for both artifact kinds).
- **Self-hosted native-beta candidate build — "Sign the native bootstrap
  (Azure Artifact Signing)" needs the .NET SDK, not just the runtime.**
  Candidate run 32838619949 got one step from a complete build, then died:
  `Exception: Failed to install package: sign 0.9.1-beta.26227.3`.
  `azure/artifact-signing-action` installs its `sign` CLI (net8.0-targeted,
  per nuget.org/packages/sign, needing the .NET 8 SDK or later) via `dotnet
  tool install`. A hosted `windows-latest` runner ships the SDK
  preinstalled; this box had `dotnet` on PATH but RUNTIME-only (`dotnet
  --list-sdks` empty, only `Microsoft.NETCore.App 8.0.30`), so the tool
  install failed with "No .NET SDKs were found." A new self-hosted-only
  step, "Provision a pinned .NET SDK for the signing action," installs a
  pinned 8.0.424 SDK (LTS, 8.0.4xx band) via Microsoft's own
  `dotnet-install.ps1` — a non-admin, caller-owned install into this
  lane's own `RUNNER_TEMP` scratch root, pinned by exact `-Version` (never
  `latest`/`LTS`) — then exports `DOTNET_ROOT` and prepends the SDK
  directory to `GITHUB_PATH` so the signing step resolves it. Idempotent
  the same way every other self-hosted scratch dir in this job is: a
  pre-existing tree is trusted only when `dotnet --list-sdks` actually
  reports the pinned version (not a marker file alone), and an invalid one
  is cleared and reinstalled. Verified locally, outside any runner tree
  (`C:\CivicCastTester\dotnet-sdk-test`, deleted after): the exact command
  the signing action runs internally, `dotnet tool install sign --version
  0.9.1-beta.26227.3`, succeeds against this pinned SDK. Hosted lane
  untouched (the step is self-hosted-only). `tests/policy/
  test_native_beta_candidate_workflow.py`: +2 tests (the provisioning
  step's shape/ordering/pin, and a regression guard that a floating
  `latest`/`LTS` version would fail the pin).
- **PyAV reproducibility gate — the reviewed wheel hash was stale after
  extending its embedded build-provenance record.** PR #39 (the
  self-hosted av-provenance fix) added `pyav_sdist_url`/`sha256`/`bytes`
  to the wheel's embedded `FFMPEG-PROVENANCE.json`, which deterministically
  changes the compiled wheel's bytes — but `build_native_pyav_wheel.py`'s
  `EXPECTED_WHEEL_SHA256`/`BYTES` still pinned the PRE-change reference, so
  the hosted-lane "Two independent Windows workspaces" reproducibility
  gate (run 32831619693) failed on its very first build: `av-18.0.0-
  cp311-abi3-win_amd64.whl byte length 4347090 != pinned 4346940`. Not new
  non-determinism — the embedding mechanism (`SOURCE_DATE_EPOCH`, the
  fixed zip timestamp, `sort_keys=True` on the JSON) is unchanged and
  already handled the original FFmpeg-only provenance fields
  deterministically; the 3 new fields are static compile-time constants
  with no environment/timestamp dependency. Re-pinned `EXPECTED_WHEEL_
  SHA256`/`BYTES` to the real value the gate's own workspace-a build
  reported (`0f9427a4...` / 4,347,090 bytes); cascaded to
  `requirements-native-app.txt`'s `av==18.0.0` hash pin (the same reviewed
  wheel identity, enforced separately at install time) and, since that
  changes the lock file's own bytes, to `APP_REQUIREMENTS_SHA256` in
  `civiccast/native/app_payload.py` (`git diff` checked before re-pinning,
  per that constant's own standing rule: exactly one byte range changed,
  nothing else in the lock). Two test literals
  (`tests/native/test_pyav_wheel_builder.py`,
  `tests/native/test_app_payload.py`) updated to match. Not independently
  re-verified by a local double-build (this box has no pinned MSVC Build
  Tools install; provisioning one plus two full FFmpeg/PyAV compiles was
  not feasible in reasonable time) — verified by full test suite instead,
  and by letting CI's own two-independent-workspace comparison confirm on
  the next push.
- **S12 OTT build matrix — Samsung Tizen was the one dishonest cell:
  `tizen package` never actually ran; the job passed via a static
  `config.xml`-validation fallback instead of a real `.wgt` build.** Root
  cause, found via a base64-encoded `profiles.xml` dump on a diagnostic CI
  run (needed because GitHub's log masking hides the plaintext otherwise):
  Tizen Studio CLI 2.5.25's `tizen security-profiles add` writes
  `password="<path>.pwd"` into `profiles.xml` for both the author profile
  and the auto-attached default distributor profile — a path to a sidecar
  `.pwd` file that is never created, instead of the real plaintext
  password. `tizen package`'s signer then reads that path string literally
  as the PKCS#12 password and fails with `CertificationException: Invaild
  password` — not a certificate, cli-config, or DISPLAY-less quirk;
  install, certificate generation, security-profile registration, and
  cli-config all already worked. Two other projects hit the identical
  stack trace running `tizen package` headlessly
  (jellyfin/jellyfin-tizen#66, fgl27/smarttv-twitch#41); the new
  `civiccast/apps/ott-native/tizen/fix_signing_profile.py` applies the
  same fix those issues converged on — patch the bogus `.pwd` paths to the
  real plaintext passwords right before packaging — and stages just the
  four real runtime files into a clean temp directory first so the
  resulting `.wgt` doesn't ship this repo's dev/CI-only files. All 8
  `ci-ott-apps.yml` platforms now produce a real build artifact; see
  `docs/spec/3.0/sections/S12-ott-apps.md` and `tizen/README.md` for the
  full diagnosis. `civiccast-tizen-wgt` verified as a real signed widget
  (contains `author-signature.xml`/`signature1.xml`) on CI run
  32819441306.
- **Self-hosted native-beta candidate build — the advisory PyAV posture
  stopped one layer too early: the independent post-build provenance
  sweep still rejected the self-hosted-built `av` wheel outright.**
  Candidate run 32822175257 got through the PyAV build and `uv install`
  steps (#30's advisory posture) and still failed "Build and verify
  signed component packs": `"WHEELS/av-18.0.0-cp311-abi3-win_amd64.whl is
  not an authorized retained dependency wheel"` plus every one of `av`'s
  installed files reported `"is named by no wheel RECORD"`.
  `scripts/build_native_app_payload_pack.py`'s `build_app_payload_pack()`
  runs `scripts/verify_native_app_payload.py`'s independent, deny-by-
  default `check_app_payload_verification()` on the fully assembled tree
  AFTER the build — a separate code path from `install_pinned_
  dependencies()`, with no advisory posture of its own, so it re-rejected
  the same wheel on its own byte hash regardless of how the earlier steps
  had authorized it. `_retained_dependency_wheel_provenance()` now
  authorizes a byte-hash-mismatched `av` wheel by BUILD PROVENANCE instead
  (name/version pin against the reviewed lock stays a hard failure,
  unaffected): it re-asserts the two upstream inputs the wheel was
  compiled FROM — the PyAV sdist and the FFmpeg source archive, both
  always hash-verified hard-fail on every lane — by reading them back out
  of the wheel's own embedded `FFMPEG-PROVENANCE.json` (`ffmpeg_
  provenance()` in `build_native_pyav_wheel.py` now also records the PyAV
  sdist's hash/bytes, alongside the FFmpeg source archive's it already
  recorded) and re-checking against the same pinned constants — never
  trusted unchecked. Once authorized this way, the existing per-member
  ownership walk needs no further change: it already anchors every
  installed byte to the IN-RUN wheel's own bytes/RECORD, which resolves
  the RECORD-mismatch symptom for free — the RECORD was never wrong, it
  was simply never reached because the wheel was never authorized.
  `check_app_payload_verification()`/`build_app_payload_pack()` take the
  same `advisory_pyav_wheel_hash` flag threaded from the CLI; every OTHER
  retained wheel, and `av` itself on the hosted lane (flag unset, always),
  is unaffected. `tests/native/test_app_payload_builder.py`: +6 tests
  (authorizes a provenance-matching wheel; hosted lane still fails the
  same wheel; a wrong version pin still fails even advisory; a TAMPERED
  provenance claim still fails; a MISSING provenance file still fails; the
  flag does not relax any other distribution).
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
