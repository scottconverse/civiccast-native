# Recording  (nav id: recording, section: Run Meeting)  - page heading is "Scheduled recording"
Path prefix `S` = `civiccast/apps/portal-operator/src`; backend `civiccast/recording/`.
Source files: `S/screens/RecordingScreen.tsx`, `S/screens/recording-format.ts`, `S/screens/contribution-format.ts` (`hasRole`), `S/components/EmptyState.tsx`; backend `recording/router.py`, `recording/service.py`, `recording/models.py`, `recording/runtime.py`, `recording/input_presets.py`. `S/screens/TrimEditorScreen.tsx` is NOT reachable from this screen (see end).
Who can open it: nav entry visible only to `setup_admin`, `meeting_operator`, `support_admin` (`S/components/shell/Sidebar.tsx:131-135`). Route `/recording` (`S/routes.ts:42`). Screen role gate: view = those three; **write = `setup_admin` or `meeting_operator`; `support_admin` is read-only** (`RecordingScreen.tsx:92-93,262-273`; backend `router.py:62-63`). A signed-in user with none sees: "Forbidden — scheduled recording is an operator / setup-admin / support-admin surface. Ask your station admin for access." (`:266-269`). `publish_operator` and `records_clerk` cannot use it.

## What it is for
Lets staff set up automatic captures of a live input (SDI/HDMI/NDI card) or a network stream (RTSP, SRT, HLS, RTMP, MPEG-TS) at set times, start one by hand (`Record now`), and watch the history of captures. A finished capture becomes an asset with state `recorded` (`recording/runtime.py:641-679`), shown in the Assets list; the Jobs table links to it.

## What the user sees
1. Heading `Scheduled recording` and text "Forward-schedule captures of live inputs and network streams, or kick off an ad-hoc one-shot via Record now. The production runtime owns capture, finalization, and alerts; this screen owns configuration and history." (`:419-424`).
2. Amber banner only if a `Record now` returned 503: "Scheduled recording runtime is unavailable in this deployment. Schedules can still be created; jobs will materialize when the runtime is enabled." (`:427-432`).
3. Card `Schedules`: table Name / Source / Recurrence / Duration / Enabled / Actions (Actions only for writers).
4. Card `New schedule` (or `Edit "<name>"`) form, shown only to writers.
5. Card `Recordings`: state / Schedule ID / Limit filters, `Refresh`, table Planned start / Source / State / Duration / Bytes / Asset / Failure / Actions.

## Controls and what they do
| Control (exact label) | What it does | API / effect | Role gate | Notes |
|---|---|---|---|---|
| Schedules table rows | Show `<name>` + schedule id, source e.g. `SDI sdi-1` or `RTSP rtsp://…`, recurrence e.g. `One-shot 2026-06-20 19:00 UTC` / `Weekly Mon/Wed 19:00 UTC`, duration `HH:MM:SS`, pill `enabled`/`disabled` | `GET /api/staff/recording/schedules` | view roles | Sorted by name. Recurrence is shown in **UTC** (`recording-format.ts:28-45`). |
| `Record now` (aria `Record now from <name>`; `Starting…`) | Starts a capture right now from that schedule's source | `POST /api/staff/recording/schedules/{id}/record-now` | write | Disabled if schedule is disabled, runtime unavailable, or starting. 503 -> amber banner; 409 "An overlapping recording is already armed/active on this source"; 500 capture failure; other errors show amber "Record now failed." or server text (`:447-452`). Success: no message, new row appears in Recordings. |
| `Edit` (becomes `Editing`) | Loads the schedule into the form | none | write | schedule id locked |
| `Delete` -> `Confirm delete` / `Cancel` | Two-click delete of the schedule | `DELETE /api/staff/recording/schedules/{id}` | write | Existing jobs stay in history (`router.py:309-331`, doc: "Existing jobs that reference the schedule are left in place"). Unlike disabling, delete does not call the code that cancels still-scheduled jobs (`router.py:295`, patch handler only) - UNVERIFIED whether already-planned jobs still fire. Delete errors are not shown anywhere. |
| Form `Schedule ID (slug)` (placeholder `evening-news`) | Unique id; locked when editing | | write | Must be lowercase letters, digits, hyphens: "Slug required: lowercase letters, digits, hyphens." |
| Form `Name` (placeholder `Evening news`) | Display name | | | "Name is required." Server rejects a duplicate name with 409. |
| Form `Source kind` (groups `Live inputs`: SDI, HDMI, NDI; `Network streams`: RTSP, SRT, HLS, RTMP, MPEG-TS) | Choose input type | | | Changing kind clears Input ID |
| Form `Input ID` (SDI/HDMI = dropdown of detected capture devices `<label> (<origin>)`; NDI = text, placeholder `studio-ndi`) | Which device | `GET /api/staff/recording/input-presets` | view roles | Placeholders in dropdown: `Looking for capture devices…`, `No SDI inputs available`, `Choose an SDI input`; red "No SDI capture input was detected or configured."; error "Could not inspect capture devices."; saved id missing: `Saved input unavailable: <id>`. Wrong kind: `Input "<id>" is an SDI input; choose an HDMI input.` |
| `Inspect capture devices` (`Inspecting devices…`) | Re-scans the machine's capture cards | `GET .../input-presets?refresh=true` (re-runs FFmpeg device discovery) | | |
| Form `URI` (network kinds; placeholder `rtsp://camera.local/stream`) | Stream address | | | "URI is required for network streams." Credentials may be in the URL; nothing warns (UNVERIFIED how stored). |
| Form `Recurrence`: `One-shot` / `Weekly` | Once or repeating | | | |
| `Start (UTC)` (one-shot, datetime-local) + "In your local time: …" | Start moment | | | **The time typed is treated as UTC, not local** (`:1005`). "Start time is required." |
| Weekly: buttons `Weekdays`, `Weekend`, `Every day`, `Clear`; checkboxes Mon-Sun; `Time (HH:MM UTC)` (placeholder `19:00`) + "In your local time: …" | Repeating days/time | | | "Pick at least one weekday." / "Time must be HH:MM (24h UTC)." Day checkboxes are UTC weekdays (0 = Mon). |
| Preview "Next fire:" / "Next 3 fires:" with `UTC … · local …` | Shows next fire times | none | | |
| Form `Duration (HH:MM:SS)` (placeholder `01:30:00`, default `01:00:00`) | Length | | | "Duration must be HH:MM:SS — minutes and seconds need two digits (e.g. 01:05:00 not 1:5:0)." |
| Form `Quality preset (encoder profile)` (default `default`; suggestions default, copy, h264-1080p, h264-720p, hw-h264-1080p, hw-h264-720p) with note "Common values: hw-h264-1080p, hw-h264-720p. Contact your station admin for the full list of available presets." | Encoder preset | | | "Quality preset is required." Free text; an unknown name is not checked here (UNVERIFIED server check). |
| Form `Loudness regime`: `Inherit station default`, `Copy source audio`, `Cable / ATSC A/85 (-24 LKFS)`, `Broadcast / EBU R128 (-23 LUFS)`, `Streaming (-16 LUFS)` with one-line help under each (`:152-158`) | Loudness target | | | e.g. A/85 help: "ATSC A/85. Required by US cable headends and the CALM Act." |
| Form `Target series (optional)` | Series label | | | no explanation |
| Form `Enabled` checkbox | Include in automatic firing | | | Un-ticking on an existing schedule also cancels its still-waiting jobs (`router.py:272-296`) |
| `Create schedule` (`Creating…`) / `Save schedule changes` (aria) shown as `Save changes` (`Saving…`) | Saves; first failed attempt shows red errors under fields and focuses the first bad one | `POST /api/staff/recording/schedules` (body `station_id` fixed to `civiccast-station`, `:97,:1029`) / `PATCH .../{id}` | write | Errors in amber banner: server text. **After a successful create the form is not cleared and no success message appears** (`:370-373`); pressing again gives 409 "Recording schedule '<id>' already exists. Use PATCH to update." (`router.py:211`). 403 if the station id env differs from `civiccast-station` (`router.py:203-208`). |
| `Cancel edit` | Leaves edit mode | none | | |
| Jobs filter `State` (All states, scheduled, arming, recording, finalizing, done, failed, skipped), `Schedule ID` (placeholder `any`), `Limit` (1-500, default 50) | Narrow the list | `GET /api/staff/recording/jobs?state=&schedule_id=&limit=` | view roles | |
| `Refresh` (`Refreshing…`, aria `Refresh recordings`) | Reload | | | |
| Pill `Live · refreshing every 5 s` / `Paused · last refresh <time>` with `Pause` / `Resume` | Auto-refresh toggle; only shown while any job is scheduled/arming/recording/finalizing | | | |
| Asset link `<asset id> →` | Goes to that asset's detail (`#/assets/<id>`) | none | | |
| Job `Stop` -> `Confirm stop` / `Cancel` (aria `Stop job <id>`) | Ends a capture early; partial file is finished into an asset | `POST /api/staff/recording/jobs/{id}/stop` | write | Shown for states scheduled, arming, recording, finalizing (`:163-168`) but the server accepts only arming/recording/finalizing (`recording/models.py:90`, `service.py:617-621`): on a `scheduled` job the server answers 409 "Cannot stop job '<id>': state is 'scheduled'; only ['arming', 'finalizing', 'recording'] are stoppable." and the screen shows nothing (stop errors are not rendered). |

## States
- Role/identity: `Loading…`; identity error amber "Could not load your staff identity (<detail>). Check that you are signed in and the local API is running, then retry." (`:255-258`).
- Schedules: `Loading schedules…`; error banner `Could not load schedules.` or server text; empty: "No recording schedules yet." / "A recording schedule captures a meeting or event automatically at the same time each week. Create one below, or use Record Now for a one-off capture." (`:583-584`; there is no one-off capture without first creating a schedule, and the button is `Record now` not `Record Now`).
- Recordings: `Loading recordings…`; `Could not load jobs.`; empty: "No recordings yet." / "Every capture — in progress or finished — appears here with its status. Schedule a recording above or press Record Now to make the first one."
- Backend not ready: "Durable storage is not ready yet." (`router.py:57`).

## Typical task flows
1. Weekly capture: choose `Weekly`, tick days, set `Time (HH:MM UTC)` using the local echo, `Duration`, pick the capture card under `Input ID`, `Create schedule`. A job appears under Recordings in state `scheduled` shortly before start (created by the runtime; `service.py` `tick`).
2. Capture now: `Record now` on a schedule row -> watch row go `arming` -> `recording`; later `Stop` -> `Confirm stop` -> `finalizing` -> `done`, asset link appears.
3. Investigate a failure: filter State = failed; read the red text in `Failure`.

## Statuses and words on this screen
| Word | Meaning |
|---|---|
| `scheduled` (blue) | job planned, not started |
| `arming` (amber) | getting the input ready |
| `recording` (green) | capturing now |
| `finalizing` (amber) | closing the file and creating the asset |
| `done` (green) | finished; asset created |
| `failed` (red) | stopped with an error; text in `Failure` |
| `skipped` (grey) | not run (e.g. schedule disabled) (`router.py` patch docstring: "schedule disabled") |
| `enabled` / `disabled` | schedule switch |
State badges print the raw lowercase value, not routed through `status-language.ts` (`RecordingScreen.tsx:221-233`).

## Related settings / env / CLI / API
`/api/staff/recording/{input-presets,schedules,schedules/{id},schedules/{id}/record-now,jobs,jobs/{id}/stop}`; `CIVICCAST_STATION_ID` (default `civiccast-station`, `router.py:73,77-86`); `CIVICCAST_RECORDING_INPUT_PRESETS_JSON` (`input_presets.py:19`); `CIVICCAST_RECORDING_DRAIN_DEADLINE_SECONDS` (`app.py:664`); Assets screen (the `recorded` asset); Loudness settings in Setup.

## Help-text findings
- [HELP-01] `RecordingScreen.tsx:163-168,1874-1924` — `Stop` is offered on a `scheduled` job, the server refuses (409) and the screen swallows the error, so the click appears to do nothing. — show Stop only for arming/recording/finalizing; render stop errors. To remove a not-yet-started recording, the user should untick `Enabled` on the schedule.
- [HELP-02] `RecordingScreen.tsx:1295,1420,1005` — `Start (UTC)` / `Time (HH:MM UTC)` use UTC inputs while browsers show datetime-local in local time; the weekday boxes are also UTC days. A 7 PM Monday evening meeting in the Americas is already Tuesday in UTC. The "In your local time" echo helps but the weekday checkboxes get no echo. — label days "UTC day" or convert; manual must explain with an example.
- [HELP-03] `RecordingScreen.tsx:370-373` — creating a schedule gives no confirmation and keeps the form filled; re-clicking yields a confusing 409. — clear form and toast "Schedule saved."
- [HELP-04] `RecordingScreen.tsx:584,1806` — "use Record Now for a one-off capture" / "press Record Now to make the first one" — `Record now` only exists inside a saved schedule's row. — "Create a schedule below; then its Record now button starts a capture immediately."
- [HELP-05] `RecordingScreen.tsx:1546-1547` — "Contact your station admin for the full list of available presets." — a clerk cannot discover valid values; free-text. — dropdown of real presets (the code comment at `:122-126` already says so).
- [HELP-06] `RecordingScreen.tsx:1583` — `Target series (optional)` — unexplained jargon. — say what it does (UNVERIFIED, see below).
- [HELP-07] `RecordingScreen.tsx:229` — job state badges show raw words (`arming`, `finalizing`) and no hover explanation. — plain-language labels: "Getting ready", "Recording", "Saving file", "Done", "Failed", "Skipped".
- [HELP-08] `RecordingScreen.tsx:36-37,266-269` — the "Forbidden" message calls the screen an "operator / setup-admin / support-admin surface"; `publish_operator`/`records_clerk` never see the nav item. Fine, but wording is jargon. — "Scheduled recording needs the meeting operator, setup admin, or support admin role."
- [HELP-09] `RecordingScreen.tsx:663-703` — `Delete` confirm gives no description of what happens to planned jobs and earlier recordings. — "Past recordings stay. Future recordings from this schedule will be cancelled." (once verified).
- [HELP-10] Nav says `Recording`, page heading `Scheduled recording`, section `Recordings` is the jobs table and `Schedules` the plans; the older word `jobs` still shows in aria labels (`Stop job <id>`).

## Screenshot plan
(a) Populated Schedules table with one weekly and one one-shot row; (b) New schedule form with Weekly selected and the local echo + `Next 3 fires`; (c) form with validation errors; (d) Source kind = SDI with the capture-device dropdown (and the "No SDI inputs available" state on a box without a card); (e) Recordings table with a `recording` row, live pill, `Stop`, then `Confirm stop`; (f) a `failed` row with red Failure text; (g) support_admin read-only view; (h) 503 banner after `Record now`. Setup: a station with an input (or an RTSP test stream URI), meeting_operator/admin token.

## Trim editor (not on this screen)
The trim/chapter editor is `/assets/:assetId/trim` (`S/routes.ts:84-86`, `S/App.tsx:87-93,229,279`), opened from the Asset detail page (`onEditTrim`), not from Recording. Path from here: Recordings table `<asset id> →` -> Asset detail -> trim. Its button/aria strings seen in passing (`Close trim editor`, `Save trim & chapters`, `Preview`, `Chapters`, `Timeline`, `In point`, `Out point`, `Add chapter at playhead (M)`) belong in the Assets/Trim inventory; not inventoried here.

## UNVERIFIED / open questions
- UNVERIFIED: whether deleting a schedule cancels already-materialized `scheduled` jobs (delete handler does not call the cancel helper; `tick` behavior for orphaned jobs not read).
- UNVERIFIED: whether editing time/source of a schedule updates already-materialized jobs.
- UNVERIFIED: meaning/effect of `Target series` and `custom_field_values` (`{}` sent on create).
- UNVERIFIED: how/if a stream URI with embedded credentials is stored or masked.
- UNVERIFIED: whether `CIVICCAST_STATION_ID` is ever set differently by the installer (`installer/station_state.py` references the name; not read), which would make every Create fail with 403.
- UNVERIFIED: what `Quality preset` names the server accepts.
- UNVERIFIED: how long before start a `scheduled` job appears in the table (scheduler tick interval not read).
