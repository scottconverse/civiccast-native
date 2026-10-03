# Windows setup: Visual C++ prerequisite, component pack staging, and verification  (nav id: installer-nsis-packs-and-verify, section: Installer)
Source files (under `civiccast/apps/installer/src-tauri/`): `nsis-hooks-bootstrap.nsh:702-1030`, `src/main.rs:4469-4640,4351-4468`, `src/native_pack_staging.rs`, `src/native_install_verify.rs`, `src/native_packs.rs`
Who can open it: runs inside the elevated setup.exe (see `installer-nsis-setup-wizard.md`). No roles.

## What it is for
After Windows copies the small bootstrap, setup installs the Microsoft Visual C++ runtime, then extracts the four required signed component packs from a "packs" folder next to setup.exe, and re-verifies every extracted tree against its signed pack. Every step logs to `C:\ProgramData\CivicCast\install-progress.log` before and after, with a time stamp.

## Steps in order (details pane text, then failure)
| # | Log step | What it runs | Details-pane line on success | On failure (exit code of setup.exe) |
|---|---|---|---|---|
| 1 | `step vc-redist` | `"$INSTDIR\vc_redist.x64.exe" /install /quiet /norestart` (`:710-713`) | "Installing the offline Microsoft Visual C++ runtime prerequisite..." then "Microsoft Visual C++ runtime installation completed." | exit 3010: "...completed; a Windows restart is required." and the reboot flag is set. Exit 1638 (same or newer already installed) is accepted only if the registry key `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64` `Installed` = 1, with the line "Microsoft Visual C++ runtime already present, same or newer — prerequisite satisfied; setup did not reinstall it." Any other code fails with the redist's own code: "CivicCast (Native) setup could not install the required Microsoft Visual C++ runtime (exit code N). See the installer log at C:\ProgramData\CivicCast\install-progress.log." (`:714-761`) |
| 2 | `step stage-packs` | `"CivicCast Native.exe" --civiccast-stage-packs "$EXEDIR" --install-root "$INSTDIR"` (`:850-855`) | "Staging required native component packs from the 'packs' folder next to this installer..." then "Required native component packs staged and verified. Full detail: C:\ProgramData\CivicCast\install-progress.log" | exit 110 (child 74 = required pack missing or untrusted; child 75 = optional GPU pack present but untrusted) |
| 3 | `step d2-verify-server-binaries` | `--civiccast-verify-pack-tree ...native-server-binaries.ccpack --destination "$INSTDIR\packs\native-server-binaries\payload"` | "Native-server-binaries component pack verified against its signed pack file (D2)." | exit 111 |
| 4 | `step d2-verify-app-payload` | same for `native-app-payload.ccpack` at `$INSTDIR\runtime` | "Native-app-payload component pack verified ..." | exit 112 |
| 5 | `step d2-verify-ffmpeg-runtime` | `native-ffmpeg-runtime.ccpack` at `$INSTDIR\dependencies\ffmpeg` | "Native-ffmpeg-runtime component pack verified ..." | exit 121 |
| 6 | `step d2-verify-ollama-runtime` | `native-ollama-runtime.ccpack` at `$INSTDIR\dependencies\ollama` | "Native-ollama-runtime component pack verified ..." | exit 122 |

## Step 2 in detail (kit side-load)
- Looks for `.ccpack` files in `<folder of setup.exe>\packs` (`$EXEDIR`). Required components: native-server-binaries, native-app-payload, native-ffmpeg-runtime, native-ollama-runtime (`native_pack_staging.rs:99-104`). Optional: native-cuda-runtime (absent is fine; present-but-untrusted fails) (`:154`; `main.rs:4482-4494`).
- Each pack's signature and byte inventory are checked before copying; the landed copy is re-checked; then it is extracted: server binaries to `$INSTDIR\packs\native-server-binaries\payload`, the app to `$INSTDIR\runtime`, ffmpeg and Ollama under `$INSTDIR\dependencies`, GPU libraries to `dependencies\cuda` (`:657-685`). An already verified extracted tree is left alone.
- The old stop-the-service authority is required before any destructive rebuild of an extracted tree (`native_pack_staging.rs:687-715`).
- There is no download in this step: no channel address is pinned in this build, so only the side-load can satisfy it (`nsis-hooks-bootstrap.nsh:773-785`; `native_pack_staging.rs:340-362`; `main.rs:4495`: `--channel-url` is not passed by the hook).
- A full JSON report goes to `C:\ProgramData\CivicCast\install-manifest-report-<pid>-<time>.json`; the log gets a one-line summary `component=outcome staged=<8hex> incoming=<8hex>` (`main.rs:4564-4598`).
- Failure text shown to the operator (exit 110): "CivicCast (Native) setup could not obtain a required native component pack. The component pack file(s) are published alongside this installer -- on the same release page, or on the same distribution medium you got setup from. To retry: 1. Obtain the required .ccpack file(s) and put them in a 'packs' folder next to the installer (the same folder this setup .exe is in). 2. Run setup again. Setup safely prepares the partial installation before retrying. Your recordings, database, and settings in C:\ProgramData\CivicCast were not deleted. See the installer log at C:\ProgramData\CivicCast\install-progress.log for the exact missing component(s)." (`:867`). The log line `step stage-packs: child reported:` carries the missing names (`:861`; `native_pack_staging.rs:354-362`).
- Failure text for steps 3-6 (111, 112, 121): "...could not verify a required native component pack it just extracted against its signed manifest. This usually means disk corruption or an interrupted copy. Re-download the installer/pack and try again; if this persists, contact support with the installer log." Step 6 (122): "...could not verify the required local-AI runtime pack it just extracted against its signed manifest. Re-download the installer/pack and try again..." (`:940,976,1003,1021`). The log names the mismatched path.

## Controls and what they do
None: no operator control exists in these steps apart from the final dialog button "OK" (interactive) and the wizard's Cancel/Close. Every failure first stops the service and sets it to manual start (best-effort), then shows the dialog, then exits with the code (`CIVICCAST_FAIL`, `:357-424`).

## States
- Silent (`/S`): no dialog; failure = log line + exit code.
- Failure containment: log lines "postinstall: FAILURE CONTAINMENT begin ..." and "...confirmed (service stopped and set to manual start)" or "NOT confirmed (stop=.. config=..)" (`:386-418`).
- Re-running setup after a failure is supported: the partial install is stopped and rebuilt.

## Typical task flows
1. Kit install: setup.exe with `packs\` and `station\` beside it; steps 1-6 run unattended.
2. After exit 110: copy the named packs into `packs\` next to setup.exe, run again.
3. After 111/112/121/122: replace the kit copy (corrupt copy) and run again.

## Statuses and words on this screen
"Staging required native component packs", "D2" (internal name for re-verification), "pack", "ccpack", "payload".

## Related settings / env / CLI / API
Flags: `--civiccast-stage-packs`, `--civiccast-verify-pack-tree`, `--civiccast-verify-pack`, `--civiccast-import-pack`; child exit codes 64 (arguments), 65 (report write), 68 (verify), 74, 75, 78 (embedded trust key refused) (`main.rs:6315-6370,4351-4468`).

## Help-text findings
- [HELP-77] SERIOUS: with only setup.exe (no kit `packs` folder) setup stops at step 2 with exit 110, yet the Windows setup page promises components download later (HELP-73). The manual cannot honestly describe a download-only install. Needs owner confirmation (the code comments call it a known limitation, `:2184-2209`).
- [HELP-78] The dialog does not name the missing packs or the folder path of setup.exe; it points to a log. Add "Missing: native-ollama-runtime" to the dialog (the text is already captured at `:861`).
- [HELP-79] "D2" (`:922,938`) appears in the details pane; meaningless to operators. Suggest "Re-checking that the copied files match their signatures."
- [HELP-80] "Re-download the installer/pack" gives no download address.
- [HELP-81] No progress is shown during extraction of tens of GB; the details pane is quiet for minutes (the log shows a 107 s gap, `:967-970`).

## Screenshot plan
Details pane after steps 1-6 on a good kit; the exit-110 dialog (remove the `packs` folder); the exit-111/112 dialog (corrupt a file in a copy of the kit).

## UNVERIFIED / open questions
- UNVERIFIED: size and download address of each pack (not in these files); where the kit is published.
