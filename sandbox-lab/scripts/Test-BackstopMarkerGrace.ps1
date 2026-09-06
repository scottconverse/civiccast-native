# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-BackstopMarkerGrace.ps1 -- pytest-free PowerShell unit checks for
# Wait-ForVerdictAfterBackstopMarker (BackstopMarkerGrace.ps1), fed fake
# -TestVerdictPathExists/-SleepSeconds scriptblocks instead of a real
# filesystem and a real 45-second wait. No live sandbox required. Exits
# non-zero on any mismatch.
#
# Round-follow-up-C item 1: covers the three scenarios the review named --
# (1) marker+verdict present -> verdict path (zero wait), (2) marker only,
# verdict arrives within grace -> verdict path, (3) marker only, never
# arrives -> quiet-share only after the full grace window, never earlier.
#
# Run: pwsh -File sandbox-lab/scripts/Test-BackstopMarkerGrace.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'BackstopMarkerGrace.ps1')

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

# ---------------------------------------------------------------- scenario 1
# Marker AND verdict already present at the very first check -- must return
# verdict_arrived=$true having slept ZERO times (no grace time spent at all
# when the verdict was never actually missing).
$script:s1SleepCalls = 0
$r1 = Wait-ForVerdictAfterBackstopMarker `
    -TestVerdictPathExists { $true } `
    -SleepSeconds { param($s) $script:s1SleepCalls++ }
Assert-Equal 'scenario1 (marker+verdict present) -> verdict_arrived=True' 'True' "$($r1.verdict_arrived)"
Assert-Equal 'scenario1 waited_seconds=0 (no grace time spent)' 0 $r1.waited_seconds
Assert-Equal 'scenario1 polls=1 (single check, no retries)' 1 $r1.polls
Assert-Equal 'scenario1 slept zero times' 0 $script:s1SleepCalls

# ---------------------------------------------------------------- scenario 2
# Marker only at first; VERDICT.txt arrives partway through the grace
# window (on the 3rd check, i.e. after 2 sleeps = 10s with the default 5s
# poll interval) -- must return verdict_arrived=$true, not fall through to
# a quiet-share exit, and must not have consumed the full grace window.
$script:s2CheckCount = 0
$r2 = Wait-ForVerdictAfterBackstopMarker `
    -TestVerdictPathExists { $script:s2CheckCount++; $script:s2CheckCount -ge 3 } `
    -SleepSeconds { param($s) }
Assert-Equal 'scenario2 (verdict arrives within grace, 3rd check) -> verdict_arrived=True' 'True' "$($r2.verdict_arrived)"
Assert-Equal 'scenario2 polls=3 (arrived on the 3rd check)' 3 $r2.polls
Assert-Equal 'scenario2 waited_seconds=10 (2 poll intervals elapsed before arrival)' 10 $r2.waited_seconds

# ---------------------------------------------------------------- scenario 3
# Marker only, VERDICT.txt NEVER arrives -- must fall back to quiet-share
# only once the full default 45s grace window (poll every 5s) is
# exhausted, never earlier. Track every waited_seconds value the
# TestVerdictPathExists scriptblock was called at, to prove the function
# did not give up before the full window and did not overrun it either.
$script:s3ObservedWaits = @()
$script:s3StartWait = 0
$r3 = Wait-ForVerdictAfterBackstopMarker `
    -TestVerdictPathExists { $script:s3ObservedWaits += $script:s3StartWait; $false } `
    -SleepSeconds { param($s) $script:s3StartWait += $s }
Assert-Equal 'scenario3 (verdict never arrives) -> verdict_arrived=False' 'False' "$($r3.verdict_arrived)"
Assert-Equal 'scenario3 waited_seconds=45 (full default grace window exhausted, no more, no less)' 45 $r3.waited_seconds
Assert-Equal 'scenario3 last check happened AT the 45s boundary, not before' 'True' "$($script:s3ObservedWaits[-1] -eq 45)"
Assert-Equal 'scenario3 no check happened past the 45s boundary' 'True' "$((@($script:s3ObservedWaits | Where-Object { $_ -gt 45 })).Count -eq 0)"

# --------------------------------------------------------------- scenario 4
# Custom -GraceSeconds/-PollIntervalSeconds are honored (regression guard
# against a hardcoded 45/5 inside the loop).
$script:s4Wait = 0
$r4 = Wait-ForVerdictAfterBackstopMarker `
    -TestVerdictPathExists { $false } `
    -SleepSeconds { param($s) $script:s4Wait += $s } `
    -GraceSeconds 20 -PollIntervalSeconds 10
Assert-Equal 'scenario4 (custom grace/poll) -> waited_seconds=20' 20 $r4.waited_seconds
Assert-Equal 'scenario4 (custom grace/poll) -> verdict_arrived=False' 'False' "$($r4.verdict_arrived)"

Write-Host ""
Write-Host "BackstopMarkerGrace unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
