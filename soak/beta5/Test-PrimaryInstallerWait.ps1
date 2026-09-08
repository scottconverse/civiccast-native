# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$parseErrors=$null
$tree=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-02-FETCH-INSTALL.ps1'),[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw 'Fetch script parse failed.' }
$definitions=@($tree.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Wait-Beta5PrimaryInstaller'},$true))
if ($definitions.Count -ne 1) { throw 'Primary installer waiter is not unique.' }
. ([scriptblock]::Create($definitions[0].Extent.Text))
foreach ($expected in @(0,7)) {
    $child=Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\cmd.exe') -ArgumentList @('/d','/c','exit',"$expected") -PassThru -WindowStyle Hidden
    $observed=Wait-Beta5PrimaryInstaller $child 10000
    if ($observed -ne $expected) { throw "Actual child exitcode mismatch: expected$expected observed$observed." }
    $child.Dispose()
}
$hostExecutable=(Get-Process -Id $PID).Path
$sleeper=Start-Process -FilePath $hostExecutable -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 2') -PassThru -WindowStyle Hidden
$timedOut=$false
try {
    try { Wait-Beta5PrimaryInstaller $sleeper 1 } catch [TimeoutException] { $timedOut=$true }
    if (-not $timedOut -or $sleeper.HasExited) { throw 'Bounded waiter did not preserve the timed-out process.' }
} finally {
    if (-not $sleeper.WaitForExit(10000)) { throw 'Test child failed to finish by itself; it was not killed.' }
    $sleeper.Dispose()
}
Write-Host 'PASS: actual primary child exit0/7 and timeout-without-kill, no installer or station action.'
