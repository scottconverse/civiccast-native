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
