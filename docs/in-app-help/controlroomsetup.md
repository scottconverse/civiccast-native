# Control Room — setup (nav id: controlroomsetup)

Sidebar: Setup > **Control Room Setup**; page H1 "Control Room — setup". Manual authority: `docs/manual/src/22-configuration.md` section "Set up the Control Room" (`#configuration-controlroom`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/screens/ControlRoomSetupScreen.tsx` (593 lines) and `ControlRoomReadinessPanel.tsx` (280 lines, shared with the operate screen `ControlRoomScreen.tsx`). Labels for kinds and actions come from `control-room-format.ts`. Server text from `civiccast/control_room/policy.py`, `service.py`, `store.py`. Lines confirmed by opening the files (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "Control Room — setup"; "Register the switchers you control, set their transition timing, and author cue surfaces." | H1 and intro | ControlRoomSetupScreen.tsx:416, 418 |
| "Loading…"; "Could not load your staff identity."; "Configuring the Production Control Room requires the setup admin role." | role gate | 404, 405, 407 |
| "Checking control-room readiness..."; "Could not load control-room readiness. <text>" | readiness states | 423, 425 |
| "You can register switchers and run dry runs now. On-air readiness is confirmed once a check against the room's actual devices passes." | yellow note | ControlRoomReadinessPanel.tsx:144-145 |
| "Control-room readiness"; pills "Equipment verified" / "Equipment check pending"; "Technical detail"; boxes Devices, Surfaces, Cues, Open sessions, On-Air; "LPM profile coverage" | readiness panel | ControlRoomReadinessPanel.tsx:155, 104-105, 168, 175-179, 230 |
| "Open Control Room Setup to start or reconnect the local control service before On-Air use." and a button "Open Control Room Setup" | blocked "TSR control service" card | ControlRoomReadinessPanel.tsx:76, 219 |
| "Devices"; labels "Device label", "Kind", "Transport", "Host", "Port", "Secret (write-only)" (placeholder "kept in keyring"); button "Register device" / "Saving…" | device form | ControlRoomSetupScreen.tsx:429, 114, 119, 133, 140, 145, 150-152, 163 |
| "Network-relay trigger over TCP — direct GPI contact-closure / serial (RS-232/422) hardware is not supported in this release. Point Host/Port at a TCP-to-GPI or TCP-to-serial relay box." | shown for GPI and Serial kinds | 127-129 |
| "Could not register the device."; "Could not remove the device."; "Could not save the device profile." | errors | 431-433 |
| "Loading production devices..."; "Could not load production devices. <text>" | states | 435, 436 |
| "Test connection" / "Testing..."; "Connection test failed." | per-device button | 476, 371 |
| "Remove"; "Confirm remove <label>?"; "Confirm remove"; "Cancel" | two-step delete | 498, 481, 486, 491 |
| "No devices registered yet." + "Control Room Setup is where this station registers the switchers, routers, and other production gear it drives during a meeting. Register your first device with the form above to see it here." | empty state | 514-515 |
| "TSR device type"; "Take-delay (ms)"; "Post-roll (ms)"; "Save profile" | per-device profile row | 189, 194, 199, 210 |
| "Surfaces"; "New surface label"; "Create surface"; select "Edit surface" with "Select a surface to author cues…"; "Could not create the surface." | surfaces | 522, 525-526, 532, 538, 541, 535 |
| "Cues"; "Cue label"; "Action"; "Bank"; checkbox "Confirm"; "Payload (JSON)"; "Reset template"; "Add cue"; "Payload must be valid JSON." | cue form | 548, 260, 272, 283, 290, 303, 299, 316, 244 |
| "Register a production device before adding cues to this surface."; "No cues on this surface yet." + "Cues are the one-press actions an operator fires during a meeting — take a camera, roll a slate, pulse a device. Add the first cue with the form above and it appears here."; "Confirm delete?" / "Confirm delete" / "Delete"; "Could not add the cue."; "Could not delete the cue." | cue states | 552, 584-585, 566-577, 556-557 |

## What the screen really does
This is where a Setup admin registers production equipment (OBS, vMix, ATEM, HyperDeck, PTZ camera, OSC, TCP, HTTP, CasparCG, and two "network relay" kinds), sets each device's timing, and builds surfaces (named panels) of cues (one-press actions). The operate screen, Control Room, uses what is saved here. Only "Test connection" contacts a device, through a separate helper program (the TSR sidecar). As installed in beta.10 nothing installs or starts that helper, so the "TSR control service" readiness card is blocked and cues cannot fire until IT sets it up (`22-configuration.md`). Device passwords go to the Windows credential store and are never shown again. The headline can never read "Ready": equipment verification is fixed at "pending" in this build (service.py:809), so the best result is "Check before meeting".

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| HELP-01 | "Open Control Room Setup to start or reconnect the local control service" + a button with the same name (ControlRoomReadinessPanel.tsx:76, 219) | No control here starts the service; it is set by `CIVICCAST_CONTROL_ROOM_TSR_URL` and run by IT. On this screen the button links to the page you are already on (it is useful only on the operate screen) | blocks work |
| HELP-02 | Checkbox "Confirm" (ControlRoomSetupScreen.tsx:290) | The server treats a ticked cue as the surface's "safe-state cue"; readiness is blocked if a surface has cues and none is ticked (service.py:544-548, 771-790) | blocks work |
| HELP-03 | "TSR device type", "Take-delay (ms)", "Post-roll (ms)" with no help (189-199) | Boxes start at 0 and never show saved values; "Save profile" sends empty options and wipes any earlier options, including a public-host override (206-207; policy.py:20-21, 124-130) | misleading (data loss) |
| HELP-04 | Transport list: tcp, udp, http, websocket, serial, gpi (134-137) | Defaults to websocket whatever the kind; serial and gpi are offered although the note says direct hardware is unsupported | misleading |
| HELP-05 | Placeholder "kept in keyring" (152) | Jargon; it means the Windows credential store | cosmetic |
| HELP-06 | Readiness "Enabled devices": "Enable required devices or remove unused disabled devices" (service.py:651) | The screen has no enable or disable control; every device is created enabled | misleading |
| HELP-07 | Probe error: "...unless a setup admin records a public-host override reason in the device profile." (policy.py:156) | The screen cannot record that reason, so there is no way out | blocks work |
| HELP-08 | "surface", "cue", "LPM profile coverage" never defined (416-418, 230) | A first-time user cannot tell what they are | misleading |
| HELP-09 | Nothing says Test connection really contacts the device, or that a result older than 5 minutes reads "Stale — probe again" | `DEVICE_HEALTH_STALE_AFTER_MS = 300000` | misleading |
| NEW-1 | Yellow note: "run dry runs now" (ReadinessPanel:144-145) | In beta.10 as installed the control service is absent, so probes report unreachable and cues fail closed | misleading |
| NEW-2 | "Remove" (498) | Whether the device's cues and profile are also removed is UNVERIFIED (store.py:257 deletes the device row only); a cue that has ever fired cannot be deleted (store.py:402) | misleading |

## Proposed text
**Intro (H1 "Control Room setup"):** "What this is for: tell CivicCast which production equipment you use (switchers, deck recorders, PTZ cameras, relay boxes) and build panels of one-press actions for the Control Room screen. Who can use this: Setup admin. A *surface* is a named panel. A *cue* is one button on it, such as 'Take camera 2'. Nothing here sends a command to equipment except Test connection."
**Readiness note (until the helper is installed):** "The control service that talks to your equipment is not running on this computer. Cues cannot fire until your IT person installs and starts it (setting `CIVICCAST_CONTROL_ROOM_TSR_URL`). See the manual: Configuring the station, Set up the Control Room." Replace the "Open Control Room Setup" button on this screen with a link "Open the manual section" (`/help#configuration-controlroom`); keep the button on the operate screen.
After fix: the installer ships and starts the helper and the card says "Control service running".
**Device form:** "Kind" help "Pick the closest match. GPI and Serial need a TCP relay box (see the note)." "Transport" help "How CivicCast reaches the device. Leave on the default unless the device's manual says otherwise." Secret label "Device password (stored securely on this computer, never shown again)"; placeholder "Stored securely; never shown again".
**Test connection:** "Test connection asks the control service to open a connection to this device. A result older than 5 minutes shows 'Stale — probe again'. Only addresses on this computer or your local network are allowed." Error for a public host: "This address is not on your local network. Ask your IT person to record an override reason." After fix: an override field on the profile.
**Profile row:** "Take delay (ms): how long CivicCast waits after you press a cue before the picture changes. Post-roll (ms): how long it waits afterward. Both 0 to 600000." Add: "Saving replaces this device's whole profile, including options set elsewhere." After fix: pre-fill saved values.
**Confirm checkbox label:** "Ask for confirmation before this cue fires. Every surface with cues needs at least one ticked cue; CivicCast uses it as the safe cue." 
**Remove confirm:** "Remove <label>? Its saved settings are removed. Cues that use it may stop working." (Replace once the cascade is verified.)
**Equipment pill:** "Equipment check pending" -> add hover text "CivicCast cannot yet confirm your actual equipment, so this screen never shows 'Ready'."

## Notes for the coder
- Files: `ControlRoomSetupScreen.tsx`, `ControlRoomReadinessPanel.tsx` (the `operatorRecoveryText` helper, line 74-79), `control-room-format.ts`, `civiccast/control_room/service.py:651` and `policy.py:156` for server wording.
- Pins: `ControlRoomSetupScreen.test.tsx` ("Confirm remove", "Network-relay trigger", "Register a production device", "Payload must be valid JSON", "Equipment check pending"), `ControlRoomReadinessPanel.test.tsx` ("Equipment verified", "LPM profile coverage"), `ControlRoomScreen.test.tsx`, `e2e/control-room-readiness.spec.ts` ("Open Control Room Setup", "Control-room readiness", "Equipment check pending").
- Code fix needed, not text: ship and start the TSR sidecar (no installer step exists); Enabled toggle for devices (HELP-06); load saved profile values and stop clearing options (HELP-03); a public-host override field (HELP-07); surface edit and delete (API has PATCH/DELETE, no UI); decide whether Register device clears its form (UNVERIFIED).
