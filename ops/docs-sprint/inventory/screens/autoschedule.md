# Auto-schedule  (nav id: autoschedule, section: Run Meeting)
Path prefix `S` = `civiccast/apps/portal-operator/src`; backend under `civiccast/schedule/`.
Source files: `S/screens/AutoScheduleScreen.tsx`, `S/screens/autoschedule-format.ts`, `S/screens/status-language.ts` (`stateLabel`), `S/components/EmptyState.tsx`; backend `autoschedule_router.py`, `autoschedule_service.py`, `autoschedule_materializer.py`, `autoschedule_worker.py`, `autoschedule_models.py`, `app.py:985-1030,1472-1480`.
Who can open it: nav entry visible only to `publish_operator`, `setup_admin`, `support_admin` (`S/components/shell/Sidebar.tsx:129`). Route `/auto-schedule` (`S/routes.ts:17`). Inside: read = those three roles; write and compile = `publish_operator` or `setup_admin` only (`autoschedule_router.py:42-43`; `AutoScheduleScreen.tsx:850-854`). Others who reach the URL see `Viewing and managing <saved searches|dayparts|auto-schedule rules> requires the publish operator, setup admin, or support admin role.` (`:72-78`).

## What it is for
Auto-schedule fills a channel's air time by rule instead of one item at a time. You define a **saved search** (which recordings qualify), a **daypart** (a recurring time window on a channel, e.g. weeknights 18:00-22:00), and a **rule** joining the two. A compile run places one matching recording in each open slot of the daypart over the next 14-60 days. **Items created this way are written directly as Published, i.e. they are approved to air with no separate Commit-to-Air step** (`autoschedule_materializer.py:17-27,285-297`). A background job runs the compile every hour by default (`autoschedule_worker.py:55`; started in `app.py:1472-1481`; off only if `CIVICCAST_AUTOSCHEDULE=off`, `app.py:1472-1481`), so a saved rule can start putting programs on air without anyone pressing `Compile now`.

## What the user sees
1. Eyebrow `Run Meeting`, heading `Auto-schedule`, intro: "Define saved searches and dayparts, connect them with rules, then preview and compile to fill the schedule automatically. Compiling a rule approves its picked items to air — reviewing the preview before you compile is the approval step. Only manually-added schedule items need a separate Commit-to-Air approval." (`:857-867`).
2. Section `Saved searches` ("Named queries over your library. A rule fills its daypart by picking from one of these.").
3. Section `Dayparts` ("Recurring time windows on a channel that a rule fills (e.g. weeknights 6–10pm). Times are the station's local wall-clock (set by CIVICCAST_STATION_TZ; UTC if unset).").
4. Section `Auto-schedule rules` ("Each rule fills a daypart from a saved search. Simulate to preview; rules feed the commit gate before air.").
5. Section `Compile schedule` (only for writers).
Each list/section has its own `Add ...` button (writers only) and card rows with `Edit`/`Delete`.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Add saved search` / `Close` | Opens the search form | none | write | |
| Search form: `Name` (placeholder "Example: Recent council meetings"), `Meeting body (exact)` ("Example: City Council"), `Title contains` ("Example: budget"), `Min length (minutes)`, `Max length (minutes)`, `Include states` checkboxes, `Newest published first` | Describes which assets qualify | | write | State checkbox labels come from `stateLabel()` (`ASSET_STATES` = validated, recorded, pending_ingest, ingesting, rejected; default checked: validated, recorded) (`:46-52,:152`). Always sorts by published date (`order_by: 'published_at'`). Minutes blank = no limit. |
| `Create saved search` (`Saving...`) / `Save changes` | Saves | `POST /api/staff/auto-schedule/saved-searches`; edit = `PUT .../{id}` (`S/api/client.ts:2806-2824`; router `autoschedule_router.py:125-188`) | write | Disabled until Name filled. Errors: server text or `The saved search could not be saved.` |
| Search `Edit` / `Close`, `Delete` -> `Confirm delete?` | Edit inline; two-click delete | `DELETE .../{id}` | write | If rules use it, the confirm step adds red "Used by N rule(s) — deleting it stops them scheduling." (`:268-271`). |
| `Add daypart` / `Close` | Opens form | none | write | |
| Daypart form: `Channel` (free-text, placeholder `public`), `Name` (placeholder `Prime time`), `Start` (time, default 18:00), `End` (time, default 22:00) with note "00:00 = midnight (end of day). An end before the start wraps past midnight.", `Days` checkboxes Mon-Sun (default Mon-Fri) | Describes the window | | write | Channel is typed, not chosen from a list: a mistyped id creates a daypart for a channel that does not exist (UNVERIFIED whether the server rejects it). Needs a name, a channel and at least one day. Times are stored as minutes after midnight (`hhmmToMinute`). |
| `Create daypart` (`Saving...`) / `Save changes`; `Edit`; `Delete` -> `Confirm delete?` | Save / edit / delete | `POST/PUT/DELETE /api/staff/auto-schedule/blocks[/{id}]` | write | Same "Used by N rule(s)" warning. Card line: `<channel> · 18:00–22:00 · Mon, Tue, Wed, Thu, Fri`. |
| `Add rule` / `Close` | Opens rule form | none | write | |
| Rule form: `Name` (placeholder "Fill prime with council"), `Pick strategy` (`Newest first` / `First match` / `Random`), `Saved search` (`Choose…`), `Daypart` (`Choose…`, shown as `<name> (<channel>)`), `Rolling window (days, 14–60)` default 30, `No-repeat window (days)` default 0 | Joins search to daypart | | write | Invalid window: red "Rolling window must be a whole number from 14 to 60 days." Rule channel is taken from the chosen daypart. Priority fixed at 100 and enabled at true for new rules (`:700-710`). |
| `Create rule` (`Saving...`) / `Save changes`; `Edit`; `Delete` -> `Confirm delete?` | Save / edit / delete | `POST/PUT/DELETE /api/staff/auto-schedule/rules[/{id}]` | write | Deleting a rule shows no warning about items it already placed (UNVERIFIED what happens to them). |
| Rule card `Simulate` (`Simulating...`) | Dry-run of that rule; writes nothing | `POST /api/staff/auto-schedule/rules/{id}/preview` | read roles (incl. support_admin) | Shows "Would schedule N of M upcoming slots." then up to 30 lines `<date time>  <title>  <pill>`. Pills: `Will air`, `Already scheduled`, `No eligible video`, `No usable duration` (`autoschedule-format.ts:26-37`). Missing search/daypart: "This rule points at a saved search or daypart that no longer exists." |
| `Compile now` (`Compiling...`) in `Compile schedule` | Runs all enabled rules now and adds their picks | `POST /api/staff/auto-schedule/compile` | write (card hidden otherwise) | Result: "Added N scheduled items across M rules." No confirmation dialog. |

## States
- Role pending: `Loading <what>…`.
- Empty: `No saved searches yet.` / "A saved search collects the recordings that match rules you set — the newest council meetings, a weekly series, a category. Create one here and auto-schedule uses it to pick what airs."; `No dayparts yet.` / "A daypart is a block of air time you hand over to auto-schedule — weekday evenings, overnight repeats. Create one here and rules can start filling it."; `No rules yet.` / "A rule connects a saved search to a daypart so the channel fills itself with matching programs. Create a saved search and a daypart first, then add a rule here to connect them."
- Errors: red box with server detail, or `The saved search could not be saved.` / `The daypart could not be saved.` / `The rule could not be saved.` / `Simulation failed.` / `Compile failed.`; storage not ready -> 503 "Durable storage is not ready..." (`autoschedule_router.py:66-68`).
- Disabled rule shows a `disabled` pill (`:588-592`), but nothing on this screen can disable one.

## Typical task flows
1. First rule: `Add saved search` (e.g. Meeting body "City Council") -> `Add daypart` (channel, times, days) -> `Add rule` -> `Simulate` -> `Compile now`.
2. Check a rule before it goes live: `Simulate`, read `Will air` / `Already scheduled` pills.
3. Retire a rule: `Delete` -> `Confirm delete?` (placed items remain unless removed elsewhere - UNVERIFIED).

## Statuses and words on this screen
| Word | Meaning |
|---|---|
| `Will air` | slot is open and an eligible asset was picked (`fill`) |
| `Already scheduled` | slot already has an item (`occupied`) |
| `No eligible video` | no asset matches (`no_asset`) |
| `No usable duration` | picked asset has no length (`unplayable`) |
| `Newest first` / `First match` / `Random` | pick strategy (`newest`, `top_result`, `random_result`) |
| `<n>d window` | rolling window days shown on each rule card |
Asset state labels use `stateLabel` from `status-language.ts`.

## Related settings / env / CLI / API
`/api/staff/auto-schedule/{saved-searches,blocks,rules,rules/{id}/preview,compile}`; `CIVICCAST_AUTOSCHEDULE` (off disables the hourly background compile); station time zone (`CIVICCAST_STATION_TZ` override or the `station_timezone` saved during first setup; UTC if neither, `app.py:985-1030`); Schedule screen (shows the created items as Published); Channel Ops.

## Help-text findings
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

## Screenshot plan
(a) Whole page with one saved search, one daypart, one rule; (b) rule form with the 14-60 error; (c) `Simulate` result with mixed pills; (d) `Confirm delete?` with the "Used by 1 rule" warning; (e) `Compile schedule` success line; (f) empty states; (g) support_admin read-only view (no Add/Edit/Delete/Compile); (h) AccessNote as another role by URL. Setup: validated assets with a meeting body set; a channel; admin identity.

## UNVERIFIED / open questions
- UNVERIFIED: what happens to already-placed Published items when a rule, saved search or daypart is deleted or edited (store/materializer delete paths not read).
- UNVERIFIED: whether the server rejects a daypart whose channel id does not exist.
- UNVERIFIED: how overlapping dayparts on one channel are resolved beyond "priority, lower wins" (`autoschedule_models.py:394`); UI fixes priority at 100.
- UNVERIFIED: whether items placed by a rule appear on the Schedule screen's `Cancel` path (they are Published; Schedule only offers Cancel on Scheduled).
- Note: `autoschedule_worker.py:11-12` and `autoschedule_router.py:416` docstrings still say the items are `scheduled` and "never put anything on air"; the materializer docstring and code say Published. Code in `autoschedule_materializer.py:285-297` was treated as authoritative; a code owner should confirm the 2026-07-08 decision is current.
