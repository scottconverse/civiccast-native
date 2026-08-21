# CivicCast Installer App

This directory contains the Tauri-compatible installer shell for CivicCast's
native Windows product ([ADR 0021](../../../docs/adr/0021-native-windows-runtime.md)
-- see [BRANCHES.md](../../../BRANCHES.md)). No WSL, no Docker, no Linux
install target. The app verifies platform bootstrap, package artifacts,
model setup, NATS, local-CA mTLS, clean-install evidence, and
external-provider gates.

## Current Posture

- The signed setup app registers a Windows service through the SCM and
  supervises the control plane, Postgres, NATS, and the media workers from a
  bundled runtime, at `C:\Program Files\CivicCast (Native)\` -- no separate
  Windows-feature bootstrap, no elevated multi-step servicing UI.
- The setup app extracts the bundled Python/GStreamer/FFmpeg runtime, prepares
  local durable storage and upload folders, registers the Windows service, and
  hands the operator to the operator console.
- The native runtime host's own diagnostic log lives under
  `%USERPROFILE%\.civiccast\runtime-host.log` (see
  `civiccast.installer.service._installer_bootstrap_log_path`).
- The current UI is a guided setup flow with readiness lanes and a concrete
  operator-console handoff.
- External providers remain credential-gated until controlled live proof exists.
- The installer must not report success from placeholder credentials, missing
  package bytes, or mock provider output.

## Development

```powershell
npm ci
npm run build
npm run test:e2e
npm run tauri:build
```

Run commands from this directory. On Windows, use `npm.cmd` from PowerShell if
script execution policy blocks `npm.ps1`.

## Evidence

Release evidence lives under the repo-root `docs/releases/evidence/` directory,
especially:

- [v1.2-beta-tester-handoff.md](../../../docs/releases/evidence/v1.2-beta-tester-handoff.md)
- [v1.2-clean-windows-install-proof.md](../../../docs/releases/evidence/v1.2-clean-windows-install-proof.md)
- [v1.2-native-windows-clean-install-attempt.md](../../../docs/releases/evidence/v1.2-native-windows-clean-install-attempt.md)
- [v1.2-virtualbox-clean-windows-proof.md](../../../docs/releases/evidence/v1.2-virtualbox-clean-windows-proof.md)
- [v1.2-windows-installer-ndi-sender.md](../../../docs/releases/evidence/v1.2-windows-installer-ndi-sender.md)
- [v1.3-release-artifacts-proof.md](../../../docs/releases/evidence/v1.3-release-artifacts-proof.md)
- [v1.3-clean-windows-install-proof.md](../../../docs/releases/evidence/v1.3-clean-windows-install-proof.md)

Do not add screenshots, secrets, local credentials, or personal environment
dumps to this directory.
