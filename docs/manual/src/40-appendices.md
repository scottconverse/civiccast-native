# Appendix A: Command-line reference {#app-cli}

CivicCast has one command-line program, `civiccast`. It is for the IT person, not for a clerk or operator: nothing in the operator console requires it. You use it to check the computer, to issue or revoke the access tokens that scripts and tools use, to run the disaster-recovery drill, and to run a few checks on the cable output. Every command below exists in beta.10 (42 commands in 13 groups).

## Where the program is

On the Windows station, the installer puts CivicCast's own copy of Python and the `civiccast` program inside the install folder (normally `C:\Program Files\CivicCast (Native)`; if you chose another folder in setup, use that one). You do not need to install Python yourself. There are two equivalent ways to run it.

| Way | What you type (PowerShell, from any folder) |
| --- | --- |
| The launcher | `& "C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\bin\civiccast.exe" doctor` |
| CivicCast's Python | `& "C:\Program Files\CivicCast (Native)\runtime\python.exe" -m civiccast.cli doctor` |

Replace `doctor` with any command from the tables below. Add `--help` after any command or group to see its options on screen, for example `... civiccast.exe token --help`. A second launcher, `civiccast-runtime.exe`, sits beside it; it runs only the `runtime` group.

> **Tip:** To save typing, put the folder in a variable for the session: `$cc = "C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\bin\civiccast.exe"` and then run `& $cc doctor`.

## Before you run a command

1. **Use an Administrator PowerShell for anything that touches the station's data.** The station's database address is stored in the Windows registry at `HKLM\SOFTWARE\CivicCast\Native` (value `DatabaseUrl`), and only the SYSTEM account and Administrators can read it.
2. **The `token` commands need the database address in the shell.** They print "DATABASE_URL must point at the CivicCast database before running staff token lifecycle commands." when it is missing. Set the environment variable `DATABASE_URL` for that PowerShell window from the registry value (the value contains the database password; do not paste it into tickets or chat).
3. **A command that changes something changes the live station.** `token revoke` cannot be undone; issue a new token instead.

> **Warning:** Do not run the `runtime cutover-to-native` or `runtime rollback-to-wsl` commands on a station that has never had the older WSL-based CivicCast edition. They exist to move a machine between the two editions; the supervisor refuses to start the station while the guard thinks the other edition is active.

## How to read the tables

Each command has its own small table. The columns are:

| Column | Meaning |
| --- | --- |
| Option / argument | What you type after the command. `--name` options are optional unless the table says `(required)`. A word with no dashes (an *argument*) is positional: you type the value in that place. |
| Type | `str` is text, `int` a whole number, `path` a file or folder path, `boolean` a switch you add with no value. |
| Default | What the command uses when you leave the option out. Blank means no default. |
| Env var | An environment variable that supplies the value when the option is left out. Blank means none. |
| What it does | The program's own help text. |

Nearly every command accepts `--json`. It prints one machine-readable record instead of sentences, which is what you want in a script.

## The commands you will use most

| Command | Use it to | Notes |
| --- | --- | --- |
| `civiccast doctor` | Probe this computer: CPU, memory, disk, graphics card, operating system and the recommended hardware tier. | Add `--profile` for the full station-box profile (playout engine, clock, AI default, readiness). |
| `civiccast token issue` | Make an access token for a script or tool (see [Appendix B](#app-api)). | The secret is printed once. Default scope is `operator`, which means all five roles; narrow it with `--scopes`. |
| `civiccast token list`, `revoke`, `rotate` | See, retire or replace tokens. | `list` never shows secrets. Needs `DATABASE_URL`. |
| `civiccast dr run-drill --out <folder>` | Run the real disaster-recovery drill: back up the database, restore it into a fresh copy, test crash recovery. | The same drill is a button on the Readiness screen. Read [Appendix G](#app-checklists). |
| `civiccast cable doctor` | Run the read-only cable-headend readiness checks. | `--profile` defaults to `public-meetings`. |
| `civiccast cable commission` | Run the whole cable commissioning flow. | Sends a test signal to the headend address you give it. Do not run it while that channel is live. |
| `civiccast live-takeover state`, `take`, `return` | Check, begin or end a live takeover of one channel from the command line. | Uses the same takeover service and readiness gate as the Channels screen. |
| `civiccast egress verify` | Run a bounded TSDuck check of the channel's headend stream. | Needs the TSDuck tool (optional component). |
| `civiccast model state` | Print which AI models are installed and proven. | `model download` fetches models; `model import-offline` verifies an offline bundle. |
| `civiccast activitypub keygen` | Generate the station's federation key and print the settings to add. | Federation is off by default. |

## Full command tables

The tables below are generated from the program itself, so they match beta.10 exactly.

<!-- INCLUDE: ops/docs-sprint/inventory/generated/cli.md -->

<!-- SOURCES: inventory/generated/cli.md; civiccast/cli.py:2040-2180 (token commands, DATABASE_URL message), :2746-2755 (main_entrypoint); pyproject.toml:138-144 (two launchers); civiccast/native/app_payload.py:116-130 (bin/civiccast.exe inside site-packages); civiccast/native/supervisor/install_layout.py:95-100 (runtime\Lib\site-packages); civiccast/native/supervisor/service_env.py:74-78 (DatabaseUrl registry value); inventory/screens/installer-install-layout.md section 4 (registry ACL); civiccast/native/runtime_cli.py:1-40 (runtime group is for the WSL edition) -->

# Appendix B: HTTP API overview {#app-api}

CivicCast's web pages are built on an HTTP API: the operator console and the resident portal are both clients of it. IT staff and integrators can call the same API. This appendix explains who may call what; the generated tables at the end list every route.

## Where it is

On the station itself the API answers at `http://127.0.0.1:8000`. The program binds to the loopback address only, so it cannot be reached from other computers as installed, even though setup also opens Windows Firewall port TCP 8000 (see [Appendix D](#app-files)). Reaching it from elsewhere on the network needs something that you add, such as a reverse proxy. The same server serves the operator console at `/operator/` and the resident portal at `/`.

## The three groups of routes

| Group | Path starts with | Operations | Route groups | Who may call it |
| --- | --- | --- | --- | --- |
| Public | `/api/public/` | 53 | 19 | Anyone who can reach the server. No token. These feed the resident portal: channels and live status, schedule, recordings, search, captions, subscriptions, public agendas, the contributor form, the paywall status, and the app settings. |
| Staff | `/api/staff/` | 415 | 52 | Holders of a staff access token, and then only for the roles that route allows (see [Appendix F](#app-roles)). These feed the operator console. |
| Setup | `/api/setup/` | 7 | 6 | The station computer itself. First setup, sign-in, recovery and storage preparation. |
| Other | root and a few fixed paths | 13 | 4 | Protocol and utility routes (see below). |

In total the beta.10 server exposes 488 operations on 405 paths in 81 groups.

The 13 "other" operations are: ten at the root level (`/health`, the two federation discovery routes `/.well-known/nodeinfo` and `/.well-known/webfinger`, `/nodeinfo/2.0`, the four ActivityPub routes `/ap/actor`, `/ap/followers`, `/ap/inbox`, `/ap/outbox`, and the media file routes `/media/live/...` and `/media/vod/...`), plus `/api/hardware`, `/api/version` and the signed Stripe webhook `/api/webhooks/stripe`. None of these is covered by the staff-token check.

> **Note:** `GET /health` always answers with HTTP 200 while the program is running. Read the `status` field instead: `healthy` means the database layout matches the program; `degraded` means it does not. `schema` is one of `current`, `behind`, `not-configured` or `unknown`.

## How a caller proves who it is (the auth model)

1. **Staff routes need a bearer token.** Send the header `Authorization: Bearer <token>` with every request. A request with no header gets HTTP 401 and does not count against the lock-out limit.
2. **Where tokens come from.**
   - Sign in as the first admin: `POST /api/setup/login` from the station computer returns an `operator_console_token`. This is what the console does. The same call from another computer is refused with HTTP 403.
   - Or issue a token with `civiccast token issue` ([Appendix A](#app-cli)). The console has no screen for pasting such a token in; it is for scripts and tools.
   - Or list tokens in the `CIVICCAST_STAFF_TOKENS` setting (an older method; the server cannot revoke these, so you retire one by changing the setting). On a station that has its database token store, as the native station does, these entries are honored only when `CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB=1` is also set.
3. **A token carries scopes, and scopes become roles.** `admin` and `operator` mean all five roles; `setup_admin`, `meeting_operator`, `records_clerk`, `publish_operator` and `support_admin` (also written `setup`, `meeting`, `records`, `publish`, `support`) mean one role each. A token with no scopes has no roles.
4. **Each route names the roles that may use it.** A signed-in caller with the wrong role gets HTTP 403: "This action requires one of these CivicCast roles: ..." followed by the role names in alphabetical order.
5. **Rate limit.** Ten failed token checks in 60 seconds from one client address earns HTTP 429 ("Too many failed staff authentication attempts. Wait and retry.") with a `Retry-After` header. The numbers are settings (`CIVICCAST_AUTH_RATE_LIMIT`, `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS`). A caller that sends the exact right token is not blocked by other people's failures.
6. **Read versus write.** In beta.10 almost every `/api/staff/` route that changes something requires a role. The staff routes with no role requirement are all reads (lists, status, thumbnails) plus `POST /api/staff/auth/sign-out`; for those any valid token is enough. In the console this shows up as screens a role can open but cannot use ([Appendix F](#app-roles)).
7. **Maintenance mode.** While the service holds the station in maintenance mode (the installer does this during an upgrade, and during a hand-over between CivicCast editions), every request that changes data (POST, PUT, PATCH, DELETE) is refused with HTTP 503 and the body `{"error": "maintenance"}`. Reads still work.

> **Known issue (beta.10):** Nothing in the console lets you create operators or assign roles. The first admin and anyone signing in with that admin's password or a recovery code gets scope `admin`, which is all five roles. Role-limited behavior appears only for tokens you issue yourself on the command line.

## Getting the OpenAPI document

The OpenAPI document is the machine-readable list of every route, its inputs and its answers. On a native station it is served at `GET /openapi.json` and requires a staff token (the same bearer header as above):

```
Invoke-RestMethod -Uri http://127.0.0.1:8000/openapi.json -Headers @{ Authorization = "Bearer <token>" }
```

The interactive pages `/docs` and `/redoc` are switched off on a native station, because they load their pictures and scripts from the public internet and a council chamber computer is often not allowed to reach it. The project's source repository carries a copy of the document at `docs/openapi.json` (405 paths for beta.10).

## Error answers

Branch on the HTTP status first. The `detail` field is text for ordinary errors, an object for a version conflict (HTTP 409 with version fields) and a list of field errors for bad input (HTTP 422). The common texts are in [Appendix E](#app-status).

## Full route tables

<!-- INCLUDE: ops/docs-sprint/inventory/generated/api.md -->

<!-- SOURCES: inventory/generated/api.md (counts computed from its tables: 488 operations, 53 public, 415 staff, 7 setup, 13 other); civiccast/auth/middleware.py:26-175 (bearer check, 401/429, only /api/staff/); civiccast/auth/roles.py:14-100 (roles, aliases, 403 text); civiccast/auth/rate_limit.py:66-76; civiccast/auth/tokens.py:62-182 (CIVICCAST_STAFF_TOKENS, FALLBACK_WITH_DB at :166-170); civiccast/app.py:2972 (staff_token_store); civiccast/app.py:2093-2200, 3660-3690 (LAN-only: /docs and /redoc off, /openapi.json behind token), :690-730 (maintenance 503), :2377-2430 (/health); civiccast/native/station_runtime.py:794 (CIVICCAST_LAN_ONLY_STATION=1 on a native station); civiccast/installer/router.py:1211-1312 (setup routes loopback only); civiccast/native/supervisor/core.py:393-394 (127.0.0.1:8000); docs/openapi.json (405 paths); inventory/screens/_shell-signin-and-session.md; role scan of the loaded app (see Appendix F) -->

# Appendix C: Settings and environment variables {#app-settings}

CivicCast's low-level settings are *environment variables*: named values that Windows hands to a program when it starts. Most day-to-day choices are made on screens (Station Profile, AI Models, and so on); environment variables are for things the screens do not offer, such as how big the cache of prepared video may grow, or which ports the internal relays use. Changing one is an IT job.

## How the names are built

Every CivicCast setting starts with `CIVICCAST_` followed by capital letters and underscores, for example `CIVICCAST_CONFORM_CACHE_GB`. Values are plain text; a number is typed as digits. Yes/no switches usually accept `1` or `0` (some also accept `on`, `off`, `true`, `false`, `yes`, `no`; the table does not say which, so check the setting's own text before relying on a spelling). A few settings are also known by older or shorter names; the table lists each name exactly as the code reads it.

## The one-C spelling trap

The prefix is spelled **C-I-V-I-C-C-A-S-T** (two C's in the middle, nine letters). A setting typed **CIVICAST_** (one C, eight letters) looks almost identical and is silently ignored by anything that reads the correct name. This has already happened in the product's own code. The rule for beta.10:

1. **Use the two-C spelling for every setting**, with the exceptions in the next point.
2. **Four product settings are read only under the one-C spelling.** For these, the correct two-C spelling does nothing:
   - `CIVICAST_CAPTION_PROOF_POLL_SECONDS` (how often the on-air caption proof runs; default 30)
   - `CIVICAST_CAPTION_PROOF_TIMEOUT_SECONDS` (time limit for one proof; default 15)
   - `CIVICAST_GST_LEG_RATE_DIAG` (a diagnostic log line; on unless set to `0`, `off`, `false` or `no`)
   - `CIVICAST_WORKER_PERSISTENT` (set by the product itself; leave it alone)
3. **Two settings accept both spellings.** `CIVICCAST_EGRESS_PREPARATION_TIMEOUT_SECONDS` (default 300) and `CIVICCAST_GSTREAMER_SOURCE_SEGMENT_SECONDS` (default 1800) are read through a resolver. It uses the two-C name when that is set to something other than blank. Otherwise it uses the one-C name and writes a one-time "deprecated" warning to the log. When both are set and differ, the two-C value wins and a warning names both. A blank value counts as not set at either spelling. The one-C names will stop being read in a future release.
4. **Everything else in the table with one C is not for stations.** `CIVICAST_CI_SOURCE_SHA`, `CIVICAST_CLEANROOM_*`, `CIVICAST_EXPECTED_VERSION` and `CIVICAST_KEEP_PASSING_UI_EVIDENCE` belong to the project's build and test scripts. `CIVICAST_CONTROL_ROOM_TSR_URL` appears only in a test file (the setting the product reads is `CIVICCAST_CONTROL_ROOM_TSR_URL`). `CIVICAST_OBS_WEBSOCKET_PASSWORD` is read only by a laboratory test tool. `CIVICAST_WSL_DRIVE_MOUNT_ROOT` and `CIVICAST_TRANSLATE_WINDOWS_BACKUP_PATHS` belong to the retired WSL edition.

> **Tip:** After setting any value, restart the service and read the end of `C:\ProgramData\CivicCast\logs\control_plane-app.log`. A setting with the wrong name is not logged at all, which is why the spelling matters. How each setting treats a bad value differs (the cache size, for example, silently falls back to its default), and we did not check every setting.

## How to set a setting for the service

CivicCast runs as the Windows service `CivicCastSupervisor`. The service starts the control plane and the other programs with its own environment plus a small set of fixed values it adds last. So a setting must be in the **service's** environment, not in your own PowerShell window.

1. Open Registry Editor as Administrator.
2. Go to `HKLM\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor`.
3. Add or edit the multi-string value named `Environment`. One setting per line, written `NAME=value`, for example `CIVICCAST_CONFORM_CACHE_GB=80`.
4. Restart the service: in PowerShell, `Restart-Service CivicCastSupervisor`. Stopping it takes up to 15 seconds per child program; a channel on air goes off air while the service restarts.

> **Warning:** Restarting the service stops every channel. Do it between meetings.

> **Note:** Code comments in the product describe this `Environment` value as the place a station's settings live, but we found no installer code that writes it, so on a fresh install it may not exist and you create it. If you also set a machine-wide Windows environment variable, the service inherits it when it starts; the per-service value is the one the product documents.

### Settings the service sets for itself

The station sets these when it starts the control plane. Do not set them yourself.

| Setting | Value the service gives it |
| --- | --- |
| `CIVICCAST_EGRESS_WORK_DIR` | `C:\ProgramData\CivicCast\data\egress` |
| `CIVICCAST_UPLOAD_DIR` | `C:\ProgramData\CivicCast\data\uploads` |
| `CIVICCAST_SUPERVISED` | `1` |
| `CIVICCAST_LAN_ONLY_STATION` | `1` (turns off `/docs` and `/redoc`, puts `/openapi.json` behind a token) |
| `CIVICCAST_OPERATOR_CONSOLE_DIST`, `CIVICCAST_PUBLIC_PORTAL_DIST` | the folders holding the two web portals |
| `CIVICCAST_NATIVE_STATION`, `CIVICCAST_NATIVE_STATION_ROOT`, `CIVICCAST_NATIVE_STATION_MANIFEST` | the activated station |
| `CIVICCAST_CAPTION_RUNTIME`, `CIVICCAST_CAPTION_TIER`, `CIVICCAST_WHISPER_MODEL_PATH`, `CIVICCAST_WHISPER_DEVICE`, `CIVICCAST_WHISPER_COMPUTE_TYPE`, `CIVICCAST_EGRESS_EMBED_CAPTIONS` | caption model choices made at activation |
| `DATABASE_URL` | read from the registry value `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl` unless it is already set in the service environment (an environment value wins) |
| `OLLAMA_HOST`, `OLLAMA_MODELS`, `OLLAMA_NO_CLOUD`, `NO_PROXY` | for the AI engine: `127.0.0.1:11434`, the model folder, cloud use off |

`CIVICCAST_CAPTION_TAP` is the one exception: if you set it to the exact word `off` in the service environment, the service passes that through and live caption audio tapping stays off; any other value leaves the normal behavior.

### A few settings worth knowing

Each default below is read from the code. The full list follows in the generated table.

| Setting | What it does | Default |
| --- | --- | --- |
| `CIVICCAST_CONFORM_CACHE_GB` | How large the folder of prepared copies of programs (the *conform cache*) may grow, in gigabytes. | 60 |
| `CIVICCAST_AUTH_RATE_LIMIT` / `CIVICCAST_AUTH_RATE_LIMIT_WINDOW_SECONDS` | Failed token checks allowed per client address, and the window in seconds. | 10 / 60 |
| `CIVICCAST_EGRESS_PREPARATION_TIMEOUT_SECONDS` | Longest one video preparation step may run. Accepts either spelling. | 300 |
| `CIVICCAST_GSTREAMER_SOURCE_SEGMENT_SECONDS` | How far ahead the playout engine prepares a program. Accepts either spelling. | 1800 |
| `CIVICCAST_AUTOMATION_PASS_WATCHDOG_SECONDS` / `..._REPEAT_SECONDS` | When one channel-automation pass has run so long that its stack is written to the log, and how often it repeats. | 30 / 60 |
| `CIVICCAST_HLS_RELAY_BASE_PORT` | First of 500 local UDP ports used by the web-video relays. | 18000 |
| `CIVICCAST_TS_RELAY` | Cable relay mode: `auto`, `on` or `off`. | auto |
| `CIVICCAST_TS_RELAY_BASE_PORT` | First local UDP port used by the cable relay. | 17800 |
| `CIVICCAST_LIVE_SOURCE_READINESS_TTL_SECONDS` | How long a "Delivering" source check stays fresh on the Live screen (clamped 5 to 300). | 30 |
| `CIVICCAST_STAFF_TOKENS` | Older way to list staff tokens, one entry per token. | unset |
| `CIVICCAST_STATION_NAME`, `CIVICCAST_STATION_TZ`, `CIVICCAST_STATION_MEDIA_LIBRARY`, `CIVICCAST_STATION_RECORDINGS`, `CIVICCAST_STATION_BACKUPS` | Overrides for what Station Profile shows. | per Station Profile |
| `CIVICCAST_ACTIVITYPUB_*` | Federation switches (mode, handle, base URL, key path). Off by default; see [Chapter 15](#ch-integrations). | off |

> **Warning:** The Live screen's checks need 50 GiB free on the drive that holds `CIVICCAST_UPLOAD_DIR`, regardless of how small a meeting is. That number is built into the program and is not a setting.

## The full table

How to read it. **Name**: exactly as the code reads it. **Prod refs**: how many places in the product source (tests excluded) use the name; a count of 1 or 2 means a narrow setting. **First location**: where to look in the source. **Documented**: whether the name appears in a prose document in the repository. **Notes**: only the one-C rows have a note.

A few rows are not real settings. Names ending in an underscore (for example `CIVICCAST_FASTLY_`) are family prefixes written in code comments. `CIVICCAST_ALERT` is the name of an installer script macro, not a setting. 412 names appear: 396 with the correct spelling and 16 with one C.

<!-- INCLUDE: ops/docs-sprint/inventory/generated/env-vars.md -->

<!-- SOURCES: inventory/generated/env-vars.md; civiccast/egress/env_vars.py:1-118 (resolver rules); civiccast/app.py:1673-1677 (one-C caption proof names, defaults 30 and 15); civiccast/egress/gst/engine.py:656,3337-3345; civiccast/egress/gst/reload_policy.py:75; civiccast/egress/preparer.py:92,296-370 (300 s, CONFORM_CACHE 60); civiccast/egress/source_plan.py:75,126-170 (1800 s); civiccast/egress/automation.py:265-275 (watchdog 30/60); civiccast/egress/hls_relay.py:251-256,328-347; civiccast/egress/ts_relay.py:28-54,117; civiccast/auth/rate_limit.py:66-76; civiccast/live/readiness.py:78-84 and inventory/screens/live.md; civiccast/native/supervisor/service.py:483 (env = os.environ + spec.env); civiccast/native/supervisor/children.py:272-300,541-547,680-684; civiccast/native/station_runtime.py:766,794,1340-1443; civiccast/native/supervisor/service_env.py (DATABASE_URL); egress/env_vars.py:8-10 and station_runtime.py:1345-1349 (service registry Environment REG_MULTI_SZ; no writer found in installer sources); docs/USER-MANUAL.md:1048-1054 (one-C caption proof names confirmed) -->

# Appendix D: Files, folders, ports and services {#app-files}

Where CivicCast puts things on a Windows station, what runs, and what listens on the network. All paths assume the defaults: install folder `C:\Program Files\CivicCast (Native)` (called `<I>` below) and data folder `C:\ProgramData\CivicCast`. The data folder follows the Windows `PROGRAMDATA` setting if your machine moves it.

## Folders created by setup

### The install folder `<I>`

Everything here is program files. Changing it needs Administrator rights, and uninstalling deletes it.

| Path | What is in it |
| --- | --- |
| `<I>\CivicCast Native.exe` | The setup and first-run program. |
| `<I>\uninstall.exe` | The uninstaller. |
| `<I>\vc_redist.x64.exe` | The Microsoft Visual C++ runtime installer that setup runs first. |
| `<I>\runtime\` | CivicCast's own copy of Python 3.12, the CivicCast program, and both web portals. `runtime\python.exe` runs the program; `runtime\pythonservice.exe` hosts the Windows service. |
| `<I>\runtime\Lib\site-packages\bin\civiccast.exe` | The command-line program ([Appendix A](#app-cli)). |
| `<I>\packs\native-server-binaries\payload\` | PostgreSQL programs, and `tsduck\bin\tsp.exe` when TSDuck is shipped. |
| `<I>\packs\.station-cache\` | The cache of the large AI-model packs that setup unpacked from. About 21 GB, according to setup's own text. |
| `<I>\packs\captions-floor\` | The standard (Medium) caption model. |
| `<I>\dependencies\ffmpeg\bin\` | `ffmpeg.exe` and `ffprobe.exe`. |
| `<I>\dependencies\ollama\` | The Ollama AI engine (version 0.30.6). |
| `<I>\dependencies\cuda\` | Optional graphics-card libraries. |
| `<I>\components\<name>\` | The AI models: `summary-gemma4-12b`, `summary-gemma4-e4b`, `translation-translategemma-4b`, and the optional `captions-large-v3`. |
| `<I>\models\ollama\` | The merged AI model store that the Ollama engine reads. |
| `<I>\station\` | The signed station index and `core.ccpack`. |
| `<I>\station-set.json`, `<I>\activation-self-test.json` | Proof that activation and the self-test passed. The service will not start without them. |

### The data folder `C:\ProgramData\CivicCast`

This is everything that belongs to your station. **Uninstalling does not delete it** (no step in the uninstall code removes it).

| Path | What is in it |
| --- | --- |
| `data\pgdata\` | The PostgreSQL database cluster: all station records. Locked down to the system and administrators. |
| `data\uploads\` | Media uploaded by operators, and recordings that finish into the library (`CIVICCAST_UPLOAD_DIR`). |
| `data\egress\` | The playout engine's working folder: the plans, the prepared copies of programs, and the HLS web output. |
| `data\egress\conform-cache\` | The conform cache: prepared, ready-to-play copies of long programs. Limited to `CIVICCAST_CONFORM_CACHE_GB`, default 60 GB. |
| `data\caption-tap\` | Working folder for live captions. |
| `packs\` | Components the first-run wizard downloaded (same layout as `<I>\packs`). |
| `components\captions-large-v3\` | The optional Large caption model, if downloaded. |
| `logs\` | The logs (next section). |
| `install-progress.log` | Time-stamped notes from setup. First place to look when setup fails. |
| `install-manifest-report-<number>-<time>.json` | A report of which packs setup staged, one file per run. |
| `upgrade\` | `upgrade-engine.log`, `upgrade-journal.json` and `UPGRADE-RECOVERY.md` from the last upgrade. |
| `provision\` | `PROVISION-RECOVERY.md`, `OWNERSHIP-RECOVERY.md`, `ownership-observation.txt` and the database set-up journal. |

> **Warning:** Not everything the station needs is in `C:\ProgramData\CivicCast`. The station's own settings file `station-state.json` (the station profile, the first admin's sign-in record and the recovery-kit state) is read from `%LOCALAPPDATA%\CivicCast\` of the account the service runs as, unless `CIVICCAST_STATION_STATE_PATH` points elsewhere. The service runs as LocalSystem, so on a standard install that should be the system profile (`C:\Windows\System32\config\systemprofile\AppData\Local\CivicCast`; we did not inspect a running station to confirm it). The three default storage folders shown on Station Profile (`media`, `recordings`, `backups`) default to that same place. Include it in your backups, and check what Station Profile shows on your machine.

### Per-user files from the first-run wizard

| Path | What |
| --- | --- |
| `%USERPROFILE%\.civiccast\installer-state.json` | The wizard's saved progress. |
| `%USERPROFILE%\.civiccast\runtime-host.log` | The wizard's log. |

### Registry

| Key | What |
| --- | --- |
| `HKLM\SOFTWARE\CivicCast\Native` | `DatabaseUrl` (readable only by SYSTEM and Administrators; it holds the database password) and `InstalledVersion`. |
| `HKLM\SOFTWARE\CivicCast` | `ActiveRuntime` (which CivicCast edition owns the machine), `Maintenance`, `NativeUninstallPostclearPending`. |
| `HKLM\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor` | The Windows service. Its `Environment` value is where the product's code comments say service settings go; we found no installer code that creates it ([Appendix C](#app-settings)). |

### Shortcuts

Start menu: **CivicCast Operator Console** and **CivicCast Public Portal** (internet shortcuts to `http://127.0.0.1:8000/operator/` and `http://127.0.0.1:8000/`). Desktop: **CivicCast Operator Console**. If the service is stopped, these open a browser error page.

## Logs

All service logs are in `C:\ProgramData\CivicCast\logs`.

| File | What it records |
| --- | --- |
| `supervisor.log` | The Windows service itself: starts, stops, restarts of the child programs, watchdog messages. Rotates at 10 MiB, keeps 10 old files, written to disk on every line. |
| `control_plane-app.log` | The CivicCast program's own log: the one to read first when something on a screen fails. |
| `control_plane.log` | Raw console output of the control plane. |
| `postgres.log` | The PostgreSQL server. |
| `postgres-launcher.log` | Short-lived output from starting PostgreSQL. |
| `ollama.log` | The AI engine, when it is running (by the same naming rule: one log per child program). |

The Windows Event Log also receives service messages under the source `CivicCastSupervisor`. Setup problems are in `install-progress.log` (read it from the bottom up; find the last "begin" that has no matching "returned").

## The Windows service

| Item | Value |
| --- | --- |
| Name | `CivicCastSupervisor` (display name "CivicCast Native Supervisor") |
| Starts | Automatically with Windows. |
| Runs as | LocalSystem. |
| If it crashes | Windows restarts it after 5 seconds, then 10, then 30. |
| What it launches | PostgreSQL, then the control plane (the web server and playout engine), and the Ollama AI engine when its files are present. They start in that order and stop in reverse; each gets 15 seconds to stop politely before it is ended. |
| Restarting a child | After a child program fails, the service retries with a delay that grows from 1 second to 30 seconds. Five restarts within ten minutes put the station in the `degraded` state (the service stays up). |
| Only one copy | A system-wide lock named `Global\CivicCastSupervisorSingleton` stops a second copy. |
| Control channel | A Windows named pipe, `\\.\pipe\civiccast-supervisor`. Not a network port. |

Control it from an Administrator PowerShell: `Get-Service CivicCastSupervisor`, `Restart-Service CivicCastSupervisor`, `Stop-Service CivicCastSupervisor`.

## Ports

The "Address" column is the network address the program listens on. `127.0.0.1` means only programs on the same computer can connect.

| Port | Protocol | Who listens | Address | What it is for |
| --- | --- | --- | --- | --- |
| 8000 | TCP | The control plane (`uvicorn civiccast.app:create_app`) | `127.0.0.1` | The operator console (`/operator/`), the resident portal (`/`) and the whole API. |
| 5432, or the first free of 5433, 5434, 5435, 5544 | TCP | PostgreSQL | `127.0.0.1` | The database. Setup picks the first free port in that order and records it in the database address; the service reads the port from there. |
| 11434 | TCP | The Ollama AI engine | `127.0.0.1` | The local AI engine used for meeting summaries and Spanish translation. |
| 38474 | TCP | `CivicCast Native.exe` | `127.0.0.1` | A "one copy at a time" lock for the setup program. Not for any other use. |
| 18000 to 18499 | UDP | `ffmpeg` (one per web-video output) | `127.0.0.1` | The internal relay that turns the playout engine's stream into HLS web video. The start can be moved with `CIVICCAST_HLS_RELAY_BASE_PORT`; each output uses one port in a 500-port range. |
| 17800 and up | UDP | `tsp.exe` (TSDuck), one per channel and cable destination | `127.0.0.1` | The cable relay, used only when a cable (`udp-ts`) output exists and TSDuck is present. Its outgoing source ports sit 1,000 higher (18800 and up). Start moved with `CIVICCAST_TS_RELAY_BASE_PORT`. |
| none | Named pipe | The supervisor | local | The service's control channel (above). |

There is **no** CivicCast listener on any non-loopback address in the supervisor's normal configuration.

> **Known issue (beta.10):** Setup adds a Windows Firewall rule named "CivicCast (Native) Portal/API (TCP 8000)" that allows inbound TCP 8000 on all network profiles for `<I>\runtime\python.exe`. But the control plane listens only on `127.0.0.1`, and no setting changes that. As built, other computers on the network cannot open the console or the portal even though the firewall rule is open. If residents or staff need to reach the station from other computers, that has to be done with something you add in front of it (a reverse proxy on the same machine, for example). Test it before promising it to anyone.

### Connections the station makes outward

| Where to | Port | When |
| --- | --- | --- |
| `1.1.1.1` and `8.8.8.8` | TCP 443 | The Live screen's "Network reachable" pre-flight check connects to these to prove the station has internet. A station with no internet cannot pass that check. |
| Your cable headend or encoder | the address and port you set | A `udp-ts` cable output, and the commissioning test. |
| Streaming destinations | the address you set | SRT, RTMP, HLS and NDI outputs you add on Channels. |
| Alert destinations | email, text-message or webhook address you set | Alerts, when destinations are connected. |
| Hosted AI services | HTTPS | Only if you switch an AI job to a hosted model on AI Models. The Ollama engine itself is started with cloud use switched off. |

VDO.Ninja and coturn, which Remote Contribution needs, are **not** installed by CivicCast; whoever sets them up chooses their ports.

<!-- SOURCES: inventory/screens/installer-install-layout.md (sections 1-6, 9); civiccast/native/supervisor/install_layout.py:160-300; civiccast/native/supervisor/config.py:37-75,92-115 (names, pipe, mutex, backoff, storm, 15 s); civiccast/native/supervisor/core.py:393-394 (127.0.0.1:8000); civiccast/native/supervisor/children.py:272-300,520-551,680-684 and :100-150 (Ollama 11434, env); civiccast/native/provision/port_select.py:140 (5432,5433,5434,5435,5544); civiccast/native/supervisor/service.py:34,192-219,342-376,483,2064-2069 (logs, DB port from URL); civiccast/egress/hls_relay.py:251-256,328-347; civiccast/egress/ts_relay.py:52-54,117,190-230 (17800, +1000); civiccast/egress/relay_reclaim.py:12-40; civiccast/apps/installer/src-tauri/src/main.rs:29-36 (127.0.0.1:38474, URLs); civiccast/apps/installer/src-tauri/src/native_service_registration.rs:160-170,279-290 (auto start; restart/5000/10000/30000; firewall rule name); civiccast/installer/router.py:1211-1230 (control plane binds 127.0.0.1 only); civiccast/installer/station_state.py:599-610,1154-1175 (station-state.json and default folders under LOCALAPPDATA); civiccast/native/supervisor/children.py:272-300 (SYSTEM profile LOCALAPPDATA comment); civiccast/live/preflight.py and inventory/screens/live.md (network probe 1.1.1.1/8.8.8.8:443, 50 GiB) -->

# Appendix E: Status and error glossary {#app-status}

Every status word an operator is likely to see, with what it means. Words are written exactly as the console prints them. Where the console prints a raw code instead of a plain word, the code is given. Some words are in two vocabularies for the same thing; the tables say so.

## Readiness phrases

Five phrases are used across the console for "can I act?". Colors: green, yellow (amber), red.

| Phrase | Meaning |
| --- | --- |
| Ready | The required checks passed for what you are about to do. (green) |
| Check before meeting | Something optional or recoverable needs attention. (yellow) |
| Do not broadcast yet | A required check failed for tonight's broadcast. (red) |
| Not set up yet | An optional provider or feature has no credential or proof yet. (yellow) |
| Needs IT help | The next step needs administrator, command-line, certificate, database or service work. (red) |

On Readiness the server's own card heading can also read "Ready with optional items", which is not one of the five. Station Profile shows the raw words `green`, `yellow` and `red`. Readiness check rows are tagged `required`, `optional` or `advanced`.

## Assets (Assets screen)

The list has two columns that describe the same file in two vocabularies.

| State column | Status column | Meaning |
| --- | --- | --- |
| Analyzing (`pending_ingest`) | Validating | CivicCast is checking the uploaded file. Usually under a minute. |
| Ingesting | Ingesting | The file is being processed for ingest. |
| Validated | Packaged / Not packaged yet | The file passed the check. "Not packaged yet": use **Package for playback** to make it streamable. "Packaged": playable and ready to publish or schedule. |
| Rejected | Rejected | The file failed validation. Open the asset for the reason. |
| Recorded | Not servable yet | A live recording finished but has no public playback copy yet, so residents cannot stream it. |
| (any) | Published | Live on the resident portal. |
| (any) | Transcoding / Queued for transcode | A playback copy is being made or is waiting. The asset stays usable. |
| (any) | Missing file | CivicCast cannot find the file on disk. The console has no "relink" control; use **Replace source file** in the asset detail page. |

## Publishing (Publish screen)

| Pill on an asset | Meaning |
| --- | --- |
| Draft | The portal step has not finished: it has not run yet, or it is still running. |
| Preflight blocked | A required check stops publishing. |
| Publishing | A fallback label, used when none of the other states fits. We could not confirm a normal path that shows it in beta.10. |
| Archive pending | The portal copy is live; a required archive copy is still pending or running. |
| Archive verified | Portal live and every required archive copy is verified. |
| Reaching fewer places than planned | Portal live, but an optional reach surface failed. |
| Needs action | A required surface failed. |
| Complete | Everything required is done. |

Each surface (Portal, Internet Archive, local NAS copies, YouTube, cable file package, and the Podcast episode and Subscriber notifications rows, which are marked as coming in a future release) has its own state: Blocked, Not set up yet, Coming soon (shown as "not built yet"), Not run yet, Running, Succeeded, Failed, Overridden. Its approval is `pending`, `approved` or `overridden`. A badge marks a surface completed by a simulated (mock) provider rather than a real write.

## Captions

| Where | Words | Meaning |
| --- | --- | --- |
| Caption review queue, each line | Pending, Approved, Edited, Rejected | Nothing is attached to a recording's public video until every line is approved, edited or rejected. Lines are marked EN (English transcription) or ES (the Spanish translation pass). |
| Recording's caption job (Assets) | Transcribing..., Awaiting review, Complete, Failed | `pending`, `awaiting_review`, `complete`, `failed`. "Awaiting review" means the cues are in the review queue. |
| Channel card, Captions row | On / Off (switched off in the station profile) / Not verified; open channel caption proof | Whether captions in the live output have been proven by decoding them back. |
| Channel caption card | Captions off, Not verified, Captions on, Caption proof failed, Stale (older than 120 seconds) | The result of the decode-back proof. |
| Live caption runtime (raw words in status data) | within-capacity, overloaded, storage-refused, paused, disabled | The live caption worker's state. "overloaded" means it is falling behind. |

## Summaries (Summary review screen)

| Word | Meaning |
| --- | --- |
| Pending review | A draft waiting for a records clerk. It can be approved only if it has sourced claims. |
| Approved | A clerk approved it; a signed PDF/A-3B record can be exported. |
| Rejected | A clerk rejected it. |
| Needs evidence (`refused`) | The system could not support the summary with evidence from the captions. |

The generation job itself is `pending`, `running`, `complete` or `failed` in the API.

## Meetings, sessions and recordings

| Where | Words |
| --- | --- |
| Live session | Idle, Pre-flight, On air, Ending, Recorded |
| Live source check | Delivering (media seen within the freshness time), Needs re-check (seen, but too long ago), Not answering (last check failed), Not checked |
| Live pre-flight rows | Network reachable, Recording storage, Live source, Recording target and Operator confirmation must pass before Start Live Stream works. AI runtime may be "not configured" without blocking, but a check that fails (probed and broken) does block. Syndication, Internet Archive and NAS handoff only report and never block going on air. |
| Remote relay | Not configured, Ready, Degraded, Offline; modes Local encoder, Cloud relay, Direct platform |
| Scheduled recording job | `scheduled`, `arming`, `recording`, `finalizing`, `done`, `failed`, `skipped` |
| Schedule screen item | Scheduled (created, not yet approved to air; a premiere also says "Not yet visible to residents"), Published (approved to air; "Visible to residents"), Cancelled (withdrawn). Premiere and Embargo are the two kinds. |
| Program Guide airing | `scheduled`, `skipped_conflict`, `skipped_asset`, `cancelled` (shown as Skipped (conflict), Skipped (media), Cancelled) |
| Private rehearsal result | Passed, Failed, Not run |
| Recording finalization | Waiting, running ("Attempt N of M"), completed ("Recording saved as asset ..."), failed |

## Channels and the outgoing feed

| Word | Meaning |
| --- | --- |
| Stopped | The feed is not running. |
| Starting | Preparing the first program. "Preparing source" in the process row; no process number yet. |
| On air | The feed is running a program. |
| Changing source | The feed is switching between programs or sources. |
| Showing slate | The feed is airing its fallback card because nothing is ready. |
| Finishing current item | A "finish, then stop" command is waiting for the current program to end. |
| Stopping | A stop is under way. |
| Needs attention | The feed reported an error (red). |

Raw API words: `STOPPED`, `STARTING`, `ON_AIR`, `TRANSITIONING`, `FALLBACK_SLATE`, `DRAINING`, `STOPPING`, `ERROR`. A stop or restart can take up to about 30 seconds to show on the page.

| Commit to air | Meaning |
| --- | --- |
| Preparing | The commit was accepted and is being prepared. |
| Queued to air | A start or reload was queued for the program's scheduled time. |
| On air (confirmed) | Defined, but nothing in beta.10 sets it, so you should not see it. |
| Couldn't reach the engine | Dispatch failed. |
| Rolled back | An operator rolled the commit back. |
| Not ready to air / Committed / Ready to review | Badges on upcoming programs in the commit list. |

## Contributor submissions, alerts, emergency alerts and federation

| Where | Words |
| --- | --- |
| Contributor submission | `submitted`, `under_review`, `needs_changes`, `accepted`, `declined`, `scheduled`, `published`. The media gate: `not_run`, `passed`, `failed`, `override_accepted`. |
| Alert delivery | Delivered (also sent, success), failed, Undeliverable (`dead_letter`), pending, queued |
| Emergency (CAP) alert severity | unknown, minor, moderate, severe, extreme |
| Emergency alert status | active, superseded, expired, cancelled |
| Emergency display mode and state | crawl, overlay, forced slate; pending, displayed, cleared, expired |
| Federation follower | pending, accepted, blocked, rejected, removed |
| Federation delivery retry | pending, delivered, `dead_letter` |

## The station service (the supervisor's own state names)

These are the state names inside the Windows service. They are not what `GET /health` reports: that is a separate `healthy` or `degraded` answer about the database layout (see the end of this section). We could not confirm which of these names `supervisor.log` prints.

| State | Meaning |
| --- | --- |
| starting | The service is bringing up PostgreSQL and the control plane. |
| ready | Both are up. |
| degraded | Up, but five restarts happened in ten minutes. |
| maintenance | The installer or a migration is holding the station read-only (an upgrade, or a hand-over between CivicCast editions). Changes are refused with HTTP 503 until the hold is released. |
| blocked_wsl_active, blocked_probe_unavailable | The guard that protects against two CivicCast editions owning one machine refused to start the station. |
| stopping | A stop is under way. |

Child programs (PostgreSQL, control plane): pending, stopped, starting, ready, stopping, failed. `GET /health` returns `status` healthy or degraded and `schema` current, behind, not-configured or unknown.

## Setup program exit codes

When setup fails it ends with a number. Interactive setup shows a message box (not the number); a silent install (`/S`) shows only the number. Re-running setup after any failure is the supported recovery; nothing in these steps deletes `C:\ProgramData\CivicCast`.

| Code | Step | What it means | What to do |
| --- | --- | --- | --- |
| 82 | uninstall | The service stop could not be confirmed. | Stop the service in services.msc or reboot, then uninstall again. |
| 110 | stage packs | A required component pack is missing or not trusted, or the optional GPU pack is not trusted. | Put the named `.ccpack` files in the `packs` folder beside setup.exe and run again. |
| 111, 112, 121, 122 | verify | The unpacked server (111), app (112), ffmpeg (121) or Ollama (122) files do not match their signature. | Replace your copy of the kit and run again. |
| 113 | upgrade | The upgrade failed and its rollback failed. | Follow `C:\ProgramData\CivicCast\upgrade\UPGRADE-RECOVERY.md`. |
| 114 | upgrade | This release has a database change that cannot be rolled back; the automatic upgrade was refused. | No manual steps are given by setup. Ask the project. |
| 115 | upgrade | An unexpected fault. | Read the log. |
| 116 | database | PostgreSQL could not be provisioned. | Read the log and `provision\PROVISION-RECOVERY.md`. |
| 117 | database | An unexpected fault. | Read the log. |
| 118 | service | The Windows service could not be registered. | Read the log. |
| 119 | firewall | The firewall rule could not be created. | Read the log. |
| 120 | before install | The existing service could not be proved stopped, or its state could not be read. | Fix it and retry as Administrator. |
| 123 | activation | The station could not be activated or its self-test failed (see the next table). | See below. |
| 124 | upgrade | The upgrade was rolled back and the previous database is intact. | Read `upgrade\upgrade-engine.log`. |
| 125 | service | The service started but is not serving (health check failed). | Read `install-progress.log` and `upgrade-engine.log`. |
| 126 | service | The service would not start. | Read the `logs` folder and the Windows Application event log. |
| 127 | database | Setup cannot tell which CivicCast edition owns this machine. | If there is no WSL edition, set `HKLM\SOFTWARE\CivicCast\ActiveRuntime` to `native`; see `OWNERSHIP-RECOVERY.md`. |
| 128 | upgrade | An earlier failed upgrade left its record on disk. | Move `upgrade\upgrade-journal.json` aside and run again. |
| 129 | upgrade | An older setup was run over a newer install. The database is untouched, but the older program files were already copied over and the service is stopped. | Do not start the service. Run the newer setup, or uninstall first. |
| 130 | uninstall | You declined the ownership-transfer prompt. | None. |
| 131 | uninstall | The ownership transfer failed. | Read the detail in the message. |
| 132 | uninstall | Blocked (active edition conflict, or state unreadable). | As the message says. |
| 133 | uninstall | The service stop was not confirmed; files were kept. | Stop the service or reboot, then uninstall again. |
| 134 | uninstall | Teardown incomplete. | Remove the leftovers by hand (services.msc, firewall, registry). |
| 135 | database | The older WSL edition of CivicCast is registered on this machine. | Uninstall it or run its `cutover-to-native`, then run setup again. |

Code 123 hides a second number from the activation step: 66 (pack or index missing or not trusted), 67 (anything wrong after the packs were verified, including too little free disk space, an extraction failure, a missing file or a self-test that did not pass), 78 (the embedded signing key was refused: download setup again), 64 or 65 (a defective setup program). The self-test runs a short check of the program, PostgreSQL, ffmpeg, Ollama, a caption transcription and three AI requests; each AI request may take up to 300 seconds on a slow machine.

> **Known issue (beta.10):** The activation message tells you to find the failed self-test in `install-progress.log`. The log records only "returned 67"; the cause is in the setup program's detail pane. Run setup interactively and read the detail list if you need the cause.

## Common error messages

| Where | Message | Cause and fix |
| --- | --- | --- |
| API, HTTP 401 | Missing Authorization header. Use Bearer <staff-token>. | No token sent. In the console: sign in again on First Setup. |
| API, HTTP 401 | Invalid Authorization header. Use Bearer <staff-token>. | The header is not in the form `Bearer <token>`. |
| API, HTTP 401 | Invalid staff bearer token. | The token is wrong or from another station. |
| API, HTTP 401 | Staff bearer token has been revoked. | Issue a new one. |
| API, HTTP 401 | Staff identity is required for this action. | The route needs an identity and none was attached. |
| API, HTTP 403 | This action requires one of these CivicCast roles: ... | Wrong role. The names are the raw role ids in alphabetical order, for example `meeting_operator, setup_admin`. See [Appendix F](#app-roles). |
| API, HTTP 429 | Too many failed staff authentication attempts. Wait and retry. | Ten failed token checks in 60 seconds; wait for `Retry-After`. |
| Sign-in | Invalid admin username or password. | Use the username and password from the recovery kit, or a recovery code. |
| Sign-in, HTTP 429 | Too many sign-in attempts from this station. Wait N seconds... | Wait, or use a printed recovery code. |
| Setup, HTTP 403 | First setup can only be done from the station computer itself. | Open the console in a browser on the station, not from another computer or a remote viewer's own computer. |
| API, HTTP 503 | Durable storage is not ready yet. (Some areas, such as Publish, CG Board and Contributors, say instead: Durable storage is not ready. Open Setup and choose Prepare storage, or set DATABASE_URL for a technical deployment.) | The database is not ready. Check the service and `postgres.log`. |
| API, HTTP 503 | `{"error": "maintenance"}` | The station is in maintenance mode, normally because an upgrade is running. Reads still work; changes resume when the hold is released. |
| Live | A duplicate live-session ID error | Recheck Existing meeting and reopen the correct session. New meetings use unique IDs; do not reset station data. |
| Live | Go on air blocked: a fresh source-bound server-side pre-flight did not pass. No broadcast was started. Correct the failed checks and run pre-flight again. | Fix the red pre-flight items. |
| Remote Contribution | Remote contribution is not configured (no self-hosted VDO.Ninja URL). A compositor + VDO.Ninja + coturn must be commissioned before guests can join. | Those services are not set up. |
| Remote Contribution | Channel takeover failed; guest ... not placed on-air. | There was no ready live source to take over to. |
| Emergency Alerts | A forced full-screen slate must be confirmed by an operator... | Tick the confirmation box before choosing a forced slate. |
| Control Room | On-Air Mode expired before this cue could fire. Open a new On-Air session to continue. | The On-Air session lasts 30 minutes; open a new one. |
| Agendas | Another agenda item already occupies (agenda_id=..., order=0) | Two items cannot share an Order number; use the next number. |
| Command line | DATABASE_URL must point at the CivicCast database before running staff token lifecycle commands. | Set `DATABASE_URL` in that PowerShell window ([Appendix A](#app-cli)). |
| Windows Event Log | DATABASE_URL is unset or empty, and the installer-persisted registry value ... is also missing or empty | The station has no database address. Repair the installation. |

<!-- SOURCES: apps/portal-operator/src/types/asset.ts:50-80; components/assets/assetStatus.ts; screens/status-language.ts (readiness phrases, state labels, egress words); screens/PublishDashboardScreen.tsx:20-38,100,203; civiccast/publish/service.py:923-954; types/publish.ts; types/captions.ts; screens/OfflineCaptionJobsPanel.tsx:25-45; civiccast/captions/live_sidecar.py:23-30; types/summary.ts; civiccast/summary/models.py:12; summary/job.py:69; types/live.ts:39-130; recording/models.py:71-90; schedule/models.py:119; programlog/models.py:27; screens/commit-format.ts:14-60; egress/models.py:85-94; contribute/models.py:18-30; eas/models.py:45-61; activitypub/models.py:16,119; native/supervisor/states.py:80-110; app.py:2377-2430 (/health); installer exit codes nsis-hooks-bootstrap.nsh:455-588 and inventory/screens/installer-failures-and-logs.md, installer-nsis-activation-selftest.md; auth/middleware.py; auth/roles.py:88-98; installer/station_state.py:829; installer/router.py:1093,1250; live/router.py:534,715; live/contribution/router.py:148, service.py:362; eas/service.py:109; control_room/service.py:312; app.py:724; cli.py:2030-2040; native/supervisor/service_env.py:158-166; inventory/screens/{live,channels,publish,health,assets,eas,agendas}.md -->

# Appendix F: Roles and permissions matrix {#app-roles}

CivicCast has five roles. A role is a set of things a person is allowed to do. This appendix says which role may open which screen and which role may do which task. It is built from the console's own menu rules and from the server's role checks.

> **Note:** The menu hides screens a role cannot use, but that is only a convenience. The server checks the role again on every action. A person who types the address of a hidden screen is stopped by the screen itself or by the server.

## The five roles

| Role (as the console labels it) | Id used in messages and tokens | In plain words |
| --- | --- | --- |
| Setup admin | `setup_admin` | Sets the station up: the first admin and recovery kit, live sources, AI models, provider keys, alerts, paywall, channel and cable settings, and has write access to most configuration. |
| Meeting operator | `meeting_operator` | Runs a meeting: the Live room, feed Start/Stop/Restart, the Control Room, Remote Contribution, scheduled recording, the Program Guide, agendas. |
| Records clerk | `records_clerk` | Looks after the record: reviews captions line by line, approves summaries and exports signed records, edits agendas, sets legal holds. |
| Publish operator | `publish_operator` | Decides what residents see: schedules, packages and publishes recordings, the community board, EPG export, apps, and reviews contributor submissions. |
| Support admin | `support_admin` | Helps keep the station healthy: restore drills, update and rollback tools, support bundles, reports, read-only views of alerts and many screens. |

## How a person gets a role

1. **The first admin gets all five.** The account created on First Setup, and anyone who signs in with that admin's password or a recovery code, gets the scope `admin`, which means all five roles.
2. **Tokens for tools get what you give them.** `civiccast token issue --scopes ...` makes a token; with no `--scopes` it gets `operator`, which is also all five. Name roles (for example `--scopes records_clerk`) to narrow it ([Appendix A](#app-cli)).
3. **There is no screen for creating operators or assigning roles.** Because the console signs in only as the first admin, in a normal station every console user is effectively all five roles. The role limits below are real, but you can only see them with a narrowed token. Nothing in the console shows a person's roles as text; only the hover text on the initials badge in the top bar lists them.
4. **Roles add up.** One matching role is enough.
5. **No scopes means no roles.** A token with no scopes is refused everywhere that checks a role.

## Who can open each screen

`Y` means the menu shows the entry. `-` means it is hidden. S = Setup admin, M = Meeting operator, R = Records clerk, P = Publish operator, A = Support admin. While the console has not yet loaded who you are, role-limited entries stay hidden.

| Menu section | Screen | S | M | R | P | A |
| --- | --- | --- | --- | --- | --- | --- |
| Help | Manual | Y | Y | Y | Y | Y |
| Setup | First Setup | Y | Y | Y | Y | Y |
| Setup | Control Room Setup | Y | - | - | - | - |
| Setup | Station Profile | Y | Y | - | - | Y |
| Setup | Cable Commissioning | Y | - | - | - | Y |
| Setup | AI Models | Y | Y | - | - | - |
| Setup | Custom Fields | Y | - | - | - | - |
| Setup | Paywall | Y | - | - | - | - |
| Run Meeting | Live | Y | Y | Y | Y | Y |
| Run Meeting | Facility | Y | Y | Y | Y | Y |
| Run Meeting | Control Room | Y | Y | Y | Y | Y |
| Run Meeting | Remote Contribution | Y | Y | - | - | Y |
| Run Meeting | Channels | Y | Y | Y | Y | Y |
| Run Meeting | CG Board | Y | Y | Y | Y | Y |
| Run Meeting | CG Designer | Y | - | - | Y | Y |
| Run Meeting | Schedule | Y | Y | Y | Y | Y |
| Run Meeting | Auto-schedule | Y | - | - | Y | Y |
| Run Meeting | Program Guide | Y | Y | Y | Y | Y |
| Run Meeting | Recording | Y | Y | - | - | Y |
| Review Records | Assets | Y | Y | Y | Y | Y |
| Review Records | Missing Media | - | Y | - | Y | Y |
| Review Records | Media Lifecycle Settings | Y | - | Y | Y | - |
| Review Records | Contributors | Y | Y | Y | Y | Y |
| Review Records | Review queue | Y | Y | Y | Y | Y |
| Review Records | Summary review | Y | Y | Y | Y | Y |
| Review Records | Agendas | - | Y | Y | - | - |
| Publish | Publish | Y | Y | Y | Y | Y |
| Publish | Playback policy | Y | Y | Y | Y | Y |
| Publish | Analytics | Y | Y | Y | Y | Y |
| Publish | Reports | - | - | - | - | Y |
| Publish | EPG Export | Y | - | - | Y | - |
| Publish | Underwriting | Y | - | - | Y | Y |
| Publish | App Admin | Y | - | - | Y | - |
| System Health | Readiness | Y | Y | Y | Y | Y |
| System Health | Alerts | Y | Y | Y | Y | Y |
| System Health | Emergency Alerts | Y | Y | - | - | Y |
| System Health | Federation | Y | Y | Y | Y | Y |

Two extra pages are not in the menu: an asset's detail page and its full-screen trim editor. Both follow the Assets rules.

> **Known issue (beta.10):** The menu hides **Missing Media** and **Agendas** from a Setup admin on its own, although that role usually is the all-powerful one. This shows only for a token that carries nothing but `setup_admin`.

### Screens a role can open but cannot use

| Role | Opens, but is refused |
| --- | --- |
| Records clerk | Alerts (the list returns HTTP 403 and shows "Alerts could not load."); Federation Approve, Reject and Block (HTTP 403). |
| Publish operator | Alerts (list returns HTTP 403). Federation moderation is allowed. |
| Setup admin on its own | Federation Approve, Reject and Block (403). Key generation is allowed. |
| Support admin | Alerts rule and destination changes (Save, Add destination, Delete return 403); the feed buttons on Readiness are disabled. |
| Meeting operator | Alerts rule and destination changes (an access note); Readiness restore, update and support-bundle controls are disabled with notes. |

When the server refuses a role, the screen often prints the raw role ids ("This action requires one of these CivicCast roles: ..."), not the labels above.

## Who can do the key tasks

From the server's checks in beta.10. Read "any signed-in role" as: the server only needs a valid token, and no particular role.

| Task | Allowed roles |
| --- | --- |
| Look at lists and status (assets, publish status, Program Guide reads, channel state, readiness, caption queue, summary queue, federation status) | any signed-in role |
| Read the Schedule list and the commit history | Publish operator, Setup admin, Support admin |
| Upload a video; edit an asset's title and details; relink a file | Meeting operator, Records clerk, Support admin |
| Package an asset for playback; remove it from the portal; replace its source file | Publish operator, Setup admin |
| Set or clear a legal hold on an asset | Records clerk, Support admin |
| Approve, edit or reject a caption line; retry an offline caption job | Records clerk |
| Start a summary job or generate a summary | Records clerk, Support admin |
| Approve a summary; retry a summary job; export a signed record | Records clerk |
| Approve publishing for an asset; retry a publish surface | Publish operator |
| Create or cancel a scheduled item; commit programs to air; Auto-schedule rules | Publish operator, Setup admin |
| Add, change or disable a Program Guide slot | Meeting operator, Support admin |
| Accept, decline or send to schedule a contributor submission | Meeting operator, Publish operator |
| EPG Export setups and Underwriting spots and flights | Publish operator, Setup admin |
| Build app packages | Setup admin |
| Change app settings and branding; record store-submission notes | Publish operator, Setup admin |
| Create the live session, run pre-flight, Start Live Stream, End Live Stream, Retry finalization | Meeting operator |
| Add or edit a live source | Setup admin |
| Check a live source (the probe) | Setup admin, Meeting operator |
| Start, Stop, Restart or Finish-then-stop a channel's feed | Meeting operator |
| Run Check broadcast readiness (the private rehearsal) | Meeting operator |
| Set up recording schedules; Record now; stop a recording | Setup admin, Meeting operator |
| Open a Control Room session; fire a cue; roll back | Meeting operator |
| Plan (dry run) a cue; read a session | Meeting operator, Support admin |
| Close a Control Room session | Setup admin, Meeting operator, Support admin |
| Show or clear an emergency alert on a channel | Setup admin, Meeting operator |
| Add an emergency alert source or a manual alert | Setup admin |
| Create, change or delete an alert destination; change an alert rule | Setup admin |
| Read alert rules and destinations | Setup admin, Support admin |
| Change which AI model does a job; set a provider key | Setup admin |
| Create, edit and delete agendas and agenda items | Meeting operator, Records clerk |
| Paywall settings and comp passes | Setup admin |
| Create the federation key | Setup admin |
| Approve, reject or block a follower; replay a delivery | Publish operator, Support admin |
| Verify the backup folder | Setup admin |
| Check backup storage, run the restore drill, update preflight, maintenance window, rollback tools, repair the playout engine | Setup admin, Support admin |
| Create and download a support bundle | Support admin |
| Reports (as-run log, shows, hours by category, export) | Support admin |
| Edit community board, zones, feeds; approve bulletins | Publish operator, Setup admin |

## Role by API area

The server groups its staff routes into areas (the second part of the path after `/api/staff/`). For each area the table gives how many routes carry a role requirement, and for each role how many of those routes it may call. A dash means none. Routes with no role requirement (79 in beta.10) are all reads, plus `POST /api/staff/auth/sign-out`; any valid token may use them. Areas that have no role-gated route (`auth`, `first-run`, `release`, `doctor`) are not listed.

How this was made: the application was loaded and each route's role requirement was read from it (beta.10 code: 421 staff routes in all, which is six more than the 415 in [Appendix B](#app-api) because six installer routes are left out of the published API document; 342 are role-gated, in 48 areas, and 79 are not).

| Area | Gated routes | S | M | R | P | A |
| --- | --- | --- | --- | --- | --- | --- |
| `activitypub` | 5 | 1 | - | - | 4 | 4 |
| `agenda` | 1 | - | 1 | 1 | - | - |
| `agenda-sources` | 2 | - | 2 | 2 | - | - |
| `agendas` | 11 | - | 11 | 11 | - | - |
| `ai-models` | 8 | 8 | 4 | - | - | - |
| `alert-channels` | 4 | 4 | - | - | - | 1 |
| `alert-events` | 2 | 2 | 2 | - | - | 2 |
| `alert-rules` | 2 | 2 | - | - | - | 1 |
| `analytics` | 5 | 1 | 1 | 1 | 5 | 5 |
| `app` | 8 | 8 | - | - | 7 | - |
| `assets` | 12 | 5 | 8 | 7 | 5 | 7 |
| `audio-tracks` | 3 | 3 | 1 | - | - | 1 |
| `auto-schedule` | 17 | 17 | - | - | 17 | 7 |
| `cable` | 9 | 9 | 4 | 4 | 4 | 6 |
| `captions` | 6 | - | - | 6 | - | 2 |
| `cg` | 18 | 18 | - | - | 18 | 6 |
| `contribute` | 5 | - | 5 | - | 5 | 4 |
| `contribution` | 15 | 1 | 12 | - | - | 6 |
| `control-room` | 21 | 15 | 11 | - | - | 9 |
| `custom-fields` | 5 | 5 | 2 | 2 | - | - |
| `eas` | 9 | 9 | 6 | - | - | 4 |
| `egress` | 15 | 14 | 8 | - | - | 5 |
| `epg` | 6 | 6 | - | - | 6 | - |
| `facility` | 2 | - | 2 | - | - | 2 |
| `installer` | 33 | 29 | 1 | - | 2 | 18 |
| `live` | 12 | 6 | 7 | - | - | - |
| `media-lifecycle` | 14 | 9 | 5 | 5 | 8 | 5 |
| `migrate` | 4 | 4 | - | - | - | - |
| `paywall` | 6 | 6 | - | - | - | - |
| `playback-policy` | 2 | - | - | - | 2 | 2 |
| `playout` | 5 | 5 | - | - | 5 | 2 |
| `podcast` | 1 | - | - | - | 1 | 1 |
| `producer-ops` | 21 | - | 21 | - | 21 | 21 |
| `programlog` | 4 | - | 4 | - | - | 4 |
| `publish` | 2 | - | - | - | 2 | - |
| `recording` | 9 | 9 | 9 | - | - | 4 |
| `records` | 1 | - | - | 1 | - | - |
| `reports` | 4 | - | - | - | - | 4 |
| `runtime-safe-to-air` | 1 | 1 | 1 | 1 | 1 | 1 |
| `schedule` | 4 | 4 | - | - | 4 | 2 |
| `self-tests` | 2 | 2 | - | - | - | 2 |
| `station` | 2 | 2 | 1 | - | - | 1 |
| `station-box-profile` | 2 | 2 | 2 | - | - | 2 |
| `stream` | 1 | - | 1 | - | - | 1 |
| `subscribe` | 1 | - | - | - | 1 | 1 |
| `summaries` | 5 | - | - | 5 | - | 3 |
| `system-resources` | 1 | 1 | - | - | - | 1 |
| `underwriting` | 14 | 12 | - | - | 12 | 2 |

> **Note:** Alerts, Reports and a few areas were not tested here beyond reading the role requirement. This table says who the server lets in, not whether the screen works for them. "Role-gated" does not include checks written inside a route's own code.

<!-- SOURCES: inventory/screens/_shell-navigation-and-roles.md sections 1-6; civiccast/apps/portal-operator/src/components/shell/Sidebar.tsx:88-205 (menu and visibility; re-read for this appendix, 37 entries); civiccast/auth/roles.py:14-100; civiccast/auth/models.py; civiccast/installer/station_state.py:795-811; civiccast/cli.py:2065-2090; role-by-API tables computed by loading civiccast.app.create_app() and reading every route's require_any_role dependency (495 route-method pairs; 421 under /api/staff; 342 gated, 79 not gated; the 79 are 78 GET reads and POST /api/staff/auth/sign-out); key-task table from the same scan; inventory section 6 (visible but forbidden) -->

# Appendix G: Checklists {#app-checklists}

Copy these into your own notebook or ticket system. Each box is one action. Where a screen name is given, it is the menu name. Times typed on some screens are UTC, which is a common cause of a meeting airing a day early or late, so read the "Times" box in the go-live list first.

> **Warning:** Beta.10 is a beta candidate. The clean-install lane of the release checks passed; upgrading over an earlier release and the download-only lane were not run, and no human field tester has signed off. Use these lists to find problems early, not to certify the station.

## G.1 Go-live checklist

Do this once before the first public meeting, and again after any reinstall.

**The computer and the service**

- [ ] The Windows service `CivicCastSupervisor` is Running and set to start automatically (`Get-Service CivicCastSupervisor`).
- [ ] The top bar shows the version you meant to install (`v1.0.0-beta.10`).
- [ ] The console opens at `http://127.0.0.1:8000/operator/` on the station computer.
- [ ] Decide how residents and other staff will reach the station. As built, the program listens only on the station computer itself; reaching it from anywhere else needs something you add ([Appendix D](#app-files)). Test it from a second computer.
- [ ] Free disk space is comfortable on the drive holding `C:\ProgramData\CivicCast` (the conform cache alone may use up to 60 GB by default) and on the drive for `CIVICCAST_UPLOAD_DIR` (the Live screen needs 50 GiB free there).

**Accounts and the recovery kit**

- [ ] First Setup is done: station name, time zone, first admin.
- [ ] The recovery kit (admin username, password, the 8 one-time recovery codes) is saved or printed and stored where a second person can find it, and you pressed **I found the kit — it is stored safely**. Until you do, the whole menu except Manual is locked.
- [ ] Each person who needs the console has been told how they will sign in: the console signs in only as the first admin. Anyone who needs a narrower role needs an access token ([Appendix F](#app-roles)).

**Configuration**

- [ ] Station Profile: station name, time zone, default channel, public web address and the three storage folders look right and have space.
- [ ] Station Profile: decide the **Show live captions on air** switch (it starts off). With it off, no caption is written into the picture.
- [ ] AI Models: the caption, summary and translation models are the ones you intend. Remember that a local change takes effect the moment the choice changes.
- [ ] First Setup: **Verify backup** succeeded for your backup folder. This only proves CivicCast can write a small test file there; it does not copy your data. Arrange your own backups ([G.7](#g-drill)).
- [ ] Readiness: no required row is red; read every row in "Required before broadcast" (First admin, Recovery kit, Durable records storage, Backup, Camera or meeting source, Local recording, Resident portal, Station policy).
- [ ] Readiness: press **Check broadcast readiness** and read the result. It creates a short private test session and recording on channel `government`.
- [ ] Channels: every channel you plan to air has an outgoing-feed configuration, and you have pressed **Start** once and seen the state change to On air, then **Stop** and seen Stopped.
- [ ] If you send a channel to a cable company: Cable Commissioning is complete, and you have read the warning that the test signal goes to the headend address.
- [ ] Emergency Alerts: you know that CivicCast is not an emergency-alert device, and who adds alert sources (setup admin only, through the API).

**Times** (UTC and local)

- [ ] Recording: start time and weekday are typed in **UTC**. The screen echoes your local time; check it.
- [ ] Schedule and Program Guide: you type your browser's local time and it is stored in UTC. Program Guide weekday rules count days on the UTC calendar, so an evening meeting can land on a different weekday; check the 7-day view.
- [ ] Alerts: quiet hours are typed in UTC.
- [ ] EPG Export: dates and times in the file are UTC.
- [ ] Auto-schedule dayparts use the station time zone from First Setup.

**Public side**

- [ ] The resident portal shows your station's channels, schedule and recordings.
- [ ] Subscribe (email and RSS) and Submit a program forms work the way you intend, or you have decided not to promote them.
- [ ] Paywall, Federation and Remote Contribution stay off unless you have set them up; each is off by default.

## G.2 Meeting-night checklist

**Hours before**

- [ ] Readiness: the banner and top card are green or yellow with a reason you understand. Press **Check broadcast readiness** (needs the Meeting operator role).
- [ ] Missing Media: no meeting on this week's schedule is missing its video.
- [ ] Schedule or Program Guide: tonight's programs and the recording schedule are present. Remember the UTC rules above.
- [ ] Channels: the commit list shows tonight's programs; press **Approve & put on air** for those that need it. The program airs at its scheduled time, not at the click.
- [ ] Channels: check what **Keep this channel on air** is set to before you press Stop on a feed; if it is on, the station starts the feed again.
- [ ] Control Room (if used): start in Test mode. An On-Air session lasts 30 minutes, then must be reopened.
- [ ] Remote Contribution (if used): open the room, send single-use guest links (they expire after 4 hours).
- [ ] Captions: check the Captions row on the channel card (On, or Off because of the station profile).

**The Live room (if you use it)**

- [ ] Choose the broadcast channel and the meeting source. Press **Check source** until it says Delivering. A result goes stale after about 30 seconds.
- [ ] **Create live session**, **Start pre-flight**, tick the confirmation box in Session controls, **Run pre-flight**, fix any red row, **Start Live Stream**.
- [ ] Network reachable needs internet access (it tests 1.1.1.1 and 8.8.8.8). Recording storage needs 50 GiB free.
- [ ] **Do not refresh the browser tab while on air.** The live session is held only in that page; a refresh loses it and you cannot end the stream from that screen.

**During**

- [ ] Watch the on-air banner on Readiness; it refreshes every 5 seconds. Other panels do not refresh by themselves.
- [ ] A Stop or Restart can take up to about 30 seconds to show. Do not press it again.
- [ ] If the channel shows slate or "Needs attention", read [chapter 8](#ch-something-wrong) and the logs ([Appendix D](#app-files)).

**After**

- [ ] **End Live Stream** (if you used it) and wait for "Recording saved as asset ...". Confirm on Channels that the feed is in the state you want.
- [ ] Assets: find the recording, **Package for playback**, check the title and details.
- [ ] Review queue: approve, edit or reject every caption line; nothing is attached to the video until all are decided.
- [ ] Summary review: approve the summary if you use one; export the signed record.
- [ ] Publish: choose the surfaces and approve. Read the status pill afterward ([Appendix E](#app-status)).

## G.3 Daily checklist

- [ ] Readiness: top card, banner and required rows. Read "Latest self-check" (the daily self-check runs overnight).
- [ ] Alerts: anything active?
- [ ] Missing Media: empty?
- [ ] Machine health on Readiness: Media space and Backup space free, Database Reachable, Service Running.
- [ ] Review queue: lines waiting.
- [ ] Contributors: new submissions waiting.
- [ ] Each channel's feed state is what you expect.

## G.4 Weekly checklist

- [ ] Run the weekly self-check (**Run weekly self-check now**) and read its result.
- [ ] Look at free space and at the conform cache folder `C:\ProgramData\CivicCast\data\egress\conform-cache` against its limit.
- [ ] Open `C:\ProgramData\CivicCast\logs\supervisor.log` and scan for repeated restarts of a child program.
- [ ] Check **Check backup storage** on Readiness, and confirm your own backup ran ([G.7](#g-drill)).
- [ ] Analytics: audience counts and any gaps.
- [ ] Retention: Media Lifecycle Settings still match your retention rules and watch folders are working.
- [ ] Tokens: `civiccast token list` and revoke any you no longer need ([Appendix A](#app-cli)).

## G.5 Monthly checklist

- [ ] Run the real database restore drill (Readiness, **Run real database restore drill**, or `civiccast dr run-drill --out <folder>`), at a quiet hour.
- [ ] Restore one file from your own media backup to a different folder and play it.
- [ ] Rotate staff tokens used by scripts (`civiccast token rotate`).
- [ ] Look at the CivicCast release page for a newer release and read its notes before you decide ([Appendix K](#app-history)).
- [ ] Recovery kit: confirm it is still where you stored it. It holds 8 one-time recovery codes and each recovery uses one.
- [ ] Check certificates on Readiness ("Internal service certificates" in the advanced list).
- [ ] If Federation is on: review followers and the delivery retry queue.
- [ ] Review Windows updates and reboot at a quiet hour; confirm the service comes back by itself and the channels return.

## G.6 Before-upgrade checklist

> **Warning:** For beta.10, upgrading over an earlier release is **not proven**: that lane of the release checks was not run. Rehearse it on a spare machine, and have a backup you have restored at least once, before you do it on the station that is on the air.

- [ ] Read the release notes and the verification record for the version you are installing. Note what was and was not proven.
- [ ] Choose a time when no meeting is scheduled and no channel is needed.
- [ ] Take your own backup of the media, of `station-state.json` and of anything else you rely on, and run the restore drill the same day ([G.7](#g-drill)).
- [ ] Have the new `setup.exe` and its `packs` folder together on the station, with the downloads checked against the published checksums.
- [ ] Readiness, Update and rollback panel: save the path to the installer you would roll back to (the field is labelled **Rollback artifact path**; its own example is an older installer) with **Save rollback artifact**, then run **Run rollback rehearsal**, then **Run update preflight**.
- [ ] On Readiness, **Open maintenance window** (60 minutes). It needs the update preflight and a passed rollback rehearsal first. During the upgrade itself the service holds the station in maintenance mode, and changes are refused with HTTP 503.
- [ ] Note the free disk space.
- [ ] Run the new `setup.exe` over the existing install. It stops the service, re-checks the packs, backs up and migrates the database (with rollback if it fails), registers the service again and starts it. An older setup over a newer install is refused (exit 129).
- [ ] If setup fails, note the exit number ([Appendix E](#app-status)), read `install-progress.log` and `upgrade\upgrade-engine.log`, and re-run setup (a re-run is the supported recovery).
- [ ] After: Readiness is green, the version in the top bar changed, **Run post-update proof**, then run the go-live items that touch channels and captions.

## G.7 Disaster-recovery drill {#g-drill}

What CivicCast does and does not do for you in beta.10:

- Its drill backs up the real database, restores it into a completely fresh database, and checks row counts, content checksums and that the program's own stores can read the restored data.
- It does not replicate your media: the drill records a list of files and a hash of a bounded sample, and says you still need your own file-level backup of media.
- We found no scheduled backup job. The **Verify backup** and **Check backup storage** buttons write and read a small test file in the folder; they do not copy your data.
- No screen or command restores a backup over the live station. The drill restores into a scratch copy.

Checklist:

- [ ] Write down, in one place, what must survive a lost machine: the database, `C:\ProgramData\CivicCast\data\uploads`, `station-state.json` and its folder, the recovery kit, your own copy of `setup.exe` and the packs.
- [ ] Name who runs the backup, how often, and where the copy lives (a different computer or drive).
- [ ] Run the drill at a quiet hour: Readiness, **Run real database restore drill**, or `civiccast dr run-drill --out <folder>` (it writes `dr-drill-report.md` and `.json` into that folder).
- [ ] Read the report. Keep it with the date.
- [ ] Prove your media backup: restore a few files to another folder and play them.
- [ ] Prove the recovery kit: you can find it and the codes without the station computer. Do not use up a recovery code for practice unless you intend to.
- [ ] Rehearse a full rebuild on a spare machine: install the same setup, restore the database and media by the procedure your IT person writes, sign in, and run the go-live list.
- [ ] Record how long it took and what surprised you; fix the procedure.

<!-- SOURCES: inventory/screens/health.md (controls, check names, Machine health, self-check, update/rollback panel); inventory/screens/live.md (flow, 30 s freshness, 50 GiB, 1.1.1.1/8.8.8.8, refresh loses session); inventory/screens/setup.md and station-profile.md (Verify backup only probes a folder; storage defaults; live captions default off); inventory/screens/channels.md (commit panel, Keep this channel on air); inventory/screens/controlroom.md (30 min); inventory/screens/remotecontribution.md (invite 4 h); inventory/screens/recording.md, guide.md, schedule.md, alerts.md, epg.md, autoschedule.md (time zones); inventory/screens/_shell-signin-and-session.md (recovery kit, 8 codes, nav lock); inventory/screens/installer-install-layout.md sections 7-8 (upgrade behavior); docs/releases/v1.0.0-beta.10-verification.md (proof status); civiccast/dr/__init__.py:1-70 (drill, media manifest not replication); civiccast/egress/preparer.py:23 (60 GB); civiccast/app.py:724 (maintenance 503) -->

# Appendix H: Measured evidence and known limits {#app-evidence}

<!-- COORDINATOR WRITES SECTION H -->

# Appendix I: Glossary {#app-glossary}

Plain-English meanings of the terms used in this manual, in alphabetical order. A word in *italics* inside a definition has its own entry. Where a term is a screen name, it is the name in the console's menu.

**A**

ActivityPub
:   The open standard that lets servers follow each other's published activity. CivicCast's optional Federation feature uses it.

Admin (first admin)
:   The one local account made on First Setup. It signs in with a username and password and holds all five *roles*.

Affidavit
:   On the Underwriting screen, a per-sponsor proof-of-airing report used for billing.

Agenda
:   A numbered list of items for one recorded meeting, each optionally tied to a moment in the video. Once published it is shown with the recording on the public watch page (we could not confirm in testing exactly where on that page).

AI engine
:   The Ollama program the station runs on the same computer for meeting summaries and Spanish translation. It listens only on the station computer. See *Ollama*.

Alert
:   A problem the station has flagged, shown on the Alerts screen and counted on Readiness. Not the same as an *emergency alert*.

Alert destination
:   Where an alert is supposed to be sent: an email address, a phone number for text messages, or a *webhook*. Quiet hours (typed in UTC) are set per destination.

Alert rule
:   One condition the station watches (for example a channel going off air) with its settings: on or off, severity, how often to repeat, and whether to notify when it clears.

API
:   The set of web addresses the console, the portal and other tools use to talk to the station. See [Appendix B](#app-api).

App shell
:   A small generic viewing app that App Admin can package for a platform (web, Roku, Apple TV, Fire TV, Android, iPhone and iPad). It is not an app-store release.

Archive (surface)
:   A place where a copy of a published recording is kept: the Internet Archive or a local *NAS*. Required archive copies must succeed for the pill to read "Archive verified".

As-run log
:   The log of what actually aired on the station's channels, written by the playout engine. The Reports screen reads it.

Asset
:   One video the station holds: an uploaded file, a file picked up from a *watch folder*, an accepted contributor program or a live recording.

Auto-schedule
:   Filling a channel's air time by rule instead of one item at a time. A rule joins a *saved search* and a *daypart*; a compile run places matching recordings.

**B**

Backup destination
:   The folder you name on First Setup so CivicCast can check it can write there. It does not copy your data by itself.

Bearer token
:   The secret a tool sends in the `Authorization: Bearer` header to prove who it is to the API.

Beta candidate
:   How beta.10 is labeled: published as a *GitHub pre-release* to be tested, not a finished or production release.

Board (community board)
:   The between-programs picture a channel shows: zones for a ticker, schedule, logo, sponsor and approved *bulletins*.

Bulletin
:   A short community announcement submitted for the board. It does not air until staff approve it.

**C**

Cable file package
:   A folder made by `civiccast cable package` holding a recording, its captions and a manifest, for sending to a cable operator as files.

CAP (Common Alerting Protocol)
:   The standard format for public-safety alerts that the Emergency Alerts screen reads from feeds such as NWS, AMBER and IPAWS.

Caption
:   Text of what is said, shown with the video. Each timed line is a *cue*.

Caption review queue
:   The Review queue screen, where a person approves, edits or rejects each caption line before it is attached to a recording's public video.

CC BY 4.0
:   The license for CivicCast's documentation: you may copy and adapt it if you credit the source.

CEA-708
:   A standard for captions carried inside a television signal. The `civiccast egress verify-captions` command tests embedding and reading back this kind of caption.

CG (character generator)
:   Software that puts text and graphics on the picture. CG Board and CG Designer manage the community board.

Channel
:   One outgoing program stream with its own schedule and feed, such as `government` or `public`.

Chapter
:   A named point in a recording. An agenda can be filled from a recording's chapters.

Check source
:   The Live screen button that runs one short test on a meeting source to see whether video is arriving.

Commissioning (cable)
:   A four-step wizard that checks the computer, records the headend choices, sends a timed test signal and produces a report.

Commit to air
:   Approving a scheduled program on Channels so it airs at its time. It does not start it at the click.

Comp pass
:   A free access pass issued by staff to a named email when the *paywall* is on.

Conform
:   Preparing a copy of a program in a standard form so it plays smoothly on a channel.

Conform cache
:   The folder of prepared copies. It lives at `data\egress\conform-cache` under the data folder and is limited to 60 GB by default.

Console token
:   The proof of sign-in the browser keeps after you sign in on First Setup. It is stored in the browser until you sign out or the station rejects it.

Contributor
:   An outside producer who sends in a program through the public "Submit a program" form. Staff review these on the Contributors screen.

Control plane
:   The main CivicCast program: the web server and playout engine, listening at `127.0.0.1:8000`.

Control Room
:   The screen for driving production equipment (switchers, cameras, recorders) with one-press *cues*. Different from Control Room Setup.

Crawl
:   A message that moves across the picture. One of three ways an emergency alert can be shown (crawl, overlay, forced slate).

Cue (caption)
:   One timed line of caption text.

Cue (Control Room)
:   A one-press action on a control surface, such as taking a camera scene. You dry-run it, then confirm to fire it.

Custom field
:   A label the station invents for its programs, such as "Meeting type". It becomes a box on each asset and can become a public filter.

**D**

Daypart
:   A recurring time window on a channel, such as weeknights 6 to 10 PM, that an *Auto-schedule* rule fills.

Dead letter
:   A message that could not be delivered after the allowed tries. The console shows it as "Undeliverable".

DeckLink
:   A family of video cards (Blackmagic) used for SDI input and output.

Decode-back proof
:   A check that reads captions back out of what was actually sent, to prove they are in the picture.

Degraded
:   Working, but not fully healthy. For the service it means five restarts in ten minutes. For `/health` it means the database layout does not match the program.

Director view
:   A link, shown right after you open a Remote Contribution room, that you embed in your video switcher.

Disaster-recovery drill
:   A test that backs up the real database, restores it into a scratch copy and checks the result.

Dispatch
:   The step where a committed program's start is sent to the playout engine.

DST (daylight-saving time)
:   The twice-a-year clock change. The Schedule screen warns you to confirm the local meeting time around it.

**E**

EAS (Emergency Alert System)
:   The national alert system. CivicCast says on screen that it is **not** an EAS device.

Egress
:   Everything that carries a channel out of the station: the outgoing feed, web video, cable output and streams.

Embargo
:   A scheduled release moment for an approved recording, with no length.

Emergency alert
:   A public-safety alert pulled in from a feed. The code puts severe and extreme ones on air automatically, as a crawl or overlay, on every channel that is on air. A full-screen *forced slate* always needs an operator.

Environment variable
:   A named setting handed to a program when it starts, such as `CIVICCAST_CONFORM_CACHE_GB`. See [Appendix C](#app-settings).

EPG (electronic program guide)
:   A file of upcoming programs that cable boxes and guide services read. The EPG Export screen makes it in X-List, XMLTV or CSV form.

Event Log (Windows)
:   Windows' own record of events. The CivicCast service writes to it under the source `CivicCastSupervisor`.

Exit code
:   The number a program returns when it ends. Setup's exit codes are in [Appendix E](#app-status).

**F**

Facility
:   A preview-only screen for a video router. Its buttons show the command that would be sent; they do not send it.

Federation
:   An optional feature that lets other servers on the fediverse follow the station and see when a meeting is published. Off by default.

Fediverse
:   The network of servers (Mastodon and similar) that talk to each other using *ActivityPub*.

Feed (outgoing channel feed)
:   The running stream for a channel. Start, Stop, Restart and Finish-then-stop control it.

Feed (outside content)
:   An RSS, calendar, weather or social source that CG Designer can pull into a board zone.

FFmpeg
:   The open-source video tool CivicCast uses to prepare and check media. `ffmpeg.exe` and `ffprobe.exe` are in the install folder.

Finalization
:   After a live meeting ends: a worker finds the recording file and turns it into an *asset*.

Firewall rule
:   A Windows setting that allows or blocks network traffic. Setup adds one for TCP 8000.

First Setup
:   The screen that creates the first admin and the recovery kit, and later serves as the sign-in page.

Flight
:   The date window in which an underwriting spot should run.

Follower
:   A remote account that has asked to follow the station on the fediverse. Staff approve, reject or block it.

Forced slate
:   A full-screen takeover with an emergency message. It needs an explicit operator confirmation.

**G**

Gate A
:   The set of checks run in a clean Windows Sandbox before a release is published. It has a clean-install lane, an upgrade lane and a download-only lane. Only the clean-install lane ran for beta.10.

Gemma
:   The family of AI models used for summaries (12B and e4b) and, as TranslateGemma 4B, for Spanish translation. They run locally through *Ollama*.

GitHub pre-release
:   A release on GitHub marked as not final. Beta.10 is published this way.

GStreamer
:   The video framework CivicCast's playout engine is built on.

**H**

Headend
:   The cable company's equipment that receives a channel from the station.

HLS (HTTP Live Streaming)
:   The web video format residents' browsers play for live and recorded video.

**I**

Inbox and outbox (federation)
:   Where the station receives follow requests and where it lists its own published activity.

Ingest
:   Bringing a file or stream into the library and checking it. A file that fails the check is Rejected.

Install folder
:   Where setup puts the program, normally `C:\Program Files\CivicCast (Native)`.

Internet Archive
:   An outside archive. One of the archive copies a publish can make, if configured.

Invite link
:   A single-use browser link for a remote guest. It expires after 4 hours.

IPAWS
:   The U.S. federal alert system whose alerts, in CAP form, the Emergency Alerts screen can read.

**K**

Kit (installer kit)
:   The folder holding `setup.exe` together with the `packs` and `station` folders that setup uses.

**L**

LAN-only station
:   A station set to assume it cannot reach the public internet. A native station is set this way, so `/docs` and `/redoc` are off and `/openapi.json` needs a token.

Legal hold
:   A flag on an asset that stops it from being removed under retention rules.

LGPL and GPL
:   Two families of free-software licenses. CivicCast avoids shipping GPL-licensed code and ships LGPL libraries with their license text. See [Appendix J](#app-licenses).

Live session
:   The Live screen's record of one meeting: idle, pre-flight, on air, ending, recorded.

Live takeover
:   Putting a live source on a channel now, overriding its schedule, for up to an hour by default.

Local AI
:   AI models that run on the station computer, so nothing is sent out and there is no per-use fee.

Loopback (127.0.0.1)
:   An address that means "this computer only". A program listening there cannot be reached from the network.

LUFS
:   A unit of perceived loudness. Beta.10 levels spoken programs toward -16 LUFS when preparing them for air.

**M**

Maintenance mode
:   A state in which the service holds the station read-only while the installer or a migration works. Requests that change data get HTTP 503; reads still work.

Maintenance window
:   A 60-minute period you open from Readiness as part of an update; the console records it. Separate from the service's own *maintenance mode* during an upgrade, when changes are refused with HTTP 503.

Media gate
:   The check on a contributor's file, shown as not_run, passed, failed or override_accepted.

Meeting body
:   The name of the group that held a meeting, such as "City Council". Retention rules and Auto-schedule can match on it.

Migration (database)
:   A change to the database layout made during an upgrade, with a backup first.

Missing Media
:   A warning list of meetings in the next week whose video is not ready to play.

**N**

NAS (network-attached storage)
:   A storage box on your network. One archive copy can go there.

NDI
:   A way to send video over a network. An output kind on Channels.

NWS
:   The U.S. National Weather Service, one source of weather alerts.

**O**

Ollama
:   The local AI engine program (version 0.30.6 in beta.10), started by the service on `127.0.0.1:11434`.

On-Air Mode
:   A Control Room session type that really fires cues. It expires after 30 minutes. The other type, Test Mode, fires nothing.

OpenAPI
:   The machine-readable description of every API route, served at `/openapi.json` with a token.

Operator console
:   The staff web application at `/operator/`.

OTT
:   "Over the top": viewing apps for Roku, Apple TV, Fire TV and similar. See *App shell*.

Overlay
:   Text or graphics drawn over the picture. One of three emergency-alert display modes.

**P**

Pack (.ccpack)
:   A signed bundle of program files or models that setup unpacks and checks.

Package for playback
:   Making an asset streamable. Not the same as publishing.

Paywall
:   An optional setting that holds some recordings behind a paid subscription (through Stripe) or a free comp pass. Off by default.

PDF/A-3B
:   A long-term archive form of PDF. Summary review exports its signed record in it.

PEG
:   Public, educational and government access television.

Playback policy
:   Who is allowed to watch (everyone, signed-in residents, or an invite group), an optional public-record lock and up to four prerolls.

Playout
:   The act of airing scheduled programs on a channel. The playout engine does it.

Portal (resident portal)
:   The public web site at `/` where residents watch live and recorded meetings.

PostgreSQL
:   The database program that holds all station records. It listens only on the station computer.

Pre-flight
:   The Live screen's checklist run before a meeting goes on air.

Premiere
:   A scheduled item that places a recording on a channel at a start time for a set length.

Preroll
:   A short graphic or video card shown before playback.

Private rehearsal
:   What **Check broadcast readiness** runs: a short private test session and recording.

Program Guide
:   The screen of recurring slots that place a recording on a channel on a repeating pattern.

ProgramData
:   The Windows folder `C:\ProgramData`, where `CivicCast` holds the station's data.

Proof (egress)
:   A recorded result showing the output did what was claimed, such as a caption decode-back proof.

Publish
:   Making a recording public through chosen *surfaces*. Approving it on the Publish screen does the work.

**R**

Readiness
:   The menu name for the screen that answers "can we broadcast now?" (the page calls itself "Safe to broadcast").

Recording schedule
:   A rule for capturing a live input at set times. Times are typed in UTC.

Recovery code
:   One of 8 one-time codes in the recovery kit. Using one sets a new admin password.

Recovery kit
:   The printed or saved sheet with the admin username, password and recovery codes, made on First Setup.

Registry (Windows)
:   Windows' settings database. CivicCast keeps a few values under `HKLM\SOFTWARE\CivicCast`.

Retention
:   How long an asset is kept, set by rules (including by *meeting body*). The Media Lifecycle Settings screen says nothing is deleted automatically: expired assets are flagged for a records clerk to review.

Reverse proxy
:   A program in front of a web server that passes requests to it. You need one to let other computers reach a station that listens only on `127.0.0.1`.

Role
:   A set of permissions. CivicCast has five. See [Appendix F](#app-roles).

Rollback
:   Returning to the previous version after a failed update.

RSS
:   A feed format. Residents can follow new recordings by RSS; CG Designer can also read RSS sources.

RTMP
:   A streaming protocol that some encoders and platforms use. A kind of live source and output.

Rule (Auto-schedule)
:   A saved-search-plus-daypart pair that decides what to place when.

**S**

Safe State
:   The recovery cue you pick before opening an On-Air Control Room session. The panic and roll-back buttons fire it.

Saved search
:   A set of conditions that picks which recordings qualify for an Auto-schedule rule.

Schema
:   The shape of the database. `/health` reports whether it is current.

Scope
:   A word on a token that grants a role. `admin` and `operator` grant all five.

SDI
:   A professional video cable standard used by cameras and cable equipment.

Self-check
:   A set of automatic tests the station runs (daily and weekly); the result is on Readiness.

Service (Windows)
:   A program that Windows starts by itself. CivicCast's is `CivicCastSupervisor`.

Setup (setup.exe)
:   The Windows installer. Also the name of a menu section.

Silent install
:   Running setup with `/S`, which shows no windows and returns only an exit code.

Slate
:   A fallback card a channel shows when nothing is ready to air.

Slot
:   A recurring Program Guide entry, which a background job turns into real schedule items.

Spot
:   A short underwriting sponsor message.

SRT
:   A streaming protocol for video over unreliable networks. A kind of live source and output.

Station
:   The whole CivicCast system on one computer, and the organization it serves.

Station index
:   The signed list of the packs a station needs, in the `station` folder.

Summary
:   An AI-written meeting summary built from approved captions, where every claim points to timestamped cues. A records clerk approves it.

Supervisor
:   The service program that starts, watches and stops PostgreSQL, the control plane and the AI engine.

Support bundle
:   A redacted troubleshooting file made on Readiness by a support admin.

Surface
:   A destination in Publish (Portal, Internet Archive, NAS, YouTube, cable file package). In the Control Room, a named panel of cues.

Syndication
:   Sending a recording or stream to outside platforms. A Live pre-flight row.

**T**

Takeover
:   See *Live takeover*.

TCP and UDP
:   Two ways programs send data over a network. A "port" is a numbered door for each.

Tier (hardware)
:   The recommendation `civiccast doctor` gives for how capable the computer is.

Time zone
:   Where "9 AM" is measured. Some screens use UTC, some the browser's zone, some the station's.

Token
:   See *Bearer token* and *Console token*.

Trim
:   Cutting the start and end of a recording. There is a full-screen trim editor.

TSDuck
:   An optional tool for checking and smoothing a cable stream. Its program is `tsp.exe`.

TSR control service
:   The helper the Control Room uses to talk to production equipment.

TURN (coturn)
:   A relay server that helps remote guests connect. Remote Contribution needs one you set up.

**U**

Underwriting
:   Paid sponsor acknowledgment messages. The screen keeps a catalog of spots and flights and a billing report.

Upgrade
:   Running a newer setup over an existing install. Beta.10's upgrade lane was not tested.

UTC
:   Universal Coordinated Time, the clock that does not change with seasons or places. Several screens use it.

**V**

VDO.Ninja
:   A browser video service used for remote guests; you host it yourself.

VOD (video on demand)
:   Recorded programs residents can watch any time.

**W**

Watch folder
:   A folder CivicCast checks automatically and imports video files from.

Webhook
:   A web address that receives a message when something happens. One kind of alert destination.

WebVTT
:   A text format for captions that web players read.

Whisper (faster-whisper)
:   The speech-to-text model that makes captions. The Medium model is the standard; Large v3 is optional.

WSL (Windows Subsystem for Linux)
:   The Windows feature the older CivicCast edition ran on. Beta.10 is the native Windows edition.

**X**

X-List and XMLTV
:   File formats for program guides. EPG Export offers both and CSV.

<!-- SOURCES: terms drawn from the other appendices and from inventory/screens/*.md "What it is for" sections; civiccast/egress/models.py; civiccast/native/supervisor/*; civiccast/captions/*; docs/releases/v1.0.0-beta.10-verification.md; CHANGELOG.md beta.10 summary (-16 LUFS leveling); ActivityPub definition from inventory/screens/activitypub.md -->

# Appendix J: Licenses and third-party software {#app-licenses}

This appendix lists what CivicCast is licensed under and what other people's software ships inside it. It reports what the project's own files say. It is **not legal advice**, and it does not say whether your use of any component is allowed. Ask a lawyer who knows your situation.

## CivicCast's own license

| What | License |
| --- | --- |
| CivicCast code | Apache License 2.0 |
| CivicCast documentation (this manual) | Creative Commons Attribution 4.0 International (CC BY 4.0) |

CivicCast is an independent open-source project. It is not affiliated with, sponsored by or approved by any third-party vendor. Product names are trademarks of their owners; references to other products are for compatibility and comparison only. See the project's [Legal Notices](https://github.com/scottconverse/civiccast/blob/main/LEGAL-NOTICES.md) for the named notices.

## What the project says it has not done

- CivicCast has **not** received a third-party patent clearance or freedom-to-operate opinion.
- **You** are responsible for any patent, codec, broadcast, hardware, cloud-service, app-store or other license your deployment needs.
- The project's own notice names these areas for review by counsel: codec delivery, multi-site federation, dynamic ad insertion, automated recording derivation from live automation logs, real-time caption translation, and commercial distribution of binaries that include patent-encumbered media defaults.

## The no-GPL posture

The project's rule for what it ships in the Windows runtime (recorded in its architecture decision ADR 0021, "No GPL in the shipped runtime") and how the build enforces it:

1. **GPL media plugins are left out on purpose.** The two GStreamer plugin bundles that carry GPL code are never installed. The build records six plugin files as excluded: the x264 and x265 video encoders, and the a52, dts, dvdread and resindvd plugins. Adding either bundle is a build-refusal condition.
2. **The database pack is checked.** The build refuses to continue if any file in the server pack (PostgreSQL and TSDuck) is recorded under a GPL-family license: "zero GPL/AGPL tolerance" for that pack.
3. **FFmpeg is the LGPL build.** The standalone `ffmpeg.exe` is an LGPL "shared" build, and the FFmpeg libraries inside GStreamer report LGPL with nonfree and version-3 features disabled and no x264 or x265 encoder registered. The Python video library (PyAV) used by captions is a CivicCast-built LGPL-only wheel; the ordinary prebuilt wheels are deliberately not authorized.
4. **Libraries offered under a choice of licenses use the non-GPL choice.** librtmp is offered as GPL or LGPL, and CivicCast records LGPL; cairo as LGPL or MPL-1.1, and it records LGPL; FreeType as the FreeType License or GPL-2.0, and it records the FreeType License. Two D-Bus type files with a similar dual license were removed from the shipped files.
5. **Device control stays out of the core.** The Control Room reaches production equipment through a separate helper (the TSR control service) so that no GPL or AGPL device-control code is linked into the core program (ADR 0019).
6. **Only confirmed licenses are recorded.** For each shipped file the project records a license only where it confirmed it against the upstream project's own license file. A file with no confirmed license is reported as a gap, not guessed. In beta.10's table no file is marked unresolved.

LGPL means you receive the right to use and replace the library, and CivicCast ships the license text with it. It is not the same as GPL, and it still has conditions; read the text.

## What is bundled

| Component | Version in beta.10 | License (as the project records it) | What it does here |
| --- | --- | --- | --- |
| CivicCast program and web portals | 1.0.0-beta.10 | Apache-2.0 | The station itself. |
| GStreamer libraries and plugins | 1.28 series | LGPL-2.1-or-later for the libraries and almost all plugins; the Rust-based plugins (`hlssink3`, closed captions) are MPL-2.0 | The playout engine. |
| Cisco OpenH264 | in the closure | BSD-2-Clause | H.264 video encoding. Its patent position is a separate question that the license text does not answer. |
| VisualOn AAC encoder | in the closure | Apache-2.0 for the encoder library; the GStreamer plugin that wraps it is LGPL-2.1-or-later | AAC audio encoding. |
| FFmpeg (`ffmpeg.exe`, `ffprobe.exe` and libraries) | n8.1.2 build | LGPL-3.0-or-later | Preparing and checking media. |
| PostgreSQL | 17.10 | PostgreSQL License | The database. |
| TSDuck (optional) | 3.44 | BSD-2-Clause | Checking and smoothing a cable stream. |
| Ollama | 0.30.6 | MIT | The local AI engine. |
| OpenSSL | 3.x | Apache-2.0 | Secure connections. |
| Node.js | 24.15.0 (listed in the runtime lock) | MIT | Listed in the runtime dependency lock. |
| Whisper large-v3 speech model (via faster-whisper) | pinned revision | MIT | Captions (the optional Large model). The standard Medium model is a separate pack whose license this table does not restate. |
| Gemma 4 (12B, e4b) and TranslateGemma 4B models | as pinned in the model lock | The publisher's license, carried inside each model package | Summaries and Spanish translation. Read the license inside the package; this manual does not restate it. |
| Smaller libraries | various | BSD-2-Clause, BSD-3-Clause, MIT, Zlib, Libpng, bzip2, FreeType License (FTL), HPND-sell-variant, MIT-Modern-Variant, Unicode-TOU, SQLite's public-domain dedication, ICU, LGPL-2.1-or-later (glib, pango, libsoup, gettext, and others) | Text, fonts, images, networking and compression support. |
| Python packages | pinned by hash | Each under its own license, listed per package in the build's bill of materials | The CivicCast program's dependencies. |
| Web portal libraries | pinned | Not restated here | React, React Router, TanStack Query and hls.js in the portal bundles. |
| Microsoft Visual C++ Redistributable | the installer's own copy | Proprietary (Microsoft's terms) | Required by the Windows programs. CivicCast has no right to reproduce the text; it ships a pointer to where the real terms are. |
| NVIDIA CUDA and cuDNN libraries (optional GPU pack) | optional | NVIDIA's end-user license terms | Faster captions on an NVIDIA graphics card. The pack carries reference texts, not NVIDIA's copyrighted text. |

> **Note:** Names and versions in the table are from the project's lock files and license tables. Some lock files pin newer or older point releases than this table shows (the GStreamer line, for example, moved between two 1.28 releases during beta.10 work), so use the build's bill of materials for exact versions.

## Where the license texts are

Each runtime pack carries a `LICENSE-BOM.md` (a per-file table of license, generated from the build) and a `licenses` folder with the license text for every license it uses. CivicCast also keeps the texts in its source tree, in `civiccast/native/license_texts`, one file per license identifier:

| File | License |
| --- | --- |
| `Apache-2.0.txt` | Apache License 2.0 |
| `BSD-2-Clause.txt`, `BSD-3-Clause.txt` | BSD licenses |
| `MIT.txt`, `MIT-Modern-Variant.txt` | MIT licenses |
| `LGPL-2.1-or-later.txt` | GNU Lesser General Public License 2.1 or later |
| `MPL-2.0.txt` | Mozilla Public License 2.0 |
| `FTL.txt` | FreeType License |
| `HPND-sell-variant.txt` | HPND (sell variant), used by fontconfig |
| `LicenseRef-Fontconfig-2.16.1.txt` | fontconfig's own notice |
| `Libpng.txt`, `Zlib.txt`, `bzip2-1.0.6.txt`, `blessing.txt` | libpng, zlib, bzip2 and SQLite |
| `Unicode-TOU.txt` | Unicode terms of use |
| `LicenseRef-Microsoft-VCRedist.txt` | A pointer, not a license text: the Microsoft redistributable's terms are proprietary |

The installer is signed with an Authenticode signature (publisher Scott Converse, through Azure Trusted Signing). To check a download yourself, run `Get-AuthenticodeSignature .\setup.exe` and expect Status Valid; compare the SHA-256 against the release's `SHA256SUMS.txt`.

<!-- SOURCES: LEGAL-NOTICES.md (full); LICENSE, LICENSE-DOCS (headers); CODE_SIGNING_POLICY.md:1-20; civiccast/native/runtime_licenses.py:1-60,172-197,514-540,560-640,871-905 (GPL exclusion list, dual-license elections, server-pack zero-GPL guard, UNRESOLVED_BASENAMES = empty at :497); civiccast/native/license_texts/ (17 files listed); civiccast/native/license_texts/__init__.py:1-30 (VC++ pointer); requirements-native-runtime.in:1-27 (ADR-0021, GPL wheels absent); requirements-native-app.txt:28-33 (LGPL-only PyAV wheel); native-windows-runtime-dependencies.lock.json (ffmpeg LGPL-3.0-or-later n8.1.2, node 24.15.0 MIT, ollama 0.30.6 MIT, postgres 17.10-2, tsduck 3.44); native-windows-ollama-models.lock.json; civiccast/native/app_payload.py:107-150 (Whisper MIT); civiccast/apps/portal-operator/package.json and portal-public/package.json (dependency names); civiccast/native/runtime_licenses.py:1089-1103 (NVIDIA EULA identifiers); civiccast/apps/installer/src-tauri/src/native_install_verify.rs:286 (LICENSE-BOM.md expected with each payload); civiccast/control_room/tsr_service/README.md:16 and docs/adr/0019 -->

# Appendix K: Release history {#app-history}

Published releases of the native Windows line of CivicCast, newest first. The authored source for this list is the project's release-truth file, checked against GitHub's release page. "Superseded" means a newer release replaced it; it does not mean it was bad.

> **Note:** **v1.0.0-beta.10** was published on 2026-10-02 as a GitHub pre-release and beta candidate. Gate A passed for the clean-install lane only. The upgrade lane and the download-only lane were not run. A first install with neither the full kit nor an earlier install is not proven; the installer needs the `packs` and `station` folders. No human field-tester has signed off. The exact wording is in the project's `docs/releases/v1.0.0-beta.10-verification.md`.

| Release | Date | Status | What it was |
| --- | --- | --- | --- |
| **v1.0.0-beta.10** | 2026-10-02 (20:31 Mountain; 2026-10-03 02:31 UTC) | Current. GitHub pre-release / beta candidate | The current release. Program changes no longer leave a black or silent gap, and a watchdog ends a stuck program change; spoken programs are leveled toward -16 LUFS; schedules set to loop now loop; the conform cache default grew from 20 GB to 60 GB; faults in reload and restart are handled (orphaned relays reaped, a frozen web stream restarts its worker, an audio/video mismatch restarts the channel, live captions catch up). Proven by an eight-hour three-channel lab run on an earlier internal build of the same engine and by a clean-install check on the published installer. |
| v1.0.0-beta.9 | 2026-09-18 (changelog date) | Never published | A version bump and an installer rebuild; its work is in beta.10. |
| v1.0.0-beta.8 | none | Never published | Its work is in beta.10. |
| v1.0.0-beta.7 | 2026-09-15 (19:47 UTC) | Superseded by beta.10 | Published as a GitHub pre-release with a signed `setup.exe`. All three Gate A install journeys and an eight-hour physical-machine soak with captions off passed. Live captions stay off by default. |
| v1.0.0-beta.6 | none | Not listed as a release; the changelog calls it rejected | A candidate that was not accepted. |
| v1.0.0-beta.5 | 2026-09-09 22:14 Mountain (2026-09-10 04:14 UTC) | Superseded | Published as a pre-release after several rejected candidates; all three Gate A lanes passed at publish time. The changelog later records it, with beta.6, as rejected. |
| v1.0.0-beta.4 | 2026-09-04 (20:41 UTC) | Superseded | A download-only upgrade for stations already on beta.3: `setup.exe` and the runtime packs, no re-download of the AI model bundle. |
| v1.0.0-beta.3 | 2026-09-03 (07:14 UTC) | Superseded | The first downloadable release: `setup.exe` and the runtime packs attached to the GitHub release, verified by checksums. |
| v1.0.0-beta.2 | none | Never published | An internal baseline build used only as the starting point for upgrade tests. |
| v1.0.0-beta.1 | 2026-08-31 | Superseded | The first tagged release of the native Windows line: delivered on USB only, with no downloadable files. |

The same release-truth file also lists tags from a **different, retired product**: the older WSL-based CivicCast edition (v1.0.0-rc1 through rc15 and earlier). They are not releases of this line and are not installation targets for it. Of those, rc13 was withdrawn after a clean Windows test found installer bootstrap failures.

Pre-releases published after this manual was written are listed on the project's GitHub releases page: <https://github.com/scottconverse/civiccast-native/releases>.

<!-- SOURCES: docs/releases/release-truth.yaml (entries for beta.1-5, 7, 10; rc entries; current: v1.0.0-beta.10); CHANGELOG.md:14-60 (beta.10 summary), :453-458 (beta.9), :462-475 (beta.7), :524 (beta.5 and beta.6 rejected), :1504-1520 (beta.5), :4250-4262 (beta.4), :4747-4760 (beta.3), :5953-5958 (beta.1); docs/releases/v1.0.0-beta.10-verification.md (status wording; beta.8 and beta.9 never published); MANUAL-STYLE.md section 2 rule 4 (beta.10 wording) -->

# Appendix L: Index of screens {#app-screens}

Every screen of the operator console, then the resident portal pages and the setup program's windows. Use it to find which chapter explains a screen and who can see it.

**Roles** are written as letters: S = Setup admin, M = Meeting operator, R = Records clerk, P = Publish operator, A = Support admin. "All" means every role. Where a role has no letter, the menu hides the screen from it ([Appendix F](#app-roles)).

**How to open a screen.** In the operator console, click its name in the left menu. A screen's address is the console address plus `#/` and its path, for example `http://127.0.0.1:8000/operator/#/live`. The **Page title** column is filled in where the heading at the top of the screen differs from the menu name.

## Operator console

| Menu name | Menu section | Roles | Page title (if different) | Chapter |
| --- | --- | --- | --- | --- |
| Manual | Help | All | Operator manual | [Chapter 2](#ch-signing-in) |
| First Setup | Setup | All | First setup (also the sign-in page) | [Chapter 2](#ch-signing-in) |
| Control Room Setup | Setup | S | Control Room — setup | [Chapter 11](#ch-configuration), Configuring the station (Part II) |
| Station Profile | Setup | S, M, A | | [Chapter 11](#ch-configuration), Configuring the station (Part II) |
| Cable Commissioning | Setup | S, A | | [Chapter 11](#ch-configuration) and [Chapter 15](#ch-integrations) (Part II) |
| AI Models | Setup | S, M | | [Chapter 11](#ch-configuration), Configuring the station (Part II) |
| Custom Fields | Setup | S | | [Chapter 11](#ch-configuration), Configuring the station (Part II) |
| Paywall | Setup | S | Subscription paywall | [Chapter 11](#ch-configuration) (Part II); what residents see is in [Chapter 6](#ch-publishing) |
| Live | Run Meeting | All | Live | [Chapter 4](#ch-running-meeting) |
| Facility | Run Meeting | All | Facility router | [Chapter 4](#ch-running-meeting) |
| Control Room | Run Meeting | All | Production Control Room | [Chapter 4](#ch-running-meeting) |
| Remote Contribution | Run Meeting | S, M, A | | [Chapter 4](#ch-running-meeting) |
| Channels | Run Meeting | All | | [Chapter 4](#ch-running-meeting) |
| CG Board | Run Meeting | All | | [Chapter 4](#ch-running-meeting) |
| CG Designer | Run Meeting | S, P, A | CG Board Designer | [Chapter 4](#ch-running-meeting) |
| Schedule | Run Meeting | All | | [Chapter 3](#ch-before-meeting) |
| Auto-schedule | Run Meeting | S, P, A | | [Chapter 3](#ch-before-meeting) |
| Program Guide | Run Meeting | All | Program guide | [Chapter 3](#ch-before-meeting) |
| Recording | Run Meeting | S, M, A | Scheduled recording | [Chapter 3](#ch-before-meeting) |
| Assets | Review Records | All | | [Chapter 5](#ch-after-meeting) |
| Missing Media | Review Records | M, P, A | | [Chapter 5](#ch-after-meeting) |
| Media Lifecycle Settings | Review Records | S, R, P | | [Chapter 5](#ch-after-meeting) |
| Contributors | Review Records | All | Contributor submissions | [Chapter 3](#ch-before-meeting) |
| Review queue | Review Records | All | | [Chapter 5](#ch-after-meeting) |
| Summary review | Review Records | All | | [Chapter 5](#ch-after-meeting) |
| Agendas | Review Records | M, R | | [Chapter 3](#ch-before-meeting) |
| Publish | Publish | All | Publish dashboard | [Chapter 6](#ch-publishing) |
| Playback policy | Publish | All | | [Chapter 6](#ch-publishing) |
| Analytics | Publish | All | | [Chapter 7](#ch-station-business) |
| Reports | Publish | A | | [Chapter 7](#ch-station-business) |
| EPG Export | Publish | S, P | | [Chapter 7](#ch-station-business) |
| Underwriting | Publish | S, P, A | | [Chapter 7](#ch-station-business) |
| App Admin | Publish | S, P | | [Chapter 7](#ch-station-business) |
| Readiness | System Health | All | Safe to broadcast (System Health) | [Chapter 8](#ch-something-wrong) |
| Alerts | System Health | All | Alerts & monitoring | [Chapter 8](#ch-something-wrong) |
| Emergency Alerts | System Health | S, M, A | | [Chapter 8](#ch-something-wrong) |
| Federation | System Health | All | ActivityPub federation | [Chapter 8](#ch-something-wrong); setup detail in [Chapter 15](#ch-integrations) (Part II) |

That is 37 menu entries in six sections. Two more pages are reached from the Assets list and are not in the menu: **asset detail** (`#/assets/<asset id>`) and the full-screen **trim editor** (`#/assets/<asset id>/trim`); both are in [Chapter 5](#ch-after-meeting). An address the console does not know shows "Page not found" with buttons for Manual, First Setup, Recording, Reports and Readiness. A few old or short addresses forward to the right screen (for example `/docs` and `/manual` to Manual, `/login` to First Setup, `/readiness` to Readiness, `/today` to Schedule, `/archive` to Assets).

> **Known issue (beta.10):** The top bar clock always says "Next No events scheduled" and the pill "No live meeting broadcast", whatever the schedule holds. They are placeholders. Use Schedule and Channels for the real answers.

## Resident portal pages

These need no sign-in. They are covered in [Chapter 6](#ch-publishing).

| Page | Address | What it shows |
| --- | --- | --- |
| Home | `/` | What is live now, what is coming up, the latest recordings, the follow-by-email-or-RSS box and the Submit a program form. |
| Watch a recording | `/#/watch/<asset id>` | The video player with captions and the agenda sidebar; a subscription gate appears instead of the player if the station has set a paywall. |
| Browse recordings | `/#/recordings` | A filterable list of recordings. |
| Channel schedule | `/#/schedule?channel=<channel id>` | The coming schedule of one channel (default channel `public`). |

## Setup program windows

Covered in Part II, [Chapter 10](#ch-installing) (Installing, first run, upgrading, uninstalling): the Windows setup program (`setup.exe`) with its pre-install checks, pack staging, upgrade and database, activation and self-test, and service and finish steps; and the first-run wizard windows "Checking This Computer", "What CivicCast Needs" and "Downloading" (or "Setting Up"). Setup exit codes are in [Appendix E](#app-status).

<!-- SOURCES: civiccast/apps/portal-operator/src/components/shell/Sidebar.tsx:88-205 (37 entries, labels, sections, role gates; re-read); inventory/screens/_shell-navigation-and-roles.md sections 1-2 (aliases, extra routes, Page not found); page titles from the first lines of inventory/screens/{setup,controlroomsetup,paywall,live,cgdesigner,guide,recording,contribute,health,alerts,activitypub}.md and _shell-navigation-and-roles.md SHELL-02/03; chapter assignments follow the chapter map in MANUAL-STYLE.md section 9 and each inventory's "What it is for"; inventory/screens/public-*.md (portal pages); inventory/screens/installer-*.md (setup windows) -->
