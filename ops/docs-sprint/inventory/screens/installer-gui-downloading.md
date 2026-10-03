# Installer step: "Downloading" (or "Setting Up")  (nav id: installer-gui-downloading, section: Installer)
Source files (under `civiccast/apps/installer/`): `src/AcquisitionFlow.tsx:531-1047`, `src/acquisition-progress.ts`, `src/api.ts:842-946`, `src-tauri/src/main.rs:3014-3800`, `src-tauri/src/component_acquisition.rs`, `src-tauri/src/acquisition_catalog.rs`
Who can open it: third screen of the first-run flow; also reachable later from the wizard's "More options" > "Download AI models and captions" (`src/App.tsx:803-805`).

## What it is for
Downloads and checks every component that is not already on the computer, shows overall and per-component progress, and lets the operator stop and resume. Components already staged by setup or the USB kit are verified and marked "Found locally — verified".

## What the user sees (top to bottom)
1. Heading "Downloading" (or "Setting Up" when every row is satisfied locally); lead "Keep CivicCast Installer open. If a download is interrupted, use Resume download." (or "Everything CivicCast needs was found on this computer or your USB kit — nothing is being downloaded. Keep this window open while it finishes.") (`:764-769`).
2. Red alert bar when something is wrong (see States).
3. Overall progress: "X of Y" (e.g. "1.2 GB of 9.7 GB"), "Time left: Estimating…" / "N min left" / "Done", progress bar, and a note when the total is corrected (`:783-802`).
4. Scrollable list `aria-label="Component downloads"`, one row per ticked component.
5. Bottom bar: status message, "Stop downloading" (only while something is in flight), "Open installer log" (until all done) (`:871-927`).
When every row is done the screen marks the flow complete and moves to the setup wizard (`:700-705`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Stop downloading | stops all downloads | `cancel_acquisition`: sets a cancel flag checked at each 64 KiB buffer, marks unfinished rows canceled (`main.rs:3761-3767`) | none | message "CivicCast stopped downloading. Nothing already downloaded was lost." |
| Resume download (stopped or resumable-error row) / Retry download (restart-needed row) | re-runs that one component | `retry_acquisition_component` (`main.rs:3769-3795`): clears the cancel flag, re-runs the component, and returns only when it has finished | none | resumes from the `.partial` file with an HTTP Range request when the server allows |
| Open installer log | opens the newest log in Notepad or the default `.log` handler | `open_installer_log` (`main.rs:2953-2975`) | none | tries `C:\ProgramData\CivicCast\install-progress.log` and `%USERPROFILE%\.civiccast\runtime-host.log` |
| "What is this?" (details, current row only) | shows the component's purpose | none | none | |

## Row states (exact text)
| State | Text |
|---|---|
| Waiting | "Waiting" / "Not started yet" |
| Downloading | "Downloading", then "N MB/s — T left" or "Measuring speed"; "X of Y" |
| Stalled (no new byte for more than 10 s) | "Stalled — retrying" (`acquisition-progress.ts:224-227`) |
| Verifying | "Verifying" |
| Done, from disk | "Found locally — verified ✓" |
| Done, downloaded | "Verified ✓ — checked against its signature" |
| Stopped by operator | "Stopped. X of Y is already downloaded and kept." + button "Resume download" |
| Failed | one line from the table below + "Resume download" or "Retry download" |

## Failure lines (`acquisition-progress.ts:144-205`)
| Cause | Line shown | Button |
|---|---|---|
| network_failed | "The connection dropped. Nothing is damaged." | Resume download |
| hash_mismatch | "The downloaded file didn't match its signature and was discarded." | Retry download |
| source_not_found | "The download server didn't have this file. This is our problem, not yours." | Retry download |
| resume_invalid | "The paused download couldn't pick up where it left off, so this file will start over. This is our problem, not yours." | Retry download |
| disk_full | "This drive doesn't have enough free space to finish this download. Free up some space, then choose Retry." | Retry download |
| permission_denied | "Windows wouldn't let CivicCast save this file. Security software blocking the CivicCast folder is the usual cause; allow CivicCast in it, or start CivicCast with 'Run as administrator' once, then choose Retry." | Retry download |
| write_failed | "This file couldn't be saved to disk. The download folder may be unavailable or read-only. Check that the drive is connected and writable, then choose Retry." | Retry download |
| anything else / no reason | "This download stopped and CivicCast did not get a reason it can explain. Nothing on this computer is damaged. Choose Retry; if it stops again, use Open installer log and send that log to support." | Retry download |

## Alert bar texts
- Start refused: "CivicCast could not start downloading its components. Nothing is being downloaded right now. Use Open installer log below and send that log to support." (`api.ts:869-871`).
- Stop refused: "CivicCast could not stop the download. It is still running. Close this window to stop it; anything already downloaded is kept and setup will pick up where it left off." (`api.ts:898-900`).
- Nothing moved for 30 s with every row waiting: "No files have started downloading yet. CivicCast is still waiting for the first byte. If this does not change, use Open installer log below and send that log to support." (`:756-757`; threshold `acquisition-progress.ts:239`).
- Log could not be opened: "No CivicCast installer log exists yet. Checked: `<paths>`." (`main.rs:138-141`).

## What "Found locally — verified" means (code)
Set when every item of a component already verifies on disk with no network and no bytes streamed (`main.rs:3167-3173,3296-3302,3362-3371`). A signed pack item is checked at both candidate paths, `C:\ProgramData\CivicCast\packs\<component>.ccpack` and `<install dir>\packs\<component>.ccpack`, with the pack's ed25519 signature and the component/version identity (`main.rs:3209-3230`). A file item (caption weights, AI model blobs) must match its pinned byte size and SHA-256 at the download folder or at the install-dir copies (`component_acquisition.rs:973-989`). It is recorded for all satisfied rows up front, before the sequential downloads start (`main.rs:3362-3371`).

## Download behavior as implemented
- Order, one at a time: app_runtime, server_binaries, captions_medium, captions_large, cuda_runtime, local_ai_model (`acquisition_catalog.rs:681-688`; `main.rs:3558-3579`). All six always run (HELP-52 in the plan file).
- Network: HTTPS only (non-HTTPS redirects refused), connect timeout 30 s, whole-transfer timeout 6 hours, `.partial` file plus Range resume (`component_acquisition.rs:506,537-545`). No automatic retry loop was found in that file (search for "retry/attempt" found only test code).
- Sources: signed packs from GitHub Releases `scottconverse/civiccast-releases` tag `native-beta-1.0.0-beta.1-rc1`; caption weights from huggingface.co at a pinned revision; AI model from registry.ollama.ai (`acquisition_catalog.rs:216-259`; `component_acquisition.rs:183`).
- Destination: `C:\ProgramData\CivicCast\...` (writable without admin) (`main.rs:3604-3641`).
- Progress shown to the screen through `%USERPROFILE%\.civiccast\installer-state.json`, polled every 500 ms while anything downloads, else every 2 s (`acquisition-progress.ts:128-131`).
- Total corrects once: starts at the catalog total, and when every file's real size is known becomes the real total with the note "Total updated to X. The download was announced as Y from the published sizes; every file's real size is now known. This figure does not change again during this download." (`acquisition-progress.ts:306-327`).
- Closing the window ends the process immediately (`main.rs:6459-6463`), keeping partial files.

## Typical task flows
1. Watch to "Done"; the wizard opens.
2. Metered link: press "Stop downloading", later reopen and use Resume download.
3. Row failed: read the line, fix the cause, press Retry/Resume.

## Help-text findings
- [HELP-56] SERIOUS: `acquisition-progress.ts:224-227` and `AcquisitionFlow.tsx:1015` show "Stalled — retrying" but no retry exists in the download engine (no loop, 6-hour timeout), so the row can sit forever; the only real remedy is "Stop downloading" then "Resume download". Suggest "No data for 10 seconds. If this continues, choose Stop downloading, then Resume download."
- [HELP-57] "Open installer log" opens `install-progress.log` (the elevated setup transcript) first; a download failure's cause is not written there. The text "send that log to support" therefore points at a file that probably does not contain the failure (no GUI download log writer was found in `main.rs`; the engine detail is kept only in `installer-state.json`). Missing: where the GUI's own failure details are kept (`detail` field is "never shown", `types.ts:139`).
- [HELP-58] "Keep CivicCast Installer open" (`:768`) — the window is titled "CivicCast (Native) Setup" (`tauri.native.conf.json`); name mismatch.
- [HELP-59] "This is our problem, not yours." (source_not_found / resume_invalid) offers only Retry, but a missing file at the release tag cannot be fixed by retry; no contact route is given.
- [HELP-60] Default download source tag `native-beta-1.0.0-beta.1-rc1` is not the product version `1.0.0-beta.10` (`main.rs:35`); packs are verified against the current version (`acquisition_catalog.rs:327-338`), so a fresh download of the optional GPU pack may fail with "didn't match its signature". UNVERIFIED which assets exist at that tag.
- [HELP-61] Times, speeds use "MB/s" without explanation; "Estimating…" has no end condition stated.

## Screenshot plan
All rows "Found locally — verified ✓" on a kit install ("Setting Up" heading); a real download in progress; a stopped row with Resume; each failure line (unplug network for network_failed, fill the disk for disk_full); the 30-second alert.

## UNVERIFIED / open questions
- UNVERIFIED: whether Stop leaves an unticked-but-still-downloading component running (HELP-52).
- UNVERIFIED: what extracts a downloaded `.ccpack` after the GUI verifies it (no extraction call in `AcquisitionFlow`/`main.rs` acquisition path).
