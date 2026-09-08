# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# Provision only the reviewed portable playwright-core module; never run npm. #>
[CmdletBinding()]
param(
    [string] $TarballPath,
    [string] $ToolRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630\tools\browser-proof-r1',
    [string] $NodePath = 'C:\dev\node-v24.17.0-win-x64\node.exe',
    [string] $EdgePath = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    [switch] $Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $TarballPath) { $TarballPath = Join-Path $PSScriptRoot 'playwright-core-1.59.1.tgz' }

$script:CoreVersion = '1.59.1'
$script:CoreSha256 = '22304c3d9106ed8372ff58656f645a93bc3a2b17df8567f1413079a730d8d6fa'
$script:CoreIntegrity = 'HBV/RJg81z5BiiZ9yPzIiClYV/QMsDCKUyogwH9p3MCP6IYjUFu/MActgYAvK0oWyV9NlwM3GLBjADyWgydVyg=='

function Get-PortableCoreHashInfo {
    param([Parameter(Mandatory)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Portable playwright-core tarball is absent.' }
    $bytes = [IO.File]::ReadAllBytes($Path)
    $sha512 = [Convert]::ToBase64String(([Security.Cryptography.SHA512]::Create().ComputeHash($bytes)))
    [pscustomobject]@{
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        integrity = $sha512
        size_bytes = $bytes.Length
    }
}

function Assert-PortablePlainPath {
    param([Parameter(Mandatory)][string] $Path)
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Portable browser path crosses a reparse point.'
            }
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

function Assert-PortableChildPath {
    param([Parameter(Mandatory)][string] $BasePath, [Parameter(Mandatory)][string] $CandidatePath)
    $base = Assert-PortablePlainPath $BasePath
    $candidate = Assert-PortablePlainPath $CandidatePath
    $prefix = $base.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Portable browser path is outside its exact approved parent.'
    }
    return $candidate
}

function Assert-PortableCoreArchive {
    param([Parameter(Mandatory)][string] $Path)
    $hashes = Get-PortableCoreHashInfo $Path
    if ($hashes.sha256 -cne $script:CoreSha256 -or $hashes.integrity -cne $script:CoreIntegrity) {
        throw 'Portable playwright-core tarball does not match the reviewed lock integrity and SHA-256.'
    }
    $members = @(& tar.exe -tzf $Path)
    if ($LASTEXITCODE -ne 0 -or $members.Count -eq 0) { throw 'Portable playwright-core archive cannot be listed.' }
    $unsafe = @($members | Where-Object { $_ -match '(^|/)\.\.(/|$)' -or $_ -match '^/' -or $_ -match '^[A-Za-z]:' })
    if ($unsafe.Count -gt 0) { throw 'Portable playwright-core archive contains an unsafe member path.' }
    $verbose = @(& tar.exe -tvzf $Path)
    if ($LASTEXITCODE -ne 0 -or @($verbose | Where-Object { $_ -match '^[lh]' }).Count -gt 0) {
        throw 'Portable playwright-core archive contains links or cannot be safely inspected.'
    }
    $package = (@(& tar.exe -xOzf $Path package/package.json) -join "`n") | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $package.name -cne 'playwright-core' -or $package.version -cne $script:CoreVersion) {
        throw 'Portable playwright-core package metadata does not match the reviewed version.'
    }
    foreach ($field in @('dependencies', 'optionalDependencies', 'scripts')) {
        if ($package.PSObject.Properties[$field] -and @($package.$field.PSObject.Properties).Count -gt 0) {
            throw 'Portable playwright-core package is not self-contained.'
        }
    }
    return [pscustomobject]@{ hashes = $hashes; member_count = $members.Count; package = $package }
}

function Get-PortableBrowserPrerequisites {
    param(
        [Parameter(Mandatory)][string] $NodePath,
        [Parameter(Mandatory)][string] $EdgePath,
        [Parameter(Mandatory)][string] $CorePath
    )
    foreach ($path in @($NodePath, $EdgePath, $CorePath)) {
        if (-not (Test-Path -LiteralPath $path)) { throw 'Required browser-proof prerequisite is absent.' }
    }
    [ordered]@{
        node_path = [IO.Path]::GetFullPath($NodePath)
        edge_path = [IO.Path]::GetFullPath($EdgePath)
        playwright_core_path = [IO.Path]::GetFullPath($CorePath)
        global_npm_install = $false
        npm_scripts_run = $false
        browser_downloaded = $false
    }
}

if ($env:PORTABLE_PLAYWRIGHT_CORE_LIBRARY -eq '1') { return }

if (-not $Execute) {
    [ordered]@{
        dry_run = $true; execute = $false; package = "playwright-core@$script:CoreVersion"
        source_tarball = $TarballPath; destination_tool_root = $ToolRoot
        actions = 'Verify lock-bound SHA-256/SHA-512, inspect archive paths/links, extract only to a fresh mission tools directory, and inventory existing Node and Edge.'
        prohibited = 'npm install, npm scripts, global installation, browser download, tester/browser/API/service/Git execution.'
    } | ConvertTo-Json
    return
}

$inspection = Assert-PortableCoreArchive $TarballPath
$toolRootFull = Assert-PortablePlainPath $ToolRoot
if (Test-Path -LiteralPath $toolRootFull) { throw 'Portable browser tools directory already exists; refusing overwrite.' }
$toolParent = Assert-PortablePlainPath (Split-Path -Parent $toolRootFull)
$staging = Assert-PortablePlainPath (Join-Path $toolParent ("$((Split-Path -Leaf $toolRootFull).ToString()).staging.$([guid]::NewGuid().ToString('N'))"))
if ((Split-Path -Parent $staging) -cne $toolParent) { throw 'Portable browser staging is not a sibling of the approved tools directory.' }
try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    & tar.exe -xzf $TarballPath -C $staging
    if ($LASTEXITCODE -ne 0) { throw 'Portable playwright-core extraction failed.' }
    $extracted = Assert-PortableChildPath -BasePath $staging -CandidatePath (Join-Path $staging 'package')
    if (-not (Test-Path -LiteralPath $extracted -PathType Container)) { throw 'Portable playwright-core archive has no package root.' }
    New-Item -ItemType Directory -Path (Assert-PortableChildPath -BasePath $toolRootFull -CandidatePath (Join-Path $toolRootFull 'node_modules')) -Force | Out-Null
    $corePath = Assert-PortableChildPath -BasePath $toolRootFull -CandidatePath (Join-Path $toolRootFull 'node_modules\playwright-core')
    Move-Item -LiteralPath $extracted -Destination $corePath
    $inventory = Get-PortableBrowserPrerequisites -NodePath $NodePath -EdgePath $EdgePath -CorePath $corePath
    [ordered]@{
        schema = 'civiccast-browser-proof-portable-core-v1'; status = 'PROVISIONED'
        package = "playwright-core@$script:CoreVersion"; sha256 = $inspection.hashes.sha256
        integrity = $inspection.hashes.integrity; archive_member_count = $inspection.member_count
        prerequisites = $inventory
    } | ConvertTo-Json -Depth 5
} finally {
    # A nonempty stage is evidence of a failed or unexpected extraction. Preserve it.
    if ((Test-Path -LiteralPath $staging -PathType Container) -and
        (@(Get-ChildItem -LiteralPath $staging -Force).Count -eq 0)) {
        Remove-Item -LiteralPath $staging -Force -ErrorAction SilentlyContinue
    }
}
