# Emergency Alerts  (nav id: eas, section: System Health)
Source files (under `civiccast/apps/portal-operator/src/`): `screens/EasScreen.tsx`, `components/EasPostureBanner.tsx`, `components/AuthRequiredState.tsx`,
`components/ConfirmDialog.tsx`, `screens/contribution-format.ts` (`hasRole` :90). Server: `civiccast/eas/router.py`, `eas/service.py`, `eas/models.py`, `app.py` (:526, :564, :1724).
Route: `#/emergency-alerts`.
Who can open it: nav item requires `setup_admin`, `support_admin` or `meeting_operator` (`Sidebar.tsx:179`). Opening the URL with another role shows a note (below).

## What it is for
Shows public-safety alerts (CAP/IPAWS, National Weather Service, AMBER) that the station has pulled in from configured feeds, and lets an
operator put one on a channel as a crawl, an overlay or a full-screen slate, and take it down again. CivicCast says on screen, permanently,
that it is **not** an EAS device. Severe-or-worse alerts are also put on air **automatically** (see HELP-02).

## What the user sees (top to bottom)
1. h1 `Emergency Alerts` (`EasScreen.tsx:360`) + "Ingest and display CAP/IPAWS, NWS, and AMBER public-safety alerts on your channels." (:362).
2. Posture banner (always, cannot be closed): label `Public-safety display — not an EAS device`; text "CivicCast ingests and displays public-safety alerts (CAP/IPAWS, NWS, and AMBER) as on-channel information — a crawl, an overlay, or an operator-confirmed slate. It is not an EAS device: it does not relay the FCC Part 11 EAS signal, generates no SAME headers, and never automatically pre-empts programming. The mandatory Part 11 relay remains the cable operator's certified headend equipment." (`EasPostureBanner.tsx:24-31`).
3. `Channel` picker (dropdown of channel ids, or a text box if the channel list is empty; default value `gov`, :295). If you cannot display: "(read-only — displaying alerts requires the meeting operator or setup admin role)" (:402).
4. `Alert sources` list; 5. `Active alerts` list; 6. `On-channel now` list.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Channel` | Chooses which channel the buttons act on and which decisions are listed | `GET /api/staff/eas/decisions?channel_id=` | read: `setup_admin`,`support_admin`,`meeting_operator` | channel list from `GET /api/staff/cable/channels` |
| `Show crawl on <channel>` | Puts the alert on that channel as a scrolling crawl | `POST /api/staff/eas/alerts/{id}/display` `{channel_id,mode:"crawl",operator_confirmed:false}` | `setup_admin` or `meeting_operator` (`eas/router.py:227`) | Fires immediately, no confirm, no success message; the row appears under `On-channel now` |
| `Show overlay` | Same with mode `overlay` | same | same | Same |
| checkbox `Confirm full-screen takeover` + `Forced slate` | Full-screen takeover | same with `mode:"forced_slate",operator_confirmed:true` | same | `Forced slate` is disabled until the box is ticked; the tick resets after each use (:192). Server refuses forced slate without confirmation (`eas/service.py:107`) |
| `Clear` (in `On-channel now`) | Takes the alert off the channel | `POST /api/staff/eas/decisions/{id}/clear` | same | ConfirmDialog "Take this `<mode>` down on `<channel>`?"; body for forced slate "This ends the full-screen public-safety takeover immediately. Residents watching that channel go back to regular programming."; otherwise "This removes the public-safety alert from the channel immediately. Residents watching lose it until it is displayed again."; confirm `Clear alert` (`:429-437`) |

There is no control anywhere in the console to add, edit, enable or delete an alert source or to enter a manual alert: `upsertEasSource`, `deleteEasSource`, `createManualEasAlert` exist in `api/client.ts:1792-1813` but no screen calls them (searched `src/`). Source writes are server-limited to `setup_admin` (`eas/router.py:37`).

## States
| State | Text |
|---|---|
| Identity loading | `Loading…` |
| Identity failed (not a permission issue) | posture banner + `Could not verify your staff identity (<detail>). Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then retry once the local API is running.` (`AuthRequiredState.tsx:8-10`) |
| Wrong role | posture banner + "The Emergency Alerts console requires the setup admin, support admin, or meeting operator role. Ask your station admin for access." (:350) |
| Sources loading / empty | `Loading sources…` / "No alert sources are configured yet. Add an NWS, AMBER, or IPAWS (COG) feed to begin ingesting public-safety alerts." (:100) |
| Alerts loading / empty | `Loading alerts…` / `No active alerts.` |
| On-channel loading / empty | `Loading…` / `Nothing is being displayed.` |
| Errors | red banners `Could not load sources.`, `Could not load alerts.`, `Could not display the alert.` (with server detail; forced slate without confirm -> 409 text "A forced full-screen slate must be confirmed by an operator; CivicCast never auto-preempts (it is not an EAS device).") |
| Offline | no dedicated state |

## Typical task flows
1. Check feeds: open page -> read `Alert sources` (label, kind, minimum severity `>= severe`, `polling` or `disabled`) and `Active alerts` (event, severity badge, headline, areas).
2. Show an alert: pick channel -> `Show crawl on <channel>` or `Show overlay` -> confirm it appears under `On-channel now`.
3. Takeover: tick `Confirm full-screen takeover` -> `Forced slate` -> later `Clear` -> `Clear alert`.

## Statuses and words on this screen
- Severity badge (raw lowercase, `SeverityBadge` :72): extreme (red), severe (amber), moderate / minor (blue), unknown (green).
- Source line: `(<kind> · ≥ <severity floor>)` e.g. `nws-cap`, `ipaws-cap`, `amber-cap`, `manual` (`eas/models.py:182-186`); `polling` (green) when enabled, `disabled` (grey). `polling` only means enabled, not that the last poll worked (source health goes to Alerts as `eas-source-unavailable`, `app.py:526-560`).
- Decision list shows `<channel id>` and raw `mode` (`crawl`, `overlay`, `forced_slate`).
- How the server maps severity to the public overlay: extreme -> emergency, severe -> warning, moderate/minor/unknown -> watch (`eas/service.py:40-44`).

## Related settings / env / CLI / API
`/api/staff/eas/{sources,alerts,alerts/manual,alerts/{id}/display,decisions,decisions/{id}/clear}`; public overlay read `GET /api/public/cg/emergency-overlay` (provider wired at `app.py:3169`); poll worker `EasPollWorker` (`app.py:1724`); auto-surface `_build_eas_auto_surface` (`app.py:564`).

## Help-text findings
- [HELP-01] EasScreen.tsx:100 "Add an NWS, AMBER, or IPAWS (COG) feed to begin ingesting" - there is no way to add a feed in the console (see Controls). The only route is the API (`PUT /api/staff/eas/sources/{id}`, setup admin). Fix: say who adds feeds and how, or add the form. "COG" and "IPAWS" are undefined.
- [HELP-02] Nothing on screen says that every `severe` or `extreme` active alert is put on air **automatically** on every channel that is ON_AIR (crawl for severe, overlay for extreme) with no operator action (`app.py:564-585`, `eas/service.py:36,56-58`). The banner says only "never automatically pre-empts programming". An operator who reads the screen thinks nothing airs until they click. Fix: add "Severe and extreme alerts appear on every on-air channel automatically; use Clear to take one down."
- [HELP-03] The banner and h1 say alerts display "on your channels"/"on-channel", but the display decision is read by the public overlay endpoint (`app.py:3169`, `eas/service.py:154-175`). UNVERIFIED whether a crawl/overlay is burned into the cable/stream video or only drawn by the resident web player. This decides what an operator may promise the city. The egress side has `raise_cg_emergency_overlay` / `clear_cg_emergency_overlay` hooks (`egress/supervisor.py:182,188`) but no code was found that calls them from an EAS decision. Needs a check of the egress/graphics path.
- [HELP-04] :395 default channel id `gov` is a hard-coded guess; if the station has no `gov` channel the dropdown still lists it (:382). Fix: default to the first real channel.
- [HELP-05] Buttons `Show crawl`, `Show overlay`, `Forced slate` give no success message and no explanation of crawl vs overlay vs slate for a first-time user; `On-channel now` shows raw `forced_slate`.
- [HELP-06] Forced slate uses a checkbox rather than the `ConfirmDialog` used by `Clear`; the checkbox label `Confirm full-screen takeover` does not say it covers the whole picture for residents.
- [HELP-07] `AuthRequiredState` text names "the CivicCast installer handoff" and "a fresh operator-console link" - neither exists as a step a clerk can do; sign-in is on First Setup (`SetupScreen.tsx:1593`). Fix: "Sign in again on First Setup."
- [HELP-08] `polling` (:118) reads as healthy; a failing feed still says `polling`.
- [HELP-09] Page type scale and heading style (h1 `text-lg`, `Alert sources` h2 `text-sm`) differ from the other System Health screens (`text-2xl`); minor visual inconsistency.

## Screenshot plan
1. Page with the posture banner, one source, two active alerts (one severe, one extreme).
2. Channel with an alert on `On-channel now`, and the `Clear` ConfirmDialog.
3. Empty-sources state (fresh station). 4. Wrong-role note (needs a role-limited token).
Setup: a source and alerts must be created through the API/DB (no UI); lab station mock data may already contain some - UNVERIFIED.

## UNVERIFIED / open questions
- UNVERIFIED: HELP-03 (where the crawl/overlay is rendered).
- UNVERIFIED: whether the lab/default install seeds any alert sources; `EasPollWorker` source list and poll interval defaults (`eas/workers.py` not read).
- UNVERIFIED: how long an alert stays under `Active alerts` (depends on CAP `expires`/status; `eas/store.py` not read).
- UNVERIFIED: whether `Forced slate` produces a visible full-screen result in any player (service stores a decision; render path not read).
