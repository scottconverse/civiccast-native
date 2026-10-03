# Install layout: folders, Windows service, ports, data, logs, uninstall and upgrade as implemented  (nav id: installer-install-layout, section: Installer)
Source files: `civiccast/native/supervisor/install_layout.py`, `supervisor/service.py`, `supervisor/config.py:37-38`, `supervisor/children.py`, `supervisor/core.py:388-394`, `provision/__main__.py:541-597`; under `civiccast/apps/installer/src-tauri/`: `nsis-hooks-bootstrap.nsh`, `src/main.rs`, `src/native_service_registration.rs`, `src/native_activation.rs`
Who can open it: reference. Folders under Program Files need Administrator to change; ProgramData is created by the elevated setup.

## 1. Folders
Default install folder `C:\Program Files\CivicCast (Native)` (UNVERIFIED as the page default; it is the folder quoted in `main.rs:3590-3592` and Tauri per-machine's default). Setup may be pointed elsewhere on the folder page. Below, `<I>` is the install folder.
| Path | Contents | Source |
|---|---|---|
| `<I>\CivicCast Native.exe` | the bootstrap/GUI program | `nsis-hooks-bootstrap.nsh:1524` |
| `<I>\uninstall.exe` | uninstaller | `:1728` |
| `<I>\vc_redist.x64.exe` | Visual C++ runtime installer | `:710` |
| `<I>\runtime\` | embedded Python 3.12, CivicCast program, both web portals (`runtime\python.exe`, `runtime\pythonservice.exe`) | `native_pack_staging.rs` / `install_layout.py` |
| `<I>\packs\native-server-binaries\payload\` | PostgreSQL tools; `tsduck\bin\tsp.exe` if shipped | `install_layout.py:205-214` |
| `<I>\packs\.station-cache\` | per-pack cache of the model packs (about 21 GB per the setup text) | `:2209` |
| `<I>\packs\captions-floor\` | caption Medium model | `native_activation.rs` |
| `<I>\dependencies\ffmpeg\bin\`, `dependencies\ollama\`, `dependencies\cuda\` | ffmpeg and ffprobe, Ollama 0.30.6 AI engine, optional GPU libraries | `install_layout.py:225-244` |
| `<I>\components\<id>\` | summary-gemma4-12b, summary-gemma4-e4b, translation-translategemma-4b, optional captions-large-v3 | `native_activation.rs:35-60` |
| `<I>\models\ollama\` | the merged Ollama model store used by the station | `install_layout.py:219` |
| `<I>\station\` | embedded signed station index and `core.ccpack` | `nsis-hooks-bootstrap.nsh:13-16` |
| `<I>\station-set.json`, `<I>\activation-self-test.json` | proof that activation and self-test passed (the service will not start without them) | `native_activation.rs:882-972` |
| `C:\ProgramData\CivicCast\` | everything that survives uninstall (below) | `install_layout.py:176-193` |
Whether any machine variable moves ProgramData: the root follows the `PROGRAMDATA` environment variable and defaults to `C:\ProgramData` (`install_layout.py:168-172`).

## 2. ProgramData tree (`C:\ProgramData\CivicCast`)
| Path | What |
|---|---|
| `data\pgdata\` | PostgreSQL cluster (all station data, with a locked-down access list) (`provision/__main__.py:541-597`; `install_layout.py:216`) |
| `data\egress\` | the station's published/streamed output (HLS and other egress) |
| `data\uploads\` | operator-uploaded media (recordings, uploads) (`install_layout.py:249-257`) |
| `packs\` | components the first-run wizard downloaded (same relative layout as `<I>\packs`): `native-app-payload.ccpack`, `captions-floor\`, `local-ai-model\models\` etc. (`install_layout.py:259-270`) |
| `components\captions-large-v3\` | optional Large caption model when downloaded |
| `logs\` | see section 5 |
| `install-progress.log` | time-stamped setup breadcrumbs (`nsis-hooks-bootstrap.nsh`, CIVICCAST_STEP macro) |
| `install-manifest-report-<pid>-<time>.json` | per-run pack staging report (`main.rs:4564-4598`) |
| `upgrade\` | `upgrade-engine.log`, `upgrade-journal.json`, `UPGRADE-RECOVERY.md` |
| `provision\` | `PROVISION-RECOVERY.md`, `OWNERSHIP-RECOVERY.md`, `ownership-observation.txt`, the provisioning journal |

## 3. Per-user GUI state (first-run wizard)
- `%USERPROFILE%\.civiccast\installer-state.json` and `runtime-host.log` (`main.rs:46-72,86-160`).
- WebView storage at `%LOCALAPPDATA%\org.civiccast.native` (from the Tauri identifier; UNVERIFIED).
- Browser-storage keys `civiccast.acquisitionFlowComplete` and `civiccast.installerProgress` (see the GUI files).

## 4. Windows service, ports, firewall
| Item | Value | Source |
|---|---|---|
| Service name / display name | `CivicCastSupervisor` / "CivicCast Native Supervisor" | `supervisor/config.py:37-38` |
| Runs as, start type | LocalSystem, automatic | `native_service_registration.rs` (constants 154-245) |
| Restart on failure | after 5 s, then 10 s, then 30 s | same |
| Children it launches | PostgreSQL, the control plane (web server + station engine), the Ollama AI engine | `children.py:93` |
| Stop behavior | children stopped in reverse order, graceful first, 15 s each before termination | `service.py` docstring, `children.py:140` |
| Control plane (web pages and API) | `127.0.0.1:8000`; staff console `/operator/`, resident portal `/` | `core.py:393-394`; `nsis-hooks-bootstrap.nsh:1794-1801` |
| PostgreSQL | `127.0.0.1`, first free of 5432, 5433, 5434, 5435, 5544 | `provision/models.py:335-336`; `port_select.py:140` |
| Ollama AI engine | `127.0.0.1:11434` | `children.py:146-152` |
| Runtime-host single-instance mutex port | 38474 | summary of `main.rs` (UNVERIFIED line) |
| Windows Firewall rule | "CivicCast (Native) Portal/API (TCP 8000)", inbound, TCP 8000, any profile, program `<I>\runtime\python.exe` | `native_service_registration.rs:2774-2790` |
Registry: `HKLM\SOFTWARE\CivicCast\Native` (`DatabaseUrl` readable only by SYSTEM and Administrators, `InstalledVersion`); `HKLM\SOFTWARE\CivicCast` (`ActiveRuntime`, `Maintenance`, `NativeUninstallPostclearPending`); Tauri install key `HKLM\Software\civiccast\CivicCast (Native)`; Windows uninstall entry with `EstimatedSize`, `QuietUninstallString`, `InstallLocation`.
Observation: the control plane's default listen address is `127.0.0.1`; the firewall rule opens TCP 8000 to other machines. UNVERIFIED: whether any setting or the service registration changes the listen address; as read, other computers on the network could not reach the portal even with the rule open. [HELP-102] below.

## 5. Logs (all under `C:\ProgramData\CivicCast\logs`, `service.py:34,192,348,470`)
| File | What | Rotation |
|---|---|---|
| `supervisor.log` | the Windows service itself | 10 MiB x 10, flushed to disk each record |
| `control_plane.log` | stdout/stderr of the control plane child | UNVERIFIED rotation |
| `control_plane-app.log` | the application's own log | UNVERIFIED rotation |
| `postgres.log` | PostgreSQL server | by PostgreSQL |
| `postgres-launcher.log` | transient pg_ctl output | |
Setup logs: see section 2. GUI: `runtime-host.log` (section 3). The "Open installer log" button in the GUI: see `installer-gui-downloading.md`.

## 6. Shortcuts
Start Menu: "CivicCast Operator Console.url" (`http://127.0.0.1:8000/operator/`), "CivicCast Public Portal.url" (`http://127.0.0.1:8000/`); Desktop: "CivicCast Operator Console.url" (`nsis-hooks-bootstrap.nsh:1791-1814`).

## 7. Uninstall as implemented (detail: `installer-uninstall.md`)
Stops and removes the service, deletes the firewall rule, clears the registry keys and the maintenance flag, then deletes `<I>\runtime`, `<I>\packs` (including the 21 GB cache) and `<I>`. Keeps all of `C:\ProgramData\CivicCast`. Retries are safe. Refuses to delete files if the service cannot be confirmed stopped (exit 82/133).

## 8. Upgrade as implemented (detail: `installer-nsis-upgrade-database.md`)
Same setup.exe over an existing install: service stopped (registration kept), packs re-verified, engine backs up and migrates the database with rollback, then registers the service again and starts it. Older over newer refused (129). A same-version re-run changes nothing.

## 9. First-run wizard writes (non-elevated)
Downloads land in `C:\ProgramData\CivicCast\packs` and `components` because the GUI cannot write under Program Files (`install_layout.py:259-270`).

## Help-text findings
- [HELP-102] The product opens firewall port 8000 (so other computers can reach staff and resident pages) but, as read, binds to 127.0.0.1 only. A manual that tells IT staff "other PCs on the network can open the portal" would be wrong unless the bind is changed elsewhere. Needs a coder answer, then say plainly in the manual.
- [HELP-103] No on-screen text anywhere gives the folder list above; an operator who must back up recordings and the database has no setup text saying "back up C:\ProgramData\CivicCast".
- [HELP-104] The Start Menu shortcuts are `.url` files pointing at localhost; if the service is stopped they show a browser error, and no text tells the operator to start the service.

## Screenshot plan
Explorer views of `<I>` and `C:\ProgramData\CivicCast`; services.msc entry; firewall inbound rule.

## UNVERIFIED / open questions
- UNVERIFIED: default install folder; rotation of `control_plane*.log`; the mutex port 38474 line number; WebView data folder.
- UNVERIFIED: whether `data\egress` or `data\uploads` are removed by any step (none found).
- UNVERIFIED: that an uninstall leaves the `ProgramData\CivicCast\packs` downloads and the PostgreSQL cluster (no deleting step found).
