# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<#
.SYNOPSIS
Download and verify CivicCast Windows release artifacts.

.DESCRIPTION
Two asset-set families are supported:

  NativeCandidate (default when -Repository is scottconverse/civiccast-native):
    the native beta-candidate release shape published by
    scripts/release/publish_beta_candidate.py -- SHA256SUMS.txt, setup.exe,
    setup.exe.sidecar.json, and (with -IncludePacks) every *.ccpack runtime
    pack. setup.exe and every pack are verified against SHA256SUMS.txt; the
    sidecar is verified by its own sha256 field matching SHA256SUMS.txt's
    setup.exe line. The asset names here are pinned against the publisher's
    constants by tests/policy/test_windows_release_downloader.py so the two
    cannot drift.

  ProofKit / TesterPackage / All (the retired WSL2 rc line's shape): fetch the
    release-artifacts manifest plus the tester package and/or proof kit,
    verified against the manifest's SHA-256 values (falling back to the
    GitHub asset digest for files the manifest does not list).
#>

[CmdletBinding()]
param(
  [string]$Repository = "scottconverse/civiccast-native",
  [string]$Tag = "v1.0.0-beta.3",
  [string]$Version = "1.0.0-beta.3",
  [ValidateSet("", "NativeCandidate", "ProofKit", "TesterPackage", "All")]
  [string]$AssetSet = "",
  [switch]$IncludePacks,
  [string]$Destination = "C:\CivicCastProof",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

# Asset naming contract shared with scripts/release/publish_beta_candidate.py
# (SETUP_ASSET_NAME / SHA256SUMS_ASSET_NAME / SIDECAR_SUFFIX / PACK_SUFFIX).
$NativeSetupName = "setup.exe"
$NativeSumsName = "SHA256SUMS.txt"
$NativeSidecarSuffix = ".sidecar.json"
$NativePackSuffix = ".ccpack"

if ([string]::IsNullOrWhiteSpace($AssetSet)) {
  if ($Repository -eq "scottconverse/civiccast-native") {
    $AssetSet = "NativeCandidate"
  } else {
    $AssetSet = "ProofKit"
  }
}

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

function Read-Sha256Sums {
  # Parse the standard `<hash>  <filename>` lines publish_beta_candidate.py
  # writes into a filename -> lowercase-hash table.
  param([string]$Path)

  $table = @{}
  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
      $table[$Matches[2]] = $Matches[1].ToLowerInvariant()
    }
  }
  if ($table.Count -eq 0) {
    throw "$Path contains no parsable '<sha256>  <filename>' lines."
  }
  return $table
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$release = Get-Release -Repository $Repository -Tag $Tag

if ($AssetSet -eq "NativeCandidate") {
  # 1. SHA256SUMS.txt first: it is the hash authority for everything else.
  #    It is itself verified against the GitHub asset digest when one is
  #    available (there is no higher local authority for it).
  $sumsAsset = Get-ReleaseAsset -Release $release -Name $NativeSumsName
  $sumsPath = Join-Path $Destination $NativeSumsName
  Save-ReleaseAsset -Asset $sumsAsset -Target $sumsPath
  if ($sumsAsset.digest -and $sumsAsset.digest -match '^sha256:([0-9a-fA-F]{64})$') {
    Assert-Sha256 -Path $sumsPath -ExpectedHash $Matches[1]
  } else {
    Write-Step "$NativeSumsName has no GitHub asset digest to check against; trusting the downloaded copy as the hash authority"
  }
  $sums = Read-Sha256Sums -Path $sumsPath

  # 2. setup.exe, verified against SHA256SUMS.txt.
  if (-not $sums.ContainsKey($NativeSetupName)) {
    throw "$NativeSumsName does not list $NativeSetupName; refusing to trust the installer."
  }
  $setupAsset = Get-ReleaseAsset -Release $release -Name $NativeSetupName
  $setupPath = Join-Path $Destination $NativeSetupName
  Save-ReleaseAsset -Asset $setupAsset -Target $setupPath
  Assert-Sha256 -Path $setupPath -ExpectedHash $sums[$NativeSetupName]

  # 3. The sidecar: its sha256 field must equal SHA256SUMS.txt's setup.exe
  #    line (the same bytes described two independent ways).
  $sidecarName = "$NativeSetupName$NativeSidecarSuffix"
  $sidecarAsset = Get-ReleaseAsset -Release $release -Name $sidecarName
  $sidecarPath = Join-Path $Destination $sidecarName
  Save-ReleaseAsset -Asset $sidecarAsset -Target $sidecarPath
  $sidecar = Get-Content -LiteralPath $sidecarPath -Raw | ConvertFrom-Json
  if ([string]$sidecar.sha256 -ne $sums[$NativeSetupName]) {
    throw "$sidecarName sha256 '$($sidecar.sha256)' does not match $NativeSumsName's $NativeSetupName entry '$($sums[$NativeSetupName])'."
  }
  Write-Step "Verified $sidecarName agrees with $NativeSumsName"

  # 4. Optionally every *.ccpack runtime pack, each verified against SHA256SUMS.txt.
  if ($IncludePacks) {
    $packAssets = @($release.assets | Where-Object { $_.name -like "*$NativePackSuffix" })
    if ($packAssets.Count -eq 0) {
      throw "-IncludePacks was requested but release '$Tag' carries no $NativePackSuffix assets."
    }
    foreach ($packAsset in $packAssets) {
      if (-not $sums.ContainsKey($packAsset.name)) {
        throw "$NativeSumsName does not list $($packAsset.name); refusing to trust that pack."
      }
      $packPath = Join-Path $Destination $packAsset.name
      Save-ReleaseAsset -Asset $packAsset -Target $packPath
      Assert-Sha256 -Path $packPath -ExpectedHash $sums[$packAsset.name]
    }
  }
} else {
  $manifestName = "civiccast-$Version-release-artifacts-manifest.json"
  $proofKitName = "civiccast-$Version-clean-windows-proof-kit.zip"
  $testerPackageName = "civiccast-$Version-windows-tester-package.zip"

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
