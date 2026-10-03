# Home: live now, coming up, latest recordings (route: `#/`)

Paths are under `civiccast/apps/portal-public/`. Line numbers are `src/screens/HomeScreen.tsx` unless noted. The follow-by-email and "Submit a program" parts of Home have their own files (`public-subscribe.md`, `public-contribute.md`).

## Where the text lives now
`HomeScreen.tsx` holds all page text (lines 139-158, 372-521, 764-780, 842-888). `src/api.ts:207,218-221` builds dates and lengths. The "idle page" text comes from the server (`civiccast/cg/service.py:76-86`), and the emergency text too (`cg/service.py:89-103`). Player text is in `public-player-captions.md`.

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Loading the live stream, schedule, and recordings. | Loading banner | 378 |
| The public portal could not load right now. Refresh the page, then contact the station if the problem continues. | All three loads failed | 387-388 |
| Some portal sections need attention | Amber list title | 392 |
| Live stream: Live status is unavailable. Refresh the page or check the station link. | List line | 140-141 |
| Coming up: The schedule could not be loaded. Try again in a few minutes. | List line | 148-149 |
| Recordings: Published recordings could not be loaded. Try again or contact the station. | List line | 156-157 |
| Live now | Heading | 403 |
| `<title or Broadcast>` is on air. | Sentence | 407 |
| `<title or The station>` is on air. The web preview is turned on but not serving yet. | Sentence | 409 |
| `<title or The station>` is on air, but web preview is not enabled for this channel. | Sentence | 411 |
| The station is standing by. No program is on air right now. | Sentence | 413 |
| No live broadcast is on air. | Sentence | 414 |
| On air. The web preview is turned on but not serving yet. + The broadcast is going out on the cable channel. The station has enabled the web preview; it appears here once the channel's output restarts. This page checks again on its own. | Box | 428, 431-433 |
| On air, but web preview is not enabled for this channel. + The broadcast is going out on the cable channel. Ask the station to turn on HLS web output to watch it here. | Box | 442, 445-446 |
| Live video appears here when the station goes on air. | Empty player | 453 |
| Between-streams idle page | aria-label of idle panel | 845 |
| Broadcast status; State; Channel; Started | Card | 459, 461-463 |
| On air / On air (web preview starting) / On air (no web preview) / Standing by / Offline | State values | 345-352 |
| None yet; Time to be announced | Channel / Started when empty | 462; `api.ts:207` |
| Nothing is posted yet. Check back after the station schedules a premiere or publishes a recording. | Nothing at all | 470-471 |
| Coming up; No premieres are scheduled. | Heading; empty | 477; 493 |
| `<channel_id> / <length>` | Under each coming-up card | 486 |
| Latest recordings; Browse all recordings; No published recordings are available. | Heading; link; empty | 501; 507; 518 |
| Recording description not posted.; Published `<date>`; Watch recording | Recording card | 769; 772; 778 |
| `<severity>` notice; Cellular fallback is enabled for emergency delivery. | Emergency box | 876; 883 |

## What the page really does
Home asks the station for the live status, the premieres list and the published recordings, then shows them. It asks for the live status again every 4 seconds (`homeLive.ts:11`), so an open page follows the channel. "Coming up" lists only premieres that staff approved and that start in the future (`civiccast/schedule/router.py:200-235`); it is not the daily guide (see Schedule). When the channel is on air with web video, the player shows. When it is on air with no web video, a box says so. Otherwise a fixed "idle" panel shows. Emergency text shows only when the address has `?emergency=1`.

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-home/HELP-06 | "Ask the station to turn on HLS web output" | Jargon; and a resident cannot ask for a setting (445-446). | Medium |
| public-home/HELP-07 | Channel row and cards show `government` or `public` | Raw ids, not names (462, 486). Schedule page uses display names (`ChannelGuideScreen.tsx:124`). | Low |
| public-home/HELP-08 | Emergency feature | Shown only with `?emergency=1` (59-61). A normal visit never shows it. | High |
| public-home/NEW-1 | The `?emergency=1` box looks real | The portal calls `/api/public/cg/emergency-overlay` with no channel (108). With no channel the server returns a fixed sample: "Emergency notice / An emergency notice is active for this broadcast area. / Follow local emergency guidance..." with severity "warning" (`civiccast/cg/router.py:523-536`, `cg/service.py:96-103`). Anyone can add `?emergency=1` to the station's address and show a fake emergency on the station's own site. | High |
| public-home/NEW-2 | Idle panel says "CivicCast is ready", "Next broadcast: Public Meetings test broadcast", button "View published recordings" | These are fixed test strings for every station (`cg/service.py:79-86`). The "next broadcast" is never the real next one. The button goes to `/`, which is Home itself. The channel label above the title shows the raw id. | High |
| public-home/HELP-09 | Card title | Falls back to the raw asset id (483). | Low |
| public-home/HELP-10 | (missing) | Nothing says what to do if the video does not start. | Medium |
| public-home/NEW-3 | "No premieres are scheduled." | Schedule may still list regular programs; the two lists differ and Home does not say so (`public-schedule/HELP-44`). | Medium |
| public-home/NEW-4 | "Live now" sentence | The sentence (405) has no `role="status"`/aria-live, so a screen reader is not told when it changes after a 4-second check. | Medium |
| public-home/NEW-5 | "Recording description not posted." | Reads like an error on every untitled card (769; `public-recordings/HELP-22`). | Low |

## Proposed text
| Replace | With |
| --- | --- |
| 378 | Loading the live video, what is coming up, and recent recordings. |
| 387-388 | This page could not load right now. Please reload it. If it keeps happening, contact the station. |
| 392 | Some parts of this page did not load |
| 140-141 | Live video: We could not check if a meeting is on. Please reload the page. |
| 148-149 | Coming up: We could not load the schedule. Please try again in a few minutes. |
| 156-157 | Recordings: We could not load the recordings. Please try again, or contact the station. |
| 407 | `<title or The station>` is on air now. |
| 409 | `<title or The station>` is on air. The online video is starting. |
| 411 | `<title or The station>` is on air on the cable channel. It is not available online right now. |
| 413 | No program is on air right now. The station is ready for the next one. |
| 414 | No meeting is on air right now. |
| 428 box heading | On air. The online video is starting. |
| 431-433 | The meeting is on the cable channel. The video will appear here when it is ready. This page checks again on its own. |
| 442 box heading | On air on the cable channel only. |
| 445-446 | This meeting is not available online right now. You can watch it on the cable channel. |
| 453 | Live video appears here when a meeting is on air. |
| 845 aria-label | Nothing on air right now |
| State values | On air / On air (online video starting) / On air (cable only) / Between programs / Not on air |
| 470-471 | Nothing is posted yet. Please check back later. |
| Under "Coming up" heading (new) | Programs the station will show for the first time. For the full daily guide, open Schedule. |
| 493 | No premieres are listed right now. Open Schedule to see what airs each day. |
| Card title fallback (483) | Untitled program |
| New line under the player area | If the video does not start, reload the page. Use a recent Chrome, Edge, Firefox or Safari. |
| New line near the top (owner must approve) | This page is not an emergency alert service. In an emergency, call 911. |

**Idle panel, today (beta.10).** The text is server code, so no page text can fix it. **After fix:** title "No meeting is on air right now"; message "The next program will start here. See Coming up below."; next-broadcast line built from the real schedule, or left out; button "Browse recordings" going to `#/recordings`.
**Emergency box, today.** Honest text cannot fix a fake box; this is a code fix (below). **After fix:** the box appears on every visit when the station has an active alert, with the station's real title, message and instructions; with no alert, nothing shows.

**Accessibility.** Give the "Live now" sentence `role="status"`. State is also shown as words ("On air"), not only color. Keep the 44 px "Browse all recordings" link.

## Notes for the coder
- Edit `HomeScreen.tsx`. Code fixes needed: (1) stop `?emergency=1` from showing the sample alert: poll `/api/public/cg/emergency-overlay?channel_id=<id>` for the live channel, show the box only when a real alert comes back (the server answers 404 when none is active), and remove the `?emergency=1` switch (`cg/router.py:519-536`); (2) make the idle page real (`cg/service.py:76-86`, `cg/router.py:509-515`); (3) show channel display names; (4) first-heading `tabindex="-1"` (see `public-shell/NEW-2`).
- Tests that pin strings: `HomeScreen.noWebOutput.test.tsx:64,67,70,73,95-106,123-127,142-144,162-163`; `HomeScreen.standingBy.test.tsx:71-81,96-97,109,125-127`; `HomeScreen.livePoll.test.tsx`; `e2e/a11y.spec.ts:327-330,442-446,457-460,469-479`; `e2e/routing.spec.ts:89`. The test at `a11y.spec.ts:445-446` pins the sample idle text ("CivicCast is ready").
- Not verified: the real contents of the idle and emergency responses on a running station (read from code only).
