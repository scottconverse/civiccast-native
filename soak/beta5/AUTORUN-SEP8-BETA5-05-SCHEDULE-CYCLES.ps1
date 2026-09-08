# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([Parameter(Mandatory)][string] $IdentityPath, [switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
$id = Get-Beta5Identity $IdentityPath
$taskName = "CivicCast-Beta5-$($id.mission)-Soak"
$cycleScript = Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1'
$stableBin = Join-Path $id.mission_state_root 'bin'
$null = Assert-Beta5ChildPath -BasePath $stableBin -CandidatePath $cycleScript
if (-not (Test-Path -LiteralPath $cycleScript -PathType Leaf)) { throw "Stable cycle script is absent: $cycleScript" }
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$cycleScript`" -IdentityPath `"$IdentityPath`" -ScheduledTaskName `"$taskName`""
if ($DryRun) { Write-Host "[DRYRUN] register exact task $taskName every $($id.sample_interval_seconds)s using $cycleScript"; return }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Seconds ([int] $id.sample_interval_seconds)) -RepetitionDuration (New-TimeSpan -Seconds ([int] $id.planned_seconds + 1800))
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "SCHEDULER PASS: $taskName, $($id.sample_interval_seconds)-second cadence, exact stable script path."
