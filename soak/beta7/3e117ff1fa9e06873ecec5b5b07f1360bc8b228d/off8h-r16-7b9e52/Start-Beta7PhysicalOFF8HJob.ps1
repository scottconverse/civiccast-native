# Create and start one candidate-specific physical tester job.
[CmdletBinding()]
param([string]$PackageRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
if(-not $PackageRoot){$PackageRoot=$PSScriptRoot}
$null=& (Join-Path $PackageRoot 'Test-Beta7HarnessPackage.ps1') -PackageRoot $PackageRoot -IdentityPath (Join-Path $PackageRoot 'run-identity.json')
$null=& (Join-Path $PackageRoot 'Test-Beta7R16Harness.ps1') -PackageRoot $PackageRoot
if($DryRun){$null=& (Join-Path $PackageRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath (Join-Path $PackageRoot 'run-identity.json');Write-Output 'DRYRUN VERIFIED: exact finalized identity, complete harness, and one-run task plan passed; no mutation performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This launch order targets DESKTOP-VBMA6O5 only.'}
$missionRoot='C:\CivicCastSoak\missions\beta7-3e117ff1-off8h-r16-7b9e52'
$installedBin=Join-Path $missionRoot 'bin'
$identityPath=Join-Path $installedBin 'run-identity.json'
$id=& (Join-Path $installedBin 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
$installedPackageProof=& (Join-Path $installedBin 'Test-Beta7HarnessPackage.ps1') -PackageRoot $installedBin -IdentityPath $identityPath
$null=& (Join-Path $installedBin 'Test-Beta7R16Harness.ps1') -PackageRoot $installedBin
$upgrade=Get-Content -LiteralPath (Join-Path $id.mission_state_root 'upgrade-result.json') -Raw | ConvertFrom-Json
if($upgrade.status -cne 'PASS' -or [string]$upgrade.candidate_source_sha -cne [string]$id.candidate_source_sha){throw 'Exact candidate upgrade receipt has not passed.'}
$taskName=[string]$id.task_name
$outputName='physical-soak-off8h-r16-7b9e52'
$bin=Join-Path $missionRoot ($outputName+'-bin')
foreach($coordinationTask in @('CivicCastSoak-Poll','CivicCastSoak-Heartbeat','CivicCastSoak-Boot')){
    if(-not(Get-ScheduledTask -TaskName $coordinationTask -ErrorAction SilentlyContinue)){throw "Required coordination task is absent: $coordinationTask"}
}
$competing=@(Get-ScheduledTask -ErrorAction Stop | Where-Object {$_.TaskName -like 'CivicCast-Beta7-*' -and $_.TaskName -ne $taskName -and [string]$_.State -eq 'Running'})
if($competing.Count){throw "Another beta.7 physical task is running: $($competing.TaskName -join ', ')"}
if(Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue){throw 'Candidate-specific soak task already exists; do not launch it twice.'}
if(Test-Path -LiteralPath (Join-Path $missionRoot $outputName)){throw 'Candidate-specific physical evidence already exists; preserve it.'}
if(Test-Path -LiteralPath $bin){throw 'Stable candidate-specific script folder already exists; inspect before retry.'}
New-Item -ItemType Directory -Path $bin | Out-Null
$manifest=Get-Content -LiteralPath (Join-Path $installedBin 'harness-manifest.json') -Raw|ConvertFrom-Json
foreach($entry in @($manifest.files)){Copy-Item -LiteralPath (Join-Path $installedBin ([string]$entry.path)) -Destination (Join-Path $bin ([string]$entry.path))}
Copy-Item -LiteralPath $identityPath -Destination (Join-Path $bin 'run-identity.json')
Copy-Item -LiteralPath (Join-Path $installedBin 'harness-manifest.json') -Destination (Join-Path $bin 'harness-manifest.json')
$stableProof=& (Join-Path $bin 'Test-Beta7HarnessPackage.ps1') -PackageRoot $bin -IdentityPath (Join-Path $bin 'run-identity.json')
$null=& (Join-Path $bin 'Test-Beta7R16Harness.ps1') -PackageRoot $bin
@{schema='civiccast-beta7-harness-runtime-v1';mission_nonce=[string]$id.mission_nonce;source_commit=[string]$id.harness_source_commit;manifest_sha256=$stableProof.manifest_sha256;file_sha256=$stableProof.file_sha256;copied_utc=[datetime]::UtcNow.ToString('o')}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $bin 'harness-runtime.json') -Encoding utf8
$runner=Join-Path $bin 'Run-Beta7PhysicalOFF8HJob.ps1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$runner+'" -IdentityPath "'+$identityPath+'"'
$action=New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 11) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Settings $settings -Principal $principal -Description 'CivicCast beta.7 3e117ff1: eight measured hours captions OFF; once only.' | Out-Null
Start-ScheduledTask -TaskName $taskName
@{order='BETA7-3E117FF1-PHYSICAL-OFF8H-R16';mission_nonce=[string]$id.mission_nonce;task_name=$taskName;launch_requested_utc=[datetime]::UtcNow.ToString('o');candidate_source_sha=[string]$id.candidate_source_sha;job_report=([string]$id.evidence_relative_root+'/job.json');status='LAUNCH_REQUESTED';measured_soak_started=$false} | ConvertTo-Json -Compress
