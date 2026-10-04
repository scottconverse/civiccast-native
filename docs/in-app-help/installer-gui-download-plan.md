# What CivicCast Needs (Tauri window "CivicCast (Native) Setup", first-run screen 2)

Paths relative to `civiccast/apps/installer/`. AF = `src/AcquisitionFlow.tsx`; AP = `src/acquisition-progress.ts`; CC = `src/components-catalog.ts`.

## Where the text lives now
Screen: AF:341-529. Row names, purposes and sizes: CC:57-161. Explanations under the two optional rows: AP:502-614. Totals and the disk check: AP:383-444; the time line: AF:458-462. The download itself starts on the next screen (AF:585; `src-tauri/src/main.rs:3740-3747`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "What CivicCast Needs" | Heading | AF:392 |
| "These are the large pieces CivicCast runs on. Anything already on this computer or on your USB kit is used as-is and is not downloaded again; only what is missing comes from the internet." | Lead | AF:394-395 |
| "CivicCast application runtime" / "The CivicCast program itself: the dashboard and meeting tools staff use every day." / 482 MB | Row 1 | CC:60-63 |
| "Database & messaging services" / "The local services CivicCast runs on this computer to store meetings and pass information between its parts." / 94 MB | Row 2 | CC:69-72 |
| "Video and audio tools" / "The tools CivicCast uses to record a meeting, build the video file it publishes, and check that the file came out right." / 137 MB; pill "Not included" (title "Not available in this release"); note "Installed with the signed CivicCast setup; no separate download is needed." | Row 3 | CC:78-85, 101; AF:499-501 |
| "Caption engine — Medium (recommended)" / "Live captions for meetings as they happen. This is the standard engine and always installs." / 1.5 GB | Row 4 | CC:105-107 |
| "Caption engine — Large (optional)" / "A higher-quality caption engine. On a capable graphics card it captions live; otherwise it captions recordings after the meeting." / 3.1 GB | Row 5 (checkbox, label "Include Caption engine — Large (optional)") | CC:113-115; AF:506 |
| "GPU caption acceleration (optional)" / "Lets the caption engine run on this computer's graphics card instead of its processor, so it can caption more meetings live." / 1.3 GB | Row 6 (checkbox) | CC:133-136 |
| "Local AI model (summaries & translation)" / "Generates meeting summaries and translations on this computer, without sending recordings anywhere else." / 7.6 GB | Row 7 | CC:154-157 |
| Pill "Included" (title "Always included") | Rows 1, 2, 4, 7 | AF:510-512 |
| "Selected for this station — 3.1 GB. This station's graphics card can run it live, while the meeting is happening. Untick it to skip the download; CivicCast still captions with the standard engine, and you can add this one later at any time." | Under Large, capable card | AP:537-541, 507-509 |
| "Optional, and off unless you choose it — 3.1 GB. It is too slow for live captioning on this station, so it captions recordings after the meeting instead. If you skip it, CivicCast still captions live meetings and recordings with the standard engine; you can add this one later at any time." | Under Large, not selected | AP:544-546, 509 |
| "Selected for this station — 1.3 GB. This station's graphics card can run the caption engine. Untick it to skip the download; CivicCast still runs captions on this computer's processor, and you can add this one later at any time." | Under GPU row, capable card | AP:605-608 |
| "Optional, and off unless you choose it — 1.3 GB. If you skip it, CivicCast still runs captions on this computer's processor; you can add this one later at any time." | Under GPU row, not selected | AP:611-612 |
| "<total> total" / "Time remaining is estimated once the download starts." / "Interrupted downloads keep their progress and can be resumed." / **Continue** | Footer | AF:452, 459-464, 466 |
| "Not enough free disk space" + AP:442 sentence | Red box; disables **Continue** | AF:438; AF:465 |

## What really happens
The screen lists seven fixed catalog rows with fixed placeholder sizes; the total is the sum of the ticked ones (9.7 GB by default, about 14.1 GB with Large and GPU; AP:394-397; CC:63-157). On a first install from the kit, Windows setup has already installed the application, database tools, video tools and AI engine and extracted the speech and AI models (manual ch. 10), so most rows later show "Found locally — verified". The checkboxes change only what the next screen displays: `start_acquisition` takes no arguments and runs all six downloadable components in a fixed order (application, database tools, Medium, Large, GPU, AI model), downloading any that is not already on disk (`main.rs:3304-3324, 3740-3747`; `acquisition_catalog.rs:681-688`). Missing items come from GitHub Releases (`scottconverse/civiccast-releases`, tag `native-beta-1.0.0-beta.1-rc1`), huggingface.co and registry.ollama.ai (`acquisition_catalog.rs:221`, `component_acquisition.rs:183`). Windows setup itself does not download; see `installer-nsis-setup-wizard`.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-50 | "Anything already on this computer or on your USB kit is used as-is ... only what is missing comes from the internet" | Reads as if `setup.exe` alone works. Windows setup, which runs before this screen, cannot finish without the kit's `packs` and `station` folders (exit 110 or 123) | SERIOUS |
| HELP-51 | Row "Local AI model" 7.6 GB; total "9.7 GB" | The station needs three AI models (gemma4:12b, gemma4:e4b, translategemma:4b) and an AI engine; only the first is a row. The uninstall notice puts the model packs at about 21 GB | Moderate |
| HELP-52 | "Untick it to skip the download" (AP:538-540, 605-607) | Corrected in development source: the actual screen passes selected IDs to native admission; unchecked optional entries never enter the driver. A refused plan cannot complete from old progress. Existing installer artifacts and clean-machine behavior still need verification | Source corrected; shipment unverified |
| HELP-53 | "Database & messaging services" | The messaging server was removed from the product; only the database is installed | Low |
| HELP-54 | Rows 1 and 2 shown as downloads, "Included" | Setup installs both first; they normally show "Found locally" and download nothing | Moderate |
| HELP-55 | Sizes in GB with no time warning | The 7.6 GB model alone, if it must download, can take hours on a slow link (6-hour transfer limit, `component_acquisition.rs:545`) | Moderate |
| NEW-1 | Row 3 pill "Not included" next to "Installed with the signed CivicCast setup" | The pill reads as "CivicCast lacks this" while the note says setup installs it | Low |

## Proposed text
Lead (honest now; replaces AF:394-395): "These are the large pieces CivicCast runs on. Windows setup has already installed most of them from your kit, so they normally show 'Found locally' on the next screen and download nothing. A piece that is still missing is fetched from the internet, which can take a long time on a slow connection. Unticking an optional piece only hides it from the next screen: the download step is not told which pieces you ticked."
After fix (once the selection is passed to the download step): "These are the large pieces CivicCast runs on. Anything already on this computer or in your kit is used as it is. Only what is missing, and that you leave ticked, comes from the internet."

Row names and notes (now): Row 2 "Database service" / "The local database CivicCast runs on this computer to store meetings and information." Row 3 pill "Installed by setup" (title "Installed by Windows setup; not downloaded here"). Row 7 add a second sentence: "CivicCast uses three AI models; this row is the largest (about 7.6 GB). The other two, gemma4:e4b and translategemma:4b, came with the kit and are not listed here." Rows 1 and 2 add "Normally installed by Windows setup already."

Optional rows (honest now). Large, capable card: "Selected for this station — 3.1 GB. This station's graphics card can run it live, while the meeting is happening. If it is not already on this computer it is downloaded, and in this version unticking it may not stop that. Without it CivicCast captions with the standard engine." Large, not selected: keep AP:544-546. GPU, capable card: "Selected for this station — 1.3 GB. This station's graphics card can run the caption engine. If it is not already on this computer it is downloaded, and in this version unticking it may not stop that. Without it CivicCast runs captions on this computer's processor." After fix: restore "Untick it to skip the download".

Footer: "<total> total on this screen. This is not the whole model footprint: the kit's model packs add up to about 21 GB. Time remaining is estimated once the download starts."

## Notes for the coder
- Edit AF:394-395, 499-501, 510-512, 452, 459-464; CC:69-72, 79-80, 101; AP:537-541, 605-608. Tests: `src/optional-download-default.test.ts` (explanations must contain the size from the catalog, and "Not available to download in this release" for undeliverable rows), `src/caption-engine-copy.test.ts` (Large row and banner must never contradict each other), `src/styles.test.ts:26-29` (layout of the "Not included" / "Included" pill). No test pins the lead or the footer sentences.
- Needs a code fix, not text: pass the ticked ids into `start_acquisition` (`main.rs:3740-3747`; the driver in `run_acquisition_components` iterates `PRODUCTION_CATALOG_IDS`); use measured sizes instead of the placeholders (CC:4-13); add rows for the two other AI models or say plainly they ship with the kit (HELP-51); update the download source tag, which is `native-beta-1.0.0-beta.1-rc1`, not 1.0.0-beta.10 (HELP-60, `acquisition_catalog.rs:221`).
- A real-box test is required before shipping any text that says unticking does or does not skip a download (HELP-52).
- No NSIS or language-file changes.

### Selection correction — 2026-10-04

The screen/API/native command now carry one selected plan. Native validation keeps all four required components, rejects unknown or duplicate IDs before admission, and filters optional Large/CUDA before prescan, transfer and retry configuration. Repeating the same plan is a no-op; changing an admitted plan is refused until restart. Retry cannot add an unselected component or clear cancellation for it. Existing verification, offline reuse, transport and Windows setup are unchanged. The historical proposed text above describes the earlier defect; use the corrected Chapter 10 selection instructions for this source. This is not a clean-machine or shipped-installer claim.
