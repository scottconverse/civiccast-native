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

# ---------------------------------------------------------------- scenario 9
# Round-2 finding 3: Get-ProcessRoleLabel -- a python.exe pid that IS in
# GstWorkerPidMap and resolves to a channel via PidToChannelId.
$gstMap9 = @{ 4001 = $true }
$pidMap9 = @{ 4001 = 'government' }
$r9 = Get-ProcessRoleLabel -ProcessName 'python' -ProcessId 4001 -GstWorkerPidMap $gstMap9 -PidToChannelId $pidMap9
Assert-Equal 'scenario9 (gst-worker pid, resolved channel) -> gst-worker:government' 'gst-worker:government' $r9

# --------------------------------------------------------------- scenario 10
# Round-2 finding 3: a gst-worker pid (per GstWorkerPidMap) with NO channel
# resolution this pass (same-pass relaunch race, mirrors Resolve-EngineForPid's
# own documented race) -- must not silently mislabel as control-plane.
$r10 = Get-ProcessRoleLabel -ProcessName 'python' -ProcessId 4002 -GstWorkerPidMap (@{ 4002 = $true }) -PidToChannelId @{}
Assert-Equal 'scenario10 (gst-worker pid, unresolved channel) -> gst-worker:unknown' 'gst-worker:unknown' $r10

# --------------------------------------------------------------- scenario 11
# Round-2 finding 3: pythonservice.exe (ProcessName 'pythonservice') is
# ALWAYS the supervisor -- station_runtime.py:369/civiccast/native/
# supervisor/install_layout.py:6/25 -- never in GstWorkerPidMap.
$r11 = Get-ProcessRoleLabel -ProcessName 'pythonservice' -ProcessId 5001 -GstWorkerPidMap @{} -PidToChannelId @{}
Assert-Equal 'scenario11 (pythonservice.exe) -> supervisor' 'supervisor' $r11

# --------------------------------------------------------------- scenario 12
# Round-2 finding 3: any other python/pythonw pid not in GstWorkerPidMap is
# the control-plane child (`python -I -u -m uvicorn civiccast.app:create_app`).
$r12 = Get-ProcessRoleLabel -ProcessName 'python' -ProcessId 6001 -GstWorkerPidMap @{} -PidToChannelId @{}
Assert-Equal 'scenario12 (python.exe, not a gst-worker pid) -> control-plane' 'control-plane' $r12
$r12b = Get-ProcessRoleLabel -ProcessName 'pythonw' -ProcessId 6002 -GstWorkerPidMap @{} -PidToChannelId @{}
Assert-Equal 'scenario12b (pythonw.exe, not a gst-worker pid) -> control-plane' 'control-plane' $r12b

# --------------------------------------------------------------- scenario 13
# Round-2 finding 3: an ffmpeg.exe process (not resolved to any channel via
# PidToChannelId, and never in GstWorkerPidMap -- that map is python-only)
# falls to "other".
$r13 = Get-ProcessRoleLabel -ProcessName 'ffmpeg' -ProcessId 7001 -GstWorkerPidMap @{} -PidToChannelId @{}
Assert-Equal 'scenario13 (ffmpeg.exe, unresolved) -> other' 'other' $r13

Write-Host ""
Write-Host "CpuSampler unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
