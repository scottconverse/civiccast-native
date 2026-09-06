# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-CaptionsOffCheck.ps1 -- pytest-free PowerShell unit checks for
# Get-CaptionsOffVerification (CaptionsOffCheck.ps1), fed synthetic
# put_ok/get_ok/read_back_value tuples. No sandbox, no filesystem, no live
# station required. Exits non-zero on any mismatch.
#
# Run: pwsh -File sandbox-lab/scripts/Test-CaptionsOffCheck.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'CaptionsOffCheck.ps1')

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
# PUT 200, GET 200 with live_captions_enabled=$false -- the clean case.
# Expect: verified=$true, captions_enabled=$false, should_harness_error=$false.
$v1 = Get-CaptionsOffVerification -PutOk $true -GetOk $true -ReadBackValue $false
Assert-Equal 'scenario1 (PUT ok, GET false) -> verified' $true $v1.verified
Assert-Equal 'scenario1 captions_enabled' $false $v1.captions_enabled
Assert-Equal 'scenario1 should_harness_error' $false $v1.should_harness_error

# ---------------------------------------------------------------- scenario 2
# PUT failed outright (non-200). Expect: verified=$false, should_harness_error=$true,
# captions_enabled conservatively $true (never report "off" without confirmation).
$v2 = Get-CaptionsOffVerification -PutOk $false -GetOk $true -ReadBackValue $false
Assert-Equal 'scenario2 (PUT failed) -> verified' $false $v2.verified
Assert-Equal 'scenario2 should_harness_error' $true $v2.should_harness_error
Assert-Equal 'scenario2 captions_enabled (PUT failed, GET happened to read false anyway)' $false $v2.captions_enabled

# ---------------------------------------------------------------- scenario 3
# PUT ok, but the read-back is $true (the PUT silently did not take effect).
# Expect: verified=$false, should_harness_error=$true, captions_enabled=$true.
$v3 = Get-CaptionsOffVerification -PutOk $true -GetOk $true -ReadBackValue $true
Assert-Equal 'scenario3 (PUT ok, read-back true) -> verified' $false $v3.verified
Assert-Equal 'scenario3 should_harness_error' $true $v3.should_harness_error
Assert-Equal 'scenario3 captions_enabled' $true $v3.captions_enabled

# ---------------------------------------------------------------- scenario 4
# PUT ok, GET failed outright (no read-back at all). Expect: verified=$false,
# should_harness_error=$true, captions_enabled conservatively $true.
$v4 = Get-CaptionsOffVerification -PutOk $true -GetOk $false -ReadBackValue $null
Assert-Equal 'scenario4 (PUT ok, GET failed) -> verified' $false $v4.verified
Assert-Equal 'scenario4 should_harness_error' $true $v4.should_harness_error
Assert-Equal 'scenario4 captions_enabled' $true $v4.captions_enabled

# ---------------------------------------------------------------- scenario 5
# PUT ok, GET ok, but the field is missing/non-boolean (e.g. $null from a
# response shape this lane didn't expect) -- must not be silently coerced
# to a bool. Expect: verified=$false (a $null is NOT the literal $false),
# should_harness_error=$true, captions_enabled conservatively $true.
$v5 = Get-CaptionsOffVerification -PutOk $true -GetOk $true -ReadBackValue $null
Assert-Equal 'scenario5 (read-back non-boolean/$null) -> verified' $false $v5.verified
Assert-Equal 'scenario5 should_harness_error' $true $v5.should_harness_error
Assert-Equal 'scenario5 captions_enabled' $true $v5.captions_enabled

# ---------------------------------------------------------------- scenario 6
# Both PUT and GET failed -- the worst case. Expect: verified=$false,
# should_harness_error=$true.
$v6 = Get-CaptionsOffVerification -PutOk $false -GetOk $false -ReadBackValue $null
Assert-Equal 'scenario6 (both failed) -> verified' $false $v6.verified
Assert-Equal 'scenario6 should_harness_error' $true $v6.should_harness_error

# ---------------------------------------------------------------- scenario 7
# Round-2 finding 4 (MEDIUM): Get-MeasuredCaptionsEnabled -- the GET-only
# read used on every run (not just -CaptionsOff runs) to measure
# captions_enabled instead of the previous hardcoded $true. Clean case:
# GET ok, real bool read-back -> that value, verbatim.
Assert-Equal 'scenario7a (GET ok, read-back $true) -> $true' $true (Get-MeasuredCaptionsEnabled -GetOk $true -ReadBackValue $true)
Assert-Equal 'scenario7b (GET ok, read-back $false) -> $false' $false (Get-MeasuredCaptionsEnabled -GetOk $true -ReadBackValue $false)

# ---------------------------------------------------------------- scenario 8
# Round-2 finding 4: GET failed outright -- conservatively $true (an
# unconfirmed read is never reported as captions being off), never $null
# and never a throw.
Assert-Equal 'scenario8 (GET failed) -> $true (conservative)' $true (Get-MeasuredCaptionsEnabled -GetOk $false -ReadBackValue $null)

# ---------------------------------------------------------------- scenario 9
# Round-2 finding 4: GET ok but the field is missing/non-boolean -- must
# not be silently coerced; conservatively $true.
Assert-Equal 'scenario9 (GET ok, non-boolean/$null read-back) -> $true (conservative)' $true (Get-MeasuredCaptionsEnabled -GetOk $true -ReadBackValue $null)

# --------------------------------------------------------------- scenario 10
# Round-2 finding 4: Get-CaptionsOffVerification's own captions_enabled
# field now calls Get-MeasuredCaptionsEnabled internally -- prove the two
# functions still agree after the refactor (no behavior drift), reusing
# scenario 3's inputs (PUT ok, read-back $true -- the PUT silently did not
# take effect).
$v10 = Get-CaptionsOffVerification -PutOk $true -GetOk $true -ReadBackValue $true
Assert-Equal 'scenario10 (Get-CaptionsOffVerification.captions_enabled matches Get-MeasuredCaptionsEnabled)' (Get-MeasuredCaptionsEnabled -GetOk $true -ReadBackValue $true) $v10.captions_enabled

Write-Host ""
Write-Host "CaptionsOffCheck unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
