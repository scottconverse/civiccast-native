> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Facility (nav id: facility)

Console group: Run Meeting. The page heading reads "Facility router". Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` ("Preview a router take (Facility)") and `ops/docs-sprint/inventory/screens/facility.md`. Line numbers re-checked in the .tsx.

## Where the help text lives now
- `screens/FacilityRouterScreen.tsx`: constants 34-41; error box 94-96; endpoint list 114-142; channel picker 173-228; take preview 349-395; overlay panel 420-474; manual crosspoint 503-534; scheduled take 559-604; page header 843-850; role note 862-867; footer 938-939; loading 834.
- `civiccast/facility/router_control.py:44-45` (the "Operator action" sentence, built on the server) and `:111-112` (button caption). `civiccast/facility/store.py:42-80` (the built-in sample data). `civiccast/stream/overlays.py:92-95` (overlay proof boundary and action text).

## Current text
| String | Where | Source line |
|---|---|---|
| "Facility router" | Page heading | FacilityRouterScreen.tsx:844 |
| "Preview SDI/IP router takes from a phone, tablet, or control-room workstation before enabling hardware send." | Page intro | FacilityRouterScreen.tsx:846-847 |
| "hardware send disabled" | Amber tag | FacilityRouterScreen.tsx:850 |
| "Loading facility router inventory." | Loading | FacilityRouterScreen.tsx:834 |
| "Facility router status could not load." + API message or "Check the staff token and local API service." | Load error | FacilityRouterScreen.tsx:94-96 |
| "Target channel" / "channel selected" / "no channel selected" | Channel card | FacilityRouterScreen.tsx:173, 175 |
| "Scheduled takes, overlays, and later L-bar commands apply to this channel. Manual crosspoint preview below previews an endpoint path and does not require a channel." | Channel card help | FacilityRouterScreen.tsx:180-181 |
| "Choose a channel..." | Menu first option | FacilityRouterScreen.tsx:220 |
| "No channels are configured yet. Configure a channel in Channel Ops before scheduling a take or previewing overlays." | Empty | FacilityRouterScreen.tsx:36-37 |
| "Configured channels could not load. Scheduled take and overlay actions are unavailable until they do." | Error | FacilityRouterScreen.tsx:38 |
| "Choose a channel before scheduling a take." / "...before previewing an overlay." | Disabled reasons | FacilityRouterScreen.tsx:34-35 |
| "Scheduling a take and previewing overlays require the meeting operator or setup admin role." / "Checking your permissions..." | Disabled reasons | FacilityRouterScreen.tsx:39-41 |
| "{that sentence} Endpoint inventory and manual crosspoint preview remain available." | Amber role note | FacilityRouterScreen.tsx:864-865 |
| "The previously selected channel (X) is no longer configured. Choose another channel." | Stale notice | FacilityRouterScreen.tsx:681 |
| "Router endpoints" / "N configured" / "ready" / "off" | Endpoint list | FacilityRouterScreen.tsx:114-115, 139 |
| "preview only" | Tag on the virtual panel | FacilityRouterScreen.tsx:304 |
| "Tap to preview this route before taking it live." | Caption under each route button (server) | civiccast/facility/router_control.py:111-112 |
| "Manual crosspoint" / "Source" / "Destination" / "Preview take" / "Previewing..." | Manual panel | FacilityRouterScreen.tsx:503, 508, 515, 533 |
| "Scheduled router take" / "Preview the automatic source take that arms before a scheduled program." / "Preview scheduled take" | Scheduled panel | FacilityRouterScreen.tsx:559-561, 587 |
| "Armed take:" / "Command:" / "Proof boundary: {server text}" | Scheduled result | FacilityRouterScreen.tsx:597, 601, 604 |
| "Overlay compositor" / "Preview L-bar and squeezeback output before starting the live compositor." / "Preview L-bar and squeezeback" / "cpu plan" | Overlay panel | FacilityRouterScreen.tsx:420-422, 448, 425 |
| "Layer order:" / "Encoder:" / "Proof boundary: ..." | Overlay result | FacilityRouterScreen.tsx:458, 462, 471 |
| "Take preview" / "Pick a virtual button or source/destination pair to preview the exact command before any facility hardware integration is enabled." | Empty preview | FacilityRouterScreen.tsx:349-352 |
| "Target" / "Protocol" / "Command" / "Operator action." / "Proof boundary:" / "ready" / "blocked" | Preview card | FacilityRouterScreen.tsx:373, 377, 382, 391, 394, 369 |
| "Confirm the previewed route, then send the command from the router panel." | Operator action text (server) | civiccast/facility/router_control.py:44-45 |
| "Inventory generated {time}. Proof boundary: Inventory and command planning only; hardware send is not performed." | Footer | FacilityRouterScreen.tsx:938-939; civiccast/facility/store.py:87 |
| "Router take preview failed." / "Overlay compositor preview failed." / "Scheduled router preview failed." | Errors | FacilityRouterScreen.tsx:930, 433, 572 |

## What the screen really does
This is a preview-only page. It shows one built-in sample router ("Control room router", example address 192.0.2.10, sources "Council chamber" and "Bulletin board", destination "CivicCast capture"), the same on every station. Every button builds the text of the command that would be sent to a router and shows it. Nothing is sent to any hardware, and nothing on any channel or schedule changes. "Preview scheduled take" uses a made-up item that starts 15 minutes from now; "Preview L-bar and squeezeback" prints a video-filter plan for a fixed layout and does not run it. The only real router take in this version is a Control Room cue.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "Confirm the previewed route, then send the command from the router panel." | No send control exists; sending is disabled (`router_control.py:25-50`). | misleading |
| HELP-02 | Endpoint, "Council chamber", 192.0.2.10 look like the station's equipment | Fixed sample inventory (`store.py:42-80`); no screen or call loads real routers. | blocks work (staff may think a router is connected) |
| HELP-03 | "...require the meeting operator or setup admin role" and "manual crosspoint preview remain available" | Server allows meeting_operator or support_admin only (`civiccast/facility/router.py:51, 77`; `civiccast/stream/router.py:29`). Setup-admin-only sign-ins see enabled buttons that fail; the route buttons and "Preview take" have no screen check. Support admin has the reverse problem. | misleading |
| HELP-04 | "Preview the automatic source take that arms before a scheduled program." / "...before starting the live compositor." | Fixed request: 15 minutes ahead, 15 s lead, item `operator-preview-schedule`; no compositor start control exists. | misleading |
| HELP-05 | "Configure a channel in Channel Ops" | The nav item is called "Channels" (Sidebar.tsx). | cosmetic |
| HELP-06 | "Proof boundary: ..." and a machine id "overlay-compositor-command-planning-no-ffmpeg-execution" | Machine text shown to staff (`civiccast/stream/overlays.py:22`). | cosmetic |
| HELP-07 | "SDI/IP", "L-bar", "squeezeback", "crosspoint" | Never explained. | cosmetic |
| NEW-2 | Overlay "Operator action" text (`stream/overlays.py:93-95`) says "start the compositor from the live output panel" | No such panel exists; nothing is started. | misleading |
| NEW-1 | Heading says "Facility router" beside a fixed sample list | The page offers no way to say it is sample data. | misleading (same cause as HELP-02) |

## Proposed text
- Heading note, new line under the title (always shown): "Sample data. The router, sources and destination listed here are built-in examples, the same on every station. CivicCast does not connect to your equipment from this page."
- Page intro (:846): "This page shows the command CivicCast would send to a video router to switch a camera or feed. It sends nothing. Use it to learn what a router take looks like." Tag (:850): "preview only, nothing is sent".
- Who can use this (new): "Anyone signed in can open this page. Meeting operator and Support admin can use the preview buttons. Setup admin alone cannot." After fix: "Meeting operator and Setup admin can use the preview buttons."
- Target channel help (:180-181): "Only the scheduled-take and overlay previews use this channel. The manual preview does not need one."
- Empty channels (:37): "No channels are set up yet. Add one on the Channels screen before using the scheduled-take or overlay previews."
- Role messages (:40, :864-865): "The scheduled-take and overlay previews need the Meeting operator or Support admin role." (If the coder aligns the roles, restore "setup admin".) Note under it: "The route buttons and Preview take also need one of those roles."
- Route caption (server `router_control.py:112`): "Shows the command for this route. Nothing is switched."
- Scheduled take help (:561): "Example only: shows a take that would be sent 15 minutes from now for a made-up program. It does not read your schedule and arms nothing."
- Overlay help (:422): "Example only: shows how the picture would be shrunk to make room for a graphics frame (an L-bar). It does not start any video processing."
- "Proof boundary" labels (:394, 471, 604, 938): rename to "What this does not do:". Show the server sentence in plain English: "This only builds the command text. It does not contact any router." (Server strings to replace: `router_control.py` "Command planning only; no hardware connection is opened by this API.", "Schedule-to-router command planning only; no hardware command is sent.", `store.py:87`, `overlays.py:22`.)
- "Operator action." line (`router_control.py:45`): "Preview only. This version does not send commands to a router." After fix (hardware send added): "Check the route, then use the Send control."
- Short glossary line, bottom of page: "Router: the box that decides which camera or feed goes to which input. Take: one switch. Crosspoint: one source-to-destination connection. L-bar and squeezeback: shrinking the picture to make room for a graphics frame."
- Status words: "ready" on an endpoint means the sample endpoint is switched on, not that a router answered. Show as "enabled" / "disabled". Take preview tag "ready" / "blocked" becomes "command ready" / "endpoint disabled".

## Notes for the coder
- Edit `screens/FacilityRouterScreen.tsx` for the screen strings and `civiccast/facility/router_control.py` (lines 44-45, 80-84, 111-112) and `civiccast/facility/store.py:87`, `civiccast/stream/overlays.py:22, 92-93` for server strings.
- Strings pinned by tests: `screens/FacilityRouterScreen.test.tsx` pins "Preview scheduled take", "Preview L-bar and squeezeback", "Preview take", "Choose a channel before scheduling a take.", "Router endpoints", "Manual crosspoint", /Layer order:/, /is no longer configured\. Choose another channel\./, and expects /require the meeting operator or setup admin role/ to be absent for an allowed role (line 312). `e2e/facility-router.spec.ts` mocks the server strings (lines 60, 137, 168-198), so a server-side text change needs no e2e edit but should be re-run. `tests/facility/test_router_control.py:139` pins `operator_action.startswith("Enable the router endpoint")` for the disabled case only.
- Code fixes, not text fixes: align the screen and server role lists (HELP-03); a way to load the station's real router inventory (HELP-02); a send control if hardware send is ever enabled.
- Not verified: what a Setup-admin-only sign-in sees on a 403 (read from `require_any_role`, not run); whether the GET calls (`router-inventory`, `router-panel`) are meant to be open to every signed-in role.
