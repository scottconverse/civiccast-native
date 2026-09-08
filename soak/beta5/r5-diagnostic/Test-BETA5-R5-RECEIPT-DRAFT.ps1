# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
$env:BETA5_R5_RECEIPT_LIBRARY='1'
try { . (Join-Path $PSScriptRoot 'BETA5-R5-RECEIPT-DRAFT.ps1') } finally { Remove-Item Env:BETA5_R5_RECEIPT_LIBRARY -ErrorAction SilentlyContinue }
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Assert-True([string]$Name,[bool]$Value){if(-not $Value){throw "Assertion failed: $Name"}}
function Assert-Throws([string]$Name,[scriptblock]$Action){try{&$Action;throw "Assertion failed: $Name did not throw"}catch{if($_.Exception.Message -like 'Assertion failed:*'){throw}}}
$identity=[pscustomobject]@{mission='beta5-sep8-be1260bd0630';candidate_source_sha='be1260bd0630261c571e3adf5aac6a6cbebd9e3a';actual_installer_sha256='abc';approved_assets=$null}
$receipt=[pscustomobject]@{status='FAILED';wrapper_returned=$false}
$journal=[pscustomobject]@{stage='04-SOAK-CYCLE';status='FAILED_REQUIRES_RECONCILIATION';error_type='System.Exception'}
$verdict=[pscustomobject]@{verdict='FAIL';pid_change_count=1}
$log=[pscustomobject]@{Path='C:\CivicCastSoak\reports\AUTORUN-SEP8-BETA5-BE1260-R1-20260908T194100Z.log'}
$logText="CTRL reload: switching selector`nCTRL reload: holds released`nCTRL reload: old leg disposed`nCTRL reload committed (elements=4)`nFile engine.py, line 2720 in _dispose_source_leg`nFile engine.py, line 2730 in _dispose_source_leg`nbearer=SECRET"
$jsonReader={param($p) if($p -like '*run-identity*'){$identity}elseif($p -like '*install-retry-r1.json'){$receipt}elseif($p -like '*retry-journal*'){$journal}else{$verdict}}
$fileReader={param($p) @([pscustomobject]@{FullName=$log.Path})}
$logReader={param($p) $logText}
$out=Get-Beta5R5Receipt -Root 'C:\CivicCastSoak' -FileReader $fileReader -JsonReader $jsonReader -LogReader $logReader
Assert-True 'exact identity binding' ($out.mission -eq 'beta5-sep8-be1260bd0630' -and $out.candidate_source_sha -eq 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a')
Assert-True 'journal last stage retained' ($out.retry_journal.last_stage -eq '04-SOAK-CYCLE' -and -not $out.retry_journal.history_available)
Assert-True 'bounded stage counts and frames' ($out.log_signals[0].stage_counts.dispose -eq 1 -and $out.log_signals[0].stack_frames.Count -eq 2)
Assert-True 'raw log and secret absent' ((($out|ConvertTo-Json -Depth 12) -notmatch 'bearer=|must-not-export') -and -not $out.raw_contents_exported)
Assert-Throws 'wrong root rejected' { Get-Beta5R5Receipt -Root 'C:\Other' -FileReader $fileReader -JsonReader $jsonReader -LogReader $logReader }
$knownRuntime = [pscustomobject]@{'Lib/site-packages/civiccast/egress/daemon.py'= ('a'*64); 'Lib/site-packages/civiccast/egress/gst/strategy.py'= ('b'*64); 'unknown-secret'= 'must-not-export'}
$nestedIdentity = [pscustomobject]@{expected_runtime_file_sha256=$knownRuntime;actual_runtime_file_sha256=$knownRuntime;approved_assets=@([pscustomobject]@{title='must-not-export'})}
$nestedSummary = Get-Beta5R5JsonSummary 'identity.json' { param($p) $nestedIdentity }
Assert-True 'nested runtime identity is exported explicitly' ($nestedSummary.fields.actual_runtime_file_sha256['Lib/site-packages/civiccast/egress/daemon.py'] -eq ('a'*64) -and $nestedSummary.fields.expected_runtime_file_sha256['Lib/site-packages/civiccast/egress/gst/strategy.py'] -eq ('b'*64))
Assert-True 'only two runtime paths and asset count are exposed' ($nestedSummary.fields.actual_runtime_file_sha256.Count -eq 2 -and $nestedSummary.fields.approved_asset_count -eq 1 -and ($nestedSummary | ConvertTo-Json -Depth 12) -notmatch 'must-not-export')
$timeoutStage = Get-Beta5R5LogStageSummary 'worker.log' { param($p) 'CTRL reload: commit did not finish within 15s - quitting for daemon restart' }
Assert-True 'commit failure is not a committed marker' ($timeoutStage.stage_counts.commit -eq 0)
$oversize=Get-Beta5R5LogStageSummary 'x.log' { param($p) ('x' * (4MB + 1)) }
Assert-True 'oversize log is skipped' ($oversize.skipped_oversize -and -not $oversize.bounded_read)
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('civiccast-r5-fixture-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $identityPath = Join-Path $tempRoot 'run-identity.json'
    '{"mission":"beta5-sep8-be1260bd0630","candidate_source_sha":"be1260bd0630261c571e3adf5aac6a6cbebd9e3a"}' | Set-Content -LiteralPath $identityPath -Encoding utf8
    $logPath = Join-Path $tempRoot 'AUTORUN-SEP8-BETA5-BE1260-R1-20260908T194100Z.log'
    'selector hold dispose commit _dispose_source_leg line 2720 bearer=SECRET _dispose_source_leg line 2730' | Set-Content -LiteralPath $logPath -Encoding utf8
    'ignored' | Set-Content -LiteralPath (Join-Path $tempRoot 'AUTORUN-SEP8-BETA5-BE1260BD0630-20260908T194100Z.log') -Encoding utf8
    $actual = Get-Beta5R5ActualJsonReader $identityPath
    Assert-True 'actual JSON adapter reads fixture' ($actual.mission -eq 'beta5-sep8-be1260bd0630')
    $files = @(Get-Beta5R5ActualLogFiles $tempRoot)
    Assert-True 'actual log adapter exact prefix' ($files.Count -eq 1 -and $files[0].Name -eq 'AUTORUN-SEP8-BETA5-BE1260-R1-20260908T194100Z.log')
    $actualSummary = Get-Beta5R5LogStageSummary $files[0].FullName { param($p) Get-Beta5R5ActualLogReader $p }
    Assert-True 'actual log adapter bounded redaction' ($actualSummary.stack_frames.Count -eq 2 -and (($actualSummary | ConvertTo-Json -Depth 8) -notmatch 'SECRET|bearer'))
    $workerRoot = Join-Path $tempRoot 'egress'
    foreach ($channel in @('public','education','government')) {
        $channelLog = Join-Path $workerRoot "$channel\logs"
        New-Item -ItemType Directory -Force -Path $channelLog | Out-Null
        $logText | Set-Content -LiteralPath (Join-Path $channelLog 'gst-worker.stdout.log') -Encoding utf8
        'stderr selector old leg disposed _dispose_source_leg line 2730 bearer=SECRET' | Set-Content -LiteralPath (Join-Path $channelLog 'gst-worker.stderr.log') -Encoding utf8
    }
    $workerFiles = @(Get-Beta5R5ActualWorkerLogFiles -BaseRoot $workerRoot)
    Assert-True 'worker stdout and stderr inventory' ($workerFiles.Count -eq 6)
    $workerSummary = @(Get-Beta5R5LogStageSummary $workerFiles[0].FullName { param($p) Get-Beta5R5ActualLogReader $p })
    Assert-True 'worker stack stages and frames' ($workerSummary[0].stage_counts.hold -eq 1 -and $workerSummary[0].stage_counts.dispose -eq 1 -and $workerSummary[0].stack_frames.Count -eq 2 -and (($workerSummary | ConvertTo-Json -Depth 8) -notmatch 'SECRET|bearer'))
    Assert-True 'plain in-root path accepted' ((Assert-Beta5R5PlainPath $identityPath $tempRoot) -eq [IO.Path]::GetFullPath($identityPath))
    Assert-Throws 'plain outside path rejected' { Assert-Beta5R5PlainPath ([IO.Path]::GetFullPath((Join-Path $tempRoot '..\outside.json'))) $tempRoot }
} finally {
    $tempFull = [IO.Path]::GetFullPath($tempRoot).TrimEnd('\')
    $baseFull = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    if ((Split-Path -Parent $tempFull) -ne $baseFull -or (Split-Path -Leaf $tempFull) -notmatch '^civiccast-r5-fixture-[a-f0-9]{32}$') { throw 'Refusing unexpected fixture cleanup path.' }
    $null = Assert-Beta5R5PlainPath $tempFull $baseFull
    foreach ($child in @(Get-ChildItem -LiteralPath $tempFull -Recurse -Force)) {
        if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Refusing fixture cleanup across a reparse point.' }
    }
    Remove-Item -LiteralPath $tempFull -Recurse -Force
}
Write-Host 'PASS: R5 identity, journal, bounded stage/frame, redaction, root guards, and real-file adapters.'
