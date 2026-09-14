# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

$expectedHost='DESKTOP-VBMA6O5'
$expectedMission='BETA7-3E117FF1-OFF4H-R7-E6D01E'
$package=(Resolve-Path (Join-Path $PSScriptRoot '..\beta7\3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\off4h-r7-e6d01e')).Path
$identityPath=Join-Path $package 'run-identity.json'
$r5Root='C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r5-e27a91'
$r5IdentityPath=Join-Path $r5Root 'bin\run-identity.json'
$invalidationPath='C:\CivicCastSoak\repo\soak\beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\physical-soak-off4h-r5-e27a91\INVALIDATED.json'

if($SelfTest){
    if($expectedHost -cne 'DESKTOP-VBMA6O5' -or $expectedMission -cne 'BETA7-3E117FF1-OFF4H-R7-E6D01E'){
        throw 'Preflight diagnostic identity is not exact.'
    }
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($PSCommandPath,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw 'Preflight diagnostic has parse errors.'}
    $allowedCommands=@('Assert-Beta5InstalledIdentity','ConvertFrom-Json','ConvertTo-Json','ForEach-Object','Get-Content','Get-FileHash','Get-ScheduledTask','Invoke-Beta5Git','Join-Path','Out-Null','Resolve-Path','Select-Object','Set-StrictMode','Test-Beta7HarnessPackage','Test-Path','Where-Object','Write-Output')
    $commands=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()}|Where-Object{$_})
    $unknownCommands=@($commands|Where-Object{$allowedCommands -cnotcontains $_}|Select-Object -Unique)
    if($unknownCommands.Count){throw "Preflight diagnostic contains a command outside its read-only allowlist: $($unknownCommands -join ', ')"}
    $allowedTypes=@('datetime','Management.Automation.Language.CommandAst','Management.Automation.Language.Parser','Management.Automation.Language.TypeExpressionAst','regex','Security.Principal.WindowsBuiltInRole','Security.Principal.WindowsIdentity','Security.Principal.WindowsPrincipal','string','StringComparison','Text.Encoding')
    $types=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.TypeExpressionAst]},$true)|ForEach-Object{$_.TypeName.FullName}|Where-Object{$_}|Select-Object -Unique)
    $unknownTypes=@($types|Where-Object{$allowedTypes -cnotcontains $_})
    if($unknownTypes.Count){throw "Preflight diagnostic contains a type outside its read-only allowlist: $($unknownTypes -join ', ')"}
    $text=Get-Content -LiteralPath $PSCommandPath -Raw
    foreach($token in @("`$step='r5-invalidation-hash'","`$step='installed-runtime-hashes'","`$step='installed-service-identity'","`$step='directive-package-clean'","`$step='source-anchor-diff'","`$step='r5-remote-blob-binding'",'UTF8.GetByteCount($json) -gt 65536')){
        if([regex]::Matches($text,[regex]::Escape($token)).Count -ne 2){throw "Preflight diagnostic lost required assertion or output bound: $token"}
    }
    [pscustomobject]@{verdict='PASS';runtime=$PSVersionTable.PSEdition;version=$PSVersionTable.PSVersion.ToString();station_changes=$false;task_changes=0;schedule_changes=0;channel_changes=0}|ConvertTo-Json -Compress
    return
}

if($env:COMPUTERNAME -ine $expectedHost){throw "This diagnostic targets $expectedHost only."}
. (Join-Path $package 'Beta7Tester.Common.ps1')
$report=[ordered]@{schema='civiccast-beta7-r7-adoption-preflight-v1';hostname=[string]$env:COMPUTERNAME;mission_nonce=$expectedMission;captured_utc=[datetime]::UtcNow.ToString('o');station_changes=$false;task_changes=0;schedule_changes=0;channel_changes=0;git_fetches=0;status='STARTED';step='package';error=$null;details=[ordered]@{}}
try{
    $packageProof=& (Join-Path $package 'Test-Beta7HarnessPackage.ps1') -PackageRoot $package -IdentityPath $identityPath
    $id=& (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
    $report.details.package_manifest_sha256=[string]$packageProof.manifest_sha256
    $report.details.harness_source_commit=[string]$id.harness_source_commit

    $step='administrator';$report.step=$step
    $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'R7 adoption task is not elevated.'}

    $step='r5-invalidation-file';$report.step=$step
    if(-not(Test-Path -LiteralPath $invalidationPath -PathType Leaf)){throw 'R5 invalidation receipt is absent.'}
    $invalidation=Get-Content -LiteralPath $invalidationPath -Raw|ConvertFrom-Json
    if([string]$invalidation.status -cne 'R5_INVALIDATED' -or [string]$invalidation.mission_nonce -cne 'BETA7-3E117FF1-OFF4H-R5-E27A91'){throw 'R5 invalidation receipt is not the exact completed mission.'}

    $step='r5-invalidation-hash';$report.step=$step
    $invalidationHash=(Get-FileHash -LiteralPath $invalidationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $report.details.invalidation_sha256=$invalidationHash
    if($invalidationHash -cne [string]$id.r5_invalidation_receipt_sha256){throw 'R5 invalidation receipt bytes do not match R7 identity.'}
    if([string]$invalidation.task_state -cne 'Disabled' -or -not[bool]$invalidation.terminal_cleanup_verified -or -not[bool]$invalidation.schedule_cleanup_verified){throw 'R5 invalidation cleanup proof is incomplete.'}

    $step='r5-disabled-task';$report.step=$step
    $r5Task=Get-ScheduledTask -TaskName 'CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91' -ErrorAction SilentlyContinue
    if($r5Task -and [string]$r5Task.State -cne 'Disabled'){throw 'R5 task is not disabled.'}

    $step='r5-installed-identity';$report.step=$step
    if(-not(Test-Path -LiteralPath $r5IdentityPath -PathType Leaf)){throw 'R5 installed identity receipt is absent.'}
    $r5=Get-Content -LiteralPath $r5IdentityPath -Raw|ConvertFrom-Json
    foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha')){if([string]$r5.$field -cne '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'){throw "R5 installed identity field $field is not exact."}}
    if([string]$r5.actual_manifest_sha256 -cne [string]$id.expected_manifest_sha256 -or [string]$r5.actual_installer_sha256 -cne [string]$id.expected_installer_sha256 -or [string]$r5.installed_version -cne [string]$id.expected_version -or [string]$r5.installer_authenticode_status -cne 'Valid' -or [string]$r5.installer_signer -cne 'Scott Converse'){throw 'R5 signed-kit and installed-version identity is not exact.'}

    $step='installed-runtime-hashes';$report.step=$step
    foreach($name in @('Lib/site-packages/civiccast/egress/daemon.py','Lib/site-packages/civiccast/egress/gst/strategy.py')){
        $expected=[string]$r5.expected_runtime_file_sha256.$name;$recorded=[string]$r5.actual_runtime_file_sha256.$name
        if($expected -notmatch '^[0-9a-f]{64}$' -or $recorded -cne $expected){throw "R5 runtime receipt is invalid for $name."}
        $installedPath=Join-Path (Join-Path ([string]$id.install_root) 'runtime') ($name -replace '/','\')
        $actual=(Get-FileHash -LiteralPath $installedPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $report.details[$name]=$actual
        if($actual -cne $expected){throw "Current installed runtime differs from the exact candidate: $name"}
    }

    $step='installed-service-identity';$report.step=$step
    $installed=Assert-Beta5InstalledIdentity -Identity $id -InstallRoot ([string]$id.install_root)
    $report.details.service_process_id=$installed.service_process_id

    $step='directive-package-clean';$report.step=$step
    $directiveRoot=(Resolve-Path (Join-Path $package '..\..\..\..')).Path
    $relativePackage=$package.Substring($directiveRoot.Length).TrimStart('\') -replace '\','/'
    $directiveCommit=(Invoke-Beta5Git -Repository $directiveRoot -Arguments @('rev-parse','HEAD')|Select-Object -First 1).Trim()
    if($directiveCommit -notmatch '^[0-9a-f]{40}$'){throw 'Could not read R7 directive commit.'}
    $report.details.directive_commit=$directiveCommit
    $dirty=@(Invoke-Beta5Git -Repository $directiveRoot -Arguments @('status','--porcelain','--',$relativePackage))
    if($dirty.Count){throw "R7 package differs from its directive commit: $($dirty -join ', ')"}

    $step='source-anchor-diff';$report.step=$step
    $manifest=Get-Content -LiteralPath (Join-Path $package 'harness-manifest.json') -Raw|ConvertFrom-Json
    $manifestPaths=@($manifest.files|ForEach-Object{"$relativePackage/$($_.path)"})
    $null=Invoke-Beta5Git -Repository $directiveRoot -Arguments @('cat-file','-e',"$($id.harness_source_commit)^{commit}")
    $null=Invoke-Beta5Git -Repository $directiveRoot -Arguments @('merge-base','--is-ancestor',[string]$id.harness_source_commit,$directiveCommit)
    $harnessDiff=@(Invoke-Beta5Git -Repository $directiveRoot -Arguments (@('diff','--name-only',[string]$id.harness_source_commit,'--')+$manifestPaths))
    if($harnessDiff.Count){throw "Manifest-bound harness files changed after their source commit: $($harnessDiff -join ', ')"}

    $step='r5-remote-blob-binding';$report.step=$step
    $testerRepo='C:\CivicCastSoak\repo'
    $null=Invoke-Beta5Git -Repository $testerRepo -Arguments @('fetch','origin',[string]$id.return_branch);$report.git_fetches=1
    $null=Invoke-Beta5Git -Repository $testerRepo -Arguments @('merge-base','--is-ancestor',[string]$id.r5_invalidation_remote_commit,"origin/$($id.return_branch)")
    $relativeInvalidation='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/INVALIDATED.json'
    $remoteBlob=(Invoke-Beta5Git -Repository $testerRepo -Arguments @('rev-parse',"$($id.r5_invalidation_remote_commit)`:$relativeInvalidation")|Select-Object -First 1).Trim()
    $localBlob=(Invoke-Beta5Git -Repository $testerRepo -Arguments @('rev-parse',":$relativeInvalidation")|Select-Object -First 1).Trim()
    $report.details.remote_blob=$remoteBlob;$report.details.local_blob=$localBlob
    if($remoteBlob -cne $localBlob){throw 'Local R5 invalidation receipt does not equal the identity-bound remote commit.'}
    $report.status='PASS';$report.step='all-read-only-adoption-assertions'
}catch{
    $report.status='FAIL';$report.error=[string]$_.Exception.Message
}
$json=$report|ConvertTo-Json -Depth 12 -Compress
if([Text.Encoding]::UTF8.GetByteCount($json) -gt 65536){throw 'R7 preflight diagnostic exceeds 64 KiB.'}
Write-Output 'BETA7_R7_ADOPTION_PREFLIGHT_JSON_BEGIN'
Write-Output $json
Write-Output 'BETA7_R7_ADOPTION_PREFLIGHT_JSON_END'
