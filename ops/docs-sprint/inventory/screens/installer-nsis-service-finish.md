# Windows setup: Windows service, firewall rule, shortcuts, and finish  (nav id: installer-nsis-service-finish, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:1506-1815`, `src/native_service_registration.rs`, `src/main.rs:5956`
Who can open it: runs inside the elevated setup.exe after activation. No roles.

## What it is for
Registers the background Windows service that runs the station, opens the network port for the web pages, records the installed version, and puts shortcuts on the Start Menu and Desktop.

## Steps in order
| # | Log step | What it does | Details-pane text |
|---|---|---|---|
| 1 | `step d4-service-registration` | `"CivicCast Native.exe" --civiccast-register-native-service --install-root "$INSTDIR"` (`:1524`): registers service `CivicCastSupervisor` (display name "CivicCast Native Supervisor", LocalSystem, automatic start, restart ladder 5 s / 10 s / 30 s), starts it, and waits until the station answers as ready | "Registering the CivicCast (Native) supervisor service (D4)..." |
| 2 | (same step) | Restores a copy of `runtime\pythonservice.exe` into `runtime\Lib\site-packages\win32\pythonservice.exe` (`:1557-1563`); if the source is missing, only a log WARNING "...site-packages member NOT restored (next D5 verify will report a repair)" | none |
| 3 | `step d4-firewall-rule` | `--civiccast-register-native-firewall-rule` (`:1584`): inbound allow rule "CivicCast (Native) Portal/API (TCP 8000)", port 8000, program `<install dir>\runtime\python.exe` | "Registering the CivicCast (Native) portal/API firewall rule (D4)..." |
| 4 | `postinstall: EstimatedSize` | measures the install folder and writes it as the size shown in Windows "Apps" (`:1621`) | none (log only) |
| 5 | `InstalledVersion` | writes `HKLM\Software\CivicCast\Native\InstalledVersion` = 1.0.0-beta.10 (`:1662`) | "CivicCast (Native): recorded InstalledVersion 1.0.0-beta.10 for the next install/upgrade run." |
| 6 | uninstall registry fixes | writes `QuietUninstallString` = `"<install dir>\uninstall.exe" /S _?=<install dir>` (`:1728`) and rewrites `InstallLocation` without quotes (`:1737`) | none |
| 7 | shortcuts | see below (`:1791-1814`) | none |
| 8 | success | log "postinstall: SUCCESS (InstalledVersion 1.0.0-beta.10 recorded)" (`:1664`) | "CivicCast (Native) bootstrap install complete: required component packs staged and D2-verified, D3 install/upgrade engine run, PostgreSQL provisioned, service and firewall rule registered." (`:1665`) |

## Shortcuts written (all-users)
- Start Menu folder "CivicCast (Native)" (value of PRODUCTNAME): "CivicCast Operator Console.url" -> `http://127.0.0.1:8000/operator/`; "CivicCast Public Portal.url" -> `http://127.0.0.1:8000/`.
- Desktop: "CivicCast Operator Console.url" -> `http://127.0.0.1:8000/operator/`.
- A failed shortcut write is logged "(non-fatal)" and does not stop setup.
- UNVERIFIED: the Start Menu folder name as shown (`${PRODUCTNAME}` is expanded by the Tauri template).

## Failures
| Child exit | Setup exit | Dialog (full text for the two named cases, `:1574,1577`) |
|---|---|---|
| 84 | 125 | "CivicCast (Native) setup started the station's Windows service, but the station did not come up ready to serve. The most common cause is that the database schema is not the one this version needs, which would make the staff pages return errors. Nothing was deleted. Your recordings, database and settings in C:\ProgramData\CivicCast are intact. The exact reason the station reported is in C:\ProgramData\CivicCast\install-progress.log, and the upgrade engine's own record is in C:\ProgramData\CivicCast\upgrade\upgrade-engine.log. Resolve the cause and run setup again." |
| 83 | 126 | "CivicCast (Native) setup registered the station's Windows service, but Windows could not start it. This is a startup failure, not a registration failure -- the service exists and can be inspected in services.msc. Nothing was deleted. See C:\ProgramData\CivicCast\logs and the Windows Application event log for the exact startup error, then run setup again." |
| other non-zero | 118 | "CivicCast (Native) setup could not register the CivicCast (Native) Windows service. See the installer log for the exact error." |
| firewall non-zero | 119 | "CivicCast (Native) setup could not create the required inbound firewall rule. See the installer log for the exact error." |
Each failure first puts the service to stop and manual start (containment), then shows the dialog (interactive) and exits with the code.
Details-pane lines on failure: "CivicCast (Native): the service is running but the station is not serving (exit 84) — see the installer log above." / "...the service was registered but would not start (exit 83)..." / "CivicCast (Native): D4 service registration FAILED (exit N)..." / "CivicCast (Native): D4 firewall rule registration FAILED (exit N)...".

## What the operator does next
- Open the operator console from the Desktop shortcut (needs the service running): `http://127.0.0.1:8000/operator/`.
- If it does not load: run services.msc, find "CivicCast Native Supervisor", check it is Running; look at `C:\ProgramData\CivicCast\logs\supervisor.log` and `control_plane.log` (see `installer-failures-and-logs.md`).

## Help-text findings
- [HELP-92] Dialog 125 says "database schema" and "staff pages return errors"; it names no action. Suggest: "The station started but is not answering. Open C:\ProgramData\CivicCast\logs\control_plane.log and send the last 50 lines to support, then run setup again."
- [HELP-93] Dialog 126 sends the operator to "the Windows Application event log" without saying how to open it (Event Viewer > Windows Logs > Application).
- [HELP-94] The success line (`:1665`) mentions "D2-verified", "D3" and "D4" and does not say what to do next: no line tells the operator to open the console shortcut or that the first-run wizard will follow. UNVERIFIED: what the Tauri finish page says.
- [HELP-95] Dialog 118/119 give no detail at all ("See the installer log for the exact error") and name no log path, unlike the other dialogs.
- [HELP-96] "Windows Defender Firewall" rule name "CivicCast (Native) Portal/API (TCP 8000)" is not mentioned in any dialog; an IT person adding a rule by hand cannot learn the port from setup.

## Screenshot plan
Details pane through service and firewall steps; services.msc showing "CivicCast Native Supervisor"; Windows Firewall inbound rules; Start Menu folder with the two shortcuts.

## UNVERIFIED / open questions
- UNVERIFIED: how long the "wait until ready" lasts and its limit (registration code in `native_service_registration.rs` not read to the timeout).
- UNVERIFIED: that the firewall rule applies to all profiles (`profile any` read from the command text at `native_service_registration.rs:2774-2790`, not tested).
