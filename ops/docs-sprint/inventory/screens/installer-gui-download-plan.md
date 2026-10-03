# Installer step: "What CivicCast Needs" (download plan)  (nav id: installer-gui-download-plan, section: Installer)
Source files (under `civiccast/apps/installer/`): `src/AcquisitionFlow.tsx:339-529,1053-1163`, `src/acquisition-progress.ts`, `src/components-catalog.ts`, `src-tauri/src/main.rs`
Who can open it: same as `installer-gui-checking-computer.md` (second screen of the first-run flow).

## What it is for
Lists the large components CivicCast runs on, with size and purpose, lets the operator untick the two optional ones, and shows the total. It is the last screen before downloads start.

## What the user sees (top to bottom)
1. Heading "What CivicCast Needs"; lead: "These are the large pieces CivicCast runs on. Anything already on this computer or on your USB kit is used as-is and is not downloaded again; only what is missing comes from the internet." (`:392-396`).
2. List `aria-label="Components to download"`: one row per catalog component (7 rows, see `installer-component-catalog.md`). Each row: a pill or checkbox, bold name, one-sentence purpose, optional explanation line, size (and a time only after a speed has been measured).
3. Red "Not enough free disk space" box when the selected total exceeds free space, with the disk message (`:436-440`), or an unreadable-disk note.
4. Footer (always visible): "`<total>` total", a time line, "Interrupted downloads keep their progress and can be resumed.", and "Continue" (`:449-468`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Pill "Included" (title "Always included") | none | none | none | for required, downloadable rows (`:509-513`) |
| Pill "Not included" (title "Not available in this release") | none | none | none | for the "Video and audio tools" row (`:498-501`) |
| Checkbox, aria-label "Include Caption engine — Large (optional)" | adds/removes the large caption engine from the selection | changes only what the screen tracks (see finding HELP-52) | none | pre-ticked when this card qualifies |
| Checkbox, aria-label "Include GPU caption acceleration (optional)" | same for the GPU library | same | none | pre-ticked under the same condition |
| Continue | freezes the selection and goes to "Downloading" | the Downloading screen then calls `start_acquisition` (`:585`) | none | disabled when disk is blocked (`:465`) |

## Explanation lines under the optional rows (derived, `acquisition-progress.ts:517-614`)
- Large, pre-selected: "Selected for this station — 3.1 GB. This station's graphics card can run it live, while the meeting is happening. Untick it to skip the download; CivicCast still captions with the standard engine, and you can add this one later at any time."
- Large, not pre-selected: "Optional, and off unless you choose it — 3.1 GB. It is too slow for live captioning on this station, so it captions recordings after the meeting instead. If you skip it, CivicCast still captions live meetings and recordings with the standard engine; you can add this one later at any time."
- If the card could not be read: "...CivicCast could not check whether this station can run it during a meeting."
- GPU acceleration, pre-selected: "Selected for this station — 1.3 GB. This station's graphics card can run the caption engine. Untick it to skip the download; CivicCast still runs captions on this computer's processor, and you can add this one later at any time."
- GPU acceleration, off: "Optional, and off unless you choose it — 1.3 GB. If you skip it, CivicCast still runs captions on this computer's processor; you can add this one later at any time."
- "Video and audio tools": "Installed with the signed CivicCast setup; no separate download is needed." (`components-catalog.ts:100-101`).

## Totals
Total = sum of catalog placeholder sizes of ticked rows (`planTotals`, `acquisition-progress.ts:394-397`). Default (no optional ticks) = 482 MB + 94 MB + 1.5 GB + 7.6 GB, shown as "9.7 GB total"; with both optional rows ticked about "14.1 GB total" (arithmetic from `components-catalog.ts`, formatBytes at `acquisition-progress.ts:333-349`). Time line: "Time remaining is estimated once the download starts." (always, because no speed command is registered, `api.ts:818-840`).

## States
Probe failed: the row explanations assume no graphics knowledge; the plan still shows with the four required rows selected (`:1070-1077`). Disk unreadable: a plain line "CivicCast could not check free disk space on this computer. Setup needs about X.X GB." and Continue stays enabled.

## Typical task flows
1. Accept the default: press Continue.
2. Untick Large (and GPU) to save about 4.4 GB; press Continue.

## Related settings / env / CLI / API
`CIVICCAST_COMPONENTS_BASE_URL`, `CIVICCAST_OLLAMA_REGISTRY_BASE_URL` (download sources, `acquisition_catalog.rs:216-272`).

## Help-text findings
- [HELP-50] `AcquisitionFlow.tsx:394-395` "Anything already on this computer or on your USB kit is used as-is" — the elevated setup that ran just before this screen already required the kit, and (per `nsis-hooks-bootstrap.nsh:1441-1445,2184-2209`) cannot finish without the station model packs. A resident or clerk reads "only what is missing comes from the internet" as "setup.exe alone works". Needs an owner/coder check before the manual promises either path (see `installer-nsis-packs-and-verify.md`).
- [HELP-51] The row "Local AI model (summaries & translation)" shows 7.6 GB, but the product also needs two more model packs (gemma4:e4b and translategemma:4b) and an Ollama runtime that are not listed anywhere on this screen (`native_activation.rs:35-41`, `native_pack_staging.rs:99-104`). The "9.7 GB" total is not the whole model footprint (the uninstall notice says "about 21 GB", `nsis-hooks-bootstrap.nsh:2209`).
- [HELP-52] SERIOUS: "Untick it to skip the download" (`acquisition-progress.ts:538-540`) may not be true. `start_acquisition` takes no arguments and `production_catalog` returns all six ids, so the backend downloads the large engine and GPU library even when unticked, and the sequential order puts them before the local AI model (`main.rs:3304-3324,3740-3747`; `acquisition_catalog.rs:555-600,681-688`). The screen only hides those rows. Marked UNVERIFIED at runtime; needs a real-box test.
- [HELP-53] "Database & messaging services" (`components-catalog.ts:69`) still says "messaging", but the messaging server (NATS) was removed from the product (`install_layout.py:19-21`; `main.rs:5512-5515`). Suggest "Database service".
- [HELP-54] "CivicCast application runtime" and "Database & messaging services" are described as downloads but are staged by setup first; the screen does not say they will normally show "Found locally — verified".
- [HELP-55] "(optional)" rows give sizes in GB only; no mention that downloads use the internet connection continuously for a long time (7.6 GB model).

## Screenshot plan
Default plan on a capable NVIDIA box (both optional rows ticked); same on CPU-only (both unticked, "Optional, and off..." text); low-disk red banner; probe-failed state.

## UNVERIFIED / open questions
- UNVERIFIED: whether unticking really leaves Large/GPU undownloaded (HELP-52).
- UNVERIFIED: real sizes: the screen shows catalog placeholders; the code comment says measured sizes arrive later (`components-catalog.ts:4-13`) and the total changes once (see downloading screen).
