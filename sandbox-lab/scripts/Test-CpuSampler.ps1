# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-CpuSampler.ps1 -- pytest-free PowerShell unit checks for
# Get-CpuDeltaSample / ConvertTo-WorkingSetMb (CpuSampler.ps1), fed
# synthetic cumulative-CPU-seconds/working-set-bytes pairs. No live process
# table required -- In-Sandbox-Soak.ps1's own Get-CycleProcessCpuSamples
# (the Get-Process call plus the previous-sample tracking table) is a thin
# wrapper around this pure math and is not itself unit-tested here. Exits
# non-zero on any mismatch.
#
# Run: pwsh -File sandbox-lab/scripts/Test-CpuSampler.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CpuSampler.ps1')

$script:failures = 0
$script:total = 0

function Assert-Equal {
    param([string]$Name, $Expected, $Actual)
    $script:total++
    if ("$Expected" -ne "$Actual") {
        $script:failures++
        Write-Host "[FAIL] $Name -- expected '$Expected', got '$Actual'" -ForegroundColor Red
    } else {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
}

# ---------------------------------------------------------------- scenario 1
# First sighting of a pid -- no prior baseline. Expect: $null (never a
# delta computed against nothing).
$d1 = Get-CpuDeltaSample -CpuSecondsNow 12.5 -CpuSecondsPrev $null
Assert-Equal 'scenario1 (no prior baseline) -> $null' '' $d1

# ---------------------------------------------------------------- scenario 2
# Normal case: CPU time advanced by 3.456s between samples.
$d2 = Get-CpuDeltaSample -CpuSecondsNow 15.956 -CpuSecondsPrev 12.5
Assert-Equal 'scenario2 (normal advance) -> 3.46 (rounded 2dp)' 3.46 $d2

# ---------------------------------------------------------------- scenario 3
# Zero advance (idle process between samples) -- a real, valid 0, not $null.
$d3 = Get-CpuDeltaSample -CpuSecondsNow 12.5 -CpuSecondsPrev 12.5
Assert-Equal 'scenario3 (zero advance) -> 0' 0 $d3

# ---------------------------------------------------------------- scenario 4
# Negative delta (a monotonically increasing counter never legitimately
# goes backwards -- pid reuse by a different process between samples).
# Expect: $null, never a nonsensical negative number.
$d4 = Get-CpuDeltaSample -CpuSecondsNow 1.0 -CpuSecondsPrev 12.5
Assert-Equal 'scenario4 (negative delta, pid reuse) -> $null' '' $d4

# ---------------------------------------------------------------- scenario 5
# $null current value (Get-Process's .CPU property threw/was unavailable).
# Expect: $null regardless of a valid prior baseline.
$d5 = Get-CpuDeltaSample -CpuSecondsNow $null -CpuSecondsPrev 12.5
Assert-Equal 'scenario5 (null current) -> $null' '' $d5

# ---------------------------------------------------------------- scenario 6
# ConvertTo-WorkingSetMb: normal conversion, 1 decimal place.
$w1 = ConvertTo-WorkingSetMb -WorkingSetBytes 104857600
Assert-Equal 'scenario6 (100 MiB) -> 100' 100 $w1

# ---------------------------------------------------------------- scenario 7
# ConvertTo-WorkingSetMb: $null-safe.
$w2 = ConvertTo-WorkingSetMb -WorkingSetBytes $null
Assert-Equal 'scenario7 (null bytes) -> $null' '' $w2

# ---------------------------------------------------------------- scenario 8
# ConvertTo-WorkingSetMb: a non-round byte count rounds to 1 decimal place.
$w3 = ConvertTo-WorkingSetMb -WorkingSetBytes 15728640
Assert-Equal 'scenario8 (15 MiB) -> 15' 15 $w3

Write-Host ""
Write-Host "CpuSampler unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
