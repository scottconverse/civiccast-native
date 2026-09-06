# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-RestartClassifier.ps1 -- pytest-free PowerShell unit checks for
# RestartClassifier.ps1, fed synthetic (utc, state, pid) tuples. No
# sandbox, no live station required.
#
# Run: pwsh -File sandbox-lab/scripts/Test-RestartClassifier.ps1

$ErrorActionPreference = 'Stop'
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

$baseUtc = [datetime]::Parse('2026-09-06T07:49:00Z').ToUniversalTime()

# ---------------------------------------------------------------- scenario 1
# REGRESSION GUARD for round-8 finding 1: Add-RingSample must actually
# populate the ring. This is the exact unit check that would have caught
# the $Pid-shadows-$PID bug immediately -- with the bug present,
# Add-RingSample silently no-ops (PowerShell writes a non-terminating
# "Cannot overwrite variable Pid" error and returns), so the ring stays
# empty and this assertion fails.
$ctx1 = New-RestartClassifierContext
Add-RingSample -Context $ctx1 -ChannelId 'public' -Utc $baseUtc -State 'ON_AIR' -ProcessId 1001 -UpdatedAt $baseUtc.ToString('o')
Assert-Equal 'scenario1 (Add-RingSample actually adds a sample)' 1 $ctx1.Ring['public'].Count
Assert-Equal 'scenario1 sample pid recorded correctly' 1001 $ctx1.Ring['public'][0].pid

# ---------------------------------------------------------------- scenario 2
# Ring caps at 12 samples, dropping the OLDEST first.
$ctx2 = New-RestartClassifierContext
for ($i = 0; $i -lt 15; $i++) {
    Add-RingSample -Context $ctx2 -ChannelId 'public' -Utc $baseUtc.AddSeconds($i * 15) -State 'ON_AIR' -ProcessId 1001 -UpdatedAt $null
}
Assert-Equal 'scenario2 (ring caps at 12)' 12 $ctx2.Ring['public'].Count
Assert-Equal 'scenario2 (oldest 3 dropped, first remaining is sample #3)' $baseUtc.AddSeconds(3 * 15).ToString('o') $ctx2.Ring['public'][0].utc

# ---------------------------------------------------------------- scenario 3
# Test-TransitioningInWindow: TRUE when a TRANSITIONING sample exists
# within the lookback window, FALSE when it is outside it.
$ctx3 = New-RestartClassifierContext
Add-RingSample -Context $ctx3 -ChannelId 'public' -Utc $baseUtc -State 'TRANSITIONING' -ProcessId 1001 -UpdatedAt $null
Assert-Equal 'scenario3a (TRANSITIONING 60s before -> within 180s window)' $true (Test-TransitioningInWindow -Context $ctx3 -ChannelId 'public' -BeforeUtc $baseUtc.AddSeconds(60) -WindowSeconds 180)
Assert-Equal 'scenario3b (TRANSITIONING 200s before -> outside 180s window)' $false (Test-TransitioningInWindow -Context $ctx3 -ChannelId 'public' -BeforeUtc $baseUtc.AddSeconds(200) -WindowSeconds 180)
Assert-Equal 'scenario3c (no ring at all for this channel)' $false (Test-TransitioningInWindow -Context $ctx3 -ChannelId 'education' -BeforeUtc $baseUtc.AddSeconds(60) -WindowSeconds 180)

# ---------------------------------------------------------------- scenario 4
# Register-ChannelSample end to end: TRANSITIONING observed, THEN a pid
# change -- classified planned_restart, then recovers (ON_AIR + gstreamer)
# and lands in RestartEvents with a real recovery_gap_seconds.
$ctx4 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx4 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx4 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx4 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(40) -State 'TRANSITIONING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario4a (pid change classified planned_restart)' 'planned_restart' $ctx4.PendingRestarts['public'].classification
Register-ChannelSample -Context $ctx4 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(60) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine 'gstreamer'
Assert-Equal 'scenario4b (restart recovered, removed from pending)' 0 $ctx4.PendingRestarts.Count
Assert-Equal 'scenario4c (restart event recorded)' 1 $ctx4.RestartEvents.Count
Assert-Equal 'scenario4d (recovery_gap_seconds = 20 from detection at +40 to recovery at +60)' 20 $ctx4.RestartEvents[0].recovery_gap_seconds
Assert-Equal 'scenario4e (classification carried through)' 'planned_restart' $ctx4.RestartEvents[0].classification

# ---------------------------------------------------------------- scenario 5
# A pid change with NO TRANSITIONING sample anywhere in the ring -- must
# classify unplanned_relaunch (a crash), even though it "recovers" fast.
$ctx5 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx5 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx5 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(15) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine 'gstreamer'
Assert-Equal 'scenario5 (pid change w/o TRANSITIONING -> unplanned_relaunch)' 'unplanned_relaunch' $ctx5.PendingRestarts['public'].classification

# ---------------------------------------------------------------- scenario 6
# A pending restart that never recovers within RestartTrackingMaxSeconds
# is flushed by Get-FlushedRestartEvents as recovered=$false.
$ctx6 = New-RestartClassifierContext -RestartTrackingMaxSeconds 300
Register-ChannelSample -Context $ctx6 -ChannelId 'public' -NowUtc $baseUtc -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx6 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1002 -UpdatedAt $null -Engine $null
$flushed6 = Get-FlushedRestartEvents -Context $ctx6
Assert-Equal 'scenario6 (never-recovered restart flushed at soak end)' 1 $flushed6.Count
Assert-Equal 'scenario6 recovered=false' 'False' $flushed6[0].recovered
Assert-Equal 'scenario6 recovery_gap_seconds is null' '' "$($flushed6[0].recovery_gap_seconds)"

# ---------------------------------------------------------------- scenario 7
# Test-InActivePlannedRestartWindow: the exemption window is
# max(60s, 2x measured cycle period) -- round-8 finding 3. A 75s-period
# cycle needs a 150s exemption, not a fixed 60s one.
$ctx7 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx7 -ChannelId 'public' -NowUtc $baseUtc -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx7 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(5) -State 'TRANSITIONING' -NewPid 1002 -UpdatedAt $null -Engine $null
# 90s after detection: exceeds a plain 60s window but not 2x75=150s.
Assert-Equal 'scenario7a (90s in, 75s-period cycle -> still exempt)' $true (Test-InActivePlannedRestartWindow -Context $ctx7 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(95) -MeasuredCyclePeriodSeconds 75)
# 200s after detection: exceeds even the 150s exemption.
Assert-Equal 'scenario7b (200s in, 75s-period cycle -> no longer exempt)' $false (Test-InActivePlannedRestartWindow -Context $ctx7 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(205) -MeasuredCyclePeriodSeconds 75)
# A fast (30s) measured period never shrinks the exemption below the 60s floor.
Assert-Equal 'scenario7c (50s in, 30s-period cycle -> exempt via the 60s floor)' $true (Test-InActivePlannedRestartWindow -Context $ctx7 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(55) -MeasuredCyclePeriodSeconds 30)

Write-Host ""
Write-Host "RestartClassifier unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
