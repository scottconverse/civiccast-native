# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-HostLiveness.ps1 -- pytest-free PowerShell unit checks for
# Get-SandboxLivenessVerdict (HostLiveness.ps1), fed synthetic
# (now, launch_utc, mtimes) tuples. No sandbox, no filesystem, no live
# station required. Exits non-zero on any mismatch.
#
# Run: pwsh -File sandbox-lab/scripts/Test-HostLiveness.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'HostLiveness.ps1')

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

# [datetime] parameters in HostLiveness.ps1 are OMITTED (never passed as
# $null -- PowerShell's own type converter rejects $null against a
# [datetime] parameter, confirmed directly) when a file does not exist yet.
# This helper builds the splat so every scenario below reads as a plain
# tuple of real values without repeating that plumbing.
function Invoke-Verdict {
    param(
        [datetime]$NowUtc, [datetime]$LaunchUtc,
        $MainThreadNewestUtc = $null, $HeartbeatNewestUtc = $null,
        [int]$BootBoundMinutes = 5, [int]$QuietMinutes = 15
    )
    $splat = @{ NowUtc = $NowUtc; LaunchUtc = $LaunchUtc; BootBoundMinutes = $BootBoundMinutes; QuietMinutes = $QuietMinutes }
    if ($MainThreadNewestUtc) { $splat['MainThreadNewestUtc'] = $MainThreadNewestUtc }
    if ($HeartbeatNewestUtc) { $splat['HeartbeatNewestUtc'] = $HeartbeatNewestUtc }
    return Get-SandboxLivenessVerdict @splat
}

$launchUtc = [datetime]::Parse('2026-09-06T05:00:00Z').ToUniversalTime()

# ---------------------------------------------------------------- scenario 1
# No files at all, only 1 minute since launch -- normal, guest still
# booting (Windows Sandbox measured 30-60s boot time before its
# LogonCommand even starts). Expect: alive.
$v1 = Invoke-Verdict -NowUtc $launchUtc.AddMinutes(1) -LaunchUtc $launchUtc
Assert-Equal 'scenario1 (no files, t+1m) -> alive' 'alive' $v1.verdict

# ---------------------------------------------------------------- scenario 2
# Still no files at t+6m -- past the 5-minute boot bound. Expect:
# guest-never-started (HARNESS_ERROR at the caller, never a stall/FAIL).
$v2 = Invoke-Verdict -NowUtc $launchUtc.AddMinutes(6) -LaunchUtc $launchUtc
Assert-Equal 'scenario2 (no files, t+6m) -> guest-never-started' 'guest-never-started' $v2.verdict

# ---------------------------------------------------------------- scenario 3
# Main-thread file exists but its mtime is 16 minutes stale (>= the 15m
# quiet bound); the shipper heartbeat is still fresh (30s old) -- the
# channel is fine, the guest script itself is stuck. Expect: stall.
$now3 = $launchUtc.AddMinutes(30)
$v3 = Invoke-Verdict -NowUtc $now3 -LaunchUtc $launchUtc `
    -MainThreadNewestUtc $now3.AddMinutes(-16) -HeartbeatNewestUtc $now3.AddSeconds(-30)
Assert-Equal 'scenario3 (main-thread stale 16m, heartbeat fresh) -> stall' 'stall' $v3.verdict

# ---------------------------------------------------------------- scenario 4
# Both main-thread mtime AND the heartbeat are stale (>= 15m) -- the
# channel itself (or the guest as a whole) is wedged. Expect: quiet-share.
$now4 = $launchUtc.AddMinutes(30)
$v4 = Invoke-Verdict -NowUtc $now4 -LaunchUtc $launchUtc `
    -MainThreadNewestUtc $now4.AddMinutes(-20) -HeartbeatNewestUtc $now4.AddMinutes(-18)
Assert-Equal 'scenario4 (main-thread + heartbeat both stale) -> quiet-share' 'quiet-share' $v4.verdict

# ---------------------------------------------------------------- scenario 5
# Main-thread file exists and its mtime is fresh (30s old) well after the
# boot bound -- ordinary steady-state progress. Expect: alive.
$now5 = $launchUtc.AddMinutes(10)
$v5 = Invoke-Verdict -NowUtc $now5 -LaunchUtc $launchUtc -MainThreadNewestUtc $now5.AddSeconds(-30)
Assert-Equal 'scenario5 (main-thread fresh, well past boot bound) -> alive' 'alive' $v5.verdict

# ---------------------------------------------------------------- scenario 6
# Main-thread file exists, stale exactly AT the quiet bound (15.0m), no
# heartbeat at all (never existed) -- must not treat "at the boundary" as
# still-alive, and a missing heartbeat is stale by definition. Expect:
# quiet-share.
$now6 = $launchUtc.AddMinutes(30)
$v6 = Invoke-Verdict -NowUtc $now6 -LaunchUtc $launchUtc -MainThreadNewestUtc $now6.AddMinutes(-15)
Assert-Equal 'scenario6 (main-thread exactly at 15m bound, no heartbeat) -> quiet-share' 'quiet-share' $v6.verdict

# ---------------------------------------------------------------- scenario 7
# Regression guard for the exact head-406fe80 bug: at t+40s (well inside
# the boot bound, no files yet), the verdict must be 'alive' with a bound
# printed as a real, positive number -- never "0 minute(s)".
$now7 = $launchUtc.AddSeconds(40)
$v7 = Invoke-Verdict -NowUtc $now7 -LaunchUtc $launchUtc
Assert-Equal 'scenario7 (t+40s, no files) -> alive (regression guard)' 'alive' $v7.verdict
$script:total++
if ($v7.reason -match 'boot bound 0m' -or $v7.reason -notmatch 'boot bound 5m') {
    $script:failures++
    Write-Host "[FAIL] scenario7 reason must cite a real, non-zero boot bound -- got: $($v7.reason)" -ForegroundColor Red
} else {
    Write-Host "[PASS] scenario7 reason cites a real boot bound" -ForegroundColor Green
}

# ---------------------------------------------------------------- scenario 8
# Round-8 finding 10: Get-SandboxLivenessVerdict must accept an EXPLICIT
# $null for -MainThreadNewestUtc/-HeartbeatNewestUtc, called DIRECTLY (not
# through Invoke-Verdict's splat helper, which conditionally omits the
# parameter instead of passing $null and so would never have caught this
# regression). A plain [datetime] parameter rejects an explicit $null
# argument outright ("Cannot convert null to type System.DateTime",
# confirmed directly) -- this call would have thrown before this fix.
try {
    $v8 = Get-SandboxLivenessVerdict -NowUtc $launchUtc.AddMinutes(1) -LaunchUtc $launchUtc -MainThreadNewestUtc $null -HeartbeatNewestUtc $null
    Assert-Equal 'scenario8 (explicit $null args, direct call) -> alive, no throw' 'alive' $v8.verdict
} catch {
    $script:total++
    $script:failures++
    Write-Host "[FAIL] scenario8 (explicit `$null args, direct call) -- threw: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "HostLiveness unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
