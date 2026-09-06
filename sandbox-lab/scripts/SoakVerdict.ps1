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
#          tsduck_verdict = 'pass'; last_error = $null
#          in_planned_restart_window = $false }
#       ...
#     )
#   }
#
# ROUND-6 CHANGE: relaunch/restart classification moved OUT of the per-cycle
# check entirely. With CIVICCAST_EGRESS_SEAMLESS_RELOAD off (beta.5 default),
# EVERY schedule-plan rollover is a PLANNED worker restart: the daemon writes
# state=TRANSITIONING, drains to EOS, then starts a new worker (new pid) --
# a pid change alone was never evidence of a crash. In-Sandbox-Soak.ps1 now
# samples state+pid+updated_at every 15s (a 12-sample/3-minute ring per
# channel, embedded in each cycle's JSON for evidence) and classifies each
# detected pid change itself, in real time, using that ring: a pid change is
# `planned_restart` if the channel's own ring shows state=='TRANSITIONING'
# within the preceding 3 minutes, `unplanned_relaunch` otherwise (a crash:
# state ERROR/FALLBACK_SLATE, or a pid change with no TRANSITIONING sample
# at all). That classification is pre-computed in the guest and handed to
# Get-SoakVerdict as -RestartEvents, never re-derived here -- this file
# stays a pure aggregator over already-classified events plus the per-cycle
# ON_AIR/tsp checks.
#
# PASS criterion:
#   - every post-warmup cycle has all channels ON_AIR on GStreamer UNLESS a
#     channel is inside an ACTIVE planned-restart window (marked
#     `in_planned_restart_window` on that channel's row by the guest -- the
#     up-to-60s stretch between a planned restart's pid change and its
#     recovery) -- that is the licensed exception a restart needs to not be
#     mistaken for an outage.
#   - every post-warmup cycle has tsp PASS on every channel, NO exception
#     for a restart window -- a truly seamless reload should not drop
#     packets either, and this is exactly the thing this soak exists to
#     prove or disprove.
#   - ZERO unplanned_relaunch events, at any time (never excused by warm-up
#     -- see Get-SoakVerdict).
#   - EVERY planned_restart event recovered (state ON_AIR on gstreamer)
#     within 60 seconds of its pid-change detection. A planned restart that
#     never recovered within the tracking window, or recovered slower than
#     60s, fails the run.

function Test-SoakCycle {
    <#
      .SYNOPSIS
      Evaluate one cycle record's ON_AIR/engine/tsp state against the PASS
      criteria (restart/relaunch classification is evaluated separately by
      Get-SoakVerdict against -RestartEvents, not here).

      .PARAMETER Cycle
      One cycle record (see schema above).

      .PARAMETER IsWarmup
      Whether this cycle falls inside the warm-up grace window (its
      cycle_utc is earlier than StartUtc + WarmupSeconds).

      .OUTPUTS
      [pscustomobject] @{ ok; reason; not_on_air; tsp_fail }
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
        return [pscustomobject]@{ ok = $false; reason = 'no channel data in cycle'; not_on_air = @(); tsp_fail = @() }
    }

    # engine must be exactly 'gstreamer' post-warmup -- $null (worker not
    # found / EgressStateRow carries no engine field so it must be inferred
    # from the OS process census, see In-Sandbox-Soak.ps1's
    # Get-EngineForWorkerPid) and 'ffmpeg-fallback' both fail here. A
    # missing/unknown engine is not "probably fine" -- it means either no
    # worker is running or the shipped default silently fell back, and
    # allow_software_fallback is set to $false in the channel config
    # specifically so that fallback is a real, visible failure rather than
    # a channel that happens to still look ON_AIR. The ONE exception:
    # `in_planned_restart_window` -- a channel legitimately draining/
    # restarting under a classified planned restart is not an outage.
    $notOnAir = @($channels | Where-Object { -not $_.in_planned_restart_window -and ($_.engine_state -ne 'ON_AIR' -or $_.engine -ne 'gstreamer') })
    $tspFail = @($channels | Where-Object { $_.tsduck_verdict -ne 'pass' })

    if ($IsWarmup) {
        # During warm-up, a channel that is not yet ON_AIR/gstreamer is
        # tolerated (still transitioning). A tsp FAIL is also tolerated
        # during warm-up for the same reason (no stream up yet to probe).
        return [pscustomobject]@{ ok = $true; reason = $null; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }) }
    }

    if ($notOnAir.Count -gt 0) {
        $ids = ($notOnAir | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; reason = "not ON_AIR on gstreamer (and not inside a classified planned-restart window): $ids"; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @() }
    }
    if ($tspFail.Count -gt 0) {
        $ids = ($tspFail | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; reason = "tsduck egress probe failed: $ids"; not_on_air = @(); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }) }
    }

    return [pscustomobject]@{ ok = $true; reason = $null; not_on_air = @(); tsp_fail = @() }
}

function Get-SoakVerdict {
    <#
      .SYNOPSIS
      Aggregate a list of cycle records PLUS a list of classified restart
      events into a PASS/FAIL soak verdict.

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

      .PARAMETER RestartEvents
      Array of already-classified restart events, each:
        @{ channel_id; detected_utc; old_pid; new_pid
           classification = 'planned_restart' | 'unplanned_relaunch'
           recovered = [bool]; recovery_gap_seconds = [double] or $null }
      Never excused by warm-up: a restart detected during the warm-up
      window is still classified and still counted.

      .OUTPUTS
      [pscustomobject] @{
        verdict                  = 'PASS' | 'FAIL'
        reason                   = $null | string
        first_failing_cycle      = $null | (the cycle_utc string)
        cycles_total             = int
        cycles_warmup            = int
        cycles_evaluated         = int
        unplanned_relaunch_count = int
        planned_restart_count    = int
        max_restart_gap_seconds  = $null | double
      }
    #>
    param(
        [AllowEmptyCollection()]
        [array]$Cycles = @(),
        [Parameter(Mandatory = $true)] [datetime]$StartUtc,
        [int]$WarmupSeconds = 180,
        [AllowEmptyCollection()]
        [array]$RestartEvents = @()
    )

    $restartEvents = @($RestartEvents)
    $unplannedEvents = @($restartEvents | Where-Object { $_.classification -eq 'unplanned_relaunch' })
    $plannedEvents = @($restartEvents | Where-Object { $_.classification -eq 'planned_restart' })
    $unplannedCount = $unplannedEvents.Count
    $plannedCount = $plannedEvents.Count
    $gapValues = @($restartEvents | Where-Object { $null -ne $_.recovery_gap_seconds } | ForEach-Object { [double]$_.recovery_gap_seconds })
    $maxGap = $(if ($gapValues.Count -gt 0) { ($gapValues | Measure-Object -Maximum).Maximum } else { $null })

    $sorted = @($Cycles | Sort-Object { [datetime]$_.cycle_utc })

    $failResult = $null

    if ($unplannedCount -gt 0) {
        $first = $unplannedEvents | Sort-Object { [datetime]$_.detected_utc } | Select-Object -First 1
        $failResult = [pscustomobject]@{
            verdict = 'FAIL'
            reason = "unplanned relaunch on channel=$($first.channel_id) at $($first.detected_utc) (old_pid=$($first.old_pid) new_pid=$($first.new_pid)) -- no TRANSITIONING sample preceded the pid change"
            first_failing_cycle = "$($first.detected_utc)"
        }
    }

    if (-not $failResult) {
        $slowOrMissing = @($plannedEvents | Where-Object { -not $_.recovered -or $null -eq $_.recovery_gap_seconds -or [double]$_.recovery_gap_seconds -gt 60 })
        if ($slowOrMissing.Count -gt 0) {
            $first = $slowOrMissing | Sort-Object { [datetime]$_.detected_utc } | Select-Object -First 1
            $gapDesc = $(if ($null -ne $first.recovery_gap_seconds) { "$($first.recovery_gap_seconds)s" } else { 'never (not recovered within the tracking window)' })
            $failResult = [pscustomobject]@{
                verdict = 'FAIL'
                reason = "planned restart on channel=$($first.channel_id) at $($first.detected_utc) did not return to ON_AIR on gstreamer within 60s (actual: $gapDesc)"
                first_failing_cycle = "$($first.detected_utc)"
            }
        }
    }

    if (-not $failResult) {
        if ($sorted.Count -eq 0) {
            $failResult = [pscustomobject]@{ verdict = 'FAIL'; reason = 'no cycles recorded'; first_failing_cycle = $null }
        } else {
            $warmupCount = 0
            $evaluatedCount = 0
            foreach ($cycle in $sorted) {
                $cycleUtc = [datetime]$cycle.cycle_utc
                $isWarmup = ($cycleUtc.ToUniversalTime() - $StartUtc.ToUniversalTime()).TotalSeconds -lt $WarmupSeconds
                if ($isWarmup) { $warmupCount++ } else { $evaluatedCount++ }

                $r = Test-SoakCycle -Cycle $cycle -IsWarmup $isWarmup
                if (-not $r.ok) {
                    $failResult = [pscustomobject]@{
                        verdict = 'FAIL'
                        reason = "cycle $($cycle.cycle_utc): $($r.reason)"
                        first_failing_cycle = "$($cycle.cycle_utc)"
                    }
                    break
                }
            }
            if (-not $failResult -and $evaluatedCount -eq 0) {
                $failResult = [pscustomobject]@{
                    verdict = 'FAIL'
                    reason = 'every recorded cycle fell inside the warm-up window -- no post-warmup cycle was ever evaluated (soak too short or warm-up misconfigured)'
                    first_failing_cycle = $null
                }
            }
        }
    }

    # Recompute warmup/evaluated counts once more for the final object
    # (the loop above may have broken early on a mid-run failure, before
    # every cycle was classified into warmup/evaluated).
    $warmupCountFinal = 0
    $evaluatedCountFinal = 0
    foreach ($cycle in $sorted) {
        $cycleUtc = [datetime]$cycle.cycle_utc
        if (($cycleUtc.ToUniversalTime() - $StartUtc.ToUniversalTime()).TotalSeconds -lt $WarmupSeconds) { $warmupCountFinal++ } else { $evaluatedCountFinal++ }
    }

    if ($failResult) {
        return [pscustomobject]@{
            verdict = 'FAIL'
            reason = $failResult.reason
            first_failing_cycle = $failResult.first_failing_cycle
            cycles_total = $sorted.Count
            cycles_warmup = $warmupCountFinal
            cycles_evaluated = $evaluatedCountFinal
            unplanned_relaunch_count = $unplannedCount
            planned_restart_count = $plannedCount
            max_restart_gap_seconds = $maxGap
        }
    }

    return [pscustomobject]@{
        verdict = 'PASS'
        reason = $null
        first_failing_cycle = $null
        cycles_total = $sorted.Count
        cycles_warmup = $warmupCountFinal
        cycles_evaluated = $evaluatedCountFinal
        unplanned_relaunch_count = $unplannedCount
        planned_restart_count = $plannedCount
        max_restart_gap_seconds = $maxGap
    }
}
