# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# RestartClassifier.ps1 -- dot-sourceable planned/unplanned worker-restart
# classification for the sandbox soak lane, extracted from
# In-Sandbox-Soak.ps1 into its own file (matching SoakVerdict.ps1 /
# HostLiveness.ps1's pattern) so it is unit-testable with synthetic data
# (Test-RestartClassifier.ps1) without a live sandbox or station.
#
# THE BUG THIS EXTRACTION EXISTS FOR (round-8 finding 1, BLOCKER): the
# inline version's ring-sample function had a parameter named `$Pid`. $PID
# is a READ-ONLY AUTOMATIC VARIABLE in PowerShell (the current process
# id) -- PowerShell variable names are case-insensitive, so `$Pid` IS
# `$PID` to the parameter binder, and binding any value to it throws
# "Cannot overwrite variable Pid because it is read-only or constant"
# (confirmed directly: VariableNotWritable, SessionStateUnauthorized-
# AccessException) on EVERY call. With $ErrorActionPreference='Continue'
# at script scope, that error goes to the error stream and the call
# silently no-ops: the function body never runs, the ring is never
# populated, and nothing downstream ever finds out (confirmed directly:
# the script does not crash, it just silently never records a single ring
# sample). That is exactly why run 7's cycle JSON showed "sample_ring":
# [null] and Test-TransitioningInWindow always returned $false, so every
# pid change -- including a genuinely planned restart -- was misclassified
# unplanned_relaunch. This file uses $ProcessId throughout, and ships with
# a real unit test that calls it, so this exact class of error (an
# automatic-variable name shadowed by a parameter, silently swallowed by a
# non-strict error preference) fails a unit check the moment it recurs.
#
# STATE MODEL: every function here takes a $Context object (from
# New-RestartClassifierContext) instead of relying on ambient script-scope
# variables. This is what makes the whole thing testable in isolation --
# a test builds a fresh context, feeds it synthetic samples, and asserts
# on its Ring/PendingRestarts/RestartEvents afterward, with no dependency
# on the real driver's global state.
#
# SAMPLING CADENCE (round-8 finding 2, BLOCKER): a single state-plus-tsp
# "heavy cycle" (3 channels x up to a 40s-bounded 20s tsp probe each) can
# take 60-75+ seconds end to end, and the previous single-timer poll loop
# scheduled its NEXT heavy cycle at +60s from the PREVIOUS one's start --
# so once a cycle ran even slightly over 60s, the "light 15s sample"
# branch became mathematically unreachable (the heavy-cycle condition was
# already true again the moment the loop looped back around). Fixed by
# INTERLEAVING a full all-channel state sample before each of the three
# per-channel tsp probes inside a heavy cycle (one of the two fixes this
# review explicitly authorized, the other being a separate background
# sampler process) -- see In-Sandbox-Soak.ps1's poll loop. That gives
# ~3 ring samples spaced roughly by each channel's own tsp duration
# (~20-25s apart) across the ~60-75s heavy-cycle period, which is what
# makes a TRANSITIONING state shorter than the ~75s worst-case cycle
# period actually visible in the ring -- not a literal independent 15s
# timer (the README no longer claims one; see round-8 finding 9).
#
# EXEMPTION WINDOW (round-8 finding 3, BLOCKER): a fixed 60s "is this
# channel still inside its planned-restart grace window" exemption is
# shorter than the real ~75s heavy-cycle period, so a CORRECTLY classified
# planned restart could still get flagged as "not ON_AIR" by the very next
# per-cycle check before its own 60s recovery clock (measured against the
# PASS bound, which is a real product requirement and stays 60s) had even
# been evaluated once. Test-InActivePlannedRestartWindow now takes the
# actual measured cycle period and uses max(60s, 2x that period) as the
# EXEMPTION window (how long a channel is excused from the ON_AIR check
# while a restart is in flight) -- deliberately a SEPARATE number from the
# 60s PASS bound (how long a restart is ALLOWED to take before the run
# fails), which Get-SoakVerdict / SoakVerdict.ps1 still enforces unchanged.

function New-RestartClassifierContext {
    <#
      .SYNOPSIS
      A fresh, isolated state container for one soak run (or one unit
      test). Never share a context across two independent runs/tests.
    #>
    param([int]$RestartTrackingMaxSeconds = 300)
    return [pscustomobject]@{
        Ring = @{}
        PendingRestarts = @{}
        LastPidForChannel = @{}
        RestartEvents = New-Object System.Collections.ArrayList
        RestartTrackingMaxSeconds = $RestartTrackingMaxSeconds
    }
}

function Add-RingSample {
    <#
      .PARAMETER ProcessId
      Deliberately NOT named $Pid -- see this file's header.
    #>
    param($Context, [string]$ChannelId, [datetime]$Utc, $State, $ProcessId, $UpdatedAt)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { $Context.Ring[$ChannelId] = New-Object System.Collections.ArrayList }
    $null = $Context.Ring[$ChannelId].Add([ordered]@{ utc = $Utc.ToUniversalTime().ToString('o'); state = $State; pid = $ProcessId; updated_at = $UpdatedAt })
    while ($Context.Ring[$ChannelId].Count -gt 12) { $Context.Ring[$ChannelId].RemoveAt(0) }
}

function Test-TransitioningInWindow {
    param($Context, [string]$ChannelId, [datetime]$BeforeUtc, [int]$WindowSeconds = 180)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { return $false }
    foreach ($s in @($Context.Ring[$ChannelId])) {
        if ($s.state -ne 'TRANSITIONING') { continue }
        try {
            $sUtc = [datetime]::Parse($s.utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
        } catch { continue }
        if ($sUtc -le $BeforeUtc -and ($BeforeUtc - $sUtc).TotalSeconds -le $WindowSeconds) { return $true }
    }
    return $false
}

function Register-ChannelSample {
    <#
      .SYNOPSIS
      Called for EVERY sample (each interleaved pass, at whatever cadence
      the caller actually achieves) -- records it into the ring, checks
      any pending restart for recovery-or-give-up (evaluated from THIS
      sample's own real timestamp, i.e. from the ring, never from a fixed
      cycle boundary), then checks THIS sample for a new pid change and
      classifies it via Test-TransitioningInWindow.

      .PARAMETER Engine
      The engine already resolved for $NewPid by the CALLER (e.g.
      In-Sandbox-Soak.ps1's Get-EngineForWorkerPid, which needs
      Win32_Process and so cannot live in this pure, synthetic-data-
      testable file). Passing it in, already resolved, is what keeps this
      file testable with plain strings instead of needing to mock WMI.
    #>
    param($Context, [string]$ChannelId, [datetime]$NowUtc, $State, [Nullable[int]]$NewPid, $UpdatedAt, $Engine)

    Add-RingSample -Context $Context -ChannelId $ChannelId -Utc $NowUtc -State $State -ProcessId $NewPid -UpdatedAt $UpdatedAt

    if ($Context.PendingRestarts.ContainsKey($ChannelId)) {
        $pending = $Context.PendingRestarts[$ChannelId]
        if ($State -eq 'ON_AIR' -and $Engine -eq 'gstreamer') {
            $gap = ($NowUtc - $pending.detected_utc).TotalSeconds
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $true; recovery_gap_seconds = [math]::Round($gap, 1)
            })
            $Context.PendingRestarts.Remove($ChannelId)
        } elseif ((($NowUtc) - $pending.detected_utc).TotalSeconds -gt $Context.RestartTrackingMaxSeconds) {
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $false; recovery_gap_seconds = $null
            })
            $Context.PendingRestarts.Remove($ChannelId)
        }
    }

    $prevPid = $(if ($Context.LastPidForChannel.ContainsKey($ChannelId)) { $Context.LastPidForChannel[$ChannelId] } else { $null })
    if ($null -ne $NewPid -and $null -ne $prevPid -and $prevPid -ne $NewPid) {
        $isPlanned = Test-TransitioningInWindow -Context $Context -ChannelId $ChannelId -BeforeUtc $NowUtc -WindowSeconds 180
        $classification = $(if ($isPlanned) { 'planned_restart' } else { 'unplanned_relaunch' })
        $Context.PendingRestarts[$ChannelId] = [ordered]@{ detected_utc = $NowUtc; old_pid = $prevPid; new_pid = $NewPid; classification = $classification }
    }
    if ($null -ne $NewPid) { $Context.LastPidForChannel[$ChannelId] = $NewPid }
}

function Test-InActivePlannedRestartWindow {
    <#
      .SYNOPSIS
      Whether $ChannelId is inside an ACTIVE (not yet recovered)
      planned-restart EXEMPTION window -- the licensed exception
      SoakVerdict.ps1's Test-SoakCycle grants from the ON_AIR check.

      .PARAMETER MeasuredCyclePeriodSeconds
      The actual observed time between the driver's heavy cycles. The
      exemption window is max(60s, 2x this) -- deliberately NOT the same
      60s the PASS contract uses to judge whether a restart recovered in
      time (see this file's header, "EXEMPTION WINDOW"). Default 60 so a
      caller with no measurement yet (the very first cycle) still gets a
      sane answer.
    #>
    param($Context, [string]$ChannelId, [datetime]$NowUtc, [double]$MeasuredCyclePeriodSeconds = 60)
    if (-not $Context.PendingRestarts.ContainsKey($ChannelId)) { return $false }
    $pending = $Context.PendingRestarts[$ChannelId]
    if ($pending.classification -ne 'planned_restart') { return $false }
    $exemptionWindowSeconds = [Math]::Max(60, 2 * $MeasuredCyclePeriodSeconds)
    return (($NowUtc - $pending.detected_utc).TotalSeconds -le $exemptionWindowSeconds)
}

function Get-FlushedRestartEvents {
    <#
      .SYNOPSIS
      Flush any restart still pending (soak ended before it resolved
      either way) into RestartEvents as recovered=$false, then return the
      full event list as a plain array. Call once, at the end of the
      poll loop.

      NOTE: `return ,@(...)` -- the leading unary comma is NOT decorative.
      PowerShell UNWRAPS a single-element array back down to its bare
      element when it crosses a function return/pipeline boundary
      (confirmed directly: `return @($ArrayListOfOne)` came back as the
      bare OrderedDictionary, not a 1-element array, the moment the
      caller had exactly one restart event -- silently breaking any
      caller iterating "for each event" the moment there was only one).
      The comma forces the array to stay an array through that boundary;
      a plain in-place `@(...)` assignment in the SAME scope (never
      crossing a function call) does not have this problem.
    #>
    param($Context)
    foreach ($channelId in @($Context.PendingRestarts.Keys)) {
        $pending = $Context.PendingRestarts[$channelId]
        $null = $Context.RestartEvents.Add([ordered]@{
            channel_id = $channelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
            old_pid = $pending.old_pid; new_pid = $pending.new_pid
            classification = $pending.classification
            recovered = $false; recovery_gap_seconds = $null
        })
        $Context.PendingRestarts.Remove($channelId)
    }
    return ,@($Context.RestartEvents)
}
