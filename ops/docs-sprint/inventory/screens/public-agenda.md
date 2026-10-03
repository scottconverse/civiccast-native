# Meeting agenda sidebar (agenda "chapters")  (nav id: public-agenda, section: Public)
Source files: `civiccast/apps/portal-public/src/MeetingAgendaSidebar.tsx` (line cites), `agendaToChapters.ts`, `types.ts:143-161`, `screens/WatchScreen.tsx:156-159`
Who can open it: everyone (shown beside the player on a watch page).

## What it is for
When the station has published an agenda for a meeting, residents see its items next to the video. Clicking an item with a time jumps the video to that moment, so the agenda works as the meeting's chapters.

## What the user sees
Card headed "Agenda" (230). If the agenda has a source document: link "Agenda document" (243; opens a new tab) and, if the URL is a web address ending in `.pdf`, an embedded viewer headed "Agenda document" (h4, 308) with the note "Browser cannot render the PDF? Open it in a new tab via the link above." (316). Then a list (`aria-label="Agenda items"`, 253) of buttons: number (e.g. "3.a"), title, and a time `HH:MM:SS` or "—".
No agenda published: nothing is shown at all and the player takes the space (144-149).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Item button (aria-label "Jump to `<number> <title>`") | seeks the video to the item's time and plays | `playerHandleRef.seekTo(seconds)` | none | disabled and skipped by Tab when the item has no time (264-270); disabled items show "—" |
| Arrow Up/Down, Home, End | move focus between items with times | none | none | (172-218) |
| Agenda document (link) | opens the source document | none | none | `rel="noopener noreferrer"` |

## States
- Loading: "Loading agenda…" (138).
- Server 404: nothing shown. Other failure: amber box "The agenda could not be loaded right now." (161).
- Agenda with no items: "No agenda items posted." (248).
- Data: `GET /api/public/agendas/<asset_id>`; only published agendas are returned; drafts look like 404 (`types.ts:154-155`).

## Typical task flows
1. Open a recording, read the agenda, click item "5 Public comment" to jump there.
2. Keyboard: Tab into list, arrow to an item, Enter.

## Statuses and words on this screen
Timecode format is always `HH:MM:SS` (54-62).

## Chapters: what is and is not built
`agendaToChapters.ts` converts agenda items to a chapter list but nothing in the portal imports it (only its test does; `grep` over `src`). The video player has no chapter markers on the timeline. The clickable agenda is the only chapter feature residents get. Note the file's own comment at lines 11-14 says the chapter strip is "TODO".

## Help-text findings
- [HELP-33] No text explains that agenda items are clickable or that "—" means "no video time recorded for this item" (290-294). Suggest a one-line hint above the list: "Select an item to jump to that part of the video."
- [HELP-34] Agenda times come from operator timestamps; an item with a time beyond the video length lands on the last frame (clamped, `HlsPlayer.tsx:72`) with no message.
- [HELP-35] On a load failure the sidebar says "could not be loaded right now" with no retry.

## Screenshot plan
Agenda with times and a PDF link (wide); agenda with some items lacking times; recording with no agenda (no sidebar); error state.

## UNVERIFIED / open questions
- UNVERIFIED: how agendas get published and how items get video times (operator-side).
