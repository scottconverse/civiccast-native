# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $CandidateSha,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $BuildSourceSha,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string] $GateASourceSha,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string] $ManifestSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string] $InstallerSha256,
    [Parameter(Mandatory)][ValidatePattern('^[1-9]\d*$')][string] $BuildRunId,
    [Parameter(Mandatory)][ValidateSet('success')][string] $BuildConclusion,
    [Parameter(Mandatory)][ValidatePattern('^[1-9]\d*$')][string] $GateARunId,
    [Parameter(Mandatory)][ValidateSet('PASS', 'PENDING')][string] $GateAVerdict,
    [Parameter(Mandatory)][string] $ExpectedVersion,
    [Parameter(Mandatory)][string] $KitBaseUrl,
    [Parameter(Mandatory)][string] $ReturnRepositoryUrl,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9-]+$')][string] $ExpectedHostname,
    [string] $PackageRoot = $PSScriptRoot,
    [string] $TesterRoot = 'C:\CivicCastSoak',
    [string] $OperatorTokenPath = 'C:\CivicCastSoak\state\token',
    [switch] $DryRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PackageRoot 'Beta5Tester.Common.ps1')
if ($BuildConclusion -cne 'success') { throw 'BuildConclusion must be exactly success.' }
if ($GateAVerdict -cnotin @('PASS', 'PENDING')) { throw 'GateAVerdict must be exactly PASS or PENDING.' }
if ($CandidateSha -ne $BuildSourceSha -or $CandidateSha -ne $GateASourceSha) { throw 'Build/Gate A source identity does not match candidate.' }
if ("$env:COMPUTERNAME" -ne $ExpectedHostname) { throw "This directive targets '$ExpectedHostname', not '$env:COMPUTERNAME'." }
$mission = "beta5-sep8-$($CandidateSha.Substring(0, 12))"
$missionRoot = Join-Path (Get-Beta5FullPath $TesterRoot) ("missions\" + $mission)
$stableBin = Join-Path $missionRoot 'bin'
$existingState = Join-Path $missionRoot 'soak-state.json'
$existingFinal = Join-Path $missionRoot ("return-repo\soak\beta5\$mission\final-verdict.json")
if ((Test-Path -LiteralPath $existingState) -or (Test-Path -LiteralPath $existingFinal)) { throw 'This mission is active or terminal; replay requires a new mission identity and cannot overwrite stable scripts or rerun installation.' }
$scripts = @('Beta5Tester.Common.ps1', 'ProbeContracts.psm1', 'AUTORUN-SEP8-BETA5-01-PREFLIGHT.ps1', 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1', 'AUTORUN-SEP8-BETA5-03-START-SOAK.ps1', 'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1', 'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1')
foreach ($name in $scripts) { if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $name) -PathType Leaf)) { throw "Package is missing $name" } }
if ($DryRun) {
    & (Join-Path $PackageRoot 'AUTORUN-SEP8-BETA5-01-PREFLIGHT.ps1') -CandidateSha $CandidateSha -BuildSourceSha $BuildSourceSha -GateASourceSha $GateASourceSha -ManifestSha256 $ManifestSha256 -InstallerSha256 $InstallerSha256 -BuildRunId $BuildRunId -BuildConclusion $BuildConclusion -GateARunId $GateARunId -GateAVerdict $GateAVerdict -ExpectedVersion $ExpectedVersion -KitBaseUrl $KitBaseUrl -ReturnRepositoryUrl $ReturnRepositoryUrl -ExpectedHostname $ExpectedHostname -TesterRoot $TesterRoot -DryRun
    Write-Host '[DRYRUN] stable-copy, download, install, HTTP writes, Git writes, task registration, and sampling skipped.'
    return
}
New-Item -ItemType Directory -Force -Path $stableBin | Out-Null
foreach ($name in $scripts) { Copy-Item -LiteralPath (Join-Path $PackageRoot $name) -Destination (Join-Path $stableBin $name) -Force }
$preflight = Join-Path $stableBin 'AUTORUN-SEP8-BETA5-01-PREFLIGHT.ps1'
& $preflight -CandidateSha $CandidateSha -BuildSourceSha $BuildSourceSha -GateASourceSha $GateASourceSha -ManifestSha256 $ManifestSha256 -InstallerSha256 $InstallerSha256 -BuildRunId $BuildRunId -BuildConclusion $BuildConclusion -GateARunId $GateARunId -GateAVerdict $GateAVerdict -ExpectedVersion $ExpectedVersion -KitBaseUrl $KitBaseUrl -ReturnRepositoryUrl $ReturnRepositoryUrl -ExpectedHostname $ExpectedHostname -TesterRoot $TesterRoot
$identityPath = Join-Path $missionRoot 'run-identity.json'
$identity = Get-Beta5Identity $identityPath
$archivedLegacyMarker = Move-Beta5LegacySoakMarker $identity
if ($archivedLegacyMarker) { Write-Host "Archived legacy AUTORUN-3 trigger recoverably at $archivedLegacyMarker" }
& (Join-Path $stableBin 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1') -IdentityPath $identityPath
& (Join-Path $stableBin 'AUTORUN-SEP8-BETA5-03-START-SOAK.ps1') -IdentityPath $identityPath -OperatorTokenPath $OperatorTokenPath
$taskName = "CivicCast-Beta5-$mission-Soak"
& (Join-Path $stableBin 'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1') -IdentityPath $identityPath -OperatorTokenPath $OperatorTokenPath
$identity = Get-Beta5Identity $identityPath
$telemetry = Join-Path $identity.return_repo_path "soak\beta5\$mission\telemetry"
$latest = Get-ChildItem -LiteralPath $telemetry -Filter 'cycle-*.json' -File | Sort-Object Name | Select-Object -Last 1
if (-not $latest) { throw 'Immediate actual-media cycle did not produce telemetry.' }
$cycle = Get-Content -LiteralPath $latest.FullName -Raw | ConvertFrom-Json
if ($cycle.mission -ne $mission -or $cycle.candidate_source_sha -ne $CandidateSha -or @($cycle.channels).Count -ne 3) { throw 'Immediate cycle identity/channel proof is invalid.' }
if (@($cycle.channels | Where-Object { $_.state -ne 'ON_AIR' -or $_.engine -ne 'gstreamer' -or -not $_.pid -or $_.tsduck.verdict -ne 'pass' }).Count -ne 0) { throw 'Immediate actual-media cycle did not pass all three channels.' }
& (Join-Path $stableBin 'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1') -IdentityPath $identityPath
Write-Host "BETA5 TESTER MISSION STARTED: $mission; task=$taskName; first actual-media cycle passed; final verdict remains pending for two hours."
