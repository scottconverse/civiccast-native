# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# CpuSampler.ps1 -- dot-sourceable pure conversions for the per-process CPU
# instrumentation (each cycle row's per-pid cpu_seconds_delta/
# working_set_mb), extracted so the arithmetic is unit-testable
# (Test-CpuSampler.ps1) without a live process table. In-Sandbox-Soak.ps1's
# own Get-CycleProcessCpuSamples does the actual Get-Process call and
# tracks the previous-sample table (script-scope state, not testable in
# isolation); this file holds only the pure math it calls per pid.

function Get-CpuDeltaSample {
    <#
      .SYNOPSIS
      CPU-seconds consumed by one process since its last sample.

      .PARAMETER CpuSecondsNow
      The process's current total processor time in seconds (Get-Process's
      own `.CPU` property -- cumulative since the process started, not a
      rate).

      .PARAMETER CpuSecondsPrev
      The same process's total processor time as of the previous cycle's
      sample, or $null if this is the first cycle this pid has been seen.

      .OUTPUTS
      $null when there is no valid prior baseline (first sighting of this
      pid) OR when the computed delta would be negative -- a monotonically
      increasing per-process counter never legitimately goes backwards, so
      a negative delta means the tracking table's pid was silently reused
      by a DIFFERENT process between samples (the caller prunes pids not
      seen in the current cycle, but a same-pid reuse WITHIN one cycle
      gap is still possible); reporting a nonsensical negative number as
      evidence would be worse than reporting no delta at all for that one
      cycle. Otherwise the rounded (2 decimal places) non-negative delta.
    #>
    param(
        [Nullable[double]]$CpuSecondsNow,
        [Nullable[double]]$CpuSecondsPrev
    )
    if ($null -eq $CpuSecondsNow -or $null -eq $CpuSecondsPrev) { return $null }
    $delta = $CpuSecondsNow - $CpuSecondsPrev
    if ($delta -lt 0) { return $null }
    return [math]::Round($delta, 2)
}

function ConvertTo-WorkingSetMb {
    <#
      .SYNOPSIS
      Bytes -> MB (1 decimal place), $null-safe.
    #>
    param([Nullable[int64]]$WorkingSetBytes)
    if ($null -eq $WorkingSetBytes) { return $null }
    return [math]::Round($WorkingSetBytes / 1MB, 1)
}
