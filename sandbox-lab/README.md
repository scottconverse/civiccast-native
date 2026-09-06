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
duration; the schedule is sized for the ON_AIR poll's own worst case, from
the actual COMMITTED item count, not the target), all three channels are
configured/started and polled until **every** channel (not just one) is
confirmed `ON_AIR` within a 12-minute bound before the soak clock starts —
a bound expiring while the remaining channel(s) are still visibly
progressing (a non-null state, never silent) is reported as `HARNESS_ERROR`
(a lane-sizing gap), never a product FAIL; only a channel that never
returns a single state row at all is a genuine FAIL. Then it polls for
`-Minutes` SOAK minutes: a full ~20-25s tsp probe per channel, run 3
channels per ~60-75s cycle, with an all-channel state sample taken
immediately before each channel's own probe (so state/pid is sampled
roughly 3 times per cycle, not once) into a 12-sample/~3-minute ring per
channel — close enough in practice to catch a restart shorter than the
worst-case ~75s cycle period, though it is NOT a literal independent 15s
timer.

**PASS** requires: every cycle after a 3-minute warm-up grace has all three
channels `ON_AIR` on an OS-process-verified GStreamer engine (never a
software fallback) UNLESS a channel is inside an active, classified
planned-restart window; a passing TSDuck (`tsp.exe`) egress probe on every
channel every cycle (no restart-window exception — a genuinely seamless
reload should not drop packets either; a tsp result of `not-run` or
`error:...` — the TOOL is missing or failed to launch — is `HARNESS_ERROR`
instead, since a broken probe proves nothing about the product); **zero
unplanned relaunches**; and **every planned restart returns to `ON_AIR` on
GStreamer within 60 seconds** (a fixed PASS bound, unrelated to the
in-flight EXEMPTION window below). A worker pid change is classified
`planned_restart` if the channel's own sample ring shows `TRANSITIONING`
in the preceding 3 minutes (a normal schedule-plan rollover, expected with
`CIVICCAST_EGRESS_SEAMLESS_RELOAD` off, the beta.5 default) and
`unplanned_relaunch` otherwise (a crash); while a planned restart is in
flight, the channel is excused from the ON_AIR check for
max(60s, 2x the measured cycle period) — a separate, more generous number
than the 60s PASS bound, sized so a ~75s real cycle period can't flag a
correctly-classified restart before its own recovery clock has even been
checked once. `VERDICT.json` reports `unplanned_relaunch_count`,
`planned_restart_count`, `max_restart_gap_seconds`, and the full
`restart_events` list; otherwise **FAIL**, naming the first failing
cycle/event and why. This classification logic lives in
`scripts/RestartClassifier.ps1` (dot-sourced by the in-sandbox driver and
its own unit tests, `Test-RestartClassifier.ps1`) — extracted the same way
`SoakVerdict.ps1`/`HostLiveness.ps1` already were, after an inline version
had a parameter accidentally named `$Pid` (PowerShell's read-only `$PID`
automatic variable), which silently no-opped every ring write with no
crash and no product/host visible signal until this review caught it.

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
under `cycles/` (each channel row carries its own up-to-12-sample
`sample_ring` and the cycle's `measured_cycle_period_seconds`),
`restart-events.json`, a rollup every 3 minutes under `rollups/`,
per-channel egress worker logs (`logs/<label>/egress-per-channel/
<channel>/`, plus a `prepared/` directory LISTING, never a copy) alongside
the daemon-level logs at each checkpoint and on every FAIL, and a final
`VERDICT.json` / `VERDICT.txt` (verdict one of `PASS`, `FAIL`,
`HARNESS_ERROR`).

The verify/verdict logic lives in `scripts/SoakVerdict.ps1` (the per-cycle
PASS/FAIL/HARNESS_ERROR judgment), `scripts/RestartClassifier.ps1` (planned-
vs-unplanned restart classification and ring sampling), and
`scripts/HostLiveness.ps1` (the host's stall/quiet-share classification) —
each dot-sourced by both its real caller and its own unit-test file, so
the same code judges a real run and a synthetic unit-test tuple. Run the
unit tests with:

```powershell
pwsh -File sandbox-lab/scripts/Test-SoakVerdict.ps1
pwsh -File sandbox-lab/scripts/Test-RestartClassifier.ps1
pwsh -File sandbox-lab/scripts/Test-HostLiveness.ps1
```
