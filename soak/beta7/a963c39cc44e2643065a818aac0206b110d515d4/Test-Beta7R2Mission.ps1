$ErrorActionPreference='Stop'
$driver=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoak.ps1') -Raw
$job=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-Beta7SoakR2Job.ps1') -Raw
$start=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakR2Job.ps1') -Raw
foreach($required in @('RequireTransportAdmission','acquisition-diagnostic','clean-admission','excluded_from_verdict','ExistingRunRoot')){
    if($driver -notmatch [regex]::Escape($required)){throw "R2 driver contract is missing $required"}
}
if($driver -notmatch "clean-admission'.*verdict -ne 'PASS'"){throw 'R2 clean admission is not fail-closed.'}
if($driver -notmatch 'if \(\$RequireTransportAdmission\)' -or $driver -match 'if \(\$attachOn -and \$RequireTransportAdmission\)'){throw 'R2 transport admission must guard both ON startup and OFF restart.'}
if($job -notmatch '-Minutes 120 -Mode Both' -or $job -notmatch '-RequireTransportAdmission'){throw 'R2 job does not request the full admitted ON/OFF measurement.'}
if($job -notmatch 'STOP-VERIFIED.json' -or $job -notmatch '2026-09-12T23:02:27.0222520Z'){throw 'R2 job is not bound to the preserved R1 stop receipt.'}
if($job -match "clone','--quiet" -or $job -match 'ReplaceOverlappingTestSchedule'){throw 'R2 job may not clone a return repo or replace schedule rows.'}
foreach($token in @('physical-soak-r2','PhysicalSoak-R2','Run-Beta7SoakR2Job.ps1')){
    if(($job+$start) -notmatch [regex]::Escape($token)){throw "R2 identity is missing $token"}
}
& (Join-Path $PSScriptRoot 'Start-Beta7SoakR2Job.ps1') -PackageRoot $PSScriptRoot -DryRun | Out-Null
& (Join-Path $PSScriptRoot 'Run-Beta7SoakR2Job.ps1') -IdentityPath (Join-Path $PSScriptRoot 'run-identity.json') -DryRun | Out-Null
Write-Output 'BETA7_R2_MISSION_SELFTEST_PASS'
