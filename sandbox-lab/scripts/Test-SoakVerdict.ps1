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
        [string]$Engine = 'gstreamer',
        [string]$Tsduck = 'pass',
        [bool]$Relaunched = $false
    )
    return [ordered]@{
        channel_id = $Id; engine_state = $State; engine = $Engine
        tsduck_verdict = $Tsduck; relaunched_this_cycle = $Relaunched
        relaunches_total = $(if ($Relaunched) { 1 } else { 0 })
        last_error = $null
    }
}

function New-Cycle {
    param([string]$Utc, [array]$Channels)
    return [ordered]@{ cycle_utc = $Utc; channels = $Channels }
}

$startUtc = [datetime]::Parse('2026-09-05T18:00:00Z').ToUniversalTime()
$threeChannelsGood = @(
    (New-Channel -Id 'public'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)

# ---------------------------------------------------------------- scenario 1
# All good: warm-up cycle at T+60s (fine even if not ON_AIR, but here IS
# ON_AIR), then 5 post-warmup cycles every 60s all clean. Expect PASS.
$cycles1 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:07:00Z' -Channels $threeChannelsGood)
)
$v1 = Get-SoakVerdict -Cycles $cycles1 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario1 (all good) -> PASS' 'PASS' $v1.verdict

# ---------------------------------------------------------------- scenario 2
# One relaunch in a post-warmup cycle. Expect FAIL.
$channelsWithRelaunch = @(
    (New-Channel -Id 'public' -Relaunched $true), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles2 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $channelsWithRelaunch)
    (New-Cycle -Utc '2026-09-05T18:06:00Z' -Channels $threeChannelsGood)
)
$v2 = Get-SoakVerdict -Cycles $cycles2 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario2 (one relaunch) -> FAIL' 'FAIL' $v2.verdict
Assert-Equal 'scenario2 first_failing_cycle' '2026-09-05T18:05:00Z' $v2.first_failing_cycle

# ---------------------------------------------------------------- scenario 3
# ON_AIR missing AFTER warm-up. Expect FAIL.
$channelsNotOnAir = @(
    (New-Channel -Id 'public' -State 'STARTING'), (New-Channel -Id 'education'), (New-Channel -Id 'government')
)
$cycles3 = @(
    (New-Cycle -Utc '2026-09-05T18:01:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:04:00Z' -Channels $threeChannelsGood)
    (New-Cycle -Utc '2026-09-05T18:05:00Z' -Channels $channelsNotOnAir)
)
$v3 = Get-SoakVerdict -Cycles $cycles3 -StartUtc $startUtc -WarmupSeconds 180
Assert-Equal 'scenario3 (ON_AIR missing post-warmup) -> FAIL' 'FAIL' $v3.verdict
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

Write-Host ""
Write-Host "SoakVerdict unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
