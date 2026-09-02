# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<#
.SYNOPSIS
Download and verify CivicCast Windows release-candidate artifacts.

.DESCRIPTION
Fetches the release artifact manifest plus the Windows tester package and/or
clean-Windows proof kit from a GitHub Release. Downloaded assets are verified
against the SHA-256 values in the release manifest before extraction or use.
#>

[CmdletBinding()]
param(
  [string]$Repository = "scottconverse/civiccast-native",
  [string]$Tag = "v1.0.0-beta.2",
  [string]$Version = "1.0.0-beta.2",
  [ValidateSet("ProofKit", "TesterPackage", "All")]
  [string]$AssetSet = "ProofKit",
  [string]$Destination = "C:\CivicCastProof",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host "[CivicCast] $Message"
}

function Get-Release {
  param([string]$Repository, [string]$Tag)

  $uri = "https://api.github.com/repos/$Repository/releases/tags/$Tag"
  try {
    return Invoke-RestMethod -Uri $uri -Headers @{
      "Accept" = "application/vnd.github+json"
      "User-Agent" = "CivicCast-Windows-Release-Downloader"
    }
  } catch {
    throw "Could not load GitHub Release $Repository $Tag. Publish the release/tag/assets first, then retry. GitHub error: $($_.Exception.Message)"
  }
}

function Get-ReleaseAsset {
  param(
    [object]$Release,
    [string]$Name
  )

  $asset = @($Release.assets | Where-Object { $_.name -eq $Name }) | Select-Object -First 1
  if (-not $asset) {
    $available = @($Release.assets | ForEach-Object { $_.name }) -join ", "
    throw "GitHub Release '$($Release.tag_name)' does not contain required asset '$Name'. Available assets: $available"
  }
  return $asset
}

function Save-ReleaseAsset {
  param(
    [object]$Asset,
    [string]$Target
  )

  if ((Test-Path -LiteralPath $Target) -and -not $Force) {
    Write-Step "Using existing $Target"
    return
  }

  Write-Step "Downloading $($Asset.name)"
  Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $Target -Headers @{
    "Accept" = "application/octet-stream"
    "User-Agent" = "CivicCast-Windows-Release-Downloader"
  }
}

function Get-ManifestEntry {
  param(
    [object]$Manifest,
    [string]$FileName
  )

  return @($Manifest.artifacts | Where-Object { $_.filename -eq $FileName }) | Select-Object -First 1
}

function Get-ExpectedSha256 {
  # The release-artifacts manifest is built by one CI job (Linux/portable
  # outputs) and does not cover artifacts a separate job uploads directly
  # (the Windows installer, proof kit, and tester package). When the
  # manifest has no entry for a file, fall back to the GitHub Release
  # asset's own server-computed digest -- the same value a tester's local
  # `Get-FileHash` will produce, and independent of which job built it.
  param(
    [object]$Manifest,
    [object]$Asset,
    [string]$FileName
  )

  $entry = Get-ManifestEntry -Manifest $Manifest -FileName $FileName
  if ($entry) {
    Write-Step "$FileName checksum source: release-artifacts manifest"
    return $entry.sha256
  }
  if ($Asset.digest -and $Asset.digest -match '^sha256:([0-9a-fA-F]{64})$') {
    Write-Step "$FileName checksum source: GitHub Release asset digest (not listed in the release-artifacts manifest, which only covers the Linux build job's outputs)"
    return $Matches[1]
  }
  throw "No checksum available for '$FileName': not in the release manifest and the GitHub Release asset has no usable digest."
}

function Assert-Sha256 {
  param(
    [string]$Path,
    [string]$ExpectedHash
  )

  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
  if ($actual -ne $ExpectedHash.ToLowerInvariant()) {
    throw "SHA-256 mismatch for $Path. Expected $ExpectedHash but got $actual."
  }
  Write-Step "Verified SHA-256 for $Path"
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$manifestName = "civiccast-$Version-release-artifacts-manifest.json"
$proofKitName = "civiccast-$Version-clean-windows-proof-kit.zip"
$testerPackageName = "civiccast-$Version-windows-tester-package.zip"

$release = Get-Release -Repository $Repository -Tag $Tag

$manifestAsset = Get-ReleaseAsset -Release $release -Name $manifestName
$manifestPath = Join-Path $Destination $manifestName
Save-ReleaseAsset -Asset $manifestAsset -Target $manifestPath
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

$requestedAssets = @()
if ($AssetSet -in @("ProofKit", "All")) {
  $requestedAssets += $proofKitName
}
if ($AssetSet -in @("TesterPackage", "All")) {
  $requestedAssets += $testerPackageName
}

foreach ($name in $requestedAssets) {
  $asset = Get-ReleaseAsset -Release $release -Name $name
  $target = Join-Path $Destination $name
  Save-ReleaseAsset -Asset $asset -Target $target
  $expectedHash = Get-ExpectedSha256 -Manifest $manifest -Asset $asset -FileName $name
  Assert-Sha256 -Path $target -ExpectedHash $expectedHash

  if ($name -eq $proofKitName) {
    Write-Step "Extracting clean Windows proof kit to $Destination"
    Expand-Archive -LiteralPath $target -DestinationPath $Destination -Force
  }
}

Write-Step "Done."
Write-Host ""
Write-Host "Downloaded artifacts:"
Get-ChildItem -LiteralPath $Destination -File | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize

if (Test-Path -LiteralPath (Join-Path $Destination "VERIFY-AND-LAUNCH.ps1")) {
  Write-Host ""
  Write-Host "Next command:"
  Write-Host "  powershell -ExecutionPolicy Bypass -File `"$Destination\VERIFY-AND-LAUNCH.ps1`""
}
