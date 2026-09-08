# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Read-only prerequisite discovery. No browser, installer or station API action.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mission = 'beta5-sep8-be1260bd0630'
$candidate = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$expectedHostname = 'DESKTOP-VBMA6O5'
$missionRoot = "C:\CivicCastSoak\missions\$mission"
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5'))
if ($DryRun) {
    [ordered]@{mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHostname;dry_run=$true;browser_launched=$false;install_attempted=$false;token_read=$false;operation='Read known existing Node/browser/package paths and return a bounded report in a fresh R2 directory.'} | ConvertTo-Json
    return
}
if ($env:COMPUTERNAME -cne $expectedHostname) { throw 'Browser inventory targets the dedicated tester only.' }
. (Join-Path $packageRoot 'Beta5Tester.Common.ps1')
$inventoryRoot = Join-Path $missionRoot 'browser-prerequisites-r2'
$null = Assert-Beta5ChildPath $missionRoot $inventoryRoot
if (Test-Path -LiteralPath $inventoryRoot) { throw 'R2 inventory already exists; preserve it.' }
$bin = Join-Path $inventoryRoot 'bin'
New-Item -ItemType Directory -Path $bin | Out-Null
$support = @()
foreach ($relative in @('Beta5Tester.Common.ps1','caption-proof\Get-Beta5BrowserPrerequisites.ps1')) {
    $source = Join-Path $packageRoot $relative
    $destination = Join-Path $bin ([IO.Path]::GetFileName($relative))
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    Copy-Item -LiteralPath $source -Destination $destination
    if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) { throw 'Inventory copy differs from its reviewed source.' }
    $support += [pscustomobject]@{name=[IO.Path]::GetFileName($relative);sha256=$hash}
}
. (Join-Path $bin 'Beta5Tester.Common.ps1')
$failure = $null
try {
    $reportText = @(& (Join-Path $bin 'Get-Beta5BrowserPrerequisites.ps1') -RunIdentityPath (Join-Path $missionRoot 'run-identity.json') -TesterPrepRoot $bin) -join "`n"
    $report = $reportText | ConvertFrom-Json
    if ($report.hostname -cne $expectedHostname -or $report.candidate_source_sha -cne $candidate -or $report.mission -cne $mission) { throw 'Browser inventory identity differs.' }
    $report | Add-Member -NotePropertyName diagnostic_status -NotePropertyValue 'COLLECTED'
} catch {
    $failure = $_
    $sourceName = if ($_.InvocationInfo.ScriptName) { Split-Path -Leaf $_.InvocationInfo.ScriptName } else { $null }
    $report = [pscustomobject]@{schema='civiccast-native-beta5-browser-inventory-failure-v1';mission=$mission;candidate_source_sha=$candidate;hostname=$expectedHostname;diagnostic_status='FAILED';error_type=$_.Exception.GetType().FullName;script_basename=$sourceName;line=[int]$_.InvocationInfo.ScriptLineNumber;observed_utc=[datetimeoffset]::UtcNow.ToString('o');browser_launched=$false;install_attempted=$false;token_read=$false}
}
$report | Add-Member -NotePropertyName support_files -NotePropertyValue $support
$localReport = Join-Path $inventoryRoot 'browser-prerequisites.json'
Write-Beta5JsonAtomic $report $localReport
$returnRepo = Join-Path $inventoryRoot 'return-repo'
$returnBranch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
# The reviewed common helper checks exit codes while tolerating Git's normal
# progress stderr in Windows PowerShell. Never collect or print credentials.
$null = Invoke-Beta5Git -Repository $inventoryRoot -Arguments @('clone','--quiet','--depth','1','--single-branch','--branch',$returnBranch,'https://github.com/scottconverse/civiccast-native.git',$returnRepo)
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('config','user.name',"soak-tester-$expectedHostname")
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('config','user.email','soak-tester@civiccast.invalid')
$relativeReport = "soak/beta5/$mission/browser-prerequisites-r2.json"
$destinationReport = Join-Path $returnRepo $relativeReport
if (Test-Path -LiteralPath $destinationReport) { throw 'R2 report already published; preserve it.' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinationReport) | Out-Null
Copy-Item -LiteralPath $localReport -Destination $destinationReport
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('add','--',$relativeReport)
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('commit','--quiet','-s','-m',"test: beta5 browser prerequisites R2 $mission",'--',$relativeReport)
try { $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('push','--quiet','origin',$returnBranch) }
catch {
    $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('pull','--rebase','origin',$returnBranch)
    $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('push','--quiet','origin',$returnBranch)
}
if ($null -ne $failure) { throw $failure }
Write-Host 'Read-only browser prerequisite report returned. No browser or installer was launched.'
