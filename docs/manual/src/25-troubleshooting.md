# Troubleshooting matrix {#ch-troubleshooting}

This chapter is for the person who looks after the CivicCast station computer: usually the one or two IT staff at a small city. It lists what goes wrong in beta.10, how to tell which problem you have by looking at a screen, a log line or a command result, and what to do. It is organised by area. Each area is a table with four columns: the **symptom** you see, the **likely cause**, **how to confirm** it, and the **fix**. Where we could not find a fix in the code, the table says so instead of guessing.

> **Note:** Beta.10 was published on 2026-10-02 as a GitHub pre-release (a beta candidate). Gate A, the formal acceptance run, passed for the clean-install lane only. The upgrade lane and the download-only lane were not run. A first install with neither the full kit nor an earlier install is not proven: setup needs the `packs` and `station` folders beside it. No human field-tester has signed it off. The 8-hour soak run was done on an earlier internal build (C16), not on the published files. Treat every fix in this chapter as advice for a beta, and expect to meet problems that are not listed here.

## Before you start

- **Who can do what.** Reading logs and running the commands below needs an Administrator account on the station computer (the service runs as LocalSystem and its folders are locked down). Console buttons mentioned in the matrix need a role: **Support admin** for the Readiness support bundle; **Setup admin or Support admin** for "Repair GStreamer runtime & restore full egress"; **Setup admin** for settings and emergency-alert feeds; **Meeting operator** to start and stop channels and to retry a recording's finalization; **Publish operator** for the Publish screen. The roles are listed in [Appendix: roles](#app-roles).
- **Open PowerShell as Administrator** before running any command in this chapter. Commands are shown for PowerShell.
- **Log times are local time.** The log line format is the date and time, the level, the logger name and the message: for example `2026-10-01 18:45:59,040 INFO ...`. The times in the logs are the station computer's clock, in its own time zone, with no zone marker. Several console screens, by contrast, treat a time you type as UTC (Coordinated Universal Time): Recording, the Program Guide and the Schedule. If a scheduled item ran at a different hour than you expected, convert before you conclude that something is broken.
- **Changing an environment variable.** Many settings in this chapter are environment variables. The station's control plane gets the supervisor's own environment plus a few values the supervisor sets itself, and the code comments name the service's `Environment` registry value as the place an operator sets them. We did not find a settings file for them. The steps are in [Running it day to day](#ch-operations), under "Set environment variables for the service": edit that value, then restart the service with `Restart-Service CivicCastSupervisor`. We did not run that sequence on a station, so check the result with the log lines named in each row.
- **Restarting the service interrupts the air.** `Restart-Service CivicCastSupervisor` stops every channel. Do it between programs, or on a channel nobody is watching.
- **Only the station computer can sign in.** The control plane listens on `127.0.0.1` port 8000 only. Sign-in and first setup refuse requests that do not come from the station itself. See [Signing in](#ch-signing-in).

## Where things are logged

Everything below `C:\ProgramData\CivicCast` survives an uninstall and survives a failed setup. Nothing in setup deletes it.

| What you want | File or place | Notes |
|---|---|---|
| Did the Windows service start, restart or give up? | `C:\ProgramData\CivicCast\logs\supervisor.log` | The service itself. Rotates at 10 MiB, keeps 10 old files, and is written to disk on every record. |
| The application's own log (channels, captions, publishing, recording) | `C:\ProgramData\CivicCast\logs\control_plane-app.log` | Most of the log lines quoted in this chapter are here. Old files are named `control_plane-app.log.1` and up. |
| Raw output of the web server process | `C:\ProgramData\CivicCast\logs\control_plane.log` | Crashes before the application logger starts land here. |
| The database server | `C:\ProgramData\CivicCast\logs\postgres.log`, `postgres-launcher.log` | `postgres-launcher.log` is the short-lived start-up output. |
| Why the supervisor stopped trying to start | `C:\ProgramData\CivicCast\STATION-START-FAILED.md` | Written after 3 failed starts in a row with the same error. Removed after the next successful start. |
| What setup did, step by step | `C:\ProgramData\CivicCast\install-progress.log` | Read it from the bottom. Find the last "begin" with no matching "returned". |
| Which pack was missing or untrusted | `C:\ProgramData\CivicCast\install-manifest-report-<pid>-<time>.json` | One per setup run. |
| Upgrade, rollback, provisioning | `C:\ProgramData\CivicCast\upgrade\` (`upgrade-engine.log`, `upgrade-journal.json`, `UPGRADE-RECOVERY.md`) and `provision\` (`PROVISION-RECOVERY.md`, `OWNERSHIP-RECOVERY.md`, `ownership-observation.txt`) | |
| One channel's encoder and relays | `C:\ProgramData\CivicCast\data\egress\<channel>\logs\` (`gst-worker.stdout.log`, `gst-worker.stderr.log`, `hls-relay.<sink label>.stderr.log`) | On the default GStreamer engine the worker logs are named `gst-worker.*`. On the FFmpeg fallback engine they are `ffmpeg.stdout.log` and `ffmpeg.stderr.log`. |
| First-run wizard | `%USERPROFILE%\.civiccast\runtime-host.log` and `installer-state.json` | Per Windows user, not per station. |
| Windows' own record of the service | Event Viewer, Windows Logs, Application, source `CivicCastSupervisor` | Setup exit 126 sends you here. |

Two commands you will use constantly:

```powershell
Get-Content C:\ProgramData\CivicCast\logs\control_plane-app.log -Tail 200
Select-String -Path C:\ProgramData\CivicCast\logs\control_plane-app.log* -Pattern "Caption tap"
```

And one to ask the running station how it is:

```powershell
curl.exe http://127.0.0.1:8000/health
```

The answer is a short JSON document with `status` (`healthy` or `degraded`), `version`, and `schema` (`current`, `behind`, `not-configured` or `unknown`), plus `schema_db_revision`, `schema_expected_head` and `mode`. `status` is `healthy` only when `schema` is `current`; any other schema state reads `degraded`. The HTTP status is 200 whenever the web server process is alive, so read the words in the body, not the number.

## Install and activation (setup exit codes)

Setup returns a number when it fails. Interactive setup shows a dialog with words but not the number; the silent run (`/S`) shows only the number. The full table is in [Reference tables](#reference-tables-ch14). On a failure, setup first puts the service, if it exists, into "stopped, manual start", so a failed install does not leave a half-built station running. Running setup again is the supported recovery.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| Setup stops at exit 110, or a dialog names `.ccpack` files | A required pack is missing or not trusted. A first install needs the `packs` and `station` folders beside `setup.exe`. | `install-progress.log` contains a `step stage-packs: child reported:` line naming the pack; the JSON `install-manifest-report-*.json` has the detail. | Put the full kit (the `packs` and `station` folders, with the files named in the log) beside `setup.exe` and run setup again. |
| Setup stops at exit 111, 112, 121 or 122 | After unpacking, the server tools, the program files, FFmpeg or Ollama do not match their signed list. The copy of the kit is damaged. | The last "begin" in `install-progress.log` is a verify step. | Replace your copy of the kit from the original download and run setup again. |
| Setup stops at exit 123 | Activation failed. The child code says which part: 64 arguments, 65 could not write the report, 66 pack missing or untrusted, 67 activation or self-test failed, 78 the embedded trust key was refused. | `install-progress.log` ends with `step d4-activate-station: returned 67` (or the other child code). | See the next two rows for exit 67. For 66 see exit 110. |
| Exit 123 child 67 on a computer that is short of disk | The same code is used for "not enough free disk space" and for unpacking failures. Activation needs the total size of the packs plus 2 GB of headroom. | The setup details pane shows "Not enough free disk space to activate this station..." | Free disk space and run setup again. |
| Exit 123 child 67 with enough disk | A self-test check failed. The checks include: the Python core imports; PostgreSQL, FFmpeg and Ollama report their pinned versions; TSDuck, if present; a CPU caption test on a sample file (300 second limit); and the three AI models answering (wait limit 300 seconds). | The failing check is named in the setup details pane while setup is open. | Keep the details pane text and the log, then run setup again. If it fails twice for the same reason, collect the items under "What to collect before asking for help". |
| Exit 116 or 117 | PostgreSQL could not be provisioned. | `provision\PROVISION-RECOVERY.md` and the end of `install-progress.log`. | Follow `PROVISION-RECOVERY.md`; run setup again. |
| Exit 127 | Setup cannot tell which CivicCast runtime owns this machine. | `provision\OWNERSHIP-RECOVERY.md`. | If there is no older WSL product, set `HKLM\SOFTWARE\CivicCast\ActiveRuntime` to the text `native`, then run setup again. |
| Exit 135 | The older WSL edition of CivicCast is still registered. | The dialog says so. | Uninstall it, or run its `cutover-to-native`, then run setup again. |
| Exit 118, 119 or 120 | Service registration failed (118), the firewall rule could not be made (119), or the old service could not be stopped before install (120). | `install-progress.log`. The dialog for 118 and 119 names no log path. | Run setup again as Administrator. For 120, stop the service in `services.msc` first. |
| Exit 125 | The service started but the station did not become ready to serve. The dialog names the database schema as the usual cause. | `install-progress.log` and `upgrade\upgrade-engine.log`; then `logs\control_plane.log`. | Fix the cause the logs name, then run setup again. Your data is untouched. |
| Exit 126 | The service is registered but Windows could not start it. | Event Viewer, Application log; `logs\`. | Fix the start-up error it names, then run setup again. |

> **Known issue (beta.10):** The exit-67 dialog tells you the failing self-test is named in `install-progress.log`. It is not. The child's error goes only to the setup details pane, and the log has only the line `step d4-activate-station: returned 67`. If the setup window has closed, the failing check is lost; run setup again and watch the details pane.

> **Known issue (beta.10):** Exit 67 is also returned for "not enough disk space" and for unpacking failures, although the dialog says "NOT a missing-files problem". Check free disk space before you chase a self-test.

> **Known issue (beta.10):** The dialogs never show the exit code, and 27 different codes exist (82 and 110 to 135). This chapter's table is the only place we know of that lists them.

> **Known issue (beta.10):** On a fresh install, the playout engine's first packets can arrive more than 60 seconds after its first start, while the channel already reports its output as "connected" (which is true by design while it shows the fallback slate). Separately, the setup self-test's wait for its private AI runtime was raised from 60 to 300 seconds, because that runtime took 61 seconds to answer in the clean-install test. A slow first minute on a new install is not by itself a fault.

## Sign-in

There is no separate login page. Sign-in is on the **First Setup** screen (`#/setup`), in the **Admin sign-in** card.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| "Invalid admin username or password." | Wrong username or password. | The red alert on the card. | Use the username and password from the recovery kit. If the password is lost, use **Use recovery code**: it consumes one of the 8 one-time codes and sets a new password of 12 or more characters. |
| "Too many sign-in attempts from this station. Wait N seconds, then try again..." | The setup sign-in limiter is cooling down. | The text names the wait. | Wait the number of seconds shown, then use the correct password or a recovery code. |
| "Too many failed attempts to authenticate with the staff API. Wait N seconds, then try again." | 10 bad tokens in 60 seconds from one client address. A request with no token at all does not count. | The text (the console writes it itself), and an HTTP 429 from the API. The API's own `detail` is "Too many failed staff authentication attempts. Wait and retry." with a `Retry-After` header in seconds. | Wait. The limit is set by `CIVICCAST_AUTH_RATE_LIMIT` (default 10) and `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS` (default 60). |
| The card "First setup can only be done from the station computer itself" | You opened the console from another computer, or through a remote-viewer that is not running on the station. | The page is HTTP 403. | Sign in on the station computer itself, or in a remote-desktop session on it. The sign-in and recovery routes accept only loopback requests. |
| Notice "You were signed out", or "This browser's console sign-in is no longer valid" | The station rejected the token (HTTP 401). Most often this browser's session was the oldest and was dropped because the station keeps only 20 console sessions. | The notice appears after a screen change. | Sign in again. Nothing is wrong with the station. |
| A screen says "This action requires one of these CivicCast roles: ..." | The token lacks a role (HTTP 403). | The text lists role ids such as `meeting_operator`. | Sign in as someone who holds the role. The console has no screen that grants roles. |
| The browser shows its own error page for `http://127.0.0.1:8000/operator/` | The service is not running, or this is not the station computer. | `Get-Service CivicCastSupervisor` | See "Station will not start". |

> **Warning:** The code contains a switch, `CIVICCAST_ALLOW_FIRST_ADMIN_RESET`, that its own comments describe as a destructive full station wipe. We did not test it and we do not recommend it. If the password and all 8 recovery codes are lost, ask for help before you try anything else.

## Station will not start

The service is `CivicCastSupervisor` ("CivicCast Native Supervisor"). It runs as LocalSystem, starts automatically, and Windows restarts it after 5, 10 and 30 seconds if it stops. It starts two programs of its own, PostgreSQL and then the control plane (the web server and station engine), plus an optional Ollama AI engine on `127.0.0.1:11434`. The control plane gets 180 seconds to become ready, PostgreSQL gets 60 seconds, and a stop gives each child 15 seconds before it is ended.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| `Get-Service CivicCastSupervisor` says Stopped, and the console will not load | The supervisor gave up. After 3 failed starts with the same error it writes a marker file. | `C:\ProgramData\CivicCast\STATION-START-FAILED.md` exists. In `supervisor.log`: `station could not start: <ErrorType>: <detail>` and `consecutive failed start count is now N`. | Read the reason in the marker file. Fix it, then `Start-Service CivicCastSupervisor`. The marker is removed after a successful start. |
| The marker file's reason is "Native station activation self-test receipt does not match this distribution" | `station-set.json` or `activation-self-test.json` in the install folder is missing, stale or from another build. The service will not start without them. | The reason text. | Run setup again so activation re-creates them. Do not edit either file by hand. |
| `supervisor.log` says `singleton not acquired (<status>): <detail> -- another supervisor owns the station` | A second copy of the supervisor is running. | The line itself. | Stop the other copy. Check `Get-Service` and Task Manager for a second `CivicCast` process. |
| State is `blocked_wsl_active` or `blocked_probe_unavailable` | The older WSL edition is active, or the check for it could not run. | `supervisor.log`. | Remove or cut over the WSL edition (see exit 135 above). |
| `curl.exe http://127.0.0.1:8000/health` returns `"status":"degraded"` | The database schema is not `current`: it is `behind` (older than the program), `not-configured` or `unknown` (the database could not be read). This field says nothing about the other parts of the station. | The `schema` value in the answer, and `supervisor.log`. | `behind`: see "Upgrade problems". `unknown` or `not-configured`: see "Database problems". The next rows cover other faults. |
| `supervisor.log`: `ffmpeg/ffprobe not staged at ... (degraded media handling, ...)` | FFmpeg is missing from the install folder. The station runs, but media preparation is degraded. | The line. | Run setup again to restore the files. |
| `supervisor.log`: `ollama child skipped (degraded AI, service healthy): ...` | The AI engine could not start. Summaries and translation are unavailable; the station is otherwise healthy. | The line. Port 11434 belongs to CivicCast's own Ollama. | Check that another program is not holding `127.0.0.1:11434`. Run setup again if the files are damaged. |
| `supervisor.log` (level ERROR): `... degrading egress to the FFmpeg concat engine (CIVICCAST_EGRESS_ENGINE=ffmpeg-concat) so the channel keeps airing.` | The GStreamer files are damaged. The station tried an in-place self-repair, it did not restore them, and the station switched to the older FFmpeg concat engine. | The line. | On **Readiness**, press **Repair GStreamer runtime & restore full egress** (Setup admin or Support admin). If that fails, run setup again. |

> **Warning:** Do not hand-edit `station-set.json`, `activation-self-test.json` or `STATION-START-FAILED.md`. Re-running setup rebuilds them.

## Channels will not start, or sit on the slate

First, the words. The console shows an egress state in plain words: **Stopped**, **Starting**, **On air**, **Changing source**, **Showing slate**, **Finishing current item**, **Stopping** and **Needs attention**. They correspond to the internal states STOPPED, STARTING, ON_AIR, TRANSITIONING, FALLBACK_SLATE, DRAINING, STOPPING and ERROR. The log line that records every change is:

```
channel <id>: egress state -> <STATE> (source=..., pid=..., last_error=...)
```

The `last_error` part is the reason. Search the application log for it: `Select-String -Path C:\ProgramData\CivicCast\logs\control_plane-app.log* -Pattern "egress state ->"`.

A channel that shows **Showing slate** is on air with the "technical difficulties" picture instead of its program. The station chose that rather than dead air. It is a symptom, not a fault in itself. The `last_error` tells you which of these it is:

| `last_error` text (start of it) | What it means | Fix |
|---|---|---|
| "Preparing the scheduled program; airing the fallback slate so the channel stays up while it conforms." | The next program is not yet in a form that can air (it is being conformed: re-encoded to the station's standard picture and sound). A cold file can take minutes. | Wait. If it happens every time, look at "Program change problems". |
| "No valid source plan is available; generated fallback slate." | Nothing is scheduled and nothing else is available to air. | Schedule something, or check **Auto-schedule** and the Program Guide. |
| "Scheduled source plan expired during preparation; aired fallback slate while automation resolves the current schedule." | The preparation took longer than the item's slot. | Automation resolves it on its own. If frequent, see the preparation times below. |
| "Live source failed repeatedly; aired fallback slate instead of an infinite crash-loop." | The real source failed 5 times in a row without staying healthy for 60 seconds. Automation tries the real source again about every 30 seconds. | Look at `gst-worker.stderr.log` for the source's own error. Fix the source (network stream, file, capture device). |
| "caption storage refused: ..." | The channel could not store caption data, usually a full disk or a permissions problem. | See "Disk full". |
| "egress encoder unavailable; aired fallback slate: ..." | No video encoder could start. See "GPU and encoder problems". | See that section. |

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| **Needs attention** (ERROR) | The start failed and even the slate could not be encoded, or the configuration is invalid or a secret could not be resolved. With no FFmpeg at all there is no path to air anything. | `egress state -> ERROR ... last_error=...` in the application log. | Fix the named cause, then press **Start** again. |
| The channel stays **Starting** and then restarts | The engine produced no output. The worker quits itself so the daemon can restart it. | `gst-worker.stderr.log`: `CTRL first-output: no output within 45s of PLAYING - quitting for daemon restart`. The limit is `CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S`, clamped to between 10 and 120 seconds. | Check the source and encoder rows. If it is only the first start on a new install, wait: see the Known issue above on slow first packets. |
| On air, then silently stops sending | A running worker stopped producing output. | `gst-worker.stderr.log`: `CTRL stall: no output for 10s - quitting for daemon restart`. Application log: `channel <id>: worker exited (exit_code=..., state=..., desired=..., pending_reload=..., deliberate_kill=...)`. | The daemon restarts the worker itself. Look for repeated exits. |
| The picture is frozen but the audio goes on | Video-only freeze. | `gst-worker.stderr.log` lines of the form `CTRL output: <total> buffers (+delta) since PLAYING [mux-in 5.0s: video=+0 audio=+235]`: `video=+0` with audio climbing. | The channel heals the web stream first. After that, see the next row. |
| Log level CRITICAL: `channel <id>: the HLS live window is still frozen N.Ns after the relay self-heal replaced its ffmpeg child ... Freeze escalation budget exhausted (N worker restarts already spent in the last hour): NOT restarting the worker again ... this needs an operator` | The channel's live web stream stayed frozen for more than 30 seconds after the relay was healed, and 3 worker restarts in the last hour are already spent. | The CRITICAL line (repeated at most every 10 minutes). Earlier in the hour you see ERROR lines ending `restart N of at most 3 in the last hour`. | A person has to act. Stop and start the channel from **Channels**, or restart the service between programs. Keep the logs for the support request. |

> **Known issue (beta.10):** A watchdog gap on one path (audit finding A-001) can leave a channel stuck with no one restarting it. If a channel is stuck in **Changing source** with nothing in the logs for more than half an hour (the stall watchdog's own bound is 690 plus 960 seconds, then a 300-second grace period, which is more than half an hour in all), stop and start the channel by hand.

## Program change problems

A program change is the moment a channel moves from one scheduled item to the next. CivicCast tries to do it without a break: it prepares the next item ahead of time and swaps the source at the boundary (a "seamless reload"). If that fails it retries, and then falls back to a restart or to the slate. In the 8-hour run on build C16, 50 program changes happened with no holes. Those numbers come from an earlier internal build, not the published files.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| A change was late by a few seconds, and the log shows a retry | A first-attempt abort at a very short tail boundary. | `Boundary reload for <channel> did not land (...); re-resolving and re-arming (retry N of 2) ...` | None needed. In the lab it healed in about 3 seconds. After the 2 retries are spent: `...retries were spent; arming the fallback slate at the boundary...` |
| The channel restarted at a change instead of swapping | The seamless swap did not land. | `Seamless content-reload for <channel> did not land (...); falling back to restart.` | Look at the `(...)` reason. A restart means a short interruption, not a failure. |
| The slate came up for several minutes at a change | Preparation of the next item was cold and slow. | `Content-reload source preparation for <channel> took N.Ns for N segment(s)`, or `...preparation FAILED ... falling back to restart.` In the lab the longest preparation times were 449 seconds (C15) and 389 seconds (C16). | A 3 to 5 minute slate after a short plan followed by a long item was seen on an earlier internal build, and a look-ahead warm-up was added afterwards. Make sure the next items are in the conform cache (see "Loudness"). |
| The log says the rollover is "past due" | The change should have happened already. | `Channel automation rollover horizon for <channel> is past due by Ns but the seamless reload is still settling; waiting.` or `Channel automation rollover reload for <channel> did not land within Ns (current_proof_event_id unchanged); retrying.` | These are the system retrying. Escalate only if they repeat for many minutes. |
| The channel is pinned at **Changing source** | Reload stall. | `Channel <id>: reload stall -- pinned TRANSITIONING for Ns with nothing in flight ... Re-issuing the rollover now`; if that fails: `reload stall not cleared by the re-issue ... Restarting the channel's egress`. | The watchdog does both steps itself. If it is still stuck afterwards, stop and start the channel. |
| The worker said the commit did not finish | The reload commit did not complete. | `gst-worker.stderr.log`: `CTRL reload: commit did not finish`. | The daemon falls back. |
| A single dropped frame at a join between two pieces | A known single-frame drop. | `CTRL mux diagnostic: dropped future-dated video arrival`. | None. It is one frame. |
| A change aired only the tail of the closing item | The plan was resolved against a short remainder. | `Plan for <channel> resolved to a N.Ns tail of the closing scheduled item`. | Check the schedule's times. Remember that times typed on schedule screens are UTC. |

> **Known issue (beta.10):** In the 8-hour run on build C16, an unexplained rebuild at 07:53 was not resolved before the run ended. We cannot tell you its cause. Keep the logs if you see one.

## No audio, low audio, loudness

CivicCast conforms every program to a loudness target. There are three targets: streaming at -16 LUFS, ATSC A/85 at -24 LKFS (the cable headend standard in the United States) and EBU R128 at -23 LUFS. The headend presets use A/85. For speech, a "leveling ride" raises quiet stretches by up to 18 dB over 4-minute windows. The beta.10 bar for the public stream is -16 LUFS plus or minus 1.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| Speech sounds uneven across a long meeting | The leveling ride failed and the item was conformed with the simpler loudnorm filter instead, which does not hold the level across every 4-minute stretch. | `Speech leveling ride failed for '<name>' (window: ...): ... Conforming with loudnorm instead, which does not hold the level across every 4-minute stretch.` | Re-record or re-upload if the source is damaged. Otherwise accept it; the item still aired. |
| A program is noticeably quiet and the log mentions the loudness gate | The source is quieter than the ride can lift. 18 dB of lift reaches a source down to about -35 LUFS; below that, the window is listed in the report as out of reach and is not counted as a failure. | `Speech leveling for '<name>' (window: ...): the kept attempt misses the loudness gate (worst 4-minute stretch N LU, whole program N LU).` | Fix the recording level at the microphone. A check on one public window read -19.4 LUFS and passed on re-check; that is the quiet-source class. |
| A true-peak error in the log | A peak exceeded the hard bound. | An ERROR line from the loudness module. | Collect the log and the asset id. The program still aired. |
| Conform runs again and again for the same file | The conform cache is too small, so files are evicted and rebuilt. The cache size is `CIVICCAST_CONFORM_CACHE_GB`, default 60. The older default of 20 caused thrash: one 4.4-hour asset took about 11 GB. | `Conform-cache warm failed for '<name>' ... not retrying it for 6h` is the failure line. `0` turns the cache off. | Keep the setting at its default or raise it, and keep the disk free. In the 8-hour run 46 GB of the 60 GB was used. |
| Silence on air, picture present | The source has no audio track, or the audio leg of the worker failed. | `gst-worker.stderr.log`: in the `CTRL output:` lines, `audio=+0`. | Check the source file or capture device. |

> **Known issue (beta.10):** There is no check that stops the 60 GB cache from filling the disk (audit finding A-008). Watch free space. See "Disk full".

## Captions late or missing

There are two different kinds of captions, and they fail in different ways.

- **Live captions on air** (the words burned onto the cable and web picture while a meeting is running) are **off by default in beta.10**. The Station Profile checkbox **Show live captions on air** is off, and the setting `CIVICCAST_CAPTION_TAP=off` forces them off whatever the checkbox says. The caption part of the encoder is built only when a channel starts, so changing the checkbox reaches the picture at that channel's next start, not at the next program change.
- **Captions on recordings** are produced separately, after the fact, and are what viewers of a published recording get. Their failures are in the Publishing and Recording sections, not here.

### What happens to live caption audio under load

When live captions are on, a "tap" copies the channel's audio in 5-second pieces and a worker turns each piece into text, one at a time. On a computer without a suitable graphics card the speech-to-text is done by the CPU, which has to share that CPU with the video encoder. **If the worker falls behind, the station throws the oldest audio away so that the channel stays on air.** Those words never become captions. That is deliberate: the program is more important than its captions. But it means a live caption stream can have holes, and this is the one place where beta.10 is known to lose caption content during a live meeting.

In order of increasing severity, you will see three log lines in `control_plane-app.log`:

1. **Falling behind** (INFO). The worker is catching up and live captions continue:

   ```
   Caption tap is behind for channel <id>: N settled segments is over the maximum 2 on scan N of 15. Transcribing the oldest N now and leaving the rest queued; live captions continue.
   ```

2. **Catch-up discard** (WARNING). The backlog stayed over the maximum for the whole scan window of 15 scans (about 30 seconds). The oldest audio was thrown away and the worker resumed at the newest:

   ```
   Caption tap catch-up for channel <id>: N settled segments stayed over the maximum 2 for the whole 15-scan window. Discarded the oldest N segment(s) (N.Ns of audio, indices N-N) and resumed at the newest N. Live captions continue; the pause is not engaged (shed N of 3 in 300s).
   ```

3. **Overload pause** (WARNING). Three discards inside 300 seconds engage a pause. Live captions stop for a time, any caption on screen is cleared, and the stale audio is discarded:

   ```
   Caption tap overload for channel <id>: N settled segments exceeds the maximum 2. Live captions are PAUSED for Ns (overload #N) so playout keeps the CPU; active captions were cleared and the stale audio was discarded.
   ```

   The pause starts at 120 seconds, doubles with each repeat, and is capped at 900 seconds.

A fourth message looks alarming but is routine housekeeping: `Caption tap discarded N leftover segment(s) for channel <id> at <time>; they belonged to a finished broadcast`. Those segments belonged to a program that already ended. No audio was lost.

How often does it happen? In the 8-hour run on build C16 there were 13 catch-up discard events. Seven small ones coincided with disk scans the lab was running at the time; leaving those out, about 160 seconds of audio was lost on a quiet machine. In the earlier C15 run about 75 seconds was lost. In a 30-minute run (C17) there were none. The discards cluster around the long preparation of a new item, when the CPU is busy. **This is not fixed in beta.10.** Captions can be a legal requirement for public meetings (accessibility rules such as ADA Title II apply to cities); ask your city attorney what applies to you. We cannot tell you that live captions in beta.10 meet any legal standard for completeness.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| No captions on the live picture at all | Live captions are off (the default). | Station Profile checkbox **Show live captions on air**; the caption status card on **Channels** reads "Captions off". | Turn the checkbox on, then stop and start the channel. Also check that `CIVICCAST_CAPTION_TAP` is not set to `off`. |
| Captions have gaps, with lines reading "Caption tap catch-up ... Discarded" | The CPU could not keep up. | `Select-String -Path C:\ProgramData\CivicCast\logs\control_plane-app.log* -Pattern "Caption tap"` and count the `catch-up` lines. | Live GPU captioning needs an NVIDIA graphics card with at least 8 GB of video memory plus the CUDA pack (the cuBLAS and cuDNN libraries). Without that, expect discards when a heavy item is being prepared. Tuning knobs exist (see the next row), but we did not test other values. |
| You want to change how aggressively it sheds | Defaults: maximum backlog 2 segments, a 15-scan persistence window, shed limit 3 within 300 seconds. | Environment variables `CIVICCAST_CAPTION_TAP_MAX_BACKLOG_SEGMENTS`, `CIVICCAST_CAPTION_TAP_OVERLOAD_PERSISTENCE_SCANS`, `CIVICCAST_CAPTION_TAP_CATCH_UP_SHED_LIMIT` (0 turns catch-up off), `CIVICCAST_CAPTION_TAP_CATCH_UP_SHED_WINDOW_SECONDS`, `CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`, `CIVICCAST_CAPTION_TAP_CPU_THREADS`. | Not recommended without testing. We have no measurement showing that any other value is better. |
| The caption status card says "Not verified" or "Caption proof failed" | The proof that the captions actually reached the picture is missing or failed. The card is stale after 120 seconds. | The card on **Channels**. | Check the live captions rows above, then the channel's logs. |
| `supervisor.log`: `Caption tier <tier> at <folder> is staged but has no valid activation self-test receipt ... Starting on the proven floor caption tier instead`, and an alert `caption-tier-degraded` ("Captions are running on the standard tier; the large caption model (...) needs re-validation -- open AI Models") | An optional larger caption model left over from an earlier install has no valid receipt, so the station started on the proven floor tier, the Medium model. | The log line and the alert. | The station works on the Medium caption model. The code says the larger one is to be re-validated from the console (the **AI Models** screen). |
| Captions on H.265 channels | The caption inserter is H.264 only on native Windows. | The log: "HEVC/H.265 cannot embed captions on native Windows -- the caption inserter is H.264-only...". | Use H.264 for channels that must carry captions. |

> **Known issue (beta.10):** The Station Profile screen's help text describes channels being paused with their audio discarded. The code does something more specific: it first catches up by discarding the oldest pieces, and pauses only after three discards inside 300 seconds. The same screen text also warns that, with live captions on, the picture can freeze for 25 to 30 seconds and then catch up in a burst every minute or two, and that a channel can rarely restart itself; the code comments record this as the reason the setting is off by default in this beta. If you quote the screen to a board or an auditor, quote this section instead.

> **Known issue (beta.10):** Caption data is never removed. Review rows, evidence recordings and the `active.vtt` file for each channel keep growing (audit findings B-003, B-004 and B-005). Over weeks this uses disk. See "Disk full".

## Recording failures

Scheduled recording runs inside the station (`CIVICCAST_SCHEDULED_RECORDING`, `inline` or `off`; it looks for new jobs every 10 seconds and plans 600 seconds ahead). Recordings are made by FFmpeg, one process per job.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| The recording job shows "ffmpeg exited before recording started for job ..." | The input could not be opened. | The text in the job's **Failure** column. The channel logs. | Check the input address or capture device and its permissions. |
| "ffmpeg did not create a recording segment for job ..." or "ffmpeg created a zero-byte recording file for job ..." | The input opened but delivered nothing, or the target folder is not writable. | The Failure column. | Check the input is live, and that the folder has space and is not read-only. |
| "No local recording target is configured.", "No production local recording target is configured; only the installer rehearsal target was available." or "No usable local recording target is configured." | No recording folder is set up. | The Failure column. | Configure a local recording target; see [Configuring the station](#ch-configuration). |
| "Recording input preset ... is not available for ... Open Recording and select a detected or configured input preset." | The chosen input is not on this machine. | The Failure column. | Choose a detected input on **Recording**. |
| "Capture file ... does not exist." or "... is empty." | A capture that ended with no media. | The Failure column. | Check the capture source. |
| "Unsupported scheduled recording encoder profile" | The encoder profile name is not one of: copy, default, inherit, h264-1080p, hw-h264-1080p, h264-720p, hw-h264-720p. | The text. | Pick one of those. |
| An amber banner "Scheduled recording runtime is unavailable in this deployment." (HTTP 503) | `CIVICCAST_SCHEDULED_RECORDING` is `off`, or the runtime did not start. | The banner. | Set it to `inline` and restart the service. |
| HTTP 403 on the recording schedule | `CIVICCAST_STATION_ID` does not match (default `civiccast-station`). | The response. | Set the matching value. |
| A recording finished, but the Live room or assets show a failed finalization | The post-recording worker failed. The failure codes are `recording.never_appeared` (waited 1800 seconds), `recording.not_local`, `probe.failed`, `finalize.invalid_trim`, `package.failed`, `cdn.upload_failed`, `worker.interrupted` and `internal.error`. | `GET /api/staff/live/finalizations` or the Live room. | Press **Retry finalization** in the Live room, or call `POST /api/staff/live/sessions/{id}/finalization/retry`. The worker makes 3 attempts by default (`CIVICCAST_FINALIZATION_MAX_ATTEMPTS`), waiting 30 seconds before the second and doubling the wait after each further failure (`CIVICCAST_FINALIZATION_BACKOFF_SECONDS`). The retry call needs the Meeting operator role and answers 409 if the finalization is running or already complete. |
| The schedule ran at the wrong hour | The time was typed as UTC. | Compare the time on the job with the computer's clock. | Re-enter the time in UTC. |
| A recording alert, `scheduled-recording-failure` or `scheduled-recording-dropout` | A job failed, or the input dropped out during the job. | **Alerts** screen. | See the rows above. |

> **Known issue (beta.10):** **Stop** is also offered on a recording job that is still in the `scheduled` state (not yet started). The station refuses it with HTTP 409 ("Cannot stop job ... only ['arming', 'finalizing', 'recording'] are stoppable"), and the screen does not show the error, so nothing seems to happen. **Stop** does work on a job that is arming, recording or finalizing. To stop a job that has not started from running, the usual way is to untick **Enabled** on its schedule; we did not confirm that this also cancels a job that already exists.

> **Known issue (beta.10):** Creating a recording schedule gives no confirmation, and creating the same one again returns 409 "already exists". Check the list before you try again.

## Publishing problems

The Publish screen records "operator-dashboard" as the operator for every approval. Publish targets are the resident portal, Internet Archive, Local NAS (rsync or ZFS), YouTube Live, YouTube VOD, a podcast episode, subscriber notifications and a cable file package. The podcast and subscriber targets are "future": nothing is mailed or posted on publish (the owner parked real sends on 2026-09-02).

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| Approving fails with "Publish preflight blocked: this asset has no manifest_url. Run the packager or fix ingest before approving publish." (HTTP 409) | The recording has not been packaged for the web yet. | The error text. | Wait for packaging, or retry finalization (see above). |
| "Publish blocked: CivicCast cannot queue this recording's caption job ... Nothing was published." (HTTP 409) | The caption job for this recording could not be queued. | The error text. | Check disk space and the caption pack. Then approve again. |
| A target shows a success message but nothing arrived at YouTube or the archive | Providers default to **mock**. Each of `CIVICCAST_PROVIDER_INTERNET_ARCHIVE`, `_LOCAL_NAS`, `_YOUTUBE`, `_MAIL` and `_WEBHOOK` is `mock` unless set to `real`. | Check the environment variables. | Set the variable to `real` and add the credentials listed in [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations). |
| A target you did not tick was reset on a second approval | Approving again rebuilds the whole run and resets unticked targets. | The Publish screen. | Tick every target in one approval. |
| The cable file package row says "not set up (optional)" | `CIVICCAST_CABLE_PACKAGE_OUTPUT_DIR` is not set. | The row. | Set it (see Chapter 15) and approve again. |
| A mailing list or fediverse follower did not hear about a new recording | Subscriber notifications are parked, and federation is off by default. | Nothing is sent by design. | None in beta.10. |

> **Known issue (beta.10):** The Publish screen does not always say when a mock provider did the work. An Internet Archive or Local NAS row carries a "Simulated" note, but the card's headline can still read "Archive verified" (HELP-02), and a YouTube row from the mock provider shows a success message with no simulated note (HELP-03). Before you rely on a publish target, send one test and look at the far end.

> **Known issue (beta.10):** Approving a recording can announce it to federation followers as a hidden side effect when ActivityPub is on. See Chapter 15.

> **Known issue (beta.10):** A second approval resets any target you left unticked (HELP-01). Tick everything in a single approval.

## The portal does not show video

Residents see the portal at `http://127.0.0.1:8000/`. That address works on the station computer. The code binds to `127.0.0.1`, although setup opens a firewall rule for TCP port 8000. We did not test reaching the portal from a second computer (HELP-102). A public site for residents therefore needs something in front of the station that this manual does not describe. Test from the real network before you promise anything to the public.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| The live page says offline or "standing by" | `curl.exe http://127.0.0.1:8000/api/public/live/current` reports a state: `offline`, `on_air`, `on_air_no_web_output` or `standing_by`. | Read `state` and `reason` in the answer. The reasons are "no HLS output configured", "HLS output configured but not serving yet" and "fallback slate, no program on air". | The first needs an `hls` output on the channel (see Chapter 15). The second means the web stream has not started: see the HLS relay row. The third is the slate: see "Channels will not start". |
| The channel is on air, but the web stream is empty | The HLS relay did not start or died. | Application log: `HLS relay up for <channel>`, `HLS relay could not start for <channel> ... ffmpeg is not available`, `HLS relay for <channel> ... restarting the relay child`. The relay's own log is `data\egress\<channel>\logs\hls-relay.<sink label>.stderr.log`. | Restore FFmpeg by running setup again; stop and start the channel. |
| A recording page has no video | The recording has no `manifest_url`, so it was never packaged, or the web copy failed. | Assets screen status; finalization codes above. | Retry finalization. |
| Recordings play on the station but are slow or missing for the public | The CDN selector is on and uploading failed (`cdn.upload_failed`). | Failure code in the finalization list. | Check the CDN settings in Chapter 15. The CDN paths were not exercised in Gate A or in the 8-hour run. |
| Video is not found at all at `/media/live/<channel>/playlist.m3u8` | The channel has no HLS output, or is not running. | `curl.exe -I http://127.0.0.1:8000/media/live/<channel>/playlist.m3u8` | See above. |

> **Known issue (beta.10):** The `finalization-worker-runbook` in the repository says the local media base address defaults to `http://127.0.0.1:8000`. In the code the default is empty, which means addresses relative to the site. We follow the code.

## Disk full

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| Alert `disk-low`: "Low free space: media X GB (min 20)" | Free space on the media or backup drive fell below the limit. The default thresholds are 20 GB for media and 20 GB for backup. | **Readiness** shows "Media space" and "Backup space" in GB free. | Free space. The conform cache (up to 60 GB), old recordings and caption data are the large items. |
| Setup refuses with "Not enough free disk space to activate this station..." | Activation needs the total of the pack sizes plus 2 GB. | The setup details pane. | Free space. |
| Uploads fail with HTTP 507 on the contribute page | The drive is full. | The response. | Free space. |
| Disk fills slowly over weeks | Caption data is never pruned, and the conform cache can grow to 60 GB with no check on free space. | Folder sizes under `C:\ProgramData\CivicCast\data`. | Plan the disk size for the long term; see [Planning your station](#ch-planning). |

> **Known issue (beta.10):** The anonymous contributor upload spools a file to disk before any size limit applies, and can fill the drive (audit finding B-001). If the contribute page is open to the public, watch free space closely.

## Database problems (and why there is no NATS)

CivicCast used to have a message broker called NATS. It was removed (decision 0023, owner decision of 2026-08-20). An in-process event bus replaced it. There is no NATS child to start, to check or to repair. If an old note tells you to look for one, ignore it.

PostgreSQL listens on `127.0.0.1` on the first free port of 5432, 5433, 5434, 5435 and 5544, chosen when the station was provisioned. The control plane finds its database address from the registry value `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl`, readable only by SYSTEM and Administrators, unless the environment variable `DATABASE_URL` overrides it.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| **Readiness** machine health row says the database is **Unreachable**, or alert `db-unreachable`: "Database is not reachable from the host." | PostgreSQL stopped or cannot be reached. | `logs\postgres.log` and `logs\postgres-launcher.log`. | Restart the service. If it fails again, read the PostgreSQL log for the cause (disk full, damaged files). |
| Alert `service-down`: "The CivicCast egress service is not running." | The egress engine is not running. | The alert. | Check `supervisor.log`. |
| Log: `DATABASE_URL source: environment override ...` or `... registry (HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl)` | This is an informational line that says which source won. | The line. | If an old `DATABASE_URL` machine variable points at a database that is gone, remove it. |
| A command-line tool says "DATABASE_URL must point at the CivicCast database before running staff token lifecycle commands." | The `civiccast` command line did not find the database address. | The message. | In an Administrator PowerShell, set `$env:DATABASE_URL` from the registry value for that shell only. |
| `/health` shows `schema` as `behind` | The database has not been migrated to this program's version. | `curl.exe http://127.0.0.1:8000/health` | See "Upgrade problems". |

## GPU and encoder problems

The default encoder path is GStreamer. On Windows, a hardware H.264 request is mapped to the Media Foundation encoder (`mfh264enc`), and the default H.264 software encoder is `openh264enc`. HEVC (H.265) needs hardware; there is no software HEVC in this build.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| The channel does not air its program (it shows the slate, or ends in **Needs attention**). The message "No hardware video encoder was found on this machine. To broadcast on the CPU instead (slower), turn on 'Allow software (CPU) encoding fallback' in this channel's settings, then start the channel again. HEVC/H.265 needs hardware and is not available this way." appears in `last_error`, usually after `egress encoder unavailable; aired fallback slate:` | The pre-flight probe found no hardware encoder. | `last_error` on the channel, and the application log. | Either turn on **Allow software (CPU) encoding fallback** in the channel's settings, or install the drivers for the graphics card. |
| "No hardware HEVC/H.265 encoder is available on this machine. HEVC requires a hardware encoder -- there is no software HEVC in this build..." | An H.265 channel on a computer with no hardware HEVC encoder. | The text. | Use H.264. |
| Log warning: "No hardware video encoder was found; 'allow_software_fallback' is on, so this channel is encoding on the CPU (openh264enc). This is slower and may not keep up with live on a weak CPU." | Software fallback is on. | The warning. | This is informational. On a weak CPU, expect trouble in "Program change problems" and "Captions". |
| Log: `egress encoder unavailable (...); falling back to the technical-difficulties slate rather than dead air.` | Neither the GStreamer nor the FFmpeg encoder could start for the program, so the slate is being encoded instead. | The line, and `last_error` "egress encoder unavailable; aired fallback slate: ...". | Fix the reason after the colon. |
| The channel is in ERROR with no slate | FFmpeg is absent from the machine, so even the slate cannot be encoded. | `last_error` is a message about FFmpeg not found. | Run setup again to restore the files. |
| Live GPU captions will not run | The graphics card has less than 8 GB of video memory, is not NVIDIA, or the CUDA pack is missing. | See "Captions". | See "Captions". |

## Upgrade problems

> **Warning:** In beta.10 the upgrade lane was not run in Gate A. An upgrade from an earlier build is unproven. Back up `C:\ProgramData\CivicCast` (with the service stopped) before you try one.

An upgrade is the same `setup.exe` run over an existing install. The service is stopped (its registration is kept), packs are re-verified, the engine backs up and migrates the database with a rollback, then the service is registered and started again. Setup refuses to put an older version over a newer one.

| Symptom | Likely cause | How to confirm | Fix |
|---|---|---|---|
| Setup exit 113 | The upgrade failed and the rollback also failed. | `C:\ProgramData\CivicCast\upgrade\UPGRADE-RECOVERY.md`. | Follow the steps in that file. |
| Setup exit 114 | This release has a database change that cannot be rolled back, so the automatic upgrade was refused. | The dialog. | No manual path is written in the dialog (HELP-107). Ask for help before you proceed. |
| Setup exit 115 | An unexpected fault in the upgrade step. | `install-progress.log`. | Run setup again; collect the logs if it repeats. |
| Setup exit 124 | The engine was rolled back and the old database is intact. The service is left stopped and set to manual start on purpose. | `upgrade\upgrade-engine.log`. | Read the reason. Do not set the service back to automatic by hand: a successful run of setup restores it. If the dialog says containment was not confirmed, run `sc stop CivicCastSupervisor` and `sc config CivicCastSupervisor start= demand`, then fix the reason and run setup again. |
| Setup exit 128 | The record of an earlier failed upgrade is still on disk. | `upgrade\upgrade-journal.json` exists. | Move that file aside (do not delete it) and run setup again. |
| Setup exit 129 | An older setup was run over a newer install. | The dialog. | Run the newer setup, or uninstall first. |
| After the upgrade `/health` says `schema` is `behind` | The migration did not run. | `curl.exe http://127.0.0.1:8000/health`. | Run setup again; see exit 125. |
| Uninstall exit 82, 133 or 134 | The service could not be confirmed stopped (82, 133), or teardown is incomplete (134, remove by hand). | The dialog. | Stop the service in `services.msc` or restart Windows, then uninstall again. For 134, remove the leftovers in `services.msc`, Windows Firewall and the registry. |

## What to collect before asking for help

Collect these before you ask anyone for help. Together they answer most questions.

1. **The time and what you saw.** Write down the clock time with its zone, the channel, and the words on screen. Say whether anyone changed a setting just before.
2. **The whole `C:\ProgramData\CivicCast\logs` folder** (`supervisor.log`, `control_plane-app.log` and its numbered copies, `control_plane.log`, `postgres.log`), copied while the problem is fresh. Rotation can overwrite old lines.
3. **`C:\ProgramData\CivicCast\install-progress.log`**, the `upgrade` and `provision` folders, and any `STATION-START-FAILED.md` or `install-manifest-report-*.json`, for install and upgrade problems.
4. **The channel's own logs**: everything in `C:\ProgramData\CivicCast\data\egress\<channel>\logs\`.
5. **The health answer**: the output of `curl.exe http://127.0.0.1:8000/health` and of `Get-Service CivicCastSupervisor`.
6. **The version**: it is in the health answer, and the installed version is recorded in the registry value `InstalledVersion` under `HKLM\SOFTWARE\CivicCast\Native`.
7. **The support bundle**, if the console still loads: on **Readiness**, as a Support admin, create the support bundle. It is a JSON file named `<bundle id>.json` in a `support-bundles` folder next to `station-state.json` (the folder can be moved with `CIVICCAST_SUPPORT_BUNDLE_DIR`), and the console offers it for download. It holds the version, platform, which settings are present (without their values), setup, storage and health information, alerts, recent samples and the tail of some logs. Lines that contain a secret marker are dropped.
8. **Command-line status**, if you can run it: `runtime\python.exe -m civiccast.cli runtime status` and `... doctor`, using the `runtime` folder in the install folder. We have not run these on a station; the code supports them. The command list is in [Appendix: command line](#app-cli).

> **Known issue (beta.10):** The support bundle does not collect the logs you most need. It reads `%USERPROFILE%\.civiccast\runtime-host.log` and each channel's `ffmpeg.stdout.log` and `ffmpeg.stderr.log`. The default GStreamer engine writes `gst-worker.*` logs instead, and `supervisor.log` and `control_plane-app.log` are not included at all. Add them by hand (steps 2 and 4).

> **Note:** No dialog, log line or screen in beta.10 names a support address, phone number or issue tracker. Send your collection to whoever supplied the beta to you, or to the project's page on GitHub.

## Reference tables {#reference-tables-ch14}

### Setup exit codes

| Code | Step | Meaning |
|---|---|---|
| 82 | Uninstall | The service stop was not confirmed. |
| 110 | Stage packs | A required pack is missing or untrusted (child code 74), or the optional GPU pack is untrusted (child code 75). |
| 111 | Verify | The unpacked server tools do not match their signed list. |
| 112 | Verify | The unpacked program files do not match. |
| 113 | Upgrade | Upgrade failed and the rollback failed. See `UPGRADE-RECOVERY.md`. |
| 114 | Upgrade | The release has a migration that cannot be rolled back; the automatic upgrade was refused. |
| 115 | Upgrade | An unexpected fault. |
| 116 | Provision | PostgreSQL could not be provisioned. See `PROVISION-RECOVERY.md`. |
| 117 | Provision | An unexpected fault. |
| 118 | Service | The Windows service could not be registered. |
| 119 | Firewall | The inbound rule could not be created. |
| 120 | Pre-install | The existing service could not be stopped, or its state could not be read. |
| 121 | Verify | FFmpeg does not match. |
| 122 | Verify | Ollama does not match. |
| 123 | Activation | Child codes 64, 65, 66, 67 and 78, or another. |
| 124 | Upgrade | The engine was rolled back and the old database is intact. See `upgrade-engine.log`. |
| 125 | Service | The service started but the station is not serving (child code 84). |
| 126 | Service | The service would not start (child code 83). |
| 127 | Provision | Runtime ownership unknown (child code 85). See `OWNERSHIP-RECOVERY.md`. |
| 128 | Upgrade | An earlier failed upgrade's journal is still on disk. |
| 129 | Upgrade | An older setup over a newer install. |
| 130 | Uninstall | You declined the ownership-transfer prompt. |
| 131 | Uninstall | Ownership transfer failed. |
| 132 | Uninstall | Blocked: an active runtime together with a WSL product, or unreadable state. |
| 133 | Uninstall | Service stop unconfirmed; files kept. |
| 134 | Uninstall | Teardown incomplete; remove the leftovers by hand. |
| 135 | Provision | The older WSL edition is registered (child code 87). |
| 3010 | Visual C++ | The Visual C++ runtime installed and Windows needs a restart. We could not confirm that setup itself returns this number. |

Child codes seen: 64 arguments, 65 report write, 66 pack missing or untrusted, 67 activation or self-test, 68 verify, 73 and 74 uninstall preflight, 75 provision or pack, 78 embedded trust key refused, 83 service start, 84 not serving, 85 ownership, 87 other product. A child code of 77 appears in the setup code but its meaning is not named in any text we read. A first install with only `setup.exe` and no kit stops at exit 110 (see the first row of the install table).

### Log line index

| Quote this fragment | Where | Section |
|---|---|---|
| `channel <id>: egress state -> <STATE>` | `control_plane-app.log` | Channels |
| `Boundary reload for ... did not land` | `control_plane-app.log` | Program changes |
| `Seamless content-reload for ... did not land` | `control_plane-app.log` | Program changes |
| `reload stall -- pinned TRANSITIONING` | `control_plane-app.log` | Program changes |
| `Freeze escalation budget exhausted` | `control_plane-app.log` | Channels |
| `CTRL first-output: no output within 45s` | `gst-worker.stderr.log` | Channels |
| `Caption tap is behind` | `control_plane-app.log` | Captions |
| `Caption tap catch-up ... Discarded` | `control_plane-app.log` | Captions |
| `Caption tap overload ... PAUSED` | `control_plane-app.log` | Captions |
| `Speech leveling ride failed` | `control_plane-app.log` | Loudness |
| `HLS relay could not start` | `control_plane-app.log` | Portal |
| `TS relay up for` and `TS relay failed to start` | `control_plane-app.log` | Chapter 15 |
| `degrading egress to the FFmpeg concat engine` | `supervisor.log` | Station will not start |
| `station could not start:` | `supervisor.log` | Station will not start |
| `singleton not acquired` | `supervisor.log` | Station will not start |

## If it did not work

If nothing here matches, do the following in order. First, run `curl.exe http://127.0.0.1:8000/health` and write down the answer. Second, read the last 200 lines of `control_plane-app.log` and `supervisor.log` and look for lines at WARNING, ERROR or CRITICAL level. Third, if the station is not on air and you are able to restart it, restart the service between programs. Fourth, collect the items in "What to collect before asking for help". Do not delete anything under `C:\ProgramData\CivicCast`; it holds the database and every recording.

## Related

- [Signing in and finding your way around](#ch-signing-in)
- [Running the meeting](#ch-running-meeting)
- [Publishing, and what residents see](#ch-publishing)
- [When something looks wrong](#ch-something-wrong)
- [Installing, first run, upgrading, uninstalling](#ch-installing)
- [Running it day to day](#ch-operations)
- [Cable headend, streaming, CDN, federation, emergency alerts, the API](#ch-integrations)

<!-- SOURCES: inventory/screens/installer-failures-and-logs.md; installer-install-layout.md; installer-nsis-service-finish.md; installer-nsis-activation-selftest.md; _shell-signin-and-session.md; health.md; channels.md; recording.md; publish.md; eas.md; generated/env-vars.md; docs/releases/v1.0.0-beta.10-verification.md; ops/beta10-oversight/HANDOFF-2026-10-01.md, audits/audit-lite-whole-repo-beta10-2026-10-02.md; civiccast/captions/tap_worker.py:150-410,900-1070,1810-1830,1955-1995; captions/tap_backoff.py; civiccast/egress/daemon.py (_write_state, _start encoder-unavailable path ~2683-2730, reload paths), egress/automation.py, egress/gst/{bridge,encoder_probe}.py, egress/hls_relay.py, egress/loudness_ride.py, egress/preparer.py; civiccast/native/supervisor/{service,children,start_failure_marker,config}.py; civiccast/app.py (health); civiccast/installer/{service,station_state}.py (support bundle ~3330-3560); civiccast/recording/runtime.py; civiccast/live/finalization_worker.py; civiccast/publish/service.py; civiccast/alerting/resource_sampler.py; civiccast/apps/installer/src-tauri/nsis-hooks-bootstrap.nsh:455-588; civiccast/apps/installer/src-tauri/src/main.rs:4782-4798 (self-test wait); civiccast/native/station_runtime.py:1090-1340 (caption tier, FFmpeg degrade); civiccast/auth/middleware.py:100-160 (429 text); civiccast/installer/router.py:1060-1100; civiccast/app.py:2377-2450 (/health); civiccast/egress/router.py (repair-gstreamer); civiccast/live/router.py (finalization retry); civiccast/live/finalization_worker.py:100-145,823; civiccast/app_platform/router.py; ops/beta10-oversight/verdicts/rung-8h-c16-*--VERDICT-NOTE.md -->
