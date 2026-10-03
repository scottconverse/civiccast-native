# App Admin  (nav id: appadmin, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/AppAdminScreen.tsx` (line numbers below), `.../screens/app-admin-format.ts`, `.../components/ConfirmDialog.tsx`,
`.../auth/roles.ts`, `.../api/client.ts:1497-1600`, `.../screens/ChannelOpsScreen.tsx:200-360` (where the build profile is edited).
Backend: `civiccast/app_platform/build_router.py`, `build_orchestrator.py`, `build_store.py`, `build_models.py`, `router.py:130-215`, `models.py:95-115`;
`civiccast/apps/app-platform-shells/` (`README.md`, `store-readiness.json`, `scripts/build-targets.mjs`).
Who can open it: `Sidebar.tsx:169` `requiredRoles: ['setup_admin', 'publish_operator']`. The screen computes `canQueue` = setup_admin, `canWrite` = setup_admin or publish_operator, `canRead` = canWrite (lines 211-215).
Anyone else who reaches the address sees "Viewing and managing OTT app builds requires the setup admin or publish operator role." (line 50) and no data.
- Read build profile, list/download builds, list/edit store submissions: setup_admin or publish_operator (`build_router.py:55,148,230,270,282`).
- Queue ("Build") an app: setup_admin only (`build_router.py:56,178`); publish_operator sees "Queueing a build requires the setup admin role." (line 313).
- `GET /api/staff/app/config` (feeds the Build profile box) has no role dependency (`router.py:137-143`).
Not reachable while the recovery kit is pending.

## What it is for
CivicCast can package a generic "app shell" (a small web-based viewer app) for several platforms (web, Roku, Apple TV, Fire TV, Android TV, Android phone/tablet, iPhone/iPad) from the station's settings.
This screen builds that package on the station computer, keeps a history of builds with download links, and gives staff a notebook to record the status of each app-store submission done by hand elsewhere.
It does not publish any app to any store (line 355).

## What the user sees (top to bottom)
1. h1 "App Admin" and text: "Build the OTT app shells for each platform and track their store submissions. Apps read the station config at runtime — branding + content update without a rebuild." (lines 265-269)
2. Loading, identity-error or no-access notes (lines 272-285), then an action error box.
3. Section "Build profile" (read-only): App name, Tier, Store-ready yes/no, icon URL.
4. Section "New build": "Platform target", "Tier", button "Queue build".
5. Section "Build history": newest first; each row `{platform} · {tier}`, then `{time} · sha {first 12 chars} · {who}` and a "Download" button.
6. Section "Store submissions": line "CivicCast makes no calls to app stores — record submission status here after submitting offline." then one editable row per tracked platform.
The page re-reads builds, submissions and config every 30 seconds (line 31).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Platform target (drop-down, first option "Select a platform…") | Choose web pwa, roku, tvos, fire tv, android tv, android mobile, ios ipados | local | setup_admin | Displayed with underscores replaced by spaces, lowercase (`app-admin-format.ts:35-37`) |
| Tier (first option "Select a tier…") | unbranded / branded | local; sent as `build_tier` | setup_admin | Only labels the record: the build script does not read the tier or the station config (HELP-02) |
| Queue build (shows "Building…" while running) | Opens a confirm dialog, then runs the build | `POST /api/staff/app/builds` body `{app_target, build_tier}` | setup_admin | Disabled until both fields chosen. Dialog title `Queue a {platform} build ({tier} tier)?`, body "The build runs on this machine using the station app build toolchain and appears in Build history when it finishes.", buttons "Queue build" / Cancel (lines 113-125). Runs inside the web request (not a background queue): `orchestrate_build` is called directly (`build_router.py:190`); it runs `node scripts/build-targets.mjs` then zips that platform's folder (`build_orchestrator.py:136-168`) |
| Download (build row) | Saves the ZIP | `GET /api/staff/app/builds/{id}/download` via authenticated fetch | setup_admin / publish_operator | File named `{platform}-{record_id}.zip` (line 250). Failure: "Could not download the artifact." Server refuses files outside the managed folder (403) or missing files (404 "Build artifact file is no longer present on disk.") |
| Status (per submission) | draft / pending review / approved / rejected / published / withdrawn | `PATCH /api/staff/app/store-submissions/{platform}` | publish_operator / setup_admin | Read-only text for others (line 158 `disabled`) |
| Version name, Package ID, Published URL | Free-text notes | same PATCH | | Empty values are sent as null (Package ID, Published URL); Version name omitted if empty |
| Save (per submission, "Saving…") | Stores the row and stamps who and when | PATCH; server sets `updated_by`, `updated_at` (`build_router.py:296-302`) | | No confirmation. Many rows share one `saving` flag so all Save buttons show "Saving…" together (line 370) |

## States
- Loading: "Loading…" (identity), build profile "Loading…" (also shown forever if the config request fails because errors are not displayed, lines 292-301).
- Identity error: "Could not verify your access — {detail}." (line 277). Action error box shows API text or "Could not queue the build." / "Could not update the submission." / "Could not download the artifact."
- Build history: error "Could not load builds — {detail}."; empty "No builds yet." (line 328).
- Store submissions: error "Could not load submissions — {detail}."; empty "No submissions tracked yet." (line 364). On a fresh station this is the permanent state: the store starts empty and nothing creates a row (`build_store.py:79-83`; the only writer is the PATCH route and the screen offers no way to add a platform). See HELP-04.
- Build failures (server detail): "App build tooling is not configured in this runtime. Meeting capture and scheduled recording are unaffected; app-shell builds are optional and require the station app build toolchain." (when node is missing or the shell build fails); "That app target is not buildable from App Admin."; "Build failed ({ExceptionType}). Check server logs for details."; 503 "Build artifact produced but could not be recorded (...). Check storage and retry." (`build_router.py:57-61,105-111,215-224`)

## Typical task flows
1. Make a web app package: choose "web pwa" and a tier, Queue build, confirm, wait (the button reads "Building…"), then Download from Build history.
2. Record a store submission: (only possible if a row exists, see HELP-04) change Status, type Version name, Package ID, Published URL, Save.
3. Change what the apps are called or look like: edit on the Channels screen, not here. App name, Tier and "Store ready" are edited in the form at `ChannelOpsScreen.tsx:281-353` (nav "Channels"); this screen only displays them.

## Statuses and words on this screen
Submission statuses (raw values `draft`, `pending_review`, `approved`, `rejected`, `published`, `withdrawn`) shown with underscores removed, lowercase, e.g. "pending review"; summary line is `{status} · v{version} · {packageId}` (`app-admin-format.ts:51-58`). "Store-ready: yes/no" is just a flag someone set; it does not test anything (`models.py:104`). Build proof wording stored with each record: "local artifact, SHA-256 verified" (`build_orchestrator.py:15`). Not routed through `status-language.ts` on purpose (comment lines 28-33).

## Related settings / env / CLI / API
`CIVICCAST_APP_BUILD_STORE_PATH` (JSON store), `CIVICCAST_APP_BUILD_ARTIFACTS_DIR` (default under storage dir `app-build-artifacts`), `node` on PATH plus the built-in `app-platform-shells` folder. Public config URL the apps read at run time: `/api/public/app/config` (`app-platform-shells/README.md:6,59-62`). Channels screen (build profile and channel branding). `store-readiness.json` in the shells folder: advice for "certified integrators" (device proof and store review are separate work).

## Help-text findings
- [HELP-01] lines 265-269 "Build the OTT app shells ... track their store submissions." — "OTT", "app shell", "tier", "build profile" and "store-ready" are never defined. Plain text: "OTT apps are viewing apps for Roku, Apple TV, Fire TV, Android and iPhone/iPad. This screen builds a basic starter package of each; a technical person must still sign it and submit it to the store."
- [HELP-02] lines 88-100 Tier, and `app_platform/build_orchestrator.py:101-128`, `scripts/build-targets.mjs` — the choice "unbranded / branded" only changes the label saved in Build history; the build command is the same and the script contains no reference to tier or station settings (grep of `build-targets.mjs` for tier/branded/config found nothing). The ZIP is a generic shell that fetches branding from `/api/public/app/config` when it runs. So "Tier" does not change what you get. Either explain this or remove the choice. UNVERIFIED whether the shells' own source varies by tier (only the build script was grepped).
- [HELP-03] lines 113-117 dialog body "appears in Build history when it finishes" — the page also freezes on "Building…" while the single web request runs (no progress, no time estimate; a long build can hit browser or proxy time-outs; UNVERIFIED duration). Say "This can take a few minutes. Keep this page open."
- [HELP-04] lines 354-365 — "No submissions tracked yet." has no way to start tracking one; the screen has no "Add platform" control and the server never creates default rows. As shipped, the section is a dead end for a clerk. Add one blank row per platform or an "Add" button; until then the manual must say the section is only usable through the API.
- [HELP-05] lines 289-301 comment "edit via Channel & Settings" is not shown to users, and the visible "Build profile" box has no pointer to where App name, Tier and Store ready are changed (Channels screen). Add "Change these on the Channels screen."
- [HELP-06] lines 265-269 "branding + content update without a rebuild" — supported by the shells reading `/api/public/app/config` at run time (UNVERIFIED in a running app) but a first-time reader will take it to mean the stores accept it without review. Add that store review is separate.
- [HELP-07] "Store-ready: yes/no" (line 296) — implies the app is ready for a store. It is a flag from the Channels form; the build is a generic ZIP and `store-readiness.json` says device testing and store review are external work. Label "Marked store-ready (manual flag)".
- [HELP-08] lines 355 and 188-190 — good note ("CivicCast makes no calls to app stores"), but the Status drop-down invites changing to "published" with no check that a Published URL exists. Fine to document; not a blocker.
- [HELP-09] lines 334-335 — build rows show `sha {12 characters}` and the operator id; no explanation of what the SHA is for (checking the file was not altered). Add a tooltip: "Fingerprint of the ZIP. Compare it if you pass the file to someone else."
- [HELP-10] line 83 and 95 — platform names appear as lowercase "web pwa", "tvos", "ios ipados", "fire tv". Use "Web app (PWA)", "Apple TV (tvOS)", "iPhone/iPad (iOS)", "Fire TV" for people.

## Screenshot plan
1. Setup admin with no builds: Build profile filled, New build form empty ("Select a platform…", "Select a tier…"), "No builds yet.", "No submissions tracked yet."
2. Confirm dialog for a web pwa unbranded build.
3. Build history with one row after a successful build; Download button.
4. A failed build showing the "App build tooling is not configured ..." box (on a machine without node).
5. A store submission row (needs one created through the API first) in each of publish_operator (editable) and meeting_operator (not shown) views.
6. Publish operator view: "Queueing a build requires the setup admin role."
Setup: `node` installed for the success case; no `node` for the failure case; a PATCH to `/api/staff/app/store-submissions/roku` to create a row.

## UNVERIFIED / open questions
- UNVERIFIED: how long a build takes and whether `node` is bundled with the installed product (`build_native_app_payload.py` mentions node tooling; install layout not checked).
- UNVERIFIED: what is inside each platform ZIP and whether any platform's ZIP is installable on a device (only the build script path was read).
- UNVERIFIED: whether the shells honour tier in their own source (see HELP-02).
- UNVERIFIED: that `app_name`, icon and branding really are applied at run time in a running app (README states it; no app was run).
- UNVERIFIED: what happens in the browser if the build request exceeds a proxy time limit.
