# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference='Stop'
function Read-ProgressText([string]$Path) {
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $lines=@(Get-Content -LiteralPath $Path -Tail 500 | ForEach-Object {[string]::Concat('',[string]$_)})
    $plain=[string]::Join("`n",[string[]]$lines)
    if($plain.Length -gt 100000){$plain=$plain.Substring($plain.Length-100000)}
    return $plain
}
if($SelfTest){
    $value=Read-ProgressText $PSCommandPath
    $json=@{text=$value} | ConvertTo-Json -Compress
    if(($json | ConvertFrom-Json).text -ne $value){throw 'Plain-text serialization failed.'}
    Write-Output 'PASS: bounded plain-text serialization round trip.'
    return
}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This diagnostic targets DESKTOP-VBMA6O5 only.'}
$mission='C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c'
$report=[ordered]@{order='FIXED-BETA-STARTUP-DIAGNOSTIC-R1';utc=[datetime]::UtcNow.ToString('o');station_changes=$false;task=$null;files=@{}}
$task=Get-ScheduledTask -TaskName 'CivicCast-FixedBeta-39e7-PhysicalSoak-R2' -ErrorAction SilentlyContinue
if($task){
    $info=$task | Get-ScheduledTaskInfo
    $report.task=@{name=[string]$task.TaskName;state=[string]$task.State;last_result=[long]$info.LastTaskResult;last_run_utc=$info.LastRunTime.ToUniversalTime().ToString('o')}
}
foreach($name in @('physical-soak-r2-job.json','physical-soak-r2-publish-error.txt','physical-soak-r2-job.log')){
    $report.files[$name]=Read-ProgressText (Join-Path $mission $name)
}
$root=Join-Path $mission 'physical-soak-r2'
if(Test-Path -LiteralPath $root -PathType Container){
    foreach($run in @(Get-ChildItem -LiteralPath $root -Directory)){
        foreach($relative in @('CHANNEL-INVENTORY.json','progress.log','VERDICT.json','ON\SOAK-START.json','OFF\SOAK-START.json','ON\VERDICT.json','OFF\VERDICT.json')){
            $report.files[([string]$run.Name+'/'+$relative)]=Read-ProgressText (Join-Path $run.FullName $relative)
        }
    }
}

foreach($channel in @('public','education','government')){
    $logs=Join-Path 'C:\ProgramData\CivicCast\data\egress' ($channel+'\logs')
    foreach($name in @('gst-worker.stdout.log','gst-worker.stderr.log')){
        $report.files[($channel+'/'+$name)]=Read-ProgressText (Join-Path $logs $name)
    }
}
$logRoot='C:\ProgramData\CivicCast\logs'
if(Test-Path -LiteralPath $logRoot){
    foreach($file in @(Get-ChildItem -LiteralPath $logRoot -File | Where-Object {$_.Name -match 'egress|supervisor|server'} | Sort-Object LastWriteTime -Descending | Select-Object -First 4)){
        $report.files[('service/'+[string]$file.Name)]=Read-ProgressText $file.FullName
    }
}

$json=$report | ConvertTo-Json -Depth 5 -Compress
if($json.Length -gt 1500000){throw 'Progress report exceeds 1500 KiB.'}
Write-Output 'FIXED_BETA_SOAK_PROGRESS_JSON_BEGIN'
Write-Output $json
Write-Output 'FIXED_BETA_SOAK_PROGRESS_JSON_END'
