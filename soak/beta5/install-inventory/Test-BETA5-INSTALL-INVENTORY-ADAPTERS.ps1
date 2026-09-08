# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'BETA5-INSTALL-INVENTORY-ADAPTERS.ps1')
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$fixtureRoot = Join-Path $temporaryBase ('civiccast-install-inventory-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
$passed = 0
function Assert-InventoryAdapter {
    param([bool] $Condition, [string] $Name)
    if (-not $Condition) { throw "Assertion failed: $Name" }
    $script:passed++
}
try {
    $log = Join-Path $fixtureRoot 'AUTORUN-SEP8-BETA5-BE1260-R1-20260908T151611Z.log'
    @('arbitrary secret token not-for-export', 'Installed ffprobe.exe is required for gap-free schedule durations.') | Set-Content -LiteralPath $log
    $signal = Get-Beta5KnownInstallLogSignals $log
    Assert-InventoryAdapter ($signal.inspected -and $signal.ffprobe_lookup_failure) 'actual known failure classified'
    Assert-InventoryAdapter (-not $signal.fetch_verify_upgrade_pass) 'no invented completed install'
    Assert-InventoryAdapter (-not (($signal | ConvertTo-Json) -match 'not-for-export|gap-free schedule')) 'raw log and secrets never serialized'
    @('tar.exe : Not found in archive SECRET_DO_NOT_EXPORT', 'At C:\CivicCastSoak\missions\beta5-sep8-be1260bd0630\bin\AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1:70 char:19', '    + CategoryInfo : NotSpecified: (SECRET:String) [], RemoteException', '    + FullyQualifiedErrorId : NativeCommandError') | Set-Content -LiteralPath $log
    $nativeSignal = Get-Beta5KnownInstallLogSignals $log
    Assert-InventoryAdapter ($nativeSignal.known_failure_categories -contains 'native_archive_member_missing') 'known archive category classified'
    Assert-InventoryAdapter ($nativeSignal.script_locations.Count -eq 1 -and $nativeSignal.script_locations[0].line -eq 70) 'only known script location retained'
    Assert-InventoryAdapter ($nativeSignal.powershell_error_categories -contains 'NotSpecified') 'only bounded PowerShell category retained'
    Assert-InventoryAdapter (-not (($nativeSignal | ConvertTo-Json -Depth 8) -match 'SECRET|FullyQualifiedErrorId|RemoteException')) 'arbitrary error text excluded'
    'FETCH/VERIFY/UPGRADE PASS: 1.0.0-beta.5, manifest+installer hashes independent, signer Scott Converse, service running from C:\CivicCastHostStore\install.' | Set-Content -LiteralPath $log
    $signal = Get-Beta5KnownInstallLogSignals $log
    Assert-InventoryAdapter ($signal.fetch_verify_upgrade_pass -and -not $signal.ffprobe_lookup_failure) 'actual exact success phrase distinguished'
    '' | Set-Content -LiteralPath $log
    Assert-InventoryAdapter ((Get-Beta5KnownInstallLogSignals $log).inspected) 'empty log inspected safely'
    $wrongRejected = $false
    try { Get-Beta5KnownInstallLogSignals (Join-Path $fixtureRoot 'other.log') } catch { $wrongRejected = $true }
    Assert-InventoryAdapter $wrongRejected 'other log rejected'
    $missing = Join-Path $fixtureRoot 'AUTORUN-SEP8-BETA5-BE1260-R1-20260908T151612Z.log'
    Assert-InventoryAdapter (-not (Get-Beta5KnownInstallLogSignals $missing).inspected) 'missing original log safely represented'
    $stream = [IO.File]::Open($log, [IO.FileMode]::Create, [IO.FileAccess]::Write)
    try { $stream.SetLength(4MB + 1) } finally { $stream.Dispose() }
    $large = Get-Beta5KnownInstallLogSignals $log
    Assert-InventoryAdapter ($large.skipped_oversize -and -not $large.inspected) 'oversize log not read'
    $logs = @(Read-Beta5InventoryLogs $fixtureRoot 'AUTORUN-SEP8-BETA5-BE1260-R1-')
    Assert-InventoryAdapter ($logs.Count -eq 1 -and $logs[0].FullName -eq $log) 'actual filesystem adapter receives exact filename prefix'
    Assert-InventoryAdapter (@(Read-Beta5InventoryKit $fixtureRoot).Count -eq 1) 'bounded actual file inventory'
    Assert-InventoryAdapter ($null -eq (Read-Beta5InventoryIdentity (Join-Path $fixtureRoot 'absent.json'))) 'absent identity adapter returns null'
    $invalidIdentity = Join-Path $fixtureRoot 'identity.json'
    '{invalid' | Set-Content -LiteralPath $invalidIdentity
    $badJson = $false
    try { Read-Beta5InventoryIdentity $invalidIdentity } catch { $badJson = $true }
    Assert-InventoryAdapter $badJson 'malformed actual identity rejected for caller to summarize'
    Write-Host "PASS: $passed actual inventory adapter assertions; no live service/process/remote calls."
} finally {
    $resolvedFixture = [IO.Path]::GetFullPath($fixtureRoot).TrimEnd('\')
    if (-not $resolvedFixture.StartsWith($temporaryBase + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolvedFixture) -notmatch '^civiccast-install-inventory-[0-9a-f]{32}$') { throw 'Refusing unconfined test cleanup.' }
    $null = Assert-Beta5InventoryPlainPath $resolvedFixture
    foreach ($entry in Get-ChildItem -LiteralPath $resolvedFixture -Recurse -Force) {
        if (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing test cleanup across a reparse point.' }
    }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
