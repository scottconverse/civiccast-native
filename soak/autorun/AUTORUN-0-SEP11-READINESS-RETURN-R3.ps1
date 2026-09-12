# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Continue'
if($DryRun){Write-Output 'R3: DESKTOP-VBMA6O5 only; read poll and R1/R2 logs; publish JSON; no probe reruns or station changes.';exit 0}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'R3 targets DESKTOP-VBMA6O5 only.'}
$root='C:\CivicCastSoak'
$repo=Join-Path $root 'repo'
$relative='soak/fixed-beta-39e7/readiness-return-r3.json'
$report=[ordered]@{order='READINESS-RETURN-R3';hostname=$env:COMPUTERNAME;utc=[DateTime]::UtcNow.ToString('o');station_changes=$false;no_autorun=$env:CIVICCAST_SOAK_NO_AUTORUN;logs=@()}
$report.poll_tail=@(Get-Content -LiteralPath "$root\reports\poll.log" -Tail 20 -ErrorAction SilentlyContinue)
$report.done_markers=@(Get-ChildItem -LiteralPath "$root\state\autorun-done" -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -like '*SEP11*'} | Select-Object Name,LastWriteTime)
$logFiles=@(Get-ChildItem -LiteralPath "$root\reports" -File -ErrorAction SilentlyContinue | Where-Object {$_.Name -match '^AUTORUN-SEP11-FIXED-BETA-READINESS-R[12]-.*\.log$'} | Sort-Object LastWriteTime -Descending | Select-Object -First 4)
foreach($logFile in $logFiles){
    $text=Get-Content -LiteralPath $logFile.FullName -Raw -ErrorAction SilentlyContinue
    $match=[regex]::Match([string]$text,'(?s)FIXED_BETA_READINESS_JSON_BEGIN\s*(.*?)\s*FIXED_BETA_READINESS_JSON_END')
    $parsed=$null
    if($match.Success){try{$parsed=$match.Groups[1].Value|ConvertFrom-Json -ErrorAction Stop}catch{}}
    $report.logs+= [pscustomobject]@{name=$logFile.Name;bytes=$logFile.Length;readiness=$parsed;tail=@(Get-Content -LiteralPath $logFile.FullName -Tail 18)}
}
$report.tasks=@(Get-ScheduledTask -ErrorAction SilentlyContinue|Where-Object {$_.TaskName -like 'CivicCastSoak-*' -or $_.TaskName -like 'CivicCast-Beta5-*'}|Select-Object TaskName,@{n='state';e={$_.State.ToString()}})
$destination=Join-Path $repo $relative
if(Test-Path -LiteralPath $destination){throw 'R3 receipt exists; preserve it.'}
New-Item -ItemType Directory -Force -Path (Split-Path $destination)|Out-Null
$report|ConvertTo-Json -Depth 12|Set-Content -LiteralPath $destination -Encoding utf8 -ErrorAction Stop
& git -C $repo add -- $relative
if($LASTEXITCODE -ne 0){throw 'R3 JSON staging failed.'}
& git -C $repo commit --only -s -m 'test: diagnose tester readiness return path' -- $relative
if($LASTEXITCODE -ne 0){throw 'R3 JSON commit failed.'}
& git -C $repo push origin tester/soak8-e1acfe6-DESKTOP-VBMA6O5
if($LASTEXITCODE -ne 0){
    & git -C $repo pull --rebase origin tester/soak8-e1acfe6-DESKTOP-VBMA6O5
    if($LASTEXITCODE -ne 0){throw 'R3 JSON preserved locally; rebase failed.'}
    & git -C $repo push origin tester/soak8-e1acfe6-DESKTOP-VBMA6O5
    if($LASTEXITCODE -ne 0){throw 'R3 JSON preserved locally; push failed.'}
}
Write-Output 'R3 readiness return-path JSON published.'
