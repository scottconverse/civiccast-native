# Recording (nav id: recording)

Console group: Run Meeting. The page heading reads "Scheduled recording". Spec written against beta.10. Paths are under `civiccast/apps/portal-operator/src/screens/` unless they start with `civiccast/`. Authority: `docs/manual/src/12-before-meeting.md` ("Record a meeting automatically (Recording)") and `ops/docs-sprint/inventory/screens/recording.md`. Line numbers re-checked in `RecordingScreen.tsx` (1936 lines).

## Where the help text lives now
- `RecordingScreen.tsx`: access messages 255-257, 267-268; heading and intro 419-423; runtime-unavailable bar 429-430; schedules card 572-690; form 855-1625 (validation messages 823-851, loudness words 140-157, preset suggestions 127-134); jobs card 1631-1930 (live pill 1710-1715, filters 1758-1765, empty text 1805-1806, Stop 1874-1922).
- `recording-format.ts:28-43` (recurrence text, always in UTC). `civiccast/recording/router.py` (server messages) and `service.py:617-621` (what can be stopped).

## Current text
| String | Where | Source line |
|---|---|---|
| "Scheduled recording" | Heading | RecordingScreen.tsx:419 |
| "Forward-schedule captures of live inputs and network streams, or kick off an ad-hoc one-shot via Record now. The production runtime owns capture, finalization, and alerts; this screen owns configuration and history." | Intro | RecordingScreen.tsx:421-423 |
| "Forbidden — scheduled recording is an operator / setup-admin / support-admin surface. Ask your station admin for access." | Role refusal | RecordingScreen.tsx:267-268 |
| "Could not load your staff identity ({detail}). Check that you are signed in and the local API is running, then retry." | Error | RecordingScreen.tsx:255-257 |
| "Scheduled recording runtime is unavailable in this deployment. Schedules can still be created; jobs will materialize when the runtime is enabled." | Amber bar after Record now fails with 503 | RecordingScreen.tsx:429-430 |
| "Schedules" / table heads Name, Source, Recurrence, Duration, Enabled | Card | RecordingScreen.tsx:572, 593-595 |
| "No recording schedules yet." / "A recording schedule captures a meeting or event automatically at the same time each week. Create one below, or use Record Now for a one-off capture." | Empty | RecordingScreen.tsx:583-584 |
| "One-shot {date time} UTC" / "Weekly Mon/Wed {time} UTC" | Recurrence column | recording-format.ts:36, 43 |
| "enabled" / "disabled" | Tag | RecordingScreen.tsx:629 |
| "Record now" / "Starting…" / "Edit" / "Editing" / "Delete" / "Confirm delete" / "Cancel" | Row buttons | RecordingScreen.tsx:649, 661, 676, 687 |
| "Record now failed." (or server text) | Row error | RecordingScreen.tsx:450 |
| "New schedule" / `Edit "{name}"` / "Cancel edit" | Form header | RecordingScreen.tsx:1068, 1077 |
| "Schedule ID (slug)" / "Name" / "Source kind" / "Input ID" / "URI" | Form labels | RecordingScreen.tsx:1084, 1117, 1138, 1174, 1246 |
| "Slug required: lowercase letters, digits, hyphens." / "Name is required." / "Input ID is required for live sources." / "URI is required for network streams." | Validation | RecordingScreen.tsx:823, 825, 830, 835 |
| "Looking for capture devices…" / "No {kind} inputs available" / "Choose an {kind} input" / "Saved input unavailable: {id}" / "No {kind} capture input was detected or configured." / "Inspect capture devices" / "Inspecting devices…" | Input ID | RecordingScreen.tsx:1190-1197, 1213, 1223 |
| "Recurrence" / "One-shot" / "Weekly" | Form | RecordingScreen.tsx:1275, 1288-1289 |
| "Start (UTC)" / "In your local time: {time}" | One-shot | RecordingScreen.tsx:1295, 1316 |
| "Weekdays" / "Weekend" / "Every day" / "Clear" / "Time (HH:MM UTC)" / "In your local time: {time}" | Weekly | RecordingScreen.tsx:1355, 1369, 1383, 1397, 1420, 1447 |
| "Start time is required." / "Pick at least one weekday." / "Time must be HH:MM (24h UTC)." | Validation | RecordingScreen.tsx:838, 841, 843 |
| "Next fire:" / "Next 3 fires:" + "UTC … · local …" | Preview | RecordingScreen.tsx:1476 |
| "Duration (HH:MM:SS)" / "Duration must be HH:MM:SS — minutes and seconds need two digits (e.g. 01:05:00 not 1:5:0)." | Form | RecordingScreen.tsx:1498, 849 |
| "Quality preset (encoder profile)" / "Common values: hw-h264-1080p, hw-h264-720p. Contact your station admin for the full list of available presets." / "Quality preset is required." | Form | RecordingScreen.tsx:1525, 1546-1547, 851 |
| "Loudness regime" + five choices and one-line help each | Form | RecordingScreen.tsx:1557, 140-157 |
| "Target series (optional)" / "Enabled" | Form | RecordingScreen.tsx:1583, 1601 |
| "Create schedule" / "Creating…" / "Save changes" / "Saving…" | Submit | RecordingScreen.tsx:1616-1620 |
| "Recordings" / "Live · refreshing every 5 s" / "Paused · last refresh {time}" / "Pause" / "Resume" / "Refresh" | Jobs card | RecordingScreen.tsx:1682, 1710-1715, 1724, 1739 |
| "All states" and raw words scheduled, arming, recording, finalizing, done, failed, skipped | Filter and tags | RecordingScreen.tsx:1758-1765 |
| Table heads "Planned start", "Failure" | Jobs table | RecordingScreen.tsx:1815, 1821 |
| "No recordings yet." / "Every capture — in progress or finished — appears here with its status. Schedule a recording above or press Record Now to make the first one." | Empty | RecordingScreen.tsx:1805-1806 |
| "Stop" / "Confirm stop" / "Cancel" | Job buttons | RecordingScreen.tsx:1922, 1895, 1906 |
| "Could not load schedules." / "Could not load jobs." / "Could not create schedule." / "Could not update schedule." / "Could not inspect capture devices." | Errors | RecordingScreen.tsx:439, 503, 468, 470, 477 |

## What the screen really does
Recording sets up automatic captures of a video card (SDI, HDMI, NDI) or a network stream at set times, starts a capture from a saved schedule with "Record now", and lists every capture with its state. Every time you type on this screen is UTC, not local time, and the weekday boxes are UTC days. A finished capture becomes a library video in the Recorded state; the Recordings table links to it. There is no one-off capture without a saved schedule. After "Create schedule" works, the form is not cleared and no message appears, so look for the new row. "Stop" is offered on a job that has not started, but the station refuses it and shows nothing. Setup admins and Meeting operators can change things; Support admins can look only.

## Mismatches
| ID | Text says | What happens (code) | Severity |
|---|---|---|---|
| HELP-01 | "Stop" shown on a `scheduled` job | `ACTIVE_JOB_STATES` includes scheduled (:163-168); the server accepts only arming, recording, finalizing (`civiccast/recording/service.py:617-621`) and answers 409; the screen shows no stop error. | misleading |
| HELP-02 | "Start (UTC)", "Time (HH:MM UTC)", Mon to Sun boxes | Times and weekdays are UTC; a Monday 7 PM meeting in US Mountain Time is Tuesday in UTC; the weekday boxes get no local echo (:1295, 1420). After a clock change the local time moves. | blocks work (recording on the wrong day) |
| HELP-03 | (nothing after Create schedule) | Form stays filled; no message (`:370-373`); a second click returns 409 "Recording schedule '{id}' already exists. Use PATCH to update." | misleading |
| HELP-04 | "use Record Now for a one-off capture" / "press Record Now to make the first one" | The button is "Record now" and exists only on a saved schedule's row (:649). | misleading |
| HELP-05 | "Contact your station admin for the full list of available presets." | Free text; unknown names are not checked here (UNVERIFIED on the server). | misleading |
| HELP-06 | "Target series (optional)" | Unexplained; effect not confirmed. | cosmetic |
| HELP-07 | State words arming, finalizing, etc. | Raw lowercase words with no explanation (:221-233). | cosmetic |
| HELP-08 | "Forbidden — ... an operator / setup-admin / support-admin surface." | Jargon. Publish operator and Records clerk never see the menu item. | cosmetic |
| HELP-09 | "Delete" then "Confirm delete" | No word on planned jobs or earlier recordings; delete does not cancel waiting jobs (UNVERIFIED whether they still start); delete errors are not shown. | misleading |
| HELP-10 | "Recording", "Scheduled recording", "Recordings", "Schedules", aria "Stop job" | Several names for the screen and its parts. | cosmetic |
| NEW-1 | (nothing) | A stream address with a user name and password gets no warning; how it is stored is not confirmed. | misleading |
| NEW-2 | Intro: "kick off an ad-hoc one-shot via Record now" | Same cause as HELP-04. Also "Schedule ID" cannot be changed after saving (locked when editing). | cosmetic |

## Proposed text
- Heading: keep "Scheduled recording". Intro (:421-423): "Use this screen to record a video card or a network stream automatically at set times, or to start a recording right now from a saved schedule. A finished recording appears in the Assets list. All times on this screen are UTC, not your local time."
- Who can use this (new): "Setup admin and Meeting operator: create, change, delete, Record now, Stop. Support admin: look only. Other roles cannot open this screen."
- Refusal (:267-268): "Scheduled recording needs the Setup admin, Meeting operator or Support admin role. Ask your station admin for access."
- UTC warning (new, top of the New schedule form): "Times you type here are UTC (a world clock with no daylight saving), not local time. The weekday boxes are UTC days too. A Monday 7 PM meeting in US Mountain time is already Tuesday in UTC: tick Tue, not Mon. Read the 'Next 3 fires' lines to check the local day and time. After the clocks change, edit the schedule: your local time moves by an hour."
- Weekday checkboxes legend (:1337): "Weekdays (UTC days)".
- Empty schedules (:584): "No recording schedules yet. Create one below. Then its row has a Record now button that starts a recording right away."
- Empty recordings (:1806): "No recordings yet. A recording appears here when a schedule starts or when you press Record now on a schedule."
- Record now button: tooltip "Starts a recording from this schedule now. It runs for the schedule's duration unless you stop it. The new row in Recordings is the only confirmation."
- After Create schedule (code fix pending): "Look for the new row in the Schedules table above. Do not press Create schedule twice." After fix: "Schedule saved."
- Quality preset note (:1546-1547): "Leave 'default' unless your station admin gives you another name. Names such as hw-h264-1080p use the computer's video hardware. CivicCast does not check the name here." After fix: a menu of real presets.
- Target series (:1583): "Target series (optional): leave blank unless your administrator tells you what to enter. What it does is not confirmed in this version."
- Stream address note under URI (:1246): "Do not put a user name or password in the address unless your IT person says how CivicCast stores it."
- Job state words (:1758-1765 and tags): scheduled = "Planned", arming = "Getting ready", recording = "Recording", finalizing = "Saving file", done = "Done", failed = "Failed (see Failure)", skipped = "Skipped". Keep the raw word as a tooltip so support can read it.
- Stop button: show only for Getting ready, Recording and Saving file. Tooltip: "Ends the recording now. The part already recorded is saved as a video. This cannot be undone." For a Planned job: "To cancel a recording that has not started, untick Enabled on its schedule."
- Delete confirm (:676): "Past recordings stay in the list. This screen does not say whether recordings already planned from this schedule still run. Untick Enabled first to cancel them."

## Notes for the coder
- Files: `RecordingScreen.tsx`, `recording-format.ts`.
- Tests that pin strings: `RecordingScreen.test.tsx` pins the labels /Schedule ID \(slug\)/i, /^Name$/i, /Source kind/i, /Input ID/i, /^URI$/i, /Recurrence/i, /Start \(UTC\)/i, /Time \(HH:MM UTC\)/i, /Duration \(HH:MM:SS\)/i (e.g. :274-338, 434-489), the group name /Weekdays/i (:442), the aria names "Record now from {name}", "Edit schedule {name}", "Delete schedule {name}", "Confirm delete schedule {name}", "Stop job {id}", "Confirm stop job {id}", "Cancel stop job {id}" (:227-239, 645-674), /Forbidden/i (:217), /No recording schedules yet\./i and /No recordings yet\./i (:257, 264), /Scheduled recording runtime is unavailable/i (:568, 582), validation texts /URI is required for network streams/i, /Pick at least one weekday/i, /Start time is required/i, /Duration must be HH:MM:SS/i, and the test ids `job-state-badge-{state}` (:610), `one-shot-local-echo` (:701), `next-fire-preview`, `loudness-help`. `e2e/a11y.spec.ts:219-233` pins the heading "Scheduled recording", the heading "New schedule" and the button "Create schedule". Changing the visible state words is safe if the test ids stay.
- Code fixes, not text fixes: show Stop only for stoppable states and render stop errors (HELP-01); local-time echo for the weekday boxes or convert days (HELP-02); clear the form and show a toast after Create (HELP-03); a real preset list (HELP-05); show delete errors and decide what happens to planned jobs (HELP-09); warn about credentials in a URI (NEW-1).
- Not verified: whether deleting a schedule cancels jobs already planned; whether editing a schedule updates jobs already planned; what Target series does; how a stream address with credentials is stored; what preset names the server accepts; how many minutes before the start a Planned job appears (the manual says up to ten, by default); whether `CIVICCAST_STATION_ID` ever differs from `civiccast-station` (which would make every Create fail with 403).
