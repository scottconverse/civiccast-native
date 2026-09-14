[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'
$package=Join-Path $PSScriptRoot '..\beta7\3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\off4h-r4-c83f2d'
$identityPath=Join-Path $package 'run-identity.json'
if($DryRun){
    $null=& (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
    & (Join-Path $package 'Invoke-Beta7TesterUpgrade.ps1') -PackageRoot $package -DryRun
    & (Join-Path $package 'Start-Beta7PhysicalOFF4HJob.ps1') -PackageRoot $package -DryRun
    Write-Output 'DRYRUN VERIFIED: exact finalized bindings and execution plan passed; no mutation performed.'
    return
}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This beta.7 mission targets DESKTOP-VBMA6O5 only.'}
$coordinationTasks=@('CivicCastSoak-Poll','CivicCastSoak-Heartbeat','CivicCastSoak-Boot')
foreach($name in $coordinationTasks){if(-not(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)){throw "Required coordination task is absent: $name"}}
$id=& (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
$competing=@(Get-ScheduledTask -ErrorAction Stop | Where-Object {$_.TaskName -like 'CivicCast-Beta7-*' -and $_.TaskName -ne [string]$id.task_name -and [string]$_.State -eq 'Running'})
if($competing.Count){throw "Another beta.7 physical task is running: $($competing.TaskName -join ', ')"}
& (Join-Path $package 'Invoke-Beta7TesterUpgrade.ps1') -PackageRoot $package
$launch=& (Join-Path $package 'Start-Beta7PhysicalOFF4HJob.ps1') -PackageRoot $package
if(-not($launch -match [regex]::Escape([string]$id.task_name))){throw 'Physical soak handoff did not return the exact candidate-specific task receipt.'}
foreach($name in $coordinationTasks){if(-not(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)){throw "Coordination task disappeared during mission launch: $name"}}
$task=Get-ScheduledTask -TaskName ([string]$id.task_name) -ErrorAction SilentlyContinue
if(-not $task){throw 'Candidate-specific physical soak task was not created.'}
Write-Output ($launch -join "`n")
