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

function Get-ProcessRoleLabel {
    <#
      .SYNOPSIS
      Round-2 finding 3 (MEDIUM): every process
      Get-CycleProcessCpuSamples samples is a python.exe/pythonw.exe/
      pythonservice.exe/ffmpeg.exe -- the review's complaint was that the
      raw pid/process_name rows gave a human no way to tell which one was
      which without leaving VERDICT.json/cycle JSON entirely. Labels each
      row using ONLY pid facts the harness already holds in scope --
      $GstWorkerPidMap (Get-GstWorkerPidMap's existing single CIM query,
      already paid for) and $PidToChannelId (built from THIS pass's own
      Get-ChannelStateSample.pid per channel, already fetched via the
      egress state API, not a process query at all) -- never an
      additional Win32_Process/CIM lookup.

      .PARAMETER ProcessName
      Get-Process's own `.ProcessName` (extension-less, e.g. "python",
      "pythonservice", "ffmpeg").

      .PARAMETER ProcessId
      The sampled process's pid.

      .PARAMETER GstWorkerPidMap
      Get-GstWorkerPidMap's own output: hashtable/dictionary of
      {[int]pid -> $true} for every python.exe process whose CommandLine
      matched `egress[\/]gst[\/]worker\.py` this pass.

      .PARAMETER PidToChannelId
      Hashtable/dictionary of {[int]pid -> [string]channel_id}, built from
      this pass's own per-channel state samples (each channel's engine pid,
      whichever engine -- gstreamer or ffmpeg-fallback -- is actually
      running it).

      .OUTPUTS
      [string] one of:
        "gst-worker:<channel_id>" -- pid is a known gst-worker process
                                     (per GstWorkerPidMap) AND resolves to
                                     a channel (per PidToChannelId).
        "gst-worker:unknown"      -- pid is a known gst-worker process but
                                     did not resolve to any channel this
                                     pass (a same-pass relaunch race --
                                     rare; see Resolve-EngineForPid's own
                                     comment on the identical race).
        "supervisor"              -- pythonservice.exe: the Windows
                                     service host (station_runtime.py:369)
                                     that hosts CivicCastSupervisor.
        "control-plane"           -- any other python/pythonw process not
                                     in GstWorkerPidMap: the
                                     `python -I -u -m uvicorn
                                     civiccast.app:create_app` child
                                     (civiccast/native/supervisor/
                                     service.py's control_plane_child_spec).
        "other"                   -- everything else (e.g. an ffmpeg.exe
                                     not resolved to any channel this pass).
    #>
    param(
        [string]$ProcessName,
        [int]$ProcessId,
        $GstWorkerPidMap = @{},
        $PidToChannelId = @{}
    )
    if ($GstWorkerPidMap.ContainsKey($ProcessId)) {
        $chId = $PidToChannelId[$ProcessId]
        if ($chId) { return "gst-worker:$chId" }
        return 'gst-worker:unknown'
    }
    if ($ProcessName -eq 'pythonservice') { return 'supervisor' }
    if ($ProcessName -match '^python') { return 'control-plane' }
    return 'other'
}
