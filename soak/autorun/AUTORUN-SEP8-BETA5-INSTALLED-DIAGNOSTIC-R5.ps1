# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Read-only tester diagnosis. Only its own report/helper-copy/Git-return files are written.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mission = 'beta5-sep8-be1260bd0630'
$candidate = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$expectedHost = 'DESKTOP-VBMA6O5'
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5'))
$missionRoot = "C:\CivicCastSoak\missions\$mission"
$outputRoot = Join-Path $missionRoot 'installed-diagnostic-r5'
if ($DryRun) {
    [ordered]@{mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHost;dry_run=$true;output=$outputRoot;action='Read installed identity receipts, two runtime hashes and six bounded worker logs; return redacted diagnostic through Git.';station_changes=$false;token_read=$false;install_retry=$false}|ConvertTo-Json
    return
}
if ($env:COMPUTERNAME -ine $expectedHost) { throw 'R5 targets the dedicated tester only.' }
. (Join-Path $sourceRoot 'Beta5Tester.Common.ps1')
$identity = Get-Beta5Identity (Join-Path $missionRoot 'run-identity.json')
if ($identity.mission -cne $mission -or $identity.candidate_source_sha -cne $candidate) { throw 'R5 mission/source mismatch.' }
$previousLibrary = $env:BETA5_R5_RECEIPT_LIBRARY
try {
    $env:BETA5_R5_RECEIPT_LIBRARY = '1'
    . (Join-Path $sourceRoot 'r5-diagnostic\BETA5-R5-RECEIPT-DRAFT.ps1')
} finally {
    if ($null -eq $previousLibrary) { Remove-Item Env:BETA5_R5_RECEIPT_LIBRARY -ErrorAction SilentlyContinue } else { $env:BETA5_R5_RECEIPT_LIBRARY = $previousLibrary }
}
$null = Assert-Beta5R5PlainPath $outputRoot $missionRoot
if (Test-Path -LiteralPath $outputRoot) { throw 'R5 state already exists; preserve it instead of replaying.' }
$bin = Join-Path $outputRoot 'bin'
New-Item -ItemType Directory -Path $bin | Out-Null
$support = @()
foreach ($relative in @('Beta5Tester.Common.ps1','r5-diagnostic\BETA5-R5-RECEIPT-DRAFT.ps1')) {
    $source = Join-Path $sourceRoot $relative
    $destination = Join-Path $bin ([IO.Path]::GetFileName($relative))
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    Copy-Item -LiteralPath $source -Destination $destination
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) { throw 'R5 support-copy hash mismatch.' }
    $support += [pscustomobject]@{name=[IO.Path]::GetFileName($relative);sha256=$hash}
}
. (Join-Path $bin 'Beta5Tester.Common.ps1')
$previousLibrary = $env:BETA5_R5_RECEIPT_LIBRARY
try {
    $env:BETA5_R5_RECEIPT_LIBRARY = '1'
    . (Join-Path $bin 'BETA5-R5-RECEIPT-DRAFT.ps1')
} finally {
    if ($null -eq $previousLibrary) { Remove-Item Env:BETA5_R5_RECEIPT_LIBRARY -ErrorAction SilentlyContinue } else { $env:BETA5_R5_RECEIPT_LIBRARY = $previousLibrary }
}
$failure = $null
try {
    $report = Get-Beta5R5ActualReceipt -Root 'C:\CivicCastSoak'
    $report.diagnostic_status = 'COLLECTED'
} catch {
    $failure = $_
    $report = [ordered]@{schema='civiccast-native-beta5-r5-receipt-v1';mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHost;diagnostic_status='FAILED';observed_utc=[DateTime]::UtcNow.ToString('o');error_type=$_.Exception.GetType().FullName;script_basename=$(if($_.InvocationInfo.ScriptName){Split-Path -Leaf $_.InvocationInfo.ScriptName}else{$null});line=[int]$_.InvocationInfo.ScriptLineNumber;raw_contents_exported=$false;token_read=$false}
}
$report.support_files = $support
$receipt = Join-Path $outputRoot 'installed-diagnostic-r5.json'
Write-Beta5JsonAtomic $report $receipt
$returnRepo = Assert-Beta5R5PlainPath (Join-Path $outputRoot 'return-repo') $outputRoot
$branch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$null = Invoke-Beta5Git $outputRoot @('clone','--quiet','--depth','1','--single-branch','--branch',$branch,'https://github.com/scottconverse/civiccast-native.git',$returnRepo)
$null = Invoke-Beta5Git $returnRepo @('config','user.name',"soak-tester-$expectedHost")
$null = Invoke-Beta5Git $returnRepo @('config','user.email','soak-tester@civiccast.invalid')
$relativeReceipt = "soak/beta5/$mission/installed-diagnostic-r5.json"
$destinationReceipt = Join-Path $returnRepo $relativeReceipt
if (Test-Path -LiteralPath $destinationReceipt) { throw 'R5 report is already published; preserve it.' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationReceipt) | Out-Null
Copy-Item -LiteralPath $receipt -Destination $destinationReceipt
$null = Invoke-Beta5Git $returnRepo @('add','--',$relativeReceipt)
$null = Invoke-Beta5Git $returnRepo @('commit','--quiet','-s','-m',"test: collect installed beta5 failure diagnostic R5 $mission",'--',$relativeReceipt)
try { $null = Invoke-Beta5Git $returnRepo @('push','--quiet','origin',$branch) } catch {
    $null = Invoke-Beta5Git $returnRepo @('pull','--rebase','origin',$branch)
    $null = Invoke-Beta5Git $returnRepo @('push','--quiet','origin',$branch)
}
if ($null -ne $failure) { throw $failure }
Write-Host 'R5 installed identity and bounded worker failure signals returned; no station change or retry performed.'
