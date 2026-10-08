> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Channel schedule (route: `#/schedule?channel=<id>`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/ChannelGuideScreen.tsx` unless noted.

## Where the text lives now
`ChannelGuideScreen.tsx` (lines 99-211). Lengths come from `src/api.ts:217-222`. Channel names come from the station (`branding.display_name`, line 124). The default channel is `public` (`src/router.ts:53`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Channel schedule | Heading | 102 |
| What airs over the next three days. Times are shown in your local timezone. | Intro | 105-106 |
| Channels | aria-label of the channel links | 110 |
| `<channel display name>` (for example "Public Channel") | One link per channel | 124 |
| Loading the channel schedule. | Loading | 136 |
| The schedule could not be loaded. `<server message>` Try again, then contact the station if the problem continues. | Error | 146-147 |
| Retry | Button | 154 |
| Nothing is on the schedule for this channel yet. Check back soon. | Empty | 161 |
| `<weekday, month day>` (for example "Tuesday, October 6") | Day heading | 169-173 |
| `<time>` / `<title>` / `<N min, N sec or Duration not posted>` | One row per program | 192; 195; 203 |
| On now | Tag on the running program | 198 |

## What the page really does
It asks the server for the next 72 hours of a channel's program log (`/api/public/programlog/channels/<id>/guide?hours=72`, line 69) and groups it by day in the visitor's own time zone. It also asks for the channel names; if that fails, only one link shows (93-96). The server lists only airings marked "scheduled" whose start is still in the future (`civiccast/programlog/router.py:367-369`). A program that has already started is not in the list. The list comes from the station's repeating weekly slots (Program Guide), and it lists an airing as soon as the guide builds it, whether or not staff approved it to air (manual chapter 12). Rows are plain text, not links.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-schedule/NEW-1 | Tag "On now" marks what is on the air (also stated in manual chapter 15) | The server drops every airing whose start is before the moment of the request (`programlog/router.py:369`). A running program is therefore missing, and the tag needs `start <= now` (`ChannelGuideScreen.tsx:179-183`), which is only true if the page stays open past a start time and re-draws (nothing re-draws on a timer). In practice "On now" almost never shows, and a resident looking for the meeting in progress will not find it here. | High |
| public-schedule/NEW-2 | "What airs over the next three days" | The list is the planned weekly slots, not a list of programs staff approved to air. A slot can be listed and never air. | Medium |
| public-schedule/HELP-41 | (missing) | Rows are not links; no word on whether a program is also online, or on which cable channel number. | Medium |
| public-schedule/HELP-42 | "The schedule could not be loaded. `<server message>`" | The raw server sentence is pasted in (147), for example "The program guide is temporarily unavailable." or a status code. | Medium |
| public-schedule/HELP-43 | "Times are shown in your local timezone." | True, but nothing gives the station's own time zone, which matters when comparing to a printed cable guide. | Medium |
| public-schedule/HELP-44 | (missing) | Home's "Coming up" (approved premieres) and this guide (weekly slots) are different lists and nothing says so. | Medium |
| public-schedule/NEW-3 | Default channel | `#/schedule` opens channel `public` even if the station has no such channel (`router.ts:53`); the server's `default_channel_id` is ignored (`app_platform/models.py:612`). The page then shows "Nothing is on the schedule..." and no link is marked current. | Medium |
| public-schedule/NEW-4 | Channel links | Called buttons in the manual; they are links (`<a>`, 114). Screen readers say "link, current page". Fine, but the label list is the only way to switch; with the config call failing only one link shows (93-96) with no explanation. | Low |

## Proposed text
| Replace | With |
| --- | --- |
| 105-106 | The regular weekly schedule for the next three days. Times are in your local time zone. |
| 105-106, today (beta.10) add | A program that has already started is not listed here. To see what is on now, go to Home. |
| 105-106, after fix (NEW-1 fixed) | The regular weekly schedule for the next three days. Times are in your local time zone. |
| 146-147 | We could not load the schedule. Please try again. If it keeps happening, contact the station. (Do not print the server message.) |
| 161 | Nothing is on the schedule for this channel yet. Please check back soon. |
| Under the heading (new) | Premieres (programs shown for the first time) are listed on Home under "Coming up". |
| Time note (new; station adds its zone from settings) | The station is in `<station time zone>`. |
| Duration | Keep "N min". Replace "Duration not posted" with "Length not listed". |
| Day heading | Keep. |
| 198 (after fix) | On now |

**"On now" today (beta.10).** The tag is not reliable; do not describe it to residents. **After fix:** the server keeps airings that are still running and the page re-checks every minute; then "On now" and a link to Home's player work.

**New help line for residents:** "This list shows the station's regular weekly plan. The cable channel is the final word."  (owner to confirm; it protects against a listed slot that does not air).

**Accessibility.** Channel links sit in a labeled navigation with `aria-current="page"`; keep. Each row should read as one sentence: time, title, length. Do not rely on the green bar; the tag text carries the meaning. Rows need a visible link or button if they ever play something (44 px target).

## Notes for the coder
- Edit `ChannelGuideScreen.tsx`. Code fixes: (1) in `programlog/router.py:369` keep entries where `start + duration > now`; (2) re-render the "On now" check on a one-minute timer; (3) strip the raw server text from line 147; (4) use `default_channel_id` from `/api/public/app/config` instead of the fixed `public`; (5) add station time zone to the config and show it; (6) link "On now" to Home.
- Tests that pin strings: `ResidentRetry.test.tsx:113` ("Loading the channel schedule."), `e2e/a11y.spec.ts:384-386` (heading "Channel schedule" and focus), `e2e/routing.spec.ts:254` (link "Schedule").
- Doc fix for the manual owner: manual chapter 15 says the running program shows "On now"; the code in `programlog/router.py:369` makes that untrue.
- Not verified: whether live meetings appear in the guide (only slots from the Program Guide were read); behavior on a running station.
