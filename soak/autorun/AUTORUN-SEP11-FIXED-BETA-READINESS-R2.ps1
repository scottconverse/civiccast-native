# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'
$relative='soak/fixed-beta-39e7/readiness-r2.json'
if($DryRun){[ordered]@{order='READINESS-R2';target='DESKTOP-VBMA6O5';receipt=$relative;station_changes=$false;force_push=$false}|ConvertTo-Json;exit 0}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'R2 targets DESKTOP-VBMA6O5 only.'}
$root='C:\CivicCastSoak'
$repo=Join-Path $root 'repo'
$branch='tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$reportLog=Get-ChildItem -LiteralPath (Join-Path $root 'reports') -Filter 'AUTORUN-SEP11-FIXED-BETA-READINESS-R1-*.log' -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$raw=if($reportLog){Get-Content -LiteralPath $reportLog.FullName -Raw}else{''}
$replayed=$false
$match=[regex]::Match($raw,'(?s)FIXED_BETA_READINESS_JSON_BEGIN\s*(.*?)\s*FIXED_BETA_READINESS_JSON_END')
if(-not $match.Success){
    $replayed=$true
    # This later coordinator order explicitly authorizes one new read-only probe.
    # No poller .done marker is removed and the original output remains intact.
    $probe=Join-Path $PSScriptRoot 'AUTORUN-SEP11-FIXED-BETA-READINESS-R1.ps1'
    $raw=(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe 2>&1 | Out-String)
    if($LASTEXITCODE -ne 0){throw 'R1 readiness probe failed; original report retained locally.'}
    $match=[regex]::Match($raw,'(?s)FIXED_BETA_READINESS_JSON_BEGIN\s*(.*?)\s*FIXED_BETA_READINESS_JSON_END')
}
if(-not $match.Success){throw 'Readiness output did not contain a complete JSON report.'}
$readiness=$match.Groups[1].Value | ConvertFrom-Json
if($readiness.hostname -ine $env:COMPUTERNAME -or $readiness.candidate_source_sha -ne '39e7ec3cbb4ccbeb3009ff3257dfc314010151f3'){throw 'Readiness identity mismatch.'}
$lan=[ordered]@{url='http://192.168.0.135:8766/SHA256SUMS.txt';reachable=$false}
try{$response=Invoke-WebRequest -UseBasicParsing -Uri $lan.url -TimeoutSec 8;$lan.reachable=($response.StatusCode -eq 200);$lan.status=$response.StatusCode}catch{$lan.error_type=$_.Exception.GetType().Name}
$receipt=[ordered]@{order='READINESS-R2';returned_utc=[DateTime]::UtcNow.ToString('o');r1_log_found=[bool]$reportLog;r1_replayed=$replayed;r1_json_parsed=$true;readiness=$readiness;candidate_lan=$lan;station_changes=$false;log_return_issue='The existing poller adds *.log without force; repository ignores *.log. This order returns JSON explicitly.'}
$destination=Join-Path $repo $relative
if(Test-Path -LiteralPath $destination){throw 'Receipt already exists; preserve it instead of replaying.'}
New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $destination -Encoding utf8
& git -C $repo add -- $relative
if($LASTEXITCODE -ne 0){throw 'Could not stage readiness JSON.'}
& git -C $repo commit --only -s -m 'test: return fixed beta tester readiness JSON' -- $relative
if($LASTEXITCODE -ne 0){throw 'Could not commit readiness JSON.'}
& git -C $repo push origin $branch
if($LASTEXITCODE -ne 0){
    & git -C $repo pull --rebase origin $branch
    if($LASTEXITCODE -ne 0){throw 'Receipt preserved; rebase failed. Never force-push.'}
    & git -C $repo push origin $branch
    if($LASTEXITCODE -ne 0){throw 'Receipt preserved; retry push failed.'}
}
Write-Output "Readiness JSON returned: $relative"
