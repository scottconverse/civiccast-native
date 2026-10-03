# Install layout: folders, service, ports, data and logs (reference; no screen of its own)

Paths relative to `civiccast/` unless stated. Hooks = `apps/installer/src-tauri/nsis-hooks-bootstrap.nsh`; main = `apps/installer/src-tauri/src/main.rs`; IL = `native/supervisor/install_layout.py`.

## Where the text lives now
No setup screen lists these folders. The facts live in code: IL:160-301 (every path), `native/supervisor/config.py:37-39` (service names), `apps/installer/src-tauri/src/native_service_registration.rs:154-164, 2774-2790` (service start type, firewall rule), main:3604-3641 (where the first-run window downloads), Hooks:1621-1738 (Apps entry), Hooks:1794-1808 (shortcuts). The only places setup names a folder to the reader are the dialogs that say `C:\ProgramData\CivicCast` and the log path.

## Current text
| String | Where it appears | Source line |
| --- | --- | --- |
| "CivicCast (Native)" (Apps entry, version 1.0.0-beta.10, size measured after install) | Windows Settings, Apps | Hooks:1621-1623; `tauri.native.conf.json:3,5` |
| "CivicCast Operator Console" (Desktop and Start menu folder "CivicCast (Native)") and "CivicCast Public Portal" (Start menu) | Shortcuts | Hooks:1794, 1801, 1808 |
| "CivicCast Native Supervisor" (service name `CivicCastSupervisor`) | Services | `config.py:37-38` |
| "CivicCast (Native) Portal/API (TCP 8000)" | Windows Firewall inbound rules | `native_service_registration.rs:164` |
| "Your recordings, database, and settings in C:\ProgramData\CivicCast were not deleted." | Many dialogs | Hooks:867, 1504 and others |
| "Free disk space on <install target>" | First-run window | `src/AcquisitionFlow.tsx:298`; `hardware_inventory.rs:506-510` |

## What really happens
The program is installed per machine, by default in `C:\Program Files\CivicCast (Native)` (the folder the code quotes at `main.rs:3588-3592`; the setup page default is UNVERIFIED), and everything that must survive an uninstall lives in `C:\ProgramData\CivicCast` (IL:168-193; follows the `PROGRAMDATA` variable). One Windows service, `CivicCastSupervisor`, runs as LocalSystem, starts automatically and restarts after 5, 10 and 30 seconds; it starts PostgreSQL, the CivicCast web application and, if present, the AI engine, and stops them in reverse order (manual ch. 10, 12; `children.py`). The web pages are on `127.0.0.1:8000` (console `/operator/`, portal `/`), PostgreSQL on `127.0.0.1` at the first free of ports 5432, 5433, 5434, 5435 and 5544, and the AI engine on `127.0.0.1:11434` (`core.py:393-394`; `provision/models.py:335-336`; `children.py:146-152`). Setup also opens an inbound Windows Firewall rule for TCP 8000, although the web application listens on this computer only (manual ch. 9, 13). Three web shortcuts open the console and portal. Uninstall removes the install folder, service, rule and shortcuts and keeps `C:\ProgramData\CivicCast` (`installer-uninstall`).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-102 | The firewall rule "...Portal/API (TCP 8000)" reads as "other computers can open the portal" | The control plane binds `127.0.0.1` only (`core.py:393`; manual ch. 9 and 13, which call the rule broader than needed). No setting was found that changes it (UNVERIFIED). Help text must not promise network access | Moderate |
| HELP-103 | No text gives the folder list or says what to back up | Recordings, the database and settings are in `C:\ProgramData\CivicCast` (`data\pgdata`, `data\uploads`, `data\egress`, logs); an operator who must back up has no setup text naming it | Moderate |
| HELP-104 | Three shortcuts look like program icons | They are `.url` web links; with the service stopped they show a browser error and nothing says to start the service | Moderate |
| NEW-1 | Setup names port 8000 only inside a rule name | Nothing tells IT staff that PostgreSQL takes 5432 or the next free port, or that the AI engine takes 11434. Another program already using 11434 would clash (UNVERIFIED which side wins) | Low |
| NEW-2 | "packs" appears twice | `<install folder>\packs` (runtime packs and the 21 GB model cache) is deleted by uninstall; `C:\ProgramData\CivicCast\packs` (what the first-run window downloaded) is kept (main:3604-3641; `installer-uninstall`). Nothing explains the difference | Low |

## Proposed text
In-app help block "Where CivicCast puts things" (now; ready to paste):
> **Program files.** `C:\Program Files\CivicCast (Native)` unless you chose another folder at setup. This folder holds the program (`runtime`), the video tools and AI engine (`dependencies`), the speech and AI models (`components`, `models` and `packs`, about 21 GB of model packs in `packs\.station-cache`) and two files, `station-set.json` and `activation-self-test.json`, that prove setup's self-test passed. Uninstall deletes this whole folder.
> **Your data.** `C:\ProgramData\CivicCast`. Back this folder up; uninstall never deletes it. It holds the database (`data\pgdata`), recordings and uploads (`data\uploads`), the playout working folder and ready-to-play cache (`data\egress`), setup's records (`install-progress.log`, `upgrade`, `provision`), the station's logs (`logs`) and anything the first-run window downloaded (`packs`, `components`). For how to back up and restore, see Chapter 12 of the manual (Back up and restore).
> **The service.** Windows Services shows "CivicCast Native Supervisor" (name CivicCastSupervisor). It runs without anyone signed in, starts with Windows, restarts itself after a crash, and starts the database, the CivicCast web application and the AI engine.
> **Addresses and ports.** The operator console is http://127.0.0.1:8000/operator/ and the resident portal is http://127.0.0.1:8000/, both only on this computer. The database listens on 127.0.0.1 on port 5432 (or the next free one of 5433, 5434, 5435, 5544) and the AI engine on 127.0.0.1 port 11434. Setup adds the Windows Firewall rule "CivicCast (Native) Portal/API (TCP 8000)" (inbound, TCP 8000, any profile, for `runtime\python.exe`); as installed, the station does not answer other computers on the network.
> **Shortcuts.** "CivicCast Operator Console" (Desktop and Start menu folder "CivicCast (Native)") and "CivicCast Public Portal" are web links to those two addresses. If the browser shows an error, the service is stopped: press the Windows key and R, type services.msc, press Enter, find "CivicCast Native Supervisor" and choose Start.
> **Logs.** Setup: `C:\ProgramData\CivicCast\install-progress.log`. Station: `C:\ProgramData\CivicCast\logs` (`supervisor.log`, `control_plane.log`, `control_plane-app.log`, `postgres.log`). First-run window: `%USERPROFILE%\.civiccast\runtime-host.log` and `installer-state.json`.
> **Registry.** `HKLM\SOFTWARE\CivicCast\Native` holds `DatabaseUrl` (readable only by SYSTEM and Administrators) and `InstalledVersion`; `HKLM\SOFTWARE\CivicCast` holds `ActiveRuntime` and the `Maintenance` flag.

First-run window label (now): replace "Free disk space on C:\Program Files" with "Free disk space on the drive that holds Program Files (C:\Program Files)" until the code reads the real install folder.

After fix: if the web application is ever made reachable from other computers, say so and name the setting; until then keep the sentence that the station does not answer other computers.

## Notes for the coder
- No setup string needs a hooks edit for this page; the help block is new in-app text. The first-run label is at `apps/installer/src/AcquisitionFlow.tsx:298`. Folder names in the block are quoted from IL:168-301 and main:3604-3641; re-check them against the code when the layout changes.
- Test pins: none by string. `tests/policy/test_native_installer_identity.py` pins the shortcut URLs against `main.rs` constants `OPERATOR_CONSOLE_URL` and `RESIDENT_PORTAL_URL` (`main.rs:30-31`) ; do not change those literals as part of a wording edit.
- Needs a code answer: HELP-102 (is port 8000 meant to be reachable from the network?). Shortcuts that start the service or say it is stopped (HELP-104). Default folder and other-profile behavior of the firewall rule are UNVERIFIED at runtime (profile any is read from the command at `native_service_registration.rs:2790`).
- UNVERIFIED: the default folder on Tauri's page; rotation of `control_plane*.log`; whether any step removes `data\egress` or `data\uploads` (none found); the Python-side teardown's effect on `data\pgdata`.
