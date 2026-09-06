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
    param($Context, [string]$ChannelId, [datetime]$Utc, $State, $ProcessId, $UpdatedAt, $LastError)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { $Context.Ring[$ChannelId] = New-Object System.Collections.ArrayList }
    $null = $Context.Ring[$ChannelId].Add([ordered]@{ utc = $Utc.ToUniversalTime().ToString('o'); state = $State; pid = $ProcessId; updated_at = $UpdatedAt; last_error = $LastError })
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

function Test-PlannedRestartSignal {
    <#
      .SYNOPSIS
      Round-9 "CLASSIFIER TRUTH" fix: TRANSITIONING-preceded-the-pid-change
      alone is NOT sufficient evidence of a planned restart. Measured on
      609273d (item 60): the daemon writes TRANSITIONING and the worker
      then CRASHES ~1s later -- the old rule ("TRANSITIONING within 3 min
      before pid change => planned") called that crash planned. A REAL
      planned (flag-OFF) restart at main 250026b is: TRANSITIONING ->
      worker exits 0 after EOS -> daemon _start -> STARTING -> ON_AIR. A
      crash is: non-zero exit / last_error set / state ERROR or
      FALLBACK_SLATE, or a daemon "relaunch after crash" log line.

      Round-9 finding N7 tightens this further: TRANSITIONING must be the
      LAST non-ON_AIR-pid-change-adjacent state observed for the OLD pid --
      i.e. the sample IMMEDIATELY PRECEDING the pid-change sample in the
      ring, not merely "seen at some point in the last 180s" -- AND within
      one sample interval (~30s default) of the pid change. A wide 180s
      lookback could match a stale TRANSITIONING from an entirely earlier,
      unrelated event; the tightened rule only credits the state
      transition that immediately, contiguously precedes THIS specific pid
      change.

      Classifies planned ONLY if:
        1. The ring sample immediately before $BeforeUtc (the pid-change
           sample itself, already added to the ring before this is called)
           has state == 'TRANSITIONING', AND
        2. That sample's timestamp is within $MaxGapSeconds of $BeforeUtc, AND
        3. NO sample between that TRANSITIONING sample and $BeforeUtc shows
           state in ('ERROR','FALLBACK_SLATE') or a non-null/non-empty
           last_error (defense-in-depth -- with the tightened window there
           should be no room for anything to occur between two adjacent
           samples, but this is checked rather than assumed).
      Worker exit code (mentioned in the review as a third, "if available"
      signal from parsing the daemon's own log lines) is NOT implemented
      here -- no confirmed log line format for it was found in this repo's
      current checkout (grepped, no match), so this does not invent a
      pattern with no evidence behind it; the signals above are both
      directly available from the state API this lane already polls.
    #>
    param($Context, [string]$ChannelId, [datetime]$BeforeUtc, [int]$MaxGapSeconds = 30)
    if (-not $Context.Ring.ContainsKey($ChannelId)) { return $false }
    $samples = @($Context.Ring[$ChannelId] | ForEach-Object {
        $sUtc = $null
        try { $sUtc = [datetime]::Parse($_.utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime() } catch { }
        if ($sUtc) { [pscustomobject]@{ utc = $sUtc; state = $_.state; last_error = $_.last_error } }
    } | Sort-Object utc)

    # The sample AT $BeforeUtc is the pid-change sample itself (already
    # added to the ring by Add-RingSample before this is called) -- the
    # "last non-ON_AIR state of the OLD pid" is the sample immediately
    # PRECEDING it, i.e. the most recent one strictly earlier than $BeforeUtc.
    $priorSamples = @($samples | Where-Object { $_.utc -lt $BeforeUtc })
    if ($priorSamples.Count -eq 0) { return $false }
    $lastPrior = $priorSamples[-1]

    if ($lastPrior.state -ne 'TRANSITIONING') { return $false }
    if (($BeforeUtc - $lastPrior.utc).TotalSeconds -gt $MaxGapSeconds) { return $false }

    foreach ($s in $samples) {
        if ($s.utc -le $lastPrior.utc -or $s.utc -gt $BeforeUtc) { continue }
        if ($s.state -eq 'ERROR' -or $s.state -eq 'FALLBACK_SLATE') { return $false }
        if (-not [string]::IsNullOrWhiteSpace("$($s.last_error)")) { return $false }
    }
    return $true
}

function Register-ChannelSample {
    <#
      .SYNOPSIS
      Called for EVERY sample (each interleaved pass, at whatever cadence
      the caller actually achieves) -- records it into the ring, checks
      any pending restart for recovery-or-give-up (evaluated from THIS
      sample's own real timestamp, i.e. from the ring, never from a fixed
      cycle boundary), then checks THIS sample for a new pid change and
      classifies it via Test-PlannedRestartSignal.

      .PARAMETER Engine
      The engine already resolved for $NewPid by the CALLER (e.g.
      In-Sandbox-Soak.ps1's Get-EngineForWorkerPid, which needs
      Win32_Process and so cannot live in this pure, synthetic-data-
      testable file). Passing it in, already resolved, is what keeps this
      file testable with plain strings instead of needing to mock WMI.

      .PARAMETER LastError
      The state row's own last_error field for THIS sample -- feeds
      Test-PlannedRestartSignal's crash-signal check (round-9
      "CLASSIFIER TRUTH").
    #>
    param($Context, [string]$ChannelId, [datetime]$NowUtc, $State, [Nullable[int]]$NewPid, $UpdatedAt, $Engine, $LastError)

    # Round-9 finding N1 (BLOCKER): a SECOND pid change arriving while a
    # PREVIOUS one for the same channel is still pending (unresolved) used
    # to overwrite $Context.PendingRestarts[$ChannelId] outright, silently
    # ERASING the first event -- measured: 2 relaunches collapsed into 1
    # recorded event; a crash immediately followed by a legitimate rollover
    # could read as PASS with unplanned_relaunch_count=0. Flush the
    # existing pending restart as its OWN event (recovered=$false,
    # superseded=$true, its ORIGINAL classification preserved) BEFORE
    # recording the new one, so a crash is never silently absorbed by
    # whatever restart happens to come after it.
    $prevPidBeforeThisSample = $(if ($Context.LastPidForChannel.ContainsKey($ChannelId)) { $Context.LastPidForChannel[$ChannelId] } else { $null })
    $pidChangedThisSample = ($null -ne $NewPid -and $null -ne $prevPidBeforeThisSample -and $prevPidBeforeThisSample -ne $NewPid)
    if ($pidChangedThisSample -and $Context.PendingRestarts.ContainsKey($ChannelId)) {
        $superseded = $Context.PendingRestarts[$ChannelId]
        $null = $Context.RestartEvents.Add([ordered]@{
            channel_id = $ChannelId; detected_utc = $superseded.detected_utc.ToUniversalTime().ToString('o')
            old_pid = $superseded.old_pid; new_pid = $superseded.new_pid
            classification = $superseded.classification
            recovered = $false; recovery_gap_seconds = $null; superseded = $true
        })
        $Context.PendingRestarts.Remove($ChannelId)
    }

    Add-RingSample -Context $Context -ChannelId $ChannelId -Utc $NowUtc -State $State -ProcessId $NewPid -UpdatedAt $UpdatedAt -LastError $LastError

    if ($Context.PendingRestarts.ContainsKey($ChannelId)) {
        $pending = $Context.PendingRestarts[$ChannelId]
        if ($State -eq 'ON_AIR' -and $Engine -eq 'gstreamer') {
            $gap = ($NowUtc - $pending.detected_utc).TotalSeconds
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $true; recovery_gap_seconds = [math]::Round($gap, 1); superseded = $false
            })
            $Context.PendingRestarts.Remove($ChannelId)
        } elseif ((($NowUtc) - $pending.detected_utc).TotalSeconds -gt $Context.RestartTrackingMaxSeconds) {
            $null = $Context.RestartEvents.Add([ordered]@{
                channel_id = $ChannelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
                old_pid = $pending.old_pid; new_pid = $pending.new_pid
                classification = $pending.classification
                recovered = $false; recovery_gap_seconds = $null; superseded = $false
            })
            $Context.PendingRestarts.Remove($ChannelId)
        }
    }

    if ($pidChangedThisSample) {
        $isPlanned = Test-PlannedRestartSignal -Context $Context -ChannelId $ChannelId -BeforeUtc $NowUtc -MaxGapSeconds 30
        $classification = $(if ($isPlanned) { 'planned_restart' } else { 'unplanned_relaunch' })
        $Context.PendingRestarts[$ChannelId] = [ordered]@{ detected_utc = $NowUtc; old_pid = $prevPidBeforeThisSample; new_pid = $NewPid; classification = $classification }
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

      CALLING CONVENTION (round-9 finding N6, BLOCKER -- a regression this
      review caught in the round-8 fix): ALWAYS call this as
      `@(Get-FlushedRestartEvents -Context $ctx)` -- never a bare
      `$x = Get-FlushedRestartEvents ...`. `return @($Context.RestartEvents)`
      ENUMERATES the array onto the function's output stream (N separate
      pipeline objects, not one array object), and the caller's own `@()`
      collects however many objects actually flow through -- confirmed
      directly to work correctly for N=0, 1, 2, and 3 with this exact
      calling shape. The PREVIOUS version of this function used
      `return ,@(...)` (a leading unary comma) to fix a DIFFERENT, narrower
      problem (a bare, unwrapped `$x = Get-Foo` call silently collapsing a
      1-element array down to its bare element) -- but the comma forces the
      function to emit exactly ONE pipeline object (an array containing the
      real array as its single element), so the driver's actual calling
      shape (`$restartEventsArray = @(Get-FlushedRestartEvents ...)`,
      In-Sandbox-Soak.ps1) received a 1-element array whose sole element
      was the REAL N-element array, for every N -- confirmed directly.
      Two real relaunches collapsed to Count=1 (not 2), max_restart_gap_seconds
      read empty, the >60s recovery-time FAIL rule stopped firing, and
      restart-events.json serialized as a nested `{"value":[...]}` shape.
      The fix is symmetric with the ORIGINAL problem it was chasing: keep
      the plain `@(...)` return AND always call this function through an
      `@()` wrapper -- never through a bare assignment, which is the one
      calling shape this plain form does not handle safely for N=1.
    #>
    param($Context)
    foreach ($channelId in @($Context.PendingRestarts.Keys)) {
        $pending = $Context.PendingRestarts[$channelId]
        $null = $Context.RestartEvents.Add([ordered]@{
            channel_id = $channelId; detected_utc = $pending.detected_utc.ToUniversalTime().ToString('o')
            old_pid = $pending.old_pid; new_pid = $pending.new_pid
            classification = $pending.classification
            recovered = $false; recovery_gap_seconds = $null; superseded = $false
        })
        $Context.PendingRestarts.Remove($channelId)
    }
    return @($Context.RestartEvents)
}
