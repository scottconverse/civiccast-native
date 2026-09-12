[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'
$package=Join-Path $PSScriptRoot '..\beta7\a963c39cc44e2643065a818aac0206b110d515d4'
if($DryRun){Write-Output 'DRYRUN: exact a963c39 beta.7 install and physical-soak handoff; no actions performed.'; return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This beta.7 mission targets DESKTOP-VBMA6O5 only.'}
& (Join-Path $package 'Invoke-Beta7TesterUpgrade.ps1') -PackageRoot $package
$launch = & (Join-Path $package 'Start-Beta7SoakJob.ps1') -PackageRoot $package
if (-not ($launch -match 'CivicCast-Beta7-.*-PhysicalSoak-R1')) { throw 'Beta.7 soak handoff did not return the dedicated task receipt.' }
$taskName=([regex]::Match(($launch -join "`n"),'CivicCast-Beta7-[^\s]+-PhysicalSoak-R1')).Value
$task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if (-not $task) { throw "Dedicated beta.7 task was not created: $taskName" }
Write-Output ($launch -join "`n")
