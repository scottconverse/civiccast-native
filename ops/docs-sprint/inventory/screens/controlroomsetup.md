# Control Room Setup  (nav id: controlroomsetup, section: Setup)
Source files (under `civiccast\apps\portal-operator\src\`): `screens\ControlRoomSetupScreen.tsx` (screen + DeviceForm, DeviceProfileForm, CueForm), `screens\ControlRoomReadinessPanel.tsx`, `screens\control-room-format.ts`, `components\EmptyState.tsx`, `screens\status-language.ts`, `api\client.ts:1672-1740`.
Backend: `civiccast\control_room\router.py` (staff routes `/api/staff/control-room/*`), `control_room\service.py` (probe_device 487, readiness_report 512-840), `control_room\policy.py`, `control_room\store.py`, `app.py:3054-3065` (TSR URL).
Who can open it: sidebar shows it only to `setup_admin` (`Sidebar.tsx:101`). The screen itself also checks: any other role sees the blue note "Configuring the Production Control Room requires the setup admin role." (ControlRoomSetupScreen.tsx:407). During identity load: "Loading…"; identity failure: "Could not load your staff identity." (404-405). Kit-pending lock applies to the whole sidebar.

## What it is for
This is where the station registers the production gear a meeting is run with (video switchers, deck recorders, PTZ cameras, "network relay" boxes), sets how long each device takes to respond, and builds "surfaces" (a named panel) holding "cues" (one-press actions such as take a camera scene). The operate screen "Control Room" (`controlroom`) uses what is configured here. Nothing on this screen sends a live command to a device except "Test connection".

## What the user sees
Top to bottom (`ControlRoomSetupScreen.tsx:413-591`):
1. H1 "Control Room — setup" and "Register the switchers you control, set their transition timing, and author cue surfaces."
2. **Readiness panel** (`ControlRoomReadinessPanel`): optional yellow note about unverified equipment, headline "Control-room readiness" with two pills, summary sentence, "Technical detail" disclosure, five count boxes (Devices n/n, Surfaces, Cues, Open sessions, On-Air), a card per blocked/warning check, and a collapsed "LPM profile coverage" details block.
3. **Devices** section: registration form row, then one card per device (name, kind, reachability pill, "Health:" pill, Test connection, Remove, and a timing/profile row).
4. **Surfaces** section: "New surface label" + "Create surface", and a dropdown "Edit surface".
5. **Cues** section (only after a surface is picked): cue form, list of cues with Delete.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Device label (115) | Free-text name, required | `POST /api/staff/control-room/devices` | `setup_admin` (router.py:79,267) | Max 160 chars |
| Kind (120) | OBS Studio, vMix, Blackmagic ATEM, HyperDeck, PTZ camera, OSC, TCP device, HTTP device, CasparCG, GPI (network relay), Serial (network relay) (`control-room-format.ts:6-23`) | same | | For GPI/Serial a note appears: "Network-relay trigger over TCP — direct GPI contact-closure / serial (RS-232/422) hardware is not supported in this release. Point Host/Port at a TCP-to-GPI or TCP-to-serial relay box." (127-129) |
| Transport (134) | tcp, udp, http, websocket, serial, gpi (raw words) | same | | Default "websocket" regardless of Kind. "serial"/"gpi" transports offered although the note says direct hardware is unsupported |
| Host / Port (141,146) | Optional address and port 1-65535 | same | | Host is later checked by the target-safety rule (below) |
| Secret (write-only) (151) | Password for the device, placeholder "kept in keyring" | Sent with create, stored under handle `crsecret_<id>` in the OS keyring, never returned (router.py:395-409) | | 503 "The credential store is not available to persist the device secret." if no keyring |
| Register device (163) | Creates the device, always `enabled: true` | `POST .../devices` | `setup_admin` | Busy label "Saving…". Form is NOT cleared after success (UNVERIFIED visually; no reset code in `DeviceForm`) |
| Test connection (476) | Asks the control service to open a connection to the device; records reachable/unreachable and time | `POST .../devices/{id}/probe` (router.py:378; `probe_device` service.py:487) | server allows `setup_admin`, `support_admin`; UI only shows to setup_admin | Busy "Testing...". Result shown as a pill (Reachable / Unreachable / Not probed / Disabled) plus the server's detail text. Refuses non-private hosts: "Device host must be localhost, .local, or a private/link-local IP unless a setup admin records a public-host override reason in the device profile." (policy.py:156) |
| Remove -> Confirm remove / Cancel (498,486,491) | Two-step delete of a device | `DELETE .../devices/{id}` | `setup_admin` | Text "Confirm remove <label>?". UNVERIFIED whether its cues and profile are deleted along with it (store.py:257 only deletes the device row; cascade not checked) |
| TSR device type (190) | Free text, defaults to the Kind in capitals | `PUT .../devices/{id}/profile` | `setup_admin` | |
| Take-delay (ms) / Post-roll (ms) (195,200) | Timing for transitions, 0-600000 | same | | Boxes always start at 0 and do not show saved values (183-185) |
| Save profile (210) | Saves the profile; **always sends empty `options` and `capability_map`** (206-207), and bumps profile version | same | | Re-saving overwrites earlier timing and wipes any `options` (including a public-host override recorded elsewhere, policy.py:20-21,124-130) |
| New surface label (526) + Create surface (532) | Creates a surface assigned to role `meeting_operator` (hard-coded, line 381) | `POST .../surfaces` | `setup_admin` | No edit/delete surface control on this screen even though API has PATCH/DELETE (router.py:465-502) |
| Edit surface dropdown (538) | Picks a surface; first option "Select a surface to author cues…" | `GET .../surfaces`, `GET .../surfaces/{id}` | read: `setup_admin`, `support_admin`, `meeting_operator` | |
| Cue label (261), Device (266), Action (273), Bank (284), Confirm (290) | Cue fields. Actions (labels `cueActionLabel`): Take scene, Take input, Transition, Run macro, Play deck, Cue deck, Recall PTZ preset, Send OSC, Send HTTP, Push overlay, Clear overlay, GPI pulse, Serial send, Router take | `POST .../surfaces/{id}/cues` | `setup_admin` | Server rejects an action the chosen device kind does not support: "Action 'x' is not exposed for 'y' devices in CivicCast 3.1." (policy.py:112). Allowed list per kind: policy.py:21-41. Bank 0-99 |
| Payload (JSON) (304), Reset template (299) | Editable JSON, pre-filled with a template per action (`CUE_PAYLOAD_TEMPLATES`, 51-66) | same | | Invalid JSON -> "Payload must be valid JSON." (244). Keys like rename/delete/remove/destination_path are refused (policy.py:44-55) |
| Add cue (316) | Saves cue (position always 0) | same | | Needs a label and a device; if no devices: "Register a production device before adding cues to this surface." (552) |
| Delete -> Confirm delete / Cancel (577,569,572) | Two-step cue delete | `DELETE .../cues/{id}` | `setup_admin` | A cue that has ever fired cannot be deleted: 409 "cue <id> has already fired at least once and cannot be deleted" (store.py:402) |
| Open Control Room Setup (button inside blocked readiness cards) | Link to `/control-room-setup` | none | | It links to the page you are already on |

## States
- Loading identity: "Loading…". Not setup_admin: blue note (above).
- Readiness: "Checking control-room readiness..." / "Could not load control-room readiness. <server text>".
- Devices: "Loading production devices..." / "Could not load production devices. ..." / empty-state "No devices registered yet." + body "Control Room Setup is where this station registers the switchers, routers, and other production gear it drives during a meeting. Register your first device with the form above to see it here." (514-515).
- Surfaces: "Loading control surfaces..." / "Could not load control surfaces. ..."; Cues: "Loading cues for this surface..." / "Could not load this surface. ..."; empty "No cues on this surface yet." (584-585).
- Errors on create/remove/save: "Could not register the device.", "Could not remove the device.", "Could not save the device profile.", "Could not create the surface.", "Could not add the cue.", "Could not delete the cue." (each replaced by server detail when present).
- Storage not ready: server returns 503 "Durable storage is not ready yet." (router.py:76).
- Not-configured control service: readiness card "TSR control service" is blocked; detail "<...>; live cue fire/probe paths fail closed." (service.py:574-576).

## Typical task flows
1. Add a device -> Test connection -> set Take-delay/Post-roll -> Save profile.
2. Create a surface -> pick it in "Edit surface" -> add cues (one cue with Confirm ticked) -> check the readiness panel clears.
3. Fix a blocked check: read the card text, correct the device/cue, re-read readiness (invalidated after each save, not after Test connection; 361-366).

## Statuses and words on this screen
Readiness pill words come from `status-language.ts`: "Ready", "Check before meeting", "Do not broadcast yet" (headline: ready+equipment-unverified shows "Check before meeting"; blocked shows "Do not broadcast yet"; `ControlRoomReadinessPanel.tsx:148-153`). Equipment pill: "Equipment verified" / "Equipment check pending" (`station_device_ready` is hard-coded false in service.py:809, so it always reads pending in this build). Device pills: Disabled, Reachable, Unreachable, Not probed; Health: Never probed, "Stale — probe again" (older than 5 minutes, `DEVICE_HEALTH_STALE_AFTER_MS = 300_000`), Healthy, Unreachable. Check list in the backend: TSR control service, Device inventory, Device profiles, Enabled devices, Device health, Device target safety, Control surfaces, Timeline cues, Cue action safety, Safe-state cue candidate, Station-device evidence (service.py:577-830).

## Related settings / env / CLI / API
`CIVICCAST_CONTROL_ROOM_TSR_URL` (e.g. loopback `http://127.0.0.1:7717`; app.py:3054-3065), OS keyring for device secrets, Node TSR sidecar (`control_room\tsr_service`). Other staff routes not used here: PATCH device, PATCH/DELETE surface, sessions, plan/fire/rollback. Roles: `setup_admin` configures; `meeting_operator` opens sessions and fires; `support_admin` may probe and read.

## Help-text findings
- [HELP-01] ControlRoomReadinessPanel.tsx:76 — "Open Control Room Setup to start or reconnect the local control service before On-Air use." — there is no start/reconnect control on this page; the service is configured by the environment variable `CIVICCAST_CONTROL_ROOM_TSR_URL` and "supervised" elsewhere; the red button "Open Control Room Setup" also points at the page the reader is already on — fix: say who starts the service (support/IT) and drop the self-link on this screen.
- [HELP-02] ControlRoomSetupScreen.tsx:290 — checkbox label "Confirm" — unexplained. The backend treats a cue with this ticked as the "safe-state cue", and readiness is BLOCKED if a surface has cues but none ticked (service.py:544-548,771-790) — fix: label "Ask for confirmation before firing (use for the emergency/safe cue)" and say each surface needs at least one.
- [HELP-03] ControlRoomSetupScreen.tsx:188-200 — "TSR device type", "Take-delay (ms)", "Post-roll (ms)" — jargon and no help text; the boxes start at 0 and never show the saved value, and "Save profile" also clears hidden options — fix: show saved values, explain in one sentence each, and warn that saving replaces the old profile.
- [HELP-04] ControlRoomSetupScreen.tsx:134-137 — Transport list shows raw "tcp/udp/http/websocket/serial/gpi"; "serial" and "gpi" transport conflict with the note that direct serial/GPI hardware is unsupported — fix: pick the transport automatically from Kind or explain.
- [HELP-05] ControlRoomSetupScreen.tsx:152 — placeholder "kept in keyring" — jargon — fix: "Stored securely on this computer; never shown again."
- [HELP-06] service.py:651 (readiness check "Enabled devices") says "Enable required devices or remove unused disabled devices" but this screen has no way to disable or enable a device (every device is created enabled; edit API unused) — fix: add an Enabled toggle or reword.
- [HELP-07] policy.py:156 error text mentions a "public-host override reason in the device profile" that the screen cannot record — a user who gets this error on Test connection has no UI path out — fix: state "ask support" or add the control.
- [HELP-08] ControlRoomSetupScreen.tsx:416-418 — H1 "Control Room — setup" vs sidebar "Control Room Setup" and "Surfaces" / "cues" / "LPM profile coverage" — "surface" and "LPM" are never defined on the page — fix: add a one-line glossary under the H1.
- [HELP-09] No explanation anywhere on the screen that "Test connection" really contacts the device through the control service, and that a result older than 5 minutes shows "Stale — probe again".

## Screenshot plan
1. Non-setup_admin view (blue note).
2. Fresh station: readiness blocked (TSR control service not configured) with all blocker cards and the empty-device state.
3. Device form with GPI kind selected (relay note visible).
4. A registered device with Reachable and Healthy pills after Test connection; a second showing the unreachable detail text.
5. Surface selected with CueForm and a template payload; invalid-JSON error; an empty-cue state.
6. Confirm remove and Confirm delete states.
Setup: needs a running control service (or none, to show the blocked state) and at least one device that answers on loopback.

## UNVERIFIED / open questions
- UNVERIFIED: whether deleting a device also deletes its cues/profile (needs DB schema foreign keys in `control_room\migrations`).
- UNVERIFIED: whether the Register device form clears after success.
- UNVERIFIED: that `station_device_ready` can never become true in this build (only saw the literal `False` in `readiness_report`).
- UNVERIFIED: who or what supervises/starts the Node TSR sidecar on the packaged station.
