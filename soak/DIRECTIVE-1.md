# DIRECTIVE 1 — soak8-e1acfe6: the loop runs the mission

Trigger: START NOW

Read this once so you know what is happening on your machine. **You are not
the one who executes this mission** — the scheduled tasks the bootstrap
installed do. Your only job was to run the bootstrap. If it printed
`LOOP PROVEN`, you are done.

## What the loop is

`bootstrap/Install-SoakLoop.ps1` registered three Windows Scheduled Tasks
under your own user account. They survive the agent app closing and they
survive a reboot.

| Task | Every | What it does |
|---|---|---|
| `CivicCastSoak-Poll` | 10 min | fetch `soak8-e1acfe6-directives`, read `LATEST-TEST-DIRECTIVE.md`, push `soak/AUTO-ACK-<n>.md` on any change, **and execute any `soak/autorun/AUTORUN-*.ps1` it has not run yet** |
| `CivicCastSoak-Heartbeat` | 30 min | push `soak/heartbeats/heartbeat-<utc>.json` — health, schema, db_revision, service state, process RSS/CPU, disk, uptime, and the egress + engine state of all three channels |
| `CivicCastSoak-Boot` | at logon | push a boot marker, then heartbeat immediately |

The executor is the point. Future orders arrive as new
`soak/autorun/AUTORUN-<n>.ps1` files on the directives branch and run
themselves within 10 minutes. **No human is ever needed again.**

Your branch (everything is pushed here): `tester/soak8-e1acfe6-<YOUR-HOSTNAME>`
Directives branch (read only, never push): `soak8-e1acfe6-directives`

## What the autoruns already queued will do

**AUTORUN-1 — get the kit and install it.**
Kit (LAN, from HALO, port 8766 open):
`http://192.168.0.135:8766/b78b9c7dfa4d66b442172759439553381ec8be44/`
It downloads `SHA256SUMS.txt` at that root, then fetches every file it names
with `curl.exe` (URL-encoded URL, decoded local name — a listing-walk fetch is
what produced a zero-byte installer on the last mission), re-fetching only what
is missing or hash-bad, and stops hard unless `bad=0`. Then a silent install:
`/S /D=C:\CivicCastHostStore\install`. An existing CivicCast is uninstalled
first **only** if a `CivicCastSupervisor` service exists *and* its registered
version differs from the kit's — otherwise it upgrades in place. It waits for
`http://127.0.0.1:8000/health` to report `status: healthy`, `schema: current`,
and commits `soak/INSTALL-RESULT.md` with the installer exit code, the
`install-progress.log` tail and the health JSON.

**AUTORUN-2 — stand the station up and start three channels.**
First-admin setup through `POST /api/setup/first-admin` (loopback-admitted on
first run); the operator token is stored at `C:\CivicCastSoak\state\token` with
a restricted ACL and is never committed. Then three channels — **public**
(udp 9001), **education** (udp 9002), **government** (udp 9003) — each cycling
the four real LPM sample videos from the kit's `samples\`, a program change
every 20 minutes, staggered 0 / 7 / 14 minutes so their transitions never
coincide. **The encoder engine is left at the station's shipped default
(GStreamer). Nothing forces ffmpeg** — this candidate exists to prove the
GStreamer engine emits TS, so a silent ffmpeg fallback is a finding, not a
workaround. `soak/CHANNEL-SCHEDULE.md` and `soak/SOAK-START.md` record the plan
and the UTC start.

**AUTORUN-3 — prove the picture is really coming out.**
Every ~30 minutes: TSDuck (`tsp.exe` from the kit's own
`packs\native-server-binaries\payload\tsduck\bin\`) analyses each of the three
UDP sinks for 30 s. It fails closed — a timed-out run, a nonzero exit, a
missing or empty report, or zero packets is a FAIL, never a pass. It records
invalid syncs, transport errors, continuity discontinuities, plus
`engine_state`, `last_error` and whether a `gst-launch-1.0` or an `ffmpeg`
worker is actually running, so **every probe says GStreamer or ffmpeg-fallback,
per channel**. Results land in `soak/egress/egress-<utc>.json`, a rollup in
`soak/SOAK-REPORT-<host>-<utc>.md` every 4 hours, and at T+8h
`soak/final-verdict.json`.

## Rules

1. The kit comes only from `http://192.168.0.135:8766/...`. Never GitHub, never
   another host or port. If it fails, the autorun commits the error and stops —
   do not invent a workaround.
2. **Polling never ends.** The T+8h verdict ends this mission's data collection,
   not your polling duty. Do not unregister the `CivicCastSoak-*` tasks. Ever.
   Other projects use this box.
3. Never wait for a human. Nobody is watching this machine.
4. If the bootstrap printed `LOOP FAILED`, paste the printed reason into your
   reply and stop. Do not improvise a fix.
5. Never edit product code. Everything you push goes to your own tester branch.

## Where to look

- `C:\CivicCastSoak\reports\poll.log` — every poll, and every autorun it executed
- `C:\CivicCastSoak\reports\AUTORUN-*.log` — full output of each autorun (also
  mirrored to `soak/autorun-logs/` on your branch)
- `C:\CivicCastSoak\state\` — `last-directive.txt`, `autorun-done\`, `soak-started`
