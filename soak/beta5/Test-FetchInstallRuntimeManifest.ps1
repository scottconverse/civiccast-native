# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# Regression proof for the pre-install runtime-manifest extraction only. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $AppPack,
    [string] $ScriptPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ScriptPath) {
    $ScriptPath = Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1'
}

function Assert-True {
    param([Parameter(Mandatory)][bool] $Condition, [Parameter(Mandatory)][string] $Message)
    if (-not $Condition) { throw $Message }
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref] $tokens, [ref] $parseErrors)
Assert-True ($parseErrors.Count -eq 0) 'Fetch/install script must parse without PowerShell errors.'
$assignments = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true))
Assert-True (@($assignments | Where-Object { $_.Left.Extent.Text -eq '$runtimeEntries' }).Count -eq 1) 'Runtime extraction must use the non-automatic $runtimeEntries variable exactly once.'
Assert-True (@($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.VariableExpressionAst] -and $node.VariablePath.UserPath -eq 'matches' }, $true)).Count -eq 0) 'Do not assign/read $matches: PowerShell treats it as automatic $Matches.'

Assert-True (Test-Path -LiteralPath $AppPack -PathType Leaf) "App pack was not found: $AppPack"
$manifestOutput = @(& tar.exe -xOf $AppPack manifest.json 2>$null)
Assert-True ($LASTEXITCODE -eq 0 -and $manifestOutput.Count -gt 0) 'Could not read the actual app-pack manifest.'
$packManifest = ($manifestOutput -join "`n") | ConvertFrom-Json
$runtimeTargets = @(
    'Lib/site-packages/civiccast/egress/daemon.py',
    'Lib/site-packages/civiccast/egress/gst/strategy.py'
)
$expectedRuntimeHashes = [ordered]@{}
$loops = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.ForEachStatementAst] -and
    $node.Body.Extent.Text.Contains('$expectedRuntimeHashes[$relative] =')
}, $true))
Assert-True ($loops.Count -eq 1) 'Expected exactly one production runtime-hash extraction loop.'
# Execute the actual parsed source loop, not a separately retyped approximation.
. ([scriptblock]::Create($loops[0].Extent.Text))

Assert-True ($expectedRuntimeHashes.Count -eq 2) 'Expected exactly the two runtime hash bindings.'
foreach ($hash in $expectedRuntimeHashes.Values) {
    Assert-True ($hash -match '^[0-9a-f]{64}$') 'Runtime binding must be a lowercase SHA-256 value.'
}
Assert-True ($packManifest.metadata.source_sha -ceq 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a') 'Actual pack must name the signed candidate.'
Assert-True ($expectedRuntimeHashes[$runtimeTargets[0]] -ceq 'a8e967de4a64115a60a1288447ce119f4f2b18f9451e0fff56e958b915036419') 'Daemon hash differs from independently verified candidate.'
Assert-True ($expectedRuntimeHashes[$runtimeTargets[1]] -ceq '74bb7a8f7a67037bce7a7066e0af01b85b8c36430d0f034a5c564ab3989ede3e') 'Strategy hash differs from independently verified candidate.'
Write-Host "PASS: extracted two runtime hashes from $AppPack"
