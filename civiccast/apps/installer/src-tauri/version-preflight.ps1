# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
param(
    [Parameter(Mandatory = $true)][string]$CandidateVersion,
    [string]$InstalledVersion
)
$ErrorActionPreference = 'Stop'
try {
    if (-not $PSBoundParameters.ContainsKey('InstalledVersion')) {
        $key = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
            [Microsoft.Win32.RegistryHive]::LocalMachine,
            [Microsoft.Win32.RegistryView]::Registry64)
        try {
            $native = $key.OpenSubKey('Software\CivicCast\Native')
            try { $InstalledVersion = if ($native) { $native.GetValue('InstalledVersion', '') } else { '' } }
            finally { if ($native) { $native.Dispose() } }
        } finally { $key.Dispose() }
    }
    if (-not $InstalledVersion) { exit 0 }
    function Parse-Version([string]$value) {
        if ($value -notmatch '^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)\.?(\d+))?$') {
            throw 'Unrecognized CivicCast version; refusing replacement until installation identity is checked.'
        }
        [pscustomobject]@{
            Core = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
            Release = if ($Matches[4]) { 0 } else { 1 }
            Label = [string]$Matches[4]
            Number = if ($Matches[5]) { [long]$Matches[5] } else { 0 }
        }
    }
    $old = Parse-Version $InstalledVersion
    $new = Parse-Version $CandidateVersion
    $order = $old.Core.CompareTo($new.Core)
    if ($order -eq 0) { $order = $old.Release.CompareTo($new.Release) }
    if ($order -eq 0) { $order = [string]::CompareOrdinal($old.Label, $new.Label) }
    if ($order -eq 0) { $order = $old.Number.CompareTo($new.Number) }
    Write-Output "CivicCast version preflight: installed=$InstalledVersion candidate=$CandidateVersion"
    if ($order -gt 0) { exit 129 }
    exit 0
} catch {
    Write-Output "CivicCast version preflight failed: $($_.Exception.Message)"
    exit 130
}
