# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# Download, independently verify, and normally upgrade the dedicated tester. #>
[CmdletBinding()]
param([Parameter(Mandatory)][string] $IdentityPath, [switch] $DryRun)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
$id = Get-Beta5Identity $IdentityPath
$kitRoot = Join-Path $id.tester_root ("kit-" + $id.candidate_source_sha)
$null = Assert-Beta5ChildPath -BasePath $id.tester_root -CandidatePath $kitRoot
$manifestPath = Join-Path $kitRoot 'SHA256SUMS.txt'
$installRoot = 'C:\CivicCastHostStore\install'

if ($DryRun) {
    Write-Host "[DRYRUN] verify manifest hash $($id.expected_manifest_sha256), every manifest entry, one signed beta.5 root installer, then normal upgrade to $installRoot"
    return
}

function Invoke-Beta5Download {
    param([Parameter(Mandatory)][string] $Url, [Parameter(Mandatory)][string] $Destination)
    $temporary = "$Destination.$([guid]::NewGuid().ToString('N')).download"
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
        & curl.exe -fsSL --retry 5 --retry-delay 5 --output $temporary $Url
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
            throw "Download failed: $Url"
        }
        Move-Item -LiteralPath $temporary -Destination $Destination -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

New-Item -ItemType Directory -Force -Path $kitRoot | Out-Null
$manifestDownload = "$manifestPath.download"
Invoke-Beta5Download -Url ($id.kit_base_url + 'SHA256SUMS.txt') -Destination $manifestDownload
$manifestHash = (Get-FileHash -LiteralPath $manifestDownload -Algorithm SHA256).Hash.ToLowerInvariant()
if ($manifestHash -ne $id.expected_manifest_sha256) {
    throw "Downloaded manifest hash '$manifestHash' does not equal the independently supplied hash."
}
Move-Item -LiteralPath $manifestDownload -Destination $manifestPath -Force
$entries = @(Read-Beta5Manifest -ManifestPath $manifestPath -KitRoot $kitRoot)
$installers = @($entries | Where-Object { $_.relative_path -notmatch '\\' -and $_.relative_path -match '.+_x64-setup\.exe$' })
if ($installers.Count -ne 1) { throw "Expected exactly one root *_x64-setup.exe in the manifest; found $($installers.Count)." }
$sampleEntries = @($entries | Where-Object { $_.relative_path -match '^samples\\[^\\]+\.(mp4|mov|mxf)$' })
if ($sampleEntries.Count -lt 1) { throw 'Manifest contains no root samples media.' }

foreach ($entry in $entries) {
    $needsDownload = $true
    if (Test-Path -LiteralPath $entry.local_path -PathType Leaf) {
        $existingHash = (Get-FileHash -LiteralPath $entry.local_path -Algorithm SHA256).Hash.ToLowerInvariant()
        $needsDownload = ($existingHash -ne $entry.sha256)
    }
    if ($needsDownload) {
        $urlPath = (($entry.relative_path -split '\\') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/'
        Invoke-Beta5Download -Url ($id.kit_base_url + $urlPath) -Destination $entry.local_path
    }
    $actualHash = (Get-FileHash -LiteralPath $entry.local_path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $entry.sha256) { throw "Manifest mismatch after download: $($entry.relative_path)" }
}

$appPackEntries = @($entries | Where-Object { $_.relative_path -eq 'packs\native-app-payload.ccpack' })
if ($appPackEntries.Count -ne 1) { throw 'Manifest must contain exactly one native-app-payload.ccpack.' }
$appPack = $appPackEntries[0].local_path
$packManifestOutput = @(& tar.exe -xOf $appPack manifest.json 2>$null)
if ($LASTEXITCODE -ne 0 -or $packManifestOutput.Count -eq 0) { throw 'Could not read native-app-payload.ccpack manifest.json.' }
$packSignature = @(& tar.exe -xOf $appPack manifest.sig 2>$null)
if ($LASTEXITCODE -ne 0 -or $packSignature.Count -eq 0 -or -not ($packSignature -join '').Trim()) { throw 'Native app payload has no embedded manifest signature.' }
$packManifest = ($packManifestOutput -join "`n") | ConvertFrom-Json
if ($packManifest.product -ne 'civiccast-native' -or $packManifest.product_version -ne $id.expected_version -or $packManifest.metadata.source_sha -ne $id.candidate_source_sha -or $packManifest.metadata.civiccast_source_head -ne $id.candidate_source_sha -or [bool] $packManifest.metadata.civiccast_source_dirty) {
    throw 'Native app payload manifest does not bind the clean expected candidate source/version.'
}
$runtimeTargets = @('Lib/site-packages/civiccast/egress/daemon.py', 'Lib/site-packages/civiccast/egress/gst/strategy.py')
$expectedRuntimeHashes = [ordered]@{}
foreach ($relative in $runtimeTargets) {
    $matches = @($packManifest.files | Where-Object { $_.path -eq $relative })
    if ($matches.Count -ne 1 -or "$($matches[0].sha256)" -notmatch '^[0-9a-f]{64}$') { throw "Native app payload manifest does not uniquely bind $relative." }
    $expectedRuntimeHashes[$relative] = "$($matches[0].sha256)"
}

$installer = $installers[0].local_path
$installerHash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($installerHash -ne $id.expected_installer_sha256) { throw 'Installer hash does not equal the independently supplied installer hash.' }
$version = (Get-Item -LiteralPath $installer).VersionInfo.ProductVersion
if ("$version" -ne "$($id.expected_version)") { throw "Installer ProductVersion '$version' does not equal '$($id.expected_version)'." }
$signature = Get-AuthenticodeSignature -LiteralPath $installer
$signerName = $(if ($signature.SignerCertificate) { $signature.SignerCertificate.GetNameInfo([System.Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false) } else { '' })
if ($signature.Status -ne 'Valid' -or $signerName -ne 'Scott Converse') {
    throw "Installer signature is not Valid and signed by Scott Converse (status=$($signature.Status), signer=$signerName)."
}

Set-Beta5IdentityField $id 'actual_manifest_sha256' $manifestHash
Set-Beta5IdentityField $id 'actual_installer_sha256' $installerHash
Set-Beta5IdentityField $id 'installer_product_version' "$version"
Set-Beta5IdentityField $id 'installer_authenticode_status' "$($signature.Status)"
Set-Beta5IdentityField $id 'installer_signer' $signerName
Set-Beta5IdentityField $id 'artifacts_verified_utc' (Get-Date).ToUniversalTime().ToString('o')
Write-Beta5JsonAtomic -Object $id -Path $IdentityPath

# Normal upgrade only: no uninstaller, ProgramData removal, install-root removal, or reboot.
$installInvocationUtc = (Get-Date).ToUniversalTime()
$process = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$installRoot") -PassThru -Wait -WindowStyle Hidden
$null = $process.Handle
if ($process.ExitCode -ne 0) { throw "Installer exited $($process.ExitCode)." }

$installed = $null
$deadline = (Get-Date).AddMinutes(30)
do {
    try {
        $installed = Assert-Beta5InstalledIdentity -Identity $id -InstallRoot $installRoot
        break
    } catch {
        if ((Get-Date) -ge $deadline) { throw }
        Start-Sleep -Seconds 15
    }
} while ((Get-Date) -lt $deadline)
if (-not $installed) { throw 'Installed identity did not become ready.' }
$serviceStartedUtc = ([datetime] $installed.service_process_started_utc).ToUniversalTime()
if ($serviceStartedUtc -lt $installInvocationUtc.AddSeconds(-2)) { throw 'CivicCastSupervisor was not restarted by this candidate installation.' }
$actualRuntimeHashes = [ordered]@{}
foreach ($relative in $runtimeTargets) {
    $installedPath = Join-Path (Join-Path $installRoot 'runtime') ($relative -replace '/', '\')
    $null = Assert-Beta5ChildPath -BasePath (Join-Path $installRoot 'runtime') -CandidatePath $installedPath
    if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf)) { throw "Installed candidate file is absent: $installedPath" }
    $actualRuntimeHashes[$relative] = (Get-FileHash -LiteralPath $installedPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualRuntimeHashes[$relative] -ne $expectedRuntimeHashes[$relative]) { throw "Installed runtime file does not match the candidate app pack: $relative" }
}

$uninstallKeys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$product = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
    Where-Object { $_.PSObject.Properties.Name -contains 'DisplayName' -and $_.PSObject.Properties.Name -contains 'DisplayVersion' -and $_.DisplayName -eq 'CivicCast (Native)' -and $_.DisplayVersion -eq $id.expected_version } |
    Select-Object -First 1
if (-not $product) { throw 'Installed Programs identity does not contain the expected CivicCast beta.5 version.' }
if ($product.PSObject.Properties.Name -contains 'InstallLocation' -and $product.InstallLocation) {
    $observedInstall = Get-Beta5FullPath "$($product.InstallLocation)"
    if (-not $observedInstall.Equals((Get-Beta5FullPath $installRoot), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed Programs location '$observedInstall' does not equal '$installRoot'."
    }
}

Set-Beta5IdentityField $id 'installed_version' "$($installed.health.version)"
Set-Beta5IdentityField $id 'installed_schema' "$($installed.health.schema)"
Set-Beta5IdentityField $id 'installed_schema_db_revision' "$($installed.health.schema_db_revision)"
Set-Beta5IdentityField $id 'installed_schema_expected_head' "$($installed.health.schema_expected_head)"
Set-Beta5IdentityField $id 'installed_service_path' "$($installed.service_path)"
Set-Beta5IdentityField $id 'installed_service_process_id' ([int] $installed.service_process_id)
Set-Beta5IdentityField $id 'installed_service_process_started_utc' $installed.service_process_started_utc
Set-Beta5IdentityField $id 'installed_location' $installRoot
Set-Beta5IdentityField $id 'native_app_payload_sha256' ((Get-FileHash -LiteralPath $appPack -Algorithm SHA256).Hash.ToLowerInvariant())
Set-Beta5IdentityField $id 'native_app_payload_source_sha' "$($packManifest.metadata.source_sha)"
Set-Beta5IdentityField $id 'expected_runtime_file_sha256' $expectedRuntimeHashes
Set-Beta5IdentityField $id 'actual_runtime_file_sha256' $actualRuntimeHashes
Set-Beta5IdentityField $id 'installed_utc' (Get-Date).ToUniversalTime().ToString('o')
Write-Beta5JsonAtomic -Object $id -Path $IdentityPath
Write-Host "FETCH/VERIFY/UPGRADE PASS: $($id.expected_version), manifest+installer hashes independent, signer Scott Converse, service running from $installRoot."
