# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<#
Only this file belongs in soak/autorun. Put the support package in soak/beta5.
Do not dispatch this wrapper until every placeholder is replaced from a successful signed build,
an assigned exact-source Gate A run (PENDING or PASS), and signed-kit evidence.
Public release publication remains separately gated on all three Gate A lanes passing.
#>
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$facts = [ordered]@{
    CandidateSha = '__CANDIDATE_SHA_40__'
    BuildSourceSha = '__BUILD_SOURCE_SHA_40__'
    GateASourceSha = '__GATE_A_SOURCE_SHA_40__'
    ManifestSha256 = '__MANIFEST_SHA256_64__'
    InstallerSha256 = '__INSTALLER_SHA256_64__'
    BuildRunId = '__BUILD_RUN_ID__'
    BuildConclusion = 'success'
    GateARunId = '__GATE_A_RUN_ID__'
    GateAVerdict = 'PENDING'
    ExpectedVersion = '1.0.0-beta.5'
    KitBaseUrl = '__KIT_BASE_URL_ENDING_IN_CANDIDATE_SHA__'
    ReturnRepositoryUrl = 'https://github.com/scottconverse/civiccast-native.git'
    ExpectedHostname = 'DESKTOP-VBMA6O5'
}
if (($facts.Values -join '|') -match '__[A-Z0-9_]+__') { throw 'Beta.5 autorun facts are unresolved; nothing was changed.' }
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5')).TrimEnd('\')
$orchestrator = Join-Path $packageRoot 'Invoke-Beta5TesterMission.ps1'
if (-not (Test-Path -LiteralPath $orchestrator -PathType Leaf)) { throw "Beta.5 support package is absent: $packageRoot" }
& $orchestrator @facts -PackageRoot $packageRoot -DryRun:$DryRun
