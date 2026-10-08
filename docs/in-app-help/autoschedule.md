> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Auto-schedule (nav id: autoschedule)

Console group: Run Meeting. Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/screens/` unless they start with `civiccast/`. Authority: `docs/manual/src/12-before-meeting.md` ("Fill a channel by rule (Auto-schedule)") and `ops/docs-sprint/inventory/screens/autoschedule.md`. Line numbers re-checked in `AutoScheduleScreen.tsx`.

## Where the help text lives now
- `AutoScheduleScreen.tsx`: access note 72-78; page intro 859-866; saved searches 276-330 (form 139-235); dayparts 458-515 (form 344-423); rules 752-808 (form 620-719; card 560-615; simulate result 526-557); compile 811-843.
- `autoschedule-format.ts:26-37` (slot labels); `status-language.ts` (`stateLabel`, asset state words).
- `civiccast/schedule/autoschedule_materializer.py:285-297` (items are written as Published) and `autoschedule_worker.py:50-57` (hourly compile).

## Current text
| String | Where | Source line |
|---|---|---|
| "Run Meeting" / "Auto-schedule" | Eyebrow, heading | AutoScheduleScreen.tsx:859 |
| "Define saved searches and dayparts, connect them with rules, then preview and compile to fill the schedule automatically. Compiling a rule approves its picked items to air — reviewing the preview before you compile is the approval step. Only manually-added schedule items need a separate Commit-to-Air approval." | Page intro | AutoScheduleScreen.tsx:863-866 |
| "Viewing and managing {saved searches / dayparts / auto-schedule rules} requires the publish operator, setup admin, or support admin role." | Access note | AutoScheduleScreen.tsx:75 |
| "Saved searches" / "Named queries over your library. A rule fills its daypart by picking from one of these." / "Add saved search" / "Close" | Section | AutoScheduleScreen.tsx:276-283 |
| Placeholders "Example: Recent council meetings", "Example: City Council", "Example: budget" | Search form | AutoScheduleScreen.tsx:184, 188, 192 |
| "Meeting body (exact)" / "Title contains" / "Min length (minutes)" / "Max length (minutes)" / "Include states" / "Newest published first" | Search form | AutoScheduleScreen.tsx:187, 191, 195, 199, 204, 224 |
| "Create saved search" / "Saving..." / "Save changes" | Search form | AutoScheduleScreen.tsx:233 |
| "No saved searches yet." / "A saved search collects the recordings that match rules you set — the newest council meetings, a weekly series, a category. Create one here and auto-schedule uses it to pick what airs." | Empty | AutoScheduleScreen.tsx:300-301 |
| "Used by N rule(s) — deleting it stops them scheduling." | Delete warning | AutoScheduleScreen.tsx:270, 452 |
| "Delete" / "Confirm delete?" / "Removing..." | Delete button | AutoScheduleScreen.tsx:124 |
| "Dayparts" / "Recurring time windows on a channel that a rule fills (e.g. weeknights 6–10pm). Times are the station's local wall-clock (set by CIVICCAST_STATION_TZ; UTC if unset)." / "Add daypart" | Section | AutoScheduleScreen.tsx:458-466 |
| Placeholders "public", "Prime time" / "Start" / "End" / "00:00 = midnight (end of day). An end before the start wraps past midnight." / "Days" / "Create daypart" | Daypart form | AutoScheduleScreen.tsx:370, 374, 377, 381, 383, 387, 419 |
| "No dayparts yet." / "A daypart is a block of air time you hand over to auto-schedule — weekday evenings, overnight repeats. Create one here and rules can start filling it." | Empty | AutoScheduleScreen.tsx:483-484 |
| "Auto-schedule rules" / "Each rule fills a daypart from a saved search. Simulate to preview; rules feed the commit gate before air." / "Add rule" | Section | AutoScheduleScreen.tsx:752-759 |
| "Pick strategy" / "Newest first" / "First match" / "Random" / "Saved search" / "Daypart" / "Choose…" | Rule form | AutoScheduleScreen.tsx:654-673 |
| "Rolling window (days, 14–60)" / "No-repeat window (days)" / "Rolling window must be a whole number from 14 to 60 days." / placeholder "Fill prime with council" | Rule form | AutoScheduleScreen.tsx:680, 684, 689, 651 |
| "Create rule" / "No rules yet." / "A rule connects a saved search to a daypart so the channel fills itself with matching programs. Create a saved search and a daypart first, then add a rule here to connect them." | Rule form, empty | AutoScheduleScreen.tsx:715, 776-777 |
| "Simulate" / "Simulating..." / "Would schedule N of M upcoming slots." / "This rule points at a saved search or daypart that no longer exists." | Rule card | AutoScheduleScreen.tsx:600, 538, 530 |
| "Will air" / "Already scheduled" / "No eligible video" / "No usable duration" | Slot labels | autoschedule-format.ts:26-37 |
| "Compile schedule" / "Run every enabled rule and add its picks to the schedule. The new items still need an operator commit before they air." / "Compile now" / "Compiling..." | Compile card | AutoScheduleScreen.tsx:823, 825, 829 |
| "Added N scheduled items across M rules." | Result | AutoScheduleScreen.tsx:839 |
| "The saved search could not be saved." / "The daypart could not be saved." / "The rule could not be saved." / "Simulation failed." / "Compile failed." | Errors | AutoScheduleScreen.tsx:293, 476, 769, 612, 834 |

## What the screen really does
Auto-schedule picks recordings for a time of day by rule. A saved search says which recordings qualify, a daypart is a repeating window of time on a channel, and a rule joins the two. For each open day inside the rolling window, one recording is placed at the daypart's start time with its own length; if anything is already scheduled inside that day's daypart, that day is left alone. Items placed this way are written as Published, so they are approved to air with no separate approval step, and the station also compiles by itself about once an hour. Simulate writes nothing and is the only preview. Deleting a rule does not remove programs it already placed. Only Publish operators and Setup admins can change anything; Support admins can look and run Simulate.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "The new items still need an operator commit before they air." (:825) | Items are born Published (`autoschedule_materializer.py:285-297`), so they are already approved. The page intro (:864-866) is correct and contradicts this line. | blocks work (puts programs on the air) |
| HELP-02 | "rules feed the commit gate before air." (:754) | Same: there is no commit gate for these items. | misleading |
| HELP-03 | "Added N scheduled items across M rules." (:839) | They are Published, not Scheduled (a different state on the Schedule screen). | misleading |
| HELP-04 | Intro says the preview is the approval step | Saved enabled rules are also compiled by the station about every hour (`autoschedule_worker.py:55`), with no button press. Not mentioned on the screen. | blocks work |
| HELP-05 | "(set by CIVICCAST_STATION_TZ; UTC if unset)" (:460-461) | Variable-name jargon; the zone is the Timezone box on Station Profile; "local" or unset counts as UTC (manual, ch. 12). | misleading |
| HELP-06 | Daypart "Channel" box | Free text (placeholder "public"); a typo makes a daypart for a channel that does not exist (UNVERIFIED if refused). | misleading |
| HELP-07 | "Rolling window (days, 14–60)", "No-repeat window (days)" | Unexplained (`civiccast/schedule/autoschedule_models.py:392-394`). | cosmetic |
| HELP-08 | "Meeting body (exact)" | Must match the video's Meeting body text exactly, including capitals. | cosmetic |
| HELP-09 | A "disabled" tag exists on rule cards | Nothing here disables a rule, or sets priority or dates (priority fixed at 100). | cosmetic |
| HELP-10 | "Delete" / "Confirm delete?" on a rule | No warning that already-placed programs stay Published and will air. | blocks work |
| NEW-1 | Page has no "who can use this" line | Others who reach the URL see the access note; the Support admin sees no Add/Edit/Delete/Compile and nothing says why. | cosmetic |
| NEW-2 | "Include states" lists Waiting for media, Rejected, etc. | Only Validated and Recorded can air (`civiccast/schedule/commit_service.py:66-68`); other boxes pick videos that cannot play. | misleading |

## Proposed text
- Page intro (:863-866): "Auto-schedule fills a channel's air time by rule. Programs it places are approved to air at once. There is no separate approval step. Use Simulate to see what a rule would do before you compile. CivicCast also compiles every saved rule by itself about once an hour, so a saved rule can put programs on the air without anyone pressing a button."
- Who can use this (new): "Publish operator or Setup admin: create, edit, delete and compile. Support admin: look and use Simulate only."
- Daypart help (:460-461): "A repeating window of time on a channel that a rule fills, for example weeknights 6 to 10 PM. Times use the station's time zone, set in the Timezone box on the Station Profile screen. Until it is set, times are UTC."
- Daypart Channel box: placeholder "Channel id: copy it from the Channels screen". After fix: a menu.
- Rules help (:754): "Each rule fills a daypart from a saved search. Simulate shows what it would place. Compiling puts those programs on the air."
- Compile card (:825): "Runs every rule now. The programs it picks are approved to air immediately. There is no confirmation box."
- Result (:839): "Added N programs across M rules. They are Published and will air at their times. See them on the Schedule screen."
- Rolling window label help: "How many days ahead to fill (14 to 60)."; No-repeat: "Do not pick the same video again within this many days. 0 allows repeats."
- Meeting body label: "Meeting body (must match the video's Meeting body exactly, including capital letters)".
- Include states: add "Only Validated and Recorded videos can air. Leave the other boxes unticked."
- Delete on a rule: add "Programs this rule already placed stay on the schedule and will still air. Remove them elsewhere." (Note: no screen removes a Published item in beta.10; see the Schedule spec.)
- Delete on a search or daypart: keep "Used by N rule(s) — deleting it stops them scheduling." Replace with "Used by N rule(s). Deleting it stops those rules from placing programs. It does not remove programs already placed."
- Simulate labels: "Will air" = "A program will be placed", "Already scheduled" = "Skipped: something is already scheduled in this daypart that day", keep "No eligible video", "No usable duration" = "Video has no length".

## Notes for the coder
- Files: `AutoScheduleScreen.tsx`, `autoschedule-format.ts`; docstrings in `civiccast/schedule/autoschedule_worker.py:11-12` and `autoschedule_router.py:416` still say items are Scheduled and "never put anything on air"; the code writes Published. A code owner should confirm that decision is current (inventory note).
- Tests that pin strings: `AutoScheduleScreen.test.tsx` pins "Delete" and "Confirm delete?" (:17-19), "Create saved search", the placeholders 'Example: Recent council meetings' and 'Example: City Council' (:33-36), the label 'Min length (minutes)', "Create daypart", the placeholders 'public' and 'Prime time' (:61-62), "Save changes", 'Waiting for media' (:119), /14 to 60 days/ (:127-129), the label 'Rolling window (days, 14–60)', "Create rule", 'Fill prime with council', 'Saved search', 'Daypart' labels (:153-161), and 'Would schedule 1 of 2 upcoming slots.' (:186). Keep the label text of form fields and update the placeholder tests if you change placeholders. `Sidebar.test.tsx:27, 45, 50` pins the nav label.
- Code fixes, not text fixes: decide whether compiled items should start Published or Scheduled (HELP-01, HELP-04 follow from the answer); a way to disable a rule and set priority or dates (HELP-09); a channel menu for dayparts (HELP-06); a way to remove programs a rule placed; a Cancel button for Published rows on Schedule.
- Not verified: what happens to already-placed items when a rule, search or daypart is edited or deleted; whether the server refuses a daypart for an unknown channel; how overlapping dayparts on one channel are resolved.
