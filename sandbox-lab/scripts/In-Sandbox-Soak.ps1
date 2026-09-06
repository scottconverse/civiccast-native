# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# In-Sandbox-Soak.ps1 -- runs INSIDE Windows Sandbox via the .wsb
# LogonCommand rendered from CivicCastSandboxSoak.wsb.template. Drives a
# silent install of the mapped kit, starts the station, sets it up
# (first-admin), loads the kit's sample videos into the three egress
# channels, commits them to air, then polls every 60s for -Minutes minutes,
# writing a rollup every 3 minutes plus station logs, and a final
# VERDICT.json/VERDICT.txt when done.
#
# PS 5.1 COMPATIBLE ONLY -- Windows Sandbox's built-in Windows PowerShell is
# 5.1, not PowerShell 7. No ternary (?:), no null-coalescing (??), no
# `[array]::Empty[...]`, no `-Parallel`. Reused code paths (silent install
# flag, health endpoint, first-admin body shape, multipart asset upload,
# schedule+commit, channel config/start, tsp egress probe) come from:
#   - sandbox-lab/Run-GateA.ps1 (host) + sandbox-lab/scripts/In-Sandbox-Report.ps1
#     (guest): silent install is `/S /D=C:\...\install` (NSIS convention),
#     health lives at both /health and /api/health (civiccast/app.py:2140-2141,
#     same handler).
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-8.ps1: the
#     POST /api/setup/first-admin body shape (FirstAdminSetupRequest).
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-9m.ps1: the
#     PROVEN-WORKING (beta.5-shaped, HTTP 422 avoided) multipart asset
#     upload, channel config PUT body, schedule POST + Commit-to-Air POST
#     ordering (schedule/commit ALL channels while still stopped, THEN
#     config+start -- avoids a reload storm on an already-ON_AIR channel),
#     and the ON_AIR poll.
#   - C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-3.ps1: the
#     tsp.exe egress-proof invocation (Test-TsProof) and per-channel
#     relaunch (worker-restart) tracking (Update-RelaunchTracking).
#
# This lane is deliberately simpler than Gate A's In-Sandbox-Report.ps1: it
# installs one ~300MB setup.exe (not a 20+GB kit) and writes small JSON
# files, not tens of GB -- the VSMB-wedge conditions documented in that
# script's <gate-a-mapped-folder-stalls> header (multi-GB transfers pinning
# the shared transport for minutes) do not apply at this scale, so this
# script writes directly to the mapped output folder rather than running
# Gate A's separate local-dir + shipper-process architecture. If this lane
# is ever pointed at a much larger kit or a much longer -Minutes, revisit
# that assumption first.
param(
    [int]$Minutes = 15
)

$ErrorActionPreference = 'Continue'

$KitDir      = 'C:\CivicCastKit'
$OutDir      = 'C:\CivicCastSoakOutput'
$InstallDir  = 'C:\CivicCastSoakInstall'
$Base        = 'http://127.0.0.1:8000'
$RunStart    = Get-Date
$RunStartUtc = $RunStart.ToUniversalTime()

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'cycles') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'rollups') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir 'logs') | Out-Null

Start-Transcript -Path (Join-Path $OutDir 'sandbox-soak-transcript.log') -Force | Out-Null

function Write-SoakLog {
    param([string]$Message)
    $line = "$((Get-Date).ToUniversalTime().ToString('o')) $Message"
    Add-Content -Path (Join-Path $OutDir 'soak-log.txt') -Value $line -Encoding UTF8
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

# --------------------------------------------------------------------------
# Overall watchdog: a genuinely separate powershell.exe process (NOT
# Start-Job -- In-Sandbox-Report.ps1 documents a real
# System.OutOfMemoryException hit loading PSWorkflow/PSScheduledJob module
# type data under this VM's memory pressure the moment Start-Job was
# invoked, so this mirrors that same avoidance). If this script hangs
# somewhere and never reaches VERDICT.json, the watchdog writes a
# WATCHDOG-TIMEOUT.txt and a fail-closed VERDICT.json/.txt so the host's own
# poll loop (Run-SandboxSoak.ps1) is never the only backstop.
# --------------------------------------------------------------------------
try {
    $watchdogScript = @'
param([string]$OutDir, [int]$Minutes)
$deadline = (Get-Date).AddMinutes($Minutes + 10)
$donePath = Join-Path $OutDir 'VERDICT.json'
while ((Get-Date) -lt $deadline) {
    if (Test-Path $donePath) { exit 0 }
    Start-Sleep -Seconds 20
}
if (-not (Test-Path $donePath)) {
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    "watchdog_fired_utc=$ts reason=VERDICT.json not present after Minutes+10 -- main script presumed hung" |
        Set-Content -Path (Join-Path $OutDir 'WATCHDOG-TIMEOUT.txt') -Encoding UTF8
    $verdict = [ordered]@{
        schema_version = 1; verdict = 'FAIL'; reason = 'in-sandbox watchdog fired -- main script did not complete'
        first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        watchdog_timeout = $true; done_utc = $ts
    }
    ($verdict | ConvertTo-Json -Depth 6) | Set-Content -Path $donePath -Encoding UTF8
    "verdict=FAIL (watchdog timeout) reason=see WATCHDOG-TIMEOUT.txt" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
}
'@
    $watchdogPath = Join-Path $env:TEMP 'civiccast-soak-watchdog.ps1'
    Set-Content -Path $watchdogPath -Value $watchdogScript -Encoding UTF8
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$watchdogPath`"",
        '-OutDir', "`"$OutDir`"", '-Minutes', $Minutes
    ) -WindowStyle Hidden | Out-Null
    Write-SoakLog "watchdog spawned (fires at Minutes+10 = $($Minutes + 10)m if VERDICT.json never appears)"
} catch {
    Write-SoakLog "watchdog spawn failed (non-fatal): $_"
}

function Copy-StationLogs {
    <#
      Copies the station's daemon/worker/install logs + installer-state.json
      into $OutDir\logs. Called at the end AND every 3 minutes during the
      soak loop, so a hung sandbox still leaves partial evidence on the host
      (mirrors Gate A's own "copy every checkpoint, not just at the end"
      lesson from <gate-a-mapped-folder-stalls>).
    #>
    param([string]$Label)
    $dst = Join-Path $OutDir "logs\$Label"
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
# 1. Locate and run the installer silently.
# --------------------------------------------------------------------------
$summary = [ordered]@{
    run_start_utc = $RunStartUtc.ToString('o')
    installer_found = $null
    installer_exit_code = $null
    station_healthy = $false
    first_admin_ok = $null
    samples_found = 0
    assets_uploaded = 0
    channels_started = @()
    error = $null
}

$installerExe = Get-ChildItem -Path $KitDir -Filter '*setup.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installerExe) {
    $summary.error = "no *setup.exe found under $KitDir"
    Write-SoakLog $summary.error
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}
$summary.installer_found = $installerExe.FullName
Write-SoakLog "installer: $($installerExe.FullName)"

Write-SoakLog "running silent install: /S /D=$InstallDir"
try {
    $proc = Start-Process -FilePath $installerExe.FullName -ArgumentList "/S /D=$InstallDir" -PassThru -Wait -WindowStyle Hidden
    $summary.installer_exit_code = $proc.ExitCode
} catch {
    $summary.error = "installer launch failed: $_"
    Write-SoakLog $summary.error
}
Write-SoakLog "installer exit code: $($summary.installer_exit_code)"
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

if ($summary.installer_exit_code -ne 0) {
    $summary.error = "installer did not exit 0 (exit=$($summary.installer_exit_code))"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

# --------------------------------------------------------------------------
# 2. Start the station the same way the installed product starts on a real
#    box: the installer's own service (CivicCastSupervisor) is set to
#    auto-start; nudge it in case it hasn't come up yet, then poll /health.
# --------------------------------------------------------------------------
try {
    Start-Service -Name 'CivicCastSupervisor' -ErrorAction Stop
    Write-SoakLog "Start-Service CivicCastSupervisor: requested"
} catch {
    Write-SoakLog "Start-Service CivicCastSupervisor: $_ (service may already be running or auto-started)"
}

Write-SoakLog "polling for station health (up to 20 minutes)..."
$healthy = $false
$healthDeadline = (Get-Date).AddMinutes(20)
while ((Get-Date) -lt $healthDeadline) {
    try {
        $h = Invoke-RestMethod -Uri "$Base/health" -TimeoutSec 10 -ErrorAction Stop
        if ($h.status -eq 'healthy') { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 6
}
$summary.station_healthy = $healthy
Write-SoakLog "station healthy: $healthy"
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

if (-not $healthy) {
    $summary.error = "station never reported healthy at $Base/health within 20 minutes"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

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
Add-Type -AssemblyName System.Net.Http
function Invoke-AssetUpload {
    param([string]$BaseUrl, [string]$Token, [string]$AssetId, [string]$Title, [string]$FilePath, [int]$TimeoutSec = 900)
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
        try { $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('video/mp4') } catch { }
        $content.Add($fileContent, 'file', [System.IO.Path]::GetFileName($FilePath))
        $resp = $client.PostAsync($url, $content).Result
        $result.status = [int]$resp.StatusCode
        $result.body_raw = $resp.Content.ReadAsStringAsync().Result
        $result.ok = $resp.IsSuccessStatusCode
        try { $client.Dispose() } catch { }
    } catch {
        $result.error = "$_"
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
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

if (-not $token) {
    $summary.error = "first-admin setup did not return an operator_console_token -- cannot configure or start channels"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

# --------------------------------------------------------------------------
# 4. Load the kit's sample videos into the three egress channels, the way
#    AUTORUN-9m does it: upload assets, schedule + Commit-to-Air EVERY
#    channel while still stopped, THEN config+start (avoids a reload storm
#    on an already-ON_AIR channel -- see AUTORUN-9m.ps1 header, item B-B).
# --------------------------------------------------------------------------
function Get-Mp4DurationSeconds {
    param([string]$FfprobeExe, [string]$FilePath, [int]$DefaultSeconds = 30)
    if (-not $FfprobeExe -or -not (Test-Path $FfprobeExe) -or -not (Test-Path $FilePath)) { return $DefaultSeconds }
    try {
        $out = & $FfprobeExe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $FilePath 2>$null
        $first = ($out | Select-Object -First 1)
        $val = [double]0
        if ([double]::TryParse($first, [ref]$val) -and $val -gt 0) { return [int][Math]::Ceiling($val) }
    } catch { }
    return $DefaultSeconds
}

$samples = @(Get-ChildItem (Join-Path $KitDir 'samples') -Filter '*.mp4' -File -ErrorAction SilentlyContinue | Sort-Object Name)
$summary.samples_found = $samples.Count
Write-SoakLog "samples found: $($samples.Count)"
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

if ($samples.Count -lt 1) {
    $summary.error = "no sample videos found under $KitDir\samples"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

$ffprobeCandidates = @(
    (Join-Path $KitDir 'packs\native-server-binaries\payload\ffmpeg\bin\ffprobe.exe'),
    (Join-Path $InstallDir 'packs\native-server-binaries\payload\ffmpeg\bin\ffprobe.exe'),
    (Join-Path $InstallDir 'ffmpeg\bin\ffprobe.exe'),
    'C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe',
    'C:\Program Files\CivicCast (Native)\ffmpeg\bin\ffprobe.exe'
)
$ffprobeExe = $ffprobeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

$channelSpecs = @(
    @{ id = 'public';     port = 9001 }
    @{ id = 'education';  port = 9002 }
    @{ id = 'government'; port = 9003 }
)

# Upload up to 4 clips as assets.
$stagedAssets = @()
$stampNow = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
foreach ($s in ($samples | Select-Object -First 4)) {
    $assetId = "sandboxsoak-$stampNow-$([System.IO.Path]::GetFileNameWithoutExtension($s.Name).Substring(0, [Math]::Min(20, $s.BaseName.Length)))" -replace '[^a-zA-Z0-9\-]', '-'
    $up = Invoke-AssetUpload -BaseUrl $Base -Token $token -AssetId $assetId -Title $s.Name -FilePath $s.FullName
    if ($up.ok) {
        $summary.assets_uploaded++
        $dur = Get-Mp4DurationSeconds -FfprobeExe $ffprobeExe -FilePath $s.FullName -DefaultSeconds 30
        $stagedAssets += [ordered]@{ id = $assetId; duration_seconds = $dur }
        Write-SoakLog "asset uploaded: $assetId ($($s.Name), duration=${dur}s)"
    } else {
        Write-SoakLog "asset upload FAILED for $($s.Name): status=$($up.status) body=$($up.body_raw)"
    }
}
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

if ($stagedAssets.Count -eq 0) {
    $summary.error = "no assets uploaded successfully -- cannot schedule or start channels"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

# Schedule + Commit-to-Air, covering (Minutes + 10) minutes per channel,
# back-to-back, BEFORE any channel is configured/started.
$soakCoverageMin = $Minutes + 10
$schedulingStart = (Get-Date)
$scheduleEnd = $schedulingStart.AddMinutes($soakCoverageMin)
foreach ($c in $channelSpecs) {
    $cursor = $schedulingStart.AddSeconds(-60)
    $assetIdx = 0
    $scheduled = 0
    $committed = 0
    while (($cursor -lt $scheduleEnd) -and ($scheduled -lt 500)) {
        $asset = $stagedAssets[$assetIdx % $stagedAssets.Count]
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
            break
        }
        $cursor = $cursor.AddSeconds([int]$asset.duration_seconds)
        $assetIdx++
    }
    Write-SoakLog "channel=$($c.id) schedule_items=$scheduled committed=$committed"
}

# NOW configure + start each channel.
foreach ($c in $channelSpecs) {
    $cfg = [ordered]@{
        channel_id = $c.id; enabled = $true; auto_start = $true; allow_software_fallback = $true
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
Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')

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
    $summary.error = "no channel reached ON_AIR within 6 minutes of the start command -- soak clock not started"
    Save-Json -Obj $summary -Path (Join-Path $OutDir 'summary.json')
    Copy-StationLogs -Label 'final'
    $verdict = [ordered]@{ schema_version = 1; verdict = 'FAIL'; reason = $summary.error; first_failing_cycle = $null; cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0 }
    Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
    "verdict=FAIL reason=$($summary.error)" | Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8
    Stop-Transcript | Out-Null
    exit 1
}

$SoakStartUtc = (Get-Date).ToUniversalTime()
Write-SoakLog "soak clock started (UTC): $($SoakStartUtc.ToString('o')) -- at least one channel confirmed ON_AIR"

# --------------------------------------------------------------------------
# 5. Poll loop: every 60s for -Minutes minutes, one cycle record per poll.
#    tsp egress probe + relaunch tracking ported from AUTORUN-3.ps1.
# --------------------------------------------------------------------------
$tspCandidates = @(
    (Join-Path $KitDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'packs\native-server-binaries\payload\tsduck\bin\tsp.exe'),
    (Join-Path $InstallDir 'tsduck\bin\tsp.exe'),
    'C:\Program Files\CivicCast (Native)\tsduck\bin\tsp.exe'
)
$tsp = $tspCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tsp) {
    $found = Get-ChildItem -Path $InstallDir -Filter 'tsp.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $tsp = $found.FullName }
}
Write-SoakLog "tsp.exe: $(if ($tsp) { $tsp } else { 'NOT FOUND -- egress probes will report not-run' })"

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
$deadline = $RunStart.AddMinutes($Minutes)
Write-SoakLog "entering poll loop: -Minutes $Minutes (deadline $($deadline.ToUniversalTime().ToString('o')))"

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
            if ($st.PSObject.Properties.Name -contains 'engine') { $row.engine = $st.engine }
            if (-not $row.engine -and $st.pid) {
                $wp = Get-Process -Id ([int]$st.pid) -ErrorAction SilentlyContinue
                if ($wp) {
                    if ($wp.ProcessName -match '^python') { $row.engine = 'gstreamer' }
                    elseif ($wp.ProcessName -match '^ffmpeg') { $row.engine = 'ffmpeg' }
                    else { $row.engine = "unknown:$($wp.ProcessName)" }
                }
            }
        } catch {
            $row.last_error = "state read failed: $($_.Exception.Message)"
        }
        $newPid = $(if ($row.pid) { [int]$row.pid } else { $null })
        $row.relaunched_this_cycle = Update-RelaunchState -ChannelId $c.id -NewPid $newPid

        $ts = Test-TsProof -TspExe $tsp -Port $c.port -Seconds 20 -OutDir (Join-Path $OutDir 'cycles') -Label "$($c.id)-c$cycleN"
        $row.tsduck_verdict = $ts.verdict
        $rows += $row
    }

    $cycle = [ordered]@{ cycle_utc = $cycleUtc.ToString('o'); channels = $rows }
    $allCycles += $cycle
    Save-Json -Obj $cycle -Path (Join-Path $OutDir "cycles\cycle-$('{0:d4}' -f $cycleN).json")
    Write-SoakLog "cycle $cycleN @ $($cycleUtc.ToString('o')): $(($rows | ForEach-Object { "$($_.channel_id)=$($_.engine_state)/$($_.engine)/tsp=$($_.tsduck_verdict)/relaunch=$($_.relaunched_this_cycle)" }) -join ' ')"

    # Rollup + log copy every 3 minutes (every 3rd cycle at a 60s cadence).
    if (($cycleN - $lastRollupCycle) -ge 3) {
        $lastRollupCycle = $cycleN
        $rollup = [ordered]@{
            rollup_utc = (Get-Date).ToUniversalTime().ToString('o')
            cycles_so_far = $cycleN
            soak_start_utc = $SoakStartUtc.ToString('o')
            elapsed_minutes = [math]::Round(((Get-Date) - $RunStart).TotalMinutes, 2)
            latest_cycle = $cycle
        }
        Save-Json -Obj $rollup -Path (Join-Path $OutDir "rollups\rollup-$('{0:d4}' -f $cycleN).json")
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
    station_healthy      = $summary.station_healthy
    samples_found        = $summary.samples_found
    assets_uploaded      = $summary.assets_uploaded
}
Save-Json -Obj $verdict -Path (Join-Path $OutDir 'VERDICT.json')
"verdict=$($verdictResult.verdict) reason=$($verdictResult.reason) cycles_total=$($verdictResult.cycles_total) cycles_evaluated=$($verdictResult.cycles_evaluated)" |
    Set-Content -Path (Join-Path $OutDir 'VERDICT.txt') -Encoding UTF8

Copy-StationLogs -Label 'final'
Write-SoakLog "VERDICT: $($verdictResult.verdict) -- $($verdictResult.reason)"

Stop-Transcript | Out-Null
