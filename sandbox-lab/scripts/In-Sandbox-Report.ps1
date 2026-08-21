# In-Sandbox-Report.ps1
# Runs INSIDE Windows Sandbox via the .wsb LogonCommand.
# Drives a silent install of the published CivicCast Native beta.1 installer,
# then collects a clean-box baseline: exit code, install tree, station-set.json,
# activation-self-test.json, CivicCastSupervisor service state, installer logs,
# and Event Log errors during the run window. Writes JSON + a done-marker to
# the host-visible C:\CivicCastOutput so the host launcher knows when to stop
# polling and can read the results back.
#
# HARDENED 2026-08-17 after a run that got all the way through a clean
# postinstall (verified via install-progress.log) but then hung for 6+
# minutes past _AFTER_INSTALL.marker with no summary.json ever written --
# the previous version did two full-tree `Get-ChildItem -Recurse` scans
# (once each for station-set.json / activation-self-test.json) over a
# 10,629-file / 5.4 GB install tree, which is exactly the kind of thing that
# is fast on a real disk and can take many minutes on Windows Sandbox's
# virtualized/differencing storage. Fixes in this version:
#   (a) summary.json is now written INCREMENTALLY after every numbered step
#       below (Save-Summary), so a hang anywhere after step N still leaves
#       steps 1..N's results on disk for the host to read.
#   (b) the two full-tree recursive searches are replaced with TARGETED,
#       bounded path checks (exact known locations + one shallow,
#       non-recursive listing of app\* subfolders) -- see Test-KnownPaths.
#   (c) the CivicCastSupervisor service check remains non-blocking
#       (Get-Service / sc.exe query / sc.exe qc, none of which wait), and a
#       Start-Service attempt (new) is wrapped in a bounded poll (max 60s)
#       instead of any unbounded wait.
#   (d) a DONE.json marker (not just the old DONE.marker text file) is
#       written as the LAST statement in the script -- Host-Launch-
#       Sandbox-Test.ps1 now polls for DONE.json specifically, so a stray
#       earlier marker (e.g. _AFTER_INSTALL.marker) can never be mistaken
#       for real completion again.

# HARDENED <gate-a-station-up-wait-and-log-capture>: bounded script-level
# watchdog. -MaxScriptMinutes defaults to 100 (LogonCommand invokes this
# script with no arguments, so the default always applies in production;
# it exists as a parameter purely so a developer/dry-run can shorten it).
# Deliberately NOT implemented with Start-Job -- service.py's own history
# (see comment near the Get-WinEvent call further down) documents a real
# System.OutOfMemoryException hit loading PSWorkflow/PSScheduledJob module
# type data the moment Start-Job was invoked under this VM's memory
# pressure, so the watchdog is a genuinely separate powershell.exe process
# (Start-Process) instead -- it never touches the job-scheduling subsystem.
param(
    [int]$MaxScriptMinutes = 100
)

$ErrorActionPreference = 'Continue'
$OutDir = 'C:\CivicCastOutput'
$PayloadDir = 'C:\CivicCastPayload'
$LocalInstallStage = 'C:\CivicCastInstall'
$RunStart = Get-Date

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Start-Transcript -Path (Join-Path $OutDir 'sandbox-transcript.log') -Force | Out-Null

function Write-Marker {
    param([string]$Name, [string]$Content = '')
    Set-Content -Path (Join-Path $OutDir $Name) -Value $Content -Encoding UTF8
}

Write-Marker -Name '_STARTED.marker' -Content "Started $RunStart"

# Spawn the watchdog now, as early as possible, so it bounds the ENTIRE run
# (installer through T5 soak) -- not just the parts of the script written
# after it. Two independent triggers, both handled by this ONE separate
# process (still not Start-Job -- see below):
#   (1) OVERALL bound: if DONE.json still does not exist $MaxScriptMinutes
#       minutes from now, write WATCHDOG-TIMEOUT.txt + a placeholder
#       DONE.json so Host-Launch-Sandbox-Test.ps1's poll loop can never
#       wait on a zombie in-sandbox script forever.
#   (2) STALENESS bound, added after the 8579e66-run4 evidence: run #4
#       reached 'station-diag-captured-after-t3t5' at 11:52:11Z and then
#       never advanced -- 'install-progress-log-copied' (the very next
#       step, block 6 below) never arrived in 6+ minutes, with no
#       DONE.json, and $MaxScriptMinutes=100 was far too coarse a bound to
#       catch that kind of late-stage stall promptly. Once
#       summary.json.last_completed_step first reaches a step at or after
#       the runtime verdict (matches 'runtime-check-*', or equals
#       't3t5-skipped-station-down' or 't5-soak-complete'), this watchdog
#       polls it every 30s; if it stops changing for 8 minutes, the
#       watchdog writes STALL-TIMEOUT.txt + a placeholder DONE.json.
# Deliberately NOT implemented with Start-Job -- service.py's own history
# (see comment near the Get-WinEvent call further down) documents a real
# System.OutOfMemoryException hit loading PSWorkflow/PSScheduledJob module
# type data the moment Start-Job was invoked under this VM's memory
# pressure, so the watchdog is a genuinely separate powershell.exe process
# (Start-Process) instead -- it never touches the job-scheduling subsystem.
try {
    $watchdogScript = @'
param([string]$OutDir, [int]$Minutes)

$donePath = Join-Path $OutDir 'DONE.json'
$summaryPath = Join-Path $OutDir 'summary.json'
$deadline = (Get-Date).AddSeconds([Math]::Max(60, $Minutes * 60))
$pollIntervalSeconds = 30
$stallThresholdSeconds = 8 * 60

$staleTrackingStarted = $false
$lastSeenStep = $null
$lastChangeTime = Get-Date

function Test-PostRuntimeVerdictStep {
    param([string]$Step)
    if (-not $Step) { return $false }
    if ($Step -like 'runtime-check-*') { return $true }
    if ($Step -eq 't3t5-skipped-station-down') { return $true }
    if ($Step -eq 't5-soak-complete') { return $true }
    return $false
}

while ((Get-Date) -lt $deadline) {
    if (Test-Path $donePath) { break }

    $step = $null
    if (Test-Path $summaryPath) {
        try {
            $raw = Get-Content -Path $summaryPath -Raw -Encoding UTF8 -ErrorAction Stop
            $obj = $raw | ConvertFrom-Json -ErrorAction Stop
            $step = $obj.last_completed_step
        } catch {
            $step = $null  # mid-write or transiently malformed -- try again next poll
        }
    }

    if ($step) {
        if (-not $staleTrackingStarted) {
            if (Test-PostRuntimeVerdictStep -Step $step) {
                $staleTrackingStarted = $true
                $lastSeenStep = $step
                $lastChangeTime = Get-Date
            }
        } elseif ($step -ne $lastSeenStep) {
            $lastSeenStep = $step
            $lastChangeTime = Get-Date
        } else {
            $stalledSeconds = ((Get-Date) - $lastChangeTime).TotalSeconds
            if ($stalledSeconds -ge $stallThresholdSeconds -and -not (Test-Path $donePath)) {
                $ts = (Get-Date).ToUniversalTime().ToString('o')
                $stuckSinceIso = $lastChangeTime.ToUniversalTime().ToString('o')
                "stall_detected_utc=$ts stuck_step=$lastSeenStep stuck_since_utc=$stuckSinceIso stalled_seconds=$([Math]::Round($stalledSeconds, 1)) threshold_seconds=$stallThresholdSeconds" |
                    Set-Content -Path (Join-Path $OutDir 'STALL-TIMEOUT.txt') -Encoding UTF8
                if (-not (Test-Path $donePath)) {
                    $doneObj = [ordered]@{
                        done_utc             = $ts
                        last_completed_step  = $lastSeenStep
                        installer_exit_code  = $null
                        harness_completed    = $false
                        watchdog_timeout     = $false
                        stall_timeout        = $true
                    }
                    ($doneObj | ConvertTo-Json -Depth 3) | Set-Content -Path $donePath -Encoding UTF8
                }
                break
            }
        }
    }

    Start-Sleep -Seconds $pollIntervalSeconds
}

if (-not (Test-Path $donePath)) {
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    "watchdog_fired_utc=$ts max_script_minutes=$Minutes reason=DONE.json not present after the bounded deadline -- main script presumed hung or zombied" |
        Set-Content -Path (Join-Path $OutDir 'WATCHDOG-TIMEOUT.txt') -Encoding UTF8
    if (-not (Test-Path $donePath)) {
        $doneObj = [ordered]@{
            done_utc             = $ts
            last_completed_step  = 'watchdog-timeout'
            installer_exit_code  = $null
            harness_completed    = $false
            watchdog_timeout     = $true
        }
        ($doneObj | ConvertTo-Json -Depth 3) | Set-Content -Path $donePath -Encoding UTF8
    }
}
'@
    $watchdogPath = Join-Path $env:TEMP 'civiccast-gate-a-watchdog.ps1'
    Set-Content -Path $watchdogPath -Value $watchdogScript -Encoding UTF8
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $watchdogPath,
        '-OutDir', $OutDir, '-Minutes', $MaxScriptMinutes
    ) -WindowStyle Hidden | Out-Null
    Write-Marker -Name '_WATCHDOG_SPAWNED.marker' -Content "MaxScriptMinutes=$MaxScriptMinutes stall_threshold_minutes=8 started_utc=$((Get-Date).ToUniversalTime().ToString('o'))"
} catch {
    Add-Content -Path (Join-Path $OutDir 'summary-write-errors.log') -Value "watchdog spawn failed (non-fatal, continuing without a watchdog): $_"
}

$summary = [ordered]@{
    run_start_utc          = $RunStart.ToUniversalTime().ToString('o')
    sandbox_has_gpu        = $false
    networking              = 'disabled'
    installer_source        = $null
    installer_sha256        = $null
    silent_flag_used        = $null
    installer_exit_code     = $null
    installer_launch_error  = $null
    install_dir_found       = $null
    install_dir_candidates  = @()
    install_tree_top_levels = @()
    station_set_json_found  = @()
    activation_self_test_json_found = @()
    marker_search_method     = 'targeted (non-recursive) -- see HARDENED note at top of script'
    arp_entries              = @()
    service_get_service       = $null
    service_sc_query_raw      = $null
    service_sc_qc_raw         = $null
    service_start_attempt     = $null
    install_progress_log_found = $false
    install_progress_log_tail  = @()
    installer_nsis_log_found   = $false
    event_log_errors           = @()
    errors                     = @()
    last_completed_step        = 'init'
    run_end_utc                = $null
}

# (a) Incremental writer: called after EVERY step below so a hang later in
# the script can never swallow earlier results. Cheap (summary is small
# JSON, never the multi-GB install tree itself).
function Save-Summary {
    param([string]$Step)
    $summary.last_completed_step = $Step
    try {
        $summaryPath = Join-Path $OutDir 'summary.json'
        ($summary | ConvertTo-Json -Depth 8) | Set-Content -Path $summaryPath -Encoding UTF8
    } catch {
        # Writing the summary itself must never throw and abort the run.
        try { Add-Content -Path (Join-Path $OutDir 'summary-write-errors.log') -Value "step=$Step : $_" } catch {}
    }
}

# (b) Bounded, targeted marker-file lookup -- replaces the old
# `Get-ChildItem -Recurse` full-tree scans. Checks only the exact locations
# the coordinator specified, plus a SHALLOW (one-level, non-recursive)
# listing of immediate subfolders under <installDir>\app, never a deep walk.
function Test-KnownPaths {
    param([string]$InstallDir, [string]$FileName)
    $hits = New-Object System.Collections.Generic.List[string]

    # <installDir>\<file>
    $p = Join-Path $InstallDir $FileName
    if (Test-Path $p) { $hits.Add($p) }

    # <installDir>\app\<file>
    $appDir = Join-Path $InstallDir 'app'
    $p = Join-Path $appDir $FileName
    if (Test-Path $p) { $hits.Add($p) }

    # <installDir>\app\*\<file>  -- one shallow, non-recursive enumeration of
    # app's immediate subdirectories only (bounded by however many top-level
    # app subfolders exist, typically a handful -- not a tree walk).
    if (Test-Path $appDir) {
        Get-ChildItem -Path $appDir -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $candidate = Join-Path $_.FullName $FileName
            if (Test-Path $candidate) { $hits.Add($candidate) }
        }
    }

    # %ProgramData%\CivicCast\<file>
    $pd = Join-Path $env:ProgramData 'CivicCast'
    $p = Join-Path $pd $FileName
    if (Test-Path $p) { $hits.Add($p) }

    return ($hits | Select-Object -Unique)
}

# ============================================================================
# HARDENED <gate-a-station-up-wait-and-log-capture> -- station diagnostics
# capture. The 8579e66-run3 evidence proved the harness had NO way to see
# why the station never listened on :8000: postgres.log / nats.log /
# control_plane.log / supervisor.log all live under
# %ProgramData%\CivicCast\logs INSIDE the sandbox, which resets every
# session, and nothing copied them out before the VM was torn down. This
# function is called twice -- once right after the station-up-wait
# concludes (pass OR fail) and once, unconditionally, from the top-level
# `finally` block -- so a diagnosis is preserved even if something later in
# the run hangs or throws.
#
# Every operation here is BOUNDED and TARGETED, matching this file's
# existing "no recursive scans over the 10k-file install tree" discipline:
# robocopy of two small, known ProgramData subdirectories (never the
# install tree), three non-blocking process/service queries, and a
# `-MaxEvents`-capped Get-WinEvent call. Paths are taken from
# civiccast/native/supervisor/install_layout.py's `resolve_install_layout`
# (the single source of truth for the installed layout) rather than
# re-guessed here: log_root = <ProgramData>\CivicCast\logs (every child's
# <name>.log plus the rotating supervisor.log all land there in one place),
# config lives at <ProgramData>\CivicCast\config (nats-server.conf etc --
# explicitly NOT the sibling data\pgdata / data\nats-store directories,
# which are excluded from the robocopy).
function Invoke-StationDiagCapture {
    param([string]$OutDir, [string]$InstallDir, [string]$Label, [datetime]$RunStart)
    $diagDir = Join-Path $OutDir "station-diag\$Label"
    New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
    $note = Join-Path $diagDir '_capture-note.txt'
    "captured_utc=$((Get-Date).ToUniversalTime().ToString('o')) label=$Label" | Set-Content -Path $note -Encoding UTF8

    $pdCivicCast = Join-Path $env:ProgramData 'CivicCast'

    # Whole logs dir -- it is small (text logs, not media/model data), per
    # the coordinator's note. Covers postgres.log, nats.log,
    # control_plane.log, ollama.log, and the rotating supervisor.log in one
    # bounded copy (see install_layout.default_log_root / service.py's
    # child_log_path -- all children log to <log_root>\<name>.log).
    $logsSrc = Join-Path $pdCivicCast 'logs'
    if (Test-Path $logsSrc) {
        try {
            & robocopy.exe $logsSrc (Join-Path $diagDir 'logs') /E /R:1 /W:1 /NFL /NDL /NJH /NJS 2>&1 |
                Out-File -FilePath (Join-Path $diagDir 'robocopy-logs.log') -Encoding UTF8
        } catch { "robocopy logs failed: $_" | Add-Content -Path $note -Encoding UTF8 }
    } else {
        "logs dir not present at $logsSrc (station never got far enough to log, or ProgramData path differs)" | Add-Content -Path $note -Encoding UTF8
    }

    # Config only -- /XD excludes 'data' and 'pgdata' so a misplaced
    # co-located data directory can never turn this into an unbounded copy
    # of the postgres cluster or NATS JetStream store.
    $configSrc = Join-Path $pdCivicCast 'config'
    if (Test-Path $configSrc) {
        try {
            & robocopy.exe $configSrc (Join-Path $diagDir 'config') /E /XD 'data' 'pgdata' 'nats-store' /R:1 /W:1 /NFL /NDL /NJH /NJS 2>&1 |
                Out-File -FilePath (Join-Path $diagDir 'robocopy-config.log') -Encoding UTF8
        } catch { "robocopy config failed: $_" | Add-Content -Path $note -Encoding UTF8 }
    } else {
        "config dir not present at $configSrc" | Add-Content -Path $note -Encoding UTF8
    }

    try { (& sc.exe qc CivicCastSupervisor 2>&1 | Out-String) | Set-Content -Path (Join-Path $diagDir 'sc-qc.txt') -Encoding UTF8 } catch { "sc qc capture failed: $_" | Add-Content -Path $note -Encoding UTF8 }
    try { (& sc.exe query CivicCastSupervisor 2>&1 | Out-String) | Set-Content -Path (Join-Path $diagDir 'sc-query.txt') -Encoding UTF8 } catch { "sc query capture failed: $_" | Add-Content -Path $note -Encoding UTF8 }
    try {
        $ns = (& netstat.exe -ano 2>&1)
        ($ns | Select-String -Pattern 'LISTENING') | Out-String | Set-Content -Path (Join-Path $diagDir 'netstat-listening.txt') -Encoding UTF8
    } catch { "netstat capture failed: $_" | Add-Content -Path $note -Encoding UTF8 }
    try {
        $taskPattern = 'python|pythonservice|civiccast|postgres|nats|ollama'
        $rows = (& tasklist.exe /v /fo csv 2>&1) | ConvertFrom-Csv -ErrorAction SilentlyContinue |
            Where-Object { $_.'Image Name' -match $taskPattern }
        $rows | Format-Table -AutoSize | Out-String -Width 300 | Set-Content -Path (Join-Path $diagDir 'tasklist-filtered.txt') -Encoding UTF8
    } catch { "tasklist capture failed: $_" | Add-Content -Path $note -Encoding UTF8 }

    try {
        $winEventStart = $RunStart
        $startedMarker = Join-Path $OutDir '_STARTED.marker'
        if (Test-Path $startedMarker) { $winEventStart = (Get-Item $startedMarker).CreationTime }
        $events = Get-WinEvent -FilterHashtable @{
            LogName = 'Application', 'System'; Level = 1, 2, 3; StartTime = $winEventStart
        } -MaxEvents 200 -ErrorAction SilentlyContinue
        $eventRows = @($events | ForEach-Object {
            [ordered]@{
                TimeCreated  = $_.TimeCreated.ToString('o')
                LogName      = $_.LogName
                LevelDisplay = $_.LevelDisplayName
                ProviderName = $_.ProviderName
                Id           = $_.Id
                Message      = ($_.Message -split "`n" | Select-Object -First 5) -join ' | '
            }
        })
        ($eventRows | ConvertTo-Json -Depth 4) | Set-Content -Path (Join-Path $diagDir 'winevent-app-system.json') -Encoding UTF8
    } catch { "winevent capture failed: $_" | Add-Content -Path $note -Encoding UTF8 }

    if ($InstallDir) {
        foreach ($f in @('activation-self-test.json', 'station-set.json')) {
            $src = Join-Path $InstallDir $f
            if (Test-Path $src) {
                Copy-Item -LiteralPath $src -Destination (Join-Path $diagDir $f) -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# ============================================================================
# HARDENED 2026-08-18 -- helpers added for T2 (render assert), T3 (real
# authenticated content loop), and T4 (product-engine egress) upgrades.
# audit findings this section addresses:
#   QA-F1: the old T2 pass criterion was "200 status + >0 bytes", which is
#          true for the served SPA shell whether or not the SPA ever mounts.
#          Test-RenderAssert below drives real headless Edge and requires
#          the DOM to grow far past the raw shell AND contain real UI copy.
#   QA-F2: the old T4 "egress" proof piped raw ffmpeg straight at a UDP
#          port -- it proved ffmpeg works, not that CivicCast's own egress
#          engine (config -> daemon -> sink) works. The T4 section now
#          attempts to drive that engine through its real staff API first
#          and only falls back to the synthetic-ffmpeg proof, labeled
#          PASS_FFMPEG_FALLBACK (never plain PASS), if the API path is
#          genuinely blocked.
#   T3:    a real authenticated content loop -- installer nonce -> staff
#          bearer token -> generate/upload/package/publish an asset ->
#          prove it on the public surface -> prove offline captions land.
#
# All HTTP calls in these helpers go through Invoke-CivicCastApi so every
# step logs method/url/status, and any >=400 response has its body
# captured -- consistent with this file's existing philosophy of leaving a
# forensic trail even when a step fails, rather than just failing silently.
# ============================================================================

Add-Type -AssemblyName System.Net.Http

# Generic JSON-capable HTTP helper. Never throws past its own boundary --
# failures (including non-2xx responses) are captured into the returned
# object so callers can make bounded, fail-honest decisions instead of
# relying on try/catch control flow for expected-failure paths (e.g. a 404
# probing for an endpoint that may not exist on this build).
function Invoke-CivicCastApi {
    param(
        [string]$Method,
        [string]$Url,
        [string]$LogFile,
        [object]$BodyObj = $null,
        [string]$BearerToken = $null,
        [string]$SetupNonce = $null,
        [int]$TimeoutSec = 30
    )
    $result = [ordered]@{
        method = $Method; url = $Url; status = $null; ok = $false
        body_raw = $null; body_json = $null; error = $null
    }
    try {
        $headers = @{}
        if ($BearerToken) { $headers['Authorization'] = "Bearer $BearerToken" }
        if ($SetupNonce) { $headers['X-CivicCast-Setup-Nonce'] = $SetupNonce }
        $params = @{
            Uri = $Url; Method = $Method; Headers = $headers; UseBasicParsing = $true
            TimeoutSec = $TimeoutSec; ErrorAction = 'Stop'
        }
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
            } catch {}
        }
        $result.error = "$_"
    }
    if ($result.body_raw) {
        try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    try {
        "$Method $Url -> status:$($result.status) ok:$($result.ok) err:$($result.error)" | Add-Content -Path $LogFile -Encoding UTF8
        if ((-not $result.ok) -or ($result.status -ge 400)) {
            "  BODY: $($result.body_raw)" | Add-Content -Path $LogFile -Encoding UTF8
        }
    } catch {}
    return $result
}

# Multipart asset upload -- Windows PowerShell 5.1's Invoke-WebRequest has
# no -Form parameter (that is PowerShell 6+ only), so multipart/form-data
# is built by hand via System.Net.Http.MultipartFormDataContent.
function Invoke-AssetUpload {
    param(
        [string]$BaseUrl, [string]$Token, [string]$AssetId, [string]$Title,
        [string]$FilePath, [string]$LogFile, [int]$TimeoutSec = 180
    )
    $url = "$BaseUrl/api/staff/assets/upload"
    $result = [ordered]@{ method = 'POST'; url = $url; status = $null; ok = $false; body_raw = $null; body_json = $null; error = $null }
    try {
        $handler = New-Object System.Net.Http.HttpClientHandler
        $client = New-Object System.Net.Http.HttpClient($handler)
        $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
        $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $Token)
        $content = New-Object System.Net.Http.MultipartFormDataContent
        $content.Add((New-Object System.Net.Http.StringContent($AssetId)), 'asset_id')
        $content.Add((New-Object System.Net.Http.StringContent($Title)), 'title')
        $fileBytes = [System.IO.File]::ReadAllBytes($FilePath)
        $fileContent = New-Object System.Net.Http.ByteArrayContent(,$fileBytes)
        try { $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('video/mp4') } catch {}
        $content.Add($fileContent, 'file', [System.IO.Path]::GetFileName($FilePath))
        $resp = $client.PostAsync($url, $content).Result
        $result.status = [int]$resp.StatusCode
        $result.body_raw = $resp.Content.ReadAsStringAsync().Result
        $result.ok = $resp.IsSuccessStatusCode
        try { $client.Dispose() } catch {}
    } catch {
        $result.error = "$_"
    }
    if ($result.body_raw) {
        try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch {}
    }
    try {
        "POST $url -> status:$($result.status) ok:$($result.ok) err:$($result.error)" | Add-Content -Path $LogFile -Encoding UTF8
        if ((-not $result.ok) -or ($result.status -ge 400)) {
            "  BODY: $($result.body_raw)" | Add-Content -Path $LogFile -Encoding UTF8
        }
    } catch {}
    return $result
}

# Probe the shipped ffmpeg's h264 encoder before trusting it for real work.
# The shipped pack is the LGPL/v3 build (no GPL libx264) -- resolve_h264_
# encoder in the native stream code falls back to libopenh264 on a CPU-only
# box, so that is what this harness must probe and use too.
function Test-Libopenh264 {
    param([string]$FfmpegExe)
    if (-not $FfmpegExe -or -not (Test-Path $FfmpegExe)) { return $false }
    try {
        $tmp = Join-Path $env:TEMP ("probe-" + [Guid]::NewGuid().ToString('N') + '.mp4')
        $probeArgs = @('-y','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=320x240:rate=25','-t','1','-c:v','libopenh264', $tmp)
        $p = Start-Process -FilePath $FfmpegExe -ArgumentList $probeArgs -PassThru -NoNewWindow -Wait
        $ok = ($p.ExitCode -eq 0) -and (Test-Path $tmp) -and ((Get-Item $tmp -ErrorAction SilentlyContinue).Length -gt 0)
        Remove-Item -Path $tmp -Force -ErrorAction SilentlyContinue
        return [bool]$ok
    } catch { return $false }
}

# Locate msedge.exe -- verify the standard path at runtime, fall back to
# where.exe, exactly per the coordinator's environment notes.
function Get-EdgePath {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    try {
        $found = & where.exe msedge.exe 2>$null | Select-Object -First 1
        if ($found -and (Test-Path $found)) { return $found }
    } catch {}
    return $null
}

# Bounded headless-Edge dump-dom. Uses a per-call --user-data-dir (a shared
# profile can attach to / hang on another running Edge session -- observed
# on the host during dry-run) and a HARD kill via $p.WaitForExit(ms) rather
# than -Wait, so a stuck render can never hang the whole harness run.
function Invoke-HeadlessDumpDom {
    param([string]$EdgeExe, [string]$Url, [string]$OutFile, [int]$TimeoutSec = 75, [int]$VirtualTimeBudgetMs = 10000)
    $result = [ordered]@{ url = $Url; ok = $false; timed_out = $false; exit_code = $null; error = $null }
    $udd = Join-Path $env:TEMP ("edge-udd-" + [Guid]::NewGuid().ToString('N'))
    try {
        New-Item -ItemType Directory -Force -Path $udd | Out-Null
        $edgeArgs = @(
            '--headless=new','--disable-gpu','--hide-scrollbars','--no-first-run',
            '--disable-extensions','--disable-sync','--disable-background-networking',
            '--disable-default-apps','--disable-component-update',
            '--disable-client-side-phishing-detection',
            "--user-data-dir=$udd",
            "--virtual-time-budget=$VirtualTimeBudgetMs",
            '--dump-dom', $Url
        )
        $stderrFile = "$OutFile.stderr.log"
        $p = Start-Process -FilePath $EdgeExe -ArgumentList $edgeArgs -PassThru -NoNewWindow `
            -RedirectStandardOutput $OutFile -RedirectStandardError $stderrFile
        $p.Handle | Out-Null   # forces handle creation so WaitForExit is reliable (known PS quirk)
        $finished = $p.WaitForExit($TimeoutSec * 1000)
        if (-not $finished) {
            $result.timed_out = $true
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        } else {
            $result.exit_code = $p.ExitCode
            $result.ok = $true
        }
    } catch {
        $result.error = "$_"
    } finally {
        try { Remove-Item -Recurse -Force -Path $udd -ErrorAction SilentlyContinue } catch {}
    }
    return $result
}

# T2 render assert (QA-F1 fix). The raw HTTP capture proves the server
# returned *a* response; it says nothing about whether the SPA actually
# mounted. PASS requires the dumped DOM to be both a large multiple of the
# raw shell's size AND to contain real UI copy that provably is not in the
# raw shell -- so a large-but-broken response (e.g. a stack trace page)
# can't fake a pass just by being bigger than the shell.
function Test-RenderAssert {
    param([string]$Label, [string]$Url, [string[]]$KnownStrings, [string]$EdgeExe, [string]$DomOutFile)
    $r = [ordered]@{
        label = $Label; url = $Url; raw_bytes = 0; dumped_bytes = 0; ratio = 0.0
        known_string_matched = $null; known_string_in_raw = $false
        edge_ok = $false; timed_out = $false; error = $null; result = 'FAIL'
    }
    try {
        $rawResp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 15 -ErrorAction Stop
        $rawBody = [string]$rawResp.Content
    } catch {
        $r.error = "raw fetch failed: $_"
        return $r
    }
    $r.raw_bytes = $rawBody.Length
    foreach ($ks in $KnownStrings) {
        if ($rawBody.Contains($ks)) { $r.known_string_in_raw = $true }
    }
    if (-not $EdgeExe) {
        $r.error = 'msedge.exe not found on this box (checked standard path + where.exe)'
        return $r
    }
    $dump = Invoke-HeadlessDumpDom -EdgeExe $EdgeExe -Url $Url -OutFile $DomOutFile
    $r.edge_ok = $dump.ok
    $r.timed_out = $dump.timed_out
    if ($dump.error -and -not $r.error) { $r.error = $dump.error }
    if ($r.timed_out) {
        if (-not $r.error) { $r.error = 'headless Edge dump-dom timed out' }
        return $r
    }
    if (-not (Test-Path $DomOutFile)) {
        $r.error = 'no DOM output file produced'
        return $r
    }
    $dumpedBody = Get-Content -Path $DomOutFile -Raw -ErrorAction SilentlyContinue
    if (-not $dumpedBody) { $dumpedBody = '' }
    $r.dumped_bytes = $dumpedBody.Length
    if ($r.raw_bytes -gt 0) { $r.ratio = [Math]::Round(([double]$r.dumped_bytes / [double]$r.raw_bytes), 2) }
    foreach ($ks in $KnownStrings) {
        if ($dumpedBody.Contains($ks)) { $r.known_string_matched = $ks; break }
    }
    $pass = ($r.dumped_bytes -gt (3 * $r.raw_bytes)) -and ($r.dumped_bytes -gt 3000) -and ($null -ne $r.known_string_matched) -and (-not $r.known_string_in_raw)
    if ($pass) { $r.result = 'PASS' } else { $r.result = 'FAIL' }
    return $r
}

# TSDuck tsp verification -- same command pattern as the kit's own
# verify-egress.ps1 (-I ip <port> -P until --seconds N -P analyze --json),
# reimplemented standalone here because verify-egress.ps1 hardcodes a fixed
# 3-channel/3-port set (public/education/government @ 9001-9003) and T4's
# product-engine attempt targets one channel on a dedicated port so it can
# never collide with the synthetic-ffmpeg fallback's fixed ports.
function Test-TsProof {
    param([string]$TspExe, [int]$Port, [int]$Seconds, [string]$OutDir, [string]$Label)
    $result = [ordered]@{
        label = $Label; port = $Port; tsp_found = $false; ran = $false; timed_out = $false
        exit_code = $null; report_found = $false
        invalid_syncs = $null; transport_errors = $null; discontinuities = $null
        verdict = 'not-run'
    }
    if (-not $TspExe -or -not (Test-Path $TspExe)) {
        $result.verdict = 'not-run: tsp.exe not found'
        return $result
    }
    $result.tsp_found = $true
    $report = Join-Path $OutDir "tsduck-$Label-report.json"
    $stdout = Join-Path $OutDir "tsduck-$Label.stdout.log"
    $stderr = Join-Path $OutDir "tsduck-$Label.stderr.log"
    $tspArgs = @('-I','ip',"$Port",'--buffer-size','16777216','-P','until','--seconds',"$Seconds",'-P','analyze','--json','--output-file',$report,'-O','drop')
    try {
        $proc = Start-Process -FilePath $TspExe -ArgumentList $tspArgs -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $timeoutSec = $Seconds + 20
        try {
            Wait-Process -Id $proc.Id -Timeout $timeoutSec -ErrorAction Stop
        } catch {
            $result.timed_out = $true
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $proc.Id -Timeout 5 -ErrorAction SilentlyContinue
        }
        $proc.Refresh()
        $result.ran = $true
        if (-not $result.timed_out) { $result.exit_code = $proc.ExitCode }
    } catch {
        $result.verdict = "error: $_"
        return $result
    }
    if (Test-Path $report) {
        $result.report_found = $true
        try {
            $j = Get-Content -Raw -Path $report | ConvertFrom-Json
            $invalidSyncs = 0
            $transportErrors = 0
            if ($j.ts -and $j.ts.packets) {
                if ($j.ts.packets.PSObject.Properties.Name -contains 'invalid-syncs') { $invalidSyncs = [int]$j.ts.packets.'invalid-syncs' }
                if ($j.ts.packets.PSObject.Properties.Name -contains 'transport-errors') { $transportErrors = [int]$j.ts.packets.'transport-errors' }
            }
            $disc = 0
            foreach ($pidRow in @($j.pids)) {
                if ($pidRow.packets -and ($pidRow.packets.PSObject.Properties.Name -contains 'discontinuities')) { $disc += [int]$pidRow.packets.discontinuities }
            }
            $result.invalid_syncs = $invalidSyncs
            $result.transport_errors = $transportErrors
            $result.discontinuities = $disc
            if ($invalidSyncs -eq 0 -and $transportErrors -eq 0 -and $disc -eq 0) { $result.verdict = 'pass' } else { $result.verdict = 'fail' }
        } catch {
            $result.verdict = "report-parse-error: $_"
        }
    } else {
        $result.verdict = 'fail-no-report'
    }
    return $result
}

try {
    # 0. SKIP-REINSTALL MODE -- EXPERIMENTAL, OPT-IN ONLY, GATED (2026-08-19).
    #    A live run proved this mode's core premise wrong: station_up stayed
    #    False because CivicCastSupervisor never existed to answer on 8000.
    #    Root-caused afterward (static discovery, no further launches): the
    #    Windows service registration, HKLM\SOFTWARE\CivicCast\Native\
    #    DatabaseUrl / SetupNonce, AND the PostgreSQL/NATS data directories
    #    themselves ALL live under %ProgramData%\CivicCast and the registry --
    #    both on the Sandbox's own OS disk, which resets EVERY session. Only
    #    C:\CivicCastHostStore\install (a MappedFolder) survives. So
    #    station-set.json existing there proves activation/model-staging
    #    finished once; it does NOT prove postgres/service state is
    #    recoverable this session -- restoring that would need the real
    #    installer's provisioning step, which itself needs an installer-only
    #    Ed25519 pack public key this harness has no safe way to obtain (see
    #    PREFLIGHT.md next to this script for the full writeup). Given that,
    #    and per the coordinator's explicit "stop discovering serially, gate
    #    it" decision: this path is now OFF BY DEFAULT. The proven, working
    #    full-install path (installer + activation, every run) is what
    #    actually runs unless BOTH an explicit opt-in marker AND the
    #    persistence signal are present -- so an ordinary run can never be
    #    silently short-circuited by a stray leftover station-set.json.
    $PersistentInstallDir = 'C:\CivicCastHostStore\install'
    $SkipModeOptInFile = Join-Path $OutDir 'SKIP_MODE.txt'
    $skipModeOptedIn = Test-Path $SkipModeOptInFile
    $stationSetPresent = $false
    try {
        if (Test-Path (Join-Path $PersistentInstallDir 'station-set.json')) { $stationSetPresent = $true }
    } catch {}
    $skipReinstall = $skipModeOptedIn -and $stationSetPresent
    $summary.skip_mode_opted_in = $skipModeOptedIn
    $summary.skip_mode_station_set_present = $stationSetPresent
    $summary.skip_reinstall = $skipReinstall
    $installResultFile = Join-Path $OutDir 'INSTALL-RESULT.txt'

    if ($skipReinstall) {
        "INSTALL=SKIPPED_PERSISTENT_EXPERIMENTAL install_dir=$PersistentInstallDir checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $installResultFile -Encoding UTF8
        "opt_in_file=$SkipModeOptInFile station_set_present=$stationSetPresent" | Add-Content -Path $installResultFile -Encoding UTF8
        Write-Marker -Name '_SKIP_REINSTALL.marker' -Content (Get-Date).ToString('o')
        $summary.installer_source = "SKIPPED (SKIP_MODE.txt opt-in + persistent station-set.json found at $PersistentInstallDir)"
        $summary.silent_flag_used = 'SKIPPED_PERSISTENT_EXPERIMENTAL'
        $summary.installer_exit_code = 'SKIPPED'
        # No fresh install ran this session -- there is no real "just
        # installed" boot to time. Use "now" so station_boot_seconds still
        # reports a bounded, non-null number (time from re-registration
        # attempt to health) instead of silently going null in this mode.
        $script:AfterInstallTime = Get-Date
        Save-Summary -Step 'install-skipped-persistent'

        # EXPERIMENTAL, best-effort, NON-BLOCKING: attempt to re-register the
        # CivicCastSupervisor Windows service against the persistent install
        # via its real, module-level SCM entry point (confirmed by reading
        # supervisor\service_host.py: `win32serviceutil.HandleCommandLine`,
        # the exact same mechanism pythonservice.exe uses). This ONLY
        # recreates the service object -- it does nothing about the missing
        # DatabaseUrl/postgres-data problem above, so it is expected to leave
        # the service unable to actually start in most sandbox sessions; it
        # is attempted anyway (cheap, ~seconds) in case a future run's
        # environment differs, and its result is informational only. Any
        # failure here is caught and logged, never thrown -- this step must
        # never block reaching the existing (unconditional, already-bounded)
        # service-state/start-attempt logic below.
        $expLog = Join-Path $OutDir 'SKIP-MODE-SERVICE-REREGISTER.txt'
        "attempted_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $expLog -Encoding UTF8
        try {
            $runtimePython = Join-Path $PersistentInstallDir 'runtime\python.exe'
            "runtime_python=$runtimePython present=$([bool](Test-Path $runtimePython))" | Add-Content -Path $expLog -Encoding UTF8
            if (Test-Path $runtimePython) {
                $regOut = Join-Path $OutDir 'SKIP-MODE-SERVICE-REREGISTER.stdout.log'
                $regErr = Join-Path $OutDir 'SKIP-MODE-SERVICE-REREGISTER.stderr.log'
                $regArgs = @('-m', 'civiccast.native.supervisor.service_host', 'install')
                $regProc = Start-Process -FilePath $runtimePython -ArgumentList $regArgs -PassThru -NoNewWindow -Wait `
                    -RedirectStandardOutput $regOut -RedirectStandardError $regErr -WorkingDirectory $PersistentInstallDir
                "service_host_install_exit_code=$($regProc.ExitCode)" | Add-Content -Path $expLog -Encoding UTF8
            } else {
                "SKIPPED: runtime python.exe not found -- cannot attempt registration" | Add-Content -Path $expLog -Encoding UTF8
            }
        } catch {
            "EXPERIMENTAL_REGISTRATION_ERROR (non-fatal, continuing): $_" | Add-Content -Path $expLog -Encoding UTF8
        }
        "note=this step is informational only; DatabaseUrl/postgres-data are still expected to be missing this session -- see PREFLIGHT.md" | Add-Content -Path $expLog -Encoding UTF8
        Save-Summary -Step 'skip-mode-experimental-service-reregister'
    } else {
        $skipGateNote = if ($skipModeOptedIn -and -not $stationSetPresent) {
            ' (SKIP_MODE.txt present but no persistent station-set.json found -- opt-in condition not met)'
        } elseif (-not $skipModeOptedIn -and $stationSetPresent) {
            ' (persistent station-set.json found but SKIP_MODE.txt opt-in not present -- full install runs by default)'
        } else {
            ''
        }
        "INSTALL=RAN_FRESH checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))$skipGateNote" | Set-Content -Path $installResultFile -Encoding UTF8

        # 1. Run the installer DIRECTLY from the read-only host-mapped payload
        #    ($PayloadDir = C:\CivicCastPayload). The old harness copied the whole
        #    payload to a local writable stage first, but this kit carries ~22.9GB
        #    of station models -- copying it in, then letting the install stage the
        #    packs AND activation cache the station bundle, blew past the Sandbox's
        #    virtual disk (os error 112 "not enough space" during station-pack
        #    cache). The installer only READS $EXEDIR\packs and $EXEDIR\station and
        #    writes solely to $INSTDIR, so a read-only $EXEDIR is fine and saves the
        #    entire 22.9GB copy.
        $LocalInstallStage = $PayloadDir
        $exe = Get-ChildItem -Path $PayloadDir -Filter '*setup.exe' | Select-Object -First 1
        if (-not $exe) {
            throw "No *setup.exe found in mapped payload at $PayloadDir"
        }
        $summary.installer_source = $exe.FullName
        try {
            $summary.installer_sha256 = (Get-FileHash -Path $exe.FullName -Algorithm SHA256).Hash.ToLower()
        } catch { $summary.errors += "hash of staged exe failed: $_" }

        $packsDir = Join-Path $PayloadDir 'packs'
        $summary.errors += "packs dir present: $(Test-Path $packsDir); contents: $((Get-ChildItem $packsDir -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -join ', ')"
        Save-Summary -Step 'staged-payload'

        # 2. Run the installer silently. Tauri/NSIS convention is uppercase /S for
        #    silent mode (no UI, no prompts, default install dir). Capture the raw
        #    process exit code -- nsis-hooks-bootstrap.nsh's CIVICCAST_FAIL macro
        #    (SetErrorLevel + Abort) makes the process exit code a real, meaningful
        #    signal of which postinstall step failed (110=pack delivery,
        #    111/112/121/122=D2 verify, 116-119=D4 provision/service/firewall,
        #    120=install-over-existing refusal, 123=D4 activation [K1], etc).
        # /D= sets the NSIS install directory to the WRITABLE host-mapped folder
        # (C:\CivicCastHostStore\install, backed by the host's 1.2TB) so the WHOLE
        # install -- stage-packs, provision (which creates the dependencies/
        # junctions in place), and activation (which stages ~40GB of models and
        # REFUSES junction/symlink install-roots) -- runs natively on real disk
        # instead of the Sandbox's ~40GB virtual C:. /D must be the LAST argument
        # and unquoted (NSIS quirk); the path has no spaces so this is clean.
        $summary.silent_flag_used = '/S /D=C:\CivicCastHostStore\install'
        Write-Marker -Name '_BEFORE_INSTALL.marker' -Content (Get-Date).ToString('o')
        try {
            $proc = Start-Process -FilePath $exe.FullName -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait -WindowStyle Hidden
            $summary.installer_exit_code = $proc.ExitCode
        } catch {
            $summary.installer_launch_error = "$_"
            $summary.errors += "installer launch/wait failed: $_"
        }
        Write-Marker -Name '_AFTER_INSTALL.marker' -Content (Get-Date).ToString('o')
        # station_boot_seconds (station-up-wait, below) is measured from this
        # timestamp -- capture it as a real DateTime now rather than
        # re-parsing the marker file back off disk later.
        $script:AfterInstallTime = Get-Date
        Save-Summary -Step 'installer-ran'

        # Give any late-writing child processes (service self-registration, log
        # flush) a short, BOUNDED grace window before we start reading state.
        Start-Sleep -Seconds 15
        Save-Summary -Step 'post-install-grace-sleep'
    }

    # 3. Locate the install directory. SKIP-REINSTALL MODE: no installer ran
    #    this session, so there is no fresh ARP registration to find (ARP is
    #    registry/OS state and does not persist across Sandbox sessions) --
    #    use the known, fixed /D= target directly instead. Otherwise, don't
    #    assume a path -- check ARP (Add/Remove Programs) registry entries
    #    first (authoritative, InstallLocation), then fall back to a
    #    directory-name scan of the two Program Files roots.
    if ($skipReinstall) {
        $installDir = $null
        if (Test-Path $PersistentInstallDir) { $installDir = $PersistentInstallDir }
        $summary.install_dir_candidates = @($PersistentInstallDir)
        $summary.install_dir_found = $installDir
        Save-Summary -Step 'install-dir-located'
    } else {
        $arpRoots = @(
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
        )
        $arpHits = foreach ($root in $arpRoots) {
            Get-ItemProperty -Path $root -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -like '*CivicCast*' }
        }
        foreach ($hit in $arpHits) {
            $summary.arp_entries += [ordered]@{
                DisplayName     = $hit.DisplayName
                DisplayVersion  = $hit.DisplayVersion
                InstallLocation = $hit.InstallLocation
                UninstallString = $hit.UninstallString
                EstimatedSize   = $hit.EstimatedSize
            }
        }

        $candidates = New-Object System.Collections.Generic.List[string]
        foreach ($hit in $arpHits) {
            if ($hit.InstallLocation) { $candidates.Add($hit.InstallLocation) }
        }
        foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
            if ($root -and (Test-Path $root)) {
                Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
                    Where-Object { $_.Name -like '*Civic*' } |
                    ForEach-Object { $candidates.Add($_.FullName) }
            }
        }
        $candidates = $candidates | Select-Object -Unique
        $summary.install_dir_candidates = $candidates

        $installDir = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        $summary.install_dir_found = $installDir
        Save-Summary -Step 'install-dir-located'
    }

    if ($installDir) {
        # Top-level + one-level-deep tree listing (bounded: only immediate
        # children, and only the first 50 grandchildren per container -- this
        # was already safe in the previous version and is unchanged).
        $summary.install_tree_top_levels = Get-ChildItem -Path $installDir -Force -ErrorAction SilentlyContinue |
            ForEach-Object {
                $entry = [ordered]@{ name = $_.Name; type = if ($_.PSIsContainer) {'dir'} else {'file'} }
                if ($_.PSIsContainer) {
                    $entry.children = (Get-ChildItem -Path $_.FullName -Force -ErrorAction SilentlyContinue |
                        Select-Object -First 50 -ExpandProperty Name)
                }
                $entry
            }
        Save-Summary -Step 'install-tree-top-levels'

        # 4. TARGETED (non-recursive) lookup for the two activation-related
        #    marker files -- see Test-KnownPaths above. Checks:
        #      <installDir>\station-set.json
        #      <installDir>\app\station-set.json
        #      <installDir>\app\*\station-set.json  (shallow, one level)
        #      %ProgramData%\CivicCast\station-set.json
        #    and the same four shapes for activation-self-test.json.
        $summary.station_set_json_found = Test-KnownPaths -InstallDir $installDir -FileName 'station-set.json'
        Save-Summary -Step 'station-set-json-check'
        $summary.activation_self_test_json_found = Test-KnownPaths -InstallDir $installDir -FileName 'activation-self-test.json'
        Save-Summary -Step 'activation-self-test-json-check'
    } else {
        # No install dir found via ARP/Program Files scan -- still check the
        # ProgramData-only shape of Test-KnownPaths so we don't silently skip
        # the one location that doesn't depend on $installDir. Pass a
        # nonexistent dummy install dir so only the ProgramData branch fires.
        $summary.station_set_json_found = Test-KnownPaths -InstallDir 'C:\__no-install-dir-found__' -FileName 'station-set.json'
        $summary.activation_self_test_json_found = Test-KnownPaths -InstallDir 'C:\__no-install-dir-found__' -FileName 'activation-self-test.json'
        Save-Summary -Step 'marker-check-no-install-dir'
    }

    # 4b. If activation did NOT write station-set.json, re-run the activation
    #     CLI directly against the (now fully provisioned) install with full
    #     stdout+stderr captured, so we get the EXACT underlying error the NSIS
    #     ExecToLog swallowed (the installer only logs a generic "bundle not
    #     found" template + exit 123). This reproduces the same activation the
    #     installer ran, against the same install dir, bundle, and runtimes.
    # Bulletproof plain-text capture (NO ConvertTo-Json, OS-level stream
    # redirect so the activation stderr lands on disk even if this script
    # later dies): write activation-rerun.log + a flat result file.
    $rr = Join-Path $OutDir 'ACTIVATION-RESULT.txt'
    "installer_exit_code=$($summary.installer_exit_code)" | Set-Content -Path $rr -Encoding UTF8
    "install_dir=$installDir" | Add-Content -Path $rr -Encoding UTF8
    $stationHit = ($summary.station_set_json_found | Measure-Object).Count
    "station_set_json_found_after_install=$stationHit" | Add-Content -Path $rr -Encoding UTF8
    if ($stationHit -eq 0 -and $installDir) {
        # With /D=C:\CivicCastHostStore\install the install already lives on the
        # host-backed folder (real disk, junctions intact). If the installer's
        # OWN activation still didn't write station-set.json, re-run activation
        # directly against that same install root (NO copy -- copying breaks the
        # provision-created dependency junctions), with cache on host disk too.
        $hostStore   = 'C:\CivicCastHostStore'
        $hostInstall = $installDir
        $cache       = Join-Path $hostStore 'cache'
        $bundle      = 'C:\CivicCastPayload\station\station-index.json'
        "hoststore_present=$([bool](Test-Path $hostStore))" | Add-Content -Path $rr -Encoding UTF8
        "hostinstall=$hostInstall" | Add-Content -Path $rr -Encoding UTF8
        $exe = Join-Path $hostInstall 'CivicCast Native.exe'
        "rerun_exe=$exe present=$([bool](Test-Path $exe))" | Add-Content -Path $rr -Encoding UTF8
        "rerun_bundle=$bundle present=$([bool](Test-Path $bundle))" | Add-Content -Path $rr -Encoding UTF8
        if ((Test-Path $exe) -and (Test-Path $bundle)) {
            New-Item -ItemType Directory -Force -Path $cache | Out-Null
            $outLog = Join-Path $OutDir 'activation-rerun.stdout.log'
            $errLog = Join-Path $OutDir 'activation-rerun.stderr.log'
            "(started $(Get-Date -Format o))" | Set-Content -Path $errLog -Encoding UTF8
            # GUI-subsystem Tauri app: use Start-Process -Wait (the call operator
            # does not wait for GUI apps); explicit-quoted arg string so the
            # space+parens in the install path survive Windows PowerShell 5.1.
            $argStr = '--civiccast-activate-station --install-root "' + $hostInstall + '"' +
                      ' --civiccast-import-station "' + $bundle + '"' +
                      ' --cache-root "' + $cache + '"'
            $proc = Start-Process -FilePath $exe -ArgumentList $argStr -Wait -PassThru `
                -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
            "rerun_exit_code=$($proc.ExitCode)" | Add-Content -Path $rr -Encoding UTF8
            # station-set.json / activation-self-test.json now land in the
            # host-mapped install root. Copy any proof out to $OutDir.
            $ssPath = Join-Path $hostInstall 'station-set.json'
            $stPath = Join-Path $hostInstall 'activation-self-test.json'
            "station_set_json_found_after_rerun=$([int](Test-Path $ssPath))" | Add-Content -Path $rr -Encoding UTF8
            "station_set_path=$ssPath" | Add-Content -Path $rr -Encoding UTF8
            if (Test-Path $ssPath) {
                Copy-Item -LiteralPath $ssPath -Destination (Join-Path $OutDir 'PROVEN-station-set.json') -Force -ErrorAction SilentlyContinue
            }
            if (Test-Path $stPath) {
                Copy-Item -LiteralPath $stPath -Destination (Join-Path $OutDir 'PROVEN-activation-self-test.json') -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # 5. CivicCastSupervisor service state -- Get-Service (typed) and raw
    #    sc.exe query / qc (matches exactly what the installer's own
    #    PREINSTALL refusal-gate check does: "sc query CivicCastSupervisor",
    #    exit 0 = registered, 1060 = ERROR_SERVICE_DOES_NOT_EXIST = not
    #    registered). None of these three calls block/wait.
    $svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
    if ($svc) {
        $summary.service_get_service = [ordered]@{
            Name              = $svc.Name
            Status            = $svc.Status.ToString()
            StartType         = $svc.StartType.ToString()
        }
    } else {
        $summary.service_get_service = $null
    }
    $summary.service_sc_query_raw = (& sc.exe query CivicCastSupervisor 2>&1 | Out-String)
    $summary.service_sc_qc_raw    = (& sc.exe qc CivicCastSupervisor 2>&1 | Out-String)
    Save-Summary -Step 'service-state-query'

    # (c) OPTIONAL bounded start attempt -- only if the service is actually
    # registered and not already running, so we learn whether it CAN run
    # (vs. dead-ending pre-activation) rather than just its at-rest status.
    # Start-Service itself does not block; the wait below is capped at 60s
    # and polls Status rather than doing any unbounded wait.
    if ($svc -and $svc.Status -ne 'Running') {
        $attempt = [ordered]@{
            attempted       = $true
            start_error     = $null
            status_after    = $null
            reached_running = $false
            poll_seconds    = 0
        }
        try {
            Start-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
        } catch {
            $attempt.start_error = "$_"
        }
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
            $attempt.poll_seconds += 3
            $cur = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
            $attempt.status_after = if ($cur) { $cur.Status.ToString() } else { 'unknown' }
            if ($cur -and $cur.Status -eq 'Running') { $attempt.reached_running = $true; break }
            if ($cur -and $cur.Status -in @('Stopped','StopPending') -and $attempt.start_error) { break }
        }
        $summary.service_start_attempt = $attempt
    } elseif ($svc) {
        $summary.service_start_attempt = [ordered]@{ attempted = $false; reason = "already $($svc.Status)" }
    } else {
        $summary.service_start_attempt = [ordered]@{ attempted = $false; reason = 'service not registered' }
    }
    Save-Summary -Step 'service-start-attempt'

    # 5b. STATION-UP WAIT (HARDENED <gate-a-station-up-wait-and-log-capture>
    #     after 8579e66-run3: the old version polled 3 endpoints
    #     SEQUENTIALLY at up to 180s EACH -- ~9.5 minutes total -- then gave
    #     up. The Aug-19 reference run only worked because ~25 minutes of
    #     unrelated activation work happened to sit between install and this
    #     check, giving the station time to cold-boot postgres+nats+
    #     control-plane; 8579e66-run3 had no such gap and the station simply
    #     never got there within the old bound. This version polls ONLY
    #     /api/health on a single bounded 20-minute deadline (6s interval),
    #     logs every poll's timestamp + outcome/error to
    #     STATION-UP-WAIT.txt, and only probes /operator/ and / (short,
    #     60s-bounded each) AFTER health itself has answered 200 --
    #     matching the coordinator's exact spec. station_boot_seconds is
    #     measured from _AFTER_INSTALL.marker (informational only: Gate A's
    #     judge records it but does not fail on duration -- Gate B owns
    #     timing).
    $rt = Join-Path $OutDir 'RUNTIME-RESULT.txt'
    $stationWaitLog = Join-Path $OutDir 'STATION-UP-WAIT.txt'
    "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $rt -Encoding UTF8
    $afterInstallIso = if ($script:AfterInstallTime) { $script:AfterInstallTime.ToUniversalTime().ToString('o') } else { '<not-set>' }
    "wait_started_utc=$((Get-Date).ToUniversalTime().ToString('o')) after_install_marker_utc=$afterInstallIso deadline_minutes=20 poll_interval_seconds=6" |
        Set-Content -Path $stationWaitLog -Encoding UTF8

    $endpoints = [ordered]@{
        health           = 'http://127.0.0.1:8000/api/health'
        operator_console = 'http://127.0.0.1:8000/operator/'
        resident_portal  = 'http://127.0.0.1:8000/'
    }
    $summary.runtime_checks = [ordered]@{}

    # ---- health: the ONLY endpoint with the long (20-minute) bound ----
    $healthRes = [ordered]@{ url = $endpoints.health; status = $null; ok = $false; bytes = 0; snippet = $null; error = $null; polls = 0 }
    $stationFirstHealthyTime = $null
    $healthDeadline = (Get-Date).AddMinutes(20)
    while ((Get-Date) -lt $healthDeadline) {
        $healthRes.polls++
        $pollTs = (Get-Date).ToUniversalTime().ToString('o')
        try {
            $r = Invoke-WebRequest -Uri $endpoints.health -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            $healthRes.status = [int]$r.StatusCode
            $body = [string]$r.Content
            $healthRes.bytes = $body.Length
            $healthRes.snippet = ($body.Substring(0, [Math]::Min(300, $body.Length))) -replace '\s+', ' '
            if ($healthRes.status -eq 200 -and $healthRes.bytes -gt 0) {
                $healthRes.ok = $true
                $stationFirstHealthyTime = Get-Date
                "poll #$($healthRes.polls) $pollTs -> status:$($healthRes.status) STATION HEALTHY" | Add-Content -Path $stationWaitLog -Encoding UTF8
                break
            }
            "poll #$($healthRes.polls) $pollTs -> status:$($healthRes.status) ok:false bytes:$($healthRes.bytes)" | Add-Content -Path $stationWaitLog -Encoding UTF8
        } catch {
            $healthRes.error = "$($_.Exception.Message)"
            "poll #$($healthRes.polls) $pollTs -> ERROR: $($healthRes.error)" | Add-Content -Path $stationWaitLog -Encoding UTF8
        }
        Start-Sleep -Seconds 6
    }
    if (-not $healthRes.ok) {
        "wait_ended_utc=$((Get-Date).ToUniversalTime().ToString('o')) result=TIMEOUT total_polls=$($healthRes.polls) (20-minute bounded deadline reached, station never answered /api/health)" |
            Add-Content -Path $stationWaitLog -Encoding UTF8
    }
    $summary.runtime_checks['health'] = $healthRes
    "health=status:$($healthRes.status) ok:$($healthRes.ok) bytes:$($healthRes.bytes) polls:$($healthRes.polls) err:$($healthRes.error)" | Add-Content -Path $rt -Encoding UTF8

    $summary.station_up = [bool]$healthRes.ok
    $summary.station_first_healthy_utc = if ($stationFirstHealthyTime) { $stationFirstHealthyTime.ToUniversalTime().ToString('o') } else { $null }
    if ($stationFirstHealthyTime -and $script:AfterInstallTime) {
        $summary.station_boot_seconds = [Math]::Round((New-TimeSpan -Start $script:AfterInstallTime -End $stationFirstHealthyTime).TotalSeconds, 1)
    } else {
        $summary.station_boot_seconds = $null
    }
    "station_up=$($summary.station_up) station_first_healthy_utc=$($summary.station_first_healthy_utc) station_boot_seconds=$($summary.station_boot_seconds)" |
        Add-Content -Path $stationWaitLog -Encoding UTF8
    Save-Summary -Step 'station-up-wait'

    # ---- operator_console / resident_portal: ONLY after health=200, short 60s bound each ----
    foreach ($name in @('operator_console', 'resident_portal')) {
        $url = $endpoints[$name]
        $res = [ordered]@{ url = $url; status = $null; ok = $false; bytes = 0; snippet = $null; error = $null; polls = 0 }
        if ($healthRes.ok) {
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Date) -lt $deadline) {
                $res.polls++
                try {
                    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
                    $res.status = [int]$r.StatusCode
                    $body = [string]$r.Content
                    $res.bytes = $body.Length
                    $res.snippet = ($body.Substring(0, [Math]::Min(300, $body.Length))) -replace '\s+', ' '
                    if ($res.status -eq 200 -and $res.bytes -gt 0) { $res.ok = $true }
                    break
                } catch {
                    $res.error = "$($_.Exception.Message)"
                    Start-Sleep -Seconds 6
                }
            }
        } else {
            $res.error = 'skipped: /api/health did not answer 200 within the 20-minute station-up-wait deadline'
        }
        $summary.runtime_checks[$name] = $res
        "$name=status:$($res.status) ok:$($res.ok) bytes:$($res.bytes) polls:$($res.polls) err:$($res.error)" | Add-Content -Path $rt -Encoding UTF8
        Save-Summary -Step "runtime-check-$name"
    }
    # Capture the operator console + portal HTML to files for eyeball/browser proof.
    foreach ($name in @('operator_console','resident_portal','health')) {
        try {
            $u = $endpoints[$name]
            $r2 = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            [string]$r2.Content | Set-Content -Path (Join-Path $OutDir "ui-$name.html") -Encoding UTF8
        } catch {}
    }

    # Station diagnostics -- FIRST capture, right after the station-up
    # decision and BEFORE the runtime verdict downstream (Gate A's own
    # judge, and this script's T2/T3/T4/T5 gating below) consumes it.
    # Captured unconditionally (pass or fail) so a station that never came
    # up still leaves behind whatever the supervisor/postgres/nats/control-
    # plane children managed to log before giving up.
    try {
        Invoke-StationDiagCapture -OutDir $OutDir -InstallDir $installDir -Label 'after-station-up-wait' -RunStart $RunStart
    } catch {
        "station diag capture (after-station-up-wait) failed: $_" | Add-Content -Path (Join-Path $OutDir 'summary-write-errors.log') -Encoding UTF8
    }
    Save-Summary -Step 'station-diag-captured-after-wait'
    Save-Summary -Step 'runtime-ui-captured'

    # 5c. T2 RENDER ASSERT (QA-F1 fix). The T1 checks above only prove the
    #     server answered with 200 + nonzero bytes -- true for the bare SPA
    #     shell whether or not the SPA ever mounts. Drive headless Edge
    #     against both shells with a virtual-time budget so React's async
    #     data fetch (portal: assets/schedule; operator: setup/auth state)
    #     has time to resolve before dump-dom captures the DOM -- a bare
    #     --dump-dom with no time budget under-captures a still-loading SPA
    #     (confirmed on the host dry-run: 2.7KB without a time budget vs.
    #     11.9KB with one, on the SAME page). PASS requires the dumped DOM
    #     to be a large multiple of the raw shell AND contain real UI copy
    #     that provably is not present in the raw shell.
    $edgeExe = Get-EdgePath
    $t2 = Join-Path $OutDir 'T2-RENDER-RESULT.txt'
    "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t2 -Encoding UTF8
    "edge_exe=$edgeExe" | Add-Content -Path $t2 -Encoding UTF8
    $renderTargets = @(
        @{ label = 'portal';   url = $endpoints.resident_portal;  known = @('No live broadcast is on air.','Latest recordings','Coming up','Broadcast status'); out = (Join-Path $OutDir 'ui-dom-portal.html') },
        @{ label = 'operator'; url = $endpoints.operator_console; known = @('No live meeting broadcast','Open navigation','Setup First setup'); out = (Join-Path $OutDir 'ui-dom-operator.html') }
    )
    $summary.t2_render_checks = [ordered]@{}
    $t2AllPass = $true
    foreach ($t in $renderTargets) {
        $res = Test-RenderAssert -Label $t.label -Url $t.url -KnownStrings $t.known -EdgeExe $edgeExe -DomOutFile $t.out
        $summary.t2_render_checks[$t.label] = $res
        if ($res.result -ne 'PASS') { $t2AllPass = $false }
        "T2_$($t.label) raw=$($res.raw_bytes) dumped=$($res.dumped_bytes) ratio=$($res.ratio) known_matched=$($res.known_string_matched) known_in_raw=$($res.known_string_in_raw) edge_ok=$($res.edge_ok) timed_out=$($res.timed_out) error=$($res.error) result=$($res.result)" | Add-Content -Path $t2 -Encoding UTF8
    }
    "T2_RENDER=$(if($t2AllPass){'PASS'}else{'FAIL'})" | Add-Content -Path $t2 -Encoding UTF8
    Save-Summary -Step 't2-render-assert'

    # ================= T3 (loop/surfaces) · T4 (egress) · T5 (soak) =================
    $t35 = Join-Path $OutDir 'T3T5-RESULT.txt'
    "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t35 -Encoding UTF8
    $stationUp = $false
    try { $stationUp = ($summary.station_up -eq $true) } catch {}
    "station_up=$stationUp station_boot_seconds=$($summary.station_boot_seconds)" | Add-Content -Path $t35 -Encoding UTF8
    $BASE = 'http://127.0.0.1:8000'
    $soakDir = 'C:\CivicCastSoak'
    $runRoot = 'C:\CivicCastSoakRun'
    New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
    if ($installDir) {
        $ffmpeg = Join-Path $installDir 'dependencies\ffmpeg\bin\ffmpeg.exe'
        $tsdukBin = Join-Path $installDir 'packs\native-server-binaries\payload\tsduck\bin'
        $env:CIVICCAST_FFMPEG = $ffmpeg
        $env:FFMPEG = $ffmpeg                                  # start-encoders.ps1 reads $env:FFMPEG only
        $env:CIVICCAST_TSDUCK_PATH = $tsdukBin
        $env:TSP = (Join-Path $tsdukBin 'tsp.exe')             # verify-egress.ps1 prefers $env:TSP
        $env:BASE_URL = $BASE
        $env:RUN_ROOT = $runRoot
        "ffmpeg_present=$([bool](Test-Path $ffmpeg)) tsp_present=$([bool](Test-Path (Join-Path $tsdukBin 'tsp.exe')))" | Add-Content -Path $t35 -Encoding UTF8
    }

    if ($stationUp) {
        # --- T3: surfaces respond + staff auth enforced (ported from synthetic-probes) ---
        function Test-Endpoint($label, $url, $expect) {
            $st = -1
            try { $st = [int](Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop).StatusCode }
            catch { try { $st = [int]$_.Exception.Response.StatusCode.value__ } catch { $st = -1 } }
            $ok = ($st -eq $expect)
            "T3 $label -> $st (expect $expect) $(if($ok){'ok'}else{'FAIL'})" | Add-Content -Path $t35 -Encoding UTF8
            return $ok
        }
        $t3 = $true
        $t3 = (Test-Endpoint 'health-200'            "$BASE/api/health"        200) -and $t3
        $t3 = (Test-Endpoint 'operator-console-200'  "$BASE/operator/"         200) -and $t3
        $t3 = (Test-Endpoint 'resident-portal-200'   "$BASE/"                  200) -and $t3
        $t3 = (Test-Endpoint 'staff-agendas-401'     "$BASE/api/staff/agendas" 401) -and $t3
        "T3_RESULT=$(if($t3){'PASS'}else{'FAIL'})" | Add-Content -Path $t35 -Encoding UTF8
        Save-Summary -Step 't3-surfaces'

        # --- T3 REAL LOOP: authenticated content loop, end to end -----------------
        # nonce (HKLM) -> POST first-admin -> bearer token -> generate a 30s test
        # MP4 with the bundled ffmpeg -> upload -> package -> approve/publish ->
        # assert on /api/public/assets -> poll for offline captions. Bounded and
        # fail-honest: every HTTP step logs method/url/status to T3-LOOP.txt, and
        # any >=400 response has its body captured (via Invoke-CivicCastApi).
        $t3loop = Join-Path $OutDir 'T3-LOOP.txt'
        "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t3loop -Encoding UTF8
        $t3LoopState = 'FAIL(unstarted)'
        $token = $null
        $loopAssetId = $null
        if (-not $installDir) {
            $t3LoopState = 'SKIPPED(no-install-dir)'
            "SKIPPED: no install dir located, cannot resolve ffmpeg for asset generation" | Add-Content -Path $t3loop -Encoding UTF8
        } else {
            try {
                if ($skipReinstall) {
                    # SKIP-REINSTALL MODE: this admin was already created by a
                    # PRIOR run against the same persistent host-backed install.
                    # The installer's setup nonce lives in HKLM, which is
                    # OS/registry state and does NOT persist across Sandbox
                    # sessions (only MappedFolders do) -- so first-admin cannot
                    # be, and does not need to be, re-run. Reuse the credentials
                    # that prior run wrote to T3-CREDENTIALS.txt and sign in via
                    # /api/setup/login instead (no nonce required for login).
                    $credFile = Join-Path $OutDir 'T3-CREDENTIALS.txt'
                    if (-not (Test-Path $credFile)) { $t3LoopState = 'PARTIAL(reuse-credentials-missing)'; throw "SKIP-REINSTALL mode but $credFile not found -- cannot reuse admin credentials" }
                    $creds = @{}
                    foreach ($line in (Get-Content -Path $credFile -ErrorAction Stop)) {
                        $eqIdx = $line.IndexOf('=')
                        if ($eqIdx -gt 0) { $creds[$line.Substring(0, $eqIdx)] = $line.Substring($eqIdx + 1) }
                    }
                    if (-not $creds.ContainsKey('admin_username') -or -not $creds.ContainsKey('admin_password')) {
                        $t3LoopState = 'PARTIAL(reuse-credentials-malformed)'; throw "$credFile is missing admin_username/admin_password"
                    }
                    "reused_credentials_from=$credFile admin_username=$($creds['admin_username'])" | Add-Content -Path $t3loop -Encoding UTF8
                    $loginBody = [ordered]@{ admin_username = $creds['admin_username']; admin_password = $creds['admin_password'] }
                    $rLogin = Invoke-CivicCastApi -Method 'Post' -Url "$BASE/api/setup/login" -LogFile $t3loop -BodyObj $loginBody
                    if ($rLogin.status -ne 200 -or -not $rLogin.body_json) { $t3LoopState = 'PARTIAL(login)'; throw "setup/login failed: status=$($rLogin.status)" }
                    $token = $rLogin.body_json.operator_console_token
                    if (-not $token) { $t3LoopState = 'PARTIAL(login-token)'; throw "no operator_console_token in setup/login response" }
                    "token_acquired=true (via reused-credential login) token_length=$($token.Length)" | Add-Content -Path $t3loop -Encoding UTF8
                } else {
                    # Step 1: read the installer's setup nonce from HKLM (admin-readable).
                    $nonceRegPath = 'HKLM:\SOFTWARE\CivicCast\Native'
                    $nonce = $null
                    try { $nonce = (Get-ItemProperty -Path $nonceRegPath -Name 'SetupNonce' -ErrorAction Stop).SetupNonce } catch {
                        "nonce read failed at $nonceRegPath\SetupNonce : $_" | Add-Content -Path $t3loop -Encoding UTF8
                    }
                    if (-not $nonce) { $t3LoopState = 'PARTIAL(nonce)'; throw "setup nonce not found at $nonceRegPath\SetupNonce" }
                    "nonce_present=true nonce_length=$($nonce.Length)" | Add-Content -Path $t3loop -Encoding UTF8

                    # Step 2: POST first-admin -> bearer token. Password is generated
                    # here (never hardcoded) and written to T3-CREDENTIALS.txt only --
                    # this is a disposable sandbox station, torn down with the VM.
                    $genPw = -join (((48..57) + (65..90) + (97..122)) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
                    $genPw = $genPw + 'Aa1!'
                    $credFile = Join-Path $OutDir 'T3-CREDENTIALS.txt'
                    "station_name=Sandbox Proof Station" | Set-Content -Path $credFile -Encoding UTF8
                    "admin_username=sandboxproof" | Add-Content -Path $credFile -Encoding UTF8
                    "admin_password=$genPw" | Add-Content -Path $credFile -Encoding UTF8

                    $firstAdminBody = [ordered]@{
                        station_name             = 'Sandbox Proof Station'
                        admin_display_name       = 'Sandbox Proof Admin'
                        admin_username           = 'sandboxproof'
                        admin_password           = $genPw
                        recovery_kit_destination = 'sandbox automated test run -- not physically stored'
                    }
                    $r1 = Invoke-CivicCastApi -Method 'Post' -Url "$BASE/api/setup/first-admin" -LogFile $t3loop -BodyObj $firstAdminBody -SetupNonce $nonce
                    if ($r1.status -ne 200 -or -not $r1.body_json) { $t3LoopState = 'PARTIAL(first-admin)'; throw "first-admin failed: status=$($r1.status)" }
                    $token = $r1.body_json.operator_console_token
                    if (-not $token) { $t3LoopState = 'PARTIAL(first-admin-token)'; throw "no operator_console_token in first-admin response" }
                    "token_acquired=true token_length=$($token.Length)" | Add-Content -Path $t3loop -Encoding UTF8
                }

                # Step 3: pick the T3 upload asset. Prefer the REAL LPM clip staged in
                # the mapped scripts folder (real speech -> whisper produces real caption
                # cues; the synthetic sine-tone clip gives whisper nothing to transcribe,
                # which makes a captions FAIL ambiguous). Fall back to generating the
                # synthetic clip only when no real clip is present, and say so in the log.
                $mp4Path = Join-Path $runRoot 't3-test-asset.mp4'
                $lpmClip = 'C:\CivicCastScripts\lpm-sample-short.mp4'
                if (Test-Path $lpmClip) {
                    Copy-Item -Path $lpmClip -Destination $mp4Path -Force
                    "t3_asset_source=real-lpm-clip ($lpmClip)" | Add-Content -Path $t3loop -Encoding UTF8
                } else {
                    if (-not (Test-Libopenh264 -FfmpegExe $ffmpeg)) { $t3LoopState = 'PARTIAL(ffmpeg-probe)'; throw "libopenh264 probe failed on $ffmpeg" }
                    "libopenh264_probe=ok" | Add-Content -Path $t3loop -Encoding UTF8
                    $genArgs = @(
                        '-y','-hide_banner','-loglevel','warning',
                        '-f','lavfi','-i','testsrc=size=1280x720:rate=30','-t','30',
                        '-f','lavfi','-i','sine=frequency=1000:sample_rate=48000','-t','30',
                        '-map','0:v:0','-map','1:a:0',
                        '-c:v','libopenh264','-b:v','1500k','-g','60',
                        '-c:a','aac','-b:a','96k',
                        '-movflags','+faststart',
                        $mp4Path
                    )
                    $genProc = Start-Process -FilePath $ffmpeg -ArgumentList $genArgs -PassThru -NoNewWindow -Wait -RedirectStandardError (Join-Path $OutDir 't3-generate-mp4.stderr.log')
                    "t3_asset_source=synthetic-sine-tone (captions may legitimately be empty) generate_mp4_exit=$($genProc.ExitCode)" | Add-Content -Path $t3loop -Encoding UTF8
                }
                $mp4Ok = (Test-Path $mp4Path) -and ((Get-Item $mp4Path -ErrorAction SilentlyContinue).Length -gt 0)
                "t3_asset path=$mp4Path exists=$mp4Ok bytes=$((Get-Item $mp4Path -ErrorAction SilentlyContinue).Length)" | Add-Content -Path $t3loop -Encoding UTF8
                if (-not $mp4Ok) { $t3LoopState = 'PARTIAL(generate-mp4)'; throw "T3 asset staging failed" }

                # Step 4: upload. Asset id/title are always freshly generated
                # (timestamp + random suffix) so a SKIP-REINSTALL run against an
                # install that already has a previously-published asset is still
                # self-contained -- it can never collide with (or be mistaken
                # for) a prior run's asset.
                $loopAssetSuffix = -join ((97..122) | Get-Random -Count 4 | ForEach-Object { [char]$_ })
                $loopAssetId = 'sandbox-proof-' + (Get-Date -Format 'yyMMddHHmmss') + '-' + $loopAssetSuffix
                $loopAssetTitle = 'Sandbox Proof Asset ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
                $up = Invoke-AssetUpload -BaseUrl $BASE -Token $token -AssetId $loopAssetId -Title $loopAssetTitle -FilePath $mp4Path -LogFile $t3loop
                if ($up.status -ne 201) { $t3LoopState = 'PARTIAL(upload)'; throw "upload failed: status=$($up.status)" }
                "uploaded_asset_id=$loopAssetId" | Add-Content -Path $t3loop -Encoding UTF8

                # Step 5: package.
                $pkg = Invoke-CivicCastApi -Method 'Post' -Url "$BASE/api/staff/assets/$loopAssetId/package" -LogFile $t3loop -BearerToken $token
                if ($pkg.status -ne 200) { $t3LoopState = 'PARTIAL(package)'; throw "package failed: status=$($pkg.status)" }

                # Step 6: approve/publish (portal surface).
                $approveBody = [ordered]@{ operator_id = 'sandboxproof'; operator_display_name = 'Sandbox Proof Admin' }
                $appr = Invoke-CivicCastApi -Method 'Post' -Url "$BASE/api/staff/publish/assets/$loopAssetId/approve" -LogFile $t3loop -BodyObj $approveBody -BearerToken $token
                if ($appr.status -ne 200) { $t3LoopState = 'PARTIAL(approve)'; throw "approve failed: status=$($appr.status)" }

                # Step 7: assert it appears on the PUBLIC surface (bounded poll, 60s).
                $pubDeadline = (Get-Date).AddSeconds(60)
                $foundPublic = $false
                while ((Get-Date) -lt $pubDeadline -and -not $foundPublic) {
                    $pub = Invoke-CivicCastApi -Method 'Get' -Url "$BASE/api/public/assets" -LogFile $t3loop
                    if ($pub.status -eq 200 -and $pub.body_json) {
                        $hit = $pub.body_json | Where-Object { $_.asset_id -eq $loopAssetId -or $_.id -eq $loopAssetId }
                        if ($hit) { $foundPublic = $true; break }
                    }
                    Start-Sleep -Seconds 5
                }
                "asset_found_public=$foundPublic asset_id=$loopAssetId" | Add-Content -Path $t3loop -Encoding UTF8
                if (-not $foundPublic) { $t3LoopState = 'PARTIAL(public-listing)'; throw "asset $loopAssetId not found on /api/public/assets within 60s" }
                Save-Summary -Step 't3-loop-published'

                # Step 8: poll for offline captions (bounded 20 min -- CPU whisper is
                # slow). Endpoint discovery is dynamic rather than hardcoded: this
                # kit's build can differ from what was last probed, so fetch
                # openapi.json in-sandbox and look for a captions/offline-jobs-shaped
                # staff route before falling back to the documented default path.
                # Do not hard-fail on schema drift -- capture raw responses either way.
                #
                # EVIDENCE FIX: earlier version only logged status:200 per poll, which
                # cannot distinguish "no job was ever enqueued" (audit finding K3-1:
                # publish-time enqueue swallows exceptions) from "job is still running
                # on CPU whisper". Now: (a) every poll's FULL body is captured to
                # T3-CAPTIONS.txt for the first poll, any poll whose body differs from
                # the last logged one, and the final poll; (b) if the job list is empty
                # for this asset right after publish, attempt a manual enqueue
                # (POST route discovered from the same openapi.json fetch) and log
                # that request+response, then resume polling as normal.
                $capEndpoint = $null
                $capEnqueueEndpoint = $null
                $capSpecPaths = $null
                try {
                    $spec = Invoke-CivicCastApi -Method 'Get' -Url "$BASE/openapi.json" -LogFile $t3loop
                    if ($spec.status -eq 200 -and $spec.body_json -and $spec.body_json.paths) {
                        $capSpecPaths = $spec.body_json.paths
                        $allPaths = $capSpecPaths.PSObject.Properties.Name
                        $capPaths = $allPaths | Where-Object { $_ -like '*caption*offline*job*' -or $_ -like '*offline*caption*job*' }
                        if (-not $capPaths) { $capPaths = $allPaths | Where-Object { $_ -like '*caption*job*' } }
                        if ($capPaths) { $capEndpoint = ($capPaths | Select-Object -First 1) }
                    }
                } catch { "caption endpoint discovery error: $_" | Add-Content -Path $t3loop -Encoding UTF8 }
                if (-not $capEndpoint) { $capEndpoint = '/api/staff/captions/offline-jobs' }
                "caption_endpoint=$capEndpoint" | Add-Content -Path $t3loop -Encoding UTF8

                # Manual-enqueue route discovery: prefer a POST method on the SAME
                # collection path we poll (the common REST shape); else any other
                # caption/job-shaped path that declares a POST.
                if ($capSpecPaths) {
                    $capEndpointNode = $capSpecPaths.PSObject.Properties | Where-Object { $_.Name -eq $capEndpoint } | Select-Object -First 1
                    if ($capEndpointNode -and ($capEndpointNode.Value.PSObject.Properties.Name -contains 'post')) {
                        $capEnqueueEndpoint = $capEndpoint
                    } else {
                        $postCapPaths = $capSpecPaths.PSObject.Properties | Where-Object {
                            ($_.Name -like '*caption*job*') -and ($_.Value.PSObject.Properties.Name -contains 'post')
                        }
                        if ($postCapPaths) { $capEnqueueEndpoint = ($postCapPaths | Select-Object -First 1).Name }
                    }
                }
                "caption_enqueue_endpoint=$capEnqueueEndpoint" | Add-Content -Path $t3loop -Encoding UTF8

                $capLog = Join-Path $OutDir 'T3-CAPTIONS.txt'
                "asset_id=$loopAssetId" | Set-Content -Path $capLog -Encoding UTF8
                "caption_endpoint=$capEndpoint" | Add-Content -Path $capLog -Encoding UTF8
                "caption_enqueue_endpoint=$capEnqueueEndpoint" | Add-Content -Path $capLog -Encoding UTF8

                $vttFound = $false
                $vttInfo = $null
                $capDeadline = (Get-Date).AddMinutes(20)
                $capBeat = 0
                $lastCapBodyRaw = $null
                $everSawJobForAsset = $false
                $capRouteMissing = $false
                $manualEnqueueAttempted = $false
                $manualEnqueueSucceeded = $false
                $manualEnqueueDetail = $null
                while ((Get-Date) -lt $capDeadline -and -not $vttFound) {
                    $capBeat++
                    $isFirstPoll = ($capBeat -eq 1)
                    $cj = Invoke-CivicCastApi -Method 'Get' -Url "$BASE$capEndpoint" -LogFile $t3loop -BearerToken $token
                    if ($cj.status -eq 404) {
                        "caption_endpoint_404 -- not present on this build; aborting caption poll" | Add-Content -Path $t3loop -Encoding UTF8
                        "---- poll #$capBeat (FINAL, 404) $((Get-Date).ToUniversalTime().ToString('o')) ----" | Add-Content -Path $capLog -Encoding UTF8
                        "$($cj.body_raw)" | Add-Content -Path $capLog -Encoding UTF8
                        $capRouteMissing = $true
                        break
                    }

                    $bodyChanged = ($cj.body_raw -ne $lastCapBodyRaw)
                    if ($isFirstPoll -or $bodyChanged) {
                        "---- poll #$capBeat $((Get-Date).ToUniversalTime().ToString('o')) status=$($cj.status) (first=$isFirstPoll changed=$bodyChanged) ----" | Add-Content -Path $capLog -Encoding UTF8
                        "$($cj.body_raw)" | Add-Content -Path $capLog -Encoding UTF8
                    }
                    $lastCapBodyRaw = $cj.body_raw

                    $jobsForAsset = @()
                    if ($cj.status -eq 200 -and $cj.body_json) {
                        $jobs = $cj.body_json
                        if ($jobs.PSObject -and ($jobs.PSObject.Properties.Name -contains 'jobs')) { $jobs = $jobs.jobs }
                        $jobsForAsset = @($jobs) | Where-Object {
                            ($_.asset_id -eq $loopAssetId) -or ($_.assetId -eq $loopAssetId) -or ($_.target_asset_id -eq $loopAssetId)
                        }
                    }
                    if ($jobsForAsset.Count -gt 0) { $everSawJobForAsset = $true }

                    foreach ($j in $jobsForAsset) {
                        $cueCount = $null
                        foreach ($f in @('cue_count','cueCount')) {
                            if ($j.PSObject.Properties.Name -contains $f) { $cueCount = $j.$f }
                        }
                        if ($cueCount -and [int]$cueCount -gt 0) { $vttFound = $true; $vttInfo = $j; break }
                    }

                    # K3-1 check + manual enqueue, attempted ONCE on the first poll only
                    # if nothing is queued for this asset yet. Publish's own enqueue is
                    # expected to be near-immediate, so an empty list this early either
                    # means K3-1 (swallowed exception, nothing was ever queued) or a
                    # genuinely broken/undiscoverable API -- attempting immediately
                    # (rather than waiting out the full 20-minute bound) keeps this
                    # bounded and leaves the rest of the window to observe completion.
                    if ($isFirstPoll -and -not $everSawJobForAsset -and -not $manualEnqueueAttempted) {
                        $manualEnqueueAttempted = $true
                        if (-not $capEnqueueEndpoint) {
                            $manualEnqueueDetail = 'no POST enqueue route discovered in openapi.json'
                            "manual_enqueue_attempted=true route=none detail=$manualEnqueueDetail" | Add-Content -Path $capLog -Encoding UTF8
                        } else {
                            $enqueueUrl = "$BASE$capEnqueueEndpoint"
                            $enqueueBody = [ordered]@{ asset_id = $loopAssetId }
                            "manual_enqueue_request: POST $enqueueUrl body=$(($enqueueBody | ConvertTo-Json -Compress))" | Add-Content -Path $capLog -Encoding UTF8
                            $enq = Invoke-CivicCastApi -Method 'Post' -Url $enqueueUrl -LogFile $t3loop -BodyObj $enqueueBody -BearerToken $token
                            "manual_enqueue_response: status=$($enq.status) body=$($enq.body_raw)" | Add-Content -Path $capLog -Encoding UTF8
                            if ($enq.status -ge 200 -and $enq.status -lt 300) {
                                $manualEnqueueSucceeded = $true
                                $manualEnqueueDetail = "enqueue POST succeeded (status=$($enq.status))"
                            } else {
                                $manualEnqueueDetail = "enqueue POST failed (status=$($enq.status))"
                            }
                        }
                    }

                    Save-Summary -Step "t3-loop-caption-poll-$capBeat"
                    if (-not $vttFound) { Start-Sleep -Seconds 30 }
                }
                if (-not $capRouteMissing) {
                    "---- poll #$capBeat (FINAL) $((Get-Date).ToUniversalTime().ToString('o')) ----" | Add-Content -Path $capLog -Encoding UTF8
                    "$lastCapBodyRaw" | Add-Content -Path $capLog -Encoding UTF8
                }

                if ($vttFound) {
                    ($vttInfo | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $OutDir 'T3-caption-artifact.json') -Encoding UTF8
                    "captions_result=PASS cue_count_found=true" | Add-Content -Path $t3loop -Encoding UTF8
                    "CAPTIONS=PASS" | Add-Content -Path $capLog -Encoding UTF8
                    "CAPTIONS=PASS" | Add-Content -Path $t3loop -Encoding UTF8
                    $t3LoopState = 'PASS'
                } elseif ($everSawJobForAsset) {
                    # A job for the asset was OBSERVED, so auto-enqueue demonstrably
                    # worked -- this must outrank any "no enqueue route" conclusion
                    # (the 2026-08-19 run mislabeled exactly this: completed job in
                    # the poll bodies, verdict said FAIL_NO_ENQUEUE_ROUTE because the
                    # manual-enqueue POST probe 404'd).
                    $completeZeroCues = ($lastCapBodyRaw -match '"state"\s*:\s*"complete"') -and
                                        ($lastCapBodyRaw -match '"cue_count"\s*:\s*0') -and
                                        ($lastCapBodyRaw -match '"last_error"\s*:\s*""')
                    if ($completeZeroCues) {
                        # Pipeline ran to completion with no error and produced zero
                        # cues -- the honest outcome for a no-speech (sine-tone) clip.
                        # Mechanism proven; content proof needs a real-speech upload.
                        "captions_result=COMPLETE_ZERO_CUES (job completed clean; zero cues -- expected for a no-speech source)" | Add-Content -Path $t3loop -Encoding UTF8
                        "CAPTIONS=COMPLETE_ZERO_CUES" | Add-Content -Path $capLog -Encoding UTF8
                        "CAPTIONS=COMPLETE_ZERO_CUES" | Add-Content -Path $t3loop -Encoding UTF8
                        $t3LoopState = 'PARTIAL(captions-zero-cues)'
                    } else {
                        # Job existed but none completed with cue_count>0 inside the
                        # bounded window -- most likely still running (CPU whisper is
                        # slow), but PASS requires evidence.
                        "captions_result=FAIL_ENQUEUED_NO_COMPLETE (polled $capBeat times over up to 20 min)" | Add-Content -Path $t3loop -Encoding UTF8
                        "CAPTIONS=FAIL_ENQUEUED_NO_COMPLETE" | Add-Content -Path $capLog -Encoding UTF8
                        "CAPTIONS=FAIL_ENQUEUED_NO_COMPLETE" | Add-Content -Path $t3loop -Encoding UTF8
                        $t3LoopState = 'PARTIAL(captions)'
                    }
                } elseif ($capRouteMissing -or (-not $capEndpoint)) {
                    "captions_result=FAIL_NO_ENQUEUE_ROUTE (caption endpoint not present on this build)" | Add-Content -Path $t3loop -Encoding UTF8
                    "CAPTIONS=FAIL_NO_ENQUEUE_ROUTE" | Add-Content -Path $capLog -Encoding UTF8
                    "CAPTIONS=FAIL_NO_ENQUEUE_ROUTE" | Add-Content -Path $t3loop -Encoding UTF8
                    $t3LoopState = 'PARTIAL(captions)'
                } elseif ($manualEnqueueAttempted -and $manualEnqueueSucceeded) {
                    # Publish's own auto-enqueue never produced a job for this asset
                    # (K3-1: publish enqueue swallows exceptions), but the SAME
                    # endpoint accepted a manually-triggered enqueue -- confirms the
                    # caption pipeline itself works and isolates the bug to the
                    # publish-time enqueue call specifically.
                    "captions_result=FAIL_NEVER_ENQUEUED (K3-1 confirmed: publish never enqueued a job for $loopAssetId; manual enqueue via $capEnqueueEndpoint succeeded -- $manualEnqueueDetail)" | Add-Content -Path $t3loop -Encoding UTF8
                    "CAPTIONS=FAIL_NEVER_ENQUEUED (K3-1 confirmed, manual enqueue worked)" | Add-Content -Path $capLog -Encoding UTF8
                    "CAPTIONS=FAIL_NEVER_ENQUEUED (K3-1 confirmed, manual enqueue worked)" | Add-Content -Path $t3loop -Encoding UTF8
                    $t3LoopState = 'PARTIAL(captions)'
                } else {
                    # Never saw a job for this asset, and either no enqueue route was
                    # discoverable or the manual enqueue attempt itself failed --
                    # cannot distinguish K3-1 from a broken/undiscoverable API here.
                    "captions_result=FAIL_NO_ENQUEUE_ROUTE (manual_enqueue_attempted=$manualEnqueueAttempted detail=$manualEnqueueDetail)" | Add-Content -Path $t3loop -Encoding UTF8
                    "CAPTIONS=FAIL_NO_ENQUEUE_ROUTE" | Add-Content -Path $capLog -Encoding UTF8
                    "CAPTIONS=FAIL_NO_ENQUEUE_ROUTE" | Add-Content -Path $t3loop -Encoding UTF8
                    $t3LoopState = 'PARTIAL(captions)'
                }
            } catch {
                "T3_LOOP_ERROR: $_" | Add-Content -Path $t3loop -Encoding UTF8
            }
        }
        "T3_LOOP=$t3LoopState" | Add-Content -Path $t3loop -Encoding UTF8
        Save-Summary -Step 't3-real-loop'

        # --- T4: PRODUCT-ENGINE EGRESS (QA-F2 fix) ---
        # QA-F2: the prior proof drove raw ffmpeg straight at a bare UDP port --
        # that proves ffmpeg works, not that CivicCast's own egress engine
        # (staff config -> daemon -> sink) works. Attempt to drive that real
        # engine through its staff API first (discover routes from the SERVED
        # openapi.json, PUT a udp-ts sink config, POST a start command, verify
        # with tsp using the same command pattern as the kit's verify-egress.ps1).
        # Only if that path is genuinely blocked does this fall back to the
        # synthetic-ffmpeg proof -- and that result is labeled
        # PASS_FFMPEG_FALLBACK, never plain PASS, so a fallback can never be
        # mistaken for proof the product's own engine works. No silent
        # substitution -- that is the whole point of this audit finding.
        $t4notes = Join-Path $OutDir 'T4-ENGINE-NOTES.txt'
        "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t4notes -Encoding UTF8
        $t4EnginePath = $false
        $t4EngineBlockReason = $null
        $engineToken = $token   # reuse the T3 REAL LOOP bearer token if we have one
        if (-not $engineToken) {
            $t4EngineBlockReason = 'no-bearer-token (T3 REAL LOOP did not reach a staff token)'
            "$t4EngineBlockReason -- egress config/commands routes require staff auth, so the product-engine path cannot be attempted without T3 having authenticated first" | Add-Content -Path $t4notes -Encoding UTF8
        } else {
            try {
                # (a) Discovery via the SERVED openapi.json, not a recursive
                # site-packages grep. This harness was hardened once already
                # (see file header) against unbounded recursive filesystem
                # scans over Sandbox's slow virtualized/differencing disk --
                # deliberately not reintroducing that class of scan here when
                # the served spec already gives an authoritative, cheap answer.
                $specR = Invoke-CivicCastApi -Method 'Get' -Url "$BASE/openapi.json" -LogFile $t4notes
                $egressPaths = @()
                if ($specR.status -eq 200 -and $specR.body_json -and $specR.body_json.paths) {
                    $egressPaths = @($specR.body_json.paths.PSObject.Properties.Name | Where-Object { $_ -like '*egress*' } | Sort-Object)
                }
                "discovered_egress_paths_count=$($egressPaths.Count)" | Add-Content -Path $t4notes -Encoding UTF8
                $egressPaths | ForEach-Object { "  $_" | Add-Content -Path $t4notes -Encoding UTF8 }

                $configPath = $egressPaths | Where-Object { $_ -like '*channels/{channel_id}/config' } | Select-Object -First 1
                $commandsPath = $egressPaths | Where-Object { $_ -like '*channels/{channel_id}/commands' } | Select-Object -First 1
                $statePath = $egressPaths | Where-Object { $_ -like '*channels/{channel_id}/state' } | Select-Object -First 1

                if (-not $configPath -or -not $commandsPath) {
                    $t4EngineBlockReason = 'no config+commands egress route discovered in openapi.json'
                    "$t4EngineBlockReason" | Add-Content -Path $t4notes -Encoding UTF8
                } else {
                    # Dedicated port (19003), distinct from the fallback's fixed
                    # 9001-9003, so the two paths can never collide even if a
                    # stop/teardown races a later fallback run.
                    $engineChannel = 'government'
                    $enginePort = 19003
                    # Bug fix (sandbox run evidence, T4-ENGINE-NOTES.txt): the bare
                    # "$enginePort?pkt_size=1316" form sent a mangled uri ("udp://
                    # 127.0.0.1:=1316" per the 422's echoed input) -- braced ${}
                    # interpolation removes any ambiguity at the "?". Also: unlike
                    # the raw-ffmpeg fallback below (which needs ?pkt_size for
                    # ffmpeg's own UDP muxer), the EgressConfig sink schema takes a
                    # plain udp://host:port uri with NO query string -- packetization/
                    # latency are separate typed fields (latency_ms, below), not URI
                    # params, so the query string is dropped entirely here rather
                    # than just re-escaped.
                    $engineUri = "udp://127.0.0.1:${enginePort}"
                    $configUrl = "$BASE" + ($configPath -replace '\{channel_id\}', $engineChannel)
                    $commandsUrl = "$BASE" + ($commandsPath -replace '\{channel_id\}', $engineChannel)
                    "config_url=$configUrl" | Add-Content -Path $t4notes -Encoding UTF8
                    "commands_url=$commandsUrl" | Add-Content -Path $t4notes -Encoding UTF8

                    $cfgBody = [ordered]@{
                        channel_id              = $engineChannel
                        enabled                 = $true
                        auto_start              = $false
                        allow_software_fallback = $true
                        fill_policy             = 'slate'
                        slate_message           = 'Sandbox proof run -- product-engine egress test, no live source configured.'
                        sinks                   = @(
                            [ordered]@{
                                kind                    = 'udp-ts'
                                label                   = 'sandbox-proof-engine'
                                uri                     = $engineUri
                                latency_ms              = 2000
                                loudness_regime         = 'inherit'
                                eas_tone_strip_enabled  = $true
                            }
                        )
                    }
                    $cfgR = Invoke-CivicCastApi -Method 'Put' -Url $configUrl -LogFile $t4notes -BodyObj $cfgBody -BearerToken $engineToken
                    if ($cfgR.status -ne 200) {
                        $t4EngineBlockReason = "config PUT failed: status=$($cfgR.status)"
                        "$t4EngineBlockReason" | Add-Content -Path $t4notes -Encoding UTF8
                    } else {
                        $startR = Invoke-CivicCastApi -Method 'Post' -Url $commandsUrl -LogFile $t4notes -BodyObj (@{ action = 'start' }) -BearerToken $engineToken
                        if ($startR.status -ne 202) {
                            $t4EngineBlockReason = "start command failed: status=$($startR.status)"
                            "$t4EngineBlockReason" | Add-Content -Path $t4notes -Encoding UTF8
                        } else {
                            # Bounded settle window -- give the daemon time to spin
                            # up and start emitting before the tsp capture window.
                            Start-Sleep -Seconds 20
                            if ($statePath) {
                                $stateUrl = "$BASE" + ($statePath -replace '\{channel_id\}', $engineChannel)
                                $stR = Invoke-CivicCastApi -Method 'Get' -Url $stateUrl -LogFile $t4notes -BearerToken $engineToken
                                if ($stR.body_json) { "engine_state=$($stR.body_json.state)" | Add-Content -Path $t4notes -Encoding UTF8 }
                            }
                            $tspExe = Join-Path $tsdukBin 'tsp.exe'
                            $tsProof = Test-TsProof -TspExe $tspExe -Port $enginePort -Seconds 8 -OutDir $OutDir -Label 'engine-government'
                            ($tsProof | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $OutDir 'egress-verify-engine.json') -Encoding UTF8
                            "engine_tsp_verdict=$($tsProof.verdict) invalid_syncs=$($tsProof.invalid_syncs) transport_errors=$($tsProof.transport_errors) discontinuities=$($tsProof.discontinuities)" | Add-Content -Path $t4notes -Encoding UTF8
                            # Bounded, best-effort stop of the daemon we started.
                            try { Invoke-CivicCastApi -Method 'Post' -Url $commandsUrl -LogFile $t4notes -BodyObj (@{ action = 'stop' }) -BearerToken $engineToken | Out-Null } catch {}
                            if ($tsProof.verdict -eq 'pass') {
                                $t4EnginePath = $true
                            } else {
                                $t4EngineBlockReason = "engine started but tsp verification did not pass (verdict=$($tsProof.verdict))"
                                "$t4EngineBlockReason" | Add-Content -Path $t4notes -Encoding UTF8
                            }
                        }
                    }
                }
            } catch {
                $t4EngineBlockReason = "exception during product-engine attempt: $_"
                "$t4EngineBlockReason" | Add-Content -Path $t4notes -Encoding UTF8
            }
        }
        "t4_engine_path_succeeded=$t4EnginePath" | Add-Content -Path $t4notes -Encoding UTF8
        Save-Summary -Step 't4-engine-attempt'

        if ($t4EnginePath) {
            "T4_RESULT=PASS_PRODUCT_ENGINE" | Add-Content -Path $t35 -Encoding UTF8
            Save-Summary -Step 't4-egress-product-engine'
        } else {
            "T4_engine_path_blocked_reason=$t4EngineBlockReason (see T4-ENGINE-NOTES.txt)" | Add-Content -Path $t35 -Encoding UTF8
            # --- T4 fallback: synthetic encoders + TSDuck verify ---
            # The shipped ffmpeg is the LGPL/version3 pack build: it carries libopenh264 +
            # h264_nvenc but NOT GPL libx264/libx265 (by design). The native stream code
            # (_ffmpeg.py resolve_h264_encoder: nvenc->mf->libopenh264->libx264) resolves to
            # libopenh264 on a CPU box, so the egress proof must use that encoder. The kit's
            # start-encoders.ps1 hardcodes libx264 (assumes a tester-supplied GPL ffmpeg), so
            # we spawn the encoders inline here with the shipped encoder and leave the kit's
            # verify-egress.ps1 (the actual TSDuck assertion) untouched.
            try {
                $t4chs = @(@{c='public';p=9001}, @{c='education';p=9002}, @{c='government';p=9003})
                $t4procs = @()
                $t4logs = Join-Path $runRoot 'logs'
                New-Item -ItemType Directory -Force -Path $t4logs | Out-Null
                foreach ($e in $t4chs) {
                    $a = @(
                        '-y','-hide_banner','-loglevel','warning',
                        '-f','lavfi','-re','-i','color=size=1280x720:rate=30:color=#1A1A1A,format=yuv420p',
                        '-f','lavfi','-re','-i','sine=frequency=1000:sample_rate=48000',
                        '-map','0:v:0','-map','1:a:0',
                        '-c:v','libopenh264','-b:v','1500k','-g','60',
                        '-c:a','aac','-b:a','96k',
                        '-f','mpegts','-fflags','+genpts','-flush_packets','1',
                        "udp://127.0.0.1:$($e.p)?pkt_size=1316"
                    )
                    $t4procs += (Start-Process -FilePath $ffmpeg -ArgumentList $a -PassThru -NoNewWindow -RedirectStandardError (Join-Path $t4logs "ffmpeg-$($e.c).log"))
                }
                ("T4 encoders started: " + (($t4procs | ForEach-Object { $_.Id }) -join ',')) | Add-Content -Path (Join-Path $OutDir 'start-encoders.log')
                Start-Sleep -Seconds 20
                & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $soakDir 'scripts\verify-egress.ps1') -HeartbeatIndex 1 -Seconds 8 *> (Join-Path $OutDir 'verify-egress.log')
                foreach ($p in $t4procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
                $ev = Get-ChildItem (Join-Path $runRoot 'egress-verify') -Filter '*.json' -ErrorAction SilentlyContinue | Select-Object -Last 1
                if ($ev) {
                    Copy-Item $ev.FullName (Join-Path $OutDir 'egress-verify.json') -Force
                    $body = Get-Content $ev.FullName -Raw
                    $pass = ($body -match '"invalid_syncs"\s*:\s*0') -and ($body -match '"transport_errors"\s*:\s*0') -and ($body -match '"discontinuities"\s*:\s*0')
                    "T4_RESULT=$(if($pass){'PASS_FFMPEG_FALLBACK'}else{'CHECK egress-verify.json'})" | Add-Content -Path $t35 -Encoding UTF8
                } else {
                    "T4_RESULT=NO_ARTIFACT (see start-encoders.log / verify-egress.log)" | Add-Content -Path $t35 -Encoding UTF8
                }
            } catch { "T4_ERROR=$_" | Add-Content -Path $t35 -Encoding UTF8 }
            Save-Summary -Step 't4-egress-ffmpeg-fallback'
        }

        # --- T5: bounded soak (default 20 min; SOAK_MINUTES.txt overrides for full 4h) ---
        $soakMin = 20
        try { if (Test-Path (Join-Path $OutDir 'SOAK_MINUTES.txt')) { $soakMin = [int]((Get-Content (Join-Path $OutDir 'SOAK_MINUTES.txt') | Select-Object -First 1).Trim()) } } catch {}
        "T5_soak_minutes=$soakMin" | Add-Content -Path $t35 -Encoding UTF8
        $soakEnd = (Get-Date).AddMinutes($soakMin)
        $beat = 0; $soakFail = 0
        while ((Get-Date) -lt $soakEnd) {
            $beat++
            $hs = -1
            try { $hs = [int](Invoke-WebRequest -Uri "$BASE/api/health" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop).StatusCode } catch { $hs = -1 }
            if ($hs -ne 200) { $soakFail++ }
            "T5 beat=$beat health=$hs $((Get-Date).ToString('o'))" | Add-Content -Path $t35 -Encoding UTF8
            Save-Summary -Step "t5-beat-$beat"
            Start-Sleep -Seconds 300
        }
        "T5_RESULT=$(if($soakFail -eq 0){'PASS'}else{'FAIL'}) beats=$beat unhealthy=$soakFail" | Add-Content -Path $t35 -Encoding UTF8
        Save-Summary -Step 't5-soak-complete'
    } else {
        # HARDENED <gate-a-station-up-wait-and-log-capture>: EXPLICITLY skip
        # T3/T4/T5 -- write each of their own result files with a real
        # SKIPPED verdict line (never leave them absent/ambiguous, and never
        # attempt T4's product-engine call, ffmpeg-fallback encoder run, or
        # T5's 20-minute soak against a station that never came up; that is
        # what left the 8579e66-run3 script hung with no forward progress
        # for 30+ minutes after t2-render-assert). scripts/gate_a_verdict.py
        # already fails closed on a SKIPPED value for every one of these
        # (only an explicit PASS / PASS_PRODUCT_ENGINE line passes), so this
        # is purely about leaving an honest, bounded, non-hanging trail --
        # not a verdict-judge contract change.
        "T3T5_SKIPPED=station health check did not pass" | Add-Content -Path $t35 -Encoding UTF8
        "T3_RESULT=SKIPPED(station-down)" | Add-Content -Path $t35 -Encoding UTF8
        "T4_RESULT=SKIPPED(station-down)" | Add-Content -Path $t35 -Encoding UTF8
        "T5_soak_minutes=0 (skipped)" | Add-Content -Path $t35 -Encoding UTF8
        "T5_RESULT=SKIPPED beats=0 unhealthy=0" | Add-Content -Path $t35 -Encoding UTF8

        $t3loopSkip = Join-Path $OutDir 'T3-LOOP.txt'
        "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t3loopSkip -Encoding UTF8
        "SKIPPED: station health check did not pass within the 20-minute station-up-wait deadline -- see STATION-UP-WAIT.txt and station-diag\after-station-up-wait\ for why" | Add-Content -Path $t3loopSkip -Encoding UTF8
        "T3_LOOP=SKIPPED(station-down)" | Add-Content -Path $t3loopSkip -Encoding UTF8
        "CAPTIONS=SKIPPED(station-down)" | Add-Content -Path $t3loopSkip -Encoding UTF8

        $t4notesSkip = Join-Path $OutDir 'T4-ENGINE-NOTES.txt'
        "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))" | Set-Content -Path $t4notesSkip -Encoding UTF8
        "SKIPPED: station health check did not pass -- the product-engine attempt requires a staff bearer token from T3, which never ran" | Add-Content -Path $t4notesSkip -Encoding UTF8
        "t4_engine_path_succeeded=false" | Add-Content -Path $t4notesSkip -Encoding UTF8

        Save-Summary -Step 't3t5-skipped-station-down'
    }

    # Station diagnostics -- SECOND capture point, still inside the try
    # block right after the T3/T4/T5 decision (pass-through path OR the
    # skip path above), before the installer-log/event-log tail steps.
    # This is IN ADDITION TO the unconditional final capture in the
    # `finally` block below (the task's "before ... AND again at the end"),
    # so a soak-loop hang or an exception in steps 6/7 still leaves a
    # post-T3/T4/T5 diagnostic snapshot on disk even if the true final
    # capture never runs.
    try {
        Invoke-StationDiagCapture -OutDir $OutDir -InstallDir $installDir -Label 'after-t3t5' -RunStart $RunStart
    } catch {
        "station diag capture (after-t3t5) failed: $_" | Add-Content -Path (Join-Path $OutDir 'summary-write-errors.log') -Encoding UTF8
    }
    Save-Summary -Step 'station-diag-captured-after-t3t5'

    # 6. Installer logs: install-progress.log (the nsh's own breadcrumb log,
    #    always at $COMMONPROGRAMDATA\CivicCast\install-progress.log) plus any
    #    NSIS log if one exists.
    #    HARDENED <gate-a-station-up-wait-and-log-capture> follow-up
    #    (8579e66-run4 evidence): this was the EXACT spot run #4 stalled --
    #    'station-diag-captured-after-t3t5' was the last step Save-Summary
    #    ever recorded, and 'install-progress-log-copied' never arrived.
    #    Root cause is not fully proven (the staleness watchdog above is the
    #    real guarantee against a repeat), but this is a cheap, safe
    #    tightening regardless: the -Tail read now runs against the copy
    #    that was JUST WRITTEN to $OutDir (a host-mapped, real-disk
    #    MappedFolder) instead of re-reading $progressLog a second time from
    #    %ProgramData%, which lives on the Sandbox's own virtualized/
    #    differencing C: -- one read of the slower source instead of two.
    $progressLog = Join-Path $env:ProgramData 'CivicCast\install-progress.log'
    $progressLogCopy = Join-Path $OutDir 'install-progress.log'
    if (Test-Path $progressLog) {
        $summary.install_progress_log_found = $true
        Copy-Item -Path $progressLog -Destination $progressLogCopy -Force
        $summary.install_progress_log_tail = Get-Content -Path $progressLogCopy -Tail 80 -ErrorAction SilentlyContinue
    }
    Save-Summary -Step 'install-progress-log-copied'

    # 7. Windows Event Log errors/criticals during the run window (Application
    #    + System). Best-effort; a from-scratch Sandbox may have very little
    #    in these logs. Bounded via -MaxEvents (stops the query itself early,
    #    unlike Select-Object -First which only trims AFTER full retrieval).
    #    NOT wrapped in Start-Job: a 2026-08-16 run under memory pressure hit
    #    System.OutOfMemoryException loading PSWorkflow/PSScheduledJob module
    #    type data the moment Start-Job was invoked -- job infrastructure has
    #    real memory cost this VM does not reliably have to spare on top of
    #    the already-running PostgreSQL/NATS/pythonservice.exe stack. A direct
    #    call costs nothing extra and -MaxEvents keeps it from running long.
    try {
        $events = Get-WinEvent -FilterHashtable @{
            LogName   = 'Application', 'System'
            Level     = 1, 2, 3
            StartTime = $RunStart
        } -MaxEvents 25 -ErrorAction SilentlyContinue
        $summary.event_log_errors = @($events | ForEach-Object {
            [ordered]@{
                TimeCreated  = $_.TimeCreated.ToString('o')
                LogName      = $_.LogName
                LevelDisplay = $_.LevelDisplayName
                ProviderName = $_.ProviderName
                Id           = $_.Id
                Message      = ($_.Message -split "`n" | Select-Object -First 3) -join ' | '
            }
        })
    } catch {
        $summary.errors += "event log query failed: $_"
    }
    Save-Summary -Step 'event-log-checked'

} catch {
    $summary.errors += "top-level failure: $_"
} finally {
    # Station diagnostics -- THIRD and final capture point, unconditional,
    # regardless of pass/fail/exception. This is the one capture guaranteed
    # to run even if something above this `finally` threw before reaching
    # either of the two earlier capture points.
    try {
        Invoke-StationDiagCapture -OutDir $OutDir -InstallDir $installDir -Label 'final' -RunStart $RunStart
    } catch {
        try { "station diag capture (final) failed: $_" | Add-Content -Path (Join-Path $OutDir 'summary-write-errors.log') -Encoding UTF8 } catch {}
    }

    $summary.run_end_utc = (Get-Date).ToUniversalTime().ToString('o')
    $summary.harness_completed = $true
    Save-Summary -Step 'finally-block'

    try { Stop-Transcript | Out-Null } catch {}

    # (d) DONE.json -- the unambiguous, authoritative completion signal. This
    # is the LAST thing the script does, after every other write. The old
    # DONE.marker text file is kept too (harmless, backward compatible) but
    # Host-Launch-Sandbox-Test.ps1 now polls for DONE.json specifically.
    #
    # `harness_completed=true` / `watchdog_timeout=false` are the
    # authoritative completion signal gate_a_verdict.py's check_completion
    # actually gates on now -- NOT a specific `last_completed_step` string.
    # (The prior contract required last_completed_step=='t5-soak-complete',
    # but steps 6/7 below T5 -- install-progress-log-copied,
    # event-log-checked -- and this very finally block ALWAYS run after
    # T5 and legitimately advance last_completed_step past it, so that
    # contract could never actually pass on a real completed run. Fixed as
    # part of this change; see scripts/gate_a_verdict.py and its tests.)
    # If the separate watchdog process (spawned at script entry) already
    # wrote WATCHDOG-TIMEOUT.txt / a placeholder DONE.json before reaching
    # here, this is the REAL completion and safely overwrites both.
    Write-Marker -Name 'DONE.marker' -Content (Get-Date).ToString('o')
    $doneObj = [ordered]@{
        done_utc              = (Get-Date).ToUniversalTime().ToString('o')
        last_completed_step   = $summary.last_completed_step
        installer_exit_code   = $summary.installer_exit_code
        harness_completed     = $true
        watchdog_timeout       = $false
        station_up             = $summary.station_up
        station_first_healthy_utc = $summary.station_first_healthy_utc
        station_boot_seconds   = $summary.station_boot_seconds
    }
    ($doneObj | ConvertTo-Json -Depth 3) | Set-Content -Path (Join-Path $OutDir 'DONE.json') -Encoding UTF8
    # The main script reached its real end -- remove the watchdog's own
    # WATCHDOG-TIMEOUT.txt if the watchdog raced a slow-but-successful
    # finish (extremely unlikely given the 100-minute default vs this
    # script's own bounded steps, but the file's mere presence is what
    # gate_a_verdict.py's completion check fails closed on, so a stale one
    # from a genuinely-completed run must not linger).
    try {
        $wd = Join-Path $OutDir 'WATCHDOG-TIMEOUT.txt'
        if (Test-Path $wd) { Remove-Item -Path $wd -Force -ErrorAction SilentlyContinue }
    } catch {}
}
