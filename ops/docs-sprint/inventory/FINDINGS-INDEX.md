# Help-text and behavior findings index (all screens)

473 findings across 63 inventories. Each finding is verbatim from its inventory file in `screens/<name>.md`, where the full evidence (file:line) lives. IDs are unique only within a file. These feed (a) the manual, which must not describe broken behavior as working, and (b) the in-app-help handoff and bug list for the coder.

## Counts per inventory

| Inventory | Findings | UNVERIFIED marks | Lines |
| --- | ---: | ---: | ---: |
| _shell-navigation-and-roles | 0 | 8 | 130 |
| _shell-shared-components | 0 | 5 | 78 |
| _shell-signin-and-session | 0 | 6 | 80 |
| activitypub | 9 | 7 | 81 |
| agendas | 12 | 8 | 84 |
| ai-models | 9 | 6 | 66 |
| alerts | 11 | 6 | 82 |
| analytics | 9 | 8 | 79 |
| appadmin | 10 | 9 | 82 |
| assets | 14 | 7 | 105 |
| autoschedule | 10 | 8 | 78 |
| cg | 8 | 8 | 78 |
| cgdesigner | 9 | 11 | 78 |
| channels | 12 | 9 | 88 |
| commissioning | 11 | 5 | 81 |
| contribute | 10 | 6 | 75 |
| controlroom | 8 | 5 | 82 |
| controlroomsetup | 9 | 7 | 83 |
| custom-fields | 8 | 7 | 74 |
| eas | 9 | 7 | 76 |
| epg | 10 | 6 | 83 |
| facility | 7 | 4 | 70 |
| guide | 10 | 6 | 81 |
| health | 12 | 9 | 112 |
| help | 13 | 7 | 89 |
| installer-component-catalog | 4 | 3 | 51 |
| installer-failures-and-logs | 4 | 8 | 71 |
| installer-gui-checking-computer | 5 | 4 | 61 |
| installer-gui-download-plan | 6 | 4 | 57 |
| installer-gui-downloading | 6 | 4 | 84 |
| installer-gui-setup-wizard | 7 | 3 | 69 |
| installer-install-layout | 3 | 10 | 92 |
| installer-nsis-activation-selftest | 5 | 3 | 62 |
| installer-nsis-packs-and-verify | 5 | 2 | 57 |
| installer-nsis-service-finish | 5 | 5 | 52 |
| installer-nsis-setup-wizard | 4 | 6 | 49 |
| installer-nsis-upgrade-database | 5 | 4 | 57 |
| installer-uninstall | 5 | 5 | 50 |
| live | 12 | 7 | 89 |
| medialifecycle | 10 | 7 | 80 |
| missingmedia | 6 | 4 | 57 |
| paywall | 10 | 17 | 93 |
| playback | 9 | 7 | 90 |
| public-agenda | 3 | 2 | 44 |
| public-contribute | 5 | 4 | 57 |
| public-home | 5 | 4 | 72 |
| public-paywall | 5 | 4 | 50 |
| public-player-captions | 5 | 5 | 51 |
| public-recordings | 5 | 2 | 58 |
| public-schedule | 4 | 2 | 44 |
| public-shell | 5 | 5 | 80 |
| public-subscribe | 4 | 5 | 50 |
| public-watch | 3 | 3 | 51 |
| publish | 12 | 7 | 111 |
| recording | 10 | 12 | 98 |
| remotecontribution | 8 | 9 | 79 |
| reports | 10 | 5 | 77 |
| review | 9 | 6 | 75 |
| schedule | 9 | 8 | 84 |
| setup | 11 | 9 | 109 |
| station-profile | 10 | 6 | 76 |
| summary | 9 | 5 | 109 |
| underwriting | 10 | 9 | 92 |

## All findings


### activitypub

- [HELP-01] The screen never tells the operator how federation actually gets turned on. After `Generate station key` the only guidance is the server sentence about "whoever manages this station's CivicCast environment file ... then restart CivicCast". A clerk does not know what an environment file or restart is, and the manual says "no command line is required" and "See the station's ActivityPub screen for the current on/off switch" (`docsite/manual.json`, `provider-federation`) - there is no on/off switch on this screen. Fix: say plainly "Federation is turned on by your IT person editing settings and restarting the CivicCast service" and name this the last step; fix the manual.
- [HELP-02] Manual names the screen "ActivityPub" ("open ActivityPub in the console"); the nav entry is `Federation`. Fix: say "Federation".
- [HELP-03] ActivityPubScreen.tsx:650 error text blames "the API logs" for every moderation failure, including a role/permission failure (server allows only `publish_operator` and `support_admin`, `router.py:55`). The Approve/Reject/Block buttons are shown to every role. Fix: show the server message ("This action requires one of these CivicCast roles: ...") and name the role in plain words.
- [HELP-04] :634 "cannot re-follow until unblocked" - there is no unblock action in the console; the `Blocked` tab lists entries with no buttons (`:346` hides Block, nothing replaces it). Fix: say how to unblock or remove the sentence.
- [HELP-05] :164 and :186 "Generating again reuses it" is accurate, but nothing says that the key file path and the `CIVICCAST_ACTIVITYPUB_*` names are IT items; `Copy settings` copies raw `KEY=value` lines. Add "send this to your IT person".
- [HELP-06] Jargon on the on-screen cards: `station actor`, `inbox`, `Signed fetch`, `Domain policy Allow 0 / block 0`, `Outbox`, `dead letter`, `HTTP <code>`, `Key <id>`. The off-state explanation is good plain language; the on-state is not. Fix: one-line meanings under each tile.
- [HELP-07] `Mode` tile shows `approval-only` etc. raw; the three modes (open, limited, approval-only) are never explained on screen.
- [HELP-08] "Default-safe" (:147) is an engineer's phrase; a clerk may not know it means "off and nothing is exposed".
- [HELP-09] No success feedback after `Approve` (no toast); the tile counts change after a refetch.

### agendas

- [HELP-01] `:209` "Meeting asset ID" is a free-text box: the user must already know the recording's internal ID (shown in Assets under the title) and type it in lowercase; the server does not check it exists (UNVERIFIED) and allows only one agenda per meeting. Fix: a drop-down of recordings by title, and say "one agenda per meeting".
- [HELP-02] `:196,209` "Agenda ID (slug)" / "Item ID (slug)" — jargon; a wrong character gives a raw JSON 422 (e.g. uppercase). Fix: generate IDs automatically, or say "lowercase letters, numbers and dashes only".
- [HELP-03] `:501` Order starts at 0 for every new item; a second item fails with 409 "Another agenda item already occupies (agenda_id='…', order=0)". Fix: default to the next free number and explain "Order = position in the list".
- [HELP-04] `service.py:136-142` shown to the user on a failed Publish: "…(DC-1)…" — an internal rule code. Fix: "Add at least one item before publishing."
- [HELP-05] `:345-366` Delete/Confirm delete arms with no Cancel and no way to un-arm; a delete of an agenda removes all items with no undo. The item delete has the same pattern.
- [HELP-06] `:1202-1206` does not say that edits to items of an already-published agenda go live immediately (only PDF and external imports reopen it as a draft, `router.py:493-501`; typed edits do not). Fix: "Changes to a published agenda are visible to residents as soon as you save."
- [HELP-07] `:822-1099` the whole "Import from an external agenda system" block is shown on every station but is switched off by default; the only message is the server's "Set CIVICCAST_AGENDA_SOURCE…" which a clerk cannot act on. Fix: hide the block or show "Not turned on for this station — ask your administrator" before the first click. Also "Tenant / site code" is unexplained (example `longmont`).
- [HELP-08] `:549-560` "Video timecode (seconds…)" requires the clerk to convert minutes to seconds by hand; the tip tells them to find the moment on the public portal and paste seconds. Fix: accept h:mm:ss.
- [HELP-09] `:1581-1584` PDF import help is long and technical ("numbered items, ALL-CAPS section headings, and call-time markers are recognized"); `:1553-1555` placeholder shows the line format but not the Number-splitting rule.
- [HELP-10] `:1191` the page always creates agendas for station `civiccast-station` while the list is filtered by `CIVICCAST_STATION_ID` (`agenda/router.py:132`); if that variable is set differently the new agenda would not appear in the list (UNVERIFIED).
- [HELP-11] The agenda never says where residents see it (the recording's public watch page) or links to it when `VITE_PUBLIC_PORTAL_BASE_URL` is unset; no Manual link.
- [HELP-12] Header comment in `:25-27` and `:5` mention "PDF returns 415" — stale developer text, not shown to users (for the coder, not the manual).

### ai-models

- [HELP-01] `ai_models\catalog.py:145-148` (shown in the Translation card under "About") — "NOT YET CONNECTED (audit finding, 2026-08-29): no caller supplies a translation target, so this model is never actually invoked and no translated caption track is published. Selecting it has no visible effect yet; see AiModelsScreen's translation banner." — directly contradicts the grey note on the same card, which says it translates recordings (the screen comment at AiModelsScreen.tsx:197-203 says it is now connected, `app.py:1538` builds a translator from this selection). The stale text is rendered for the default model — fix: replace the tier note with a plain description (e.g. "On-device Spanish translation, 4B model") and delete the audit text.
- [HELP-02] AiModelsScreen.tsx:220, 275 — "Current model" shows the internal slug (e.g. `gemma4-e4b-ollama`, `whisper-medium-faster`) and the dropdown options read "<slug> — Local · Free (local) · needs 8 GB" — slugs mean nothing to a clerk and there is no plain name or "recommended" mark — fix: show a friendly name ("Gemma 4 small, runs on this computer") and mark the default.
- [HELP-03] AiModelsScreen.tsx:248-250 and ai-models-format.ts — "Frontier" / "Cloud" bands and "per-token" cost are jargon; no sentence says what a token is or gives a per-meeting dollar example; cost is only ~$/1M tokens — fix: add an "about $X per hour of meeting" example or hide.
- [HELP-04] AiModelsScreen.tsx:342-381 — for a hosted choice the key box says "Provider API key required." but the page never says where to get a key or which provider (Ollama Cloud vs OpenRouter) the tier uses; the staged tier's band label is the only clue — fix: name the provider and link to its key page.
- [HELP-05] AiModelsScreen.tsx:268-275 — a local change takes effect the moment the dropdown changes, with no confirmation and no note on when the new model starts being used (next meeting? next job?). The code does not say; UNVERIFIED how running jobs behave — fix: state "Applies to new captions/summaries from now on" once verified.
- [HELP-06] Captions card gives no hint about the difference between live captions and recording captions; the Station Profile page has a separate "Show live captions on air" switch (default OFF) — a clerk will assume choosing a caption model turns captions on. The page never mentions that switch — fix: add a link/sentence.
- [HELP-07] The "(exceeds this box)" suffix disables options silently; the user cannot see this computer's RAM on this page — fix: show "This computer has N GB".
- [HELP-08] AuthRequiredState text mentions an "installer handoff" and "operator-console link" that no longer exist (see station-profile inventory HELP-10).
- [HELP-09] `ai_models\catalog.py:90-96` — the "About" line for the 12B summary model (shown when it is the current model) says "...QAT... measured CPU-only on the 32GB reference station it took 366s... (memory allocation failure; a crashed llama-server process)" — engineering notes, not operator guidance — fix: "Needs a graphics card. On a computer without one it is very slow and may fail; use the smaller model."

### alerts

- [HELP-01] AlertsScreen.tsx:207-296, :690-694 - the screen says "choose where alerts are sent", but a new install seeds every rule with an empty destination list (`evaluator.py:156-160`), the rule editor never sends `channel_ids` (the API supports it, `router.py:232`), and creating a destination does not attach it to a rule (`router.py:374-389`). With no destination wired, the server only writes a "suppressed" delivery row (`evaluator.py:430-445`) that no screen shows. Result: an operator can follow the page exactly and never receive an alert. This is the most serious finding on this screen. Fix: either wire destinations to rules in the UI (and say so), or state plainly on screen that rules need destinations attached by IT.
- [HELP-02] :31-36 and :765 say `setup admin or support admin` can manage rules/destinations, but the server allows changes only for `setup_admin` (`router.py:284,378,403,430`). A support admin sees the editors, edits, and gets a 403 on `Save`. Fix: reads for both, edits for setup admin only, and say so.
- [HELP-03] :31-36 "Active alerts remain visible to you above." - false for `records_clerk` and `publish_operator` (they are not allowed to read events, `router.py:453`) although the nav shows them the screen. Fix: hide the nav entry for them or show a clear access note.
- [HELP-04] :184 and :777 "watch box" - undefined jargon. Fix: "the station monitor" or say what is watched (channels, disk, database, service, AI engine).
- [HELP-05] :457-483 `Quiet hours ... (UTC, HH:MM)` - a clerk thinks in local time; nothing says critical alerts ignore quiet hours (server comment: "critical alerts always send; warning/info held", `models.py:166`). Fix: show local-time equivalent and the critical exception.
- [HELP-06] `alerts-format.ts:15-38` lacks labels for nine server conditions (list above) so operators will see raw text such as "asrun outbox degraded" or "caption tier degraded". Also those conditions have no rule card (unseeded, `models.py:80-110`), so they cannot be tuned here.
- [HELP-07] :692-694 "the destination address is shown in full" contradicts the API field name `target_redacted` and the server doc "Reads return target_redacted ... never raw PII" (`models.py:151-155`). UNVERIFIED which is true; check what the list endpoint returns for a saved email.
- [HELP-08] :261 `Re-alert after (minutes)` - no explanation of what 0 means, nor of "dedupe". `Notify on resolve` is not explained. The rule card shows `rule_id` (e.g. `off-air`-style code) as a grey tag.
- [HELP-09] :612-630 Delete is armed by one click and stays armed with no cancel/timeout, unlike every other destructive action (shared `ConfirmDialog`). Fix: use ConfirmDialog.
- [HELP-10] No `Send test alert` button, so there is no way to prove a destination works; the only related text is the self-check item `Alert delivery ready` on Readiness (`SystemHealthScreen.tsx:405`).
- [HELP-11] Eyebrow `Operations` (:773) does not match the sidebar section `System Health`.

### analytics

- [HELP-01] line 219 "Turn it on in Setup to collect Viewer Count and Time Viewed." — no Setup screen has such a switch; it is a server environment setting. Say "Ask the person who installed CivicCast to turn on audience counting (setting CIVICCAST_PUBLIC_ANALYTICS_KEY or CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS)", or add the control.
- [HELP-02] line 588 "Report unavailable." — hides the real reason. A role without access gets a 403; show "Analytics is for Support admins and Publish operators. Ask your station admin for access." (compare Reports/EPG, which do this). Hide the nav item for other roles (nav has no `requiredRoles`).
- [HELP-03] line 432 — the Privacy boundary box prints a machine string, `aggregate-only-no-session-ip-or-viewer-identity`. Replace with: "Counts only. CivicCast stores no names, IP addresses or viewer identifiers."
- [HELP-04] line 509 "Export CSV" — silently exports VOD only when ALL is selected and exports only the rollup table, not what the page shows. Say "Exports the VOD (or Live) rollup table for the chosen range" and handle failures.
- [HELP-05] lines 345-351 — the Board PDF always covers "now minus N days" and ignores the VOD/LIVE filter; the station name on the PDF is fixed as "CivicCast station" (line 351) even if the station has a name. Tell the person "PDF title says 'CivicCast station'" or pass the real station name.
- [HELP-06] line 427 "Podcast downloads" "Aggregate episode count" — Publish says podcasts are "coming in a future release", so this number is expected to be 0; explain or hide until podcasts ship.
- [HELP-07] lines 423-428 — "Live peak" detail "Highest reported sample" and "View hours" "Aggregate playback time" are jargon-adjacent; define "A view = one playback start; a viewer is not identified or de-duplicated" (UNVERIFIED how views are counted, see below).
- [HELP-08] lines 25-30 "Quarter" and "Year" mean 90 and 365 days rolling, not calendar periods; label "90d" / "365d" or say so.
- [HELP-09] lines 530-531 button labels "bar"/"line" are lowercase words with no icon or name; use "Bar chart" / "Line chart".

### appadmin

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

### assets

- [HELP-01] `AssetsScreen.tsx:222` header text never says the list is only the first 50 rows, that newly uploaded unpublished files sort after published ones, or that search covers only those rows — a station with >50 assets can upload a file and not find it. Fix: paginate (use `X-Total-Count`) or add "Showing 50 of N" plus a Next button.
- [HELP-02] `OP/types/asset.ts:55` / `assetStatus.ts:84` — State says "Analyzing" while Status for the same row says "Validating"; "Recorded" (amber) beside "Not servable yet". Two vocabularies for one thing. Fix: show one column, or rename State "Analyzing" to "Validating".
- [HELP-03] `types/asset.ts:58` tooltip "ffprobe is running on the uploaded file." — jargon, and `pending_ingest` is not produced by uploads. Fix: "CivicCast is checking the video file."
- [HELP-04] `AssetDetailScreen.tsx:823` Technical > State prints the raw code (`validated`, `pending_ingest`); the upload success text prints it too (`AssetUploadControl.tsx:322`). Fix: use the same labels as the table.
- [HELP-05] `AssetUploadControl.tsx:220` "The file is added to this list once ingest validation finishes." — validation is finished before "Uploaded" appears; a rejected file is not listed anywhere and leaves no row. Say: "If the file is not a supported video, you will see the reason here and nothing is saved." and state the size limit.
- [HELP-06] `AssetsScreen.tsx:222` and the Status "Package for playback" never explain Package vs Publish vs Remove from portal; the row can show "Packaged" and residents still cannot see it until Publish is approved. Fix: one sentence: "Package = make it streamable. Publish (Publish screen) = show it to residents."
- [HELP-07] `AssetsScreen.tsx:408,423` Edit trim / Package buttons appear only for `validated` rows although the API packages `recorded` rows too (`router.py:86,405`) and the detail page offers trim for `recorded`; `AssetDetailScreen.tsx:883-884` tells operators of a recorded file to "Set a public manifest URL in Setup", which contradicts the packaging path. Fix: show Package for `recorded`, drop the stale Setup sentence.
- [HELP-08] `AssetDetailScreen.tsx:771`, `:856`, `MediaLifecyclePanel.tsx:174-218,231` — Save metadata, Remove from portal, Legal hold and Replace source are all clickable for every role; a wrong role gets the raw API text "This action requires one of these CivicCast roles: …" after clicking. Fix: disable with the role named, as Package already does.
- [HELP-09] `MediaLifecyclePanel.tsx:159` "Archival (CLAUDE.md §4.6): portal + Internet Archive + local NAS, all verified" — a developer file reference in the UI. `:144` "Failed — normalize before air" has no control or help for normalizing. Fix: "All three copies (portal, Internet Archive, local NAS) have been checked." and say where to fix loudness (or that it is informational).
- [HELP-10] `MediaLifecyclePanel.tsx:254` replace-source dialog says every viewer sees the new file "immediately once processing finishes". The code resets the row to `validated` but leaves the old package/publish date untouched (`media_lifecycle_store.py:427`, no repackage call anywhere after replace), so residents keep the OLD video until someone packages again. Fix: "After replacing, use Package for playback again."
- [HELP-11] `OfflineCaptionJobsPanel.tsx:46` "Measured ~37 seconds for 11 seconds of audio on a 32 GB CPU-only reference machine" — lab figure; a volunteer cannot map it to their PC. Fix: "Transcribing a full meeting can take longer than the meeting itself."
- [HELP-12] `OfflineCaptionJobsPanel.tsx:49` "waiting in the caption review queue" — does not say that nothing is attached to the video until **every** cue is approved, edited or rejected, nor that "Review queue" is in the left menu. Add both.
- [HELP-13] `assetStatus.ts:71-77` (status "Missing file", also the same words in `media_lifecycle_worker.py:633`) tell the operator to "relink or replace the source", but the console has no relink control (grep of `OP/` finds no `relink` API function); only Replace source file (publish_operator/setup_admin) exists. Say "Replace the source file in the asset detail page."
- [HELP-14] Nothing on these pages links to the Manual (no `manual-link` use in any file of this screen).

### autoschedule

- [HELP-01] `AutoScheduleScreen.tsx:825` — "Run every enabled rule and add its picks to the schedule. The new items still need an operator commit before they air." — **Wrong.** Items are born Published and air without a commit (`autoschedule_materializer.py:20-27,285-297`). Contradicts the page intro (`:864-866`), which is right. — "Run every enabled rule now. The picks are approved to air immediately."
- [HELP-02] `AutoScheduleScreen.tsx:754` — "rules feed the commit gate before air." — Wrong for the same reason. — Delete or replace with "Simulate shows what a rule would place; compiling puts those items on air."
- [HELP-03] `AutoScheduleScreen.tsx:839` — "Added N scheduled items across M rules." — they are Published, not "scheduled" (the word means a different, not-yet-aired state on the Schedule screen). — "Added N programs to the schedule."
- [HELP-04] `AutoScheduleScreen.tsx:862-866` — omits that the station also compiles by itself every hour (`autoschedule_worker.py`); the intro says "reviewing the preview before you compile is the approval step", but a saved, enabled rule is compiled on a timer with no further step. — Add "Saved rules are also compiled automatically about once an hour."
- [HELP-05] `AutoScheduleScreen.tsx:460-461` — "(set by CIVICCAST_STATION_TZ; UTC if unset)" — environment-variable jargon, and incomplete (the zone chosen in First Setup is used, `app.py:1000-1024`). — "Times use the station's time zone from First Setup."
- [HELP-06] `AutoScheduleScreen.tsx:370` — daypart `Channel` is a free-text box with placeholder `public`, unlike Schedule and Program Guide which offer a channel dropdown. — use a dropdown.
- [HELP-07] `AutoScheduleScreen.tsx:679-686` — `Rolling window (days, 14–60)` and `No-repeat window (days)` are unexplained. — "How far ahead to fill" / "Don't repeat the same recording within this many days (0 = allow repeats)" (meaning per `autoschedule_models.py:392-394`).
- [HELP-08] `AutoScheduleScreen.tsx:188` — `Meeting body (exact)` — "exact" is cryptic; must match the meeting body text on the asset. — "Must match the asset's Meeting body exactly, including capitals."
- [HELP-09] `AutoScheduleScreen.tsx:588` — a `disabled` rule pill exists but there is no control to enable/disable a rule or daypart, nor to set priority or active dates (inputs are kept from the saved object, `:408-413,:700-710`). — manual should not mention enabling/disabling.
- [HELP-10] `AutoScheduleScreen.tsx:124` — `Delete` -> `Confirm delete?` on a rule gives no hint what happens to items already placed. — add sentence once verified.

### cg

- [HELP-01] `CgBoardScreen.tsx:713-715` — "Build the between-streams board, live ticker, schedule zones, and streaming output contract." — The screen cannot build anything except bulletins; zones, feeds and template are edited on CG Designer. — "Preview the community board and approve community bulletins for this channel. To change the board's layout, zones or feeds, use CG Designer."
- [HELP-02] `CgBoardScreen.tsx:126` — heading `Visual layout editor` — Read-only preview; nothing is editable and template buttons do not save. — Rename `Layout preview` and add "Choosing a template here only changes this preview."
- [HELP-03] `Sidebar.tsx:126` / `B/router.py:630` — CG Board is visible to everyone but bulletin queue requires publish_operator or setup_admin; a meeting_operator or support_admin sees a raw server message ("This action requires one of these CivicCast roles: publish_operator, setup_admin.") in a red box — hide the panel or show "Managing bulletins requires the publish operator or setup admin role." (CG Designer already has such an `AccessNote`, `CgBoardDesignerScreen.tsx:62-67`).
- [HELP-04] `CgBoardScreen.tsx:464-467` — "Approved bulletins air as branded filler slides between programs on channels set to “Community bulletins”." — correct but gives no path. — Add "(Channels -> Between programs, show)". Also: new bulletins start as Submitted and do not air until you press Approve.
- [HELP-05] `:630-632` — "Add an approved RSS, calendar, weather, or permitted social source…" — no pointer to where; jargon "feed-driven CG zones". — "No outside news or calendar feeds are connected. Add one in CG Designer -> Feed sources."
- [HELP-06] `:178,:135,:650` — raw strings `source-pending`, `proof_boundary`, `feed_adapter`-style kinds shown to operators — jargon. — Hide or caption.
- [HELP-07] `:719-735` — option `Public board` is channel id `public`, not a real channel; unexplained. — Caption: "Public board = the default board shown on the resident web portal."  UNVERIFIED that this is the meaning (code only shows id `public` used as default `channel_id`).
- [HELP-08] `:461` — two different buttons both labelled `Add bulletin` (panel header and form submit) — confusing for manual/screenshots. — Rename the submit to `Save bulletin`.

### cgdesigner

- [HELP-01] `:535-536` "The engine composites this board into the channel." — jargon; does not say when it shows (between programs as filler per `egress/bulletin_filler.py:5-7`). — "This board is what viewers see between programs on this channel."
- [HELP-02] `:62-67` vs `Sidebar.tsx:127` — support_admin can open the screen but every editing control silently disappears with no banner. — Show "You can view this board but not change it. Changing it needs the publish operator or setup admin role."
- [HELP-03] `:204-231` — labels `Region`, `Zone kind`, `Content source`, `feed adapter`, `emergency`, `bug`, `sponsor` are unexplained; values are raw enum text with underscores replaced. — add one-line helper under each ("Region = which part of the screen"), and say what each content source shows.
- [HELP-04] `:275-277` — "Require operator approval of feed items before they show" appears for every content source although it only matters for feed zones (UNVERIFIED for other sources). — show only for feed adapter.
- [HELP-05] `:384,:355` — `Trust tier`/`Feed tags`/`Allowed tags` unexplained; relationship between feed tags and zone allowed tags is only in a code comment (`board_models.py:97-98`). — "Only feed items with one of these tags will appear in this zone."
- [HELP-06] `:610` — changing `Board template` saves instantly with no confirmation or hint of effect. — add note or confirm.
- [HELP-07] `:589-593` — no button to switch a board off (API supports `active`, UI never sends it). Not a bug, but a manual should not promise it.
- [HELP-08] Header word `Designer` and nav label `CG Designer` vs title `CG Board Designer`; CG = "character generator" never spelled out anywhere in `portal-operator/src` (grep for "character generator" returns nothing). — spell out once.
- [HELP-09] No place says feeds can't be added unless a board exists (`:671` Feed panel only renders when a board exists). — empty-state text on Board should say "Create a board first, then add zones and feeds."

### channels

- [HELP-01] `feed-command-confirm.ts:30-31` Stop dialog — "Residents watching lose the stream until the feed is started again." — With "Keep this channel on air" saved, the automation re-issues Start for a stopped channel about every 30 s (`BE\egress\automation.py:1351-1380, 945`; `daemon.py:1495-1500` notes a stop is a candidate for re-start). The dialog and the 24/7 checkbox never mention each other. — Say: "If 'Keep this channel on air' is on, CivicCast starts it again within about 30 seconds. Turn that off first to keep it stopped." Confirm with an engineer; not run.
- [HELP-02] `ChannelOpsScreen.tsx:917-920` — "Keep this channel on air / Starts the feed automatically after restarts and crashes." plus "Save automation settings" with no confirmation. Saving it ON for an enabled channel can put the channel on air without anyone pressing Start. — Add a consequence sentence and ideally a confirm.
- [HELP-03] `ChannelOpsScreen.tsx:1150, 1196-1200` — lower-third pill reads "On air" for the SAVED setting although the picture only changes on the next pipeline build; the explanation is in small grey text. — Rename pill to "Saved: on" / "Saved: off".
- [HELP-04] `CommitToAirPanel.tsx:85` button "Approve & put on air" and `commit-format.ts:15-28` "Queued to air" — The click publishes the schedule item and queues a feed start/reload; the program airs at its scheduled time, not at the click, and on a stopped channel the click also starts the whole feed. No confirmation. "On air (confirmed)" is never produced: no code sets the `acknowledged` state (only defined in `BE\schedule\commit_models.py:79-88`). Row text "aired <time>" is shown for future programs. — Reword to "Approve for the schedule"; explain timing; ask coder to add a confirm; drop "confirmed" claim.
- [HELP-05] `TakeoverCard.tsx:154-158, 262-273` — "Put a live source on this channel now, overriding the schedule" — The screen never says WHICH source (`path_id` not sent) or that it lasts up to 1 hour (`router.py:145`; what happens at 1 h is UNVERIFIED), and the button silently disables 30 s after the last "Check source" with only "No live source is ready yet." — Help must tell the operator to run "Check source" on Live just before and to read the source name afterwards in the "Live takeover — <name>" badge.
- [HELP-06] `ChannelOpsScreen.tsx:356-364, 474-484` — "Save station config" / "Save channel branding" are enabled for everyone but the server needs setup_admin or publish_operator (`app_platform\router.py:152, 192`); a meeting operator gets a raw "This action requires one of these CivicCast roles: publish_operator, setup_admin." Also "Build tier", "Store ready", "Analytics enabled" are unexplained and change public app settings. — Gate/explain.
- [HELP-07] `CommitToAirPanel.tsx:432-436` — if the commit list call fails (for example a meeting_operator without publish rights: `playout_router.py:213`) the panel still says "Nothing has been committed to air on this channel yet." because errors are not shown. — Misleading; coder fix or help note.
- [HELP-08] `ChannelOpsScreen.tsx:1271` vs `2089` — banner help says meeting operator or setup admin may edit; only meeting_operator can in the UI.
- [HELP-09] `CableVerificationCard.tsx:61-62` — "Turn this on and CivicCast downloads the free TSDuck toolkit for you — no separate setup, no admin rights" — says "Turn this on" but the control is a download button with no confirm; internet access is required. — Say "Downloads about N MB from the internet; press only on a connected station" (size not in code: UNVERIFIED).
- [HELP-10] `ChannelOpsScreen.tsx:896-898` — "Create one from the channel egress runbook (or the setup flow)" — a non-technical user cannot act on this; the real step is "Apply a headend preset" (the Start reason names it). — Align wording and point to the preset panel.
- [HELP-11] Jargon unexplained: "Proof log", "Machine summary", "CTV feed", "Decode-back proofs", "LUFS/LKFS", "SAP", "TSDuck", "mux rate", "HLS", "NDI", "SDI", "pipeline build", "Regime", "Standard". — Glossary in help file.
- [HELP-12] `ChannelOpsScreen.tsx:1981` pill "refreshes every 30s" while feed state after Stop/Restart may take up to 30 s to change (only Start polls faster, 1886-1888). — Tell operators a Stop can take up to 30 s to show.

### commissioning

- [HELP-01] CommissioningWizardScreen.tsx:218 — "Complete the first-run cable checks first (all pass or Continue-anyway on warnings)." — there is no "Continue anyway" button; the step unlocks automatically when no check says FAIL — fix: "Run the cable checks. This step opens when no check fails (warnings are allowed)."
- [HELP-02] CommissioningWizardScreen.tsx:126 — "Run cable checks" always sends profile `peg-cable`, so even a public-meetings station gets "DeckLink / BMD Desktop Video SDK" and cable wording — and nothing on screen says this wizard is only for stations that feed a cable headend; the sidebar entry is visible to every setup_admin — fix: add an opening paragraph "Only needed if this station sends a channel to a cable company."
- [HELP-03] CommissioningWizardScreen.tsx:259-276 and 277-288 — Screen 9 looks like it configures the channel (headend profile, destination, format, fill policy), but it only saves the choices to the station record; nothing outside the CLI report reads `channel_setup` (grep of `civiccast\**\*.py`), and the proof sends to the channel's existing UDP output set on the Channels screen — fix: say "This records your choices for the report. Apply the headend profile on the Channels screen first, or the proof will fail with 'no udp-ts sink'."
- [HELP-04] CommissioningWizardScreen.tsx:375-376 and 421 — "through the GStreamer engine" / "through the live GStreamer engine ... replacing the channel's real output" — code drives an ffmpeg test-pattern generator straight to the UDP address (commissioning.py:484), it does not replace on-air output but sends a second stream to the same address; the dialog's warning is still right to scare on-air users, but it names the wrong component and doesn't say "do not run while the channel is on air" — fix: "Sends a test signal to the cable-headend address for N seconds. Do not run this while the channel is live."
- [HELP-05] CommissioningWizardScreen.tsx:578 — "Screens 8-11 of the commissioning wizard (S3)" — "Screens 1-7" do not exist on this page, "S3" is an internal spec tag; the step cards are titled "Screen 8..11" — fix: number them Step 1-4.
- [HELP-06] SystemHealthScreen.tsx:1279 — "Support bundles require support admin." appears on this screen to a signed-in support_admin (because `canCreate` is `setup_admin`), while a setup_admin-only token is allowed to click and gets 403 from the server (router.py:911). The single local admin (scope `admin` = all roles) works — fix: pass `canCreate` from the real server rule.
- [HELP-07] CommissioningWizardScreen.tsx:171-176 and 310-312 — Output format codes (720p30, 1080i60...) and Fill policy "Slate / Loop / Silence" have no explanation (what a slate is, what fill policy covers); "SDI device (optional)" has no example — fix: one help line each.
- [HELP-08] CommissioningWizardScreen.tsx:389-391 — Test pattern "Live" is offered but behaves exactly like bars + tone in code; fix: remove or implement.
- [HELP-09] CommissioningWizardScreen.tsx:81, 435 — check statuses and the verdict show raw "FAIL / WARNING / SKIPPED / partial" instead of the five standard readiness phrases from `status-language.ts` — fix: route through `readinessLabel`.
- [HELP-10] Output proof messages end with "(boundary) The output proof drives a bounded ffmpeg SMPTE-bars+tone generator ... (that remains rung 3, MASTER §13.2, gated on real DeckLink hardware)" — internal planning vocabulary shown to the operator — fix: "This test checks the network signal only, not SDI hardware."
- [HELP-11] The whole screen never says what passing means (e.g. "Ready for broadcast" has no definition; per code it also requires the proof to have no blockers, so a "partial" verdict can never read as ready, commissioning.py:713) — fix: define in a sentence.

### contribute

- [HELP-01] `ContributeScreen.tsx:97` every failure, including a failed Accept/Decline/Schedule or a 403 for a support admin, is titled "Contributor queue could not load." Fix: a separate box "That action did not go through: {reason}".
- [HELP-02] `contribute/store.py:855` (shown to the contributor and listed in "Status notification outbox") says a scheduled program "will air automatically", but "Send to schedule" only creates a draft entry; it airs after Commit-to-Air (`egress/source_plan.py:507-509`). Operators are not told that step is still theirs. Fix: button hint "Creates a draft entry on the Schedule. Commit it there to put it on air." and change the contributor wording.
- [HELP-03] `ContributeScreen.tsx:143-153` "Status notification outbox" and "Status notices" suggest messages were sent. Notices are only recorded in the submission file; no code outside `civiccast/contribute/` reads them (`grep notifications_sent` / `notification_outbox`), no mail is sent from here. Contributors see status only by pasting their receipt token on the public "Check submission status" box. Fix: label "Status messages (not emailed)" and tell producers to keep the receipt.
- [HELP-04] `:353-355` "Send to schedule" uses the requested air date or the current time, the channel stored on the submission (the public form always sends channel `public`, `HomeScreen.tsx:273`), and 30 minutes; none of this is shown before clicking. Fix: show "Channel: {id}, start: {date}" under the button and warn when no date was requested.
- [HELP-05] `:296,300-303` "Decline reason" and "Operator note" are not explained: are they shown to the producer? Code: the decline reason is returned in the contributor status (`store.py:207`); notes are not visible to producers (UNVERIFIED, see below). Fix: say who sees each box.
- [HELP-06] `:341-346` "Accept" does not say it will check the file and copy it into the library, that a bad file is refused, or that the asset then appears in Assets. `:231-234` "Media gate" prints `not run`/`passed` without explanation. Fix: hint text on the buttons and a tooltip on "Media gate".
- [HELP-07] Page heading "Contributor submissions" vs nav "Contributors"; label "Producer workflow"; "Agreement: {id} / {version}" shows internal ids. Fix: "Agreement accepted: {title}, version n".
- [HELP-08] The page never says where producers submit (public portal home page, "Submit a program") or gives a link/copy button to give to producers. Add one sentence and a link.
- [HELP-09] `:34-42` no "Published" tab although that state exists; Accept/Decline/Send to schedule have no confirmation, and Decline of a Scheduled/Accepted item cancels a schedule entry silently.
- [HELP-10] No link to the Manual on this page; the nav shows the page to roles that cannot use it (records_clerk, setup_admin) and shows actions to roles that cannot act (support_admin).

### controlroom

- [HELP-01] `BE\control_room\service.py:809` + `ControlRoomReadinessPanel.tsx:122-147` — `station_device_ready` is hard-coded False, so the headline can never read "Ready" and the warning "On-air readiness is confirmed once a check against the room's actual devices passes." is permanent. No screen offers that check. A clerk will wait for something that cannot happen. — Help must say: "This always shows 'Check before meeting'; it means the equipment has not been verified by CivicCast, not that something is broken." Log for coder.
- [HELP-02] `ControlRoomScreen.tsx:326, 725-730` + `service.py:237, 303-313` — an On-Air session silently expires after 30 minutes and the screen never shows the time left. After expiry the session is closed server-side, so both "Panic: Run Safe State" and "Roll back to Safe State" fail with "On-Air Mode expired ...". Council meetings often run longer. — Tell operators to re-open an On-Air session before 30 minutes; coder should show a countdown. (Rollback bypasses expiry only while the session is still open.)
- [HELP-03] `ControlRoomScreen.tsx:322-328` — "Panic: Run Safe State" is disabled until you press "Dry Run Safe State", and any other cue's dry run disables it again. In an emergency the label says "Panic" but needs two presses and has no confirmation. — Explain the order in the button's neighbour text; suggest always dry-running the safe-state cue after opening the session.
- [HELP-04] `ControlRoomScreen.tsx:530-533` — "requires the publish/meeting operator, setup admin, or support admin role" — publish_operator is not a permitted role (`READ_ROLES`, line 50; backend `router.py:78-90`). — "requires the meeting operator, setup admin or support admin role".
- [HELP-05] `BE\control_room\router.py:219-225` shown through `ControlRoomScreen.tsx:687` — 409 text tells the user "A setup admin or support admin can force-close it", but no screen button does that and a refresh loses your own open session id (it is held in page memory, line 433). — Document how a stuck lock is cleared (admin ends the session via API/support) or add a control.
- [HELP-06] `ControlRoomScreen.tsx:560-561` — "TSR control service", "LPM profile coverage", "Safe State", "S5", "Playout (S5)" (260) are unexplained jargon. — Replace "TSR control service" with "the production-control helper" in help text; drop "(S5)".
- [HELP-07] `ControlRoomScreen.tsx:203-206, 214` — "needs confirm" is shown on cue buttons; "Fire..." vs "Test..." wording changes with mode but a first-time user cannot tell a Test session fires nothing until reading the blue banner. — Help should lead with "Test Mode never touches your equipment".
- [HELP-08] `ControlRoomReadinessPanel.tsx:75-77` — for the TSR check the screen replaces the server text with "Open Control Room Setup to start or reconnect the local control service before On-Air use." but the backend action says to set `CIVICCAST_CONTROL_ROOM_TSR_URL` (`service.py:574`). — The setup screen may not start the helper (see `controlroomsetup.md`); verify before publishing the sentence.

### controlroomsetup

- [HELP-01] ControlRoomReadinessPanel.tsx:76 — "Open Control Room Setup to start or reconnect the local control service before On-Air use." — there is no start/reconnect control on this page; the service is configured by the environment variable `CIVICCAST_CONTROL_ROOM_TSR_URL` and "supervised" elsewhere; the red button "Open Control Room Setup" also points at the page the reader is already on — fix: say who starts the service (support/IT) and drop the self-link on this screen.
- [HELP-02] ControlRoomSetupScreen.tsx:290 — checkbox label "Confirm" — unexplained. The backend treats a cue with this ticked as the "safe-state cue", and readiness is BLOCKED if a surface has cues but none ticked (service.py:544-548,771-790) — fix: label "Ask for confirmation before firing (use for the emergency/safe cue)" and say each surface needs at least one.
- [HELP-03] ControlRoomSetupScreen.tsx:188-200 — "TSR device type", "Take-delay (ms)", "Post-roll (ms)" — jargon and no help text; the boxes start at 0 and never show the saved value, and "Save profile" also clears hidden options — fix: show saved values, explain in one sentence each, and warn that saving replaces the old profile.
- [HELP-04] ControlRoomSetupScreen.tsx:134-137 — Transport list shows raw "tcp/udp/http/websocket/serial/gpi"; "serial" and "gpi" transport conflict with the note that direct serial/GPI hardware is unsupported — fix: pick the transport automatically from Kind or explain.
- [HELP-05] ControlRoomSetupScreen.tsx:152 — placeholder "kept in keyring" — jargon — fix: "Stored securely on this computer; never shown again."
- [HELP-06] service.py:651 (readiness check "Enabled devices") says "Enable required devices or remove unused disabled devices" but this screen has no way to disable or enable a device (every device is created enabled; edit API unused) — fix: add an Enabled toggle or reword.
- [HELP-07] policy.py:156 error text mentions a "public-host override reason in the device profile" that the screen cannot record — a user who gets this error on Test connection has no UI path out — fix: state "ask support" or add the control.
- [HELP-08] ControlRoomSetupScreen.tsx:416-418 — H1 "Control Room — setup" vs sidebar "Control Room Setup" and "Surfaces" / "cues" / "LPM profile coverage" — "surface" and "LPM" are never defined on the page — fix: add a one-line glossary under the H1.
- [HELP-09] No explanation anywhere on the screen that "Test connection" really contacts the device through the control service, and that a result older than 5 minutes shows "Stale — probe again".

### custom-fields

- [HELP-01] CustomFieldsScreen.tsx:262 — "Searchable (portal facet)" and 271 "Exposed to public API" — a field only appears as a public filter when BOTH are ticked; ticking only "Searchable" does nothing for residents, and "API" is jargon for "visible to the public" — fix: one control "Show on the public website" or explain that both are needed.
- [HELP-02] CustomFieldsScreen.tsx:162,181 — "Field key (machine name)" / "Lowercase machine key" — nothing stops capitals or spaces (only the internal id is slugged), and creating a second field with the same key silently replaces the first (upsert), including changing its type — fix: refuse duplicate keys with a plain message, or validate the pattern.
- [HELP-03] CustomFieldsScreen.tsx:415 — delete conflict text is the server's: "Custom field 'cf-meeting-type' has existing values; pass confirm=True to cascade-delete them." followed by "Confirming will permanently delete this field and all its values." — shows an internal id and "confirm=True"; also the first Delete click on a field with no values deletes it with no prompt — fix: always confirm and say "N assets have a value for this field".
- [HELP-04] CustomFieldsScreen.tsx:361-380 — ↑ ↓ reorder buttons swap the Order numbers; when fields share Order 0 (every field made without setting Order) nothing visibly moves — fix: renumber all rows on move, or explain Order.
- [HELP-05] CustomFieldsScreen.tsx:203-222 — Type can be changed on a field that already has values; no warning about what happens to existing values (UNVERIFIED) — fix: warn or lock when values exist.
- [HELP-06] AssetCustomFieldsEditor.tsx / store.py:328 — a "Required" field makes any asset without a value unsavable (including values for other fields); server message uses ids: "Required field 'cf-x' ('Label') must be present." — page never warns that ticking Required affects every existing asset — fix: warn on the Required checkbox.
- [HELP-07] CustomFieldsScreen.tsx:51 — the screen creates fields for station id `civiccast-station` always, while the server lists fields for `CIVICCAST_STATION_ID` if set; with that variable set new fields would not appear in the list — fix: let the server assign the station.
- [HELP-08] Nav/section: sidebar group "Setup" holds this entry, but its effect is mostly on Assets and the public site; neither page says where the fields show up besides the one H1 sentence — fix: add "Edit values on Assets > (an asset)".

### eas

- [HELP-01] EasScreen.tsx:100 "Add an NWS, AMBER, or IPAWS (COG) feed to begin ingesting" - there is no way to add a feed in the console (see Controls). The only route is the API (`PUT /api/staff/eas/sources/{id}`, setup admin). Fix: say who adds feeds and how, or add the form. "COG" and "IPAWS" are undefined.
- [HELP-02] Nothing on screen says that every `severe` or `extreme` active alert is put on air **automatically** on every channel that is ON_AIR (crawl for severe, overlay for extreme) with no operator action (`app.py:564-585`, `eas/service.py:36,56-58`). The banner says only "never automatically pre-empts programming". An operator who reads the screen thinks nothing airs until they click. Fix: add "Severe and extreme alerts appear on every on-air channel automatically; use Clear to take one down."
- [HELP-03] The banner and h1 say alerts display "on your channels"/"on-channel", but the display decision is read by the public overlay endpoint (`app.py:3169`, `eas/service.py:154-175`). UNVERIFIED whether a crawl/overlay is burned into the cable/stream video or only drawn by the resident web player. This decides what an operator may promise the city. The egress side has `raise_cg_emergency_overlay` / `clear_cg_emergency_overlay` hooks (`egress/supervisor.py:182,188`) but no code was found that calls them from an EAS decision. Needs a check of the egress/graphics path.
- [HELP-04] :395 default channel id `gov` is a hard-coded guess; if the station has no `gov` channel the dropdown still lists it (:382). Fix: default to the first real channel.
- [HELP-05] Buttons `Show crawl`, `Show overlay`, `Forced slate` give no success message and no explanation of crawl vs overlay vs slate for a first-time user; `On-channel now` shows raw `forced_slate`.
- [HELP-06] Forced slate uses a checkbox rather than the `ConfirmDialog` used by `Clear`; the checkbox label `Confirm full-screen takeover` does not say it covers the whole picture for residents.
- [HELP-07] `AuthRequiredState` text names "the CivicCast installer handoff" and "a fresh operator-console link" - neither exists as a step a clerk can do; sign-in is on First Setup (`SetupScreen.tsx:1593`). Fix: "Sign in again on First Setup."
- [HELP-08] `polling` (:118) reads as healthy; a failing feed still says `polling`.
- [HELP-09] Page type scale and heading style (h1 `text-lg`, `Alert sources` h2 `text-sm`) differ from the other System Health screens (`text-2xl`); minor visual inconsistency.

### epg

- [HELP-01] lines 593-599 — "committed schedule", "field map", "aggregator endpoint", "X-List" are unexplained. Plain version: "Creates a file of your upcoming program schedule for TV-guide services. Use Download to get the file, or give an https address to send it automatically."
- [HELP-02] lines 248-266 and placeholder `channel=pub-1` `genre=category` — wrong example. The map only renames column headings, and the real column names are `start_date, start_time, end_date, end_time, title, description, category, rating` (`epg.py:165-174`). `channel` is not a column, and a map for XMLTV has no effect. Suggested placeholder `title=Program Title` and the text "Optional. Rename column headings: left = CivicCast name, right = the heading the guide service expects. Does not apply to XMLTV."
- [HELP-03] lines 223-246 — "Aggregator endpoint" says nothing about what is sent (the whole guide for the horizon, every press of Generate now) or that no password can be supplied. Add: "Generate now sends the whole guide to this address immediately. CivicCast cannot log in to the receiving service."
- [HELP-04] lines 163-179 "Channel ID" with placeholder `pub-1` — a person cannot know their channel id here. Provide a drop-down (the Reports screen already has one) and say "0 slots means this channel has no published schedule items in the next N days."
- [HELP-05] lines 595-596 — the export promises a guide but descriptions, categories and ratings are always empty (`schedule_adapter.py:84-97`; `app.py:3189` passes no category resolver). Don't promise genre/category columns in the manual until wired.
- [HELP-06] line 416 "Generate now" — no warning that a push to an outside service cannot be recalled (the Delete warning does mention "Existing aggregator data is not deleted"). Add a confirmation when an endpoint is set.
- [HELP-07] lines 340-343 "The staff API is still up; retry once the aggregator endpoint recovers." speaks to developers. Say "The guide file could not be delivered. Nothing was changed on your station. Check the address and try again."
- [HELP-08] Config ID: no format hint for the slug rule; capitals or spaces fail with a server message. Add "lowercase letters, numbers, - and _ only".
- [HELP-09] The Edit form can change channel, format, horizon, endpoint, field map but not the Config ID; the grey disabled box does not say why. Add "ID cannot be changed".
- [HELP-10] Nav says "EPG Export" while Run Meeting has a separate "Program Guide" screen; the manual needs one sentence on the difference (Program Guide = the on-air guide; EPG Export = file sent to outside services). UNVERIFIED which of the two Program Guide is (not read).

### facility

- [HELP-01] `BE\facility\router_control.py:45` shown in "Take preview" as "Operator action. Confirm the previewed route, then send the command from the router panel." — There is no send control anywhere, and the page says hardware send is disabled. — Replace with "Preview only. This version does not send commands to a router."
- [HELP-02] `FacilityRouterScreen.tsx:304, 850` pills "preview only" / "hardware send disabled" and the inventory (`store.py:42-80`) — a clerk will assume the listed router, "Council chamber" and 192.0.2.10 are THEIR equipment. They are sample data. — Add a visible "Sample data" note until real inventory exists; manual must say so.
- [HELP-03] `FacilityRouterScreen.tsx:654-657, 40` vs `BE\facility\router.py:51, 77` — UI enables the scheduled-take and overlay buttons for meeting_operator or setup_admin and says "require the meeting operator or setup admin role"; the backend allows meeting_operator or support_admin. A setup admin sees enabled buttons that return 403 ("This action requires one of these CivicCast roles: meeting_operator, support_admin."). The virtual buttons and "Preview take" have no UI gate at all although the backend gates them, and the amber note says they "remain available" (864-865). — Align the roles and fix the note.
- [HELP-04] `FacilityRouterScreen.tsx:560-561, 421-422` — "Preview the automatic source take that arms before a scheduled program." / "Preview L-bar and squeezeback output before starting the live compositor." — Neither a real schedule nor a "start compositor" control exists; the scheduled preview uses a made-up item 15 minutes from now. — Say "Example only: shows a take 15 minutes from now."
- [HELP-05] `FacilityRouterScreen.tsx:37` — "Configure a channel in Channel Ops" — nav label is "Channels" (`Sidebar.tsx:125`). — "Configure a channel on the Channels screen."
- [HELP-06] `FacilityRouterScreen.tsx:395, 471, 604, 938` — "Proof boundary: ..." and the string "overlay-compositor-command-planning-no-ffmpeg-execution" printed verbatim. — Jargon / machine id. Rename to "What this does not do" with plain sentence.
- [HELP-07] `FacilityRouterScreen.tsx:846` — "SDI/IP router takes", "L-bar", "squeezeback", "crosspoint" are unexplained. — Add one-line glossary in the help file.

### guide

- [HELP-01] `ProgramGuideScreen.tsx:447-449` — "The automation engine airs scheduled entries and falls back to filler between programs." — Misleading: the entries this screen builds are state Scheduled, which do **not** air until approved with `Publish to residents` on the Schedule screen (or Channel Ops Commit-to-Air). Only Published items go to air (`egress/source_plan.py:507-511`). A station that adds a weekly slot and walks away gets nothing on air. — "Each slot creates Scheduled items on the Schedule screen. Open Schedule and press Publish to residents on each one to approve it to air."
- [HELP-02] `ProgramSlotDrawer.tsx:19-21` — `Weekdays`: "Airs Monday through Friday." — The weekday test is done on the UTC date (`occurrences.py:44-46`, console sends UTC, `ProgramSlotDrawer.tsx:119-127`). For a US evening start (e.g. 7 PM Mountain = 01:00 UTC next day) the Friday-evening airing falls on UTC Saturday and is dropped, while Sunday-evening (UTC Monday) is kept. Daily/Weekly also step by fixed 24 h / 7 d in UTC, so local air time moves by an hour when daylight-saving time changes. — Until fixed, the manual must warn; otherwise "Weekdays" should be verified per station time zone. (Probable defect, UNVERIFIED by running.)
- [HELP-03] `ProgramGuideScreen.tsx:544` — "...nothing new will schedule until the slot is re-enabled." — there is no way to re-enable. — "To restart a disabled slot, add it again."
- [HELP-04] `ProgramGuideScreen.tsx:186-187` — "The program guide is the weekly grid of what airs..." — the screen shows two lists, not a grid. — "A list of repeating programs for this channel."
- [HELP-05] `ProgramGuideScreen.tsx:33-41` — chip `manual` appears raw; `Skipped · conflict` gives no next step. — add `manual: 'Scheduled directly'` and a hint "Change or cancel the other program, then Refresh guide".
- [HELP-06] `ProgramGuideScreen.tsx:483-495` / nav — `Refresh guide` is global (all channels), toolbar suggests it is per channel. — "Refresh guide (all channels)".
- [HELP-07] `Sidebar.tsx:130` + `programlog/router.py:132` — visible to everyone, writable only by meeting_operator / support_admin; a publish_operator or setup_admin-only token sees the failure only after filling the form. — gate the buttons with a role note (like Schedule does).
- [HELP-08] `ProgramSlotDrawer.tsx:79-82,231-233` — lists only `validated` assets, so recordings captured by the Recording screen (state `recorded`, `recording/runtime.py:679`) cannot be picked, although the materializer accepts `recorded` (`materializer.py:41,196`). Message sends the user to "the Assets tab" with no action to take. — include `recorded` assets.
- [HELP-09] `ProgramGuideScreen.tsx:446` — nav says `Program Guide`, heading says `Program guide`, eyebrow `Workflow` (not a nav section name). Minor.
- [HELP-10] No place shows or edits a slot after creation (the API supports `PATCH /slots/{id}`, no UI). Manual should not promise editing.

### health

- [HELP-01] SystemHealthScreen.tsx:1520 vs :1552 - header pill says `Check before meeting` for every yellow, while the card below shows the server label, which is `Ready with optional items` when only optional items are yellow - the same page shows two different verdicts for one state, and the second is not one of the five approved phrases. Fix: one phrase, or make the pill use `report.label`.
- [HELP-02] SystemHealthScreen.tsx:198-203 - gate items are `<a href="#health-check-<id>">`. The console runs under `HashRouter` (`main.tsx:14`); `Layout.tsx:36-46` documents that a bare `#...` link is read as a route and lands on "Page not found". UNVERIFIED at runtime, but the same codebase calls this a known failure. Fix: scroll with JS like the skip link does.
- [HELP-03] Name drift: nav `Readiness`, h1 `Safe to broadcast`, eyebrow/copy `System Health`, server text "Use Run Meeting for the live event and keep System Health open." (`service.py:4088`). A first-time user cannot tell these are one place. Fix: pick one name.
- [HELP-04] `Check broadcast readiness` (:1577) hides what it does: the server makes a private live session on channel `government`, copies the sample video and finalizes a recording asset (`service.py:3889-4004`). Panel text says only "checks configuration, storage, and the bundled sample video" (:166). Fix: say "This creates a short private test recording in your media library" (UNVERIFIED whether it is visible on Assets) and name the result "Private rehearsal".
- [HELP-05] :1517/:1553 "Last checked" - no Refresh control, and the checklist does not poll (see States). Fix: add `Refresh` and say when it updates.
- [HELP-06] Jargon with no explanation for a non-technical reader: `GStreamer closure`, `FFmpeg fallback engine` (:826-828), `SHA-256`, `Schema drift ... re-migrate` (:610), `proof event`, `Migration safety`, `Window expires`, `Rollback artifact`, `SRT`, `Dropped frames`, `LUFS`. Fix: one-line plain definitions or a manual link (`manualLink()` exists but this screen never uses it).
- [HELP-07] :1657 "Close of the window happens automatically when it expires." - garbled sentence. Fix: "The window closes by itself after 60 minutes."
- [HELP-08] :1026-1027 buttons are greyed out with no reason (e.g. `Open maintenance window` needs preflight and rollback proof; `Run failed-update rehearsal` needs proof `passed`). Only the three role notes explain disabled state. Fix: show the missing prerequisite under the button.
- [HELP-09] :783 and :1584 name roles ("meeting operator") but the screen never says how an operator gets that role; role labels in the top bar are hover-only (`TopBar.tsx:152`).
- [HELP-10] :1254 "Generate a redacted troubleshooting file for tester support." - "tester" is beta-only wording and does not say where the file goes or who may read it. Fix: "for CivicCast support" plus what is redacted (UNVERIFIED - read `support_bundle` redaction code).
- [HELP-11] Feed controls (:756-761) do not say the command is only queued; nothing tells the user to wait or refresh, and the egress panel has no polling. After `Restart feed` the pill may stay on the old state.
- [HELP-12] :1175 placeholder path ends `CivicCast_1.4.0_x64-setup.exe` - a 1.4.0 example on a 1.0 beta product; may mislead.

### help

- [HELP-01] The shipped in-app manual is out of date against its own source. `manual.json` (commit `c08032c4`, 2026-10-02 02:34 -0600) was rendered before `docs/USER-MANUAL.md` last changed (`9b834a3d`, 2026-10-02 20:36 -0600; current source sha `9ec58a06...94d6` != recorded `b5df977e...6e37`). The tag `v1.0.0-beta.10` carries the old file (`manual.render.json` at the tag has the same hash). The in-app text still says beta.10 "is a beta candidate: it has not been published, and its formal station acceptance (Gate A) has not been run. The latest published release is v1.0.0-beta.7" - false for the running product. The CI drift gate (`ci-docs.yml:75-76`) would fail on this tree. Fix: re-render at the end of the doc sprint and re-check before the next tag.
- [HELP-02] The manual body has 36 internal links of the form `href="#section"` (e.g. `#glossary`, `#your-first-beta-workflow`). The console is a `HashRouter` app (`main.tsx:14`); `Layout.tsx:36-46` records that a bare `#...` link is read as a route and lands on "Page not found". `ManualScreen` has no click handler on the content panel (:145-155). So cross-links inside the manual very likely break. UNVERIFIED at runtime (needs one click in the lab). Fix: intercept clicks in the content panel and route them to `/help#id`, or rewrite hrefs at render time.
- [HELP-03] Section `report-without-github` (the target of the sidebar `Report a beta issue` link) tells the reader to go to System Health and press `Create support bundle` and `Download support bundle`. Those buttons work only for the `support_admin` role (`SystemHealthScreen.tsx:1496,1279`; `installer/router.py:911`), and the nav calls the page `Readiness`, not `System Health`. A meeting operator or records clerk cannot follow the steps. The same section sends people to `SECURITY.md`, a repository file they cannot open from the console. Fix: say who can create the bundle and put the contact address in the text.
- [HELP-04] Section `your-first-beta-workflow` tells users: "In System Health, choose Run private rehearsal." No such button exists; the button is `Check broadcast readiness` (`SystemHealthScreen.tsx:1577`), and the screen's own name is `Readiness`/`Safe to broadcast`.
- [HELP-05] `Search this manual` (:131) promises a text search but filters section titles only (:62-63). Fix: placeholder "Filter sections by title" or add real search.
- [HELP-06] Intro text (:98) names a repository file path (`docs/USER-MANUAL.md`); a clerk does not know what that is. Fix: "This is the CivicCast user manual, built into the console so it works without internet."
- [HELP-07] The contents list is one flat 64-entry list that mixes the clerk-level guide (Section A) with engineering sections B and C (environment variables, Alembic migration chain, protocol seams). Nothing labels "start here" or role-based guides (the quick guides are three entries in the middle of Section A). Fix: show Section A by default and fold B/C under "For IT staff".
- [HELP-08] All 45 external links (GitHub, Google Cloud console, etc.) open in the same tab because the sanitizer drops `target`/`rel` (`render.py:123`); the intro promises it "works with no internet connection" but many steps are external. Clicking one replaces the console; a clerk loses their place. Fix: allow `target="_blank" rel="noopener noreferrer"` for http(s) links.
- [HELP-09] Section `roles-and-permissions` / `the-five-role-model` cite `KNOWN_ROLES` and `require_role("...")`; neither name exists in the code (`civiccast/auth/roles.py` has `ALL_OPERATOR_ROLES` and `require_any_role`; searched all `*.py`). The table says support_admin "cannot change records or publish" while code lets it run restore/update/rollback, moderate federation and edit schedule/CG data (see `_shell-navigation-and-roles.md`). Fix: regenerate that section from `_shell-navigation-and-roles.md`.
- [HELP-10] Section `destructive-actions-confirm` lists "Emergency Alert Screen - ... force a slate" among actions that show a confirmation dialog; the code uses a tick-box, not the dialog (`EasScreen.tsx:177-196`). The same section says the Channels feed buttons are covered; Alerts destination delete uses an inline two-step button instead (`AlertsScreen.tsx:612-630`).
- [HELP-11] Section `provider-federation` says to "open ActivityPub in the console" and "See the station's ActivityPub screen for the current on/off switch"; the nav item is `Federation` and the screen has no on/off switch (see `activitypub.md` HELP-01).
- [HELP-12] On a failed load the operator sees developer wording such as "Run: uv run python scripts/render_docsite_manual.py" (`service.py:38-40`). Only reachable on a broken install, but should be a plain "The manual file is missing; reinstall or contact support."
- [HELP-13] There is no link from the Manual page to the PDF/Word copies that exist in `docs/` (`USER-MANUAL.pdf`, `.docx`), and no print layout rule was found for the page (UNVERIFIED: `index.css` print rules not searched).

### installer-component-catalog

- [HELP-69] Plain-English names differ from the files a support person sees (`native-app-payload.ccpack`, etc.); the manual needs one translation table (this file).
- [HELP-70] The "Database & messaging services" name is stale (see HELP-53).
- [HELP-71] The wizard names two sizes as measured "from the manifests" (`components-catalog.ts:7-13`) but they are fixed placeholders; the first total shown can change once.
- [HELP-72] "Local AI model (summaries & translation)" is one row but the station needs three models (gemma4:12b, gemma4:e4b, translategemma:4b); only the first is on the screen.

### installer-failures-and-logs

- [HELP-105] SERIOUS: About 26 distinct setup exit codes (110-135 plus 82) with no table available to the operator; the dialogs show text but never the code, and the silent run shows only the code. The manual needs this table; the setup should print "Error 123" in dialogs.
- [HELP-106] Dialogs say "contact support" but give no contact (see HELP-74).
- [HELP-107] Dialog 114 says "Use the manual upgrade path with operator acknowledgement" and no manual path exists in setup text.
- [HELP-108] Exit code 77 is returned by the preflight but is not named in any text read (UNVERIFIED meaning).

### installer-gui-checking-computer

- [HELP-45] `AcquisitionFlow.tsx:313` "reopen CivicCast Installer" — there is no icon or shortcut called "CivicCast Installer"; the Start Menu entries created by setup are the two web shortcuts (`nsis-hooks-bootstrap.nsh:1791-1807`) and the app is "CivicCast (Native)". Suggest "close this window and open CivicCast (Native) again from the Start menu" (UNVERIFIED that Tauri creates a Start Menu entry for the app).
- [HELP-46] The disk check counts only the downloadable components (about 9.7 GB for the default set), not the ~21 GB of model packs the earlier setup phase already extracted, and says nothing about space needed after downloads (recordings). A resident-style reader will think 10 GB is enough. Suggest stating the figure and that recordings need more.
- [HELP-47] "Medium"/"Large" caption engines are named without saying what the difference means for the meeting (live vs after the meeting) until the next screen.
- [HELP-48] Graphics line says "(8 GB)" with no explanation that 8 GB or more is the threshold; add "needs an NVIDIA card with 8 GB or more".
- [HELP-49] `AcquisitionFlow.tsx:218` "usually takes a few seconds" is not tested on a slow box; the first-launch screen before it says up to a minute (`App.tsx:640`).

### installer-gui-download-plan

- [HELP-50] `AcquisitionFlow.tsx:394-395` "Anything already on this computer or on your USB kit is used as-is" — the elevated setup that ran just before this screen already required the kit, and (per `nsis-hooks-bootstrap.nsh:1441-1445,2184-2209`) cannot finish without the station model packs. A resident or clerk reads "only what is missing comes from the internet" as "setup.exe alone works". Needs an owner/coder check before the manual promises either path (see `installer-nsis-packs-and-verify.md`).
- [HELP-51] The row "Local AI model (summaries & translation)" shows 7.6 GB, but the product also needs two more model packs (gemma4:e4b and translategemma:4b) and an Ollama runtime that are not listed anywhere on this screen (`native_activation.rs:35-41`, `native_pack_staging.rs:99-104`). The "9.7 GB" total is not the whole model footprint (the uninstall notice says "about 21 GB", `nsis-hooks-bootstrap.nsh:2209`).
- [HELP-52] SERIOUS: "Untick it to skip the download" (`acquisition-progress.ts:538-540`) may not be true. `start_acquisition` takes no arguments and `production_catalog` returns all six ids, so the backend downloads the large engine and GPU library even when unticked, and the sequential order puts them before the local AI model (`main.rs:3304-3324,3740-3747`; `acquisition_catalog.rs:555-600,681-688`). The screen only hides those rows. Marked UNVERIFIED at runtime; needs a real-box test.
- [HELP-53] "Database & messaging services" (`components-catalog.ts:69`) still says "messaging", but the messaging server (NATS) was removed from the product (`install_layout.py:19-21`; `main.rs:5512-5515`). Suggest "Database service".
- [HELP-54] "CivicCast application runtime" and "Database & messaging services" are described as downloads but are staged by setup first; the screen does not say they will normally show "Found locally — verified".
- [HELP-55] "(optional)" rows give sizes in GB only; no mention that downloads use the internet connection continuously for a long time (7.6 GB model).

### installer-gui-downloading

- [HELP-56] SERIOUS: `acquisition-progress.ts:224-227` and `AcquisitionFlow.tsx:1015` show "Stalled — retrying" but no retry exists in the download engine (no loop, 6-hour timeout), so the row can sit forever; the only real remedy is "Stop downloading" then "Resume download". Suggest "No data for 10 seconds. If this continues, choose Stop downloading, then Resume download."
- [HELP-57] "Open installer log" opens `install-progress.log` (the elevated setup transcript) first; a download failure's cause is not written there. The text "send that log to support" therefore points at a file that probably does not contain the failure (no GUI download log writer was found in `main.rs`; the engine detail is kept only in `installer-state.json`). Missing: where the GUI's own failure details are kept (`detail` field is "never shown", `types.ts:139`).
- [HELP-58] "Keep CivicCast Installer open" (`:768`) — the window is titled "CivicCast (Native) Setup" (`tauri.native.conf.json`); name mismatch.
- [HELP-59] "This is our problem, not yours." (source_not_found / resume_invalid) offers only Retry, but a missing file at the release tag cannot be fixed by retry; no contact route is given.
- [HELP-60] Default download source tag `native-beta-1.0.0-beta.1-rc1` is not the product version `1.0.0-beta.10` (`main.rs:35`); packs are verified against the current version (`acquisition_catalog.rs:327-338`), so a fresh download of the optional GPU pack may fail with "didn't match its signature". UNVERIFIED which assets exist at that tag.
- [HELP-61] Times, speeds use "MB/s" without explanation; "Estimating…" has no end condition stated.

### installer-gui-setup-wizard

- [HELP-62] SERIOUS: `App.tsx:674` "Download, install, create the first admin, then open the dashboard without terminal commands." — the installer never creates an admin (no code does; search for admin creation found only this sentence). First-admin creation happens in the operator console or by recovery code (not in this inventory). Suggest "Install CivicCast, then open the operator console to set up the first administrator."
- [HELP-63] `App.tsx:677` "Report a beta issue" opens GitHub issue creation, which requires a GitHub account; the resident portal's link and the operator manual have a no-account path (`portal-public/src/App.tsx:35`). Inconsistent; offer the same no-account route.
- [HELP-64] "CivicCast Installer" is the heading but the window and app are "CivicCast (Native) Setup"/"CivicCast (Native)"; and "Platform: windows-native" is shown raw (`App.tsx:696`). Suggest hiding the raw value.
- [HELP-65] State word "Partial", "Needs setup", "Needs input", "Credential gated", "Hardware required" are developer states; none are produced by the shipping native flow except Ready/Needs setup/In progress/Error/Loading.
- [HELP-66] "Show uninstall instructions" shows one line in the status area, easy to miss, and does not list steps. See `installer-uninstall.md` for what Windows uninstall actually does.
- [HELP-67] "Ready" can show while captions and AI models are absent (App.tsx comment at lines 794-802: a silent install reaches Ready without them); nothing on the Ready screen says models may be missing.
- [HELP-68] "Resume after reboot" panel text is a developer message (`progress.message`) shown verbatim.

### installer-install-layout

- [HELP-102] The product opens firewall port 8000 (so other computers can reach staff and resident pages) but, as read, binds to 127.0.0.1 only. A manual that tells IT staff "other PCs on the network can open the portal" would be wrong unless the bind is changed elsewhere. Needs a coder answer, then say plainly in the manual.
- [HELP-103] No on-screen text anywhere gives the folder list above; an operator who must back up recordings and the database has no setup text saying "back up C:\ProgramData\CivicCast".
- [HELP-104] The Start Menu shortcuts are `.url` files pointing at localhost; if the service is stopped they show a browser error, and no text tells the operator to start the service.

### installer-nsis-activation-selftest

- [HELP-87] SERIOUS: the exit-67 dialog says the failed self-test "is named in the installer log at install-progress.log", but activation runs with `nsExec::ExecToLog` (`:1459,1467`): the child's error line goes to the setup details pane only; install-progress.log receives just "step d4-activate-station: returned 67" (`:1475`). No "child reported" line is written (compare stage-packs, `:861`). A support person following the dialog will not find the cause. Needs a coder fix: capture and log the child's output.
- [HELP-88] SERIOUS: exit 67 is also returned for "not enough free disk space" and extraction failures (`native_activation.rs:870-879,947`), yet the dialog insists "This is NOT a missing-files problem" and blames a self-test. An operator with a full drive is told the wrong thing.
- [HELP-89] The details pane shows only "Activating the CivicCast (Native) station (K1)..." for what can be many minutes of extraction plus AI test runs. No progress, no "this takes a long time" warning. "(K1)" is an internal ticket id.
- [HELP-90] The activation step needs the full kit or a prior pack cache (HELP-77); the dialog for 66 tells the operator to copy "the full CivicCast kit folder" but the kit's folder layout is not described anywhere in the setup.
- [HELP-91] "self-test" is not explained (what is tested, that Spanish translation is exercised, that CPU is used so a slow computer needs longer).

### installer-nsis-packs-and-verify

- [HELP-77] SERIOUS: with only setup.exe (no kit `packs` folder) setup stops at step 2 with exit 110, yet the Windows setup page promises components download later (HELP-73). The manual cannot honestly describe a download-only install. Needs owner confirmation (the code comments call it a known limitation, `:2184-2209`).
- [HELP-78] The dialog does not name the missing packs or the folder path of setup.exe; it points to a log. Add "Missing: native-ollama-runtime" to the dialog (the text is already captured at `:861`).
- [HELP-79] "D2" (`:922,938`) appears in the details pane; meaningless to operators. Suggest "Re-checking that the copied files match their signatures."
- [HELP-80] "Re-download the installer/pack" gives no download address.
- [HELP-81] No progress is shown during extraction of tens of GB; the details pane is quiet for minutes (the log shows a 107 s gap, `:967-970`).

### installer-nsis-service-finish

- [HELP-92] Dialog 125 says "database schema" and "staff pages return errors"; it names no action. Suggest: "The station started but is not answering. Open C:\ProgramData\CivicCast\logs\control_plane.log and send the last 50 lines to support, then run setup again."
- [HELP-93] Dialog 126 sends the operator to "the Windows Application event log" without saying how to open it (Event Viewer > Windows Logs > Application).
- [HELP-94] The success line (`:1665`) mentions "D2-verified", "D3" and "D4" and does not say what to do next: no line tells the operator to open the console shortcut or that the first-run wizard will follow. UNVERIFIED: what the Tauri finish page says.
- [HELP-95] Dialog 118/119 give no detail at all ("See the installer log for the exact error") and name no log path, unlike the other dialogs.
- [HELP-96] "Windows Defender Firewall" rule name "CivicCast (Native) Portal/API (TCP 8000)" is not mentioned in any dialog; an IT person adding a rule by hand cannot learn the port from setup.

### installer-nsis-setup-wizard

- [HELP-73] SERIOUS: the folder page text (`:199`) says captions and AI models download after Setup finishes, but the install phase itself needs the kit's station folder and model packs and fails with exit 123 or 110 without them (`:1441-1445`, `:2184-2209`; see `installer-nsis-packs-and-verify.md`, `installer-nsis-activation-selftest.md`). The text and the "Space required" figure both understate the footprint (about 5.1 GiB declared, more than 21 GB of packs extracted plus 2 GB working room, `native_activation.rs:841`).
- [HELP-74] Error dialogs say "contact support with C:\ProgramData\CivicCast\install-progress.log" but no support contact is given in any dialog (`:657,662,667`).
- [HELP-75] Dialog text uses "bootstrap", "supervisor service", "service registration", "upgrade identity": jargon for a PEG station manager. Suggest a plain first sentence ("Setup could not stop the running CivicCast service, so it did not change anything.").
- [HELP-76] No page tells the operator that setup can take a long time (copying and testing tens of GB, with AI test runs); see activation file.

### installer-nsis-upgrade-database

- [HELP-82] The 124 dialog gives raw `sc` commands (`:1255`), for a case where setup could not stop the service. A PEG station manager needs a copy-paste recipe plus where to find "Services"; the existing text is the only recipe and is hidden inside a rare branch.
- [HELP-83] "cutover-to-native" and "ActiveRuntime" (127, 135) are internal; no plain explanation that CivicCast has an older WSL-based edition that must be removed first.
- [HELP-84] Several dialogs say "database/messaging" (`:1334`) though messaging was removed; stale.
- [HELP-85] "D3", "D4", "journal", "owner-run-id" appear in the details pane (`:1136,1305`).
- [HELP-86] No dialog says how long the upgrade backup and migration will take or that the database is backed up (UNVERIFIED where the backup is stored).

### installer-uninstall

- [HELP-97] SERIOUS: the uninstall notice tells the operator that after uninstalling, setup.exe alone "cannot download" the models. The product's wizard text says components download. The two statements contradict each other for the operator (HELP-73/77); the notice is the only honest one and appears only at the moment of deletion.
- [HELP-98] "ActiveRuntime", "WSL product", "ownership" in the Yes/No box (`:1850`): the manual must explain the older WSL-based edition, or the box is unanswerable for most users.
- [HELP-99] "services.msc, or 'sc stop CivicCastSupervisor'" (`:1986,2047`): no instruction for opening Services, no mention that the service display name is "CivicCast Native Supervisor".
- [HELP-100] The dialog text still says "database/messaging processes" (`:2047`); stale (messaging is gone).
- [HELP-101] No dialog lists what is kept (recordings under `data\egress` and `data\uploads`, the database) or says how to remove it fully; the operator who wants a clean machine has no instructions.

### live

- [HELP-01] `LiveRoomScreen.tsx:1431` — "Residents watching the live stream lose it immediately." — The handler only moves the session to Ending (`router.py:736-773`, `store.py:391-407`); it queues no egress command. Residents' status falls through to the channel's egress state (`router.py:310-321`), so the stream may continue. — Say what really happens: "This marks the meeting as ended and starts saving the recording. It does not stop the channel feed; use Channels for that." (confirm with owner/engineer first).
- [HELP-02] `LiveRoomScreen.tsx:64, 1135-1140, 1431` — fixed session id `council-live-room`; dialog promises "start a new live session to go live again". A second create returns 409 "LiveSession already exists: council-live-room" (`router.py:529-535`) and nothing in the screen lists or reopens an existing session. — Either the product needs a new id per meeting (coder) or help must say "one live session per station until IT resets it".
- [HELP-03] `LiveRoomScreen.tsx:1025` — the session is held only in page memory (`useState(null)`); nothing fetches an existing session on load. After a browser refresh during a meeting the buttons return to "Create live session" and "End Live Stream" is disabled. — Tell operators not to refresh while on air; log as a product defect for the coder.
- [HELP-04] `LiveRoomScreen.tsx:110-113` — every failed action (403 role error, 409 pre-flight block, 409 duplicate) is followed by "Next step. Confirm the CivicCast server is running and connected to its database, then refresh this screen." — Wrong advice for most failures, and "refresh" is exactly what loses the session (HELP-03). — Use "Next step" only for load errors; show the server's own next step for action errors.
- [HELP-05] `LiveRoomScreen.tsx:959-961` — "Run pre-flight to populate the nine-check contract." — Jargon. — "Press Run pre-flight to check the camera, recording drive, internet and your confirmation."
- [HELP-06] `LiveRoomScreen.tsx:1385, 1404` — "Start pre-flight" and "Run pre-flight" read as the same action; the first runs nothing. — Rename "Start pre-flight" to "Begin checklist" or merge; explain order in a one-line note above the buttons.
- [HELP-07] `types\live.ts:98` — "Check the confirmation box below, then select Run pre-flight again." — The box is in the right-hand Session controls, above the checklist, not below it. — "Tick the confirmation box in Session controls".
- [HELP-08] `LiveRoomScreen.tsx:318-322, 1292` — heading "Source switcher" and text about arrow keys. — Selecting a card chooses what pre-flight tests; it switches nothing on air. — Rename "Choose meeting source".
- [HELP-09] `LiveRoomScreen.tsx:907-909, 922` — "On-air preview" with "CivicCast only shows source media here after server-side verification." — No code path ever shows video; the panel is a permanent placeholder. — Remove the panel or label it "No video preview in this version".
- [HELP-10] `types\live.ts:70-71` — "Network reachable" / "Recording storage" — The network check needs internet (1.1.1.1 and 8.8.8.8 on 443) so an offline station cannot go on air; the storage check needs 50 GiB free on the CivicCast data drive, not the recording target drive. — Add both facts to the row text and the manual.
- [HELP-11] `LiveRoomScreen.tsx:130-134, 1266` — "Safe to broadcast" banner is computed from the last System Health rehearsal, not from the pre-flight run on this page (`client.ts:728` sends no flags; `installer\service.py:3668-3674`). It can say "Check before meeting" while pre-flight says "Pre-flight ready". — Add "This banner reflects the last System Health rehearsal" under the title; also the text says "System Health" while the nav item is "Readiness".
- [HELP-12] `LiveRoomScreen.tsx:273-281` — "Retry finalization" is shown to every role but the backend allows only meeting_operator (`router.py:824`). — Gate or explain.

### medialifecycle

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

### missingmedia

- [HELP-01] `MissingMediaScreen.tsx:62-65` "Every asset scheduled in the coming week is validated or recorded and ready for air." is too strong. The check only covers schedule items still in draft state `scheduled`; items already committed to air (`published`, which is what actually airs, `schedule/router.py:211-217`) are not checked (`media_lifecycle_worker.py:849-855`), and a file deleted in the last hour is not yet flagged. Fix: "No draft schedule items for the next 7 days have a media problem. Items already committed to air are not checked here."
- [HELP-02] `:145-148` hard-codes "next 7 days" although the horizon is configurable; uses "source asset", "validated", "recorded" and "air check" without explanation. Fix: "Meetings on the Schedule in the next 7 days whose video is not ready to play. Fix these before the meeting."
- [HELP-03] `:105` every card says "🔴 Not ready" regardless of reason; `:96` shows raw codes (`pending_ingest`, `rejected`). Fix: use the Assets screen words (Validating, Rejected, Missing file) and say what to do per reason (upload a replacement / wait / re-link).
- [HELP-04] No sentence explains how to fix a card: the page offers only "Open asset", and the asset detail page's fixes (Replace source file, Package) need publish_operator/setup_admin, which a meeting_operator or support_admin (who may open this page) does not hold. Add "Ask a publish operator to replace the file."
- [HELP-05] `:141` label "Media Lifecycle" sits above the page, but the nav group is "Review Records" and the sibling page is "Media Lifecycle Settings"; first-time users may think this is a settings page. Rename label to "Schedule check".
- [HELP-06] `:40` error "Request failed: …" and the 403 role sentence are shown raw; there is no explanation that the page is limited to certain roles. Add one line under the heading naming the roles.

### paywall

- [HELP-01] PaywallScreen.tsx:352 and 596-598 — Save sends `null` when the secret box is blank, and the box is ALWAYS blank after a reload because the server hides the secret; so changing any other setting (a tier, the switch) and clicking Save silently deletes the stored signing secret. Magic links and Stripe webhook checks then stop working — fix: send "leave unchanged" when the box was not touched, and show "A secret is saved" from `signing_secret_present`.
- [HELP-02] PaywallScreen.tsx:604 and 655 — the secret is described as "base64 secret; rotate via Generate" and the warning mentions "update Stripe's webhook secret", but the screen never says where to find the Stripe webhook secret, and Stripe makes its own `whsec_` value for each webhook endpoint; the code verifies Stripe signatures with THIS field (service.py:503-535), so Generate is probably the wrong value to use for Stripe (UNVERIFIED against Stripe docs) — fix: say "paste the Signing secret from your Stripe webhook endpoint" or split into two fields.
- [HELP-03] PaywallScreen.tsx:409-414 — "every asset is public" and "Tier-based gating active" imply content is protected once ON; the code found does not block media at the server, and the public site's checkout and tiers routes are not present in the server package, and magic-link emails are not sent — the page promises a working paywall; the feature looks unfinished — fix: add a visible "Beta: not ready for live use" line or hold the sidebar entry back until the delivery path works.
- [HELP-04] PaywallScreen.tsx:413, 576, 597, 851, 1147 — "PAN", "DC-4", "DC-1", "HMAC", "Scope kind", "Tier ID (slug)", "catch-all", "comp" are jargon or internal requirement codes — fix: "no card numbers are ever stored here", remove DC codes, "Pass applies to: one recording / one series / everything", "Free pass (comp)".
- [HELP-05] PaywallScreen.tsx:787, 1033 — "Save with the enable toggle on to manage tiers and grants." but the sections unlock as soon as the box is ticked (before saving); and the grants form posts to the server immediately, regardless of whether the paywall is saved ON — fix: reword to "Tick Enable paywall to edit tiers and grants."
- [HELP-06] PaywallScreen.tsx:1029-1032 — "Server-side grant history is a follow-up." is a developer note; staff cannot see, search or revoke passes issued earlier, and the page does not say so beyond that line — fix: "Passes you issued before today are not listed here."
- [HELP-07] PaywallScreen.tsx:591-592 — the "mock (contract tests / lab)" option is selectable on a live station with no warning — fix: hide `mock` unless the station is in lab mode.
- [HELP-08] PaywallScreen.tsx:889 — "Stripe price IDs start with price_." is the only guidance; it never says the price must already exist in Stripe, which currency/tax rules apply, or that the station never creates prices (that is only in a code comment, 10-14) — fix: add one sentence "Create your price in the Stripe dashboard, then paste its id here."
- [HELP-09] PaywallScreen.tsx:713-716 — Delete config says gating is disabled until re-created but does not say whether existing subscribers and passes are kept (UNVERIFIED) — fix: state the result.
- [HELP-10] PaywallScreen.tsx:202-205, 139 — code comments claim a 404 maps to an empty form, but the server now returns 200 (router.py:276); harmless to users, noted so the manual does not describe a "no config" error.

### playback

- [HELP-01] lines 490-499 ("Access tier: Public / Authenticated / Invite only") and the empty-state text lines 635 — the screen reads as if choosing "Invite only" stops uninvited people watching. Code search of `civiccast/` shows `evaluate`/`effective_policy` consumers only in: the podcast RSS route, the app-catalog builder (it copies the tier into catalog metadata as `entitlement_required`), and the public `/evaluate` endpoint. The resident web player (`apps/portal-public/src/HlsPlayer.tsx`) and the media/HLS route (`stream/media_router.py`) never call it; no TypeScript, Swift or Kotlin client in the repo calls `/api/public/playback-policy`. So the video itself is not blocked by this setting, and the decision log stays empty because nothing calls `/evaluate` (except podcast-feed checks). Fix before documenting as a feature: either wire enforcement or relabel the screen "Planned access rules (not yet enforced on video)". The manual must not promise resident sign-in gating.
- [HELP-02] lines 501-512 "Invite group", "OIDC provider" — no explanation what these are or where the groups/providers are created. Viewer accounts and invite groups exist only inside signed tokens (`entitlements.py:352-370`); there is no screen to create them or issue a token. Add: "Invite group: a short name (lowercase, no spaces) that you put into residents' sign-in tokens."
- [HELP-03] line 434-441 Target ID — default `government` is unexplained, and a typo silently creates a new policy for a channel that does not exist (the server accepts any slug). Use a drop-down of real channels/assets and say "Use the channel or recording ID shown on Channels / Assets."
- [HELP-04] lines 517-545 — "Public-record asset" and "Public archive complete" are jargon and clicking either silently flips Access tier to Public and clears Authenticated RSS. Add helper text: "Public records can never be restricted. Ticking this sets access to Public."
- [HELP-05] lines 555-575 — "Preroll" is not defined; say "A short card or clip shown to residents before the recording starts. Prerolls play for viewers only; they are never added to archive copies." Also "Skip after seconds" has no "blank = cannot skip" note (blank sends null, line 129-131).
- [HELP-06] lines 634-636 empty-state sentence "Decisions appear as soon as residents start watching" — see HELP-01; likely false for video.
- [HELP-07] lines 322-345 field labels "Duration seconds", "Skip after seconds", "Asset URL" with placeholder `/media/preroll/station-card.png` — no statement of where the file must live or that a relative path is read by the player; UNVERIFIED that any player loads prerolls (see below).
- [HELP-08] line 449 "Save policy" has no success message; the only sign is "Updated {time}" changing (line 484). Add a "Saved" notice.
- [HELP-09] lines 453-461 — a 403 for roles without publish_operator/support_admin is shown as raw server text after the person has typed everything; hide or disable Save and say "Only Publish operators and Support admins can change playback rules" up front.

### public-agenda

- [HELP-33] No text explains that agenda items are clickable or that "—" means "no video time recorded for this item" (290-294). Suggest a one-line hint above the list: "Select an item to jump to that part of the video."
- [HELP-34] Agenda times come from operator timestamps; an item with a time beyond the video length lands on the last frame (clamped, `HlsPlayer.tsx:72`) with no message.
- [HELP-35] On a load failure the sidebar says "could not be loaded right now" with no retry.

### public-contribute

- [HELP-15] `HomeScreen.tsx:704-705` "Receipt" and "Status token" — two unexplained codes; nothing says "write these down, you will need both to check status; they are not saved on this page". Suggest an explanatory line and a Copy button.
- [HELP-16] No text states accepted file types, maximum size, expected length or the review turnaround; `accept="video/*"` only. Missing.
- [HELP-17] No explicit agreement checkbox; the form records acceptance silently using the producer name (282-286). For a legal agreement that is surprising to the resident; flag for owner/legal.
- [HELP-18] `HomeScreen.tsx:749` the state text can read like `under review` or a raw code; replace with a fixed plain-English map once the state list is known.
- [HELP-19] Whether the resident receives an email at the address entered is not stated (the form passes it as a notification target, 288-293); UNVERIFIED that mail is sent.

### public-home

- [HELP-06] `HomeScreen.tsx:446` "Ask the station to turn on HLS web output to watch it here." — jargon ("HLS web output") on a public page; suggest "This meeting is airing on the cable channel but is not available online right now."
- [HELP-07] `HomeScreen.tsx:462,486` Channel row shows the raw id (`government`, `public`) and "Coming up" shows "`<channel_id> / 90 min`"; use the channel display name (the Schedule page already does, `ChannelGuideScreen.tsx:124`).
- [HELP-08] `HomeScreen.tsx:59-61` the emergency notice appears only if the visitor adds `?emergency=1`; a resident will never see it by normal browsing. Wrong/missing for an emergency feature; needs owner decision on how the notice is triggered (UNVERIFIED whether another page or the idle page carries it).
- [HELP-09] `HomeScreen.tsx:483` coming-up card falls back to the raw `asset_id` when the title is missing.
- [HELP-10] No sentence tells residents that live video needs a current browser, or what to do if the video does not start.

### public-paywall

- [HELP-36] `PaywallGate.tsx:545` "New here?" then a Subscribe button, with the email taken from the sign-in field above; a first-time resident does not know that the "Sign in by email" box is also where to type the email for Subscribe. Suggest a separate "Your email" field or a hint under the button.
- [HELP-37] `PaywallGate.tsx:298` "Enter your email above before subscribing." is the only guidance for that dependency.
- [HELP-38] "tier" appears in `tier_required` text (57): "A paid tier is required" — jargon; suggest "A paid plan is required."
- [HELP-39] A station that has not set up payments still shows the gate with "Contact them" but gives no contact details; the portal has no station contact info anywhere. Missing.
- [HELP-40] After checkout, nothing on this page explains what happens next (UNVERIFIED).

### public-player-captions

- [HELP-28] `HlsPlayer.tsx:227` "does not support HLS playback" — jargon; suggest "This browser cannot play the video. Try the latest Chrome, Edge, Firefox or Safari."
- [HELP-29] `HlsPlayer.tsx:321` "The stream may be unavailable." — for a recording this wording is wrong (it is not a stream) and no next step is given; suggest "The video could not be played. Please reload the page; if it still fails, contact the station."
- [HELP-30] No message appears when a video has no captions, so a resident who needs captions cannot tell "none exist" from "not loaded yet". Missing line: "Captions are not available for this video."
- [HELP-31] The caption bar says only "Captions" with raw track names; no help that Spanish or other languages may be machine-translated (UNVERIFIED if they are).
- [HELP-32] There is no Retry on player errors (text says "try again").

### public-recordings

- [HELP-20] `RecordingsScreen.tsx:396` says "Clear the search or facets" but there is no clear button, and "facets" is jargon; suggest "Try different words or choose All years / All bodies" and add a "Clear all" control.
- [HELP-21] The search only looks at title and description (88-89), not the meeting transcript, agenda item text or captions. The placeholder says so ("Search by title or description") but the intro line says "Search and replay every published meeting recording"; docs must not promise transcript search.
- [HELP-22] Cards show "Recording description not posted." for untitled-description assets (HomeScreen.tsx:769) — wording suggests an error; suggest hiding the line.
- [HELP-23] Reduced-search note (363-365) uses an em dash and "reduced-search mode"; suggest "Search is limited right now. Some filters may show fewer results. Please try again soon."
- [HELP-24] Search is case-insensitive substring only; no mention of this.

### public-schedule

- [HELP-41] Entries are not links; a resident cannot click "On now" to watch it, nor see which channel number on the cable system it is. Missing cross-link to Home's player; the page does not say whether the channel is also online.
- [HELP-42] If the server error text is raw (e.g. an HTTP status), it is spliced into the sentence (147); suggest hiding it.
- [HELP-43] Day headings and times use browser locale; nothing states the station's own time zone, which matters when residents compare with the posted cable schedule.
- [HELP-44] Home's "Coming up" (premieres, `/api/public/schedule/coming-up`) and this guide (program log) are two different lists with no explanation of the difference.

### public-shell

- [HELP-01] `src/App.tsx:139` "Report a beta issue" — a resident is sent to `/operator/#/help#report-without-github`, the manual inside the staff console, with no explanation — missing/confusing: residents see a staff product and a "GitHub account" section. Suggest a plain resident page ("Tell the station about a problem": email/phone from station settings) or label it "Report a problem with this page (opens the station help page)".
- [HELP-02] `App.tsx:143` "Do not include passwords, recovery codes, staff tokens, or private meeting material in reports." — jargon aimed at staff, shown to the public; suggest "Please do not put passwords or private information in your report."
- [HELP-03] `App.tsx:116` blurb mentions "premieres" and "resident archive" — station jargon; suggest "Watch the meeting that is on now, see what is coming up, and replay past meetings."
- [HELP-04] No page in the portal explains captions, languages, agenda use, or how to subscribe; no Help link in the header. Missing: add a short "How to use this site" page.
- [HELP-05] `analytics.ts` collects playback counts but the portal has no privacy statement visible to residents. Missing: one-line "We count views without recording who you are" (confirm wording with owner).

### public-subscribe

- [HELP-11] `HomeScreen.tsx:572` "Test one-click unsubscribe" — developer wording shown to residents after signup; suggest "Unsubscribe from this list" or remove (the token is only needed for testing).
- [HELP-12] `HomeScreen.tsx:224,581,587` subscription target and feed URLs are hard-coded to a channel named `government`, while the schedule's default channel is `public` (`router.ts:53`) and contributions use channel `public` (`HomeScreen.tsx:273`). If a station has no channel called `government`, the feeds and signup point at nothing. Needs owner/coder check; docs must not promise a specific feed URL until confirmed.
- [HELP-13] `HomeScreen.tsx:531-534` does not say what "this channel" is or how often mail is sent, nor that the first email is a confirmation request that must be clicked. Suggest adding "You will get one email asking you to confirm."
- [HELP-14] "RSS", "double opt-in", "tracking pixels" (592-594) are jargon for residents; suggest "We will not track whether you open our emails. You can unsubscribe in one click."

### public-watch

- [HELP-25] `WatchScreen.tsx:43` "Recording not found" depends on the server message containing the words "not found"; if the server text differs the resident gets the generic error with a Retry that cannot succeed. UNVERIFIED backend text (`civiccast/vod/router.py` not read). Needs coder check.
- [HELP-26] No on-page help for how to turn captions on or use agenda items; the caption bar appears only when the video has caption tracks and says nothing when it has none.
- [HELP-27] Share link uses the page's own address; on a station reached by an internal or temporary address, copied links will not work for outside residents. Not stated anywhere.

### publish

- [HELP-01] `publish/service.py:543-589,820-829` + `PublishDashboardScreen.tsx:465-473` — approving a second time rebuilds the run from scratch, so any surface not ticked in that approval goes back to "Not run yet". Verified by calling `approve_publish` in memory (portal-only, then internet-archive-only): result "portal pending, internet-archive succeeded", dashboard state "draft", `canonical_public False`, while the recording is still public. The screen's own text promises "Archive and reach surfaces ... are opt-in: tick each one you mean to publish this time" (line 677), which invites exactly this. Fix (code): merge with the previous run. Until then manual must say "tick everything you want in one approval" and the paragraph must not say "this time".
- [HELP-02] lines 627-631 and `service.py:973-975` — card says "IA and local NAS verified" and the tile/state say "Archive verified" even when every archive surface was a simulated mock or an override. Row-level warning exists (lines 209-218) but the headline does not. Suggested: "Archive copies recorded (simulated - not a real archive)" when any required surface has `simulated` or is overridden.
- [HELP-03] line 203 and `syndicate/models.py:22-37` — YouTube rows show a success message from the mock provider with no simulated warning. Add the same "Simulated" note, and say in plain words "Nothing was sent to YouTube".
- [HELP-04] `SRC/components/shell/Sidebar.tsx:161` section summary "Resident portal, archives, and notifications" and line 66-67 — notifications are not sent in this release. Change to "Resident portal, archives, and outside services".
- [HELP-05] line 668-692 and confirm body line 744-748 — nothing tells the operator that publishing also announces to the fediverse when Federation is on, or that Internet Archive/YouTube uploads cannot be undone from CivicCast. Add one sentence to the dialog when those surfaces are ticked: "This cannot be taken back from CivicCast."
- [HELP-06] line 733-737 — "Nothing else was published" is not true when some surfaces succeeded before the error. Say "Surfaces that finished before the problem stay published; check each row."
- [HELP-07] lines 197, 203 — raw words "canonical / archive / reach / record / audience", "pending/approved/overridden", "Required" badge with no definition. Replace with "Public portal", "Archive copy", "Outside service", "Cable handoff"; explain Required = "needed before a public-record meeting counts as archived".
- [HELP-08] lines 156-160 — a "Cable file package" row that ended "not set up (optional)" has no checkbox or Retry afterwards, so after the folder is configured there is no way to run it for that recording. Add Retry for `not_configured`.
- [HELP-09] lines 33-38 vs `status-language.ts:217` — filter chip text "Reaching fewer places than planned" is long and the row/ card pill uses the same words; the metric tile says "Degraded". Use one phrase.
- [HELP-10] lines 594-595 — operator shown in audit is always "Operator dashboard". Manual must not promise per-person audit for Publish until fixed.
- [HELP-11] line 749 confirm button "Approve and Publish" shows even if only archive surfaces are selected; the body handles it, but the title still says "to residents". Minor.
- [HELP-12] `SRC/screens/PublishDashboardScreen.tsx:780` "Open deployment settings, connect the CivicCast database" — there is no screen named "deployment settings"; backend says "Open Setup and choose Prepare storage". Use the backend wording.

### recording

- [HELP-01] `RecordingScreen.tsx:163-168,1874-1924` — `Stop` is offered on a `scheduled` job, the server refuses (409) and the screen swallows the error, so the click appears to do nothing. — show Stop only for arming/recording/finalizing; render stop errors. To remove a not-yet-started recording, the user should untick `Enabled` on the schedule.
- [HELP-02] `RecordingScreen.tsx:1295,1420,1005` — `Start (UTC)` / `Time (HH:MM UTC)` use UTC inputs while browsers show datetime-local in local time; the weekday boxes are also UTC days. A 7 PM Monday evening meeting in the Americas is already Tuesday in UTC. The "In your local time" echo helps but the weekday checkboxes get no echo. — label days "UTC day" or convert; manual must explain with an example.
- [HELP-03] `RecordingScreen.tsx:370-373` — creating a schedule gives no confirmation and keeps the form filled; re-clicking yields a confusing 409. — clear form and toast "Schedule saved."
- [HELP-04] `RecordingScreen.tsx:584,1806` — "use Record Now for a one-off capture" / "press Record Now to make the first one" — `Record now` only exists inside a saved schedule's row. — "Create a schedule below; then its Record now button starts a capture immediately."
- [HELP-05] `RecordingScreen.tsx:1546-1547` — "Contact your station admin for the full list of available presets." — a clerk cannot discover valid values; free-text. — dropdown of real presets (the code comment at `:122-126` already says so).
- [HELP-06] `RecordingScreen.tsx:1583` — `Target series (optional)` — unexplained jargon. — say what it does (UNVERIFIED, see below).
- [HELP-07] `RecordingScreen.tsx:229` — job state badges show raw words (`arming`, `finalizing`) and no hover explanation. — plain-language labels: "Getting ready", "Recording", "Saving file", "Done", "Failed", "Skipped".
- [HELP-08] `RecordingScreen.tsx:36-37,266-269` — the "Forbidden" message calls the screen an "operator / setup-admin / support-admin surface"; `publish_operator`/`records_clerk` never see the nav item. Fine, but wording is jargon. — "Scheduled recording needs the meeting operator, setup admin, or support admin role."
- [HELP-09] `RecordingScreen.tsx:663-703` — `Delete` confirm gives no description of what happens to planned jobs and earlier recordings. — "Past recordings stay. Future recordings from this schedule will be cancelled." (once verified).
- [HELP-10] Nav says `Recording`, page heading `Scheduled recording`, section `Recordings` is the jobs table and `Schedules` the plans; the older word `jobs` still shows in aria labels (`Stop job <id>`).

### remotecontribution

- [HELP-01] `RemoteContributionScreen.tsx:650` button "On air" — to a clerk this reads as "show this guest's picture". In code it also switches the whole channel to its live source (`BE\app.py:3094-3104`), with no confirmation, recorded under "remote-contribution". — Help and the button need to say so; suggest the coder add a confirm and the real operator name.
- [HELP-02] `RemoteContributionScreen.tsx:358, 667` — "Every guest ... is disconnected immediately" / "video/audio cuts from the broadcast" — `close_room` and `drop_guest` only update records (`service.py:207-216, 381-395`); no VDO.Ninja or channel call was found. Whether guests really lose their connection depends on something outside this code. — Verify in the lab before the manual repeats it.
- [HELP-03] `RemoteContributionScreen.tsx:57` — setup_admin is allowed in but the backend room list/detail require meeting_operator or support_admin (`router.py:60`), so a setup admin can create a room and then sees "Could not load rooms." — Align or mention.
- [HELP-04] `RemoteContributionScreen.tsx:503-510` — free-text "Channel id" with example "gov-ch-1"; the station's default channel id is `government` (`LiveRoomScreen.tsx:62`). A typo makes "On air" fail later. — Use a dropdown of real channels, or say "copy the id from Channels".
- [HELP-05] `RemoteContributionScreen.tsx:373` — "Director view (embed in your switcher)" — jargon; the director link is where the operator watches and controls the VDO.Ninja room. — Explain "Director view: the page you keep open to see and arrange the guests".
- [HELP-06] `RemoteContributionScreen.tsx:282-285, 773-778` — "compositor", "wpesrc", "coturn", "TURN", "ICE" (771) unexplained; first-time setup is not possible from this screen. — Provide a plain "what has to be set up first" help section with a link to IT guide.
- [HELP-07] `RemoteContributionScreen.tsx:547` — "single-use browser link" omits that it expires in 4 hours and that public-comment guests must accept terms first (`service.py:57, 272-280`). — Add both.
- [HELP-08] `RemoteContributionScreen.tsx:655-658` — "Mute" / "Off air" imply audio and picture change; code only changes the record (UNVERIFIED-02). — Confirm behaviour with the engineer.

### reports

- [HELP-01] `reports-format.ts:72-77` "Define it in Setup → Custom Fields" — Custom Fields is a Setup item restricted to `setup_admin` (`Sidebar.tsx:113`), but this screen is for `support_admin` only, so the reader usually cannot open it. Add "(ask your Setup admin)" or allow both roles.
- [HELP-02] lines 614-620 — the lede is dense: "half-open ([from, to))" is jargon. Replace with "Pick the first day and the day AFTER the last day you want. To see one day, choose that day and the next day." The UTC offset warning belongs next to the date boxes, not in a paragraph (a Mountain station is 6-7 hours behind UTC, so an evening meeting can fall on the next UTC day).
- [HELP-03] lines 413-417, 457-462 tables show raw `asset_id` values and `channel_id`; recording titles are not shown, so a clerk cannot recognise "Council - July 8". Add a Title column (data exists on assets).
- [HELP-04] line 465 "Verified" yes/no has no definition. Say "Verified = the station's playout system confirmed this actually aired" in a tooltip or note.
- [HELP-05] line 461 `Source` shows `program` / `filler` / `live` / `slate` / `spot` raw; define: filler = community bulletin board, slate = fallback card shown when the feed failed. `spot` (underwriting) never appears (see Underwriting screen).
- [HELP-06] lines 623-628 / 388-392 empty-state text blames "no content has aired" when the real causes can also be a wrong Channel, a range in UTC, or the as-run log not being written (database not ready). Add those three checks.
- [HELP-07] Hours tab has no download buttons while the other two do (lines 708-732); say so or add them.
- [HELP-08] Field key placeholder `category` and default value `category` (lines 236, 527): if no field named category exists the first view of the Hours tab shows the error box immediately. Pre-check or explain.
- [HELP-09] The text "franchise-compliance reports" assumes the reader knows the term "franchise". Define: "Reports a cable franchise or city may ask for: what aired, when, for how long."
- [HELP-10] Public as-run endpoint (`/api/public/reports/as-run`, no sign-in) is not mentioned anywhere on this screen or the nav; operators should be told the air log is publicly readable (category and verified are omitted).

### review

- [HELP-01] `ReviewQueueScreen.tsx:362-367` **Approve ignores text typed in "Reviewed text" unless Save edit was clicked first**; the card does not say so and there is no warning when the box differs from the saved text. A volunteer who corrects a word and clicks Approve publishes the old text. Fix: Approve should send the edited text (or disable Approve while the box has unsaved changes and say "Save edit first").
- [HELP-02] `:509-513` The page never explains that captions reach the video only after **every** cue (English, then Spanish) is approved, edited or rejected, nor which recording a cue belongs to beyond a bare asset id (`:281`, no title). Fix: add "{n} of {total} cues left for {recording title}" and the rule sentence.
- [HELP-03] `:619-628` and `:110` failures of Approve/Save/Reject are titled "Could not load caption review." Fix: "That change was not saved: {reason}".
- [HELP-04] `:118` "check caption review logs in deployment settings" — no such screen for a non-technical user; `:141-143` "captions runtime emits review items" is jargon. Fix: "Cues appear here after you approve a recording for the portal on the Publish screen (that starts captioning) and it finishes transcribing."
- [HELP-05] `:359-407` Reject has no confirmation and no explanation that a rejected line is simply left out of the captions; Approve/Reject do not explain "Edited" vs "Approved" (both publish).
- [HELP-06] `:134` Empty-state next step "run a captioned recording or live session" omits the normal path (publish a recording). `:604-606` Spanish explanation says "translated" without saying the translation is machine-made and also needs review (the same cards, ES badge).
- [HELP-07] `:354` "I compared this low-confidence cue with its audio evidence." is enabled only after the audio plays, but nothing says why the box is grey. Add "Play the audio first."
- [HELP-08] A page with thousands of cards (`:424-427` comment: "thousands of rows" for a council session) has no paging or "next unreviewed" jump; it renders every visible card at once. Fix: paging or a "Next pending" button (performance UNVERIFIED).
- [HELP-09] No link to the Manual; role note appears only after identity loads.

### schedule

- [HELP-01] `S/types/schedule.ts:37-39` — Premiere: "Publish a recorded asset to the public portal at a scheduled time." — Wrong/misleading: saving a premiere only creates a Scheduled draft; nothing airs or shows to residents until `Publish to residents` is pressed (`egress/source_plan.py:507-511`, `schedule/router.py:199-222`). The router docstring even says the opposite ("airs automatically once its air time arrives", `router.py:1206-1208`) - do not copy it. — "Puts a recorded asset on a channel at a set time. After you save it, press Publish to residents to approve it to air."
- [HELP-02] `S/types/schedule.ts:41-44` — Embargo: "Approve now; release becomes public at the embargo time." — No code found that releases an embargo: embargo rows are excluded from the source plan, from Coming Up, and cannot be committed ("embargo entries publish at a single moment and cannot be committed to air", `commit_service.py:154-161`). Promises behavior I could not find. — Hide Embargo or say what it really does; until verified the manual should not describe it as working. (UNVERIFIED, see below.)
- [HELP-03] `Sidebar.tsx:128` — nav visible to all roles, but a meeting_operator/records_clerk only sees an error with "check the server logs" advice (`ScheduleScreen.tsx:248`). — Show "Viewing the schedule needs the publish operator, setup admin or support admin role."
- [HELP-04] `ScheduleDrawer.tsx:99-101,272-283` — only `validated` assets listed; assets in state `recorded` (everything captured by the Recording screen, `recording/runtime.py:679`; recorded is a terminal state, `schedule/models.py:54-60`) are not offered, yet the backend accepts them for air (`commit_service.py:68`). Message "Upload and validate an asset in the Assets tab first." sends a recording operator on a dead-end. — list `validated` and `recorded`, or say recordings must be validated first. (UNVERIFIED whether another step converts recorded to validated; none found.)
- [HELP-05] `ScheduleScreen.tsx:716-729` — no way to cancel a Published item from this screen although `POST .../cancel` allows it; the Auto-schedule screen creates items already Published, so a wrong auto item cannot be removed here. — add a cancel/unpublish path or point to Channel Ops rollback.
- [HELP-06] `ScheduleScreen.tsx:575-584` — "Visible to residents." toast is shown even when the report says the engine nudge failed. — read `dispatch_status` and warn.
- [HELP-07] `ScheduleScreen.tsx:861` — "Conflicts on the same channel are rejected at the database layer." and `:283` "Conflicts are caught at the database layer before the form submits." — developer wording; the second is also inaccurate (the check happens when you submit). — "The station will not let two programs overlap on the same channel."
- [HELP-08] `ScheduleScreen.tsx:866-889` — tab labels `week`/`list` are lowercase raw ids; `Workflow` eyebrow is vague. Minor.
- [HELP-09] `ScheduleScreen.tsx:696-710` vs Program Guide: the same `Publish to residents` button also airs on the channel; the words "residents" hides that it goes on the linear channel. — "Approve to air".

### setup

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

### station-profile

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

### summary

- [HELP-01] `SummaryReviewScreen.tsx:10-14,234` — The Approve button sends extra fields `operator_id` and `operator_display_name`. The server's request model forbids anything except `approval_note` (`summary/router.py:111-115`, `extra="forbid"`). A Pydantic copy of that model rejects the same body (checked in a throwaway Python call; the running station was not exercised). Approve most likely fails with HTTP 422, and the page shows "Could not load summary review." with a JSON error. If confirmed, this blocks the whole summary workflow. Fix for the coder: send only `approval_note` (the server already takes the operator from the signed-in token, `router.py:174-181`) and change the error title. (Coordinator re-checked the model definition and the screen's payload on 2026-10-03: both as described.)
- [HELP-02] `:138,201-211` and `summary/store.py:54-59` — After a successful Approve the summary becomes Approved and drops out of this list (only Pending review and Needs evidence are listed). The "Export signed record" button (enabled only for Approved) can then no longer be reached, and nothing in the console lists, downloads or verifies records. The header promises "then export the PDF/A-3B signed-record artifact" (`:259-260`). Fix: list Approved items (or add an "Approved" tab) and add Download and Verify links.
- [HELP-03] `TranscriptCuePlayer.tsx:20-26` — "Inline transcript player" and "Transcript seek target" show only cue ids and times. The reviewer cannot read the quoted transcript or hear the audio here, yet the page says to "approve only summaries whose quantitative claims link to transcript cue timestamps". Fix: show the cue text, or rename the box "Source cues" and link to Review queue or the recording.
- [HELP-04] `:159-160`, `:108-109`, `SourcedClaimList.tsx:24` tell the reader to "regenerate", but there is no regenerate button here. On the asset page, the AI summary card shows only "Summary generated. Review it in Summary review" once any job exists (`GenerateSummaryPanel.tsx:392-399,453-461`). Fix: add "Generate again" for finished jobs.
- [HELP-05] `:146` — The card title is the asset id ("meeting id"), not the meeting name. `:148` shows the raw summary id and model tag (jargon). Fix: show the recording title and date, and move ids to a "details" line.
- [HELP-06] `:259-261` — Jargon: "quantitative claims", "cue timestamps", "PDF/A-3B", "signed-record artifact". Nothing explains what a signed record is for, or that the timestamp authority is a test one by default (`:207-209` "remains deterministic unless a real authority is configured" is unreadable to a clerk). Fix: a plain description and a clear warning when no real timestamp service is set up.
- [HELP-07] `:61,273-281` — Action failures get the same wrong title, and a 422 error is shown as raw JSON.
- [HELP-08] `types/summary.ts:10` and the yellow bar say "more evidence" but not what the clerk should do (fix cues in Review queue, then generate again).
- [HELP-09] There is no link to the Manual or to Review queue.

### underwriting

- [HELP-01] Empty-state lines 1559-1560 "airing reports build from it" and 873-875 "appear here automatically once ... the compiler runs", and the whole screen premise — from code: (a) the only caller of the trafficking compiler is the manual `POST /api/staff/underwriting/compile` endpoint (`router.py:606-640`); no scheduler or program-log code calls it. (b) Nothing outside `underwriting/` reads placements (grep of `civiccast/` for `SpotPlacement`, `list_placements`, `spot_placements` outside tests/migrations finds only `app.py` wiring). (c) The playout engine never records an as-run entry of kind `spot`: `map_source_kind` returns only program, live, slate or filler (`egress/asrun.py:90-108`), yet the affidavit counts only `source_kind="spot"` entries (`service.py:539-546`). So creating spots and flights does not make anything air, and affidavits will be empty. UNVERIFIED by running (no live station). Until proven otherwise the manual must describe this as a planning list and must not tell clerks it will insert sponsor messages or produce billing proof. Suggested screen banner: "Beta: sponsor spots are recorded here but are not yet inserted into the broadcast automatically."
- [HELP-02] Affidavit "Download CSV/XML/PDF" (lines 1019-1048) — these are ordinary links (`<a href download>`), and every `/api/staff/*` route needs an `Authorization: Bearer ...` header (`auth/middleware.py:88-94`; no cookie or query-token path found). A browser link cannot send that header, so the expected result is a saved or shown error "Missing Authorization header. Use Bearer <staff-token>." instead of a file. Reports and Analytics were already converted to header-carrying downloads (`ReportsScreen.tsx:270-282`, `AnalyticsScreen.tsx:341-360`); this one was not. UNVERIFIED in a browser. Fix: use `downloadStaffBlob` like Reports. Until then do not document these buttons as working.
- [HELP-03] lines 873-875 — see HELP-01; "automatically" is unsupported.
- [HELP-04] lines 1419-1423 — jargon: "trafficking compiler", "flight", "placements", "affidavit", "47 CFR 73.503". Define each in one sentence in the manual and in a short helper line: flight = a sponsor's dates and channels; placement = a specific schedule slot a spot was assigned to; affidavit = a sponsor-ready list of every time their spot aired.
- [HELP-05] lines 397-399 "NOT attested — operator must attest before traffic." — "traffic" is broadcast jargon and the unattested spot is not actually blocked unless `CIVICCAST_REQUIRE_FCC_ACK=1` (UNVERIFIED that the compiler skips un-attested spots; the compiler is documented as honoring a policy gate, `service.py` header). Say "Not attested yet. Tick the box in Edit before this spot can be used."
- [HELP-06] Channels field (lines 652-658) — no "required" marker; the server rejects an empty list ("channels must list at least one channel slug"). Mark required and list real channel ids.
- [HELP-07] lines 292, 270, 277 — Asset ID is typed by hand with no way to pick a recording; an unknown id is accepted silently. Add a picker or say "Copy the ID from Assets".
- [HELP-08] lines 1066-1082 — good three-cause empty state, but add a fourth: "Spot airings are only counted if the station records them as spot airings (see Reports > As-Run, Source = spot)". Remove once HELP-01 is resolved.
- [HELP-09] Date semantics differ between tabs (Placements half-open, Affidavits inclusive) and are explained only in a paragraph (line 1426-1428); put a one-line hint under each date pair. Dates and times are UTC; a Mountain-time evening airing can land on the next UTC day.
- [HELP-10] Delete spot warning mentions flights and placements but not that the affidavit for that sponsor changes; also no undo. Add "This cannot be undone."
