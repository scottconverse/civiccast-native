# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$previousLibraryFlag = [Environment]::GetEnvironmentVariable('BETA5_PREINSTALL_RETRY_LIBRARY', 'Process')
$env:BETA5_PREINSTALL_RETRY_LIBRARY = '1'
try { . (Join-Path $PSScriptRoot 'BETA5-PREINSTALL-RETRY.ps1') }
finally {
    if ($null -eq $previousLibraryFlag) { Remove-Item Env:BETA5_PREINSTALL_RETRY_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:BETA5_PREINSTALL_RETRY_LIBRARY = $previousLibraryFlag }
}

function Assert-True([string] $Name, [bool] $Value) {
    if (-not $Value) { throw "Assertion failed: $Name" }
}

function Assert-Throws([string] $Name, [scriptblock] $Action) {
    try {
        & $Action
        throw "Assertion failed: $Name did not throw"
    } catch {
        if ($_.Exception.Message -like 'Assertion failed:*') { throw }
    }
}

$missionRoot = 'C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630'
$identity = [pscustomobject]@{
    mission = 'beta5-sep8-be1260bd0630'
    candidate_source_sha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    build_source_sha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    gate_a_source_sha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    expected_hostname = 'DESKTOP-VBMA6O5'
    hostname = 'DESKTOP-VBMA6O5'
    build_run_id = '34237280539'
    expected_version = '1.0.0-beta.5'
    expected_manifest_sha256 = '97fe8a28fcbadf92abe31d7ae747fa6ef7fe905bff5c72cc99ff9fa6bf1be43a'
    expected_installer_sha256 = '5b3fec96cac6bd76cfc88fc7993f5e731d9b945d6606dd4c28f9a256c2c8b7e0'
    tester_root = 'C:\CivicCastSoak'
    mission_state_root = $missionRoot
    return_repo_path = (Join-Path $missionRoot 'return-repo')
    actual_manifest_sha256 = $null
    actual_installer_sha256 = $null
    artifacts_verified_utc = $null
    installed_utc = $null
    installed_service_process_id = $null
    approved_assets = $null
    retry_install_started_utc = $null
}
$goodLog = [pscustomobject]@{
    inspected = $true
    known_failure_categories = @('property_missing', 'native_command_error')
    missing_property_names = @('sha256')
    mentioned_script_filenames = @('AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1')
    script_locations = @()
    line_character_locations = @(
        [pscustomobject]@{ line = 56; character = 1 }
        [pscustomobject]@{ line = 51; character = 1 }
    )
}
$diagnostic = [pscustomobject]@{
    diagnostic_status = 'COLLECTED'
    mission = 'beta5-sep8-be1260bd0630'
    candidate_source_sha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
    hostname = 'DESKTOP-VBMA6O5'
    collected_utc = '2026-09-08T00:30:00Z'
    known_original_log_signals = @($goodLog)
    service = [pscustomobject]@{ state = 'Running'; process_id = 4711 }
}
$now = [datetimeoffset]'2026-09-08T01:00:00Z'

Assert-PreinstallRetryFacts $identity $diagnostic $now
Assert-True 'positive reviewed retry facts accepted' $true

$wrongIdentity = $identity | Select-Object *
$wrongIdentity.mission = 'other-mission'
Assert-Throws 'wrong mission rejected' { Assert-PreinstallRetryFacts $wrongIdentity $diagnostic $now }

$wrongSource = $identity | Select-Object *
$wrongSource.build_source_sha = '0000000000000000000000000000000000000000000000000000000000000000'
Assert-Throws 'wrong build source rejected' { Assert-PreinstallRetryFacts $wrongSource $diagnostic $now }

$wrongBuild = $identity | Select-Object *
$wrongBuild.build_run_id = '0'
Assert-Throws 'wrong build rejected' { Assert-PreinstallRetryFacts $wrongBuild $diagnostic $now }

$wrongRoot = $identity | Select-Object *
$wrongRoot.tester_root = 'C:\OtherRoot'
Assert-Throws 'wrong tester root rejected' { Assert-PreinstallRetryFacts $wrongRoot $diagnostic $now }

$progressed = $identity | Select-Object *
$progressed.installed_utc = '2026-09-08T00:45:00Z'
Assert-Throws 'progressed identity rejected' { Assert-PreinstallRetryFacts $progressed $diagnostic $now }

$stale = $diagnostic | Select-Object *
$stale.collected_utc = '2026-09-07T22:59:00Z'
Assert-Throws 'stale diagnostic rejected' { Assert-PreinstallRetryFacts $identity $stale $now }

$future = $diagnostic | Select-Object *
$future.collected_utc = '2026-09-08T01:01:00Z'
Assert-Throws 'future diagnostic rejected' { Assert-PreinstallRetryFacts $identity $future $now }

$wrongLine = $diagnostic | Select-Object *
$wrongLine.known_original_log_signals = @([pscustomobject]@{
    inspected = $true; known_failure_categories = @('property_missing', 'native_command_error')
    missing_property_names = @('sha256'); mentioned_script_filenames = @('AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1')
    script_locations = @([pscustomobject]@{ script = 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1'; line = 80 })
    line_character_locations = @([pscustomobject]@{ line = 51; character = 1 }, [pscustomobject]@{ line = 56; character = 1 })
})
Assert-Throws 'structured script location rejected' { Assert-PreinstallRetryFacts $identity $wrongLine $now }

$noPropertyFailure = $diagnostic | Select-Object *
$noPropertyFailure.known_original_log_signals = @([pscustomobject]@{
    inspected = $true; known_failure_categories = @('native_command_error')
    missing_property_names = @('sha256'); mentioned_script_filenames = @('AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1')
    script_locations = @(); line_character_locations = @([pscustomobject]@{ line = 51; character = 1 }, [pscustomobject]@{ line = 56; character = 1 })
})
Assert-Throws 'missing property category rejected' { Assert-PreinstallRetryFacts $identity $noPropertyFailure $now }

$wrongOuterLines = $diagnostic | Select-Object *
$wrongOuterLines.known_original_log_signals = @([pscustomobject]@{
    inspected = $true; known_failure_categories = @('property_missing', 'native_command_error')
    missing_property_names = @('sha256'); mentioned_script_filenames = @('AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1')
    script_locations = @(); line_character_locations = @([pscustomobject]@{ line = 50; character = 1 }, [pscustomobject]@{ line = 56; character = 1 })
})
Assert-Throws 'unexpected outer line rejected' { Assert-PreinstallRetryFacts $identity $wrongOuterLines $now }

$noOldService = $diagnostic | Select-Object *
$noOldService.service = [pscustomobject]@{ state = 'Stopped'; process_id = 4711 }
Assert-Throws 'no observed old service rejected' { Assert-PreinstallRetryFacts $identity $noOldService $now }

Write-Host 'PASS: pre-install retry facts accept only the exact unprogressed candidate diagnosis.'
