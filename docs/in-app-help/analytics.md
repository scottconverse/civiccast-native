# Analytics (nav id: analytics)

Console group: Publish. Spec for the in-app help of the audience numbers screen. Written against beta.10. Paths are under `civiccast/apps/portal-operator/src/`; line numbers are in `screens/AnalyticsScreen.tsx` unless stated.

## Where the help text lives now
- Heading and intro 497-499; Export CSV 509; chart buttons 518-531; range labels 25-30 (Quarter 28, Year 29); metric drop-down in the toolbar 516-579.
- Generate Board PDF 371; "Include sections" 378; Download PDF 404; PDF failure 356; station label 351.
- Loading 583; error 588.
- Telemetry-off box 210-224 (text 217-221).
- Panel empty sentences 130, 160, 193, 311; "Peak Concurrent applies to live streams only." 265.
- Tiles 424-427; Privacy boundary 431-434.
- Nav entry and roles: `components/shell/Sidebar.tsx:165`; API roles `civiccast/analytics/router.py:33,47,181,243,287`.

## Current text
| String | Where | Source line |
|---|---|---|
| "Aggregate station reporting for grants, franchise updates, and operator planning." | Intro | :499 |
| "Export CSV" | Button | :509 |
| "bar" / "line" | Chart buttons | :518 |
| "Quarter" / "Year" (90 and 365 days) | Range buttons | :28-29 |
| "Generate Board PDF"; "Include sections" (Totals, Top content, Year-over-year, Live-event peaks) | PDF panel | :371, 378 |
| "Could not generate the board PDF. Try again." | PDF error | :356 |
| "Report unavailable." (same text for no role, server error and offline) | Error | :588 |
| "Audience telemetry is off" / "Turn it on in Setup to collect Viewer Count and Time Viewed. The Reports tab (as-run / proof-of-performance) still works — it reads the program log, not the beacon." | Banner | :217-221 |
| "No viewer data yet — rows appear once residents start watching this station." | Empty table | :130 |
| "No playback data yet — rows appear once published recordings get their first views." | Empty table | :160 |
| "No live samples yet — rows appear after this station's first live stream." | Empty table | :193 |
| "No rollup rows for this range — pick a wider range, or check back after the station has aired content." | Empty table | :311 |
| "Asset views" ("{n} day window"); "View hours" ("Aggregate playback time"); "Live peak" ("Highest reported sample"); "Podcast downloads" ("Aggregate episode count") | Tiles | :424-427 |
| "Privacy boundary" with the machine phrase `aggregate-only-no-session-ip-or-viewer-identity` | Box | :431 (server text, `analytics/store.py:141`) |

## What the screen really does
It shows play counts for recorded meetings and live streams for the last 7, 30, 90 or 365 days, counted back from now (not calendar quarters or years). The numbers come only from anonymous messages the resident website sends: playback start, heartbeat, finish, error and schedule browsing; no names, IP addresses or viewer identifiers are kept. A view is one play start; the same person twice counts twice. Most of the small tables (Geography, Device, Platform, Caption Usage, Audio Usage, Subscription Growth) and the Live peak tile stay empty because the website does not send that information. Export CSV with ALL selected exports the VOD table only. The Board PDF ignores the VOD/LIVE/ALL buttons, uses "now minus the range", and its title is always "CivicCast station". Counting is off until an IT person changes a station setting; nothing in the console turns it on. Only support_admin and publish_operator can load the numbers; everyone else sees the page frame and "Report unavailable."

## Mismatches
| ID | Text says | What really happens | Severity |
|---|---|---|---|
| HELP-01 | "Turn it on in Setup" | No Setup screen has the switch; it is a server setting (`CIVICCAST_PUBLIC_ANALYTICS_KEY` or `CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS`, `app_platform/router.py:573-590`) | blocks work |
| HELP-02 | "Report unavailable." | Hides the real reason: a role without access gets a 403 | misleading |
| HELP-03 | Privacy boundary prints a machine phrase | Means counts only | cosmetic |
| HELP-04 | "Export CSV" | ALL exports VOD only; only the rollup table; a failed download shows nothing (`:484`) | misleading |
| HELP-05 | Board PDF | Ignores VOD/LIVE; title fixed "CivicCast station" (`:345-352`) | misleading |
| HELP-06 | "Podcast downloads" "Aggregate episode count" | Podcasts are "coming in a future release" on Publish; expect 0 | misleading |
| HELP-07 | "Live peak", "View hours" details | Jargon; a view is not a unique person; UNVERIFIED de-duplication rules | misleading |
| HELP-08 | "Quarter", "Year" | Rolling 90 and 365 days | misleading |
| HELP-09 | Lowercase "bar" / "line" | No chart name or icon | cosmetic |
| NEW-1 | "The Reports tab (as-run / proof-of-performance) still works" | Reports is a separate screen in the menu, shown only to support_admin | misleading |
| NEW-2 | Empty tables imply data will arrive | Geography, Device, Platform, Caption Usage, Audio Usage, Subscription Growth and Live peak stay empty in beta.10 because the website never sends that data (manual ch.16) | misleading |

## Proposed text
What this is for (new, under heading): "How many times residents started a recording or a live stream on the station's website and apps. It does not count people watching on cable."
Who can use it (new): "Support admin and publish operator. Other roles see an empty page."
Intro: "Counts of plays for grants, franchise updates and planning. A view is one time someone starts playing; the same person watching twice counts twice. No names, IP addresses or viewer identifiers are stored."
Range buttons: "7 days", "30 days", "90 days", "365 days" (counted back from now).
Chart buttons: "Bar chart" / "Line chart".
Telemetry-off box: "Counting is switched off, so nothing is being counted. Ask the person who installed CivicCast to turn on audience counting (settings CIVICCAST_PUBLIC_ANALYTICS_KEY or CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS, then restart CivicCast). The Reports screen, for the support admin role, still works; it reads what aired, not who watched."
After fix (a Setup switch exists): "Turn on audience counting in Setup."
Role error (replace "Report unavailable."): "Analytics is for support admins and publish operators. Ask your station administrator for access." For other failures: "The report could not load. Try again; if it repeats, tell your IT person."
Privacy box: "Counts only. CivicCast stores no names, IP addresses or viewer identifiers." Show "Report made {time}".
Tile details: "Asset views" = "Plays of recordings in the last {n} days"; "View hours" = "Time watched, added up from where each play finished; people who stop early add nothing"; "Live peak" = "Most people watching a live stream at once, if reported. Usually empty in beta.10"; "Podcast downloads" = "Always 0 in beta.10; podcasts are not available yet".
Small tables: add one line "Empty in beta.10: the website does not report this information."
Export CSV helper: "Saves the VOD or Live totals table for the chosen range. With ALL selected you get VOD only. Choose LIVE to get the live table." After fix: handle ALL and show an error if the download fails.
Board PDF helper: "A one-click report for a board or grant. It covers the last {n} days for VOD and live together, whatever VOD/LIVE/ALL says. The title says CivicCast station; add your station name by hand." Failure: keep.

## Notes for the coder
- Edit `AnalyticsScreen.tsx` and `components/analytics/RollupChart.tsx`; role-based nav entry in `components/shell/Sidebar.tsx:165` (add `requiredRoles: ['support_admin', 'publish_operator']`).
- Tests that pin strings (verified by grep): `screens/AnalyticsScreen.test.tsx` ("Report unavailable", "Audience telemetry", "loading report"). Update with HELP-01 and HELP-02 changes.
- Code fixes, not text fixes: a Setup control for the analytics switch (HELP-01); Export CSV for ALL and error handling (HELP-04); PDF station name and filter (HELP-05); role message instead of "Report unavailable." (HELP-02); more data from the website beacon (NEW-2).
- UNVERIFIED in the inventory: rollup refresh timing; view de-duplication; what the board PDF looks like; whether Geography is ever filled.
