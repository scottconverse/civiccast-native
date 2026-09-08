# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $IdentityPath,
    [string] $OperatorTokenPath = 'C:\CivicCastSoak\state\token',
    [switch] $DryRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
Add-Type -AssemblyName System.Net.Http

function Invoke-Beta5Api {
    param([string] $Method, [string] $Url, $BodyObj = $null, [string] $BearerToken, [int] $TimeoutSec = 120)
    $result = [ordered]@{ status = $null; body_json = $null; body_raw = $null; error = $null }
    try {
        $parameters = @{ Uri = $Url; Method = $Method; Headers = @{ Authorization = "Bearer $BearerToken" }; UseBasicParsing = $true; TimeoutSec = $TimeoutSec; ErrorAction = 'Stop' }
        if ($null -ne $BodyObj) { $parameters.Body = $BodyObj | ConvertTo-Json -Depth 10; $parameters.ContentType = 'application/json' }
        $response = Invoke-WebRequest @parameters
        $result.status = [int] $response.StatusCode; $result.body_raw = [string] $response.Content
    } catch {
        $result.error = $_.Exception.Message
        if ($_.Exception.Response) {
            try { $result.status = [int] $_.Exception.Response.StatusCode; $reader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); $result.body_raw = $reader.ReadToEnd() } catch { }
        }
    }
    if ($result.body_raw) { try { $result.body_json = $result.body_raw | ConvertFrom-Json } catch { } }
    return [pscustomobject] $result
}

function Invoke-Beta5Upload {
    param([string] $BaseUrl, [string] $Token, [string] $AssetId, [string] $Title, [string] $FilePath)
    $client = New-Object Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromMinutes(15)
    $client.DefaultRequestHeaders.Authorization = New-Object Net.Http.Headers.AuthenticationHeaderValue('Bearer', $Token)
    $form = New-Object Net.Http.MultipartFormDataContent
    try {
        $form.Add((New-Object Net.Http.StringContent($AssetId)), 'asset_id')
        $form.Add((New-Object Net.Http.StringContent($Title)), 'title')
        $bytes = New-Object Net.Http.ByteArrayContent(,[IO.File]::ReadAllBytes($FilePath))
        $form.Add($bytes, 'file', [IO.Path]::GetFileName($FilePath))
        $response = $client.PostAsync("$BaseUrl/api/staff/assets/upload", $form).Result
        return [pscustomobject]@{ status = [int] $response.StatusCode; body_raw = $response.Content.ReadAsStringAsync().Result }
    } finally { $form.Dispose(); $client.Dispose() }
}

function Get-Beta5MediaDuration {
    param([string] $FfprobeExe, [string] $FilePath)
    $output = @(& $FfprobeExe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $FilePath 2>$null)
    if ($LASTEXITCODE -ne 0 -or $output.Count -eq 0) { throw "ffprobe failed for $FilePath" }
    $value = [double] 0
    $ok = [double]::TryParse("$($output[0])", [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref] $value)
    if (-not $ok -or $value -le 0) { throw "ffprobe returned an invalid duration for $FilePath" }
    return [int] [Math]::Ceiling($value)
}

function Set-Beta5ApprovedAssetsReceipt {
    param(
        [Parameter(Mandatory)] $Identity,
        [Parameter(Mandatory)][string] $IdentityPath,
        [Parameter(Mandatory)][array] $Assets
    )
    if ($Assets.Count -ne 2) { throw 'The approved-assets receipt requires exactly two assets in program order.' }
    $seen = @{}
    $receipt = @()
    foreach ($asset in $Assets) {
        $assetId = "$($asset.id)"
        $title = "$($asset.title)"
        $duration = [int] $asset.duration_seconds
        if (-not $assetId.Trim() -or -not $title.Trim() -or $duration -le 0) { throw 'Approved asset receipt fields must be nonblank with a positive duration.' }
        if ($seen.ContainsKey($assetId)) { throw "Approved asset ID is duplicated: $assetId" }
        $seen[$assetId] = $true
        $receipt += [ordered]@{ asset_id = $assetId; duration_seconds = $duration; title = $title }
    }
    Set-Beta5IdentityField $Identity 'approved_assets' $receipt
    Write-Beta5JsonAtomic -Object $Identity -Path $IdentityPath
    return @($receipt)
}

function Stop-Beta5Channels {
    param([Parameter(Mandatory)] $Identity, [Parameter(Mandatory)][string] $Token, [Parameter(Mandatory)][scriptblock] $ApiInvoker, [scriptblock] $SleepInvoker = { param($Seconds) Start-Sleep -Seconds $Seconds })
    $base = 'http://127.0.0.1:8000'
    foreach ($channel in @($Identity.channels)) {
        $response = & $ApiInvoker -Method Post -Url "$base/api/staff/egress/channels/$($channel.channel_id)/commands" -BodyObj @{ action = 'stop' } -BearerToken $Token
        if ($response.status -ne 202 -and $response.status -ne 404) { throw "Could not quiesce $($channel.channel_id): status=$($response.status)" }
    }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        $allStopped = $true
        foreach ($channel in @($Identity.channels)) {
            $response = & $ApiInvoker -Method Get -Url "$base/api/staff/egress/channels/$($channel.channel_id)/state" -BearerToken $Token
            if ($response.status -ne 404 -and ($response.status -ne 200 -or $response.body_json.state -ne 'STOPPED')) { $allStopped = $false }
        }
        if ($allStopped) { return }
        & $SleepInvoker 5
    } while ((Get-Date) -lt $deadline)
    throw 'All tester channels did not quiesce before scheduling.'
}

function Invoke-Beta5ScheduleAndStart {
    param([Parameter(Mandatory)] $Identity, [Parameter(Mandatory)][array] $Assets, [Parameter(Mandatory)][string] $Token, [Parameter(Mandatory)][scriptblock] $ApiInvoker, [datetime] $Now = (Get-Date).ToUniversalTime())
    if ($Assets.Count -lt 1) { throw 'No approved assets are available.' }
    $base = 'http://127.0.0.1:8000'; $start = $Now.AddSeconds(-30); $end = $Now.AddSeconds([int] $Identity.planned_seconds + 900)
    $counts = [ordered]@{}
    # All channels are fully scheduled and committed before the first config or start call.
    foreach ($channel in @($Identity.channels)) {
        $cursor = $start; $index = 0; $count = 0
        while ($cursor -lt $end) {
            if ($count -ge 3000) { throw "Schedule cap reached for $($channel.channel_id)." }
            $asset = $Assets[$index % $Assets.Count]
            $item = & $ApiInvoker -Method Post -Url "$base/api/staff/schedule" -BodyObj @{ asset_id = $asset.id; channel_id = $channel.channel_id; mode = 'premiere'; scheduled_at = $cursor.ToString('o'); duration_seconds = [int] $asset.duration_seconds; notes = $Identity.mission } -BearerToken $Token
            if ($item.status -ne 201 -or -not $item.body_json.id) { throw "Schedule failed for $($channel.channel_id): status=$($item.status)" }
            $occurrence = "$($Identity.mission)-$($channel.channel_id)-$count-$([guid]::NewGuid().ToString('N'))"
            $commit = & $ApiInvoker -Method Post -Url "$base/api/staff/playout/commit" -BodyObj @{ channel_id = $channel.channel_id; occurrence_id = $occurrence; schedule_item_id = "$($item.body_json.id)" } -BearerToken $Token
            if ($commit.status -ne 201) { throw "Commit failed for $($channel.channel_id): status=$($commit.status)" }
            $cursor = $cursor.AddSeconds([int] $asset.duration_seconds); $index++; $count++
        }
        $counts[$channel.channel_id] = $count
    }
    foreach ($channel in @($Identity.channels)) {
        $config = @{ channel_id = $channel.channel_id; enabled = $true; auto_start = $true; allow_software_fallback = $true; fill_policy = 'slate'; slate_message = "$($Identity.mission) tester"; sinks = @(@{ kind = 'udp-ts'; label = "$($Identity.mission)-$($channel.channel_id)"; uri = "udp://127.0.0.1:$($channel.udp_port)"; latency_ms = 2000; loudness_regime = 'inherit'; eas_tone_strip_enabled = $true }) }
        $response = & $ApiInvoker -Method Put -Url "$base/api/staff/egress/channels/$($channel.channel_id)/config" -BodyObj $config -BearerToken $Token
        if ($response.status -ne 200) { throw "Config failed for $($channel.channel_id): status=$($response.status)" }
    }
    foreach ($channel in @($Identity.channels)) {
        $response = & $ApiInvoker -Method Post -Url "$base/api/staff/egress/channels/$($channel.channel_id)/commands" -BodyObj @{ action = 'start' } -BearerToken $Token
        if ($response.status -ne 202) { throw "Start failed for $($channel.channel_id): status=$($response.status)" }
    }
    return [pscustomobject]@{ schedule_start_utc = $start.ToString('o'); schedule_end_utc = $end.ToString('o'); counts = $counts }
}

if ($env:BETA5_TESTER_LIBRARY -eq '1') { return }
$id = Get-Beta5Identity $IdentityPath
foreach ($fact in 'actual_manifest_sha256', 'actual_installer_sha256', 'installer_authenticode_status', 'installer_signer', 'installed_version', 'installed_service_path', 'installed_service_process_started_utc', 'native_app_payload_source_sha', 'expected_runtime_file_sha256', 'actual_runtime_file_sha256') {
    if ($id.PSObject.Properties.Name -notcontains $fact -or -not $id.$fact) { throw "Verified installed identity is missing '$fact'." }
}
if ($id.actual_manifest_sha256 -ne $id.expected_manifest_sha256 -or $id.actual_installer_sha256 -ne $id.expected_installer_sha256 -or $id.installer_authenticode_status -ne 'Valid' -or $id.installer_signer -ne 'Scott Converse' -or $id.installed_version -ne $id.expected_version) { throw 'Installed identity facts do not match the approved candidate.' }
if ($id.native_app_payload_source_sha -ne $id.candidate_source_sha) { throw 'Installed native app payload source SHA is not the candidate SHA.' }
foreach ($relative in 'Lib/site-packages/civiccast/egress/daemon.py', 'Lib/site-packages/civiccast/egress/gst/strategy.py') {
    $expectedProperty = $id.expected_runtime_file_sha256.PSObject.Properties[$relative]
    $recordedProperty = $id.actual_runtime_file_sha256.PSObject.Properties[$relative]
    if (-not $expectedProperty -or -not $recordedProperty -or $expectedProperty.Value -ne $recordedProperty.Value) { throw "Installed runtime receipt mismatch: $relative" }
    $installedPath = Join-Path 'C:\CivicCastHostStore\install\runtime' ($relative -replace '/', '\')
    if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf) -or (Get-FileHash -LiteralPath $installedPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedProperty.Value) { throw "Current installed runtime no longer matches candidate app payload: $relative" }
}
$null = Assert-Beta5InstalledIdentity -Identity $id
if (-not (Test-Path -LiteralPath $OperatorTokenPath -PathType Leaf)) { throw 'Existing tester operator token is absent.' }
$token = (Get-Content -LiteralPath $OperatorTokenPath -Raw).Trim()
if (-not $token) { throw 'Existing tester operator token is empty.' }
if ($DryRun) { Write-Host '[DRYRUN] validated identity, installed version/schema/service, and presence of an existing nonempty token; no token value or HTTP write emitted.'; return }

$returnRepo = $id.return_repo_path
if (-not (Test-Path -LiteralPath (Join-Path $returnRepo '.git'))) {
    & git clone --quiet --single-branch --branch $id.return_branch $id.return_repository_url $returnRepo
    if ($LASTEXITCODE -ne 0) { throw 'Could not clone the required tester return branch.' }
}
$null = Sync-Beta5ReturnRepository $id
& git -C $returnRepo config user.name "soak-tester-$($id.hostname)"
& git -C $returnRepo config user.email 'soak-tester@civiccast.invalid'

$finalPath = Join-Path $returnRepo "soak\beta5\$($id.mission)\final-verdict.json"
$statePath = Join-Path $id.mission_state_root 'soak-state.json'
if ((Test-Path -LiteralPath $finalPath) -or (Test-Path -LiteralPath $statePath)) { throw 'This mission already has a start marker or terminal verdict; refusing to reuse its state.' }
$api = ${function:Invoke-Beta5Api}
Stop-Beta5Channels -Identity $id -Token $token -ApiInvoker $api
$kit = Join-Path $id.tester_root ("kit-" + $id.candidate_source_sha)
$manifestEntries = @(Read-Beta5Manifest -ManifestPath (Join-Path $kit 'SHA256SUMS.txt') -KitRoot $kit)
$clips = @($manifestEntries | Where-Object { $_.relative_path -match '^samples\\[^\\]+\.mp4$' } | Select-Object -First 2)
if ($clips.Count -ne 2) { throw 'The verified kit manifest must contain at least two MP4 samples.' }
foreach ($clip in $clips) { if ((Get-FileHash -LiteralPath $clip.local_path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $clip.sha256) { throw "Sample hash changed: $($clip.relative_path)" } }
$ffprobe = @('C:\CivicCastHostStore\install\packs\native-server-binaries\payload\ffmpeg\bin\ffprobe.exe', 'C:\CivicCastHostStore\install\ffmpeg\bin\ffprobe.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $ffprobe) { throw 'Installed ffprobe.exe is required for gap-free schedule durations.' }

$upload = ${function:Invoke-Beta5Upload}; $assets = @()
foreach ($clip in $clips) {
    $assetId = "$($id.mission)-$([guid]::NewGuid().ToString('N'))"
    $assetTitle = "$($id.mission) $([IO.Path]::GetFileNameWithoutExtension($clip.local_path))"
    $result = & $upload -BaseUrl 'http://127.0.0.1:8000' -Token $token -AssetId $assetId -Title $assetTitle -FilePath $clip.local_path
    if ($result.status -ne 201) { throw "Upload failed for $($clip.relative_path): status=$($result.status)" }
    $result = & $api -Method Post -Url "http://127.0.0.1:8000/api/staff/assets/$assetId/package" -BearerToken $token -TimeoutSec 900
    if ($result.status -ne 200) { throw "Package failed for $assetId`: status=$($result.status)" }
    $deadline = (Get-Date).AddMinutes(15); $ready = $false
    do { $result = & $api -Method Get -Url "http://127.0.0.1:8000/api/staff/assets/$assetId" -BearerToken $token; if ($result.status -eq 200 -and $result.body_json.state -in 'validated', 'recorded') { $ready = $true; break }; Start-Sleep -Seconds 10 } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw "Asset did not become ready: $assetId" }
    $result = & $api -Method Post -Url "http://127.0.0.1:8000/api/staff/publish/assets/$assetId/approve" -BodyObj @{ operator_id = 'soakadmin'; operator_display_name = 'Soak Operator' } -BearerToken $token -TimeoutSec 900
    if ($result.status -ne 200) { throw "Approval failed for $assetId`: status=$($result.status)" }
    $assets += [pscustomobject]@{ id = $assetId; duration_seconds = Get-Beta5MediaDuration -FfprobeExe $ffprobe -FilePath $clip.local_path; title = $assetTitle }
}
$null = Set-Beta5ApprovedAssetsReceipt -Identity $id -IdentityPath $IdentityPath -Assets $assets
$schedule = Invoke-Beta5ScheduleAndStart -Identity $id -Assets $assets -Token $token -ApiInvoker $api

$deadline = (Get-Date).AddMinutes(6); $accepted = @{}
do {
    foreach ($channel in @($id.channels)) {
        $state = & $api -Method Get -Url "http://127.0.0.1:8000/api/staff/egress/channels/$($channel.channel_id)/state" -BearerToken $token
        if ($state.status -eq 200 -and $state.body_json.state -eq 'ON_AIR' -and $state.body_json.pid) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($state.body_json.pid)" -ErrorAction SilentlyContinue
            if ($process -and $process.Name -eq 'python.exe' -and $process.CommandLine -match 'egress[\\/]gst[\\/]worker\.py') { $accepted[$channel.channel_id] = [int] $state.body_json.pid }
        }
    }
    if ($accepted.Count -eq 3) { break }
    Start-Sleep -Seconds 10
} while ((Get-Date) -lt $deadline)
if ($accepted.Count -ne 3) { throw 'All three channels did not prove ON_AIR on the GStreamer worker; no soak clock was written.' }
$started = (Get-Date).ToUniversalTime()
foreach ($name in $accepted.Keys) {
    Set-Content -LiteralPath (Join-Path $id.mission_state_root "pid-$name") -Value $accepted[$name] -Encoding ascii
    $workerLog = "C:\ProgramData\CivicCast\data\egress\$name\logs\gst-worker.stdout.log"
    if (-not (Test-Path -LiteralPath $workerLog -PathType Leaf)) { throw "GStreamer worker log is absent for $name; no soak clock was written." }
    Set-Content -LiteralPath (Join-Path $id.mission_state_root "worker-log-offset-$name") -Value (Get-Item -LiteralPath $workerLog).Length -Encoding ascii
}
Write-Beta5JsonAtomic -Object ([ordered]@{ schema = 'civiccast-native-beta5-soak-state-v1'; mission = $id.mission; candidate_source_sha = $id.candidate_source_sha; started_utc = $started.ToString('o'); planned_seconds = $id.planned_seconds; schedule_start_utc = $schedule.schedule_start_utc; schedule_end_utc = $schedule.schedule_end_utc }) -Path $statePath
Set-Beta5IdentityField $id 'soak_start_utc' $started.ToString('o'); Write-Beta5JsonAtomic -Object $id -Path $IdentityPath
Write-Host "START PASS: all schedules committed before starts; three GStreamer channels ON_AIR at $($started.ToString('o'))."
