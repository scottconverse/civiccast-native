# Reports  (nav id: reports, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/ReportsScreen.tsx` (line numbers below), `.../screens/reports-format.ts`,
`.../screens/contribution-format.ts:91-97` (`hasRole`), `.../api/client.ts:3040-3100`. Backend: `civiccast/reporting/router.py`, `service.py`,
`models.py`, `asrun_recorder.py`, `civiccast/egress/asrun.py`, `civiccast/egress/daemon.py:3160-3190`.
Who can open it: `Sidebar.tsx:166` `requiredRoles: ['support_admin']` - only the Support admin sees the menu entry. A person who types the address
without that role sees the banner "Reports require the support admin role. Ask your station admin for access." (line 605) and no data request is sent.
The API enforces the same single role (`reporting/router.py:70,141,166,196,220`). Tokens with scope `admin`/`operator` carry all roles (`auth/roles.py:22-24`).
Not reachable while the recovery kit is pending.

## What it is for
It lists what actually aired on the station's channels (the "as-run" log the playout engine writes), totals it per recording ("Shows"), and groups airtime hours by a
custom field such as "category" for franchise or compliance reports. Everything can be downloaded as CSV or XML. It reads the broadcast log, not viewer counts.

## What the user sees (top to bottom)
1. h1 "Reports" and text: "Franchise-compliance reports off the as-run log. The date range is half-open ([from, to)) so a single day = From today, Through tomorrow. CSV/XML downloads use the same filter set as the on-screen table. Dates are UTC midnight to UTC midnight; if your station runs on local time, factor the offset into the From / Through you pick." (lines 614-620)
2. Blue banner when the range is valid and nothing has aired: "No content has aired yet on this station. Reports will populate after your first scheduled meeting plays out." (lines 623-628)
3. Tabs: Shows (default), As-Run, Hours by Category (lines 66-73, 312-381). Arrow/Home/End keys move between tabs.
4. Filter bar "Report filters": From, Through, "Channel (optional)", and on As-Run / Hours tabs "Field key (required)" (lines 145-244). Default range: today 00:00 UTC to tomorrow 00:00 UTC (lines 83-97).
5. Per tab: Download CSV / Download XML (Shows and As-Run only), then the table.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Tab: Shows / As-Run / Hours by Category | Switch report | none | support_admin | Shows and As-Run both load on first view (comment lines 548-552) |
| From / Through (date inputs, aria "From date (UTC)" / "Through date (UTC)") | Report window `[From, Through)` | `from`, `to` as `YYYY-MM-DDT00:00:00Z` | | Must satisfy From < Through or the warning "Pick a From date that is strictly before the Through date." shows and queries/downloads stop (lines 185, 534, 642) |
| Channel (optional) | All channels, or one | `channel=` | | A drop-down "All channels" of `slug (channel_id)`; if the channel list cannot load it becomes a text box with the tag "Channel list unavailable; type the channel ID." (lines 191-209) |
| Field key (required) | Custom-field name used for the Category column / grouping | `field=` | | Default text `category`. Shown on As-Run and Hours tabs |
| Download CSV / Download XML (aria "Download shows CSV" etc.) | Saves the report with the current filters | `GET /api/staff/reports/export?type=shows|as-run&format=csv|xml&from&to&channel&field` via authenticated fetch, saved as `civiccast-{type}-{from}.{fmt}` (lines 270-282) | support_admin | Buttons show "Downloading CSV..." / "Downloading XML..."; failure shows an amber banner with the server text or "Could not download the report." The server names the file `as-run-{from}-{to}.csv` but the browser file name is the one above |
| (Hours tab) | No download buttons on this tab | | | Hours-by-category can only be read on screen |

## States
- Identity loading: "Loading…" (line 586). Identity error: "Could not load your staff identity (...). Check that you are signed in (staff token) and the local API is running, then retry." (lines 594-597)
- No role: "Reports require the support admin role. Ask your station admin for access." (line 605)
- Table loading: "Loading shows report…", "Loading as-run report…", "Loading hours-by-category report…"
- Query error: amber banner with server text, else "Could not load the shows report." / "...as-run report." / "...hours-by-category report." Backend 503 text: "Durable storage is not ready yet." (`router.py:65`)
- Empty Shows: "No air times in the selected range. As-run rows appear automatically when a meeting plays out — schedule a meeting under Run Meeting → Schedule, then run it. (Wider date ranges may surface earlier broadcasts if you already have history.)" (lines 388-392). Empty As-Run: same with "No as-run entries in the selected range." (lines 429-433).
- Hours tab without a key: "Enter the custom-field key to group by (e.g. category)." (line 712). Unknown key: "No custom field named "{key}" is defined for this station. Define it in Setup → Custom Fields, then re-run the report." (`reports-format.ts:72-77`). Key known but no airings: `No entries grouped by "{key}" in the selected range.` (line 480)

## Typical task flows
1. Day's log: leave dates at today/tomorrow, open As-Run, read, Download CSV.
2. Monthly franchise report: set From = first of month, Through = first of next month, Shows tab, Download XML.
3. Hours by category: Hours by Category tab, type the field key (e.g. `category`), read hours per category.
Tables: Shows = Asset, Plays, Total airtime, First aired (UTC), Last aired (UTC). As-Run = Channel, Start (UTC), End (UTC), Duration, Source, Asset, Category, Verified. Hours = Category, Entries, Total airtime, Hours (lines 399-405, 440-449, 488-493).

## Statuses and words on this screen
Source (raw `source_kind`): `program`, `filler`, `live`, `slate`, `spot` (`reporting/models.py:55`). The engine maps channel-graphics boards to `filler`, a forced fallback to `slate`, and never emits `spot` (`egress/asrun.py:90-108`). Verified: "yes"/"no" - rows written by the playout engine are always verified because they exist only when a proof event fired (`reporting/models.py:70-92`, `asrun_recorder.py:46`). Shows excludes anything with no library asset (filler/slate/live) (`service.py:240-250`). Not routed through `status-language.ts`. Durations rendered by `formatHms` e.g. "1h 2m 5s"; hours "12.35h".

## Related settings / env / CLI / API
`CIVICCAST_STATION_ID` (default `civiccast-station`, `router.py:80-87`). Custom Fields screen (setup_admin only) defines the category key. API: `/api/staff/reports/as-run`, `/shows`, `/hours-by-category`, `/export`.
Public: `GET /api/public/reports/as-run` is NOT authenticated and returns the same air log without internal fields (`router.py:271-293`); the staff screen gives no hint that a public copy of the as-run list exists.

## Help-text findings
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

## Screenshot plan
1. Fresh station: deploy-day banner plus the Shows empty sentence.
2. After a scheduled item has played: Shows table with rows; As-Run table with Verified "yes".
3. Hours by Category with a defined field, and with an unknown key (amber banner).
4. Invalid range warning (From after Through).
5. Channel list unavailable text box (stop the channel API) - optional.
6. Role-denied banner (log in as publish_operator only).
Setup: a station with at least two aired programs on one channel; a custom field named `category` with values on those assets; a `support_admin` token.

## UNVERIFIED / open questions
- UNVERIFIED: the exact CSV/XML columns (`service.py:574-660` not read in full).
- UNVERIFIED: that the engine writes an as-run row on every real transition in a live install (only the recorder call site `egress/daemon.py:3160-3190` was read).
- UNVERIFIED: whether the public as-run endpoint is reachable from the resident portal or only by direct request.
- UNVERIFIED: that a CIVICCAST_STATION_ID other than the default keeps reports and the underwriting/EPG creation forms consistent (the console sends the fixed value `civiccast-station` on create for EPG and underwriting).
