# Remote Contribution (nav id: remotecontribution)

Console group: Run Meeting. Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` ("Bring in remote guests") and `ops/docs-sprint/inventory/screens/remotecontribution.md`. Line numbers re-checked in the .tsx.

## Where the help text lives now
- `screens/RemoteContributionScreen.tsx`: access refusal 253-254; header 268-272; not-configured alert 282-284; rooms card 291-324; selected-room card 328-408; open/close buttons 351, 367; close dialog 357-359; director link 373; invite form 547-575; invite list 585-593; guest tray 617-676; drop dialog 664-669; diagnostics 413-429 and 756-806.
- `screens/contribution-format.ts` (room, guest, quality, role words, lines 14-83).
- Server messages: `civiccast/live/contribution/router.py:147-150` (not configured), `service.py:358-362` (takeover failed), `:57` (4-hour invite).

## Current text
| String | Where | Source line |
|---|---|---|
| "Remote Contribution" / "Bring remote council members, presenters, and public comment onto the channel over the browser via self-hosted VDO.Ninja — no install for the guest." | Heading, intro | RemoteContributionScreen.tsx:268, 271-272 |
| "You don’t have access to the remote-contribution console. It is available to meeting operators, setup admins, and support admins." | Refusal | RemoteContributionScreen.tsx:253-254 |
| "Remote contribution isn’t configured yet. A compositor (the GStreamer wpesrc engine or OBS) plus self-hosted VDO.Ninja and coturn must be commissioned before guests can reach the channel. See the diagnostics drawer for status." | Amber alert | RemoteContributionScreen.tsx:282-284 |
| "Rooms" / "setup admin can create" | Card, tag | RemoteContributionScreen.tsx:291-292 |
| Placeholders "Room name (e.g. Council Chamber Guests)" / "Channel id (e.g. gov-ch-1)" / "Create room" | Create form | RemoteContributionScreen.tsx:498, 506, 517 |
| "Could not create the room." / "Could not load rooms." | Errors | RemoteContributionScreen.tsx:297, 302 |
| "No contribution rooms yet." / "Contribution rooms let remote presenters send live video into this station from a web browser — no studio visit needed. Create a room above and its invite links appear here." | Empty | RemoteContributionScreen.tsx:306-307 |
| "Select a room" / "Choose a room to open it, send guest invites, and run the guest tray." | Right card | RemoteContributionScreen.tsx:328, 331 |
| "channel {id} · up to {N} guests" | Room line | RemoteContributionScreen.tsx:338 |
| "Open room" / "Close room" | Buttons | RemoteContributionScreen.tsx:351, 367 |
| `Close "{room}"?` / "Every guest connected right now is disconnected immediately and the room stops accepting contribution. If the meeting is live, their video/audio drops from the broadcast the instant you confirm. You can reopen the room and re-invite guests afterward." / "Close room now" | Close dialog | RemoteContributionScreen.tsx:357-359 |
| "Director view (embed in your switcher)" / "Copy" / "Copied" | Link box | RemoteContributionScreen.tsx:373, 133 |
| "Generates a single-use browser link — no install required for the guest." / "Guest name" / "Contribution role" / "Generate invite link" | Invite form | RemoteContributionScreen.tsx:547, 552, 560, 574 |
| "Council member" / "Presenter" / "Public comment" | Role menu | contribution-format.ts:33-35 |
| "Guest link for {name} — send this" / "Could not mint the invite." | Link box, error | RemoteContributionScreen.tsx:389, 384 |
| "Sent invites (N)" / "Used" / "Pending" | Invite list | RemoteContributionScreen.tsx:585, 593 |
| "Guests (N)" / "No guests connected. Send an invite link to bring one in." | Guest tray | RemoteContributionScreen.tsx:617, 621 |
| "Admit" / "On air" / "Mute" / "Off air" / "Drop" | Guest buttons | RemoteContributionScreen.tsx:646, 649, 655, 658, 661 |
| `Drop {name}?` / "{name} is on air right now — dropping ends their connection immediately and their video/audio cuts from the broadcast mid-session. They would need a new invite to rejoin." / "Ends {name}'s connection to this room immediately. They would need a new invite to rejoin." / "Drop guest" | Drop dialog | RemoteContributionScreen.tsx:664-669 |
| "In waiting room", "On air", "Muted", "Invited", "Joining", "Dropped", "Ended"; Idle, Open, Live, Closing, Closed; Unknown, Good, Degraded, Poor | Tags | contribution-format.ts:14-20, 42-48, 62-65 |
| "Action failed — please retry." | Guest action error | RemoteContributionScreen.tsx:403 |
| "Diagnostics" / "TURN reachable/unreachable" / "VDO up/down" / "coturn up/down" | Diagnostics | RemoteContributionScreen.tsx:413, 756-758 |
| "Remote contribution requires a compositor (the GStreamer engine or OBS) plus self-hosted VDO.Ninja and a reachable TURN server ... guests cannot reach the channel until they are commissioned." | Diagnostics warning | RemoteContributionScreen.tsx:774-778 |
| "No local coturn process, but TURN is reachable — expected for a documented external TURN server (see below)." / "ICE: {summary}" / "Test TURN connectivity" / "How to point this station at coturn" | Diagnostics | RemoteContributionScreen.tsx:767-768, 771, 790, 806 |
| "Channel takeover failed; guest {id} not placed on-air." | Server error | civiccast/live/contribution/service.py:358-362 |

## What the screen really does
Remote Contribution manages rooms, invite links and a guest list for people joining from a web browser. The video itself is handled by separate software (VDO.Ninja and a compositor) that must be set up first. A guest's "On air" button marks that guest on air and also switches the whole channel to its live source, the same as Take live on Channels, for up to one hour, with no confirmation and under the name "remote-contribution". Mute, Off air, Drop and Close room change CivicCast's records only; in the code read, nothing tells VDO.Ninja, the compositor or the channel to cut anything. Nothing here returns the channel to its schedule when guests leave. An invite link works once and expires after 4 hours.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | Button "On air" | Also takes the whole channel live (`civiccast/app.py:3094-3104`), no confirmation, audit name "remote-contribution". | blocks work (changes what is on the air) |
| HELP-02 | Close and Drop dialogs: guests are "disconnected immediately", video "cuts from the broadcast" | Records only (`service.py:207-216, 381-395`); no call to VDO.Ninja or the channel found. | misleading |
| HELP-03 | Screen lets setup_admin in (:57) | Room list/detail need meeting_operator or support_admin (`router.py:60`); a setup admin sees a refusal instead of rooms. | misleading |
| HELP-04 | Placeholder "Channel id (e.g. gov-ch-1)" | Free text; real default id is `government`; a typo makes On air fail later. | misleading |
| HELP-05 | "Director view (embed in your switcher)" | Jargon; it is the page the operator keeps open to see and arrange guests. Shown only right after Open room. | cosmetic |
| HELP-06 | "compositor", "wpesrc", "coturn", "TURN", "ICE" | Never explained; setup is not possible from this screen. | cosmetic |
| HELP-07 | "single-use browser link" | Also expires after 4 hours (`service.py:57`); Public comment guests must accept terms first (`service.py:272-280`). | misleading |
| HELP-08 | "Mute", "Off air" | Records only (UNVERIFIED in inventory). A Muted guest has no Mute or Off air button, only On air and Drop. | misleading |
| NEW-1 | "Admit" (tag stays "In waiting room" after admitting) | Admit keeps state Connected (`service.py:315-321`); only the Admit button disappears and On air turns on. | misleading |
| NEW-2 | Empty text "Create a room above" (:307) | Only Setup admin sees the create form; others read an instruction they cannot follow. | cosmetic |
| NEW-3 | Director and guest link boxes | Shown only right after the click; lost on reload or room change; invite list shows names only (:372, 387). | misleading |

## Proposed text
- Intro (:271-272): "Use this screen to let remote guests (council members, presenters, public commenters) join from a web browser. CivicCast keeps the rooms, invite links and guest list. Separate software (VDO.Ninja and a video mixer) does the video and must be set up first by IT."
- Who can use this (new): "Setup admin: create a room. Meeting operator: open and close rooms, invite, admit, put guests on air. Support admin: can see rooms and run the connection test. A Setup admin without the Meeting operator or Support admin role can create a room but cannot see it."
- Refusal (:253): "Remote Contribution needs the Meeting operator, Setup admin or Support admin role."
- Create form placeholders: "Room name (for example Council Chamber Guests)" and "Channel id: copy it exactly from the Channels screen (for example government)". After fix: replace the id box with a channel menu.
- Empty rooms text (:307): "No rooms yet. A Setup admin creates a room, then a Meeting operator opens it and sends invite links."
- Director box label (:373): "Director link: keep this page open to see and arrange your guests. It is shown only now. If you reload, click Open room again."
- Guest link label (:389): "Guest link for {name}. Send it to them now. It works once and expires after 4 hours. It will not be shown again."
- Invite helper (:547): "Makes a one-time link. The guest needs nothing installed. It expires after 4 hours. Public comment guests must accept terms before they can join."
- Guest buttons (add a line above the tray): "Admit lets a guest out of the waiting room. The tag still says 'In waiting room' until you press On air."
- "On air" button: tooltip and line under the tray: "On air shows this guest and also switches the whole channel to its live source for up to one hour, like Take live on Channels. No confirmation box. Make sure the live source passes Check source on the Live screen first." After fix (confirm added): "Confirm: put {name} on air and switch the channel to live?"
- Mute and Off air: "These change CivicCast's record only. They may not silence or hide the guest. Mute them in VDO.Ninja too and listen to the channel." After fix: remove.
- Drop dialog bodies (:667-668): on air: "{name} is on air right now. CivicCast marks them as dropped and they need a new invite to rejoin. This may not cut their video or sound. Check VDO.Ninja and the channel." Not on air: "CivicCast marks {name} as dropped. They need a new invite to rejoin."
- Close dialog body (:358): "This marks the room closed and every guest as ended. It may not disconnect guests or remove them from the picture. It does not return the channel to its schedule. Use Return to schedule on Channels. You can reopen the room and send new invites."
- Add after the guest tray: "When guests leave, the channel stays on its live source until you press Return to schedule on Channels."
- Not-configured alert (:282-284): "Guest video is not set up on this station. Tell your IT person. It needs VDO.Ninja, a video mixer and a TURN relay (a server that helps guests behind firewalls connect). The Diagnostics box shows what is missing."
- Diagnostics warning (:774-778): same sentence with "compositor" written as "video mixer", "TURN" explained once as above.
- Glossary line (new): "Room: one session with a guest list. Director link: the control page for the room. Guest link: the one-time link a guest opens."

## Notes for the coder
- Files: `screens/RemoteContributionScreen.tsx`, `screens/contribution-format.ts`; server strings in `civiccast/live/contribution/service.py` and `router.py:147-150`.
- Tests that pin strings: `screens/RemoteContributionScreen.test.tsx` pins "In waiting room", "Admit", "On air", "Guests (1)", "Drop", "Drop guest", "Cancel", dialog text 'Drop Jane?' and 'on air right now' (lines 143, 158), /requires a compositor/ (181, 209, 220), "TURN unreachable", "TURN reachable", /No local coturn process, but TURN is reachable/ (210). Keep those substrings or update the tests. `Sidebar.test.tsx:19, 50, 56` pins the nav label "Remote Contribution".
- Code fixes, not text fixes: confirm box and real operator name on guest On air (HELP-01); make Mute, Off air, Drop and Close actually reach the compositor and VDO.Ninja, or confirm in the lab that they do (HELP-02, HELP-08); hand the channel back when the last guest leaves (inventory UNVERIFIED-03); align read roles with the server (HELP-03); channel menu instead of free text (HELP-04); keep the director and guest links visible after reload or show them again.
- Not verified: the real effect of Mute, Off air, Drop and Close on a VDO.Ninja connection; the guest-side invite page (see public-contribute inventory).
