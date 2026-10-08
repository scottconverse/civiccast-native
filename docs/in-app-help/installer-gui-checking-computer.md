> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Checking This Computer (Tauri window "CivicCast (Native) Setup", first-run screen 1)

Paths relative to `civiccast/apps/installer/`. AF = `src/AcquisitionFlow.tsx`; AP = `src/acquisition-progress.ts`; API = `src/api.ts`; HW = `src-tauri/src/hardware_inventory.rs`.

## Where the text lives now
Screen and facts: AF:196-333. Probe messages: API:793-801. Recommendation and disk-space wording: AP:430-442, 638-677. Window title: `src-tauri/tauri.native.conf.json:10`. The screen is skipped once the browser-storage flag `civiccast.acquisitionFlowComplete` is "1" (AF:56-72; `src/App.tsx:315-317`); "More options, Download AI models and captions" clears it (`App.tsx:618-622`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Checking This Computer" / "CivicCast is looking at this computer's hardware so it can recommend the right setup." / "This usually takes a few seconds." | While probing (at least 0.65 s, AF:1063-1065) | AF:201, 202, 218 |
| "Here is what CivicCast found on this computer." | Heading lead once the probe answered | AF:269 |
| "Processor" / "Memory" / "Graphics" / "Free disk space on <install target>" (or "Free disk space") | Facts panel | AF:286, 291, 294, 298 |
| "<CPU name> (N cores)"; "N GB"; "<card> (N GB), ..."; "No dedicated graphics card"; "Unavailable" | Fact values | AF:122, 165, 167, 177, 291, 300 |
| "CivicCast could not read this computer's hardware." / banner "Hardware check unavailable" / "CivicCast could not check this computer's hardware. It will not guess: nothing about this computer is shown below, and the free-space check could not be made. Setup can continue, but if a download later runs out of room, free up space and choose Retry." | Probe failed | AF:232, 247; API:793-796 |
| "CivicCast could not check this computer's hardware in this preview. No real hardware readings are available here." | Browser preview only | API:799-801 |
| "CivicCast could not check this computer's graphics card, so it is installing the standard caption engine (Medium), which runs in real time on any supported CPU." | Recommendation, graphics unreadable | AP:644-646 |
| "This station's graphics card can run the higher-quality caption engine live, and CivicCast has selected it. You can uncheck it on the next screen." | Capable NVIDIA card (the normal case for it) | AP:659-661 |
| "This station's graphics card can run the higher-quality caption engine live. CivicCast installs the standard caption engine (Medium); the next screen offers the higher-quality one as an extra download." | Capable, not selected | AP:664-666 |
| "This station's graphics card could run the higher-quality caption engine live, but that engine is not available to download in this release. ..." | Capable, engine not offered (not the shipping state) | AP:652-654 |
| "This station has no dedicated graphics card. We recommend the standard caption engine (Medium), which runs in real time on this CPU." | No dedicated card | AP:671 |
| "This station's graphics card is not one CivicCast can run the higher-quality caption engine on. We recommend the standard caption engine (Medium), which runs in real time here." | AMD, Intel or small NVIDIA card | AP:674-675 |
| "Not enough free disk space" / "This drive doesn't have enough free space: needs X.X GB free, this drive has Y.Y GB." / "Free up space on this drive, then reopen CivicCast Installer." | Red box; hides **Continue** | AF:311-313; AP:442 |
| "CivicCast could not check free disk space on this computer. Setup needs about X.X GB." | Plain note; does not block | AP:430-432 |
| **Continue** | Button | AF:253, 326 |

## What really happens
This is the first screen of the window that opens after Windows setup. It reads the processor name, memory, graphics cards (Windows DXGI list, software adapters and exact duplicates removed) and the free space on the drive that holds `%ProgramFiles%` (HW:506-510, 530-538; AF:142-154). Any value it cannot read is shown as "Unavailable", never as a number. Only an NVIDIA card (vendor 0x10DE) with 8 GB or more of video memory counts for the higher-quality (Large) caption engine; AMD and Intel cards are listed but never raise it (HW:133, 180-194). Free space is compared with the catalog's placeholder download sizes for the default selection (9.7 GB, or about 14.1 GB with the Large engine and GPU library; `AF:260-262`, `AP:717-737`). If free space is short, **Continue** is hidden. The window runs as the signed-in user and shows once per Windows account.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-45 | "reopen CivicCast Installer" (AF:313) | There is no icon by that name. The window is titled "CivicCast (Native) Setup" and the program is `CivicCast Native.exe` in the install folder (`tauri.native.conf.json:3,10`; Hooks:1743-1751 notes the shortcuts point to the console, not this window) | Moderate |
| HELP-46 | Disk check "needs X GB" (about 9.7) | Counts only the downloadable rows, not the roughly 21 GB model packs setup already copied; recordings need more (manual ch. 9: plan for about 55 GB for a first install) | Moderate |
| HELP-47 | "Medium" and "Large" caption engines | Not explained until the next screen | Low |
| HELP-48 | Graphics line "(8 GB)" | No hint that 8 GB or more, on an NVIDIA card, is the threshold | Low |
| HELP-49 | "usually takes a few seconds" | Untested on a slow PC; the screen before it says up to a minute (`App.tsx:640`) | Low |
| HELP-52 (cited) | "You can uncheck it on the next screen" (AP:661) | Unchecking only hides the row; the download driver runs all six components (see `installer-gui-download-plan`) | SERIOUS |
| NEW-1 | "Free disk space on <install target>" | The target is `%ProgramFiles%` (usually `C:\Program Files`), not the folder chosen on setup's folder page (HW:506-510) | Moderate |
| NEW-2 | Red "Not enough free disk space" block with **Continue** hidden | The check runs after setup has already used its space and compares what is left with the download size. A kit install that found everything locally downloads nothing, yet this block can still stop the screen. The station does not need this window (manual ch. 10 Tip) | Moderate |

## Proposed text
Facts note (new line under the facts panel, now): "A capable graphics card for the higher-quality caption engine means an NVIDIA card with 8 GB or more of video memory. AMD and Intel graphics are listed but do not count."

Medium and Large in one line (add to the recommendation banner, now): "Medium captions meetings live, as they happen. Large is more accurate; on a capable graphics card it also captions live, otherwise it captions recordings after the meeting."

Probing sub-line: "This usually takes a few seconds. On a new computer it can take up to a minute."

Disk block (replace AF:313; keep the heading and AP:442 line). Honest text for now: "The free space left on this drive (Y.Y GB) is less than the size of the downloads this screen counts (X.X GB). If you installed from the full kit, setup has already copied what CivicCast needs and nothing may need downloading: you can close this window and use 'CivicCast Operator Console' on the Desktop. Otherwise free up space on this drive, close this window, and open CivicCast (Native) again (the Start menu entry, or CivicCast Native.exe in C:\Program Files\CivicCast (Native)) to repeat the check. A first install needs about 55 GB in all, and recordings need more."
After fix: remove the block when every row would be satisfied locally, and say "Free disk space on <the drive setup used>".

Installer name in this window: wherever the text says "CivicCast Installer", say "CivicCast (Native) Setup" (also AF:768, `App.tsx:282, 639, 670`).

## Notes for the coder
- Edit AF:202, 218, 313 and the recommendation text in AP:638-677. Tests that pin this screen: `src/hardware-honesty.test.ts:125-178, 220, 233` pins the processor, memory and the graphics format "NVIDIA GeForce RTX 5070 Ti (16 GB)" and that **Continue** is hidden when blocked; do not change the "(N GB)" format without updating those lines. `src/caption-engine-copy.test.ts` pins that the banner and the Large row never contradict each other (`claimsItRunsLiveHere`, `claimsItIsTooSlowForLive`); any new banner sentence about live or recorded captions must pass both. `tests/policy/test_hardware_inventory_policy.py:247` pins the heading "Here is what CivicCast found on this computer".
- NEW-1 and NEW-2 need a code fix: read free space for the real install folder (HW:506-510 uses `%ProgramFiles%`), and skip the block when `startAcquisition` would find every row local (`main.rs:3362-3371`).
- UNVERIFIED: that Tauri creates a Start menu entry for the app (hence the hedged "Start menu entry, or CivicCast Native.exe" wording above).
