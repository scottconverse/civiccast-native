# Installer component catalog (names, sizes, purpose, where each lands)  (nav id: installer-component-catalog, section: Installer)
Source files (under `civiccast/apps/installer/`): `src/components-catalog.ts`, `src-tauri/src/acquisition_catalog.rs`, `src-tauri/src/native_pack_staging.rs:99-154`, `src-tauri/src/native_activation.rs:35-60`, `src-tauri/src/hardware_inventory.rs`
Who can open it: reference for the "What CivicCast Needs" and "Downloading" screens. No UI of its own.

## What it is for
CivicCast is installed in two layers. The elevated Windows setup extracts signed ".ccpack" files from the kit folder (runtime, database tools, video tools, AI engine, caption and AI models). Afterwards the first-run wizard checks a second, shorter list (this catalog) and downloads anything missing. This file lists both lists so the manual can name every piece.

## A. The first-run wizard catalog (7 rows on screen, `components-catalog.ts:57-161`)
Sizes are the catalog placeholders shown on screen (`formatBytes`: 1 decimal GB, whole MB). Real sizes replace them once known.
| Screen name | Id | Size shown | Shipping state | Purpose text on screen | Source (when it must download) | Lands in |
|---|---|---|---|---|---|---|
| CivicCast application runtime | app_runtime | 482 MB | Included, downloadable | "The CivicCast program itself: the dashboard and meeting tools staff use every day." | GitHub release asset `native-app-payload.ccpack` | `C:\ProgramData\CivicCast\packs\native-app-payload.ccpack`; already-staged copy `<install dir>\packs\...` counts as found |
| Database & messaging services | server_binaries | 94 MB | Included, downloadable | "The local services CivicCast runs on this computer to store meetings and pass information between its parts." | `native-server-binaries.ccpack` | same folder |
| Video and audio tools | media_tools | 137 MB (143,477,803 bytes) | "Not included" pill | "The tools CivicCast uses to record a meeting, build the video file it publishes, and check that the file came out right." Note: "Installed with the signed CivicCast setup; no separate download is needed." | not downloaded (not in `production_catalog`) | `<install dir>\dependencies\ffmpeg` by setup |
| Caption engine — Medium (recommended) | captions_medium | 1.5 GB | Included, downloadable | "Live captions for meetings as they happen. This is the standard engine and always installs." | huggingface.co, faster-whisper-medium at a pinned revision, 4 files each with pinned size and SHA-256 | `C:\ProgramData\CivicCast\packs\captions-floor\` |
| Caption engine — Large (optional) | captions_large | 3.1 GB | Optional checkbox; pre-ticked on NVIDIA >= 8 GB | "A higher-quality caption engine. On a capable graphics card it captions live; otherwise it captions recordings after the meeting." | huggingface.co, large-v3, 6 pinned files | `C:\ProgramData\CivicCast\components\captions-large-v3\` |
| GPU caption acceleration (optional) | cuda_runtime | 1.3 GB | Optional checkbox; pre-ticked with Large | "Lets the caption engine run on this computer's graphics card instead of its processor, so it can caption more meetings live." | `native-cuda-runtime.ccpack` (cuBLAS + cuDNN) | `packs\native-cuda-runtime.ccpack`; extracted to `dependencies\cuda` by setup when present |
| Local AI model (summaries & translation) | local_ai_model | 7.6 GB | Included, downloadable | "Generates meeting summaries and translations on this computer, without sending recordings anywhere else." | registry.ollama.ai, model gemma4:12b (manifest plus content-addressed blobs) | `C:\ProgramData\CivicCast\packs\local-ai-model\models\`; also counted as present when found in `<install dir>\models\ollama` |
Totals: default 9.7 GB; with both optional rows 14.1 GB (calculated from the sizes above).
Row labels on screen use the name column. Pills: "Included" (title "Always included"), "Not included" (title "Not available in this release").

## B. What the elevated setup requires beyond the wizard catalog
(from the kit; none of these appear as rows on the plan screen)
| Component id (pack) | What it holds | Where setup puts it | Required? |
|---|---|---|---|
| native-server-binaries | PostgreSQL tools (postgres, pg_ctl, initdb), optional TSDuck | `<install dir>\packs\native-server-binaries\payload\` | required (`native_pack_staging.rs:99-104`) |
| native-app-payload | embedded Python 3.12, the CivicCast program, both web portals | `<install dir>\runtime\` | required |
| native-ffmpeg-runtime | ffmpeg and ffprobe | `<install dir>\dependencies\ffmpeg\bin\` | required |
| native-ollama-runtime | Ollama 0.30.6 AI engine | `<install dir>\dependencies\ollama\ollama.exe` | required |
| native-cuda-runtime | GPU libraries | `<install dir>\dependencies\cuda` | optional |
| core | placeholder notice (about 1.5 KB) | not extracted | station index entry |
| captions-floor | Whisper medium weights and test audio | `<install dir>\packs\captions-floor\` | required by activation |
| summary-gemma4-12b, summary-gemma4-e4b, translation-translategemma-4b | AI model files, merged into one store | `<install dir>\components\<id>\` then merged to `<install dir>\models\ollama\` | required by activation (`native_activation.rs:35-41`) |
| captions-large-v3 | large Whisper | `<install dir>\components\captions-large-v3\` | optional |
The uninstall notice describes the packs as "about 21 GB" (`nsis-hooks-bootstrap.nsh:2209`).

## C. Caption engine choice logic
Recommended tier is "floor" (Medium) unless an NVIDIA card with at least 8 GB VRAM is found, then "large-v3" (`hardware_inventory.rs:187-241`). Large is only ever pre-selected when the component can be downloaded in this release (it can; `acquisition_catalog.rs:681-688`). The product always installs Medium; Large is an add-on (`native_activation.rs:26-34`).

## Help-text findings
- [HELP-69] Plain-English names differ from the files a support person sees (`native-app-payload.ccpack`, etc.); the manual needs one translation table (this file).
- [HELP-70] The "Database & messaging services" name is stale (see HELP-53).
- [HELP-71] The wizard names two sizes as measured "from the manifests" (`components-catalog.ts:7-13`) but they are fixed placeholders; the first total shown can change once.
- [HELP-72] "Local AI model (summaries & translation)" is one row but the station needs three models (gemma4:12b, gemma4:e4b, translategemma:4b); only the first is on the screen.

## Screenshot plan
The plan screen on a capable box and on a CPU-only box (see `installer-gui-download-plan.md`).

## UNVERIFIED / open questions
- UNVERIFIED: real byte sizes of each pack and of the e4b and translategemma models (not in the files read).
- UNVERIFIED: that `components_base_url` assets exist for each pack (HELP-60).
