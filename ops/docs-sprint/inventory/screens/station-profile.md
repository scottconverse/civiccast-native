# Station Profile  (nav id: station-profile, section: Setup)
Source files (under `civiccast\apps\portal-operator\src\`): `screens\StationProfileScreen.tsx` (StationProfileScreen, StationIdentityPanel, StationBoxProfilePanel, SecurityPanel, RegeneratedKitPanel, CopyPathButton), `components\AuthRequiredState.tsx`, `screens\manual-link.ts`, `api\client.ts:677,701,937,945,989`.
Backend: `civiccast\platform\station_router.py`, `civiccast\installer\station_state.py` (resolve_* loaders 216-410, `update_station_profile_fields` 433-467, `regenerate_recovery_kit` 1003-1082), `civiccast\installer\router.py:1526-1577`, `civiccast\platform\station_box_profile.py`.
Who can open it: sidebar shows it to `setup_admin`, `meeting_operator`, `support_admin` (`Sidebar.tsx:103-106`); the screen repeats the check (`READ_ROLES`, StationProfileScreen.tsx:38). Anyone else sees the blue note "Station Profile requires the setup admin, meeting operator, or support admin role. Ask your station admin for access." (827-828). Only `setup_admin` can save or use the Security buttons (`WRITE_ROLES`, line 39; server `require_any_role("setup_admin")`, station_router.py:129, installer/router.py:1530,1559).

## What it is for
It shows and edits the station's identity (name, time zone, default channel, public web address, the three storage folders, and the live-captions switch), shows what this computer actually has (CPU, RAM, playout engine, readiness colours), and holds two security actions for the admin: sign out every other signed-in browser, and replace the recovery codes with a new set.

## What the user sees
Header H1 "Station Profile" + one grey line (840-841); two side-by-side cards on wide screens, then a full-width card:
1. **Station identity** card (263): read-only tag when not setup_admin; fields; storage roots with Copy path buttons; paragraph about service-account paths; "Show live captions on air" checkbox with a long explanation; Save.
2. **Station box profile (S1)** card (478): ReadinessBadge (green/yellow/red), CPU/RAM/Recommended tier/Playout engine/AI summary default list, "Cable-grade OS:" line, "PEG readiness" list of dimension rows.
3. **Security** card (668): "Sessions" box and "Recovery kit" box.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Station name (278) | Display name | `PUT /api/staff/station/profile` (`put_station_profile`, station_router.py:123) | `setup_admin` | Required; Save disabled if empty. Env `CIVICCAST_STATION_NAME` overrides what is shown and used |
| Timezone (IANA name, or "local") (289) | Free text, placeholder "America/New_York" | same | | Server only trims it (station_state.py:445); no validity check seen (UNVERIFIED elsewhere) |
| Default channel id (301) | Free text channel id | same | | Normal values `public`, `education`, `government` (station_state.py:85-98). Unknown ids are healed to "government" when read (101-113) |
| Public base URL (optional) (312) | Address residents use, placeholder "https://watch.example.gov" | same | | UI sends `null` for a blank box and the server treats null as "leave unchanged" (433-452), so an existing URL cannot be cleared here |
| Media library / Recordings / Backups paths (339,351,363) | Edit the three stored folder paths | same | `setup_admin` | See Help-text findings: in the Python code searched, nothing reads these saved paths to decide where files go |
| Copy path (100) | Copies that path to the clipboard; text becomes "Copied" for 2 s | browser clipboard only | all readers | Silent on clipboard failure |
| Show live captions on air (409) | Switch saved with the profile | `live_captions_enabled` in the same PUT | `setup_admin` | Default OFF in this beta (`LIVE_CAPTIONS_DEFAULT`; station_state.py `resolve_live_captions_enabled`). `CIVICCAST_CAPTION_TAP=off` in the environment forces off; no env can force on |
| Save (441; aria-label "Save station profile") | Sends all fields in one PUT | same | `setup_admin` | Disabled until something changed and name non-empty. Success "Station profile saved."; failure shows server text or "Could not save the station profile." |
| Sign out other sessions (700) -> "Confirm — sign out other sessions" (717) / Cancel (725) | Ends every operator-console session except this browser | `POST /api/staff/installer/sessions/revoke-others` (installer/router.py:1526) | `setup_admin` | Confirmation text: "This immediately signs out every other browser and device signed in as this admin." Result message e.g. "Signed out N other operator-console sessions. This browser stays signed in." or "No other operator-console sessions were signed in. This browser stays signed in." (service.py:1028-1034). Only works if you signed in with the station admin password; otherwise 401 "Invalid staff bearer token." |
| Regenerate recovery kit (756) -> "Confirm — regenerate kit" (776) / Cancel (784) | Creates 8 new recovery codes; **old codes stop working at once**; resets "kit confirmed" to No | `POST /api/staff/installer/recovery-kit/regenerate` (router.py:1555) | `setup_admin` | Confirm text: "This permanently invalidates every existing recovery code and replaces them with 8 new ones." |
| Print kit (606) / Save kit (614) | Print dialog / download `civiccast-recovery-kit-<id>.txt` (codes only, no password) | browser only | | Print sets "action taken" immediately, even if the dialog is cancelled (572), unlike First Setup |
| Checkbox "I have saved or printed the new recovery codes and stored them away from this computer." (625) + Done (641) | Records that the new kit is saved | `POST /api/setup/recovery-kit/acknowledge` | `setup_admin` | "Recording confirmation…" while busy. The new codes exist only in this screen's memory: leaving the page loses them |

## States
- Loading: "Loading…" (identity), "Loading station identity…" (225), "Probing station hardware and playout-engine readiness…" (459).
- Identity failure (any error): "Could not verify your staff identity (<server text>). Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link, then retry once the local API is running." (`AuthRequiredState.tsx:7-9`, shown at StationProfileScreen.tsx:819).
- No station yet (404): "No station identity yet -- complete First Setup to create the station profile before editing it here." (235-236).
- Other errors: "Could not load the station identity.", "Could not load the station box profile.", "No station identity is available yet.", "No station box profile is available yet."
- Read-only roles: "read-only" tag on Station identity and Security; Security shows "Sessions and recovery-kit actions require the setup admin role." (792). Buttons hidden.
- Banner tone note: every Banner has `role="alert"` (63) so even the green "Station profile saved." is announced assertively.

## Typical task flows
1. Rename station / set URL: edit -> Save -> "Station profile saved."
2. Find where recordings live: Copy path -> paste into File Explorer (the page says to use Assets instead for finding a recording).
3. Lost laptop: Sign out other sessions -> Confirm.
4. Lost/never-saved recovery codes: Regenerate recovery kit -> Confirm -> Print/Save -> tick box -> Done.
5. Turn live captions on/off: tick -> Save.

## Statuses and words on this screen
Readiness badge and dimension colours show the raw words "green", "yellow", "red" (uppercase) not the five phrases from `status-language.ts`. Dimensions (from `station_box_profile.py` ~1030-1245): Playout engine, Clock, DeckLink / SDI, TSDuck, Backup destination, AI model memory, Cable-grade OS. Example messages: "GStreamer base engine is ready.", "System clock is not NTP-synced.", "No backup destination is configured.", "<n>GB system RAM is under the recommended floor.", "Not required for this deployment profile." The screen always asks the server for profile `public-meetings` (no selector).

## Related settings / env / CLI / API
`CIVICCAST_STATION_NAME`, `CIVICCAST_STATION_TZ`, `CIVICCAST_STATION_MEDIA_LIBRARY`, `CIVICCAST_STATION_RECORDINGS`, `CIVICCAST_STATION_BACKUPS`, `CIVICCAST_STATION_STORAGE_ROOT`, `CIVICCAST_CAPTION_TAP`, `CIVICCAST_ALLOW_FIRST_ADMIN_RESET`. Default folders: `%LOCALAPPDATA%\CivicCast\{media,recordings,backups}` of the service account (station_state.py:1154-1170). Related endpoints: `GET /api/staff/station-box-profile`, `GET /api/staff/station-box-profile/readiness` (not used here).

## Help-text findings
- [HELP-01] StationProfileScreen.tsx:339-371 and 375-386 — Storage roots are editable with a Save button, and the page says "this form shows the value currently in effect" — in `civiccast\*.py` the saved paths are read only by this screen's GET (`grep resolve_station_storage_locations`), nothing consumes them to choose where media, recordings or backups are written (the docstring itself says CIVICCAST_UPLOAD_DIR etc. are separate, station_state.py:385-399). A clerk who edits a path will believe files moved — fix: make the fields read-only labels ("where CivicCast keeps files") or state plainly that changing them does not move anything.
- [HELP-02] StationProfileScreen.tsx:507-509 — "Cable-grade OS: Single-Windows-PC certification for 24/7 cable is pending the soak result — see MASTER §13.1." — internal document reference and a cable claim shown to every station, even though the readiness row for public-meetings says "Not required" — fix: show only for cable deployments and remove "MASTER §13.1".
- [HELP-03] StationProfileScreen.tsx:478, 838-841 — "Station box profile (S1)" and "per S1: identity is what you edit, readiness is what the box actually detects" and "PEG readiness" "Recommended tier" "qualifies for" — internal spec names and jargon — fix: "This computer" card; define PEG once.
- [HELP-04] StationProfileScreen.tsx:289, 301 — "Timezone (IANA name, or "local")" and "Default channel id" — a non-technical admin does not know IANA names or channel ids; no list of valid values (public, education, government) — fix: dropdowns.
- [HELP-05] StationProfileScreen.tsx:412-420 — live-captions text is long, says "rarely a channel restarts itself" and "their audio discarded"; honest but alarming, and it never says the default is OFF in a way a reader can find quickly ("Off when the station is installed in this beta") — fix: lead with the current state and the one-line recommendation.
- [HELP-06] StationProfileScreen.tsx:735-738 — "This requires being signed in with the current admin password -- it is not a way back in if you are locked out." — the server only requires a `setup_admin` token (any session), not the password; also nothing warns that leaving the page before saving loses the new codes (the first-run kit survives reloads; this one does not) — fix: add "Do not leave this page until you have saved the codes."
- [HELP-07] StationProfileScreen.tsx:681-683 — "Sign out other sessions" says "every OTHER operator-console session" and "signed in as this admin"; it fails with an unexplained 401 text ("Invalid staff bearer token.") if the user signed in by a staff token rather than the admin password — fix: translate that error.
- [HELP-08] StationProfileScreen.tsx:312 — "Public base URL (optional)" no explanation of what it is used for; clearing it silently does not work (see controls).
- [HELP-10] AuthRequiredState.tsx:7-9 (shown when sign-in is missing/expired) — "Sign in again from the CivicCast installer handoff or ask a setup admin for a fresh operator-console link" — the installer-handoff link was retired (router.py:1214-1226) and the real way back in is First Setup's "Admin sign-in" — fix: "Open First Setup and sign in with the admin password."
- [HELP-09] Readiness colours shown as bare "GREEN/YELLOW/RED" (120,135) while every other screen uses "Ready / Check before meeting / Do not broadcast yet" — fix: use `readinessLabel`.

## Screenshot plan
1. setup_admin view fully loaded (identity + box profile + Security collapsed state).
2. A meeting_operator or support_admin view (read-only tags; needs a token with that scope made by `civiccast token issue --scopes`).
3. Dirty form with Save enabled, then "Station profile saved." banner.
4. Sessions confirm state; Recovery kit confirm state; the "New recovery kit ready" panel (mask codes in the capture).
5. Box profile with a yellow row (e.g. no backup configured) and the Cable-grade OS line.
6. 404 state (before First Setup) if capturable.

## UNVERIFIED / open questions
- UNVERIFIED: whether any non-Python launcher (PowerShell/installer, native supervisor in other dirs) reads `station-state.json` storage locations to place recordings; only `civiccast\**\*.py` searched.
- UNVERIFIED: time zone value validation downstream (`app.py` `_station_tz`).
- UNVERIFIED: that `meeting_operator`/`support_admin` can load the screen end to end (role lists read from code, not run).
- UNVERIFIED: which dimensions appear for the `public-meetings` profile in practice (read code branches ~1030-1245, not executed).
