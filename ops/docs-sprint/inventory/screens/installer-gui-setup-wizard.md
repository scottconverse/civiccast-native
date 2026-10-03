# Installer step: setup wizard / "CivicCast Installer" status window  (nav id: installer-gui-setup-wizard, section: Installer)
Source files (under `civiccast/apps/installer/`): `src/App.tsx`, `src/api.ts`, `src/installer-transition.ts`, `src/lane-affordances.ts`, `src/progress-visual.ts`, `src-tauri/src/main.rs`
Who can open it: whoever starts the installed app "CivicCast (Native)" (it runs as the normal user; the app manifest is `asInvoker`, `build.rs`). No sign-in or roles. Fixtures for testing: `?state=loading|success|empty|error|partial|blocked|progress|skipped_model|offline_bundle|credential_gated|beta_handoff|activitypub_setup` (`api.ts:15-244`).

## What it is for
After the download screens (or on every later launch) this window shows whether the CivicCast background service is up, lets the operator open the operator console, and offers a few recovery buttons. In the shipping flow it is mostly a status panel for two steps: "Setting up CivicCast" and "CivicCast setup".

## What the user sees
1. Until state loads: "CivicCast Installer" / "Checking Windows settings. This can take up to a minute on a new computer." / "CivicCast is working. This screen will update when the check finishes." (`App.tsx:636-646`). After that, the three download screens run first if never completed (see the other files).
2. Header "CivicCast Installer"; lead "CivicCast is installed and ready. Open the operator console to continue." or "Download, install, create the first admin, then open the dashboard without terminal commands." (`:671-675`); link "Report a beta issue"; "Do not include passwords, recovery codes, staff tokens, or private meeting material." (`:683-685`); pill "Ready" or "Not ready".
3. Band "Platform" with the value (normally `windows-native`) (`:694-697`).
4. Phase strip "Installer progress overview": "Setting up CivicCast", "Preparing video tools", "Preparing local storage", "Generating local secrets", "Starting CivicCast", "Opening the dashboard"; one is highlighted by lane id (`:26-41,214-225`).
5. "Installer progress saved" / "Resume after reboot" panel with the saved message and "Reset progress" (`:227-252`).
6. Setup-activity box (only while the runtime step runs): bold message, phase, "N seconds elapsed" / "N minutes M seconds elapsed", spinner, "Keep CivicCast Installer open. The timer and activity bar remain live while bundled components are prepared." (`:254-286`).
7. Status line (aria-live) with the last action's message.
8. Wizard: left list of steps (number, name, state word, "N of M ready" bar), right detail for the chosen step: "Step N", state word, step name, primary button, detail text, "Next: <next step>", buttons.
9. Footer: "CivicCast is open source: program code under the Apache License 2.0, documentation under CC BY 4.0. Full license texts and legal notices: LEGAL-NOTICES.md." (`:833-846`).

## Steps (lanes) the native app itself produces (`api.ts:248-420`, from `%USERPROFILE%\.civiccast\installer-state.json`)
| Step name | State | Detail text |
|---|---|---|
| Setting up CivicCast | Ready | "CivicCast's local services are ready on this computer." |
| CivicCast setup | Needs setup ("partial") | "CivicCast's local services are ready. It still needs to prepare storage and start the dashboard." Next: "Choose Continue to finish setup and open the operator dashboard." |
| CivicCast setup | In progress | the saved message; Next "Keep this window open while CivicCast prepares storage and starts the dashboard." (or "...while CivicCast recovers automatically." when status is "unavailable") |
| CivicCast setup | Ready | the saved message; Next "Open the operator console. Sign in if prompted, then run System Health and a private rehearsal." |
| CivicCast setup | Error | the saved message; Next "Use Open installer log below, then retry. If the failure repeats, send that log to support." |
| (no state file, service not up) "Starting CivicCast" | Loading | "CivicCast is starting its local services. On a first launch this takes a moment while the station prepares its database and control plane." Next: "Keep this window open. It updates by itself as soon as the station answers." (`api.ts:112-126`) |
| (restart pending, legacy) | Needs setup | Next: "Restart this computer, then open CivicCast Installer again. It picks up where it stopped." |
State words (`App.tsx:43-55`): Loading, Ready, Needs input, Error, Partial, Needs setup, In progress, Cancelled, Credential gated, Hardware required, Not available.
Every launch also writes the runtime step state: "CivicCast's native background service is running." (ready) or "CivicCast's native background service is not reachable yet." (unavailable), after one `/health` probe on 127.0.0.1:8000 (`main.rs:4136-4164`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Open operator console | opens `http://127.0.0.1:8000/operator/` in the default browser | `open_operator_console` -> `cmd /C start` (`main.rs:3807-3825`); only local 8000 / 5173 URLs allowed (`:3797-3805`) | none | primary button when the station is ready; hover title shows the URL. Auto-opens once after a setup this window itself ran (`App.tsx:455-480`) |
| Continue | runs the runtime start step | `run_local_installer_action(lane, "continue")` -> starts a hidden `--civiccast-runtime-host` process and polls `/health` for 10 s (`main.rs:4068-4107,508-521`) | none | auto-clicked once at launch when the platform step is ready and the runtime step is "Needs setup" (`App.tsx:366-429`), banner "CivicCast is finishing setup. The dashboard will open when everything is ready." |
| Retry | same as Continue | same | none | shown on Error or Cancelled |
| Next step | moves to the next step in the list | none | none | when the current step is already ready |
| Prepare storage / Set up models | labels used for the storage / models lanes | same actions | none | only in summary-API or fixture lanes |
| Cancel | writes "paused" state | `run_local_installer_action(.., "cancel")` | none | only for a step "In progress" and not the runtime activity (`:780-784`); message "CivicCast paused this lane. Resume from this installer before the first public meeting." |
| Open installer log | opens the newest log | `open_installer_log` | none | only on an Error step on Windows (`:775-779`) |
| More options > Repair this step | for runtime lanes re-runs the runtime start; for other lanes only writes "CivicCast queued a repair pass for this installer lane." | `main.rs:4219-4229` | none | hidden for the "Setting up CivicCast" step and unless the step is Error/Needs setup (`lane-affordances.ts:37-42`) |
| More options > Download AI models and captions | clears the first-run latch and re-enters the three download screens | `clearAcquisitionFlowComplete()` (`App.tsx:618-622`) | none | safe on a healthy station: verified components download nothing |
| More options > Show uninstall instructions | shows the message "Use Windows Settings to uninstall CivicCast after backing up meeting records." | writes state `uninstall_requested` (`main.rs:4230-4235`) | none | does not uninstall anything |
| Reset progress | deletes the saved state file | `reset_local_installer_state`: "CivicCast reset installer progress. Durable records were not deleted." (`main.rs:2930-2939`) | none | hidden during setup activity |
| Report a beta issue | opens a GitHub new-issue page `scottconverse/civiccast-native` in a browser | none | none | needs a GitHub account (`App.tsx:677`) |
| ActivityPub federation guide | link to `docs/ops/activitypub-federation.md` on GitHub | none | none | only on the optional ActivityPub step (fixture) |

## Behavior notes
- State is re-read every 2 s; a step the operator clicked stays selected (`App.tsx:482-509`). While the runtime step is running it refreshes every 3 s (`:431-453`).
- If the saved state says ready but `/health` fails, it flips to "unavailable" and vice versa (`main.rs:2880-2928`). "Ready" therefore means only that the control plane answered `/health`.
- Closing the window exits the whole app (`main.rs:6459-6463`) and the background runtime host loop also exits when a shutdown marker file appears (`:162-197`).
- The runtime host only watches health and writes `%USERPROFILE%\.civiccast\runtime-host.log`; recovery is done by the Windows service's own restart actions 5 s / 10 s / 30 s (`main.rs:568-615`).

## Help-text findings
- [HELP-62] SERIOUS: `App.tsx:674` "Download, install, create the first admin, then open the dashboard without terminal commands." — the installer never creates an admin (no code does; search for admin creation found only this sentence). First-admin creation happens in the operator console or by recovery code (not in this inventory). Suggest "Install CivicCast, then open the operator console to set up the first administrator."
- [HELP-63] `App.tsx:677` "Report a beta issue" opens GitHub issue creation, which requires a GitHub account; the resident portal's link and the operator manual have a no-account path (`portal-public/src/App.tsx:35`). Inconsistent; offer the same no-account route.
- [HELP-64] "CivicCast Installer" is the heading but the window and app are "CivicCast (Native) Setup"/"CivicCast (Native)"; and "Platform: windows-native" is shown raw (`App.tsx:696`). Suggest hiding the raw value.
- [HELP-65] State word "Partial", "Needs setup", "Needs input", "Credential gated", "Hardware required" are developer states; none are produced by the shipping native flow except Ready/Needs setup/In progress/Error/Loading.
- [HELP-66] "Show uninstall instructions" shows one line in the status area, easy to miss, and does not list steps. See `installer-uninstall.md` for what Windows uninstall actually does.
- [HELP-67] "Ready" can show while captions and AI models are absent (App.tsx comment at lines 794-802: a silent install reaches Ready without them); nothing on the Ready screen says models may be missing.
- [HELP-68] "Resume after reboot" panel text is a developer message (`progress.message`) shown verbatim.

## Screenshot plan
Starting state; ready state with "Open operator console"; runtime step in progress with timer; error step with "Open installer log"; "More options" expanded; footer.

## UNVERIFIED / open questions
- UNVERIFIED: the `/api/staff/installer/summary` fetch (`api.ts:622-640`) is a relative URL; inside the Tauri window it probably cannot reach the station, so lanes come from the saved state file or the "Starting CivicCast" fallback. Not tested.
- UNVERIFIED: the Windows setup program's finish page (Run checkbox) that launches this window (Tauri NSIS template not in the repo).
