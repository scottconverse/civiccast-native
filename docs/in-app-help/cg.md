> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# CG Board (nav id: cg)

Console group: Run Meeting. Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/screens/` unless they start with `civiccast/`. Authority: `docs/manual/src/13-running-meeting.md` ("Show community bulletins between programs (CG Board)") and `ops/docs-sprint/inventory/screens/cg.md`. Line numbers re-checked in `CgBoardScreen.tsx`.

## Where the help text lives now
- `CgBoardScreen.tsx`: heading and subtitle 712-715; channel menu 718-735; error 741; template buttons 75-99, 745-754; layout preview 104-186 (heading 126); output paths 660-686; dynamic feeds 597-657; community bulletins panel 378-590; add form 203-280; moderation dialog 282-376, 564-590; status words 192-200.
- `civiccast/cg/router.py:630, 647, 681` (role gates) and `:655-662` (storage message). `ChannelOpsScreen.tsx:957-958` (where bulletins are switched on).

## Current text
| String | Where | Source line |
|---|---|---|
| "CG Board" | Heading | CgBoardScreen.tsx:712 |
| "Build the between-streams board, live ticker, schedule zones, and streaming output contract." | Subtitle | CgBoardScreen.tsx:714 |
| "Channel" / "Public board" | Menu | CgBoardScreen.tsx:718, 729 |
| "CG board could not load." (or the server text) | Red box | CgBoardScreen.tsx:741 |
| "Template library" + template label + "{N} regions / {ratio}" | Template row | CgBoardScreen.tsx:745, 98 |
| "Visual layout editor" / template id / proof-boundary pill / "Loading template…" / "Loading…" | Preview panel | CgBoardScreen.tsx:126, 128, 135 |
| Region names "Main", "Lower", "Side", "Bug", "Background"; "{zone kind} / {source or 'source-pending'}"; "Unassigned" | Zone boxes | CgBoardScreen.tsx:38-43, 178, 61 |
| "Output paths" and three URLs or "Loading…" | Right column | CgBoardScreen.tsx:663-680 |
| "Dynamic feeds" / "Loading configured feeds…" / "Could not load configured feeds." | Right column | CgBoardScreen.tsx:611, 615, 625 |
| "No dynamic feeds are configured." / "Add an approved RSS, calendar, weather, or permitted social source before using feed-driven CG zones." | Empty feeds | CgBoardScreen.tsx:631-632 |
| "Community bulletins" / "Add bulletin" / "Close" | Panel header | CgBoardScreen.tsx:454, 461 |
| "Approved bulletins air as branded filler slides between programs on channels set to “Community bulletins”." | Panel help | CgBoardScreen.tsx:465-466 |
| "Organization" / "Submitted by" / "Title" / "Message" / "Add bulletin" / "Adding…" | Add form | CgBoardScreen.tsx:226-228, 243, 270 |
| "Submitted" / "Needs changes" / "Approved" / "Scheduled" / "Declined" / "Notes: {note}" | Tags | CgBoardScreen.tsx:196-200, 513 |
| "Approve" / "Request changes" / "Decline" | Row buttons | CgBoardScreen.tsx:525, 536, 547 |
| "Request changes" / "What needs to change before this bulletin can air?" / "Send request" / "Cancel" | Dialog | CgBoardScreen.tsx:564-570, 362 |
| "Decline bulletin" / "Why is this bulletin declined? (Required.)" | Dialog | CgBoardScreen.tsx:564-570 |
| "Enter a note before submitting — it tells the submitter what to fix." / "Request changes cancelled — no note was sent." / "Decline cancelled — the bulletin was not declined." | Toasts | CgBoardScreen.tsx:318, 586-587 |
| "Your staff identity has not loaded yet — try again in a moment." | Error | CgBoardScreen.tsx:434 |
| "Could not load the bulletin queue." / "Could not add the bulletin." / "Could not update the bulletin." | Errors | CgBoardScreen.tsx:471, 415, 425 |
| "No bulletins yet." / "The community board runs station and community announcements on this channel between programs. Add the first bulletin above to get it started." | Empty queue | CgBoardScreen.tsx:485-486 |
| "Durable storage is not ready. Open Setup and choose Prepare storage before managing community bulletins." | Server error | civiccast/cg/router.py:658-660 |
| "Rotates approved bulletin-board slides; falls back to slate when none are approved." | Channels, "Community bulletins" card | ChannelOpsScreen.tsx:958 |

## What the screen really does
CG Board shows a read-only preview of the community board for one channel and holds the queue of community bulletins. Staff add a bulletin (organization, submitter, title, message; all four required), then Approve it, send it back with Request changes, or Decline it. An approved bulletin may be shown as a slide between programs, but only on a channel whose "Between programs, show" setting on the Channels screen is "Community bulletins". The template buttons change only the preview and save nothing. Zones, feeds and the template itself are edited on CG Designer. The bulletin queue needs the Setup admin or Publish operator role; other roles see the server's role message in a red box.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "Build the between-streams board, live ticker, schedule zones, and streaming output contract." | The screen builds only bulletins; layout, zones and feeds are on CG Designer. | misleading |
| HELP-02 | "Visual layout editor" | Read-only preview; template buttons do not save and do not change what airs. | misleading |
| HELP-03 | Panel visible to all signed-in roles | Bulletin calls need setup_admin or publish_operator (`civiccast/cg/router.py:630, 647, 681`); others see "This action requires one of these CivicCast roles: publish_operator, setup_admin." | misleading |
| HELP-04 | "...channels set to 'Community bulletins'." | No pointer to where that is set (Channels, "Run this channel 24/7", "Between programs, show"). A new bulletin starts as Submitted and does not air until Approved. | misleading |
| HELP-05 | "Add an approved RSS, calendar, weather, or permitted social source before using feed-driven CG zones." | Says nowhere to add it (CG Designer, Add feed). | cosmetic |
| HELP-06 | "source-pending", proof-boundary pill, feed kinds | Raw technical strings shown to operators. | cosmetic |
| HELP-07 | "Public board" | Is channel id `public`, not a real channel; meaning unexplained (UNVERIFIED). | cosmetic |
| HELP-08 | Two buttons labelled "Add bulletin" | Header toggle and form submit share a name. | cosmetic |
| NEW-1 | Empty text "Add the first bulletin above" | The Add button is at the top of this same panel; wording is loose. Also no start or end date can be set; a bulletin is eligible as soon as it is approved. | cosmetic |
| NEW-2 | "Scheduled" tag | Defined in the screen (:199) but nothing on this screen sets that state. | cosmetic |

## Proposed text
- Subtitle (:714): "Preview the community board and approve community bulletins for each channel. To change the board's layout, zones or outside feeds, use CG Designer."
- Who can use this (new): "Anyone signed in can look at the preview. Setup admin or Publish operator can add, approve, send back and decline bulletins. Other roles see a refusal."
- Role refusal (replace raw server message when the call returns 403): "Managing bulletins needs the Publish operator or Setup admin role."
- "Visual layout editor" (:126) becomes "Layout preview". Add under it: "Choosing a template here only changes this preview. It does not save anything or change what airs. Change the board on CG Designer."
- "Public board" caption: "Public board: the default board for the resident web portal." Use only after the coder confirms this meaning.
- Panel help (:465-466): "An approved bulletin can appear as a slide between programs. This happens only on a channel whose 'Between programs, show' setting (Channels, Run this channel 24/7) is 'Community bulletins'. If no bulletins are approved, the channel shows the station slate. A new bulletin does not air until you press Approve."
- Add form: rename the submit button (:270) to "Save bulletin". Add a line above the fields: "All four boxes are required. Limits: 160 characters for Organization and Submitted by, 200 for Title, 500 for Message. There is no start or end date. An approved bulletin stays eligible until you decline it."
- Row buttons: "Approve" keep, add one line under the list: "Approve has no confirmation box. Once approved, the bulletin can air at once. Decline pulls a bulletin that is airing. A declined bulletin cannot be approved again here. Add a new one instead."
- Empty queue (:486): "No bulletins yet. Press Add bulletin at the top of this box to write the first one."
- Empty feeds (:632): "No outside news, calendar or weather feeds are connected. A Setup admin or Publish operator adds one on CG Designer, under Add feed."
- Zone boxes: show "not connected yet" instead of "source-pending" (:178). Replace the proof-boundary pill text (:135) with a short caption or hide it.
- Storage error (`router.py:658-660`): "The station's database is not ready. Tell your IT person to run Prepare storage in Setup."

## Notes for the coder
- Files: `CgBoardScreen.tsx` (all text), `civiccast/cg/router.py:658-660`, `ChannelOpsScreen.tsx:958` (no change needed).
- Tests that pin strings: `CgBoardScreen.test.tsx` pins "Loading template…", "Loading…", the template id and "S6 V1" (:106-107), "Loading configured feeds…", "No dynamic feeds are configured." and its body text (:184-186), "Request changes", "Send request", "Decline", "Decline bulletin" and the placeholder 'What needs to change before this bulletin can air?' (:268-292). `e2e/cg-bulletins.spec.ts:168` pins the heading "Community bulletins"; lines 234 and 239 click "Add bulletin" twice (header, then `.last()` for the submit), so renaming the submit to "Save bulletin" needs that spec changed. `e2e/channel-app-config.spec.ts:449` pins the radio "Community bulletins". `tests/cg/test_board_api.py` is server-side only.
- Code fixes, not text fixes: gate or hide the bulletin panel by role (HELP-03); add air-from and air-until fields (the server supports them); allow re-approving a declined bulletin or say it cannot be done; set `tone` and meaning for "Scheduled" or remove it.
- Not verified: that the "Public board" option means the resident-portal default; how often and in what order approved bulletins rotate on air; that a bulletin actually appeared on a running channel (the manual states this was not watched).
