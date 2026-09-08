# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Portable test library only; no browser launch or CivicCast configuration change.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$mission='beta5-sep8-be1260bd0630'
$candidate='be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$expectedHost='DESKTOP-VBMA6O5'
$sourceRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5'))
$missionRoot="C:\CivicCastSoak\missions\$mission"
$outputRoot=Join-Path $missionRoot 'browser-tools-r1'
$toolRoot=Join-Path $missionRoot 'tools\browser-proof-r1'
if($DryRun){[ordered]@{mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHost;dry_run=$true;package='playwright-core@1.59.1';destination=$toolRoot;source='Exact signed-source npm lock URL with SHA256 and SHA512 verification';browser_launch=$false;global_install=$false;station_changes=$false;token_read=$false}|ConvertTo-Json;return}
if($env:COMPUTERNAME -cne $expectedHost){throw 'Portable tools target the dedicated tester only.'}
. (Join-Path $sourceRoot 'Beta5Tester.Common.ps1')
$identity=Get-Beta5Identity (Join-Path $missionRoot 'run-identity.json')
if($identity.mission -cne $mission -or $identity.candidate_source_sha -cne $candidate){throw 'Portable tools mission/source mismatch.'}
$null=Assert-Beta5ChildPath $missionRoot $outputRoot
$null=Assert-Beta5ChildPath $missionRoot $toolRoot
if((Test-Path -LiteralPath $outputRoot) -or (Test-Path -LiteralPath $toolRoot)){throw 'Portable tool state exists; preserve it rather than replay.'}
$bin=Join-Path $outputRoot 'bin'
New-Item -ItemType Directory -Path $bin | Out-Null
$support=@()
foreach($relative in @('Beta5Tester.Common.ps1','caption-proof\Get-Beta5BrowserPrerequisites.ps1','browser-tools\Provision-PortablePlaywrightCore.ps1')){
    $source=Join-Path $sourceRoot $relative
    $destination=Join-Path $bin ([IO.Path]::GetFileName($relative))
    $hash=(Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant()
    Copy-Item -LiteralPath $source -Destination $destination
    if((Get-FileHash -LiteralPath $destination).Hash.ToLowerInvariant() -cne $hash){throw 'Portable tool helper copy hash mismatch.'}
    $support += [pscustomobject]@{name=[IO.Path]::GetFileName($relative);sha256=$hash}
}
. (Join-Path $bin 'Beta5Tester.Common.ps1')
$failure=$null
try {
    $archive=Join-Path $outputRoot 'playwright-core-1.59.1.tgz'
    & curl.exe -fsSL --retry 3 --max-time 120 --output $archive 'https://registry.npmjs.org/playwright-core/-/playwright-core-1.59.1.tgz'
    if($LASTEXITCODE -ne 0){throw 'Locked portable package download failed.'}
    $provisionText=@(& (Join-Path $bin 'Provision-PortablePlaywrightCore.ps1') -TarballPath $archive -ToolRoot $toolRoot -NodePath 'C:\dev\node-v24.17.0-win-x64\node.exe' -EdgePath 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' -Execute) -join "`n"
    $provision=$provisionText | ConvertFrom-Json
    if($provision.status -cne 'PROVISIONED'){throw 'Portable package did not produce its verified receipt.'}
    $reportText=@(& (Join-Path $bin 'Get-Beta5BrowserPrerequisites.ps1') -RunIdentityPath (Join-Path $missionRoot 'run-identity.json') -TesterPrepRoot $bin) -join "`n"
    $report=$reportText | ConvertFrom-Json
    $coreJson=Join-Path $provision.prerequisites.playwright_core_path 'package.json'
    $null=Assert-Beta5ChildPath $toolRoot $coreJson
    $corePackage=Get-Content -LiteralPath $coreJson -Raw | ConvertFrom-Json
    if($corePackage.name -cne 'playwright-core' -or $corePackage.version -cne '1.59.1'){throw 'Extracted package identity differs.'}
    $report.packages += [pscustomobject]@{kind='playwright-core';path=$coreJson;exists=$true;package_name=$corePackage.name;package_version=$corePackage.version}
    $report | Add-Member -NotePropertyName portable_dependency_provisioning -NotePropertyValue $provision
    $report | Add-Member -NotePropertyName diagnostic_status -NotePropertyValue 'COLLECTED'
    $report | Add-Member -NotePropertyName qualification -NotePropertyValue 'Prerequisite inventory is read-only; the enclosing directive additionally downloaded/verified/extracted one portable test module. No Node/browser/npm execution, global installation, product modification, or station API call.'
} catch {
    $failure=$_
    $scriptName=if($_.InvocationInfo.ScriptName){Split-Path -Leaf $_.InvocationInfo.ScriptName}else{$null}
    $report=[pscustomobject]@{schema='civiccast-native-beta5-browser-tools-failure-v1';mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHost;diagnostic_status='FAILED';observed_utc=[datetimeoffset]::UtcNow.ToString('o');error_type=$_.Exception.GetType().FullName;script_basename=$scriptName;line=[int]$_.InvocationInfo.ScriptLineNumber;browser_launched=$false;global_install=$false;token_read=$false}
}
$report | Add-Member -NotePropertyName support_files -NotePropertyValue $support
$receipt=Join-Path $outputRoot 'browser-prerequisites-tools-r1.json'
Write-Beta5JsonAtomic $report $receipt
$returnRepo=Join-Path $outputRoot 'return-repo'
$branch='tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$null=Invoke-Beta5Git $outputRoot @('clone','--quiet','--depth','1','--single-branch','--branch',$branch,'https://github.com/scottconverse/civiccast-native.git',$returnRepo)
$null=Invoke-Beta5Git $returnRepo @('config','user.name',"soak-tester-$expectedHost")
$null=Invoke-Beta5Git $returnRepo @('config','user.email','soak-tester@civiccast.invalid')
$relativeReceipt="soak/beta5/$mission/browser-prerequisites-tools-r1.json"
$destinationReceipt=Join-Path $returnRepo $relativeReceipt
if(Test-Path -LiteralPath $destinationReceipt){throw 'Portable tool receipt already published; preserve it.'}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationReceipt) | Out-Null
Copy-Item -LiteralPath $receipt -Destination $destinationReceipt
$null=Invoke-Beta5Git $returnRepo @('add','--',$relativeReceipt)
$null=Invoke-Beta5Git $returnRepo @('commit','--quiet','-s','-m',"test: prepare portable browser proof library $mission",'--',$relativeReceipt)
try{$null=Invoke-Beta5Git $returnRepo @('push','--quiet','origin',$branch)}catch{$null=Invoke-Beta5Git $returnRepo @('pull','--rebase','origin',$branch);$null=Invoke-Beta5Git $returnRepo @('push','--quiet','origin',$branch)}
if($null -ne $failure){throw $failure}
Write-Host 'Locked portable browser test library prepared and inventoried; no browser was launched.'
