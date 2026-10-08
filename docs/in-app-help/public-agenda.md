> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Meeting agenda card (shown beside the video on a Watch page, `#/watch/<asset_id>`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/MeetingAgendaSidebar.tsx` unless noted. Staff write and publish the agenda on the Agendas screen (manual chapter 12).

## Where the text lives now
`MeetingAgendaSidebar.tsx` (lines 128-321). The card is placed by `src/screens/WatchScreen.tsx:156-159`. Item numbers, titles and times come from the agenda staff entered.

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Agenda | Card heading (loading, error and normal) | 135, 158, 230 |
| Loading agenda… | While loading | 138 |
| The agenda could not be loaded right now. | Error (amber) | 161 |
| Agenda document | Link, opens a new tab, only if staff gave a document address | 243 |
| No agenda items posted. | Agenda has no items | 248 |
| Agenda items | aria-label of the list | 253 |
| `<number>` `<title>` `<hh:mm:ss>` (for example "3.a Approve minutes 00:12:40") | One button per item | 283-293 |
| — | Time shown for an item with no video time | 293 |
| Jump to `<number> <title>` | aria-label of each item button | 257-258 |
| Agenda document | Heading (h4) and frame title when the document address ends in .pdf | 308, 311 |
| Browser cannot render the PDF? Open it in a new tab via the link above. | Note under the PDF | 316 |

## What the page really does
If staff published an agenda for the recording, a card lists its items in order. An item that has a video time is a button; pressing it jumps the video to that time and starts playback if it was paused (`HlsPlayer.tsx:66-79`). A time past the end of the video lands on the last frame with no message. An item with no time shows "—" and is switched off (270). If the agenda has a document address, a link opens it in a new tab, and a document address that is a web address ending in `.pdf` also shows in a frame (301-318). With no agenda the card does not appear and the video fills the width (144-149). A draft agenda is not shown (`src/types.ts:154-155`). Arrow keys, Home and End move between items that have times (172-218). The player has no chapter marks; this card is the only chapter tool (`src/agendaToChapters.ts` is not used by any screen).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-agenda/HELP-33 | (missing) | Nothing says the items are clickable or that "—" means "no video time for this item". | Medium |
| public-agenda/HELP-34 | Item time | A time later than the video lands on the last frame, no message (`HlsPlayer.tsx:72`). | Low |
| public-agenda/HELP-35 | "could not be loaded right now" | No retry; the resident must reload the whole page (161). | Low |
| public-agenda/NEW-1 | "Jump to `<item>`" | Items with no time have this same label but are disabled and skipped by Tab (264-270). A screen reader reads "Jump to 2 Public comment" (usually with "unavailable"), which promises a jump that cannot happen. | Medium |
| public-agenda/NEW-2 | Item time | The aria-label replaces the visible text, so a screen reader never says the time (267). | Medium |
| public-agenda/NEW-3 | Disabled items | Switched-off buttons are not focusable, so a keyboard user may not learn those items exist except by browsing the list. | Low |
| public-agenda/NEW-4 | "Agenda document" link | Opens whatever address staff typed, with no check of the start of the address in the portal (`href`, 238). Server checks: UNVERIFIED. | Low |
| public-agenda/NEW-5 | Agenda next to a gated video | The card stays visible when the subscription gate hides the video (`WatchScreen.tsx:143-160`), so a resident can press items that jump nothing. | Low (paywall on only) |

## Proposed text
| Replace | With |
| --- | --- |
| New line under the "Agenda" heading (new) | Press an item with a time to jump to that part of the video. |
| 138 | Loading the agenda… |
| 161 | We could not load the agenda. Please reload the page. |
| 248 | No agenda items have been posted yet. |
| 243 | Agenda document (opens in a new tab) |
| 293 "—" | — (aria-label adds: "no video time") |
| 257-258 aria-label (item with a time) | Jump to `<number> <title>`, at `<h hours m minutes s seconds>` (for example "Jump to 3.a Approve minutes, at 12 minutes 40 seconds") |
| aria-label (item with no time) | `<number> <title>`, no video time |
| 316 | Cannot see the document here? Use the Agenda document link above. |
| 311 frame title | Agenda document (PDF) |

**Time format.** The card always shows hours, minutes and seconds ("00:12:40"), even for short meetings (54-62). Keep it. Staff must type seconds today (manual chapter 12); that is a staff-side issue.

**What to say if there is no agenda (new, optional on the Watch page).** Nothing. The card is hidden on purpose.

**Accessibility and keyboard.** Tab goes to the first item with a time. Up and Down arrows move between items with times; Home and End go to the first and last. Enter or Space jumps. Buttons are 44 px high. Give items with no time a text label ("no video time") instead of only a dash. Do not use color alone to show an item is off.

## Notes for the coder
- Edit `MeetingAgendaSidebar.tsx`. Code fixes: separate labels for items with and without times and include the time; allow a retry; consider showing a short note when a time is past the end of the video; check that the document address starts with `http://` or `https://` before making a link.
- Tests that pin strings: `MeetingAgendaSidebar.test.tsx:107-108,117-123,133,145,156-176,189,202,274-278,325` use button names "Jump to 1 Roll call", "Jump to 3.a Approve minutes", "Jump to 2 Awaiting timecode" and link name "Agenda document". Adding the time to the aria-label changes these exact names; update the tests with it.
- Not verified: how staff get video times onto items (staff side), and whether the server restricts the document address.
