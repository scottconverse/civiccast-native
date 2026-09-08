# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $NodePath,
    [Parameter(Mandatory)][string] $PlaywrightCorePath,
    [Parameter(Mandatory)][string] $BrowserExecutablePath,
    [Parameter(Mandatory)][string] $AssetId,
    [Parameter(Mandatory)][string] $CandidateSourceSha,
    [Parameter(Mandatory)][string] $EvidenceRoot,
    [ValidateRange(30, 120)][int] $TimeoutSeconds = 90,
    [switch] $Execute
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-ResidentProofPath {
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][string] $Label,
        [switch] $MustBeFile,
        [switch] $MustBeDirectory,
        [switch] $MustNotExist
    )
    if (-not [IO.Path]::IsPathRooted($Path)) { throw "$Label must be an absolute path." }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($MustNotExist -and (Test-Path -LiteralPath $full)) { throw "$Label already exists: $full" }
    if ($MustBeFile -and -not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "$Label is not an existing file: $full" }
    if ($MustBeDirectory -and -not (Test-Path -LiteralPath $full -PathType Container)) { throw "$Label is not an existing directory: $full" }
    $cursor = $(if (Test-Path -LiteralPath $full) { $full } else { Split-Path -Parent $full })
    if (-not $cursor -or -not (Test-Path -LiteralPath $cursor)) { throw "$Label parent directory is absent." }
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "$Label crosses a reparse point: $cursor" }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

if ($AssetId.Length -lt 1 -or $AssetId.Length -gt 128 -or $AssetId -match '[\x00-\x1f\x7f/\\]' -or $AssetId -in @('.', '..')) {
    throw 'AssetId is empty, oversized, or contains a control character/path separator.'
}
if ($CandidateSourceSha -cnotmatch '^[0-9a-f]{40}$') { throw 'CandidateSourceSha must be lowercase 40hex.' }
$node = Assert-ResidentProofPath -Path $NodePath -Label 'Node executable' -MustBeFile
$playwrightCore = Assert-ResidentProofPath -Path $PlaywrightCorePath -Label 'Playwright Core package' -MustBeDirectory
$browser = Assert-ResidentProofPath -Path $BrowserExecutablePath -Label 'Browser executable' -MustBeFile
$evidence = Assert-ResidentProofPath -Path $EvidenceRoot -Label 'Evidence directory' -MustNotExist
if ([IO.Path]::GetFileName($node) -cne 'node.exe') { throw 'NodePath must name node.exe.' }
if ([IO.Path]::GetFileName($browser) -cnotin @('msedge.exe', 'chrome.exe')) { throw 'BrowserExecutablePath must name msedge.exe or chrome.exe.' }
$packageJsonPath = Join-Path $playwrightCore 'package.json'
if (-not (Test-Path -LiteralPath $packageJsonPath -PathType Leaf)) { throw 'Playwright Core package.json is absent.' }
$package = Get-Content -LiteralPath $packageJsonPath -Raw | ConvertFrom-Json
if ($null -eq $package.PSObject.Properties['name'] -or "$($package.name)" -cne 'playwright-core') {
    throw 'PlaywrightCorePath is not an explicit playwright-core package.'
}
$runner = Join-Path $PSScriptRoot 'Run-ResidentBrowserProof.cjs'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw 'Resident browser proof runner is absent.' }

if (-not $Execute) {
    [pscustomobject][ordered]@{
        schema = 'civiccast-native-beta5-resident-browser-proof-plan-v1'
        live_execution = 'NOT_RUN'
        candidate_source_sha = $CandidateSourceSha
        asset_id = $AssetId
        watch_url = "http://127.0.0.1:8000/#/watch/$([uri]::EscapeDataString($AssetId))"
        node_path = $node
        playwright_core_path = $playwrightCore
        playwright_core_version = $(if ($null -ne $package.PSObject.Properties['version']) { "$($package.version)" } else { $null })
        browser_executable_path = $browser
        evidence_root = $evidence
        timeout_seconds = $TimeoutSeconds
        isolated_temporary_profile = $true
        authorization_or_token_input = $false
        station_api_writes = $false
        analytics_post_blocked_before_network = $true
        installation_or_download = $false
        qualification = 'Validation plan only. Parent wrapper must independently bind approved asset, post-soak PASS, service identity, and fresh installed runtime hashes.'
    } | ConvertTo-Json -Depth 8
    return
}

$arguments = @(
    $runner,
    '--playwright-core', $playwrightCore,
    '--browser-executable', $browser,
    '--asset-id', $AssetId,
    '--candidate-source-sha', $CandidateSourceSha,
    '--evidence-dir', $evidence,
    '--timeout-seconds', "$TimeoutSeconds"
)
& $node @arguments
$nodeExit = $LASTEXITCODE
$reportPath = Join-Path $evidence 'resident-browser-proof.json'
if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "Browser proof produced no report (Node exit $nodeExit)." }
$report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
if ("$($report.schema)" -cne 'civiccast-native-beta5-resident-browser-proof-v1' -or "$($report.asset_id)" -cne $AssetId -or "$($report.candidate_source_sha)" -cne $CandidateSourceSha) {
    throw 'Browser proof report identity is invalid.'
}
if ($nodeExit -ne 0 -or "$($report.verdict)" -cne 'PASS') { throw "Resident browser proof failed; inspect $reportPath" }
$report | ConvertTo-Json -Depth 20
