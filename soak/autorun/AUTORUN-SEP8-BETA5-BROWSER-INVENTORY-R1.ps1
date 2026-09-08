# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Read-only machine inventory; no browser launch, install or station API write.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$expectedHostname = 'DESKTOP-VBMA6O5'
$expectedSha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$mission = 'beta5-sep8-be1260bd0630'
$missionRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630'
$identityPath = Join-Path $missionRoot 'run-identity.json'
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5'))
$commonSource = Join-Path $packageRoot 'Beta5Tester.Common.ps1'
$inventorySource = Join-Path $packageRoot 'caption-proof\Get-Beta5BrowserPrerequisites.ps1'
foreach ($path in @($commonSource, $inventorySource)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Inventory support file is absent: $path" }
}
if ($DryRun) {
    [ordered]@{
        mission = $mission
        expected_hostname = $expectedHostname
        candidate_source_sha = $expectedSha
        operation = 'Known browser/tool paths and mission-stage presence only'
        station_api_calls = $false
        browser_launch = $false
        install_or_service_changes = $false
        token_read = $false
        report_publication = 'One JSON report on the existing tester return branch'
        dry_run = $true
    } | ConvertTo-Json
    return
}
if ("$env:COMPUTERNAME" -cne $expectedHostname) { throw "This inventory targets $expectedHostname only." }
. $commonSource
$identity = Get-Beta5Identity $identityPath
if ("$($identity.mission)" -cne $mission -or "$($identity.candidate_source_sha)" -cne $expectedSha) {
    throw 'Browser inventory identity does not match its exact candidate mission.'
}
$inventoryRoot = Join-Path $missionRoot 'browser-prerequisites-r1'
$null = Assert-Beta5ChildPath -BasePath $missionRoot -CandidatePath $inventoryRoot
if (Test-Path -LiteralPath $inventoryRoot) { throw 'Inventory already has local state; inspect it before using a new directive.' }
$stableBin = Join-Path $inventoryRoot 'bin'
New-Item -ItemType Directory -Path $stableBin | Out-Null
Copy-Item -LiteralPath $commonSource -Destination (Join-Path $stableBin 'Beta5Tester.Common.ps1')
Copy-Item -LiteralPath $inventorySource -Destination (Join-Path $stableBin 'Get-Beta5BrowserPrerequisites.ps1')
$resultText = @(& (Join-Path $stableBin 'Get-Beta5BrowserPrerequisites.ps1') -RunIdentityPath $identityPath -TesterPrepRoot $stableBin) -join "`n"
$result = $resultText | ConvertFrom-Json
if ("$($result.hostname)" -cne $expectedHostname -or "$($result.candidate_source_sha)" -cne $expectedSha) {
    throw 'Browser inventory result has an unexpected host or candidate identity.'
}
$installedReceipt = $null -ne $identity.PSObject.Properties['installed_utc']
$stage = [ordered]@{
    installed_receipt_present = $installedReceipt
    installed_utc = $(if ($installedReceipt) { $identity.installed_utc } else { $null })
    soak_state_present = (Test-Path -LiteralPath (Join-Path $missionRoot 'soak-state.json') -PathType Leaf)
    terminal_verdict_present = (Test-Path -LiteralPath (Join-Path $identity.return_repo_path "soak\beta5\$mission\final-verdict.json") -PathType Leaf)
    qualification = 'Presence inventory only; not a fresh installed-source or soak acceptance verdict'
}
$result | Add-Member -NotePropertyName mission_stage -NotePropertyValue $stage
$localReport = Join-Path $inventoryRoot 'browser-prerequisites.json'
Write-Beta5JsonAtomic -Object $result -Path $localReport

# A separate shallow checkout avoids changing the active sampler's checkout
# and still publishes to the established tester branch. No credential is read.
$returnRepo = Join-Path $inventoryRoot 'return-repo'
$returnBranch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
& git clone --quiet --depth 1 --single-branch --branch $returnBranch 'https://github.com/scottconverse/civiccast-native.git' $returnRepo
if ($LASTEXITCODE -ne 0) { throw 'Could not create the inventory return checkout; local report is preserved.' }
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('config', 'user.name', "soak-tester-$expectedHostname")
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('config', 'user.email', 'soak-tester@civiccast.invalid')
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('pull', '--rebase', 'origin', $returnBranch)
$relativeReport = "soak/beta5/$mission/browser-prerequisites-r1.json"
$returnReport = Assert-Beta5ChildPath -BasePath $returnRepo -CandidatePath (Join-Path $returnRepo $relativeReport)
New-Item -ItemType Directory -Path (Split-Path -Parent $returnReport) -Force | Out-Null
if (Test-Path -LiteralPath $returnReport) { throw 'An inventory report with this identity is already published; local report is preserved.' }
Copy-Item -LiteralPath $localReport -Destination $returnReport
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('add', '--', $relativeReport)
$null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('commit', '--quiet', '-s', '-m', "test: record beta5 browser prerequisites $mission", '--', $relativeReport)
try {
    $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('push', '--quiet', 'origin', $returnBranch)
} catch {
    $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('pull', '--rebase', 'origin', $returnBranch)
    $null = Invoke-Beta5Git -Repository $returnRepo -Arguments @('push', '--quiet', 'origin', $returnBranch)
}
Write-Host "Browser prerequisite inventory published for $mission. No browser, installer or station command was executed."
