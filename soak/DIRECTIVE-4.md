# DIRECTIVE-4 — 2-hour real-hardware soak, kit e5020746 (1.0.0-beta.5 candidate)

Plain-language summary of what the tester's poll task will run, and where the
results land.

## What runs

- **AUTORUN-2.ps1** (install): fetches the e5020746 kit into a fresh `C:\CivicCastSoak\kit-e5020746...` folder from the LAN server, verifies every file against SHA256SUMS, picks the installer by its manifest name, and installs it OVER the existing (stopped) station; it does not re-arm itself on failure, so a failed install is reported once and the queue moves on:
  fetches and verifies the kit, then installs it silently. Runs once.

- **AUTORUN-4.ps1** (`soak/autorun/AUTORUN-4.ps1`, renamed from the held
  AUTORUN-2): does first-admin setup, configures the three egress channels
  (public/9001, education/9002, government/9003, all UDP-TS, engine left at
  the shipped default -- GStreamer, nothing forces ffmpeg), registers the
  sample videos, and schedules 6 program-change slots per channel (20 minutes
  each, staggered 0/7/14 minutes) covering a 2-hour-15-minute window so every
  channel is still actively playing something through the T+2h verdict below.
  Starts playout, then writes `C:\CivicCastSoak\state\soak-started`. Runs once.
  Reads the kit from `C:\CivicCastSoak\kit-e5020746fa40e7a3f1a160d3a8e1add5c3b57786`.

- **AUTORUN-3.ps1** (`soak/autorun/AUTORUN-3.ps1`, the recurring verify script
  -- kept at this exact name because the poll task re-runs it every cycle
  once `soak-started` exists): every ~30 minutes, per channel --
  - runs `tsp` (TSDuck) against the channel's UDP sink for 30 seconds and
    fails closed on any empty/unparsable/error report;
  - reads `GET /api/staff/egress/channels/<id>/state` for `state`, `pid`,
    `current_source_label`, and `last_error`;
  - tracks worker restarts: a pid change from one cycle to the next counts as
    one relaunch, persisted per channel under `C:\CivicCastSoak\state\`,
    along with the channel's last 3 `last_error` strings;
  - samples CPU% (approximated from cumulative CPU-seconds delta between
    cycles) and RSS of the `python`/`gst-launch-1.0` worker processes, so a
    stall can be correlated against load.

  Writes a rollup every 30 minutes (was 4 hours) and a final verdict at
  **T+2h** (was T+8h). **PASS** requires: every channel `ON_AIR` on the
  GStreamer engine at every cycle, every tsp probe passing, and zero
  relaunches per channel across the whole run. Relaunch counts and last
  errors are always reported in the rollups and the verdict, whether the run
  passes or fails. Polling continues after the verdict is written; only data
  collection for this mission ends.

## Where reports land

All reports commit to `C:\CivicCastSoak\repo` and push to
`tester/soak8-e1acfe6-$env:COMPUTERNAME`:

- `soak/SETUP-BLOCKED.md`, `soak/CHANNEL-SCHEDULE.md`, `soak/SOAK-START.md`,
  `soak/AUTORUN-4-RESULT-*.md` (from AUTORUN-4)
- `soak/egress/egress-*.json` (per-cycle egress + relaunch + worker-sample data)
- `soak/SOAK-REPORT-<host>-*.md` (30-minute rollups)
- `soak/final-verdict.json` (T+2h PASS/FAIL verdict)

## Dry run

Both AUTORUN-3.ps1 and AUTORUN-4.ps1 accept `-DryRun`, which stops before any
HTTP write (POST/PUT) or `git push` and prints what it would have done. Use
it to rehearse a run without touching the station or the repo.

## Do not touch

`soak/held/` is left exactly as is (AUTORUN-1.ps1, the old 8-hour
AUTORUN-2.ps1, the old 8-hour AUTORUN-3.ps1). It is historical/parked, not
part of this directive.

## Addendum 05:55Z — renamed to AUTORUN-5 / AUTORUN-6

Your poll task runs each `soak/autorun/AUTORUN-<n>.ps1` name exactly once and
keeps a done-marker per NAME. The names AUTORUN-2 and AUTORUN-3 were already
marked done on this box from the first queue, so the new install script was
skipped and the channel script (AUTORUN-4) correctly stopped with "station is
not healthy". Nothing is wrong with your box. The same scripts are now queued
under fresh names:

- `AUTORUN-5.ps1` — install the e5020746 kit (fresh folder, verified, over the existing station)
- `AUTORUN-6.ps1` — three channels for 2 hours
- `AUTORUN-3.ps1` — the recurring verify (runs every poll once `state\soak-started` exists; its once-marker does not matter)

## Addendum 07:55Z — channel script re-queued as AUTORUN-8

Your diagnostics (AUTORUN-7) show `state\autorun-done\AUTORUN-6.ps1.done` dated
2026-09-03, left by the first mission, so the renamed channel script was skipped
as well. Names 1-7 are all consumed on this box. The same channel script is now
`AUTORUN-8.ps1`. Nothing else changes: install is done (beta.5 healthy), the
recurring verify is `AUTORUN-3.ps1`.

## Addendum 08:05Z — clean reinstall (AUTORUN-9) then channels (AUTORUN-10)

AUTORUN-8 reported `first-admin POST failed: 409 Conflict`: this station already
has an admin from the 2026-09-03 mission, and no credentials for it were stored
on this box, so nothing can log in. On a tester box the right fix is a fresh
station:

- `AUTORUN-9.ps1` — quiet uninstall, remove `C:\ProgramData\CivicCast` and
  `C:\CivicCastHostStore\install`, install the SAME verified e5020746 kit fresh
  (no download), wait for `/health`, report `soak/REINSTALL-RESULT.md`.
- `AUTORUN-9b.ps1` — the channel script again (named 9b so it sorts AFTER 9; the executor sorts names as text) (first-admin now succeeds), 2 hours.
- `AUTORUN-3.ps1` — the recurring verify, unchanged.

## Addendum 08:30Z — the 409 is a leftover marker; AUTORUN-9c clears it, AUTORUN-9d starts channels

Even after the clean reinstall, first-admin answered 409. The product keeps its
"first-admin complete" marker in `station-state.json` under the SERVICE
account's `%LOCALAPPDATA%\CivicCast`, which no uninstall or data wipe touched
(product defect, filed as batch item 41).

- `AUTORUN-9c.ps1` — stop the service, rename that file to `*.bak-<stamp>`
  (every candidate profile path), start the service, wait for `/health`, report
  `soak/STATE-RESET-RESULT.md` including `/api/setup/station-state`.
- `AUTORUN-9d.ps1` — the channel script again.

## Addendum 08:55Z — channels for real: AUTORUN-9e

AUTORUN-9d created the admin (token stored) but every channel config PUT and
asset registration returned 422: its request bodies were from beta.3. It still
wrote `state\soak-started`, so the verify was counting a soak that never began.
`AUTORUN-9e.ps1` uses the request bodies proven by the sandbox lane on this
exact API (multipart asset upload -> package -> ready -> approve; schedule +
Commit-to-Air; config PUT with slate_message and sink loudness/EAS fields; start),
clears the false marker first, captures every non-2xx response body, and sets
`soak-started` only after a channel reports ON_AIR.


## Addendum (second soak) -- AUTORUN-9j: upgrade to kit 91caebc and restart the 2-hour soak

Soak #1 on kit e502074 ended FAIL (relaunches public 2 / education 1 / government 3; TSDuck pass
every cycle). Root cause measured on this box: the live caption tap ran CPU ASR for all three
channels in-process, held the control plane near 3 cores, and starved the playout workers
(`CTRL stall: no output for 10s` -> relaunch). The fix (PR #172) is in kit
`91caebccc6a6decef476fea5cd785a9ff19abfe6` (main; installer 1.0.0-beta.5), served from
`http://192.168.0.135:8766/91caebccc6a6decef476fea5cd785a9ff19abfe6/` (19-line SHA256SUMS).

`AUTORUN-9j.ps1` (runs once): fetch + verify the kit into `C:\CivicCastSoak\kit-91caebc...`,
install it silently OVER the running station (customer upgrade path), wait for `/health`
healthy + schema current, wait until all three channels report ON_AIR, then archive soak #1's
probes to `soak/archive-e502074-soak1/`, reset the relaunch/pid/rollup counters under
`state\`, and write a fresh `state\soak-started`. `AUTORUN-3` then verifies every 30 min as
before and writes a new `soak/final-verdict.json` at 2 h. PASS rule unchanged: ON_AIR on
GStreamer every cycle, tsp pass every cycle, ZERO relaunches per channel.
Result file: `soak/INSTALL-RESULT-9j.md`. Exit codes: 1 fetch blocked (retries next poll),
2 hash mismatch (retries), 3 no installer, 4 not healthy after install, 5 fewer than 3
channels ON_AIR (soak NOT restarted; report and stop).


## Addendum -- AUTORUN-9k (read-only)

AUTORUN-9j upgraded to kit 91caebc cleanly (installer exit 0, /health healthy, version 1.0.0-beta.5, upgrade engine NO-OP same version) but found 0/3 channels ON_AIR after 10 min and all three `data\egress\<id>\state.json` files missing, so it did NOT restart the soak. `AUTORUN-9k.ps1` (runs once, changes nothing) reports the egress data dir, raw `GET /api/staff/egress/channels`, `/api/staff/schedule`, `/api/staff/playout/state`, `/api/staff/station/profile`, processes, install-progress.log tail and the installed version, to `soak/DIAG-9k-<stamp>.md`.


## Addendum -- AUTORUN-9l: restart the channels, then soak #2

Why the channels stayed dark: egress state is a Postgres row (`egress_states`), preserved by the upgrade; the automation loop re-issues `start` only for channels whose config has `auto_start=true` (civiccast/egress/automation.py:478-493). Soak channels were started by hand, so after the service restart nothing starts them. `AUTORUN-9l.ps1` (runs once) records each channel's state, POSTs `{action:start}` to `/api/staff/egress/channels/<id>/commands` (the 9e route), polls `/state` up to 6 min, and only when 3/3 are ON_AIR archives soak #1's probes to `soak/archive-e502074-soak1/`, resets the relaunch counters and writes a fresh `state\soak-started`. Result: `soak/RESTART-RESULT-9l.md`. Exit 5 = start sent but <3 ON_AIR (soak NOT restarted).


## Addendum -- AUTORUN-9m: reschedule content, then soak #2

The 18:25Z rollup shows all three channels running on GStreamer in FALLBACK_SLATE with tsp pass: they did come back after the upgrade, but soak #1's schedule (2h15 from 09:05Z) ran out hours ago, so there is nothing to play. `AUTORUN-9l` will only send `start` (harmless). `AUTORUN-9m.ps1` (runs once) is AUTORUN-9e with the upload step replaced: it lists `/api/staff/assets`, reuses every `soak8-9e-*` asset in a ready state (durations from the record, else ffprobe of the matching sample clip), schedules 2h15 back-to-back per channel + Commit-to-Air, re-applies the channel config, sends start, polls up to 6 min for ON_AIR (all three), archives soak #1's probes to `soak/archive-e502074-soak1/`, resets the relaunch counters and writes a fresh `state\soak-started`. Results: `AUTORUN-9m-RESULT-<stamp>.md`, `CHANNEL-SCHEDULE-9m.md`, `SOAK-START-9m.md`, or `SETUP-BLOCKED-9m.md`.


## Addendum -- AUTORUN-3 warm-up grace (verdict rule change, rev 22)

AUTORUN-9m reset `last-egress-run`, so AUTORUN-3 probed 19 s after soak-started (18:40:55Z): tsp pass on all three channels, but education and government were still TRANSITIONING from the start command. Under the strict rule that one warm-up sample alone would make a clean 2-hour soak FAIL. Rule now: probes taken within 3 minutes of soak-started stay on disk and in the rollups but are excluded from the verdict; the verdict JSON lists them in `warmup_probes_excluded`. Everything else (ON_AIR on GStreamer every cycle, tsp pass every cycle, zero relaunches) is unchanged.


## Addendum -- AUTORUN-9o (read-only)

Soak #2's first rollup (19:16Z) shows the control plane still near 2.9 cores and public/education relaunched once. `AUTORUN-9o.ps1` (runs once, changes nothing) reports every `runtime-status.json` under ProgramData\CivicCast, caption-tap / overload / pause / stall / relaunch log lines and counts, the station profile and channel states, and a 10-s per-process CPU sample, to `soak/DIAG-9o-<stamp>.md`.


## Addendum -- AUTORUN-9q

`AUTORUN-9p.ps1` had a PowerShell quoting error (does not parse; it produces no report). `AUTORUN-9q.ps1` is the same read-only installed-code check, fixed. Result: `soak/DIAG-9q-<stamp>.md`.


## Addendum -- soak #2 measured the OLD code; clean reinstall (AUTORUN-9r..9u) -> soak #3

Root cause (repo, main 91caebc): the installer's pack staging keys on the pack's declared
`product_version` string, not on the pack's content. Both candidate kits (e502074 and 91caebc)
declare 1.0.0-beta.5, so `native_pack_staging.rs` classified the stale on-disk
`native-app-payload.ccpack` as AlreadySatisfied and never copied or extracted the new one
(`classify_dest_pack_state` -> AlreadySatisfied at native_pack_staging.rs:189/:741;
`ensure_pack_extracted` idempotent return at :645-656). The D3 `SAME_VERSION_NO_OP` line is only the
migration gate. A real beta.4 -> beta.5 upgrade (different strings) replaces the payload.

So on this box: `AUTORUN-9r` quiet-uninstalls, removes `C:\ProgramData\CivicCast`, installs kit
91caebc fresh (`/S /D=C:\CivicCastHostStore\install`), waits for /health; `AUTORUN-9s` clears the
persisted first-admin marker (station-state.json under the service profile) and restarts;
`AUTORUN-9t` does first-admin and stores the token; `AUTORUN-9u` is AUTORUN-9e for this kit
(upload the 4 clips, schedule 2h15 per channel + commit, config PUT, start), archives the invalid
soak #2 probes to `soak/archive-91caebc-soak2-oldcode/`, resets the counters and writes
`state\soak-started`. AUTORUN-3 then verifies as before (30-min cadence, 3-min warm-up grace,
verdict at 2 h). Results: REINSTALL-RESULT-9r.md, STATE-RESET-RESULT-9s.md, AUTORUN-9t-RESULT-*.md,
AUTORUN-9u-RESULT-*.md / CHANNEL-SCHEDULE-9u.md / SOAK-START-9u.md / SETUP-BLOCKED-9u.md.


## Addendum -- AUTORUN-9v (read-only)

After the clean reinstall, `AUTORUN-9v.ps1` repeats the installed-code check (same as 9q): hashes of the installed civiccast files, presence of `tap_backoff.py`, `CaptionBackoffPolicy` in tap_worker.py, journals. Result `soak/DIAG-9v-<stamp>.md`. A soak #3 verdict only counts if this shows the #172 code on disk.


## Addendum -- AUTORUN-9w

`AUTORUN-9u` uploaded the 4 clips, scheduled 272 items per channel (30 s each: ffprobe is not on this box, default duration), applied config and sent start, but no channel reported ON_AIR within its 3-minute window on the freshly installed station, so it did not write `soak-started`. `AUTORUN-9w.ps1` (runs once) records each channel's raw `/state`, sends `start` again (harmless if already running), polls up to 6 minutes, and when all three are ON_AIR archives the earlier probes to `soak/archive-91caebc-soak2-oldcode/`, resets the counters and writes `state\soak-started` (soak #3). Result `soak/RESTART-RESULT-9w.md`; exit 5 = still <3 ON_AIR.


## Addendum -- AUTORUN-9x (read-only)

The 20:46Z probe of soak #3 shows one relaunch per channel in the first 30 minutes on the NEW code (9w also re-sent `start` at 20:16:29Z, which restarts workers, so some of that may be the harness). `AUTORUN-9x.ps1` (runs once, changes nothing) dumps the caption runtime-status files, every relaunch / stall / egress-state / start-command line from the control-plane log since 20:10Z with timestamps, counts, the station profile and channel states, and a 10-s per-process CPU sample. Result `soak/DIAG-9x-<stamp>.md`.
