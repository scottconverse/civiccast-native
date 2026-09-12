[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'
$package=Join-Path $PSScriptRoot '..\beta7\a963c39cc44e2643065a818aac0206b110d515d4'
if($DryRun){Write-Output 'BETA7_R2_DRYRUN: preserve R1; no reinstall, republish, reconfigure, start, or task mutation performed.'; return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This beta.7 R2 mission targets DESKTOP-VBMA6O5 only.'}
$launch=& (Join-Path $package 'Start-Beta7SoakR2Job.ps1') -PackageRoot $package
if(-not($launch -match 'CivicCast-Beta7-.*-PhysicalSoak-R2')){throw 'Beta.7 R2 handoff did not return the dedicated R2 task receipt.'}
$taskName=([regex]::Match(($launch -join "`n"),'CivicCast-Beta7-[^\s]+-PhysicalSoak-R2')).Value
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if(-not $task){throw "Dedicated beta.7 R2 task was not created: $taskName"}
Write-Output ($launch -join "`n")
