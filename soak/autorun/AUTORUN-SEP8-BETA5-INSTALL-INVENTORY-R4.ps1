# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Diagnostic dispatch only. No installer, service, station API, or task changes.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$mission = 'beta5-sep8-be1260bd0630'
$candidate = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$expectedHostname = 'DESKTOP-VBMA6O5'
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5\install-inventory'))
$sourceFiles = @('BETA5-TESTER-INSTALL-INVENTORY-DRAFT.ps1', 'BETA5-INSTALL-INVENTORY-ADAPTERS.ps1')
if ($DryRun) {
    [ordered]@{
        mission = $mission; candidate_source_sha = $candidate; expected_hostname = $expectedHostname
        dry_run = $true; process_execution = $false; install_or_service_changes = $false
        raw_log_exported = $false; token_read = $false
        reads = 'Mission identity allowlist, exact install/soak markers, selected process names and metadata, current service metadata, bounded kit inventory, and fixed boolean phrases from up to three original autorun logs.'
        process_qualification = 'Generic helper names may include unrelated processes. Names/PIDs/parents/times/CPU do not establish association with the candidate install; command lines are excluded.'
        writes = 'Fresh diagnostic report and separate Git return checkout only; no changes to the original mission bin or installed station.'
        publication = 'One JSON diagnostic to the established tester return branch; not release acceptance.'
    } | ConvertTo-Json
    return
}
if ("$env:COMPUTERNAME" -cne $expectedHostname) { throw 'This diagnostic targets the dedicated tester only.' }
foreach ($file in $sourceFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $file) -PathType Leaf)) { throw 'Diagnostic support file is absent.' }
}
. (Join-Path $packageRoot 'BETA5-INSTALL-INVENTORY-ADAPTERS.ps1')
$diagnosticRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630\install-inventory-r4'
$null = Assert-Beta5InventoryPlainPath $diagnosticRoot
if (Test-Path -LiteralPath $diagnosticRoot) { throw 'Diagnostic state already exists; preserve and reconcile it rather than rerun.' }
$binRoot = Join-Path $diagnosticRoot 'bin'
New-Item -ItemType Directory -Path $binRoot | Out-Null
$sources = @()
foreach ($file in $sourceFiles) {
    $sourcePath = Assert-Beta5InventoryPlainPath (Join-Path $packageRoot $file)
    $destination = Join-Path $binRoot $file
    $before = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    Copy-Item -LiteralPath $sourcePath -Destination $destination
    $after = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
    if ($before -cne $after) { throw 'Diagnostic support copy failed its hash check.' }
    $sources += [pscustomobject]@{ name = $file; sha256 = $after.ToLowerInvariant() }
}
$previousLibrary = $env:BETA5_INVENTORY_DRAFT_LIBRARY
try {
    $env:BETA5_INVENTORY_DRAFT_LIBRARY = '1'
    . (Join-Path $binRoot 'BETA5-TESTER-INSTALL-INVENTORY-DRAFT.ps1')
} finally {
    if ($null -eq $previousLibrary) { Remove-Item Env:BETA5_INVENTORY_DRAFT_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:BETA5_INVENTORY_DRAFT_LIBRARY = $previousLibrary }
}
. (Join-Path $binRoot 'BETA5-INSTALL-INVENTORY-ADAPTERS.ps1')
try {
    $report = Get-Beta5LiveInstallInventory -Root 'C:\CivicCastSoak'
    $report | Add-Member -NotePropertyName diagnostic_status -NotePropertyValue 'COLLECTED'
} catch {
    # Even a partial diagnostic failure must return an explicit receipt. Exception
    # text is deliberately excluded because system errors may embed sensitive data.
    $report = [pscustomobject]@{
        schema = 'civiccast-native-beta5-install-inventory-failure-v1'
        mission = $mission; candidate_source_sha = $candidate; hostname = $expectedHostname
        diagnostic_status = 'FAILED'; error_type = $_.Exception.GetType().FullName
        collected_utc = (Get-Date).ToUniversalTime().ToString('o')
    }
}
$report | Add-Member -NotePropertyName support_files -NotePropertyValue $sources
$localReport = Join-Path $diagnosticRoot 'install-inventory-r4.json'
$report | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $localReport -Encoding utf8
$returnRepo = Join-Path $diagnosticRoot 'return-repo'
$returnBranch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
function Invoke-InventoryGit {
    param([string[]] $Arguments)
    & git @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Diagnostic Git operation failed; local report is preserved.' }
}
Invoke-InventoryGit @('--no-pager', 'clone', '--quiet', '--depth', '1', '--single-branch', '--branch', $returnBranch, 'https://github.com/scottconverse/civiccast-native.git', $returnRepo)
Invoke-InventoryGit @('-C', $returnRepo, 'config', 'user.name', "soak-tester-$expectedHostname")
Invoke-InventoryGit @('-C', $returnRepo, 'config', 'user.email', 'soak-tester@civiccast.invalid')
$relative = "soak/beta5/$mission/install-inventory-r4.json"
$destinationReport = Join-Path $returnRepo $relative
if (Test-Path -LiteralPath $destinationReport) { throw 'Diagnostic report already published; refusing to overwrite.' }
New-Item -ItemType Directory -Path (Split-Path -Parent $destinationReport) -Force | Out-Null
Copy-Item -LiteralPath $localReport -Destination $destinationReport
Invoke-InventoryGit @('-C', $returnRepo, 'add', '--', $relative)
Invoke-InventoryGit @('-C', $returnRepo, 'commit', '--quiet', '-s', '-m', "test: diagnose beta5 install progress $mission", '--', $relative)
try { Invoke-InventoryGit @('-C', $returnRepo, 'push', '--quiet', 'origin', $returnBranch) }
catch {
    Invoke-InventoryGit @('-C', $returnRepo, 'pull', '--rebase', 'origin', $returnBranch)
    Invoke-InventoryGit @('-C', $returnRepo, 'push', '--quiet', 'origin', $returnBranch)
}
Write-Host "Install inventory returned: $($report.diagnostic_status). No installer, station API, service, or task change."
