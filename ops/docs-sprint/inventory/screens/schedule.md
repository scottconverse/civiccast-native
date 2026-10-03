# Schedule  (nav id: schedule, section: Run Meeting)
Path prefix `S` = `civiccast/apps/portal-operator/src`; backend under `civiccast/`.
Source files: `S/screens/ScheduleScreen.tsx`, `S/components/schedule/ScheduleDrawer.tsx`, `S/screens/scheduleGrouping.ts`, `S/types/schedule.ts`, `S/screens/CommitToAirPanel.tsx` (`DryRunReview`), `S/components/ConfirmDialog.tsx`; backend `schedule/router.py`, `schedule/store.py`, `schedule/playout_router.py`, `schedule/commit_service.py`, `egress/source_plan.py`, `cable/router.py`.
Who can open it: nav entry has no `requiredRoles` (`S/components/shell/Sidebar.tsx:128`), so every signed-in operator sees it. Route `/schedule` (`/today` is an alias to it, `S/routes.ts:55`). **Reading the list needs `publish_operator`, `setup_admin` or `support_admin`** (`schedule/router.py:1242`, `_READ_ROLES` :130); creating, cancelling, and Publish to residents need `publish_operator` or `setup_admin` (`router.py:1181,1317`, `playout_router.py:119,153`). A `meeting_operator` or `records_clerk` gets the red "Could not load schedule." box.

## What it is for
Schedule is the list/calendar of one-off scheduled items on the station's channels. Each item is a **Premiere** (a recorded asset placed on a channel at a start time for a set length) or an **Embargo** (a single release moment, no length). A new premiere is created in state Scheduled and does not air or appear to residents until someone presses `Publish to residents` (the Commit-to-Air check); items from recurring slots (Program Guide) also land here as Scheduled.

## What the user sees
1. Eyebrow `Workflow`, heading `Schedule`, line "Week of <Mon d> – <d>, <year> · times shown in your browser timezone. Conflicts on the same channel are rejected at the database layer." (`ScheduleScreen.tsx:856-862`).
2. Toolbar: tabs `week` / `list` (shown capitalized by CSS), `‹` (aria-label `Previous week`), `Today`, `›` (`Next week`), button `New scheduled item` at right (`:869-929`). Phones (<768 px wide) start in List view (`:784-787`).
3. Body: loading skeleton, error box, empty state, week grid, or day-grouped list (below).
4. A slide-in drawer `New scheduled item` and a confirm dialog (below).

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `week` / `list` tabs | Switch view | none | all | List shows **all** items (not just this week) (`:968-969`); the "Week of" heading does not change meaning. |
| `‹` `Today` `›` | Move the week (Monday start) | none | all | |
| Week-grid event block (aria-label e.g. `Premiere · <title> · 7:00 PM – 8:00 PM on <channel_id>`) | Click switches to List view anchored on that week | none | all | `:946-956`; comment says a detail drawer is "queued for v0.4". Cancelled items show struck-through at 55% opacity. Embargo shows as a 30-minute marker. |
| Note bar `Showing 5 am–11 pm (auto-extended to cover events outside business hours).` | Info only | | | appears when hours differ from the default 6 am-10 pm (`:350-361`) |
| `New scheduled item` | Opens drawer | none | button visible to all; creation fails with 403 for non-publishers | `:921-928` |
| Drawer `Mode`: cards `Premiere` ("Publish a recorded asset to the public portal at a scheduled time.") / `Embargo` ("Approve now; release becomes public at the embargo time.") | Chooses mode | | | descriptions from `S/types/schedule.ts:34-44` |
| Drawer `Asset` dropdown (`<title> · <asset_id>`) | Picks the asset | `GET /api/staff/assets` | any signed-in | Only assets with state `validated` are listed (`ScheduleDrawer.tsx:99-101`); first is preselected. Help line: "Only validated assets are eligible. Trim and chapter edits are applied at packaging time." If none: "**No validated assets.** Upload and validate an asset in the Assets tab first." |
| Drawer `Channel` dropdown | Picks channel (display names) | `GET /api/staff/cable/channels` (all operator roles, `cable/router.py:164-170`) | | Errors: "Could not load this station's channels. Close and retry." / "No channels are configured on this station yet." |
| Drawer `Start at` (premiere) / `Release at` (embargo) | `datetime-local`, default = next full hour | | | Preview line "<Day, Mon d, h:mm> (<IANA tz>)". Blank/invalid: "Enter a date and time to schedule this." |
| Drawer `Duration (min)` (premiere only) | whole minutes, default 60, min 1 | sent as seconds; server max 14 days (1,209,600 s) (`schedule/models.py:934-937`) | | Not shown for embargo |
| Drawer yellow box "Timezone check: this time is saved from the browser timezone shown above. During daylight-saving changes, confirm the local meeting time against the station calendar before creating the schedule item." | Info | | | `:416-424` |
| Drawer `Notes (optional)` (placeholder "Operator notes — visible in the audit log.") | Free text, max 2000 chars server-side | | | |
| Drawer `Schedule premiere` / `Schedule embargo` (`Scheduling…`) | Creates the item (state Scheduled) | `POST /api/staff/schedule` | `publish_operator`/`setup_admin` | Success: drawer closes, toast "Scheduled." + "`Premiere · <title> · Tue, Oct 6, 7:00 PM`". Overlap on same channel: red "Time slot conflicts." + server message + "Existing: <asset_id> on <channel_id> at <time>" + "**Next step.** Pick a different time, channel, or cancel the conflicting item." (embargoes never conflict, `router.py:1199-1204`). Other failures: "Could not schedule." + detail. 404 if the asset id does not exist. |
| Drawer `Cancel`, `✕` (aria `Close drawer`), backdrop, Esc | Close without saving | none | | |
| List row `Publish to residents` (only premiere + state Scheduled) | Runs a dry-run check, then shows the review panel | `POST /api/staff/playout/prepare-commit` with `occurrence_id = manual:<item id>` | `publish_operator`/`setup_admin`; for others the button is shown disabled and a grey note explains | While checking: `Checking…`. Failure text: "Could not check whether this is ready to publish." |
| Review panel (`DryRunReview`): badge `Safe to air` or `Not safe to air yet`, time + minutes, media problem line, `Clashes with N other program(s) already scheduled:` list, `Dead-air gap before this program (it can still air):` list | Shows what the check found | | | `CommitToAirPanel.tsx:108-147`. Approve button disabled unless the check passed and role allows (`canApprove`). Conflict = fail; gap = information only (`commit_service.py:140-165`, module doc). |
| Review `Publish to residents` (`Publishing…`) | Re-checks, then flips item to Published, records who approved, and nudges the playout engine | `POST /api/staff/playout/commit` | same | Toast "Visible to residents." + title. Error "Could not publish this to residents." (409 clash / 422 media became unplayable). The toast is shown on any 201 even if the engine nudge failed (the report then holds `dispatch_status: error`) (`ScheduleScreen.tsx:575-584`; `playout_router.py:168-171`). |
| Review `Cancel` | Closes review | none | | |
| List row `Cancel` (state Scheduled only) | Opens confirm dialog: title `Cancel scheduled item for "<name>"?`, body "The item is removed from the schedule and will not air at its scheduled time. This cannot be undone — you would need to create a new scheduled item to air it again.", buttons `Cancel scheduled item` / `Cancel` | `POST /api/staff/schedule/{id}/cancel` | `publish_operator`/`setup_admin` (button visible to all) | Toast "Cancelled." or "Could not cancel scheduled item." Published items show **no** Cancel button here even though the API allows cancelling them (`store.py:1047-1070`). |

## States
- Loading: three grey pulsing bars.
- Error: red box, heading `Could not load schedule.` (or `Durable storage is not ready.` on HTTP 503), the server message, "**Next step.** Try again, or check the server logs for more detail." / "Open Setup, prepare durable storage, then return here.", buttons `Go to Setup` (503 only, link `#/setup`) and `Retry` (`:229-271`). Role-denied text from server: "This action requires one of these CivicCast roles: publish_operator, setup_admin, support_admin." (`auth/roles.py:80-97`).
- Empty (no items at all): "Nothing scheduled this week." / "Schedule a premiere to publish a recorded asset at a specific time, or an embargo to release an approved asset later. Conflicts are caught at the database layer before the form submits." + button `New scheduled item`.
- Week view with items elsewhere: "Nothing scheduled this week. Use the arrows to browse, or switch to List view to see all items."
- Unreadable time rows: "1 scheduled item has an air time this station cannot read, so it is not shown below." (or `N scheduled items have air times ...`) + "The rest of the schedule is complete and unaffected. Cancel and re-schedule them, or send this list to support:" + ids (`:607-626`).
- Non-publisher banner above the list: "You can view the schedule here. Publishing a premiere to residents requires the publish operator or setup admin role." (`:598-606`).

## Typical task flows
1. Put a recording on a channel once: `New scheduled item` -> Mode Premiere -> pick asset, channel, start, duration -> `Schedule premiere` -> switch to `list` -> `Publish to residents` on the new row -> read the panel -> `Publish to residents`.
2. Remove a mistaken item: list view -> `Cancel` -> `Cancel scheduled item`.
3. Clear a clash: the drawer names the existing item; cancel it (list view) or pick another time.

## Statuses and words on this screen
| Word | Meaning (code) |
|---|---|
| Mode chip `Premiere` / `Embargo` | `S/types/schedule.ts:34-44` |
| State chip `Scheduled` | created, not yet approved to air; for premieres the row also says `Not yet visible to residents` (`ScheduleScreen.tsx:210-218`) |
| `Published` | approved/committed (or auto-approved by Auto-schedule); premieres say `Visible to residents`; airs via source plan (`egress/source_plan.py:507-511`) and appears in the public Coming Up list (`schedule/router.py:199-236`) |
| `Cancelled` | withdrawn; greyed out |
| `Today` chip | the current day group |
| `Safe to air` / `Not safe to air yet` | dry-run result |
Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`/api/staff/schedule` (list/create/get/cancel), `/api/staff/playout/{prepare-commit,commit,rollback/{id}}`, `/api/public/schedule/coming-up`, `/api/staff/cable/channels`, `/api/staff/assets`; Channel Ops (Commit-to-Air panel, rollback); Program Guide and Auto-schedule feed this same table.

## Help-text findings
- [HELP-01] `S/types/schedule.ts:37-39` — Premiere: "Publish a recorded asset to the public portal at a scheduled time." — Wrong/misleading: saving a premiere only creates a Scheduled draft; nothing airs or shows to residents until `Publish to residents` is pressed (`egress/source_plan.py:507-511`, `schedule/router.py:199-222`). The router docstring even says the opposite ("airs automatically once its air time arrives", `router.py:1206-1208`) - do not copy it. — "Puts a recorded asset on a channel at a set time. After you save it, press Publish to residents to approve it to air."
- [HELP-02] `S/types/schedule.ts:41-44` — Embargo: "Approve now; release becomes public at the embargo time." — No code found that releases an embargo: embargo rows are excluded from the source plan, from Coming Up, and cannot be committed ("embargo entries publish at a single moment and cannot be committed to air", `commit_service.py:154-161`). Promises behavior I could not find. — Hide Embargo or say what it really does; until verified the manual should not describe it as working. (UNVERIFIED, see below.)
- [HELP-03] `Sidebar.tsx:128` — nav visible to all roles, but a meeting_operator/records_clerk only sees an error with "check the server logs" advice (`ScheduleScreen.tsx:248`). — Show "Viewing the schedule needs the publish operator, setup admin or support admin role."
- [HELP-04] `ScheduleDrawer.tsx:99-101,272-283` — only `validated` assets listed; assets in state `recorded` (everything captured by the Recording screen, `recording/runtime.py:679`; recorded is a terminal state, `schedule/models.py:54-60`) are not offered, yet the backend accepts them for air (`commit_service.py:68`). Message "Upload and validate an asset in the Assets tab first." sends a recording operator on a dead-end. — list `validated` and `recorded`, or say recordings must be validated first. (UNVERIFIED whether another step converts recorded to validated; none found.)
- [HELP-05] `ScheduleScreen.tsx:716-729` — no way to cancel a Published item from this screen although `POST .../cancel` allows it; the Auto-schedule screen creates items already Published, so a wrong auto item cannot be removed here. — add a cancel/unpublish path or point to Channel Ops rollback.
- [HELP-06] `ScheduleScreen.tsx:575-584` — "Visible to residents." toast is shown even when the report says the engine nudge failed. — read `dispatch_status` and warn.
- [HELP-07] `ScheduleScreen.tsx:861` — "Conflicts on the same channel are rejected at the database layer." and `:283` "Conflicts are caught at the database layer before the form submits." — developer wording; the second is also inaccurate (the check happens when you submit). — "The station will not let two programs overlap on the same channel."
- [HELP-08] `ScheduleScreen.tsx:866-889` — tab labels `week`/`list` are lowercase raw ids; `Workflow` eyebrow is vague. Minor.
- [HELP-09] `ScheduleScreen.tsx:696-710` vs Program Guide: the same `Publish to residents` button also airs on the channel; the words "residents" hides that it goes on the linear channel. — "Approve to air".

## Screenshot plan
(a) Week view with 3-4 items incl. a Premiere and an Embargo; (b) List view with a Scheduled row showing `Not yet visible to residents` and the `Publish to residents` button; (c) review panel with `Safe to air`; (d) review panel with `Not safe to air yet` + clash list; (e) New scheduled item drawer with Mode, Asset, Channel, timezone box; (f) conflict error in drawer; (g) Cancel confirm dialog; (h) empty state; (i) non-publisher view (support_admin) with grey banner; (j) error state as meeting_operator. Setup: at least one validated asset and channel; create a second overlapping item to get the clash.

## UNVERIFIED / open questions
- UNVERIFIED: whether anything ever releases an Embargo item (grepped `civiccast/` for "embargo": only schedule/store/models/router/commit_service match). Need: a code owner statement or a publish-side worker.
- UNVERIFIED: whether Assets screen "Package" or another flow changes `recorded` assets to `validated`.
- UNVERIFIED: what `Publish to residents` does to the asset's VOD/portal page itself (only the schedule state and engine nudge were traced).
- UNVERIFIED: engine behavior after the nudge (`egress/dispatcher.py` module doc only: reload/start command).
- UNVERIFIED: `S/screens/ScheduleList.publish.test.tsx` etc. not read; no UI run.
