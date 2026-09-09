# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Hermetic contract test for the host -> .wsb -> guest phase-bound hand-off.
# It invokes the real host runner in -DryRun mode against a disposable,
# hash-valid minimal kit; it never launches Windows Sandbox or an installer.

param(
    # Test-only input: lets a reviewer run this exact contract against a
    # checked-out historical sandbox-lab directory to demonstrate the old
    # missing-forwarding failure. Production callers do not use this test.
    [string]$SandboxRoot = ''
)

$ErrorActionPreference = 'Stop'

function Assert-That {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "ASSERTION FAILED: $Message" }
}

function Assert-OwnedTemporaryTree {
    param([string]$BasePath, [string]$TargetPath)

    $separator = [char]92
    $baseFull = [System.IO.Path]::GetFullPath($BasePath).TrimEnd($separator)
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath).TrimEnd($separator)
    $basePrefix = $baseFull + $separator
    Assert-That ($targetFull.StartsWith($basePrefix, [System.StringComparison]::OrdinalIgnoreCase)) `
        "cleanup target is outside the owned temporary base: $targetFull"

    $baseItem = Get-Item -LiteralPath $baseFull -Force
    Assert-That (-not [bool]($baseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) `
        'owned temporary base must not be a reparse point'

    if (-not (Test-Path -LiteralPath $targetFull)) { return }
    $targetItem = Get-Item -LiteralPath $targetFull -Force
    Assert-That (-not [bool]($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) `
        'cleanup target must not be a reparse point'
    $reparseChildren = @(Get-ChildItem -LiteralPath $targetFull -Force -Recurse -ErrorAction Stop | Where-Object {
            [bool]($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
        })
    Assert-That ($reparseChildren.Count -eq 0) 'owned temporary tree must contain no reparse points before cleanup'
}

function Invoke-GuestParameterContract {
    param(
        [System.Management.Automation.Language.ScriptBlockAst]$GuestAst,
        [hashtable]$Parameters = @{}
    )

    $parameterBlock = $GuestAst.ParamBlock
    Assert-That ($null -ne $parameterBlock) 'guest script has a parameter block'
    $probeText = $parameterBlock.Extent.Text + @'

[pscustomobject]@{
    install_bound_minutes = $InstallBoundMinutes
    health_bound_minutes = $HealthBoundMinutes
}
'@
    $probe = [scriptblock]::Create($probeText)
    return & $probe @Parameters
}

function Assert-GuestRejectsBound {
    param(
        [System.Management.Automation.Language.ScriptBlockAst]$GuestAst,
        [string]$ParameterName,
        [int]$Value
    )

    $rejected = $false
    try {
        $null = Invoke-GuestParameterContract -GuestAst $GuestAst -Parameters @{ $ParameterName = $Value }
    } catch {
        $rejected = $true
    }
    Assert-That $rejected "guest rejects ${ParameterName}=$Value"
}

function Assert-HostRejectsBoundBeforeFiles {
    param(
        [string]$HostRunner,
        [string]$Sha,
        [string]$KitRoot,
        [string]$NoCreateRoot,
        [string]$ParameterName,
        [int]$Value
    )

    $rejected = $false
    try {
        $arguments = @{ $ParameterName = $Value }
        & $HostRunner -Sha $Sha -Root $NoCreateRoot -KitRoot $KitRoot -DryRun @arguments 2>&1 | Out-Null
    } catch {
        $rejected = $true
    }
    Assert-That $rejected "host rejects ${ParameterName}=$Value during parameter binding"
    Assert-That (-not (Test-Path -LiteralPath $NoCreateRoot)) `
        "host invalid ${ParameterName}=$Value created files before rejecting the parameter"
}

if (-not $SandboxRoot) { $SandboxRoot = Split-Path -Parent $PSScriptRoot }
$sandboxRoot = (Resolve-Path -LiteralPath $SandboxRoot -ErrorAction Stop).Path
$hostRunner = Join-Path $sandboxRoot 'Run-SandboxSoak.ps1'
$templatePath = Join-Path $sandboxRoot 'CivicCastSandboxSoak.wsb.template'
$guestPath = Join-Path $sandboxRoot 'scripts\In-Sandbox-Soak.ps1'

Assert-That (Test-Path -LiteralPath $hostRunner -PathType Leaf) 'host runner is present'
Assert-That (Test-Path -LiteralPath $templatePath -PathType Leaf) 'WSB template is present'
Assert-That (Test-Path -LiteralPath $guestPath -PathType Leaf) 'guest runner is present'

$tokens = $null
$parseErrors = $null
$guestAst = [System.Management.Automation.Language.Parser]::ParseFile($guestPath, [ref]$tokens, [ref]$parseErrors)
Assert-That (@($parseErrors).Count -eq 0) 'guest runner parses before inspecting its parameter contract'
$guestDefaults = Invoke-GuestParameterContract -GuestAst $guestAst
Assert-That ($guestDefaults.install_bound_minutes -eq 20) 'guest install bound default is 20 minutes'
Assert-That ($guestDefaults.health_bound_minutes -eq 10) 'guest health bound default is 10 minutes'
$guestOverrides = Invoke-GuestParameterContract -GuestAst $guestAst -Parameters @{
    InstallBoundMinutes = 45
    HealthBoundMinutes = 17
}
Assert-That ($guestOverrides.install_bound_minutes -eq 45) 'guest accepts an install bound override'
Assert-That ($guestOverrides.health_bound_minutes -eq 17) 'guest accepts a health bound override'
foreach ($parameterName in @('InstallBoundMinutes', 'HealthBoundMinutes')) {
    foreach ($invalidValue in @(0, 181)) {
        Assert-GuestRejectsBound -GuestAst $guestAst -ParameterName $parameterName -Value $invalidValue
    }
}

$parameterEnd = $guestAst.ParamBlock.Extent.EndOffset
$laterBoundAssignments = @(
    $guestAst.FindAll({ param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true) |
        Where-Object {
            $_.Extent.StartOffset -ge $parameterEnd -and
            @('$InstallBoundMinutes', '$HealthBoundMinutes') -contains $_.Left.Extent.Text
        }
)
Assert-That ($laterBoundAssignments.Count -eq 0) `
    'guest body does not reset an install or health parameter after binding'

$testBase = Join-Path ([System.IO.Path]::GetTempPath()) 'civiccast-soak-bound-tests'
New-Item -ItemType Directory -Force -Path $testBase | Out-Null
$testRoot = Join-Path $testBase ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot -ErrorAction Stop | Out-Null
try {
    $harnessRoot = Join-Path $testRoot 'sandbox-lab'
    $kitRoot = Join-Path $testRoot 'kit-root'
    $sha = '0123456789abcdef0123456789abcdef01234567'
    $kit = Join-Path $kitRoot $sha

    New-Item -ItemType Directory -Force -Path $harnessRoot, $kit | Out-Null
    Copy-Item -LiteralPath $templatePath -Destination (Join-Path $harnessRoot 'CivicCastSandboxSoak.wsb.template')
    Copy-Item -LiteralPath (Join-Path $sandboxRoot 'scripts') -Destination (Join-Path $harnessRoot 'scripts') -Recurse

    $installer = Join-Path $kit 'candidate-setup.exe'
    $samples = Join-Path $kit 'samples'
    New-Item -ItemType Directory -Force -Path $samples | Out-Null
    [System.IO.File]::WriteAllText($installer, 'not executed by DryRun')
    [System.IO.File]::WriteAllText((Join-Path $samples 'sample.mp4'), 'not decoded by DryRun')
    $sumLines = @(
        ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() + ' *candidate-setup.exe'),
        ((Get-FileHash -LiteralPath (Join-Path $samples 'sample.mp4') -Algorithm SHA256).Hash.ToLowerInvariant() + ' *samples/sample.mp4')
    )
    Set-Content -LiteralPath (Join-Path $kit 'SHA256SUMS.txt') -Value $sumLines -Encoding UTF8

    $invalidRoot = Join-Path $testRoot 'must-not-be-created'
    foreach ($parameterName in @('InstallBoundMinutes', 'HealthBoundMinutes')) {
        foreach ($invalidValue in @(0, 181)) {
            Assert-HostRejectsBoundBeforeFiles -HostRunner $hostRunner -Sha $sha -KitRoot $kitRoot `
                -NoCreateRoot $invalidRoot -ParameterName $parameterName -Value $invalidValue
        }
    }

    $output = & $hostRunner -Sha $sha -Root $harnessRoot -KitRoot $kitRoot -Minutes 15 `
        -InstallBoundMinutes 45 -HealthBoundMinutes 17 -DryRun 2>&1
    Assert-That ($LASTEXITCODE -eq 0) ("host dry run exits successfully: " + ($output | Out-String))

    $wsb = @(Get-ChildItem -LiteralPath $harnessRoot -Filter 'CivicCastSandboxSoak-soak-*.wsb' -File)
    Assert-That ($wsb.Count -eq 1) 'host dry run emitted exactly one rendered WSB file'
    $rendered = Get-Content -LiteralPath $wsb[0].FullName -Raw -Encoding UTF8
    Assert-That ($rendered -match '(?s)-InstallBoundMinutes\s+45\s+-HealthBoundMinutes\s+17\s+-OnAirBoundMinutes') `
        'rendered guest command carries both requested phase bounds in order'
    Assert-That ($rendered -notmatch '\{\{(?:INSTALL|HEALTH)_BOUND_MINUTES\}\}') `
        'rendered WSB contains no phase-bound placeholders'

    $guest = Get-Content -LiteralPath (Join-Path $harnessRoot 'scripts\In-Sandbox-Soak.ps1') -Raw -Encoding UTF8
    Assert-That ($guest -match 'install_bound_minutes\s*=\s*\$InstallBoundMinutes') `
        'guest records the effective install budget'
    Assert-That ($guest -match 'health_bound_minutes\s*=\s*\$HealthBoundMinutes') `
        'guest records the effective health budget'

    Write-Host 'PASS: real Run-SandboxSoak -DryRun forwards custom install/health bounds to the guest.'
} finally {
    Assert-OwnedTemporaryTree -BasePath $testBase -TargetPath $testRoot
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
