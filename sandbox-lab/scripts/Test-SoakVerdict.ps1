# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-SoakVerdict.ps1 -- pytest-free PowerShell unit checks for
# SoakVerdict.ps1's verify/verdict logic, run against synthetic rollups (no
# sandbox, no live station, no tsp.exe required). Exits non-zero on any
# mismatch so it can gate a build the same way a pytest suite would.
#
# Run: pwsh -File sandbox-lab/scripts/Test-SoakVerdict.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'SoakVerdict.ps1')
# Round-9 finding N6: also dot-source RestartClassifier.ps1 so one scenario
# below can exercise the EXACT end-to-end driver shape
# (RestartClassifier's Get-FlushedRestartEvents -> Get-SoakVerdict
# -RestartEvents), not just SoakVerdict.ps1 in isolation.
. (Join-Path $PSScriptRoot 'RestartClassifier.ps1')

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

function New-Channel {
    param(
        [string]$Id,
        [string]$State = 'ON_AIR',
        # N10: deliberately UNTYPED (not [string]) -- a [string]-typed
        # parameter coerces an explicit -Engine $null argument to '' during
        # PowerShell's own parameter binding (confirmed directly: IsNull=False,
        # IsEmpty=True), so scenario4b's "engine=$null" case was actually
        # exercising engine='' this whole time, never a real null. Untyped
        # binding passes $null through unchanged (confirmed: IsNull=True),
        # which is what a real EgressStateRow-derived row with no engine
        # census match looks like (see In-Sandbox-Soak.ps1's
        # Get-EngineForWorkerPid, which returns $null, never '').
        $Engine = 'gstreamer',
        [string]$Tsduck = 'pass',
        [bool]$InPlannedRestartWindow = $false,
        # Round-10 finding 4: lets a scenario build a row that carries the
        # exact "state read failed" prefix Get-ChannelStateSample stamps in
        # In-Sandbox-Soak.ps1, to test the harness-read-failure exclusion.
        $LastError = $null
    )
    return [ordered]@{
        channel_id = $Id; engine_state = $State; engine = $Engine
        tsduck_verdict = $Tsduck; last_error = $LastError
        in_planned_restart_window = $InPlannedRestartWindow
    }
}

function New-Cycle {
    param([string]$Utc, [array]$Channels)
    return [ordered]@{ cycle_utc = $Utc; channels = $Channels }
}

# Round-6: restart events are now pre-classified by the guest (In-Sandbox-
# Soak.ps1's ring-buffer classification) and handed to Get-SoakVerdict as a
# flat list -- SoakVerdict.ps1 itself never re-derives classification, so
# these unit checks build already-classified events directly, exactly the
# shape the real driver produces.
function New-RestartEvent {
    param(
        [string]$ChannelId,
        [string]$DetectedUtc,
        [string]$Classification,
        [int]$OldPid = 1000,
        [int]$NewPid = 1001,
        [bool]$Recovered = $true,
        $RecoveryGapSeconds = 20,
        # Round-10 finding 8: lets a scenario build a superseded event
        # exactly as RestartClassifier.ps1's Register-ChannelSample flushes
        # one (round-9 N1) -- recovered=$false, recovery_gap_seconds=$null,
        # superseded=$true.
        [bool]$Superseded = $false,
        # Round-11 finding 3: lets a scenario build an event flushed within
        # the final 60s of the soak window (Get-FlushedRestartEvents
        # -SoakEndUtc) -- excluded from the recovery-timeout FAIL rule.
        [bool]$Incomplete = $false
    )
    return [ordered]@{
        channel_id = $ChannelId; detected_utc = $DetectedUtc
        old_pid = $OldPid; new_pid = $NewPid
        classification = $Classification
        recovered = $Recovered; recovery_gap_seconds = $RecoveryGapSeconds
        superseded = $Superseded; incomplete = $Incomplete
    }
}

$startUtc = [datetime]::Parse('2026-09-05T18:00:00Z').ToUniversalTime()
$threeChannelsGood = @(
    (New-Channel -Id 'public'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)

# ---------------------------------------------------------------- scenario 1
# All good: warm-up cycle at T+60s (fine even if not ON_AIR, but here IS
# ON_AIR), then 5 post-warmup cycles every 60s all clean, no restart events
# at all. Expect PASS.
$cycles1 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:07:00Z' -Channels $threeChannelsGood)
)
$v1 = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario1 (all good, no restarts) -> PASS' 'PASS' $v1.verdict
Assert-Equal 'scenario1 unplanned_relaunch_count' 0 $v1.unplanned_relaunch_count
Assert-Equal 'scenario1 planned_restart_count' 0 $v1.planned_restart_count

# ---------------------------------------------------------------- scenario 2
# ONE unplanned relaunch event (no TRANSITIONING preceded it -- a crash).
# Expect FAIL regardless of how clean every cycle otherwise looks.
$cycles2 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $threeChannelsGood)
)
$restartEvents2 = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'unplanned_relaunch' -Recovered $true -RecoveryGapSeconds 10)
)
$v2 = Get-SoakVerdict -Cycles $cycles2 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents2
Assert-Equal 'scenario2 (one unplanned relaunch) -> FAIL' 'FAIL' $v2.verdict
Assert-Equal 'scenario2 unplanned_relaunch_count' 1 $v2.unplanned_relaunch_count

# ---------------------------------------------------------------- scenario 3
# ON_AIR missing AFTER warm-up, with NO restart classification covering it
# (in_planned_restart_window=$false) -- must still FAIL exactly as before
# round 6 (the exemption is narrow: only a channel the guest explicitly
# marked as inside a classified planned-restart window is excused).
$channelsNotOnAir = @(
    (New-Channel -Id 'public' -State 'STARTING'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles3 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $channelsNotOnAir)
)
$v3 = Get-SoakVerdict -Cycles $cycles3 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario3 (ON_AIR missing post-warmup, no restart window) -> FAIL' 'FAIL' $v3.verdict
Assert-Equal 'scenario3 first_failing_cycle' '2026-09-05T18:05:00Z' $v3.first_failing_cycle

# ---------------------------------------------------------------- scenario 4
# ON_AIR missing DURING warm-up only (transitioning right after start, the
# exact soak8 finding in DIRECTIVE-4.md line 162), then clean afterwards.
# Expect PASS.
$cycles4 = @(
    (New-Cycle -Utc '2026-09-05T18:00:19Z' -Channels $channelsNotOnAir)   # T+19s, inside 180s warm-up
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)  # T+60s, still inside warm-up
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)  # T+240s, post-warmup, clean
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
)
$v4 = Get-SoakVerdict -Cycles $cycles4 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario4 (ON_AIR missing warm-up only) -> PASS' 'PASS' $v4.verdict

# -------------------------------------------------------------- scenario 4b
# engine=$null post-warmup (EgressStateRow carries no `engine` field --
# civiccast/egress/models.py:506-518 -- so this is what a worker-pid-found-
# but-census-inconclusive, or no-worker-at-all, row looks like). Expect FAIL
# -- a null engine must never read as "probably gstreamer, close enough".
$channelsEngineNull = @(
    (New-Channel -Id 'public' -Engine $null), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles4b = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsEngineNull)
)
$v4b = Get-SoakVerdict -Cycles $cycles4b -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario4b (engine=null post-warmup) -> FAIL' 'FAIL' $v4b.verdict

# -------------------------------------------------------------- scenario 4c
# engine='ffmpeg-fallback' post-warmup (allow_software_fallback=$false in
# the channel config makes this a real, visible failure -- see
# In-Sandbox-Soak.ps1's channel config body). Expect FAIL.
$channelsFfmpegFallback = @(
    (New-Channel -Id 'public' -Engine 'ffmpeg-fallback'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles4c = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsFfmpegFallback)
)
$v4c = Get-SoakVerdict -Cycles $cycles4c -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario4c (engine=ffmpeg-fallback post-warmup) -> FAIL' 'FAIL' $v4c.verdict

# ---------------------------------------------------------------- scenario 5
# tsduck fail post-warmup. Expect FAIL (sanity check for the tsp-fail path).
$channelsTspFail = @(
    (New-Channel -Id 'public' -Tsduck 'fail-stream-errors'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles5 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsTspFail)
)
$v5 = Get-SoakVerdict -Cycles $cycles5 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario5 (tsp fail post-warmup) -> FAIL' 'FAIL' $v5.verdict

# ---------------------------------------------------------------- scenario 6
# Every cycle inside warm-up (soak too short) -> FAIL, never a false PASS.
$cycles6 = @(
    (New-Cycle -Utc '2026-09-05T18:00:10Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
)
$v6 = Get-SoakVerdict -Cycles $cycles6 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario6 (all cycles inside warm-up) -> FAIL' 'FAIL' $v6.verdict

# ---------------------------------------------------------------- scenario 7
# No cycles at all -> FAIL, never a false PASS.
$v7 = Get-SoakVerdict -Cycles @() -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario7 (no cycles) -> FAIL' 'FAIL' $v7.verdict

# ---------------------------------------------------------------- scenario 8
# Round 6, item 2: a PLANNED restart (TRANSITIONING preceded the pid
# change) that returned to ON_AIR on gstreamer in 20s. The channel's cycle
# row during the restart window is marked in_planned_restart_window so the
# per-cycle ON_AIR check does not separately flag it. Expect PASS.
#
# Round-8 finding 3: cycles are now spaced 75s apart (not a flat 60s) --
# the measured real heavy-cycle period once 3 serial ~20-25s tsp probes are
# accounted for, per the coordinator's own instruction to fix this scenario
# onto realistic spacing. Test-SoakCycle itself does not consume cycle
# period directly (in_planned_restart_window is pre-computed by the guest
# using RestartClassifier.ps1's own max(60s, 2x measured period) exemption
# -- see Test-RestartClassifier.ps1's scenario 7 for THAT unit coverage);
# this scenario exists to prove SoakVerdict.ps1 still PASSes a realistic,
# non-60s-aligned cycle timeline once the guest has done its job.
$channelsPublicInRestartWindow = @(
    (New-Channel -Id 'public' -State 'TRANSITIONING' -Engine $null -InPlannedRestartWindow $true)
    (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles8 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)                # T+60s, warm-up
    (New-Cycle -Utc '2026-09-05T18:03:15Z' -Channels $threeChannelsGood)                # T+195s, post-warmup, clean
    (New-Cycle -Utc '2026-09-05T18:04:30Z' -Channels $channelsPublicInRestartWindow)    # +75s, restart in progress
    (New-Cycle -Utc '2026-09-05T18:05:45Z' -Channels $threeChannelsGood)                # +75s, recovered
)
$restartEvents8 = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $true -RecoveryGapSeconds 20)
)
$v8 = Get-SoakVerdict -Cycles $cycles8 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents8
Assert-Equal 'scenario8 (planned restart, 20s recovery, 75s-spaced cycles) -> PASS' 'PASS' $v8.verdict
Assert-Equal 'scenario8 planned_restart_count' 1 $v8.planned_restart_count
Assert-Equal 'scenario8 max_restart_gap_seconds' 20 $v8.max_restart_gap_seconds

# ---------------------------------------------------------------- scenario 9
# A PLANNED restart that took 90s to recover -- exceeds the 60s PASS bound
# (a SEPARATE number from the exemption window RestartClassifier.ps1 uses
# to decide in_planned_restart_window -- see that file's header,
# "EXEMPTION WINDOW"). Expect FAIL even though the classification itself
# was correct (planned, not a crash) -- "planned" only excuses the OUTAGE,
# not a slow recovery.
$restartEvents9 = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $true -RecoveryGapSeconds 90)
)
$v9 = Get-SoakVerdict -Cycles $cycles8 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents9
Assert-Equal 'scenario9 (planned restart, 90s recovery, 75s-spaced cycles) -> FAIL' 'FAIL' $v9.verdict

# --------------------------------------------------------------- scenario 10
# A pid change classified unplanned_relaunch because NO TRANSITIONING
# sample preceded it (the guest's own classification, handed in
# pre-computed) -- must FAIL even if it "recovered" quickly, since a
# crash-and-restart is still a crash.
$restartEvents10 = @(
    (New-RestartEvent -ChannelId 'education' -DetectedUtc '2026-09-05T18:05:10Z' -Classification 'unplanned_relaunch' -Recovered $true -RecoveryGapSeconds 15)
)
$v10 = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents10
Assert-Equal 'scenario10 (pid change w/o TRANSITIONING, classified unplanned) -> FAIL' 'FAIL' $v10.verdict
Assert-Equal 'scenario10 unplanned_relaunch_count' 1 $v10.unplanned_relaunch_count

# --------------------------------------------------------------- scenario 11
# Round-8 finding 5: tsp 'not-run' (tool missing) is a HARNESS/TOOLING
# defect, never a product FAIL -- it says nothing about the product because
# the probe never ran at all. Must classify HARNESS_ERROR even though every
# channel otherwise looks perfectly healthy.
$channelsTspNotRun = @(
    (New-Channel -Id 'public' -Tsduck 'not-run: tsp.exe not found'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles11 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsTspNotRun)
)
$v11 = Get-SoakVerdict -Cycles $cycles11 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario11a (tsp not-run, tool missing) -> HARNESS_ERROR' 'HARNESS_ERROR' $v11.verdict

# A tsp exception (process threw trying to launch) is the same class of
# harness defect, also HARNESS_ERROR.
$channelsTspError = @(
    (New-Channel -Id 'public' -Tsduck 'error: access denied launching tsp.exe'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles11b = @(
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsTspError)
)
$v11b = Get-SoakVerdict -Cycles $cycles11b -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario11b (tsp error: launching) -> HARNESS_ERROR' 'HARNESS_ERROR' $v11b.verdict

# fail-timed-out and fail-zero-packets (tsp DID run) stay product FAIL,
# never HARNESS_ERROR -- the negative-control half of this same finding.
$channelsTspTimedOut = @(
    (New-Channel -Id 'public' -Tsduck 'fail-timed-out'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles11c = @(
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsTspTimedOut)
)
$v11c = Get-SoakVerdict -Cycles $cycles11c -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario11c (tsp fail-timed-out, tool ran) -> FAIL (not HARNESS_ERROR)' 'FAIL' $v11c.verdict

# --------------------------------------------------------------- scenario 12
# Round-9 finding N3: the FULL tsp verdict -> classification routing table,
# one assertion per verdict string, so every tsp verdict this lane can
# produce (Test-TsProof in In-Sandbox-Soak.ps1) is proven to route to the
# right class in one place. 'fail-no-report'/'fail-unparsable-report'/
# 'fail-no-ts-section' join 'not-run'/'error:*' as HARNESS_ERROR (tsp exited
# 0 but produced nothing analyzable -- the beta.3 empty-report precedent);
# every other 'fail-*' shape and 'pass' are unchanged.
$tspRoutingTable = @(
    @{ Verdict = 'not-run'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'not-run: tsp.exe not found'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'error: could not start process'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'fail-no-report'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'fail-unparsable-report'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'fail-no-ts-section'; Expect = 'HARNESS_ERROR' }
    @{ Verdict = 'fail-timed-out'; Expect = 'FAIL' }
    @{ Verdict = 'fail-zero-packets'; Expect = 'FAIL' }
    @{ Verdict = 'fail-exit-1'; Expect = 'FAIL' }
    @{ Verdict = 'fail-stream-errors'; Expect = 'FAIL' }
    @{ Verdict = 'pass'; Expect = 'PASS' }
)
foreach ($row in $tspRoutingTable) {
    $channelsRow = @(
        (New-Channel -Id 'public' -Tsduck $row.Verdict), (New-Channel -Id 'education' -Tsduck $row.Verdict), (New-Channel -Id 'government' -Tsduck $row.Verdict)
    )
    $cyclesRow = @((New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsRow))
    $vRow = Get-SoakVerdict -Cycles $cyclesRow -StartUtc $startUtc -WarmupSeconds 180
    Assert-Equal "scenario12 tsp routing '$($row.Verdict)' -> $($row.Expect)" $row.Expect $vRow.verdict
}

# --------------------------------------------------------------- scenario 13
# Round-9 finding N6 (BLOCKER), end to end through the EXACT real-driver
# shape: RestartClassifier.ps1's Register-ChannelSample/Get-FlushedRestartEvents
# (real functions, not synthetic New-RestartEvent objects) feeding
# Get-SoakVerdict -RestartEvents, exactly as In-Sandbox-Soak.ps1 wires them.
# TWO planned restarts (different channels), each recovering in 200s --
# past the 60s PASS bound. The previous `return ,@(...)` form double-wrapped
# this exact 2-event array under the driver's own `@(Get-FlushedRestartEvents
# ...)` calling shape (confirmed directly), so Get-SoakVerdict never saw
# more than a single nested element, max_restart_gap_seconds came back
# empty, and the >60s rule never fired -- this is precisely the
# "two planned restarts recovering in 200s => PASS" false-negative the
# review reported. Expect FAIL and max_restart_gap_seconds=200.
$n6Start = [datetime]::Parse('2026-09-05T19:00:00Z').ToUniversalTime()
$n6Ctx = New-RestartClassifierContext
foreach ($chan in 'public', 'education') {
    Register-ChannelSample -Context $n6Ctx -ChannelId $chan -NowUtc $n6Start -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
    Register-ChannelSample -Context $n6Ctx -ChannelId $chan -NowUtc $n6Start.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
    Register-ChannelSample -Context $n6Ctx -ChannelId $chan -NowUtc $n6Start.AddSeconds(40) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null
    Register-ChannelSample -Context $n6Ctx -ChannelId $chan -NowUtc $n6Start.AddSeconds(240) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine 'gstreamer'
}
$n6Events = @(Get-FlushedRestartEvents -Context $n6Ctx)
Assert-Equal 'scenario13a (2 planned restarts, real driver shape) -> both events present' 2 $n6Events.Count
$v13 = Get-SoakVerdict -Cycles @() -StartUtc $n6Start -WarmupSeconds 180 -RestartEvents $n6Events
Assert-Equal 'scenario13b (both recovered in 200s, exceeds 60s bound) -> FAIL' 'FAIL' $v13.verdict
Assert-Equal 'scenario13c (max_restart_gap_seconds = 200, not empty/nested)' 200 $v13.max_restart_gap_seconds
Assert-Equal 'scenario13d (planned_restart_count = 2, both counted)' 2 $v13.planned_restart_count

# --------------------------------------------------------------- scenario 14
# Round-10 finding 4 (HIGH): a channel row whose state read FAILED
# (last_error starting with the literal "state read failed") carries
# engine_state=$null -- previously indistinguishable from a channel
# genuinely off air. A SINGLE such row, post-warmup, must be excused from
# the ON_AIR check (not FAIL) -- but THREE CONSECUTIVE such rows for the
# same channel must escalate to HARNESS_ERROR (the read path itself is
# broken), never silently pass forever with engine_state=$null the whole
# time, and never present as a product FAIL either.
$channelsOneReadFailure = @(
    (New-Channel -Id 'public' -State $null -Engine $null -LastError 'state read failed: status=0 error=timeout'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles14a = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsOneReadFailure)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
)
$v14a = Get-SoakVerdict -Cycles $cycles14a -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario14a (ONE state-read-failure row post-warmup) -> PASS (excused, not FAIL)' 'PASS' $v14a.verdict

$cycles14b = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsOneReadFailure)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $channelsOneReadFailure)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $channelsOneReadFailure)
)
$v14b = Get-SoakVerdict -Cycles $cycles14b -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario14b (THREE consecutive state-read-failure rows) -> HARNESS_ERROR' 'HARNESS_ERROR' $v14b.verdict

# A read failure that is NOT consecutive (a good read in between) must
# reset the streak and never escalate.
$cycles14c = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsOneReadFailure)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $channelsOneReadFailure)
    (New-Cycle -Utc '2026-09-05T18:07:00Z' -Channels $channelsOneReadFailure)
)
$v14c = Get-SoakVerdict -Cycles $cycles14c -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario14c (read failures NOT consecutive, streak resets) -> PASS' 'PASS' $v14c.verdict

# --------------------------------------------------------------- scenario 15
# Round-10 finding 8 (MEDIUM): a SUPERSEDED planned-restart event
# (recovered=$false, recovery_gap_seconds=$null, superseded=$true --
# RestartClassifier.ps1's round-9 N1 flush) must NOT itself count against
# the 60s recovery-time FAIL rule -- it is accounted for by whatever pid
# change superseded it. Only the superseded event is present here (no
# successor event added), isolating the exclusion itself.
$restartEvents15 = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $false -RecoveryGapSeconds $null -Superseded $true)
)
$v15 = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents15
Assert-Equal 'scenario15 (superseded planned restart, recovered=false/gap=null) -> PASS (excluded from recovery rule)' 'PASS' $v15.verdict
Assert-Equal 'scenario15 planned_restart_count still counts the superseded event' 1 $v15.planned_restart_count

# --------------------------------------------------------------- scenario 16
# Round-11 finding 3 (HIGH): an INCOMPLETE planned-restart event (detected
# within the final 60s of the soak window, recovered=$false,
# recovery_gap_seconds=$null -- Get-FlushedRestartEvents -SoakEndUtc's own
# flush shape) must NOT count against the 60s recovery-timeout FAIL rule,
# exactly like a superseded event. The non-incomplete NEGATIVE control
# (identical shape but incomplete=$false) must still FAIL -- proving the
# exclusion is scoped to incomplete events only, never a blanket pass for
# "never recovered".
$restartEvents16 = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $false -RecoveryGapSeconds $null -Incomplete $true)
)
$v16 = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents16
Assert-Equal 'scenario16a (incomplete planned restart, recovered=false/gap=null) -> PASS (excluded from recovery rule)' 'PASS' $v16.verdict
Assert-Equal 'scenario16a incomplete_restart_count' 1 $v16.incomplete_restart_count

$restartEvents16b = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $false -RecoveryGapSeconds $null -Incomplete $false)
)
$v16b = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents16b
Assert-Equal 'scenario16b (NOT incomplete, never recovered) -> FAIL' 'FAIL' $v16b.verdict
Assert-Equal 'scenario16b incomplete_restart_count' 0 $v16b.incomplete_restart_count

# --------------------------------------------------------------- scenario 17
# Round-11 finding 4 (MEDIUM): under the NORMAL (flag-off) contract, a
# classified planned_restart is perfectly normal and must still PASS
# (scenario8 already proves this) -- the STRICTER contract only applies
# when -SeamlessReload is explicitly passed. Re-run scenario8's exact
# clean-planned-restart fixture with -SeamlessReload $true and confirm it
# now FAILS (a planned_restart under this flag means the seamless path
# did not run), then confirm the SAME fixture still PASSES with the flag
# left at its default ($false).
$vSeamlessOff = Get-SoakVerdict -Cycles $cycles8 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents8
Assert-Equal 'scenario17a (planned restart, -SeamlessReload NOT passed) -> PASS' 'PASS' $vSeamlessOff.verdict
$vSeamlessOn = Get-SoakVerdict -Cycles $cycles8 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents8 -SeamlessReload $true
Assert-Equal 'scenario17b (identical fixture, -SeamlessReload $true) -> FAIL (planned_restart_count must be 0 under the flag)' 'FAIL' $vSeamlessOn.verdict

# A reload_aborted event under -SeamlessReload is ALSO a FAIL, even with
# zero restart events at all (no unplanned, no planned) -- the abort
# itself is the failure, a fallback-to-restart the flag promised would
# never happen.
$reloadAborts17 = @(@{ channel_id = 'public'; reason = 'did not land (aborted: build failed)' })
$vSeamlessAbort = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -SeamlessReload $true -ReloadAbortEvents $reloadAborts17
Assert-Equal 'scenario17c (reload_aborted event, -SeamlessReload $true, no restart events at all) -> FAIL' 'FAIL' $vSeamlessAbort.verdict
Assert-Equal 'scenario17c reload_aborted_count' 1 $vSeamlessAbort.reload_aborted_count

# The SAME reload-abort event under the NORMAL (flag-off) contract is NOT
# a failure -- a fallback-to-restart is exactly what flag-off operation
# is; reload_aborted only fails the run when the flag is actually claiming
# the seamless path should have been used.
$vNoSeamlessAbort = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -ReloadAbortEvents $reloadAborts17
Assert-Equal 'scenario17d (same reload_aborted event, flag NOT passed) -> PASS (not a failure off-flag)' 'PASS' $vNoSeamlessAbort.verdict
Assert-Equal 'scenario17d reload_aborted_count still reported' 1 $vNoSeamlessAbort.reload_aborted_count

# The NON-superseded negative control: the identical recovered=false/gap=null
# shape, but superseded=$false, must still FAIL exactly as scenario9 proves
# for a slow recovery -- confirming the exclusion is scoped to superseded
# events only, not a blanket pass for "never recovered".
$restartEvents15b = @(
    (New-RestartEvent -ChannelId 'public' -DetectedUtc '2026-09-05T18:04:30Z' -Classification 'planned_restart' -Recovered $false -RecoveryGapSeconds $null -Superseded $false)
)
$v15b = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents15b
Assert-Equal 'scenario15b (NOT superseded, never recovered) -> FAIL' 'FAIL' $v15b.verdict

# --------------------------------------------------------------- scenario 18
# Round-12 finding 6 (MEDIUM): a harness-shape tsp/read-failure defect must
# NEVER pre-empt a confirmed product FAIL, and must never even be
# evaluated (let alone escalate) when confined entirely to the warm-up
# window.
#
# 18a: a POST-warmup cycle carries a tsp harness-shape defect (tool
# missing) AND a confirmed unplanned_relaunch restart event exists. The
# run must report FAIL (the crash), with the harness-shape defect
# mentioned as a note in the reason -- never silently reported as
# HARNESS_ERROR, which would look like the crash never happened at all.
$channelsTspNotRunPostWarmup = @(
    (New-Channel -Id 'public' -Tsduck 'not-run: tsp.exe not found'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles18a = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsTspNotRunPostWarmup)
)
$restartEvents18a = @(
    (New-RestartEvent -ChannelId 'education' -DetectedUtc '2026-09-05T18:02:00Z' -Classification 'unplanned_relaunch' -Recovered $true -RecoveryGapSeconds 10)
)
$v18a = Get-SoakVerdict -Cycles $cycles18a -StartUtc $startUtc -WarmupSeconds 180 -RestartEvents $restartEvents18a
Assert-Equal 'scenario18a (post-warmup tsp harness-defect AND a confirmed unplanned relaunch) -> FAIL, not HARNESS_ERROR' 'FAIL' $v18a.verdict
Assert-Equal 'scenario18a reason mentions the crash' $true ($v18a.reason -match 'unplanned relaunch')
Assert-Equal 'scenario18a reason ALSO carries the harness note (never silently dropped)' $true ($v18a.reason -match 'harness-shape')

# 18b: the SAME tsp harness-shape defect, but confined ENTIRELY to the
# warm-up window, with everything else clean post-warmup -- must PASS. A
# harness-shape defect the run never even got to evaluate (still inside
# warm-up, where the tsp probe/read path may not be meaningful yet) is not
# surfaced as anything at all.
$cycles18b = @(
    (New-Cycle -Utc '2026-09-05T18:00:19Z' -Channels $channelsTspNotRunPostWarmup)   # T+19s, inside 180s warm-up
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)             # post-warmup, clean
)
$v18b = Get-SoakVerdict -Cycles $cycles18b -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario18b (tsp harness-defect confined to warm-up only) -> PASS' 'PASS' $v18b.verdict

# 18c: the harness-shape defect IS post-warmup, and there is NO confirmed
# product FAIL anywhere -- must still report HARNESS_ERROR (the round-8/10
# baseline behavior, now correctly scoped to post-warmup cycles only).
$v18c = Get-SoakVerdict -Cycles $cycles18a -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario18c (post-warmup tsp harness-defect, no product FAIL) -> HARNESS_ERROR' 'HARNESS_ERROR' $v18c.verdict

# 18d: a 3-consecutive-read-failure streak that STARTS during warm-up and
# continues past it -- the tally must carry across the warm-up boundary
# (not reset at the boundary), but the ESCALATION only fires once the
# triggering cycle is itself post-warmup.
$channelsOneReadFailure18d = @(
    (New-Channel -Id 'public' -State $null -Engine $null -LastError 'state read failed: status=0 error=timeout'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles18d = @(
    (New-Cycle -Utc '2026-09-05T18:00:10Z' -Channels $channelsOneReadFailure18d)   # T+10s, warm-up, streak=1
    (New-Cycle -Utc '2026-09-05T18:00:40Z' -Channels $channelsOneReadFailure18d)   # T+40s, warm-up, streak=2
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $channelsOneReadFailure18d)   # post-warmup, streak=3 -> escalate
)
$v18d = Get-SoakVerdict -Cycles $cycles18d -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario18d (read-failure streak spans the warm-up boundary, escalates once post-warmup) -> HARNESS_ERROR' 'HARNESS_ERROR' $v18d.verdict

Write-Host ""
Write-Host "SoakVerdict unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
