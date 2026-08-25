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
| `completion` | The harness itself reached its own authoritative completion signal (`DONE.json.harness_completed == true`, no `WATCHDOG-TIMEOUT.txt`/`STALL-TIMEOUT.txt`/`HOST-QUIET-SHARE.txt`) | `DONE.json`, `summary.json` |

**Two verdicts, and two non-verdicts.** `gate-a-verdict.json` carries `PASS`
or `FAIL` when the gate actually observed the candidate, and one of two other
values when it did not:

| Value | Meaning | Marker | Checks in the document |
|---|---|---|---|
| `PASS` / `FAIL` | A real station-acceptance finding | — | All computed, and they decide the verdict |
| `BUSY` | The run never started — Windows Sandbox was occupied by another process on this shared box (see "Shared Windows Sandbox: the busy guard") | `SANDBOX-BUSY.txt` | Empty: no evidence was ever produced |
| `HARNESS_ERROR` | The run started, then lost its evidence channel (see "Mapped-folder stalls") | `HOST-QUIET-SHARE.txt` | All computed and recorded as forensics, but they do not decide the verdict |

Neither non-verdict is reported as a FAIL. Calling a broken harness a product
failure is the same authored-truth mistake Gate A exists to eliminate,
pointed the other way. Exit codes: `0` PASS, `1` FAIL, `2` for `BUSY`,
`HARNESS_ERROR`, or a missing output directory — all of which mean "no
observation", never "bad candidate".

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

## Shared Windows Sandbox: the busy guard

Windows Sandbox is **single-instance per machine** — only one VM can run at a
time, system-wide, regardless of who launches it. The Gate A runner box is
**shared**: an independent, unrelated build system (not part of this
project) also launches Windows Sandbox on the same machine at unpredictable
times. Gate A's harness must never launch into that other party's sandbox,
wait on it ambiguously, or kill it — and the other party is symmetrically
unaware of Gate A. Neither side can coordinate with the other, so the guard
is entirely observational: check for a running sandbox before launching, and
never touch a sandbox process this run didn't itself start.

**`Host-Launch-Sandbox-Test.ps1` — pre-launch guard.** Immediately after
stamping a clean `output\` (step 1) and before rendering/launching the `.wsb`
(step 2), it checks `Get-Process` for any of `WindowsSandboxClient`,
`WindowsSandboxRemoteSession`, `WindowsSandboxServer`, `vmmemWindowsSandbox`.
If any are running:

- It does **not** launch. It polls every 30s, for up to `-SandboxWaitMinutes`
  (default `90`), logging one line every ~2 minutes to
  `output\SANDBOX-WAIT.txt` (timestamp + the observed process names/PIDs).
- If the sandbox frees up within the window, it proceeds to launch normally
  (with one more log line noting when it became free).
- If it is **still busy at the deadline**, it writes `output\SANDBOX-BUSY.txt`
  (same detail line as the final `SANDBOX-WAIT.txt` entry) and exits with
  code **`3`** — a distinct, harness-specific code, never touching the
  foreign sandbox.

**`Host-Launch-Sandbox-Test.ps1` — teardown guard.** The script records the
PIDs of its own sandbox processes right after its own `Start-Process` call
(the busy guard above already proved none were running immediately before
that point, and the single-instance property means every sandbox process
that exists from then on belongs to this run). At teardown it stops **only**
those recorded PIDs — never a blanket `Stop-Process` by name. If the
recorded PID list is empty, or none of those PIDs are still alive under a
sandbox process name, it logs that and leaves everything alive rather than
guessing (see the "NEVER kill by image name" lesson this guard was written
to avoid repeating).

**`Run-GateA.ps1`.** Accepts and passes through `-SandboxWaitMinutes`
(default `90`) to `Host-Launch-Sandbox-Test.ps1`. A launcher exit code of
`3` is treated as a **harness-busy** outcome, not a station-acceptance
FAIL: it writes a `gate-a-verdict.json` with `"verdict": "BUSY"` and
`"reason": "sandbox-busy-other-user"` (empty `checks`, since no evidence was
ever produced) into the evidence directory alongside whatever
`SANDBOX-WAIT.txt`/`SANDBOX-BUSY.txt` output exists, and exits **`2`**
(harness error) — never `1` (product FAIL).

**`scripts/gate_a_verdict.py`.** If `SANDBOX-BUSY.txt` is present in the
evidence directory being judged, the judge short-circuits to the same
`"verdict": "BUSY"` document *before* running any of the required checks,
rather than letting every check fail closed on evidence files that were
never going to exist (no sandbox ever launched). `main()` returns exit code
`2` for a `BUSY` verdict, matching the "harness error, not a product
finding" contract already used for a missing output directory. This applies
whether the judge is invoked by `Run-GateA.ps1` or run standalone against a
busy evidence directory.

**`gate-a-station-acceptance.yml`.** The `Fail the job on a non-PASS
verdict or harness error` step reads `gate-a-verdict.json`'s `verdict`
field when the run didn't PASS. A `BUSY` verdict gets a distinctly worded,
clearly-re-runnable failure message (Windows Sandbox was occupied by the
other party for the whole wait window — not a product regression) instead
of the generic non-PASS message. There is no auto-retry beyond the
launcher's own `-SandboxWaitMinutes` window; re-running the workflow is a
human/on-call action. The job's `concurrency: gate-a` group (unchanged by
this guard) only ever serializes **our own** Gate A runs against each
other — the other party's sandbox usage is invisible to GitHub Actions and
cannot be coordinated through workflow concurrency.

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
- **Script-level watchdog — two triggers, one process.** A genuinely
  separate `powershell.exe` process (`Start-Process`, deliberately **not**
  `Start-Job` — see the code comment for the documented `Start-Job`/
  PSWorkflow out-of-memory history on this VM) is spawned at script entry
  and polls every 30s:
  - **Overall bound.** If `DONE.json` still does not exist
    `-MaxScriptMinutes` minutes later (default 100), it writes
    `WATCHDOG-TIMEOUT.txt` and a placeholder `DONE.json` so
    `Host-Launch-Sandbox-Test.ps1`'s poll loop can never wait on a zombie
    in-sandbox script forever.
  - **Staleness bound**, added after `8579e66-run4` stalled 6+ minutes
    past `station-diag-captured-after-t3t5` (block 6's install-progress-log
    copy) with no forward progress and no `DONE.json` — `-MaxScriptMinutes`
    alone was far too coarse to catch that promptly. Once
    `summary.json.last_completed_step` first reaches a step at or after the
    runtime verdict (`runtime-check-*`, `t3t5-skipped-station-down`, or
    `t5-soak-complete`), the watchdog tracks it; if it stops changing for 8
    minutes, the watchdog writes `STALL-TIMEOUT.txt` and a placeholder
    `DONE.json` (`stall_timeout: true`).

  Either `WATCHDOG-TIMEOUT.txt` or `STALL-TIMEOUT.txt` is a named FAIL in
  the `completion` check regardless of what else in `DONE.json` looks
  complete.

  > **Superseded in part.** The staleness bound's *arming* rule described
  > above (match `last_completed_step` against three names) is what failed
  > on run6 and has been replaced — see "Mapped-folder stalls" below for the
  > arming fix, the `step_seq` change, and the new budget numbers
  > (`-MaxScriptMinutes` is 150, not 100). The two triggers and their two
  > marker files are otherwise unchanged.

## Mapped-folder stalls, the shipper, and the quiet-share fallback

Three Gate A runs hung late, each at a different statement, each with the
sandbox VM alive and `In-Sandbox-Report.ps1` writing nothing further:

| Run | Last `summary.json` step | What actually hung |
|---|---|---|
| run3 `8579e66` | `t2-render-assert` | The 5th of a run of consecutive ~30-byte `Add-Content` appends to `T3T5-RESULT.txt` — the file has 4 of its 9 expected lines |
| run4 `8579e66` | `station-diag-captured-after-t3t5` | The four-statement window to `install-progress-log-copied`, which includes a `Copy-Item` onto an existing mapped file |
| run6 `f31618f` | `station-diag-captured-after-t3t5` | Same window. Every product check had already **passed** (`T3_LOOP=PASS`, `CAPTIONS=PASS`, `T4_RESULT=PASS_PRODUCT_ENGINE`, `T5_RESULT=PASS beats=4 unhealthy=0`) before the run was failed closed 47 minutes later |

**What the failure mode is not.** "Sustained/large I/O exhausts the share"
does not survive run3, where a 30-byte append to an already-created file
wedged. "The share dies" does not survive run6: 42 minutes into that stall
the *separate* watchdog `powershell.exe` created `WATCHDOG-TIMEOUT.txt` and
`DONE.json` in the very same mapped folder, and both reached the host. The
share was fine.

**What it is.** A synchronous, uncancellable, timeout-less file operation
issued against a VSMB/9P share the guest does not control can wedge the
*issuing thread* permanently, while the share keeps serving other file
objects and other processes normally. `In-Sandbox-Report.ps1` ran the entire
gate on one thread and wrote every artifact straight to the share, so any
single wedged I/O ended the run silently. Whether the wedge is a stuck file
object or a stuck IRP on that connection cannot be distinguished from
post-mortem timestamps, and it does not matter: both have the same fix.

The fix takes the share off the critical path:

- **Local evidence directory.** `$OutDir` inside the sandbox is now
  `C:\CivicCastLocalOut`, on storage the VM owns. The transcript, every
  `T*-RESULT` file, every `station-diag` capture, every redirected child
  stdout/stderr, `summary.json`, and `DONE.json` all land there.
- **A shipper process.** A supervisor spawns one short-lived tick child every
  ~25s; each tick writes `_SHIPPER-HEARTBEAT.txt` locally and then
  `robocopy /E` mirrors the local directory into `C:\CivicCastOutput`. A tick
  that wedges on the share costs that tick — the supervisor skips while a
  child is still running, and force-replaces one older than three intervals,
  because a fresh process gets fresh handles (exactly the property run6's
  watchdog demonstrated). The mirror is **additive, never `/MIR`**: the host
  owns files in that folder too (`.gitkeep`, `_HOST_LAUNCHED.marker`,
  `SOAK_MINUTES.txt`, `HOST-QUIET-SHARE.txt`) and a purge would delete them.
  The one retraction the harness genuinely needs — a `WATCHDOG-TIMEOUT.txt`
  that a genuine completion later supersedes — is an explicit named list.
  `DONE.json` is excluded from the bulk mirror (`/XF`) and copied on its own
  after it returns, so the harness's oldest contract survives the new
  channel: DONE.json appearing on the host still means everything else
  already arrived. robocopy does not copy in write order, and the host tears
  the VM down within 10s of seeing that file.
- **Two bounded exceptions.** The driver itself touches the share exactly
  twice: a one-time inbound seed at entry (so host-provided
  `SOAK_MINUTES.txt` / `SKIP_MODE.txt` reach the reads further down) and a
  final flush after `DONE.json`. Both go through `Invoke-BoundedProcess`,
  which kills the child on timeout instead of waiting on it.
- **The watchdog moved too.** It now polls `summary.json` from, and writes
  its markers to, the local directory. In run6 it happened to write across
  the share successfully; had its *read* wedged instead, nothing at all would
  have fired.

### Why the staleness watchdog missed run6

It armed by matching the *current* value of `summary.json.last_completed_step`
against `runtime-check-*`, `t3t5-skipped-station-down`, or `t5-soak-complete`,
polling every 30 seconds. Every one of those is a momentary value. Run6's
`runtime-check-*` steps occupied `summary.json` from 22:29:57 to 22:29:58
(all three surfaces answered on poll #1 — see `RUNTIME-RESULT.txt`), and
`t5-soak-complete` was written at ~22:54:46 and superseded by
`station-diag-captured-after-t3t5` at 22:54:48. Roughly a 3-second target
sampled at 30-second intervals: the watchdog never armed, the run wedged at
22:54:48, and only the coarse 100-minute bound fired, at 23:36:50.

Two structural changes, both in `In-Sandbox-Report.ps1`:

- **Arm on a sticky file, not a transient value.** The driver writes
  `_VERDICT-STAGE.marker` once, at the station-up verdict (covering both the
  station-up and station-down paths), and never removes it. `Test-Path`
  cannot be raced by a coarse poller. The step-name predicate is kept —
  widened to every post-verdict step — as a redundant second arming path,
  never as the only one.
- **Stall on a monotonic counter, not name equality.** `summary.json` now
  carries `step_seq` (incremented on every `Save-Summary`) and `step_utc`.
  Step names can legitimately repeat; `step_seq` cannot, so "progress
  stopped" is an observation rather than an inference from string equality.

### The host's quiet-share fallback

On a healthy run the shipper heartbeat means *something* under `output\`
changes at least every ~25 seconds, right through the T5 soak's otherwise
silent 5-minute beats. `Host-Launch-Sandbox-Test.ps1` now watches for that:
no change anywhere under `output\` for `-QuietShareMinutes` (default 15)
while **our own** VM is still alive (checked by the PIDs the launcher
recorded right after its own launch, per the shared-sandbox ownership rule
above) means the guest-to-host channel — or the guest itself — is wedged and
no further waiting can produce evidence. It writes `HOST-QUIET-SHARE.txt` (on
the host's own disk, the one write in this system the wedged share cannot
affect) and exits **4** — distinct from the plain timeout's `2` and from the
busy guard's `3`, because "never started" and "started and went dark" are
different conditions. `scripts/gate_a_verdict.py` turns that marker into
`verdict: "HARNESS_ERROR"`.

### Budget ordering

| Bound | Where | Value |
|---|---|---|
| In-sandbox script watchdog | `In-Sandbox-Report.ps1 -MaxScriptMinutes` | 150 |
| Host poll deadline | `Host-Launch-Sandbox-Test.ps1 -TimeoutMinutes` | 170 |
| Same, passed through | `Run-GateA.ps1 -TimeoutMinutes` | 170 |
| Same again, **explicit override** | `.github/workflows/gate-a-station-acceptance.yml` | 170 |
| Host quiet-share bound | `Host-Launch-Sandbox-Test.ps1 -QuietShareMinutes` | 15 |
| In-sandbox staleness bound | watchdog `-StallMinutes` | 8 |

The poll deadline is **one setting written in three places**, and the CI
workflow's explicit argument is the one that actually governs every gate run
— a script default fixed on its own would have looked correct and changed
nothing. The watchdog must fire before that deadline or every long run
degrades into an unexplained host timeout with no watchdog evidence, which is
exactly what a 150-minute watchdog under the previous 120/150-minute host
deadlines would have produced.
`tests/gate_a/test_gate_a_harness_contract.py` reads all four literals and
fails the build if the ordering drifts.

`-SandboxWaitMinutes` (90) is deliberately **not** part of this ordering: it
bounds a wait *before* the run starts, not a run already underway.

### Residual risk this change does NOT remove

`C:\CivicCastHostStore` is also a read-write mapped folder, and it is the
**install target** — the product installs into `C:\CivicCastHostStore\install`
and the station runs from there, by design, so the install tree stays visible
to the host. The driver still reads that share synchronously on its own
thread (`Test-KnownPaths`, the `station-set.json` /
`activation-self-test.json` copies in `Invoke-StationDiagCapture`, the
install-tree listing). None of the three observed stalls were on that share,
and moving the install target would destroy the install evidence Gate A
exists to collect — so this is a named, accepted residual, not a solved
problem. What has changed is the blast radius: a wedge there is now bounded
by the staleness watchdog (8 minutes) and the host quiet-share detector (15
minutes) instead of running silently to the whole-script deadline, and it
reports as a stall or a harness error rather than as 47 minutes of nothing.

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

## Running Gate A in CI vs. locally

The workflow (`.github/workflows/gate-a-station-acceptance.yml`) does **not**
call `Run-GateA.ps1 -RunId` any more. `gh run download`'s single stream was
measured at ~1.3 GB/10min against the ~21 GB `native-beta-kit-<sha>`
artifact — ~2.5h per gate just to fetch the kit. Instead the workflow
resolves the candidate sha itself, prunes `kit-staging/` down to that sha
(21 GB/run adds up fast on a runner with finite disk), fetches the artifact
with `actions/download-artifact@v4` (parallel, chunked — a few minutes
instead of hours), and calls `Run-GateA.ps1 -KitDir sandbox-lab/kit-staging/<sha>
-SourceSha <sha> -RunId <id>` — the sha and run id are passed through as
metadata so `gate-a-verdict.json` still carries them even though the script
itself didn't do the resolving.

`-RunId` alone (the single-stream `gh run download` path) still works and is
the right choice for a one-off local run against a completed
`native-beta-candidate-artifacts` build, where standing up the parallel-
download step isn't worth it for a single kit fetch.

Prerequisites: Windows with the Windows Sandbox feature enabled, `gh`
(GitHub CLI, authenticated) if using `-RunId`, `uv` on PATH.

```powershell
# From a completed native-beta-candidate-artifacts workflow run:
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId 32444504123

# Against an already-extracted kit directory (skip the gh download) --
# the shape CI itself uses after its own parallel download:
pwsh -File sandbox-lab/Run-GateA.ps1 -KitDir C:\path\to\extracted-kit -SourceSha abc1234 -RunId 32444504123

# Shorter soak window for a quick local check:
pwsh -File sandbox-lab/Run-GateA.ps1 -RunId 32444504123 -SoakMinutes 5 -TimeoutMinutes 60
```

`-SourceSha` and `-RunId` are optional with `-KitDir`. Without `-SourceSha`,
the script tries the kit's own `station\native-station-bundle-report.json`
next (forward-looking — that report does not carry a sha-shaped field as of
this writing), then the `-KitDir` leaf directory name if it looks like a sha
(the `kit-staging\<sha>\` convention), then falls back to `unknown-local`.

Exit codes: `0` = PASS, `1` = FAIL (a real station-acceptance finding —
see `gate-a-verdict.json`), `2` = anything that is not a station-acceptance
finding at all: a `BUSY` verdict (Windows Sandbox was occupied by the other,
independent process on this box for the whole `-SandboxWaitMinutes` wait
window — see "Shared Windows Sandbox: the busy guard" above), a
`HARNESS_ERROR` verdict (the mapped output folder went quiet while the VM
was alive — see "Mapped-folder stalls" below), a timeout waiting for
`DONE.json`, no Sandbox VM, a bad/incomplete kit layout, or missing
`gh`/`uv`. None of those is ever a statement about the candidate.

`Host-Launch-Sandbox-Test.ps1` itself uses finer codes, all of which
`Run-GateA.ps1` collapses into its own `2` after recording which one
happened in the evidence directory — so callers only ever need to handle
`Run-GateA.ps1`'s three exit codes (`0`/`1`/`2`):

| Launcher exit | Meaning |
|---|---|
| `1` | No Windows Sandbox VM process a few seconds after launch |
| `2` | Timed out waiting for `DONE.json` |
| `3` | Gave up waiting for Windows Sandbox to become free; never launched (`SANDBOX-BUSY.txt`) |
| `4` | Launched, then the mapped output folder went quiet while the VM was alive (`HOST-QUIET-SHARE.txt`) |

Evidence for every run — pass or fail — lands at
`sandbox-lab/evidence/<source_sha>/<utc-timestamp>/`, a full copy of
`sandbox-lab/output/` plus `gate-a-verdict.json`.

## Cutting the download further: self-hosted candidate builds

Even at ~1-2 MB/s the download above is one leg of a two-leg transfer
problem: `native-beta-candidate-artifacts.yml` normally builds on a hosted
`windows-latest` runner and uploads the same ~21 GB kit (plus an ~18.6 GB
station bundle and a ~3 GB candidate) before Gate A ever starts pulling it
back down onto this box — full round trip, ~2.5-3h before the Windows
Sandbox even launches.

`native-beta-candidate-artifacts.yml` accepts a `build_target` input on
manual dispatch. `hosted` (the default, and every `push`-triggered build on
the release branch) is unchanged from the description above. `self-hosted`
runs the build on THIS SAME `[self-hosted, windows, sandbox-lab]` box Gate A
runs on. It keeps intermediate mirrors under
`C:\CivicCastTester\candidates\<sha>\` and writes the FINAL kit in the flat
layout Gate A expects — `setup.exe`, `packs\`, `station\` directly under the
directory — straight to `C:\CivicCastTester\kit-staging\<sha>\`, instead of
only uploading it. By default it also skips the two large uploads (station
bundle, kit) — the small `native-beta-candidate-<sha>` artifact (~3 GB)
still uploads unconditionally. Pass `upload_large_artifacts: true` on the
dispatch to force the two large uploads anyway (e.g. to let a different
machine run Gate A against that candidate).

`gate-a-station-acceptance.yml` owns the consumer side of this contract in
its own "Reuse a locally pre-staged kit" step: it checks
`C:\CivicCastTester\kit-staging\<sha>\` directly (a `station\` subdirectory
and a `*setup.exe` at the root) and, when present, junctions it into
`sandbox-lab/kit-staging/<sha>` and skips the ~21 GB download entirely. Any
candidate that step doesn't find this way — an older run predating this
contract, a hosted build, or a self-hosted build whose local path isn't
present on the box handling this particular Gate A run — falls back to the
`actions/download-artifact@v4` fetch exactly as described above. Producer
(this workflow) and consumer (that step) are deliberately two separate,
independently mergeable changes that agree only on the path/layout contract
above, not on a shared artifact or workflow-to-workflow signal.

Because a self-hosted build and Gate A now share the one physical box, both
workflows' top-level `concurrency:` block uses the same `sandbox-lab` group
when a self-hosted build is in play, so the two never execute at once — the
later one queues (`cancel-in-progress: false`) rather than contending for
the box's disk, CPU, and the Windows Sandbox feature itself. Only dispatch a
self-hosted candidate build when Gate A is not currently mid-run; queueing
behind it is safe but still a wait.

The self-hosted lane also makes the compiled PyAV wheel's byte-exact
reproducibility check (inside `scripts/build_native_pyav_wheel.py`)
advisory rather than a hard failure — see
`docs/process/pyav-wheel-reproducibility.md` for why running the identical
pinned toolchain on a different physical machine can legitimately produce
non-byte-identical (but still correct — the runtime probe and license gate
both still run unconditionally) output. Every pinned *download* in that
build stays a hard failure on every lane; only the final compiled wheel's
identity assertion is affected, and only on `self-hosted`.

Local disk under both `C:\CivicCastTester\candidates\` and
`C:\CivicCastTester\kit-staging\` is pruned to the current sha at the start
of `build-native-beta` on the self-hosted lane, the same pattern
`gate-a-station-acceptance.yml` already used for its own
`sandbox-lab/kit-staging\` — without it, every self-hosted dispatch would
add another ~20-40 GB across the two roots that never gets reclaimed.

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
│   #  (writes to the VM-local C:\CivicCastLocalOut; a shipper child process
│   #   mirrors that into the mapped C:\CivicCastOutput, i.e. output\ below)
│   ├── Watch-Run.ps1                   # Legacy interactive monitor — NOT used by Run-GateA.ps1
│   ├── PREFLIGHT.md                    # Static parse/semantics verification record
│   └── lpm-sample-short.mp4            # Real speech clip for a meaningful captions proof
├── soak-4h/                            # Copied verbatim from the v3.0 tester-handoff kit (read-only source)
├── runner/
│   └── Install-GateARunner.ps1         # Self-hosted Windows runner registration (interactive logon task)
├── output/        (gitignored)         # Live run output — wiped at the start of every run
├── hoststore/      (gitignored)        # Persistent install dir — reset at the start of every run
├── kit-download/   (gitignored)        # Junction to the resolved kit — never a copy
│   # (no .gitkeep here -- Run-GateA.ps1 deletes and replaces this whole
│   #  directory with an NTFS junction on every run, so a tracked placeholder
│   #  file inside it can never survive a run; kit-staging/ and evidence/
│   #  keep theirs because those directories are only written INTO, never
│   #  replaced wholesale)
├── kit-staging/    (gitignored)        # Downloaded candidate artifacts, keyed by source SHA
│   #  (in CI: pruned to only the current candidate's sha before every
│   #   download -- kits run ~21 GB each and the runner's disk is finite)
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
touches is a fixed Sandbox-internal path, either a mapped-folder mount
(`C:\CivicCastPayload`, `C:\CivicCastOutput`, `C:\CivicCastScripts`,
`C:\CivicCastHostStore`, `C:\CivicCastSoak`) or, since the mapped-folder-stall
fix, the VM-local `C:\CivicCastLocalOut` — never a host path — so it was
imported byte-for-byte. Only `Host-Launch-Sandbox-Test.ps1` needed
parameterization (it previously hardcoded an absolute host `$Root`), and the
`.wsb` became a template rendered per-run instead of a static file, because
Windows Sandbox's `MappedFolder` entries require absolute host paths that
cannot be relative to the `.wsb` file's own location.
