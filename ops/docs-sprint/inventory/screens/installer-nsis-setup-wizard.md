# Windows setup program (setup.exe): start, pages, pre-install checks  (nav id: installer-nsis-setup-wizard, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `tauri.native.conf.json`, `tauri.conf.json`, `nsis-lang-native-english.nsh`, `nsis-hooks-bootstrap.nsh:1-700`, `build.rs`
Who can open it: any Windows user who can approve the administrator (UAC) prompt: the config sets `installMode: perMachine` (`tauri.native.conf.json`). Silent mode `/S` is supported and every failure writes the log instead of a dialog (`nsis-hooks-bootstrap.nsh:247-267`).

## What it is for
This is the elevated first phase: a standard Windows (NSIS) setup wizard built by Tauri. It installs the small bootstrap program, then the hooks in `nsis-hooks-bootstrap.nsh` do all real work: prerequisite, pack staging, upgrade engine, database, station activation, service, firewall. This file covers the pages and the checks before any file is replaced. Later steps are in the other `installer-nsis-*.md` files.

## Identity
Product name "CivicCast (Native)"; main program "CivicCast Native.exe"; version `1.0.0-beta.10`; publisher "CivicCast"; copyright "© 2026 The CivicCast Authors"; English only; icon `icons/icon.ico`; WebView2 bundled as an offline installer, installed silently (`tauri.native.conf.json`). The bootstrap embeds only three small resources: `vc_redist.x64.exe`, `station\station-index.json`, `station\core.ccpack` (`:13-16`). Its size is gated below 300 MB (`App.tsx:816-832`).

## Pages and strings (from the config and language file; the page order itself comes from the Tauri NSIS template and is UNVERIFIED)
1. Windows UAC prompt (per-machine install).
2. If CivicCast is already installed: maintenance page. Strings (`nsis-lang-native-english.nsh`): "Already Installed", "CivicCast (Native) 1.0.0-beta.10 is already installed. Select the operation you want to perform and click Next to continue.", "Add/Reinstall components", "Uninstall CivicCast (Native)", "Uninstall before installing", "Do not uninstall", "Choose the maintenance option to perform.", "Choose how you want to install CivicCast (Native).". Newer-installed warning: "A newer version of CivicCast (Native) is already installed! It is not recommended that you install an older version. ..." Older/unknown: "An older version of CivicCast (Native) is installed on your system. It's recommended that you uninstall the current version before installing...". Silent downgrade: "Downgrades are disabled for this installer, can't proceed with the silent installer, please use the graphical interface installer instead."
3. Running-app check: "CivicCast (Native) is running! Please close it first then try again." / "...is running! Click OK to kill it" / "Failed to kill CivicCast (Native). Please close it first then try again".
4. Choose Install Location (default folder: UNVERIFIED, Tauri per-machine default is `C:\Program Files\CivicCast (Native)`, matching the path quoted in `main.rs:3590-3592`). Extra text above the browse box: "CivicCast (Native) needs the space shown below on this drive for the program itself. After Setup finishes, the CivicCast setup wizard downloads additional components (captions and AI models) separately -- their sizes are shown individually, before anything downloads, on that wizard's own screen." (`:199`). The "Space required" figure includes 5,400,000 KB (about 5.1 GiB) declared for the packs (`:189,631`).
5. Installing page with a details list. Lines written there are listed in the other files (every step also writes `C:\ProgramData\CivicCast\install-progress.log`).
6. WebView2 lines: "Downloading WebView2 bootstrapper...", "Installing WebView2...", "WebView2 installed successfully", "Error: Installing WebView2 failed with exit code ...", "Failed to install WebView2! The app can't run without it. Try restarting the installer." (appear only if WebView2 is missing and an install runs).
7. Finish page (UNVERIFIED, Tauri template): after a successful install the CivicCast (Native) window opens with the first-run wizard (`installer-gui-checking-computer.md`).
8. Options shown at uninstall: checkbox "Also delete this account's saved installer settings (your recordings, database and settings in C:\ProgramData\CivicCast always stay on this computer)." (`nsis-lang-native-english.nsh:58`).

## Pre-install steps (NSIS_HOOK_PREINSTALL, `:625-700`)
| Step | What happens | Operator-visible text |
|---|---|---|
| Declare space | `AddSize 5400000` KB | space figure on page 4 |
| Classify install | runs `sc.exe query CivicCastSupervisor` | log: "preinstall: classify existing install for upgrade" |
| Existing install found | runs the old program with `--civiccast-stop-native-service` (graceful stop, keeps the service registration and version/database markers for the upgrade engine) | "Preparing the existing CivicCast (Native) installation for a data-preserving upgrade..." |
| Stop refused | aborts with exit 120 before replacing any file | "CivicCast (Native) setup found an existing installation but could not safely stop its native service (service-stop exit N). Setup stopped before replacing application files. Its service registration, upgrade identity, recordings, database, and settings were not deleted. Retry after resolving the service error; if it persists, contact support with C:\ProgramData\CivicCast\install-progress.log." |
| Service present but old program missing | exit 120 | "...found the CivicCastSupervisor service, but the existing CivicCast Native bootstrap is missing from `<dir>`... Do not delete C:\ProgramData\CivicCast; it contains the station's recordings, database, and settings. Repair or remove the broken application installation without deleting application data, then retry, or contact support..." |
| Service query fails for another reason | exit 120 | "...could not safely determine whether the CivicCastSupervisor service exists (service-query exit N). Only Windows service error 1060 definitively means the service is absent..." Retry as administrator. |
| Fresh install | log "no existing install found; fresh install" | none |
| Stop old GUI | `taskkill /IM "CivicCast Native.exe" /T /F` only if an older exe exists | "Stopping the existing CivicCast Native bootstrap before installation..." or "No prior CivicCast Native bootstrap process to stop (fresh install)." |

## Typical task flows
1. Fresh install: double-click setup.exe from the kit folder, approve UAC, choose folder, wait for the steps in the other files, then the CivicCast window opens.
2. Upgrade: run the newer setup.exe; the old service is stopped first, data is kept.
3. Silent: `setup.exe /S` (quiet; failures only in the exit code and the log).

## Help-text findings
- [HELP-73] SERIOUS: the folder page text (`:199`) says captions and AI models download after Setup finishes, but the install phase itself needs the kit's station folder and model packs and fails with exit 123 or 110 without them (`:1441-1445`, `:2184-2209`; see `installer-nsis-packs-and-verify.md`, `installer-nsis-activation-selftest.md`). The text and the "Space required" figure both understate the footprint (about 5.1 GiB declared, more than 21 GB of packs extracted plus 2 GB working room, `native_activation.rs:841`).
- [HELP-74] Error dialogs say "contact support with C:\ProgramData\CivicCast\install-progress.log" but no support contact is given in any dialog (`:657,662,667`).
- [HELP-75] Dialog text uses "bootstrap", "supervisor service", "service registration", "upgrade identity": jargon for a PEG station manager. Suggest a plain first sentence ("Setup could not stop the running CivicCast service, so it did not change anything.").
- [HELP-76] No page tells the operator that setup can take a long time (copying and testing tens of GB, with AI test runs); see activation file.

## Screenshot plan
Maintenance page on a machine with CivicCast installed; folder page (showing the extra text and "Space required"); details pane during install; the preinstall refusal dialog (stop the service with a lock or break the old exe).

## UNVERIFIED / open questions
- UNVERIFIED: exact page sequence, default install folder, finish-page options (Tauri template not in the repo).
- UNVERIFIED: wording after Tauri expands `{{product_name}}`.
