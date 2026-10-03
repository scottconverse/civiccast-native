# Media Lifecycle Settings  (nav id: medialifecycle, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`.
Source files: `OP/screens/MediaLifecycleSettingsScreen.tsx`, `OP/components/media-lifecycle/FolderBrowser.tsx`; route `OP/App.tsx:282` (`/media-lifecycle`); nav `OP/components/shell/Sidebar.tsx:149-152`. Backend: `civiccast/schedule/media_lifecycle_router.py`, `civiccast/schedule/media_lifecycle_store.py`, `civiccast/schedule/watch_folder_worker.py`, `civiccast/schedule/media_lifecycle_models.py`.

Who can open it: nav entry shown to `setup_admin`, `publish_operator`, `records_clerk` (`Sidebar.tsx:151`). The three sections each call the API separately and the API's role sets do **not** match the nav (table). The screen has no role check or per-button gating; a wrong role sees buttons that fail. With a generic `operator`/`admin` token (all five roles, `civiccast/auth/roles.py:23-24`) everything works.

| API call (section) | Roles that pass | `media_lifecycle_router.py` |
|---|---|---|
| list watch folders; storage budget; (also readiness, missing media) | meeting_operator, publish_operator, support_admin | `:84,626-630,922-926` |
| add / remove watch folder | publish_operator, setup_admin | `:83,638-643,821-825` |
| "Scan now", "Browse…" (folder picker) | setup_admin only | `:96,676-680,753-757` |
| list retention rules | meeting_operator, publish_operator, support_admin, records_clerk | `:845-849` |
| add / remove rule, "Apply rules now" | records_clerk, setup_admin | `:857-862,890-894,908-911` |
Consequences: a `setup_admin`-only token cannot load the watch-folder list, the retention list or the storage budget (each shows a red inline box with "This action requires one of these CivicCast roles: …"); a `records_clerk`-only token sees the retention rules but not watch folders or storage; a `publish_operator`-only token can add folders but gets a role error on "Scan now", "Browse…", and on every retention button.

## What it is for
Three station-wide settings on one page: (1) watch folders, directories on the station computer (local disk, USB, or a network share) that CivicCast checks automatically and imports video files from; (2) retention rules that set an asset's retention policy by its "meeting body" name; (3) a read-only view of how much disk the media library uses. Each section loads and fails on its own (`MediaLifecycleSettingsScreen.tsx:1-4`).

## What the user sees
1. Label "Media Lifecycle", heading "Media Lifecycle Settings", text "Watch folders, retention automation, and storage budget. Ingest-time readiness badges live on the Assets screen; missing scheduled media is under Missing Media." (`:595-602`).
2. Card **Watch folders** — "Auto-ingest files dropped into a local disk, USB, or NAS/SMB directory. Hands-off after setup." (`:243`). A path box (placeholder "/mnt/nas/incoming or D:\\incoming", aria-label "Watch folder path"), buttons "Browse…" and "Add watch folder"; then one row per folder.
3. Card **Retention automation** — "Assign a retention policy automatically by meeting series, e.g. 'City Council' → meeting retention. Never auto-deletes -- expired assets are flagged for records-clerk review." (`:412`). Form: "Rule name", "Meeting body (exact match)" (placeholder "City Council"), "Retention policy" (list: default, permanent, meeting, short), "Add rule"; then rule rows and "Apply rules now".
4. Card **Storage budget** — "Media library disk usage by retention tier." (`:542`). Big number (total used), "of {budget} budget ({n}%)", and a table Retention policy / Assets / Bytes used.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Watch folder path (text) | Path **on the station computer** | - | - | Page never says "station computer" |
| Browse… | Opens a "Choose a folder" window listing drives and sub-folders of the station's local disks; "Up", "Cancel", select button | GET `/api/staff/media-lifecycle/browse-folders?path=` | setup_admin | Local drives only (network paths must be typed); Windows system folders and whole drives are refused (`media_lifecycle_router.py:124-147,253-295`); empty: "No subfolders here."; error "Can't open this folder…" |
| Add watch folder | Saves the folder with fixed settings: enabled, wait 10 s for a file to stop growing (`MediaLifecycleSettingsScreen.tsx:176`); server defaults poll every 5 s, leave files in place ("leave_with_ledger") (`media_lifecycle_models.py:688-693`) | POST `/api/staff/media-lifecycle/watch-folder-configs` | publish_operator, setup_admin | Folder must exist and be readable; 422 texts: "That folder does not exist or CivicCast cannot read it. Check the path is correct, the drive/share is connected, and the account running CivicCast has read access to it." ; "An entire drive (e.g. C:\) cannot be a watch folder. Choose a specific subfolder."; "That path is not allowed. CivicCast will not browse or watch Windows system directories, an entire drive, or a raw device-namespace path."; admin shares like `\\host\C$` refused (`:133-147,262-293`). Toasts "Watch folder added." / "Could not add watch folder." + detail |
| Scan now (per folder) | Checks that folder immediately instead of waiting; shows "Scanning…" | POST `…/watch-folder-configs/{id}/scan-now` (`:676`) | setup_admin | Disabled when the folder is Disabled. Toasts: "Scanned {path}: {n} file(s) ingested." / "Scanned {path}: no files found." / "Scanned {path}: {n} file(s) seen, nothing new to ingest." / "Could not scan {path}." (`:208-229`). 409 if a scan is already running; 503 "The watch-folder daemon is not running in this deployment." |
| Remove (folder) | Opens dialog `Remove the watch folder {path}?` — "New files dropped there stop being ingested automatically. Assets already ingested from this folder are not affected." Confirm "Remove folder" | DELETE watch-folder-config | publish_operator, setup_admin | No success toast; files in the folder are never deleted by CivicCast (`watch_folder_worker.py:33-37`) |
| Add rule | Creates a rule (priority fixed at 0, enabled) | POST `…/retention-policies` | records_clerk, setup_admin | Toast "Retention rule added." / "Could not add retention rule." |
| Remove (rule) | Dialog `Remove the retention rule "{name}"?` — "The rule stops applying on future runs. Assets keep the retention policy they already have." Confirm "Remove rule" | DELETE | records_clerk, setup_admin | - |
| Apply rules now | Runs every enabled rule over every asset once; toast "Applied rules: {n} asset(s) updated." | POST `…/retention-policies/apply` | records_clerk, setup_admin | Shown only when at least one rule exists. Writes an audit entry per change (`media_lifecycle_store.py:309-347`). **This button is the only caller of the apply routine** (`grep apply_retention_policies`) |
There is no control to enable/disable a folder (the row only prints "Enabled"/"Disabled"), edit a folder's check interval, or edit a rule.

## States
- Each card: grey pulsing bar while loading; red inline box (`role=alert`) on error with the server text or "Request failed: {message}" (`:75-77`).
- Watch folders empty: "No watch folders configured yet. Every asset comes in via manual upload until you add one." (`:293`). Rules empty: "No automation rules yet. Retention policy is set per-asset in the asset editor until you add one." (`:472`). Storage empty table: "No assets have a recorded file size yet." (`:563`).
- Folder row status (right side): **Not scanned yet** + "No automatic check has run yet — the next one runs within {n}s, or use Scan now." (`:112,121-122`); **OK** + "Last poll: {n}s/m/h/d ago" + "Last ingest: …" ("never" when empty, `:31-42,126-127`); **Degraded** (red, announced) + the reason text, e.g. folder unplugged (`:109,130-137`).
- Storage budget missing: "No budget configured (set CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES)" (`:557`).

## Typical task flows
1. Auto-import from a folder: (setup admin) Browse… -> pick folder -> Add watch folder -> drop a video in it -> wait about 10-20 s (file must be unchanged on two polls) -> asset appears in Assets as Validated; title = file name without extension (`watch_folder_worker.py:845`), asset id made from the file name. Use Scan now to test immediately.
2. Fix a "Degraded" folder: read the reason -> reconnect the drive/share -> Scan now.
3. Retention rule: type a name, the exact meeting body name used in asset editors, pick policy -> Add rule -> Apply rules now. (Nothing applies by itself.)
4. Watch disk use: read the total and the by-policy table.

## Statuses and words on this screen
(`status-language.ts` not used.) Watch-folder health: `ok` shown as "OK", `degraded` as "Degraded", `unknown` as "Not scanned yet" (`:109-112`). Retention policy words are the raw codes `default`, `permanent`, `meeting`, `short` in the list, the rule rows ("Council → meeting") and the storage table (`:29,485,577`); the asset editor shows them as Default, Permanent, Meeting (long), Short (`AssetDetailScreen.tsx:40-61`). Rule rows read "{name} — {meeting body or 'any'} → {policy}".

## Related settings / env / CLI / API
`CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES` (`media_lifecycle_router.py:929`); `CIVICCAST_UPLOAD_DIR` (watch-folder copies go there; the worker refuses to run if unset, `watch_folder_worker.py:354,385`); `CIVICCAST_WATCH_FOLDER_WORKER`, `CIVICCAST_WATCH_FOLDER_POLL_SECONDS`, `CIVICCAST_WATCH_FOLDER_MAX_CONCURRENT_FOLDERS`; `CIVICCAST_MEDIA_LIFECYCLE_WORKER`; API prefix `/api/staff/media-lifecycle/` (watch-folder-configs, browse-folders, retention-policies, storage-budget, audit-log). Audit log endpoint exists (`:966`) but the console has no screen for it. Design record: `docs/adr/0024-watch-folder-daemon-processed-file-and-degraded-state.md` (named in `watch_folder_worker.py:38`).

## Help-text findings
- [HELP-01] `MediaLifecycleSettingsScreen.tsx:412` card text "Assign a retention policy automatically…" and the 'Hands-off' wording imply rules run on their own. The only code that applies rules is the "Apply rules now" button (`media_lifecycle_router.py:914`; no worker calls it). Fix: "Rules take effect when you press Apply rules now."
- [HELP-02] `:485` / `:432` a rule with a blank "Meeting body (exact match)" is listed as "any → {policy}", but the apply routine skips rules without a meeting body (`media_lifecycle_store.py:331`), so it matches nothing. Fix: require the field, or say "A rule only applies to assets whose Meeting body matches this text exactly."
- [HELP-03] `:412` and `:452` "Retention policy" shows `default/permanent/meeting/short` raw; the asset editor shows Default / Permanent / "Meeting (long)" / Short with explanations. Fix: reuse the editor words and one-line meanings; also say that applying a rule changes only the policy label, not the deadline (UNVERIFIED how the deadline follows, see below).
- [HELP-04] `:254` placeholder reads `/mnt/nas/incoming or D:\\incoming`; as a JSX attribute the two backslashes are literal, so the Windows example is shown with a doubled backslash (UNVERIFIED on screen). The text also never says the path is on the station computer, that network shares must be typed (Browse is local drives only), or that only setup admins can Browse and Scan now. Fix: "Folder on this station's computer, e.g. D:\Incoming or \\nas\Videos".
- [HELP-05] `:243` "Hands-off after setup." omits: files are copied (the original stays), a file must be unchanged for two checks (10 s settle, 5 s poll), only supported video formats are imported (same list as Upload), and an imported file never overwrites an existing asset unless the same path changes later (it replaces that asset's source).
- [HELP-06] `:557` "No budget configured (set CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES)" — an environment variable name with no way for a non-technical user to set it. Fix: "No limit has been set. Ask your station administrator." and add a UI field or Manual link.
- [HELP-07] `:307,312` rows print "Enabled"/"Disabled" with no way to change it and no explanation of why a folder would be disabled; "Scan now" is disabled silently for them.
- [HELP-08] `:101-107` the nav shows this page to roles that cannot use parts of it (see table); nothing on the page names the role needed for each button. Add per-button hints like the Assets Package button.
- [HELP-09] `:600-601` points to "Ingest-time readiness badges" on Assets, but the Assets table calls them "Status"; Remove-folder success has no toast so it is unclear that anything happened.
- [HELP-10] No link to the Manual on this page.

## Screenshot plan
1. Fresh state: all three cards empty.
2. After adding a folder: row in "Not scanned yet", then "OK" with Last poll/Last ingest, then "Degraded" (unplug or rename the folder, wait one poll).
3. "Choose a folder" window (drives list, then inside a folder). Setup: setup_admin token.
4. Add-folder error (nonexistent path) and the Remove dialog.
5. A rule list with "Apply rules now" and the success toast; the retention table.
6. Storage card with and without a budget; red error box when signed in as a setup_admin-only token.

## UNVERIFIED / open questions
- UNVERIFIED: whether applying a rule changes the asset's expiry date (it sets `retention_policy` only, `media_lifecycle_store.py:331-336`; deadline logic `schedule/store.py:315-335` and `retention_terms.py` not read).
- UNVERIFIED: exact placeholder rendering (needs the screen).
- UNVERIFIED: which file types the watch-folder daemon accepts (assumed the same `validate_ingest` gate as Upload; `watch_folder_worker.py` imports `validate_ingest` but the file-pattern/extension filter was not read).
- UNVERIFIED: whether `app.py` starts the watch-folder worker by default (settings default mode is "inline", `watch_folder_worker.py:230`; the wiring in `civiccast/app.py` was not read).
