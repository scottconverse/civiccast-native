# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{40}$')][string] $ExpectedSha,
    [Parameter(Mandatory)][string] $ExpectedVersion,
    [Parameter(Mandatory)][string] $AssetId,
    [Parameter(Mandatory)][string] $RunIdentityPath,
    [Parameter(Mandatory)][string] $FinalVerdictPath,
    [string] $OperatorTokenPath = 'C:\CivicCastSoak\state\token',
    [string] $ApiBase = 'http://127.0.0.1:8000',
    [string] $TesterPrepRoot = (Join-Path $PSScriptRoot '..'),
    [string] $EvidenceContractsPath = (Join-Path $PSScriptRoot '..\filler-probe\ProbeContracts.psm1'),
    [string] $OutputDirectory,
    [ValidateRange(1, 60)][int] $PollIntervalSeconds = 10,
    [ValidateRange(10, 3600)][int] $MaxPollSeconds = 1800,
    [switch] $Execute
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$commonPath = Join-Path $TesterPrepRoot 'Beta5Tester.Common.ps1'
if (-not (Test-Path -LiteralPath $commonPath -PathType Leaf)) { throw "Tester common helper is absent: $commonPath" }
if (-not (Test-Path -LiteralPath $EvidenceContractsPath -PathType Leaf)) { throw "Tester evidence contracts are absent: $EvidenceContractsPath" }
. $commonPath
Import-Module $EvidenceContractsPath -Force
Import-Module (Join-Path $PSScriptRoot 'CaptionProof.Contracts.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'CaptionProof.Http.psm1') -Force

$base = $ApiBase.TrimEnd('/')
if ($base -cne 'http://127.0.0.1:8000') { throw 'Caption acceptance is restricted to the installed station loopback API.' }
$expectedShaNormalized = $ExpectedSha.ToLowerInvariant()
$identityPath = (Resolve-Path -LiteralPath $RunIdentityPath).Path
$identity = Get-Beta5Identity $identityPath
$expectedVerdictPath = Join-Path $identity.return_repo_path "soak\beta5\$($identity.mission)\final-verdict.json"
if ((Get-Beta5FullPath $FinalVerdictPath) -cne (Get-Beta5FullPath $expectedVerdictPath)) {
    throw "Final verdict path is not the selected mission's exact return-repository verdict."
}
$verdictPath = (Resolve-Path -LiteralPath $FinalVerdictPath).Path
$verdict = Get-Content -LiteralPath $verdictPath -Raw | ConvertFrom-Json
Assert-TesterEvidence $identity $verdict $expectedShaNormalized $ExpectedVersion
if ("$($identity.candidate_source_sha)" -cne $expectedShaNormalized) { throw 'Expected source SHA does not match the run identity.' }

$plan = [pscustomobject][ordered]@{
    schema = 'civiccast-native-beta5-caption-acceptance-plan-v1'
    execute = [bool] $Execute
    mission = "$($identity.mission)"
    candidate_source_sha = "$($identity.candidate_source_sha)"
    expected_version = $ExpectedVersion
    asset_id = $AssetId
    api_base = $base
    run_identity_path = $identityPath
    final_verdict_path = $verdictPath
    operator_token_source = 'existing tester token file; value and path are not recorded'
    token_recorded = $false
    permitted_product_mutations = @('POST caption review approval for this asset EN rows', 'POST caption review approval for this asset ES rows')
    forbidden_product_mutations = @('channel commands/configuration', 'schedule writes', 'asset/package/publication writes', 'install/service/reboot', 'provider/CDN publication')
    resident_browser_playback = 'NOT_RUN_BY_THIS_HELPER'
}
if (-not $Execute) {
    $plan | ConvertTo-Json -Depth 10
    return
}

if (-not (Test-Path -LiteralPath $OperatorTokenPath -PathType Leaf)) { throw 'Tester token file is absent.' }
$token = (Get-Content -LiteralPath $OperatorTokenPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($token)) { throw 'Tester token is empty.' }

$runName = 'caption-proof-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $identity.mission_state_root "evidence\$runName"
}
$output = Assert-Beta5ChildPath -BasePath $identity.mission_state_root -CandidatePath $OutputDirectory
if (Test-Path -LiteralPath $output) { throw "Caption proof output already exists: $output" }
New-Item -ItemType Directory -Path $output | Out-Null
$eventsPath = Join-Path $output 'events.jsonl'
$resultPath = Join-Path $output 'caption-acceptance.json'
$planPath = Join-Path $output 'plan.json'
Write-Beta5JsonAtomic $plan $planPath

$httpClient = New-CaptionProofHttpClient
$apiInvoker = { param($Method, $Path, $Body, $ResponseKind) Invoke-CaptionProofHttpRequest -Client $httpClient -BaseUri ([uri] ($base + '/')) -BearerToken $token -Method $Method -Path $Path -Body $Body -ResponseKind $ResponseKind }
$installedIdentityInvoker = {
    $service = Assert-Beta5InstalledIdentity -Identity $identity -BaseUrl $base
    $runtimeHashes = Assert-CaptionInstalledRuntimeHashes -Identity $identity
    [pscustomobject][ordered]@{
        health = $service.health
        service_state = $service.service_state
        service_path = $service.service_path
        service_executable = $service.service_executable
        service_process_id = $service.service_process_id
        service_process_started_utc = $service.service_process_started_utc
        current_runtime_hashes = $runtimeHashes
    }
}
$eventRecorder = {
    param($Event)
    # Events intentionally contain IDs, hashes, sizes, and decision facts only.
    # They never contain the token, clip bytes, or caption text.
    ($Event | ConvertTo-Json -Depth 10 -Compress) | Add-Content -LiteralPath $eventsPath -Encoding utf8
}

try {
    $result = Invoke-CaptionProofWorkflow `
        -Identity $identity `
        -AssetId $AssetId `
        -ApiInvoker $apiInvoker `
        -InstalledIdentityInvoker $installedIdentityInvoker `
        -EventRecorder $eventRecorder `
        -PollIntervalSeconds $PollIntervalSeconds `
        -MaxPollSeconds $MaxPollSeconds
} finally {
    $httpClient.Dispose()
}
Write-Beta5JsonAtomic $result $resultPath
$result | ConvertTo-Json -Depth 30
if ($result.verdict -ne 'PASS') { exit 2 }
