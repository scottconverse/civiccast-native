> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Control Room (nav id: controlroom)

Console group: Run Meeting. The page heading reads "Production Control Room". Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` ("Open a Control Room session" and following) and `ops/docs-sprint/inventory/screens/controlroom.md`. Line numbers re-checked in the .tsx.

## Where the help text lives now
- `screens/ControlRoomScreen.tsx`: role refusal 530-533; header 558-561; helper-down bar 567-568; readiness load states 573-575; devices 113-139, 579-583; surface menu 587-597; mode, prerequisites, open button 604-664; end dialog 671-676; banners 252-279; Safe State panel 281-338; cue buttons 203-216; audit 403-406; result banners 720-744; support bundle 352-381.
- `screens/ControlRoomReadinessPanel.tsx`: unverified note 143-146; headline and tags 155-160; counters 175-179; recovery text 74-78; "Technical detail" 85, 168; "LPM profile coverage" 230.
- `screens/control-room-format.ts` (device kinds, cue actions, health words). `civiccast/control_room/service.py` (server messages: expiry 237, 312; readiness 62-67, 809). `civiccast/control_room/router.py:216-225` (lock message).

## Current text
| String | Where | Source line |
|---|---|---|
| "Production Control Room" | Heading | ControlRoomScreen.tsx:558 |
| "Drive your OBS / vMix / ATEM / decks via the TSR control service. Cues are previewed before they fire." | Intro | ControlRoomScreen.tsx:560-561 |
| "Production control unavailable — the TSR control service is not running or not configured. Cues cannot fire until it is restored." | Amber bar (only after a failed probe, dry run or fire) | ControlRoomScreen.tsx:567-568 |
| "The Production Control Room requires the publish/meeting operator, setup admin, or support admin role. Ask your station admin for access." | Role refusal | ControlRoomScreen.tsx:531-532 |
| "Checking control-room readiness..." / "Could not load control-room readiness. {detail}" | Readiness states | ControlRoomScreen.tsx:573, 575 |
| "You can register switchers and run dry runs now. On-air readiness is confirmed once a check against the room's actual devices passes." | Permanent amber note | ControlRoomReadinessPanel.tsx:144-145 |
| "Control-room readiness" + headline tag + "Equipment verified" / "Equipment check pending" | Readiness card | ControlRoomReadinessPanel.tsx:155-160, 104-105 |
| "Devices", "Surfaces", "Cues", "Open sessions", "On-Air" | Counters | ControlRoomReadinessPanel.tsx:175-179 |
| "Open Control Room Setup to start or reconnect the local control service before On-Air use." | Recovery text for the helper check | ControlRoomReadinessPanel.tsx:76 |
| "Open Control Room Setup" / "Technical detail" / "LPM profile coverage" | Button / disclosures | ControlRoomReadinessPanel.tsx:219, 85, 230 |
| "Devices" / "No devices to operate yet." / "The Control Room drives this station's registered production gear — switchers, routers, players — during a live meeting. Register a device in Control Room Setup and it appears here, ready to probe and operate." | Devices | ControlRoomScreen.tsx:579, 116-117 |
| "Probe" / "Probing…" | Chip button | ControlRoomScreen.tsx:139 |
| "Reachable", "Unreachable", "Disabled", "Not probed", "Healthy", "Never probed", "Stale — probe again" | Chip tags | control-room-format.ts:62-86 |
| "Could not load devices." / "Could not load surfaces." / "Could not load this surface." / "Loading cues for this surface..." | Errors | ControlRoomScreen.tsx:581, 589, 603, 602 |
| "Control surface" / "Select a surface…" | Menu | ControlRoomScreen.tsx:587, 594 |
| "Read-only — opening a session and firing cues requires the meeting operator role." | Role note | ControlRoomScreen.tsx:605 |
| "Test Mode" / "On-Air Mode" | Radio | ControlRoomScreen.tsx:614, 621 |
| "On-Air Session is blocked until readiness passes. {first blocker}" | Warning | ControlRoomScreen.tsx:628 |
| "Ready:" / "Needs attention:" + "Control-room readiness", "Safe-state cue selected", "On-Air responsibility acknowledged" | Prerequisites | ControlRoomScreen.tsx:550-553, 634 |
| "Select safe-state cue..." / "I understand On-Air cue actions may be sent to production devices" | Menu / checkbox | ControlRoomScreen.tsx:643, 650 |
| "Open Test Session" / "Open On-Air Session" / "Opening..." | Button | ControlRoomScreen.tsx:662 |
| "Test session open" / "On-Air session open" | Pill | ControlRoomScreen.tsx:667 |
| "End the control room session?" / On-Air body "This releases the operator lock ... until a new session is opened." / Test body (no first clause) / "End session" | Confirm box | ControlRoomScreen.tsx:671-676 |
| "ON-AIR MODE - cue actions can be sent to production devices. Safe-state cue: {id}." / "TEST MODE - device actions are blocked and recorded as test-only audit events." | Mode banners | ControlRoomScreen.tsx:269-270, 276 |
| "On-Air session expires in {time} at {deadline}." / "On-Air session expired at {deadline}. Normal cues are paused. Panic can still run the safe-state cue; end this session to release the surface." | On-Air deadline status | ControlRoomScreen.tsx: session expiry status |
| "Checking the current session and operator lock..." / "Another operator owns this surface's active ... session. It is read-only to you" / "Force-close session" | Session restore, foreign-owner lock and authorized release | ControlRoomScreen.tsx: active surface session panel |
| "Program feed: {source or 'not bound to a live source yet'}" / "This console produces the source. Taking it to air on a channel is a Playout (S5) action — it is not fired from here." | Feed banner | ControlRoomScreen.tsx:255-256, 258-259 |
| "{label} is the configured recovery cue for this session." / "No safe-state cue is configured for this session." | Safe State panel | ControlRoomScreen.tsx:308-309 |
| "Dry Run Safe State" / "Panic: Run Safe State" / "Record Safe State Test" / "Panic sends the configured safe-state cue immediately, including after the On-Air deadline." | Safe State buttons and help text | ControlRoomScreen.tsx: Safe State panel |
| "Test... (needs confirm)" / "Fire... (needs confirm)" / "Confirm test action" / "Record test action" / "Confirm fire" / "Fire cue" / "Cancel" | Cue buttons | ControlRoomScreen.tsx:203-206, 238 |
| "Ready to send" / "Not ready" / "dry-run {12 chars}" / "take-delay Nms · post-roll Nms" / "Next: {action}" | Plan card | ControlRoomScreen.tsx:157, 160, 165, 171 |
| "This surface has no cues yet." | Empty | ControlRoomScreen.tsx:716 |
| "Fired-cue audit" / "No cues fired this session yet. Every cue you fire is logged here for the record." / "Planned" "Fired" "Failed" | Audit | ControlRoomScreen.tsx:403, 406; control-room-format.ts:90 |
| "Rolled back to Safe State." / "Test action recorded." / "Cue fired." | Result banners | ControlRoomScreen.tsx: result banners |
| "Could not dry run the cue." / "Could not fire the cue." / "Could not open the session." | Fallback errors | ControlRoomScreen.tsx:720, 723, 687 |
| "On-Air Mode expired before this cue could fire. Open a new On-Air session to continue." | Server error | civiccast/control_room/service.py:312 |
| "A session is already open on this surface, locked by {name} since {time}. A setup admin or support admin can force-close it to release the lock." | Server error | civiccast/control_room/router.py:219-225 |
| "Support bundle" / "Create a redacted troubleshooting bundle and review the contents before sharing it." / "Operator note" / "Create support bundle" / "Support bundles require support admin." | Support card | ControlRoomScreen.tsx:355-357, 361, 370, 373 |

## What the screen really does
The Control Room sends commands to production gear (OBS, vMix, ATEM, decks, PTZ cameras, routers) through a small helper program. You open a session on a control surface, preview an ordinary cue (a dry run), then confirm to send it. In Test Mode nothing is sent; an audit row says "Planned". In On-Air Mode ordinary cues are sent to the device. Beta.12 shows the 30-minute session deadline and countdown; at expiry ordinary cue controls pause, while the session owner can still use Panic as long as the session remains open. The selected surface and open session are restored after refresh. Another operator sees the lock read-only; Setup and Support admins can release it after confirmation. Releasing a lock does not undo cues already sent. Panic uses the direct safe-state recovery action and does not require a dry run. The headline can never read "Ready" in beta.10 because "equipment verified" is fixed to false, so "Check before meeting" means the room has not been verified, not that something is broken. This screen does not put anything on a channel.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | Amber note "...confirmed once a check against the room's actual devices passes"; headline | `station_device_ready=False` is hard-coded (`service.py:809`); no screen offers the check, so the note never goes away and the headline cannot be "Ready". | misleading |
| HELP-02 | (nothing about time) | Historical beta.10 finding. Beta.12 shows the deadline/countdown; ordinary cue controls pause at expiry and API fire requests are refused without closing the session, so the owner can still run Panic. | resolved in beta.12 |
| HELP-03 | "Panic: Run Safe State" | Historical beta.10 finding. Beta.12 Panic uses the direct recovery action and does not depend on a dry-run result. | resolved in beta.12 |
| HELP-04 | "requires the publish/meeting operator, setup admin, or support admin role" | `READ_ROLES` (:50) has no publish_operator; a publish operator alone is refused. | misleading |
| HELP-05 | Lock message: "A setup admin or support admin can force-close it" | Historical beta.10 finding. Beta.12 restores the owner's session after refresh and gives Setup/Support admins a confirmed force-close action for another operator's lock. | resolved in beta.12 |
| HELP-06 | "TSR control service", "LPM profile coverage", "Safe State", "Playout (S5)" | Jargon, never explained (:260, 560; Panel :230). | cosmetic |
| HELP-07 | "Test... (needs confirm)" / "Fire... (needs confirm)" | A first-time user cannot tell Test from On-Air except from the banner; Test never touches equipment. | misleading |
| HELP-08 | "Open Control Room Setup to start or reconnect the local control service" | Backend says to set `CIVICCAST_CONTROL_ROOM_TSR_URL` (`service.py:568-575`); Setup may not start the helper (UNVERIFIED). | misleading |
| NEW-1 | "Program feed: not bound to a live source yet" | Not verified that any code binds a source (UNVERIFIED); read as "nothing is connected", not as an error. | cosmetic |
| NEW-2 | Amber bar "Production control unavailable" | Shows only after a probe, dry run or fire has failed; absent on first open even if the helper is down (:59-63, 463, 482). | misleading |

## Proposed text
- Page intro (:560): "Use this screen to send cues (one action each, such as 'switch to camera 2') to your production equipment. You preview each cue first. Test Mode never touches your equipment. This screen does not put anything on a channel. Use Take live on Channels for that."
- Who can use this (new): "Meeting operator: open a session and send cues. Setup admin and Support admin: check devices (Probe). Support admin: create a support bundle. Publish operator alone cannot use this screen."
- Role refusal (:531): "The Control Room needs the Meeting operator, Setup admin or Support admin role. Ask your station admin for access."
- Words: replace "TSR control service" with "production-control helper" everywhere (:560, 567, readiness text). Replace "Playout (S5)" with "Channels" (:259): "This screen produces the picture source. To put it on a channel, use Take live on the Channels screen."
- Readiness note (:144-145): "CivicCast has not checked this room against your real equipment, and this version has no way to do that check. 'Check before meeting' here means 'not verified'. It does not mean something is broken. Rehearse in Test Mode and keep your equipment's own controls within reach." After fix (real check added): original text.
- Helper-down bar (:567): "The production-control helper is not running or cannot be reached, so cues cannot be sent. Tell your IT person. This bar appears only after a check or a cue fails."
- Helper recovery text (:76): "The production-control helper is not running. Ask your IT person to start it."
- Test Mode radio, new line under it: "Test Mode: nothing is sent to equipment. Each cue is only recorded as 'Planned'." On-Air Mode line: "On-Air Mode: cues are really sent to your equipment and can change the picture on the channel."
- On-Air time limit, new line next to the "Open On-Air Session" button: "An On-Air session closes by itself 30 minutes after you open it. Note the time and open a new session before then. Cues already sent are not undone." After fix: show a countdown.
- Panic button note under Safe State panel (:333): "Before an emergency, press Dry Run Safe State so Panic is ready. Pressing Dry Run on any other cue makes Panic grey again. Panic and Roll back send the recovery cue at once with no confirmation box."
- Cue plan card (:151-175): keep the button labels and add this line: "Dry run: shows what would be sent. Nothing has been sent yet."
- Lock message (router.py:219-225): "A session is already open on this surface (opened by {name} at {time} UTC). Ask your IT person to close it. This screen cannot release it." After fix (force-close button): keep original.
- "Fired-cue audit" empty text (:406): "No cues have been sent in this session. Every cue is listed here with Planned (Test Mode), Fired or Failed."
- Warning for session loss, near End session: "Do not refresh this page. CivicCast keeps your session only in the open page. Open Channels in another tab."

## Notes for the coder
- Files: `screens/ControlRoomScreen.tsx`, `screens/ControlRoomReadinessPanel.tsx` (text at 76, 144-145), `civiccast/control_room/router.py:219-225`, `service.py:312`.
- Tests that pin old strings: `screens/ControlRoomScreen.test.tsx:364` pins the role refusal "requires the publish/meeting operator, setup admin, or support admin role"; it pins "Control-room readiness", "Equipment check pending", "Open Test Session", "Open On-Air Session", "Panic: Run Safe State", "Dry Run Safe State", "Create support bundle", "Support bundles require support admin.", /Playout \(S5\) action/ (:201), /TEST MODE - device actions are blocked/ (:213), /Dry Run checks the current device and cue state/ (:188). `screens/ControlRoomReadinessPanel.test.tsx` pins "Equipment check pending", "Check before meeting", "Technical detail" order (:121-131). `e2e/control-room-readiness.spec.ts:342-364` pins "Equipment check pending", "Technical detail", link "Open Control Room Setup" and /Open Control Room Setup to start or reconnect/ (:352). Changing the helper recovery text (:76) needs that e2e line changed.
- Code fixes, not text fixes: a countdown or auto-renew for On-Air sessions (HELP-02); make Panic runnable without a prior dry run (HELP-03); a force-close control (HELP-05); keep the session id across refresh; a real station-device check so `station_device_ready` can be true (HELP-01); drop `publish_operator` mention or allow it (HELP-04).
- Not verified: whether the installer starts the helper (UNVERIFIED-01 in the inventory); what cues do on real OBS/vMix/ATEM hardware; whether `program_feed_source_ref` is ever set.
