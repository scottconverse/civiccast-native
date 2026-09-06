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

# ======================================================= Wait-ForVerdictWithGrace
# Round-4 review finding 4/5: this wrapper is the ONE shared helper
# Run-SandboxSoak.ps1's three pre-'running' phases (installing,
# awaiting-health, awaiting-soak-start) all now call -- extracted here
# (rather than left inline in Run-SandboxSoak.ps1, which has top-level
# side-effecting code and so cannot itself be dot-sourced by a test) so
# THIS wiring is directly unit-testable too, not just the underlying
# Wait-ForVerdictAfterBackstopMarker it wraps.

# scenario 5: verdict already present -- verdict_arrived=$true, and
# -LogSuccess IS called (the wrapper's whole point is to surface a
# human-readable "grace saved this run from a premature stall" message).
$script:s5LogCalls = @()
$r5 = Wait-ForVerdictWithGrace `
    -VerdictTxtPath 'C:\fake\VERDICT.txt' `
    -PhaseDescription 'installer bound exceeded' `
    -TestVerdictPathExists { param($p) $true } `
    -LogSuccess { param($m) $script:s5LogCalls += $m } `
    -SleepSeconds { param($s) }
Assert-Equal 'scenario5 (Wait-ForVerdictWithGrace, verdict present) -> verdict_arrived=True' 'True' "$($r5.verdict_arrived)"
Assert-Equal 'scenario5 -LogSuccess called exactly once' 1 $script:s5LogCalls.Count
Assert-Equal 'scenario5 logged message includes the -PhaseDescription' 'True' "$($script:s5LogCalls[0] -match [regex]::Escape('installer bound exceeded'))"

# scenario 6: verdict never arrives within the grace window --
# verdict_arrived=$false, and -LogSuccess is NEVER called (nothing to
# report -- the caller falls through to its own stall/quiet-share exit).
$script:s6LogCalls = @()
$r6 = Wait-ForVerdictWithGrace `
    -VerdictTxtPath 'C:\fake\VERDICT.txt' `
    -PhaseDescription 'station-healthy bound exceeded' `
    -TestVerdictPathExists { param($p) $false } `
    -LogSuccess { param($m) $script:s6LogCalls += $m } `
    -SleepSeconds { param($s) } `
    -GraceSeconds 10 -PollIntervalSeconds 5
Assert-Equal 'scenario6 (Wait-ForVerdictWithGrace, verdict never arrives) -> verdict_arrived=False' 'False' "$($r6.verdict_arrived)"
Assert-Equal 'scenario6 -LogSuccess is never called when the grace window is exhausted' 0 $script:s6LogCalls.Count
Assert-Equal 'scenario6 waited_seconds honors the custom -GraceSeconds (10)' 10 $r6.waited_seconds

# scenario 7: -VerdictTxtPath is actually threaded through to the
# -TestVerdictPathExists closure's own argument (not silently dropped) --
# the fake closure only returns $true for the EXACT path passed in.
$script:s7ReceivedPath = $null
$r7 = Wait-ForVerdictWithGrace `
    -VerdictTxtPath 'C:\fake\a-specific-run\VERDICT.txt' `
    -PhaseDescription 'x' `
    -TestVerdictPathExists { param($p) $script:s7ReceivedPath = $p; $p -eq 'C:\fake\a-specific-run\VERDICT.txt' } `
    -LogSuccess { param($m) } `
    -SleepSeconds { param($s) }
Assert-Equal 'scenario7 -VerdictTxtPath reaches the TestVerdictPathExists closure unmodified' 'C:\fake\a-specific-run\VERDICT.txt' $script:s7ReceivedPath
Assert-Equal 'scenario7 (matching path) -> verdict_arrived=True' 'True' "$($r7.verdict_arrived)"

# scenario 8 (round-5 review finding 8): NAMED regression guard for the
# parameter-name-collision infinite-recursion bug this function's own
# implementation hit while it was first being wired up (see
# Wait-ForVerdictWithGrace's own header/inline comment). The bug: a
# wrapping scriptblock that referenced `$TestVerdictPathExists` directly
# -- the SAME name as Wait-ForVerdictAfterBackstopMarker's own parameter
# -- recursed into itself under PowerShell's dynamic (not lexical)
# scriptblock variable resolution, because by the time that scriptblock
# actually RUNS (inside Wait-ForVerdictAfterBackstopMarker's own function
# body), the name `$TestVerdictPathExists` resolves to THAT function's own
# same-named parameter -- which, by then, IS the very scriptblock trying
# to run, so invoking it calls itself, forever ("call depth overflow" was
# the observed failure). This test passes a -TestVerdictPathExists
# scriptblock whose OWN BODY deliberately references a variable literally
# named `$TestVerdictPathExists` (shadowing-by-name, the exact collision
# shape that broke this the first time) and confirms the CALL STILL
# TERMINATES normally instead of recursing -- proving
# Wait-ForVerdictWithGrace's own internal rename (capturing the injected
# closure into a differently-named local variable before wrapping it) is
# what actually prevents the collision, regardless of what name a CALLER
# happens to use for its own variables.
$script:s8CallCount = 0
$r8 = Wait-ForVerdictWithGrace `
    -VerdictTxtPath 'C:\fake\collision-test\VERDICT.txt' `
    -PhaseDescription 'collision regression guard' `
    -TestVerdictPathExists {
        param($p)
        # This scriptblock's OWN body names a variable
        # $TestVerdictPathExists -- deliberately shadowing the name of
        # Wait-ForVerdictAfterBackstopMarker's own parameter, the exact
        # collision shape that caused the original infinite recursion.
        $TestVerdictPathExists = 'deliberately shadowing the collision name'
        $script:s8CallCount++
        $script:s8CallCount -ge 1
    } `
    -LogSuccess { param($m) } `
    -SleepSeconds { param($s) }
Assert-Equal 'scenario8 (parameter-name-collision regression guard) call terminates normally, does not recurse' 'True' "$($r8.verdict_arrived)"
Assert-Equal 'scenario8 the (potentially colliding) closure was invoked exactly once, not recursively' 1 $script:s8CallCount

Write-Host ""
Write-Host "BackstopMarkerGrace unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
