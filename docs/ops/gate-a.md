# Gate A — Automated Station-Acceptance Release Gate

## Why this exists

This project's historical failure mode is builder-authored "it works" claims
outrunning reality (see `CLAUDE.md`'s Mandatory CivicCast Cross-Agent Audit
Protocol). Gate A replaces prose with a machine verdict: a clean Windows
Sandbox install of the real candidate kit, K1 activation, both UIs rendered,
the clerk loop (upload → publish → captions) exercised, the product egress
engine verified with TSDuck, and a bounded soak — judged by code, fail-closed,
never from prose.

It is built from a standalone harness (`Host-Launch-Sandbox-Test.ps1` +
`In-Sandbox-Report.ps1`) that was proven manually against real candidate
builds before this repository absorbed it. See "Provenance" below.

## What Gate A proves, and what it does not

**Proves** (the checks in `scripts/gate_a_verdict.py`, each fail-closed):

| Check | What it proves | Evidence file(s) |
|---|---|---|
| `install` | The signed installer runs silently to exit 0 and station-set.json exists after install | `summary.json` |
| `activation` | The K1 mandatory activation hook ran and staged the station | `ACTIVATION-RESULT.txt`, `summary.json` |
| `runtime` | The station answers `/api/health`, the operator console, and the resident portal, all HTTP 200 | `summary.json.runtime_checks` |
| `t2_render` | Both UIs actually render their SPA shell (not just serve a stub document — checked via a headless-Edge DOM dump ratio) | `T2-RENDER-RESULT.txt` |
| `t3_loop` | The clerk loop completes: nonce → first-admin → token → upload → package → approve/publish → public listing | `T3T5-RESULT.txt`, `T3-LOOP.txt` |
| `captions` | The offline caption pipeline produced real cues from a real speech clip (not a synthetic sine tone) | `T3-LOOP.txt`, `T3-caption-artifact.json` |
| `t4_engine` | The product egress engine (GStreamer) started and passed TSDuck transport-stream verification — `PASS_FFMPEG_FALLBACK` is a FAIL, see below | `T3T5-RESULT.txt` |
| `t5_soak` | The bounded soak stayed healthy for its whole window (`unhealthy=0`) | `T3T5-RESULT.txt` |
| `completion` | The harness itself reached its own authoritative completion signal (`DONE.json.harness_completed == true`, no `WATCHDOG-TIMEOUT.txt`) | `DONE.json`, `summary.json` |

Each row cites the 3.0 MASTER spec's station-acceptance gate
(`docs/spec/3.0/civiccast-3.0-station-in-a-box-MASTER.md` §12, "Station
acceptance"): *"operator installs+commissions without terminal work ... runs
the three PEG channels ... publishes VOD from a recorded meeting..."* — Gate A
exercises the subset of that ladder a disposable, offline, no-SDI Windows
Sandbox VM can prove in under two hours, not the whole ladder.

**Does NOT prove** — these remain out of scope by design, not by oversight:

- The 24h/72h real-hardware unattended soaks with kill+restart+reboot (§12,
  §5 unified proof/certification ladder). That is **Gate B**, a separate,
  real-hardware job — not built here.
- Physical SDI proof (rung 3 of the proof ladder). Windows Sandbox has no
  hardware pass-through.
- The commissioning-wizard UI walkthrough, force matrix, schedule commit,
  OTT-app presence, and support-bundle export — the existing
  Playwright/manual acceptance work covers these; Gate A does not replace
  them.
- Networking is disabled inside the Sandbox VM (see `CivicCastSandboxTest.wsb.template`),
  so YouTube Live / Internet Archive / real syndication targets are never
  exercised — only the portal-tier clerk loop and local egress.

### `t4_engine` policy: `PASS_FFMPEG_FALLBACK` is a FAIL

`In-Sandbox-Report.ps1`'s T4 step first attempts the real product egress
engine (GStreamer, driven through `/api/staff/egress/channels/.../commands`);
if that path is blocked for any reason it falls back to spawning synthetic
ffmpeg encoders and re-using the soak kit's `verify-egress.ps1` TSDuck check,
recording `T4_RESULT=PASS_FFMPEG_FALLBACK`. That fallback predates
CHANGELOG's "Egress default engine flipped to GStreamer (S15)". Now that
GStreamer is the shipped default engine, a candidate that only proves the
fallback path has not proven what a real station actually runs — so Gate A's
`t4_engine` check treats `PASS_FFMPEG_FALLBACK` as a named FAIL, not a
degraded pass, and only accepts `T4_RESULT=PASS_PRODUCT_ENGINE`.

## Station-up wait, diagnostics capture, and the script-level watchdog

Added after the 8579e66-run3 evidence showed the station's own process
never listened on `:8000` and the harness had no way to see why (its
child-process logs live under `%ProgramData%\CivicCast\logs`, ephemeral
inside Windows Sandbox, and nothing copied them out before the VM was
torn down):

- **Station-up wait.** `In-Sandbox-Report.ps1` polls **only**
  `/api/health` on a single bounded 20-minute deadline (6s interval),
  logging every poll's timestamp and outcome to `STATION-UP-WAIT.txt`.
  `/operator/` and `/` are only probed (60s bound each) once health has
  answered 200. `summary.json` records `station_up`,
  `station_first_healthy_utc`, and `station_boot_seconds` (measured from
  `_AFTER_INSTALL.marker`) — `station_boot_seconds` is **informational
  only** in `gate-a-verdict.json`; Gate A does not fail on boot duration
  (Gate B owns timing).
- **Station diagnostics capture.** `Invoke-StationDiagCapture` runs at
  three points — right after the station-up wait concludes (pass or
  fail), right after the T3/T4/T5 decision, and unconditionally in the
  top-level `finally` block — writing bounded snapshots to
  `output/station-diag/<after-station-up-wait|after-t3t5|final>/`: a
  `robocopy` of `%ProgramData%\CivicCast\logs` (every child's `<name>.log`
  plus the rotating `supervisor.log`, per
  `civiccast/native/supervisor/install_layout.py`), a `robocopy` of
  `%ProgramData%\CivicCast\config` (excluding `data`/`pgdata`/`nats-store`),
  `sc qc`/`sc query` output, `netstat -ano` LISTENING lines, a filtered
  `tasklist /v`, and up to 200 Application/System Windows Event Log
  errors/warnings since `_STARTED.marker`. None of these operations scan
  the multi-GB install tree.
- **No hangs when the station never comes up.** If `station_up` is
  `False`, T3/T4/T5 are explicitly skipped (never attempted) — each
  writes its own result file with a `SKIPPED(station-down)` verdict line
  rather than being left absent or hanging in an unbounded loop.
  `scripts/gate_a_verdict.py` already fails closed on any non-`PASS`
  value for these checks, so this changes the evidence trail, not the
  judge's pass/fail contract for `t3_loop`/`captions`/`t4_engine`/`t5_soak`.
- **Script-level watchdog.** A genuinely separate `powershell.exe` process
  (`Start-Process`, deliberately **not** `Start-Job` — see the code
  comment for the documented `Start-Job`/PSWorkflow out-of-memory history
  on this VM) is spawned at script entry. If `DONE.json` still does not
  exist `-MaxScriptMinutes` minutes later (default 100), it writes
  `WATCHDOG-TIMEOUT.txt` and a placeholder `DONE.json` so
  `Host-Launch-Sandbox-Test.ps1`'s poll loop can never wait on a zombie
  in-sandbox script forever. `WATCHDOG-TIMEOUT.txt` is a named FAIL in
  the `completion` check regardless of what else in `DONE.json` looks
  complete.

## Known harness quirk: the Aug-19 reference run's `completion` check

The PASS fixture used in `tests/gate_a/fixtures/pass-2026-08-19/` is a
verbatim copy of a real Windows Sandbox run's output directory from
2026-08-19 that exercised every step successfully — `T2_RENDER=PASS`,
`T3_RESULT=PASS`, `T3_LOOP=PASS`, `CAPTIONS=PASS` (cue_count 20),
`T4_RESULT=PASS_PRODUCT_ENGINE`, `T5_RESULT=PASS beats=2 unhealthy=0`. **It
does not contain `DONE.json`.** Judging it with `scripts/gate_a_verdict.py`
produces an overall verdict of **FAIL** — every check passes except
`completion`.

This is a real, documented property of that historical run, not a bug in the
fixture or the judge, and this module deliberately does not special-case it
to force a PASS — doing that would be exactly the "authored truth" failure
mode Gate A exists to eliminate. Root cause: `In-Sandbox-Report.ps1` writes
`DONE.json` as the very last thing it does, inside a `finally` block, after
stopping its own PowerShell transcript and querying the Windows Event Log.
The Aug-19 run (and an earlier run captured in
`sandbox-lab/evidence/run2-summary.json`, whose own `harness_note` field
independently documents the same pattern) was monitored by the old
host-side `sandbox-lab/scripts/Watch-Run.ps1` script, which declares "done"
the instant `T3T5-RESULT.txt` contains a `T5_RESULT=` line — racing ahead of
the script's own `finally` block by several minutes. The operator's habit of
closing the Sandbox VM as soon as the watcher printed `DONE` pre-empted that
tail end of the script before it could write `DONE.json`.

`Run-GateA.ps1` does not use `Watch-Run.ps1`. It uses
`Host-Launch-Sandbox-Test.ps1`'s own poll loop, which waits for the real
`DONE.json` file (up to `-TimeoutMinutes`) before it will touch the VM. A
real Gate A run is therefore expected to produce a genuine `DONE.json` when
the run truly completes; `Watch-Run.ps1` is kept in `sandbox-lab/scripts/`
only for interactive manual debugging, and Gate A's own orchestration never
invokes it.

## Running Gate A locally

Prerequisites: Windows with the Windows Sandbox feature enabled, `gh`
(GitHub CLI, authenticated) if using `-RunId`, `uv` on PATH.

```powershell
# From a completed native-beta-candidate-artifacts workflow run:
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId 32444504123

# Against an already-extracted kit directory (skip the gh download):
pwsh -File sandbox-lab/Run-GateA.ps1 -KitDir C:\path\to\extracted-kit

# Shorter soak window for a quick local check:
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId 32444504123 -SoakMinutes 5 -TimeoutMinutes 60
```

Exit codes: `0` = PASS, `1` = FAIL (a real station-acceptance finding —
see `gate-a-verdict.json`), `2` = harness error (timeout waiting for
`DONE.json`, no Sandbox VM, bad/incomplete kit layout, missing `gh`/`uv`).

Evidence for every run — pass or fail — lands at
`sandbox-lab/evidence/<source_sha>/<utc-timestamp>/`, a full copy of
`sandbox-lab/output/` plus `gate-a-verdict.json`.

You can also run the judge directly against any evidence directory without
launching Sandbox at all:

```powershell
uv run python scripts/gate_a_verdict.py sandbox-lab/evidence/<sha>/<stamp> --source-sha <sha> --run-id <id>
```

## Directory layout (`sandbox-lab/`)

```text
sandbox-lab/
├── CivicCastSandboxTest.wsb.template   # Windows Sandbox config template (rendered per-run)
├── Host-Launch-Sandbox-Test.ps1        # Host: renders the .wsb, launches Sandbox, polls DONE.json
├── Run-GateA.ps1                       # Host: kit resolution + orchestration + judging + evidence
├── scripts/
│   ├── In-Sandbox-Report.ps1           # Runs INSIDE the Sandbox VM (LogonCommand) — the driver
│   ├── Watch-Run.ps1                   # Legacy interactive monitor — NOT used by Run-GateA.ps1
│   ├── PREFLIGHT.md                    # Static parse/semantics verification record
│   └── lpm-sample-short.mp4            # Real speech clip for a meaningful captions proof
├── soak-4h/                            # Copied verbatim from the v3.0 tester-handoff kit (read-only source)
├── runner/
│   └── Install-GateARunner.ps1         # Self-hosted Windows runner registration (interactive logon task)
├── output/        (gitignored)         # Live run output — wiped at the start of every run
├── hoststore/      (gitignored)        # Persistent install dir — reset at the start of every run
├── kit-download/   (gitignored)        # Junction to the resolved kit — never a copy
├── kit-staging/    (gitignored)        # Downloaded candidate artifacts, keyed by source SHA
└── evidence/       (gitignored)        # Every run's preserved output, keyed by <sha>/<timestamp>
```

## Runner setup

Gate A needs an interactive Windows desktop session — Windows Sandbox cannot
launch from a Session-0 service. `sandbox-lab/runner/Install-GateARunner.ps1`
registers the self-hosted runner as an **interactive logon scheduled task**,
not a Windows service (contrast with the existing Linux self-hosted runner in
`docs/ops/self-hosted-ci.md`, which correctly must be a systemd service for
its own, opposite reason). See that script's header comment for the full
rationale.

```powershell
# Get a registration token first:
gh api repos/scottconverse/civiccast-native/actions/runners/registration-token --method POST

pwsh -File sandbox-lab/runner/Install-GateARunner.ps1 -Token <token>
```

This installs to `C:\actions-runner-gate-a` by default, registers with labels
`self-hosted,windows,sandbox-lab`, and creates a scheduled task that starts
`run.cmd` at interactive logon for the current user. The task was not
launched by this install (no token available in this environment to actually
register against GitHub) — after registering, either log off/on once or run
`Start-ScheduledTask -TaskName 'CivicCastGateARunner-<name>'` to start it,
then confirm with `gh api repos/scottconverse/civiccast-native/actions/runners`.

## Promotion rule

Gate A's workflow (`.github/workflows/gate-a-station-acceptance.yml`) is
**informational only**. It runs automatically after every successful
`native-beta-candidate-artifacts` build and reports its verdict, but it does
not block merges or releases. Per this repo's CLAUDE.md "Owner gates"
section, only Scott can promote it to a required check (branch protection)
and only Scott flips that setting — no agent does this automatically. The
agreed bar: promote after **3 consecutive green (PASS) runs** against real
candidate builds.

## Provenance

Gate A's harness scripts were imported from a standalone proof harness at
`C:\Users\scott\Desktop\Code\sandbox-lab\` (outside this repository, not a
git repo) that was manually proven against real candidate builds before this
import. `In-Sandbox-Report.ps1` needed no host-path changes — every path it
touches is a fixed Sandbox-internal mapped-folder drive letter
(`C:\CivicCastPayload`, `C:\CivicCastOutput`, `C:\CivicCastScripts`,
`C:\CivicCastHostStore`, `C:\CivicCastSoak`), never a host path — so it was
imported byte-for-byte. Only `Host-Launch-Sandbox-Test.ps1` needed
parameterization (it previously hardcoded an absolute host `$Root`), and the
`.wsb` became a template rendered per-run instead of a static file, because
Windows Sandbox's `MappedFolder` entries require absolute host paths that
cannot be relative to the `.wsb` file's own location.
