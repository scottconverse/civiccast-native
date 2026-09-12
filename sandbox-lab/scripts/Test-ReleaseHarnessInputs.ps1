# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
$ErrorActionPreference = 'Stop'
$reportText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'In-Sandbox-Report.ps1') -Raw
$parseErrors = $null
$parseTokens = $null
$reportAst = [System.Management.Automation.Language.Parser]::ParseInput($reportText, [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Report script does not parse.' }
$apiFunction = $reportAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-CivicCastApi'}, $true)
Invoke-Expression $apiFunction.Extent.Text
function Invoke-WebRequest {
    param($Uri, $Method, $Headers, [switch]$UseBasicParsing, $TimeoutSec, $ErrorAction)
    if ($Headers.Authorization -ne "Bearer $token") { throw 'Schema discovery request omitted its staff authorization.' }
    return @{StatusCode=200; Content='{"paths":{"/api/staff/egress/channels/{channel_id}/config":{},"/api/staff/egress/channels/{channel_id}/commands":{}}}'}
}
$BASE = 'http://127.0.0.1:8000'
$token = [guid]::NewGuid().ToString('N')
$engineToken = $token
$t3loop = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
$t4notes = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
$failures = @()
try {
    $discoveryCalls = @($reportText -split '\r?\n' | Where-Object { $_ -match '^\s*\$(spec|specR) = Invoke-CivicCastApi.*openapi.json' })
    if ($discoveryCalls.Count -ne 2) { throw 'Expected both schema-discovery call sites.' }
    foreach ($discoveryCall in $discoveryCalls) {
        Invoke-Expression $discoveryCall
        $response = if ($discoveryCall -match '\$specR =') { $specR } else { $spec }
        if ($response.status -ne 200 -or -not $response.body_json.paths) { $failures += 'Schema discovery did not authenticate and return paths.' }
    }
    foreach ($requestLog in @($t3loop, $t4notes)) {
        if ((Get-Content -LiteralPath $requestLog -Raw).Contains($token)) { throw 'Request log leaked authorization.' }
    }
} finally {
    foreach ($requestLog in @($t3loop, $t4notes)) { if (Test-Path -LiteralPath $requestLog) { Remove-Item -LiteralPath $requestLog } }
}
. (Join-Path $PSScriptRoot 'DaemonLogPatterns.ps1')
$soakText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'In-Sandbox-Soak.ps1') -Raw
$soakAst = [System.Management.Automation.Language.Parser]::ParseInput($soakText, [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Soak script does not parse.' }
$assignment = $soakAst.Find({param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$reloadArmedNeverCommittedChannels'}, $true)
$channelSpecs = @(@{id='public'}, @{id='education'}, @{id='government'})
function Update-WorkerStdoutCounters { param($ChannelId) }
foreach ($missingChannels in @(@(), @('public'), @('public','government'))) {
    $script:reloadArmedChannels = @{public=$true;education=$true;government=$true}
    $script:workerStdoutCountsByChannel = @{}
    foreach ($channel in $channelSpecs) { $script:workerStdoutCountsByChannel[$channel.id] = @{reload_committed_count=$(if ($channel.id -in $missingChannels) {0} else {241})} }
    Invoke-Expression $assignment.Extent.Text
    if ($reloadArmedNeverCommittedChannels -isnot [array] -or $reloadArmedNeverCommittedChannels.Count -ne $missingChannels.Count) { $failures += "Actual soak call site did not preserve $($missingChannels.Count) missing-channel entries." }
    if (($reloadArmedNeverCommittedChannels | Sort-Object) -join ',' -ne (($missingChannels | Sort-Object) -join ',')) { $failures += 'Missing-channel identities changed.' }
}
if ($failures.Count) { throw ($failures -join "`n") }
Write-Host 'Release harness inputs: PASS (both authenticated discovery calls, no token logging, zero/one/two missing channels).'
