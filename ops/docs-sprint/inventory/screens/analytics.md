# Analytics  (nav id: analytics, section: Publish)
Source files: `civiccast/apps/portal-operator/src/screens/AnalyticsScreen.tsx` (line numbers below), `.../components/analytics/RollupChart.tsx`,
`.../api/client.ts:2025-2066`. Backend: `civiccast/analytics/router.py`, `store.py`, `pg_store.py`, `models.py`, `exports.py`;
`civiccast/app_platform/router.py:573-590` (telemetry switch); resident-side emitter `civiccast/apps/portal-public/src/analytics.ts`.
Who can open it: nav entry has no `requiredRoles` (`Sidebar.tsx:165`) so everyone signed in sees it, and the screen has no role check.
The API allows only `support_admin` and `publish_operator` (`analytics/router.py:33,47,181,243,287`). `setup_admin`, `meeting_operator` and
`records_clerk` therefore see the page frame and a bare "Report unavailable." (line 588), which does not say why (HELP-02).
Not reachable while the recovery kit is pending.

## What it is for
It shows how many residents watched recorded meetings (VOD) and live streams, for 7 days to a year, with charts and tables, and lets staff download a
spreadsheet (CSV) or a one-click "board" PDF. The numbers come only from anonymous beacons sent by the public portal; no names, IP addresses or session ids are kept.

## What the user sees (top to bottom)
1. Header: h1 "Analytics"; text "Aggregate station reporting for grants, franchise updates, and operator planning."; buttons "Export CSV" and "Generate Board PDF" (lines 495-513).
2. Toolbar (lines 516-579): chart type buttons "bar" / "line" (shown with CSS capitalise), a drop-down labelled "Metric" (Viewer Count / Time Viewed / Peak Concurrent), range buttons 7d / 30d / Quarter / Year (default 30d), stream buttons VOD / LIVE / ALL (default ALL).
3. "Loading report..." or "Report unavailable." box.
4. If telemetry is off: box "Audience telemetry is off" (lines 210-224).
5. Panels "VOD" and "Live": stats line `{n} views · {x}h watched · peak {p}`, then two charts "Top by {metric}" and "{metric} over time" (lines 226-293). Peak Concurrent on VOD shows "Peak Concurrent applies to live streams only."
6. Link "Show rollup data table ({n} rows)" / "Hide ..." expanding a table: Stream, Bucket, Subject, Viewer Count, Time Viewed (h), Peak Concurrent (lines 295-326, 622-633).
7. Four tiles: "Asset views" (`{n} day window`), "View hours" ("Aggregate playback time"), "Live peak" ("Highest reported sample"), "Podcast downloads" ("Aggregate episode count") (lines 423-428).
8. Box "Privacy boundary" with the server text and "Generated {time}" (lines 430-434).
9. Tables "Asset Time Series", "Live Concurrent Viewers", then six small tables Geography, Device, Platform, Caption Usage, Audio Usage, Subscription Growth (lines 436-446).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Export CSV (line 509) | Downloads a flat CSV of rollups | `GET /api/staff/analytics/export.csv?stream_type=&bucket=&range_days=` -> file `analytics-rollups-{vod|live}-{N}d.csv` (lines 483-491) | support_admin, publish_operator | With stream = ALL it exports VOD only (line 484), with no notice. No error handling: a failed download shows nothing |
| Generate Board PDF (line 371) | Opens a small panel "Include sections": Totals, Top content, Year-over-year, Live-event peaks (all ticked) | none until the next button | same | |
| Download PDF (line 404) | Builds and downloads the PDF | `POST /api/staff/analytics/reports/board-pdf` with range = now minus N days to now, `station_label: "CivicCast station"` (lines 345-352); file `audience-report-{date}.pdf` | same | Also saves a snapshot of the numbers in the database when durable storage is on (`router.py:296-328`), with the operator id; on the file-store it is not saved. Failure text: "Could not generate the board PDF. Try again." (line 356). Label shows "Generating…" |
| bar / line | Switches the "over time" chart | local | | |
| Metric | Which number the charts show | local (rollups already contain all three) | | |
| 7d / 30d / Quarter / Year | Window = 7, 30, 90, 365 days | refetches report and rollups | | Server accepts 1-366 days |
| VOD / LIVE / ALL | Which panels show | refetches | | |
| Show/Hide rollup data table | Toggles table | local | | Counts rows of both panels |

## States
- Loading: "Loading report..." (line 583); inside a panel "Loading…" (line 269).
- Error: "Report unavailable." (line 588). Same text for 403, 500 and offline.
- Telemetry off (`ingest_configured` false): "Audience telemetry is off" / "Turn it on in Setup to collect Viewer Count and Time Viewed. The Reports tab (as-run / proof-of-performance) still works — it reads the program log, not the beacon." (lines 217-221). The switch is two environment settings, `CIVICCAST_PUBLIC_ANALYTICS_KEY` or `CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS` (`app_platform/router.py:573-590`); the operator console has no Setup control for it (grep of the console source for "telemetry" finds only this banner).
- No data tables: "No viewer data yet — rows appear once residents start watching this station." (line 130); "No playback data yet — rows appear once published recordings get their first views." (line 160); "No live samples yet — rows appear after this station's first live stream." (line 193); "No rollup rows for this range — pick a wider range, or check back after the station has aired content." (line 311).
- File-store mode (no durable database): rollups are always empty and charts are blank (`analytics/store.py:rollups` returns `[]`); the Asset/Live tables still fill from raw events.

## Typical task flows
1. Monthly numbers for a grant: choose 30d, ALL, press Export CSV (VOD only) or Generate Board PDF, leave all four sections ticked, Download PDF.
2. Check a live night: choose 7d and LIVE; read Peak Concurrent and the "Live Concurrent Viewers" table.
3. Spot a problem: "Audience telemetry is off" means nothing is being counted at all.

## Statuses and words on this screen
Metric names Viewer Count / Time Viewed / Peak Concurrent; tile "Live peak" = highest peak among the samples; "Asset views" and "View hours" come from the per-day asset table; "Podcast downloads" is a count of podcast events. Beacon events counted: `playback_start`, `playback_heartbeat`, `playback_complete`, `playback_error`, `schedule_browse` (`portal-public/src/analytics.ts:19-23`). Privacy text from the server: `aggregate-only-no-session-ip-or-viewer-identity` (`analytics/store.py:141`) displayed verbatim. Events older than 366 days are dropped (default retention, `store.py:30`; `CIVICCAST_ANALYTICS_RETENTION_DAYS`, max 366).

## Related settings / env / CLI / API
`CIVICCAST_PUBLIC_ANALYTICS_KEY`, `CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS`, `CIVICCAST_ANALYTICS_RETENTION_DAYS`, `CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS`.
API: `/api/staff/analytics/reports/overview`, `/rollups`, `/export.csv`, `/reports/board-pdf`; also `/reports/audience?kind=weekly|monthly|custom&format=csv|xml` (franchise "audience report", any of the five roles; no button on this screen). Public ingest `POST /api/public/app/analytics/events`.

## Help-text findings
- [HELP-01] line 219 "Turn it on in Setup to collect Viewer Count and Time Viewed." — no Setup screen has such a switch; it is a server environment setting. Say "Ask the person who installed CivicCast to turn on audience counting (setting CIVICCAST_PUBLIC_ANALYTICS_KEY or CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS)", or add the control.
- [HELP-02] line 588 "Report unavailable." — hides the real reason. A role without access gets a 403; show "Analytics is for Support admins and Publish operators. Ask your station admin for access." (compare Reports/EPG, which do this). Hide the nav item for other roles (nav has no `requiredRoles`).
- [HELP-03] line 432 — the Privacy boundary box prints a machine string, `aggregate-only-no-session-ip-or-viewer-identity`. Replace with: "Counts only. CivicCast stores no names, IP addresses or viewer identifiers."
- [HELP-04] line 509 "Export CSV" — silently exports VOD only when ALL is selected and exports only the rollup table, not what the page shows. Say "Exports the VOD (or Live) rollup table for the chosen range" and handle failures.
- [HELP-05] lines 345-351 — the Board PDF always covers "now minus N days" and ignores the VOD/LIVE filter; the station name on the PDF is fixed as "CivicCast station" (line 351) even if the station has a name. Tell the person "PDF title says 'CivicCast station'" or pass the real station name.
- [HELP-06] line 427 "Podcast downloads" "Aggregate episode count" — Publish says podcasts are "coming in a future release", so this number is expected to be 0; explain or hide until podcasts ship.
- [HELP-07] lines 423-428 — "Live peak" detail "Highest reported sample" and "View hours" "Aggregate playback time" are jargon-adjacent; define "A view = one playback start; a viewer is not identified or de-duplicated" (UNVERIFIED how views are counted, see below).
- [HELP-08] lines 25-30 "Quarter" and "Year" mean 90 and 365 days rolling, not calendar periods; label "90d" / "365d" or say so.
- [HELP-09] lines 530-531 button labels "bar"/"line" are lowercase words with no icon or name; use "Bar chart" / "Line chart".

## Screenshot plan
1. Telemetry-off state on a fresh install (banner visible, tables showing their empty sentences).
2. Populated state: set the ingest key, play a recording and a live stream in the portal, wait for rollups (UNVERIFIED rollup delay), capture toolbar, VOD and Live panels, tiles, privacy box, tables.
3. Board PDF panel open.
4. A `meeting_operator` or `setup_admin` session showing "Report unavailable."
Setup: `CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS` set to the portal origin; durable database mode.

## UNVERIFIED / open questions
- UNVERIFIED: rollup refresh timing (worker `AnalyticsRollupWorker` in `app.py:1295-1306`; poll interval not read) and therefore how long after viewing the charts update.
- UNVERIFIED: how "views" and "viewer count" are computed (de-duplication rules in `pg_store.py`, `store.py::_asset_views` not read).
- UNVERIFIED: what the board PDF looks like (generator `analytics/exports.py` not read).
- UNVERIFIED: that `RollupChart` handles empty data without a visible placeholder.
- UNVERIFIED: whether the on-page "Geography" table is ever filled (the portal beacon sends only coarse `properties`; no geography emitter found in `portal-public/src/analytics.ts`, lines 1-80 read).
