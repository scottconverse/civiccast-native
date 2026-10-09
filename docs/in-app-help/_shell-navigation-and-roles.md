> Historical beta.10 audit snapshot dated 2026-10-03; retained for traceability, not current UI or user guidance.

# Navigation, top bar and roles (nav id: _shell-navigation-and-roles)

A shared surface: the top bar, the sidebar (6 sections, 37 entries), the "not found" page and the role model. Manual authority: `docs/manual/src/11-signing-in.md` (sections "Find your way around the console", "Which screens you can see") and Appendix F (`app-roles`).

## Where the help text lives now
`civiccast/apps/portal-operator/src/components/shell/Sidebar.tsx` (labels, section tooltips, profile card, footer), `TopBar.tsx` (logo, pill, clock, theme, badge, Sign out, drawer button), `Layout.tsx` (skip link, drawer), `App.tsx` (not-found and loading text), `auth/roles.ts` (role labels). Lines confirmed by opening each file (HEAD 0b35aef6).

## Current text
| String | Where | Source line |
| --- | --- | --- |
| "CivicCast station" over "Public meetings" | sidebar profile card | Sidebar.tsx:84-85 |
| Section names Help, Setup, Run Meeting, Review Records, Publish, System Health | sidebar | Sidebar.tsx:90, 96, 118, 139, 160, 173 |
| Section tooltips: "Operator manual, glossary, and provider setup guides" / "Admin setup and station configuration" / "Night-of-broadcast controls" / "Assets, captions, summaries, agendas, and signed records" / "Resident portal, archives, and notifications" / "Readiness, federation, and advanced health" | `title` on each section header | Sidebar.tsx:91, 97, 119, 140, 161, 174 |
| Nav labels for this file's screens: Manual; First Setup; Control Room Setup; Station Profile; Cable Commissioning; AI Models; Custom Fields; Paywall; Readiness; Alerts; Emergency Alerts; Federation | sidebar rows | Sidebar.tsx:93, 100-114, 177-180 |
| "Show <section> navigation" / "Hide <section> navigation" | section button aria-label | Sidebar.tsx:319 |
| "<label> is planned for a later public-beta update." | disabled-row text, no item uses it | Sidebar.tsx:225 |
| "Report a beta issue"; "No GitHub account? That's fine — the link above covers that too. Do not include passwords, recovery codes, staff tokens, or private meeting material."; "Operator-first beta" | sidebar footer | Sidebar.tsx:399, 402-403, 405 |
| "Primary navigation" | sidebar and drawer label | Sidebar.tsx:364; Layout.tsx:102 |
| "No live meeting broadcast" | top-bar pill (fixed) | TopBar.tsx:65, 78 |
| "Local <time> / Next No events scheduled" | top-bar clock (fixed) | TopBar.tsx:93-98 |
| "Switch to dark theme" / "Switch to light theme" | theme button | TopBar.tsx:113 |
| "Open navigation"; "Close navigation"; "Skip to main content" | drawer button, backdrop, skip link | TopBar.tsx:228; Layout.tsx:90, 65 |
| "Page not found" / "This operator route does not exist in this build." + buttons Manual, First Setup, Recording, Reports, Readiness | unknown address | App.tsx:103, 105, 110-114 |
| "Loading this CivicCast screen..." | while a screen loads | App.tsx:251 |
| Role labels: Setup admin, Meeting operator, Records clerk, Publish operator, Support admin | badge hover text only | auth/roles.ts:6-12 |

## What the screen really does
The sidebar lists screens by role: an entry with a role list is hidden until the identity check has loaded, and shown only if one listed role matches. The first admin created on First Setup holds all five roles (token scope `admin`), so on a normal station everyone sees all 37 entries; the console has no screen to add people or give roles. The nav filter is a convenience: each screen and each server route checks the role again. While the first-run recovery kit is unconfirmed, every entry except Manual is grey, Sign out is off and any other address returns to First Setup. The top-bar pill and the "Next" clock text are fixed placeholders that never change.

## Mismatches
| ID | What the text says | What really happens | Severity |
| --- | --- | --- | --- |
| SHELL-01 | Profile card always "CivicCast station" / "Public meetings" (Sidebar.tsx:84-85) | Never shows the station name set in First Setup or Station Profile | cosmetic |
| SHELL-02 | "No live meeting broadcast" and "Next No events scheduled" (TopBar.tsx:78, 98) | Constant placeholders (comment "Sprint 0.3: no live module yet"); unchanged during a live meeting or with a full schedule | misleading (a user will believe the schedule is empty) |
| SHELL-03 | Different names for one screen | Nav "Readiness" = H1 "Safe to broadcast" = "System Health" in other text; "Federation" = "ActivityPub federation"; "Alerts" = "Alerts & monitoring"; "CG Designer" = "CG Board Designer"; "Recording" = "Scheduled recording"; "Contributors" = "Contributor submissions"; page eyebrow "Operations" (Alerts) and "System Health" (Readiness) | misleading |
| SHELL-04 | Roles appear only as raw ids in 403 text and hover-only labels | Nothing explains that a first admin holds all five roles or who grants a role | misleading |
| SHELL-05 | Nav hides Missing Media and Agendas from `setup_admin`; shows Alerts and Federation to roles the server then refuses | Harmless for first-admin tokens; confusing for a role-limited token | cosmetic |
| SHELL-06 | Help tooltip lists "glossary, and provider setup guides" | One entry (Manual) | cosmetic |
| NEW-1 | "Primary navigation" and the nav has no "Sign in" entry | First Setup doubles as sign-in (see `_shell-signin-and-session.md`) | misleading |
| NEW-2 | Footer: "No GitHub account? ... the link above covers that too" | The linked manual section tells people to use "System Health" and a support bundle only a Support admin can make (HELP-03 in `help.md`) | misleading |

## Proposed text
**Profile card:** "<Station name>" over "Operator console". After fix: read the name from Station Profile (`GET /api/staff/station/profile`). Until then: "This station" over "Operator console".
**Top bar (until wired):** remove the pill and the "Next ..." text; keep "Local <time>". If kept, change to "Meeting status: not shown here. See Live and Readiness." After fix: pill "On air: <channel>" or "Not live", and "Next: <title> at <time>".
**Section tooltips:** Help "The CivicCast manual"; Setup "Set up the station and change its settings"; Run Meeting "Run live meetings and what is on the air"; Review Records "Videos, captions, summaries and agendas"; Publish "What residents see, and audience numbers"; System Health "Is the station healthy? Alerts and emergency alerts".
**One short tooltip per screen in this file (a "What this is for" line and a "Who can use this" line).** Use the sidebar name as the one name; make each page H1 match it and drop "System Health" from messages (say "Readiness").
| Screen | What this is for | Who can use it |
| --- | --- | --- |
| Manual | Read the CivicCast manual built into the console | Anyone, even signed out |
| First Setup (after fix: Sign in) | Sign in, or create the station's first admin and recovery kit | Anyone at the station computer |
| Control Room Setup | Register switchers and cameras and build cue panels | Setup admin |
| Station Profile | Station name, time zone, live-captions switch, security actions | Setup admin changes; Meeting operator and Support admin read |
| Cable Commissioning | Four-step test for a station that feeds a cable headend | Setup admin runs; Support admin reads |
| AI Models | Choose the model for captions, summaries and Spanish translation | Setup admin changes; Meeting operator reads |
| Custom Fields | Add your own labels to videos | Setup admin |
| Paywall | Optional paid access to recordings. Not ready for live use | Setup admin |
| Readiness | Can we broadcast right now? | Everyone signed in; some buttons need a role |
| Alerts | Problems CivicCast has flagged | Setup admin, Support admin and Meeting operator can read the list; only Setup admin changes rules |
| Emergency Alerts | Show public-safety alerts on a channel. Not an EAS device | Setup admin, Support admin, Meeting operator |
| Federation | Optional sharing with Mastodon-style sites | Everyone opens it; Publish operator and Support admin act on followers |
**Role help (new, one place):** under the badge hover add a link "What can my roles do?" to `/help#app-roles`. Message text for the first admin: "The account made on First Setup holds all five roles."
**Not found page:** "This address does not exist in this version of the console. Pick a screen from the menu." (drop "operator route").
**Footer:** "Need to report a problem? Open Report a beta issue. You do not need a GitHub account. Never include passwords, recovery codes, staff tokens or private meeting material."

## Notes for the coder
- Edit `Sidebar.tsx` (profile card needs a station-name query), `TopBar.tsx` (pill and clock), each screen's H1 (SHELL-03: `SystemHealthScreen.tsx:1513-1515`, `AlertsScreen.tsx:773-775`, `ActivityPubScreen.tsx:582`, `CgBoardDesignerScreen.tsx:533`, Recording and Contributors screens), `App.tsx` (404 text).
- Gate A pins strings in the rendered console: `sandbox-lab/scripts/In-Sandbox-Report.ps1:3226` looks for "No live meeting broadcast", "Open navigation" or "Setup First setup" (the Setup label over the First setup H1). Any one match passes; if you change all three the T2 render check fails. Update that list in the same change.
- Other pins: `TopBar.test.tsx` (theme button), `Layout.test.tsx` and `e2e/a11y.spec.ts` ("Report a beta issue"), `e2e/cg-bulletins.spec.ts`, `e2e/channel-app-config.spec.ts` ("CivicCast station"), `e2e/route-table-smoke.spec.ts` and `full-ui-walkthrough.spec.ts` ("Page not found"), `SetupScreen.test.tsx` ("Public meetings"); also re-run `Sidebar.test.tsx` (not searched for these strings).
- Code fix needed, not text: wire the pill and clock to live and schedule data (SHELL-02); a station-name query for the profile card; page titles per screen (`document.title` is always "CivicCast Operator", `index.html:6`).
