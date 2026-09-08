# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# Materialize a candidate-bound tester identity. This script performs no network or product action. #>
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
    [Parameter(Mandatory)][ValidatePattern('^1\.0\.0-beta\.5(?:[.+-][0-9A-Za-z.-]+)?$')][string] $ExpectedVersion,
    [Parameter(Mandatory)][ValidatePattern('^https?://')][string] $KitBaseUrl,
    [Parameter(Mandatory)][ValidatePattern('^https://')][string] $ReturnRepositoryUrl,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9-]+$')][string] $ExpectedHostname,
    [string] $TesterRoot = 'C:\CivicCastSoak',
    [int] $PlannedSeconds = 7200,
    [ValidateRange(30, 60)][int] $SampleIntervalSeconds = 60,
    [switch] $DryRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')

if ($BuildConclusion -cne 'success') { throw 'BuildConclusion must be exactly success.' }
if ($GateAVerdict -cnotin @('PASS', 'PENDING')) { throw 'GateAVerdict must be exactly PASS or PENDING.' }
if ($CandidateSha -ne $BuildSourceSha -or $CandidateSha -ne $GateASourceSha) { throw 'CandidateSha, BuildSourceSha, and GateASourceSha must match exactly.' }
if ($PlannedSeconds -lt 7200) { throw 'PlannedSeconds must be at least 7200.' }
$KitBaseUrl = $KitBaseUrl.TrimEnd('/') + '/'
if ($KitBaseUrl -notlike "*/$CandidateSha/") { throw 'KitBaseUrl must end in the exact full candidate SHA and a slash.' }
$kitUri = [uri] $KitBaseUrl
if ($kitUri.Scheme -ne 'http' -or $kitUri.Port -ne 8766 -or $kitUri.Host -notin '192.168.0.135', '127.0.0.1', 'localhost') { throw 'KitBaseUrl must use the approved local/LAN port-8766 staging server.' }
if ($ReturnRepositoryUrl -ne 'https://github.com/scottconverse/civiccast-native.git') { throw 'Unexpected return repository URL.' }

$testerRootFull = Get-Beta5FullPath $TesterRoot
$mission = "beta5-sep8-$($CandidateSha.Substring(0, 12))"
$missionState = Join-Path $testerRootFull ("missions\" + $mission)
$returnRepo = Join-Path $missionState 'return-repo'
$hostname = "$env:COMPUTERNAME"
if (-not $hostname) { throw 'COMPUTERNAME is unavailable.' }
if ($hostname -ne $ExpectedHostname) { throw "This directive targets '$ExpectedHostname', not '$hostname'." }
$identity = [ordered]@{
    schema = 'civiccast-native-tester-run-identity-v3'; mission = $mission
    candidate_source_sha = $CandidateSha; build_source_sha = $BuildSourceSha; gate_a_source_sha = $GateASourceSha
    expected_manifest_sha256 = $ManifestSha256; actual_manifest_sha256 = $null
    expected_installer_sha256 = $InstallerSha256; actual_installer_sha256 = $null
    expected_version = $ExpectedVersion; build_run_id = [int64] $BuildRunId; build_conclusion = $BuildConclusion; gate_a_run_id = [int64] $GateARunId
    gate_a_verdict = $GateAVerdict; kit_base_url = $KitBaseUrl; return_repository_url = $ReturnRepositoryUrl
    return_branch = "tester/soak8-e1acfe6-$ExpectedHostname"; hostname = $hostname; expected_hostname = $ExpectedHostname; tester_root = $testerRootFull
    mission_state_root = $missionState; return_repo_path = $returnRepo
    planned_seconds = $PlannedSeconds; sample_interval_seconds = $SampleIntervalSeconds
    channels = @([ordered]@{ channel_id = 'public'; udp_port = 9001 }, [ordered]@{ channel_id = 'education'; udp_port = 9002 }, [ordered]@{ channel_id = 'government'; udp_port = 9003 })
    prepared_utc = (Get-Date).ToUniversalTime().ToString('o')
}
$identityPath = Join-Path $missionState 'run-identity.json'
if ($DryRun) { $identity | ConvertTo-Json -Depth 8; return }
if (Test-Path -LiteralPath $identityPath) {
    $existing = Get-Beta5Identity $identityPath
    $immutable = @('mission', 'candidate_source_sha', 'build_source_sha', 'gate_a_source_sha', 'expected_manifest_sha256', 'expected_installer_sha256', 'expected_version', 'build_run_id', 'build_conclusion', 'gate_a_run_id', 'gate_a_verdict', 'kit_base_url', 'return_repository_url', 'return_branch', 'expected_hostname', 'planned_seconds', 'sample_interval_seconds')
    foreach ($name in $immutable) { if ("$($existing.$name)" -ne "$($identity[$name])") { throw "Existing immutable identity differs at '$name'." } }
    Write-Host "PREFLIGHT PASS (existing immutable identity retained): $identityPath"
    return
}
New-Item -ItemType Directory -Force -Path $missionState | Out-Null
Write-Beta5JsonAtomic -Object $identity -Path $identityPath
Write-Host "PREFLIGHT PASS: $identityPath"
