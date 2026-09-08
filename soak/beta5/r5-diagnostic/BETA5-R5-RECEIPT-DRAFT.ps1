# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Bounded R5 receipt collector; reads only when called by the explicit launcher.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:R5Host = 'DESKTOP-VBMA6O5'
$script:R5Mission = 'beta5-sep8-be1260bd0630'
$script:R5Candidate = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$script:R5Root = 'C:\CivicCastSoak'

function Assert-Beta5R5Root {
    param([Parameter(Mandatory)][string] $Root)
    $actual = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    if (-not $actual.Equals($script:R5Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'R5 collector requires the exact C:\CivicCastSoak root.'
    }
    $actual
}

function Get-Beta5R5Scalar {
    param([Parameter(Mandatory)] $Object, [Parameter(Mandatory)][string] $Name)
    $property = @($Object.PSObject.Properties | Where-Object { $_.Name -ceq $Name }) | Select-Object -First 1
    if ($null -eq $property) { return $null }
    $value = $property.Value
    if ($null -eq $value -or $value -is [System.Management.Automation.PSObject] -or ($value -is [System.Collections.IEnumerable] -and $value -isnot [string])) { return $null }
    "$value"
}

function Get-Beta5R5JsonSummary {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][scriptblock] $JsonReader)
    try { $object = & $JsonReader $Path } catch { return [ordered]@{ path=$Path; present=$true; valid_json=$false; error_type=$_.Exception.GetType().Name } }
    if ($null -eq $object) { return [ordered]@{ path=$Path; present=$false; valid_json=$false; error_type=$null } }
    $fields = [ordered]@{}
    foreach ($name in @('mission','candidate_source_sha','build_source_sha','gate_a_source_sha','build_run_id','expected_version','expected_hostname','hostname','expected_manifest_sha256','actual_manifest_sha256','expected_installer_sha256','actual_installer_sha256','artifacts_verified_utc','installed_utc','installed_service_process_id','retry_install_started_utc','installed_service_path','installed_service_started_utc','approved_assets','verdict','reason','status','error_type','pid_change_count','nonzero_pid_change_count','installed_version','installer_product_version','installer_authenticode_status','installer_signer','native_app_payload_source_sha','native_app_payload_sha256','installed_service_process_started_utc','expected_runtime_file_sha256','actual_runtime_file_sha256')) {
        $fields[$name] = Get-Beta5R5Scalar $object $name
    }
    foreach ($mapName in @('expected_runtime_file_sha256','actual_runtime_file_sha256')) {
        $hashes = [ordered]@{}
        $mapProperty = $object.PSObject.Properties[$mapName]
        foreach ($relative in @('Lib/site-packages/civiccast/egress/daemon.py','Lib/site-packages/civiccast/egress/gst/strategy.py')) {
            $value = $null
            if ($null -ne $mapProperty -and $null -ne $mapProperty.Value) {
                $entry = $mapProperty.Value.PSObject.Properties[$relative]
                if ($null -ne $entry -and "$($entry.Value)" -match '^[0-9a-fA-F]{64}$') { $value = "$($entry.Value)".ToLowerInvariant() }
            }
            $hashes[$relative] = $value
        }
        $fields[$mapName] = $hashes
    }
    $assetsProperty = $object.PSObject.Properties['approved_assets']
    $fields['approved_assets'] = $null
    $fields['approved_asset_count'] = $(if ($null -ne $assetsProperty -and $null -ne $assetsProperty.Value) { @($assetsProperty.Value).Count } else { $null })
    [ordered]@{ path=$Path; present=$true; valid_json=$true; fields=$fields }
}

function Get-Beta5R5JournalSummary {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][scriptblock] $JsonReader)
    $summary = Get-Beta5R5JsonSummary $Path $JsonReader
    if (-not $summary.valid_json -or -not $summary.present) { return $summary }
    $object = & $JsonReader $Path
    [ordered]@{ path=$Path; present=$true; valid_json=$true; last_stage=(Get-Beta5R5Scalar $object 'stage'); status=(Get-Beta5R5Scalar $object 'status'); error_type=(Get-Beta5R5Scalar $object 'error_type'); history_available=$false; note='Single retry-journal.json is last-state-only; it does not prove every prior step transition.' }
}

function Get-Beta5R5LogStageSummary {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][scriptblock] $LogReader)
    try { $content = & $LogReader $Path } catch { return [ordered]@{ path=$Path; present=$true; bounded_read=$false; error_type=$_.Exception.GetType().Name } }
    if ($null -eq $content) { return [ordered]@{ path=$Path; present=$false; bounded_read=$false; error_type=$null } }
    if ("$content".Length -gt 4MB) { return [ordered]@{ path=$Path; present=$true; bounded_read=$false; skipped_oversize=$true; error_type=$null } }
    $text = "$content"
    $stages = [ordered]@{}
    $patterns = [ordered]@{ selector='(?m)^CTRL reload: switching selector\s*$'; hold='(?m)^CTRL reload: holds released\s*$'; dispose='(?m)^CTRL reload: old leg disposed\s*$'; commit='(?m)^CTRL reload committed(?: \(elements=\d+\))?\s*$' }
    foreach ($stage in $patterns.Keys) { $stages[$stage] = [regex]::Matches($text, $patterns[$stage]).Count }
    $frames = @()
    foreach ($line in @(2720,2730)) {
        if ([regex]::IsMatch($text, "(?im)_dispose_source_leg[^\r\n]*(?:line\s*)?$line|(?:line\s*)?$line[^\r\n]*_dispose_source_leg")) { $frames += [ordered]@{ function='_dispose_source_leg'; line=$line } }
    }
    [ordered]@{ path=$Path; present=$true; bounded_read=$true; skipped_oversize=$false; error_type=$null; stage_counts=$stages; stack_frames=@($frames); raw_text_exported=$false }
}

function Get-Beta5R5Receipt {
    param(
        [Parameter(Mandatory)][string] $Root,
        [Parameter(Mandatory)][scriptblock] $FileReader,
        [Parameter(Mandatory)][scriptblock] $JsonReader,
        [Parameter(Mandatory)][scriptblock] $LogReader
    )
    $rootFull = Assert-Beta5R5Root $Root
    $missionRoot = Join-Path (Join-Path $rootFull 'missions') $script:R5Mission
    $returnMission = Join-Path $missionRoot 'return-repo\soak\beta5\beta5-sep8-be1260bd0630'
    $identityPath = Join-Path $missionRoot 'run-identity.json'
    $retryReceiptPath = Join-Path $missionRoot 'install-retry-r1-dispatch\install-retry-r1.json'
    $journalPath = Join-Path $missionRoot 'install-retry-r1\retry-journal.json'
    $verdictPath = Join-Path $returnMission 'final-verdict.json'
    $logDir = Join-Path $rootFull 'reports'
    $receipt = [ordered]@{
        schema='civiccast-native-beta5-r5-receipt-v1'; host=$script:R5Host; mission=$script:R5Mission; candidate_source_sha=$script:R5Candidate
        observed_utc=[DateTime]::UtcNow.ToString('o')
        report_kind='bounded diagnostic only; not an installation, media, or terminal acceptance verdict'
        identity=(Get-Beta5R5JsonSummary $identityPath $JsonReader)
        retry_dispatch=(Get-Beta5R5JsonSummary $retryReceiptPath $JsonReader)
        retry_journal=(Get-Beta5R5JournalSummary $journalPath $JsonReader)
        final_verdict=(Get-Beta5R5JsonSummary $verdictPath $JsonReader)
        log_signals=@()
        raw_contents_exported=$false; command_lines_exported=$false; secrets_exported=$false
    }
    $logItems = @(& $FileReader $logDir)
    foreach ($item in $logItems | Select-Object -First 3) { $receipt.log_signals += ,(Get-Beta5R5LogStageSummary $item.FullName $LogReader) }
    $receipt
}

function Assert-Beta5R5PlainPath {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][string] $Root)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Path)
    if (-not ($full.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'R5 path escapes the exact tester root.' }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'R5 path crosses a reparse point.' }
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    $full
}

function Assert-Beta5R5WithinRoot {
    param([Parameter(Mandatory)][string] $Path, [Parameter(Mandatory)][string] $Root)
    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Path)
    if (-not ($full.Equals($rootFull, [StringComparison]::OrdinalIgnoreCase) -or $full.StartsWith($rootFull + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'R5 path escapes its bounded read root.' }
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'R5 path crosses a reparse point.' }
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent
    }
    $full
}

function Get-Beta5R5ActualFileReader {
    param([Parameter(Mandatory)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    Get-Item -LiteralPath $Path -Force
}

function Get-Beta5R5ActualJsonReader {
    param([Parameter(Mandatory)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Length -gt 1MB) { throw 'R5 JSON input exceeds the bounded read limit.' }
    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Get-Beta5R5ActualLogReader {
    param([Parameter(Mandatory)][string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.Length -gt 4MB) { throw 'R5 log input exceeds the bounded read limit.' }
    Get-Content -LiteralPath $Path -Raw
}

function Get-Beta5R5ActualLogFiles {
    param([Parameter(Mandatory)][string] $Directory)
    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) { return @() }
    @(Get-ChildItem -LiteralPath $Directory -File -Force | Where-Object { $_.Name -cmatch '^AUTORUN-SEP8-BETA5-BE1260-R1-\d{8}T\d{6}Z\.log$' } | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 3)
}

function Get-Beta5R5ActualWorkerLogFiles {
    param([string] $BaseRoot = 'C:\ProgramData\CivicCast\data\egress')
    $base = [IO.Path]::GetFullPath($BaseRoot).TrimEnd('\')
    $items = @()
    foreach ($channel in @('public','education','government')) {
        foreach ($stream in @('stdout','stderr')) {
            $path = Join-Path $base "$channel\logs\gst-worker.$stream.log"
            try { $null = Assert-Beta5R5WithinRoot $path $base } catch { throw "Worker log path failed its bounded-root check: $path" }
            if (Test-Path -LiteralPath $path -PathType Leaf) { $items += Get-Item -LiteralPath $path -Force }
        }
    }
    @($items)
}

function Get-Beta5R5ActualReceipt {
    param([Parameter(Mandatory)][string] $Root)
    $rootFull = Assert-Beta5R5Root $Root
    if ("$env:COMPUTERNAME" -ine $script:R5Host) { throw 'R5 collector targets the dedicated tester hostname only.' }
    $missionRoot = Join-Path (Join-Path $rootFull 'missions') $script:R5Mission
    $logDir = Join-Path $rootFull 'reports'
    # Validate every path before any adapter opens it.  This keeps a junction or
    # symlink from redirecting an otherwise bounded read outside the tester root.
    $paths = @(
        (Join-Path $missionRoot 'run-identity.json')
        (Join-Path $missionRoot 'install-retry-r1-dispatch\install-retry-r1.json')
        (Join-Path $missionRoot 'install-retry-r1\retry-journal.json')
        (Join-Path $missionRoot 'return-repo\soak\beta5\beta5-sep8-be1260bd0630\final-verdict.json')
        $logDir
    )
    foreach ($path in $paths) { $null = Assert-Beta5R5PlainPath $path $rootFull }
    $receipt = Get-Beta5R5Receipt -Root $rootFull -FileReader { param($p) Get-Beta5R5ActualLogFiles $p } -JsonReader { param($p) Get-Beta5R5ActualJsonReader $p } -LogReader { param($p) Get-Beta5R5ActualLogReader $p }
    $receipt.path_guards = $paths
    $receipt.processes = @(Get-Beta5R5ActualProcessMetadata)
    $receipt.service = Get-Beta5R5ActualServiceMetadata
    $receipt.current_runtime_file_sha256 = [ordered]@{}
    $runtimeRoot = 'C:\CivicCastHostStore\install\runtime'
    foreach ($relative in @('Lib/site-packages/civiccast/egress/daemon.py','Lib/site-packages/civiccast/egress/gst/strategy.py')) {
        $path = Assert-Beta5R5WithinRoot (Join-Path $runtimeRoot $relative) $runtimeRoot
        $receipt.current_runtime_file_sha256[$relative] = $(if (Test-Path -LiteralPath $path -PathType Leaf) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null })
    }
    $receipt.worker_log_signals = @((Get-Beta5R5ActualWorkerLogFiles) | ForEach-Object { Get-Beta5R5LogStageSummary $_.FullName { param($p) Get-Beta5R5ActualLogReader $p } })
    $receipt.process_command_lines_exported = $false
    $receipt
}

function Get-Beta5R5ActualProcessMetadata {
    # Names/PIDs are diagnostic metadata only; command lines and environment are
    # deliberately excluded because they can contain credentials.
    $names = @('CivicCast (Native)_1.0.0-beta.5_x64-setup.exe','setup.exe','powershell.exe','pwsh.exe','tar.exe','curl.exe')
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $names -ccontains $_.Name } | ForEach-Object {
        [ordered]@{ name="$($_.Name)"; process_id=[int]$_.ProcessId; parent_process_id=[int]$_.ParentProcessId; creation_time="$($_.CreationDate)" }
})
}

function Get-Beta5R5ActualServiceMetadata {
    # Win32_Service PathName is a command line. Return only its executable.
    $service = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $service) { return [ordered]@{ present=$false; name='CivicCastSupervisor'; status=$null; process_id=$null; executable_path=$null } }
    $pathName = "$($service.PathName)".Trim()
    $executable = $null
    if ($pathName.StartsWith('"')) {
        $closing = $pathName.IndexOf('"', 1)
        if ($closing -gt 1) { $executable = $pathName.Substring(1, $closing - 1) }
    } elseif ($pathName) {
        $match = [regex]::Match($pathName, '^(.*?\.exe)(?:\s|$)', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($match.Success) { $executable = $match.Groups[1].Value }
    }
    [ordered]@{ present=$true; name="$($service.Name)"; status="$($service.State)"; process_id=if($service.ProcessId){[int]$service.ProcessId}else{$null}; executable_path=$executable }
}

if ($env:BETA5_R5_RECEIPT_LIBRARY -eq '1') { return }
if (-not $DryRun) { throw 'Invoke through the explicit read-only R5 launcher; this file only defines the collector.' }
[ordered]@{ schema='civiccast-native-beta5-r5-receipt-v1'; host=$script:R5Host; mission=$script:R5Mission; candidate_source_sha=$script:R5Candidate; dry_run=$true; action='Read-only collector; launch with Invoke-BETA5-R5-RECEIPT-DRAFT.ps1 -Execute.' } | ConvertTo-Json
