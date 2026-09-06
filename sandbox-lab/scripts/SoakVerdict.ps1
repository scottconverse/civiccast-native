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
      [pscustomobject] @{ ok; harness_error; reason; not_on_air; tsp_fail; tsp_harness_error }
      `ok` is $true when the cycle satisfies the PASS criteria for its
      warm-up status. `harness_error` is $true when the failure is a
      harness/tooling defect (tsp.exe missing, or tsp itself threw
      launching), never a product finding -- Get-SoakVerdict reports these
      as HARNESS_ERROR, never FAIL. `reason` is a short human string
      naming the first failing condition when ok is $false.
    #>
    param(
        [Parameter(Mandatory = $true)] $Cycle,
        [bool]$IsWarmup = $false
    )

    $channels = @($Cycle.channels)
    if ($channels.Count -eq 0) {
        return [pscustomobject]@{ ok = $false; harness_error = $false; reason = 'no channel data in cycle'; not_on_air = @(); tsp_fail = @() }
    }

    # Round-8 finding 5 (HIGH) / round-9 finding N3 (MEDIUM): tsp verdicts
    # that mean the PROBE ITSELF never produced a usable result are
    # HARNESS/TOOLING defects, never a product finding:
    #   - 'not-run' / 'not-run:*'    -- tsp.exe missing from the bounded
    #     candidate list; the probe never launched at all.
    #   - 'error:*'                  -- the process threw trying to launch.
    #   - 'fail-no-report'           -- tsp exited 0 but wrote no report
    #     file at all.
    #   - 'fail-unparsable-report'   -- tsp exited 0, wrote a report, but it
    #     is not valid JSON.
    #   - 'fail-no-ts-section'       -- tsp exited 0, wrote valid JSON, but
    #     it carries no `ts` analysis section.
    # (round-9's own citation: this is the same beta.3 empty-report
    # precedent Gate A's own judge already treats as a harness condition,
    # not a station-acceptance FAIL -- an exit-0 tool that produced nothing
    # analyzable proves nothing about the stream either way.) 'fail-timed-out',
    # 'fail-zero-packets', 'fail-exit-N', and 'fail-stream-errors' (tsp DID
    # run and observed something concrete about the actual stream) stay
    # product FAIL, unchanged. Checked BEFORE anything else, in every cycle
    # (including warm-up -- a broken probe is not something warm-up should
    # ever mask, since it means NO cycle's tsp result can be trusted).
    $tspHarnessError = @($channels | Where-Object {
        $v = "$($_.tsduck_verdict)"
        $v -eq 'not-run' -or $v -like 'not-run:*' -or $v -like 'error:*' -or
            $v -eq 'fail-no-report' -or $v -eq 'fail-unparsable-report' -or $v -eq 'fail-no-ts-section'
    })
    if ($tspHarnessError.Count -gt 0) {
        $ids = ($tspHarnessError | ForEach-Object { "$($_.channel_id)=$($_.tsduck_verdict)" }) -join ', '
        return [pscustomobject]@{ ok = $false; harness_error = $true; reason = "tsp harness/tooling defect (tool missing, failed to launch, or produced no usable analysis -- not a product finding): $ids"; not_on_air = @(); tsp_fail = @() }
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
    #
    # Round-10 finding 4 (HIGH): a channel row whose OWN state read failed
    # (In-Sandbox-Soak.ps1's Get-ChannelStateSample returning ok=$false)
    # carries engine_state=$null -- previously indistinguishable from a
    # channel that is genuinely down, so a single dropped HTTP read (a
    # harness/network blip, not a product finding) failed the whole cycle.
    # last_error starting with the literal "state read failed" (the exact
    # prefix Get-ChannelStateSample stamps, see In-Sandbox-Soak.ps1) marks
    # this row as a HARNESS sample -- excluded from the ON_AIR check here;
    # Get-SoakVerdict below separately tracks 3 CONSECUTIVE such rows per
    # channel and escalates to HARNESS_ERROR if that ever happens (a lone
    # dropped read is excused silently; a channel that cannot be read three
    # times running means the read path itself is broken, not that the
    # channel fell off air, and must never present as a product FAIL).
    $isStateReadFailure = { param($row) "$($row.last_error)" -like 'state read failed*' }
    $notOnAir = @($channels | Where-Object { -not $_.in_planned_restart_window -and -not (& $isStateReadFailure $_) -and ($_.engine_state -ne 'ON_AIR' -or $_.engine -ne 'gstreamer') })
    $tspFail = @($channels | Where-Object { $_.tsduck_verdict -ne 'pass' })

    if ($IsWarmup) {
        # During warm-up, a channel that is not yet ON_AIR/gstreamer is
        # tolerated (still transitioning). A tsp FAIL is also tolerated
        # during warm-up for the same reason (no stream up yet to probe).
        return [pscustomobject]@{ ok = $true; harness_error = $false; reason = $null; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }) }
    }

    if ($notOnAir.Count -gt 0) {
        $ids = ($notOnAir | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; harness_error = $false; reason = "not ON_AIR on gstreamer (and not inside a classified planned-restart window): $ids"; not_on_air = @($notOnAir | ForEach-Object { $_.channel_id }); tsp_fail = @() }
    }
    if ($tspFail.Count -gt 0) {
        $ids = ($tspFail | ForEach-Object { $_.channel_id }) -join ', '
        return [pscustomobject]@{ ok = $false; harness_error = $false; reason = "tsduck egress probe failed: $ids"; not_on_air = @(); tsp_fail = @($tspFail | ForEach-Object { $_.channel_id }) }
    }

    return [pscustomobject]@{ ok = $true; harness_error = $false; reason = $null; not_on_air = @(); tsp_fail = @() }
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
           recovered = [bool]; recovery_gap_seconds = [double] or $null
           incomplete = [bool] }
      Never excused by warm-up: a restart detected during the warm-up
      window is still classified and still counted.

      .PARAMETER SeamlessReload
      Round-11 finding 4 (MEDIUM): whether this run was launched with
      -SeamlessReload. Under this flag the PASS contract is STRICTER than
      the normal (flag-off) one: zero unplanned_relaunch, zero
      reload_aborted (see -ReloadAbortEvents), planned_restart_count MUST
      be zero (a classified planned_restart under this flag means the
      seamless content-reload path did NOT run at all -- it fell back to
      an actual worker restart, which is exactly the failure mode this
      flag exists to prove absent), and tsp pass every cycle (already
      enforced unconditionally by Test-SoakCycle, restated here as part of
      the documented contract). Default $false (the normal contract).

      .PARAMETER ReloadAbortEvents
      Round-11 finding 4: array of @{ channel_id; reason } -- daemon.py
      WARNING lines (main 250026b:1946/2132/2143/2156, all ending
      "...falling back to restart.") indicating a seamless content-reload
      attempt was aborted. These are never a FAIL under the normal
      (flag-off) contract (a fallback-to-restart is exactly what flag-off
      operation is), but ANY of them under -SeamlessReload is a FAIL.

      .OUTPUTS
      [pscustomobject] @{
        verdict                  = 'PASS' | 'FAIL' | 'HARNESS_ERROR'
        reason                   = $null | string
        first_failing_cycle      = $null | (the cycle_utc string)
        cycles_total             = int
        cycles_warmup            = int
        cycles_evaluated         = int
        unplanned_relaunch_count = int
        planned_restart_count    = int
        incomplete_restart_count = int
        reload_aborted_count     = int
        max_restart_gap_seconds  = $null | double
      }
    #>
    param(
        [AllowEmptyCollection()]
        [array]$Cycles = @(),
        [Parameter(Mandatory = $true)] [datetime]$StartUtc,
        [int]$WarmupSeconds = 180,
        [AllowEmptyCollection()]
        [array]$RestartEvents = @(),
        [bool]$SeamlessReload = $false,
        [AllowEmptyCollection()]
        [array]$ReloadAbortEvents = @()
    )

    $restartEvents = @($RestartEvents)
    $unplannedEvents = @($restartEvents | Where-Object { $_.classification -eq 'unplanned_relaunch' })
    $plannedEvents = @($restartEvents | Where-Object { $_.classification -eq 'planned_restart' })
    $unplannedCount = $unplannedEvents.Count
    $plannedCount = $plannedEvents.Count
    # Round-11 finding 3: events flushed as `incomplete=$true` (detected in
    # the final 60s of the soak window -- never had a fair chance to
    # recover before this lane stopped watching) -- reported for
    # visibility, excluded from the recovery-timeout FAIL rule below.
    $incompleteCount = @($restartEvents | Where-Object { $_.incomplete -eq $true }).Count
    $reloadAbortEvents = @($ReloadAbortEvents)
    $reloadAbortedCount = $reloadAbortEvents.Count
    $gapValues = @($restartEvents | Where-Object { $null -ne $_.recovery_gap_seconds } | ForEach-Object { [double]$_.recovery_gap_seconds })
    $maxGap = $(if ($gapValues.Count -gt 0) { ($gapValues | Measure-Object -Maximum).Maximum } else { $null })

    $sorted = @($Cycles | Sort-Object { [datetime]$_.cycle_utc })

    # Round-10 finding 4 (HIGH): a channel whose state read fails THREE
    # CONSECUTIVE cycles running (last_error starting with the literal
    # "state read failed", the exact prefix Get-ChannelStateSample stamps
    # in In-Sandbox-Soak.ps1) means the read path itself is broken, not
    # that the channel actually fell off air -- Test-SoakCycle above
    # already excludes a single such row from the ON_AIR check, but a
    # PERSISTENT read failure needs its own escalation (a channel that is
    # actually down would otherwise sail through cycle after cycle with
    # every row silently excused, engine_state=$null the entire time, and
    # never be reported as anything at all). Tracked per-channel across the
    # whole run, in cycle order, resetting to 0 on any row that is NOT a
    # read failure -- checked in the SAME pass as the tsp harness-defect
    # check below (both are harness/tooling conditions, checked first,
    # before any product PASS/FAIL classification).
    $isStateReadFailure = { param($row) "$($row.last_error)" -like 'state read failed*' }
    $consecutiveReadFailures = @{}

    # Round-8 finding 5: a tsp harness/tooling defect (tool missing, or
    # threw trying to launch) in ANY cycle -- warm-up or not -- means NO
    # cycle's tsp result in this run can be trusted, so this is checked
    # FIRST and wins over every other classification. HARNESS_ERROR, never
    # FAIL: a broken probe says nothing about the product.
    foreach ($cycle in $sorted) {
        $cycleUtc = [datetime]$cycle.cycle_utc
        $isWarmup = ($cycleUtc.ToUniversalTime() - $StartUtc.ToUniversalTime()).TotalSeconds -lt $WarmupSeconds

        foreach ($row in @($cycle.channels)) {
            $chId = "$($row.channel_id)"
            if (& $isStateReadFailure $row) {
                $consecutiveReadFailures[$chId] = $(if ($consecutiveReadFailures.ContainsKey($chId)) { $consecutiveReadFailures[$chId] + 1 } else { 1 })
                if ($consecutiveReadFailures[$chId] -ge 3) {
                    return [pscustomobject]@{
                        verdict = 'HARNESS_ERROR'
                        reason = "cycle $($cycle.cycle_utc): channel=$chId state read failed $($consecutiveReadFailures[$chId]) consecutive cycles running (last_error: $($row.last_error)) -- the read path itself is broken, not a product finding"
                        first_failing_cycle = "$($cycle.cycle_utc)"
                        cycles_total = $sorted.Count
                        cycles_warmup = 0
                        cycles_evaluated = 0
                        unplanned_relaunch_count = $unplannedCount
                        planned_restart_count = $plannedCount
                        incomplete_restart_count = $incompleteCount
                        reload_aborted_count = $reloadAbortedCount
                        max_restart_gap_seconds = $maxGap
                    }
                }
            } else {
                $consecutiveReadFailures[$chId] = 0
            }
        }

        $r = Test-SoakCycle -Cycle $cycle -IsWarmup $isWarmup
        if ($r.harness_error) {
            return [pscustomobject]@{
                verdict = 'HARNESS_ERROR'
                reason = "cycle $($cycle.cycle_utc): $($r.reason)"
                first_failing_cycle = "$($cycle.cycle_utc)"
                cycles_total = $sorted.Count
                cycles_warmup = 0
                cycles_evaluated = 0
                unplanned_relaunch_count = $unplannedCount
                planned_restart_count = $plannedCount
                incomplete_restart_count = $incompleteCount
                reload_aborted_count = $reloadAbortedCount
                max_restart_gap_seconds = $maxGap
            }
        }
    }

    $failResult = $null

    if ($unplannedCount -gt 0) {
        $first = $unplannedEvents | Sort-Object { [datetime]$_.detected_utc } | Select-Object -First 1
        $failResult = [pscustomobject]@{
            verdict = 'FAIL'
            reason = "unplanned relaunch on channel=$($first.channel_id) at $($first.detected_utc) (old_pid=$($first.old_pid) new_pid=$($first.new_pid)) -- no TRANSITIONING sample preceded the pid change"
            first_failing_cycle = "$($first.detected_utc)"
        }
    }

    # Round-11 finding 4 (MEDIUM): under -SeamlessReload the contract is
    # STRICTER -- zero reload_aborted (a seamless content-reload that fell
    # back to a real restart) AND planned_restart_count MUST be zero (a
    # classified planned_restart under this flag means the seamless path
    # never ran at all, whether or not the daemon logged an explicit abort
    # line for it). Checked before the normal recovery-timeout rule below
    # since it can fail a run that would otherwise look like a clean PASS
    # (fast, fully-recovered restarts are still restarts the flag promised
    # would not happen).
    if (-not $failResult -and $SeamlessReload) {
        if ($reloadAbortedCount -gt 0) {
            $firstAbort = $reloadAbortEvents | Select-Object -First 1
            $failResult = [pscustomobject]@{
                verdict = 'FAIL'
                reason = "-SeamlessReload requested but a seamless content-reload aborted on channel=$($firstAbort.channel_id) ($($firstAbort.reason)) -- fell back to a restart"
                first_failing_cycle = $null
            }
        } elseif ($plannedCount -gt 0) {
            $firstPlanned = $plannedEvents | Sort-Object { [datetime]$_.detected_utc } | Select-Object -First 1
            $failResult = [pscustomobject]@{
                verdict = 'FAIL'
                reason = "-SeamlessReload requested but channel=$($firstPlanned.channel_id) had a classified planned_restart at $($firstPlanned.detected_utc) -- the seamless content-reload path did not run"
                first_failing_cycle = "$($firstPlanned.detected_utc)"
            }
        }
    }

    if (-not $failResult) {
        # Round-10 finding 8 (MEDIUM): a SUPERSEDED planned-restart event
        # (RestartClassifier.ps1's round-9 N1 fix -- flushed with
        # recovered=$false, recovery_gap_seconds=$null the moment a SECOND
        # pid change arrives before the first one resolves) is not itself
        # a recovery failure -- it is accounted for by whatever pid change
        # superseded it (that successor event is its own, separate entry
        # in $plannedEvents/$unplannedEvents and is judged on its own
        # merits above/below). Counting a superseded event against the
        # 60s-recovery rule double-penalizes a channel that simply
        # restarted twice in quick succession for a FAIL neither restart,
        # on its own, actually earned. Superseded events are still counted
        # in planned_restart_count/unplanned_relaunch_count above (via
        # $restartEvents, unfiltered) -- only excluded from THIS recovery
        # check.
        $slowOrMissing = @($plannedEvents | Where-Object { -not ($_.superseded -eq $true) -and -not ($_.incomplete -eq $true) -and (-not $_.recovered -or $null -eq $_.recovery_gap_seconds -or [double]$_.recovery_gap_seconds -gt 60) })
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
            incomplete_restart_count = $incompleteCount
            reload_aborted_count = $reloadAbortedCount
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
        incomplete_restart_count = $incompleteCount
        reload_aborted_count = $reloadAbortedCount
        max_restart_gap_seconds = $maxGap
    }
}
