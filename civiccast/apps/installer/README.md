# CivicCast Installer App

This directory contains the Tauri-compatible installer shell for CivicCast. The
installer is part of the `1.0.0-rc17` beta-blocker repair line. rc13 is withdrawn from beta
installation while this repair is verified. The app verifies
platform bootstrap, package artifacts, model setup, NATS, local-CA mTLS,
clean-install evidence, and external-provider gates.

## Current Posture

- On Windows, CivicCast uses a Windows helper to run its local meeting tools on
  the user's computer.
- The app can launch setup for that Windows helper and ask Windows for the
  required approval.
- Windows helper setup is single-instance across clicks, installer processes,
  and installer close/reopen cycles while an elevated bootstrap is active.
  While Windows servicing runs, the UI shows the active phase, step count,
  elapsed time, and a heartbeat every few seconds. CivicCast never force-kills
  DISM or starts a second Windows-feature step after a failed or reboot-pending
  first step. Helper consoles stay hidden; the Windows administrator-consent
  prompt remains visible.
- The Windows helper setup writes a local diagnostic log under
  `%USERPROFILE%\.civiccast\bootstrap-wsl2-ubuntu.log`, writes structured state
  under `%USERPROFILE%\.civiccast\bootstrap-wsl2-ubuntu.result.json`, and tells
  the operator when a restart or IT help is required.
- For IT: the Windows helper is WSL2 Ubuntu 24.04 with Python 3.12 and systemd.
  CivicCast requires WSL2, not WSL1.
- Inside the dedicated distro, `civiccast.service` runs as the unprivileged
  `civiccast` account. Root-owned releases and the `current` link live under
  `/opt/civiccast`; mutable station data lives under `/var/lib/civiccast`.
  Runtime output is in `/var/lib/civiccast/logs/civiccast.log`, bootstrap output
  is in `/var/lib/civiccast/logs/bootstrap.log`, and `journalctl -u civiccast`
  shows supervisor diagnostics.
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
