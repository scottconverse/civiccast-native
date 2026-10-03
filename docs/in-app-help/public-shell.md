# Resident portal frame: header, menu, report link (route: every page; `index.html` + `#/...`)

Paths below are relative to `civiccast/apps/portal-public/`. Beta.10 facts only. Severity: High = resident is misled or stuck, Medium = confusing or hard to use, Low = polish.

## Where the text lives now
- `src/App.tsx`: header, menu, report link, skip link, direct-video view (lines 104-145, 204, 233-247).
- `index.html`: browser tab title (line 7), search-result description (line 8), language (line 2).
- No other file holds shell text. There is no footer, no `<noscript>` block and no `document.title` code (grep of `src` and `index.html` finds none).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| Skip to main content | Hidden link, shows on first Tab | `src/App.tsx:204` |
| CivicCast Portal | Small label above the title | `src/App.tsx:108` |
| CivicCast public portal | Page title (h1) | `src/App.tsx:111` |
| Watch the current broadcast, see upcoming premieres, and replay published meetings from the resident archive. | Intro under the title | `src/App.tsx:114-115` |
| Portal sections | aria-label of the menu | `src/App.tsx:119` |
| Home / Recordings / Schedule | Menu links | `src/App.tsx:121,127,130` |
| Report a beta issue | Link, opens a new tab | `src/App.tsx:139` (target `BETA_FEEDBACK_URL`, line 35) |
| Do not include passwords, recovery codes, staff tokens, or private meeting material in reports. | Small print | `src/App.tsx:143` |
| Direct video preview / This link may show a live feed or a recording. | Heading and line when the address has `?manifest=` | `src/App.tsx:238,241` |
| CivicCast Portal | Browser tab title, same on every page | `index.html:7` |
| CivicCast public portal — adaptive HLS playback for civic broadcast recordings. | Description search engines may show | `index.html:8` |

## What the page really does
The frame is a title, three menu links (Home, Recordings, Schedule) and a "Report a beta issue" link. The address after `#` changes as you move, so every page can be copied. English only, dark colors only, no sign-in. If the address has `?manifest=<video address>`, the frame shows only a video player and ignores the page. Moving between pages moves keyboard focus to the new page's heading, but only after a first click or key press (`App.tsx:79-99`). Every page counts one anonymous "page viewed" event and the video player counts plays; there is no notice about this (`src/analytics.ts`).

## Mismatches
| ID | What it says | What really happens | Severity |
| --- | --- | --- | --- |
| public-shell/HELP-01 | "Report a beta issue" suggests a place to tell the station | It opens the staff manual (`/operator/#/help#report-without-github`, `App.tsx:35`). The anchor exists (`civiccast/docsite/manual.json:138`) but the section is "Don't Have A GitHub Account?": it talks about GitHub, "System Health", a "support bundle" and emailing the project maintainer. Nothing in it tells a resident how to reach their own station. | High |
| public-shell/HELP-02 | Small print about "recovery codes, staff tokens" | Staff words shown to the public (`App.tsx:143`). | Medium |
| public-shell/HELP-03 | Intro uses "premieres" and "resident archive" | Station jargon (`App.tsx:114-115`). | Low |
| public-shell/HELP-04 | (missing) | No help page, no Help link, no word on captions, languages, agenda or subscribing. | Medium |
| public-shell/HELP-05 | (missing) | Views and watch time are counted (`analytics.ts`, `HlsPlayer.tsx:104-157`); residents are told nothing. No name, email or viewer ID is sent (inventory, `analytics.ts:60-76`). | Medium |
| public-shell/NEW-1 | Tab title always "CivicCast Portal" | Nothing sets `document.title`, so the title never says Recordings, Schedule or the meeting name. Screen reader users and people with many tabs cannot tell pages apart (WCAG 2.4.2). | Medium |
| public-shell/NEW-2 | Focus moves to the new page's heading | The code looks for `h2[tabindex="-1"]` (`App.tsx:97`). Recordings, Schedule and Watch have one; Home's headings do not (`HomeScreen.tsx:402`). Going to Home, or to a Watch page that is still loading, moves no focus. | Medium |
| public-shell/NEW-3 | Search-result description says "adaptive HLS playback" | Jargon in public search results (`index.html:8`). | Low |
| public-shell/NEW-4 | Link name is only "Report a beta issue" | It opens a new tab (`App.tsx:135`) and nothing says so, including to screen readers. | Low |
| public-shell/NEW-5 | Header names the product, not the station | The portal never shows the station's name or contact link. The server already sends `station_name`, `support_url`, `privacy_url` and `analytics_privacy_notice_url` in `/api/public/app/config` (`civiccast/app_platform/models.py:604-622`), but the portal reads only `channels` (`src/types.ts:53-55`). The shipped defaults are the name "CivicCast station" and the links `/support` and `/privacy` (`app_platform/store.py:243-255`); no such pages exist in the portal, so those links would show Home. | Medium |
| public-shell/NEW-6 | (missing) | No `<noscript>` text. With JavaScript off the page is blank. | Low |

## Proposed text
| Replace | With |
| --- | --- |
| Intro (`App.tsx:114`) | Watch the meeting that is on now, see what is coming up, and replay past meetings. |
| Report link text (`App.tsx:139`) | Report a problem with this site |
| Report link aria-label (add) | Report a problem with this site (opens in a new tab) |
| Small print (`App.tsx:143`) | Please do not put passwords or private information in your report. |
| Tab title (`index.html:7`, then set per page) | CivicCast Portal. Per page: "Recordings - CivicCast Portal", "Schedule - CivicCast Portal", "<recording title> - CivicCast Portal". |
| `index.html:8` description | Watch live meetings, see the schedule, and replay past meetings from your city. |
| New `<noscript>` | This site needs JavaScript. Please turn it on, or contact the station. |
| Direct preview line (`App.tsx:241`) | This link plays one video. It may be a live meeting or a recording. |

**Report link, today (beta.10).** The destination cannot be fixed with words. Until it is fixed, put one honest line under the link: "This opens the station help page. It is written for station staff." **After fix:** the link goes to a short resident page: "Tell the station about a problem. Email: <station email>. Phone: <station phone>." (use the station's `support_url` once the station has set a real one; see notes).

**New short help: "How to use this site"** (a small page or a "Help" link in the header; every line is true in beta.10):
- Home shows what is on air now, what is coming up, and the newest recordings.
- Recordings lets you search by title or description. You can also pick a year or a meeting body.
- Schedule lists what airs on each channel over the next three days.
- On a recording page, press play. If you see a Captions bar, press the language you want. Press Off to turn captions off.
- If the meeting has an agenda, press an item with a time to jump to that part of the video.
- The video needs a recent Chrome, Edge, Firefox or Safari.
- Use Copy share link to send a recording to someone.
- If the video does not start, reload the page. If that does not help, contact the station.

**New privacy line (owner must approve the wording; counting only runs when the station has turned it on, `analytics.ts:41-50`, so the coder may show it only then):** "This site counts views and how far people watch. The counts do not include your name, email or any personal ID."

**Accessibility.** Keep the skip link as the first Tab stop. Give Home's first heading `tabindex="-1"` so focus lands there. Keep `aria-current="page"` on the menu. Keep the 44 px menu buttons.

## Notes for the coder
- Edit `src/App.tsx`, `index.html`, and add a `useEffect` that sets `document.title` from the route (Watch: use the recording title once loaded).
- Code fixes (do not do with text): a resident help page; read `station_name`, `support_url`, `privacy_url` from `/api/public/app/config` (already served) and show them; the station must replace the defaults `/support` and `/privacy` (staff setting `PATCH /api/staff/app/config`, `app_platform/router.py:148-168`) or the links lead nowhere; `tabIndex={-1}` on Home's first h2 (`HomeScreen.tsx:402`) and focus handling while Watch is loading.
- Tests that pin strings: `e2e/a11y.spec.ts:326,340,378,491` and `e2e/contrast.spec.ts:302-333` use heading "CivicCast public portal"; `a11y.spec.ts:342,407,424` use "Skip to main content"; `a11y.spec.ts:491` uses the link name "Report a beta issue". `e2e/a11y.spec.ts:380-386` pins focus on Recordings and Schedule headings. Changing the h1 or link name means updating these.
- Not verified: whether the staff manual page needs a staff sign-in (the manual API `civiccast/docsite/router.py:19-22` has no sign-in check; the operator app route is `/help`, `portal-operator/src/App.tsx:257`).
