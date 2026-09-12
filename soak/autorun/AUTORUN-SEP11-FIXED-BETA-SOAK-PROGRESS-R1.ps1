# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference='Stop'
function Read-ProgressText([string]$Path) {
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){return $null}
    $lines=@(Get-Content -LiteralPath $Path -Tail 20 | ForEach-Object {[string]::Concat('',[string]$_)})
    $plain=[string]::Join("`n",[string[]]$lines)
    if($plain.Length -gt 12000){$plain=$plain.Substring($plain.Length-12000)}
    return $plain
}
if($SelfTest){
    $value=Read-ProgressText $PSCommandPath
    $json=@{text=$value} | ConvertTo-Json -Compress
    if($json -match 'PSProvider|PSDrive|ImplementingType' -or ($json | ConvertFrom-Json).text -ne $value){throw 'Plain-text serialization failed.'}
    Write-Output 'PASS: bounded plain-text serialization round trip.'
    return
}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This diagnostic targets DESKTOP-VBMA6O5 only.'}
$mission='C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c'
$report=[ordered]@{order='FIXED-BETA-SOAK-PROGRESS-R1';utc=[datetime]::UtcNow.ToString('o');station_changes=$false;task=$null;files=@{}}
$task=Get-ScheduledTask -TaskName 'CivicCast-FixedBeta-39e7-PhysicalSoak-R1' -ErrorAction SilentlyContinue
if($task){
    $info=$task | Get-ScheduledTaskInfo
    $report.task=@{name=[string]$task.TaskName;state=[string]$task.State;last_result=[long]$info.LastTaskResult;last_run_utc=$info.LastRunTime.ToUniversalTime().ToString('o')}
}
foreach($name in @('physical-soak-job.json','physical-soak-publish-error.txt','physical-soak-job.log')){
    $report.files[$name]=Read-ProgressText (Join-Path $mission $name)
}
$root=Join-Path $mission 'physical-soak'
if(Test-Path -LiteralPath $root -PathType Container){
    foreach($run in @(Get-ChildItem -LiteralPath $root -Directory)){
        foreach($relative in @('progress.log','VERDICT.json','ON\SOAK-START.json','OFF\SOAK-START.json','ON\VERDICT.json','OFF\VERDICT.json')){
            $report.files[([string]$run.Name+'/'+$relative)]=Read-ProgressText (Join-Path $run.FullName $relative)
        }
    }
}
$json=$report | ConvertTo-Json -Depth 5 -Compress
if($json.Length -gt 131072){throw 'Progress report exceeds 128 KiB.'}
Write-Output 'FIXED_BETA_SOAK_PROGRESS_JSON_BEGIN'
Write-Output $json
Write-Output 'FIXED_BETA_SOAK_PROGRESS_JSON_END'
