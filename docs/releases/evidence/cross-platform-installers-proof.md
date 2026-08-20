# Cross-Platform Installers Proof

Run: `2026-05-19-cross-platform-installers`

## Automated Evidence

- Focused installer and policy contracts: `python -m pytest -q --tb=short tests/installer/test_platform_bootstrap.py tests/installer/test_package_artifacts.py tests/installer/test_model_state.py tests/installer/test_airgap_import.py tests/installer/test_installer_api_contract.py tests/installer/test_existing_first_run_regression.py tests/policy/test_cross_platform_installer_policy.py`
- Result: `35 passed in 6.38s`
- Full suite: `python -m pytest -q`
- Result: `959 passed, 3 skipped in 205.57s`

## Browser QA Evidence

The Tauri-compatible React shell under `civiccast/apps/installer/` defines deterministic fixtures for loading, success, empty, error, partial, blocked, progress/cancel, and credential-gated states.

- Build: `npm run build`
- Result: Vite built `dist/index.html`, CSS, and JS successfully.
- Browser QA: `npm run test:e2e`
- Result: `26 passed (5.6s)` across desktop and mobile Chromium projects.
- Coverage: visible actionable copy, console error capture, keyboard focus, and mobile/desktop viewport checks for loading, success, empty, error, partial, blocked, progress/cancel, skipped-model, offline-bundle, live-summary platform mapping, and credential-gated states.

Native Tauri package signing/building is represented by deterministic manifests and package metadata in this lane. OS-specific package tooling absence is recorded as blocked proof by `build_cross_platform_installer_artifacts`, not as a successful native package claim.

Native service start, full runtime configuration, and automatic operator-console launch are not claimed in this proof lane. The GUI queues local installer actions and keeps those actions blocked or pending until OS/package proof exists.

## Platform Proof Gaps

- Windows: bootstrap contract is WSL2 Ubuntu only. Missing WSL2 must surface an
  `Install WSL2 Ubuntu` action that launches the Microsoft WSL installer with
  Windows elevation; see
  `docs/releases/evidence/v1.2-virtualbox-clean-windows-proof.md`.
- Linux/macOS: package lanes require service metadata, sidecars, SHA-256, signed install manifests, and attestation references.
- Model setup: skipped or unavailable models remain `proof_unavailable`.
- Air gap: network-enabled verification is rejected.
