# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference='Stop'

function Read-BoundedText([string]$Path,[int]$Tail=1500,[int]$MaxChars=180000) {
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $lines=@(Get-Content -LiteralPath $Path -Tail $Tail | ForEach-Object {[string]::Concat('',[string]$_)})
    $plain=[string]::Join("`n",[string[]]$lines)
    if($plain.Length -gt $MaxChars){$plain=$plain.Substring($plain.Length-$MaxChars)}
    return $plain
}

function Get-FileEvidence([string]$Path,[int]$Tail=1500,[int]$MaxChars=180000) {
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $item=Get-Item -LiteralPath $Path
    return [ordered]@{
        path=[string]$Path
        length=[long]$item.Length
        last_write_utc=$item.LastWriteTimeUtc.ToString('o')
        tail=Read-BoundedText -Path $Path -Tail $Tail -MaxChars $MaxChars
    }
}

if($SelfTest){
    $value=Get-FileEvidence -Path $PSCommandPath -Tail 50 -MaxChars 12000
    $roundTrip=(@{file=$value} | ConvertTo-Json -Depth 5 -Compress | ConvertFrom-Json)
    if(-not $roundTrip.file.last_write_utc -or $roundTrip.file.tail.Length -gt 12000){throw 'Bounded evidence serialization failed.'}
    Write-Output 'PASS: bounded file evidence serialization round trip.'
    return
}

if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This diagnostic targets DESKTOP-VBMA6O5 only.'}
$mission='C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c'
$report=[ordered]@{
    order='FIXED-BETA-R3-FAILURE-DIAGNOSTIC-R2'
    captured_utc=[datetime]::UtcNow.ToString('o')
    station_changes=$false
    task=$null
    processes=@()
    files=[ordered]@{}
}

$task=Get-ScheduledTask -TaskName 'CivicCast-FixedBeta-39e7-PhysicalSoak-R3' -ErrorAction SilentlyContinue
if($task){
    $info=$task | Get-ScheduledTaskInfo
    $report.task=[ordered]@{
        name=[string]$task.TaskName
        state=[string]$task.State
        last_result=[long]$info.LastTaskResult
        last_run_utc=$info.LastRunTime.ToUniversalTime().ToString('o')
    }
}

$candidateProcesses=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(civiccast|python|gst|ffmpeg)' -or
    ([string]$_.ExecutablePath) -like 'C:\CivicCastHostStore\install\*'
})
foreach($process in $candidateProcesses){
    $report.processes+=@([ordered]@{
        name=[string]$process.Name
        process_id=[uint32]$process.ProcessId
        parent_process_id=[uint32]$process.ParentProcessId
        creation_date=[string]$process.CreationDate
        executable_path=[string]$process.ExecutablePath
    })
}

foreach($name in @('physical-soak-r3-job.json','physical-soak-r3-publish-error.txt','physical-soak-r3-job.log')){
    $path=Join-Path $mission $name
    $report.files[('mission/'+$name)]=Get-FileEvidence -Path $path -Tail 1000 -MaxChars 120000
}

$runRoot=Join-Path $mission 'physical-soak-r3'
if(Test-Path -LiteralPath $runRoot -PathType Container){
    foreach($run in @(Get-ChildItem -LiteralPath $runRoot -Directory)){
        foreach($relative in @(
            'CHANNEL-INVENTORY.json','progress.log','VERDICT.json','STOP-VERIFIED.json',
            'ON\SOAK-START.json','ON\STARTUP-STATE.json','ON\states.ndjson',
            'ON\hardware.ndjson','ON\transport-results.json'
        )){
            $key='run/'+[string]$run.Name+'/'+($relative -replace '\\','/')
            $report.files[$key]=Get-FileEvidence -Path (Join-Path $run.FullName $relative) -Tail 1500 -MaxChars 180000
        }
    }
}

foreach($channel in @('public','education','government')){
    $logs=Join-Path 'C:\ProgramData\CivicCast\data\egress' ($channel+'\logs')
    foreach($name in @('gst-worker.stdout.log','gst-worker.stderr.log')){
        $report.files[('worker/'+$channel+'/'+$name)]=Get-FileEvidence -Path (Join-Path $logs $name) -Tail 2000 -MaxChars 90000
    }
}

$logRoot='C:\ProgramData\CivicCast\logs'
if(Test-Path -LiteralPath $logRoot -PathType Container){
    foreach($file in @(Get-ChildItem -LiteralPath $logRoot -File | Where-Object {
        $_.Name -match 'egress|supervisor|server|control_plane'
    } | Sort-Object LastWriteTime -Descending | Select-Object -First 4)){
        $report.files[('service/'+[string]$file.Name)]=Get-FileEvidence -Path $file.FullName -Tail 1000 -MaxChars 50000
    }
}

$json=$report | ConvertTo-Json -Depth 7 -Compress
if($json.Length -gt 1500000){throw 'Diagnostic report exceeds 1500 KiB.'}
Write-Output 'FIXED_BETA_R3_FAILURE_DIAGNOSTIC_R2_JSON_BEGIN'
Write-Output $json
Write-Output 'FIXED_BETA_R3_FAILURE_DIAGNOSTIC_R2_JSON_END'
