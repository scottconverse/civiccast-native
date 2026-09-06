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

## 15-minute local soak

A fast, LOCAL pre-check that finds bugs on HALO in ~15 minutes instead of on
a tester box in hours. It drives a real silent install + station start +
sample-content playout inside a disposable Windows Sandbox VM, using a kit
already verified on disk (no download). It is **not** a replacement for
Gate A — it's a quick sanity pass you run before pushing something out to
the tester fleet, reusing Gate A's own proven install/health/channel-start
code paths (see `scripts/In-Sandbox-Soak.ps1`'s header for exactly which
lines came from where) at a much shorter default duration.

```powershell
pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> [-Minutes 15] [-KitRoot C:\CivicCastTester\kit-safe]
```

Add `-DryRun` to verify the kit, render the `.wsb`, and parse-check both
in-sandbox scripts without ever launching Windows Sandbox.

What it checks, end to end: silent install (`/S /D=...`) exits 0, the
station reports healthy at `/health`, first-admin setup succeeds, the kit's
`samples\*.mp4` clips upload as assets and get scheduled + committed to air
on all three channels, then polls every 60s for `-Minutes` minutes. **PASS**
requires every cycle after a 3-minute warm-up grace to have all three
channels `ON_AIR` on GStreamer, a passing TSDuck (`tsp.exe`) egress probe on
each channel's UDP sink, and zero worker relaunches; otherwise **FAIL**,
naming the first failing cycle and why.

Refuses to start (exit 3) if Windows Sandbox is already running (it's a
single-instance-per-machine resource shared with Gate A and other agents on
this box) and refuses (exit 2) if the kit's `SHA256SUMS.txt` is missing or
any listed file fails verification. A stall guard (exit 4) fires if no new
rollup lands for 6 minutes — it kills the sandbox and preserves whatever
evidence exists rather than hanging indefinitely.

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
