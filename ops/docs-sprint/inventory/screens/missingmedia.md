# Missing Media  (nav id: missingmedia, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`.
Source files: `OP/screens/MissingMediaScreen.tsx`; route `OP/App.tsx:70-73,281` (`/missing-media`); nav `OP/components/shell/Sidebar.tsx:143-147`. Backend: `civiccast/schedule/media_lifecycle_router.py:945-958`, `civiccast/schedule/media_lifecycle_worker.py:836-877`, `civiccast/schedule/media_integrity_worker.py`.

Who can open it: nav entry shown only to `meeting_operator`, `publish_operator`, `support_admin` (`Sidebar.tsx:146`). The API uses the same set (`_READ_ROLES`, `media_lifecycle_router.py:84,949`). The screen has no role check of its own, so a `records_clerk`-only or `setup_admin`-only user who types `/#/missing-media` sees the error box with the server text "This action requires one of these CivicCast roles: meeting_operator, publish_operator, support_admin." (`auth/roles.py:96-97`). A token with the generic `operator`/`admin` scope has all roles (`auth/roles.py:23-24`).

## What it is for
A warning list: shows meetings that are on the schedule for the coming week whose video file is not ready to play. Each card says which meeting, which channel, what state the video is in, and why it is not ready, with a button to open the video in Assets. Nothing is stored; the list is recomputed on every request, so a card disappears as soon as the video becomes ready (`MissingMediaScreen.tsx:1-8`).

## What the user sees
1. Small label "Media Lifecycle", heading "Missing Media" (`:141-144`), text "Meetings scheduled in the next 7 days whose source asset is not validated, not recorded, or missing its file. Fix these before air check." (`:145-148`).
2. A column of cards, one per scheduled item. Each: bold "{asset title} — {Weekday, Mon D, h:mm AM/PM}" (`:92-94`); grey mono line "{channel id} · source asset '{asset id}' · state: {asset state}" (`:96`); a badge reading "🔴 Not ready" (`:105`, fixed text on every card); the reason sentence (`:109`); button "Open asset" (`:119`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Open asset | Goes to `/assets/{asset id}` (the asset detail page) | route only | none in UI | Rendered because `App.tsx:72` passes `onOpenAsset` |
| Retry (error box only) | Refetches the list | GET `/api/staff/media-lifecycle/missing-media` | meeting_operator, publish_operator, support_admin | - |
There are no other controls: no refresh button, no dismiss, no link to the Schedule. The page loads once when opened (cache 30 s, no refetch on window focus, `OP/queryClient.ts:46-50`), so leave and return to refresh.

## States
- Loading: two grey pulsing bars (`:70-81`).
- Empty: "Nothing missing." / "Every asset scheduled in the coming week is validated or recorded and ready for air." (`:62-65`).
- Error: heading "Could not load missing-media alerts." or, for HTTP 503, "Durable storage is not ready." (`:37`), then the server text or "Request failed: {message}", then "Retry" (`:40,49`). The 503 detail is "Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment." (`media_lifecycle_router.py:98-101`).
- Offline / server down: shows the "Could not load" error with the browser's message.

## Typical task flows
1. Open Missing Media before a meeting week -> read each card's reason -> "Open asset" -> in Assets re-upload / Replace source / re-link the file -> come back later; the card is gone once the asset is `validated`/`recorded` and its file exists.
2. If the card is about an asset that no longer exists the "Open asset" button leads to a "Could not load asset." page (asset record is gone, `media_lifecycle_worker.py:859`).

## Statuses and words on this screen
(`status-language.ts` not used.) Reasons come verbatim from the server (`media_lifecycle_worker.py:859-864`):
- "Referenced asset no longer exists." (state shown as "unknown").
- "Asset is in state '{state}', not validated/recorded." (state words are the raw database codes: `pending_ingest`, `ingesting`, `rejected`).
- "Asset's backing file is missing." (file flagged missing by the hourly integrity scan).
What counts: schedule items in state `scheduled` only, whose start time is between now and now + 7 days (`:849-855`; horizon setting `CIVICCAST_MISSING_MEDIA_HORIZON_DAYS`, default 7, `:400,457`). Items already in state `published` (committed to air) are **not** looked at (see findings). The "missing file" flag is set by `media_integrity_worker` that polls every 3600 s by default (`media_integrity_worker.py:85`, env `CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS`), so a deleted file can take up to an hour to show.

## Related settings / env / CLI / API
`CIVICCAST_MISSING_MEDIA_HORIZON_DAYS`, `CIVICCAST_MEDIA_INTEGRITY_WORKER`, `CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS`, `CIVICCAST_MEDIA_LIFECYCLE_WORKER`; GET `/api/staff/media-lifecycle/missing-media` (`MissingMediaAlertRow`: schedule_id, asset_id, asset_title, channel_id, scheduled_start, asset_state, reason); related relink API `POST /api/staff/assets/{id}/relink` (no client function or control exists in the console: `relink` appears in `OP/` only in `assetStatus.ts` text and the generated types).

## Help-text findings
- [HELP-01] `MissingMediaScreen.tsx:62-65` "Every asset scheduled in the coming week is validated or recorded and ready for air." is too strong. The check only covers schedule items still in draft state `scheduled`; items already committed to air (`published`, which is what actually airs, `schedule/router.py:211-217`) are not checked (`media_lifecycle_worker.py:849-855`), and a file deleted in the last hour is not yet flagged. Fix: "No draft schedule items for the next 7 days have a media problem. Items already committed to air are not checked here."
- [HELP-02] `:145-148` hard-codes "next 7 days" although the horizon is configurable; uses "source asset", "validated", "recorded" and "air check" without explanation. Fix: "Meetings on the Schedule in the next 7 days whose video is not ready to play. Fix these before the meeting."
- [HELP-03] `:105` every card says "🔴 Not ready" regardless of reason; `:96` shows raw codes (`pending_ingest`, `rejected`). Fix: use the Assets screen words (Validating, Rejected, Missing file) and say what to do per reason (upload a replacement / wait / re-link).
- [HELP-04] No sentence explains how to fix a card: the page offers only "Open asset", and the asset detail page's fixes (Replace source file, Package) need publish_operator/setup_admin, which a meeting_operator or support_admin (who may open this page) does not hold. Add "Ask a publish operator to replace the file."
- [HELP-05] `:141` label "Media Lifecycle" sits above the page, but the nav group is "Review Records" and the sibling page is "Media Lifecycle Settings"; first-time users may think this is a settings page. Rename label to "Schedule check".
- [HELP-06] `:40` error "Request failed: …" and the 403 role sentence are shown raw; there is no explanation that the page is limited to certain roles. Add one line under the heading naming the roles.

## Screenshot plan
1. Empty state (fresh station / nothing scheduled).
2. Two or three cards with different reasons: draft schedule item whose asset file was deleted from disk (wait up to 1 h for the scan or until the integrity worker has run), an asset in state not validated/recorded, and an item whose asset record was removed. Setup: create schedule items 1-6 days ahead on any channel and break their files.
3. Error state: sign in with a records_clerk-only token and open `#/missing-media`.

## UNVERIFIED / open questions
- UNVERIFIED: whether any code path other than the schedule-migration import ever leaves an asset in `pending_ingest`/`ingesting`/`rejected` (see assets.md), which decides whether the "not validated/recorded" reason can appear in practice.
- Only `published` schedule items air (`civiccast/egress/source_plan.py:507-509`), and Commit-to-Air checks playability once at commit time (`schedule/commit_service.py:130-131`). UNVERIFIED: that nothing re-checks a `published` item's file afterwards (searched `media_lifecycle_worker.py` and the router only).
- UNVERIFIED: whether the app wires `get_missing_media_reader` in every deployment (DI seam returns `None` by default, `media_lifecycle_router.py:939-942`; wiring lives in `civiccast/app.py`, not read).
