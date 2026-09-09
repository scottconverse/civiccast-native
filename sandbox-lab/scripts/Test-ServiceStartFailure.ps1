# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-ServiceStartFailure.ps1 -- pytest-free PowerShell unit checks for
# ServiceStartFailureCheck.ps1's Test-ServiceStartFailureIsProductCrash,
# fed synthetic Get-Service/Get-WinEvent results (both mocked as plain
# functions defined in THIS script's own top-level scope -- since neither
# file is a module, PowerShell's normal command-precedence rules resolve
# an unqualified `Get-Service`/`Get-WinEvent` call inside the dot-sourced
# function to these local overrides rather than the real cmdlets). No
# live System event log required.
#
# Round-14 finding 8 (LOW).
#
# Run: pwsh -File sandbox-lab/scripts/Test-ServiceStartFailure.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ServiceStartFailureCheck.ps1')

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

# Real display name used throughout -- round-14 finding 1's whole point is
# that this is NOT the same as the short service name 'CivicCastSupervisor'.
$script:MockDisplayName = 'CivicCast Native Supervisor'
# Set per-scenario before calling the function under test.
$script:MockEvents = @()

function New-SyntheticScmEvent {
    <#
      .SYNOPSIS
      Builds a synthetic Get-WinEvent-shaped record. -PropertyIndex places
      the display-name value at that position in .Properties (round-14
      finding 3: 7009's own layout carries it at index 1, not 0) --
      defaults to 0 for the 7034/7031/7024/7000 shape.
    #>
    param([int]$Id, [datetime]$TimeCreated, [string]$DisplayNameValue, [int]$PropertyIndex = 0, [string]$Message = 'synthetic SCM event')
    $props = @()
    for ($i = 0; $i -le $PropertyIndex; $i++) {
        $props += [pscustomobject]@{ Value = $(if ($i -eq $PropertyIndex) { $DisplayNameValue } else { 'other-property-value' }) }
    }
    return [pscustomobject]@{ Id = $Id; TimeCreated = $TimeCreated; Message = $Message; Properties = $props }
}

# Mock cmdlets -- defined once, read $script:MockEvents/$script:MockDisplayName
# fresh on every call so each scenario just reassigns those two variables.
function Get-Service {
    param([string]$Name, [string]$ErrorAction)
    if (-not $script:MockDisplayName) { throw "synthetic Get-Service failure (no mock display name set)" }
    return [pscustomobject]@{ DisplayName = $script:MockDisplayName }
}
function Get-WinEvent {
    param($FilterHashtable, [string]$ErrorAction)
    return @($script:MockEvents)
}

$now = [datetime]::Parse('2026-09-06T12:00:00Z').ToUniversalTime()
$sinceUtc = $now.AddMinutes(-1)

# ---------------------------------------------------------------- scenario 1
# A single 7034 (terminated unexpectedly) naming the REAL display name ->
# IsProductCrash=True (FAIL).
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7034 -TimeCreated $now -DisplayNameValue $script:MockDisplayName)
)
$r1 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario1 (7034 only) -> IsProductCrash=True' 'True' "$($r1.IsProductCrash)"

# ---------------------------------------------------------------- scenario 2
# Round-14 finding 2 (HIGH): Get-WinEvent returns NEWEST FIRST -- a 7000
# (SCM-side, no-start) logged AFTER an EARLIER real 7034 crash must not
# mask it. $script:MockEvents is built newest-first (matching the real
# cmdlet's own ordering) to prove the function scans the WHOLE set, not
# just element [0].
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7000 -TimeCreated $now -DisplayNameValue $script:MockDisplayName)
    (New-SyntheticScmEvent -Id 7034 -TimeCreated $now.AddSeconds(-10) -DisplayNameValue $script:MockDisplayName)
)
$r2 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario2 (7000 newest, 7034 older in the same set) -> IsProductCrash=True (the crash is not masked)' 'True' "$($r2.IsProductCrash)"

# ---------------------------------------------------------------- scenario 3
# 7000 alone (the SCM itself could not get the process running) ->
# IsProductCrash=False (HARNESS_ERROR) -- round-14 finding 4: no message-
# text promotion branch exists any more; this is unconditional.
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7000 -TimeCreated $now -DisplayNameValue $script:MockDisplayName -Message 'The CivicCast Native Supervisor service failed to start due to the following error: some SCM-side error text that would previously have been pattern-matched')
)
$r3 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario3 (7000 only) -> IsProductCrash=False (HARNESS_ERROR)' 'False' "$($r3.IsProductCrash)"

# ---------------------------------------------------------------- scenario 4
# Round-14 finding 1 (BLOCKER) regression guard: an event naming the WRONG
# value (e.g. the short service name 'CivicCastSupervisor', which is what
# the pre-round-14 code incorrectly matched against) must NOT match --
# proving the fix actually requires the real DISPLAY name. No event
# matches, no exception text -> falls through to the final HARNESS_ERROR
# default (IsProductCrash=False) via the "no evidence" path, not via a
# false positive event match.
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7034 -TimeCreated $now -DisplayNameValue 'CivicCastSupervisor')
)
$r4 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario4 (event names the SHORT service name, not the display name) -> no match, IsProductCrash=False' 'False' "$($r4.IsProductCrash)"
Assert-Equal 'scenario4 reason confirms no event matched (not a crash-event reason)' 'True' "$($r4.Reason -match 'no SCM crash/no-start event')"

# ---------------------------------------------------------------- scenario 5
# Round-14 finding 3 (HIGH): 7009's display-name property sits at index 1
# (Properties[0] is the timeout in ms), not index 0 -- must still match.
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7009 -TimeCreated $now -DisplayNameValue $script:MockDisplayName -PropertyIndex 1)
)
$r5 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario5 (7009, display name at Properties[1]) -> matched, IsProductCrash=False (HARNESS_ERROR)' 'False' "$($r5.IsProductCrash)"
Assert-Equal 'scenario5 reason confirms the 7009 event WAS matched (not the no-evidence default)' 'True' "$($r5.Reason -match '7009')"

# ---------------------------------------------------------------- scenario 6
# No events at all, but the exception text matches a known SCM-refusal
# phrase -> still IsProductCrash=False, via the exception-text branch
# (unchanged from round-11/12).
$script:MockEvents = @()
$r6 = Test-ServiceStartFailureIsProductCrash -ExceptionText 'Cannot start service CivicCastSupervisor: Access is denied.' -SinceUtc $sinceUtc
Assert-Equal 'scenario6 (no events, exception text is an SCM refusal) -> IsProductCrash=False' 'False' "$($r6.IsProductCrash)"
Assert-Equal 'scenario6 reason cites the exception text' 'True' "$($r6.Reason -match 'Access is denied')"

# ---------------------------------------------------------------- scenario 7
# Followup finding 3 (round 14 addendum): Get-Service ITSELF throws (e.g.
# the service failed to register at all -- exactly the scenario this
# function exists for), but a real 7034 crash event is still present in
# the System event log, naming the WELL-KNOWN constant display name
# ('CivicCast Native Supervisor') the function falls back to when
# Get-Service fails. Must still catch it -- IsProductCrash=True -- rather
# than silently skipping the event-log check entirely and defaulting to
# HARNESS_ERROR just because Get-Service happened to fail.
$script:MockDisplayName = $null   # forces the mock Get-Service to throw
$script:MockEvents = @(
    (New-SyntheticScmEvent -Id 7034 -TimeCreated $now -DisplayNameValue 'CivicCast Native Supervisor')
)
$r7 = Test-ServiceStartFailureIsProductCrash -ExceptionText '' -SinceUtc $sinceUtc
Assert-Equal 'scenario7 (Get-Service throws, but a real 7034 exists under the well-known constant name) -> IsProductCrash=True' 'True' "$($r7.IsProductCrash)"
$script:MockDisplayName = 'CivicCast Native Supervisor'   # restore for tidiness

# ---------------------------------------------------------------- scenario 8
# Round-follow-up-C finding: ServiceStartFailureCheck.ps1's fallback
# well-known display name (used only when Get-Service itself throws, see
# scenario 7 above) is a hand-duplicated copy of
# civiccast/native/supervisor/config.py's own DISPLAY_NAME constant -- no
# import path exists from PowerShell into that Python module. A comment
# alone cannot stop the two copies drifting apart, so this scenario reads
# config.py's own source line via regex and asserts it is byte-identical
# to $script:ServiceStartFailureWellKnownDisplayName: a rename in either
# file without the other now fails this suite instead of silently
# reintroducing round-14 finding 1's exact bug class (the function looking
# for a display name the installer no longer uses).
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$configPyPath = Join-Path $repoRoot 'civiccast\native\supervisor\config.py'
if (-not (Test-Path $configPyPath)) {
    $script:total++
    $script:failures++
    Write-Host "[FAIL] scenario8 (config.py DISPLAY_NAME drift guard) -- config.py not found at $configPyPath" -ForegroundColor Red
} else {
    $configPyText = Get-Content -Path $configPyPath -Raw
    $displayNameMatch = [regex]::Match($configPyText, 'DISPLAY_NAME\s*=\s*"([^"]*)"')
    if (-not $displayNameMatch.Success) {
        $script:total++
        $script:failures++
        Write-Host "[FAIL] scenario8 (config.py DISPLAY_NAME drift guard) -- DISPLAY_NAME constant not found in $configPyPath" -ForegroundColor Red
    } else {
        Assert-Equal 'scenario8 (config.py DISPLAY_NAME matches the PowerShell fallback constant)' $displayNameMatch.Groups[1].Value $script:ServiceStartFailureWellKnownDisplayName
    }
}

Write-Host ""
Write-Host "ServiceStartFailure unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
