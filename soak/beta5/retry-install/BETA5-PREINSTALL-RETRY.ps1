# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([string] $PackageRoot, [string] $PackageManifest, [switch] $Execute)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$retrySha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$retryMission = 'beta5-sep8-be1260bd0630'
$retryHostname = 'DESKTOP-VBMA6O5'
$retryMissionRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630'
$retryOriginalBin = Join-Path $retryMissionRoot 'bin'
$retryBin = Join-Path $retryOriginalBin 'install-retry-r1'
$retryJournalRoot = Join-Path $retryMissionRoot 'install-retry-r1'
$retryIdentityPath = Join-Path $retryMissionRoot 'run-identity.json'
$retryDiagnosticPath = Join-Path $retryMissionRoot 'install-inventory-r4\install-inventory-r4.json'
$retryFiles = @('Beta5Tester.Common.ps1', 'ProbeContracts.psm1', 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1', 'AUTORUN-SEP8-BETA5-03-START-SOAK.ps1', 'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1', 'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1')

function Assert-PreinstallRetryFacts {
    param([Parameter(Mandatory)] $Identity, [Parameter(Mandatory)] $Diagnostic, [Parameter(Mandatory)][datetimeoffset] $Now)
    foreach ($pair in @{
        mission=$retryMission; candidate_source_sha=$retrySha; build_source_sha=$retrySha; gate_a_source_sha=$retrySha
        expected_hostname=$retryHostname; hostname=$retryHostname; build_run_id='34237280539'; expected_version='1.0.0-beta.5'
        expected_manifest_sha256='97fe8a28fcbadf92abe31d7ae747fa6ef7fe905bff5c72cc99ff9fa6bf1be43a'
        expected_installer_sha256='5b3fec96cac6bd76cfc88fc7993f5e731d9b945d6606dd4c28f9a256c2c8b7e0'
    }.GetEnumerator()) {
        $property = $Identity.PSObject.Properties[$pair.Key]
        if ($null -eq $property -or "$($property.Value)" -cne "$($pair.Value)") { throw "Retry identity mismatch: $($pair.Key)." }
    }
    foreach ($pair in @{
        tester_root='C:\CivicCastSoak'; mission_state_root=$retryMissionRoot
        return_repo_path=(Join-Path $retryMissionRoot 'return-repo')
    }.GetEnumerator()) {
        $property = $Identity.PSObject.Properties[$pair.Key]
        if ($null -eq $property -or -not ([IO.Path]::GetFullPath("$($property.Value)").TrimEnd('\')).Equals($pair.Value,[StringComparison]::OrdinalIgnoreCase)) { throw "Retry path mismatch: $($pair.Key)." }
    }
    foreach ($name in @('actual_manifest_sha256','actual_installer_sha256','artifacts_verified_utc','installed_utc','installed_service_process_id','approved_assets','retry_install_started_utc')) {
        $property = $Identity.PSObject.Properties[$name]
        if ($null -ne $property -and $null -ne $property.Value -and "$($property.Value)" -ne '') { throw "Retry refuses a progressed identity at $name; reconcile it first." }
    }
    if ($Diagnostic.diagnostic_status -cne 'COLLECTED' -or $Diagnostic.mission -cne $retryMission -or $Diagnostic.candidate_source_sha -cne $retrySha -or $Diagnostic.hostname -cne $retryHostname) { throw 'Retry diagnostic does not identify this candidate and tester.' }
    $age = ($Now.ToUniversalTime() - ([datetimeoffset]$Diagnostic.collected_utc).ToUniversalTime()).TotalMinutes
    if ($age -lt 0 -or $age -gt 60) { throw 'Retry diagnostic must be no more than60 minutes old.' }
    $logs = @($Diagnostic.known_original_log_signals | Where-Object {
        $_.inspected -and
        $_.known_failure_categories -contains 'property_missing' -and
        $_.known_failure_categories -contains 'native_command_error' -and
        $_.missing_property_names -contains 'sha256' -and
        $_.mentioned_script_filenames -contains 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1' -and
        @($_.script_locations).Count -eq 0 -and
        (@($_.line_character_locations | ForEach-Object { [int]$_.line } | Sort-Object) -join ',') -eq '51,56'
    })
    if ($logs.Count -ne 1) { throw 'Retry requires the actual R4 property/native-command diagnostic structure; no remote source line is asserted.' }
    if ($Diagnostic.service.state -cne 'Running' -or [int]$Diagnostic.service.process_id -le 0) { throw 'Retry lacks an observed old running service.' }
}

function Assert-PreinstallPlainPath {
    param([Parameter(Mandatory)][string] $Path)
    $full=[IO.Path]::GetFullPath($Path)
    $cursor=$full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item=Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Retry path crosses a reparse point.' }
        }
        $parent=Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor=$parent
    }
    return $full
}

if ($env:BETA5_PREINSTALL_RETRY_LIBRARY -eq '1') { return }
if (-not $Execute) {
    [ordered]@{
        mission=$retryMission; candidate_source_sha=$retrySha; hostname=$retryHostname; execute=$false
        requirement='Actual R4 diagnostic confirms property_missing plus native_command_error, missing sha256, the exact FETCH-INSTALL filename, no structured script location, and only outer lines 51/56; unchanged uninstalled identity; fresh original service and no active installer/soak.'
        action='Reverify every downloaded artifact, normally upgrade once, start exact three-channel media soak from separate verified scripts, and schedule sampling after first real transport PASS.'
        preserved='Original six mission script files, signed installer/packs, original kickoff/evidence and station data. New retry bin is a child directory; no original file is overwritten.'
    } | ConvertTo-Json
    return
}
if ("$env:COMPUTERNAME" -cne $retryHostname) { throw 'Retry targets the dedicated tester only.' }
$null=Assert-PreinstallPlainPath $retryIdentityPath
$null=Assert-PreinstallPlainPath $retryDiagnosticPath
$identity=Get-Content -LiteralPath $retryIdentityPath -Raw | ConvertFrom-Json
$diagnostic=Get-Content -LiteralPath $retryDiagnosticPath -Raw | ConvertFrom-Json
Assert-PreinstallRetryFacts $identity $diagnostic ([datetimeoffset]::UtcNow)
foreach ($path in @($retryBin,$retryJournalRoot,(Join-Path $retryMissionRoot 'soak-state.json'),(Join-Path $identity.return_repo_path "soak\beta5\$retryMission\final-verdict.json"))) {
    $null=Assert-PreinstallPlainPath $path
    if (Test-Path -LiteralPath $path) { throw 'Retry output, active soak, or terminal evidence already exists; refusing replay.' }
}
$taskName="CivicCast-Beta5-$retryMission-Soak"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'The exact mission sampler already exists; refusing installation.' }
$setupProcesses=@(Get-CimInstance Win32_Process -Property Name,ProcessId | Where-Object { $_.Name -in @('CivicCast (Native)_1.0.0-beta.5_x64-setup.exe','setup.exe','civiccast-installer.exe') })
if ($setupProcesses.Count -gt 0) { throw 'An installer is already running; preserve it and reconcile first.' }
$oldService=Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -Property State,ProcessId,PathName
if ($oldService.State -cne 'Running' -or [int]$oldService.ProcessId -ne [int]$diagnostic.service.process_id) { throw 'Installed service changed after diagnosis.' }
$oldProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$oldService.ProcessId)" -Property CreationDate
if (([datetimeoffset]$oldProcess.CreationDate).ToUniversalTime() -ne ([datetimeoffset]$diagnostic.service.started_utc).ToUniversalTime()) { throw 'Installed service process was replaced after diagnosis.' }

$sourceRoot=Assert-PreinstallPlainPath $PackageRoot
$manifestPath=Assert-PreinstallPlainPath $PackageManifest
$manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -cne 'civiccast-native-beta5-retry-package-v1' -or $manifest.candidate_source_sha -cne $retrySha -or @($manifest.files).Count -ne $retryFiles.Count) { throw 'Unexpected reviewed retry package manifest.' }
foreach ($name in $retryFiles) {
    $entry=@($manifest.files | Where-Object { $_.name -ceq $name })
    if ($entry.Count -ne 1 -or "$($entry[0].sha256)" -cnotmatch '^[0-9a-f]{64}$') { throw 'Retry manifest file binding is missing or invalid.' }
    $sourcePath=Assert-PreinstallPlainPath (Join-Path $sourceRoot $name)
    if ((Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[0].sha256) { throw "Retry source hash mismatch: $name." }
}
. (Join-Path $sourceRoot 'Beta5Tester.Common.ps1')
$identity=Get-Beta5Identity $retryIdentityPath
$originalHashes=@($retryFiles | ForEach-Object {
    $path=Join-Path $retryOriginalBin $_
    [pscustomobject]@{name=$_;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
})
# CreateNew is the exclusive dispatch boundary. No automatic deletion/replay.
New-Item -ItemType Directory -Path $retryJournalRoot | Out-Null
$lockPath=Join-Path $retryJournalRoot 'dispatch.lock'
$lock=[IO.File]::Open($lockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
$journal=[ordered]@{schema='civiccast-native-beta5-install-retry-v1';mission=$retryMission;candidate_source_sha=$retrySha;stage='COPY';status='STARTED';started_utc=[datetimeoffset]::UtcNow.ToString('o');original_script_hashes=$originalHashes;support_manifest_sha256=(Get-FileHash -LiteralPath $manifestPath).Hash.ToLowerInvariant();error_type=$null}
$journalPath=Join-Path $retryJournalRoot 'retry-journal.json'
try {
    Write-Beta5JsonAtomic $journal $journalPath
    New-Item -ItemType Directory -Path $retryBin | Out-Null
    foreach ($entry in $manifest.files) {
        $destination=Join-Path $retryBin $entry.name
        Copy-Item -LiteralPath (Join-Path $sourceRoot $entry.name) -Destination $destination
        if ((Get-FileHash -LiteralPath $destination).Hash.ToLowerInvariant() -cne $entry.sha256) { throw 'Copied retry script failed its hash binding.' }
    }
    foreach ($step in @('02-FETCH-INSTALL','03-START-SOAK','04-SOAK-CYCLE')) {
        $journal.stage=$step
        Write-Beta5JsonAtomic $journal $journalPath
        $stepPath=Join-Path $retryBin "AUTORUN-SEP8-BETA5-$step.ps1"
        & $stepPath -IdentityPath $retryIdentityPath
    }
    $identity=Get-Beta5Identity $retryIdentityPath
    $telemetry=Join-Path $identity.return_repo_path "soak\beta5\$retryMission\telemetry"
    $latest=Get-ChildItem -LiteralPath $telemetry -Filter 'cycle-*.json' -File | Sort-Object Name | Select-Object -Last 1
    if ($null -eq $latest) { throw 'Retry immediate cycle produced no evidence.' }
    $cycle=Get-Content -LiteralPath $latest.FullName -Raw | ConvertFrom-Json
    if ($cycle.mission -cne $retryMission -or $cycle.candidate_source_sha -cne $retrySha -or @($cycle.channels).Count -ne 3) { throw 'Retry cycle identity or channel count mismatch.' }
    if (@($cycle.channels | Where-Object { $_.state -ne 'ON_AIR' -or $_.engine -ne 'gstreamer' -or -not $_.pid -or $_.tsduck.verdict -ne 'pass' }).Count -gt 0) { throw 'Retry immediate actual-media proof did not pass.' }
    $journal.stage='05-SCHEDULE-CYCLES'
    Write-Beta5JsonAtomic $journal $journalPath
    & (Join-Path $retryBin 'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1') -IdentityPath $retryIdentityPath
    $journal.status='STARTED_WITH_FIRST_CYCLE_PASS'
    $journal.stage='TWO_HOUR_SOAK_PENDING'
} catch {
    $journal.status='FAILED_REQUIRES_RECONCILIATION'
    $journal.error_type=$_.Exception.GetType().FullName
    throw
} finally {
    $journal.updated_utc=[datetimeoffset]::UtcNow.ToString('o')
    try { Write-Beta5JsonAtomic $journal $journalPath } finally { $lock.Dispose() }
    foreach ($entry in $originalHashes) {
        if ((Get-FileHash -LiteralPath (Join-Path $retryOriginalBin $entry.name)).Hash.ToLowerInvariant() -cne $entry.sha256) { throw 'An original mission script changed during retry; inspect evidence.' }
    }
}
Write-Host 'Exact candidate retry installed and started sampling; two-hour media verdict remains pending.'
