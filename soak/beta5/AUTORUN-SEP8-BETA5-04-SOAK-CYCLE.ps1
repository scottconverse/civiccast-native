# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $IdentityPath,
    [string] $OperatorTokenPath = 'C:\CivicCastSoak\state\token',
    [string] $ScheduledTaskName,
    [switch] $DryRun
)
Import-Module (Join-Path $PSScriptRoot 'ProbeContracts.psm1') -Force

function Test-Beta5ZeroInteger {
    param($Value)
    if ($null -eq $Value) { return $false }
    $parsed = [int64] 0
    return [int64]::TryParse("$Value", [ref] $parsed) -and $parsed -eq 0
}

function Test-TsProof {
    param([string] $TspExe, [int] $Port, [string] $OutDir, [string] $Label)
    $result = [ordered]@{ verdict = 'not-run'; packets_total = $null; invalid_syncs = $null; transport_errors = $null; discontinuities = $null }
    if (-not $TspExe -or -not (Test-Path -LiteralPath $TspExe -PathType Leaf)) { return [pscustomobject] $result }
    $report = Join-Path $OutDir "tsduck-$Label.json"
    $stdout = Join-Path $OutDir "tsduck-$Label.stdout.log"
    $stderr = Join-Path $OutDir "tsduck-$Label.stderr.log"
    try {
        $process = Start-Process -FilePath $TspExe -ArgumentList @('-I', 'ip', "$Port", '-P', 'until', '--seconds', '20', '-P', 'analyze', '--json', '--output-file', $report, '-O', 'drop') -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $null = $process.Handle
        if (-not $process.WaitForExit(40000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $result.verdict = 'fail-timed-out'; return [pscustomobject] $result
        }
        $process.Refresh()
        return Read-TsVerdict -Path $report -ExitCode $process.ExitCode
    } catch { $result.verdict = "error:$($_.Exception.Message)" }
    return [pscustomobject] $result
}

function Get-Beta5Verdict {
    param(
        [array] $Cycles,
        [datetime] $StartUtc,
        [datetime] $Now,
        [int] $DurationSeconds = 7200,
        [int] $MaxGapSeconds = 180,
        [string] $ExpectedSha,
        [string] $ExpectedMission,
        [string[]] $ExpectedChannels = @('public', 'education', 'government')
    )
    $StartUtc = $StartUtc.ToUniversalTime()
    $Now = $Now.ToUniversalTime()
    foreach ($rawCycle in @($Cycles)) {
        if ($null -eq $rawCycle -or $rawCycle.PSObject.Properties.Name -notcontains 'utc') { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'missing cycle time' } }
        try { $null = [datetime] $rawCycle.utc } catch { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'invalid cycle time' } }
    }
    $all = @($Cycles | Sort-Object { [datetime] $_.utc })
    if ($all.Count -eq 0) {
        if (($Now - $StartUtc).TotalSeconds -lt $DurationSeconds) { return [pscustomobject]@{ verdict = 'PENDING'; reason = 'no cycles yet' } }
        return [pscustomobject]@{ verdict = 'FAIL'; reason = 'no cycles' }
    }
    $previous = $StartUtc
    foreach ($cycle in $all) {
        foreach ($name in 'candidate_source_sha', 'mission', 'channels') {
            if ($cycle.PSObject.Properties.Name -notcontains $name) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "missing cycle field $name" } }
        }
        if ($cycle.candidate_source_sha -ne $ExpectedSha -or $cycle.mission -ne $ExpectedMission) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'identity mismatch' } }
        try { $at = ([datetime] $cycle.utc).ToUniversalTime() } catch { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'invalid cycle time' } }
        if ($at -lt $StartUtc -or ($at - $previous).TotalSeconds -gt $MaxGapSeconds) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'missing interval' } }
        $previous = $at
        foreach ($name in 'pid_change_count', 'reload_aborted_count', 'reload_stuck_count') {
            if ($cycle.PSObject.Properties.Name -notcontains $name -or -not (Test-Beta5ZeroInteger $cycle.$name)) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "nonzero or missing $name" } }
        }
        $channels = @($cycle.channels)
        $ids = @($channels | ForEach-Object { "$($_.channel_id)" })
        if ($channels.Count -ne $ExpectedChannels.Count -or @($ids | Sort-Object -Unique).Count -ne $ExpectedChannels.Count) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'wrong channel count' } }
        foreach ($expected in $ExpectedChannels) { if ($ids -notcontains $expected) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "missing channel $expected" } } }
        foreach ($channel in $channels) {
            foreach ($name in 'channel_id', 'state', 'engine', 'pid', 'tsduck') {
                if ($channel.PSObject.Properties.Name -notcontains $name) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "missing channel field $name" } }
            }
            $parsedPid = [int64] 0; $packets = [int64] 0
            if ($channel.state -ne 'ON_AIR' -or $channel.engine -ne 'gstreamer' -or $null -eq $channel.pid -or -not [int64]::TryParse("$($channel.pid)", [ref] $parsedPid) -or $parsedPid -le 0) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'engine/state/pid failure' } }
            if (-not $channel.tsduck) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'missing TSDuck proof' } }
            foreach ($name in 'verdict', 'packets_total', 'invalid_syncs', 'transport_errors', 'discontinuities') {
                if ($channel.tsduck.PSObject.Properties.Name -notcontains $name) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "missing TSDuck field $name" } }
            }
            if ($channel.tsduck.verdict -ne 'pass' -or $null -eq $channel.tsduck.packets_total -or -not [int64]::TryParse("$($channel.tsduck.packets_total)", [ref] $packets) -or $packets -le 0) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'media packet failure' } }
            foreach ($counter in 'invalid_syncs', 'transport_errors', 'discontinuities') { if ($channel.tsduck.PSObject.Properties.Name -notcontains $counter -or -not (Test-Beta5ZeroInteger $channel.tsduck.$counter)) { return [pscustomobject]@{ verdict = 'FAIL'; reason = "media counter failure: $counter" } } }
        }
    }
    if (($Now - $StartUtc).TotalSeconds -lt $DurationSeconds) { return [pscustomobject]@{ verdict = 'PENDING'; reason = 'elapsed below required duration' } }
    if (($Now - $previous).TotalSeconds -gt $MaxGapSeconds) { return [pscustomobject]@{ verdict = 'FAIL'; reason = 'missing final interval' } }
    return [pscustomobject]@{ verdict = 'PASS'; reason = $null }
}

if ($env:BETA5_SOAK_LIBRARY -eq '1') { return }
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
$id = Get-Beta5Identity $IdentityPath
$statePath = Join-Path $id.mission_state_root 'soak-state.json'
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw 'Soak state is absent.' }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ($state.mission -ne $id.mission -or $state.candidate_source_sha -ne $id.candidate_source_sha) { throw 'Soak-state identity mismatch.' }
if (-not (Test-Path -LiteralPath $OperatorTokenPath -PathType Leaf)) { throw 'Tester token file is absent.' }
$token = (Get-Content -LiteralPath $OperatorTokenPath -Raw).Trim()
if (-not $token) { throw 'Tester token is empty.' }
if ($DryRun) { Write-Host '[DRYRUN] identity/state/token-presence validated; actual API, process, TSDuck, file, Git, and task actions skipped.'; return }

$now = (Get-Date).ToUniversalTime()
$evidence = Join-Path $id.mission_state_root ("evidence\" + $now.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$kit = Join-Path $id.tester_root ("kit-" + $id.candidate_source_sha)
$tsp = @("$kit\packs\native-server-binaries\payload\tsduck\bin\tsp.exe", 'C:\CivicCastHostStore\install\packs\native-server-binaries\payload\tsduck\bin\tsp.exe', 'C:\CivicCastHostStore\install\tsduck\bin\tsp.exe') | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $tsp) { throw 'tsp.exe is absent; actual-media sampling cannot run.' }
$headers = @{ Authorization = "Bearer $token" }
$rows = @(); $pidChanges = 0; $aborts = 0; $stalls = 0
foreach ($channel in @($id.channels)) {
    $channelId = "$($channel.channel_id)"
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/staff/egress/channels/$channelId/state" -Headers $headers -TimeoutSec 20
    $process = $(if ($response.pid) { Get-CimInstance Win32_Process -Filter "ProcessId=$($response.pid)" -ErrorAction SilentlyContinue } else { $null })
    $engine = $(if ($process -and $process.Name -eq 'python.exe' -and $process.CommandLine -match 'egress[\\/]gst[\\/]worker\.py') { 'gstreamer' } else { 'unknown' })
    $pidFile = Join-Path $id.mission_state_root "pid-$channelId"
    if (-not (Test-Path -LiteralPath $pidFile -PathType Leaf)) { $pidChanges++ }
    elseif ((Get-Content -LiteralPath $pidFile -Raw).Trim() -ne "$($response.pid)") { $pidChanges++ }
    if ($response.pid) { Set-Content -LiteralPath $pidFile -Value $response.pid -Encoding ascii }
    $logPath = "C:\ProgramData\CivicCast\data\egress\$channelId\logs\gst-worker.stdout.log"
    $offsetFile = Join-Path $id.mission_state_root "worker-log-offset-$channelId"
    if (-not (Test-Path -LiteralPath $logPath -PathType Leaf) -or -not (Test-Path -LiteralPath $offsetFile -PathType Leaf)) { $aborts++; $stalls++ }
    else {
        $offset = [int64] (Get-Content -LiteralPath $offsetFile -Raw).Trim(); $length = (Get-Item -LiteralPath $logPath).Length
        if ($length -lt $offset) { $stalls++ } else {
            $stream = [IO.File]::Open($logPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            try { $null = $stream.Seek($offset, [IO.SeekOrigin]::Begin); $reader = New-Object IO.StreamReader($stream); $newLog = $reader.ReadToEnd(); $reader.Dispose() } finally { $stream.Dispose() }
            $aborts += @($newLog -split "`r?`n" | Where-Object { $_ -match '^CTRL reload aborted:' }).Count
            $stalls += @($newLog -split "`r?`n" | Where-Object { $_ -match '^CTRL stall:|^WORKER_RESULT.*["'']stall["'']' }).Count
            Set-Content -LiteralPath $offsetFile -Value $length -Encoding ascii
        }
    }
    $rows += [ordered]@{ channel_id = $channelId; state = $response.state; pid = $response.pid; engine = $engine; command_line = $(if ($process) { $process.CommandLine } else { $null }); tsduck = Test-TsProof -TspExe $tsp -Port ([int] $channel.udp_port) -OutDir $evidence -Label $channelId }
}
$cycle = [ordered]@{ schema = 'civiccast-native-beta5-media-cycle-v3'; mission = $id.mission; candidate_source_sha = $id.candidate_source_sha; utc = $now.ToString('o'); channels = $rows; pid_change_count = $pidChanges; reload_aborted_count = $aborts; reload_stuck_count = $stalls }
$repo = $id.return_repo_path
$telemetry = Join-Path $repo "soak\beta5\$($id.mission)\telemetry"
$cyclePath = Join-Path $telemetry "cycle-$($now.ToString('yyyyMMddTHHmmssZ')).json"
Write-Beta5JsonAtomic -Object $cycle -Path $cyclePath
Publish-Beta5Report -Identity $id -ReportPath $cyclePath -Message "test: beta5 media telemetry $($id.mission)"
$cycles = @(Get-ChildItem -LiteralPath $telemetry -Filter 'cycle-*.json' -File | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json })
$verdict = Get-Beta5Verdict -Cycles $cycles -StartUtc ([datetime] $state.started_utc) -Now $now -DurationSeconds ([int] $id.planned_seconds) -MaxGapSeconds 180 -ExpectedSha $id.candidate_source_sha -ExpectedMission $id.mission
if ($verdict.verdict -ne 'PENDING') {
    $finalPath = Join-Path $repo "soak\beta5\$($id.mission)\final-verdict.json"
    Write-Beta5JsonAtomic -Object ([ordered]@{ schema = 'civiccast-native-beta5-media-verdict-v3'; mission = $id.mission; candidate_source_sha = $id.candidate_source_sha; verdict = $verdict.verdict; reason = $verdict.reason; completed_utc = $now.ToString('o') }) -Path $finalPath
    Publish-Beta5Report -Identity $id -ReportPath $finalPath -Message "test: beta5 final media verdict $($id.mission) $($verdict.verdict)"
    if ($ScheduledTaskName) { Unregister-ScheduledTask -TaskName $ScheduledTaskName -Confirm:$false -ErrorAction Stop }
}
