# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([string]$PackageRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
if(-not $PackageRoot){$PackageRoot=$PSScriptRoot}
$files=@('Beta5Tester.Common.ps1','Run-FixedBetaSoakJob.ps1','Run-BetaExistingTesterSoak.ps1','FixedBetaTransportProbe.ps1','TSDuckReportClassifier.ps1')
foreach($name in $files){if(-not(Test-Path -LiteralPath (Join-Path $PackageRoot $name) -PathType Leaf)){throw "Missing soak package file: $name"}}
if($DryRun){Write-Output 'DRYRUN: copy five soak helpers; create one dedicated six-hour task; start it once; preserve coordination tasks. No actions performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This launch order targets DESKTOP-VBMA6O5 only.'}
$missionRoot='C:\CivicCastSoak\missions\beta6-sep11-39e7ec3cbb4c'
$installedBin=Join-Path $missionRoot 'bin'
$identityPath=Join-Path $installedBin 'run-identity.json'
$bin=Join-Path $missionRoot 'physical-soak-r2-bin'
$taskName='CivicCast-FixedBeta-39e7-PhysicalSoak-R2'
foreach($installedHelper in @($identityPath,(Join-Path $installedBin 'Beta5Tester.Common.ps1'))){if(-not(Test-Path -LiteralPath $installedHelper -PathType Leaf)){throw "Verified upgrade helper is missing: $installedHelper"}}
$upgrade=Get-Content -LiteralPath (Join-Path $missionRoot 'upgrade-result.json') -Raw | ConvertFrom-Json
if($upgrade.status -ne 'PASS' -or $upgrade.candidate_source_sha -ne '39e7ec3cbb4ccbeb3009ff3257dfc314010151f3'){throw 'Exact candidate upgrade has not passed.'}
$previous=Get-ScheduledTask -TaskName 'CivicCast-FixedBeta-39e7-PhysicalSoak-R1' -ErrorAction SilentlyContinue
if($previous -and [string]$previous.State -eq 'Running'){throw 'Previous attempt is still running; preserve it.'}
$previousResult=Get-Content -LiteralPath (Join-Path $missionRoot 'physical-soak-job.json') -Raw | ConvertFrom-Json
if($previousResult.job_state -ne 'FAIL'){throw 'R2 requires the preserved failed R1 result.'}
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Dedicated soak task already exists; do not launch it twice.'}
if(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r2')){throw 'Physical soak evidence already exists; preserve it.'}
if(Test-Path -LiteralPath $bin){throw 'R2 stable script folder already exists; inspect before retry.'}
New-Item -ItemType Directory -Path $bin | Out-Null
foreach($name in $files){
    $destination=Join-Path $bin $name
    if(Test-Path -LiteralPath $destination){throw "Stable soak script already exists: $name"}
    Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination $destination
}
$runner=Join-Path $bin 'Run-FixedBetaSoakJob.ps1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$runner+'" -IdentityPath "'+$identityPath+'"'
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -Principal $principal -Description 'Fixed CivicCast beta 39e7: two120-minute physical soak phases; once only.' | Out-Null
Start-ScheduledTask -TaskName $taskName
@{order='FIXED-BETA-PHYSICAL-SOAK-R2';task_name=$taskName;launch_requested_utc=[datetime]::UtcNow.ToString('o');candidate_source_sha='39e7ec3cbb4ccbeb3009ff3257dfc314010151f3';job_report='soak/fixed-beta-39e7/physical-soak-r2/job.json';status='LAUNCH_REQUESTED';measured_soak_started=$false} | ConvertTo-Json -Compress
