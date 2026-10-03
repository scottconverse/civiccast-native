# Program Guide  (nav id: guide, section: Run Meeting)
Path prefix `S` = `civiccast/apps/portal-operator/src`; backend under `civiccast/programlog/`.
Source files: `S/screens/ProgramGuideScreen.tsx`, `S/components/programlog/ProgramSlotDrawer.tsx`, `S/components/ConfirmDialog.tsx`, `S/components/EmptyState.tsx`; backend `programlog/router.py`, `programlog/materializer.py`, `programlog/occurrences.py`, `programlog/models.py`, `schedule/router.py`.
Who can open it: nav entry has no `requiredRoles` (`S/components/shell/Sidebar.tsx:130`), so every signed-in operator sees it. Route `/guide` (alias `/program-guide`; note `/guide` is NOT the manual, `S/routes.ts:47-55`). Reading slots and the log has no role check beyond being signed in (`programlog/router.py:157-168,258-263`). **Writing (`Add to guide`, `Disable`, `Refresh guide`) requires `meeting_operator` or `support_admin`** (`router.py:128,190,217,241`) - not `setup_admin` or `publish_operator`. The screen itself does not hide or disable these buttons for other roles; they fail with a server message.

## What it is for
The Program Guide holds recurring "slots": a recording placed on a channel at a time that repeats (Once, Daily, Weekly, Weekdays). A background job turns each slot into real schedule items over the next 72 hours. The screen lists the slots and a 7-day day-by-day view of what has been built, including the airings that were skipped and why. The items it creates are in state **Scheduled** on the Schedule screen and still need `Publish to residents` before they air (`programlog/materializer.py:212-220`; only Published items air, `egress/source_plan.py:507-511`).

## What the user sees
1. Eyebrow `Workflow`, heading `Program guide`, text "Place recordings on a channel's recurring guide. The automation engine airs scheduled entries and falls back to filler between programs. Times shown in your browser timezone." (`ProgramGuideScreen.tsx:445-449`).
2. Toolbar: `Channel` dropdown (channel display names; starts on id `public`), `Refresh guide`, and `Add to guide` at right (`:453-506`).
3. Section `Recurring slots`: one row per slot.
4. Section `Next 7 days`: entries grouped by day with a `Today` chip.
5. Drawer `Add to guide` and a confirm dialog.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| `Channel` dropdown | Switches channel for slots and log | `GET /api/staff/cable/channels`; slots `GET /api/staff/programlog/slots?channel_id=`; log `GET /api/staff/programlog/channels/{id}/log?hours=168` | any signed-in | Shows the raw id if the channel list is empty (`:474`). |
| `Refresh guide` (`Refreshing…`) | Builds the next 72 h of airings from every enabled slot **on all channels**, not just the one selected | `POST /api/staff/programlog/materialize` | `meeting_operator` / `support_admin` | Toast "Guide refreshed." + "`N scheduled · N conflicts · N not playable`". Failure toast "Could not refresh the guide." |
| `Add to guide` (toolbar) | Opens drawer for the selected channel | none | button always visible | |
| Drawer header `Program guide · <channel id>` / heading `Add to guide` | | | | |
| Drawer `Recording` dropdown (`<title> · <asset_id>`) | Picks the asset | `GET /api/staff/assets` | any | Only `validated` assets (`ProgramSlotDrawer.tsx:79-82`). If none: "**No validated recordings.** Upload and validate a recording in the Assets tab first." Help: "Only validated recordings can air. The guide refreshes within the rolling horizon after you add a slot." |
| Drawer `Repeats` cards: `Once` ("Airs a single time at the start time."), `Daily` ("Airs every day at this time."), `Weekly` ("Airs every week on this weekday."), `Weekdays` ("Airs Monday through Friday.") | Chooses recurrence (default Weekly) | | | |
| Drawer `First airing` (datetime-local, default next full hour) | Start of first airing | | | Invalid: "Enter a date and time for the first airing." Preview "<Day, Mon d, h:mm> (<tz>)". |
| Drawer `Repeat until (optional)` (not for Once) | Last date it may air | | | Invalid: "The repeat-until date could not be read. Re-enter it." |
| Drawer checkbox `Use the recording's own length` / `Duration (min)` | Duration from the asset, or a fixed minutes value (>= 1; server max 14 days) | | | |
| Drawer `Guide title (optional)` (placeholder "Shown to residents instead of the recording title.", max 200) | Title override | | | |
| Drawer `Add to guide` (`Adding…`) | Creates slot, then runs a materialize pass | `POST /api/staff/programlog/slots` | `meeting_operator` / `support_admin` | Toast "Added to guide." + "`<title or asset id> · Weekly`". Error box "Could not add to guide." + server message (e.g. role text: "This action requires one of these CivicCast roles: meeting_operator, support_admin."). |
| Drawer `Cancel`, `✕`, backdrop, Esc | Close | none | | |
| Slot row `Disable` | Opens confirm: title `Disable "<name>"?`, body "All future airings from this recurring slot are cancelled from the guide immediately. Past and in-progress airings are unaffected, but nothing new will schedule until the slot is re-enabled.", buttons `Disable slot` / `Cancel` | `POST /api/staff/programlog/slots/{id}/disable` (cancels each future Scheduled item) | `meeting_operator` / `support_admin` | Toast "Slot disabled." + "`<name> · N future airing(s) cancelled`". Once disabled the row shows a `Disabled` pill; **there is no re-enable control** and the update API has no `enabled` field (`router.py:75-88`). |

## States
- Loading: three grey bars (slots or log loading).
- Error: red box `Could not load the program guide.` or `Durable storage is not ready.` (503) + server text + "**Next step.** Try again, or check the server logs for more detail." / "Open Setup, prepare durable storage, then return here." + `Go to Setup` (503) and `Retry` (`:132-174`). Storage-not-ready text: "Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment." (`router.py:27-30`).
- No slots: "Nothing on the guide yet." / "The program guide is the weekly grid of what airs on this channel. Place a recording with “Add to guide” and its recurring slot appears here." (`:186-187`) (there is no weekly grid on this screen).
- Empty log: "Nothing scheduled for the next 7 days." / "This log is the day-by-day schedule built from the guide's recurring slots. Add a slot, then press “Refresh guide” to build out the week." (`:266-267`).
- Unreadable times: "1 guide entry has an air time this station cannot read and is not shown below." (+ plural) "The rest of the guide is complete." (`:283-286`).
- Slot with no length override shows `recording length` (`fmtDuration`, `:70`).

## Typical task flows
1. Repeat a recording weekly: `Add to guide` -> choose recording, `Weekly`, first airing -> `Add to guide` -> (slot appears; entries appear under `Next 7 days` with status `Scheduled`) -> go to Schedule screen and `Publish to residents` for each (publisher role) so it actually airs.
2. Fix a skipped airing: read the amber `Skipped · conflict` / `Skipped · not playable` rows (detail text under the title), correct the clash or the asset, then use `Refresh guide`. Skips are not retried automatically (`materializer.py` module doc).
3. Stop a series: `Disable` -> `Disable slot`.

## Statuses and words on this screen
| Word | Meaning (code) |
|---|---|
| Recurrence pill `Once` / `Daily` / `Weekly` / `Weekdays` | slot repeat rule (`:26-31`) |
| Row status `Scheduled` | a schedule item exists for this airing (state Scheduled on the Schedule screen) |
| `Skipped · conflict` | another item overlapped on that channel; `detail` text shows the server message |
| `Skipped · not playable` | asset missing, not validated/recorded, no local file, or unknown length (`materializer.py:196-207`; `_PLAYABLE_ASSET_STATES` at `:41`) |
| `Cancelled` | airing cancelled because slot disabled |
| `manual` (raw word) | an item scheduled directly on the Schedule screen with no slot; the log merges these in with detail "Scheduled directly (no recurring slot)." (`router.py:318-319`); **`manual` is not in the status table, so the chip shows the raw lowercase word `manual`** (`:33-41,:44`) |
| `Disabled` | slot disabled |
| `first <date>`, `until <date>` | slot start and end dates |
Not routed through `status-language.ts`.

## Related settings / env / CLI / API
`CIVICCAST_PROGRAM_LOG_WORKER` (default `inline`; `off` stops the background build), `CIVICCAST_PROGRAM_LOG_POLL_SECONDS` (300 s), `CIVICCAST_PROGRAM_LOG_HORIZON_HOURS` (72 h) (`materializer.py:60-77`); `/api/staff/programlog/{slots,slots/{id},slots/{id}/disable,materialize,channels/{id}/log}`; public `/api/public/programlog/channels/{id}/guide` (resident guide; lists occurrences in status Scheduled only, `router.py:337-379`); Schedule screen; Channel Ops.

## Help-text findings
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

## Screenshot plan
(a) Populated: two slots and a 7-day log with a mix of `Scheduled`, `Skipped · conflict`, `Skipped · not playable`, `manual`; (b) Add to guide drawer with Weekly; (c) Disable confirm dialog; (d) empty slots + empty log; (e) error state; (f) a slot with the `Disabled` pill. Setup: validated asset, channel, an overlapping manual schedule item to force a conflict, a deleted/ineligible asset to force `not playable`. Use a `meeting_operator` token for writes.

## UNVERIFIED / open questions
- UNVERIFIED: HELP-02 (weekday/DST drift) was derived from reading `compute_occurrences`, not from running it; also assumes the stored `first_start_at` stays UTC.
- UNVERIFIED: whether the Channel Ops screen has any control that bulk-publishes Scheduled items from slots (only the Schedule screen path was traced).
- UNVERIFIED: whether `Add to guide` rejects a channel id not in the channel list (`channel_id` is free-form 1-80 chars, `router.py:59`).
- UNVERIFIED: that a station without any `meeting_operator`/`support_admin` token (e.g. the first admin issued scope `admin` expands to all five roles per `auth/roles.py:22-24`) can edit; the default admin can.
