> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Contributors (nav id: contribute)

Console group: Review Records. The page heading on screen is "Contributor submissions". Spec for the in-app help of the inbox for programs sent in by outside producers. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`.

## Where the help text lives now
All in `screens/ContributeScreen.tsx`.
- Label, heading, intro: 489-495. Tiles: 499-501. Search box 513-516 and tabs 35-41.
- Card: Media / Media gate / Agreement labels 225, 231, 237; box labels 260, 269, 278, 287, 296; button labels (Start review 320, Request changes 336, Accept 345, Send to schedule 360, Decline 386); Minutes 363; status pill 85; date fallbacks 58, 60.
- Producer activity 122-139; Status notification outbox 152-177.
- Empty 560; filtered-empty 568; error box title 97.
- Handoff values sent by Send to schedule: 448-457. Contributor-facing status messages: `civiccast/contribute/store.py:840-858`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Producer workflow" | Label | ContributeScreen.tsx:489 |
| "Contributor submissions" | Heading (nav says "Contributors") | :491 |
| "Review programs from external producers, keep the broken-media gate visible, and hand accepted content to scheduling without giving contributors operator access." | Intro | :493-495 |
| "Needs action" / "Total submissions" / "Status notices" | Tiles | :499-501 |
| "Search title, producer, or tag..." | Search | :516 |
| All, Submitted, Reviewing, Needs changes, Accepted, Scheduled, Declined (no Published tab) | Tabs | :35-41 |
| "Media" / "Media gate" / "Agreement" ("{agreement id} / {version}", or "missing / -") | Card facts, no explanation | :225,231,237 |
| "Review title" / "Review tags" / "Review description" / "Operator note or change request" / "Decline reason" | Card boxes | :260,269,278,287,296 |
| "Start review" / "Request changes" / "Accept" / "Send to schedule" / "Minutes" / "Decline" | Buttons, no hints, no confirmation | :320-386 |
| "Not requested" / "Unreadable date" | Requested date fallback | :58,60 |
| "Producer activity" ("{n} submitted / {n} scheduled / {n} declined") | Report tiles | :122-139 |
| "Status notification outbox" | Last 6 notices | :152 |
| "No contributor submissions are waiting." | Empty | :560 |
| "No contributor submissions match the current filter." | Filter empty | :568 |
| "Contributor queue could not load." (also used for failed actions) | Error box title | :97 |
| "Your program has a real spot on the schedule and will air automatically." | Shown to producer and in the outbox | contribute/store.py:855 |

## What the screen really does
Producers submit a program on the resident portal; staff review it here. Start review only changes a label. Request changes and Decline record a note or reason; Accept checks the video file with ffprobe (a bad file is refused and nothing changes) and then copies it into the Assets library as a Validated recording. Send to schedule (Accepted only) makes a draft entry on the Schedule, using the producer's requested air date or the current moment, the channel stored on the submission, and the Minutes box; it does not put anything on the air. Decline on an item that already has a schedule entry cancels that entry first. Nothing is emailed; the status notices are a log, and a producer sees status only by pasting their receipt and token on the portal. Staff who can read the queue (publish operator, meeting operator, support admin) are not all allowed to act: only publish operator and meeting operator can use the buttons.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "Contributor queue could not load." | Same title for any failure, including a refused Accept or a 403 (`:97`) | misleading |
| HELP-02 | "will air automatically" | Send to schedule makes a draft; it airs only after Commit to Air on the Schedule (`egress/source_plan.py:507-509`) | blocks work |
| HELP-03 | "Status notices", "Status notification outbox" | Only a log in the submission file; no email; producers must use Check status on the portal | misleading |
| HELP-04 | No text before Send to schedule | Channel (always `public` from the portal form, `HomeScreen.tsx:273`), start (requested date or now) and length (Minutes, default 30) are used unseen | misleading |
| HELP-05 | "Decline reason" and "Operator note" unexplained | Decline reason goes to the producer (`store.py:207`); who sees the operator note is UNVERIFIED. Per the manual, Request changes shows the producer only a fixed message | misleading |
| HELP-06 | "Accept", "Media gate" unexplained | Accept checks and copies the file; Media gate reads "not run" then "passed" | misleading |
| HELP-07 | Heading vs nav; "Agreement: id / version" | Internal ids shown | cosmetic |
| HELP-08 | Never says where producers submit | Portal home page, "Submit a program" | misleading |
| HELP-09 | No Published tab; no confirmation on Accept, Decline or Send to schedule | Decline silently cancels a schedule entry | misleading |
| HELP-10 | No Manual link; page shown to roles that cannot use it | records_clerk and setup_admin get a load error; support_admin can read but actions fail | misleading |
| NEW-1 | Send to schedule offered for any Accepted item | Per the manual (ch.12), the requested air date is sent without a time zone and the Schedule refuses that; expect "Could not build a schedule item from this handoff" when a date was requested. Read from code, not run on a station | blocks work |
| NEW-2 | "Request changes" and "Operator note or change request" | The note is not sent to the producer; they see only "The operator needs changes before this program can move forward." (manual ch.12) | blocks work |

## Proposed text
What this is for (new, under the heading): "Programs sent in by community producers through the resident portal. Review each one, ask for changes, accept it into the library, or decline it."
Who can use it (new): "Everyone signed in can open this page, but only a publish operator or meeting operator can use the buttons. A support admin can read the queue."
Heading: "Contributors" (match the menu). Label above it: "Community programs".
Intro: "Producers send programs from the Submit a program form at the bottom of the resident portal home page. Producers never get a login to this console. Nothing is emailed to producers. They see the state only by pasting their receipt and status token into Check submission status on the portal. Tell them to keep both."
Tile "Status notices": "Status messages logged (not emailed)". Outbox heading: "Status messages (a log; not emailed)".
Media gate (tooltip): "The file check. It reads 'not run' until you click Accept, then 'passed'." Agreement: "Agreement accepted: {title}, version {n}" (hide internal ids).
Box helpers: Review title/tags/description: "What goes into the library when you click Accept. Residents see the title and description if the recording is published." Operator note or change request: "Saved on the submission for staff. In beta.10 the producer does NOT see this text. If the producer must fix something, contact them yourself." Decline reason: "The producer can see this reason on the status page. Write it for them."
Button hints (one line under each, or a tooltip):
- Start review: "Marks the submission Under review. Nothing is checked."
- Request changes: "Marks it Needs changes. The producer sees only a fixed message, not your note."
- Accept: "Checks the video file. If it is usable, copies it into Assets as Validated. A damaged file is refused and nothing changes. The producer's original stays in the intake folder."
- Send to schedule: "Creates a DRAFT entry on the Schedule from the Minutes box, the requested air date (or now) and the channel {id}. It does not put the program on air. Open Schedule and approve it there." Until fixed, add: "If the producer gave an air date this can fail. Use New scheduled item on the Schedule instead."
- Decline: "Marks it Declined with the reason. If a schedule entry exists it is cancelled first. Cannot be undone from this screen."
Confirm text before Decline (after fix): "Decline this program and cancel its schedule entry?"
Producer-facing message for Scheduled (store.py:855), honest for now: "Your program has a spot on the schedule as a draft. Station staff still have to approve it for air."
After fix (Send to schedule works and commits): "Your program is on the schedule and will air at the time shown."
Error title: "That did not go through" for failed actions, and "Contributor queue could not load." only for the list; show the reason under it. Role error: "Your sign-in cannot review submissions. Ask your station administrator for the publish operator or meeting operator role."
Empty text: "No contributor submissions are waiting. Producers send programs from the Submit a program form on the resident portal home page."

## Notes for the coder
- Edit `screens/ContributeScreen.tsx`; contributor-facing wording is in `civiccast/contribute/store.py:840-858` and the public form in `civiccast/apps/portal-public/src/screens/HomeScreen.tsx:603-734`.
- Tests that pin strings (verified by grep): there is no `ContributeScreen.test.tsx` and no operator e2e spec for this screen. `tests/contribute/test_store.py` pins the producer message "will air automatically" (`civiccast/contribute/store.py:855`); update it together with that message.
- Code fixes, not text fixes: separate error box for actions (HELP-01); send the time zone with `requested_start` or default to a valid time (NEW-1); pass the change-request note to the producer (NEW-2); send "Send to schedule" through Commit to Air or reword the producer message (HELP-02); disable action buttons for support_admin (HELP-10); add a Published tab; confirmation dialogs; real email or remove the "outbox" wording (HELP-03).
- UNVERIFIED in the inventory: whether producers can see the operator note; whether channel `public` exists on a normal station; whether the Schedule screen labels contributor entries.
