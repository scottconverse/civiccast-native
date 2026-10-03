# Resident portal shell: header, navigation, routing, accessibility, analytics  (nav id: public-shell, section: Public)
Source files: `civiccast/apps/portal-public/src/App.tsx`, `router.ts`, `analytics.ts`, `main.tsx`, `index.css`, `index.html`, `api.ts`
(all paths below are relative to `civiccast/apps/portal-public/`). Server mount: `civiccast/app.py:2583-2600`.
Who can open it: everyone. No sign-in, no roles. The portal calls only `/api/public/*` endpoints.

## What it is for
The shell is the frame around every resident page: a title, three nav links, a "Report a beta issue" link and a hash router. It is served by the
station's control plane at the web root `/` (`civiccast/app.py:2594-2600`, mounted only when the packaged-portal env var
`CIVICCAST_PUBLIC_PORTAL_DIST` is set; install layout sets it to `<INSTDIR>\runtime\Lib\site-packages\civiccast\apps\portal-public\dist`,
see `civiccast/native/supervisor/install_layout.py:116-119,249-255`). The staff console is a separate app at `/operator/`.

## What the user sees (top to bottom)
1. A hidden "Skip to main content" link, visible only when it receives keyboard focus (`src/App.tsx:204`).
2. Header: small label "CivicCast Portal" (107-109), H1 "CivicCast public portal" (110-112), blurb "Watch the current broadcast, see upcoming premieres, and replay published meetings from the resident archive." (113-116).
3. Nav (`aria-label="Portal sections"`): Home, Recordings, Schedule (120-131); current page gets `aria-current="page"`. Recordings stays highlighted on a recording's watch page (125).
4. Link "Report a beta issue" (139), opens in a new tab.
5. Small print: "Do not include passwords, recovery codes, staff tokens, or private meeting material in reports." (143)
6. `<main id="main-content">` with the current view.
Page title in the browser tab: "CivicCast Portal"; `<html lang="en">` (`index.html:2,6`). There is no footer.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Home | goes to `#/` | none | none | |
| Recordings | goes to `#/recordings` | none | none | active also on `#/watch/...` (`App.tsx:125`) |
| Schedule | goes to `#/schedule` | none | none | |
| Report a beta issue | opens `/operator/#/help#report-without-github` in a new tab (`App.tsx:35,134-139`) | none | none | lands in the STAFF console manual (comment at `App.tsx:20-35` says no staff sign-in needed for it; UNVERIFIED in `civiccast/docsite/router.py`) |
| Skip to main content | moves keyboard focus to `<main>` without changing the route (`App.tsx:188-191`) | none | none | |

## Routes (hash router, `src/router.ts:28-56`)
| URL | View |
|---|---|
| `#/` (or anything unrecognized) | Home (`public-home.md`) |
| `#/recordings?q=&year=&body=&cf.<key>=&page=` | Browse recordings (`public-recordings.md`) |
| `#/watch/<asset_id>` | One recording (`public-watch.md`) |
| `#/schedule?channel=<id>` | Channel guide (`public-schedule.md`); channel defaults to `public` (53) |
| `?manifest=<url>` (real query string, any route) | "Direct video preview" player-only view that overrides the route (`App.tsx:37-39,148-149,233-247`) |
| `/?subscription=confirm|unsubscribe&token=<t>` (real query string) | Home reads it and confirms/unsubscribes (`screens/HomeScreen.tsx:49-57,197-215`) |
| `/?emergency=1` | Home fetches the emergency notice (`HomeScreen.tsx:59-61,107-115`) |
| `?token=<t>` in search or hash on a watch page | magic-link sign-in for paid content (`PaywallGate.tsx:108-119`) |
Manifest-override text: heading "Direct video preview", "This link may show a live feed or a recording." (`App.tsx:238-242`).

## States
- No global loading/offline state; each view has its own. A bad hash falls back to Home (`router.ts:55`).
- JavaScript required (single-page app). UNVERIFIED: no `<noscript>` text exists (none in `index.html`).

## Typical task flows
1. Resident opens the station address, lands on Home, uses nav to reach Recordings or Schedule.
2. Resident shares a link: every view is a copyable URL (`router.ts:4-9`).
3. Keyboard user presses Tab once: skip link appears; after the first click/keypress, route changes move focus to the page's `h2[tabindex=-1]` (`App.tsx:79-99`).

## Statuses and words on this screen
Not applicable (no status words in the shell).

## Accessibility and language features (as implemented)
- Skip link (WCAG 2.4.1), focus moves to the new view heading after navigation (`App.tsx:63-99`), `min-h-11` (44px) tap targets, `aria-live` regions on loading/status text, `aria-pressed` on caption buttons, visible focus rings.
- Language: page is English only. No language switcher, no translation of portal text (`grep` for i18n/hreflang found none). Spanish appears only as a caption track name served by the video manifest (see `public-player-captions.md`).
- No dark/light toggle; fixed dark theme (`index.css:4-8,13`).

## Analytics (privacy)
- One `schedule_browse` event per view change with property `section` = `portal_home`, `recordings_browse`, `watch_recording`, `channel_guide`, `watch_manifest_override` (`App.tsx:41-61`).
- Player events `playback_start`, `playback_heartbeat` (every 60 s, includes `position_seconds`), `playback_complete`, `playback_error` (`HlsPlayer.tsx:7,104-157`).
- Sent to `POST /api/public/app/analytics/events` with a random per-event id, no viewer id/cookie (`analytics.ts:4-16,60-76`). First 403/503 turns it off for the browser session via `sessionStorage` key `civiccast.analyticsDisabled` (`analytics.ts:31-50`). There is no resident-facing notice or opt-out.

## Related settings / env / CLI / API
`CIVICCAST_PUBLIC_PORTAL_DIST`, `CIVICCAST_OPERATOR_CONSOLE_DIST`, `/api/public/app/analytics/events`.

## Help-text findings
- [HELP-01] `src/App.tsx:139` "Report a beta issue" — a resident is sent to `/operator/#/help#report-without-github`, the manual inside the staff console, with no explanation — missing/confusing: residents see a staff product and a "GitHub account" section. Suggest a plain resident page ("Tell the station about a problem": email/phone from station settings) or label it "Report a problem with this page (opens the station help page)".
- [HELP-02] `App.tsx:143` "Do not include passwords, recovery codes, staff tokens, or private meeting material in reports." — jargon aimed at staff, shown to the public; suggest "Please do not put passwords or private information in your report."
- [HELP-03] `App.tsx:116` blurb mentions "premieres" and "resident archive" — station jargon; suggest "Watch the meeting that is on now, see what is coming up, and replay past meetings."
- [HELP-04] No page in the portal explains captions, languages, agenda use, or how to subscribe; no Help link in the header. Missing: add a short "How to use this site" page.
- [HELP-05] `analytics.ts` collects playback counts but the portal has no privacy statement visible to residents. Missing: one-line "We count views without recording who you are" (confirm wording with owner).

## Screenshot plan
Header at desktop width; header after Tab (skip link visible); `?manifest=` view; a deep-link to an unknown hash showing Home.

## UNVERIFIED / open questions
- UNVERIFIED: that the report-without-github anchor exists in the packaged operator manual (needs `civiccast/docsite/router.py` and the manual page).
- UNVERIFIED: what HTTP port the station serves `/` on (see `installer-install-layout.md` for the installer's port facts).
