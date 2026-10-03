# Watch a recording (route: `#/watch/<asset_id>`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/WatchScreen.tsx` unless noted. The video player and caption bar are in `public-player-captions.md`, the agenda card in `public-agenda.md`, the subscription gate in `public-paywall.md`.

## Where the text lives now
`WatchScreen.tsx` (lines 74-180). Date and length words: `src/api.ts:207,217-222`. The "not found" decision reads the server's message (line 43; server text `civiccast/schedule/router.py:177-180`).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Back to all recordings | Link at top | 78 |
| Loading this recording. | Loading | 87 |
| Recording not found | Heading, "not found" state | 97 |
| This recording does not exist or is no longer published. Browse the archive for the current recordings. | Text | 100-101 |
| This recording could not be loaded right now. Try again, then contact the station if the problem continues. | Error | 112-113 |
| Retry | Button | 120 |
| `<recording title>` | Heading | 129 |
| Published `<date>` / `<length>` (for example "Published Tue, Oct 6, 7:00 PM / 47 min") | Under the title | 132-133 |
| Recording description not posted. | When no description | 162 |
| Copy share link | Button | 170 |
| Link copied. | After a successful copy | 174 |
| Copy this link to share the recording: | Browser pop-up when copying is blocked | 68 |

## What the page really does
It loads one published recording by its id and shows the title, the video, the agenda card (if the station posted an agenda), the description and a Copy share link button. The video sits inside the subscription gate; when the station has no paywall on, the gate lets the video through. The agenda card is outside the gate. "Copy share link" copies the address you used to reach the portal plus `#/watch/<id>` (62). If your browser blocks copying, a pop-up shows the address to copy by hand (68). "Not found" shows when the server's error message contains the words "not found" (43); beta.10's server says "Asset not found: `<id>`" for a missing or unpublished recording (`schedule/router.py:177-180`), so that works today.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-watch/HELP-25 | "Recording not found" | Works today, but it depends on the server's wording (43). A different wording gives the generic error plus a Retry that cannot succeed. (Checked against the server text; low risk.) | Low |
| public-watch/HELP-26 | (missing) | No help on turning captions on or clicking agenda items. The caption bar shows only if the video has caption tracks, and nothing is said when it has none. | Medium |
| public-watch/HELP-27 | "Copy share link" | The link uses the address the viewer used (62). If the station was opened by an inside or temporary address, a copied link will not open for people outside. | Medium |
| public-watch/NEW-1 | "Published `<date>` / `<length>`" | The date is the day it was posted, not the day of the meeting. The portal holds no meeting date (`src/types.ts:6-20`). A slash between two facts reads badly aloud. | Low |
| public-watch/NEW-2 | "Recording description not posted." | Reads like an error (162). | Low |
| public-watch/NEW-3 | Focus on page change | The page heading only exists after the recording loads (96, 128), so when a resident opens the page, `App.tsx:97` finds no heading and moves no focus. A screen reader user is not told the page changed (see `public-shell/NEW-2`). | Medium |
| public-watch/NEW-4 | "Retry" for load errors | Fine. It repeats the same request (`retryLoad`, 56-59); a recording removed in the meantime then shows "Recording not found". | Low |
| public-watch/NEW-5 | Video area | When the station turns on the paywall, the gate covers every recording and cannot be finished (see `public-paywall.md`). The Watch page gives no other way in. | High (only when the paywall is on) |

## Proposed text
| Replace | With |
| --- | --- |
| 87 | Loading the recording. |
| 100-101 | We could not find this recording. It may have been taken down. Go back to the list of recordings to find another. |
| 112-113 | We could not load this recording. Please try again. If it keeps happening, contact the station. |
| 132-133 | Posted `<date>`. Length: `<length>`. |
| 162 | (hide the line when there is no description) or "No description yet." |
| 170 | Copy share link |
| 174 | Link copied. You can paste it into an email or message. |
| 68 pop-up | Copy this link to share the recording: |
| New line under the share button (today, beta.10) | The link works for people who can reach this website the same way you did. |
| New line under the video (new) | Captions: if you see a Captions bar under the video, press the language you want. Agenda: if the meeting has an agenda, press an item to jump to it. |
| New line (new) | If the video does not start, reload the page. Use a recent Chrome, Edge, Firefox or Safari. |

**After fix (share link):** build the link from a station address set in settings, so it works for everyone; then drop the "same way you did" line.
**After fix (focus):** a visible heading with `tabindex="-1"` shows while loading, so focus lands on it.

**Accessibility.** The page title is an `h2` with the recording name; keep it as the focus target. "Link copied." is announced politely (`role="status"`); keep. The video is labeled "Meeting video player" (see player file). Buttons are 44 px high; keep.

## Notes for the coder
- Edit `WatchScreen.tsx`. Code fixes: render a loading heading (`tabIndex={-1}`) so focus moves; check `error.status === 404` instead of the message text; build the share link from a configured public address.
- Tests that pin strings: `ResidentRetry.test.tsx:140-142` ("Loading this recording.", heading "Recovered recording"), `e2e/routing.spec.ts:192-194,204-205` (heading, "Copy share link", heading "Recording not found", link "Back to all recordings").
- Not verified: whether the description can hold markup (it is shown as plain text, line 162).
