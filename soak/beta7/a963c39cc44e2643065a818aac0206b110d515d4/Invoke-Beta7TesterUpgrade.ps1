# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([string]$PackageRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
if(-not $PackageRoot){$PackageRoot=$PSScriptRoot}
$sourceIdentity=Join-Path $PackageRoot 'run-identity.json'
$sourceFiles=@('Beta7Tester.Common.ps1','AUTORUN-BETA7-FETCH-INSTALL.ps1','run-identity.json')
foreach($name in $sourceFiles){if(-not(Test-Path -LiteralPath (Join-Path $PackageRoot $name) -PathType Leaf)){throw "Package file missing: $name"}}
if($DryRun){Write-Output 'DRYRUN: exact tester; fresh mission; pause only legacy beta sampler; verify signed kit; in-place upgrade; return success/failure JSON. No actions performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This upgrade order targets DESKTOP-VBMA6O5 only.'}
. (Join-Path $PackageRoot 'Beta7Tester.Common.ps1')
$id=Get-Beta5Identity $sourceIdentity
$missionRoot=[string]$id.mission_state_root
if(Test-Path -LiteralPath $missionRoot){throw 'Mission already exists. Preserve its evidence and inspect before issuing any later retry order.'}
$report=[ordered]@{order='FIXED-BETA7-UPGRADE-R1';hostname=[string]$env:COMPUTERNAME;candidate_source_sha=[string]$id.candidate_source_sha;started_utc=[datetime]::UtcNow.ToString('o');status='STARTED';step='preflight';legacy_tasks=@();identity=$null;error=$null}
try{
    $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Tester upgrade task must run elevated.'}
    if(-not(Test-Path -LiteralPath ([string]$id.install_root) -PathType Container)){throw "Expected existing tester install root is absent: $($id.install_root)"}
    if(-not(Test-Path -LiteralPath 'C:\CivicCastSoak\state\token' -PathType Leaf)){throw 'Existing station token is absent; preserve station for diagnosis.'}
    $bin=Join-Path $missionRoot 'bin'
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    foreach($name in $sourceFiles){Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination (Join-Path $bin $name)}
    $identityPath=Join-Path $bin 'run-identity.json'
    $report.step='legacy-sampler-pause'
    foreach($task in @(Get-ScheduledTask -ErrorAction Stop | Where-Object {$_.TaskName -like 'CivicCast-Beta5-*-Soak'})){
        $report.legacy_tasks+=@{name=[string]$task.TaskName;path=[string]$task.TaskPath;was_enabled=[bool]$task.Settings.Enabled;was_running=([string]$task.State -eq 'Running')}
        Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath | Out-Null
        if([string]$task.State -eq 'Running'){Stop-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath}
    }
    $report.legacy_marker_archive=Move-Beta5LegacySoakMarker $id
    Write-Beta5JsonAtomic $report (Join-Path $missionRoot 'upgrade-progress.json')
    $report.step='fetch-verify-upgrade'
    & (Join-Path $bin 'AUTORUN-BETA7-FETCH-INSTALL.ps1') -IdentityPath $identityPath
    $report.identity=Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
    $report.status='PASS'
    $report.step='installed-identity-verified'
}catch{
    $report.status='FAIL'
    $report.error=[string]$_.Exception.Message
}finally{
    $report.finished_utc=[datetime]::UtcNow.ToString('o')
    # Identity/report fields are deliberately constructed values, not provider objects.
    $json=$report | ConvertTo-Json -Depth 7 -Compress
    if(Test-Path -LiteralPath $missionRoot){[IO.File]::WriteAllText((Join-Path $missionRoot 'upgrade-result.json'),$json,[Text.UTF8Encoding]::new($false))}
    Write-Output 'FIXED_BETA_UPGRADE_RESULT_JSON_BEGIN'
    Write-Output $json
    Write-Output 'FIXED_BETA_UPGRADE_RESULT_JSON_END'
}
if($report.status -ne 'PASS'){throw 'Fixed beta tester upgrade did not pass. See the returned result; do not replay this order.'}
