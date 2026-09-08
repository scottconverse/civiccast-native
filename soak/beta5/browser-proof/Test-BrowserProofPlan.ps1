# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-True([string] $Label, [bool] $Condition) {
    if (-not $Condition) { throw "Assertion failed: $Label" }
}

$parseErrors = $null
$null = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'Invoke-Beta5ResidentBrowserProof.ps1'),
    [ref] $null,
    [ref] $parseErrors
)
Assert-True 'PowerShell entrypoint parses' (@($parseErrors).Count -eq 0)

$root = Join-Path ([IO.Path]::GetTempPath()) ("civiccast-browser-proof-test-" + [guid]::NewGuid().ToString('N'))
try {
    $tools = Join-Path $root 'tools'
    $playwright = Join-Path $root 'node_modules\playwright-core'
    $evidence = Join-Path $root 'evidence'
    New-Item -ItemType Directory -Path $tools, $playwright | Out-Null
    Set-Content -LiteralPath (Join-Path $tools 'node.exe') -Value 'not executed' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $tools 'msedge.exe') -Value 'not executed' -Encoding ascii
    Set-Content -LiteralPath (Join-Path $playwright 'package.json') -Value '{"name":"playwright-core","version":"1.2.3-test"}' -Encoding ascii
    $text = @(& (Join-Path $PSScriptRoot 'Invoke-Beta5ResidentBrowserProof.ps1') `
        -NodePath (Join-Path $tools 'node.exe') `
        -PlaywrightCorePath $playwright `
        -BrowserExecutablePath (Join-Path $tools 'msedge.exe') `
        -AssetId 'approved-asset-1' `
        -CandidateSourceSha ('a' * 40) `
        -EvidenceRoot $evidence) -join "`n"
    $plan = $text | ConvertFrom-Json
    Assert-True 'plan does not execute live browser' ($plan.live_execution -ceq 'NOT_RUN')
    Assert-True 'plan exact asset' ($plan.asset_id -ceq 'approved-asset-1')
    Assert-True 'plan exact loopback watch route' ($plan.watch_url -ceq 'http://127.0.0.1:8000/#/watch/approved-asset-1')
    Assert-True 'plan declares no API writes' ($plan.station_api_writes -eq $false)
    Assert-True 'plan declares isolated profile' ($plan.isolated_temporary_profile -eq $true)
    Assert-True 'plan creates no evidence directory' (-not (Test-Path -LiteralPath $evidence))

    $failed = $false
    try {
        & (Join-Path $PSScriptRoot 'Invoke-Beta5ResidentBrowserProof.ps1') `
            -NodePath (Join-Path $tools 'node.exe') `
            -PlaywrightCorePath $playwright `
            -BrowserExecutablePath (Join-Path $tools 'msedge.exe') `
            -AssetId '../wrong' `
            -CandidateSourceSha ('a' * 40) `
            -EvidenceRoot $evidence | Out-Null
    } catch { $failed = $true }
    Assert-True 'path-like asset rejected' $failed
} finally {
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host 'PASS: inert validation plan requires explicit tools/browser/asset/source and performs no execution or evidence write.'
