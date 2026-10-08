> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Live (nav id: live)

Console group: Run Meeting. Spec for the in-app help of the Live screen, written against beta.10. Paths are under `civiccast/apps/portal-operator/src/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` and `ops/docs-sprint/inventory/screens/live.md`; every line number below was re-checked in the .tsx.

## Where the help text lives now
- `screens/LiveRoomScreen.tsx`: page header 1246-1251; state pills 1256-1260; action error box 99-116 and 1264; safe-to-broadcast panel 118-189; role note 1275; loading 1281; source guidance 837-893; preview panel 907-931; source cards 318-323; source detail 429-479; source edit form 603-683; ingest panel 733-765; session controls 1332-1442; finalization panel 243-290; recording targets 1448; checklist 953-1015.
- `types/live.ts`: session words 39-48 (`LIVE_STATE_META`); source words 118-123 (`SOURCE_READINESS_LABEL`); row names 70-80 (`PREFLIGHT_LABELS`); next-step hints 89-103 (`PREFLIGHT_NEXT_STEP`).
- `screens/status-language.ts:31-35` (shared Ready / Check before meeting / Do not broadcast yet words).

## Current text
| String | Where | Source line |
|---|---|---|
| "Operator live room" / "Live" | Header small caps / heading | LiveRoomScreen.tsx:1246, 1248 |
| "Run pre-flight and start only after CivicCast verifies the source, storage, and network from the server." | Page intro | LiveRoomScreen.tsx:1250-1251 |
| "Live action failed." + server text + "Next step. Confirm the CivicCast server is running and connected to its database, then refresh this screen." | Red box after any failed action AND after a load failure | LiveRoomScreen.tsx:1264, 1235, 110-113 |
| "Could not load live room." | Load failure title | LiveRoomScreen.tsx:1235 |
| "Safe to broadcast: Ready / Check before meeting / Do not broadcast yet" + "Resident preview" | Top panel | LiveRoomScreen.tsx:130-134, 173, 185 |
| "Broadcast readiness could not be checked. Do not start the stream." / "Retry the check. If it fails again, open System Health and confirm the CivicCast service and database are ready." / "Retry check" | Panel error | LiveRoomScreen.tsx:143-146, 154 |
| "Live-room controls require the meeting operator role. Source status and readiness checks remain visible." | Role note | LiveRoomScreen.tsx:1275 |
| "Source switcher" / "Arrow keys move between configured meeting sources. A source is only shown as delivering if CivicCast has actually seen media from it in the last {N} seconds." | Source section | LiveRoomScreen.tsx:318-322 |
| "On-air preview" / "CivicCast only shows source media here after server-side verification." | Preview heading, helper | LiveRoomScreen.tsx:907-909 |
| "Source preview unavailable" / "CivicCast has not verified incoming video or audio from {name}. No simulated preview or audio meter is shown." / "Next step. Connect a real encoder or meeting source and run pre-flight. Start Live Stream remains blocked until a server-side media probe passes." | Preview body | LiveRoomScreen.tsx:922-931 |
| "Delivering" / "Needs re-check" / "Not answering" / "Not checked" | Source pills | types/live.ts:118-123 |
| "Check source" / "Checking source..." / "Edit source" | Buttons | LiveRoomScreen.tsx:450, 464 |
| "Editing a source needs the setup admin role. Ask your station admin to change the address or type." | Non-admin note | LiveRoomScreen.tsx:470-471 |
| "Checking a source needs the meeting operator or setup admin role. Ask a meeting operator or your station admin to confirm it is delivering media." | Note | LiveRoomScreen.tsx:476-478 |
| "Saving this change clears what CivicCast knows about this source. You will need to choose Check source again before it can take air." | Edit warning | LiveRoomScreen.tsx:680-681 |
| "Someone else changed this source while you were editing it. Your changes were kept ..." | Edit conflict | LiveRoomScreen.tsx:1214-1215 |
| "Remote ingest status is unavailable. Local encoder sources can still run from this room." | Ingest error | LiveRoomScreen.tsx:738 |
| "No meeting source is configured for this channel yet. Add a camera, encoder, or sample source above before running pre-flight -- CivicCast has no listener at any default address until you do." | Ingest, no paths | LiveRoomScreen.tsx:761-763 |
| "Choose a camera or test source" / "Open camera and test media setup" / "Needs IT help" | No-source card | LiveRoomScreen.tsx:858, 867, 880 |
| "No meeting source is ready yet. Open Setup and choose a camera or test video." | Guidance failed | LiveRoomScreen.tsx:840-844 |
| "Session controls" / "Broadcast channel" / "Channel is fixed while a session exists." / "The session and ingest plan use this channel." | Right column | LiveRoomScreen.tsx:1332, 1339, 1364-1365 |
| "Create live session" / "Start pre-flight" / "Run pre-flight" / "Start Live Stream" / "End Live Stream" | Buttons | LiveRoomScreen.tsx:1376, 1385, 1404, 1424, 1440 |
| "Operator confirms the meeting details and acknowledges the server-side pre-flight result." | Checkbox | LiveRoomScreen.tsx:1394-1395 |
| "End the live stream?" / "Residents watching the live stream lose it immediately. The session moves to finalization and cannot be resumed from here — start a new live session to go live again." / "End live stream" | Confirm box | LiveRoomScreen.tsx:1430-1432 |
| "Recording finalization" / "Waiting" / "The finalization worker picks the recording up within a few seconds of End Live Stream. This panel updates automatically." | Panel | LiveRoomScreen.tsx:243-258 |
| "Recording saved as asset {id}. Find it in the Assets library." / "Finalization failed." / "Attempt N of M. The recording is being checked and packaged." / "Retry finalization" | Panel | LiveRoomScreen.tsx:263-264, 270, 287-288, 280 |
| "Recording targets: N" | Footer | LiveRoomScreen.tsx:1448 |
| "Pre-flight checklist" / "Every failed item includes the backend reason and a next action." | Checklist header | LiveRoomScreen.tsx:953-955 |
| "Run pre-flight to populate the nine-check contract." | Empty checklist | LiveRoomScreen.tsx:960 |
| "{N} pre-flight check(s) must pass before this room can go live. Each failed item below says what to do next." | Failed summary | LiveRoomScreen.tsx:974-977 |
| "Network reachable", "Recording storage", "AI runtime", "Live source", "Recording target", "Operator confirmation", "Syndication", "Internet Archive", "NAS handoff" | Row names | types/live.ts:70-80 |
| "Check the confirmation box below, then select Run pre-flight again." | Row hint | types/live.ts:101 |
| "Idle", "Pre-flight", "On air", "Ending", "Recorded", "No session", "Pre-flight ready", "Pre-flight blocked" | Pills | types/live.ts:39-48; LiveRoomScreen.tsx:1258, 1260 |

## What the screen really does
The Live screen walks one meeting through a fixed order: choose a configured source, create a live session, run nine checks, mark the session "On air", later end it. "Start Live Stream" and "End Live Stream" change only the live-session record and the public "on air" status. They do not start, stop or switch the channel's video feed (Channels does that). The session is held only in the open page, with a fixed id, so a refresh loses it and a second "Create live session" is refused. "Source switcher" only chooses which source the checks test. No video is ever shown. After End, a worker waits for a recording file named after the session in the recording location and makes it an asset.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | Dialog: "Residents watching the live stream lose it immediately." | End only sets state to Ending and stamps ended_at (`civiccast/live/router.py:736-773`); no feed command. Channel keeps broadcasting. | misleading (can leave a channel on air) |
| HELP-02 | "...start a new live session to go live again." | Session id is fixed `council-live-room` (LiveRoomScreen.tsx:64, 1136); a repeat create returns 409 "LiveSession already exists: council-live-room" (`router.py:529-535`). | blocks work |
| HELP-03 | (nothing) | Session lives in `useState(null)` (:1025); refresh returns to "Create live session" and disables End. | blocks work |
| HELP-04 | Every failure ends "Confirm the CivicCast server is running ... then refresh this screen." | Same ErrorPanel is used for role, 409 pre-flight and duplicate errors (:110-113, 1264). "Refresh" loses the session. | misleading |
| HELP-05 | "populate the nine-check contract" | Jargon (:960). | cosmetic |
| HELP-06 | "Start pre-flight" and "Run pre-flight" | Start only moves Idle to Pre-flight, runs nothing (`router.py:567-607`). | misleading |
| HELP-07 | "Check the confirmation box below" | Box is in Session controls, above the checklist (types/live.ts:101). | cosmetic |
| HELP-08 | "Source switcher" + arrow keys | Selecting a card switches nothing on air (:318-322, 1292). | misleading |
| HELP-09 | "On-air preview ... shows source media here after server-side verification" | No code path draws video; permanent placeholder (:907-931). | misleading |
| HELP-10 | "Network reachable", "Recording storage" | Network = reach 1.1.1.1 then 8.8.8.8 on port 443, 3 s each (`network_probe.py:43-52`): needs internet. Storage = at least 50 GiB free on the CivicCast data drive, not the recording target (`preflight.py:195`). | blocks work |
| HELP-11 | "Safe to broadcast" panel | Reflects the last System Health rehearsal, not this page's pre-flight (`LiveRoomScreen.tsx:1266`; `civiccast/installer/service.py:3668-3674`); text says "System Health" while the nav item is "Readiness" (Sidebar.tsx:177). | misleading |
| HELP-12 | "Retry finalization" shown to all | Backend allows only meeting_operator (`router.py:824`). | cosmetic |
| NEW-1 | "picks the recording up within a few seconds of End Live Stream" (:257) | Worker waits for `<recording target>\<session id>.mp4`; gives up after 1800 s (`finalization_worker.py:113`, 452). Nothing on this screen creates the file. | misleading |
| NEW-2 | "Every failed item includes the backend reason" (:955); "acknowledges the server-side pre-flight result" (:1394) | Jargon ("backend", "server-side"). | cosmetic |

## Proposed text
Use these strings as-is. Where a line says "after fix", use the first text now and the second after the coder change.

- Page intro (:1250): "Use this screen to check that the source, the recording drive and the internet connection are ready, and to record that a meeting is live. It does not start or stop the channel's video. Use Channels for that. Needs the Meeting operator role."
- New line under the heading: "Do not refresh this page or open another screen in this tab during a meeting. This screen forgets your session if you do. Open Channels in a second tab. (After fix: remove this line once the session is reloaded from the server.)"
- Action error footer (:110-113, action errors only): drop the fixed "Next step". Show: "Read the message above. Do not refresh this page during a meeting." Load errors keep: "Next step. Check that the CivicCast service is running, then reload this page."
- Safe-to-broadcast title note: "This panel shows the result of the last test run on the Readiness screen. It is not the checklist below."
- "Source switcher" heading (:318) becomes "Choose a meeting source". Helper (:320-322): "Pick the source the checklist will test. This does not put the source on the air. A source shows Delivering only if CivicCast saw video from it in the last {N} seconds. Press Check source right before you go live."
- "On-air preview" (:907) becomes "Video preview". Helper (:909): "This version does not show video here. Watch your own monitor or the channel output." After fix: restore the original text.
- Preview body: keep "Source preview unavailable"; replace the Next step with "Press Check source until the source says Delivering."
- "Start pre-flight" (:1385): "Begin checklist". Add above the buttons: "Order: 1 Create live session. 2 Begin checklist. 3 Tick the box. 4 Run pre-flight. 5 Start Live Stream when the channel is really broadcasting."
- Checkbox (:1394): "I confirm the meeting details and have read the checklist result."
- "Start Live Stream" (:1424): tooltip and note: "Marks the session On air and shows 'on air' to residents on the portal. It does not start the channel. No confirmation box. Press it only when the channel is already broadcasting."
- End dialog body (:1431): "This marks the meeting as ended and starts saving the recording. It does not stop the channel. To take the channel off the air, use Stop on the Channels screen. After you end, CivicCast cannot create another live session until IT clears this one." After fix (new id per meeting): "...Start a new live session for the next meeting."
- Finalization waiting text (:257): "CivicCast is looking for the recording file in the recording location. If no file appears within 30 minutes, CivicCast gives up and shows a message here. This panel updates by itself."
- Empty checklist (:960): "Press Run pre-flight to check the source, the recording drive, the internet connection and your confirmation."
- Checklist helper (:955): "A failed item has a red border and tells you what to fix."
- Row text additions (show under the row name): Network reachable: "Needs a working internet connection." Recording storage: "Needs at least 50 GiB free on the CivicCast data drive." Syndication, Internet Archive, NAS handoff: "Reported only. Does not stop you going on air." AI runtime: "Optional."
- Row hint (types/live.ts:101): "Tick the confirmation box in Session controls, then select Run pre-flight again."
- Retry finalization: show to everyone but add "Needs the Meeting operator role." when the role is missing.
- Who can use this (new, top of page): "Anyone signed in can look. Meeting operator: create the session, run the checklist, start and end. Meeting operator or Setup admin: Check source. Setup admin: Edit source."

## Notes for the coder
- Edit `screens/LiveRoomScreen.tsx` (lines above) and `types/live.ts:98-101`. `ErrorPanel` (:99-116) is shared by load errors and action errors: give it a `kind` prop.
- Tests pinning strings: `e2e/live-room.spec.ts` pins "Create live session", "Start pre-flight", "Run pre-flight", "Start Live Stream", "End Live Stream", the dialog name "End the live stream?" and button "End live stream" (lines 497-515, 657-685, 745-806), the text /Resolve the item above, then select Run pre-flight again/ (685), /connected to its database/ (load error, 665), "Source preview unavailable" and /No simulated preview or audio meter is shown/ (525-527). `screens/LiveRoomScreen.test.tsx` pins "Source preview unavailable", "Delivering", "Needs re-check", "Not answering", "Check source", "Checking source...", "Edit source", "Save source", /clears what CivicCast knows/, /Server now has/. If you rename "Start pre-flight" update the e2e role names.
- Code fixes, not text fixes: (1) load the open session on mount, or show existing sessions (HELP-03); (2) new session id per meeting (HELP-02); (3) make End Live Stream stop the channel feed or document it (HELP-01); (4) draw a real preview or remove the panel (HELP-09); (5) gate "Retry finalization" by role (HELP-12); (6) decide whether the Safe-to-broadcast panel should include the pre-flight result (HELP-11).
- Not verified: who writes `<session id>.mp4` (UNVERIFIED-02 in the inventory); whether GET reads on the live router have role gates.
