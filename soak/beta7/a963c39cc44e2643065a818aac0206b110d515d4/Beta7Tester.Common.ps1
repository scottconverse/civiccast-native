# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-Beta5FullPath {
    param([Parameter(Mandatory)][string] $Path)
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-Beta5ChildPath {
    param(
        [Parameter(Mandatory)][string] $BasePath,
        [Parameter(Mandatory)][string] $CandidatePath,
        [switch] $AllowBase
    )
    $base = Get-Beta5FullPath $BasePath
    $candidate = Get-Beta5FullPath $CandidatePath
    if ($AllowBase -and $candidate.Equals($base, [StringComparison]::OrdinalIgnoreCase)) { return $candidate }
    $prefix = $base + [System.IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the required root '$base': $candidate"
    }
    $cursor = $candidate
    while ($cursor.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or $cursor.Equals($base, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Path crosses a reparse point: $cursor" }
        }
        if ($cursor.Equals($base, [StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent.TrimEnd('\')
    }
    return $candidate
}

function ConvertFrom-Beta5ManifestPath {
    param([Parameter(Mandatory)][string] $RelativePath)
    $relative = $RelativePath.Trim().TrimStart('*')
    if (-not $relative -or [System.IO.Path]::IsPathRooted($relative) -or $relative.StartsWith('/') -or $relative.StartsWith('\')) {
        throw "Manifest path is not relative: $RelativePath"
    }
    if ($relative.Contains(':')) { throw "Manifest path contains an alternate stream or drive prefix: $RelativePath" }
    $segments = @($relative -split '[\\/]')
    if ($segments.Count -eq 0 -or @($segments | Where-Object { -not $_ -or $_ -eq '.' -or $_ -eq '..' }).Count -gt 0) {
        throw "Manifest path contains an empty or traversal segment: $RelativePath"
    }
    return ($segments -join '\')
}

function Read-Beta5Manifest {
    param(
        [Parameter(Mandatory)][string] $ManifestPath,
        [Parameter(Mandatory)][string] $KitRoot
    )
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Kit manifest is absent: $ManifestPath" }
    $lines = @(Get-Content -LiteralPath $ManifestPath | Where-Object { $_.Trim() })
    if ($lines.Count -eq 0) { throw 'Kit manifest is empty.' }
    $seen = @{}
    $entries = @()
    foreach ($line in $lines) {
        if ($line -notmatch '^([0-9A-Fa-f]{64})\s+\*?(.+)$') { throw "Invalid SHA256SUMS line: $line" }
        $hash = $Matches[1].ToLowerInvariant()
        $manifestRelative = $Matches[2]
        $relative = ConvertFrom-Beta5ManifestPath $manifestRelative
        $key = $relative.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw "Duplicate manifest path: $relative" }
        $seen[$key] = $true
        $localPath = Join-Path $KitRoot $relative
        $null = Assert-Beta5ChildPath -BasePath $KitRoot -CandidatePath $localPath
        $entries += [pscustomobject]@{
            sha256 = $hash
            relative_path = $relative
            local_path = $localPath
        }
    }
    return @($entries)
}

function Get-Beta5Identity {
    param([Parameter(Mandatory)][string] $IdentityPath)
    if (-not (Test-Path -LiteralPath $IdentityPath -PathType Leaf)) { throw "Missing run identity: $IdentityPath" }
    $id = Get-Content -LiteralPath $IdentityPath -Raw | ConvertFrom-Json
    $required = @(
        'schema', 'mission', 'candidate_source_sha', 'build_source_sha', 'gate_a_source_sha',
        'expected_manifest_sha256', 'expected_installer_sha256', 'expected_version',
        'build_run_id', 'build_conclusion', 'gate_a_run_id', 'gate_a_verdict', 'kit_base_url',
        'return_repository_url', 'return_branch', 'hostname', 'expected_hostname', 'tester_root',
        'mission_state_root', 'return_repo_path', 'install_root', 'planned_seconds',
        'sample_interval_seconds', 'channels', 'expected_elements_per_phase'
    )
    foreach ($name in $required) {
        if ($id.PSObject.Properties.Name -notcontains $name) { throw "Run identity is missing required fact '$name'." }
    }
    if ($id.schema -ne 'civiccast-native-tester-run-identity-v3') { throw 'Unexpected identity schema.' }
    $templateFields = @()
    foreach ($name in 'candidate_source_sha', 'build_source_sha', 'gate_a_source_sha') {
        $value = "$($id.$name)"
        if ($value -ceq 'BETA7_SOURCE_SHA') { $templateFields += $name; continue }
        if ($value -notmatch '^[0-9a-fA-F]{40}$') { throw "Invalid $name." }
    }
    if ($id.build_source_sha -ne $id.candidate_source_sha -or $id.gate_a_source_sha -ne $id.candidate_source_sha) {
        throw 'Build and Gate A source SHAs must equal the candidate SHA.'
    }
    foreach ($name in 'expected_manifest_sha256', 'expected_installer_sha256') {
        $value = "$($id.$name)"
        if ($value -in @('MANIFEST_SHA256','INSTALLER_SHA256')) { $templateFields += $name; continue }
        if ($value -notmatch '^[0-9a-fA-F]{64}$') { throw "Invalid $name." }
    }
    if ("$($id.build_conclusion)" -cne 'success') { throw 'Candidate build conclusion is not exactly success.' }
    if ("$($id.gate_a_verdict)" -cne 'PASS') { throw 'Gate A verdict must be exactly PASS before install or soak.' }
    foreach ($name in 'build_run_id','gate_a_run_id') {
        $value = "$($id.$name)"
        if ($value -in @('BUILD_RUN_ID','GATE_A_RUN_ID')) { $templateFields += $name; continue }
        if ($value -notmatch '^\d+$' -or [int64] $value -le 0) {
            throw 'Build and Gate A run IDs must be positive numeric identifiers.'
        }
    }
    if ($templateFields.Count -gt 0) {
        throw "Run identity still contains beta.7 placeholders: $($templateFields -join ', ')"
    }
    $candidate = "$($id.candidate_source_sha)".ToLowerInvariant()
    $version = "$($id.expected_version)"
    $kitBase = "$($id.kit_base_url)"
    $isBeta7 = $candidate -match '^[0-9a-f]{40}$' -and
        $version -match '^1\.0\.0-beta\.7(?:[.+-][0-9A-Za-z.-]+)?$'
    if (-not $isBeta7) { throw 'Expected version is not the beta.7 contract; beta.5 and beta.6 are rejected.' }
    $kitUri = [uri] "$($id.kit_base_url)"
    if ($kitUri.Scheme -ne 'http' -or $kitUri.Port -ne 8766 -or $kitUri.Host -notin '192.168.0.135', '127.0.0.1', 'localhost') { throw 'Kit URL is not the approved local/LAN staging server.' }
    if ($kitBase -cne "http://192.168.0.135:8766/$candidate/") { throw 'Beta.7 kit URL is not bound to the exact candidate on the approved LAN server.' }
    if ($id.return_repository_url -ne 'https://github.com/scottconverse/civiccast-native.git') { throw 'Return repository URL is not the approved CivicCast repository.' }
    if ($id.hostname -ne $id.expected_hostname) { throw 'Identity hostname does not equal the explicitly expected tester hostname.' }
    if ("$env:COMPUTERNAME" -ne $id.expected_hostname) { throw "Identity targets '$($id.expected_hostname)', not this host '$env:COMPUTERNAME'." }
    if ($id.return_branch -ne "tester/soak8-e1acfe6-$($id.expected_hostname)") { throw 'Return branch is not bound to the expected tester hostname.' }
    if ([int] $id.planned_seconds -lt 7200) { throw 'Duration is below two hours.' }
    if ([int] $id.sample_interval_seconds -gt 60 -or [int] $id.sample_interval_seconds -lt 30) { throw 'Sample interval must be between 30 and 60 seconds.' }
    $missionRoot = Assert-Beta5ChildPath -BasePath $id.tester_root -CandidatePath $id.mission_state_root
    $null = Assert-Beta5ChildPath -BasePath $missionRoot -CandidatePath $id.return_repo_path
    if (-not [System.IO.Path]::IsPathRooted([string]$id.install_root)) { throw 'Identity install_root must be absolute.' }
    $expectedPhases=@($id.expected_elements_per_phase.PSObject.Properties)
    if ($expectedPhases.Count -ne 2 -or @($expectedPhases.Name | Where-Object { $_ -notin @('ON','OFF') }).Count -gt 0) { throw 'Identity expected_elements_per_phase must contain exactly ON and OFF.' }
    foreach ($phase in $expectedPhases) {
        $expectedTopology=@($phase.Value.PSObject.Properties)
        if ($expectedTopology.Count -ne 3 -or @($expectedTopology.Name | Where-Object { $_ -notin @('public','education','government') }).Count -gt 0) { throw "Identity topology expectation for $($phase.Name) must contain exactly public, education, and government." }
        foreach ($topology in $expectedTopology) {
            $counts=@($topology.Value)
            if (-not $counts.Count -or @($counts | Where-Object { "$_" -notmatch '^\d+$' -or [int]$_ -le 0 }).Count) { throw "Identity topology expectation for $($phase.Name)/$($topology.Name) must contain positive integers." }
        }
    }
    $expectedChannels = @{ public = 9001; education = 9002; government = 9003 }
    if (@($id.channels).Count -ne 3) { throw 'Identity must contain exactly three channels.' }
    foreach ($channel in @($id.channels)) {
        if (-not $expectedChannels.ContainsKey("$($channel.channel_id)") -or [int] $channel.udp_port -ne $expectedChannels["$($channel.channel_id)"]) { throw 'Identity channel set/port mapping is not the required tester mapping.' }
    }
    if (@($id.channels | ForEach-Object { $_.channel_id } | Sort-Object -Unique).Count -ne 3) { throw 'Identity channel IDs are not unique.' }
    return $id
}

function Set-Beta5IdentityField {
    param([Parameter(Mandatory)] $Identity, [Parameter(Mandatory)][string] $Name, $Value)
    $Identity | Add-Member -NotePropertyName $Name -NotePropertyValue $Value -Force
}

function Move-Beta5LegacySoakMarker {
    param([Parameter(Mandatory)] $Identity)
    $legacy = Join-Path $Identity.tester_root 'state\soak-started'
    if (-not (Test-Path -LiteralPath $legacy -PathType Leaf)) { return $null }
    $archive = Join-Path $Identity.mission_state_root 'archive'
    $destination = Join-Path $archive 'legacy-soak-started.pre-beta5.txt'
    $null = Assert-Beta5ChildPath -BasePath $Identity.mission_state_root -CandidatePath $destination
    if (Test-Path -LiteralPath $destination) { throw "Legacy soak marker archive already exists while the live marker is still present: $destination" }
    New-Item -ItemType Directory -Force -Path $archive | Out-Null
    Move-Item -LiteralPath $legacy -Destination $destination
    return $destination
}

function Write-Beta5JsonAtomic {
    param([Parameter(Mandatory)] $Object, [Parameter(Mandatory)][string] $Path)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $temporary = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        $Object | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporary -Encoding utf8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-Beta5Git {
    param([Parameter(Mandatory)][string] $Repository, [Parameter(Mandatory)][string[]] $Arguments)
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Git writes normal progress/diagnostic text to stderr even on exit 0.
        # Continue is scoped to this native capture only; callers still receive
        # a terminating error for a non-zero Git exit code below.
        $ErrorActionPreference = 'Continue'
        $rawOutput = @(& git -C $Repository @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $output = @($rawOutput | ForEach-Object { [string]$_ })
    if ($exitCode -ne 0) { throw "git $($Arguments -join ' ') failed in $Repository`: $($output -join ' ')" }
    return @($output)
}

function Sync-Beta5ReturnRepository {
    param([Parameter(Mandatory)] $Identity)
    $repository = Get-Beta5FullPath $Identity.return_repo_path
    if (-not (Test-Path -LiteralPath (Join-Path $repository '.git'))) { throw "Return repository is absent: $repository" }
    $branch = (Invoke-Beta5Git -Repository $repository -Arguments @('branch', '--show-current') | Select-Object -First 1).Trim()
    if ($branch -ne $Identity.return_branch) { throw "Return repo branch '$branch' is not identity branch '$($Identity.return_branch)'." }
    $null = Invoke-Beta5Git -Repository $repository -Arguments @('pull', '--rebase', '--autostash', 'origin', $Identity.return_branch)
    return $repository
}

function Publish-Beta5Report {
    param([Parameter(Mandatory)] $Identity, [Parameter(Mandatory)][string] $ReportPath, [Parameter(Mandatory)][string] $Message)
    $repository = Get-Beta5FullPath $Identity.return_repo_path
    $report = Assert-Beta5ChildPath -BasePath $repository -CandidatePath $ReportPath
    $allowedRoot = Join-Path $repository ("soak\beta7\" + $Identity.mission)
    $null = Assert-Beta5ChildPath -BasePath $allowedRoot -CandidatePath $report
    $repository = Sync-Beta5ReturnRepository $Identity
    $relative = $report.Substring($repository.Length).TrimStart('\')
    $null = Invoke-Beta5Git -Repository $repository -Arguments @('add', '--', $relative)
    $status = @(Invoke-Beta5Git -Repository $repository -Arguments @('status', '--porcelain', '--', $relative))
    if ($status.Count -eq 0) { return }
    $null = Invoke-Beta5Git -Repository $repository -Arguments @('commit', '--quiet', '-m', $Message, '--', $relative)
    try {
        $null = Invoke-Beta5Git -Repository $repository -Arguments @('push', '--quiet', 'origin', $Identity.return_branch)
    } catch {
        $null = Invoke-Beta5Git -Repository $repository -Arguments @('pull', '--rebase', '--autostash', 'origin', $Identity.return_branch)
        $null = Invoke-Beta5Git -Repository $repository -Arguments @('push', '--quiet', 'origin', $Identity.return_branch)
    }
}

function Get-Beta5ServiceExecutable {
    param([Parameter(Mandatory)][string] $ServicePathName)
    $value = $ServicePathName.Trim()
    if ($value.StartsWith('"')) {
        $closing = $value.IndexOf('"', 1)
        if ($closing -lt 2) { throw 'Service PathName contains an unclosed quote.' }
        return $value.Substring(1, $closing - 1)
    }
    return ($value -split '\s+', 2)[0]
}

function Assert-Beta5InstalledIdentity {
    param([Parameter(Mandatory)] $Identity, [string] $BaseUrl = 'http://127.0.0.1:8000', [string] $InstallRoot = 'C:\CivicCastHostStore\install')
    $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 20
    if ($health.status -ne 'healthy' -or "$($health.schema)" -ne 'current') { throw 'Installed station health/schema is not ready.' }
    if ("$($health.version)" -ne "$($Identity.expected_version)") { throw "Running version '$($health.version)' does not equal expected '$($Identity.expected_version)'." }
    $service = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction SilentlyContinue
    if (-not $service -or $service.State -ne 'Running' -or [int64] $service.ProcessId -le 0) { throw 'CivicCastSupervisor is not running with a process ID.' }
    $serviceExe = Get-Beta5ServiceExecutable $service.PathName
    $null = Assert-Beta5ChildPath -BasePath $InstallRoot -CandidatePath $serviceExe
    $serviceProcess = Get-Process -Id ([int] $service.ProcessId) -ErrorAction Stop
    return [pscustomobject]@{ health = $health; service_state = $service.State; service_path = $service.PathName; service_executable = $serviceExe; service_process_id = [int] $service.ProcessId; service_process_started_utc = $serviceProcess.StartTime.ToUniversalTime().ToString('o') }
}
