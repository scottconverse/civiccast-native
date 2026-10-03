# Installer step: "Checking This Computer" (hardware check and recommendation)  (nav id: installer-gui-checking-computer, section: Installer)
Source files (under `civiccast/apps/installer/`): `src/AcquisitionFlow.tsx`, `src/acquisition-progress.ts`, `src/api.ts`, `src-tauri/src/hardware_inventory.rs`, `src/App.tsx`
Who can open it: whoever launches the installed "CivicCast (Native)" app window on a fresh Windows account. No sign-in, no roles. Shown once per Windows account: it is skipped when the browser-storage flag `civiccast.acquisitionFlowComplete` = `1`, when the URL has `?state=` or `?downloadExperience=0` (`src/App.tsx:301,315-317`; `src/AcquisitionFlow.tsx:56-72`).

## What it is for
This is the first window of the setup wizard that runs after the Windows installer finished (see `installer-nsis-*.md` for the earlier, elevated phase). It reads the computer's processor, memory, graphics card and free disk space, says which caption engine CivicCast recommends, and blocks if the drive is too full. It runs before anything is downloaded.

## What the user sees (top to bottom)
1. While probing (at least 0.65 s, `AcquisitionFlow.tsx:1063-1065`): heading "Checking This Computer", "CivicCast is looking at this computer's hardware so it can recommend the right setup.", spinner and "This usually takes a few seconds." (`AcquisitionFlow.tsx:201-218`).
2. Facts panel `aria-label="Hardware summary"`: Processor, Memory, Graphics, "Free disk space on `<install target>`" (or "Free disk space") (`:284-303`).
3. Recommendation sentence (`recommendationSentence`, `acquisition-progress.ts:638-677`).
4. A red "Not enough free disk space" box, or a plain note if free space could not be read.
5. "Continue" button (hidden when disk is blocked).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Continue | goes to "What CivicCast Needs" | none | none | not shown when free space is below the required total (`:324-330`); on probe failure it still shows and lets setup continue (`:251-255`) |

## How the numbers are produced (hardware_inventory.rs)
- Command `native_hardware_inventory` (`main.rs:3004-3012`). Processor name from registry `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0\ProcessorNameString`; cores via `GetLogicalProcessorInformationEx`; memory via `GlobalMemoryStatusEx` (GB, 1 decimal); free space via `GetDiskFreeSpaceExW` on the install target; graphics via DXGI adapter list, skipping the software adapter and exact duplicates (`hardware_inventory.rs:263-470`; `AcquisitionFlow.tsx:142-154`).
- Any value that cannot be read is shown as "Unavailable" and never replaced with a number (`AcquisitionFlow.tsx:118-122,156-178`; `hardware_inventory.rs:80-95`). Graphics reads "No dedicated graphics card" only when the probe ran and found none (`:164-166`).
- Graphics line format: `<name> (<VRAM> GB)`, comma-separated (`:167`).
- Caption engine rule: only NVIDIA adapters (PCI vendor 0x10DE) count; the best one's VRAM is rounded to 0.1 GB; below 8 GB = Medium ("floor"); 8 GB or more = Large (large-v3) capable (`hardware_inventory.rs:130-194`). AMD and Intel cards are listed but never raise the engine (`:21-37`).
- Disk rule: required bytes = sum of the catalog sizes of the default selection (the always-included, downloadable rows, plus Large and GPU acceleration when this card qualifies; `defaultSelectedComponentIds`, `acquisition-progress.ts:717-737`, sizes in `installer-component-catalog.md`; `AcquisitionFlow.tsx:260-262`). If free bytes are less: blocked (`acquisition-progress.ts:424-444`).

## States (exact text)
| State | Text |
|---|---|
| Probing | "Checking This Computer" / "This usually takes a few seconds." |
| Probe failed | heading "Hardware check unavailable" + "CivicCast could not check this computer's hardware. It will not guess: nothing about this computer is shown below, and the free-space check could not be made. Setup can continue, but if a download later runs out of room, free up space and choose Retry." (`api.ts:793-796`). In a browser preview: "CivicCast could not check this computer's hardware in this preview. No real hardware readings are available here." (`:799-801`) |
| Disk too small | "Not enough free disk space" / "This drive doesn't have enough free space: needs X.X GB free, this drive has Y.Y GB." / "Free up space on this drive, then reopen CivicCast Installer." (`:310-313`; `acquisition-progress.ts:442`) |
| Disk unreadable | "CivicCast could not check free disk space on this computer. Setup needs about X.X GB." (`:430-432`); does not block |

## Recommendation sentences (all five cases, `acquisition-progress.ts:638-677`)
1. Graphics probe failed: "CivicCast could not check this computer's graphics card, so it is installing the standard caption engine (Medium), which runs in real time on any supported CPU."
2. Capable NVIDIA card and Large selected by default (the shipping case): "This station's graphics card can run the higher-quality caption engine live, and CivicCast has selected it. You can uncheck it on the next screen."
3. Capable but Large not selected: "...CivicCast installs the standard caption engine (Medium); the next screen offers the higher-quality one as an extra download."
4. Dedicated card that does not qualify: "This station's graphics card is not one CivicCast can run the higher-quality caption engine on. We recommend the standard caption engine (Medium), which runs in real time here."
5. No dedicated card: "This station has no dedicated graphics card. We recommend the standard caption engine (Medium), which runs in real time on this CPU."

## Typical task flows
1. Read the facts, press Continue.
2. Disk blocked: free up space, close and reopen the installer, which repeats the check.

## Related settings / env / CLI / API
Tauri command `native_hardware_inventory` / `nativeHardwareInventory`; installer window title "CivicCast (Native) Setup" (`tauri.native.conf.json`); latch key `civiccast.acquisitionFlowComplete`.

## Help-text findings
- [HELP-45] `AcquisitionFlow.tsx:313` "reopen CivicCast Installer" — there is no icon or shortcut called "CivicCast Installer"; the Start Menu entries created by setup are the two web shortcuts (`nsis-hooks-bootstrap.nsh:1791-1807`) and the app is "CivicCast (Native)". Suggest "close this window and open CivicCast (Native) again from the Start menu" (UNVERIFIED that Tauri creates a Start Menu entry for the app).
- [HELP-46] The disk check counts only the downloadable components (about 9.7 GB for the default set), not the ~21 GB of model packs the earlier setup phase already extracted, and says nothing about space needed after downloads (recordings). A resident-style reader will think 10 GB is enough. Suggest stating the figure and that recordings need more.
- [HELP-47] "Medium"/"Large" caption engines are named without saying what the difference means for the meeting (live vs after the meeting) until the next screen.
- [HELP-48] Graphics line says "(8 GB)" with no explanation that 8 GB or more is the threshold; add "needs an NVIDIA card with 8 GB or more".
- [HELP-49] `AcquisitionFlow.tsx:218` "usually takes a few seconds" is not tested on a slow box; the first-launch screen before it says up to a minute (`App.tsx:640`).

## Screenshot plan
Healthy NVIDIA >= 8 GB station (case 2); CPU-only station (case 5); AMD iGPU station (case 4); low-disk block; probe-failed box (run the web build in a browser preview).

## UNVERIFIED / open questions
- UNVERIFIED: install target path shown (`hardware.install_target`): the Rust collector for it was not read.
- UNVERIFIED: whether the app can be re-run to repeat the check once the latch is set (it can: App.tsx "More options" > "Download AI models and captions", see `installer-gui-setup-wizard.md`).
