# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$previous = $env:BETA5_RETRY_AUTORUN_LIBRARY
$env:BETA5_RETRY_AUTORUN_LIBRARY = '1'
try { . (Join-Path $PSScriptRoot 'retry-install\Invoke-Beta5PreinstallRetry.ps1') }
finally {
    if ($null -eq $previous) { Remove-Item Env:BETA5_RETRY_AUTORUN_LIBRARY -ErrorAction SilentlyContinue }
    else { $env:BETA5_RETRY_AUTORUN_LIBRARY = $previous }
}

function Assert-True { param([string] $Name, [bool] $Value) if (-not $Value) { throw "Assertion failed: $Name" } }
function Assert-Throws { param([string] $Name, [scriptblock] $Action) try { & $Action; throw "Assertion failed: $Name did not throw" } catch { if ($_.Exception.Message -like 'Assertion failed:*') { throw } } }

$temp = Join-Path ([IO.Path]::GetTempPath()) ("beta5-retry-autorun-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $temp | Out-Null
    $supportRoot = Join-Path $temp 'beta5'
    $wrapperRoot = Join-Path $supportRoot 'retry-install'
    New-Item -ItemType Directory -Path $wrapperRoot -Force | Out-Null
    foreach ($name in $script:RetryFiles) { Set-Content -LiteralPath (Join-Path $supportRoot $name) -Value "# $name" -Encoding utf8 }
    Set-Content -LiteralPath (Join-Path $wrapperRoot 'BETA5-PREINSTALL-RETRY.ps1') -Value '# wrapper' -Encoding utf8
    $files = @($script:RetryFiles | ForEach-Object {
        [pscustomobject]@{ name = $_; sha256 = (Get-FileHash -LiteralPath (Join-Path $supportRoot $_) -Algorithm SHA256).Hash.ToLowerInvariant() }
    })
    $wrapperHash = (Get-FileHash -LiteralPath (Join-Path $wrapperRoot 'BETA5-PREINSTALL-RETRY.ps1') -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{ schema = 'civiccast-native-beta5-retry-package-v1'; candidate_source_sha = $script:RetryCandidate; files = $files; wrapper = [ordered]@{ name = 'BETA5-PREINSTALL-RETRY.ps1'; sha256 = $wrapperHash } }
    $manifestPath = Join-Path $wrapperRoot 'package-sha256.json'
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    $contract = Get-RetryPackageContract -SupportRoot $supportRoot -WrapperRoot $wrapperRoot -ManifestPath $manifestPath
    Assert-True 'six support plus wrapper are bound' ($contract.Bindings.Count -eq 7)
    $copy = Join-Path $temp 'copy'
    $copiedManifest = Copy-RetryPackage -Contract $contract -Destination $copy
    Assert-True 'wrapper copy hash preserved' ((Get-FileHash -LiteralPath (Join-Path $copy 'BETA5-PREINSTALL-RETRY.ps1') -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $wrapperHash)
    Assert-True 'manifest copy exists' (Test-Path -LiteralPath $copiedManifest -PathType Leaf)
    $bad = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $bad.PSObject.Properties.Remove('wrapper')
    $bad | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    Assert-Throws 'wrapper hash must be present' { Get-RetryPackageContract -SupportRoot $supportRoot -WrapperRoot $wrapperRoot -ManifestPath $manifestPath }
    $safe = Get-RetrySafeFailure ([System.Management.Automation.ErrorRecord]::new([InvalidOperationException]::new('secret'), 'id', [Management.Automation.ErrorCategory]::InvalidOperation, $null))
    Assert-True 'safe failure excludes message' (-not ($safe.PSObject.Properties.Name -contains 'message'))
    Invoke-RetryGit -Arguments @('fake') -Runner {
        param([string[]] $GitArguments)
        & $env:ComSpec /d /c 'echo synthetic git progress 1>&2 & exit /b 0'
    }
    Assert-True 'native success restores caller error preference' ($ErrorActionPreference -eq 'Stop')
    Assert-Throws 'native Git stderr is classified by exit code' {
        Invoke-RetryGit -Arguments @('fake') -Runner {
            param([string[]] $GitArguments)
            & $env:ComSpec /d /c 'echo synthetic git stderr 1>&2 & exit /b 7'
        }
    }
    $journalRoot = Join-Path $temp 'mission'
    $journalDirectory = Join-Path $journalRoot 'install-retry-r1'
    New-Item -ItemType Directory -Path $journalDirectory -Force | Out-Null
    @{ status = 'FAILED_REQUIRES_RECONCILIATION'; stage = '02-FETCH-INSTALL'; error_type = 'System.InvalidOperationException' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $journalDirectory 'retry-journal.json') -Encoding utf8
    $summary = Get-RetryJournalSummary -MissionRoot $journalRoot
    Assert-True 'failed wrapper journal is surfaced' ($summary.present -and $summary.status -eq 'FAILED_REQUIRES_RECONCILIATION')
    Set-Content -LiteralPath (Join-Path $journalDirectory 'retry-journal.json') -Value '{not-json' -Encoding utf8
    $unreadable = Get-RetryJournalSummary -MissionRoot $journalRoot
    Assert-True 'journal parse error is explicit and sanitized' ($null -ne $unreadable.read_failure -and -not ($unreadable.read_failure.PSObject.Properties.Name -contains 'message'))
    Write-Host 'PASS: retry autorun package/wrapper hashes and safe failure receipt contract.'
} finally {
    $resolvedTemp = [IO.Path]::GetFullPath($temp)
    $allowedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedTemp.StartsWith($allowedTemp,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolvedTemp) -notmatch '^beta5-retry-autorun-[0-9a-f]{32}$') { throw 'Refusing unexpected fixture cleanup path.' }
    if (Test-Path -LiteralPath $resolvedTemp) { Remove-Item -LiteralPath $resolvedTemp -Recurse -Force }
}
