# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')

function Assert-True([string] $Name, [bool] $Value) {
    if (-not $Value) { throw "Assertion failed: $Name" }
}

function Assert-Throws([string] $Name, [scriptblock] $Action) {
    try {
        & $Action
        throw "Assertion failed: $Name did not throw"
    } catch {
        if ($_.Exception.Message -like 'Assertion failed:*') { throw }
        return $_.Exception.Message
    }
}

$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) "civiccast-git-helper-test-$([guid]::NewGuid().ToString('N'))"
$oldPath = $env:PATH
try {
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    $stub = Join-Path $temporaryRoot 'git.cmd'
    @'
@echo off
if "%3"=="fail" (
  >&2 echo expected failure stderr
  exit /b 7
)
>&2 echo expected success stderr
exit /b 0
'@ | Set-Content -LiteralPath $stub -Encoding ascii
    $env:PATH = "$temporaryRoot;$oldPath"

    $success = @(Invoke-Beta5Git -Repository 'C:\unused-local-fixture' -Arguments @('probe'))
    Assert-True 'successful stderr is returned as a string' ($success.Count -eq 1 -and $success[0] -is [string])
    Assert-True 'successful stderr does not become a terminating error' ($success[0] -eq 'expected success stderr')

    $failureMessage = Assert-Throws 'non-zero Git exit fails' { Invoke-Beta5Git -Repository 'C:\unused-local-fixture' -Arguments @('fail') }
    Assert-True 'failure includes flattened native output' ($failureMessage -like '*expected failure stderr*')
    Assert-True 'failure does not leak a RemoteException wrapper' ($failureMessage -notlike '*RemoteException*')
} finally {
    $env:PATH = $oldPath
    if (Test-Path -LiteralPath $temporaryRoot) {
        # Only this one known fixture file is removed; no recursive target.
        if (Test-Path -LiteralPath $stub) { Remove-Item -LiteralPath $stub -Force }
        Remove-Item -LiteralPath $temporaryRoot
    }
}
Write-Host 'PASS: Invoke-Beta5Git handles successful stderr and rejects non-zero exit codes.'
