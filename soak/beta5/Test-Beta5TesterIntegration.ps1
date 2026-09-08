# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
function Assert-True([string] $Name, [bool] $Value) { if (-not $Value) { throw "Assertion failed: $Name" } }
function Assert-Throws([string] $Name, [scriptblock] $Action) { try { & $Action; throw "Assertion failed: $Name did not throw" } catch { if ($_.Exception.Message -like 'Assertion failed:*') { throw } } }
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("beta5-tester-contract-" + [guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $base = Join-Path $testRoot 'soak\beta5'; $child = Join-Path $base 'mission\cycle.json'; $sibling = Join-Path $testRoot 'soak\beta50\escape.json'
    Assert-True 'Windows child path accepted' ((Assert-Beta5ChildPath $base $child) -eq (Get-Beta5FullPath $child))
    Assert-Throws 'prefix sibling rejected' { Assert-Beta5ChildPath $base $sibling }
    Assert-Throws 'manifest traversal rejected' { ConvertFrom-Beta5ManifestPath 'samples/../escape.mp4' }
    Assert-Throws 'manifest rooted path rejected' { ConvertFrom-Beta5ManifestPath 'C:\escape.mp4' }
    Assert-Throws 'manifest ADS rejected' { ConvertFrom-Beta5ManifestPath 'samples/a.mp4:evil' }

    $manifest = Join-Path $testRoot 'SHA256SUMS.txt'
    Set-Content -LiteralPath $manifest -Value @((('a' * 64) + ' *CivicCast (Native)_1.0.0-beta.5_x64-setup.exe'), (('b' * 64) + ' *samples/sample.mp4')) -Encoding ascii
    $entries = @(Read-Beta5Manifest $manifest $testRoot)
    Assert-True 'real flat installer pattern supported' (@($entries | Where-Object { $_.relative_path -match '.+_x64-setup\.exe$' }).Count -eq 1)
    Assert-True 'manifest sample represented' (@($entries | Where-Object { $_.relative_path -eq 'samples\sample.mp4' }).Count -eq 1)

    $incomplete = Join-Path $testRoot 'incomplete.json'; @{ schema = 'civiccast-native-tester-run-identity-v3' } | ConvertTo-Json | Set-Content -LiteralPath $incomplete
    Assert-Throws 'identity missing facts fails closed' { Get-Beta5Identity $incomplete }

    $preflight = Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-01-PREFLIGHT.ps1'
    $targetRoot = Join-Path $testRoot 'target'
    $facts = @{ CandidateSha = ('a' * 40); BuildSourceSha = ('a' * 40); GateASourceSha = ('a' * 40); ManifestSha256 = ('b' * 64); InstallerSha256 = ('c' * 64); BuildRunId = '123'; BuildConclusion = 'success'; GateARunId = '456'; GateAVerdict = 'PENDING'; ExpectedVersion = '1.0.0-beta.5'; KitBaseUrl = ('http://127.0.0.1:8766/' + ('a' * 40) + '/'); ReturnRepositoryUrl = 'https://github.com/scottconverse/civiccast-native.git'; TesterRoot = $targetRoot }
    Assert-Throws 'wrong expected host fails before writes' { & $preflight @facts -ExpectedHostname 'NOT-THIS-HOST' }
    Assert-True 'wrong-host preflight wrote nothing' (-not (Test-Path -LiteralPath $targetRoot))

    $invalidVerdictFacts = $facts.Clone(); $invalidVerdictFacts.TesterRoot = Join-Path $testRoot 'invalid-verdict'; $invalidVerdictFacts.GateAVerdict = 'FAIL'
    Assert-Throws 'invalid Gate A verdict rejected' { & $preflight @invalidVerdictFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'invalid Gate A verdict wrote nothing' (-not (Test-Path -LiteralPath $invalidVerdictFacts.TesterRoot))

    $lowercaseVerdictFacts = $facts.Clone(); $lowercaseVerdictFacts.TesterRoot = Join-Path $testRoot 'lowercase-verdict'; $lowercaseVerdictFacts.GateAVerdict = 'pending'
    Assert-Throws 'noncanonical Gate A verdict rejected' { & $preflight @lowercaseVerdictFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'noncanonical Gate A verdict wrote nothing' (-not (Test-Path -LiteralPath $lowercaseVerdictFacts.TesterRoot))

    $wrongSourceFacts = $facts.Clone(); $wrongSourceFacts.TesterRoot = Join-Path $testRoot 'wrong-source'; $wrongSourceFacts.GateASourceSha = ('d' * 40)
    Assert-Throws 'Gate A source mismatch rejected' { & $preflight @wrongSourceFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'Gate A source mismatch wrote nothing' (-not (Test-Path -LiteralPath $wrongSourceFacts.TesterRoot))

    $zeroRunFacts = $facts.Clone(); $zeroRunFacts.TesterRoot = Join-Path $testRoot 'zero-run'; $zeroRunFacts.GateARunId = '0'
    Assert-Throws 'unassigned Gate A run ID rejected' { & $preflight @zeroRunFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'unassigned Gate A run ID wrote nothing' (-not (Test-Path -LiteralPath $zeroRunFacts.TesterRoot))

    $failedBuildFacts = $facts.Clone(); $failedBuildFacts.TesterRoot = Join-Path $testRoot 'failed-build'; $failedBuildFacts.BuildConclusion = 'failure'
    Assert-Throws 'non-successful candidate build rejected' { & $preflight @failedBuildFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'non-successful candidate build wrote nothing' (-not (Test-Path -LiteralPath $failedBuildFacts.TesterRoot))

    & $preflight @facts -ExpectedHostname $env:COMPUTERNAME | Out-Null
    $identityPath = Join-Path $targetRoot ("missions\beta5-sep8-" + ('a' * 12) + '\run-identity.json')
    $saved = Get-Beta5Identity $identityPath
    Assert-True 'pending Gate A candidate accepted for tester kickoff' ($saved.gate_a_verdict -eq 'PENDING' -and $saved.gate_a_run_id -eq 456)
    Assert-True 'successful candidate build is recorded' ($saved.build_conclusion -eq 'success' -and $saved.build_run_id -eq 123)
    Set-Beta5IdentityField $saved 'actual_installer_sha256' ('c' * 64)
    Write-Beta5JsonAtomic $saved $identityPath
    & $preflight @facts -ExpectedHostname $env:COMPUTERNAME | Out-Null
    $retained = Get-Beta5Identity $identityPath
    Assert-True 'idempotent preflight retains verification receipt' ($retained.actual_installer_sha256 -eq ('c' * 64))
    Assert-True 'immutable kickoff evidence remains pending' ($retained.gate_a_verdict -eq 'PENDING')
    $laterPassFacts = $facts.Clone(); $laterPassFacts.GateAVerdict = 'PASS'
    Assert-Throws 'later Gate A PASS cannot rewrite kickoff evidence' { & $preflight @laterPassFacts -ExpectedHostname $env:COMPUTERNAME }
    Assert-True 'rejected PASS rewrite leaves pending identity intact' ((Get-Beta5Identity $identityPath).gate_a_verdict -eq 'PENDING')
    New-Item -ItemType Directory -Force -Path (Join-Path $targetRoot 'state') | Out-Null
    Set-Content -LiteralPath (Join-Path $targetRoot 'state\soak-started') -Value 'legacy-marker' -Encoding ascii
    $archivedMarker = Move-Beta5LegacySoakMarker $retained
    Assert-True 'legacy AUTORUN-3 marker moved, not deleted' ((-not (Test-Path -LiteralPath (Join-Path $targetRoot 'state\soak-started'))) -and (Get-Content -LiteralPath $archivedMarker -Raw).Trim() -eq 'legacy-marker')
    $replayRoot = Join-Path $testRoot 'replay-target'; $replayMission = Join-Path $replayRoot ("missions\beta5-sep8-" + ('a' * 12)); $replayBin = Join-Path $replayMission 'bin'
    New-Item -ItemType Directory -Force -Path $replayBin | Out-Null; Set-Content -LiteralPath (Join-Path $replayBin 'Beta5Tester.Common.ps1') -Value 'sentinel-do-not-overwrite'; Set-Content -LiteralPath (Join-Path $replayMission 'soak-state.json') -Value '{}'
    $orchestrator = Join-Path $PSScriptRoot 'Invoke-Beta5TesterMission.ps1'
    $replayFacts = $facts.Clone(); $replayFacts.TesterRoot = $replayRoot
    Assert-Throws 'active mission replay refused before child actions' { & $orchestrator @replayFacts -ExpectedHostname $env:COMPUTERNAME -PackageRoot $PSScriptRoot }
    Assert-True 'active mission stable bin not overwritten' ((Get-Content -LiteralPath (Join-Path $replayBin 'Beta5Tester.Common.ps1') -Raw).Trim() -eq 'sentinel-do-not-overwrite')

    $receiptIdentityPath = $identityPath
    $env:BETA5_TESTER_LIBRARY = '1'
    try { . (Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-03-START-SOAK.ps1') -IdentityPath 'library-only' } finally { Remove-Item Env:BETA5_TESTER_LIBRARY -ErrorAction SilentlyContinue }
    Assert-True 'fractional duration matches product ingest floor' ((ConvertTo-Beta5ScheduleDuration '31.75') -eq 31)
    Assert-True 'whole duration is unchanged' ((ConvertTo-Beta5ScheduleDuration '31.0') -eq 31)
    foreach ($invalidDuration in 'NaN', 'Infinity', '0.9', '-2', 'not-a-duration', '2147483648') {
        Assert-Throws "invalid duration rejected: $invalidDuration" { ConvertTo-Beta5ScheduleDuration $invalidDuration }
    }
    $receiptAssets = @(
        [pscustomobject]@{ id = 'asset-first'; duration_seconds = 60; title = 'Mission first sample' },
        [pscustomobject]@{ id = 'asset-second'; duration_seconds = 61; title = 'Mission second sample' }
    )
    $receipt = @(Set-Beta5ApprovedAssetsReceipt -Identity $retained -IdentityPath $receiptIdentityPath -Assets $receiptAssets)
    Assert-True 'approved asset receipt preserves deterministic order and exact fields' ($receipt.Count -eq 2 -and $receipt[0].asset_id -eq 'asset-first' -and $receipt[0].duration_seconds -eq 60 -and $receipt[0].title -eq 'Mission first sample' -and $receipt[1].asset_id -eq 'asset-second')
    $withAssets = Get-Beta5Identity $receiptIdentityPath
    Assert-True 'approved asset receipt is stored without changing kickoff evidence' (@($withAssets.approved_assets).Count -eq 2 -and $withAssets.gate_a_verdict -eq 'PENDING' -and $withAssets.actual_installer_sha256 -eq ('c' * 64))
    Assert-Throws 'incomplete approved asset receipt rejected' { Set-Beta5ApprovedAssetsReceipt -Identity $withAssets -IdentityPath $receiptIdentityPath -Assets @($receiptAssets[0]) }
    Assert-True 'rejected receipt leaves existing approved assets intact' (@((Get-Beta5Identity $receiptIdentityPath).approved_assets).Count -eq 2)
    $id = [pscustomobject]@{ mission = 'm'; planned_seconds = 7200; channels = @([pscustomobject]@{ channel_id = 'public'; udp_port = 9001 }, [pscustomobject]@{ channel_id = 'education'; udp_port = 9002 }, [pscustomobject]@{ channel_id = 'government'; udp_port = 9003 }) }
    $script:stopCalls = @()
    $fakeStopApi = { param($Method, $Url, $BodyObj, $BearerToken); $script:stopCalls += [pscustomobject]@{ method = $Method; url = $Url; body = $BodyObj }; if ($Url -like '*/commands') { [pscustomobject]@{ status = 202; body_json = @{} } } else { [pscustomobject]@{ status = 200; body_json = [pscustomobject]@{ state = 'STOPPED' } } } }
    Stop-Beta5Channels -Identity $id -Token 'not-a-real-token' -ApiInvoker $fakeStopApi -SleepInvoker { param($Seconds) }
    Assert-True 'all three old channel instances quiesced' (@($script:stopCalls | Where-Object { $_.url -like '*/commands' -and $_.body.action -eq 'stop' }).Count -eq 3)
    $script:calls = @(); $script:item = 0
    $fakeApi = {
        param($Method, $Url, $BodyObj, $BearerToken)
        $script:calls += [pscustomobject]@{ method = $Method; url = $Url; body = $BodyObj }
        if ($Url -like '*/api/staff/schedule') { $script:item++; return [pscustomobject]@{ status = 201; body_json = [pscustomobject]@{ id = "item-$script:item" } } }
        if ($Url -like '*/playout/commit') { return [pscustomobject]@{ status = 201; body_json = @{} } }
        if ($Url -like '*/config') { return [pscustomobject]@{ status = 200; body_json = @{} } }
        if ($Url -like '*/commands') { return [pscustomobject]@{ status = 202; body_json = @{} } }
        throw "Unexpected fake URL $Url"
    }
    $null = Invoke-Beta5ScheduleAndStart -Identity $id -Assets @([pscustomobject]@{ id = 'asset'; duration_seconds = 600 }) -Token 'not-a-real-token' -ApiInvoker $fakeApi -Now ([datetime] '2026-01-01T00:00:00Z')
    $commitIndices = @(); $configIndices = @(); $startIndices = @()
    for ($i = 0; $i -lt $script:calls.Count; $i++) { if ($script:calls[$i].url -like '*/playout/commit') { $commitIndices += $i }; if ($script:calls[$i].url -like '*/config') { $configIndices += $i }; if ($script:calls[$i].url -like '*/commands') { $startIndices += $i } }
    Assert-True 'all three channels configured' ($configIndices.Count -eq 3)
    Assert-True 'all three channels started' ($startIndices.Count -eq 3)
    Assert-True 'every commit precedes first config' (($commitIndices | Measure-Object -Maximum).Maximum -lt ($configIndices | Measure-Object -Minimum).Minimum)
    Assert-True 'every config precedes first start' (($configIndices | Measure-Object -Maximum).Maximum -lt ($startIndices | Measure-Object -Minimum).Minimum)

    $wrapper = Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5.ps1'
    Assert-Throws 'unresolved wrapper facts fail before deployment' { & $wrapper -DryRun }
    $schedulerText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'AUTORUN-SEP8-BETA5-05-SCHEDULE-CYCLES.ps1') -Raw
    Assert-True 'scheduler uses identity cadence seconds' ($schedulerText -match 'RepetitionInterval \(New-TimeSpan -Seconds')
    Assert-True 'scheduler passes exact task name for terminal cleanup' ($schedulerText -match '-ScheduledTaskName')
    Write-Host 'PASS: path confinement, exact-source Gate A PENDING kickoff, immutable identity, approved-assets receipt, upload/schedule ordering, wrapper fail-closed, and scheduler contracts.'
} finally { Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue }
