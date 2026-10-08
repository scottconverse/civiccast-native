> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# CivicCast Installer status window (Tauri window "CivicCast (Native) Setup", after the download screens)

Paths relative to `civiccast/apps/installer/`. App = `src/App.tsx`; API = `src/api.ts`; main = `src-tauri/src/main.rs`.

## Where the text lives now
Header, buttons and footer: App:639-846. Step wording from the saved state: API:112-126, 248-420. Messages the program returns: main:2938, 4075-4104, 4136-4150, 4211-4258. The window is the same program as the download screens; this panel shows after them (once per Windows account) and on every later launch (`App:649-651`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "CivicCast Installer" / "Checking Windows settings. This can take up to a minute on a new computer." / "CivicCast is working. This screen will update when the check finishes." | Until state loads | App:639, 640, 643 |
| "CivicCast Installer" | Header | App:670 |
| "CivicCast is installed and ready. Open the operator console to continue." | Lead when ready | App:673 |
| "Download, install, create the first admin, then open the dashboard without terminal commands." | Lead when not ready | App:674 |
| "Report a beta issue" (opens a GitHub new-issue page); "Do not include passwords, recovery codes, staff tokens, or private meeting material." | Header | App:677-685 |
| "Ready" / "Not ready" | Pill | App:689 |
| "Platform" + "windows-native" | Band | App:695-696 |
| "Setting up CivicCast", "Preparing video tools", "Preparing local storage", "Generating local secrets", "Starting CivicCast", "Opening the dashboard" | Phase strip | App:26-33 |
| "Resume after reboot" / "Installer progress saved" + the saved message; **Reset progress** | Panel | App:242-247 |
| "Keep CivicCast Installer open. The timer and activity bar remain live while bundled components are prepared." | Activity box | App:282 |
| "CivicCast is finishing setup. The dashboard will open when everything is ready." | Banner after auto-start | App:378 |
| Step labels "Setting up CivicCast" and "CivicCast setup" with details "CivicCast's local services are ready on this computer.", "...It still needs to prepare storage and start the dashboard.", and nexts "Choose Continue to finish setup and open the operator dashboard.", "Keep this window open while CivicCast prepares storage and starts the dashboard.", "Open the operator console. Sign in if prompted, then run System Health and a private rehearsal.", "Use Open installer log below, then retry. If the failure repeats, send that log to support." | Step list and detail | API:248-420 (351, 382, 413) |
| "Starting CivicCast" / "CivicCast is starting its local services. On a first launch this takes a moment while the station prepares its database and control plane." / "Keep this window open. It updates by itself as soon as the station answers." | When no state file and the station is not up | API:118-123 |
| State words: Loading, Ready, Needs input, Error, Partial, Needs setup, In progress, Cancelled, Credential gated, Hardware required, Not available | Step list | App:43-55 |
| **Open operator console**, **Continue**, **Retry**, **Next step**, **Prepare storage**, **Set up models**, **Cancel**, **Open installer log**, **More options**: **Repair this step**, **Download AI models and captions**, **Show uninstall instructions** | Buttons | App:72-86, 777, 782, 787-808 |
| "CivicCast's native background service is running." / "...is not reachable yet." | Runtime step, one health check at launch | main:4141, 4147 |
| "CivicCast paused this lane. Resume from this installer before the first public meeting." | After **Cancel** | main:4211 |
| "CivicCast queued a repair pass for this installer lane." | After **Repair this step** on a non-runtime step | main:4226 |
| "Use Windows Settings to uninstall CivicCast after backing up meeting records." | After **Show uninstall instructions** | main:4232 |
| "CivicCast reset installer progress. Durable records were not deleted." | After **Reset progress** | main:2938 |
| "Retrying <step>. CivicCast is refreshing this proof step." | After **Retry** | App:518 |
| "CivicCast is open source: program code under the Apache License 2.0, documentation under CC BY 4.0. Full license texts and legal notices: LEGAL-NOTICES.md." | Footer | App:835-843 |

## What really happens
After the download screens, or on any later start, the window reads `%USERPROFILE%\.civiccast\installer-state.json` and makes one check of `http://127.0.0.1:8000/health`. It shows "Ready" only when that check answered; it does not check captions or AI models (App:794-802 comment; main:2880-2928, 4136-4164). **Open operator console** opens `http://127.0.0.1:8000/operator/` in the default browser, and does so once by itself after a setup this window ran (App:455-480). **Continue** or **Retry** starts a hidden runtime-host process that only watches the station's health and writes `runtime-host.log`; the station itself is the Windows service Windows setup already started (main:4068-4107; manual ch. 10). **Cancel** only writes a "paused" note. **Repair this step** restarts that runtime host for the runtime steps and otherwise writes a note; it does not run the repair command. **Show uninstall instructions** shows one sentence and uninstalls nothing. Closing the window ends the whole program (main:6459-6463).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-62 | "Download, install, create the first admin..." (App:674) | The installer never creates an administrator. That is done on First setup in the operator console | SERIOUS |
| HELP-63 | "Report a beta issue" | Opens GitHub's new-issue page, which needs a GitHub account | Low |
| HELP-64 | "CivicCast Installer"; "Platform windows-native" | The window is "CivicCast (Native) Setup"; "windows-native" is an internal value | Low |
| HELP-65 | Needs input, Partial, Credential gated, Hardware required, Not available | Developer states the native flow does not produce; only Ready, Needs setup, In progress, Error and Loading do | Low |
| HELP-66 | "Show uninstall instructions" | One line in the status area; no steps; uninstalls nothing | Moderate |
| HELP-67 | "Ready" and "CivicCast is installed and ready" | Means only that `/health` answered; captions and AI models can be absent (a silent install reaches Ready without them) | SERIOUS |
| HELP-68 | "Resume after reboot" / "Installer progress saved" + raw message | Shows the saved developer message verbatim | Low |
| NEW-1 | "...then run System Health and a private rehearsal" (API:351) | The console screen is named Readiness (headed "Safe to broadcast"; manual ch. 10) | Moderate |
| NEW-2 | "refreshing this proof step", "paused this lane", "queued a repair pass for this installer lane" | "proof step" and "lane" are internal words | Low |
| NEW-3 | **Repair this step** | Not connected to the real repair command (`--civiccast-repair`); for non-runtime steps only a note is written (main:4219-4228) | Moderate |
| NEW-4 | **Cancel** and "paused" | Writes a state note and stops nothing (main:4207-4215) | Low |

## Proposed text
Header and lead (now): heading "CivicCast (Native) Setup"; lead when not ready: "Windows setup has installed CivicCast. This window shows whether the station is running. Open the operator console to create the first administrator." When ready: "CivicCast is installed and the station is running. Open the operator console to create the first administrator or sign in." Hide the "Platform" band. Replace "CivicCast Installer" with "CivicCast (Native) Setup" in App:282, 639, 670 and the saved-state texts that say "open CivicCast Installer again" (API:276).

Ready pill, with a line beneath it (now): "Ready means the station answered a health check. It does not check captions or AI models. Open the operator console, go to Readiness and run a private rehearsal before a meeting." In the step detail (API:351): "Open the operator console. Sign in if prompted, then open Readiness and run a private rehearsal."

Report link (now): "Report a beta issue (opens GitHub; needs a free GitHub account)". After fix: add the no-account route.

Buttons and notes (now): **Show uninstall instructions** shows: "To uninstall: back up C:\ProgramData\CivicCast first (it holds the database and recordings and is kept). Then open Windows Settings, Apps, Installed apps, find CivicCast (Native) and choose Uninstall. Uninstall keeps C:\ProgramData\CivicCast. The model packs inside the install folder are deleted, so a reinstall needs the full kit." **Cancel** message: "CivicCast marked this step as paused. This does not stop the station. Choose Continue to resume." **Repair this step** message (non-runtime steps): "CivicCast noted a repair request. This button does not repair files. To repair an install, run the same version of setup.exe again with its 'packs' folder and choose Add/Reinstall components." **Retry**: "Retrying <step name>. CivicCast is checking this step again."

State words: show only Loading, Ready, Needs setup, In progress and Error.

After fix: when **Repair this step** runs `--civiccast-repair`, say what it repaired; when Ready also checks captions and AI models, restore "installed and ready".

## Notes for the coder
- Edit App:518, 640, 643, 670, 674, 681, 689 and the pill area, 695-696, 787-808 (messages come from `main.rs:4207-4235` and `api.ts`). Pinned tests: `src/license-footer.test.ts` (footer), `src/acquisition-reentry.test.ts:85-88` ("Show uninstall instructions" and the re-entry control), `src/installer-transition.test.ts`, `src/api.test.ts` (state wording), `e2e/installer.spec.ts` (about 21 specs on the lane wizard); search each for the strings you change.
- Needs a code fix, not text: a "Ready" that checks captions and models (HELP-67); wire **Repair this step** to `--civiccast-repair` (NEW-3); make **Show uninstall instructions** show real steps in a dialog; a no-GitHub issue route (HELP-63).
- UNVERIFIED: the `/api/staff/installer/summary` fetch (`api.ts:622-640`) uses a relative URL that probably cannot reach the station from this window; lanes then come from the saved state file or the "Starting CivicCast" fallback; the finish page of Windows setup that launches this window (Tauri template).
