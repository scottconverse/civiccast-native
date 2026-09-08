# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^https?://')][string]$ApiBase,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,63}$')][string]$ChannelId,
    [Parameter(Mandatory=$true)][string]$BearerToken,
    [Parameter(Mandatory=$true)][string]$FirstAssetId,
    [Parameter(Mandatory=$true)][string]$SecondAssetId,
    [Parameter(Mandatory=$true)][string]$FirstSourceLabel,
    [Parameter(Mandatory=$true)][string]$SecondSourceLabel,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedSha,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion,
    [Parameter(Mandatory=$true)][string]$InstallReceiptPath,
    [Parameter(Mandatory=$true)][ValidateRange(1024,65535)][int]$UdpPort,
    [Parameter(Mandatory=$true)][string]$TspExe,
    [ValidateRange(5,120)][int]$ProgramSeconds = 30,
    [ValidateRange(45,300)][int]$GapSeconds = 90,
    [ValidateRange(5,120)][int]$LeadSeconds = 30,
    [ValidateRange(5,30)][int]$TsProbeSeconds = 10,
    [switch]$LongBoard,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'ProbeContracts.psm1') -Force
$Base = $ApiBase.TrimEnd('/')
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runId = 'filler-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out = Join-Path (Join-Path $root 'results') $runId
New-Item -ItemType Directory -Force -Path $out | Out-Null
$headers = @{ Authorization = "Bearer $BearerToken" }
$started = (Get-Date).ToUniversalTime()
$p1Start = $started.AddSeconds($LeadSeconds)
$p2Start = $p1Start.AddSeconds($ProgramSeconds + $GapSeconds)
$plan = [ordered]@{
    run_id=$runId; planned_at_utc=$started.ToString('o'); api_base=$Base
    channel_id=$ChannelId; expected_sha=$ExpectedSha.ToLowerInvariant()
    expected_version=$ExpectedVersion; udp_port=$UdpPort
    first_asset_id=$FirstAssetId; second_asset_id=$SecondAssetId
    first_start_utc=$p1Start.ToString('o'); program_seconds=$ProgramSeconds
    gap_seconds=$GapSeconds; second_start_utc=$p2Start.ToString('o')
    long_board=[bool]$LongBoard; execute=[bool]$Execute
    token_recorded=$false
}
$plan | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'PLAN.json') -Encoding UTF8
if (-not $Execute) { Write-Host "PLAN ONLY: $out"; exit 0 }
$samples=@();$phaseProof=@{};$created=@();$bulletinIds=@()
trap {
    $samples|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out 'STATE-SAMPLES.json') -Encoding UTF8
    [ordered]@{verdict='FAIL';run_id=$runId;expected_sha=$ExpectedSha.ToLowerInvariant();install_receipt_path=$receipt;install_receipt_sha256=$receiptHash;expected_version=$ExpectedVersion;error="$($_.Exception.GetType().Name): $($_.Exception.Message)";phase_proof=$phaseProof;created_schedule=$created;bulletin_ids=$bulletinIds}|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $out 'RESULT.json') -Encoding UTF8
    exit 2
}
if (-not (Test-Path -LiteralPath $TspExe -PathType Leaf)) { throw "tsp.exe not found: $TspExe" }
if ($LongBoard -and $LeadSeconds -lt 120) { throw '-LongBoard requires -LeadSeconds 120 so 13 create/approve pairs cannot consume the schedule lead.' }

function Invoke-Api([string]$Method,[string]$Path,[object]$Body=$null) {
    $args = @{ Method=$Method; Uri="$Base$Path"; Headers=$headers; TimeoutSec=30 }
    if ($null -ne $Body) { $args.ContentType='application/json'; $args.Body=($Body|ConvertTo-Json -Depth 8) }
    Invoke-RestMethod @args
}
function Add-Program([string]$Asset,[datetime]$When,[string]$Occurrence) {
    $item=Invoke-Api Post '/api/staff/schedule' (New-ScheduleBody $Asset $ChannelId $When $ProgramSeconds $runId)
    $commit=Invoke-Api Post '/api/staff/playout/commit' (New-CommitBody $ChannelId $Occurrence "$($item.id)")
    [ordered]@{schedule_item_id="$($item.id)"; occurrence_id=$Occurrence; commit=$commit}
}
function Test-Ts([string]$Phase) {
    $json=Join-Path $out ("ts-$Phase.json"); $stdout=Join-Path $out ("ts-$Phase.stdout.txt"); $stderr=Join-Path $out ("ts-$Phase.stderr.txt")
    $args=@('-I','ip',"$UdpPort",'--buffer-size','16777216','-P','until','--seconds',"$TsProbeSeconds",'-P','analyze','--json','--output-file',$json,'-O','drop')
    $proc=Start-Process -FilePath $TspExe -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $null=$proc.Handle; if(-not $proc.WaitForExit(($TsProbeSeconds+20)*1000)){Stop-Process -Id $proc.Id -Force; return [ordered]@{verdict='fail-timed-out'}}; $proc.Refresh()
    return Read-TsVerdict -Path $json -ExitCode $proc.ExitCode
}

$receipt=(Resolve-Path -LiteralPath $InstallReceiptPath -ErrorAction Stop).Path
$receiptRaw=Get-Content -LiteralPath $receipt -Raw
if($receiptRaw -notmatch ('(?i)'+[regex]::Escape($ExpectedSha))){throw 'install receipt does not bind the exact expected SHA'}
$receiptHash=(Get-FileHash -Algorithm SHA256 -LiteralPath $receipt).Hash.ToLowerInvariant()
$health=Invoke-RestMethod -Method Get -Uri "$Base/health" -TimeoutSec 20
$version=Invoke-RestMethod -Method Get -Uri "$Base/api/version" -TimeoutSec 20
Assert-ExpectedVersion $version $ExpectedVersion
$before=Invoke-Api Get "/api/staff/egress/channels/$ChannelId/state"
if($before.state -notin @('ON_AIR','FALLBACK_SLATE')){throw "channel is not already running: $($before.state)"}
$initialPid=[int64]$before.pid
if($initialPid -le 0){throw "channel did not report a positive GStreamer PID: $initialPid"}
$worker=Get-CimInstance Win32_Process -Filter "ProcessId=$initialPid"|Where-Object{$_.CommandLine -match 'egress[\\/]gst[\\/]worker\.py'}
if(-not $worker){throw "reported pid $initialPid is not a local installed GStreamer worker; run this probe on the TEST machine"}
$detail=Invoke-Api Get "/api/staff/egress/channels/$ChannelId"
if($detail.config.fill_policy -ne 'bulletins'){throw "dedicated channel fill_policy must already be bulletins; actual=$($detail.config.fill_policy)"}
if(-not @($detail.config.sinks|Where-Object{$_.kind -eq 'udp-ts' -and $_.uri -eq "udp://127.0.0.1:$UdpPort"}).Count){throw "dedicated channel lacks expected loopback udp-ts sink on port $UdpPort"}

if($LongBoard){
    foreach($i in 1..13){
        $b=Invoke-Api Post "/api/staff/cg/channels/$ChannelId/bulletins" (New-BulletinBody $runId $i)
        $null=Invoke-Api Patch "/api/staff/cg/channels/$ChannelId/bulletins/$($b.submission_id)" (New-BulletinApprovalBody $runId)
        $bulletinIds += "$($b.submission_id)"
    }
    $queue=Invoke-Api Get "/api/staff/cg/channels/$ChannelId/bulletins"
    $retained=@($queue.submissions|Where-Object{$bulletinIds -contains $_.submission_id -and $_.state -eq 'accepted'}).Count
    if($retained -ne 13){throw "long-board retention failed: retained=$retained expected=13"}
}

$p1Start=(Get-Date).ToUniversalTime().AddSeconds($LeadSeconds);$p2Start=$p1Start.AddSeconds($ProgramSeconds+$GapSeconds)
$plan.first_start_utc=$p1Start.ToString('o');$plan.second_start_utc=$p2Start.ToString('o');$plan|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out 'PLAN.json') -Encoding UTF8
$created=@(Add-Program $FirstAssetId $p1Start "$runId-p1"; Add-Program $SecondAssetId $p2Start "$runId-p2")
$deadline=$p2Start.AddSeconds($ProgramSeconds+120)
while((Get-Date).ToUniversalTime() -lt $deadline){
    $s=Invoke-Api Get "/api/staff/egress/channels/$ChannelId/state"
    $row=[ordered]@{utc=(Get-Date).ToUniversalTime().ToString('o');state=$s.state;pid=$s.pid;label=$s.current_source_label}
    $samples += $row
    Assert-StablePid $s $initialPid
    $workerNow=Get-CimInstance Win32_Process -Filter "ProcessId=$initialPid"|Where-Object{$_.CommandLine -match 'egress[\\/]gst[\\/]worker\.py'}
    if(-not $workerNow){throw "pid $initialPid no longer resolves to the installed GStreamer worker"}
    $now=(Get-Date).ToUniversalTime()
    if($now -lt $p1Start){Start-Sleep -Seconds 2; continue}
    $phase=$(if($now -lt $p1Start.AddSeconds($ProgramSeconds)){'program1'}elseif($now -lt $p2Start){'filler'}else{'program2'})
    $phaseMatches=$(if($phase -eq 'program1'){$s.state -eq 'ON_AIR' -and $s.current_source_label -eq $FirstSourceLabel}elseif($phase -eq 'filler'){$s.state -eq 'FALLBACK_SLATE'}else{$s.state -eq 'ON_AIR' -and $s.current_source_label -eq $SecondSourceLabel})
    if($phaseMatches -and -not $phaseProof.ContainsKey($phase)){$ts=Test-Ts $phase;$phaseProof[$phase]=[ordered]@{state=$s.state;label=$s.current_source_label;ts=$ts;ts_ok=($ts.verdict -eq 'pass')}}
    if($phaseProof.ContainsKey('program1') -and $phaseProof.ContainsKey('filler') -and $phaseProof.ContainsKey('program2')){break}
    Start-Sleep -Seconds 2
}
$samples|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $out 'STATE-SAMPLES.json') -Encoding UTF8
$pass=($phaseProof.program1.state -eq 'ON_AIR' -and $phaseProof.program1.label -eq $FirstSourceLabel -and $phaseProof.filler.state -eq 'FALLBACK_SLATE' -and $phaseProof.program2.state -eq 'ON_AIR' -and $phaseProof.program2.label -eq $SecondSourceLabel -and $phaseProof.program1.ts_ok -and $phaseProof.filler.ts_ok -and $phaseProof.program2.ts_ok)
$result=[ordered]@{verdict=$(if($pass){'PASS'}else{'FAIL'});run_id=$runId;expected_sha=$ExpectedSha.ToLowerInvariant();install_receipt_path=$receipt;install_receipt_sha256=$receiptHash;expected_version=$ExpectedVersion;observed_version=$version.version;health=$health;initial_pid=$initialPid;phase_proof=$phaseProof;created_schedule=$created;bulletin_ids=$bulletinIds;limitations=@('Long-board retention and filler TS are proven; individual slide visibility requires frame capture/OCR.')}
$result|ConvertTo-Json -Depth 12|Set-Content -LiteralPath (Join-Path $out 'RESULT.json') -Encoding UTF8
if($pass){exit 0}else{exit 1}
