# Stage 1 Installer Lifecycle Verification

This runbook covers the Stage 1 lifecycle paths and the evidence contract that
counts toward machine-readable Stage 1 lifecycle pass status. The proof must
include executed checks for clean install, first-run, repair coverage,
release-artifact binding, uninstall, reinstall, and upgrade to be eligible for
`status: passed`.

Evidence files consumed by `run_stage1_lifecycle_proof.py`:

- `.../artifacts/stage1-lifecycle/3.3-stage1-final/uninstall-proof.json`
- `.../artifacts/stage1-lifecycle/3.3-stage1-final/reinstall-proof.json`
- `.../artifacts/stage1-lifecycle/3.3-stage1-final/upgrade-proof.json`

## Repair verification

Automated coverage: `civiccast/apps/installer/e2e/installer.spec.ts` includes
`installer saves repair progress and can reset it`. That test queues a repair,
persists resumable installer progress, reloads the installer, and verifies reset
clears the saved state.

## Uninstall verification

Local proof steps:

1. Install `civiccast-3.3.0-windows-setup.exe` on the reset clean Windows VM.
2. Confirm the uninstall registry key exists under
   `HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\CivicCast Installer`.
3. Confirm the registry `UninstallString` points to `uninstall.exe`.
4. Launch `uninstall.exe` from that path after backing up any generated meeting
   records.
5. Confirm `%LOCALAPPDATA%\CivicCast Installer` is removed or contains only
   allowed post-uninstall marker/log files, and confirm the uninstall registry
   key is gone.

The Stage 1 clean VM proof captures the uninstall registry entry and
`uninstall.exe` path. Capture this Stage 1 uninstall proof in
`uninstall-proof.json` as `{"status": "passed", ...}` with matching
`source_state` once the destructive path is run.

## Reinstall verification

Local same-version reinstall proof steps:

1. Start from a VM state where `civiccast-3.3.0-windows-setup.exe` already
   installed successfully.
2. Run the same installer again as a same-version reinstall.
3. Confirm the installer exits 0.
4. Confirm the installed app still reports product version `3.3.0`.
5. Confirm the saved installer state still renders the correct first-run lane
   and does not lose the operator-facing recovery path.

This is the required same-version reinstall path for Stage 1. Capture
`reinstall-proof.json` as `{"status": "passed", ...}` with matching
`source_state` once executed.

## Upgrade verification

Local upgrade proof steps:

1. Reset the clean Windows VM to a pre-3.3 snapshot.
2. Install the published `v3.2.0-beta1` Windows installer.
3. Confirm the installed app launches and exposes the v3.2 beta uninstall entry.
4. Run `civiccast-3.3.0-windows-setup.exe` over that installation.
5. Confirm the installed app reports product version `3.3.0`.
6. Confirm first-run or saved setup state remains recoverable and the Windows
   helper lane stays actionable.
7. Keep rollback by retaining the v3.2 installer asset and station data backup.

Capture successful execution as `upgrade-proof.json` with `{"status": "passed", ...}`
and matching `source_state`. Stage 1 cannot mark lifecycle proof as passed until
all three of uninstall, reinstall, and upgrade proofs are executed and bound.

## Machine-readable lifecycle schema

Each lifecycle JSON file must be source-bound to the current commit and must
include the VM/package execution shape, not only `{"status": "passed"}`:

- top-level `version`, `vm_report`, `vm`, and `snapshot`.
- top-level `package.installer_sha256` and `package.proof_kit_sha256`.
- one lifecycle object named `uninstall`, `reinstall`, or `upgrade` with
  `exit_code: 0`, `started_at`, and `finished_at`.
- uninstall evidence additionally records `entries_after`, `app_path_after`,
  and `retained_paths_policy`. Retained user data paths are allowed only when
  the policy explicitly lists them as preserved station/operator state; leftover
  uninstall registry entries or installed executable paths block the proof.
