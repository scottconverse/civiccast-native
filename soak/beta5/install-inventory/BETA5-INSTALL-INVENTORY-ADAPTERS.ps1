# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Read-only adapters. Dot-sourcing defines functions; it does not collect data.
Set-StrictMode -Version Latest

function Assert-Beta5InventoryPlainPath {
    param([Parameter(Mandatory)][string] $Path)
    $full = [IO.Path]::GetFullPath($Path)
    $cursor = $full
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Inventory path crosses a reparse point.' }
        }
        $next = Split-Path -Parent $cursor
        if (-not $next -or $next -eq $cursor) { break }
        $cursor = $next
    }
    return $full
}

function Read-Beta5InventoryFile {
    param([string] $Path)
    $null = Assert-Beta5InventoryPlainPath $Path
    if (Test-Path -LiteralPath $Path -PathType Leaf) { Get-Item -LiteralPath $Path }
}

function Read-Beta5InventoryIdentity {
    param([string] $Path)
    $item = Read-Beta5InventoryFile $Path
    if ($null -eq $item) { return $null }
    if ($item.Length -gt 1MB) { throw 'Identity receipt exceeds inventory limit.' }
    Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Read-Beta5InventoryProcesses {
    param([string[]] $Names)
    foreach ($process in @(Get-CimInstance Win32_Process -Property Name,ProcessId,ParentProcessId,CreationDate,KernelModeTime,UserModeTime)) {
        if ($Names -notcontains $process.Name) { continue }
        [pscustomobject]@{
            Name = $process.Name; Id = $process.ProcessId; ParentProcessId = $process.ParentProcessId
            StartTimeUtc = $process.CreationDate
            CpuSeconds = ([double] $process.KernelModeTime + [double] $process.UserModeTime) / 10000000
        }
    }
}

function Read-Beta5InventoryService {
    param([string] $Name)
    if ($Name -cne 'CivicCastSupervisor') { throw 'Unexpected service inventory target.' }
    $service = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -Property Name,State,ProcessId,PathName
    if ($null -eq $service) { return $null }
    $started = $null
    if ($service.ProcessId -gt 0) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$service.ProcessId)" -Property CreationDate
        if ($null -ne $process) { $started = $process.CreationDate }
    }
    [pscustomobject]@{ State = $service.State; ProcessId = $service.ProcessId; PathName = $service.PathName; StartTimeUtc = $started }
}

function Read-Beta5InventoryKit {
    param([string] $Path)
    $root = Assert-Beta5InventoryPlainPath $Path
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return }
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($root)
    $count = 0
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            $count++
            if ($count -gt 200) { throw 'Kit inventory exceeds its bounded entry count.' }
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Kit inventory encountered a reparse point.' }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) } else { $item }
        }
    }
}

function Read-Beta5InventoryLogs {
    param([string] $Directory, [string] $Prefix)
    $null = Assert-Beta5InventoryPlainPath $Directory
    if ($Prefix -cne 'AUTORUN-SEP8-BETA5-BE1260-R1-') { throw 'Unexpected original autorun log prefix.' }
    if (Test-Path -LiteralPath $Directory -PathType Container) {
        Get-ChildItem -LiteralPath $Directory -File -Filter ($Prefix + '*.log') | Where-Object {
            ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0
        }
    }
}

function Get-Beta5KnownInstallLogSignals {
    param([Parameter(Mandatory)][string] $Path)
    # Inspect only bounded original-autorun text internally. Never return any text,
    # match capture, arbitrary exception, token or command line from that log.
    $name = [IO.Path]::GetFileName($Path)
    if ($name -cnotmatch '^AUTORUN-SEP8-BETA5-BE1260-R1-\d{8}T\d{6}Z\.log$') { throw 'Unexpected log classifier filename.' }
    $item = Read-Beta5InventoryFile $Path
    $result = [ordered]@{
        path = $Path; bytes = $(if ($null -eq $item) { $null } else { $item.Length })
        inspected = $false; skipped_oversize = $false
        ffprobe_lookup_failure = $false; fetch_verify_upgrade_pass = $false
        exact_signature_rejection = $false; raw_log_exported = $false
        known_failure_categories = @(); script_locations = @(); powershell_error_categories = @()
    }
    if ($null -eq $item) { return [pscustomobject] $result }
    if ($item.Length -gt 4MB) { $result.skipped_oversize = $true; return [pscustomobject] $result }
    $content = Get-Content -LiteralPath $Path -Raw
    if ($null -ne $content) {
        $result.ffprobe_lookup_failure = $content.Contains('Installed ffprobe.exe is required for gap-free schedule durations.')
        $result.fetch_verify_upgrade_pass = $content.Contains('FETCH/VERIFY/UPGRADE PASS: 1.0.0-beta.5, manifest+installer hashes independent, signer Scott Converse, service running from C:\CivicCastHostStore\install.')
        $result.exact_signature_rejection = $content.Contains('Installer signature is not Valid and signed by Scott Converse')
        $phrases = [ordered]@{
            download_failed = 'Download failed:'
            manifest_hash_mismatch = 'does not equal the independently supplied hash.'
            entry_hash_mismatch = 'Manifest mismatch after download:'
            app_manifest_read_failed = 'Could not read native-app-payload.ccpack manifest.json.'
            app_signature_missing = 'Native app payload has no embedded manifest signature.'
            app_identity_mismatch = 'Native app payload manifest does not bind the clean expected candidate source/version.'
            runtime_manifest_binding_failed = 'Native app payload manifest does not uniquely bind'
            installer_hash_mismatch = 'Installer hash does not equal the independently supplied installer hash.'
            installer_version_mismatch = 'Installer ProductVersion'
            native_archive_member_missing = 'Not found in archive'
            property_missing = 'cannot be found on this object'
            sha256_property_missing = "The property 'sha256' cannot be found"
            variable_unset = 'has not been set'
            native_command_error = 'NativeCommandError'
        }
        foreach ($key in $phrases.Keys) {
            if ($content.Contains($phrases[$key])) { $result.known_failure_categories += $key }
        }
        $compactLocationText = [regex]::Replace($content, '\s+', '')
        foreach ($match in [regex]::Matches($compactLocationText, '(AUTORUN-SEP8-BETA5-(?:01-PREFLIGHT|02-FETCH-INSTALL|03-START-SOAK)\.ps1):(\d+)char:(\d+)')) {
            $result.script_locations += [pscustomobject]@{ script = $match.Groups[1].Value; line = [int]$match.Groups[2].Value; character = [int]$match.Groups[3].Value }
        }
        foreach ($match in [regex]::Matches($content, '(?m)^\s*\+?\s*CategoryInfo\s*:\s*([A-Za-z]+)\s*:')) {
            $result.powershell_error_categories += $match.Groups[1].Value
        }
    }
    $result.inspected = $true
    return [pscustomobject] $result
}

function Get-Beta5LiveInstallInventory {
    param([Parameter(Mandatory)][string] $Root)
    Assert-Beta5InventoryHost "$env:COMPUTERNAME"
    Assert-Beta5InventoryRoot $Root
    $snapshot = Get-Beta5InventorySnapshot -ActualHostname "$env:COMPUTERNAME" -Root $Root `
        -FileReader ${function:Read-Beta5InventoryFile} -JsonReader ${function:Read-Beta5InventoryIdentity} `
        -ProcessReader ${function:Read-Beta5InventoryProcesses} -ServiceReader ${function:Read-Beta5InventoryService} `
        -KitReader ${function:Read-Beta5InventoryKit} -LogReader ${function:Read-Beta5InventoryLogs}
    $signals = @($snapshot.original_autorun_logs | ForEach-Object { Get-Beta5KnownInstallLogSignals $_.path })
    $snapshot | Add-Member -NotePropertyName known_original_log_signals -NotePropertyValue $signals
    $snapshot | Add-Member -NotePropertyName collected_utc -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o'))
    $snapshot | Add-Member -NotePropertyName qualification -NotePropertyValue 'Diagnostic metadata and exact known log phrases only. Identity binding is not installed-source or soak acceptance.'
    $snapshot | Add-Member -NotePropertyName process_qualification -NotePropertyValue 'Selected generic helper names may include unrelated processes. Metadata does not establish association with this candidate install; no process command line was collected.'
    $snapshot.safety = 'No raw log text, process command lines, tokens, passwords, or credentials exported. At most 3 original autorun logs of at most 4MiB each inspected for fixed boolean signals.'
    return $snapshot
}
