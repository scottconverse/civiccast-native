# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# In-Sandbox-Soak.ps1 -- runs INSIDE Windows Sandbox via the .wsb
# LogonCommand rendered from CivicCastSandboxSoak.wsb.template. Drives a
# silent install of the mapped kit, starts the station, sets it up
# (first-admin), loads the kit's sample videos into the three egress
# channels, commits them to air, then polls every 60s for -Minutes SOAK
# minutes (the clock starts only once /health is OK and all three channels
# are configured/started -- see soak_start_utc below, NOT from process
# launch), writing a rollup every 3 minutes plus station logs, and a final
# VERDICT.json/VERDICT.txt when done.
#
# PS 5.1 COMPATIBLE ONLY -- Windows Sandbox's built-in Windows PowerShell is
# 5.1, not PowerShell 7. No ternary (?:), no null-coalescing (??), no
# `[array]::Empty[...]`, no `-Parallel`. Reused code paths (silent install
# flag, health endpoint + predicate, first-admin body shape, multipart asset
# upload, schedule+commit, channel config/start, tsp egress probe, bounded
# process pattern, VSMB-safe local-dir+shipper architecture) come from:
#   - sandbox-lab/Run-GateA.ps1 (host) + sandbox-lab/scripts/In-Sandbox-Report.ps1
#     (guest): silent install is `/S /D=C:\...\install` (NSIS convention);
#     health lives at both /health and /api/health (civiccast/app.py:2140-2141,
#     same handler); the health PREDICATE requires body.status=="healthy" AND
#     body.schema=="current" (In-Sandbox-Report.ps1:2852-2860 -- HTTP 200 is
#     LIVENESS ONLY, per Gate A run 33681670855's lesson: a beta.3 station
#     serving 500s over an unmigrated beta.2 DB still answered 200 with
#     {"status":"degraded","schema":"behind"}); the local-dir + background
#     shipper architecture (In-Sandbox-Report.ps1's <gate-a-mapped-folder-
#     stalls> section, ~lines 39-155) so a wedged write against the mapped
#     folder shows up as a stale mtime on the host, never a hung main
#     thread; the PS 5.1 Start-Process/PassThru ExitCode-reads-$null-unless-
#     Handle-is-cached-first bug (memory: ps51-passthru-exitcode-null.md;
#     also In-Sandbox-Report.ps1's Invoke-BoundedProcess pattern) for the
#     bounded installer run; targeted/bounded candidate-path checks instead
#     of a full-tree recursive scan (In-Sandbox-Report.ps1:18-28's HARDENED
#     note on why a full `Get-ChildItem -Recurse` over the install tree is
#     slow/risky on Windows Sandbox's virtualized storage).
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-8.ps1: the
#     POST /api/setup/first-admin body shape (FirstAdminSetupRequest).
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-9m.ps1: the
#     PROVEN-WORKING (beta.5-shaped, HTTP 422 avoided) multipart asset
#     upload, channel config PUT body, schedule POST + Commit-to-Air POST
#     ordering (schedule/commit ALL channels while still stopped, THEN
#     config+start -- avoids a reload storm on an already-ON_AIR channel),
#     and the ON_AIR poll.
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-9e.ps1:341-342:
#     the asset_id SHAPE -- 'sbsoak-' + yyMMddHHmmss + '-' + 4 random a-z
#     chars (+ a per-clip index appended here, see below) -- required
#     because civiccast/schedule/router.py:724-727 constrains asset_id to
#     `^[a-z0-9][a-z0-9-]{2,63}$` (lowercase only; the first cut of this
#     script used mixed-case + a UTC 'T'/'Z' timestamp and 422'd on every
#     upload, and two clips whose first 20 basename chars matched collided
#     409 on top of that).
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-3.ps1: the
#     tsp.exe egress-proof invocation (Test-TsProof), per-channel relaunch
#     (worker-restart) tracking (Update-RelaunchTracking), and the engine
#     CENSUS via Win32_Process CommandLine matching
#     (AUTORUN-3.ps1:244-251) -- civiccast/egress/models.py:506-518 shows
#     EgressStateRow carries NO `engine` field at all, so the engine can
#     only be inferred from the OS process, never read off the state API.
#
# ROLLOVER INSTRUMENT: every scheduled item is pinned to duration_seconds=30
# regardless of the clip's real length (civiccast/schedule's D42 clips media
# to the slot, so this is a legitimate schedule, not a lie about the asset).
# ffprobe is deliberately NOT used to discover real durations -- the kit
# ships ffmpeg only under packs\*.ccpack and the installed layout puts it
# under `dependencies\`, not `packs\...\payload\` (that path only ever
# existed in this script's own wrong guess, and does not exist once
# installed to -D=C:\CivicCastSoakInstall) -- so probing was always going to
# silently fall back to a default anyway. Fixing it to be an EXPLICIT
# constant turns "every clip happens to default to 30s" into "every 30s slot
# is the intended rollover instrument": with (Minutes+10)*2 items per
# channel at 30s each, program content rolls over roughly every 4 minutes
# for the whole soak, which is exactly the cadence a real soak needs to
# prove the engine survives a source-plan rollover repeatedly, not just once.
param(
    [int]$Minutes = 15,
    # Round-15 finding (a): was a hardcoded `$OnAirBoundMinutes = 12` deep
    # in section 4 -- now a real parameter, threaded from
    # Run-SandboxSoak.ps1's own -OnAirBoundMinutes (default 12, unchanged
    # behavior for every existing caller that doesn't pass it) so the
    # coordinator can widen/narrow the ON_AIR bound per run without editing
    # this file. Recorded in SOAK-START.json/VERDICT.json alongside
    # everything else the ON_AIR poll already carries.
    [int]$OnAirBoundMinutes = 12,
    # Round-6 item 1: when set, the guest exports
    # CIVICCAST_EGRESS_SEAMLESS_RELOAD=1 at MACHINE scope before starting the
    # CivicCastSupervisor service, so the service and its control-plane
    # child inherit it (civiccast/egress/gst/strategy.py:627-634 on PR #176,
    # head 20f316f, reads it with a truthy check -- that PR is unmerged as
    # of this writing, so this lane cannot independently verify the exact
    # line numbers/behavior against ITS OWN checkout; the env var name and
    # contract are taken as given from the coordinator). Recorded as
    # seamless_reload=<bool> in the header log line, SOAK-START.json, and
    # VERDICT.json regardless of whether verification below succeeds.
    [switch]$SeamlessReload,

    # sandbox-soak lane follow-up A, item 1: when set, right after
    # first-admin succeeds this PUTs {"live_captions_enabled": false} to
    # /api/staff/station/profile (civiccast/platform/station_router.py's
    # `put_station_profile`) using the operator's own first-admin token,
    # then GETs the profile back to confirm the read-back value is really
    # the boolean $false -- never the machine-scope caption-tap env var
    # (CIVICCAST_CAPTION_TAP), which this switch deliberately does not
    # touch. A failed PUT or a read-back that is not false is a
    # HARNESS_ERROR (the operator explicitly asked to test this flag; see
    # CaptionsOffCheck.ps1's Get-CaptionsOffVerification, same principle as
    # -SeamlessReload's own verification above). Recorded as
    # captions_enabled/captions_off_verified in SOAK-START.json and
    # VERDICT.json regardless.
    [switch]$CaptionsOff,

    # sandbox-lab lane follow-up D: arbitrary environment-variable
    # injection into the CivicCastSupervisor service's own per-service
    # Environment REG_MULTI_SZ -- and therefore into every GStreamer
    # egress worker, which inherits the daemon's process environment
    # wholesale (civiccast/egress/gst/strategy.py's
    # _default_worker_launcher: `env = {key: value for key, value in
    # os.environ.items() if key not in ("SWAPS", "INTERVAL")}`, passed
    # straight to subprocess.Popen). Accepts either a single ';'-separated
    # string ("NAME=VALUE;NAME2=VALUE2") or an array of one-pair-per-
    # element strings (@('A=1','B=2')) -- see WorkerEnv.ps1's own header
    # for why both shapes parse identically once PowerShell's own
    # `[string[]]` coercion is accounted for. An empty VALUE ("NAME=") is
    # the explicit unset/remove form -- see WorkerEnv.ps1 and
    # civiccast/captions/tap.py:67-73's own empty-string-is-absent
    # handling for CIVICCAST_CAPTION_TAP_DIR specifically (this lane does
    # not assume every variable shares that fallback, hence a real
    # removal rather than writing an empty string). Merged into the SAME
    # Stop-Service/Start-Service cycle as -SeamlessReload (one restart
    # total, never two) and verified the same way that flag already is --
    # per-entry results recorded as worker_env_requested/
    # worker_env_verified in SOAK-START.json and VERDICT.json; an
    # unverified entry is HARNESS_ERROR, exactly like -SeamlessReload and
    # -CaptionsOff (never an unconfirmed premise of a PASS/FAIL verdict
    # for a flag the operator explicitly asked to test).
    [string[]]$WorkerEnv
)

$ErrorActionPreference = 'Continue'

# Round-2 run-2 finding: EVERY asset upload failed in 15ms with a bare
# "status= body=" -- transcript line 44 showed the real cause, dropped by
# the earlier catch block: TerminatingError(New-Object):
# "Cannot find type [System.Net.Http.HttpClientHandler]: verify that the
# assembly containing this type is loaded." Windows PowerShell 5.1 does NOT
# auto-load System.Net.Http the way a .NET Framework app referencing it in
# a project file would -- Add-Type must run first, at script scope, before
# ANY New-Object System.Net.Http.* call (Invoke-AssetUpload's own
# Add-Type call, previously placed just above its function definition, was
# lost in an earlier rewrite of this file). Run-SandboxSoak.ps1's -DryRun
# now also shells out to `powershell.exe` (the same engine as the guest) to
# instantiate HttpClientHandler as a pre-launch self-check for exactly this
# class of error.
Add-Type -AssemblyName System.Net.Http

# --------------------------------------------------------------------------
# VSMB-SAFE OUTPUT ARCHITECTURE. $LocalDir is a real local disk the VM fully
# owns -- every write this script makes (transcript, summary.json, cycles,
# rollups, phase markers, VERDICT.json/.txt) lands there and can never wedge
# on the shared VSMB transport. $ShipDir is the host-mapped folder; a
# separate, disposable shipper process (spawned below, never Start-Job --
# see the watchdog comment for why) mirrors $LocalDir -> $ShipDir on a fixed
# tick via a fresh, bounded robocopy.exe child each time, so a single wedged
# tick costs that tick and nothing else. This script's own execution thread
# touches $ShipDir directly exactly ONCE, at the very end (Invoke-FinalFlush),
# and that one call is itself bounded.
# --------------------------------------------------------------------------
$KitDir     = 'C:\CivicCastKit'
$LocalDir   = 'C:\CivicCastSoakLocal'
$ShipDir    = 'C:\CivicCastSoakOutput'
$InstallDir = 'C:\CivicCastSoakInstall'
$Base       = 'http://127.0.0.1:8000'
$RunStart   = Get-Date

# Round-2 finding 6 (LOW): the ONE list of candidate egress work-dir paths.
# Copy-StationLogs and Update-WorkerStdoutCounters (item 2's worker-stdout
# reader) each used to hardcode their OWN separate copy of this same
# literal path -- a future path change would need editing in two places
# and could silently drift between them. Both now resolve
# (Test-Path-first-match, at CALL time, never cached) against this one
# array.
$script:EgressWorkDirCandidates = @('C:\ProgramData\CivicCast\data\egress')

# Bounds (minutes). The host's Run-SandboxSoak.ps1 uses the SAME defaults
# for its own phase deadlines -- keep these two files in sync if either
# changes; see that script's -InstallBoundMinutes/-HealthBoundMinutes.
$InstallBoundMinutes = 20
$HealthBoundMinutes  = 10
# Generous setup-phase grace (first-admin + asset upload + schedule/commit +
# channel config/start + ON_AIR poll) folded into the watchdog's pre-soak
# bound below; not separately enforced against the host since the host's
# own generic quiet-share liveness check (soak-log.txt/summary.json mtime)
# already covers this phase.
$SetupGraceMinutes = 15
$PreSoakMaxMinutes = $InstallBoundMinutes + $HealthBoundMinutes + $SetupGraceMinutes

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null
foreach ($sub in 'cycles', 'rollups', 'logs') {
    New-Item -ItemType Directory -Force -Path (Join-Path $LocalDir $sub) | Out-Null
}

Start-Transcript -Path (Join-Path $LocalDir 'sandbox-soak-transcript.log') -Force | Out-Null

function Write-SoakLog {
    param([string]$Message)
    $line = "$((Get-Date).ToUniversalTime().ToString('o')) $Message"
    Add-Content -Path (Join-Path $LocalDir 'soak-log.txt') -Value $line -Encoding UTF8
    Write-Host $line
}

function Save-Json {
    param([object]$Obj, [string]$Path)
    try {
        ($Obj | ConvertTo-Json -Depth 12) | Set-Content -Path $Path -Encoding UTF8
    } catch {
        Write-SoakLog "Save-Json FAILED for $Path : $_"
    }
}

# Bounded child-process runner: Start-Process (never Wait-Job/Start-Job --
# In-Sandbox-Report.ps1 documents a real System.OutOfMemoryException hit
# loading PSWorkflow/PSScheduledJob module type data the moment Start-Job
# was invoked under this VM's memory pressure), cache .Handle IMMEDIATELY
# (PS 5.1: .ExitCode reads back $null forever unless a handle was open
# before the process transitioned to exited -- memory:
# ps51-passthru-exitcode-null.md, and AUTORUN-3.ps1's Test-TsProof uses the
# same fix), then WaitForExit with an explicit timeout so nothing here can
# hang indefinitely.
function Invoke-BoundedProcess {
    param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds = 60)
    $result = [ordered]@{ started = $false; exited = $false; exit_code = $null; elapsed_seconds = $null; error = $null }
    $startedAt = Get-Date
    try {
        $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden -ErrorAction Stop
        $result.started = $true
        $null = $p.Handle
        $exited = $p.WaitForExit($TimeoutSeconds * 1000)
        $result.exited = $exited
        if ($exited) {
            $p.Refresh()
            $result.exit_code = $p.ExitCode
        } else {
            $result.error = "did not exit within ${TimeoutSeconds}s -- killing pid $($p.Id)"
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
    } catch {
        $result.error = "$_"
    }
    $result.elapsed_seconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    return $result
}

# Same bounded-process contract as Invoke-BoundedProcess (cache .Handle
# immediately, PS 5.1 ExitCode fix), but polls WaitForExit in
# $HeartbeatSeconds slices instead of one long blocking wait so the caller
# can log progress. MEASURED NEED, not speculative: the first real run's
# soak-log.txt went silent for the installer's entire 13m05s (05:02:30 ->
# 05:15:35, exit 0) with a single blocking Wait -- the host's generic
# liveness check (mtime of soak-log.txt) had nothing to look at for that
# whole window. Used for the installer specifically; tsp.exe and the
# shipper/watchdog's own robocopy ticks are all short enough that a single
# bounded wait is fine.
function Invoke-BoundedProcessWithHeartbeat {
    param(
        [string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutSeconds,
        [int]$HeartbeatSeconds = 60, [scriptblock]$OnHeartbeat = $null
    )
    $result = [ordered]@{ started = $false; exited = $false; exit_code = $null; elapsed_seconds = $null; error = $null }
    $startedAt = Get-Date
    try {
        $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden -ErrorAction Stop
        $result.started = $true
        $null = $p.Handle
        $exited = $false
        $deadline = $startedAt.AddSeconds($TimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if ($p.WaitForExit($HeartbeatSeconds * 1000)) { $exited = $true; break }
            $elapsedNow = [int](((Get-Date) - $startedAt).TotalSeconds)
            if ($OnHeartbeat) { try { & $OnHeartbeat $elapsedNow } catch { } }
        }
        $result.exited = $exited
        if ($exited) {
            $p.Refresh()
            $result.exit_code = $p.ExitCode
        } else {
            $result.error = "did not exit within ${TimeoutSeconds}s -- killing pid $($p.Id)"
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
    } catch {
        $result.error = "$_"
    }
    $result.elapsed_seconds = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    return $result
}

function Invoke-FinalFlush {
    <#
      The ONE place this script's own thread touches the mapped folder
      directly -- a single bounded robocopy mirror, called right before
      every exit path (success or fail-fast). Bounded so it can never
      reproduce the exact wedge this architecture exists to avoid.

      Round-3(d): robocopy's own exit-code contract is NOT the usual
      0=success. Per `robocopy /?`: 0 = no files copied (nothing to do), 1
      = files copied successfully, 2 = extra files/dirs detected, 3 = 1+2,
      up through 7 (1+2+4) -- ALL OF 0-7 are success. Only >= 8 indicates a
      real failure (8 = mismatches, 16 = fatal error). The previous log
      line printed the raw exit_code with no interpretation, so a
      completely healthy final flush that copied files (exit 1) read in
      the log exactly like a real failure would.
    #>
    param([int]$TimeoutSeconds = 120)
    $r = Invoke-BoundedProcess -FilePath 'robocopy.exe' -ArgumentList @(
        $LocalDir, $ShipDir, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
    ) -TimeoutSeconds $TimeoutSeconds
    $robocopyOk = $r.exited -and ($null -ne $r.exit_code) -and ([int]$r.exit_code -lt 8)
    Write-SoakLog "final flush to $ShipDir : started=$($r.started) exited=$($r.exited) exit_code=$($r.exit_code) (robocopy: $(if ($robocopyOk) { 'SUCCESS, <8' } else { 'FAILURE, >=8 or never exited' })) elapsed=$($r.elapsed_seconds)s error=$($r.error)"
    return $robocopyOk
}

function Invoke-GuestShutdown {
    <#
      Round-3(c): the sandbox VM does NOT tear itself down when the
      LogonCommand script exits -- confirmed directly on run 2:
      WindowsSandboxRemoteSession/WindowsSandboxServer/vmmemWindowsSandbox
      were all still alive after VERDICT.txt was written, and
      Run-SandboxSoak.ps1's own "still shutting down, not force-closing"
      grace-window log line was papering over a VM that was never actually
      shutting down at all. The guest must ask the GUEST OS itself to power
      off -- `shutdown.exe /s /t 5` schedules a shutdown 5s out (enough
      time for this process's own `exit` to complete first) rather than
      blocking on it, so it can never turn into one more thing this script
      hangs waiting for. Non-fatal: if it fails, Run-SandboxSoak.ps1's own
      bounded wait-then-kill (by recorded PID only) is the backstop.
    #>
    try {
        Write-SoakLog "requesting guest OS shutdown (shutdown.exe /s /t 5)"
        & shutdown.exe /s /t 5 /c "CivicCast sandbox soak lane: run complete" 2>&1 | Out-Null
    } catch {
        Write-SoakLog "guest shutdown request failed (non-fatal -- Run-SandboxSoak.ps1's own PID-bounded kill is the backstop): $_"
    }
}

function Write-PhaseMarker {
    param([string]$Name, [object]$Obj)
    Save-Json -Obj $Obj -Path (Join-Path $LocalDir $Name)
    Write-SoakLog "phase marker written: $Name"
}

# Round-2 finding 5 (LOW): set $true right after SOAK-START.json is
# actually written (section 4, once all channels confirm ON_AIR) -- read by
# Write-HarnessErrorVerdictAndExit below so a harness error that fires
# BEFORE that point (every current call site does; kept as a real guard,
# not a dead check, in case a future call site is ever added after it)
# still leaves a SOAK-START.json on disk for any downstream tooling that
# expects one on every run, not only on runs that got far enough to reach
# the real one.
$script:soakStartWritten = $false

function Write-FailVerdictAndExit {
    <#
      Every early-exit path funnels through here: record the reason, copy
      what station logs exist, write a fail-closed VERDICT.json/.txt, force
      a final flush to the host, stop the transcript, exit.
    #>
    param([string]$Reason, [int]$ExitCode = 1)
    $summary.error = $Reason
    Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'FAIL'; reason = $Reason; first_failing_cycle = $null
        cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0; soak_start_utc = $null
        # Round-7: carry whatever per-channel timing was captured before the
        # fail, if this fail path ran after the ON_AIR poll (e.g. the
        # not-all-ON_AIR timeout) -- $null (never an error) if the fail
        # happened earlier and these variables don't exist yet.
        first_state_row_s = $firstStateRowSByChannel
        time_to_on_air_s  = $timeToOnAirSByChannel
    }
    Save-Json -Obj $verdict -Path (Join-Path $LocalDir 'VERDICT.json')
    "verdict=FAIL reason=$Reason" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
    Write-SoakLog "FAIL: $Reason"
    Invoke-FinalFlush
    Stop-Transcript | Out-Null
    Invoke-GuestShutdown
    exit $ExitCode
}

function Write-HarnessErrorVerdictAndExit {
    <#
      N9: distinct from Write-FailVerdictAndExit -- this is for a setup
      problem THIS SCRIPT can positively diagnose as a harness/scheduling
      defect (e.g. insufficient schedule coverage for the requested
      -Minutes), never a product defect. verdict=HARNESS_ERROR in
      VERDICT.txt/.json, which Run-SandboxSoak.ps1 reports as exit 6, the
      same code its own quiet-share detector uses -- both mean "no product
      conclusion can be drawn from this run."

      Round-2 finding 5 (LOW): two additions --
      (1) the caption fields (captions_off_requested/captions_enabled/
      captions_off_verified) now ride along in VERDICT.json here too, same
      as the success-path VERDICT.json already carries -- $null when
      $summary itself does not exist yet (this function is called before
      $summary's own init, which no current call site does, but the guard
      costs nothing and keeps this function correct if one ever is), never
      guessed;
      (2) if SOAK-START.json was never written (every current
      harness-error call site fires before section 4's ON_AIR
      confirmation, i.e. always, today), write a minimal one HERE so
      downstream tooling that expects a SOAK-START.json on every run
      finds one even on a run that failed before reaching the real one --
      explicitly marked so it is never mistaken for the real,
      clock-started one.
    #>
    param([string]$Reason, [int]$ExitCode = 1)
    $capOffRequested = $(if ($summary) { $summary.captions_off_requested } else { $null })
    $capEnabled      = $(if ($summary) { $summary.captions_enabled } else { $null })
    $capOffVerified  = $(if ($summary) { $summary.captions_off_verified } else { $null })
    # sandbox-lab lane follow-up D: same never-guessed, $null-before-init
    # guard as the caption fields just above.
    $workerEnvReq = $(if ($summary) { $summary.worker_env_requested } else { $null })
    $workerEnvVer = $(if ($summary) { $summary.worker_env_verified } else { $null })
    if ($summary) {
        $summary.error = $Reason
        Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')
    }
    Copy-StationLogs -Label 'final'
    if (-not $script:soakStartWritten) {
        Write-PhaseMarker -Name 'SOAK-START.json' -Obj ([ordered]@{
            soak_start_utc = $null
            harness_error_before_soak_start = $true
            captions_off_requested = $capOffRequested
            captions_enabled       = $capEnabled
            captions_off_verified  = $capOffVerified
            worker_env_requested   = $workerEnvReq
            worker_env_verified    = $workerEnvVer
        })
        $script:soakStartWritten = $true
    }
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'HARNESS_ERROR'; reason = $Reason; first_failing_cycle = $null
        cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0; soak_start_utc = $null
        captions_off_requested = $capOffRequested
        captions_enabled       = $capEnabled
        captions_off_verified  = $capOffVerified
        worker_env_requested   = $workerEnvReq
        worker_env_verified    = $workerEnvVer
    }
    Save-Json -Obj $verdict -Path (Join-Path $LocalDir 'VERDICT.json')
    "verdict=HARNESS_ERROR reason=$Reason" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
    Write-SoakLog "HARNESS_ERROR: $Reason"
    Invoke-FinalFlush
    Stop-Transcript | Out-Null
    Invoke-GuestShutdown
    exit $ExitCode
}

# --------------------------------------------------------------------------
# Shipper: a persistent supervisor process that mirrors $LocalDir -> $ShipDir
# on a fixed tick via a fresh, bounded robocopy.exe child each time. It dies
# with the VM at teardown; it also stops on its own once
# _SHIP-STOP.marker appears (written just before Invoke-FinalFlush's own
# direct call, purely for tidiness -- Invoke-FinalFlush does not depend on
# the shipper having stopped).
# --------------------------------------------------------------------------
try {
    $shipperScript = @'
param([string]$LocalDir, [string]$ShipDir, [int]$IntervalSeconds = 15, [int]$TickTimeoutSeconds = 45)
$stopMarker = Join-Path $LocalDir '_SHIP-STOP.marker'
# N11: track the PID of any tick this loop force-killed for timing out.
# Stop-Process is fire-and-forget -- it does not itself guarantee the
# process is actually gone by the time it returns (a process wedged deep
# enough on a stuck I/O syscall can be uninterruptible for a stretch). If a
# "killed" child is confirmed still alive on the NEXT iteration, skip
# spawning a new one entirely this tick rather than risk two robocopy
# processes racing against the same $LocalDir/$ShipDir tree -- retry the
# kill instead and let the following ticks keep trying.
$pendingKillPid = $null
while ($true) {
    if (Test-Path $stopMarker) { break }
    try {
        "shipper_tick_utc=$((Get-Date).ToUniversalTime().ToString('o'))" |
            Set-Content -Path (Join-Path $LocalDir '_SHIPPER-HEARTBEAT.txt') -Encoding UTF8
    } catch { }

    $stillWedged = $false
    if ($pendingKillPid) {
        $still = $null
        try { $still = Get-Process -Id $pendingKillPid -ErrorAction Stop } catch { $still = $null }
        if ($still) {
            $stillWedged = $true
            try { Stop-Process -Id $pendingKillPid -Force -ErrorAction SilentlyContinue } catch { }
        } else {
            $pendingKillPid = $null
        }
    }

    if (-not $stillWedged) {
        try {
            $p = Start-Process -FilePath 'robocopy.exe' -ArgumentList @(
                $LocalDir, $ShipDir, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
            ) -PassThru -WindowStyle Hidden -ErrorAction Stop
            $null = $p.Handle
            if (-not $p.WaitForExit($TickTimeoutSeconds * 1000)) {
                try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
                $pendingKillPid = $p.Id
            }
        } catch { }
    }

    if (Test-Path $stopMarker) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
'@
    $shipperPath = Join-Path $env:TEMP 'civiccast-soak-shipper.ps1'
    Set-Content -Path $shipperPath -Value $shipperScript -Encoding UTF8
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$shipperPath`"",
        '-LocalDir', "`"$LocalDir`"", '-ShipDir', "`"$ShipDir`""
    ) -WindowStyle Hidden | Out-Null
    Write-SoakLog "shipper spawned (mirrors $LocalDir -> $ShipDir every 15s)"
} catch {
    Write-SoakLog "shipper spawn failed (non-fatal, but the host will see nothing until Invoke-FinalFlush at the very end): $_"
}

# --------------------------------------------------------------------------
# Watchdog: a genuinely separate powershell.exe process (NOT Start-Job, same
# OOM-avoidance reason as above). Two phases so it fires at the RIGHT
# deadline instead of a launch-relative one that has nothing to do with how
# long setup actually took:
#   Phase A (pre-soak): if SOAK-START.json never appears within
#     $PreSoakMaxMinutes of THIS watchdog's own launch (a proxy for script
#     launch -- it is spawned within the first few statements), the soak
#     clock never started at all -- write a fail-closed VERDICT.
#   Phase B (post-soak): once SOAK-START.json appears, recompute the
#     deadline as soak_start_utc + Minutes + 10 (read from the marker's own
#     content, not the watchdog's launch time) and wait for VERDICT.json.
# Both phases read/write ONLY $LocalDir.
# --------------------------------------------------------------------------
try {
    $watchdogScript = @'
param([string]$LocalDir, [int]$Minutes, [int]$PreSoakMaxMinutes)
$donePath = Join-Path $LocalDir 'VERDICT.json'
$soakStartPath = Join-Path $LocalDir 'SOAK-START.json'
$launchTime = Get-Date

$preSoakDeadline = $launchTime.AddMinutes($PreSoakMaxMinutes)
while ((Get-Date) -lt $preSoakDeadline) {
    if (Test-Path $donePath) { exit 0 }
    if (Test-Path $soakStartPath) { break }
    Start-Sleep -Seconds 20
}
if (Test-Path $donePath) { exit 0 }
if (-not (Test-Path $soakStartPath)) {
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    "watchdog_fired_utc=$ts phase=pre-soak reason=SOAK-START.json not present after ${PreSoakMaxMinutes}m -- install/health/setup presumed hung" |
        Set-Content -Path (Join-Path $LocalDir 'WATCHDOG-TIMEOUT.txt') -Encoding UTF8
    # Round-8 finding 5: a watchdog timeout is a HARNESS condition -- the
    # main script hung or died, which says nothing about the product --
    # never a product FAIL.
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'HARNESS_ERROR'
        reason = 'in-sandbox watchdog fired before the soak clock ever started (install/health/setup presumed hung)'
        first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        watchdog_timeout = $true; watchdog_phase = 'pre-soak'; done_utc = $ts; soak_start_utc = $null
    }
    ($verdict | ConvertTo-Json -Depth 6) | Set-Content -Path $donePath -Encoding UTF8
    "verdict=HARNESS_ERROR (watchdog timeout, pre-soak) reason=see WATCHDOG-TIMEOUT.txt" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
    exit 0
}

$soakStartUtc = (Get-Date).ToUniversalTime()
try {
    $soakStartObj = Get-Content -Path $soakStartPath -Raw | ConvertFrom-Json
    $soakStartUtc = [datetime]::Parse($soakStartObj.soak_start_utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
} catch { }
$postSoakDeadlineUtc = $soakStartUtc.AddMinutes($Minutes + 10)

while ((Get-Date).ToUniversalTime() -lt $postSoakDeadlineUtc) {
    if (Test-Path $donePath) { exit 0 }
    Start-Sleep -Seconds 20
}
if (-not (Test-Path $donePath)) {
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    "watchdog_fired_utc=$ts phase=post-soak reason=VERDICT.json not present by soak_start_utc($($soakStartUtc.ToString('o')))+Minutes($Minutes)+10" |
        Set-Content -Path (Join-Path $LocalDir 'WATCHDOG-TIMEOUT.txt') -Encoding UTF8
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'HARNESS_ERROR'
        reason = 'in-sandbox watchdog fired -- main script did not complete within soak_start_utc + Minutes + 10'
        first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        watchdog_timeout = $true; watchdog_phase = 'post-soak'; done_utc = $ts; soak_start_utc = $soakStartUtc.ToString('o')
    }
    ($verdict | ConvertTo-Json -Depth 6) | Set-Content -Path $donePath -Encoding UTF8
    "verdict=HARNESS_ERROR (watchdog timeout, post-soak) reason=see WATCHDOG-TIMEOUT.txt" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
}
'@
    $watchdogPath = Join-Path $env:TEMP 'civiccast-soak-watchdog.ps1'
    Set-Content -Path $watchdogPath -Value $watchdogScript -Encoding UTF8
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watchdogPath`"",
        '-LocalDir', "`"$LocalDir`"", '-Minutes', $Minutes, '-PreSoakMaxMinutes', $PreSoakMaxMinutes
    ) -WindowStyle Hidden | Out-Null
    Write-SoakLog "watchdog spawned (pre-soak bound=${PreSoakMaxMinutes}m; post-soak bound=soak_start_utc+Minutes(${Minutes})+10m)"
} catch {
    Write-SoakLog "watchdog spawn failed (non-fatal): $_"
}

# sandbox-lab lane follow-up D, item 2 (round-3 review): Copy-GstDebugTail
# now lives in its own dot-sourceable file, GstDebugTail.ps1, matching this
# project's established extraction pattern (ServiceStartFailureCheck.ps1/
# CaptionsOffCheck.ps1/WorkerStdoutParser.ps1/CpuSampler.ps1/WorkerEnv.ps1)
# so it is unit-testable (Test-GstDebugTail.ps1) against real temp files/
# streams -- including a file held open for write by another process and
# a file that grows mid-copy -- instead of only ever being exercised
# inside a live sandbox soak. See that file's own header for the
# live-open-file share-mode fix, the growing-file bound fix, and the
# banner/naming fix.
. (Join-Path 'C:\CivicCastSoakScripts' 'GstDebugTail.ps1')

function Copy-StationLogs {
    <#
      Copies the station's daemon/worker/install logs, installer-state.json,
      station-set.json, and (round-4 item 2) the PER-CHANNEL egress worker
      logs into $LocalDir\logs (the shipper mirrors it out from there).
      Called at the end, on EVERY FAIL path (via Write-FailVerdictAndExit /
      Write-HarnessErrorVerdictAndExit), and every 3 minutes during the soak
      loop, so a hung sandbox still leaves partial evidence on the host.

      Round-4 finding: run 4's evidence had ONLY C:\ProgramData\CivicCast\
      logs\* (the daemon-level log, which just says "issued start" / "TS
      relay up") -- never the per-channel egress worker's own logs, which
      civiccast/egress/gst/strategy.py:748 places OUTSIDE that tree, at
      <egress_work_dir>\<channel_id>\logs\ (egress_work_dir defaults to
      C:\ProgramData\CivicCast\data\egress -- children.py's
      default_egress_work_dir). That is exactly where a worker's own
      startup failure/traceback would actually be. Ported from
      In-Sandbox-Report.ps1:1369-1400's Invoke-StationDiagCapture (Gate A's
      own T4 fix for the identical gap), narrowed the same way: robocopy
      ONLY <channel>\logs with a *.log filter, never the sibling media/
      segment artifacts in the same work dir. Also copies each channel's
      small top-level JSON state (playout-graph.json, compliance-last.json,
      compliance-report.json -- civiccast/egress/gst/strategy.py:745,
      civiccast/egress/compliance.py:459/567) and writes a DIRECTORY
      LISTING (never a copy -- prepared\ holds transcoded media, easily
      hundreds of MB per clip) of <channel>\prepared\.

      TARGETED, bounded candidate paths only throughout -- no full-tree
      recursive scan over the install directory (In-Sandbox-Report.ps1:18-28's
      HARDENED note: a full `Get-ChildItem -Recurse` over a multi-thousand-
      file install tree is exactly the kind of thing that is fast on a real
      disk and can take minutes on Windows Sandbox's virtualized/
      differencing storage).
    #>
    param([string]$Label)
    $dst = Join-Path $LocalDir "logs\$Label"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    $candidates = @(
        (Join-Path $InstallDir 'install-progress.log'),
        (Join-Path $InstallDir 'installer-state.json'),
        'C:\ProgramData\CivicCast\installer-state.json',
        (Join-Path $InstallDir 'station-set.json'),
        (Join-Path $InstallDir 'app\station-set.json'),
        'C:\ProgramData\CivicCast\station-set.json',
        'C:\ProgramData\CivicCast\logs',
        (Join-Path $InstallDir 'logs')
    )
    foreach ($c in $candidates) {
        try {
            if (Test-Path $c -PathType Leaf) {
                Copy-Item -LiteralPath $c -Destination $dst -Force -ErrorAction SilentlyContinue
            } elseif (Test-Path $c -PathType Container) {
                & robocopy.exe $c (Join-Path $dst (Split-Path -Leaf $c)) /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
            }
        } catch { }
    }

    # Round-2 finding 6: shared candidate list -- see its own declaration
    # near the top of this file.
    $egressWorkDirCandidates = $script:EgressWorkDirCandidates
    $egressSrc = $egressWorkDirCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    $egressNote = Join-Path $dst 'egress-work-dir-note.txt'
    if (-not $egressSrc) {
        "egress work dir not present under any of: $($egressWorkDirCandidates -join ', ')" | Set-Content -Path $egressNote -Encoding UTF8
        return
    }
    "egress work dir: $egressSrc" | Set-Content -Path $egressNote -Encoding UTF8
    $egressDst = Join-Path $dst 'egress-per-channel'
    New-Item -ItemType Directory -Force -Path $egressDst | Out-Null
    $channelDirs = @(Get-ChildItem -LiteralPath $egressSrc -Directory -ErrorAction SilentlyContinue)
    if ($channelDirs.Count -eq 0) {
        "no per-channel subdirectories under $egressSrc" | Add-Content -Path $egressNote -Encoding UTF8
    }
    foreach ($cd in $channelDirs) {
        $channelName = $cd.Name
        $chDst = Join-Path $egressDst $channelName
        New-Item -ItemType Directory -Force -Path $chDst | Out-Null

        $logsSrc = Join-Path $cd.FullName 'logs'
        if (Test-Path $logsSrc) {
            & robocopy.exe $logsSrc (Join-Path $chDst 'logs') '*.log' /S /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
        } else {
            "no logs\ under $($cd.FullName)" | Add-Content -Path $egressNote -Encoding UTF8
        }

        foreach ($stateFile in @('playout-graph.json', 'compliance-last.json', 'compliance-report.json')) {
            $sfPath = Join-Path $cd.FullName $stateFile
            if (Test-Path $sfPath -PathType Leaf) {
                Copy-Item -LiteralPath $sfPath -Destination (Join-Path $chDst $stateFile) -Force -ErrorAction SilentlyContinue
            }
        }

        # Listing only, NEVER a copy -- prepared\ holds transcoded media
        # (easily hundreds of MB per clip); the point is to see WHAT was
        # prepared and WHEN, not to duplicate it into evidence.
        $preparedSrc = Join-Path $cd.FullName 'prepared'
        if (Test-Path $preparedSrc) {
            try {
                Get-ChildItem -LiteralPath $preparedSrc -File -ErrorAction SilentlyContinue |
                    Select-Object Name, Length, LastWriteTimeUtc |
                    ConvertTo-Json -Depth 3 |
                    Set-Content -Path (Join-Path $chDst 'prepared-listing.json') -Encoding UTF8
            } catch { }
        }
    }

    # Round-15 finding (b): run 11 (candidate 3b, -SeamlessReload) timed out
    # at 12 minutes with NO state row on any channel and only the
    # "education" channel's directory + conform-cache present under the
    # egress work dir -- the per-channel loop just above only ever sees a
    # channel that ALREADY has a directory under $egressSrc, so a channel
    # whose conform/prepare work hadn't created one yet was invisible to
    # this evidence capture entirely, and there was no way to tell from the
    # captured evidence whether conform was still actively running or had
    # simply stalled. Captured HERE (unconditional -- every known channel
    # from $channelSpecs is listed even if its directory does not exist
    # yet, reported as such, rather than silently absent) into
    # logs\<label>\conform-progress.json:
    #   - a (name, size, mtime) listing of the GLOBAL conform-cache dir
    #     (shared across all channels, civiccast/egress -- conform results
    #     are cached once and reused, so this is the one place to see
    #     whether ANY conform work is landing at all);
    #   - the SAME per-channel prepared\ listing as above, but for every
    #     channel this script knows about (not just ones whose directory
    #     happens to already exist), each stamped with whether its
    #     directory was even present;
    #   - a Win32_Process snapshot of every ffmpeg.exe/python.exe child
    #     (CommandLine + CreationDate) -- if conform is still running, its
    #     process (and command line, which names the source/output paths)
    #     should show up here even when nothing has landed on disk yet.
    $conformProgress = [ordered]@{
        captured_utc = (Get-Date).ToUniversalTime().ToString('o')
        conform_cache = $null
        channels = @()
        processes = @()
    }
    $conformCacheSrc = Join-Path $egressSrc 'conform-cache'
    if (Test-Path $conformCacheSrc) {
        try {
            $conformProgress.conform_cache = @(Get-ChildItem -LiteralPath $conformCacheSrc -Recurse -File -ErrorAction SilentlyContinue |
                Select-Object Name, @{n = 'FullPath'; e = { $_.FullName } }, Length, LastWriteTimeUtc)
        } catch { $conformProgress.conform_cache = "error listing $($conformCacheSrc): $_" }
    } else {
        $conformProgress.conform_cache = "not present: $conformCacheSrc"
    }
    foreach ($cs in @($channelSpecs)) {
        $chDir = Join-Path $egressSrc $cs.id
        $chPreparedSrc = Join-Path $chDir 'prepared'
        $chEntry = [ordered]@{ channel_id = $cs.id; channel_dir_present = (Test-Path $chDir); prepared = $null }
        if (Test-Path $chPreparedSrc) {
            try {
                $chEntry.prepared = @(Get-ChildItem -LiteralPath $chPreparedSrc -File -ErrorAction SilentlyContinue |
                    Select-Object Name, Length, LastWriteTimeUtc)
            } catch { $chEntry.prepared = "error listing $($chPreparedSrc): $_" }
        } else {
            $chEntry.prepared = "not present: $chPreparedSrc"
        }
        $conformProgress.channels += $chEntry
    }
    try {
        $conformProgress.processes = @(Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
            Select-Object ProcessId, Name, CommandLine, CreationDate)
    } catch { $conformProgress.processes = "error querying Win32_Process: $_" }
    try {
        $conformProgress | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $dst 'conform-progress.json') -Encoding UTF8
    } catch { }

    # sandbox-lab lane follow-up D, item 2: when -WorkerEnv set GST_DEBUG_FILE
    # (see $script:GstDebugFilePath, resolved once near the top of this
    # file), copy that file AND any rotated/sibling *.gstdebug files
    # sitting in the same directory into this checkpoint's own
    # gst-debug\ subfolder -- called on every Copy-StationLogs invocation
    # (every checkpoint-cycleN AND 'final'), same as the rest of this
    # function, so a mid-soak GStreamer debug log is visible in the
    # evidence trail even if the run never reaches 'final'. GST_DEBUG at
    # level 4 across four elements for a whole soak can grow large fast,
    # and this evidence capture must never itself become the thing that
    # stalls a checkpoint OR flood the host with gigabytes of shipped
    # evidence -- see Get-GstDebugCaptureDecision (GstDebugTail.ps1,
    # round-4/round-5 review findings) for the gating/split-budget rules
    # applied just below, and Copy-GstDebugTail's own header for the
    # tail-copy mechanics (live-open-file share mode, growing-file bound,
    # banner-only-when-truncated).
    $gstDebugDst = Join-Path $dst 'gst-debug'
    $gstDebugNote = Join-Path $dst 'gst-debug-note.txt'
    if (-not $script:GstDebugFilePath) {
        "GST_DEBUG_FILE was not requested via -WorkerEnv for this run -- nothing to capture" | Set-Content -Path $gstDebugNote -Encoding UTF8
    } else {
        $gstDebugMaxBytes = 200MB
        $isPeriodicCheckpoint = ($Label -match '^checkpoint-cycle\d+$')
        if ($isPeriodicCheckpoint) { $script:GstDebugPeriodicCheckpointCount++ }
        $captureDecision = Get-GstDebugCaptureDecision `
            -IsPeriodicCheckpoint $isPeriodicCheckpoint `
            -PeriodicCheckpointIndex $script:GstDebugPeriodicCheckpointCount `
            -EveryN $GstDebugCaptureEveryN `
            -PeriodicBytesSoFar $script:GstDebugPeriodicBytesCopied `
            -PeriodicCapBytes $GstDebugPeriodicCapBytes `
            -NonPeriodicBytesSoFar $script:GstDebugNonPeriodicBytesCopied `
            -NonPeriodicCapBytes $GstDebugNonPeriodicCapBytes

        if (-not $captureDecision.should_capture) {
            "SKIPPED for label '$Label': $($captureDecision.reason) (periodic so far: $([math]::Round($script:GstDebugPeriodicBytesCopied / 1MB, 1)) MB of a $([math]::Round($GstDebugPeriodicCapBytes / 1MB, 0)) MB cap; non-periodic so far: $([math]::Round($script:GstDebugNonPeriodicBytesCopied / 1MB, 1)) MB of a $([math]::Round($GstDebugNonPeriodicCapBytes / 1MB, 0)) MB reserve)" | Set-Content -Path $gstDebugNote -Encoding UTF8
        } else {
            $gstDebugDir = Split-Path -Parent $script:GstDebugFilePath
            $gstDebugBaseName = Split-Path -Leaf $script:GstDebugFilePath
            $gstDebugNoteLines = @(
                "GST_DEBUG_FILE requested: $($script:GstDebugFilePath)"
                "capture reason: $($captureDecision.reason)"
            )
            if (-not (Test-Path $gstDebugDir)) {
                $gstDebugNoteLines += "directory does not exist (yet): $gstDebugDir"
            } else {
                # Candidates come from TWO independent, deliberately separate
                # rules, never a blind directory-wide sweep: (1) the primary
                # file plus GStreamer's own rotation convention (a numeric/
                # backup suffix appended to the base name), matched by PREFIX
                # against the requested base name; and (2) any file with a
                # `.gstdebug` extension in this same directory, matched by
                # EXTENSION ALONE -- NOT gated on the base-name prefix at all.
                # Rule (2) is a deliberately wider net (the accepted risk: a
                # stray, unrelated `.gstdebug` file some other tool dropped in
                # this exact directory would also be swept), because this is a
                # directory THIS RUN itself created for its own GST_DEBUG_FILE
                # (see the New-Item -Force call at this run's own registry-
                # write step) -- something else writing into it is already
                # unexpected enough that surfacing it as evidence is more
                # useful than silently excluding it.
                $gstCandidates = @(
                    Get-ChildItem -LiteralPath $gstDebugDir -File -ErrorAction SilentlyContinue |
                        Where-Object { $_.Name -eq $gstDebugBaseName -or $_.Name -like "$gstDebugBaseName*" -or $_.Extension -eq '.gstdebug' }
                )
                if ($gstCandidates.Count -eq 0) {
                    $gstDebugNoteLines += "directory exists but no matching file(s) found yet: $gstDebugDir (looked for '$gstDebugBaseName', '$gstDebugBaseName*', and '*.gstdebug')"
                } else {
                    New-Item -ItemType Directory -Force -Path $gstDebugDst | Out-Null
                    # Round-4 review finding 1 (HIGH), comment corrected in
                    # round-5 review finding 7: each $f below is a
                    # [System.IO.FileInfo] populated once by the Get-ChildItem
                    # call above -- its .Length property is a SNAPSHOT taken
                    # at THAT moment; .NET does not auto-refresh it, and this
                    # code never calls .Refresh() on it either. An EARLIER
                    # version of this loop branched on that cached $f.Length
                    # to decide whether the file "needed" truncation, so by
                    # the time that branch actually ran (after whatever else
                    # happened earlier in the same checkpoint), the live
                    # GST_DEBUG_FILE could already be far larger than what
                    # $f.Length still reported (measured directly, via
                    # Test-GstDebugTail.ps1's own regression guard: a file
                    # written to 1 MB, stat'd via Get-ChildItem, then grown to
                    # 5 MB through a separate handle -- the ORIGINAL FileInfo
                    # object's own .Length stayed frozen at the 1 MB value it
                    # captured, never reflecting the grown, live size).
                    # Trusting that cached value would have routed the EXACT
                    # live file this feature exists to capture down an
                    # unbounded path. Fixed by dropping any size-based branch
                    # on $f.Length entirely: Copy-GstDebugTail is always
                    # called, and it establishes truncated-vs-whole from ITS
                    # OWN freshly opened stream's live Length, never from a
                    # FileInfo any caller might have cached earlier.
                    foreach ($f in $gstCandidates) {
                        # Round-5 review finding 1: periodic and non-periodic
                        # captures draw against SEPARATE budgets/caps -- see
                        # Get-GstDebugCaptureDecision's own header. Re-checked
                        # here too (not just once per Copy-StationLogs call)
                        # because a SINGLE checkpoint can have MULTIPLE
                        # candidate files (the primary + rotated siblings),
                        # and the budget can be exhausted partway through
                        # that same foreach.
                        $bytesSoFarForThisKind = $(if ($isPeriodicCheckpoint) { $script:GstDebugPeriodicBytesCopied } else { $script:GstDebugNonPeriodicBytesCopied })
                        $capForThisKind = $(if ($isPeriodicCheckpoint) { $GstDebugPeriodicCapBytes } else { $GstDebugNonPeriodicCapBytes })
                        $capRemaining = $capForThisKind - $bytesSoFarForThisKind
                        # Round-5 review finding 6: the cap is enforced as a
                        # HARD ceiling, not a pre-write check that can still
                        # overshoot by up to one file's worth -- the residual
                        # budget is passed through as THIS COPY's own
                        # -MaxBytes, clamped to whatever is smaller (the
                        # normal 200 MB bound, or what remains of this kind's
                        # cap). Copy-GstDebugTail itself floors -MaxBytes at
                        # 4096 bytes (round-5 finding 4) -- if the residual is
                        # smaller than that, there is no meaningful budget
                        # left at all, so this capture (and every later one
                        # of the same kind, this checkpoint) is skipped
                        # outright rather than attempting an invalid call.
                        if ($capRemaining -lt 4096) {
                            $gstDebugNoteLines += "SKIPPED $($f.Name): $(if ($isPeriodicCheckpoint) { 'periodic' } else { 'non-periodic' }) budget has less than 4 KB remaining ($([math]::Round($capRemaining / 1KB, 2)) KB) -- effectively exhausted"
                            continue
                        }
                        $effectiveMaxBytes = [Math]::Min($gstDebugMaxBytes, $capRemaining)
                        $baseName = $f.Name
                        $wholeDestPath = Join-Path $gstDebugDst $baseName
                        $truncatedDestPath = Join-Path $gstDebugDst "$baseName.tail$([math]::Round($effectiveMaxBytes / 1MB, 0))mb"
                        try {
                            $copyResult = Copy-GstDebugTail -SourcePath $f.FullName -DestPathWhole $wholeDestPath -DestPathTruncated $truncatedDestPath -MaxBytes $effectiveMaxBytes
                            if ($isPeriodicCheckpoint) { $script:GstDebugPeriodicBytesCopied += $copyResult.bytes_written } else { $script:GstDebugNonPeriodicBytesCopied += $copyResult.bytes_written }
                            $destLeaf = Split-Path -Leaf $copyResult.dest_path
                            $gstDebugNoteLines += "$($f.Name) -> $destLeaf ($(if ($copyResult.truncated) { 'TRUNCATED' } else { 'whole file, untruncated' })): wrote $([math]::Round($copyResult.bytes_written / 1MB, 2)) MB (this copy's effective bound $([math]::Round($effectiveMaxBytes / 1MB, 2)) MB; directory-entry size at listing time was $([math]::Round($f.Length / 1MB, 1)) MB -- may be stale for a live-open/growing file, never trusted for the copy bound itself). $(if ($isPeriodicCheckpoint) { 'Periodic' } else { 'Non-periodic' }) budget used so far: $([math]::Round($(if ($isPeriodicCheckpoint) { $script:GstDebugPeriodicBytesCopied } else { $script:GstDebugNonPeriodicBytesCopied }) / 1MB, 1)) MB of $([math]::Round($capForThisKind / 1MB, 0)) MB"
                        } catch {
                            $gstDebugNoteLines += "FAILED to copy $($f.Name): $_"
                        }
                    }
                }
            }
            $gstDebugNoteLines | Set-Content -Path $gstDebugNote -Encoding UTF8
        }
    }
}

# N2 (blocker): Windows Defender Firewall raises a modal "Do you want to
# allow public and private networks to access this app?" prompt the FIRST
# time tsp.exe opens a listening socket for `-I ip <port>` -- on the guest
# desktop nobody is watching, with no automated way to dismiss it, so every
# probe after it fails-zero-packets and the verdict wrongly blames the
# product. Ported near-verbatim from In-Sandbox-Report.ps1:1968-1998's
# Add-CivicCastFirewallAllowRule (Gate A's own fix for the identical
# prompt, first documented at In-Sandbox-Report.ps1:1949-1966) and called
# from Gate A at In-Sandbox-Report.ps1:3266-3268 for exactly tsp/ffmpeg/
# ffprobe -- never python.exe: Gate A's own call sites never author a rule
# for the GStreamer worker either, so this does not invent one Gate A
# itself has no evidence for. This harness runs elevated in the sandbox, so
# it can author the allow rules itself before the first bind -- called
# right after PHASE-HEALTHY, before first-admin/asset-upload/schedule/
# channel-start and before the first tsp probe.
function Add-CivicCastFirewallAllowRule {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ProgramPath
    )
    if ([string]::IsNullOrWhiteSpace($ProgramPath) -or -not (Test-Path -LiteralPath $ProgramPath)) {
        Write-SoakLog "firewall_rule name=$Name program=$ProgramPath result=SKIPPED(program-not-found)"
        return $false
    }
    $resolved = (Resolve-Path -LiteralPath $ProgramPath).ProviderPath
    $ok = $true
    try {
        & netsh.exe advfirewall firewall delete rule name="$Name" 2>&1 | Out-Null
        foreach ($direction in @('in', 'out')) {
            $out = & netsh.exe advfirewall firewall add rule name="$Name" dir=$direction action=allow program="$resolved" enable=yes profile=any 2>&1
            if ($LASTEXITCODE -ne 0) {
                $ok = $false
                Write-SoakLog "firewall_rule name=$Name dir=$direction result=FAILED exit=$LASTEXITCODE detail=$($out -join ' ')"
            }
        }
    } catch {
        $ok = $false
        Write-SoakLog "firewall_rule name=$Name result=THREW detail=$_"
    }
    if ($ok) { Write-SoakLog "firewall_rule name=$Name program=$resolved dir=in+out result=ALLOWED" }
    return $ok
}

# sandbox-lab lane follow-up D: dot-sourced here, well before the installer
# even runs, so -WorkerEnv can be validated and this run can fail fast
# (before burning the full install+health window) on a malformed value --
# same "dot-sourced before first use" convention as
# ServiceStartFailureCheck.ps1/CaptionsOffCheck.ps1/WorkerStdoutParser.ps1/
# CpuSampler.ps1 just below (all four stay dot-sourced at their existing,
# later call sites -- this one alone needs to run before section 1 because
# a parse failure here is a config problem the guest can diagnose
# immediately, not something worth discovering only after a 13+ minute
# install).
. (Join-Path 'C:\CivicCastSoakScripts' 'WorkerEnv.ps1')
$workerEnvParsed = ConvertTo-WorkerEnvEntries -WorkerEnv $WorkerEnv
$workerEnvDeduped = @(Get-DedupedWorkerEnvEntries -Entries $workerEnvParsed.entries)
$workerEnvRequestedStrings = @(Format-WorkerEnvArg -Entries $workerEnvDeduped) -split ';' | Where-Object { $_.Length -gt 0 }
$script:GstDebugFilePath = Get-GstDebugFilePath -Entries $workerEnvDeduped
# Round-4 review finding 2 (round-5 review finding 1 split this into two
# INDEPENDENT budgets -- see Get-GstDebugCaptureDecision's own header for
# why a single shared cap let periodic checkpoints starve 'final' out of
# its own evidence budget): gst-debug capture is gated and volume-capped --
# see Copy-StationLogs's own gst-debug section and GstDebugTail.ps1's
# Get-GstDebugCaptureDecision for the full rules. State tracked here
# (script scope) so it persists correctly across every Copy-StationLogs
# call for the life of this run.
$script:GstDebugPeriodicCheckpointCount = 0
$script:GstDebugPeriodicBytesCopied = 0
$script:GstDebugNonPeriodicBytesCopied = 0
$GstDebugCaptureEveryN = 10
$GstDebugPeriodicCapBytes = 400MB
$GstDebugNonPeriodicCapBytes = 200MB

# --------------------------------------------------------------------------
# 1. Locate and run the installer silently, bounded to $InstallBoundMinutes.
# --------------------------------------------------------------------------
$summary = [ordered]@{
    run_start_utc = $RunStart.ToUniversalTime().ToString('o')
    seamless_reload = [bool]$SeamlessReload
    seamless_reload_verified = $null
    installer_found = $null
    installer_exit_code = $null
    installer_elapsed_seconds = $null
    station_healthy = $false
    first_admin_ok = $null
    captions_off_requested = [bool]$CaptionsOff
    captions_enabled = $true
    captions_off_verified = $false
    samples_found = 0
    assets_uploaded = 0
    channels_started = @()
    soak_start_utc = $null
    worker_env_requested = @($workerEnvRequestedStrings)
    worker_env_verified = @()
    gst_debug_file = $script:GstDebugFilePath
    error = $null
}
Write-SoakLog "run header: minutes=$Minutes seamless_reload=$([bool]$SeamlessReload) install_bound_minutes=$InstallBoundMinutes health_bound_minutes=$HealthBoundMinutes worker_env_requested=$($summary.worker_env_requested -join ', ') gst_debug_file=$($script:GstDebugFilePath)"

if ($workerEnvParsed.errors.Count -gt 0) {
    foreach ($e in $workerEnvParsed.errors) { Write-SoakLog "worker_env parse error: $e" }
    Write-HarnessErrorVerdictAndExit -Reason "-WorkerEnv failed to parse ($($workerEnvParsed.errors.Count) error(s)): $($workerEnvParsed.errors -join ' | ') -- a config problem this guest can diagnose immediately, not a product finding"
}

$installerExe = Get-ChildItem -Path $KitDir -Filter '*setup.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installerExe) {
    Write-HarnessErrorVerdictAndExit -Reason "no *setup.exe found under $KitDir -- a bad/incomplete mapped kit, not a product finding"
}
$summary.installer_found = $installerExe.FullName
Write-SoakLog "installer: $($installerExe.FullName)"

Write-SoakLog "running silent install (bounded to ${InstallBoundMinutes}m, heartbeat every 60s): /S /D=$InstallDir"
$installResult = Invoke-BoundedProcessWithHeartbeat -FilePath $installerExe.FullName -ArgumentList @("/S", "/D=$InstallDir") -TimeoutSeconds ($InstallBoundMinutes * 60) -HeartbeatSeconds 60 -OnHeartbeat {
    param($elapsed)
    Write-SoakLog "installer still running, ${elapsed}s elapsed"
}
$summary.installer_exit_code = $installResult.exit_code
$summary.installer_elapsed_seconds = $installResult.elapsed_seconds
Write-SoakLog "installer done: exit_code=$($installResult.exit_code) exited=$($installResult.exited) elapsed_seconds=$($installResult.elapsed_seconds) error=$($installResult.error)"
Write-PhaseMarker -Name 'PHASE-INSTALL-DONE.json' -Obj ([ordered]@{
    utc = (Get-Date).ToUniversalTime().ToString('o')
    exit_code = $installResult.exit_code
    exited = $installResult.exited
    elapsed_seconds = $installResult.elapsed_seconds
    error = $installResult.error
})
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if (-not $installResult.exited -or $installResult.exit_code -ne 0) {
    Write-FailVerdictAndExit -Reason "installer did not exit 0 within ${InstallBoundMinutes}m (exited=$($installResult.exited), exit_code=$($installResult.exit_code), error=$($installResult.error))"
}

# --------------------------------------------------------------------------
# 2. Start the station the same way the installed product starts on a real
#    box: the installer's own service (CivicCastSupervisor) is set to
#    auto-start; nudge it in case it hasn't come up yet, then poll /health.
#    Health PREDICATE: status=="healthy" AND schema=="current" (HTTP 200
#    alone is liveness only -- In-Sandbox-Report.ps1:2852-2860).
# --------------------------------------------------------------------------
# Round-8 finding 4 (BLOCKER): the round-6 version -- a machine-scope
# [Environment]::SetEnvironmentVariable followed by a plain Start-Service --
# NEVER actually reached the service. Two independent reasons: (a) the
# installer's own postinstall step already started CivicCastSupervisor, so
# by the time this script called Start-Service the service was already
# running -- Start-Service on an already-running service is a documented
# no-op measured at ~0.4s before the very next health check, so it never
# launched a fresh process to inherit anything; (b) even a fresh launch
# would not have helped -- Windows services are started by services.exe,
# whose own process environment block is captured once at boot and is NOT
# refreshed by a later machine-scope SetEnvironmentVariable broadcast (a
# real, well-documented Windows behavior, not specific to this box). The
# ONLY reliable way to hand a specific env var to ONE service's own process
# is the per-service Environment REG_MULTI_SZ value under that service's
# own registry key, which the SCM reads and merges in at THAT service's own
# launch time -- so this now writes there, then forces an actual
# Stop-Service + Start-Service cycle so a fresh process is what launches.
# sandbox-lab lane follow-up D: -WorkerEnv's requested entries are merged
# into this SAME registry write and this SAME Stop-Service/Start-Service
# cycle as -SeamlessReload -- one restart total, never two. $seamlessRegPath
# and the registry-write mechanics are unchanged from the pre-existing
# -SeamlessReload code (Round-8 finding 4's own fix); what changed is WHICH
# entries get merged in before the single Set-ItemProperty call.
$anyEnvInjectionRequested = ([bool]$SeamlessReload) -or ($workerEnvDeduped.Count -gt 0)
if ($anyEnvInjectionRequested) {
    $seamlessRegPath = 'HKLM:\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor'
    $envRegOk = $false

    # Item 2: if the requested env sets GST_DEBUG_FILE, create its
    # containing directory BEFORE the restart -- ffmpeg/GStreamer does not
    # create intermediate directories for a log-file path, so a worker
    # that launches with GST_DEBUG_FILE pointed at a directory that does
    # not exist yet would simply fail to write the debug log at all (not a
    # crash, just silent evidence loss). Non-fatal: a directory-creation
    # failure is logged and surfaced later via Copy-StationLogs's own
    # missing-file note, never a HARNESS_ERROR by itself -- the operator
    # explicitly asked to test env injection, not directory permissions.
    if ($script:GstDebugFilePath) {
        try {
            $gstDebugDir = Split-Path -Parent $script:GstDebugFilePath
            if ($gstDebugDir) {
                New-Item -ItemType Directory -Force -Path $gstDebugDir -ErrorAction Stop | Out-Null
                Write-SoakLog "worker_env: created GST_DEBUG_FILE directory $gstDebugDir"
            }
        } catch {
            Write-SoakLog "worker_env: FAILED to create GST_DEBUG_FILE directory for $($script:GstDebugFilePath): $_ (non-fatal -- the worker's own debug-log write will simply fail silently if this directory never exists)"
        }
    }

    # Requested entries for THIS registry write: the -SeamlessReload flag's
    # own synthetic entry (if set) plus every -WorkerEnv entry, deduped
    # together (later position wins) so a -WorkerEnv value that happens to
    # also name CIVICCAST_EGRESS_SEAMLESS_RELOAD is a well-defined
    # override, not two competing writes.
    $seamlessEntries = @()
    if ($SeamlessReload) {
        $seamlessEntries += [pscustomobject]@{ Name = 'CIVICCAST_EGRESS_SEAMLESS_RELOAD'; Value = '1'; IsUnset = $false }
    }
    $envEntriesToWrite = @(Get-DedupedWorkerEnvEntries -Entries (@($seamlessEntries) + @($workerEnvDeduped)))

    try {
        $existingEnv = @()
        try { $existingEnv = @((Get-ItemProperty -Path $seamlessRegPath -Name 'Environment' -ErrorAction Stop).Environment) } catch { $existingEnv = @() }
        $newEnv = @(Merge-WorkerEnvIntoRegistryList -ExistingEnv $existingEnv -Entries $envEntriesToWrite)
        Set-ItemProperty -Path $seamlessRegPath -Name 'Environment' -Value $newEnv -Type MultiString -ErrorAction Stop
        $readBackEnv = @((Get-ItemProperty -Path $seamlessRegPath -Name 'Environment' -ErrorAction Stop).Environment)
        $envRegOk = $true
        # Round-2 review finding (optional item): -ccontains/-cmatch, not
        # the case-INSENSITIVE default -- these compare against the exact
        # "NAME=VALUE" strings THIS RUN just wrote via Set-ItemProperty,
        # so the correct semantic is byte-for-byte string equality, not a
        # case-folded one (dedupe-by-name, elsewhere, is deliberately
        # still case-insensitive -- that is a different question, "is
        # this logically the same variable").
        foreach ($e in ($envEntriesToWrite | Where-Object { -not $_.IsUnset })) {
            if (-not ($readBackEnv -ccontains "$($e.Name)=$($e.Value)")) { $envRegOk = $false }
        }
        foreach ($e in ($envEntriesToWrite | Where-Object { $_.IsUnset })) {
            if (@($readBackEnv | Where-Object { $_ -cmatch "^$([regex]::Escape($e.Name))=" }).Count -gt 0) { $envRegOk = $false }
        }
        Write-SoakLog "worker_env: wrote $seamlessRegPath\Environment (REG_MULTI_SZ, $($newEnv.Count) entries; seamless_reload=$([bool]$SeamlessReload), worker_env_entries=$($workerEnvDeduped.Count)); read-back matches every requested entry: $envRegOk"
    } catch {
        Write-SoakLog "worker_env: FAILED to write/read-back $seamlessRegPath\Environment : $_"
    }
    if (-not $envRegOk) {
        Write-HarnessErrorVerdictAndExit -Reason "-SeamlessReload/-WorkerEnv env injection was requested but writing/confirming $seamlessRegPath\Environment (REG_MULTI_SZ) failed -- refusing to proceed with an unconfirmed environment configuration (never an 'unverified' PASS/FAIL for a flag the operator explicitly asked to test)"
    }

    try {
        Stop-Service -Name 'CivicCastSupervisor' -Force -ErrorAction Stop
        Write-SoakLog "worker_env: Stop-Service CivicCastSupervisor requested (forcing a fresh launch that reads the just-written per-service Environment)"
    } catch {
        Write-SoakLog "worker_env: Stop-Service CivicCastSupervisor: $_ (may not have been running yet -- proceeding to Start-Service regardless, which will still launch fresh with the registry value in place)"
    }
}

# Round-14 finding 8 (LOW): Test-ServiceStartFailureIsProductCrash now
# lives in its own dot-sourceable file, ServiceStartFailureCheck.ps1,
# matching this project's established extraction pattern so it is
# unit-testable (Test-ServiceStartFailure.ps1) with synthetic
# Get-Service/Get-WinEvent results instead of the live System event log.
# See that file's own header/doc comment for the full round-11 through
# round-14 finding history.
. (Join-Path 'C:\CivicCastSoakScripts' 'ServiceStartFailureCheck.ps1')

# sandbox-lab lane follow-up A: three more dot-sourceable, unit-tested
# extractions, same pattern as ServiceStartFailureCheck.ps1 just above --
# CaptionsOffCheck.ps1 (item 1's PUT/GET verification judgment),
# WorkerStdoutParser.ps1 (item 2's per-line matcher, used by
# Update-WorkerStdoutCounters below), CpuSampler.ps1 (item 3's pure
# delta/conversion math, used by Get-CycleProcessCpuSamples below). Loaded
# here (well before first use in every case) rather than scattered next to
# each call site, so this is the one place that answers "what does this
# deployment ship" alongside the other three dot-sources on this page.
. (Join-Path 'C:\CivicCastSoakScripts' 'CaptionsOffCheck.ps1')
. (Join-Path 'C:\CivicCastSoakScripts' 'WorkerStdoutParser.ps1')
. (Join-Path 'C:\CivicCastSoakScripts' 'CpuSampler.ps1')

$startServiceOk = $false
$startServiceExceptionText = $null
# Round-12 finding 5 (MEDIUM): captured immediately before the actual
# Start-Service call so the event-log query above has a precise lower
# bound -- never a crash from some earlier, unrelated point in this run
# (or a prior run entirely) mistaken for evidence about THIS attempt.
$startAttemptUtc = (Get-Date).ToUniversalTime()
try {
    Start-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
    Write-SoakLog "Start-Service CivicCastSupervisor: requested"
    $startServiceOk = $true
} catch {
    $startServiceExceptionText = "$_"
    Write-SoakLog "Start-Service CivicCastSupervisor: $_ (may not have been running yet -- proceeding to Start-Service regardless, which will still launch fresh with the registry value in place)"
}

# Round-10 finding 3 (HIGH): the round-9 N2 fix over-corrected -- it routed
# EVERY health timeout under -SeamlessReload to HARNESS_ERROR, including a
# station that came up (service Running) but genuinely never answers
# healthy, which IS a real product finding regardless of -SeamlessReload.
# Split the two: confirm the SERVICE itself actually reached Running
# BEFORE trusting the health poll to mean anything -- Start-Service
# throwing, or the service settling into any state OTHER than Running
# (short poll below to ride out a transient StartPending), is checked
# against the event log above (round-12 findings 4-5) before deciding
# harness-vs-product; a service that IS Running and simply never reports
# healthy is judged as FAIL below, unconditionally (seamless-reload or
# not).
$serviceRunning = $false
$svc = $null
$svcPollDeadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $svcPollDeadline) {
    try {
        $svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
        if ($svc.Status -eq 'Running') { $serviceRunning = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
Write-SoakLog "CivicCastSupervisor service status after Start-Service: $(if ($svc) { $svc.Status } else { '<Get-Service failed>' }) (serviceRunning=$serviceRunning)"
if (-not $startServiceOk -or -not $serviceRunning) {
    $crashCheck = Test-ServiceStartFailureIsProductCrash -ExceptionText $startServiceExceptionText -SinceUtc $startAttemptUtc
    Write-SoakLog "Start-Service $(if (-not $startServiceOk) { 'threw' } else { "succeeded but the service never reached Running (status='$(if ($svc) { $svc.Status } else { '<unknown>' })')" }) -- product-crash-vs-harness check: IsProductCrash=$($crashCheck.IsProductCrash) ($($crashCheck.Reason))"
    if ($crashCheck.IsProductCrash) {
        Write-FailVerdictAndExit -Reason "Start-Service CivicCastSupervisor $(if (-not $startServiceOk) { 'threw' } else { 'succeeded but the service never reached Running' }), and evidence shows the service process actually started and then crashed: $($crashCheck.Reason)"
    }
    if (-not $startServiceOk) {
        Write-HarnessErrorVerdictAndExit -Reason "Start-Service CivicCastSupervisor threw and no evidence the process itself ever started/crashed ($($crashCheck.Reason)) -- the SCM itself never launched the station process, so no health poll result can be judged as a product finding"
    }
    Write-HarnessErrorVerdictAndExit -Reason "Start-Service CivicCastSupervisor left the service in state '$(if ($svc) { $svc.Status } else { '<unknown>' })', never reached Running within 30s, and no event-log evidence the process itself crashed ($($crashCheck.Reason)) -- the station process itself never came up, so no health poll result can be judged as a product finding"
}

Write-SoakLog "polling for station health (bounded to ${HealthBoundMinutes}m): require status=='healthy' AND schema=='current'"
$healthy = $false
$lastHealthBody = $null
$healthDeadline = (Get-Date).AddMinutes($HealthBoundMinutes)
while ((Get-Date) -lt $healthDeadline) {
    try {
        $h = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 10 -ErrorAction Stop
        $lastHealthBody = $h
        if ($h.status -eq 'healthy' -and $h.schema -eq 'current') { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 6
}
$summary.station_healthy = $healthy
Write-SoakLog "station healthy: $healthy (last body: status=$($lastHealthBody.status) schema=$($lastHealthBody.schema))"
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if (-not $healthy) {
    # Round-9 finding N2 (HIGH) as narrowed by round-10 finding 3: the
    # service-running gate above already routes the case where THIS
    # SCRIPT's own -SeamlessReload Stop-Service/Start-Service cycle never
    # got the process back up at all (HARNESS_ERROR). By the time control
    # reaches here, Get-Service already confirmed CivicCastSupervisor
    # reached Running -- a station that IS running and simply never
    # answers /health with status=healthy is a real product finding,
    # unconditionally, seamless-reload or not (round-9's SeamlessReload
    # special-case here was too broad: it would have masked a genuine
    # health-check regression any time -SeamlessReload happened to be set).
    Write-FailVerdictAndExit -Reason "station never reported status=healthy AND schema=current at $Base/health within ${HealthBoundMinutes}m (service confirmed Running; last body: status=$($lastHealthBody.status) schema=$($lastHealthBody.schema))"
}
Write-PhaseMarker -Name 'PHASE-HEALTHY.json' -Obj ([ordered]@{ utc = (Get-Date).ToUniversalTime().ToString('o'); body_status = $lastHealthBody.status; body_schema = $lastHealthBody.schema })

# Round-8 finding 4: verification now runs AFTER the Stop-Service +
# Start-Service cycle above and the health poll that follows it -- so
# "control-plane process found" here means a FRESH one, launched after the
# registry value was written, not the pre-existing one from the
# installer's own postinstall start. Neither Get-Process/-StartInfo nor
# Win32_Process can read another process's real environment block from
# outside it (confirmed: Win32_Process carries no environment-adjacent
# property at all) -- so this can never open the child's own memory and
# read CIVICCAST_EGRESS_SEAMLESS_RELOAD out of it directly. What it CAN
# do, and what this verifies: (1) the per-service registry value is
# present (read back a second time, post-restart, in case something else
# rewrote it), (2) a control-plane process actually exists after the
# restart (proving the service cycle produced a live child at all), and
# (3) an optional, best-effort grep of the station's own log for a
# confirming line. If (1) or (2) fail, this is NOT reported as
# "unverified" -- it is a HARNESS_ERROR: a flag the operator explicitly
# asked to test must never silently ride along as an unconfirmed premise
# of a PASS or FAIL verdict.
if ($anyEnvInjectionRequested) {
    $readBackEnv2 = @()
    try {
        $readBackEnv2 = @((Get-ItemProperty -Path $seamlessRegPath -Name 'Environment' -ErrorAction Stop).Environment)
    } catch { }

    $cpProc = $null
    try {
        $cpProc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'civiccast\.app:create_app' } |
            Select-Object -First 1
    } catch { }
    if ($cpProc) {
        Write-SoakLog "worker_env verification: control-plane process found post-restart pid=$($cpProc.ProcessId)"
    } else {
        Write-SoakLog "worker_env verification: control-plane process (python.exe running uvicorn civiccast.app:create_app) NOT FOUND via Win32_Process after the restart"
    }

    if ($SeamlessReload) {
        $seamlessRegOkAfterRestart = ($readBackEnv2 -ccontains 'CIVICCAST_EGRESS_SEAMLESS_RELOAD=1')
        Write-SoakLog "seamless_reload verification: $seamlessRegPath\Environment still contains the flag: $seamlessRegOkAfterRestart"

        if (-not $seamlessRegOkAfterRestart -or -not $cpProc) {
            Write-HarnessErrorVerdictAndExit -Reason "SeamlessReload was requested but could not be confirmed after the service restart (registry_flag_present=$seamlessRegOkAfterRestart, control_plane_process_found=$([bool]$cpProc)) -- never an 'unverified' PASS/FAIL for a flag the operator explicitly asked to test"
        }

        $logCandidates = @(
            'C:\ProgramData\CivicCast\logs\control_plane.log',
            'C:\ProgramData\CivicCast\logs\control_plane-app.log'
        )
        $foundLine = $null
        foreach ($lp in $logCandidates) {
            if (Test-Path $lp) {
                try {
                    $match = Get-Content -Path $lp -Tail 500 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'seamless' -or $_ -match 'CIVICCAST_EGRESS_SEAMLESS_RELOAD' } | Select-Object -Last 1
                    if ($match) { $foundLine = "$lp : $match"; break }
                } catch { }
            }
        }
        if ($foundLine) {
            $summary.seamless_reload_verified = 'confirmed-via-log'
            Write-SoakLog "seamless_reload verification: CONFIRMED via log line (on top of the registry+process confirmation above): $foundLine"
        } else {
            $summary.seamless_reload_verified = 'confirmed-via-registry-and-process'
            Write-SoakLog "seamless_reload verification: confirmed via registry read-back + a live post-restart control-plane process; no log line additionally corroborated it (checked $($logCandidates -join ', '))"
        }
    }

    # sandbox-lab lane follow-up D: per-entry -WorkerEnv verification.
    # Reuses the EXACT same evidence -SeamlessReload's own verification
    # above already established this lane can honestly gather -- neither
    # Get-Process/-StartInfo nor Win32_Process can read another process's
    # real environment block from outside it (Win32_Process carries no
    # environment-adjacent property at all, confirmed by the comment
    # above), so "verified" here means (1) the per-service registry
    # value matches what was requested for this entry (present with the
    # exact value for a set entry; genuinely absent for an unset/removal
    # entry) AND (2) a live post-restart control-plane process exists
    # (proving the service cycle produced a fresh child at all) -- never
    # a literal read of the worker's own process environment block, which
    # this harness has no mechanism to perform. A mismatch on either
    # condition is HARNESS_ERROR, exactly like -SeamlessReload/-CaptionsOff
    # (the operator explicitly asked to test this entry).
    $workerEnvVerifiedList = @()
    $workerEnvAllOk = $true
    foreach ($e in $workerEnvDeduped) {
        $expectPresent = -not $e.IsUnset
        # Round-2 review finding (optional item): case-sensitive -- see
        # the matching comment at this run's own registry-write step above.
        $isPresentWithValue = ($readBackEnv2 -ccontains "$($e.Name)=$($e.Value)")
        $isAbsent = (@($readBackEnv2 | Where-Object { $_ -cmatch "^$([regex]::Escape($e.Name))=" }).Count -eq 0)
        $entryOk = [bool]$cpProc -and $(if ($expectPresent) { $isPresentWithValue } else { $isAbsent })
        if (-not $entryOk) { $workerEnvAllOk = $false }
        $workerEnvVerifiedList += [ordered]@{
            name = $e.Name
            unset_requested = $e.IsUnset
            registry_matches_request = $(if ($expectPresent) { $isPresentWithValue } else { $isAbsent })
            verified = $entryOk
        }
        Write-SoakLog "worker_env verification: name=$($e.Name) unset_requested=$($e.IsUnset) registry_matches_request=$(if ($expectPresent) { $isPresentWithValue } else { $isAbsent }) verified=$entryOk"
    }
    $summary.worker_env_verified = $workerEnvVerifiedList
    Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

    if ($workerEnvDeduped.Count -gt 0 -and (-not $workerEnvAllOk -or -not $cpProc)) {
        $failedNames = @($workerEnvVerifiedList | Where-Object { -not $_.verified } | ForEach-Object { $_.name }) -join ', '
        Write-HarnessErrorVerdictAndExit -Reason "-WorkerEnv was requested but could not be confirmed after the service restart for: $failedNames (control_plane_process_found=$([bool]$cpProc)) -- never an 'unverified' PASS/FAIL for entries the operator explicitly asked to test"
    }
}

# --------------------------------------------------------------------------
# Resolve tsp.exe/ffmpeg.exe/ffprobe.exe from the installed layout (bounded
# candidate paths only -- see Copy-StationLogs's header for why no
# full-tree recursive scan) and author the firewall allow rules BEFORE the
# first tsp bind (N2) -- moved up from the poll-loop section so this can
# run before first-admin/asset-upload/schedule/channel-start too, a
# superset of "before the first probe".
# --------------------------------------------------------------------------
$tspCandidates = @(
    (Join-Path $KitDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'tsduck\bin\tsp.exe'),
    'C:\Program Files\CivicCast (Native)\tsduck\bin\tsp.exe'
)
$tsp = $tspCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
Write-SoakLog "tsp.exe: $(if ($tsp) { $tsp } else { 'NOT FOUND in the bounded candidate list -- egress probes will report not-run (no full-tree recursive fallback scan; see file header)' })"

$ffmpegCandidates = @(
    (Join-Path $InstallDir 'dependencies\ffmpeg\bin\ffmpeg.exe'),
    'C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffmpeg.exe'
)
$ffmpegExe = $ffmpegCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$ffprobeCandidates = @(
    (Join-Path $InstallDir 'dependencies\ffmpeg\bin\ffprobe.exe'),
    'C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe'
)
$ffprobeExe = $ffprobeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
Write-SoakLog "ffmpeg.exe: $(if ($ffmpegExe) { $ffmpegExe } else { 'NOT FOUND' }); ffprobe.exe: $(if ($ffprobeExe) { $ffprobeExe } else { 'NOT FOUND' })"

Add-CivicCastFirewallAllowRule -Name 'CivicCast Sandbox Soak - TSDuck tsp' -ProgramPath $tsp | Out-Null
Add-CivicCastFirewallAllowRule -Name 'CivicCast Sandbox Soak - ffmpeg' -ProgramPath $ffmpegExe | Out-Null
Add-CivicCastFirewallAllowRule -Name 'CivicCast Sandbox Soak - ffprobe' -ProgramPath $ffprobeExe | Out-Null
Write-PhaseMarker -Name 'PHASE-FIREWALL-RULES.json' -Obj ([ordered]@{ utc = (Get-Date).ToUniversalTime().ToString('o'); tsp = $tsp; ffmpeg = $ffmpegExe; ffprobe = $ffprobeExe })

# --------------------------------------------------------------------------
# Generic JSON API helper -- ported from AUTORUN-9m.ps1's
# Invoke-CivicCastApi, which itself ports In-Sandbox-Report.ps1's
# Invoke-CivicCastApi: on non-2xx, read the actual response body so a 422's
# field-level detail lands in the log instead of a bare status code.
# --------------------------------------------------------------------------
function Invoke-CivicCastApi {
    param(
        [string]$Method, [string]$Url, [object]$BodyObj = $null,
        [string]$BearerToken = $null, [int]$TimeoutSec = 60
    )
    $result = [ordered]@{ method = $Method; url = $Url; status = $null; ok = $false; body_raw = $null; body_json = $null; error = $null }
    try {
        $headers = @{}
        if ($BearerToken) { $headers['Authorization'] = "Bearer $BearerToken" }
        $params = @{ Uri = $Url; Method = $Method; Headers = $headers; UseBasicParsing = $true; TimeoutSec = $TimeoutSec; ErrorAction = 'Stop' }
        if ($null -ne $BodyObj) {
            $params['Body'] = ($BodyObj | ConvertTo-Json -Depth 10)
            $params['ContentType'] = 'application/json'
        }
        $resp = Invoke-WebRequest @params
        $result.status = [int]$resp.StatusCode
        $result.body_raw = [string]$resp.Content
        $result.ok = $true
    } catch {
        $we = $_.Exception
        if ($we.Response) {
            try {
                $result.status = [int]$we.Response.StatusCode
                $stream = $we.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $result.body_raw = $reader.ReadToEnd()
            } catch { }
        }
        $result.error = "$_"
    }
    if ($result.body_raw) { try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch { } }
    return $result
}

# Multipart asset upload -- ported from AUTORUN-9m.ps1's Invoke-AssetUpload
# (Windows PowerShell 5.1's Invoke-WebRequest has no -Form; build
# multipart/form-data by hand via System.Net.Http.MultipartFormDataContent;
# System.Net.Http is Add-Type'd once at script scope, top of file).
# STREAMED, not ReadAllBytes: the LPM sample clips run up to ~858MB, and
# ReadAllBytes would materialize the whole file in managed memory before the
# first byte goes over the wire. FileStream -> StreamContent reads lazily as
# HttpClient sends.
#
# N5: PostAsync is one long blocking call for an 819MB clip with NOTHING
# logged until it returns -- exactly the same silent-window problem the
# installer's Invoke-BoundedProcessWithHeartbeat exists to fix, just for an
# in-process Task instead of a child process. Same shape here: poll
# Task.Wait($sliceMs) in a loop and log a heartbeat each slice instead of
# one blocking .Result.
function Invoke-AssetUpload {
    param([string]$BaseUrl, [string]$Token, [string]$AssetId, [string]$Title, [string]$FilePath, [int]$TimeoutSec = 900, [int]$HeartbeatSeconds = 30)
    $url = "$BaseUrl/api/staff/assets/upload"
    $result = [ordered]@{ method = 'POST'; url = $url; status = $null; ok = $false; body_raw = $null; body_json = $null; error = $null }
    $fileStream = $null
    $client = $null
    try {
        $handler = New-Object System.Net.Http.HttpClientHandler
        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
        $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $Token)
        $content = New-Object System.Net.Http.MultipartFormDataContent
        $content.Add((New-Object System.Net.Http.StringContent($AssetId)), 'asset_id')
        $content.Add((New-Object System.Net.Http.StringContent($Title)), 'title')
        $fileStream = [System.IO.File]::OpenRead($FilePath)
        $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
        try { $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('video/mp4') } catch { }
        $content.Add($fileContent, 'file', [System.IO.Path]::GetFileName($FilePath))

        $uploadStartedAt = Get-Date
        $task = $client.PostAsync($url, $content)
        $sliceMs = [Math]::Max(1000, $HeartbeatSeconds * 1000)
        $deadline = $uploadStartedAt.AddSeconds($TimeoutSec)
        while (-not $task.IsCompleted -and (Get-Date) -lt $deadline) {
            $null = $task.Wait($sliceMs)
            if (-not $task.IsCompleted) {
                Write-SoakLog "asset upload still in flight for $AssetId ($([int](((Get-Date) - $uploadStartedAt).TotalSeconds))s elapsed)"
            }
        }
        if (-not $task.IsCompleted) {
            $result.error = "upload did not complete within ${TimeoutSec}s (asset_id=$AssetId)"
            return $result
        }
        $resp = $task.Result
        $result.status = [int]$resp.StatusCode
        $result.body_raw = $resp.Content.ReadAsStringAsync().Result
        $result.ok = $resp.IsSuccessStatusCode
    } catch {
        # N5/round-3(b): a bare "$_" can render as an empty string for some
        # .NET exception shapes (exactly what happened here -- the earlier
        # catch produced the "status= body=" log line with the real cause,
        # a TerminatingError from a missing type, thrown away). Always name
        # the exception type explicitly so the FAILED log line can never be
        # silently empty again.
        $result.error = "$($_.Exception.GetType().Name): $($_.Exception.Message)"
    } finally {
        try { if ($fileStream) { $fileStream.Dispose() } } catch { }
        try { if ($client) { $client.Dispose() } } catch { }
    }
    if ($result.body_raw) { try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch { } }
    return $result
}

# --------------------------------------------------------------------------
# 3. First-admin setup (POST /api/setup/first-admin -- loopback-admitted
#    before staff auth exists). Body shape from AUTORUN-8.ps1.
# --------------------------------------------------------------------------
$token = $null
$pwd = 'Soak!' + ([guid]::NewGuid().ToString('N').Substring(0, 18))
$firstAdminBody = [ordered]@{
    station_name             = 'Sandbox Soak'
    admin_display_name       = 'Soak Operator'
    admin_username           = 'soakadmin'
    admin_password           = $pwd
    recovery_kit_destination = 'not printed -- automated sandbox soak'
    default_channel_id       = 'government'
    station_timezone         = 'local'
    channel_count            = 3
    sample_content_enabled   = $false
    initial_schedule_enabled = $false
    operation_mode           = 'test'
}
try {
    $resp = Invoke-RestMethod -Method Post -Uri "$Base/api/setup/first-admin" -ContentType 'application/json' -Body ($firstAdminBody | ConvertTo-Json -Depth 5) -TimeoutSec 120
    $token = $resp.operator_console_token
    $summary.first_admin_ok = $true
    Write-SoakLog "first-admin: complete"
} catch {
    $detail = ''
    try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    $summary.first_admin_ok = $false
    Write-SoakLog "first-admin POST failed: $($_.Exception.Message) :: $detail"
}
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if (-not $token) {
    Write-FailVerdictAndExit -Reason "first-admin setup did not return an operator_console_token -- cannot configure or start channels"
}

# --------------------------------------------------------------------------
# 3b. sandbox-lab lane follow-up A, item 1: -CaptionsOff. PUT
#     /api/staff/station/profile {"live_captions_enabled": false} using the
#     operator's own first-admin token, then GET it back to confirm. Never
#     touches the CIVICCAST_CAPTION_TAP env var. Judgment logic lives in
#     CaptionsOffCheck.ps1's Get-CaptionsOffVerification (unit-tested by
#     Test-CaptionsOffCheck.ps1) so it is exercised by the same code a real
#     run uses, not a hand-rolled inline condition.
# --------------------------------------------------------------------------
if ($CaptionsOff) {
    Write-SoakLog "captions_off: requesting live_captions_enabled=false via PUT $Base/api/staff/station/profile"
    $captionsPutR = Invoke-CivicCastApi -Method 'Put' -Url "$Base/api/staff/station/profile" -BodyObj ([ordered]@{ live_captions_enabled = $false }) -BearerToken $token
    Write-SoakLog "captions_off: PUT status=$($captionsPutR.status) body=$($captionsPutR.body_raw) error=$($captionsPutR.error)"
    $captionsPutOk = ($captionsPutR.status -eq 200)

    $captionsGetR = Invoke-CivicCastApi -Method 'Get' -Url "$Base/api/staff/station/profile" -BearerToken $token
    Write-SoakLog "captions_off: GET status=$($captionsGetR.status) body=$($captionsGetR.body_raw) error=$($captionsGetR.error)"
    $captionsGetOk = ($captionsGetR.status -eq 200 -and $null -ne $captionsGetR.body_json)
    $captionsReadBackValue = $(if ($captionsGetOk) { $captionsGetR.body_json.live_captions_enabled } else { $null })

    $captionsVerification = Get-CaptionsOffVerification -PutOk $captionsPutOk -GetOk $captionsGetOk -ReadBackValue $captionsReadBackValue
    $summary.captions_enabled = $captionsVerification.captions_enabled
    $summary.captions_off_verified = $captionsVerification.verified
    Write-SoakLog "captions_off: verified=$($captionsVerification.verified) captions_enabled=$($captionsVerification.captions_enabled) read_back_value=$captionsReadBackValue"
    Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

    if ($captionsVerification.should_harness_error) {
        Write-HarnessErrorVerdictAndExit -Reason "-CaptionsOff was requested but could not be confirmed (PUT ok=$captionsPutOk, GET ok=$captionsGetOk, live_captions_enabled read back as '$captionsReadBackValue', expected false) -- never an unconfirmed premise for a flag the operator explicitly asked to test"
    }
} else {
    # Round-2 finding 4 (MEDIUM): -CaptionsOff was NOT requested, but
    # $summary.captions_enabled must still be a MEASURED value, not the
    # hardcoded $true it was initialized to above -- one unconditional GET
    # /api/staff/station/profile, same endpoint the -CaptionsOff branch
    # above already reads, judged by the SAME conservative rule
    # (Get-MeasuredCaptionsEnabled, CaptionsOffCheck.ps1, factored out of
    # Get-CaptionsOffVerification for exactly this reuse). Never a
    # HARNESS_ERROR here -- the operator did not ask this lane to verify
    # anything about captions on this run, so a failed/unparsed GET simply
    # falls back to the same conservative $true default the hardcoded
    # value already was, just now via the same judged code path instead of
    # a bare literal.
    $captionsGetR = Invoke-CivicCastApi -Method 'Get' -Url "$Base/api/staff/station/profile" -BearerToken $token
    Write-SoakLog "captions_check (no -CaptionsOff): GET status=$($captionsGetR.status) body=$($captionsGetR.body_raw) error=$($captionsGetR.error)"
    $captionsGetOk = ($captionsGetR.status -eq 200 -and $null -ne $captionsGetR.body_json)
    $captionsReadBackValue = $(if ($captionsGetOk) { $captionsGetR.body_json.live_captions_enabled } else { $null })
    $summary.captions_enabled = Get-MeasuredCaptionsEnabled -GetOk $captionsGetOk -ReadBackValue $captionsReadBackValue
    Write-SoakLog "captions_check: measured captions_enabled=$($summary.captions_enabled) (get_ok=$captionsGetOk read_back=$captionsReadBackValue)"
    Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')
}

# --------------------------------------------------------------------------
# 4. Load the kit's sample videos into the three egress channels, the way
#    AUTORUN-9m does it: upload assets, schedule + Commit-to-Air EVERY
#    channel while still stopped, THEN config+start (avoids a reload storm
#    on an already-ON_AIR channel -- see AUTORUN-9m.ps1 header, item B-B).
# --------------------------------------------------------------------------
$samples = @(Get-ChildItem (Join-Path $KitDir 'samples') -Filter '*.mp4' -File -ErrorAction SilentlyContinue | Sort-Object Name)
$summary.samples_found = $samples.Count
Write-SoakLog "samples found: $($samples.Count)"
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if ($samples.Count -lt 1) {
    Write-HarnessErrorVerdictAndExit -Reason "no sample videos found under $KitDir\samples -- a bad/incomplete mapped kit, not a product finding"
}

$channelSpecs = @(
    @{ id = 'public';     port = 9001 }
    @{ id = 'education';  port = 9002 }
    @{ id = 'government'; port = 9003 }
)

# Asset ids: civiccast/schedule/router.py:724-727 requires
# `^[a-z0-9][a-z0-9-]{2,63}$` (lowercase only). Shape ported from
# AUTORUN-9e.ps1:341-342 ('sbsoak-' + yyMMddHHmmss + '-' + 4 random a-z
# chars), plus a per-clip index so clips whose first N basename chars
# collide never produce the same id (the earlier cut of this script derived
# the id from a truncated, mixed-case basename and hit both a 422 on case
# and a 409 on the collision).
$assetSuffix = -join ((97..122) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
$stampCompact = Get-Date -Format 'yyMMddHHmmss'
$stagedAssets = @()
$clipIndex = 0
foreach ($s in ($samples | Select-Object -First 4)) {
    $clipIndex++
    $assetId = "sbsoak-$stampCompact-$assetSuffix-$clipIndex"
    $up = Invoke-AssetUpload -BaseUrl $Base -Token $token -AssetId $assetId -Title $s.Name -FilePath $s.FullName
    if ($up.ok) {
        $summary.assets_uploaded++
        # ROLLOVER INSTRUMENT: duration is a PINNED constant, not discovered
        # via ffprobe -- see the file header for why. 30s -> content rolls
        # over roughly every 4 minutes across the whole soak.
        $stagedAssets += [ordered]@{ id = $assetId; duration_seconds = 30 }
        Write-SoakLog "asset uploaded: $assetId ($($s.Name), duration pinned to 30s)"
    } else {
        Write-SoakLog "asset upload FAILED for $($s.Name) (id=$assetId): status=$($up.status) body=$($up.body_raw) error=$($up.error)"
    }
}
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if ($stagedAssets.Count -eq 0) {
    Write-FailVerdictAndExit -Reason "no assets uploaded successfully -- cannot schedule or start channels"
}

# Round-5 item 1 / round-8 finding 6: single source of truth for the
# ON_AIR poll bound, needed HERE (to size the schedule for the worst case)
# and again below (as the actual poll deadline). Raised 10 -> 12 minutes
# (run 7's "public" channel genuinely reaching ON_AIR at 645s/10m45s --
# inside the OLD 10-minute/600s bound's own measured worst case, but with
# no margin left at all); round-15 finding (a): now a real parameter
# (-OnAirBoundMinutes, default 12, see the param block above) instead of a
# hardcoded literal here.

# Schedule + Commit-to-Air: a FIXED item count per channel, sized for the
# WORST CASE where the ON_AIR poll takes its full $OnAirBoundMinutes bound --
# ceil((Minutes + OnAirBoundMinutes + 13) * 60 / 30) items @ 30s each. This
# is the rollover instrument itself (see file header), not a wall-clock loop
# probing real durations. Coverage must span from schedulingStart-60s through
# soak_start_utc + Minutes + 3m even in that worst case; the +13 minutes is
# the fixed safety margin on top of the ON_AIR bound itself (covers the
# config+start loop and general clock slack, which are cheap relative to a
# HARNESS_ERROR abort). The N9 coverage check below still runs and still
# fails closed as HARNESS_ERROR if this sizing is ever wrong for some other
# reason -- this is a bigger default, not a replacement for that check.
# Runs for ALL channels BEFORE any channel is configured/started
# (AUTORUN-9m.ps1 header, item B-B).
$itemsPerChannel = [Math]::Ceiling((($Minutes + $OnAirBoundMinutes + 13) * 60) / 30)
$schedulingStart = (Get-Date)
Write-SoakLog "scheduling $itemsPerChannel items/channel @ 30s each (sized for the ON_AIR bound's worst case: ceil((Minutes=$Minutes + OnAirBoundMinutes=$OnAirBoundMinutes + 13) * 60 / 30))"
$committedCountByChannel = @{}
foreach ($c in $channelSpecs) {
    $cursor = $schedulingStart.AddSeconds(-60)
    $scheduled = 0
    $committed = 0
    $firstGapIndex = $null
    for ($i = 0; $i -lt $itemsPerChannel; $i++) {
        $asset = $stagedAssets[$i % $stagedAssets.Count]
        $itemBody = [ordered]@{
            asset_id = $asset.id; channel_id = $c.id; mode = 'premiere'
            scheduled_at = $cursor.ToUniversalTime().ToString('o')
            duration_seconds = [int]$asset.duration_seconds
            notes = 'sandbox-lab local soak lane'
        }
        $itemR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/schedule" -BodyObj $itemBody -BearerToken $token
        $itemCommitted = $false
        if ($itemR.status -eq 201 -and $itemR.body_json -and $itemR.body_json.id) {
            $scheduled++
            $commitBody = [ordered]@{
                channel_id = $c.id
                occurrence_id = "sandboxsoak-$($c.id)-$scheduled"
                schedule_item_id = "$($itemR.body_json.id)"
            }
            $commitR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/playout/commit" -BodyObj $commitBody -BearerToken $token
            if ($commitR.status -eq 201) { $committed++; $itemCommitted = $true }
            else { Write-SoakLog "commit FAILED channel=$($c.id) item=$($itemR.body_json.id) status=$($commitR.status) body=$($commitR.body_raw) error=$($commitR.error)" }
        } else {
            Write-SoakLog "schedule item FAILED channel=$($c.id) asset=$($asset.id) status=$($itemR.status) body=$($itemR.body_raw) error=$($itemR.error)"
        }
        if (-not $itemCommitted -and $null -eq $firstGapIndex) { $firstGapIndex = $i }
        $cursor = $cursor.AddSeconds(30)
    }
    # Round-8 finding 8: coverage is only as good as the CONTIGUOUS run of
    # committed items from slot 0 -- a gap partway through (a failed
    # schedule/commit call) breaks continuity even if later slots
    # committed fine, so the channel's real, safe committed-coverage count
    # is capped at the first gap, not the total committed count.
    $contiguousCommitted = $(if ($null -ne $firstGapIndex) { $firstGapIndex } else { $committed })
    $committedCountByChannel[$c.id] = $contiguousCommitted
    Write-SoakLog "channel=$($c.id) schedule_items=$scheduled committed=$committed contiguous_from_slot0=$contiguousCommitted (target=$itemsPerChannel)"
}
# The N9 coverage check below is only as trustworthy as the WORST channel.
$minContiguousCommitted = $(if ($committedCountByChannel.Count -gt 0) { ($committedCountByChannel.Values | Measure-Object -Minimum).Minimum } else { 0 })
Write-SoakLog "schedule coverage: min contiguous committed items across all channels = $minContiguousCommitted (of target $itemsPerChannel)"

# NOW configure + start each channel. allow_software_fallback=$false: a
# fallback away from GStreamer must be a visible FAILURE for this soak, not
# a channel that quietly keeps looking ON_AIR on the wrong engine.
foreach ($c in $channelSpecs) {
    $cfg = [ordered]@{
        channel_id = $c.id; enabled = $true; auto_start = $true; allow_software_fallback = $false
        fill_policy = 'slate'; slate_message = 'CivicCast sandbox soak lane.'
        sinks = @(
            [ordered]@{ kind = 'udp-ts'; label = "sandboxsoak-$($c.id)"; uri = "udp://127.0.0.1:$($c.port)"; latency_ms = 2000; loudness_regime = 'inherit'; eas_tone_strip_enabled = $true }
        )
    }
    $cfgR = Invoke-CivicCastApi -Method 'Put' -Url "$Base/api/staff/egress/channels/$($c.id)/config" -BodyObj $cfg -BearerToken $token
    $configOk = ($cfgR.status -eq 200)
    if (-not $configOk) { Write-SoakLog "PUT config $($c.id) FAILED: status=$($cfgR.status) body=$($cfgR.body_raw) error=$($cfgR.error)" }
    $startOk = $false
    # Round-4 item 4: log both the EXACT body this lane sends to /commands
    # and the raw response body -- run 4's control-plane app.log showed
    # automation issuing 'start' for only ONE of the three channels
    # (education); this needs to distinguish "the lane sent 3 POSTs and the
    # product only acted on 1" from "the lane never sent all 3 in the first
    # place."
    $startBody = @{ action = 'start' }
    if ($configOk) {
        $startR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/egress/channels/$($c.id)/commands" -BodyObj $startBody -BearerToken $token
        $startOk = ($startR.status -eq 202)
        Write-SoakLog "start command $($c.id): sent_body=$($startBody | ConvertTo-Json -Compress) status=$($startR.status) response_body=$($startR.body_raw) error=$($startR.error)"
    } else {
        Write-SoakLog "start command $($c.id): SKIPPED (config PUT did not return 200)"
    }
    $summary.channels_started += [ordered]@{ channel_id = $c.id; config_ok = $configOk; start_ok = $startOk; start_sent_body = $startBody; start_response_body = $startR.body_raw }
}
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

# Round-5 item 2: the moment the start commands were sent -- the origin
# point for both time_to_on_air_s and first_state_row_s below (product
# metrics per item 59, not lane diagnostics: how long the shipped engine
# itself actually takes to bring a channel up, measured the same way on
# every run).
$channelsStartedUtc = (Get-Date).ToUniversalTime()

# Round-4 item 3 (item 59): raised from 6 to 10 minutes ($OnAirBoundMinutes,
# defined earlier alongside the schedule sizing) -- a fresh station measured
# >3 minutes to bring channels ON_AIR on REAL hardware per item 59, and
# Windows Sandbox's virtualized storage/CPU is slower still; run 4's own
# evidence shows config+start all succeeded (200/202) but the 6-minute bound
# expired before any channel reported ON_AIR, so this lane's own bound was
# the failure, not necessarily the product. Run 5 then measured state=null
# for ~8 of those minutes before all three channels went ON_AIR at poll #34
# (~8.5m) -- comfortably inside the new 10-minute bound, but not before
# proving the OLD 6-minute one wrong twice. Poll cadence stays 15s.
#
# Round-4 item 1: log the FULL per-channel state on every poll (state, pid,
# current_source_label, last_error) -- run 4 left no record of what state
# each channel actually reported during the 6-minute wait. Also log the raw
# response body on the FIRST poll and every time it changes, so the
# evidence has at least one verbatim example of the API's actual shape
# without spamming an identical line every 15s for 10 minutes.
#
# Round-5 item 3: while a channel's state field is null, ALSO poll its
# .../health?limit=1 and log it -- run 5 could not tell "the daemon simply
# hasn't initialized this channel's state row yet" (expected, transient)
# apart from "the daemon is dead and nothing will ever update this row"
# (a real product failure) purely from a null state field. Health gives an
# independent signal for the same channel during exactly that ambiguous
# window.
#
# Round-7 fix: the soak clock must start only once ALL THREE channels are
# ON_AIR (still bounded by $OnAirBoundMinutes from the start commands) --
# run 7 showed soak_start_utc getting set the instant the FIRST channel
# (education) went ON_AIR (~488.8s), while public and government had not
# yet reported anything, so their time_to_on_air_s were frozen at $null
# forever (the loop broke before they ever got a chance). $allOnAir (not
# $anyOnAir) now gates the break condition; $anyOnAir is kept only as a
# diagnostic (logged, never a gate).
#
# Round-5 item 2 / round-7 fix: track, per channel, the first poll where
# state is non-null (first_state_row_s) and the first poll where state is
# ON_AIR (time_to_on_air_s), both measured from $channelsStartedUtc. Now
# that the loop runs until EVERY channel has reached ON_AIR (or the bound
# expires), every channel's dictionary entry gets a real chance to be set
# as it actually happens, never frozen by an early break.
$onAirDeadline = (Get-Date).AddMinutes($OnAirBoundMinutes)
$anyOnAir = $false
$allOnAir = $false
$lastStateRawByChannel = @{}
$lastObservedStateByChannel = @{}
$firstStateRowUtcByChannel = @{}
$firstOnAirUtcByChannel = @{}
$pollN = 0
do {
    $pollN++
    foreach ($c in $channelSpecs) {
        try {
            $stR = Invoke-CivicCastApi -Method 'Get' -Url "$Base/api/staff/egress/channels/$($c.id)/state" -BearerToken $token -TimeoutSec 20
            # Round-8 finding 7: gate on $stR.ok ALONE, not
            # "$stR.ok -and $stR.body_json" -- a genuinely successful 200
            # response carrying a JSON `null` body (no state row yet, a
            # normal pre-initialization state) has body_json=$null
            # (ConvertFrom-Json turns the literal string "null" into
            # PowerShell $null, confirmed directly), which made the OLD
            # combined condition false and routed a real 200 into the
            # "FAILED" branch below -- which never runs the health probe,
            # so the one thing this branch exists to do (tell an
            # uninitialized state row apart from a dead daemon) never ran
            # on exactly the channels/polls that needed it most.
            if ($stR.ok) {
                $st = $(if ($stR.body_json) { $stR.body_json } else { [pscustomobject]@{ state = $null; pid = $null; current_source_label = $null; last_error = $null } })
                $lastObservedStateByChannel[$c.id] = $st.state
                Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id): state=$($st.state) pid=$($st.pid) src=$($st.current_source_label) err=$($st.last_error)"
                $rawNow = "$($stR.body_raw)"
                $rawBefore = $(if ($lastStateRawByChannel.ContainsKey($c.id)) { $lastStateRawByChannel[$c.id] } else { $null })
                if ($rawBefore -ne $rawNow) {
                    Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id) raw state body (first-seen or changed): $rawNow"
                    $lastStateRawByChannel[$c.id] = $rawNow
                }

                if ($null -eq $st.state) {
                    try {
                        $hlR = Invoke-CivicCastApi -Method 'Get' -Url "$Base/api/staff/egress/channels/$($c.id)/health?limit=1" -BearerToken $token -TimeoutSec 20
                        Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id): state is null -- health?limit=1 status=$($hlR.status) body=$($hlR.body_raw) error=$($hlR.error) (distinguishes an uninitialized state row from a dead daemon)"
                    } catch {
                        Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id): state is null -- health?limit=1 THREW $_"
                    }
                } else {
                    if (-not $firstStateRowUtcByChannel.ContainsKey($c.id)) {
                        $firstStateRowUtcByChannel[$c.id] = (Get-Date).ToUniversalTime()
                    }
                }

                if ($st.state -eq 'ON_AIR') {
                    $anyOnAir = $true
                    if (-not $firstOnAirUtcByChannel.ContainsKey($c.id)) {
                        $firstOnAirUtcByChannel[$c.id] = (Get-Date).ToUniversalTime()
                    }
                }
            } else {
                Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id): state read FAILED status=$($stR.status) body=$($stR.body_raw) error=$($stR.error)"
            }
        } catch {
            Write-SoakLog "ON_AIR poll #$pollN channel=$($c.id): state read THREW $_"
        }
    }
    $allOnAir = (@($channelSpecs | Where-Object { -not $firstOnAirUtcByChannel.ContainsKey($_.id) }).Count -eq 0)
    if ($allOnAir) { break }
    Start-Sleep -Seconds 15
} while ((Get-Date) -lt $onAirDeadline)

# Round-5 item 2: compute the per-channel product metrics regardless of
# whether every channel (or even any channel) reached ON_AIR -- a channel
# that never got a state row at all, or got a state row but never ON_AIR,
# is itself the finding; record $null rather than omit it.
$timeToOnAirSByChannel = [ordered]@{}
$firstStateRowSByChannel = [ordered]@{}
foreach ($c in $channelSpecs) {
    $firstStateRowSByChannel[$c.id] = $(if ($firstStateRowUtcByChannel.ContainsKey($c.id)) { [math]::Round(($firstStateRowUtcByChannel[$c.id] - $channelsStartedUtc).TotalSeconds, 1) } else { $null })
    $timeToOnAirSByChannel[$c.id] = $(if ($firstOnAirUtcByChannel.ContainsKey($c.id)) { [math]::Round(($firstOnAirUtcByChannel[$c.id] - $channelsStartedUtc).TotalSeconds, 1) } else { $null })
    Write-SoakLog "channel=$($c.id) product metrics: first_state_row_s=$($firstStateRowSByChannel[$c.id]) time_to_on_air_s=$($timeToOnAirSByChannel[$c.id])"
}
$summary.first_state_row_s = $firstStateRowSByChannel
$summary.time_to_on_air_s = $timeToOnAirSByChannel
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if (-not $allOnAir) {
    $stuckChannels = @($channelSpecs | Where-Object { -not $firstOnAirUtcByChannel.ContainsKey($_.id) })
    $notOnAirIds = @($stuckChannels | ForEach-Object { $_.id })
    Copy-StationLogs -Label 'onair-poll-timeout'
    # Round-8 finding 6: if every stuck channel's LAST OBSERVED state is
    # non-null (the daemon is demonstrably alive and reporting SOMETHING --
    # STARTING/TRANSITIONING/etc, just not ON_AIR yet within this bound),
    # that is a BOUND-SIZING problem, not a product failure -- run 7's
    # "public" channel reached ON_AIR at 645s, past the OLD 600s bound but
    # clearly still progressing the whole time. Only a channel that never
    # got a single non-null state row at all (truly silent, no signal
    # whatsoever) is treated as a genuine product FAIL.
    $stuckWithNonNullState = @($stuckChannels | Where-Object { $lastObservedStateByChannel.ContainsKey($_.id) -and $null -ne $lastObservedStateByChannel[$_.id] })
    $stuckTrulySilent = @($stuckChannels | Where-Object { -not ($lastObservedStateByChannel.ContainsKey($_.id) -and $null -ne $lastObservedStateByChannel[$_.id]) })
    if ($stuckTrulySilent.Count -eq 0 -and $stuckWithNonNullState.Count -gt 0) {
        $stateSummary = ($stuckWithNonNullState | ForEach-Object { "$($_.id)=$($lastObservedStateByChannel[$_.id])" }) -join ', '
        Write-HarnessErrorVerdictAndExit -Reason "ON_AIR bound (${OnAirBoundMinutes}m) expired while channel(s) were still progressing (non-null state, never silent): $stateSummary -- a lane sizing gap, not a product failure (see the ON_AIR poll #N lines in soak-log.txt for every channel's state/pid/src/err each cycle)"
    }
    Write-FailVerdictAndExit -Reason "not all channels reached ON_AIR within ${OnAirBoundMinutes} minutes of the start command -- soak clock not started; channel(s) never ON_AIR: $($notOnAirIds -join ', ') (truly silent, no state row ever observed: $(@($stuckTrulySilent | ForEach-Object { $_.id }) -join ', ')) (see the ON_AIR poll #N lines in soak-log.txt for every channel's state/pid/src/err each cycle, and logs\onair-poll-timeout\ for station/egress logs at the moment of failure)"
}

# --------------------------------------------------------------------------
# THE SOAK CLOCK STARTS HERE -- health OK AND channels configured/started
# AND ALL THREE confirmed ON_AIR (round-7 fix: was "at least one", which let
# the clock start with two channels still dark and their time_to_on_air_s
# frozen at $null forever). -Minutes means SOAK minutes measured
# from this instant, never wall-clock minutes from process launch (the
# install alone can take most of $InstallBoundMinutes). Recorded as
# soak_start_utc in every rollup and in VERDICT.json, and the ONLY thing the
# in-sandbox watchdog's post-soak phase anchors on.
# --------------------------------------------------------------------------
$SoakStartUtc = (Get-Date).ToUniversalTime()
$summary.soak_start_utc = $SoakStartUtc.ToString('o')

# N9: the schedule was laid BEFORE the ON_AIR poll (deliberately -- see
# section 4's header, AUTORUN-9m's B-B anti-reload-storm ordering), anchored
# at $schedulingStart, not at $SoakStartUtc, which is only known now --
# AFTER the (up to 12-minute) ON_AIR poll above. A slow poll eats directly
# into the margin between "content is scheduled through" and "the soak
# actually needs coverage through". Verify the schedule's own coverage_end
# still clears soak_start_utc + Minutes + a 3-minute margin; if a slow
# setup already ate that margin, this is a HARNESS problem (bad sizing),
# never a product FAIL -- the engine cannot be blamed for running out of
# scheduled content this script itself failed to lay down far enough out.
#
# Round-8 finding 8: coverage_end_utc is computed from $minContiguousCommitted
# (the worst channel's actual, contiguous-from-slot0 COMMITTED item count),
# never from $itemsPerChannel -- $itemsPerChannel is only the TARGET this
# script attempted; a schedule/commit API failure partway through means
# real coverage ends at that gap, not at the target, and reporting the
# target here would let a coverage shortfall silently pass this check.
$coverageEndUtc = $schedulingStart.ToUniversalTime().AddSeconds(-60 + ($minContiguousCommitted * 30))
$requiredCoverageUtc = $SoakStartUtc.AddSeconds(($Minutes * 60) + 180)
Write-SoakLog "schedule coverage check: coverage_end_utc=$($coverageEndUtc.ToString('o')) required (soak_start+Minutes+3m)=$($requiredCoverageUtc.ToString('o'))"
if ($coverageEndUtc -le $requiredCoverageUtc) {
    Write-HarnessErrorVerdictAndExit -Reason "schedule coverage_end_utc ($($coverageEndUtc.ToString('o'))) does not clear soak_start_utc+Minutes+3m ($($requiredCoverageUtc.ToString('o'))) -- the ON_AIR poll (schedulingStart=$($schedulingStart.ToUniversalTime().ToString('o'))) ate into the scheduled-content margin; this is a harness sizing defect, not a product failure"
}

Write-SoakLog "SOAK CLOCK STARTED (UTC): $($SoakStartUtc.ToString('o')) -- ALL THREE channels confirmed ON_AIR"
Write-PhaseMarker -Name 'SOAK-START.json' -Obj ([ordered]@{
    soak_start_utc = $SoakStartUtc.ToString('o')
    channels_started_utc = $channelsStartedUtc.ToString('o')
    first_state_row_s = $firstStateRowSByChannel
    time_to_on_air_s = $timeToOnAirSByChannel
    # Round-15 finding (a): the ON_AIR bound actually in force for this run
    # -- was a hardcoded 12, now -OnAirBoundMinutes (still defaults to 12).
    on_air_bound_minutes = $OnAirBoundMinutes
    seamless_reload = [bool]$SeamlessReload
    seamless_reload_verified = $summary.seamless_reload_verified
    # sandbox-lab lane follow-up A, item 1.
    captions_off_requested = [bool]$CaptionsOff
    captions_enabled = $summary.captions_enabled
    captions_off_verified = $summary.captions_off_verified
    # sandbox-lab lane follow-up A, item 3: guest-level, recorded once.
    cpu_count = [Environment]::ProcessorCount
    # sandbox-lab lane follow-up D.
    worker_env_requested = $summary.worker_env_requested
    worker_env_verified  = $summary.worker_env_verified
    gst_debug_file       = $summary.gst_debug_file
})
$script:soakStartWritten = $true
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

# --------------------------------------------------------------------------
# 5. Poll loop: every 60s for -Minutes SOAK minutes (from $SoakStartUtc, not
#    $RunStart), one cycle record per poll. tsp egress probe ported from
#    AUTORUN-3.ps1's Test-TsProof. Engine is determined by an OS process
#    CENSUS (AUTORUN-3.ps1:244-251), never read off the egress state API --
#    civiccast/egress/models.py:506-518 shows EgressStateRow carries no
#    `engine` field at all.
# --------------------------------------------------------------------------
function Test-TsProof {
    param([string]$TspExe, [int]$Port, [int]$Seconds, [string]$OutDir, [string]$Label)
    $result = [ordered]@{ verdict = 'not-run'; packets_total = $null; invalid_syncs = $null; transport_errors = $null; discontinuities = $null; tsp_output_tail = $null }
    if (-not $TspExe -or -not (Test-Path $TspExe)) { $result.verdict = 'not-run: tsp.exe not found'; return $result }
    $report = Join-Path $OutDir "tsduck-$Label-report.json"
    $tspArgs = @('-I', 'ip', "$Port", '--buffer-size', '16777216', '-P', 'until', '--seconds', "$Seconds", '-P', 'analyze', '--json', '--output-file', $report, '-O', 'drop')
    # Round-10 finding 10 (LOW): tsp's own stdout/stderr were redirected to
    # temp files that were never read back OR deleted -- silent evidence
    # loss on every non-pass verdict (no visibility into WHY tsp failed
    # beyond the bare verdict string), plus a slow accumulation of tiny
    # abandoned temp files across a long soak. Capture the paths so the
    # `finally` block below can read the last 20 lines of each into the
    # result on any non-'pass' verdict, and ALWAYS delete them afterward
    # regardless of verdict.
    $stdoutFile = [System.IO.Path]::GetTempFileName()
    $stderrFile = [System.IO.Path]::GetTempFileName()
    try {
        try {
            $proc = Start-Process -FilePath $TspExe -ArgumentList $tspArgs -PassThru -NoNewWindow -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
            $null = $proc.Handle   # PS 5.1: ExitCode is $null unless the handle was cached before exit.
            $exited = $proc.WaitForExit(($Seconds + 20) * 1000)
            if (-not $exited) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                $result.verdict = 'fail-timed-out'
                return $result
            }
            $proc.Refresh()
            if ($proc.ExitCode -ne 0) { $result.verdict = "fail-exit-$($proc.ExitCode)"; return $result }
        } catch { $result.verdict = "error: $_"; return $result }
        if (-not (Test-Path $report)) { $result.verdict = 'fail-no-report'; return $result }
        try { $j = Get-Content $report -Raw | ConvertFrom-Json } catch { $result.verdict = 'fail-unparsable-report'; return $result }
        $ts = $j.ts
        if (-not $ts) { $result.verdict = 'fail-no-ts-section'; return $result }
        $result.packets_total = $ts.packets
        $result.invalid_syncs = $ts.invalid_syncs
        $result.transport_errors = $ts.transport_errors
        $result.discontinuities = $(if ($null -ne $ts.pcr_discontinuities) { $ts.pcr_discontinuities } else { $ts.discontinuities })
        if (-not $result.packets_total -or [int]$result.packets_total -le 0) { $result.verdict = 'fail-zero-packets'; return $result }
        $clean = ([int]$result.invalid_syncs -eq 0) -and ([int]$result.transport_errors -eq 0) -and ([int]$result.discontinuities -eq 0)
        $result.verdict = $(if ($clean) { 'pass' } else { 'fail-stream-errors' })
        return $result
    } finally {
        if ($result.verdict -ne 'pass') {
            try {
                $outTail = @(Get-Content -Path $stdoutFile -Tail 20 -ErrorAction SilentlyContinue)
                $errTail = @(Get-Content -Path $stderrFile -Tail 20 -ErrorAction SilentlyContinue)
                $result.tsp_output_tail = [ordered]@{ stdout = $outTail; stderr = $errTail }
            } catch { }
        }
        Remove-Item -Path $stdoutFile -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

# Round-9 finding N4 (MEDIUM): the interleaved sampling fix (round-8
# finding 2) turned engine resolution into 9 HTTP + up to 12 Win32_Process
# queries PER CYCLE (one CIM query per sample -- 3 channels x 3 passes --
# PLUS a redundant re-resolution for the row's own channel, PLUS
# Get-GlobalEngineCensus's own separate query). CPU starvation is this
# box's own measured soak-failure mode, so adding WMI load specifically to
# a lane whose job is to detect that starvation is directly
# counterproductive. Get-GstWorkerPidMap makes exactly ONE Win32_Process
# query per PASS (one pass = one inner sampling loop over all 3 channels),
# caching every currently-running gst-worker pid; Resolve-EngineForPid then
# resolves each of that pass's 3 samples from the cached map (a cheap
# Get-Process -Id lookup, not CIM, only for the rare "pid not a known gst
# worker" case). With 3 passes per heavy cycle, this caps CIM usage at
# ~3 queries/cycle -- Get-GlobalEngineCensus reuses the LAST pass's map
# instead of issuing its own 4th query.
function Get-GstWorkerPidMap {
    $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'egress[\\/]gst[\\/]worker\.py' })
    $map = @{}
    foreach ($p in $procs) { $map[[int]$p.ProcessId] = $true }
    return $map
}

function Resolve-EngineForPid {
    <#
      Engine resolution, ported from AUTORUN-3.ps1:244-251's logic but now
      resolving against an already-fetched $GstWorkerPidMap instead of
      querying Win32_Process per pid. EgressStateRow has no `engine` field
      (civiccast/egress/models.py:506-518), so this is inferred from the OS
      process itself regardless.
    #>
    param([Nullable[int]]$ProcId, $GstWorkerPidMap)
    if (-not $ProcId) { return $null }
    if ($GstWorkerPidMap.ContainsKey($ProcId)) { return 'gstreamer' }
    try {
        $p = Get-Process -Id $ProcId -ErrorAction Stop
        if ($p.ProcessName -match '^ffmpeg') { return 'ffmpeg-fallback' }
        # Round-10 finding 7 (MEDIUM): $GstWorkerPidMap is snapshotted ONCE
        # per PASS (round-9 finding N4) -- a worker relaunched (new pid)
        # mid-pass, after that snapshot was taken but before THIS sample,
        # is alive (Get-Process succeeds) yet absent from the map, and
        # previously fell straight through to "unknown:<name>" -- a false
        # FAIL (engine != gstreamer) for a channel that is actually fine.
        # Before giving up, re-resolve JUST this one pid with a single
        # TARGETED Win32_Process query (never a full re-scan) -- rare
        # enough (only a mid-pass relaunch race) that one extra CIM query
        # here does not reintroduce the load round-9 N4 was fixing.
        if ($p.ProcessName -match '^python') {
            try {
                $reResolved = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
                if ($reResolved -and $reResolved.CommandLine -match 'egress[\\/]gst[\\/]worker\.py') { return 'gstreamer' }
            } catch { }
        }
        return "unknown:$($p.ProcessName)"
    } catch {
        return $null
    }
}

# M8 leftover: a GLOBAL process census across all three channels, ported
# from AUTORUN-3.ps1:244-251 ($gst/$ff/$gstWorkers). Diagnostic only -- it
# never feeds the per-channel verdict (Resolve-EngineForPid above already
# does that, keyed to each channel's own worker pid) -- but a global
# ffmpeg.exe count that goes to 0 unexpectedly, or a gst-worker count that
# doesn't match the number of ON_AIR channels, is exactly the kind of cross-
# channel signal a per-channel-only view can miss. Round-9 finding N4:
# reuses the caller's already-fetched $GstWorkerPidMap instead of issuing
# its own separate Win32_Process query.
function Get-GlobalEngineCensus {
    param($GstWorkerPidMap)
    $ffmpegCount = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
    return [ordered]@{
        ffmpeg_processes = $ffmpegCount
        gst_worker_processes = $GstWorkerPidMap.Count
        gst_worker_pids = @($GstWorkerPidMap.Keys)
    }
}

# --------------------------------------------------------------------------
# Round-8: the restart/relaunch CLASSIFICATION machinery (ring sampling,
# planned-vs-unplanned classification, recovery tracking) now lives in
# sandbox-lab/scripts/RestartClassifier.ps1 -- extracted so it is
# unit-testable (Test-RestartClassifier.ps1) with synthetic (utc,state,pid)
# tuples, matching SoakVerdict.ps1/HostLiveness.ps1's own pattern. See that
# file's header for the $Pid-shadows-$PID bug this extraction fixes (round-8
# finding 1: the ring was silently never populated, so every pid change --
# including run 7's genuinely planned restart -- was misclassified
# unplanned_relaunch) and for the exemption-window fix (finding 3).
# --------------------------------------------------------------------------
. (Join-Path 'C:\CivicCastSoakScripts' 'RestartClassifier.ps1')
$restartCtx = New-RestartClassifierContext -RestartTrackingMaxSeconds 300

# Round-10 finding 5 (MEDIUM, "the important one"): feed the daemon's own
# app log into $restartCtx.LogRing so Register-ChannelSample's log-based
# classification (Test-PlannedRestartFromLog, RestartClassifier.ps1) has
# real data -- see that file's header for the full citation of the log
# line format and why it is the PRIMARY signal. Read incrementally (only
# lines appended since the last read, tracked as a running line count) so
# a 15-minute soak never re-parses the whole file every pass; a missing or
# unreadable log file is not an error here -- Update-DaemonLogRing simply
# adds nothing, and Test-PlannedRestartFromLog correctly reports $null
# (no evidence) for every channel in that case, so Register-ChannelSample
# falls back to the sample-ring signal with log_evidence='missing'.
$script:daemonLogPath = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
# Round-11 finding 2 (HIGH): a LINE-COUNT-based offset (the round-10
# version) freezes forever the moment the log rotates -- service.py:221's
# _DurableRotatingFileHandler at service.py:296-298 is configured 10 MiB x
# 10, so any soak long/chatty enough to fill 10 MiB starts a FRESH file at
# the SAME path; a line count that only ever grows never notices the
# fresh file is smaller than what was already "consumed", so every new
# line the fresh file writes is silently skipped forever after. Tracked
# instead as a BYTE offset into the file, reset to 0 whenever rotation is
# detected (the file's length shrank, OR its first line changed -- length
# alone is not quite enough evidence if a fresh file happens to grow past
# the old offset again before the next read; the first line changing is
# unambiguous, since rotation always starts a brand-new file). Reads ONLY
# the new bytes via a seek, never the whole file.
# Round-12 finding 7 (LOW): starting the offset at 0 means the FIRST
# ingestion pass reads the entire pre-existing log -- everything the
# install/first-admin/schedule/channel-start phases already logged BEFORE
# this soak's own clock started -- and stamps it all with THIS pass's
# -ObservedUtc ("now"), which is wrong on two counts: those lines are not
# actually fresh (they predate the soak, sometimes by many minutes), and
# ring entries and their pids belong to a channel-start sequence this
# soak's classification has no business reasoning about at all. Start the
# offset at the file's CURRENT length instead -- only lines appended from
# this point forward (soak-clock start) are ever ingested.
$script:daemonLogOffsetBytes = 0
try {
    $script:daemonLogOffsetBytes = (Get-Item -Path $script:daemonLogPath -ErrorAction Stop).Length
} catch {
    $script:daemonLogOffsetBytes = 0
}
$script:daemonLogFirstLineText = $null
# sandbox-lab lane follow-up A, item 2's -SeamlessReload cross-check:
# channel ids the daemon log confirmed "Seamless content-reload armed" for
# at least once (populated in Update-DaemonLogRing below via
# DaemonLogPatterns.ps1's $DaemonReloadArmedRegex). Only ever read at the
# very end of the run (see the final-verdict section) to decide whether
# any armed channel's worker-stdout reload_committed_count stayed 0 for
# the whole soak.
$script:reloadArmedChannels = @{}
# Round-14 finding 6 (MEDIUM): the log-line regex, the reload-abort regex,
# the discard-echo exclusion regex, and the "state read failed: ..."
# string formula all now live in DaemonLogPatterns.ps1, dot-sourced here
# and by Test-RestartClassifier.ps1 -- see that file's header for why
# (a test file's OWN hand-typed copy of these literals could silently
# drift from the driver's without either file's tests ever catching it).
. (Join-Path 'C:\CivicCastSoakScripts' 'DaemonLogPatterns.ps1')

function Update-DaemonLogRing {
    <#
      .PARAMETER MeasuredCyclePeriodSeconds
      Round-13 finding 5 (HIGH): sizes RestartClassifier.ps1's per-channel
      LogRing (Add-LogRingSample's -MaxRingSize) from the ACTUAL measured
      cycle period, not a fixed 30 -- see that function's own doc for why
      a fixed 30-line cap (~60s of real ~2s-tick daemon traffic) risks
      evicting the OLD pid's anchor line before this function is even
      called again. Default 60 matches the driver's own pre-first-cycle
      default.
    #>
    param($Context, [double]$MeasuredCyclePeriodSeconds = 60)
    $logRingSize = [Math]::Max(60, ([Math]::Ceiling($MeasuredCyclePeriodSeconds / 2) * 2) + 30)
    if (-not (Test-Path $script:daemonLogPath)) { return }

    try {
        $length = (Get-Item -Path $script:daemonLogPath -ErrorAction Stop).Length
    } catch { return }

    $firstLineNow = $null
    try {
        $fsProbe = [System.IO.File]::Open($script:daemonLogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $srProbe = New-Object System.IO.StreamReader($fsProbe)
            $firstLineNow = $srProbe.ReadLine()
        } finally { $fsProbe.Close() }
    } catch { }

    $rotated = ($length -lt $script:daemonLogOffsetBytes) -or
        ($null -ne $script:daemonLogFirstLineText -and $null -ne $firstLineNow -and $firstLineNow -ne $script:daemonLogFirstLineText)
    if ($rotated) {
        Write-SoakLog "daemon log rotation detected (service.py's 10 MiB x 10 rotating handler) -- resetting read offset to 0"
        $script:daemonLogOffsetBytes = 0
    }
    $script:daemonLogFirstLineText = $firstLineNow

    if ($script:daemonLogOffsetBytes -ge $length) { return }

    try {
        $fs = [System.IO.File]::Open($script:daemonLogPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $fs.Seek($script:daemonLogOffsetBytes, [System.IO.SeekOrigin]::Begin) | Out-Null
            $bytesToRead = $length - $script:daemonLogOffsetBytes
            $buffer = New-Object byte[] $bytesToRead
            $readCount = $fs.Read($buffer, 0, $bytesToRead)
            $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $readCount)
        } finally { $fs.Close() }
    } catch { return }

    # A torn final line (no trailing newline -- the writer had not
    # finished it yet) must NOT be consumed: leave it for the next pass
    # once it is complete, rather than misparsing a half-written line or
    # missing a genuine match that wasn't fully on disk yet.
    $lastNewlineIdx = $text.LastIndexOf("`n")
    if ($lastNewlineIdx -lt 0) { return }
    $completeText = $text.Substring(0, $lastNewlineIdx + 1)
    $script:daemonLogOffsetBytes += [System.Text.Encoding]::UTF8.GetByteCount($completeText)

    $nowUtc = (Get-Date).ToUniversalTime()
    foreach ($line in ($completeText -split "`r?`n")) {
        if (-not $line) { continue }
        $m = $script:DaemonLogLineRegex.Match($line)
        if ($m.Success) {
            Add-LogRingSample -Context $Context -ChannelId $m.Groups['ch'].Value -State $m.Groups['state'].Value -LastError $m.Groups['err'].Value -LogPid $m.Groups['pid'].Value -ObservedUtc $nowUtc -MaxRingSize $logRingSize
            continue
        }
        $ra = $script:DaemonReloadAbortRegex.Match($line)
        if ($ra.Success) {
            # Round-14 finding 5 (MEDIUM): the double-count this exclusion
            # was originally written to guard against does not actually
            # occur in practice (see DaemonLogPatterns.ps1's own header for
            # the measured explanation) -- kept anyway as a narrow,
            # defensive exclusion in case that ever changes, now anchored
            # on the echo's OWN FIXED shape rather than a bare "discarded:"
            # substring search (which could wrongly exclude a real abort
            # whose own reason text happened to contain that word).
            if (-not $script:DaemonReloadDiscardEchoRegex.IsMatch($line)) {
                Add-ReloadAbortSample -Context $Context -ChannelId $ra.Groups['ch'].Value -Reason $ra.Groups['reason'].Value
                Write-SoakLog "reload_aborted channel=$($ra.Groups['ch'].Value) reason=$($ra.Groups['reason'].Value)"
            }
        }
        # sandbox-lab lane follow-up A, item 2's -SeamlessReload cross-check
        # (see $script:reloadArmedChannels' own init comment above).
        $armed = $script:DaemonReloadArmedRegex.Match($line)
        if ($armed.Success) {
            $script:reloadArmedChannels[$armed.Groups['ch'].Value] = $true
            Write-SoakLog "reload_armed channel=$($armed.Groups['ch'].Value) reload_id=$($armed.Groups['reload_id'].Value)"
        }
    }
}

# --------------------------------------------------------------------------
# sandbox-lab lane follow-up A, item 2: per-channel worker-stdout parsing.
# Same incremental-byte-offset, rotation-safe read pattern as
# Update-DaemonLogRing above, one instance PER CHANNEL (each channel has
# its own gst-worker.stdout.log, unlike the single shared daemon app log).
# ConvertFrom-WorkerStdoutLines (WorkerStdoutParser.ps1, dot-sourced near
# the top of this file) does the actual line-matching; this function does
# only the file I/O and cumulative bookkeeping around it.
# --------------------------------------------------------------------------
$script:workerStdoutOffsetByChannel = @{}
$script:workerStdoutFirstLineByChannel = @{}
$script:workerStdoutCountsByChannel = @{}
# Round-follow-up-B finding 2b: separate offset/first-line bookkeeping for
# gst-worker.stderr.log, mirroring the stdout tracking above -- the two
# files rotate independently and are read by two different functions
# (Update-WorkerStdoutCounters / Update-WorkerStderrCounters), so they need
# their own cursors.
$script:workerStderrOffsetByChannel = @{}
$script:workerStderrFirstLineByChannel = @{}
foreach ($c0 in $channelSpecs) {
    $script:workerStdoutCountsByChannel[$c0.id] = [ordered]@{
        reload_committed_count   = 0
        reload_aborted_count     = 0
        reload_aborted_reasons   = @()
        worker_stall_count       = 0
        worker_stall_stderr_count = 0
    }
}

function Update-WorkerStdoutCounters {
    param([string]$ChannelId)
    # Round-2 finding 6: resolved against the SAME shared candidate list
    # Copy-StationLogs uses (script-scope $EgressWorkDirCandidates, near
    # the top of this file), at call time -- never cached from an
    # earlier-run resolution, same robustness principle as Copy-StationLogs
    # itself already had.
    $egressRoot = $script:EgressWorkDirCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $egressRoot) { return }
    $path = Join-Path $egressRoot "$ChannelId\logs\gst-worker.stdout.log"
    if (-not (Test-Path $path)) { return }
    try { $length = (Get-Item -Path $path -ErrorAction Stop).Length } catch { return }

    $firstLineNow = $null
    try {
        $fsProbe = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $srProbe = New-Object System.IO.StreamReader($fsProbe)
            $firstLineNow = $srProbe.ReadLine()
        } finally { $fsProbe.Close() }
    } catch { }

    $prevOffset = $(if ($script:workerStdoutOffsetByChannel.ContainsKey($ChannelId)) { $script:workerStdoutOffsetByChannel[$ChannelId] } else { 0 })
    $prevFirstLine = $(if ($script:workerStdoutFirstLineByChannel.ContainsKey($ChannelId)) { $script:workerStdoutFirstLineByChannel[$ChannelId] } else { $null })
    # Same rotation heuristic as Update-DaemonLogRing: length shrank, or the
    # first line changed while a previous first-line was already known.
    $rotated = ($length -lt $prevOffset) -or
        ($null -ne $prevFirstLine -and $null -ne $firstLineNow -and $firstLineNow -ne $prevFirstLine)
    if ($rotated) {
        Write-SoakLog "worker stdout log rotation detected for channel=$ChannelId -- resetting read offset to 0"
        $prevOffset = 0
    }
    $script:workerStdoutFirstLineByChannel[$ChannelId] = $firstLineNow

    if ($prevOffset -ge $length) {
        $script:workerStdoutOffsetByChannel[$ChannelId] = $prevOffset
        return
    }

    try {
        $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $fs.Seek($prevOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
            $bytesToRead = $length - $prevOffset
            $buffer = New-Object byte[] $bytesToRead
            $readCount = $fs.Read($buffer, 0, $bytesToRead)
            # Round-2 finding 7 (INFO, no change needed): .UTF8 here is
            # correct without a BOM check -- strategy.py:688 opens
            # gst-worker.stdout.log with `.open("a", encoding="utf-8")`,
            # which never writes a BOM, and a mid-file read (any offset
            # other than 0) would never see one anyway.
            $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $readCount)
        } finally { $fs.Close() }
    } catch { return }

    # A torn final line (writer hasn't finished it yet) is left for the
    # next pass -- same discipline as Update-DaemonLogRing.
    $lastNewlineIdx = $text.LastIndexOf("`n")
    if ($lastNewlineIdx -lt 0) {
        $script:workerStdoutOffsetByChannel[$ChannelId] = $prevOffset
        return
    }
    $completeText = $text.Substring(0, $lastNewlineIdx + 1)
    $script:workerStdoutOffsetByChannel[$ChannelId] = $prevOffset + [System.Text.Encoding]::UTF8.GetByteCount($completeText)

    $newLines = @($completeText -split "`r?`n" | Where-Object { $_ })
    if ($newLines.Count -eq 0) { return }
    $parsed = ConvertFrom-WorkerStdoutLines -Lines $newLines

    $counts = $script:workerStdoutCountsByChannel[$ChannelId]
    $counts.reload_committed_count += $parsed.reload_committed_count
    $counts.reload_aborted_count += $parsed.reload_aborted_count
    $counts.reload_aborted_reasons = @($counts.reload_aborted_reasons + $parsed.reload_aborted_reasons)
    $counts.worker_stall_count += $parsed.worker_stall_count

    if ($parsed.reload_committed_count -gt 0) {
        Write-SoakLog "worker stdout channel=${ChannelId}: reload committed x$($parsed.reload_committed_count) (cumulative=$($counts.reload_committed_count))"
    }
    foreach ($reason in $parsed.reload_aborted_reasons) {
        Write-SoakLog "worker stdout channel=${ChannelId}: reload aborted: $reason"
    }
    if ($parsed.worker_stall_count -gt 0) {
        Write-SoakLog "worker stdout channel=${ChannelId}: stall x$($parsed.worker_stall_count) (cumulative=$($counts.worker_stall_count))"
    }
}

function Update-WorkerStderrCounters {
    <#
      .SYNOPSIS
      Round-follow-up-B finding 2b: the stderr-side counterpart to
      Update-WorkerStdoutCounters immediately above -- same incremental-
      byte-offset, rotation-safe read pattern, against
      <egress_work_dir>\<channel>\logs\gst-worker.stderr.log instead of
      gst-worker.stdout.log. Feeds ConvertFrom-WorkerStderrLines
      (WorkerStdoutParser.ps1) the newly-appended lines and accumulates
      worker_stall_stderr_count onto the SAME per-channel counts object
      Update-WorkerStdoutCounters writes (so both fields ride together in
      every row/rollup/VERDICT.json reader without a second lookup).

      Exists to close the blind spot documented in WorkerStdoutParser.ps1's
      own header: a stall whose teardown itself hangs never reaches
      worker.py's WORKER_RESULT stdout receipt (engine.py's
      `stop(force_exit_on_hang=True)` calls `os._exit(70)` first), but the
      stall watchdog's own "CTRL stall: ..." stderr line is written before
      teardown is even attempted, so it survives that exit.
    #>
    param([string]$ChannelId)
    $egressRoot = $script:EgressWorkDirCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $egressRoot) { return }
    $path = Join-Path $egressRoot "$ChannelId\logs\gst-worker.stderr.log"
    if (-not (Test-Path $path)) { return }
    try { $length = (Get-Item -Path $path -ErrorAction Stop).Length } catch { return }

    $firstLineNow = $null
    try {
        $fsProbe = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $srProbe = New-Object System.IO.StreamReader($fsProbe)
            $firstLineNow = $srProbe.ReadLine()
        } finally { $fsProbe.Close() }
    } catch { }

    $prevOffset = $(if ($script:workerStderrOffsetByChannel.ContainsKey($ChannelId)) { $script:workerStderrOffsetByChannel[$ChannelId] } else { 0 })
    $prevFirstLine = $(if ($script:workerStderrFirstLineByChannel.ContainsKey($ChannelId)) { $script:workerStderrFirstLineByChannel[$ChannelId] } else { $null })
    $rotated = ($length -lt $prevOffset) -or
        ($null -ne $prevFirstLine -and $null -ne $firstLineNow -and $firstLineNow -ne $prevFirstLine)
    if ($rotated) {
        Write-SoakLog "worker stderr log rotation detected for channel=$ChannelId -- resetting read offset to 0"
        $prevOffset = 0
    }
    $script:workerStderrFirstLineByChannel[$ChannelId] = $firstLineNow

    if ($prevOffset -ge $length) {
        $script:workerStderrOffsetByChannel[$ChannelId] = $prevOffset
        return
    }

    try {
        $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        try {
            $fs.Seek($prevOffset, [System.IO.SeekOrigin]::Begin) | Out-Null
            $bytesToRead = $length - $prevOffset
            $buffer = New-Object byte[] $bytesToRead
            $readCount = $fs.Read($buffer, 0, $bytesToRead)
            $text = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $readCount)
        } finally { $fs.Close() }
    } catch { return }

    $lastNewlineIdx = $text.LastIndexOf("`n")
    if ($lastNewlineIdx -lt 0) {
        $script:workerStderrOffsetByChannel[$ChannelId] = $prevOffset
        return
    }
    $completeText = $text.Substring(0, $lastNewlineIdx + 1)
    $script:workerStderrOffsetByChannel[$ChannelId] = $prevOffset + [System.Text.Encoding]::UTF8.GetByteCount($completeText)

    $newLines = @($completeText -split "`r?`n" | Where-Object { $_ })
    if ($newLines.Count -eq 0) { return }
    $parsedErr = ConvertFrom-WorkerStderrLines -Lines $newLines

    $counts = $script:workerStdoutCountsByChannel[$ChannelId]
    if (-not $counts) { return }
    $counts.worker_stall_stderr_count += $parsedErr.worker_stall_stderr_count
    if ($parsedErr.worker_stall_stderr_count -gt 0) {
        Write-SoakLog "worker stderr channel=${ChannelId}: stall x$($parsedErr.worker_stall_stderr_count) (cumulative=$($counts.worker_stall_stderr_count))"
    }
}

# --------------------------------------------------------------------------
# sandbox-lab lane follow-up A, item 3: per-process CPU instrumentation.
# Get-Process's own `.CPU` property is CUMULATIVE processor time since the
# process started, not a rate -- CpuSampler.ps1's Get-CpuDeltaSample turns
# two cumulative samples into a per-interval delta ($null on first sighting
# of a pid, or if a reused pid would otherwise produce a nonsensical
# negative delta). $script:prevCpuSecondsByPid is pruned each cycle to pids
# actually seen that cycle so it cannot grow unbounded across a long soak.
# --------------------------------------------------------------------------
$script:prevCpuSecondsByPid = @{}

function Get-CycleProcessCpuSamples {
    <#
      .SYNOPSIS
      One sample per python.exe/pythonw.exe/pythonservice.exe/ffmpeg.exe
      process currently running in the guest (gst-worker processes ARE
      python.exe processes running egress/gst/worker.py, per
      Get-GstWorkerPidMap's own CommandLine match -- already covered here,
      not queried separately).

      Round-2 finding 3 (MEDIUM): two fixes to the round-1 version --
      (1) widened the Get-Process name filter from just 'python','ffmpeg'
      to also include 'pythonw' and 'pythonservice' (station_runtime.py:369
      permits all three as the native service's own Python host executable
      -- the round-1 filter silently dropped rows for whichever of these
      the install actually uses, most notably 'pythonservice' -- pywin32's
      own service host, per civiccast/native/supervisor/install_layout.py:6/25
      -- which is ALWAYS the process actually running CivicCastSupervisor);
      (2) every row now also carries a `role` label (Get-ProcessRoleLabel,
      CpuSampler.ps1) so a human reading VERDICT.json/a cycle JSON can tell
      gst-worker:<channel_id> apart from the control-plane child and the
      service supervisor without cross-referencing a separate pid list --
      built from pid facts THIS pass already holds ($GstWorkerPidMap,
      already-fetched by the caller; $PidToChannelId, built by the caller
      from this SAME pass's own per-channel state-sample pids), never an
      extra CIM query.

      .PARAMETER GstWorkerPidMap
      This pass's already-fetched Get-GstWorkerPidMap result -- reused,
      never re-queried (same discipline as Resolve-EngineForPid's own
      round-9 finding N4).

      .PARAMETER PidToChannelId
      Hashtable {[int]pid -> [string]channel_id} built by the caller from
      this pass's own $samplesThisPass (each channel's sample.pid) -- see
      the call site below.
    #>
    param(
        $GstWorkerPidMap = @{},
        $PidToChannelId = @{}
    )
    $seenPids = @{}
    $samples = @()
    $procs = @()
    try { $procs = @(Get-Process -Name 'python', 'pythonw', 'pythonservice', 'ffmpeg' -ErrorAction SilentlyContinue) } catch { $procs = @() }
    foreach ($p in $procs) {
        $seenPids[$p.Id] = $true
        $cpuNow = $(try { $p.CPU } catch { $null })
        $wsNow = $(try { $p.WorkingSet64 } catch { $null })
        $prev = $(if ($script:prevCpuSecondsByPid.ContainsKey($p.Id)) { $script:prevCpuSecondsByPid[$p.Id] } else { $null })
        $delta = Get-CpuDeltaSample -CpuSecondsNow $cpuNow -CpuSecondsPrev $prev
        if ($null -ne $cpuNow) { $script:prevCpuSecondsByPid[$p.Id] = $cpuNow }
        $samples += [ordered]@{
            pid = $p.Id
            process_name = $p.ProcessName
            role = (Get-ProcessRoleLabel -ProcessName $p.ProcessName -ProcessId $p.Id -GstWorkerPidMap $GstWorkerPidMap -PidToChannelId $PidToChannelId)
            cpu_seconds_delta = $delta
            working_set_mb = (ConvertTo-WorkingSetMb -WorkingSetBytes $wsNow)
        }
    }
    $stalePids = @($script:prevCpuSecondsByPid.Keys | Where-Object { -not $seenPids.ContainsKey($_) })
    foreach ($sp in $stalePids) { $script:prevCpuSecondsByPid.Remove($sp) }
    return $samples
}

function Get-CpuTotalPercent {
    <#
      .SYNOPSIS
      Guest-wide `\Processor(_Total)\% Processor Time`, best-effort ($null
      on any failure -- performance counters can be disabled/unavailable on
      some images, and this must never fail the run over a diagnostic-only
      reading).
    #>
    try {
        $c = Get-Counter -Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop
        return [math]::Round($c.CounterSamples[0].CookedValue, 1)
    } catch {
        return $null
    }
}

function Get-ChannelStateSample {
    <#
      Round-8 finding 7 (medium): `$stR.ok -and $stR.body_json` treated a
      genuinely successful 200 response carrying a JSON `null` body (no
      state row exists for this channel yet -- a normal, expected state
      before the daemon has posted anything) the SAME as a real read
      failure, because ConvertFrom-Json turns the literal string "null"
      into PowerShell $null (confirmed directly), which is falsy in the
      `-and` check -- so this fell into the "FAILED" branch and stamped
      last_error="state read failed: status=200 error=" on a request that
      had not failed at all. Status 200 with a null/empty body is now its
      own ok=true, state=$null outcome; only a non-2xx status or a thrown
      exception is a real read failure.

      Round-13 finding 1 (BLOCKING): the "state read failed: status=X
      error=Y" text that RestartClassifier.ps1's read-failure filter
      matches on (`-like 'state read failed*'`) was previously built ONLY
      at the cycle-row-construction call site further down in this file
      ("$row = ... last_error = $(if ($sample.ok) ... else "state read
      failed: ...")"). But Invoke-ChannelSampleAndRegister passes
      `-LastError $Sample.last_error` straight from THIS function's own
      ok=false branches, which returned last_error=$null, never that
      string -- so the real driver fed RestartClassifier.ps1 a $null
      last_error on every dropped HTTP read, and the read-failure filter
      (both Test-PlannedRestartSignal's ignore-on-walk-back and
      SoakVerdict.ps1's ON_AIR-check exclusion) never matched anything in
      production. A single transient network blip during a genuinely
      planned rollover could misclassify the whole run FAIL. Fixed by
      building the string ONCE here (via DaemonLogPatterns.ps1's
      New-StateReadFailureLastError, round-14 finding 6 -- shared with
      Test-RestartClassifier.ps1 instead of each keeping its own copy of
      the formula), in the ok=false branches themselves, so every consumer
      reads the exact same value; the row construction below no longer
      rebuilds it separately.
    #>
    param([string]$ChannelId)
    try {
        $stR = Invoke-CivicCastApi -Method 'Get' -Url "$Base/api/staff/egress/channels/$ChannelId/state" -BearerToken $token -TimeoutSec 20
        if ($stR.ok -and $stR.body_json) {
            $st = $stR.body_json
            return [pscustomobject]@{
                ok = $true; state = $st.state
                pid = $(if ($st.pid) { [int]$st.pid } else { $null })
                updated_at = $st.updated_at; last_error = $st.last_error
                status = $stR.status; body_raw = $stR.body_raw; error = $stR.error
            }
        }
        if ($stR.ok) {
            # HTTP 2xx but no parseable body_json (e.g. a literal JSON
            # `null`, or an empty body) -- no state row yet, NOT a failure.
            return [pscustomobject]@{ ok = $true; state = $null; pid = $null; updated_at = $null; last_error = $null; status = $stR.status; body_raw = $stR.body_raw; error = $null }
        }
        return [pscustomobject]@{ ok = $false; state = $null; pid = $null; updated_at = $null; last_error = (New-StateReadFailureLastError -Status $stR.status -ErrorText $stR.error); status = $stR.status; body_raw = $stR.body_raw; error = $stR.error }
    } catch {
        return [pscustomobject]@{ ok = $false; state = $null; pid = $null; updated_at = $null; last_error = (New-StateReadFailureLastError -Status $null -ErrorText $_); status = $null; body_raw = $null; error = "$_" }
    }
}

function Invoke-ChannelSampleAndRegister {
    <#
      Thin wrapper: takes one Get-ChannelStateSample result, resolves its
      engine against an already-fetched $GstWorkerPidMap (round-9 finding
      N4 -- never its own fresh Win32_Process query), registers it against
      $restartCtx (round-9 finding N7: -LastError now wired from the
      sample's own last_error field, feeding
      Test-PlannedRestartSignal's crash-signal veto -- it was previously
      never passed at all, so that veto was inert), and returns the
      resolved engine so the caller can reuse it for the cycle row instead
      of resolving it a second time. Logs a restart
      DETECTED/RECOVERED/NEVER-RECOVERED line whenever $restartCtx's own
      event/pending counts change, so the log keeps the same visibility
      the old inline version had.
    #>
    param([string]$ChannelId, [datetime]$NowUtc, $Sample, $GstWorkerPidMap, [double]$MeasuredCyclePeriodSeconds = 60)
    $engine = Resolve-EngineForPid -ProcId $Sample.pid -GstWorkerPidMap $GstWorkerPidMap
    $pendingBefore = $restartCtx.PendingRestarts.ContainsKey($ChannelId)
    $eventsBefore = $restartCtx.RestartEvents.Count
    Register-ChannelSample -Context $restartCtx -ChannelId $ChannelId -NowUtc $NowUtc -State $Sample.state -NewPid $Sample.pid -UpdatedAt $Sample.updated_at -Engine $engine -LastError $Sample.last_error -MeasuredCyclePeriodSeconds $MeasuredCyclePeriodSeconds
    if ($restartCtx.RestartEvents.Count -gt $eventsBefore) {
        $ev = $restartCtx.RestartEvents[$restartCtx.RestartEvents.Count - 1]
        Write-SoakLog "restart $(if ($ev.recovered) { 'RECOVERED' } else { 'NEVER RECOVERED' }) channel=$ChannelId classification=$($ev.classification) gap_seconds=$($ev.recovery_gap_seconds) superseded=$($ev.superseded) log_evidence=$($ev.log_evidence)"
    } elseif (-not $pendingBefore -and $restartCtx.PendingRestarts.ContainsKey($ChannelId)) {
        $p = $restartCtx.PendingRestarts[$ChannelId]
        Write-SoakLog "restart DETECTED channel=$ChannelId old_pid=$($p.old_pid) new_pid=$($p.new_pid) classification=$($p.classification) log_evidence=$($p.log_evidence)"
    }
    return $engine
}

$allCycles = @()
$cycleN = 0
$lastRollupCycle = 0
# Round-14 finding 7 (LOW): $row.log_ring_sizing_warning (round-13 finding
# 5's operator-visibility flag) was set on every row but never actually
# READ anywhere -- an exceptionally slow cycle produced the field, silently,
# with nothing surfacing it to a human. Collected here across the whole
# run and carried into both the periodic rollup and the final VERDICT.json
# as `harness_notes`.
$harnessNotes = @()
function Add-HarnessNote {
    <#
      .SYNOPSIS
      Followup finding 4 (round 14 addendum): a 15-minute soak polling
      every ~20-25s could in principle repeat the SAME underlying
      condition (e.g. the measured-cycle-period warning) dozens of times
      -- appending one line per occurrence would make harness_notes grow
      unbounded and mostly redundant. Deduplicates by EXACT text (one note
      per distinct message, not one per occurrence) and caps the total at
      20 (a run with more than 20 DISTINCT harness conditions has bigger
      problems than a truncated notes list).
    #>
    param([string]$Note)
    if ($script:harnessNotes -contains $Note) { return }
    if (@($script:harnessNotes).Count -ge 20) { return }
    $script:harnessNotes += $Note
}
$deadline = $SoakStartUtc.ToLocalTime().AddMinutes($Minutes)
# Round-8 finding 2/3: no independent 15s timer -- see RestartClassifier.ps1's
# header for why (the two-timer version's light-sample branch was
# mathematically unreachable once a heavy cycle ran even slightly over 60s,
# which every real heavy cycle does). Instead, a full all-channel state
# sample is INTERLEAVED before each of the three per-channel tsp probes
# inside one heavy cycle, giving ~3 ring samples spaced by roughly each
# channel's own tsp duration (~20-25s) across the whole ~60-75s heavy-cycle
# period -- close enough to make a TRANSITIONING state visible within that
# period without promising a literal independent timer. $measuredCyclePeriodSeconds
# tracks the actual observed time between heavy-cycle starts (default 60
# before the first one completes) and feeds Test-InActivePlannedRestartWindow's
# exemption window (max(60s, 2x that)), never the fixed PASS bound.
$measuredCyclePeriodSeconds = 60.0
$lastCycleStartUtc = $null
Write-SoakLog "entering poll loop: -Minutes $Minutes SOAK minutes from soak_start_utc (deadline $($deadline.ToUniversalTime().ToString('o'))); state sampled for all channels before each channel's own tsp probe (~3x/cycle), tsp probe cycle ~60-75s"

while ((Get-Date) -lt $deadline) {
    $cycleN++
    $cycleUtc = (Get-Date).ToUniversalTime()
    if ($lastCycleStartUtc) { $measuredCyclePeriodSeconds = ($cycleUtc - $lastCycleStartUtc).TotalSeconds }
    $lastCycleStartUtc = $cycleUtc

    $rows = @()
    $gstWorkerPidMap = @{}
    foreach ($c in $channelSpecs) {
        # Interleaved light sample: ALL channels, not just $c -- see the
        # header note above. Also captures the sample this row itself uses,
        # so no extra round-trip for $c specifically.
        #
        # Round-9 finding N4: ONE Win32_Process query per PASS (not per
        # sample) -- $gstWorkerPidMap is fetched once here and reused by
        # every one of this pass's 3 engine resolutions, capping CIM usage
        # at ~3 queries/cycle (one per outer $c iteration) instead of the
        # previous 9-12. $gstWorkerPidMap deliberately stays in scope after
        # this loop ends so Get-GlobalEngineCensus below can reuse the LAST
        # pass's map instead of issuing its own separate query.
        $gstWorkerPidMap = Get-GstWorkerPidMap
        # Round-10 finding 5: refresh $restartCtx.LogRing from the daemon's
        # own app log BEFORE registering this pass's samples, so a pid
        # change detected below has the freshest possible log evidence to
        # classify against.
        Update-DaemonLogRing -Context $restartCtx -MeasuredCyclePeriodSeconds $measuredCyclePeriodSeconds
        $samplesThisPass = @{}
        $enginesThisPass = @{}
        $sampledUtcThisPass = @{}
        foreach ($c2 in $channelSpecs) {
            $s2 = Get-ChannelStateSample -ChannelId $c2.id
            $nowUtc2 = (Get-Date).ToUniversalTime()
            $engine2 = Invoke-ChannelSampleAndRegister -ChannelId $c2.id -NowUtc $nowUtc2 -Sample $s2 -GstWorkerPidMap $gstWorkerPidMap -MeasuredCyclePeriodSeconds $measuredCyclePeriodSeconds
            $samplesThisPass[$c2.id] = $s2
            $enginesThisPass[$c2.id] = $engine2
            $sampledUtcThisPass[$c2.id] = $nowUtc2
        }
        $sample = $samplesThisPass[$c.id]

        # sandbox-lab lane follow-up A, item 2: once per channel per cycle
        # (same cadence as the tsp probe just below), not once per
        # interleaved pass -- reading the file 3x/cycle for the same data
        # would be pure overhead.
        Update-WorkerStdoutCounters -ChannelId $c.id
        # Round-follow-up-B finding 2b: read gst-worker.stderr.log at the
        # same cadence, into the same per-channel counts object -- see
        # Update-WorkerStderrCounters's own header for why this exists.
        Update-WorkerStderrCounters -ChannelId $c.id
        $workerStdoutCounts = $script:workerStdoutCountsByChannel[$c.id]

        $row = [ordered]@{
            channel_id = $c.id; engine_state = $sample.state
            # Round-9 finding N4: reuse the engine ALREADY resolved during
            # the interleaved pass above -- never a second
            # Resolve-EngineForPid call for the same pid.
            engine = $enginesThisPass[$c.id]
            # Round-13 finding 1: $sample.last_error already carries the
            # "state read failed: ..." text built once in
            # Get-ChannelStateSample's own ok=false branches -- reused
            # here verbatim, the SAME value already passed to
            # Register-ChannelSample via Invoke-ChannelSampleAndRegister,
            # never rebuilt separately (which is exactly how this drifted
            # out of sync with what the classifier actually received).
            last_error = $sample.last_error
            pid = $sample.pid; tsduck_verdict = $null; in_planned_restart_window = $false
            # Round-9 finding N5: per-row timestamp -- rows within one
            # cycle_utc are actually ~20-25s apart (one per interleaved
            # pass), not simultaneous.
            sampled_utc = $sampledUtcThisPass[$c.id].ToString('o')
            # Round-13 finding 5: visible warning when the measured cycle
            # period is running exceptionally slow (>=180s, i.e.
            # period/6 >= 30s) -- the dynamically-sized LogRing still
            # covers it (ceil(period/2)*2 + 30), but a period this slow is
            # itself a sign of station/box distress worth an operator's
            # attention independent of the classification outcome.
            log_ring_sizing_warning = ($measuredCyclePeriodSeconds / 6 -ge 30)
        }
        if ($row.log_ring_sizing_warning) {
            # Round-14 finding 7: actually surface the flag somewhere a
            # human reads -- see $harnessNotes' own init comment above.
            # Followup finding 4: deliberately GENERIC (no cycleN/exact
            # period value) so a condition that repeats across many cycles
            # collapses into ONE deduped note instead of dozens of
            # near-identical ones -- the per-cycle log line already above
            # (Write-SoakLog "cycle $cycleN ... period=...") carries the
            # precise numbers for whichever cycle a human wants to look up.
            Add-HarnessNote "channel=$($c.id): measured cycle period is exceptionally slow (period/6 >= 30s) -- log-ring sizing still covers it, but this is itself a sign of station/box distress"
        }
        $row.in_planned_restart_window = Test-InActivePlannedRestartWindow -Context $restartCtx -ChannelId $c.id -NowUtc (Get-Date).ToUniversalTime() -MeasuredCyclePeriodSeconds $measuredCyclePeriodSeconds

        $ts = Test-TsProof -TspExe $tsp -Port $c.port -Seconds 20 -OutDir (Join-Path $LocalDir 'cycles') -Label "$($c.id)-c$cycleN"
        $row.tsduck_verdict = $ts.verdict
        # Round-10 finding 10: captured tail of tsp's own stdout/stderr,
        # $null on a 'pass' verdict (nothing to explain).
        $row.tsp_output_tail = $ts.tsp_output_tail
        $row.sample_ring = @($restartCtx.Ring[$c.id])
        # sandbox-lab lane follow-up A, item 2: CUMULATIVE since soak start
        # (not a per-cycle delta) -- monotonic counters are simpler to read
        # across a rollup/VERDICT.json than reconciling per-cycle deltas,
        # and match the same cumulative-count convention this file already
        # uses for restart/reload-abort events.
        $row.reload_committed_count = $workerStdoutCounts.reload_committed_count
        $row.reload_aborted_count_worker = $workerStdoutCounts.reload_aborted_count
        $row.reload_aborted_reasons_worker = @($workerStdoutCounts.reload_aborted_reasons)
        $row.worker_stall_count = $workerStdoutCounts.worker_stall_count
        $row.worker_stall_stderr_count = $workerStdoutCounts.worker_stall_stderr_count
        $rows += $row
    }

    # sandbox-lab lane follow-up A, item 3: once per cycle (not per
    # channel) -- CPU/memory belong to guest-wide OS processes, not to any
    # one channel. Round-2 finding 3: $pidToChannelId is built here from
    # THIS pass's own $samplesThisPass (every channel's engine pid, already
    # fetched by the interleaved sample loop above -- no new query) so
    # Get-CycleProcessCpuSamples can label each row's role without ever
    # issuing an extra CIM/process lookup.
    $pidToChannelId = @{}
    foreach ($cid in $samplesThisPass.Keys) {
        $spid = $samplesThisPass[$cid].pid
        if ($spid) { $pidToChannelId[[int]$spid] = $cid }
    }
    $processSamples = Get-CycleProcessCpuSamples -GstWorkerPidMap $gstWorkerPidMap -PidToChannelId $pidToChannelId
    $cpuTotalPercent = Get-CpuTotalPercent

    $globalCensus = Get-GlobalEngineCensus -GstWorkerPidMap $gstWorkerPidMap
    $cycle = [ordered]@{
        cycle_utc = $cycleUtc.ToString('o'); channels = $rows; global_engine_observed = $globalCensus
        measured_cycle_period_seconds = [math]::Round($measuredCyclePeriodSeconds, 1)
        processes = $processSamples
        cpu_total_percent = $cpuTotalPercent
    }
    $allCycles += $cycle
    Save-Json -Obj $cycle -Path (Join-Path $LocalDir "cycles\cycle-$('{0:d4}' -f $cycleN).json")
    Write-SoakLog "cycle $cycleN @ $($cycleUtc.ToString('o')) (period=$([math]::Round($measuredCyclePeriodSeconds, 1))s): $(($rows | ForEach-Object { "$($_.channel_id)=$($_.engine_state)/$($_.engine)/tsp=$($_.tsduck_verdict)/restart_window=$($_.in_planned_restart_window)" }) -join ' ') global: ffmpeg=$($globalCensus.ffmpeg_processes) gst_workers=$($globalCensus.gst_worker_processes)"

    # Rollup + log copy every 3 minutes (every 3rd cycle at the measured cadence).
    if (($cycleN - $lastRollupCycle) -ge 3) {
        $lastRollupCycle = $cycleN
        $rollup = [ordered]@{
            rollup_utc = (Get-Date).ToUniversalTime().ToString('o')
            cycles_so_far = $cycleN
            soak_start_utc = $SoakStartUtc.ToString('o')
            elapsed_minutes = [math]::Round(((Get-Date).ToUniversalTime() - $SoakStartUtc).TotalMinutes, 2)
            latest_cycle = $cycle
            restart_events_so_far = @($restartCtx.RestartEvents)
            reload_abort_events_so_far = @($restartCtx.ReloadAbortEvents)
            # Followup finding 4: the rollup is written every 3 minutes and
            # is meant to be a lightweight checkpoint -- re-embedding the
            # FULL (already deduped/capped, but still potentially up-to-20-
            # entry) harness_notes array in every single rollup is
            # needless repetition of the SAME notes over and over across a
            # long soak. The rollup instead carries the count plus the
            # most recent 3; the full list is always in the final
            # VERDICT.json.
            harness_notes_count = @($harnessNotes).Count
            harness_notes_recent = @($harnessNotes | Select-Object -Last 3)
            # sandbox-lab lane follow-up A, item 2: cumulative-since-soak-start
            # snapshot per channel, for a rollup reader who does not want to
            # dig into latest_cycle.channels[*] for the same numbers.
            worker_stdout_cumulative_by_channel = $(
                $snap = [ordered]@{}
                foreach ($cid in $script:workerStdoutCountsByChannel.Keys) {
                    $wc = $script:workerStdoutCountsByChannel[$cid]
                    $snap[$cid] = [ordered]@{
                        reload_committed_count = $wc.reload_committed_count
                        reload_aborted_count_worker = $wc.reload_aborted_count
                        worker_stall_count = $wc.worker_stall_count
                        worker_stall_stderr_count = $wc.worker_stall_stderr_count
                    }
                }
                $snap
            )
        }
        Save-Json -Obj $rollup -Path (Join-Path $LocalDir "rollups\rollup-$('{0:d4}' -f $cycleN).json")
        Copy-StationLogs -Label "checkpoint-cycle$cycleN"
        Write-SoakLog "rollup + log checkpoint written at cycle $cycleN"
    }

    if ((Get-Date) -ge $deadline) { break }
}

# Round-12 finding 7 (LOW): one final ingestion pass -- the last in-loop
# call was up to one whole cycle period (~60-75s) ago; a crash/rollover
# that logged in that final gap deserves to be seen before classification
# is finalized and events are flushed below, not silently missed.
Update-DaemonLogRing -Context $restartCtx -MeasuredCyclePeriodSeconds $measuredCyclePeriodSeconds

# Round-follow-up-B finding 2b: same final-drain principle for the
# stderr-side counter -- run separately from the stdout drain below (it
# does not feed the armed-never-committed computation).
foreach ($c0 in $channelSpecs) {
    Update-WorkerStderrCounters -ChannelId $c0.id
}

$eventsBeforeFinalFlush = $restartCtx.RestartEvents.Count
# Round-11 finding 3 (HIGH): pass the REAL soak-end instant explicitly
# (this script's own "now", right after the poll loop exits) rather than
# relying on Get-FlushedRestartEvents' own default -- an event detected
# within the last 60s of THIS instant is flushed as incomplete=$true (see
# RestartClassifier.ps1's Get-FlushedRestartEvents header), excluded from
# SoakVerdict.ps1's 60s-recovery FAIL rule.
$soakEndUtc = (Get-Date).ToUniversalTime()
$restartEventsArray = @(Get-FlushedRestartEvents -Context $restartCtx -SoakEndUtc $soakEndUtc)
foreach ($ev in ($restartEventsArray | Select-Object -Skip $eventsBeforeFinalFlush)) {
    Write-SoakLog "restart still pending at soak end, flushed as not-recovered (incomplete=$($ev.incomplete)): channel=$($ev.channel_id) classification=$($ev.classification)"
}
$reloadAbortEventsArray = @($restartCtx.ReloadAbortEvents)
# Round-10 finding 6 (MEDIUM): Save-Json's `$Obj | ConvertTo-Json` pipes a
# top-level ARRAY object-by-object into ConvertTo-Json under PS 5.1;
# ConvertTo-Json has no way to tell "one object piped through" from "an
# array of exactly one object piped through" -- N=1 serializes as a bare
# JSON OBJECT (no enclosing `[...]`), and N=0 (nothing flows through the
# pipeline at all) serializes as an EMPTY FILE, not `[]`. Wrapping in a
# hashtable makes the top-level pipeline object always be exactly ONE
# object (the wrapper), regardless of how many events are inside its
# `events` array -- confirmed directly for N=0, 1, 2 (Test-RestartClassifier.ps1
# scenario 14).
Save-Json -Obj ([ordered]@{ events = @($restartEventsArray) }) -Path (Join-Path $LocalDir 'restart-events.json')

Write-SoakLog "poll loop complete: $cycleN cycles recorded, $($restartEventsArray.Count) restart event(s) ($(@($restartEventsArray | Where-Object { $_.classification -eq 'planned_restart' }).Count) planned, $(@($restartEventsArray | Where-Object { $_.classification -eq 'unplanned_relaunch' }).Count) unplanned)"

# --------------------------------------------------------------------------
# 6. Final verdict via the shared SoakVerdict.ps1 logic (dot-sourced from
#    the mapped scripts folder so the exact same code path Test-SoakVerdict
#    exercises against synthetic data also judges this real run).
# --------------------------------------------------------------------------
. (Join-Path 'C:\CivicCastSoakScripts' 'SoakVerdict.ps1')

# sandbox-lab lane follow-up A, item 2's -SeamlessReload cross-check:
# any channel the daemon log confirmed "Seamless content-reload armed"
# for, whose own worker-stdout reload_committed_count stayed 0 for the
# whole soak. Computed regardless of -SeamlessReload (cheap, and visible
# in VERDICT.json either way); Get-SoakVerdict itself only acts on this
# list under -SeamlessReload (see SoakVerdict.ps1's own header). Round-2
# finding 2: the filter itself lives in Get-ReloadArmedNeverCommittedChannels
# (DaemonLogPatterns.ps1) so it is directly unit-testable. Round-follow-up-B
# finding 2d: the final per-channel worker-stdout drain (up to one whole
# cycle period, ~60-75s, stale by the time the poll loop exits -- a reload
# committed in that final gap would otherwise leave
# $script:workerStdoutCountsByChannel stale for both this computation, a
# false reload_armed_never_committed FAIL under -SeamlessReload, and
# VERDICT.json's own worker_stdout_by_channel snapshot further down) and
# this computation are now both driven through
# Invoke-FinalWorkerStdoutDrainAndComputeArmedNeverCommitted
# (DaemonLogPatterns.ps1), whose own ordering contract guarantees the
# drain completes for every channel before the computation runs --
# provable directly (Test-RestartClassifier.ps1) without a live soak.
$reloadArmedNeverCommittedChannels = Invoke-FinalWorkerStdoutDrainAndComputeArmedNeverCommitted `
    -ChannelIds @($channelSpecs | ForEach-Object { $_.id }) `
    -ArmedChannelIds @($script:reloadArmedChannels.Keys) `
    -WorkerStdoutCountsByChannel $script:workerStdoutCountsByChannel `
    -DrainAction { param($cid) Update-WorkerStdoutCounters -ChannelId $cid }
if ($reloadArmedNeverCommittedChannels.Count -gt 0) {
    Write-SoakLog "reload_armed_never_committed: $($reloadArmedNeverCommittedChannels -join ', ') (daemon log confirmed armed, worker stdout never logged a commit)"
}

$verdictResult = Get-SoakVerdict -Cycles $allCycles -StartUtc $SoakStartUtc -WarmupSeconds 180 -RestartEvents $restartEventsArray -SeamlessReload ([bool]$SeamlessReload) -ReloadAbortEvents $reloadAbortEventsArray -ReloadArmedNeverCommittedChannels $reloadArmedNeverCommittedChannels

$verdict = [ordered]@{
    schema_version       = 1
    verdict              = $verdictResult.verdict
    reason               = $verdictResult.reason
    first_failing_cycle  = $verdictResult.first_failing_cycle
    cycles_total         = $verdictResult.cycles_total
    cycles_warmup        = $verdictResult.cycles_warmup
    cycles_evaluated     = $verdictResult.cycles_evaluated
    # Round-6 item 2: relaunch/restart classification counts (item 59
    # product metrics) -- see SoakVerdict.ps1's header for the full PASS
    # contract these feed into.
    unplanned_relaunch_count = $verdictResult.unplanned_relaunch_count
    planned_restart_count    = $verdictResult.planned_restart_count
    # Round-11 findings 3/4: restarts still pending in the final 60s of
    # the soak window (never had a fair chance to recover -- excluded from
    # the recovery-timeout FAIL rule, still visible here) and seamless
    # content-reload aborts (a distinct daemon.py WARNING-line event class
    # -- FAILs the run only under -SeamlessReload).
    incomplete_restart_count = $verdictResult.incomplete_restart_count
    reload_aborted_count     = $verdictResult.reload_aborted_count
    reload_abort_events      = $reloadAbortEventsArray
    max_restart_gap_seconds  = $verdictResult.max_restart_gap_seconds
    restart_events           = $restartEventsArray
    # Round-14 finding 7: operator-visible notes accumulated across the
    # run (currently: exceptionally slow measured-cycle-period warnings --
    # see $harnessNotes' own init comment) that don't themselves change
    # the PASS/FAIL/HARNESS_ERROR verdict but are worth a human's
    # attention.
    harness_notes            = @($harnessNotes)
    soak_start_utc       = $SoakStartUtc.ToString('o')
    run_end_utc          = (Get-Date).ToUniversalTime().ToString('o')
    minutes_requested    = $Minutes
    # Round-15 finding (a): the ON_AIR bound actually in force for this run.
    on_air_bound_minutes = $OnAirBoundMinutes
    installer_exit_code  = $summary.installer_exit_code
    installer_elapsed_seconds = $summary.installer_elapsed_seconds
    station_healthy      = $summary.station_healthy
    samples_found        = $summary.samples_found
    assets_uploaded      = $summary.assets_uploaded
    # Round-6 item 1: seamless-reload flag + verification status.
    seamless_reload          = [bool]$SeamlessReload
    seamless_reload_verified = $summary.seamless_reload_verified
    # Round-5 item 2: product metrics (item 59), carried from SOAK-START.json
    # into the final verdict too so a single file has both the pass/fail
    # judgment and the timing evidence behind the soak-clock start.
    channels_started_utc = $channelsStartedUtc.ToString('o')
    first_state_row_s    = $firstStateRowSByChannel
    time_to_on_air_s     = $timeToOnAirSByChannel
    # sandbox-lab lane follow-up A, item 1.
    captions_off_requested = [bool]$CaptionsOff
    captions_enabled       = $summary.captions_enabled
    captions_off_verified  = $summary.captions_off_verified
    # sandbox-lab lane follow-up A, item 2: final cumulative-since-soak-start
    # per-channel worker-stdout counts, plus which armed channels (if any)
    # never logged a commit -- see the computation just above this block.
    worker_stdout_by_channel = $(
        $wsnap = [ordered]@{}
        foreach ($cid in $script:workerStdoutCountsByChannel.Keys) {
            $wc = $script:workerStdoutCountsByChannel[$cid]
            $wsnap[$cid] = [ordered]@{
                reload_committed_count      = $wc.reload_committed_count
                reload_aborted_count_worker = $wc.reload_aborted_count
                reload_aborted_reasons_worker = @($wc.reload_aborted_reasons)
                worker_stall_count          = $wc.worker_stall_count
                worker_stall_stderr_count   = $wc.worker_stall_stderr_count
            }
        }
        $wsnap
    )
    reload_armed_channels               = @($script:reloadArmedChannels.Keys)
    reload_armed_never_committed_channels = $reloadArmedNeverCommittedChannels
    # sandbox-lab lane follow-up D.
    worker_env_requested = $summary.worker_env_requested
    worker_env_verified  = $summary.worker_env_verified
    gst_debug_file       = $summary.gst_debug_file
}
# N8: copy station logs BEFORE writing the verdict, not after -- the fail
# path (Write-FailVerdictAndExit) already had this order right; the success
# path had it backwards, so a run whose LAST action was the log copy could
# still show VERDICT.txt on the host before that copy (and, in the worst
# case, before a final flush) had actually landed.
Copy-StationLogs -Label 'final'
Save-Json -Obj $verdict -Path (Join-Path $LocalDir 'VERDICT.json')
"verdict=$($verdictResult.verdict) reason=$($verdictResult.reason) cycles_total=$($verdictResult.cycles_total) cycles_evaluated=$($verdictResult.cycles_evaluated)" |
    Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
Write-SoakLog "VERDICT: $($verdictResult.verdict) -- $($verdictResult.reason)"

# Ask the shipper to stop, then do the one bounded direct flush this
# script's own thread ever performs against the mapped folder.
try { Set-Content -Path (Join-Path $LocalDir '_SHIP-STOP.marker') -Value 'stop' -Encoding UTF8 } catch { }
Invoke-FinalFlush

Stop-Transcript | Out-Null
Invoke-GuestShutdown
