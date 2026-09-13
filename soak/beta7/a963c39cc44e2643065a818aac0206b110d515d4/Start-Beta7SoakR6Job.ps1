# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([string]$PackageRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
if(-not $PackageRoot){$PackageRoot=$PSScriptRoot}
$files=@('Beta7Tester.Common.ps1','Run-Beta7SoakR6Job.ps1','Run-BetaExistingTesterSoakR6.ps1','Beta7TransportProbeR6.ps1','TSDuckReportClassifierR6.ps1')
foreach($name in $files){if(-not(Test-Path -LiteralPath (Join-Path $PackageRoot $name) -PathType Leaf)){throw "Missing soak package file: $name"}}
if($DryRun){Write-Output 'DRYRUN: preserve R1-R5; require exact R5 admission failure receipt; create one unique R6 task with existing install/return repo. No actions performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This launch order targets DESKTOP-VBMA6O5 only.'}
$missionRoot='C:\CivicCastSoak\missions\beta7-sep12-a963c39cc44e2643065a818aac0206b110d515d4'
$installedBin=Join-Path $missionRoot 'bin'
$identityPath=Join-Path $installedBin 'run-identity.json'
. (Join-Path $installedBin 'Beta7Tester.Common.ps1')
$id=Get-Beta5Identity $identityPath
$expectedSourceSha='a963c39cc44e2643065a818aac0206b110d515d4'
foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha')){if([string]$id.$field -cne $expectedSourceSha){throw "R6 identity field $field is not the exact authorized a963 candidate."}}
$upgrade=Get-Content -LiteralPath (Join-Path $id.mission_state_root 'upgrade-result.json') -Raw | ConvertFrom-Json
if($upgrade.status -cne 'PASS' -or [string]$upgrade.candidate_source_sha -cne $expectedSourceSha){throw 'Exact a963 candidate upgrade receipt has not passed.'}
$missionRoot=[string]$id.mission_state_root
$bin=Join-Path $missionRoot 'physical-soak-r6-bin'
$taskName='CivicCast-Beta7-' + [string]$id.candidate_source_sha + '-PhysicalSoak-R6'
foreach($installedHelper in @($identityPath,(Join-Path $installedBin 'Beta7Tester.Common.ps1'))){if(-not(Test-Path -LiteralPath $installedHelper -PathType Leaf)){throw "Verified upgrade helper is missing: $installedHelper"}}
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Dedicated soak task already exists; do not launch it twice.'}
if(-not(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r1'))){throw 'R1 evidence is absent; R6 may only recover the preserved R1 mission.'}
if(-not(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r2'))){throw 'R2 evidence is absent; R6 may only follow the preserved R2 mission.'}
$r5ReceiptPath=Join-Path $missionRoot 'physical-soak-r5-job.json'
if(-not(Test-Path -LiteralPath $r5ReceiptPath -PathType Leaf)){throw 'Preserved R5 job receipt is absent.'}
$r5Receipt=Get-Content -LiteralPath $r5ReceiptPath -Raw | ConvertFrom-Json
if([string]$r5Receipt.job_state -cne 'FAIL' -or [string]$r5Receipt.source_sha -cne $expectedSourceSha -or [string]$r5Receipt.error -cne 'ON transport admission did not produce a clean 0/0/0 round on all three channels.'){
    throw 'R5 receipt is not the exact preserved a963 admission-logic failure receipt.'
}
if(-not(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r5') -PathType Container)){throw 'Preserved R5 evidence directory is absent.'}
if(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r6')){throw 'R6 physical soak evidence already exists; preserve it.'}
if(Test-Path -LiteralPath $bin){throw 'R6 stable script folder already exists; inspect before retry.'}
New-Item -ItemType Directory -Path $bin | Out-Null
foreach($name in $files){
    $destination=Join-Path $bin $name
    if(Test-Path -LiteralPath $destination){throw "Stable soak script already exists: $name"}
    Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination $destination
}
$runner=Join-Path $bin 'Run-Beta7SoakR6Job.ps1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$runner+'" -IdentityPath "'+$identityPath+'"'
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -Principal $principal -Description 'CivicCast beta.7 R6: admitted recovery, two 120-minute physical soak phases; once only.' | Out-Null
Start-ScheduledTask -TaskName $taskName
@{order='BETA7-PHYSICAL-SOAK-R6';task_name=$taskName;launch_requested_utc=[datetime]::UtcNow.ToString('o');candidate_source_sha='a963c39cc44e2643065a818aac0206b110d515d4';job_report='soak/beta7-a963c39cc44e2643065a818aac0206b110d515d4/physical-soak-r6/job.json';status='LAUNCH_REQUESTED';measured_soak_started=$false} | ConvertTo-Json -Compress
