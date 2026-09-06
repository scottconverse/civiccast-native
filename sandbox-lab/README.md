# sandbox-lab/

Gate A — the automated station-acceptance release gate. Full documentation
(what it proves, verdict criteria, how to run it, runner setup, promotion
rule): **[`docs/ops/gate-a.md`](../docs/ops/gate-a.md)**.

Quick start:

```powershell
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId <native-beta-candidate-artifacts run id>
```

`output/`, `hoststore/`, `kit-download/`, `kit-staging/`, and `evidence/` are
per-run state (gitignored, kept as empty tracked directories via
`.gitkeep`) — `Run-GateA.ps1` regenerates them on every run.

## Local soak

A fast, LOCAL pre-check that finds bugs on HALO in ~15 SOAK minutes instead
of on a tester box in hours. It drives a real silent install + station
start + sample-content playout inside a disposable Windows Sandbox VM,
using a kit already verified on disk (no download). It is **not** a
replacement for Gate A — it's a quick sanity pass you run before pushing
something out to the tester fleet, reusing Gate A's own proven
install/health/channel-start code paths (see `scripts/In-Sandbox-Soak.ps1`'s
header for exactly which lines came from where) at a much shorter default
duration.

```powershell
pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> [-Minutes 15] [-KitRoot C:\CivicCastTester\kit-safe] [-SeamlessReload]
```

Add `-DryRun` to verify the kit, render the `.wsb`, run the
`System.Net.Http.HttpClientHandler` self-check (the guest's own Windows
PowerShell 5.1 engine, not `pwsh`), and parse-check both in-sandbox scripts
without ever launching Windows Sandbox — a dry run is exempt from the busy
guard below since it never launches anything.

`-SeamlessReload` exports `CIVICCAST_EGRESS_SEAMLESS_RELOAD=1` at MACHINE
scope inside the guest before the station service starts (PR #176, head
20f316f — unmerged as of this writing; taken as given from the coordinator,
not independently verified against this checkout). Recorded as
`seamless_reload`/`seamless_reload_verified` in `SOAK-START.json` and
`VERDICT.json`; verification can only ever be "confirmed via a control-plane
log line" or honestly "unverified" — neither `Get-Process` nor
`Win32_Process` can read another process's real environment block from
outside it.

`-Minutes` is **SOAK minutes**, not wall-clock minutes from launch: the
clock starts only once the station reports healthy AND all three channels
are configured/started/confirmed `ON_AIR` (`soak_start_utc`, recorded in
every rollup and in `VERDICT.json`) — not from process launch. Installing
alone measured 13m05s on the first real run, so a launch-relative deadline
would declare that a stall before the install even finished.

What it checks, end to end: silent install (`/S /D=...`) exits 0 within the
installer bound, the station reports `status=="healthy"` AND
`schema=="current"` at `/health` within the health bound (HTTP 200 alone is
liveness only — a degraded station on an unmigrated DB still answers 200),
firewall allow rules are authored for tsp/ffmpeg/ffprobe (Defender's
first-bind modal, same fix as Gate A's), first-admin setup succeeds, the
kit's `samples\*.mp4` clips upload as assets (pinned to a 30-second
schedule slot each — the deliberate rollover instrument, not a discovered
duration; the schedule is sized for the ON_AIR poll's own worst case) and
get scheduled + committed to air on all three channels, then polls (a
lightweight state sample every ~15s, a full cycle with a TSDuck probe every
~60s) for `-Minutes` SOAK minutes.

**PASS** requires: every cycle after a 3-minute warm-up grace has all three
channels `ON_AIR` on an OS-process-verified GStreamer engine (never a
software fallback) UNLESS a channel is inside an active, classified
planned-restart window; a passing TSDuck (`tsp.exe`) egress probe on every
channel every cycle (no restart-window exception — a genuinely seamless
reload should not drop packets either); **zero unplanned relaunches**; and
**every planned restart returns to `ON_AIR` on GStreamer within 60
seconds**. A worker pid change is classified `planned_restart` if the
channel's own 15s-sample ring shows `TRANSITIONING` in the preceding 3
minutes (a normal schedule-plan rollover, expected with
`CIVICCAST_EGRESS_SEAMLESS_RELOAD` off, the beta.5 default) and
`unplanned_relaunch` otherwise (a crash). `VERDICT.json` reports
`unplanned_relaunch_count`, `planned_restart_count`,
`max_restart_gap_seconds`, and the full `restart_events` list; otherwise
**FAIL**, naming the first failing cycle/event and why.

Refuses to start (exit 3) if Windows Sandbox is already running (it's a
single-instance-per-machine resource shared with Gate A and other agents on
this box — `-DryRun` is exempt) and refuses (exit 2) if the kit's
`SHA256SUMS.txt` is missing or any listed file fails verification. Separate
stall bounds apply per phase — a boot bound (default 5 min: absence of any
main-thread file before this is normal, not staleness), installer (default
20 min from launch), station-healthy (default 10 min after install),
rollup-stall (default 6 min once the soak clock has started) — plus a
generic 15-minute main-thread quiet-liveness backstop (newest mtime among
`soak-log.txt`/`summary.json`/phase markers, classified via the shipper's
own heartbeat) that covers every phase, including setup (first-admin/
asset-upload/schedule/channel-start) which has no dedicated bound of its
own. A stall whose sandbox process(es) belong to this run (by recorded PID,
never by bare name) is killed (exit 4) and evidence preserved; one that
can't be positively attributed to this run touches nothing (exit 5,
`FOREIGN-SANDBOX-SESSION.txt`); a stale main-thread signal alongside a
stale/missing shipper heartbeat is `HOST-QUIET-SHARE.txt` (exit 6,
HARNESS_ERROR — no product conclusion, e.g. the guest itself also reports
HARNESS_ERROR when its own schedule-coverage sizing check fails).
`vmmemWindowsSandbox` cannot be stopped from an unelevated host (confirmed:
`Access is denied`) — the host waits up to 3 minutes for it to exit on its
own and reports it as lingering rather than retrying a kill that can only
fail.

Evidence lands under `soak-output/soak-<shortsha>-<UTC stamp>/` — a
separate per-run root from Gate A's own `output/` above (which
`Host-Launch-Sandbox-Test.ps1` wipes at the start of every Gate A run, so
sharing it would risk a soak run's evidence being deleted mid-run by a
concurrent Gate A run). Every run writes `summary.json`, per-cycle JSON
under `cycles/` (each channel row carries its own 12-sample/~3-minute
`sample_ring`), `restart-events.json`, a rollup every 3 minutes under
`rollups/`, per-channel egress worker logs (`logs/<label>/egress-per-channel/
<channel>/`) alongside the daemon-level logs at each checkpoint and on every
FAIL, and a final `VERDICT.json` / `VERDICT.txt`.

The verify/verdict logic lives in `scripts/SoakVerdict.ps1` (dot-sourced by
both the in-sandbox driver and its own unit tests) and
`scripts/HostLiveness.ps1` (the host's stall/quiet-share classification,
dot-sourced by `Run-SandboxSoak.ps1` and its own unit tests) — both pure,
synthetic-data-testable functions so the same code judges a real run and a
unit-test tuple. Run the unit tests with:

```powershell
pwsh -File sandbox-lab/scripts/Test-SoakVerdict.ps1
pwsh -File sandbox-lab/scripts/Test-HostLiveness.ps1
```
