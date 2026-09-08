# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# INERT DRAFT ONLY. Safe metadata inventory for an owner-reviewed future wrapper.
# It never reads log contents, process command lines, tokens, or credentials.
[CmdletBinding()]
param(
    [switch] $DryRun,
    [string] $TesterRoot = 'C:\CivicCastSoak'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:InventoryCandidateSha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$script:InventoryBuildRunId = '34237280539'
$script:InventoryHostname = 'DESKTOP-VBMA6O5'
$script:InventoryMission = 'beta5-sep8-be1260bd0630'

function Get-Beta5InventoryPlan {
    param([Parameter(Mandatory)][string] $Root)
    $missionRoot = Join-Path (Join-Path $Root 'missions') $script:InventoryMission
    [pscustomobject][ordered]@{
        schema = 'civiccast-native-beta5-install-inventory-draft-v1'
        candidate_source_sha = $script:InventoryCandidateSha
        build_run_id = $script:InventoryBuildRunId
        hostname = $script:InventoryHostname
        mission = $script:InventoryMission
        tester_root = $Root
        marker_paths = @(
            (Join-Path $missionRoot 'run-identity.json')
            (Join-Path $missionRoot 'soak-state.json')
            (Join-Path (Join-Path $missionRoot 'return-repo\soak\beta5') ($script:InventoryMission + '\final-verdict.json'))
        )
        install_progress_path = 'C:\ProgramData\CivicCast\install-progress.log'
        original_autorun_log_directory = (Join-Path $Root 'reports')
        original_autorun_log_prefix = 'AUTORUN-SEP8-BETA5-BE1260-R1-'
        kit_root = (Join-Path $Root ('kit-' + $script:InventoryCandidateSha))
        process_names = @('CivicCast (Native)_1.0.0-beta.5_x64-setup.exe', 'setup.exe', 'civiccast-installer.exe', 'tar.exe', 'curl.exe', 'powershell.exe', 'pwsh.exe')
        service_name = 'CivicCastSupervisor'
        output_policy = 'metadata only: paths, presence, size, mtime, PID, parent PID, start time, service path; never contents, command lines, tokens, or credentials'
    }
}

function Assert-Beta5InventoryRoot {
    param([Parameter(Mandatory)][string] $Root)
    $expected = [System.IO.Path]::GetFullPath('C:\CivicCastSoak').TrimEnd('\')
    $actual = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (-not $actual.Equals($expected, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Inventory root must be exactly C:\CivicCastSoak."
    }
}

function Assert-Beta5InventoryHost {
    param([Parameter(Mandatory)][string] $ActualHostname)
    if ($ActualHostname -cne $script:InventoryHostname) {
        throw "Inventory is only for $($script:InventoryHostname)."
    }
}

function Get-Beta5InventoryFileMetadata {
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][scriptblock] $FileReader
    )
    $item = & $FileReader $Path
    if ($null -eq $item) {
        return [pscustomobject][ordered]@{ path = $Path; present = $false; size_bytes = $null; modified_utc = $null }
    }
    [pscustomobject][ordered]@{
        path = $Path
        present = $true
        size_bytes = [int64] $item.Length
        modified_utc = ([datetime] $item.LastWriteTimeUtc).ToString('o')
    }
}

function Get-Beta5InventoryExecutablePath {
    param([AllowNull()][string] $PathName)
    if ([string]::IsNullOrWhiteSpace($PathName)) { return $null }
    $value = $PathName.Trim()
    if ($value.StartsWith('"')) {
        $closing = $value.IndexOf('"', 1)
        if ($closing -lt 2) { return $null }
        return $value.Substring(1, $closing - 1)
    }
    if (-not $value) { return $null }
    $match = [regex]::Match($value, '^(.+?\.exe)(?:\s+.*)?$', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($match.Success) { return $match.Groups[1].Value }
    return ($value -split '\s+', 2)[0]
}

function Get-Beta5InventoryPropertyValue {
    param([Parameter(Mandatory)][object] $Object, [Parameter(Mandatory)][string] $Name)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-Beta5InventoryJsonSummary {
    param(
        [Parameter(Mandatory)][string] $Path,
        [Parameter(Mandatory)][scriptblock] $JsonReader
    )
    try { $identity = & $JsonReader $Path } catch { return [pscustomobject][ordered]@{ path = $Path; present = $true; valid_json = $false; receipt_matches_expected = $false; mismatches = @('invalid_json') } }
    if ($null -eq $identity) { return [pscustomobject][ordered]@{ path = $Path; present = $false; valid_json = $false; receipt_matches_expected = $false; mismatches = @('missing_identity') } }
    $allowed = @('schema','mission','candidate_source_sha','build_source_sha','gate_a_source_sha','build_run_id','expected_version','hostname','expected_hostname','installed_version','installed_schema','installed_location','installed_service_path','installed_service_process_id','installed_service_process_started_utc','installed_utc','actual_manifest_sha256','actual_installer_sha256','installer_authenticode_status','installer_signer')
    $summary = [ordered]@{ path = $Path; present = $true; valid_json = $true; receipt_matches_expected = $true; mismatches = @() }
    foreach ($name in $allowed) {
        $property = $identity.PSObject.Properties[$name]
        if ($null -ne $property) {
            if ($null -eq $property.Value) { $summary.valid_json = $false; $summary.receipt_matches_expected = $false; $summary.mismatches += $name; continue }
            if ($property.Value -is [System.Collections.IDictionary] -or $property.Value -is [System.Array] -or $property.Value -is [pscustomobject] -and $property.Value -isnot [string]) {
                $summary.valid_json = $false
                continue
            }
            $summary[$name] = if ($name -eq 'installed_service_path') { Get-Beta5InventoryExecutablePath "$($property.Value)" } else { $property.Value }
        }
    }
    foreach ($expected in @{
        schema = 'civiccast-native-tester-run-identity-v3'; mission = $script:InventoryMission
        candidate_source_sha = $script:InventoryCandidateSha; build_source_sha = $script:InventoryCandidateSha
        gate_a_source_sha = $script:InventoryCandidateSha; build_run_id = $script:InventoryBuildRunId
        expected_hostname = $script:InventoryHostname; hostname = $script:InventoryHostname
    }.GetEnumerator()) {
        if (-not $summary.Contains($expected.Key) -or "$($summary[$expected.Key])" -cne "$($expected.Value)") { $summary.receipt_matches_expected = $false; $summary.mismatches += $expected.Key }
    }
    if (-not $summary.valid_json) { $summary.receipt_matches_expected = $false; $summary.mismatches += 'non_scalar_allowlisted_field' }
    [pscustomobject] $summary
}

function Get-Beta5InventoryAutorunLogMetadata {
    param(
        [Parameter(Mandatory)][string] $Directory,
        [Parameter(Mandatory)][string] $Prefix,
        [Parameter(Mandatory)][scriptblock] $LogReader
    )
    $directoryFull = [System.IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $directoryPrefix = $directoryFull + '\'
    @(& $LogReader $Directory $Prefix | Where-Object {
        $full = [System.IO.Path]::GetFullPath("$($_.FullName)")
        $name = [System.IO.Path]::GetFileName($full)
        $full.StartsWith($directoryPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
            $name -match '^AUTORUN-SEP8-BETA5-BE1260-R1-\d{8}T\d{6}Z\.log$'
    } | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 3 | ForEach-Object {
        [pscustomobject][ordered]@{ path = $_.FullName; present = $true; size_bytes = [int64] $_.Length; modified_utc = ([datetime] $_.LastWriteTimeUtc).ToString('o') }
    })
}

function Get-Beta5InventoryProcessMetadata {
    param(
        [Parameter(Mandatory)][string[]] $Names,
        [Parameter(Mandatory)][scriptblock] $ProcessReader
    )
    @(& $ProcessReader $Names | ForEach-Object {
        $processId = Get-Beta5InventoryPropertyValue -Object $_ -Name 'Id'
        $parentProcessId = Get-Beta5InventoryPropertyValue -Object $_ -Name 'ParentProcessId'
        $startedUtc = Get-Beta5InventoryPropertyValue -Object $_ -Name 'StartTimeUtc'
        $cpuSeconds = Get-Beta5InventoryPropertyValue -Object $_ -Name 'CpuSeconds'
        [pscustomobject][ordered]@{
            name = Get-Beta5InventoryPropertyValue -Object $_ -Name 'Name'
            process_id = if ($null -eq $processId) { $null } else { [int64] $processId }
            parent_process_id = if ($null -eq $parentProcessId) { $null } else { [int64] $parentProcessId }
            started_utc = if ($null -eq $startedUtc) { $null } else { ([datetime] $startedUtc).ToString('o') }
            cpu_seconds = if ($null -eq $cpuSeconds) { $null } else { [double] $cpuSeconds }
        }
    })
}

function Get-Beta5InventorySnapshot {
    param(
        [Parameter(Mandatory)][string] $ActualHostname,
        [Parameter(Mandatory)][string] $Root,
        [Parameter(Mandatory)][scriptblock] $FileReader,
        [Parameter(Mandatory)][scriptblock] $JsonReader,
        [Parameter(Mandatory)][scriptblock] $ProcessReader,
        [Parameter(Mandatory)][scriptblock] $ServiceReader,
        [Parameter(Mandatory)][scriptblock] $KitReader,
        [Parameter(Mandatory)][scriptblock] $LogReader
    )
    Assert-Beta5InventoryHost $ActualHostname
    Assert-Beta5InventoryRoot $Root
    $plan = Get-Beta5InventoryPlan $Root
    $identityPath = $plan.marker_paths[0]
    $service = & $ServiceReader $plan.service_name
    $serviceSummary = if ($null -eq $service) { $null } else {
        $serviceProcessId = Get-Beta5InventoryPropertyValue -Object $service -Name 'ProcessId'
        $servicePathName = Get-Beta5InventoryPropertyValue -Object $service -Name 'PathName'
        $serviceStartedUtc = Get-Beta5InventoryPropertyValue -Object $service -Name 'StartTimeUtc'
        [pscustomobject][ordered]@{
            name = $plan.service_name
            state = Get-Beta5InventoryPropertyValue -Object $service -Name 'State'
            process_id = if ($null -eq $serviceProcessId) { $null } else { [int64] $serviceProcessId }
            executable_path = Get-Beta5InventoryExecutablePath $servicePathName
            started_utc = if ($null -eq $serviceStartedUtc) { $null } else { ([datetime] $serviceStartedUtc).ToString('o') }
        }
    }
    $kitFiles = @(& $KitReader $plan.kit_root)
    $kitTotalBytes = if ($kitFiles.Count -eq 0) { [int64] 0 } else { [int64] (@($kitFiles | Measure-Object -Property Length -Sum).Sum) }
    [pscustomobject][ordered]@{
        schema = $plan.schema
        candidate_source_sha = $plan.candidate_source_sha
        build_run_id = $plan.build_run_id
        hostname = $ActualHostname
        mission = $plan.mission
        identity = Get-Beta5InventoryJsonSummary $identityPath $JsonReader
        markers = @($plan.marker_paths | ForEach-Object { Get-Beta5InventoryFileMetadata $_ $FileReader })
        install_progress = Get-Beta5InventoryFileMetadata $plan.install_progress_path $FileReader
        original_autorun_logs = Get-Beta5InventoryAutorunLogMetadata $plan.original_autorun_log_directory $plan.original_autorun_log_prefix $LogReader
        service = $serviceSummary
        processes = Get-Beta5InventoryProcessMetadata $plan.process_names $ProcessReader
        kit_files_count = [int64] $kitFiles.Count
        kit_files_total_bytes = $kitTotalBytes
        safety = 'No log text, process command lines, tokens, passwords, or credentials collected.'
    }
}

if ($env:BETA5_INVENTORY_DRAFT_LIBRARY -eq '1') { return }
    if (-not $DryRun) { Assert-Beta5InventoryHost "$env:COMPUTERNAME" }
Assert-Beta5InventoryRoot $TesterRoot
$plan = Get-Beta5InventoryPlan $TesterRoot
if ($DryRun) { $plan | ConvertTo-Json -Depth 8; return }
throw 'INERT DRAFT: live adapters are not bound in this file.'
