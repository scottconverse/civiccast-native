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

- **This repository.** 2,090 files, ~24 MB, copied from the native-Windows
  release line. The old (private, not archived) repository's 286 MB of
  packed history — WSL-era churn plus roughly 640 MB of historical Git-LFS
  tester binaries — does not transfer, by construction.
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
