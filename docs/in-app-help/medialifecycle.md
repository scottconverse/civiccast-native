# Media Lifecycle Settings (nav id: medialifecycle)

Console group: Review Records. Spec for the in-app help of watch folders, retention rules and the storage budget. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`.

## Where the help text lives now
All in `screens/MediaLifecycleSettingsScreen.tsx` unless stated.
- Page label, heading and intro: 596-602.
- Watch folders card: subtitle 243; placeholder 254; Browse 266; Add 274; empty 293; Enabled/Disabled 307; remove dialog 331-332; row status words 109-137; Scan now 146; toasts 180-227.
- Retention automation card: subtitle 412; field labels 422, 432, 443; placeholder 435; Add rule 464; empty 472; remove dialog 514-515; Apply rules now 507; toasts 378-402.
- Storage budget card: subtitle 542; no-budget text 557; empty table 563; table head 569.
- Folder picker window: `components/media-lifecycle/FolderBrowser.tsx` (not re-read; see inventory).
- Role limits: `civiccast/schedule/media_lifecycle_router.py:83-96,626-680,753-757,845-911`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Watch folders, retention automation, and storage budget. Ingest-time readiness badges live on the Assets screen; missing scheduled media is under Missing Media." | Page intro | :600-601 |
| "Auto-ingest files dropped into a local disk, USB, or NAS/SMB directory. Hands-off after setup." | Watch folders subtitle | :243 |
| "/mnt/nas/incoming or D:\\incoming" (JSX attribute; the doubled backslash is probably shown literally, unverified on screen) | Path box placeholder | :254 |
| "Browse…" / "Add watch folder" | Buttons | :266 / :274 |
| "No watch folders configured yet. Every asset comes in via manual upload until you add one." | Empty | :293 |
| "Enabled" / "Disabled" | Folder row (no control to change it) | :307 |
| "Not scanned yet" / "OK" / "Degraded"; "No automatic check has run yet — the next one runs within {n}s, or use Scan now."; "Last poll: …"; "Last ingest: …" | Folder status | :112,121-127 |
| "Remove the watch folder {path}?" / "New files dropped there stop being ingested automatically. Assets already ingested from this folder are not affected." / "Remove folder" | Dialog | :331-333 |
| "Assign a retention policy automatically by meeting series, e.g. 'City Council' → meeting retention. Never auto-deletes -- expired assets are flagged for records-clerk review." | Retention subtitle | :412 |
| "Rule name" / "Meeting body (exact match)" / "Retention policy" / "Add rule" | Form | :422,432,443,464 |
| "No automation rules yet. Retention policy is set per-asset in the asset editor until you add one." | Empty | :472 |
| "The rule stops applying on future runs. Assets keep the retention policy they already have." | Remove-rule dialog | :515 |
| "Apply rules now"; toast "Applied rules: {n} asset(s) updated." | Button, toast | :507, :400 |
| "Media library disk usage by retention tier." | Storage subtitle | :542 |
| "No budget configured (set CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES)" | Storage | :557 |
| "No assets have a recorded file size yet." | Storage empty | :563 |
| Policy words `default`, `permanent`, `meeting`, `short` shown raw | Rule form, rule rows, storage table | :29,485,577 |

## What the screen really does
Three cards. Watch folders: a folder on the station's own computer is checked about every few seconds; a new video that has stopped growing is copied into the library and appears in Assets as Validated (the original stays in place). Retention rules: each rule sets the retention policy label on every video whose Meeting body matches the rule's text exactly; nothing applies a rule except the Apply rules now button, and a rule with a blank meeting body matches nothing. Storage budget: a read-only total of disk use with a table by retention policy. All buttons are shown to every role; each needs a different role and a wrong-role click returns the server's error text. The nav shows the page to setup_admin, publish_operator and records_clerk, but the cards load for different roles (see Notes).

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "Assign a retention policy automatically" / "Hands-off" | Rules run only when someone clicks Apply rules now; no worker calls the apply routine (`media_lifecycle_router.py:914`) | blocks work |
| HELP-02 | Blank "Meeting body" listed as "any → {policy}" | The apply step skips rules with no meeting body (`media_lifecycle_store.py:331`); it matches nothing | blocks work |
| HELP-03 | Policy shown as `meeting`, `short` | Asset editor says Default, Permanent, Meeting (long), Short; applying a rule changes only the policy label, and whether the deadline follows is UNVERIFIED | misleading |
| HELP-04 | Placeholder and path box never say "on the station computer" | Browse lists local drives only, network paths must be typed, Browse and Scan now need setup_admin (`media_lifecycle_router.py:676-680,753-757`) | misleading |
| HELP-05 | "Hands-off after setup" | A file must be unchanged for two checks (10 s settle in the add call, `:176`); originals stay in place; format list is the same gate as Upload (UNVERIFIED) | misleading |
| HELP-06 | "set CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES" | An environment variable name with no way for a clerk to set it | misleading |
| HELP-07 | "Enabled"/"Disabled" | No control to change it; Scan now is disabled silently for a disabled folder | cosmetic |
| HELP-08 | Page visible to three roles | Each button needs other roles; nothing names them | misleading |
| HELP-09 | "Ingest-time readiness badges" | Assets calls them Status; no toast after Remove folder | cosmetic |
| HELP-10 | No Manual link | n/a | cosmetic |
| NEW-1 | "Never auto-deletes -- expired assets are flagged for records-clerk review" | The console has no screen that lists the flagged items (API only; manual ch.14) | misleading |

## Proposed text
What this is for (new, under heading): "Three station-wide settings: folders CivicCast watches for new videos, rules that label recordings with a retention policy, and how much disk the library uses."
Who can use it (new): "Adding or removing a watch folder: publish operator or setup administrator. Browse and Scan now: setup administrator. Retention rules and Apply rules now: records clerk or setup administrator. If a button gives a role message, ask your station administrator."
Intro: "Watch folders, retention rules and disk use. The Status column of the Assets list shows whether each video is ready. Meetings with a missing video are listed under Missing Media."
Watch folders subtitle: "CivicCast checks a folder on this station's computer (a local disk, a USB drive, or a network share) and copies new videos into the library. The original file is left where it is. A new file is imported after it has stopped growing, usually within about 20 seconds. Only the same video types as Upload are imported: MP4, MOV, MKV, WebM, AVI, MPEG-TS."
Placeholder: "Folder on this computer, for example D:\Incoming or \\nas\Videos". Add under the box: "Browse shows only this computer's own drives. Type a network path by hand."
Folder row, Disabled: "Disabled: CivicCast is not checking this folder. In beta.10 the screen cannot turn it back on; remove it and add it again."
Remove-folder dialog: keep, add "CivicCast never deletes files in the folder."
Retention subtitle: "A rule sets the retention policy of every recording whose Meeting body matches the rule's text exactly (same spelling). Rules do nothing until you click Apply rules now; CivicCast does not run them by itself. Applying a rule replaces a policy someone chose by hand on a recording. CivicCast never deletes a recording on its own; when its retention date passes it is marked for records review (in beta.10 there is no screen to see that list; ask your IT person)."
After fix (scheduled apply): "Rules are applied every night and when you click Apply rules now."
Meeting body label: "Meeting body (exact match, required)". Policy words: Default, Permanent, Meeting (long), Short, matching the asset editor.
Apply rules now (confirm text, new): "Apply every rule to every recording now? Policies chosen by hand on matching recordings will be replaced."
Storage no-budget: "No size limit has been set. Ask your IT person; in beta.10 it cannot be set from this screen." After fix: "Set a limit: {field}."
Remove-rule dialog: keep.

## Notes for the coder
- Edit `MediaLifecycleSettingsScreen.tsx` (and `FolderBrowser.tsx` for picker text).
- Tests that pin strings (verified by grep): `screens/MediaLifecycleSettingsScreen.test.tsx` ("No budget configured", "Request failed"); e2e `e2e/media-lifecycle-watch-folders.spec.ts` (a fresh folder's "Last poll" text). "Hands-off" and "Assign a retention" are not pinned.
- Code fixes, not text fixes: schedule or hook the apply routine, or disable rules whose body is blank (HELP-01/02); enable/disable a folder and edit a rule; a budget field; per-button role gating (HELP-08); a records-review screen (NEW-1). Role mismatch: a setup_admin-only token cannot load the watch-folder, rules or budget cards; a records_clerk-only token sees rules but not folders or budget (`media_lifecycle_router.py:84,626-630,845-849,922-926`).
- UNVERIFIED in the inventory: whether the deadline follows a rule change; the exact placeholder rendering; whether the app starts the watch-folder worker by default.
