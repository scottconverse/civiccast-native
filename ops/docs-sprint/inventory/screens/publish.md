# Publish  (nav id: publish, section: Publish)
Source files (paths relative to `civiccast/apps/portal-operator/src`, called "SRC" below):
`SRC/screens/PublishDashboardScreen.tsx` (all line numbers below are this file unless another path is given),
`SRC/screens/status-language.ts`, `SRC/components/ConfirmDialog.tsx`, `SRC/auth/roles.ts`, `SRC/types/publish.ts`.
Backend: `civiccast/publish/router.py`, `publish/service.py`, `publish/readiness.py`, `publish/models.py`,
`platform/providers.py`, `schedule/router.py` (public asset list, unpublish), `activitypub/service.py`.
Scope note: the work order listed `FeedApprovalQueue.tsx` and `feed-command-confirm.ts` under Publish. Neither is imported by
`PublishDashboardScreen.tsx`. They belong to other screens (see "Related" at the end); verified by grep.

Who can open it: nav entry has no `requiredRoles` (`SRC/components/shell/Sidebar.tsx:163`), so every signed-in operator sees it.
It is not reachable while the first-setup recovery kit is pending (`Sidebar.tsx:345`). Role differences:
- Reading the dashboard and the readiness check: any valid staff token (no role dependency on `GET /api/staff/publish/assets`,
  `.../preflight`; `publish/router.py:343-413`).
- Approving or retrying a surface: `publish_operator` only (`publish/router.py:420`, `:542`). The screen checks the same role
  (`hasOperatorRole(..., 'publish_operator')`, line 834-836); without it the checkboxes and buttons are disabled and the screen says
  "Publish operator role required to approve or retry surfaces." (line 729). Note that `setup_admin` and `support_admin` cannot publish.
- Tokens with scope `admin` or `operator` expand to all five roles (`civiccast/auth/roles.py:22-24`).

## What it is for
This is the one place a person decides what leaves the station: it lists every recording and, for each, a row per "surface"
(Portal, Internet Archive, local NAS copies, YouTube, cable file package, and two surfaces that are marked "coming in a future release").
An operator ticks the surfaces to publish and presses one button. The Portal surface makes the recording public to residents; the
others copy it to archives and outside services.

## What the user sees (top to bottom)
1. Header: eyebrow "Publish workflow", h1 "Publish dashboard", lede "Canonical portal, archive, reach, and signed-record surfaces are tracked separately so a YouTube problem never hides the public record state." (lines 885-891)
2. Summary tiles (only once data loads, lines 894-919): Total, Draft, Portal live, Archive verified, Degraded, Needs action.
3. Filter tabs `role=tablist` "Filter publish state" (lines 925-945): All, Needs action, Draft, Archive pending, Archive verified, Reaching fewer places than planned, Complete (labels from `stateLabel`, `status-language.ts:240-250`).
4. One card per recording (`AssetPanel`, line 429+): title (h2), asset id (monospace), a state pill, then three facts "Canonical" (`Portal public` / `Portal pending`), "Archive" (`IA and local NAS verified` / `IA and local NAS required` / `Not required`), "Published" (date or `Not public yet`) (lines 616-638).
5. Inside the card, one row per surface (9 rows, backend `publish/service.py:211-298`): Portal, Internet Archive, Local NAS rsync, Local NAS ZFS, YouTube Live, YouTube VOD, Podcast episode, Subscriber notifications, Cable file package. Each row: status dot, label, badges (`Required`, approval word, or `Coming in a future release`), a line `{kind} / {state}`, optional simulated warning, URL/path/hash, the server message, and "Next step."
6. "Readiness check" panel (lines 353-418): per surface Ready / Not ready / Ready (warning) / Unknown / Future release, with message and "Next step."
7. Two explanatory paragraphs (lines 668-692) and the "Approve and Publish selected" button with inline reasons it is disabled.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Filter tabs (All / Needs action / ...) | Filters cards by `dashboard_state` in the browser | none (client filter) | any | `preflight_blocked`, `publishing`, `portal_live` states have no tab; they appear only under All |
| Approve this surface (checkbox, line 258) | Selects a surface for the next approval | none until button | publish_operator | Only on rows in state pending/failed/blocked and not "future" rows (lines 156-160). Default ticked = Portal only (lines 465-473, F-23) |
| Use audit-logged archive override for this platform (checkbox, line 270) + textarea (aria-label "Override justification for {label}") | Skips a required archive surface instead of publishing it; the surface becomes "overridden" and counts as archive-done | `overrides[]` in the approve body; server stores justification, state `overridden` (`service.py:412-427`) | publish_operator | Only on required archive rows (line 161). UI needs 20+ chars (line 508); server minimum is 12 (`publish/models.py:49`) |
| Retry this surface (line 301) | Re-runs one failed surface only | `POST /api/staff/publish/assets/{id}/surfaces/{surface}/retry` | publish_operator | Shown only for state `failed`. A retry of Portal that succeeds also queues captions (`router.py:629-653`) |
| Approve and Publish selected (line 706) | Opens a confirm dialog, then sends the approval | `POST /api/staff/publish/assets/{id}/approve` body `approved_surface_ids`, `overrides`, `operator_id:"operator-dashboard"` (lines 593-599) | publish_operator | Disabled unless: something selected, no override missing a 20-char reason, no selected surface blocked, no selected surface whose readiness check reports error (lines 534-541). While running: "Publishing selected surfaces..." |
| Confirm dialog | Title `Publish "{title}" to residents?`; body `{n} selected surface(s) publish(es) for real: {labels}.` then either `The portal surface becomes publicly visible to residents immediately and starts offline caption transcription.` or `The portal surface is not part of this approval.`; button "Approve and Publish"; Cancel (lines 741-757) | sends the approval on confirm | | Focus starts on Cancel; Esc cancels (`ConfirmDialog.tsx`) |
| Retry readiness check (line 381) | Re-fetches readiness | `GET .../preflight` | any | Shown only if the readiness fetch failed |
| Retry (error state, line 790) | Reloads the list | `GET /api/staff/publish/assets` | any | |

## What each surface really does (from backend code)
`approve_publish` runs only the surfaces named; all others are left as they were built (`service.py:543-589`).
- **Portal**: needs the recording to have a manifest URL, otherwise the whole approval is refused with 409 "Publish preflight blocked: this asset has no manifest_url. Run the packager or fix ingest before approving publish." (`router.py:452-459`). On success the asset's `published_at` is set (`router.py:85-129`, `mark_published` at line 106), which puts it in the unauthenticated public list `GET /api/public/assets` (`schedule/router.py:150-168`) and its public detail page. It also queues offline caption transcription BEFORE publishing; if that cannot be queued the approval is refused with 409 "Publish blocked: CivicCast cannot queue this recording's caption job ... Nothing was published." (`router.py:175-179`, `:470-481`). Reversible: Assets > asset detail > "Remove from portal" (`AssetDetailScreen.tsx:862`, `POST /api/staff/assets/{id}/unpublish`, roles publish_operator or setup_admin, `schedule/router.py:129,617`). That removal does not undo anything below (docstring `schedule/router.py:640-648`).
- **Federation (hidden side effect)**: after any approval, if `federation_mode` is not `disabled`, a public "Create/Note" activity "New CivicCast recording published: {title}." is recorded and delivery to remote servers is attempted (`router.py:520-534`, `activitypub/service.py:430-460`). Nothing on this screen says so. Not reversible once delivered.
- **Internet Archive**: with the default mock provider nothing is sent; the row shows the "Simulated" note. With `CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real` it uploads the local recording file when one can be found, otherwise a small verification payload (`service.py:602-634`, `platform/providers.py:62-63,87`). A real upload to archive.org is not undoable from CivicCast.
- **Local NAS rsync / ZFS**: one shared archive run for both rows (`service.py:635-671`). Mock by default.
- **YouTube Live / YouTube VOD**: calls `publish_live` / `upload_vod(_path)` on the configured provider (`service.py:672-711`). The mock returns made-up URLs (`rtmps://youtube.example/...`, `https://youtube.example/watch?v=...`, `syndicate/models.py:22-37`) and is NOT flagged simulated, so the row says "YouTube Live RTMPS fanout proof succeeded." even when nothing was sent.
- **Cable file package**: builds a local ZIP with media, captions, metadata and hashes in the folder named by `CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR` (+ `CIVICCAST_CABLE_CAPTIONS_DIR`); if unset the row becomes "not set up (optional)" (`service.py:758-810`, `cable/package.py:173-179`).
- **Podcast episode / Subscriber notifications**: shown as "Coming in a future release"; the UI never lets you select them (`FUTURE_SURFACE_IDS`, lines 60-68). Subscriber notifications never send mail or webhooks (`service.py:71-82,738-757`). A podcast branch still exists in the API (`service.py:713`) and writes placeholder `portal.example` URLs; it is reachable only by calling the API directly.
- **Audit trail**: events record `operator_id` taken from the request body, and this screen always sends the constant `operator-dashboard` / `Operator dashboard` (lines 594-595, 862-863). The signed-in person is not recorded here. UNVERIFIED whether another layer overwrites it (none seen in `publish/router.py`).

## States
- Loading: two grey pulsing placeholder blocks (lines 812-823).
- Empty: "No assets are ready for publish review." / "Upload or record a meeting first. Packaged recordings will appear here with portal, Internet Archive, local NAS, YouTube, and signed-record status." (lines 803-807)
- Filter matches nothing: "No assets match this publish filter." (line 956)
- Load failure: "Could not load publish status." or, on HTTP 503, "Publish dashboard needs a database." with "Next step. Open deployment settings, connect the CivicCast database, then reload this screen." / "Retry the request. If it fails again, check the API server logs." (lines 771-781). Backend 503 text: "Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment." (`router.py:79-82`)
- Readiness: "Checking readiness…", "Could not load publish readiness." (lines 369, 374)
- Approval failure: "Publish stopped. {detail} Nothing else was published; correct the named issue and retry." (lines 733-737). This sentence is wrong for a partial failure: surfaces that succeeded before a provider error stay published.

## Typical task flows
1. Publish a meeting to the portal: find the card, leave only Portal ticked, press "Approve and Publish selected", read the dialog, press "Approve and Publish". Card shows Portal "Succeeded", state "Archive pending" if the recording is a public record (retention `meeting` or `permanent`, `service.py:53,108`).
2. Add archive copies later: tick Internet Archive / Local NAS rows, approve again. (See Help-text finding HELP-01: this currently resets the Portal row.)
3. Skip a required archive surface: tick the override box, type an explanation of 20+ characters, approve.
4. Recover a failed surface: read the row's message and "Next step.", fix the cause, press "Retry this surface".

## Statuses and words on this screen
Dashboard state (`stateLabel`, `status-language.ts`): draft "Draft"; preflight_blocked "Preflight blocked"; publishing "Publishing"; portal_live "Live on the portal"; reach_degraded "Reaching fewer places than planned"; archive_pending "Archive pending"; archive_verified "Archive verified"; complete "Complete"; failed_needs_action "Needs action". Logic: `service.py:923-954` (failed required surface > portal pending = draft > portal done + required pending = archive pending > reach failed = degraded > all required archives done = archive verified > complete).
Surface state shown as `{kind} / {state}`: pending shows "Not run yet" (`status-language.ts:210`); other values are sentence-cased raw words (Succeeded, Failed, Blocked, Overridden, Running, Coming soon, Not set up yet). Kind words shown raw: canonical, archive, reach, record, audience. Approval badge shows raw `pending` / `approved` / `overridden`.
Status dot symbols: OK, !, ..., - (lines 105-128). Readiness words: Ready, Not ready, Ready (warning), Unknown, Future release (lines 329-340).
`Archive verified` is also reported when the archive surfaces were completed by a simulated provider or by override (see HELP-02).

## Related settings / env / CLI / API
`CIVICCAST_PROVIDER_INTERNET_ARCHIVE`, `CIVICCAST_PROVIDER_LOCAL_NAS`, `CIVICCAST_PROVIDER_YOUTUBE` (values `mock` default, `real`), `CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR`, `CIVICCAST_CABLE_CAPTIONS_DIR`, federation mode (`activitypub/config.py:22`, Federation screen), `DATABASE_URL`.
API: `/api/staff/publish/assets`, `/assets/{id}`, `/assets/{id}/preflight`, `/assets/{id}/approve`, `/assets/{id}/surfaces/{surface}/retry`; public `/api/public/assets`.
Event emitted: broker subject `publish.asset.approved` (`service.py:112-130`).
Related components used by OTHER screens: `FeedApprovalQueue.tsx` (Approve button per community-board feed item; CG Designer, `CgBoardDesignerScreen.tsx:719`; API `POST /api/staff/cg/channels/{c}/feeds/{f}/items/{i}/approve`, roles publish_operator or setup_admin, `cg/board_router.py:58,489-493`; empty text "No items in this feed right now.", counts "{n} pending · {m} approved"). `feed-command-confirm.ts` supplies the Start/Stop/Restart/Finish-then-stop feed confirmations for Channels and Readiness (`ChannelOpsScreen.tsx:2035`, `SystemHealthScreen.tsx:1610`). Document those under their own screens.

## Help-text findings
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

## Screenshot plan
1. Empty state (fresh station, no assets).
2. One card with a mock-provider recording, Portal ticked by default, readiness panel open, all 9 rows visible (shows "Coming in a future release" rows and the "Simulated" notes after an approval).
3. The confirm dialog with only Portal selected, and a second one with Portal + Internet Archive.
4. After approval: card in "Archive pending"; then after approving archives: "Archive verified" with Simulated notes (shows HELP-02).
5. Signed in as a role without publish_operator: warning text beside the disabled button.
6. 503 error state (stop the database) and a 409 "no manifest_url" failure.
Setup: a packaged recording (manifest present), one with a public-record retention policy, one without manifest; optionally set `CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR`.

## UNVERIFIED / open questions
- UNVERIFIED: what the real (non-mock) YouTube adapter does for "YouTube Live" on a finished recording (need `platform/youtube*` real client code; only the mock was read).
- UNVERIFIED: whether any layer replaces `operator_id` with the signed-in identity (none found in the publish router).
- UNVERIFIED: whether the real Internet Archive adapter makes the item public immediately or after review (need `archive/` real client).
- UNVERIFIED: exact on-screen look of the confirm dialog (component source read, not rendered).
- UNVERIFIED: `FeedApprovalQueue` and `feed-command-confirm` behavior beyond their own files (not on this screen).
