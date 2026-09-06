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
        [bool]$InPlannedRestartWindow = $false
    )
    return [ordered]@{
        channel_id = $Id; engine_state = $State; engine = $Engine
        tsduck_verdict = $Tsduck; last_error = $null
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
        $RecoveryGapSeconds = 20
    )
    return [ordered]@{
        channel_id = $ChannelId; detected_utc = $DetectedUtc
        old_pid = $OldPid; new_pid = $NewPid
        classification = $Classification
        recovered = $Recovered; recovery_gap_seconds = $RecoveryGapSeconds
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

Write-Host ""
Write-Host "SoakVerdict unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
