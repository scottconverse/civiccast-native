# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string] $RunIdentityPath,
    [string] $TesterPrepRoot = (Join-Path $PSScriptRoot '..'),
    [ValidateSet('DESKTOP-VBMA6O5')][string] $ExpectedHostname = 'DESKTOP-VBMA6O5'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$commonPath = Join-Path $TesterPrepRoot 'Beta5Tester.Common.ps1'
if (-not (Test-Path -LiteralPath $commonPath -PathType Leaf)) { throw "Tester common helper is absent: $commonPath" }
. $commonPath
if ("$env:COMPUTERNAME" -cne $ExpectedHostname) { throw "Browser inventory targets '$ExpectedHostname', not '$env:COMPUTERNAME'." }
$identity = Get-Beta5Identity $RunIdentityPath
if ("$($identity.expected_hostname)" -cne $ExpectedHostname) { throw 'Run identity does not target the approved tester hostname.' }

function Get-KnownExecutableRecord {
    param([Parameter(Mandatory)][string] $Kind, [Parameter(Mandatory)][string] $Path)
    $exists = Test-Path -LiteralPath $Path -PathType Leaf
    $version = $null
    $productVersion = $null
    if ($exists) {
        $info = (Get-Item -LiteralPath $Path).VersionInfo
        $version = $info.FileVersion
        $productVersion = $info.ProductVersion
    }
    return [pscustomobject][ordered]@{ kind = $Kind; path = $Path; exists = $exists; file_version = $version; product_version = $productVersion }
}

function Get-KnownPackageRecord {
    param([Parameter(Mandatory)][string] $Kind, [Parameter(Mandatory)][string] $Path)
    $exists = Test-Path -LiteralPath $Path -PathType Leaf
    $version = $null
    $name = $null
    if ($exists) {
        $package = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if ($null -ne $package.PSObject.Properties['version']) { $version = "$($package.version)" }
        if ($null -ne $package.PSObject.Properties['name']) { $name = "$($package.name)" }
    }
    return [pscustomobject][ordered]@{ kind = $Kind; path = $Path; exists = $exists; package_name = $name; package_version = $version }
}

$portalRoot = Join-Path $identity.return_repo_path 'civiccast\apps\portal-public'
$null = Assert-Beta5ChildPath -BasePath $identity.return_repo_path -CandidatePath $portalRoot
$nodeRoots = @('C:\Program Files\nodejs', 'C:\Program Files (x86)\nodejs')
$executables = @()
$packages = @()
foreach ($root in $nodeRoots) {
    $executables += Get-KnownExecutableRecord 'node' (Join-Path $root 'node.exe')
    $executables += Get-KnownExecutableRecord 'npm-command' (Join-Path $root 'npm.cmd')
    $packages += Get-KnownPackageRecord 'npm-package' (Join-Path $root 'node_modules\npm\package.json')
}
$executables += Get-KnownExecutableRecord 'edge' 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$executables += Get-KnownExecutableRecord 'edge' 'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
$executables += Get-KnownExecutableRecord 'chrome' 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$executables += Get-KnownExecutableRecord 'chrome' 'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'
$packages += Get-KnownPackageRecord 'playwright-test' (Join-Path $portalRoot 'node_modules\@playwright\test\package.json')
$packages += Get-KnownPackageRecord 'playwright-core' (Join-Path $portalRoot 'node_modules\playwright-core\package.json')
$pathDiscovery = @()
foreach ($name in @('node.exe', 'npm.cmd')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue | Where-Object { $_.CommandType -in @('Application', 'ExternalScript') } | Select-Object -First 1
    $pathDiscovery += [pscustomobject][ordered]@{
        name = $name
        found = ($null -ne $command)
        path = $(if ($null -ne $command) { $command.Source } else { $null })
        command_type = $(if ($null -ne $command) { "$($command.CommandType)" } else { $null })
        process_executed = $false
    }
}

$result = [pscustomobject][ordered]@{
    schema = 'civiccast-native-beta5-browser-prerequisites-v1'
    observed_utc = (Get-Date).ToUniversalTime().ToString('o')
    hostname = "$env:COMPUTERNAME"
    mission = "$($identity.mission)"
    candidate_source_sha = "$($identity.candidate_source_sha)"
    portal_source_root = $portalRoot
    known_path_inventory_only = $true
    process_execution = $false
    browser_launched = $false
    install_attempted = $false
    executables = $executables
    packages = $packages
    path_command_discovery = $pathDiscovery
    playwright_config = [pscustomobject][ordered]@{
        path = (Join-Path $portalRoot 'playwright.config.ts')
        exists = (Test-Path -LiteralPath (Join-Path $portalRoot 'playwright.config.ts') -PathType Leaf)
    }
    existing_caption_spec = [pscustomobject][ordered]@{
        path = (Join-Path $portalRoot 'e2e\a11y.spec.ts')
        exists = (Test-Path -LiteralPath (Join-Path $portalRoot 'e2e\a11y.spec.ts') -PathType Leaf)
        qualification = 'Existing test uses mocked HLS and is not installed resident-playback proof.'
    }
    readiness = [pscustomobject][ordered]@{
        node_present = (@($executables | Where-Object { $_.kind -eq 'node' -and $_.exists }).Count -gt 0 -or @($pathDiscovery | Where-Object { $_.name -eq 'node.exe' -and $_.found }).Count -gt 0)
        npm_present = (@($executables | Where-Object { $_.kind -eq 'npm-command' -and $_.exists }).Count -gt 0 -or @($pathDiscovery | Where-Object { $_.name -eq 'npm.cmd' -and $_.found }).Count -gt 0)
        edge_or_chrome_present = (@($executables | Where-Object { $_.kind -in @('edge', 'chrome') -and $_.exists }).Count -gt 0)
        playwright_test_package_present = (@($packages | Where-Object { $_.kind -eq 'playwright-test' -and $_.exists }).Count -eq 1)
        resident_playback_proven = $false
    }
}
$result | ConvertTo-Json -Depth 12
