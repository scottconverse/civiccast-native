> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Program Guide (nav id: guide)

Console group: Run Meeting. The menu label is "Program Guide"; the page heading reads "Program guide". Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/` unless they start with `civiccast/`. Authority: `docs/manual/src/12-before-meeting.md` ("Repeat a program on a schedule (Program Guide)") and `ops/docs-sprint/inventory/screens/guide.md`. Line numbers re-checked.

## Where the help text lives now
- `screens/ProgramGuideScreen.tsx`: header 443-449; channel menu 462-474; buttons 494, 504; recurrence words 26-30; status words 37-40; error state 132-170; empty slots 186-187; Disabled tag and button 233, 248; empty log 266-267; unreadable rows 284-286; toasts 398-399, 406, 418-419, 426, 573; disable dialog 543-545; section titles 535, 557.
- `components/programlog/ProgramSlotDrawer.tsx`: recurrence cards 17-21; drawer 192-195; recording help 231-254; dates 284-340; length 363; title 397-404; submit 451.

## Current text
| String | Where | Source line |
|---|---|---|
| "Workflow" / "Program guide" | Eyebrow, heading | ProgramGuideScreen.tsx:443, 445 |
| "Place recordings on a channel's recurring guide. The automation engine airs scheduled entries and falls back to filler between programs. Times shown in your browser timezone." | Page intro | ProgramGuideScreen.tsx:447-449 |
| "Channel" / "Refresh guide" / "Refreshing…" / "Add to guide" | Toolbar | ProgramGuideScreen.tsx:462, 494, 504 |
| "Guide refreshed." + "{N} scheduled · {N} conflicts · {N} not playable" / "Could not refresh the guide." | Toasts | ProgramGuideScreen.tsx:398-399, 406 |
| "Recurring slots" / "Nothing on the guide yet." / "The program guide is the weekly grid of what airs on this channel. Place a recording with “Add to guide” and its recurring slot appears here." | Slots | ProgramGuideScreen.tsx:535, 186-187 |
| "Once" / "Daily" / "Weekly" / "Weekdays" and "Airs a single time at the start time." / "Airs every day at this time." / "Airs every week on this weekday." / "Airs Monday through Friday." | Recurrence | ProgramGuideScreen.tsx:26-30; ProgramSlotDrawer.tsx:18-21 |
| "recording length" / "until {date}" / "Disabled" / "Disable" | Slot row | ProgramGuideScreen.tsx:70, 221, 233, 248 |
| `Disable "{name}"?` / "All future airings from this recurring slot are cancelled from the guide immediately. Past and in-progress airings are unaffected, but nothing new will schedule until the slot is re-enabled." / "Disable slot" | Disable dialog | ProgramGuideScreen.tsx:543-545 |
| "Slot disabled." + "{name} · N future airing(s) cancelled" / "Could not disable the slot." | Toasts | ProgramGuideScreen.tsx:418-419, 426 |
| "Next 7 days" | Section | ProgramGuideScreen.tsx:557 |
| "Nothing scheduled for the next 7 days." / "This log is the day-by-day schedule built from the guide's recurring slots. Add a slot, then press “Refresh guide” to build out the week." | Empty log | ProgramGuideScreen.tsx:266-267 |
| "Scheduled" / "Skipped · conflict" / "Skipped · not playable" / "Cancelled" / raw "manual" | Status tags | ProgramGuideScreen.tsx:37-40, 44 |
| "1 guide entry has an air time this station cannot read and is not shown below." / "The rest of the guide is complete." | Banner | ProgramGuideScreen.tsx:284-286 |
| "Could not load the program guide." / "Durable storage is not ready." / "Try again, or check the server logs for more detail." / "Go to Setup" / "Retry" | Error | ProgramGuideScreen.tsx:142, 148-151, 160, 169 |
| "Program guide · {channel}" / "Add to guide" | Drawer | ProgramSlotDrawer.tsx:192, 195 |
| "No validated recordings. Upload and validate a recording in the Assets tab first." / "Only validated recordings can air. The guide refreshes within the rolling horizon after you add a slot." | Drawer | ProgramSlotDrawer.tsx:231-232, 253-254 |
| "Recurrence" / "First airing" / "Enter a date and time for the first airing." / "Repeat until (optional)" / "The repeat-until date could not be read. Re-enter it." | Drawer | ProgramSlotDrawer.tsx:266, 284, 307, 317, 340 |
| "Use the recording's own length" / "Guide title (optional)" / "Shown to residents instead of the recording title." | Drawer | ProgramSlotDrawer.tsx:363, 397, 404 |
| "Adding…" / "Added to guide." | Drawer button, toast | ProgramSlotDrawer.tsx:451; ProgramGuideScreen.tsx:573 |
| "This action requires one of these CivicCast roles: meeting_operator, support_admin." | Server refusal after the form is sent | civiccast/auth/roles.py (role message) |

## What the screen really does
The Program Guide holds recurring slots: a recording placed on a channel at a time that repeats (Once, Daily, Weekly, Weekdays). A background job, about every five minutes, turns each slot into schedule items for the next 72 hours. Those items are Scheduled, which means drafts. They do not air until someone presses Publish to residents on the Schedule screen. Daily, Weekly and Weekdays repeat on a fixed UTC clock, so the local air time moves one hour when daylight saving changes, and Weekdays counts days on the UTC calendar. A slot cannot be edited or re-enabled after it is added. Adding a slot needs the Meeting operator or Support admin role, although the buttons are shown to everyone.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "The automation engine airs scheduled entries and falls back to filler between programs." | Items are Scheduled and do not air until approved (`civiccast/programlog/materializer.py:212-220`; only Published items air, `civiccast/egress/source_plan.py:507-511`). | blocks work |
| HELP-02 | Weekdays: "Airs Monday through Friday." (also Daily, Weekly) | Counted on the UTC date (`civiccast/programlog/occurrences.py:44-46`). A US Friday-evening start is Saturday in UTC and is dropped; a Sunday-evening start is Monday in UTC and is kept. Daily and Weekly shift one hour at daylight saving. Derived from code, not run. | blocks work |
| HELP-03 | "...nothing new will schedule until the slot is re-enabled." | No control re-enables a slot (`civiccast/programlog/router.py:75-88`). | misleading |
| HELP-04 | "...the weekly grid of what airs on this channel." | The screen shows two lists, not a grid. | cosmetic |
| HELP-05 | Raw tag "manual"; "Skipped · conflict" with no next step | `manual` is not in the status table (:33-44). Refresh does not retry a skipped airing (it is recorded once). | misleading |
| HELP-06 | "Refresh guide" in a per-channel toolbar | Builds the guide for all channels (`POST /api/staff/programlog/materialize`). | misleading |
| HELP-07 | Buttons visible to all | Writing needs meeting_operator or support_admin (`router.py:128, 190, 217, 241`); a publish operator or setup admin learns this only after sending. | misleading |
| HELP-08 | "No validated recordings. Upload and validate a recording in the Assets tab first." | Menu lists only Validated videos (ProgramSlotDrawer.tsx:79-82); recorded videos are not offered though the guide accepts them (`materializer.py:41, 196`). | blocks work |
| HELP-09 | "Workflow" eyebrow, "Program guide" vs menu "Program Guide" | Inconsistent names. | cosmetic |
| HELP-10 | (nothing) | A slot cannot be viewed in detail or edited after creation. | cosmetic |
| NEW-1 | "press 'Refresh guide' to build out the week" (:267), "Next 7 days" | The guide builds only 72 hours ahead by default (CIVICCAST_PROGRAM_LOG_HORIZON_HOURS), so days 4 to 7 stay empty. | misleading |
| NEW-2 | Tag "Scheduled" in Next 7 days | Stays "Scheduled" after the item is published; the list cannot show approval. | misleading |

## Proposed text
- Page intro (:447-449): "Use this screen for recordings that repeat, such as every Friday night. Each slot builds draft items on the Schedule screen for about the next 3 days. A draft does not air. Open Schedule and press Publish to residents on each one to approve it to air. Times you type are in your computer's time zone. Repeats after that count in UTC."
- Who can use this (new): "Anyone signed in can look. Meeting operator or Support admin can add a slot, disable one and use Refresh guide. A Publish operator or Setup admin alone is refused after pressing Add to guide."
- Time warning (new, drawer, under Repeats): "Daily, Weekly and Weekdays repeat on a fixed UTC clock. When daylight saving changes, the program moves one hour on your clock. Check your slots after each clock change." After fix: "Repeats follow the station's time zone."
- Weekdays card (ProgramSlotDrawer.tsx:21): "Airs Monday to Friday by the UTC calendar. For an evening start in the United States this can skip Friday and include Sunday. Use Weekly slots instead, or check Next 7 days after adding." After fix (station time zone): "Airs Monday through Friday."
- Disable dialog body (:544): "This cancels every future airing the slot built, even ones you already approved. Airings that already played are not touched. There is no way to turn the slot back on. To restart it, add it again."
- Empty slots (:187): "No repeating programs on this channel yet. Press Add to guide to place a recording."
- Empty log (:267): "No airings are built for the next 7 days. Add a slot. CivicCast builds about 3 days ahead, about every 5 minutes. Press Refresh guide to build now."
- Refresh guide button label (:494): "Refresh guide (all channels)". Toast detail: "{N} added · {N} skipped for a clash · {N} skipped, video not playable".
- Status tags: "manual" becomes "Added on Schedule". Add a hint line under a "Skipped · conflict" row: "Cancel or move the other program on Schedule, then add this airing by hand. Refresh guide does not retry it." Under "Skipped · not playable": "Fix the video on Assets, then add this airing by hand on Schedule."
- Status "Scheduled" tag: relabel "Draft (not approved)" with note "Check Schedule to see whether it is approved."
- Recording help (:231-232, 253-254): "No videos are available. Only videos in the Validated state are listed. A video CivicCast recorded itself is not offered. Upload the file again on the Assets screen." and "The guide builds the airings in the next few minutes after you add a slot." After fix (Recorded offered): "Add a video on the Assets screen."
- Heading and eyebrow: "Program Guide" and remove "Workflow".

## Notes for the coder
- Files: `screens/ProgramGuideScreen.tsx`, `components/programlog/ProgramSlotDrawer.tsx`.
- Tests that pin strings: `components/programlog/ProgramSlotDrawer.test.tsx` pins 'Enter a date and time for the first airing.' (:96, 120, 128), 'The repeat-until date could not be read. Re-enter it.' (:166) and /Add to guide/i buttons (:108, 185). `e2e/program-guide.spec.ts` pins the heading "Program guide" (:186), buttons "Refresh guide" (:211), "Add to guide" (:221-246), the dialog name "Add to guide" and "Disable slot" (:263). Renaming the heading changes that spec. The manual `docs/manual/src/12-before-meeting.md` quotes the intro text and tags.
- Code fixes, not text fixes: compute Daily, Weekly and Weekdays in the station time zone (HELP-02); a re-enable control and an edit form (HELP-03, HELP-10); offer Recorded videos (HELP-08); retry a skipped airing after the cause is fixed; show the publish state in Next 7 days (NEW-2); gate the write buttons by role (HELP-07); add `manual` to the status table (HELP-05).
- Not verified: the Weekdays and daylight-saving behavior was derived from reading `compute_occurrences`, not run; whether Add to guide rejects an unknown channel id.
