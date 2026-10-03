# Home: live now, coming up, latest recordings  (nav id: public-home, section: Public)
Source files: `civiccast/apps/portal-public/src/screens/HomeScreen.tsx`, `screens/homeLive.ts`, `types.ts`, `api.ts`
(paths relative to `civiccast/apps/portal-public/`; line cites are `src/screens/HomeScreen.tsx` unless stated).
Who can open it: everyone (no sign-in). Route `#/`.

## What it is for
The landing page for residents. It shows whether the station is on air and, if so, plays the live stream; lists upcoming premieres; shows the six newest recordings;
and hosts the email-subscription and "Submit a program" forms (documented separately: `public-subscribe.md`, `public-contribute.md`).

## What the user sees (top to bottom)
1. Optional red emergency notice (only with `?emergency=1`, see below) (370, 868-888).
2. While loading: only the banner "Loading the live stream, schedule, and recordings." (378). Content sections are hidden until loading ends (397).
3. If all three loads fail: "The public portal could not load right now. Refresh the page, then contact the station if the problem continues." (387-388).
4. If some fail: amber list "Some portal sections need attention" with lines `Live stream: Live status is unavailable. Refresh the page or check the station link.` / `Coming up: The schedule could not be loaded. Try again in a few minutes.` / `Recordings: Published recordings could not be loaded. Try again or contact the station.` (139-158,392).
5. "Live now" panel (402) with a sentence and a player or placeholder, next to a "Broadcast status" card (459) with rows State, Channel, Started.
6. If nothing at all: "Nothing is posted yet. Check back after the station schedules a premiere or publishes a recording." (470).
7. "Coming up" (477): cards with title, date/time, `<channel_id> / <duration>`.
8. "Latest recordings" (501) with link "Browse all recordings" (507); up to 6 cards (HOME_RECORDING_COUNT=6, line 47).
9. "Follow new recordings" (529) and "Submit a program" (603) sections.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Video player (inside Live now) | plays the live HLS stream | `manifest_url` from `GET /api/public/live/current` | none | see `public-player-captions.md` |
| Browse all recordings | goes to `#/recordings` | none | none | |
| Watch recording (on each card) | goes to `#/watch/<asset_id>` | none | none | `RecordingCard`, 764-780 |
| (idle panel action link) | label and URL come from the server | `GET /api/public/cg/idle` | none | 857-863 |
Subscribe/contribute controls: see the two other files.

## Live-status logic (what the "Live now" sentence and State row say)
Data: `GET /api/public/live/current` loaded once, then re-checked every 4 seconds (`LIVE_POLL_SECONDS = 4`, `homeLive.ts:11`; poll at 179-195). The 4 s poll doubles as the origin's viewer-load signal (`homeLive.ts:7-10`); a failed poll silently keeps the last status (187-189).
| Server state | Sentence under "Live now" (406-414) | State row (343-352) | Panel |
|---|---|---|---|
| `on_air` | "`<title or Broadcast>` is on air." | On air | video player |
| `on_air_no_web_output` + reason `HLS output configured but not serving yet` | "`<title or The station>` is on air. The web preview is turned on but not serving yet." | On air (web preview starting) | box: "On air. The web preview is turned on but not serving yet." + "The broadcast is going out on the cable channel. The station has enabled the web preview; it appears here once the channel's output restarts. This page checks again on its own." (428-434) |
| `on_air_no_web_output` (any other reason) | "... is on air, but web preview is not enabled for this channel." | On air (no web preview) | box: "On air, but web preview is not enabled for this channel." + "The broadcast is going out on the cable channel. Ask the station to turn on HLS web output to watch it here." (442-446) |
| `standing_by` | "The station is standing by. No program is on air right now." | Standing by | idle page (never autoplays the slate, 331-332) |
| anything else | "No live broadcast is on air." | Offline | idle page, else "Live video appears here when the station goes on air." (453) |
Other rows: Channel = `channel_id` or "None yet"; Started = `formatDateTime` (e.g. "Tue, Oct 6, 7:00 PM") or "Time to be announced" (`api.ts:205-215`).
Idle panel (`aria-label="Between-streams idle page"`, 842-865): channel id, title, message, next-broadcast label, action link, all server-supplied.

## Emergency notice
Only fetched when the page URL contains `?emergency=1` (59-61,107-115); shown as `role="alert"` with "`<severity>` notice" (`watch`/`warning`/`emergency`), title, message, instructions, and "Cellular fallback is enabled for emergency delivery." if flagged (868-888). A normal visit to the portal never shows it and it is not polled.

## States
- Loading: banner above. Empty: see items 6-8: "No premieres are scheduled." (493); "No published recordings are available." (518).
- Error: see items 3-4. Offline browser: the three fetches fail, so the "could not load" banner appears.

## Typical task flows
1. Resident opens portal while a meeting is on air: sees "Live now ... is on air." and the video.
2. Station is idle: resident sees the idle panel and "Coming up".
3. Resident clicks "Watch recording" on a card to open the recording page.

## Statuses and words on this screen
On air / On air (web preview starting) / On air (no web preview) / Standing by / Offline (table above).

## Related settings / env / CLI / API
`/api/public/live/current`, `/api/public/schedule/coming-up`, `/api/public/assets`, `/api/public/cg/idle`, `/api/public/cg/emergency-overlay`.

## Help-text findings
- [HELP-06] `HomeScreen.tsx:446` "Ask the station to turn on HLS web output to watch it here." — jargon ("HLS web output") on a public page; suggest "This meeting is airing on the cable channel but is not available online right now."
- [HELP-07] `HomeScreen.tsx:462,486` Channel row shows the raw id (`government`, `public`) and "Coming up" shows "`<channel_id> / 90 min`"; use the channel display name (the Schedule page already does, `ChannelGuideScreen.tsx:124`).
- [HELP-08] `HomeScreen.tsx:59-61` the emergency notice appears only if the visitor adds `?emergency=1`; a resident will never see it by normal browsing. Wrong/missing for an emergency feature; needs owner decision on how the notice is triggered (UNVERIFIED whether another page or the idle page carries it).
- [HELP-09] `HomeScreen.tsx:483` coming-up card falls back to the raw `asset_id` when the title is missing.
- [HELP-10] No sentence tells residents that live video needs a current browser, or what to do if the video does not start.

## Screenshot plan
Station on air (player + "On air"); standing by (idle panel); offline with an empty station ("Nothing is posted yet."); web preview not enabled; partial-failure amber list (stop the schedule service); emergency notice (`/?emergency=1`).

## UNVERIFIED / open questions
- UNVERIFIED: exact server response contents for idle page and emergency overlay (backend not read).
- UNVERIFIED: what `/api/public/schedule/coming-up` includes (premieres only vs embargo items); the type allows `premiere|embargo|...` (`types.ts:35`).
