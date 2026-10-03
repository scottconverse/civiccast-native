# Facility  (nav id: facility, section: Run Meeting)
Source files: `SRC\screens\FacilityRouterScreen.tsx` (page heading "Facility router"), `SRC\components\shell\Sidebar.tsx`, `SRC\auth\roles.ts`.
Backend traced: `BE\facility\router.py`, `BE\facility\router_control.py`, `BE\facility\store.py`, `BE\facility\models.py`, `BE\stream\router.py`, `BE\stream\overlays.py`, `BE\app.py:167, 2494`.
(`SRC` = `civiccast\apps\portal-operator\src`; `BE` = `civiccast`. Route `/facility`, `SRC\routes.ts:8`. Read from code only; nothing was run.)

Who can open it: any signed-in operator (nav entry has no `requiredRoles`, `Sidebar.tsx:122`; route ungated `App.tsx:266`). Not reachable while the first-setup recovery kit is pending. Using the preview buttons needs a role (see gate column) and the UI and backend disagree about which role (HELP-03).

## What it is for
A preview-only panel for a broadcast video router (the box that decides which camera or feed goes to which input). It shows a list of configured router "endpoints", a grid of one-tap "source to destination" buttons, and a manual source/destination picker. Every button builds the exact command text that WOULD be sent and shows it. Nothing is sent to any hardware: the screen says "hardware send disabled", and the code never opens a connection (`router_control.py:25-50`). It also previews a "scheduled take" and an "L-bar and squeezeback" overlay plan.

## What the user sees
Top to bottom (`FacilityRouterScreen.tsx:840-944`):
1. Loading: "Loading facility router inventory." (834). Error: red "Facility router status could not load." + API message or "Check the staff token and local API service." (94-96).
2. Heading "Facility router", text "Preview SDI/IP router takes from a phone, tablet, or control-room workstation before enabling hardware send." (844-848) and an amber pill "hardware send disabled" (850).
3. "Target channel" card: pill "channel selected" or "no channel selected", help text, channel dropdown (first option "Choose a channel...") (152-231).
4. Amber role note when the identity is neither meeting_operator nor setup_admin (862-867).
5. "Router endpoints": pill "N configured", one card per endpoint with vendor / protocol, "TCP host:port" and a pill "ready" or "off" (102-150).
6. Left column: virtual router panel (title from server, pill "preview only"), "Manual crosspoint", "Scheduled router take", "Overlay compositor". Right column: error banner if a take preview failed, "Take preview" card, footer "Inventory generated <time>. Proof boundary: <text>" (879-941).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Endpoint card (aria-pressed) | Chooses which router endpoint the panel and previews use | local state; panel reloads `GET /api/staff/facility/router-panel?endpoint_id=` (`client.ts:1649`; `BE\facility\router.py:102-122`) | any signed-in (no gate on GET) | Clears the current take preview |
| Target channel dropdown "Choose a channel..." | Picks the channel for scheduled-take and overlay previews | local state; list from `GET /api/staff/cable/channels` | any | Auto-selected if exactly one channel exists (686-691). If the selected channel disappears: "The previously selected channel (X) is no longer configured. Choose another channel." (680) |
| Virtual button, e.g. "Council chamber to CivicCast capture" (grid) | Previews that route: sends source/destination ids to the planner and shows the command | `POST /api/staff/facility/router-take-plan` (`client.ts:1655`; `router.py:47-70`) | UI: no gate on these buttons. Backend: meeting_operator OR support_admin (`router.py:51`) | Disabled when the button is disabled by the server. Button caption under it: "Tap to preview this route before taking it live." (`router_control.py:112`). Nothing is taken |
| Manual crosspoint: "Source" and "Destination" selects, "Preview take" | Same preview for the chosen pair | same API | same | "Previewing..." while busy. Disabled until both selected |
| "Preview scheduled take" | Builds a plan for an automatic take armed ahead of a program. The request is FIXED: starts 15 minutes from now, 15 s pre-roll, schedule item id `operator-preview-schedule` (802-817) | `POST /api/staff/facility/router-schedule-plan` (`client.ts:1664`; `router.py:73-99`) | UI: needs channel + meeting_operator OR setup_admin (654-657, 695-706). Backend: meeting_operator OR support_admin (`router.py:77`) | Disabled reasons shown beneath: "Choose a channel before scheduling a take.", "No channels are configured yet. Configure a channel in Channel Ops before scheduling a take or previewing overlays.", "Configured channels could not load. Scheduled take and overlay actions are unavailable until they do.", "Checking your permissions...", "Scheduling a take and previewing overlays require the meeting operator or setup admin role." (34-41). Result lines: "Armed take:", "Command:", "Proof boundary:" (597-604). It reads no real schedule and arms nothing |
| "Preview L-bar and squeezeback" | Builds an FFmpeg filter plan for a fixed two-layer layout (squeezeback 68x72% + L-bar message well) for the chosen channel (766-800) | `POST /api/staff/stream/overlay-compositor-plan` (`client.ts:1635`; `BE\stream\router.py:25-38`) | UI as above; backend meeting_operator OR support_admin | Result shows "Layer order:", "Encoder:", the filter text and "Proof boundary: overlay-compositor-command-planning-no-ffmpeg-execution" (`overlays.py:22`). FFmpeg is not run |

Nothing on this screen can change the router, the channel, or the schedule. No control is destructive. There are no confirmation dialogs.

## States
- Empty channels: "No channels are configured yet. Configure a channel in Channel Ops before scheduling a take or previewing overlays." (36-37). The nav item is called "Channels", not "Channel Ops" (HELP-05).
- Channel list failed: red text "Configured channels could not load. ..." (38, 192-199).
- Take preview empty: "Pick a virtual button or source/destination pair to preview the exact command before any facility hardware integration is enabled." (350-352).
- Panel loading: "Loading virtual router panel." (291). Preview failed: "Router take preview failed." (930). Overlay failed: "Overlay compositor preview failed." (433). Schedule failed: "Scheduled router preview failed." (572).
- Offline/not configured: no special text. The inventory never reports "not configured": it is always the built-in sample (below).

## What data it shows (important)
The inventory is a fixed built-in sample, not station configuration: `InMemoryFacilityRouterStore.default()` (`BE\facility\store.py:42-80`) holds one endpoint "Control room router" (Blackmagic Videohub, TCP 192.0.2.10:9990, note "Example endpoint for operator training and tests."), sources "Council chamber" (port 1, linked source `rtmp-cam-01`) and "Bulletin board" (port 2), and destination "CivicCast capture" (port 7, channel `government`). `app.py` registers the router without overriding the store (`app.py:167, 2494`) and no create/edit endpoint exists in `facility\router.py`. So every station sees these same rows and 192.0.2.10 is a reserved documentation address that no real router uses.
Command shapes the preview prints (`router_control.py:127-140`): Blackmagic `VIDEO OUTPUT ROUTING:\n<dest> <source>\n\n`; Ross `XPT <source>:<dest>`; Utah `@ TAKE <dest> <source>`; Evertz `X <dest>,<source>`; generic uses an endpoint template.

## Typical task flows (only what the code supports)
1. Look at what a router take would send: pick endpoint -> tap a virtual button (or choose Source and Destination and press "Preview take") -> read "Take preview" (Target, Protocol, Command, Operator action, Proof boundary, pill "ready" or "blocked").
2. Preview a pre-program take: choose channel -> "Preview scheduled take" -> read "Armed take" time.
3. Preview overlay layout: choose channel -> "Preview L-bar and squeezeback".
There is no flow that actually switches a router; the real router-take path is a Control Room cue on a "TCP device" (`BE\control_room\policy.py:33`, action "Router take").

## Statuses and words on this screen
Endpoint pill: "ready" / "off" (139). Take preview pill: "ready" / "blocked" (369) = endpoint enabled or not (`router_control.py:43`). Scheduled pill: "ready" / "preview" (564). Channel pill: "channel selected" / "no channel selected". Overlay pill: the acceleration mode (for example a GPU name) or "cpu plan" (425). Static pills: "hardware send disabled", "preview only". "Proof boundary" = a plain statement of what the preview does not do; the server strings are: "Command planning only; no hardware connection is opened by this API." / "Schedule-to-router command planning only; no hardware command is sent." / "Inventory and command planning only; hardware send is not performed." Words are not routed through `status-language.ts`.

## Related settings / env / CLI / API
API: `/api/staff/facility/router-inventory`, `router-panel`, `router-take-plan`, `router-schedule-plan`; `/api/staff/stream/overlay-compositor-plan`; `/api/staff/cable/channels`. Related screens: Control Room (cue "Router take"), Channels. No env var or CLI found.

## Help-text findings
- [HELP-01] `BE\facility\router_control.py:45` shown in "Take preview" as "Operator action. Confirm the previewed route, then send the command from the router panel." — There is no send control anywhere, and the page says hardware send is disabled. — Replace with "Preview only. This version does not send commands to a router."
- [HELP-02] `FacilityRouterScreen.tsx:304, 850` pills "preview only" / "hardware send disabled" and the inventory (`store.py:42-80`) — a clerk will assume the listed router, "Council chamber" and 192.0.2.10 are THEIR equipment. They are sample data. — Add a visible "Sample data" note until real inventory exists; manual must say so.
- [HELP-03] `FacilityRouterScreen.tsx:654-657, 40` vs `BE\facility\router.py:51, 77` — UI enables the scheduled-take and overlay buttons for meeting_operator or setup_admin and says "require the meeting operator or setup admin role"; the backend allows meeting_operator or support_admin. A setup admin sees enabled buttons that return 403 ("This action requires one of these CivicCast roles: meeting_operator, support_admin."). The virtual buttons and "Preview take" have no UI gate at all although the backend gates them, and the amber note says they "remain available" (864-865). — Align the roles and fix the note.
- [HELP-04] `FacilityRouterScreen.tsx:560-561, 421-422` — "Preview the automatic source take that arms before a scheduled program." / "Preview L-bar and squeezeback output before starting the live compositor." — Neither a real schedule nor a "start compositor" control exists; the scheduled preview uses a made-up item 15 minutes from now. — Say "Example only: shows a take 15 minutes from now."
- [HELP-05] `FacilityRouterScreen.tsx:37` — "Configure a channel in Channel Ops" — nav label is "Channels" (`Sidebar.tsx:125`). — "Configure a channel on the Channels screen."
- [HELP-06] `FacilityRouterScreen.tsx:395, 471, 604, 938` — "Proof boundary: ..." and the string "overlay-compositor-command-planning-no-ffmpeg-execution" printed verbatim. — Jargon / machine id. Rename to "What this does not do" with plain sentence.
- [HELP-07] `FacilityRouterScreen.tsx:846` — "SDI/IP router takes", "L-bar", "squeezeback", "crosspoint" are unexplained. — Add one-line glossary in the help file.

## Screenshot plan
(a) Default view with the sample endpoint, virtual panel and "hardware send disabled" pill. (b) After tapping the "Council chamber to CivicCast capture" button: Take preview with the Videohub command. (c) Channel chosen, scheduled-take result. (d) Overlay plan result. (e) As a role without access to see the disabled-reason text. Setup: lab station with at least one channel configured (`government`).

## UNVERIFIED / open questions
- UNVERIFIED-01: Whether a later release or a hidden CLI loads real router inventory; none found in `BE\facility` or `app.py`.
- UNVERIFIED-02: What a setup_admin-only token sees in practice (403 text). Derived from `require_any_role` (`BE\auth\roles.py:63-80`), not run.
- UNVERIFIED-03: Whether the GET endpoints (`router-inventory`, `router-panel`) are meant to be open to every signed-in role; no `require_any_role` is attached.
