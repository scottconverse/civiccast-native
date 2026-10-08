> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Component catalog: what each piece is called on screen and on disk (reference; no screen of its own)

Paths relative to `civiccast/apps/installer/`. CC = `src/components-catalog.ts`; AC = `src-tauri/src/acquisition_catalog.rs`; PS = `src-tauri/src/native_pack_staging.rs`; NA = `src-tauri/src/native_activation.rs`; AF = `src/AcquisitionFlow.tsx`; AP = `src/acquisition-progress.ts`; Hooks = `src-tauri/nsis-hooks-bootstrap.nsh`.

## Where the text lives now
On-screen names, purposes and sizes: CC:57-161 (shown on "What CivicCast Needs" and "Downloading"). Which items can download: AC:681-688. Which packs Windows setup requires: PS:99-154. Which model packs activation requires: NA:37-48. Which caption engine is recommended: `src-tauri/src/hardware_inventory.rs:180-194`. File names in the kit: manual ch. 10 (full-kit listing). Nothing on screen translates the plain names into the file names a support person sees in logs.

## Current text
Three lists exist and use different names for the same pieces.
| On-screen name (first-run window) | Id in the window | File or id in setup and logs | Source line |
| --- | --- | --- | --- |
| "CivicCast application runtime" (482 MB) | `app_runtime` | `native-app-payload.ccpack` | CC:60-63; PS:111 |
| "Database & messaging services" (94 MB) | `server_binaries` | `native-server-binaries.ccpack` | CC:68-72; PS:99 |
| "Video and audio tools" (137 MB; pill "Not included") | `media_tools` | `native-ffmpeg-runtime.ccpack` | CC:77-85; PS:119 |
| "Caption engine — Medium (recommended)" (1.5 GB) | `captions_medium` | station pack `captions-floor` | CC:104-107; NA:39 |
| "Caption engine — Large (optional)" (3.1 GB) | `captions_large` | station pack `captions-large-v3` | CC:112-115; NA:48 |
| "GPU caption acceleration (optional)" (1.3 GB) | `cuda_runtime` | `native-cuda-runtime.ccpack` | CC:132-136; PS:140 |
| "Local AI model (summaries & translation)" (7.6 GB) | `local_ai_model` | station pack `summary-gemma4-12b` (also `summary-gemma4-e4b`, `translation-translategemma-4b`) | CC:153-157; NA:40-42 |
| (no row) AI engine | none | `native-ollama-runtime.ccpack` (Ollama 0.30.6) | PS:124 |
| (no row) station index placeholder | none | `core` (about 1.5 KB; not extracted) | NA:38; Hooks:1427-1431 |
Strings: the pills "Included" (title "Always included") and "Not included" (title "Not available in this release") (AF:499-512); row purposes and the optional-row explanations are quoted in `installer-gui-download-plan`.

## What really happens
Layer 1: Windows setup extracts four required signed packs (server tools, application, video tools, AI engine) and the optional GPU pack from the kit's `packs` folder into the install folder (PS:99-154). Layer 2: setup's activation step extracts the station packs from the kit's `station` folder: Medium captions, three AI models, and Large captions if present; the three AI models are merged into one store; the whole set is self-tested (`native_activation.rs:882-972`). Layer 3: the first-run window's catalog lists six downloadable items, checks each against what layers 1 and 2 left on disk and downloads only what is missing, one at a time (AC:681-688; `main.rs:3304-3339`). Medium is always installed; Large is an add-on and is pre-ticked only when an NVIDIA card with 8 GB or more of video memory is found (`hardware_inventory.rs:180-194`; NA:37-48). The sizes on screen are fixed placeholder figures (CC:4-13), not measured; the "about 21 GB" in the uninstall notice is the size of the model packs kept in the install folder.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-69 | Plain names on screen, file names in logs | A support person reading `native-app-payload.ccpack` in a log cannot map it to a row; no table exists in the product | Moderate |
| HELP-70 (same as HELP-53) | "Database & messaging services" | Messaging was removed; only the database is installed | Low |
| HELP-71 | Sizes read as facts | Fixed placeholders; the first total shown can change once, with a note, when real sizes are known (AP:306-327) | Moderate |
| HELP-72 (same as HELP-51) | One row "Local AI model" | The station needs three models (gemma4:12b, gemma4:e4b, translategemma:4b); only the first has a row | Moderate |
| NEW-1 | "Video and audio tools" shown with pill "Not included" | The tools are installed by Windows setup; the pill means "not downloaded here", which reads as "missing" | Low |
| NEW-2 | "GPU caption acceleration: Lets the caption engine run on this computer's graphics card" | The pack holds NVIDIA libraries (cuBLAS and cuDNN, PS:126-140); it helps only an NVIDIA card. The row is tickable on any computer | Low |

## Proposed text
In-app help table (now), "What each piece is":
| Name on screen | File in the kit or logs | What it does | Where it goes | Needed? |
| --- | --- | --- | --- | --- |
| CivicCast application runtime | `packs\native-app-payload.ccpack` | The CivicCast program: the operator console, resident portal and meeting tools | `<install folder>\runtime` | Yes |
| Database service | `packs\native-server-binaries.ccpack` | The PostgreSQL database tools that store meetings | `<install folder>\packs\native-server-binaries\payload` | Yes |
| Video and audio tools | `packs\native-ffmpeg-runtime.ccpack` | ffmpeg: records, builds and checks video files | `<install folder>\dependencies\ffmpeg\bin` | Yes (installed by Windows setup) |
| (not a row) AI engine | `packs\native-ollama-runtime.ccpack` | Ollama 0.30.6, runs the AI models on this computer | `<install folder>\dependencies\ollama` | Yes |
| Caption engine — Medium | `station\` pack `captions-floor` | Live captions on the processor | `<install folder>\packs\captions-floor` | Yes |
| Caption engine — Large | `station\` pack `captions-large-v3` | More accurate captions; live on a capable NVIDIA card, otherwise for recordings | `<install folder>\components\captions-large-v3` | No |
| GPU caption acceleration | `packs\native-cuda-runtime.ccpack` | NVIDIA libraries that let captions run on an NVIDIA graphics card | `<install folder>\dependencies\cuda` | No (NVIDIA only) |
| Local AI models | `station\` packs `summary-gemma4-12b`, `summary-gemma4-e4b`, `translation-translategemma-4b` | Summaries and translation on this computer; merged into one store | `<install folder>\components\<name>`, merged into `<install folder>\models\ollama` | Yes |
Sizes: quote the on-screen figures only as "about" and say they are catalog figures: application 482 MB, database tools 94 MB, video tools 137 MB, Medium 1.5 GB, Large 3.1 GB, GPU 1.3 GB, AI model 7.6 GB (the largest of three). The model packs in the kit add up to about 21 GB (uninstall notice, Hooks:2209). The real sizes of the other packs are UNVERIFIED.

On-screen replacements (now): row names "Database service" and "Local AI models (summaries & translation)" with the extra sentence in `installer-gui-download-plan`; pill on the video tools row: "Installed by setup"; GPU row purpose: "For computers with an NVIDIA graphics card. Lets the caption engine run on the graphics card instead of the processor, so it can caption more meetings live."

After fix: when real sizes come from the signed index, drop the word "about" and show each file's measured size.

## Notes for the coder
- Edit CC:69, 71, 79-80, 135, 154-156 (names and purposes) and AF:499-512 (pills). Tests: `tests/policy/test_hardware_inventory_policy.py` pins the component ids against `acquisition_catalog.rs` (`PRODUCTION_CATALOG_IDS`), not the names; `src/optional-download-default.test.ts` pins that the optional-row explanations contain the catalog size and "Not available to download in this release". No test pins "Database & messaging services".
- Needs a code fix, not text: replace the placeholder sizes with measured ones; add rows (or one combined row) for the two other AI models; pass the ticked rows into the download driver (HELP-52, see `installer-gui-download-plan`).
- UNVERIFIED: real byte sizes of each pack and of gemma4:e4b and translategemma:4b; that every asset exists at the download tag (HELP-60).
