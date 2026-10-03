# EPG Export  (nav id: epg, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/EpgExportScreen.tsx` (line numbers below), `.../screens/reports-format.ts:41-66` (field-map text parsing),
`.../components/EmptyState.tsx`, `.../api/client.ts:3000-3050`. Backend: `civiccast/reporting/router.py:137-457`, `reporting/epg.py`, `reporting/models.py:95-170`,
`reporting/schedule_adapter.py`, `civiccast/app.py:3180-3195`.
Who can open it: `Sidebar.tsx:167` `requiredRoles: ['setup_admin', 'publish_operator']`. The screen repeats the check (`ROLES`, line 38); other roles see "EPG export requires the setup admin or publish operator role. Ask your station admin for access." (lines 583-584). API: list/get/create/edit/delete and "Generate" all accept `setup_admin` or `publish_operator` (`router.py:71-73`). The router's own docstring says create/patch/delete are setup_admin only (`router.py:21-23`); the code lets both roles do all of it. Not reachable while the recovery kit is pending.

## What it is for
An EPG ("electronic program guide") export turns the station's published schedule for the next N days into a file that cable boxes, TV-guide services or apps can read.
Each export setup names a channel, a file format (X-List / XMLTV / CSV), how many days ahead, and optionally a web address to send the file to. "Generate now" either hands you the file to download or sends it to that address.

## What the user sees (top to bottom)
1. h1 "EPG Export" with text: "Compile the upcoming committed schedule into X-List / XMLTV / CSV per a field map; either download the document or push it to an aggregator endpoint. A push failure surfaces on the result rather than as a server error, so a flaky aggregator never breaks the staff API." (lines 593-599)
2. Form "Create export config" (or "Edit export config"): Config ID, Channel ID, Format, Horizon (days), Aggregator endpoint (optional), Field map, buttons "Create config" / "Save changes" / "Cancel" (lines 134-290).
3. Error banners for create, save, delete (lines 610-618).
4. "Configured exports": list of setups, each with name, `ch=... · fmt=... · horizon=...d`, the destination or "(no endpoint — Generate returns a downloadable document)", and buttons Generate now / Edit / Delete (lines 363-460).
5. Under a row after generating: a result panel.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Config ID (placeholder `epg-tv-guide-channel-1`) | Name of the setup | `config_id` in create | setup_admin / publish_operator | Locked when editing. Server requires a slug: lowercase letters, digits, `_`, `-` (`reporting/models.py:55`); a capital letter gives a server error, not a hint |
| Channel ID (placeholder `pub-1`) | Which channel's schedule to export | `channel_id` | | Free text, not a list. A wrong id gives an export with 0 slots |
| Format: "X-List (TV Guide / TitanTV)", "XMLTV", "CSV" | File type | `format` `xlist`/`xmltv`/`csv` | | X-List = CSV with Windows line endings and 8 columns; XMLTV = fixed XML; CSV = plain (`epg.py:165-239`) |
| Horizon (days) | How far ahead to include | `horizon_days` (default 14) | | Must be above 0; the page enforces only `>0`; server has no upper limit in the model |
| Aggregator endpoint (optional) | Web address that receives the file by HTTP POST | `endpoint` (max 500 chars) | | Browser rule `https://.*`. Help lines: "https only. Loopback and private IPs are rejected." and "Leave blank to download the document instead of pushing to an endpoint." The server checks the address only when pushing (`epg.py:363-445`): https required, not localhost/private/link-local IP literals, no redirects, 5 second timeout. A host name that resolves to a private address is not caught |
| Field map (placeholder `channel=pub-1` / `genre=category`) | Renames column headings | `field_map` | | One `key=value` per line, `#` comments allowed (lines 248-266). Only renames the CSV/X-List column headings; ignored for XMLTV (`epg.py:11-14`) |
| Create config / Save changes | Saves the setup | `POST /api/staff/epg/configs` (station fixed to `civiccast-station`, line 546) or `PATCH /api/staff/epg/configs/{id}` | | Disabled until Config ID, Channel ID filled and horizon > 0. Clearing the endpoint on edit sends null and switches the setup to download-only |
| Cancel (editing only) | Clears the form | local | | |
| Generate now (aria "Generate {id}") | Builds the file from the schedule | `POST /api/staff/epg/configs/{id}/generate` | | No confirmation. If an endpoint is set this really POSTs the whole guide to that outside address at once. Only one export runs at a time (others disabled) |
| Edit | Loads the setup into the form | local | | |
| Delete -> Confirm delete | Two-step delete | `DELETE /api/staff/epg/configs/{id}` | | Warning line: "Confirming will delete this EPG export config and stop pushing to {endpoint or 'this download workflow'}. Existing aggregator data is not deleted." (lines 450-455) |
| Download document (in result panel) | Saves the generated text | local file from memory | | Names the file `epg-export.xml` / `.csv` / `.txt` (xlist gives `.txt`) |

## What the generated file contains
Slots = schedule items in the committed state ("published" in the Schedule screen) for that channel whose start time falls in [now, now + horizon) (`schedule_adapter.py:70-100`). Each slot: start and end date and time in UTC, title (asset title), description (always blank), category (always blank, see HELP-05), rating (always blank). A station call-sign column is never added (the exporter supports it but is not given one, `epg.py:198-225,518-536`).

## States
- Identity loading: "Loading…". Identity error: "Could not load your staff identity (...)..." (lines 568-577).
- Configs loading: "Loading configs…"; load error banner with server text or "Could not load configs."; server 503 "Durable storage is not ready yet." or "EPG exporter is not ready yet."
- Empty: headline "No guide exports set up yet." body "An EPG export publishes this station's program guide in the format cable boxes and TV apps read. Create an export with the form above and it appears here." (lines 630-631)
- Result panel (lines 293-361): `{n} slot(s) · {x} KB ({format})`; if pushed: "Pushed to {url} at {time}."; if the push failed: "Push failed: {error}. The staff API is still up; retry once the aggregator endpoint recovers."; a green or amber box; for download "Download document". On a push (success or failure) no document is returned, so a failed push gives nothing to download.
- Generate request error: amber banner with server text or "Could not run the export."
- Delete error: "Could not delete the config."

## Typical task flows
1. Download once: Create config (endpoint blank), press Generate now, press Download document, hand the file to the guide provider.
2. Push to a provider: Create config with the provider's https address, press Generate now (each press re-sends the file; there is no schedule that does it automatically in this code).
3. Change the days ahead: Edit, change Horizon, Save changes.
4. Remove: Delete then Confirm delete.

## Statuses and words on this screen
Result words: "slot"/"slots", "Pushed to", "Push failed". Format labels as above. No shared status words. Row summary `ch=` `fmt=` `horizon=` are code-style abbreviations (line 395).

## Related settings / env / CLI / API
API: `/api/staff/epg/configs` (GET list, POST), `/{id}` (GET, PATCH, DELETE), `/{id}/generate`. Schedule screen controls what counts as committed. `CIVICCAST_STATION_ID` (list uses it, create sends the fixed `civiccast-station`).
There is no stored credential for the receiving service: the file is POSTed without any login (`epg.py:413-420` sends only a content type).

## Help-text findings
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

## Screenshot plan
1. Empty state with the form.
2. Form filled for an X-List download config; after Create: the row with "(no endpoint — Generate returns a downloadable document)".
3. After Generate now: green result panel with slot count, size, and "Download document".
4. Endpoint config with a bad address (push failure panel, amber) - use `https://example.invalid/x` so no real service is contacted.
5. Delete step 2 with the warning.
6. Role-denied banner (log in as meeting_operator).
Setup: a channel with at least two schedule items in "published" state starting in the next 14 days; a `setup_admin` or `publish_operator` token.

## UNVERIFIED / open questions
- UNVERIFIED: that schedule items reach "published" state through the Schedule screen's own action (only the adapter's use of `SCHEDULE_STATE_PUBLISHED` was read).
- UNVERIFIED: what real TV-guide services (TitanTV etc.) accept; the code only emits a generic 8-column CSV labelled "X-List".
- UNVERIFIED: whether any scheduled job pushes exports automatically (no caller of `EpgExporter.generate` other than the staff route was found by grep of `civiccast/`).
- UNVERIFIED: whether a non-default `CIVICCAST_STATION_ID` hides newly created configs from the list (create sends `civiccast-station`, list filters by the env value).
