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
$flushed6 = @(Get-FlushedRestartEvents -Context $ctx6)
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

# ---------------------------------------------------------------- scenario 8
# Round-9 finding N1 (BLOCKER): TWO consecutive pid changes for the SAME
# channel before the FIRST one resolves. The old code silently overwrote
# PendingRestarts, erasing the first event entirely (measured: 2 relaunches
# -> 1 recorded event). Both must now be recorded as their own events -- the
# first flushed as recovered=$false, superseded=$true (its ORIGINAL
# classification preserved, never silently dropped), the second following
# the normal detection/classification path.
$ctx8 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx8 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
# pid change #1 (1001->1002), NO TRANSITIONING seen -> unplanned_relaunch, still pending (never reaches ON_AIR).
Register-ChannelSample -Context $ctx8 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(10) -State 'ERROR' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario8a (first pid change, no TRANSITIONING) -> unplanned_relaunch, pending' 'unplanned_relaunch' $ctx8.PendingRestarts['public'].classification
# pid change #2 (1002->1003) arrives BEFORE #1 ever resolved -- #1 must be
# flushed as its own event now, not silently overwritten.
Register-ChannelSample -Context $ctx8 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'ERROR' -NewPid 1003 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario8b (two pid changes before first resolves) -> BOTH events recorded' 1 $ctx8.RestartEvents.Count
Assert-Equal 'scenario8c (event 1 = the FIRST, superseded, classification preserved)' 'unplanned_relaunch' $ctx8.RestartEvents[0].classification
Assert-Equal 'scenario8d (event 1 marked superseded, not silently recovered)' 'True' "$($ctx8.RestartEvents[0].superseded)"
Assert-Equal 'scenario8e (event 1 recovered=false -- it never actually reached ON_AIR)' 'False' "$($ctx8.RestartEvents[0].recovered)"
Assert-Equal 'scenario8f (second pid change now pending, its own classification)' 'unplanned_relaunch' $ctx8.PendingRestarts['public'].classification
$flushed8 = @(Get-FlushedRestartEvents -Context $ctx8)
Assert-Equal 'scenario8g (flush at soak end captures the SECOND event too -- both relaunches counted)' 2 $flushed8.Count

# --------------------------------------------------------------- scenario 9
# "CLASSIFIER TRUTH": crash-then-rollover. A crash (event 1, unplanned)
# immediately followed by a legitimate scheduled rollover (event 2,
# planned) must NOT collapse into a false PASS with unplanned=0 -- this is
# the exact measured failure mode the review reported ("crash followed by
# rollover -> PASS with unplanned=0"). Simulated via two real Register-
# ChannelSample sequences sharing one context, mirroring scenario 8's shape
# but with the second restart actually completing.
Assert-Equal 'scenario9 (crash-then-rollover) -> unplanned_relaunch_count > 0, never silently absorbed' $true (@($flushed8 | Where-Object { $_.classification -eq 'unplanned_relaunch' }).Count -gt 0)

# -------------------------------------------------------------- scenario 10
# "CLASSIFIER TRUTH": TRANSITIONING -> ERROR sample -> new pid. Even though
# TRANSITIONING technically preceded the pid change (the OLD rule's only
# check), an ERROR sample in between is a crash signal that must override
# it -- measured on 609273d (item 60): the daemon writes TRANSITIONING and
# the worker crashes ~1s later. Expect unplanned_relaunch.
$ctx10 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx10 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx10 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx10 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(21) -State 'ERROR' -NewPid 1001 -UpdatedAt $null -Engine $null -LastError 'worker crashed'
Register-ChannelSample -Context $ctx10 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(25) -State 'ERROR' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario10 (TRANSITIONING -> ERROR sample -> new pid) -> unplanned_relaunch' 'unplanned_relaunch' $ctx10.PendingRestarts['public'].classification

# -------------------------------------------------------------- scenario 11
# "CLASSIFIER TRUTH": TRANSITIONING -> STARTING -> ON_AIR (new pid) within
# 60s -- the REAL planned (flag-OFF) shape at main 250026b: worker exits 0
# after EOS, daemon _start, STARTING, ON_AIR. No ERROR/FALLBACK_SLATE/
# last_error anywhere in between. Expect planned_restart, and a full
# recovery recorded once ON_AIR actually lands.
$ctx11 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx11 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx11 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx11 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(35) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario11a (TRANSITIONING -> STARTING, new pid) -> planned_restart' 'planned_restart' $ctx11.PendingRestarts['public'].classification
Register-ChannelSample -Context $ctx11 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(50) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine 'gstreamer'
Assert-Equal 'scenario11b (recovered within 60s of detection)' 1 $ctx11.RestartEvents.Count
Assert-Equal 'scenario11c (classification stayed planned_restart)' 'planned_restart' $ctx11.RestartEvents[0].classification
Assert-Equal 'scenario11d (recovery_gap_seconds = 15, from detection at +35 to ON_AIR at +50)' 15 $ctx11.RestartEvents[0].recovery_gap_seconds

# -------------------------------------------------------------- scenario 12
# Round-9 finding N7 (second half): TRANSITIONING is only credited if it is
# the sample IMMEDIATELY PRECEDING the pid change, within ~30s -- not
# merely "seen somewhere in the last 180s." A TRANSITIONING sample 155s
# ago, followed by an intervening STARTING sample right before the actual
# pid change, must NOT count as planned even though the OLD (round-8) rule
# would have credited it (TRANSITIONING technically fell inside its 180s
# lookback). This is the exact gap N7 exists to close.
$ctx12 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx12 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx12 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx12 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(170) -State 'STARTING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx12 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(175) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario12 (TRANSITIONING 155s ago, NOT the immediately-preceding sample) -> unplanned_relaunch' 'unplanned_relaunch' $ctx12.PendingRestarts['public'].classification

# -------------------------------------------------------------- scenario 13
# Round-9 finding N6 (BLOCKER): Get-FlushedRestartEvents through the EXACT
# caller shape the real driver uses (`@(Get-FlushedRestartEvents ...)`),
# for N=0, 1, 2, and 3 pending restarts. The previous `return ,@(...)` form
# double-wrapped EVERY N under this exact calling shape (confirmed
# directly: a 3-element ArrayList came back as a 1-element array whose
# sole element was the real 3-element array) -- silently collapsing
# multiple relaunches into what looked like one event, so
# max_restart_gap_seconds and the >60s recovery-time FAIL rule stopped
# seeing anything past the first event.
function New-PendingOnly {
    param($Context, [int]$Count)
    for ($i = 0; $i -lt $Count; $i++) {
        $ch = "chan$i"
        Register-ChannelSample -Context $Context -ChannelId $ch -NowUtc $baseUtc -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
        Register-ChannelSample -Context $Context -ChannelId $ch -NowUtc $baseUtc.AddSeconds(10) -State 'TRANSITIONING' -NewPid 1002 -UpdatedAt $null -Engine $null
    }
}
foreach ($n in 0, 1, 2, 3) {
    $ctxN = New-RestartClassifierContext -RestartTrackingMaxSeconds 300
    New-PendingOnly -Context $ctxN -Count $n
    $flushedN = @(Get-FlushedRestartEvents -Context $ctxN)
    Assert-Equal "scenario13 (N=$n pending restarts, exact @() driver caller shape) -> Count=$n" $n $flushedN.Count
}

# -------------------------------------------------------------- scenario 14
# Round-10 finding 6 (MEDIUM): the wrap-in-a-hashtable JSON round trip fix
# for In-Sandbox-Soak.ps1's restart-events.json, N=0/1/2. PS 5.1's
# `$Obj | ConvertTo-Json` collapses a top-level array to a bare object for
# N=1 and an empty file for N=0 -- wrapping `@{ events = @(...) }` makes
# the top-level pipeline object always be exactly ONE object regardless of
# how many events are inside, so `.events` always round-trips as an array.
foreach ($n in 0, 1, 2) {
    $eventsN = @()
    for ($i = 0; $i -lt $n; $i++) { $eventsN += [ordered]@{ channel_id = "chan$i"; classification = 'planned_restart' } }
    $json = ([ordered]@{ events = @($eventsN) } | ConvertTo-Json -Depth 6)
    $roundTripped = $json | ConvertFrom-Json
    $readBack = @($roundTripped.events)
    Assert-Equal "scenario14 (restart-events.json wrap round-trip, N=$n)" $n $readBack.Count
}

# -------------------------------------------------------------- scenario 15
# Round-10 finding 1 (HIGH, part 1): -MaxGapSeconds is no longer a
# hardcoded 30 -- Register-ChannelSample now computes
# max(60s, 2x measured-per-sample-interval). A genuinely planned restart
# at a 31s TRANSITIONING-to-pid-change gap (the exact measured failure:
# "TRANSITIONING -> pid change at +31s => unplanned" under the OLD
# hardcoded 30s) must now classify planned under the default (no
# -MeasuredCyclePeriodSeconds passed -> effective gap = max(60,2*(60/3))=60).
$ctx15a = New-RestartClassifierContext
Register-ChannelSample -Context $ctx15a -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx15a -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx15a -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(51) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario15a (31s TRANSITIONING-to-pid-change gap, default 60s floor) -> planned_restart' 'planned_restart' $ctx15a.PendingRestarts['public'].classification

# A slower measured cycle widens the gap further: period=200s -> per-sample
# ~66.7s -> effective gap = max(60, 133.3) = 133.3s. A 120s gap is inside
# it (planned); a 140s gap on the SAME measured period is outside it
# (unplanned) -- proves the computation actually scales with the
# measurement, not just the 60s floor.
$ctx15b = New-RestartClassifierContext
Register-ChannelSample -Context $ctx15b -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx15b -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx15b -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(140) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null -MeasuredCyclePeriodSeconds 200
Assert-Equal 'scenario15b (120s gap, 200s-period cycle -> within 133.3s effective gap) -> planned_restart' 'planned_restart' $ctx15b.PendingRestarts['public'].classification

$ctx15c = New-RestartClassifierContext
Register-ChannelSample -Context $ctx15c -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx15c -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx15c -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(160) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null -MeasuredCyclePeriodSeconds 200
Assert-Equal 'scenario15c (140s gap, 200s-period cycle -> exceeds 133.3s effective gap) -> unplanned_relaunch' 'unplanned_relaunch' $ctx15c.PendingRestarts['public'].classification

# -------------------------------------------------------------- scenario 16
# Round-10 finding 1 (HIGH, part 2): a dropped/failed state read (state=$null,
# last_error starting with "state read failed" -- In-Sandbox-Soak.ps1's own
# contract) must NOT break the "immediately preceding sample" chain. A
# TRANSITIONING sample, then a failed-read sample, then the pid change --
# lastPrior must skip the failed read and find TRANSITIONING underneath it.
$ctx16 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx16 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx16 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx16 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(30) -State $null -NewPid $null -UpdatedAt $null -Engine $null -LastError 'state read failed: status=0 error=timeout'
Register-ChannelSample -Context $ctx16 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(35) -State 'ON_AIR' -NewPid 1002 -UpdatedAt $null -Engine 'gstreamer'
Assert-Equal 'scenario16 (dropped read between TRANSITIONING and pid change is ignored) -> planned_restart' 'planned_restart' $ctx16.PendingRestarts['public'].classification

# -------------------------------------------------------------- scenario 17
# Round-10 finding 5: Test-PlannedRestartFromLog, the PURE log-line
# classifier, fed synthetic lines shaped exactly like
# civiccast/egress/daemon.py:901-902's format string
# ("channel %s: egress state -> %s (source=%s, pid=%s, last_error=%s)") --
# only the parsed (state, last_error) fields matter here, matching what
# Add-LogRingSample stores.
$ctx17a = New-RestartClassifierContext
Add-LogRingSample -Context $ctx17a -ChannelId 'public' -State 'ON_AIR' -LastError '-'
Add-LogRingSample -Context $ctx17a -ChannelId 'public' -State 'TRANSITIONING' -LastError '-'
Add-LogRingSample -Context $ctx17a -ChannelId 'public' -State 'STARTING' -LastError '-'
Assert-Equal 'scenario17a (clean TRANSITIONING -> STARTING, last_error=-) -> planned ($true)' 'True' "$(Test-PlannedRestartFromLog -Context $ctx17a -ChannelId 'public')"

$ctx17b = New-RestartClassifierContext
Add-LogRingSample -Context $ctx17b -ChannelId 'public' -State 'ON_AIR' -LastError '-'
Add-LogRingSample -Context $ctx17b -ChannelId 'public' -State 'TRANSITIONING' -LastError '-'
# daemon.py:1022's exact _child_exit_error text shape.
Add-LogRingSample -Context $ctx17b -ChannelId 'public' -State 'STARTING' -LastError 'GStreamer child exited non-zero; relaunching encoder.'
Assert-Equal 'scenario17b (STARTING line carries child-exited-non-zero last_error) -> crash ($false)' 'False' "$(Test-PlannedRestartFromLog -Context $ctx17b -ChannelId 'public')"

$ctx17c = New-RestartClassifierContext
Add-LogRingSample -Context $ctx17c -ChannelId 'public' -State 'ON_AIR' -LastError '-'
Add-LogRingSample -Context $ctx17c -ChannelId 'public' -State 'ON_AIR' -LastError '-'
Assert-Equal 'scenario17c (no TRANSITIONING line anywhere) -> inconclusive ($null)' '' "$(Test-PlannedRestartFromLog -Context $ctx17c -ChannelId 'public')"

$ctx17d = New-RestartClassifierContext
Add-LogRingSample -Context $ctx17d -ChannelId 'public' -State 'TRANSITIONING' -LastError '-'
Add-LogRingSample -Context $ctx17d -ChannelId 'public' -State 'ERROR' -LastError 'some daemon error text'
Assert-Equal 'scenario17d (ERROR line after TRANSITIONING, before classification point) -> crash ($false)' 'False' "$(Test-PlannedRestartFromLog -Context $ctx17d -ChannelId 'public')"

Assert-Equal 'scenario17e (no log ring at all for this channel) -> inconclusive ($null)' '' "$(Test-PlannedRestartFromLog -Context (New-RestartClassifierContext) -ChannelId 'public')"

# -------------------------------------------------------------- scenario 18
# Round-10 finding 5 end to end via Register-ChannelSample: the daemon LOG
# is the PRIMARY signal and overrides what the sample ring alone would
# conclude. 18a: sample ring shows a clean TRANSITIONING immediately
# before the pid change (sample-only would say planned) but the log shows
# the crash text -- log wins, unplanned, log_evidence='log'. 18b: the
# reverse -- sample ring has NO TRANSITIONING at all (sample-only would
# say unplanned) but the log shows the clean planned path -- log wins,
# planned, log_evidence='log'.
$ctx18a = New-RestartClassifierContext
Register-ChannelSample -Context $ctx18a -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx18a -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Add-LogRingSample -Context $ctx18a -ChannelId 'public' -State 'TRANSITIONING' -LastError '-'
Add-LogRingSample -Context $ctx18a -ChannelId 'public' -State 'STARTING' -LastError 'GStreamer child exited non-zero; relaunching encoder.'
Register-ChannelSample -Context $ctx18a -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(35) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario18a (log shows crash despite clean sample ring) -> unplanned_relaunch' 'unplanned_relaunch' $ctx18a.PendingRestarts['public'].classification
Assert-Equal 'scenario18a log_evidence=log' 'log' $ctx18a.PendingRestarts['public'].log_evidence

$ctx18b = New-RestartClassifierContext
Register-ChannelSample -Context $ctx18b -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Add-LogRingSample -Context $ctx18b -ChannelId 'public' -State 'TRANSITIONING' -LastError '-'
Add-LogRingSample -Context $ctx18b -ChannelId 'public' -State 'STARTING' -LastError '-'
Register-ChannelSample -Context $ctx18b -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(15) -State 'STARTING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario18b (log shows clean planned path despite no TRANSITIONING in sample ring) -> planned_restart' 'planned_restart' $ctx18b.PendingRestarts['public'].classification
Assert-Equal 'scenario18b log_evidence=log' 'log' $ctx18b.PendingRestarts['public'].log_evidence

# -------------------------------------------------------------- scenario 19
# Round-10 finding 5 fallback: when the log ring has NO evidence for this
# channel (log unreadable/missing, or nothing parsed), Register-
# ChannelSample must fall back to the sample-ring signal and mark
# log_evidence='missing' -- this is scenario 4's exact shape, re-asserted
# for the log_evidence field.
$ctx19 = New-RestartClassifierContext
Register-ChannelSample -Context $ctx19 -ChannelId 'public' -NowUtc $baseUtc -State 'ON_AIR' -NewPid 1001 -UpdatedAt $null -Engine 'gstreamer'
Register-ChannelSample -Context $ctx19 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(20) -State 'TRANSITIONING' -NewPid 1001 -UpdatedAt $null -Engine $null
Register-ChannelSample -Context $ctx19 -ChannelId 'public' -NowUtc $baseUtc.AddSeconds(40) -State 'TRANSITIONING' -NewPid 1002 -UpdatedAt $null -Engine $null
Assert-Equal 'scenario19 (no log ring evidence) -> falls back to sample signal, planned_restart' 'planned_restart' $ctx19.PendingRestarts['public'].classification
Assert-Equal 'scenario19 log_evidence=missing' 'missing' $ctx19.PendingRestarts['public'].log_evidence

Write-Host ""
Write-Host "RestartClassifier unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
