# EPG Export (nav id: epg)

Console group: Publish. Spec for the in-app help of the program-guide file export. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/EpgExportScreen.tsx` unless stated.

## Where the help text lives now
- Heading 593; intro 595-598. Wrong-role banner 583-584. Identity error 572.
- Form: "Create export config" / "Edit export config" 141; Config ID 145 (placeholder 152); Channel ID 164 (placeholder 170); Horizon (days) 204; Aggregator endpoint (optional) 224 (placeholder 231; help 241, 244); Field map 250 (placeholder 257); Create config / Save changes 276.
- List row: "(no endpoint — Generate returns a downloadable document)" 403; Generate now 416; Delete warning 452-455.
- Result panel: slots 329; "Pushed to" 334; "Push failed" 340-343; Download document 355.
- Errors: "Could not run the export." 526; "Could not delete the config." 617; "Could not load configs." 627. Empty 630-631.
- Role gate: `components/shell/Sidebar.tsx:167`; API `civiccast/reporting/router.py:71-73`; exporter `civiccast/reporting/epg.py`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Compile the upcoming committed schedule into X-List / XMLTV / CSV per a field map; either download the document or push it to an aggregator endpoint. A push failure surfaces on the result rather than as a server error, so a flaky aggregator never breaks the staff API." | Intro | :595-598 |
| "Config ID" (placeholder `epg-tv-guide-channel-1`, no rule shown; a capital letter gives a server error) | Form | :145, 152 |
| "Channel ID" (placeholder `pub-1`) | Form | :164, 170 |
| "Horizon (days)" | Form | :204 |
| "Aggregator endpoint (optional)"; "https only. Loopback and private IPs are rejected."; "Leave blank to download the document instead of pushing to an endpoint." | Form | :224, 241, 244 |
| "Field map (one key=value per line; blank lines + # comments ignored)" with placeholder `channel=pub-1` / `genre=category` | Form | :250, 257 |
| "(no endpoint — Generate returns a downloadable document)" | List row | :403 |
| "Generate now" (no confirmation, even with an endpoint) | Button | :416 |
| "Confirming will delete this EPG export config and stop pushing to {endpoint}…" | Delete warning | :452-455 |
| "Push failed: {error}. The staff API is still up; retry once the aggregator endpoint recovers." | Result panel | :340-343 |
| "No guide exports set up yet." / "An EPG export publishes this station's program guide in the format cable boxes and TV apps read. Create an export with the form above and it appears here." | Empty | :630-631 |
| "EPG export requires the setup admin or publish operator role. Ask your station admin for access." | Wrong role | :583-584 |

## What the screen really does
An export is a saved setup naming a channel, a file type (X-List, XMLTV or CSV), how many days ahead, and optionally an https address. Generate now builds the file from schedule items that are published (committed) on that channel and start between now and the number of days ahead; times are UTC. Each slot has a start, an end and a title; description, category and rating are always empty. With no address, you get a file to download. With an address, CivicCast sends the whole guide to that address at once, with no password and no confirmation, and every press sends it again; nothing sends it automatically on a schedule. If the send fails you get no file. A Channel ID that does not exist gives "0 slots". Field map only renames column headings in CSV and X-List, and does nothing for XMLTV. Setup admin and publish operator can use every control. Not tested against any real guide service.

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "committed schedule", "field map", "aggregator endpoint", "X-List" | Unexplained | misleading |
| HELP-02 | Field map placeholder `channel=pub-1` `genre=category` | Only renames headings; real columns are `start_date, start_time, end_date, end_time, title, description, category, rating` (`epg.py:165-174`); `channel` is not a column; ignored for XMLTV | blocks work |
| HELP-03 | Aggregator endpoint help silent about what is sent | Whole guide, every press; no login possible (`epg.py:413-420`) | blocks work |
| HELP-04 | Channel ID typed free-text | A wrong ID gives 0 slots with no explanation | misleading |
| HELP-05 | Intro promises a guide | Description, category, rating always empty (`schedule_adapter.py:84-97`) | misleading |
| HELP-06 | "Generate now" | A push to an outside service cannot be recalled; no confirmation | blocks work |
| HELP-07 | "The staff API is still up; retry once the aggregator endpoint recovers." | Developer wording | cosmetic |
| HELP-08 | Config ID, no format hint | Lowercase letters, numbers, - and _ only | cosmetic |
| HELP-09 | Greyed Config ID when editing | Does not say it cannot change | cosmetic |
| HELP-10 | Nav "EPG Export" next to "Program Guide" | Different things: Program Guide builds the on-air schedule; EPG Export makes a file for outside services | misleading |

## Proposed text
What this is for (new, under heading): "Makes a file of your upcoming program schedule that TV-guide services and apps can read. You download the file, or give an https address and CivicCast sends it there."
Who can use it (new): "Setup admin or publish operator."
Warning (new, above Generate now): "If an address is set, Generate now sends the whole guide to that address right away and it cannot be taken back. CivicCast cannot log in to the receiving service. Each press sends it again. Nothing is sent automatically."
Intro: "Only schedule items that you have published on the Schedule screen are included, for the days ahead you choose. Times are in UTC. Descriptions, categories and ratings are empty in beta.10. Ask the guide service for a sample file first; CivicCast has not been tested with any particular service. This is different from Program Guide under Run Meeting, which builds your on-air schedule."
Config ID helper: "A name for this export. Lowercase letters, numbers, - and _ only. It cannot be changed later."
Channel ID helper: "The channel's ID, shown on the Channels screen. If the file has 0 slots, the ID is wrong or the channel has no published items in the next {n} days." After fix: a drop-down of channels.
Format helper: "Ask the guide service which format it reads. XMLTV is a common TV-guide format. X-List here is a plain eight-column table."
Horizon helper: "How many days ahead to include. Must be more than 0."
Endpoint helper: "Optional. Must start with https://. Leave empty to download the file instead. Addresses on your own network are refused."
Field map helper: "Optional. Renames column headings in CSV and X-List files only. Write one line as title=Program Title (left side is the CivicCast column, right side is the heading the service expects). Has no effect on XMLTV." Placeholder: `title=Program Title`.
Push failure text: "The guide file could not be delivered. Nothing changed on your station. Check the address and try again. No file is offered when a send fails; clear the address and run Generate now again to get a file."
Confirm before push (after fix): "Send the whole guide to {address} now?"
Empty: "No guide exports yet. Create one with the form above."
Delete warning: keep, add "Data the guide service already received stays there."

## Notes for the coder
- Edit `EpgExportScreen.tsx`; field-map parsing text in `screens/reports-format.ts:41-66`.
- Tests that pin strings (verified by grep): `screens/EpgExportScreen.test.tsx` ("Push failed"). "Compile the upcoming", "No guide exports" and "channel=pub-1" are not pinned.
- Code fixes, not text fixes: a channel drop-down (HELP-04); fill description, category and rating (HELP-05); a confirmation before a push (HELP-06); the create form always sends station `civiccast-station` while the list filters by `CIVICCAST_STATION_ID` (UNVERIFIED effect); a way to run a skipped or unconfigured push again.
- UNVERIFIED in the inventory: that items reach "published" only through the Schedule screen's own action; what real guide services accept; whether anything pushes exports on a timer (no other caller of `EpgExporter.generate` was found).
