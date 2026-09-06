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
pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> [-Minutes 15] [-KitRoot C:\CivicCastTester\kit-safe]
```

Add `-DryRun` to verify the kit, render the `.wsb`, and parse-check both
in-sandbox scripts without ever launching Windows Sandbox.

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
first-admin setup succeeds, the kit's `samples\*.mp4` clips upload as assets
(pinned to a 30-second schedule slot each — the deliberate rollover
instrument, not a discovered duration) and get scheduled + committed to air
on all three channels, then polls every 60s for `-Minutes` SOAK minutes.
**PASS** requires every cycle after a 3-minute warm-up grace to have all
three channels `ON_AIR` on an OS-process-verified GStreamer engine (never
a software fallback), a passing TSDuck (`tsp.exe`) egress probe on each
channel's UDP sink, and zero worker relaunches; otherwise **FAIL**, naming
the first failing cycle and why.

Refuses to start (exit 3) if Windows Sandbox is already running (it's a
single-instance-per-machine resource shared with Gate A and other agents on
this box) and refuses (exit 2) if the kit's `SHA256SUMS.txt` is missing or
any listed file fails verification. Separate stall bounds apply per phase
— installer (default 20 min from launch), station-healthy (default 10 min
after install), rollup-stall (default 6 min once the soak clock has
started) — plus a generic 15-minute quiet-liveness backstop (newest mtime
among `soak-log.txt`/`summary.json`/`_SHIPPER-HEARTBEAT.txt`) that covers
every phase, including setup (first-admin/asset-upload/schedule/
channel-start) which has no dedicated bound of its own. A stall (exit 4)
kills the sandbox and preserves whatever evidence exists rather than
hanging indefinitely; ownership is checked first (WindowsSandboxRemoteSession
/WindowsSandboxServer StartTime must not predate this run's own launch) —
if a stall fires against a session this run did not launch, nothing is
killed and it exits 5 instead, writing `FOREIGN-SANDBOX-SESSION.txt`.

Evidence lands under `soak-output/soak-<shortsha>-<UTC stamp>/` — a
separate per-run root from Gate A's own `output/` above (which
`Host-Launch-Sandbox-Test.ps1` wipes at the start of every Gate A run, so
sharing it would risk a soak run's evidence being deleted mid-run by a
concurrent Gate A run). Every run writes `summary.json`, per-cycle JSON
under `cycles/`, a rollup every 3 minutes under `rollups/`, station logs
copied at each rollup checkpoint and at the end, and a final
`VERDICT.json` / `VERDICT.txt`.

The verify/verdict logic lives in `scripts/SoakVerdict.ps1` (dot-sourced by
both the in-sandbox driver and the unit tests, so the same code judges a
real run and a synthetic one). Run the unit tests with:

```powershell
pwsh -File sandbox-lab/scripts/Test-SoakVerdict.ps1
```
