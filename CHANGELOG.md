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
  release line. The archived repository's 286 MB of packed history — WSL-era
  churn plus roughly 640 MB of historical Git-LFS tester binaries — does not
  transfer, by construction.
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
  mechanism for those. `scripts/build_release_artifacts.py`,
  `scripts/policy/check_sidecar_attestation_integrity.py`, and
  `scripts/policy/check_release_artifacts.py` follow the same rule; package
  sidecars now always carry a null `attestation` field. `CODE_SIGNING_POLICY.md`,
  `docs/install/windows-release-trust.md`, and
  `docs/installer/cross-platform-installer.md` describe the Authenticode +
  ed25519 chain instead of Sigstore.

### Fixed

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
  `GITHUB_REPOSITORY`. It was hard-coded to the archived repository, so
  verification would have rejected this repository's own signatures.
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
