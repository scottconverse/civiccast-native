[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'
$package=Join-Path $PSScriptRoot '..\beta7\a963c39cc44e2643065a818aac0206b110d515d4'
if($DryRun){Write-Output 'BETA7_R6_DRYRUN: preserve R1-R5 and require the exact R5 admission failure; no install, schedule, channel, task, or tester action performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This beta.7 R6 mission targets DESKTOP-VBMA6O5 only.'}
$launch=& (Join-Path $package 'Start-Beta7SoakR6Job.ps1') -PackageRoot $package
if(-not($launch -match 'CivicCast-Beta7-.*-PhysicalSoak-R6')){throw 'Beta.7 R6 handoff did not return the dedicated R6 task receipt.'}
$taskName=([regex]::Match(($launch -join "`n"),'CivicCast-Beta7-[^\s]+-PhysicalSoak-R6')).Value
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if(-not $task){throw "Dedicated beta.7 R6 task was not created: $taskName"}
Write-Output ($launch -join "`n")
