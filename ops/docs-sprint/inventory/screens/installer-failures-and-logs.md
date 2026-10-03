# Installer failures: exit codes, logs, and what the operator does  (nav id: installer-failures-and-logs, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:459-588` (exit constants) and the macros cited below; `src/main.rs`; `src/native_activation.rs`
Who can open it: reference. No UI.

## 1. How failures show
- Interactive setup: an OK-only dialog, then setup ends with the code. First, the service is put to "stopped, manual start" if it exists (`nsis-hooks-bootstrap.nsh:357-424`).
- Silent setup (`/S`): no dialog, exit code and log only (`:247-267`).
- Every step writes before and after to `C:\ProgramData\CivicCast\install-progress.log` with a time stamp; read it from the bottom up to find the last "begin" with no matching "returned".
- Re-running setup after any failure is the supported recovery; partial installs are rebuilt.
- Nothing in these hooks deletes `C:\ProgramData\CivicCast` data on failure.

## 2. Windows-setup exit codes (what setup.exe returns)
| Code | Step | Meaning | What the operator does (from the dialog) |
|---|---|---|---|
| 3010 (VC++ child) | vc_redist | success, Windows restart needed | restart Windows |
| other (VC++ child code) | vc_redist | Visual C++ runtime would not install | read log; run setup again |
| 82 | uninstall | service stop not confirmed | stop service in services.msc or reboot; uninstall again |
| 110 | stage-packs | a required pack missing/untrusted (child 74) or optional GPU pack untrusted (75) | put the named `.ccpack` files in `packs` beside setup.exe; run again |
| 111, 112, 121, 122 | D2 verify | extracted server, app, ffmpeg, Ollama tree does not match its signature | replace the kit copy; run again |
| 113 | D3 | upgrade failed and rollback failed | follow `C:\ProgramData\CivicCast\upgrade\UPGRADE-RECOVERY.md` |
| 114 | D3 | release has a migration that cannot be rolled back; auto-upgrade refused | manual upgrade path with owner acknowledgement (no steps given) |
| 115 | D3 | unexpected fault | read log |
| 116 | provision | PostgreSQL could not be provisioned | read log and `provision\PROVISION-RECOVERY.md` |
| 117 | provision | unexpected fault | read log |
| 118 | service | service could not be registered | read log |
| 119 | firewall | rule could not be created | read log |
| 120 | preinstall | existing service could not be stopped / state unreadable | fix and retry as administrator |
| 123 | activation | child 64/65/66/67/78/other (see `installer-nsis-activation-selftest.md`) | see that file |
| 124 | D3 | rolled back, previous database intact | read `upgrade\upgrade-engine.log` |
| 125 | service | started but not serving (child 84) | read `install-progress.log`, `upgrade-engine.log` |
| 126 | service | would not start (child 83) | read `logs` folder and Windows Application event log |
| 127 | provision | cannot tell which CivicCast runtime owns the machine (child 85) | set `HKLM\SOFTWARE\CivicCast\ActiveRuntime` to `native` if no WSL product; `OWNERSHIP-RECOVERY.md` |
| 128 | D3 | an earlier failed upgrade's record is still on disk | move `upgrade\upgrade-journal.json` aside; run again |
| 129 | D3 | older setup over newer install | run newer setup, or uninstall first |
| 130 | uninstall | declined the ownership-transfer prompt | none |
| 131 | uninstall | ownership transfer failed | read the detail in the dialog |
| 132 | uninstall | blocked (active runtime + WSL product, or state unreadable) | per dialog |
| 133 | uninstall | service stop unconfirmed; files kept | stop service or reboot; uninstall again |
| 134 | uninstall | teardown incomplete; remove by hand | services.msc / Firewall / registry |
| 135 | provision | another CivicCast product (the older WSL edition) is registered (child 87) | uninstall it, or run its `cutover-to-native`; run again |
Child codes also seen: 64 arguments, 65 report write, 66 pack missing/untrusted, 67 activation or self-test, 68 verify, 73/74 uninstall preflight, 75 provision/pack, 76/79 repair, 77 UNVERIFIED, 78 embedded trust key refused, 83 service start, 84 not serving, 85 ownership, 87 other product.

## 3. Where each log is
| Question | File |
|---|---|
| What step did setup reach? | `C:\ProgramData\CivicCast\install-progress.log` |
| Which pack was missing? | the `step stage-packs: child reported:` line in that log; JSON in `install-manifest-report-<pid>-<time>.json` |
| Upgrade or rollback reason | `upgrade\upgrade-engine.log`, `upgrade\upgrade-journal.json`, `upgrade\UPGRADE-RECOVERY.md` |
| Database creation or ownership | `provision\PROVISION-RECOVERY.md`, `provision\OWNERSHIP-RECOVERY.md`, `provision\ownership-observation.txt` |
| Why the station will not run | `logs\supervisor.log`, `logs\control_plane.log`, `logs\control_plane-app.log`, `logs\postgres.log` |
| Which self-test failed | UNVERIFIED location; the dialog says `install-progress.log` but see HELP-87 |
| First-run wizard | `%USERPROFILE%\.civiccast\runtime-host.log`, `installer-state.json`; GUI button "Open installer log" (see `installer-gui-downloading.md`) |

## 4. First-run wizard failures (summary; detail in the GUI files)
Download errors are shown per row with the engine's message; there is no automatic retry (UNVERIFIED: which control re-runs a failed row; see the downloading file). "Repair this step" in the lane wizard only restarts the runtime host; a repair command `--civiccast-repair` exists but is not connected to any button. "Show uninstall instructions" shows a message only. See `installer-gui-downloading.md`, `installer-gui-setup-wizard.md`.

## 5. Support path
No dialog, log or wizard text names a support address or phone, a web page, or an issue tracker. UNVERIFIED: whether the product's website lists one.

## Help-text findings
- [HELP-105] SERIOUS: About 26 distinct setup exit codes (110-135 plus 82) with no table available to the operator; the dialogs show text but never the code, and the silent run shows only the code. The manual needs this table; the setup should print "Error 123" in dialogs.
- [HELP-106] Dialogs say "contact support" but give no contact (see HELP-74).
- [HELP-107] Dialog 114 says "Use the manual upgrade path with operator acknowledgement" and no manual path exists in setup text.
- [HELP-108] Exit code 77 is returned by the preflight but is not named in any text read (UNVERIFIED meaning).

## Screenshot plan
`install-progress.log` open in Notepad at a failure; a dialog with its code (needs a forced failure).

## UNVERIFIED / open questions
- UNVERIFIED: meaning of child codes 76/77/79 beyond "repair".
- UNVERIFIED: exit 3010 is passed on as a restart prompt rather than a setup exit.
