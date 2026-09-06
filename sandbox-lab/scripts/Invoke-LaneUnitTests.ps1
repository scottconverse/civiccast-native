# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Invoke-LaneUnitTests.ps1 -- runs all four sandbox-soak-lane unit test
# suites (Test-RestartClassifier.ps1, Test-SoakVerdict.ps1,
# Test-HostLiveness.ps1, Test-ServiceStartFailure.ps1) under powershell.exe
# (Windows PowerShell 5.1 -- the actual guest engine every one of these
# files is written to run under, and the one this project's own coordinator
# has repeatedly required re-verification against across many rounds,
# since PS 5.1/PS 7 behavioral differences have been a recurring root
# cause here), and exits non-zero if ANY suite reports a failure.
#
# Followup finding 5 (round 14 addendum): every prior round manually ran
# these four files one at a time and eyeballed the tail of each transcript
# for a failure count -- this script makes that a single, scriptable,
# CI-runnable step (wired into .github/workflows/sandbox-lane-unit-tests.yml
# as the `sandbox-lane-unit` job on windows-latest, where powershell.exe
# 5.1 is present alongside pwsh) instead of a manually-repeated ritual.
#
# Run: powershell.exe -NoProfile -File sandbox-lab/scripts/Invoke-LaneUnitTests.ps1
#  (or pwsh, for a quick local sanity check -- CI always uses powershell.exe)

param(
    [string]$ScriptsDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

$suites = @(
    'Test-RestartClassifier.ps1'
    'Test-SoakVerdict.ps1'
    'Test-HostLiveness.ps1'
    'Test-ServiceStartFailure.ps1'
)

$overallFailures = 0
$results = @()

foreach ($suite in $suites) {
    $path = Join-Path $ScriptsDir $suite
    Write-Host ""
    Write-Host "=== $suite ===" -ForegroundColor Cyan
    if (-not (Test-Path $path)) {
        Write-Host "[MISSING] $path does not exist" -ForegroundColor Red
        $overallFailures++
        $results += [pscustomobject]@{ Suite = $suite; ExitCode = -1; Status = 'MISSING' }
        continue
    }
    # Each suite is its OWN top-level script (not a function) that calls
    # `exit 0`/`exit 1` at its end -- run it as a CHILD process (never dot-
    # sourced here) so that `exit` terminates only the child, and this
    # driver can read its real exit code back via $LASTEXITCODE, exactly
    # the way CI will invoke `powershell.exe -File <suite>` for each one.
    & powershell.exe -NoProfile -File $path
    $code = $LASTEXITCODE
    $status = $(if ($code -eq 0) { 'PASS' } else { 'FAIL' })
    if ($code -ne 0) { $overallFailures++ }
    $results += [pscustomobject]@{ Suite = $suite; ExitCode = $code; Status = $status }
}

Write-Host ""
Write-Host "=== Invoke-LaneUnitTests summary ===" -ForegroundColor Cyan
foreach ($r in $results) {
    $color = $(if ($r.Status -eq 'PASS') { 'Green' } else { 'Red' })
    Write-Host "  $($r.Status.PadRight(8)) $($r.Suite) (exit $($r.ExitCode))" -ForegroundColor $color
}

if ($overallFailures -gt 0) {
    Write-Host ""
    Write-Host "$overallFailures of $($suites.Count) suite(s) FAILED." -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "All $($suites.Count) suites passed." -ForegroundColor Green
exit 0
