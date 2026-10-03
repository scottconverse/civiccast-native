# Agendas  (nav id: agendas, section: Review Records)
Paths are relative to the repo root. `OP/` = `civiccast/apps/portal-operator/src/`.
Source files: `OP/screens/AgendasScreen.tsx` (whole screen), `OP/screens/agendas-format.ts` (`formatTimecode`; `slugify` and `isPlausibleHttpUrl` exist there but are not called by the screen: grep), `OP/components/EmptyState.tsx`, `OP/components/AuthRequiredState.tsx`; route `OP/App.tsx:308` (`/agendas`); nav `OP/components/shell/Sidebar.tsx:156`. Backend: `civiccast/agenda/router.py`, `civiccast/agenda/service.py`, `civiccast/agenda/store.py`, `civiccast/agenda/models.py`, `civiccast/agenda/pdf_import.py`, `civiccast/agenda_import/router.py`, `civiccast/agenda_import/config.py`. Public side: `civiccast/apps/portal-public/src/MeetingAgendaSidebar.tsx`.

Who can open it: `records_clerk` or `meeting_operator` only. The nav entry is hidden from everyone else (`Sidebar.tsx:156`), the screen re-checks (`AgendasScreen.tsx:69-71,1124-1134`) and shows "Agendas require the records clerk or meeting operator role. Ask your station admin for access." to others, "Loading…" while checking, and the sign-in prompt component if identity fails; every staff agenda API route uses the same pair (`civiccast/agenda/router.py:64,120,140…`, `agenda_import/router.py:55`). `setup_admin`, `support_admin` and `publish_operator`-only tokens are locked out. A generic `operator`/`admin` token holds all roles (`civiccast/auth/roles.py:23-24`).

## What it is for
Lets staff build a meeting agenda for one recorded meeting: a list of numbered items, each optionally tied to a time in the video. Once published, the agenda appears next to the recording on the public meeting page and clicking an item jumps the video to its time. Items can be typed in, filled from the recording's chapter markers, imported from pasted text, a PDF, or an outside agenda system.

## What the user sees
Top to bottom (`AgendasBody`, `:1199-1262`):
1. Heading "Agendas" and text "Build and publish a meeting agenda the resident sees alongside the recording. Agendas stay drafts until published; published agendas appear on the public meeting page. Publishing needs at least one item." (`:1202-1206`).
2. "Pick an agenda" drop-down, only when at least one agenda exists; entries read "{meeting asset id} — {agenda id} ({draft|published})", sorted by meeting asset (`:1215-1228,1686-1690`).
3. Card "Create new agenda": Agenda ID (slug) [placeholder council-2026-01], Meeting asset ID [asset-council-2026-01], Source doc URL (optional) [with help "Link to the published PDF/HTML agenda the resident can read alongside the video."], button "Create agenda" (`:194-248`).
4. Card "Selected agenda": agenda id, status chip (draft/published), "meeting asset: {id}", "Source doc ↗" link or "No source doc URL.", buttons **Publish** / **Unpublish** and **Delete** (`:255-381`).
5. Section "Items": form "Add item" (or "Edit item") with fields Item ID (slug) [item-01-call-to-order], Order, Number (label, optional) [1.a], Title, Video timecode (seconds, optional) with a tip, Doc anchor (optional) [#item-1a], Notes (optional); then the table "Agenda items" (columns Order, Number, Title, Timecode, Doc anchor, Confidence, Actions) (`:433-646,650-773`).
6. Section "Bulk actions": "Sync from chapters"; "Import from doc (paste plain-text agenda, one item per line)" with "Import"; "Or upload a PDF agenda…" with "Import PDF"; "Import from an external agenda system"; and an information-only card "CivicSuite event bridge — coming in a future release" (`:1507-1652`, `:822-1099`, `:795-808`).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Create agenda | Makes a draft agenda for a meeting asset (station id is fixed to `civiccast-station` by the page, `:72,1191`) | POST `/api/staff/agendas` | records_clerk, meeting_operator | Enabled when ID and asset ID are filled. IDs must be lowercase letters/digits/`-`/`_` starting with a letter or digit, up to 120 chars (`agenda/models.py:45`); otherwise a 422 whose raw JSON is shown. Duplicate agenda id: 409 "Meeting agenda '{id}' already exists. Use PATCH to update."; second agenda for the same meeting asset: 409 "An agenda already exists for (station_id='…', meeting_asset_id='…')." (`router.py:160-169`; `store.py:130`). Success selects the new agenda |
| Pick an agenda | Switches the agenda; resets item form and confirmations (component is keyed by agenda id, `:1248-1252`) | GET `/api/staff/agendas`, `/{id}/items` | same | |
| Publish | Makes the agenda public | PATCH `/api/staff/agendas/{id}` `{status:"published"}` (`router.py:195-254`) | same | Disabled with tooltip "Publish needs at least one item — add one below or sync from chapters." when there are no items (`:323-327`). Server refuses 422 "Cannot publish agenda '{id}': it has zero items. Add at least one item (DC-1) before publishing." (`service.py:136-142`). Button shows "Publishing…" |
| Unpublish | Back to draft; no confirmation | PATCH `{status:"draft"}` | same | Shows "Saving…" |
| Delete -> Confirm delete | First click arms the red "Confirm delete" button and prints "Confirming will also delete every item under this agenda." (`:377-378`); second click deletes the agenda and all items | DELETE `/api/staff/agendas/{id}` (`router.py:257-281`) | same | There is no Cancel/undo for the armed state except choosing another agenda |
| Add item / Save item / Cancel | Creates or updates one item; Cancel (edit mode only) clears the form | POST `/api/staff/agendas/{id}/items`, PATCH `/items/{item}` | same | Needs Item ID (new only), Title, Order (whole number >= 0); Timecode whole seconds >= 0 or blank (`:465-474`). The Order box starts at 0 every time, so a second new item with the same Order is refused: 409 "Another agenda item already occupies (agenda_id='…', order=0)." (`store.py:253-256`). Duplicate item id: 409 "Agenda item '{id}' already exists. Use PATCH to update." |
| Edit (row) | Loads the row into the form | none | - | |
| Delete (row) -> Confirm delete | Same two-step; removes the item | DELETE `/api/staff/agendas/{id}/items/{item}` | same | |
| Sync from chapters | Creates one item per chapter marker of the meeting asset (title = chapter name, timecode = chapter time, order = position); items whose order already exists are skipped, so edits survive a re-run | POST `/api/staff/agendas/{id}/sync-from-chapters` (`service.py:151-186`) | same | Result banner "Synced {n} new item(s) from chapter markers." or the server error. Chapters are set in the trim editor |
| Import (pasted text) | One draft item per non-blank line; a leading number like "3.a" or "VII" is split off as Number; no confidence score | POST `/api/staff/agendas/{id}/import` as `text/plain` (`router.py:469-538`) | same | Banner "Imported {n} item(s)." Help line: "Taken literally, one item per line — nothing to review." |
| Import PDF | Best-effort reading of a PDF's text layer (numbered items, ALL-CAPS headings, times); each item gets a Confidence % | same route, `application/pdf` | same | Reopens a published agenda to draft (`:1607-1612`, `router.py:493-501`). 422 "Couldn't find any recognizable items in that PDF. Try pasting the agenda's text instead."; 415 "Only plain-text and PDF agendas import here today (DOCX and other formats are a follow-up)." If any item is under 90% the banner adds "Some items were a best-effort guess (see the Confidence marks below) — review them before publishing." |
| External import: Source (Legistar, PrimeGov, CivicClerk, "JS-rendered portal (CivicPlus, Granicus, other)"), Tenant / site code (or "Display label" for the JS portal), Portal URL, Vendor hint, "Only meetings on/after (optional)", **Find meetings**, Meeting list, **Import selected meeting** | Looks up meetings at the outside system, then imports the chosen one into this agenda | GET `/api/staff/agenda-sources/{source}/{code}/meetings`; POST `/api/staff/agenda/{id}/import-external`; GET JS-portal check (`agenda_import/router.py:148-333`) | records_clerk, meeting_operator | **Off by default**: the server answers 404 "Agenda import is not enabled. Set CIVICCAST_AGENDA_SOURCE to 'legistar', 'primegov', 'civicclerk', or 'js_portal' to turn it on." (`router.py:57-60`; default `off`, `config.py:7,117,136`), shown in the yellow banner. JS-portal needs an optional runtime: line "JS-portal runtime: not installed. …" and Find is disabled. Importing into a published agenda moves it back to draft (`:1068-1073`) |
| Source doc ↗ / "open the meeting on the public portal ↗" | Opens links in a new tab | none | - | The portal link exists only when the build sets `VITE_PUBLIC_PORTAL_BASE_URL` (`:96-105`); otherwise the tip is plain text |

## States
- Page loading: "Loading…"; identity error: sign-in-required component; wrong role: info banner (above).
- No agendas: no picker, the create form, then "No agendas yet." / "Agendas list what a meeting will cover and appear alongside its recording on the public meeting page. Create one with the form above — it stays a private draft until you publish it." (`:1256-1257`).
- Items: "Loading items…"; error banner with server text; if a refresh fails but old rows exist: "Items list may be stale — last refresh failed … The rows below are from the previous successful load." (`:1482-1486`); empty: "No items on this agenda yet. Add one with the form above, or run "Sync from chapters" in the Bulk actions section if the meeting asset already has chapter markers." (`:668-670`). Draft agenda without items also shows "Publish needs at least one item. Add one below or sync from the meeting asset's chapters." (`:369-374`).
- Offline/error on any action: yellow warn banners (`role=alert`) with the server's text; validation errors (422) appear as raw JSON text.
- Not configured: external import 404 text above.

## Typical task flows
1. New agenda by hand: Create new agenda (type the recording's asset id exactly) -> add items (change Order each time: 0, 1, 2…) -> add timecodes -> Publish -> check the public watch page for that recording.
2. From chapters: set chapters in the recording's trim editor -> Create agenda -> Sync from chapters -> edit titles -> Publish.
3. From text/PDF: paste or upload -> Import -> check Confidence marks -> Publish.
4. Take down: Unpublish (draft again; public page returns 404 for it, `agenda/service.py:325-337`).
5. Delete: Delete -> Confirm delete.

## Statuses and words on this screen
(`status-language.ts` not used.) Agenda status: `draft` (grey) and `published` (green) as lowercase mono chips with aria-label "Agenda status: draft|published" (`:144-155`). Confidence: green >= 90%, amber 50-89%, red < 50%, tooltip "Confidence score from the PDF import heuristic — review before publishing if low." (`:707-718`); blank for typed/pasted items. Timecode column is HH:MM:SS from whole seconds (`agendas-format.ts:16-24`); "—" when blank. What residents see: item number, title, order, timecode and doc anchor only; **Notes** ("Operator-private notes; not shown to viewers.", `:616`) are not in the public view (`agenda/models.py:235-250`). Only published agendas are served at `/api/public/agendas/{meeting_asset_id}`; drafts return 404 (`router.py:544-574`).

## Related settings / env / CLI / API
`CIVICCAST_STATION_ID` (default `civiccast-station`, `agenda/router.py:67-79`), `CIVICCAST_AGENDA_SOURCE`, `CIVICCAST_AGENDA_SOURCE_CLIENT`, `CIVICCAST_AGENDA_SOURCE_TOKEN`, `CIVICCAST_AGENDA_SOURCE_TIMEOUT_S` (`agenda_import/config.py:117-120`), `VITE_PUBLIC_PORTAL_BASE_URL` (build setting), optional crawl4ai/Playwright runtime for JS portals; GET/POST/PATCH/DELETE `/api/staff/agendas…`; public GET `/api/public/agendas/{meeting_asset_id}`.

## Help-text findings
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

## Screenshot plan
1. First visit (no agendas): create form + "No agendas yet." box.
2. A draft agenda with 3-4 items (one with a timecode) and the Publish button; same agenda after Publish (chip "published", Unpublish button).
3. Armed "Confirm delete" state with its warning line.
4. Bulk actions: after "Sync from chapters" success banner; after a PDF import with confidence chips (green/amber/red).
5. External import block: default (not enabled) error banner; and with a station that has it enabled (Find meetings result list).
6. Role-blocked view (info banner) as a setup_admin-only token.
Setup: a recording with chapters set in the trim editor; a sample 1-2 page text PDF agenda; the public portal opened on the same recording to show the published agenda in its side panel.

## UNVERIFIED / open questions
- UNVERIFIED: whether the server rejects a meeting asset id that does not exist (no check seen in `agenda/router.py` create; store not read for asset lookup).
- UNVERIFIED: whether `CIVICCAST_STATION_ID` is set differently from `civiccast-station` on any shipped install (grep found uses only in `civiccast/app.py:3221,3356`, paywall/metadata/recording routers; installer sets it nowhere I could see).
- UNVERIFIED: how the public watch page looks and where it shows the agenda panel (only `MeetingAgendaSidebar.tsx` header read).
- UNVERIFIED: whether the installer or Setup offers a way to turn on `CIVICCAST_AGENDA_SOURCE` for non-technical users.
- UNVERIFIED: whether `VITE_PUBLIC_PORTAL_BASE_URL` is set in the shipped operator build (`import.meta.env`, read at build time).
