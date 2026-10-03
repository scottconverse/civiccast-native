# First Setup  (nav id: setup, section: Setup)
Source files (all under `civiccast\apps\portal-operator\src\` unless noted):
`screens\SetupScreen.tsx` (SetupScreen + RecoveryKitPanel, CommissioningDefaultsPanel, SignedInPanel, StorageSetupPanel, BackupSetupPanel, R2ConciergeCard, ProviderReadinessPanel, CostForecastPanel), `components\setup\SourceUploadWizard.tsx`, `auth\recoveryKitGate.ts`, `api\client.ts:621-780,931-1010`, `routes.ts`, `App.tsx:135-144,222-238`.
Backend: `civiccast\installer\router.py` (public_router `/api/setup/*` ~1211-1495; staff_router `/api/staff/installer/*`), `civiccast\installer\station_state.py`, `civiccast\installer\service.py`, `civiccast\installer\cdn_bridge.py`, `civiccast\auth\roles.py`.
Who can open it: everyone, including signed-out visitors. `/setup` is a "public route" (`routes.ts:97-99`), so the missing-session bounce in `App.tsx:236` never redirects it. The sidebar entry has no `requiredRoles` (`Sidebar.tsx:100`). The alias paths `/login` and `/sign-in` land here (`routes.ts:65-66`). First-time creation of the admin and sign-in/recovery only work from a browser on the station computer itself (loopback check, `router.py:1211-1251`); other computers get HTTP 403.

## What it is for
First Setup is the page that creates the station's one local admin account and shows the one-time recovery kit, on a brand-new station. On an already-configured station the same page becomes the sign-in page: "Admin sign-in" with the saved password, or "Use recovery code" if the password is lost. Once signed in (or right after setup) it also hosts the setup tools: camera/test media, backup folder, a storage estimate, and cloud/provider credentials.

## What the user sees
Order top to bottom (`SetupScreen.tsx:1641-2082`):
1. Header: small label "Setup", H1 "First setup", line "Create the station identity, first local admin, and recovery kit before a public meeting." (always shown, even on a configured station; 1643-1651).
2. One of the status banners if the setup-state read fails (see States).
3. Not set up yet: **Durable storage** card (566-634; button "Prepare storage"), then either the placeholder "Create the first admin after storage is ready" (1937-1947) or the **first-admin form** (1949-2068).
4. Set up but signed out: optional "You were signed out" notice, optional "Recovery kit never confirmed" warning, "Setup complete" card, **First-run defaults** card (449-538), **Admin sign-in** form (1583-1639) and **Use recovery code** form (1817-1933).
5. Right after creating the admin: **Recovery kit ready** panel (220-418). Navigation is locked until the kit is confirmed.
6. After the kit is confirmed, or signed in: a green "Setup complete" / "Signed in" / "Account recovered" card plus First-run defaults, then the admin tools block (1314-1327, shown when `setup_complete`, a just-completed setup or a sign-in, and no kit gate is up; 1534-1535): Camera or test media, Backup destination, Storage and viewing estimate, Provider setup.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Prepare storage (618) | Creates/activates the local database for meeting records, captions, summaries, subscriptions | `POST /api/setup/storage` -> `public_storage_setup` (router.py:1388). Skipped if `DATABASE_URL` is set, just returns status | Before setup: loopback only. After setup: staff token AND `setup_admin` (1383-1386) | Disabled while loading/preparing. Error text from server (503 on storage failure) |
| Station name (1969) / Admin display name (1980) / Admin username (1993) | Required text, `max` 120/120/80 | Part of `POST /api/setup/first-admin` payload | Loopback pre-setup | Error on blur "Station name is required." etc. |
| Admin password (2004) + Show/Hide | Min 12 chars, live counter "(n/12)" | same | | Help `Use at least 12 characters (n/12).` |
| Confirm admin password (2018) | Must match | client only | | "Passwords do not match." |
| Where will you keep the recovery kit? (2030) | Free-text note stored as `recovery.destination`; not a path and nothing is written there (models.py:334-347) | same | | Required |
| Resident portal URL (2044) | Optional; saved as `public_base_url` | same | | Blank -> null |
| Create first admin (2059) | Creates admin, 8 recovery codes, first console token; kit panel appears | `POST /api/setup/first-admin` (router.py:1415); `complete_first_admin_setup` (station_state.py:645) | Loopback; 409 if already set up | Disabled until all required fields valid. Server defaults not shown on the form: 3 channels (public/education/government), default channel "government", timezone "local", **Test mode**, sample content ON, starter schedule ON (models.py:349-356). Sample content seeds in the background (router.py:260-288) |
| Print kit (359) | Opens browser print dialog | `window.print()` | | Unlocks the confirm checkbox only after `afterprint` fires (290-294) |
| Save kit (367) | Downloads `civiccast-recovery-kit-<kit id>.txt` including **the admin password in plain text** and the 8 codes | client only | | Unlocks checkbox at once |
| Checkbox "I have saved or printed this kit..." (376-392) | Required before continuing | | | Disabled until Print/Save used; helper "Use Print kit or Save kit first." |
| Continue to the console (404) | Records that the kit was saved | `POST /api/setup/recovery-kit/acknowledge` (router.py:1447) | staff token + `setup_admin` post-setup | Label while busy "Recording confirmation...". 401/409 releases the gate (1512-1515). Browser also warns on leaving the page while the kit is unconfirmed (1546-1554) |
| I found the kit — it is stored safely (1797) | Same acknowledge call from the sign-in view | same | | Shown only when `recovery_kit_acknowledged === false` |
| Sign in (1631) | Password sign-in; stores a fresh console token in this browser; redirects to `/health` (or the page you were bounced from) | `POST /api/setup/login` (router.py:1469) | Loopback only, rate limited | Wrong guesses burn a budget; correct password always gets through (router.py:1163-1191). Does not sign out other browsers |
| Recover account / Confirm — consume recovery code (1926) | Two-click. Uses one of 8 one-time codes and sets a new password (min 12) | `POST /api/setup/recover` (router.py:1487) | Loopback only | First click arms and shows "This permanently consumes one recovery code — only 8 exist for this station. Click Recover account again to confirm." (1909) |
| Sign in again (1681) / Try again (1711) | Re-read setup state after stale token / rate limit | `GET /api/setup/station-state` | | Stale token is dropped from storage |
| Camera or test media card (SourceUploadWizard) | See next table | | | |
| Verify backup (720) | Writes, reads and deletes a probe file in the folder and remembers the path | `POST /api/staff/installer/backup` -> `configure_backup` (service.py:1119-1122) | `setup_admin` (router.py:722) | Disabled when folder blank. Rejects `/mnt/c/...` and drive-relative paths (service.py:1137-1150) |
| Storage estimate inputs: Hours per meeting / Meetings per month / Average viewers (1245-1281) | Pure browser arithmetic: stored GB = hours x meetings x 2; viewer GB = stored x viewers | none | none | Shows "Varies by provider" instead of a price |
| Provider cards: Save details (1137), Test connection (1159), Record proof (1083), Provision for me (804), Retry (832) | See Provider section | see below | `setup_admin` for every write | Fields disabled and warning shown if not setup_admin (925-933) |

### Camera or test media (`SourceUploadWizard.tsx`)
Six choice buttons (`CHOICE_COPY`, 25-71): "USB webcam or HDMI capture", "Phone or tablet broadcast app", "Hardware encoder or AV system", "NDI source", "Bundled sample video" (default selected), "Upload a short test video". Link "Read the full walkthrough in the manual" (212). Badge "not set up yet" or "N source(s)" (225).
| Control | What it does | API | Role |
|---|---|---|---|
| Source name + stream address + "Save meeting source" (291) | Creates a live source on channel `government` (hard-coded, 157) | `POST /api/staff/installer/source-setup/live-source` (router.py:664) | `setup_admin` |
| "Create sample media" (308) | Generates a 2-second sample video, runs ingest checks, adds to Assets | `POST .../source-setup/sample-upload` (router.py:688) | `setup_admin` |
| Title / Video file / Notes + "Upload test media" (362) | Uploads a clip via `uploadAssetFile` with `selectForRehearsal: true` | asset upload endpoint (`api/client.ts:805`) | UNVERIFIED role gate of the asset upload route |
Result box: "Ready: <id>" plus message and "Next step." (116-118). 503 text when storage not ready: "Durable storage is not ready. Open Setup and prepare storage before adding a source." (service.py:2415).

### Provider setup (`ProviderReadinessPanel`, 845-1210)
Cards come from `GET /api/staff/installer/provider-readiness` (any signed-in role). Providers in code order: Local resident portal, Backup destination, Internet Archive, YouTube, Subscriber notices, Local archive folder, Cloudflare R2, BunnyCDN, Fastly Object Storage, Akamai Object Storage, Podcast feed, Federation (service.py:2096-2312). Each card: label, status pill, message, "Required."/"Optional." + next step, a collapsed "Setup guide" (What you need / Steps / "Open provider setup" / "Read more in the manual" / "Proof required." / "Proof evidence."), then forms.
- Credential form: heading "Save provider details" (or "Or enter R2 details manually"), "CivicCast stores these locally and never shows secret values again." Button "Save details" -> `POST /api/staff/installer/provider-credentials` (`setup_admin`). Success: "Details saved. Run live proof before marking this provider ready."
- "Test connection" (Cloudflare R2 and BunnyCDN only, `CDN_TEST_PROVIDER_IDS` line 53) -> `POST .../provider-credentials/{id}/test-connection`; shows server message e.g. "Connected to the CDN with the saved credentials." / "Could not reach the CDN with these credentials. Check them and try again." (cdn_bridge.py). Fastly and Akamai have credential forms but no Test connection button here, although their setup steps say "Run Test connection" (service.py:2253,2273).
- "Record redacted proof" box (only when status is needs_live_proof): free-text "Evidence reference" + checkbox "I reviewed the proof and removed tokens, passwords, private keys, and resident data." + "Record proof" -> `POST .../provider-proof` (`setup_admin`). The server only stores the typed reference string and rejects strings containing token=/secret=/password=/private_key= (service.py:1202-1249); it does not itself run a live test.
- **CDN concierge (recommended)** card inside the Cloudflare R2 card: password field "Cloudflare API token", button "Provision for me" -> `POST /api/staff/installer/cdn-concierge/r2` (`setup_admin`): verifies token, creates bucket, enables public domain, derives keys, saves them, then health-checks (router.py:610-644). Token is not stored. If R2 not enabled: warning text + link "Enable R2 on Cloudflare" + "Retry".

## States
- Loading: "Checking setup state..." (1655). Providers: "Checking provider setup..." (936).
- Generic failure: "Could not read setup state. <server text>" (1720).
- Stale console token (HTTP 401): H2 "This browser's console sign-in is no longer valid", button "Sign in again" (1668-1682). Usually auto-handled: token dropped and notice "You were signed out" (1764) shown above the sign-in cards.
- Rate limited (429): H2 "The station is cooling down after too many requests" + "Try again" + the sign-in form (1696-1715). Server text: "Too many sign-in attempts from this station. Wait N seconds, then try again with the correct password, or use a printed recovery code." (router.py:1093).
- Not on station computer (403): H2 "First setup can only be done from the station computer itself" (1730).
- Not set up: storage card + "Create the first admin after storage is ready" until storage ready.
- Offline/unreachable server: UNVERIFIED (no special text; falls to the generic error with the browser's fetch message).
- Provider list error: "Provider readiness could not load." (941). Backup: "Backup setup failed." (725).

## Typical task flows
1. Brand-new station (on the station PC): open `/setup` -> Prepare storage -> fill form -> Create first admin -> Print kit or Save kit -> tick checkbox -> Continue to the console -> tools appear.
2. Returning operator: `/setup` (or `/login`) -> Admin sign-in -> lands on `/health` (or the page originally requested).
3. Lost password: Use recovery code -> Recover account -> Confirm — consume recovery code -> signed in with the new password.
4. Rehearsal without a camera: Camera or test media -> "Bundled sample video" -> Create sample media -> then open the readiness screen (result text says "Open System Health and select Check broadcast readiness...", SourceUploadWizard.tsx:108).
5. Cloud storage: Provider setup -> Cloudflare R2 card -> create token elsewhere -> paste -> Provision for me.

## Statuses and words on this screen
Provider/backup pills use `readinessLabel` (`status-language.ts`): Ready, Check before meeting, Do not broadcast yet, Not set up yet, Needs IT help. Raw values seen: ready, not_set_up, needs_live_proof, needs_it_help, proof_passed. First-run defaults card: Mode "Test mode" / "On-air mode"; "Dashboard commissioning" via `stateLabel` ("Not ready"/"Ready"/"Not set"). Storage: "Storage ready".

## Related settings / env / CLI / API
`CIVICCAST_STATION_STATE_PATH` (default `%LOCALAPPDATA%\CivicCast\station-state.json`, station_state.py:599-609), `CIVICCAST_ALLOW_FIRST_ADMIN_RESET=1`, `CIVICCAST_BACKUP_DIR`, `DATABASE_URL`, `CIVICCAST_AUTH_RATE_LIMIT`, `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS`. Related staff endpoints not on this screen: `/api/staff/installer/sessions/revoke-others`, `/recovery-kit/regenerate`. The first admin's token carries scope `admin`, which expands to all five roles (roles.py:22-23; station_state.py:807-811); narrower roles only exist for tokens made with `civiccast token issue --scopes` (cli.py:2047-2096) or `CIVICCAST_STAFF_TOKENS`.

## Help-text findings
- [HELP-01] SetupScreen.tsx:1649 — "Create the station identity, first local admin, and recovery kit before a public meeting." — shown on a configured station too, where the page is really the sign-in page; the sidebar calls it "First Setup" and there is no "Sign in" entry — fix: when setup is complete show "Sign in to CivicCast" and mention the sidebar label.
- [HELP-02] SetupScreen.tsx:555,1668-1672 — "CivicCast saved a fresh console token in this browser" / "console token" — jargon — fix: "You are signed in on this browser."
- [HELP-03] SetupScreen.tsx:558 and service/station_state next_step strings — "Next step: open System Health and confirm readiness before the meeting." — the sidebar group is "System Health", the item is "Readiness", and the page H1 is "Safe to broadcast" (SystemHealthScreen.tsx:1515) — three names for one place; fix: pick one name and use it everywhere.
- [HELP-04] SetupScreen.tsx:682-685 — "Backup destination ... Choose the folder or drive CivicCast should verify before meetings." / button "Verify backup" — it only writes and deletes a small test file (service.py:1083); I found no code that copies station data there on a schedule (`last_backup_at` is read but never written) — a clerk will assume backups are running — fix: "This only checks the folder can be written to. It does not make a backup yet." plus say how backups are actually made.
- [HELP-05] SetupScreen.tsx:1141 and 1037-1039 — "Run live proof before marking this provider ready." / "Record redacted proof ... Save only a file path, URL, or release evidence reference after secrets have been removed." — for Internet Archive, YouTube, notices and archive folder there is no "run proof" control on this screen, only a box to type a reference, and it is self-attested; "redacted", "evidence reference", "live proof" are unexplained — fix: explain what to do in plain steps or hide the box until a proof tool exists.
- [HELP-06] service.py:2253,2273 — Fastly and Akamai setup steps say "Run Test connection" but those cards have no Test connection button (SetupScreen.tsx:53) — fix: add the button or remove the step.
- [HELP-07] SetupScreen.tsx:760-763 — "Your station's internet can serve about 200 viewers directly... free until the night everyone shows up." — hard-coded numeric claim and cost claim with no source in code — fix: verify or soften.
- [HELP-08] SetupScreen.tsx:921-922 — "Required items protect the local tester path." — "tester path" is internal beta language.
- [HELP-09] SetupScreen.tsx:2031 — help text for the recovery-kit note is good; but the form never tells the user it will start in **Test mode** with sample content and a starter schedule (server defaults, models.py:349-356) and nothing on screen says how to leave test mode — fix: add a sentence under the form button.
- [HELP-10] SourceUploadWizard.tsx:39 vs 37 — "Do not paste camera passwords here" while the placeholder is an `rtmp://` address; no explanation of what a stream address is or where to get it — fix: add where to find it.
- [HELP-11] Station kit text — the saved kit contains the plain admin password (SetupScreen.tsx:258,370-372). Stated honestly on screen, but "stored it away from this computer" (385) does not warn against emailing or cloud-syncing the file in Downloads — fix: add that sentence.

## Screenshot plan
1. Fresh station, storage not ready (needs a reset station, or `CIVICCAST_STATION_STATE_PATH` pointing to an empty file; do not touch the live station).
2. Create-first-admin form with validation errors.
3. Recovery kit panel (with checkbox locked, then unlocked).
4. Signed-out configured station: Setup complete + First-run defaults + both sign-in cards, with and without the "Recovery kit never confirmed" banner.
5. Recovery two-click armed state.
6. Signed-in tools: Camera or test media (each choice), Backup destination ready and needs attention, Provider setup with Cloudflare R2 card expanded, CDN concierge, one "Setup guide" open.
7. Non-setup_admin view with the yellow "Setup admin role required..." banner.

## UNVERIFIED / open questions
- UNVERIFIED: whether anything automatically backs up to the verified folder (only grepped `civiccast\`; `last_backup_at` never set).
- UNVERIFIED: role gate on the asset upload endpoint used by "Upload test media" (not traced).
- UNVERIFIED: the "about 200 viewers" figure and "free" claim for Cloudflare.
- UNVERIFIED: what the screen shows when the control plane is unreachable.
- UNVERIFIED: `GET /api/staff/auth/me` role list shape beyond `roles` (not opened).
- UNVERIFIED: the sidebar on `/setup` gets roles from SetupScreen's own `staff-identity` query because the shell query is disabled on public routes (App.tsx:160); inferred from shared query key, not run.
