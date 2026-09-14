# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$package = Join-Path $PSScriptRoot '..\beta7\3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\off4h-r13-a73c91'
$identityPath = Join-Path $package 'run-identity.json'
$expectedTask = 'CivicCast-Beta7-3e117ff1-OFF4H-R13-A73C91'
$expectedMission = 'BETA7-3E117FF1-OFF4H-R13-A73C91'
$expectedSource = '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$jobRelative = 'soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r13-a73c91/job.json'
$terminalJobName = 'physical-soak-off4h-r13-a73c91-job.json'
$coordinationTasks = @('CivicCastSoak-Poll', 'CivicCastSoak-Heartbeat', 'CivicCastSoak-Boot')

function Assert-CoordinationTasks {
    foreach ($name in $coordinationTasks) {
        if (-not (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue)) {
            throw "Required coordination task is absent: $name"
        }
    }
}

function Get-VerifiedStartReceipt($Identity) {
    $path = Join-Path ([string]$Identity.mission_state_root) 'START-VERIFIED.json'
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    try { $receipt = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
    catch { return $null }
    if ([string]$receipt.schema -cne 'civiccast-beta7-start-verified-v1' -or
        [string]$receipt.status -cne 'STARTED_AND_REMOTELY_VERIFIED' -or
        [string]$receipt.candidate_source_sha -cne $expectedSource -or
        [string]$receipt.mission_nonce -cne $expectedMission -or
        [string]$receipt.harness_source_commit -cne [string]$Identity.harness_source_commit -or
        [string]$receipt.job_state -cne 'STARTED' -or
        [string]$receipt.remote_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.remote_blob -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.job_relative_path -cne $jobRelative) {
        throw 'R13 start marker does not bind the exact remotely verified candidate receipt.'
    }
    return $receipt
}

if ($DryRun) {
    $tokens = $null
    $parseErrors = $null
    $selfAst = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$parseErrors)
    if (@($parseErrors).Count) { throw "R13 activation order has parse errors: $($parseErrors.Message -join '; ')" }
    $selfText = Get-Content -LiteralPath $PSCommandPath -Raw
    $gitCommands = @($selfAst.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Invoke-Beta5Git' }, $true))
    if ($gitCommands.Count) { throw 'R13 launcher must not race the physical job for its Git checkout.' }
    if ($selfText -notmatch '(?s)Start-Beta7PhysicalOFF4HJob.*?AddMinutes\(5\).*?Get-VerifiedStartReceipt.*?terminalJobPath.*?did not publish and remotely verify its start receipt') {
        throw 'R13 launcher does not wait fail-closed for the physical job start-verification marker.'
    }
    if ($selfText -notmatch '(?s)Invoke-Beta7TesterUpgrade\.ps1.*?installedIdentityPath.*?Assert-Beta7CandidateBinding\.ps1.*?Start-Beta7PhysicalOFF4HJob\.ps1') {
        throw 'R13 launcher does not reload the adoption-updated installed identity before launch.'
    }
    $id = & (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
    $expectedEvidenceRoot = $jobRelative.Substring(0, $jobRelative.Length - '/job.json'.Length)
    if ([string]$id.task_name -cne $expectedTask -or
        [string]$id.mission_nonce -cne $expectedMission -or
        [string]$id.candidate_source_sha -cne $expectedSource -or
        [string]$id.evidence_relative_root -cne $expectedEvidenceRoot) {
        throw 'R13 activation constants do not match the finalized package identity.'
    }
    & (Join-Path $package 'Invoke-Beta7TesterUpgrade.ps1') -PackageRoot $package -DryRun | Out-Null
    & (Join-Path $package 'Start-Beta7PhysicalOFF4HJob.ps1') -PackageRoot $package -DryRun | Out-Null
    [pscustomobject]@{
        status = 'DRYRUN_VERIFIED'
        candidate_source_sha = $expectedSource
        mission_nonce = $expectedMission
        task_name = $expectedTask
        measured_minutes = 240
        captions = 'OFF'
        live_mutations = 0
        start_receipt_required = 'exact remote blob on tester evidence branch'
    } | ConvertTo-Json -Compress
    return
}

if ($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5') { throw 'This beta.7 R13 mission targets DESKTOP-VBMA6O5 only.' }
Assert-CoordinationTasks
. (Join-Path $package 'Beta7Tester.Common.ps1')
$id = & (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
$competing = @(Get-ScheduledTask -ErrorAction Stop | Where-Object {
    $_.TaskName -like 'CivicCast-Beta7-*' -and
    $_.TaskName -ne [string]$id.task_name -and
    [string]$_.State -eq 'Running'
})
if ($competing.Count) { throw "Another beta.7 physical task is running: $($competing.TaskName -join ', ')" }

& (Join-Path $package 'Invoke-Beta7TesterUpgrade.ps1') -PackageRoot $package | Out-Null
$installedIdentityPath = Join-Path ([string]$id.mission_state_root) 'bin\run-identity.json'
$id = & (Join-Path $package 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $installedIdentityPath
$launch = @(& (Join-Path $package 'Start-Beta7PhysicalOFF4HJob.ps1') -PackageRoot $package)
if (-not ($launch -match [regex]::Escape([string]$id.task_name))) {
    throw 'Physical soak handoff did not return the exact candidate-specific task receipt.'
}

$terminalJobPath = Join-Path ([string]$id.mission_state_root) $terminalJobName
$deadline = [datetime]::UtcNow.AddMinutes(5)
$verifiedStart = $null
do {
    $task = Get-ScheduledTask -TaskName ([string]$id.task_name) -ErrorAction SilentlyContinue
    if (-not $task) { throw 'Candidate-specific physical soak task disappeared before a start receipt.' }
    $verifiedStart = Get-VerifiedStartReceipt $id
    if ($verifiedStart) { break }
    if (Test-Path -LiteralPath $terminalJobPath -PathType Leaf) {
        $terminal = Get-Content -LiteralPath $terminalJobPath -Raw | ConvertFrom-Json
        throw "R13 physical task terminated before its remote start receipt: state=$($terminal.job_state), error=$($terminal.error)"
    }
    Start-Sleep -Seconds 2
} while ([datetime]::UtcNow -lt $deadline)
if (-not $verifiedStart) { throw 'R13 physical task did not publish and remotely verify its start receipt within five minutes.' }

Assert-CoordinationTasks
$finalTask = Get-ScheduledTask -TaskName ([string]$id.task_name) -ErrorAction Stop
[pscustomobject]@{
    status = 'STARTED_AND_REMOTELY_VERIFIED'
    candidate_source_sha = $expectedSource
    mission_nonce = $expectedMission
    task_name = $expectedTask
    task_state = [string]$finalTask.State
    job_state = [string]$verifiedStart.job_state
    job_started_utc = [string]$verifiedStart.job_started_utc
    remote_commit = [string]$verifiedStart.remote_commit
    remote_blob = [string]$verifiedStart.remote_blob
    start_verified_utc = [string]$verifiedStart.verified_utc
} | ConvertTo-Json -Compress
