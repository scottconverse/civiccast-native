# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:BETA5_SOAK_LIBRARY = '1'
try { . (Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-04-SOAK-CYCLE.ps1') -IdentityPath 'library-only' } finally { Remove-Item Env:BETA5_SOAK_LIBRARY -ErrorAction SilentlyContinue }
$sha = 'a' * 40; $start = [datetime] '2026-01-01T00:00:00Z'
function New-Cycle([int] $Seconds) {
    $channels = @()
    foreach ($id in 'public', 'education', 'government') {
        $channels += [pscustomobject]@{ channel_id = $id; state = 'ON_AIR'; engine = 'gstreamer'; pid = 1234; tsduck = [pscustomobject]@{ verdict = 'pass'; packets_total = 1000; invalid_syncs = 0; transport_errors = 0; discontinuities = 0 } }
    }
    return [pscustomobject]@{ mission = 'm'; candidate_source_sha = $sha; utc = $start.AddSeconds($Seconds).ToString('o'); pid_change_count = 0; reload_aborted_count = 0; reload_stuck_count = 0; channels = $channels }
}
function Assert-Equal([string] $Name, $Expected, $Actual) { if ("$Expected" -ne "$Actual") { throw "$Name expected=$Expected actual=$Actual" } }
$good = @(); for ($second = 60; $second -le 7200; $second += 60) { $good += New-Cycle $second }
Assert-Equal 'full actual coverage passes' PASS (Get-Beta5Verdict $good $start $start.AddSeconds(7200) 7200 180 $sha m).verdict
Assert-Equal 'timer alone cannot pass' FAIL (Get-Beta5Verdict @() $start $start.AddSeconds(7200) 7200 180 $sha m).verdict
Assert-Equal 'elapsed below duration stays pending' PENDING (Get-Beta5Verdict $good $start $start.AddSeconds(7199) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels = @(); Assert-Equal 'empty channels fail' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels[0].pid = $null; Assert-Equal 'null pid fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels[0].tsduck.packets_total = $null; Assert-Equal 'null packets fail' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels[0].tsduck.transport_errors = $null; Assert-Equal 'null counter fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels[0].tsduck.PSObject.Properties.Remove('discontinuities'); Assert-Equal 'missing counter fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.channels[0].PSObject.Properties.Remove('pid'); Assert-Equal 'missing pid fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.PSObject.Properties.Remove('reload_stuck_count'); Assert-Equal 'missing cycle counter fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.pid_change_count = 1; Assert-Equal 'pid change fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.reload_aborted_count = 1; Assert-Equal 'reload abort fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
$one = New-Cycle 60; $one.candidate_source_sha = 'b' * 40; Assert-Equal 'sha mismatch fails' FAIL (Get-Beta5Verdict @($one) $start $start.AddSeconds(60) 7200 180 $sha m).verdict
Assert-Equal 'coverage gap fails' FAIL (Get-Beta5Verdict @((New-Cycle 60), (New-Cycle 300)) $start $start.AddSeconds(300) 7200 180 $sha m).verdict
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ("beta5-tsduck-schema-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
    $clean = Join-Path $fixtureRoot 'clean.json'; '{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":0}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}' | Set-Content -LiteralPath $clean
    Assert-Equal 'shipped TSDuck schema passes' pass (Read-TsVerdict $clean).verdict
    $errors = Join-Path $fixtureRoot 'errors.json'; '{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":1}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}' | Set-Content -LiteralPath $errors
    Assert-Equal 'shipped TSDuck errors fail' fail-stream-errors (Read-TsVerdict $errors).verdict
    $invented = Join-Path $fixtureRoot 'invented.json'; '{"ts":{"packets":42,"invalid_syncs":0,"transport_errors":0,"discontinuities":0}}' | Set-Content -LiteralPath $invented
    if ((Read-TsVerdict $invented).verdict -eq 'pass') { throw 'obsolete invented TSDuck schema was accepted' }
} finally { Remove-Item -LiteralPath $fixtureRoot -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host 'PASS: strict beta.5 verdict rejects timer-only, missing media, identity drift, relaunches, reload failures, and gaps.'
