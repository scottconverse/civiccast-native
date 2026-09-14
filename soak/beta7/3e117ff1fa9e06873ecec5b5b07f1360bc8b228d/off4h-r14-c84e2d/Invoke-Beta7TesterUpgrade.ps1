# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Adopt the exact already-installed beta.7 bytes after re-verifying them.
[CmdletBinding()]
param([string]$PackageRoot=$PSScriptRoot,[switch]$DryRun)
$ErrorActionPreference='Stop'
$sourceIdentity=Join-Path $PackageRoot 'run-identity.json'
$packageProof=& (Join-Path $PackageRoot 'Test-Beta7HarnessPackage.ps1') -PackageRoot $PackageRoot -IdentityPath $sourceIdentity
$null=& (Join-Path $PackageRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $sourceIdentity
$null=& (Join-Path $PackageRoot 'Test-Beta7R14Harness.ps1') -PackageRoot $PackageRoot
if($DryRun){Write-Output 'DRYRUN VERIFIED: exact candidate, R14 harness, and installed-byte adoption plan passed; no mutation performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This R14 adoption order targets DESKTOP-VBMA6O5 only.'}
. (Join-Path $PackageRoot 'Beta7Tester.Common.ps1')
$id=& (Join-Path $PackageRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $sourceIdentity
$missionRoot=[string]$id.mission_state_root
if(Test-Path -LiteralPath $missionRoot){throw 'R14 mission already exists. Preserve it; never replay this nonce.'}
$r5Root='C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r5-e27a91'
$r5IdentityPath=Join-Path $r5Root 'bin\run-identity.json'
$invalidationPath='C:\CivicCastSoak\repo\soak\beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\physical-soak-off4h-r5-e27a91\INVALIDATED.json'
$report=[ordered]@{order='BETA7-R14-ADOPT-VERIFIED-INSTALL';hostname=[string]$env:COMPUTERNAME;candidate_source_sha=[string]$id.candidate_source_sha;started_utc=[datetime]::UtcNow.ToString('o');status='STARTED';step='preflight';error=$null}
try{
    $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'R14 adoption task must run elevated.'}
    if(-not(Test-Path -LiteralPath $invalidationPath -PathType Leaf)){throw 'R5 invalidation receipt is absent.'}
    $invalidation=Get-Content -LiteralPath $invalidationPath -Raw|ConvertFrom-Json
    if("$($invalidation.status)" -ne 'R5_INVALIDATED' -or "$($invalidation.mission_nonce)" -ne 'BETA7-3E117FF1-OFF4H-R5-E27A91'){throw 'R5 invalidation receipt is not the exact completed mission.'}
    $invalidationHash=(Get-FileHash -LiteralPath $invalidationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if($invalidationHash -cne "$($id.r5_invalidation_receipt_sha256)"){throw 'R5 invalidation receipt bytes do not match R14 identity.'}
    if("$($invalidation.task_state)" -ne 'Disabled' -or -not[bool]$invalidation.terminal_cleanup_verified -or -not[bool]$invalidation.schedule_cleanup_verified){throw 'R5 invalidation does not prove disabled task, terminal channel cleanup, and owned-schedule cleanup.'}
    $r5Task=Get-ScheduledTask -TaskName 'CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91' -ErrorAction SilentlyContinue
    if($r5Task -and "$($r5Task.State)" -ne 'Disabled'){throw 'R5 task is not disabled.'}
    if(-not(Test-Path -LiteralPath $r5IdentityPath -PathType Leaf)){throw 'R5 installed identity receipt is absent.'}
    $r5=Get-Content -LiteralPath $r5IdentityPath -Raw|ConvertFrom-Json
    foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha')){if("$($r5.$field)" -ne '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'){throw "R5 installed identity field $field is not exact."}}
    if("$($r5.actual_manifest_sha256)" -ne "$($id.expected_manifest_sha256)" -or "$($r5.actual_installer_sha256)" -ne "$($id.expected_installer_sha256)" -or "$($r5.installed_version)" -ne "$($id.expected_version)" -or "$($r5.installer_authenticode_status)" -ne 'Valid' -or "$($r5.installer_signer)" -ne 'Scott Converse'){throw 'R5 signed-kit and installed-version identity is not exact.'}
    $runtimeNames=@('Lib/site-packages/civiccast/egress/daemon.py','Lib/site-packages/civiccast/egress/gst/strategy.py')
    foreach($name in $runtimeNames){
        $expected="$($r5.expected_runtime_file_sha256.$name)";$recorded="$($r5.actual_runtime_file_sha256.$name)"
        if($expected -notmatch '^[0-9a-f]{64}$' -or $recorded -cne $expected){throw "R5 runtime receipt is invalid for $name."}
        $installedPath=Join-Path (Join-Path ([string]$id.install_root) 'runtime') ($name -replace '/','\')
        $actual=(Get-FileHash -LiteralPath $installedPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if($actual -cne $expected){throw "Current installed runtime differs from the exact candidate: $name"}
    }
    $installed=Assert-Beta5InstalledIdentity -Identity $id -InstallRoot ([string]$id.install_root)
    $directiveRoot=(Resolve-Path (Join-Path $PackageRoot '..\..\..\..')).Path
    $relativePackage=$PackageRoot.Substring($directiveRoot.Length).TrimStart('\').Replace('\','/')
    $directiveCommit=(& git -C $directiveRoot rev-parse HEAD).Trim()
    if($LASTEXITCODE -ne 0 -or $directiveCommit -notmatch '^[0-9a-f]{40}$'){throw 'Could not bind R14 harness to the directive commit.'}
    $dirty=@(& git -C $directiveRoot status --porcelain -- $relativePackage)
    if($LASTEXITCODE -ne 0 -or $dirty.Count){throw 'R14 package differs from its directive commit.'}
    $manifest=Get-Content -LiteralPath (Join-Path $PackageRoot 'harness-manifest.json') -Raw|ConvertFrom-Json
    $manifestPaths=@($manifest.files|ForEach-Object{"$relativePackage/$($_.path)"})
    $null=Invoke-Beta5Git -Repository $directiveRoot -Arguments @('cat-file','-e',"$($id.harness_source_commit)^{commit}")
    $null=Invoke-Beta5Git -Repository $directiveRoot -Arguments @('merge-base','--is-ancestor',[string]$id.harness_source_commit,$directiveCommit)
    $harnessDiff=@(Invoke-Beta5Git -Repository $directiveRoot -Arguments (@('diff','--name-only',[string]$id.harness_source_commit,'--')+$manifestPaths))
    if($harnessDiff.Count){throw "Manifest-bound harness files changed after their source commit: $($harnessDiff -join ', ')"}
    $testerRepo='C:\CivicCastSoak\repo'
    $null=Invoke-Beta5Git -Repository $testerRepo -Arguments @('fetch','origin',[string]$id.return_branch)
    $null=Invoke-Beta5Git -Repository $testerRepo -Arguments @('merge-base','--is-ancestor',[string]$id.r5_invalidation_remote_commit,"origin/$($id.return_branch)")
    $relativeInvalidation='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/INVALIDATED.json'
    $remoteBlob=(Invoke-Beta5Git -Repository $testerRepo -Arguments @('rev-parse',"$($id.r5_invalidation_remote_commit)`:$relativeInvalidation")|Select-Object -First 1).Trim()
    # Compare Git-normalized blobs. The Windows working file is CRLF while the
    # committed object is LF; hashing raw working bytes would reject valid,
    # exactly committed evidence.
    $localBlob=(Invoke-Beta5Git -Repository $testerRepo -Arguments @('rev-parse',":$relativeInvalidation")|Select-Object -First 1).Trim()
    if($remoteBlob -cne $localBlob){throw 'Local R5 invalidation receipt does not equal the identity-bound remote commit.'}
    $bin=Join-Path $missionRoot 'bin';New-Item -ItemType Directory -Path $bin -Force|Out-Null
    foreach($entry in @($manifest.files)){Copy-Item -LiteralPath (Join-Path $PackageRoot ([string]$entry.path)) -Destination (Join-Path $bin ([string]$entry.path))}
    Copy-Item -LiteralPath $sourceIdentity -Destination (Join-Path $bin 'run-identity.json')
    Copy-Item -LiteralPath (Join-Path $PackageRoot 'harness-manifest.json') -Destination (Join-Path $bin 'harness-manifest.json')
    $identityPath=Join-Path $bin 'run-identity.json'
    $copiedProof=& (Join-Path $bin 'Test-Beta7HarnessPackage.ps1') -PackageRoot $bin -IdentityPath $identityPath
    $id=Get-Content -LiteralPath $identityPath -Raw|ConvertFrom-Json
    foreach($field in @('actual_manifest_sha256','actual_installer_sha256','installer_product_version','installer_authenticode_status','installer_signer','native_app_payload_sha256','native_app_payload_source_sha','expected_runtime_file_sha256','actual_runtime_file_sha256','installed_version','installed_schema','installed_schema_db_revision','installed_schema_expected_head','installed_service_path','installed_location')){Set-Beta5IdentityField $id $field $r5.$field}
    Set-Beta5IdentityField $id 'installed_service_process_id' ([int]$installed.service_process_id)
    Set-Beta5IdentityField $id 'installed_service_process_started_utc' "$($installed.service_process_started_utc)"
    Set-Beta5IdentityField $id 'harness_source_commit' $directiveCommit
    Set-Beta5IdentityField $id 'harness_verified_sha256' $copiedProof.file_sha256
    Set-Beta5IdentityField $id 'adopted_from_mission' 'BETA7-3E117FF1-OFF4H-R5-E27A91'
    Set-Beta5IdentityField $id 'adopted_utc' ([datetime]::UtcNow.ToString('o'))
    Write-Beta5JsonAtomic $id $identityPath
    $report.status='PASS';$report.step='installed-bytes-and-harness-verified';$report.identity=$id;$report.package_manifest_sha256=$packageProof.manifest_sha256
}catch{$report.status='FAIL';$report.error=[string]$_.Exception.Message}
finally{
    $report.finished_utc=[datetime]::UtcNow.ToString('o')
    if(Test-Path -LiteralPath $missionRoot){Write-Beta5JsonAtomic $report (Join-Path $missionRoot 'upgrade-result.json')}
    Write-Output 'BETA7_R14_ADOPTION_RESULT_JSON_BEGIN';Write-Output ($report|ConvertTo-Json -Depth 12 -Compress);Write-Output 'BETA7_R14_ADOPTION_RESULT_JSON_END'
}
if($report.status -ne 'PASS'){throw 'R14 exact installed-byte adoption failed; preserve the mission and issue a new nonce after correction.'}
