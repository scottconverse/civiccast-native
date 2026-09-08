# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Exact signed candidate dispatch. Gate A is pending, not installation acceptance.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$facts = [ordered]@{
    CandidateSha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    BuildSourceSha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    GateASourceSha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    ManifestSha256 = '97fe8a28fcbadf92abe31d7ae747fa6ef7fe905bff5c72cc99ff9fa6bf1be43a'
    InstallerSha256 = '5b3fec96cac6bd76cfc88fc7993f5e731d9b945d6606dd4c28f9a256c2c8b7e0'
    BuildRunId = '34237280539'
    BuildConclusion = 'success'
    GateARunId = '34242157263'
    GateAVerdict = 'PENDING'
    ExpectedVersion = '1.0.0-beta.5'
    KitBaseUrl = 'http://192.168.0.135:8766/be1260bd0630261c571e3adf5aac6a6cbebd9e3a/'
    ReturnRepositoryUrl = 'https://github.com/scottconverse/civiccast-native.git'
    ExpectedHostname = 'DESKTOP-VBMA6O5'
}
$packageRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\beta5')).TrimEnd('\')
$orchestrator = Join-Path $packageRoot 'Invoke-Beta5TesterMission.ps1'
if (-not (Test-Path -LiteralPath $orchestrator -PathType Leaf)) { throw "Beta.5 support package is absent: $packageRoot" }
& $orchestrator @facts -PackageRoot $packageRoot -DryRun:$DryRun
