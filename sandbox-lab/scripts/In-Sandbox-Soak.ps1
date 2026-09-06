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
    [int]$Minutes = 15
)

$ErrorActionPreference = 'Continue'

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
    #>
    param([int]$TimeoutSeconds = 120)
    $r = Invoke-BoundedProcess -FilePath 'robocopy.exe' -ArgumentList @(
        $LocalDir, $ShipDir, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
    ) -TimeoutSeconds $TimeoutSeconds
    Write-SoakLog "final flush to $ShipDir : started=$($r.started) exited=$($r.exited) exit_code=$($r.exit_code) elapsed=$($r.elapsed_seconds)s error=$($r.error)"
}

function Write-PhaseMarker {
    param([string]$Name, [object]$Obj)
    Save-Json -Obj $Obj -Path (Join-Path $LocalDir $Name)
    Write-SoakLog "phase marker written: $Name"
}

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
    }
    Save-Json -Obj $verdict -Path (Join-Path $LocalDir 'VERDICT.json')
    "verdict=FAIL reason=$Reason" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
    Write-SoakLog "FAIL: $Reason"
    Invoke-FinalFlush
    Stop-Transcript | Out-Null
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
while ($true) {
    if (Test-Path $stopMarker) { break }
    try {
        "shipper_tick_utc=$((Get-Date).ToUniversalTime().ToString('o'))" |
            Set-Content -Path (Join-Path $LocalDir '_SHIPPER-HEARTBEAT.txt') -Encoding UTF8
    } catch { }
    try {
        $p = Start-Process -FilePath 'robocopy.exe' -ArgumentList @(
            $LocalDir, $ShipDir, '/E', '/R:0', '/W:0', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
        ) -PassThru -WindowStyle Hidden -ErrorAction Stop
        $null = $p.Handle
        if (-not $p.WaitForExit($TickTimeoutSeconds * 1000)) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        }
    } catch { }
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
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'FAIL'
        reason = 'in-sandbox watchdog fired before the soak clock ever started (install/health/setup presumed hung)'
        first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        watchdog_timeout = $true; watchdog_phase = 'pre-soak'; done_utc = $ts; soak_start_utc = $null
    }
    ($verdict | ConvertTo-Json -Depth 6) | Set-Content -Path $donePath -Encoding UTF8
    "verdict=FAIL (watchdog timeout, pre-soak) reason=see WATCHDOG-TIMEOUT.txt" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
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
        schema_version = 1; verdict = 'FAIL'
        reason = 'in-sandbox watchdog fired -- main script did not complete within soak_start_utc + Minutes + 10'
        first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        watchdog_timeout = $true; watchdog_phase = 'post-soak'; done_utc = $ts; soak_start_utc = $soakStartUtc.ToString('o')
    }
    ($verdict | ConvertTo-Json -Depth 6) | Set-Content -Path $donePath -Encoding UTF8
    "verdict=FAIL (watchdog timeout, post-soak) reason=see WATCHDOG-TIMEOUT.txt" | Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8
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

function Copy-StationLogs {
    <#
      Copies the station's daemon/worker/install logs + installer-state.json
      into $LocalDir\logs (the shipper mirrors it out from there). Called at
      the end AND every 3 minutes during the soak loop, so a hung sandbox
      still leaves partial evidence on the host. TARGETED, bounded candidate
      paths only -- no full-tree recursive scan over the install directory
      (In-Sandbox-Report.ps1:18-28's HARDENED note: a full `Get-ChildItem
      -Recurse` over a multi-thousand-file install tree is exactly the kind
      of thing that is fast on a real disk and can take minutes on Windows
      Sandbox's virtualized/differencing storage).
    #>
    param([string]$Label)
    $dst = Join-Path $LocalDir "logs\$Label"
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    $candidates = @(
        (Join-Path $InstallDir 'install-progress.log'),
        (Join-Path $InstallDir 'installer-state.json'),
        'C:\ProgramData\CivicCast\installer-state.json',
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
}

# --------------------------------------------------------------------------
# 1. Locate and run the installer silently, bounded to $InstallBoundMinutes.
# --------------------------------------------------------------------------
$summary = [ordered]@{
    run_start_utc = $RunStart.ToUniversalTime().ToString('o')
    installer_found = $null
    installer_exit_code = $null
    installer_elapsed_seconds = $null
    station_healthy = $false
    first_admin_ok = $null
    samples_found = 0
    assets_uploaded = 0
    channels_started = @()
    soak_start_utc = $null
    error = $null
}

$installerExe = Get-ChildItem -Path $KitDir -Filter '*setup.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installerExe) {
    Write-FailVerdictAndExit -Reason "no *setup.exe found under $KitDir"
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
try {
    Start-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
    Write-SoakLog "Start-Service CivicCastSupervisor: requested"
} catch {
    Write-SoakLog "Start-Service CivicCastSupervisor: $_ (service may already be running or auto-started)"
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
    Write-FailVerdictAndExit -Reason "station never reported status=healthy AND schema=current at $Base/health within ${HealthBoundMinutes}m (last body: status=$($lastHealthBody.status) schema=$($lastHealthBody.schema))"
}
Write-PhaseMarker -Name 'PHASE-HEALTHY.json' -Obj ([ordered]@{ utc = (Get-Date).ToUniversalTime().ToString('o'); body_status = $lastHealthBody.status; body_schema = $lastHealthBody.schema })

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
# multipart/form-data by hand via System.Net.Http.MultipartFormDataContent).
# STREAMED, not ReadAllBytes: the LPM sample clips run up to ~858MB, and
# ReadAllBytes would materialize the whole file in managed memory before the
# first byte goes over the wire. FileStream -> StreamContent reads lazily as
# HttpClient sends, and the underlying FileStream is disposed only after
# PostAsync().Result returns (blocking, so the stream must stay open until
# then).
function Invoke-AssetUpload {
    param([string]$BaseUrl, [string]$Token, [string]$AssetId, [string]$Title, [string]$FilePath, [int]$TimeoutSec = 900)
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
        $resp = $client.PostAsync($url, $content).Result
        $result.status = [int]$resp.StatusCode
        $result.body_raw = $resp.Content.ReadAsStringAsync().Result
        $result.ok = $resp.IsSuccessStatusCode
    } catch {
        $result.error = "$_"
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
    Write-FailVerdictAndExit -Reason "no sample videos found under $KitDir\samples"
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
        Write-SoakLog "asset upload FAILED for $($s.Name) (id=$assetId): status=$($up.status) body=$($up.body_raw)"
    }
}
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

if ($stagedAssets.Count -eq 0) {
    Write-FailVerdictAndExit -Reason "no assets uploaded successfully -- cannot schedule or start channels"
}

# Schedule + Commit-to-Air: a FIXED item count per channel, (Minutes+10)*2 @
# 30s each = (Minutes+10) minutes of scheduled coverage per channel -- this
# is the rollover instrument itself (see file header), not a wall-clock loop
# probing real durations. Runs for ALL channels BEFORE any channel is
# configured/started (AUTORUN-9m.ps1 header, item B-B).
$itemsPerChannel = ($Minutes + 10) * 2
$schedulingStart = (Get-Date)
Write-SoakLog "scheduling $itemsPerChannel items/channel @ 30s each (~$($Minutes + 10) minutes coverage)"
foreach ($c in $channelSpecs) {
    $cursor = $schedulingStart.AddSeconds(-60)
    $scheduled = 0
    $committed = 0
    for ($i = 0; $i -lt $itemsPerChannel; $i++) {
        $asset = $stagedAssets[$i % $stagedAssets.Count]
        $itemBody = [ordered]@{
            asset_id = $asset.id; channel_id = $c.id; mode = 'premiere'
            scheduled_at = $cursor.ToUniversalTime().ToString('o')
            duration_seconds = [int]$asset.duration_seconds
            notes = 'sandbox-lab local soak lane'
        }
        $itemR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/schedule" -BodyObj $itemBody -BearerToken $token
        if ($itemR.status -eq 201 -and $itemR.body_json -and $itemR.body_json.id) {
            $scheduled++
            $commitBody = [ordered]@{
                channel_id = $c.id
                occurrence_id = "sandboxsoak-$($c.id)-$scheduled"
                schedule_item_id = "$($itemR.body_json.id)"
            }
            $commitR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/playout/commit" -BodyObj $commitBody -BearerToken $token
            if ($commitR.status -eq 201) { $committed++ }
            else { Write-SoakLog "commit FAILED channel=$($c.id) item=$($itemR.body_json.id) status=$($commitR.status) body=$($commitR.body_raw)" }
        } else {
            Write-SoakLog "schedule item FAILED channel=$($c.id) asset=$($asset.id) status=$($itemR.status) body=$($itemR.body_raw)"
        }
        $cursor = $cursor.AddSeconds(30)
    }
    Write-SoakLog "channel=$($c.id) schedule_items=$scheduled committed=$committed (target=$itemsPerChannel)"
}

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
    if (-not $configOk) { Write-SoakLog "PUT config $($c.id) FAILED: status=$($cfgR.status) body=$($cfgR.body_raw)" }
    $startOk = $false
    if ($configOk) {
        $startR = Invoke-CivicCastApi -Method 'Post' -Url "$Base/api/staff/egress/channels/$($c.id)/commands" -BodyObj (@{ action = 'start' }) -BearerToken $token
        $startOk = ($startR.status -eq 202)
        if (-not $startOk) { Write-SoakLog "start command $($c.id) FAILED: status=$($startR.status) body=$($startR.body_raw)" }
    }
    $summary.channels_started += [ordered]@{ channel_id = $c.id; config_ok = $configOk; start_ok = $startOk }
}
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

# Poll up to 6 minutes for at least one channel ON_AIR before starting the
# soak clock (mirrors AUTORUN-9m's own guard: never start the clock against
# a setup that silently failed).
$onAirDeadline = (Get-Date).AddMinutes(6)
$anyOnAir = $false
do {
    foreach ($c in $channelSpecs) {
        try {
            $st = Invoke-RestMethod -Uri "$Base/api/staff/egress/channels/$($c.id)/state" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20
            if ($st.state -eq 'ON_AIR') { $anyOnAir = $true }
        } catch { }
    }
    if ($anyOnAir) { break }
    Start-Sleep -Seconds 15
} while ((Get-Date) -lt $onAirDeadline)

if (-not $anyOnAir) {
    Write-FailVerdictAndExit -Reason "no channel reached ON_AIR within 6 minutes of the start command -- soak clock not started"
}

# --------------------------------------------------------------------------
# THE SOAK CLOCK STARTS HERE -- health OK AND channels configured/started
# AND at least one confirmed ON_AIR. -Minutes means SOAK minutes measured
# from this instant, never wall-clock minutes from process launch (the
# install alone can take most of $InstallBoundMinutes). Recorded as
# soak_start_utc in every rollup and in VERDICT.json, and the ONLY thing the
# in-sandbox watchdog's post-soak phase anchors on.
# --------------------------------------------------------------------------
$SoakStartUtc = (Get-Date).ToUniversalTime()
$summary.soak_start_utc = $SoakStartUtc.ToString('o')
Write-SoakLog "SOAK CLOCK STARTED (UTC): $($SoakStartUtc.ToString('o')) -- at least one channel confirmed ON_AIR"
Write-PhaseMarker -Name 'SOAK-START.json' -Obj ([ordered]@{ soak_start_utc = $SoakStartUtc.ToString('o') })
Save-Json -Obj $summary -Path (Join-Path $LocalDir 'summary.json')

# --------------------------------------------------------------------------
# 5. Poll loop: every 60s for -Minutes SOAK minutes (from $SoakStartUtc, not
#    $RunStart), one cycle record per poll. tsp egress probe ported from
#    AUTORUN-3.ps1's Test-TsProof. Engine is determined by an OS process
#    CENSUS (AUTORUN-3.ps1:244-251), never read off the egress state API --
#    civiccast/egress/models.py:506-518 shows EgressStateRow carries no
#    `engine` field at all.
# --------------------------------------------------------------------------
$tspCandidates = @(
    (Join-Path $KitDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'tsduck\bin\tsp.exe'),
    'C:\Program Files\CivicCast (Native)\tsduck\bin\tsp.exe'
)
$tsp = $tspCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
Write-SoakLog "tsp.exe: $(if ($tsp) { $tsp } else { 'NOT FOUND in the bounded candidate list -- egress probes will report not-run (no full-tree recursive fallback scan; see file header)' })"

function Test-TsProof {
    param([string]$TspExe, [int]$Port, [int]$Seconds, [string]$OutDir, [string]$Label)
    $result = [ordered]@{ verdict = 'not-run'; packets_total = $null; invalid_syncs = $null; transport_errors = $null; discontinuities = $null }
    if (-not $TspExe -or -not (Test-Path $TspExe)) { $result.verdict = 'not-run: tsp.exe not found'; return $result }
    $report = Join-Path $OutDir "tsduck-$Label-report.json"
    $tspArgs = @('-I', 'ip', "$Port", '--buffer-size', '16777216', '-P', 'until', '--seconds', "$Seconds", '-P', 'analyze', '--json', '--output-file', $report, '-O', 'drop')
    try {
        $proc = Start-Process -FilePath $TspExe -ArgumentList $tspArgs -PassThru -NoNewWindow -RedirectStandardOutput ([System.IO.Path]::GetTempFileName()) -RedirectStandardError ([System.IO.Path]::GetTempFileName())
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
}

# Engine census, ported from AUTORUN-3.ps1:244-251: EgressStateRow has no
# `engine` field, so the engine actually running for a channel's worker pid
# is inferred from the OS process itself -- ffmpeg.exe means the software
# fallback engaged; a python.exe running civiccast\egress\gst\worker.py
# means GStreamer; anything else (including "no such pid") is reported as
# unknown/$null rather than guessed into 'gstreamer'.
function Get-EngineForWorkerPid {
    param([Nullable[int]]$ProcId)
    if (-not $ProcId) { return $null }
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
        if (-not $cim) { return $null }
        if ($cim.Name -match '^ffmpeg') { return 'ffmpeg-fallback' }
        if ($cim.CommandLine -and ($cim.CommandLine -match 'egress[\\/]gst[\\/]worker\.py')) { return 'gstreamer' }
        return "unknown:$($cim.Name)"
    } catch {
        return $null
    }
}

$lastPid = @{}
function Update-RelaunchState {
    param([string]$ChannelId, [Nullable[int]]$NewPid)
    $relaunched = $false
    if ($null -ne $NewPid) {
        if ($lastPid.ContainsKey($ChannelId) -and $lastPid[$ChannelId] -ne $NewPid) { $relaunched = $true }
        $lastPid[$ChannelId] = $NewPid
    }
    return $relaunched
}

$allCycles = @()
$cycleN = 0
$lastRollupCycle = 0
$deadline = $SoakStartUtc.ToLocalTime().AddMinutes($Minutes)
Write-SoakLog "entering poll loop: -Minutes $Minutes SOAK minutes from soak_start_utc (deadline $($deadline.ToUniversalTime().ToString('o')))"

while ((Get-Date) -lt $deadline) {
    $cycleN++
    $cycleUtc = (Get-Date).ToUniversalTime()
    $rows = @()
    foreach ($c in $channelSpecs) {
        $row = [ordered]@{ channel_id = $c.id; engine_state = $null; engine = $null; last_error = $null; pid = $null; relaunched_this_cycle = $false; tsduck_verdict = $null }
        try {
            $st = Invoke-RestMethod -Uri "$Base/api/staff/egress/channels/$($c.id)/state" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20
            $row.engine_state = $st.state
            $row.last_error = $st.last_error
            $row.pid = $st.pid
        } catch {
            $row.last_error = "state read failed: $($_.Exception.Message)"
        }
        $newPid = $(if ($row.pid) { [int]$row.pid } else { $null })
        $row.engine = Get-EngineForWorkerPid -ProcId $newPid
        $row.relaunched_this_cycle = Update-RelaunchState -ChannelId $c.id -NewPid $newPid

        $ts = Test-TsProof -TspExe $tsp -Port $c.port -Seconds 20 -OutDir (Join-Path $LocalDir 'cycles') -Label "$($c.id)-c$cycleN"
        $row.tsduck_verdict = $ts.verdict
        $rows += $row
    }

    $cycle = [ordered]@{ cycle_utc = $cycleUtc.ToString('o'); channels = $rows }
    $allCycles += $cycle
    Save-Json -Obj $cycle -Path (Join-Path $LocalDir "cycles\cycle-$('{0:d4}' -f $cycleN).json")
    Write-SoakLog "cycle $cycleN @ $($cycleUtc.ToString('o')): $(($rows | ForEach-Object { "$($_.channel_id)=$($_.engine_state)/$($_.engine)/tsp=$($_.tsduck_verdict)/relaunch=$($_.relaunched_this_cycle)" }) -join ' ')"

    # Rollup + log copy every 3 minutes (every 3rd cycle at a 60s cadence).
    if (($cycleN - $lastRollupCycle) -ge 3) {
        $lastRollupCycle = $cycleN
        $rollup = [ordered]@{
            rollup_utc = (Get-Date).ToUniversalTime().ToString('o')
            cycles_so_far = $cycleN
            soak_start_utc = $SoakStartUtc.ToString('o')
            elapsed_minutes = [math]::Round(((Get-Date).ToUniversalTime() - $SoakStartUtc).TotalMinutes, 2)
            latest_cycle = $cycle
        }
        Save-Json -Obj $rollup -Path (Join-Path $LocalDir "rollups\rollup-$('{0:d4}' -f $cycleN).json")
        Copy-StationLogs -Label "checkpoint-cycle$cycleN"
        Write-SoakLog "rollup + log checkpoint written at cycle $cycleN"
    }

    $sleepUntil = $cycleUtc.ToLocalTime().AddSeconds(60)
    $sleepSec = [int]([Math]::Max(1, ($sleepUntil - (Get-Date)).TotalSeconds))
    if ((Get-Date).AddSeconds($sleepSec) -gt $deadline) { break }
    Start-Sleep -Seconds $sleepSec
}

Write-SoakLog "poll loop complete: $cycleN cycles recorded"

# --------------------------------------------------------------------------
# 6. Final verdict via the shared SoakVerdict.ps1 logic (dot-sourced from
#    the mapped scripts folder so the exact same code path Test-SoakVerdict
#    exercises against synthetic data also judges this real run).
# --------------------------------------------------------------------------
. (Join-Path 'C:\CivicCastSoakScripts' 'SoakVerdict.ps1')
$verdictResult = Get-SoakVerdict -Cycles $allCycles -StartUtc $SoakStartUtc -WarmupSeconds 180

$verdict = [ordered]@{
    schema_version       = 1
    verdict              = $verdictResult.verdict
    reason               = $verdictResult.reason
    first_failing_cycle  = $verdictResult.first_failing_cycle
    cycles_total         = $verdictResult.cycles_total
    cycles_warmup        = $verdictResult.cycles_warmup
    cycles_evaluated     = $verdictResult.cycles_evaluated
    soak_start_utc       = $SoakStartUtc.ToString('o')
    run_end_utc          = (Get-Date).ToUniversalTime().ToString('o')
    minutes_requested    = $Minutes
    installer_exit_code  = $summary.installer_exit_code
    installer_elapsed_seconds = $summary.installer_elapsed_seconds
    station_healthy      = $summary.station_healthy
    samples_found        = $summary.samples_found
    assets_uploaded      = $summary.assets_uploaded
}
Save-Json -Obj $verdict -Path (Join-Path $LocalDir 'VERDICT.json')
"verdict=$($verdictResult.verdict) reason=$($verdictResult.reason) cycles_total=$($verdictResult.cycles_total) cycles_evaluated=$($verdictResult.cycles_evaluated)" |
    Set-Content -Path (Join-Path $LocalDir 'VERDICT.txt') -Encoding UTF8

Copy-StationLogs -Label 'final'
Write-SoakLog "VERDICT: $($verdictResult.verdict) -- $($verdictResult.reason)"

# Ask the shipper to stop, then do the one bounded direct flush this
# script's own thread ever performs against the mapped folder.
try { Set-Content -Path (Join-Path $LocalDir '_SHIP-STOP.marker') -Value 'stop' -Encoding UTF8 } catch { }
Invoke-FinalFlush

Stop-Transcript | Out-Null
