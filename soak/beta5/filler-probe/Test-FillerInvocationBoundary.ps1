# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$passed = 0
$sha = 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a'
$version = '1.0.0-beta.5'
$boundaryHostExecutable = (Get-Process -Id $PID).Path

function Assert-True([bool] $Condition, [string] $Name) {
    if (-not $Condition) { throw "FAIL: $Name" }
    $script:passed++
}

function Copy-ActualFillerHelper([string] $Destination) {
    New-Item -ItemType Directory -Path $Destination | Out-Null
    foreach ($name in @('Invoke-FillerAcceptance.ps1', 'ProbeContracts.psm1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $Destination $name)
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $name)).Hash -eq (Get-FileHash -LiteralPath (Join-Path $Destination $name)).Hash) "copied actual $name bytes"
    }
}

function Remove-SafeFixtureRoot([string] $Path) {
    $temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $prefix = $temporaryBase + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($full) -notlike 'filler-inprocess-boundary-*') {
        throw "Refusing recursive fixture cleanup outside the expected temporary child: $full"
    }
    $temporaryItem = Get-Item -LiteralPath $temporaryBase -Force
    if (($temporaryItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing recursive fixture cleanup through a reparse-point temporary base: $temporaryBase" }
    $cursor = $full
    while ($cursor.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Refusing recursive fixture cleanup across a reparse point: $cursor" }
        }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { throw 'Fixture cleanup ancestor walk did not reach the temporary base.' }
        $cursor = [IO.Path]::GetFullPath($parent).TrimEnd('\')
    }
    if (-not $cursor.Equals($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture cleanup ancestor walk left the temporary base.' }
    Remove-Item -LiteralPath $full -Recurse -Force
}

function New-AcceptanceParameters([string] $TspExe) {
    return @{
        ApiBase = 'http://127.0.0.1:8000'; ChannelId = 'boundary-probe'; BearerToken = 'in-memory-only'
        FirstAssetId = 'asset-one'; SecondAssetId = 'asset-two'; FirstSourceLabel = 'Sample one'; SecondSourceLabel = 'Sample two'
        ExpectedSha = $sha; ExpectedVersion = $version; InstallReceiptPath = (Join-Path $PSScriptRoot 'not-read-in-these-tests.json')
        UdpPort = 19091; TspExe = $TspExe
    }
}

$initializerPath = Join-Path $PSScriptRoot 'Initialize-FillerProbe.ps1'
$acceptancePath = Join-Path $PSScriptRoot 'Invoke-FillerAcceptance.ps1'
$initializerText = Get-Content -LiteralPath $initializerPath -Raw
$acceptanceText = Get-Content -LiteralPath $acceptancePath -Raw
Assert-True ($initializerText -notmatch '&\s+powershell\.exe') 'initializer does not start native PowerShell child'
Assert-True ($initializerText -match '@acceptanceParameters') 'initializer splats in-memory parameters'
Assert-True ($initializerText -match '\$global:LASTEXITCODE=\$null') 'initializer clears stale child exit state before invocation'
Assert-True ($acceptanceText -match '\$receipt=\$null;\$receiptHash=\$null') 'actual acceptance helper initializes early trap receipts'

$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('filler-inprocess-boundary-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
try {
    # Invoke copied production bytes, not a behavioral duplicate. Both paths terminate
    # before any API request, and the local override makes an accidental call fatal.
    $planRoot = Join-Path $fixtureRoot 'actual-plan'
    Copy-ActualFillerHelper $planRoot
    function Invoke-RestMethod { throw 'unexpected live API invocation from hermetic acceptance test' }
    $planFinally = $false
    try {
        $planParameters = New-AcceptanceParameters (Join-Path $planRoot 'missing-tsp.exe')
        $LASTEXITCODE = 99
        & (Join-Path $planRoot 'Invoke-FillerAcceptance.ps1') @planParameters
        $planExit = $LASTEXITCODE
    } finally { $planFinally = $true; Remove-Item Function:\Invoke-RestMethod -ErrorAction SilentlyContinue }
    Assert-True ($planExit -eq 0) 'actual plan mode propagated exit zero to caller'
    Assert-True $planFinally 'actual plan mode returned through caller finally'
    Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $planRoot 'results') -Filter 'PLAN.json' -File -Recurse).Count -eq 1) 'actual plan mode wrote its plan receipt'

    $errorRoot = Join-Path $fixtureRoot 'actual-missing-tsp'
    Copy-ActualFillerHelper $errorRoot
    function Invoke-RestMethod { throw 'unexpected live API invocation from hermetic acceptance test' }
    $errorFinally = $false
    try {
        $errorParameters = New-AcceptanceParameters (Join-Path $errorRoot 'definitely-missing-tsp.exe')
        $errorParameters.Execute = $true
        $LASTEXITCODE = 99
        & (Join-Path $errorRoot 'Invoke-FillerAcceptance.ps1') @errorParameters
        $errorExit = $LASTEXITCODE
    } finally { $errorFinally = $true; Remove-Item Function:\Invoke-RestMethod -ErrorAction SilentlyContinue }
    $errorResults = @(Get-ChildItem -LiteralPath (Join-Path $errorRoot 'results') -Filter 'RESULT.json' -File -Recurse)
    Assert-True ($errorExit -eq 2) 'actual missing-tsp trap propagated logical error 2'
    Assert-True $errorFinally 'actual missing-tsp trap returned through caller finally'
    Assert-True ($errorResults.Count -eq 1) 'actual missing-tsp trap wrote one result'
    $errorResult = Get-Content -LiteralPath $errorResults[0].FullName -Raw | ConvertFrom-Json
    Assert-True ($errorResult.verdict -eq 'FAIL') 'actual missing-tsp trap recorded FAIL'
    Assert-True ($null -eq $errorResult.install_receipt_path -and $null -eq $errorResult.install_receipt_sha256) 'actual early trap initialized receipt fields under StrictMode'
    Assert-True ($errorResult.error -match 'tsp\.exe not found') 'actual early trap retained the missing-tsp reason'

    # The actual initializer is isolated in a child host because its public contract
    # intentionally exits. The wrapper defines all HTTP calls as local function stubs.
    $wrapperPath = Join-Path $fixtureRoot 'Run-ActualInitializerWithStubs.ps1'
    @'
param([string] $InitializerPath,[string] $IdentityPath,[string] $VerdictPath,[string] $TokenPath,[string] $TspPath,[string] $OperationLog)
$ErrorActionPreference='Stop'
$global:StubOperationLog=$OperationLog
function global:Start-Sleep { param([int] $Seconds) }
function global:Invoke-RestMethod {
    param([string] $Method='Get',[string] $Uri,$Headers,[int] $TimeoutSec,$ContentType,$Body)
    if($null-ne$Headers-and"$($Headers.Authorization)"-notmatch'^Bearer '){throw 'missing stub bearer'}
    if($Uri-like'*/api/version'){return [pscustomobject]@{version='1.0.0-beta.5'}}
    if($Uri-like'*/api/staff/egress/channels' -and $Method-eq'Get'){return @()}
    if($Uri-like'*/api/staff/assets?*'){
        return @(
            [pscustomobject]@{asset_id='asset-one';title='Sample one';state='validated';manifest_url='/media/vod/asset-one/playlist.m3u8';published_at='2026-09-08T00:00:00Z';duration_seconds=30;content_hash='one'},
            [pscustomobject]@{asset_id='asset-two';title='Sample two';state='validated';manifest_url='/media/vod/asset-two/playlist.m3u8';published_at='2026-09-08T00:00:00Z';duration_seconds=31;content_hash='two'}
        )
    }
    if($Uri-like'*/config' -and $Method-eq'Put'){Add-Content -LiteralPath $global:StubOperationLog -Value "PUT config $Body";return [pscustomobject]@{saved=$true}}
    if($Uri-like'*/commands' -and $Method-eq'Post'){Add-Content -LiteralPath $global:StubOperationLog -Value "POST command $Body";return [pscustomobject]@{accepted=$true}}
    if($Uri-like'*/state' -and $Method-eq'Get'){return [pscustomobject]@{state='FALLBACK_SLATE';pid=4242}}
    throw "unexpected stub URI: $Method $Uri"
}
$token=(Get-Content -LiteralPath $TokenPath -Raw).Trim()
& $InitializerPath -ApiBase http://127.0.0.1:8000 -ChannelId boundary-probe -BearerToken $token -ExpectedSha be1260bd0630261c571e3adf5aac6a6cbebd9e3a -ExpectedVersion 1.0.0-beta.5 -RunIdentityPath $IdentityPath -FinalVerdictPath $VerdictPath -UdpPort 19091 -TspExe $TspPath -Execute
exit $LASTEXITCODE
'@ | Set-Content -LiteralPath $wrapperPath -Encoding utf8

    foreach ($case in @(
        [pscustomobject]@{ name = 'pass'; stub = 'exit 0'; exit = 0; primary_error = $false },
        [pscustomobject]@{ name = 'proof-fail'; stub = 'exit 1'; exit = 1; primary_error = $false },
        [pscustomobject]@{ name = 'invalid-exit'; stub = 'exit 9'; exit = 2; primary_error = $true },
        [pscustomobject]@{ name = 'no-exit'; stub = 'return'; exit = 2; primary_error = $true },
        [pscustomobject]@{ name = 'throw'; stub = "trap { exit 2 }; throw 'stub acceptance failure'"; exit = 2; primary_error = $false }
    )) {
        $caseRoot = Join-Path $fixtureRoot ('initializer-' + $case.name)
        New-Item -ItemType Directory -Path $caseRoot | Out-Null
        Copy-Item -LiteralPath $initializerPath,(Join-Path $PSScriptRoot 'ProbeContracts.psm1') -Destination $caseRoot
        "param(`$ApiBase,`$ChannelId,`$BearerToken,`$FirstAssetId,`$SecondAssetId,`$FirstSourceLabel,`$SecondSourceLabel,`$ExpectedSha,`$ExpectedVersion,`$InstallReceiptPath,`$UdpPort,`$TspExe,`$LeadSeconds,`$ProgramSeconds,[switch]`$Execute,[switch]`$LongBoard)`r`n$($case.stub)" | Set-Content -LiteralPath (Join-Path $caseRoot 'Invoke-FillerAcceptance.ps1') -Encoding utf8
        $hashes = [pscustomobject]@{ 'daemon.py' = ('a' * 64) }
        $identity = [pscustomobject]@{schema='civiccast-native-tester-run-identity-v3';mission='beta5-sep8-be1260bd0630';candidate_source_sha=$sha;expected_version=$version;installed_version=$version;expected_manifest_sha256=('b'*64);actual_manifest_sha256=('b'*64);expected_installer_sha256=('c'*64);actual_installer_sha256=('c'*64);native_app_payload_source_sha=$sha;expected_runtime_file_sha256=$hashes;actual_runtime_file_sha256=$hashes;approved_assets=@([pscustomobject]@{asset_id='asset-one';title='Sample one';duration_seconds=30},[pscustomobject]@{asset_id='asset-two';title='Sample two';duration_seconds=31})}
        $verdict = [pscustomobject]@{schema='civiccast-native-beta5-media-verdict-v3';mission='beta5-sep8-be1260bd0630';candidate_source_sha=$sha;verdict='PASS'}
        $identityPath = Join-Path $caseRoot 'identity.json'; $verdictPath = Join-Path $caseRoot 'verdict.json'; $tokenPath = Join-Path $caseRoot 'token'; $tspPath = Join-Path $caseRoot 'tsp.exe'; $operationLog = Join-Path $caseRoot 'operations.log'
        $identity | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $identityPath -Encoding utf8
        $verdict | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verdictPath -Encoding utf8
        $caseSecret = 'case-secret-' + [guid]::NewGuid().ToString('N'); Set-Content -LiteralPath $tokenPath -Value $caseSecret -Encoding ascii; Set-Content -LiteralPath $tspPath -Value 'fixture' -Encoding ascii
        & $boundaryHostExecutable -NoProfile -ExecutionPolicy Bypass -File $wrapperPath -InitializerPath (Join-Path $caseRoot 'Initialize-FillerProbe.ps1') -IdentityPath $identityPath -VerdictPath $verdictPath -TokenPath $tokenPath -TspPath $tspPath -OperationLog $operationLog
        $childExit = $LASTEXITCODE
        Assert-True ($childExit -eq $case.exit) "actual initializer $($case.name) propagated expected exit $($case.exit) (actual $childExit)"
        $setupResults = @(Get-ChildItem -LiteralPath (Join-Path $caseRoot 'results') -Filter 'SETUP-RESULT.json' -File -Recurse)
        Assert-True ($setupResults.Count -eq 1) "actual initializer $($case.name) wrote one setup result"
        $setup = Get-Content -LiteralPath $setupResults[0].FullName -Raw | ConvertFrom-Json
        Assert-True ([int] $setup.acceptance_exit_code -eq $case.exit) "actual initializer $($case.name) recorded logical exit"
        Assert-True (@($setup.cleanup_errors).Count -eq 0 -and [bool] $setup.retained_channel_disabled) "actual initializer $($case.name) completed cleanup"
        Assert-True (($null -ne $setup.primary_error) -eq $case.primary_error) "actual initializer $($case.name) recorded error presence"
        $operations = Get-Content -LiteralPath $operationLog -Raw
        Assert-True ($operations -match '"action"\s*:\s*"stop"' -and $operations -match '"enabled"\s*:\s*false') "actual initializer $($case.name) issued stop and disable cleanup"
        $recorded = (@(Get-ChildItem -LiteralPath (Join-Path $caseRoot 'results') -File -Recurse | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n") + $operations
        Assert-True ($recorded -notmatch [regex]::Escape($caseSecret)) "actual initializer $($case.name) did not record token"
    }
} finally {
    Remove-SafeFixtureRoot $fixtureRoot
}

Write-Host "PASS: $passed actual filler invocation boundary assertions"
