# Uninstall, and what an upgrade does to an existing install  (nav id: installer-uninstall, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:625-700,1817-2333`, `nsis-lang-native-english.nsh`, `src/main.rs:5956`, `src/native_service_registration.rs:2890`
Who can open it: any administrator (Windows Settings > Apps, or `<install dir>\uninstall.exe`; silent form is the registry `QuietUninstallString`, `:1728`).

## What it is for
Removes the program and the Windows service but keeps the station's recordings, database and settings.

## Steps in order
1. PREUNINSTALL ownership check (`:1845-1892`): details line "Checking CivicCast Native runtime ownership before uninstall...", runs `--civiccast-native-uninstall-preflight`.
   - Exit 74 (CivicCast (Native) is active and the older WSL-based CivicCast product is still installed): a Yes/No box: "CivicCast (Native) is the active runtime and the WSL product (CivicCast Installer) is still installed. To continue uninstalling CivicCast (Native), ActiveRuntime ownership must first be transferred to the WSL product, which will then become the active runtime that starts and transmits. Transfer ownership to the WSL product now and continue uninstalling CivicCast (Native)?"
     - No: "CivicCast Native uninstall was declined at the ownership transfer prompt; nothing was removed and ActiveRuntime was left unchanged." Uninstall exits 130.
     - Yes: the hook re-runs the preflight with `--acknowledge-transfer`; failure shows "CivicCast Native ownership transfer failed after acknowledgment: <detail>" and exits 131; success: "CivicCast Native ActiveRuntime ownership transferred to the WSL product; proceeding with uninstall."
   - Exit 73: the uninstall arms a later step that clears the ActiveRuntime selector (no dialog).
   - Any other non-zero: alert "CivicCast (Native) cannot be uninstalled while it is the active runtime and the WSL product remains, or when lifecycle state cannot be safely read. Details: <detail>"; exit 132.
2. Teardown (`:1934-1938`): details line "Removing the CivicCast (Native) supervisor service, firewall rule, and registry state...", runs `--civiccast-teardown-native-state`. Steps in order (`native_service_registration.rs:2890`): stop service, remove service, delete firewall rule, clear credentials, clear install markers, clear the empty Native registry key, clear the maintenance interlock, clear the empty CivicCast key.
3. If teardown returned non-zero (`:1983-2005`): "CivicCast (Native) could not be uninstalled, so the uninstall was ABORTED and NOTHING was removed -- your installation is still complete and can be uninstalled again once the problem below is cleared. The teardown step (stopping and removing the CivicCastSupervisor service, removing the firewall rule, clearing registry state) returned exit N. Most often this means the supervisor service did not stop. To finish: stop it manually (services.msc, or 'sc stop CivicCastSupervisor'), or reboot this machine, then run Uninstall again. See the installer log at C:\ProgramData\CivicCast\install-progress.log for the exact step that failed." Exit 82.
4. The running "CivicCast Native.exe" is force-ended: "Stopping the CivicCast Native bootstrap after ownership preflight..." (`:2008`).
5. POSTUNINSTALL (`:2012-2333`):
   - If teardown was 82: alert "...uninstall could not confirm that the CivicCastSupervisor service was fully stopped, so the program files were NOT removed -- deleting them now could corrupt data out from under a still-running service and its database/messaging processes. To finish removing CivicCast (Native): stop the service manually (services.msc, or 'sc stop CivicCastSupervisor'), or reboot this machine, then run Uninstall again." Exit 133; trees retained.
   - If another non-zero: "...could not fully remove the supervisor service, firewall rule, and/or registry state (exit N)... you may need to remove it manually (services.msc / Windows Defender Firewall / HKLM\Software\CivicCast\Native)." Exit 134.
   - If zero: "CivicCast (Native): supervisor service, firewall rule, and registry state removed."
   - ActiveRuntime clear (only when armed by exit 73): deletes `HKLM\Software\CivicCast\ActiveRuntime` then the pending marker; if anything has changed since preflight, it is left unchanged (lines `:2105-2165`; exit 134 if the armed plan is missing, `:2114`).
   - Notice (`:2209`): "CivicCast (Native) is being removed, including the downloaded AI model packs (about 21 GB) kept in this folder. Your recordings, database and settings in C:\ProgramData\CivicCast are NOT affected and are being kept. If you reinstall later by running setup.exe on its own, it will need those model packs again and cannot download them -- reinstall from the full CivicCast kit folder (setup.exe together with its station folder), or copy <install dir>\packs\.station-cache somewhere safe now if you want to reuse it."
   - Removal: `RMDir /r` of `<install dir>\runtime`, `<install dir>\packs`, then the whole `<install dir>` (`:2212-2214`), with `uninstall.exe` deleted on reboot if locked (`:2253-2254`).
   - Registry: deletes `HKLM\Software\civiccast\CivicCast (Native)` (the Tauri install-location key, `:2304`).
   - Shortcuts: deletes the two Start Menu `.url` files, the Start Menu folder if empty, and the Desktop "CivicCast Operator Console.url" (`:2328-2331`).
6. Option on the uninstall page (`nsis-lang-native-english.nsh:58`): checkbox "Also delete this account's saved installer settings (your recordings, database and settings in C:\ProgramData\CivicCast always stay on this computer)." That setting is the per-user folder `%USERPROFILE%\.civiccast` and the WebView data (UNVERIFIED which items the checkbox removes; template-driven).

## What stays after an uninstall
`C:\ProgramData\CivicCast` (data, logs, journals, `packs` folder staged by the GUI downloads, PostgreSQL cluster `data\pgdata`) is not removed by any step in these hooks. UNVERIFIED: whether the PostgreSQL cluster and the `ProgramData\CivicCast\packs` downloads are deleted by the Rust teardown (the listed teardown steps include none that delete them).

## Upgrade (newer setup.exe over an existing install)
- PREINSTALL stops the old service but keeps its registration and the version and database markers (`:625-700`); exit 120 if it cannot be stopped (see `installer-nsis-setup-wizard.md`).
- D3 engine backs up, migrates, health-checks and rolls back on failure (see `installer-nsis-upgrade-database.md`). Older-over-newer is refused with exit 129. A leftover failed-upgrade record blocks with 128.
- Re-running the same version: D3 no-ops (exit 12), the packs are re-checked and left alone if they match.
- The maintenance page offers "Add/Reinstall components" / "Uninstall CivicCast (Native)" and "Uninstall before installing" / "Do not uninstall" (see the wizard file).

## Help-text findings
- [HELP-97] SERIOUS: the uninstall notice tells the operator that after uninstalling, setup.exe alone "cannot download" the models. The product's wizard text says components download. The two statements contradict each other for the operator (HELP-73/77); the notice is the only honest one and appears only at the moment of deletion.
- [HELP-98] "ActiveRuntime", "WSL product", "ownership" in the Yes/No box (`:1850`): the manual must explain the older WSL-based edition, or the box is unanswerable for most users.
- [HELP-99] "services.msc, or 'sc stop CivicCastSupervisor'" (`:1986,2047`): no instruction for opening Services, no mention that the service display name is "CivicCast Native Supervisor".
- [HELP-100] The dialog text still says "database/messaging processes" (`:2047`); stale (messaging is gone).
- [HELP-101] No dialog lists what is kept (recordings under `data\egress` and `data\uploads`, the database) or says how to remove it fully; the operator who wants a clean machine has no instructions.

## Screenshot plan
Windows Settings > Apps entry; the 74 Yes/No box (needs the WSL edition); the 21 GB notice; the service-stop-unconfirmed alert (hold a lock on the service).

## UNVERIFIED / open questions
- UNVERIFIED: the Python-side teardown's effect on `C:\ProgramData\CivicCast\data\pgdata` (not read).
- UNVERIFIED: the exact page order and button names of the uninstall wizard (Tauri template).
