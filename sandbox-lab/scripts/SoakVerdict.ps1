# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# SoakVerdict.ps1 -- dot-sourceable verify/verdict logic for the local
# Windows Sandbox soak lane (sandbox-lab/Run-SandboxSoak.ps1 /
# In-Sandbox-Soak.ps1). Extracted into its own file so it can be unit-tested
# with synthetic data (Test-SoakVerdict.ps1) without needing a live sandbox,
# a live station, or tsp.exe.
#
# Schema this operates on -- ONE "cycle" record per ~60s poll inside the
# sandbox, modeled on the proven soak8 AUTORUN-3.ps1 per-cycle shape
# (C:\Users\scott\Desktop\Code\cc-soak8\soak\autorun\AUTORUN-3.ps1):
#
#   @{
#     cycle_utc              = '2026-09-05T18:41:00Z'   # ISO 8601 UTC
#     channels = @(
#       @{ channel_id = 'public'; engine_state = 'ON_AIR'; engine = 'gstreamer'
#          tsduck_verdict = 'pass'; relaunched_this_cycle = $false
#          relaunches_total = 0; last_error = $null }
#       ...
#     )
#   }
#
# PASS criterion (per the task spec): every cycle AFTER a warm-up grace
# period had ALL channels ON_AIR on GStreamer, ALL tsduck egress probes
# passed, and ZERO worker relaunches. A cycle inside the warm-up window may
# show channels not yet ON_AIR (still transitioning from the start command,
# exactly the soak8 finding recorded in
# C:\Users\scott\Desktop\Code\cc-soak8\soak\DIRECTIVE-4.md line 162) without
# failing the run. A relaunch is never excused by warm-up -- a worker
# restarting during warm-up is still a worker restarting.

function Test-SoakCycle {
    <#
      .SYNOPSIS
      Evaluate one cycle record against the PASS criteria.

      .PARAMETER Cycle
      One cycle record (see schema above).

      .PARAMETER IsWarmup
      Whether this cycle falls inside the warm-up grace window (its
      cycle_utc is earlier than StartUtc + WarmupSeconds).

      .OUTPUTS
      [pscustomobject] @{ ok; reason; not_on_air; tsp_fail; relaunch }
      `ok` is $true when the cycle satisfies the PASS criteria for its
      warm-up status. `reason` is a short human string naming the first
      failing condition when ok is $false.
    #>
    param(
        [Parameter(Mandatory = $true)] $Cycle,
        [bool]$IsWarmup = $false
    )

    $channels = @($Cycle.channels)
    if ($channels.Count -eq 0) {
        return [pscustomobject]@{ ok = $false; reason = 'no channel data in cycle'; not_on_air = @(); tsp_fail = @(); relaunch = @() }
    }

    # Relaunches are NEVER excused by warm-up.
    $relaunched = @($channels | Where-Object { $_.relaunched_this_cycle })
    if ($relaunched.Count -gt 0) {
        $ids = ($relaunched | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{
            ok = $false
            reason = "worker relaunch observed on: $ids"
            not_on_air = @()
            tsp_fail = @()
            relaunch = @($relaunched | ForEach-Object { $_.channel_id })
        }
    }

    # engine must be exactly 'gstreamer' post-warmup -- $null (worker not
    # found / EgressStateRow carries no engine field so it must be inferred
    # from the OS process census, see In-Sandbox-Soak.ps1's
    # Get-EngineForWorkerPid) and 'ffmpeg-fallback' both fail here. A
    # missing/unknown engine is not "probably fine" -- it means either no
    # worker is running or the shipped default silently fell back, and
    # allow_software_fallback is set to $false in the channel config
    # specifically so that fallback is a real, visible failure rather than
    # a channel that happens to still look ON_AIR.
    $notOnAir = @($channels | Where-Object { $_.engine_state -ne 'ON_AIR' -or $_.engine -ne 'gstreamer' })
    $tspFail = @($channels | Where-Object { $_.tsduck_verdict -ne 'pass' })

    if ($IsWarmup) {
        # During warm-up, a channel that is not yet ON_AIR/gstreamer is
        # tolerated (still transitioning). A tsp FAIL is also tolerated
        # during warm-up for the same reason (no stream up yet to probe).
        return [pscustomobject]@{ ok = $true; reason = $null; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }); relaunch = @() }
    }

    if ($notOnAir.Count -gt 0) {
        $ids = ($notOnAir | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; reason = "not ON_AIR on gstreamer: $ids"; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @(); relaunch = @() }
    }
    if ($tspFail.Count -gt 0) {
        $ids = ($tspFail | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; reason = "tsduck egress probe failed: $ids"; not_on_air = @(); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }); relaunch = @() }
    }

    return [pscustomobject]@{ ok = $true; reason = $null; not_on_air = @(); tsp_fail = @(); relaunch = @() }
}

function Get-SoakVerdict {
    <#
      .SYNOPSIS
      Aggregate a list of cycle records into a PASS/FAIL soak verdict.

      .PARAMETER Cycles
      Array of cycle records (see schema above), in any order -- sorted by
      cycle_utc internally.

      .PARAMETER StartUtc
      [datetime] (UTC) when the soak run began (channels were just
      started). Used to compute each cycle's warm-up status.

      .PARAMETER WarmupSeconds
      Length of the warm-up grace window in seconds. Default 180 (3
      minutes), matching soak8's own warm-up grace
      (AUTORUN-3.ps1's $warmupUntil = $startUtc.AddMinutes(3)).

      .OUTPUTS
      [pscustomobject] @{
        verdict              = 'PASS' | 'FAIL'
        reason               = $null | string
        first_failing_cycle  = $null | (the cycle_utc string)
        cycles_total         = int
        cycles_warmup        = int
        cycles_evaluated     = int
      }
    #>
    param(
        [AllowEmptyCollection()]
        [array]$Cycles = @(),
        [Parameter(Mandatory = $true)] [datetime]$StartUtc,
        [int]$WarmupSeconds = 180
    )

    $sorted = @($Cycles | Sort-Object { [datetime]$_.cycle_utc })
    if ($sorted.Count -eq 0) {
        return [pscustomobject]@{
            verdict = 'FAIL'; reason = 'no cycles recorded'; first_failing_cycle = $null
            cycles_total = 0; cycles_warmup = 0; cycles_evaluated = 0
        }
    }

    $warmupCount = 0
    $evaluatedCount = 0
    foreach ($cycle in $sorted) {
        $cycleUtc = [datetime]$cycle.cycle_utc
        $isWarmup = ($cycleUtc.ToUniversalTime() - $StartUtc.ToUniversalTime()).TotalSeconds -lt $WarmupSeconds
        if ($isWarmup) { $warmupCount++ } else { $evaluatedCount++ }

        $r = Test-SoakCycle -Cycle $cycle -IsWarmup $isWarmup
        if (-not $r.ok) {
            return [pscustomobject]@{
                verdict = 'FAIL'
                reason = "cycle $($cycle.cycle_utc): $($r.reason)"
                first_failing_cycle = "$($cycle.cycle_utc)"
                cycles_total = $sorted.Count
                cycles_warmup = $warmupCount
                cycles_evaluated = $evaluatedCount
            }
        }
    }

    if ($evaluatedCount -eq 0) {
        return [pscustomobject]@{
            verdict = 'FAIL'
            reason = 'every recorded cycle fell inside the warm-up window -- no post-warmup cycle was ever evaluated (soak too short or warm-up misconfigured)'
            first_failing_cycle = $null
            cycles_total = $sorted.Count
            cycles_warmup = $warmupCount
            cycles_evaluated = $evaluatedCount
        }
    }

    return [pscustomobject]@{
        verdict = 'PASS'
        reason = $null
        first_failing_cycle = $null
        cycles_total = $sorted.Count
        cycles_warmup = $warmupCount
        cycles_evaluated = $evaluatedCount
    }
}
