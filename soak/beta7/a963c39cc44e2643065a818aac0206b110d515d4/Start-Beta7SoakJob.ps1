# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([string]$PackageRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
if(-not $PackageRoot){$PackageRoot=$PSScriptRoot}
$files=@('Beta7Tester.Common.ps1','Run-Beta7SoakJob.ps1','Run-BetaExistingTesterSoak.ps1','Beta7TransportProbe.ps1','TSDuckReportClassifier.ps1')
foreach($name in $files){if(-not(Test-Path -LiteralPath (Join-Path $PackageRoot $name) -PathType Leaf)){throw "Missing soak package file: $name"}}
if($DryRun){Write-Output 'DRYRUN: copy five soak helpers; create one dedicated six-hour task; start it once; preserve coordination tasks. No actions performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This launch order targets DESKTOP-VBMA6O5 only.'}
$missionRoot='C:\CivicCastSoak\missions\beta7-sep12-a963c39cc44e2643065a818aac0206b110d515d4'
$installedBin=Join-Path $missionRoot 'bin'
$identityPath=Join-Path $installedBin 'run-identity.json'
. (Join-Path $installedBin 'Beta7Tester.Common.ps1')
$id=Get-Beta5Identity $identityPath
$missionRoot=[string]$id.mission_state_root
$bin=Join-Path $missionRoot 'physical-soak-r1-bin'
$taskName='CivicCast-Beta7-' + [string]$id.candidate_source_sha + '-PhysicalSoak-R1'
foreach($installedHelper in @($identityPath,(Join-Path $installedBin 'Beta7Tester.Common.ps1'))){if(-not(Test-Path -LiteralPath $installedHelper -PathType Leaf)){throw "Verified upgrade helper is missing: $installedHelper"}}
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Dedicated soak task already exists; do not launch it twice.'}
if(Test-Path -LiteralPath (Join-Path $missionRoot 'physical-soak-r1')){throw 'Physical soak evidence already exists; preserve it.'}
if(Test-Path -LiteralPath $bin){throw 'R1 stable script folder already exists; inspect before retry.'}
New-Item -ItemType Directory -Path $bin | Out-Null
foreach($name in $files){
    $destination=Join-Path $bin $name
    if(Test-Path -LiteralPath $destination){throw "Stable soak script already exists: $name"}
    Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination $destination
}
$runner=Join-Path $bin 'Run-Beta7SoakJob.ps1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$runner+'" -IdentityPath "'+$identityPath+'"'
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -Principal $principal -Description 'CivicCast beta.7 candidate: two120-minute physical soak phases; once only.' | Out-Null
Start-ScheduledTask -TaskName $taskName
@{order='BETA7-PHYSICAL-SOAK-R1';task_name=$taskName;launch_requested_utc=[datetime]::UtcNow.ToString('o');candidate_source_sha='a963c39cc44e2643065a818aac0206b110d515d4';job_report='soak/beta7-a963c39cc44e2643065a818aac0206b110d515d4/physical-soak-r1/job.json';status='LAUNCH_REQUESTED';measured_soak_started=$false} | ConvertTo-Json -Compress
