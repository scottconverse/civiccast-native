# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([Parameter(Mandatory)][string] $TarballPath, [Parameter(Mandatory)][string] $SignedSourceLockPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$previous = $env:PORTABLE_PLAYWRIGHT_CORE_LIBRARY
$env:PORTABLE_PLAYWRIGHT_CORE_LIBRARY = '1'
try { . (Join-Path $PSScriptRoot 'Provision-PortablePlaywrightCore.ps1') -TarballPath $TarballPath }
finally {
    if ($null -eq $previous) { Remove-Item Env:PORTABLE_PLAYWRIGHT_CORE_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:PORTABLE_PLAYWRIGHT_CORE_LIBRARY = $previous }
}

function Assert-True { param([string] $Name, [bool] $Value) if (-not $Value) { throw "Assertion failed: $Name" } }
$tarball = $TarballPath
$inspection = Assert-PortableCoreArchive $tarball
Assert-True 'lock-pinned SHA-256 is exact' ($inspection.hashes.sha256 -ceq $script:CoreSha256)
Assert-True 'lock-pinned SHA-512 integrity is exact' ($inspection.hashes.integrity -ceq $script:CoreIntegrity)
Assert-True 'package has no dependencies' (-not $inspection.package.PSObject.Properties['dependencies'])
$publicLock = $SignedSourceLockPath
$publicLockText = Get-Content -LiteralPath $publicLock -Raw
Assert-True 'signed be public portal lock pins exact integrity' ($publicLockText -match 'playwright-core-1\.59\.1\.tgz' -and $publicLockText -match [regex]::Escape($script:CoreIntegrity))

$temp = Join-Path ([IO.Path]::GetTempPath()) ("portable-core-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $node = Join-Path $temp 'node.exe'; $edge = Join-Path $temp 'msedge.exe'; $core = Join-Path $temp 'node_modules\playwright-core'
    Set-Content -LiteralPath $node -Value 'test' -Encoding ascii
    Set-Content -LiteralPath $edge -Value 'test' -Encoding ascii
    New-Item -ItemType Directory -Path $core -Force | Out-Null
    $inventory = Get-PortableBrowserPrerequisites -NodePath $node -EdgePath $edge -CorePath $core
    Assert-True 'portable core absolute path is reported' ([IO.Path]::GetFullPath($inventory.playwright_core_path) -ceq $inventory.playwright_core_path)
    Assert-True 'no npm or browser download is claimed' (-not $inventory.global_npm_install -and -not $inventory.npm_scripts_run -and -not $inventory.browser_downloaded)
    $provisionedRoot = Join-Path $temp 'provisioned'
    $result = & (Join-Path $PSScriptRoot 'Provision-PortablePlaywrightCore.ps1') -TarballPath $tarball -ToolRoot $provisionedRoot -NodePath $node -EdgePath $edge -Execute | ConvertFrom-Json
    Assert-True 'portable extraction reports provisioned' ($result.status -eq 'PROVISIONED')
    Assert-True 'portable extraction reports exact core directory' ($result.prerequisites.playwright_core_path -ceq (Join-Path $provisionedRoot 'node_modules\playwright-core'))
    Assert-True 'portable extraction did not invoke npm' (-not $result.prerequisites.npm_scripts_run -and -not $result.prerequisites.global_npm_install)
    Write-Host 'PASS: portable playwright-core archive and prerequisite inventory contract.'
} finally {
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $tempFull = [IO.Path]::GetFullPath($temp)
    $safeLeaf = Split-Path -Leaf $tempFull
    if ((Split-Path -Parent $tempFull).TrimEnd('\') -ceq $tempRoot -and
        $safeLeaf -match '^portable-core-[0-9a-f]{32}$' -and
        (Test-Path -LiteralPath $tempFull) -and
        -not ((Get-Item -LiteralPath $tempFull -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        Remove-Item -LiteralPath $tempFull -Recurse -Force
    }
}
