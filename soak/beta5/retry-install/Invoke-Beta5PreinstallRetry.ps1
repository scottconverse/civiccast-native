# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# One-shot dispatcher for the reviewed pre-install retry package. #>
[CmdletBinding()]
param([switch] $Execute)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RetryMission = 'beta5-sep8-be1260bd0630'
$script:RetryCandidate = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$script:RetryHost = 'DESKTOP-VBMA6O5'
$script:RetryBranch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$script:RetryMissionRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630'
$script:RetryFiles = @(
    'Beta5Tester.Common.ps1',
    'ProbeContracts.psm1',
    'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1',
    'AUTORUN-SEP8-BETA5-03-START-SOAK.ps1',
    'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1',
    'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1'
)

function Get-RetrySafeFailure {
    param([Parameter(Mandatory)] $ErrorRecord)
    $line = 0
    if ($null -ne $ErrorRecord.InvocationInfo) {
        $line = [int] $ErrorRecord.InvocationInfo.ScriptLineNumber
    }
    [ordered]@{
        exception_type = $ErrorRecord.Exception.GetType().FullName
        script_basename = if ($ErrorRecord.InvocationInfo -and $ErrorRecord.InvocationInfo.ScriptName) {
            Split-Path -Leaf $ErrorRecord.InvocationInfo.ScriptName
        } else { $null }
        line = $line
    }
}

function Assert-RetryPlainPath {
    param([Parameter(Mandatory)][string] $Path)
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Retry dispatch path crosses a reparse point.'
            }
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

function Get-RetryPackageContract {
    param(
        [Parameter(Mandatory)][string] $SupportRoot,
        [Parameter(Mandatory)][string] $WrapperRoot,
        [Parameter(Mandatory)][string] $ManifestPath
    )
    $support = Assert-RetryPlainPath $SupportRoot
    $wrapperRoot = Assert-RetryPlainPath $WrapperRoot
    $manifestFull = Assert-RetryPlainPath $ManifestPath
    $manifest = Get-Content -LiteralPath $manifestFull -Raw | ConvertFrom-Json
    if ($manifest.schema -cne 'civiccast-native-beta5-retry-package-v1' -or
        $manifest.candidate_source_sha -cne $script:RetryCandidate -or
        @($manifest.files).Count -ne $script:RetryFiles.Count) {
        throw 'Unexpected reviewed retry package manifest.'
    }
    $wrapper = $manifest.PSObject.Properties['wrapper']
    if ($null -eq $wrapper -or $null -eq $wrapper.Value -or
        "$($wrapper.Value.name)" -cne 'BETA5-PREINSTALL-RETRY.ps1' -or
        "$($wrapper.Value.sha256)" -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Retry manifest must bind the reviewed wrapper name and SHA-256.'
    }
    $bindings = @()
    foreach ($name in $script:RetryFiles) {
        $entry = @($manifest.files | Where-Object { $_.name -ceq $name })
        if ($entry.Count -ne 1 -or "$($entry[0].sha256)" -cnotmatch '^[0-9a-f]{64}$') {
            throw 'Retry manifest file binding is missing or invalid.'
        }
        $bindings += [pscustomobject]@{
            name = "$($entry[0].name)"; sha256 = "$($entry[0].sha256)"
            source_path = (Assert-RetryPlainPath (Join-Path $support $entry[0].name))
        }
    }
    $bindings += [pscustomobject]@{
        name = $wrapper.Value.name; sha256 = $wrapper.Value.sha256
        source_path = (Assert-RetryPlainPath (Join-Path $wrapperRoot $wrapper.Value.name))
    }
    foreach ($entry in $bindings) {
        $path = $entry.source_path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Reviewed retry package file is absent.' }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne "$($entry.sha256)") { throw "Retry package hash mismatch: $($entry.name)." }
    }
    return [pscustomobject]@{ SupportRoot = $support; WrapperRoot = $wrapperRoot; ManifestPath = $manifestFull; Manifest = $manifest; Bindings = $bindings }
}

function Copy-RetryPackage {
    param([Parameter(Mandatory)] $Contract, [Parameter(Mandatory)][string] $Destination)
    $destinationFull = Assert-RetryPlainPath $Destination
    New-Item -ItemType Directory -Path $destinationFull | Out-Null
    foreach ($entry in $Contract.Bindings) {
        $source = $entry.source_path
        $target = Join-Path $destinationFull $entry.name
        Copy-Item -LiteralPath $source -Destination $target
        $actual = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -cne "$($entry.sha256)") { throw 'Copied retry package file failed its hash binding.' }
    }
    $manifestTarget = Join-Path $destinationFull 'package-sha256.json'
    Copy-Item -LiteralPath $Contract.ManifestPath -Destination $manifestTarget
    if ((Get-FileHash -LiteralPath $manifestTarget -Algorithm SHA256).Hash.ToLowerInvariant() -cne
        (Get-FileHash -LiteralPath $Contract.ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'Copied retry package manifest failed its hash binding.'
    }
    return $manifestTarget
}

function Write-RetryJson {
    param([Parameter(Mandatory)] $Object, [Parameter(Mandatory)][string] $Path)
    $temporary = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $Object | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $Path
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-RetryGit {
    param(
        [Parameter(Mandatory)][string[]] $Arguments,
        [scriptblock] $Runner = { param([string[]] $GitArguments) & git @GitArguments }
    )
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # PS5 otherwise turns native stderr into a terminating NativeCommandError
        # before the explicit exit-code check can preserve the local receipt.
        $ErrorActionPreference = 'Continue'
        $null = @(& $Runner $Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) { throw 'Retry receipt Git operation failed; local receipt is preserved.' }
}

function Publish-RetryReceipt {
    param([Parameter(Mandatory)][string] $ReceiptPath, [Parameter(Mandatory)][string] $ReceiptRoot)
    $returnRepo = Join-Path $ReceiptRoot 'return-repo'
    Invoke-RetryGit @('--no-pager', 'clone', '--quiet', '--depth', '1', '--single-branch', '--branch', $script:RetryBranch, 'https://github.com/scottconverse/civiccast-native.git', $returnRepo)
    Invoke-RetryGit @('-C', $returnRepo, 'config', 'user.name', "soak-tester-$script:RetryHost")
    Invoke-RetryGit @('-C', $returnRepo, 'config', 'user.email', 'soak-tester@civiccast.invalid')
    $relative = "soak/beta5/$script:RetryMission/install-retry-r1.json"
    $destination = Join-Path $returnRepo $relative
    if (Test-Path -LiteralPath $destination) { throw 'Retry receipt is already published; refusing overwrite.' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $ReceiptPath -Destination $destination
    Invoke-RetryGit @('-C', $returnRepo, 'add', '--', $relative)
    Invoke-RetryGit @('-C', $returnRepo, 'commit', '--quiet', '-s', '-m', "test: beta5 preinstall retry receipt $script:RetryMission", '--', $relative)
    try { Invoke-RetryGit @('-C', $returnRepo, 'push', '--quiet', 'origin', $script:RetryBranch) }
    catch {
        Invoke-RetryGit @('-C', $returnRepo, 'pull', '--rebase', 'origin', $script:RetryBranch)
        Invoke-RetryGit @('-C', $returnRepo, 'push', '--quiet', 'origin', $script:RetryBranch)
    }
}

function Get-RetryJournalSummary {
    param([string] $MissionRoot = $script:RetryMissionRoot)
    $journalPath = Join-Path $MissionRoot 'install-retry-r1\retry-journal.json'
    try {
        if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) {
            return [ordered]@{ present = $false; status = $null; stage = $null; error_type = $null; read_failure = $null }
        }
        $journal = Get-Content -LiteralPath (Assert-RetryPlainPath $journalPath) -Raw | ConvertFrom-Json
        return [ordered]@{
            present = $true
            status = if ($journal.PSObject.Properties['status']) { "$($journal.status)" } else { $null }
            stage = if ($journal.PSObject.Properties['stage']) { "$($journal.stage)" } else { $null }
            error_type = if ($journal.PSObject.Properties['error_type']) { "$($journal.error_type)" } else { $null }
            read_failure = $null
        }
    } catch {
        return [ordered]@{
            present = $null; status = $null; stage = $null; error_type = $null
            read_failure = Get-RetrySafeFailure $_
        }
    }
}

if ($env:BETA5_RETRY_AUTORUN_LIBRARY -eq '1') { return }

$wrapperRoot = Assert-RetryPlainPath $PSScriptRoot
$supportRoot = Assert-RetryPlainPath (Split-Path -Parent $wrapperRoot)
$packageManifest = Join-Path $wrapperRoot 'package-sha256.json'
if (-not $Execute) {
    [ordered]@{
        mission = $script:RetryMission; candidate_source_sha = $script:RetryCandidate
        expected_hostname = $script:RetryHost; dry_run = $true; execute = $false
        writes = 'None. An executed run creates a fresh retry copy/journal receipt and dedicated return checkout only.'
        requires = 'Exact R4 property-missing diagnostic; pristine identity; no installer/task/soak; approved package and wrapper hashes.'
    } | ConvertTo-Json
    return
}
if ("$env:COMPUTERNAME" -cne $script:RetryHost) { throw 'This retry dispatcher targets the dedicated tester only.' }

$receiptRoot = Join-Path $script:RetryMissionRoot 'install-retry-r1-dispatch'
$receiptRoot = Assert-RetryPlainPath $receiptRoot
if (Test-Path -LiteralPath $receiptRoot) { throw 'Retry dispatch receipt state exists; preserve and reconcile it rather than rerun.' }
New-Item -ItemType Directory -Path $receiptRoot | Out-Null
$receiptPath = Join-Path $receiptRoot 'install-retry-r1.json'
$started = (Get-Date).ToUniversalTime().ToString('o')
$failure = $null
$wrapperError = $null
$wrapperReturned = $false
try {
    $contract = Get-RetryPackageContract -SupportRoot $supportRoot -WrapperRoot $wrapperRoot -ManifestPath $packageManifest
    $copiedManifest = Copy-RetryPackage -Contract $contract -Destination (Join-Path $receiptRoot 'bin')
    $copiedWrapper = Join-Path $receiptRoot 'bin\BETA5-PREINSTALL-RETRY.ps1'
    & $copiedWrapper -PackageRoot (Join-Path $receiptRoot 'bin') -PackageManifest $copiedManifest -Execute
    $wrapperReturned = $true
} catch {
    $wrapperError = $_
    $failure = Get-RetrySafeFailure $_
}
$receipt = [ordered]@{
    schema = 'civiccast-native-beta5-preinstall-retry-receipt-v1'
    mission = $script:RetryMission; candidate_source_sha = $script:RetryCandidate
    hostname = $script:RetryHost; started_utc = $started
    completed_utc = (Get-Date).ToUniversalTime().ToString('o')
    status = if ($wrapperReturned) { 'WRAPPER_RETURNED_NONTERMINAL' } else { 'FAILED' }
    wrapper_returned = $wrapperReturned; failure = $failure
    report_kind = 'dispatch receipt only; not an installer, media, or terminal soak verdict'
}
 $receipt.retry_journal = Get-RetryJournalSummary
if ($wrapperReturned) {
    if (-not $receipt.retry_journal.present) { $receipt.status = 'WRAPPER_RETURNED_WITHOUT_JOURNAL' }
}
Write-RetryJson -Object $receipt -Path $receiptPath
$publicationError = $null
try { Publish-RetryReceipt -ReceiptPath $receiptPath -ReceiptRoot $receiptRoot } catch { $publicationError = $_ }
if ($null -ne $wrapperError) { throw $wrapperError }
if ($null -ne $publicationError) { throw $publicationError }
Write-Host 'Retry wrapper returned; receipt published. The two-hour media verdict remains pending.'
