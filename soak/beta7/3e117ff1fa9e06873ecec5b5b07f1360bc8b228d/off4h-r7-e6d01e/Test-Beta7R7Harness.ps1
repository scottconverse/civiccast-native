# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<#
Non-mutating preflight for the beta.7 R7 physical-soak harness.

Local acceptance uses -RequireDualRuntime to run this exact file in Windows
PowerShell 5.1 and pwsh 7. Tester-live callers use the default current-runtime
path because the physical tester has Windows PowerShell 5.1 only. Every path
parses all package scripts, runs the driver's pure self-test, and exercises
synthetic transport fixtures without contacting the station API.
#>
[CmdletBinding()]
param(
    [string]$PackageRoot = $PSScriptRoot,
    [switch]$Child,
    [switch]$RequireDualRuntime
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Check {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-ContainsInOrder {
    param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][string[]]$Needles, [Parameter(Mandatory)][string]$Message)
    $offset = -1
    foreach ($needle in $Needles) {
        $next = $Text.IndexOf($needle, $offset + 1, [StringComparison]::Ordinal)
        if ($next -lt 0) { throw "$Message Missing or out-of-order token: $needle" }
        $offset = $next
    }
}

function Test-AuthoritativePassState {
    param($Job, $Completion)
    if ($null -eq $Job -or $null -eq $Completion) { return $false }
    return (
        [string]$Job.job_state -eq 'PASS' -and
        [string]$Completion.status -eq 'PASS' -and
        -not [string]::IsNullOrWhiteSpace([string]$Completion.verified_evidence_commit) -and
        -not [string]::IsNullOrWhiteSpace([string]$Completion.evidence_sha256) -and
        [string]$Completion.evidence_relative_path -eq [string]$Job.evidence_relative_path
    )
}

function Invoke-TransportFixtures {
    param([Parameter(Mandatory)][string]$Root)
    $transport = Join-Path $Root 'Beta7TransportProbeR7.ps1'
    . $transport

    $clean = [pscustomobject]@{
        ts = [pscustomobject]@{ packets = [pscustomobject]@{ total = 188; 'invalid-syncs' = 0; 'transport-errors' = 0 } }
        pids = @([pscustomobject]@{ packets = [pscustomobject]@{ discontinuities = 0 } })
    }
    $pass = Get-Beta7TransportGrade -Json $clean -Label 'public' -Port 9001 -ExitCode 0
    Assert-Check ($pass.verdict -eq 'PASS') 'Clean 30-second TSDuck fixture did not pass.'

    $variants = @(
        @{ name = 'zero packets'; report = [pscustomobject]@{ ts = [pscustomobject]@{ packets = [pscustomobject]@{ total = 0; 'invalid-syncs' = 0; 'transport-errors' = 0 } }; pids = @([pscustomobject]@{ packets = [pscustomobject]@{ discontinuities = 0 } }) }; exit = 0 },
        @{ name = 'invalid sync'; report = [pscustomobject]@{ ts = [pscustomobject]@{ packets = [pscustomobject]@{ total = 188; 'invalid-syncs' = 1; 'transport-errors' = 0 } }; pids = @([pscustomobject]@{ packets = [pscustomobject]@{ discontinuities = 0 } }) }; exit = 0 },
        @{ name = 'transport error'; report = [pscustomobject]@{ ts = [pscustomobject]@{ packets = [pscustomobject]@{ total = 188; 'invalid-syncs' = 0; 'transport-errors' = 1 } }; pids = @([pscustomobject]@{ packets = [pscustomobject]@{ discontinuities = 0 } }) }; exit = 0 },
        @{ name = 'PID discontinuity'; report = [pscustomobject]@{ ts = [pscustomobject]@{ packets = [pscustomobject]@{ total = 188; 'invalid-syncs' = 0; 'transport-errors' = 0 } }; pids = @([pscustomobject]@{ packets = [pscustomobject]@{ discontinuities = 1 } }) }; exit = 0 },
        @{ name = 'nonzero tsp exit'; report = $clean; exit = 1 },
        @{ name = 'missing report fields'; report = [pscustomobject]@{}; exit = 0 }
    )
    foreach ($variant in $variants) {
        $result = Get-Beta7TransportGrade -Json $variant.report -Label 'public' -Port 9001 -ExitCode $variant.exit
        Assert-Check ($result.verdict -eq 'FAIL') "TSDuck $($variant.name) fixture passed."
    }

    $cmd = [Environment]::GetEnvironmentVariable('ComSpec')
    Assert-Check (-not [string]::IsNullOrWhiteSpace($cmd) -and (Test-Path -LiteralPath $cmd -PathType Leaf)) 'cmd.exe is unavailable for non-mutating transport report fixtures.'
    $probeProcess = Start-Process -FilePath $cmd -ArgumentList @('/c', 'exit 0') -PassThru -WindowStyle Hidden
    $null = $probeProcess.WaitForExit(10000)
    $missingPath = Join-Path $Root ('missing-report-' + [guid]::NewGuid().ToString('N') + '.json')
    Assert-Check (-not (Test-Path -LiteralPath $missingPath)) 'Synthetic missing-report path unexpectedly exists.'
    $missingProbe = [pscustomobject]@{ Process = $probeProcess; StartedUtc = [datetime]::UtcNow; DeadlineUtc = [datetime]::UtcNow.AddSeconds(60); Port = 9001; Label = 'public'; AnalyzedSeconds = 30; ReportPath = $missingPath; StdoutPath = $null; StderrPath = $null }
    $missing = Complete-Beta7TransportProbe $missingProbe
    Assert-Check ($missing.verdict -eq 'FAIL' -and $missing.reason -eq 'missing report') 'Missing TSDuck report fixture did not fail as missing.'

    $malformedProcess = Start-Process -FilePath $cmd -ArgumentList @('/c', 'exit 0') -PassThru -WindowStyle Hidden
    $null = $malformedProcess.WaitForExit(10000)
    $malformedProbe = [pscustomobject]@{ Process = $malformedProcess; StartedUtc = [datetime]::UtcNow; DeadlineUtc = [datetime]::UtcNow.AddSeconds(60); Port = 9001; Label = 'public'; AnalyzedSeconds = 30; ReportPath = $PSCommandPath; StdoutPath = $null; StderrPath = $null }
    $malformed = Complete-Beta7TransportProbe $malformedProbe
    Assert-Check ($malformed.verdict -eq 'FAIL' -and $malformed.reason -eq 'malformed report') 'Malformed TSDuck report fixture did not fail as malformed.'
}

function Invoke-GitStderrFixture {
    param([Parameter(Mandatory)][string]$Root)
    . (Join-Path $Root 'Beta7Tester.Common.ps1')
    $repo=Join-Path ([IO.Path]::GetTempPath()) ('civiccast-r7-git-' + [guid]::NewGuid().ToString('N'))
    try{
        New-Item -ItemType Directory -Path $repo|Out-Null
        $null=& git -C $repo init --quiet
        if($LASTEXITCODE -ne 0){throw 'Could not create disposable Git fixture.'}
        $null=& git -C $repo config alias.noisy '!echo normal-progress 1>&2'
        if($LASTEXITCODE -ne 0){throw 'Could not configure disposable Git stderr fixture.'}
        $lines=@(Invoke-Beta5Git -Repository $repo -Arguments @('noisy'))
        Assert-Check (@($lines|Where-Object{$_ -match 'normal-progress'}).Count -eq 1) 'Git stderr success output was not captured.'
        $failed=$false
        try{$null=Invoke-Beta5Git -Repository $repo -Arguments @('definitely-not-a-command')}catch{$failed=$true}
        Assert-Check $failed 'Nonzero Git exit did not fail closed.'

        # Reproduce the tester's CRLF working file versus LF Git object. The
        # evidence binding must use the normalized index object, not a raw
        # working-file hash.
        $null=Invoke-Beta5Git -Repository $repo -Arguments @('config','core.autocrlf','true')
        $null=Invoke-Beta5Git -Repository $repo -Arguments @('config','user.name','R7 fixture')
        $null=Invoke-Beta5Git -Repository $repo -Arguments @('config','user.email','r7-fixture@civiccast.invalid')
        $receiptPath=Join-Path $repo 'receipt.json'
        [IO.File]::WriteAllText($receiptPath,"{`r`n  `"status`": `"R5_INVALIDATED`"`r`n}",[Text.UTF8Encoding]::new($false))
        $null=Invoke-Beta5Git -Repository $repo -Arguments @('add','--','receipt.json')
        $indexBlob=(Invoke-Beta5Git -Repository $repo -Arguments @('rev-parse',':receipt.json')|Select-Object -First 1).Trim()
        $rawBlob=(Invoke-Beta5Git -Repository $repo -Arguments @('hash-object','--no-filters',$receiptPath)|Select-Object -First 1).Trim()
        $null=Invoke-Beta5Git -Repository $repo -Arguments @('commit','-m','fixture receipt','--','receipt.json')
        $committedBlob=(Invoke-Beta5Git -Repository $repo -Arguments @('rev-parse','HEAD:receipt.json')|Select-Object -First 1).Trim()
        Assert-Check ($indexBlob -ceq $committedBlob) 'Normalized index receipt blob does not equal the committed receipt blob.'
        Assert-Check ($rawBlob -cne $committedBlob) 'CRLF fixture did not distinguish raw working bytes from normalized Git evidence.'
    }finally{
        if(Test-Path -LiteralPath $repo){
            # Git object files are read-only on Windows. Clear that attribute
            # only inside this disposable fixture before recursive deletion.
            foreach($file in @(Get-ChildItem -LiteralPath $repo -Recurse -Force -File -ErrorAction SilentlyContinue)){$file.IsReadOnly=$false}
            [IO.Directory]::Delete($repo,$true)
        }
    }
}

function Invoke-PowerShellArrayCompatibilityFixtures {
    param([Parameter(Mandatory)][string]$DriverText)

    # Match the real archived plan schema: it intentionally has no notes
    # field. A top-level JSON array must become individual rows under both
    # Windows PowerShell 5.1 and PowerShell 7.
    $planData = '[{"channel_id":"public","schedule_id":"fixture-public","asset_id":"asset-public","asset_label":"Public fixture","scheduled_at":"2026-09-14T04:42:55Z"},{"channel_id":"education","schedule_id":"fixture-education","asset_id":"asset-education","asset_label":"Education fixture","scheduled_at":"2026-09-14T04:47:55Z"}]' | ConvertFrom-Json
    $plan = @($planData | ForEach-Object { $_ })
    Assert-Check ($plan.Count -eq 2) 'Top-level archived-plan JSON did not enumerate to two rows.'
    Assert-Check ((@($plan.schedule_id) -join ',') -ceq 'fixture-public,fixture-education') 'Archived-plan schedule IDs were lost during enumeration.'
    Assert-Check ($plan[0].PSObject.Properties.Name -notcontains 'notes') 'Archived-plan fixture no longer matches the real note-free schema.'

    # Invoke-Station captures Invoke-RestMethod before returning it. This is
    # load-bearing in Windows PowerShell 5.1, where returning the captured
    # array enumerates its rows for collection callers.
    function Invoke-CapturedArrayFixture {
        $response = '[{"id":"public"},{"id":"education"}]' | ConvertFrom-Json
        return $response
    }
    $apiRows = @(Invoke-CapturedArrayFixture)
    Assert-Check ($apiRows.Count -eq 2 -and (@($apiRows.id) -join ',') -ceq 'public,education') 'Captured REST-array return did not enumerate to individual rows.'

    Assert-Check ($DriverText -match '(?s)function\s+Invoke-Station.*?\$response\s*=\s*Invoke-RestMethod\s+@arguments\s*\r?\n\s*return\s+\$response') 'Invoke-Station no longer captures and returns REST arrays compatibly.'
    Assert-Check ($DriverText -match '(?s)\$planData\s*=\s*Get-Content.*?published-plan\.json.*?ConvertFrom-Json\s*\r?\n\s*#.*?\r?\n\s*#.*?\r?\n\s*#.*?\r?\n\s*\$plan\s*=\s*@\(\$planData\s*\|\s*ForEach-Object\s*\{\s*\$_\s*\}\)') 'Existing-run recovery no longer explicitly enumerates top-level plan arrays.'
}

function Invoke-ChildPreflight {
    param([Parameter(Mandatory)][string]$Root)
    $root = (Resolve-Path -LiteralPath $Root).Path
    $expected = @(
        'Assert-Beta7CandidateBinding.ps1',
        'Beta7Tester.Common.ps1',
        'Beta7TransportProbeR7.ps1',
        'Invoke-Beta7TesterUpgrade.ps1',
        'Run-Beta7PhysicalOFF4HJob.ps1',
        'Run-BetaExistingTesterSoakR7.ps1',
        'Start-Beta7PhysicalOFF4HJob.ps1',
        'Test-Beta7HarnessPackage.ps1',
        'Test-Beta7R7Harness.ps1',
        'TSDuckReportClassifierR7.ps1'
    )
    foreach ($name in $expected) {
        Assert-Check (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf) "Required R7 harness test or executable is missing: $name"
    }
    $scripts = @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.ps1')
    Assert-Check ($scripts.Count -ge $expected.Count) 'R7 package does not contain every required PowerShell file.'
    foreach ($script in $scripts) {
        $tokens = $null; $parseErrors = $null
        [void][System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$parseErrors)
        if (@($parseErrors).Count) {
            $details = @($parseErrors | ForEach-Object { "$($_.Extent.StartLineNumber):$($_.Message)" }) -join '; '
            throw "PowerShell parser rejected $($script.Name): $details"
        }
    }
    foreach($liveCallerName in @('Invoke-Beta7TesterUpgrade.ps1','Start-Beta7PhysicalOFF4HJob.ps1')){
        $liveCallerText=Get-Content -LiteralPath (Join-Path $root $liveCallerName) -Raw
        Assert-Check ($liveCallerText -notmatch '(?s)Test-Beta7R7Harness\.ps1.{0,200}-RequireDualRuntime') "Tester-live caller incorrectly requires unavailable pwsh: $liveCallerName"
    }

    $identityPath = Join-Path $root 'run-identity.json'
    Assert-Check (Test-Path -LiteralPath $identityPath -PathType Leaf) 'R7 run identity is missing.'
    $identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
    # The test is not allowed to report PASS for a loose collection of scripts.
    # Prove the exact manifest bytes, every manifest-listed file, and the full
    # candidate/R5/source binding that the live adoption path will enforce.
    $packageProof = & (Join-Path $root 'Test-Beta7HarnessPackage.ps1') -PackageRoot $root -IdentityPath $identityPath
    Assert-Check ($null -ne $packageProof -and "$($packageProof.manifest_sha256)" -ceq "$($identity.expected_harness_manifest_sha256)") 'R7 package proof did not bind the exact manifest hash.'
    $boundIdentity = & (Join-Path $root 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $identityPath
    Assert-Check ($null -ne $boundIdentity -and "$($boundIdentity.mission_nonce)" -ceq 'BETA7-3E117FF1-OFF4H-R7-E6D01E') 'R7 candidate binding proof did not return the exact mission.'
    $offsets = @($identity.transport_round_offsets_seconds | ForEach-Object { [int]$_ })
    Assert-Check (($offsets -join ',') -eq '0,1800,3600,5400,7200,9000,10800,12600') 'R7 identity does not bind exactly eight 30-minute transport offsets.'
    Assert-Check (@($offsets | Where-Object { $_ -lt 0 -or $_ -ge 14400 -or $_ % 1800 -ne 0 }).Count -eq 0) 'R7 transport offsets do not fit the measured four-hour cadence.'

    $transportText = Get-Content -LiteralPath (Join-Path $root 'Beta7TransportProbeR7.ps1') -Raw
    Assert-Check ($transportText -notmatch "(?i)'-P'\s*,\s*'skip'") 'R7 transport probe still invokes the unavailable skip plugin.'
    Assert-Check ($transportText -match [regex]::Escape("@('-P','until','--seconds','30')")) 'R7 transport probe does not bind a 30-second until stage.'
    Assert-Check ($transportText -match [regex]::Escape("@('-P','analyze','--json','--output-file',`$quotedReport,'-O','drop')")) 'R7 transport probe does not bind analyze JSON output and drop.'

    $driver = Join-Path $root 'Run-BetaExistingTesterSoakR7.ps1'
    $driverText = Get-Content -LiteralPath $driver -Raw
    Assert-Check ($driverText -match [regex]::Escape("@('CIVICCAST_CAPTION_TAP','CIVICCAST_CAPTION_TAP_DIR')")) 'R7 caption-environment evidence does not use the product caption-tap variable names.'
    Assert-Check ($driverText -notmatch 'CIVICAST_CAPTION_TAP') 'R7 driver contains the misspelled caption-tap environment prefix.'
    $scheduleCleanupGuard = '(?s)# A schedule POST may commit remotely.*?if\s*\(\s*\$token\s*\)\s*\{\s*try\s*\{\s*\$scheduleCleanup\s*=\s*Remove-RemainingOwnedSchedule\s*;\s*Save-Result\s+\$scheduleCleanup\s+''SCHEDULE-CLEANUP-VERIFIED\.json'''
    Assert-Check ($driverText -match $scheduleCleanupGuard) 'R7 finalizer must invoke exact-notes schedule discovery behind the exact token-only guard, independent of recorded IDs.'
    Invoke-PowerShellArrayCompatibilityFixtures -DriverText $driverText

    # Protect the exact ordering that prevents the old 2.1-second transport
    # false failure: continuous same-PID stability, serialized admission, a
    # real programme-change topology proof, remote phase receipt, then timing.
    Assert-ContainsInOrder -Text $driverText -Needles @(
        '$stableUntil=[datetime]::UtcNow.AddSeconds(30)',
        'if($stableState.state -ne ''ON_AIR'' -or [int]$stableState.pid -ne [int]$phasePids[$stableChannel.id])',
        '"$phase/STABILIZED.json"',
        'if ($RequireTransportAdmission) {',
        'Start-Beta7TransportProbe -TspExe',
        'if ($admissionResult.verdict -ne ''PASS'')',
        '$premeasurementTopology=Invoke-PremeasurementTopologyProof',
        '$offsets=Get-LogOffsets',
        '$begin = [datetime]::UtcNow.AddSeconds(60)',
        '$end = $begin.AddMinutes($Minutes)',
        '$receipt=@(& $OnPhaseStarted $phase $begin $end)',
        'if($receipt.Count -ne 1',
        '[string]$receipt[0].status -cne ''PHASE_READY_AND_REMOTELY_VERIFIED''',
        '[string]$receipt[0].candidate_source_sha -cne $SourceSha',
        '[string]$receipt[0].remote_commit -notmatch ''^[0-9a-f]{40}$''',
        'while ([datetime]::UtcNow -lt $begin)',
        '"$phase/SOAK-START.json"'
    ) -Message 'R7 startup, admission, topology proof, receipt, and measured-clock order is not exact.'
    Assert-ContainsInOrder -Text $driverText -Needles @(
        'function Invoke-PremeasurementTopologyProof',
        '$transitionOffsets=Get-LogOffsets',
        '$targets=@($Plan | Where-Object { ([datetimeoffset]::Parse([string]$_.scheduled_at).UtcDateTime) -gt $now }',
        'if($targets.Count -ne $channels.Count)',
        '$captureAt=$target.AddSeconds(90)',
        'if($profile.live_captions_enabled -ne $false)',
        '$grade=Get-Beta7FailureGrades $logs $ExpectedElements',
        '$badTopology=@($commits | Where-Object {[int]$_ -ne 146})',
        'expected at least one complete elements=146 transaction.',
        'if(-not $grade.f1_pass -or -not $grade.f3_pass)'
    ) -Message 'R7 premeasurement proof no longer requires a future controlled transition with complete elements=146 transaction evidence.'

    $upgradeText = Get-Content -LiteralPath (Join-Path $root 'Invoke-Beta7TesterUpgrade.ps1') -Raw
    Assert-Check ($upgradeText -match '(?s)\$localBlob\s*=\s*\(Invoke-Beta5Git.{0,300}''rev-parse''.{0,100}:\$relativeInvalidation') 'R7 adoption does not compare the normalized local invalidation index blob.'
    Assert-Check ($upgradeText -notmatch '(?s)\$localBlob\s*=.{0,300}''hash-object''.{0,100}''--no-filters''') 'R7 adoption still compares raw CRLF invalidation bytes with a normalized remote blob.'
    $selfTestRoot = Join-Path ([IO.Path]::GetTempPath()) ('civiccast-r7-harness-' + [guid]::NewGuid().ToString('N'))
    # -SelfTest returns before station/token/network access. Its disposable
    # output is outside the package and contains only synthetic test evidence.
    & $driver -BaseUrl 'http://127.0.0.1:1' -OutputRoot $selfTestRoot -SourceSha '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d' -SelfTest | Out-Null
    Invoke-TransportFixtures -Root $root
    Invoke-GitStderrFixture -Root $root

    $jobText = Get-Content -LiteralPath (Join-Path $root 'Run-Beta7PhysicalOFF4HJob.ps1') -Raw
    $jobTokens=$null;$jobErrors=$null
    $jobAst=[System.Management.Automation.Language.Parser]::ParseInput($jobText,[ref]$jobTokens,[ref]$jobErrors)
    Assert-Check (@($jobErrors).Count -eq 0) 'R7 job could not be parsed for its actual terminal-state function.'
    $phaseAssignments=@($jobAst.FindAll({param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -ceq '$phaseReceipt'
    },$true))
    Assert-Check ($phaseAssignments.Count -eq 1) 'R7 job must define exactly one physical phase receipt callback.'
    $phaseCallback=& ([scriptblock]::Create($phaseAssignments[0].Right.Extent.Text))
    $report=[ordered]@{}
    $id=[pscustomobject]@{candidate_source_sha='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'}
    $jobRelative='soak/r7/job.json'
    $fixtureCommit=('a' * 40)
    $fixtureRemote=$fixtureCommit
    function Write-Job {}
    function Sync-And-Push { return $fixtureCommit }
    function Assert-RemoteBlobs { return $fixtureRemote }
    $fixtureBegin=[datetime]'2026-09-14T06:00:00Z'
    $fixtureEnd=$fixtureBegin.AddMinutes(240)
    $phaseAck=@(& $phaseCallback 'OFF' $fixtureBegin $fixtureEnd)
    Assert-Check ($phaseAck.Count -eq 1 -and
        [string]$phaseAck[0].status -ceq 'PHASE_READY_AND_REMOTELY_VERIFIED' -and
        [string]$phaseAck[0].candidate_source_sha -ceq [string]$id.candidate_source_sha -and
        [string]$phaseAck[0].phase -ceq 'OFF' -and
        [string]$phaseAck[0].begin_utc -ceq $fixtureBegin.ToString('o') -and
        [string]$phaseAck[0].end_utc -ceq $fixtureEnd.ToString('o') -and
        [string]$phaseAck[0].remote_commit -ceq $fixtureCommit
    ) 'Actual R7 physical phase callback did not return one exact verified acknowledgement.'
    $fixtureRemote=('b' * 40)
    $mismatchRejected=$false
    try{$null=& $phaseCallback 'OFF' $fixtureBegin $fixtureEnd}catch{$mismatchRejected=$true}
    Assert-Check $mismatchRejected 'Actual R7 physical phase callback accepted a remote commit mismatch.'

    $stateFunction=@($jobAst.FindAll({param($node)$node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-AuthoritativeState'},$true))
    Assert-Check ($stateFunction.Count -eq 1) 'R7 job must define exactly one Get-AuthoritativeState function.'
    . ([scriptblock]::Create($stateFunction[0].Extent.Text))
    Assert-Check ((Get-AuthoritativeState $false $false $false $false $false $false) -eq 'FAIL') 'Actual R7 state function accepted failed collection/cleanup.'
    Assert-Check ((Get-AuthoritativeState $true $true $true $false $false $false) -eq 'EVIDENCE_PUBLISH_FAIL') 'Actual R7 state function accepted missing evidence publication.'
    Assert-Check ((Get-AuthoritativeState $true $true $true $true $true $false) -eq 'EVIDENCE_PUBLISH_FAIL') 'Actual R7 state function accepted missing completion publication.'
    Assert-Check ((Get-AuthoritativeState $true $true $true $true $true $true) -eq 'PASS') 'Actual R7 state function rejected the complete authoritative path.'
    Assert-ContainsInOrder -Text $jobText -Needles @(
        "`$report.started_commit=Sync-And-Push @(`$jobRelative)",
        '$report.started_verified_commit=Assert-RemoteBlobs @($jobRelative)',
        "throw 'Initial STARTED receipt was not verified at its pushed commit.'",
        "(Join-Path `$missionRoot 'START-VERIFIED.json')",
        '$phaseReceipt='
    ) -Message 'R7 job can signal startup before the remote STARTED blob is verified.'
    Assert-ContainsInOrder -Text $jobText -Needles @(
        '$phaseReceipt={',
        'Write-Job',
        '$report.phase_commit=Sync-And-Push @($jobRelative)',
        '$report.phase_verified_commit=Assert-RemoteBlobs @($jobRelative)',
        'if([string]$report.phase_verified_commit -cne [string]$report.phase_commit)',
        'return [pscustomobject]@{status=''PHASE_READY_AND_REMOTELY_VERIFIED'''
    ) -Message 'R7 physical phase callback does not return an exact remotely verified acknowledgement.'
    Assert-ContainsInOrder -Text $jobText -Needles @(
        "STOP-VERIFIED.json",
        "STOP-FAILED.json",
        "SCHEDULE-CLEANUP-VERIFIED.json",
        "SCHEDULE-CLEANUP-FAILED.json",
        "throw 'R7 terminal channel and owned-schedule cleanup is not verified.'"
    ) -Message 'R7 job does not fail closed on terminal channel and schedule cleanup.'
    Assert-ContainsInOrder -Text $jobText -Needles @(
        "`$report.job_state='COLLECTION_PASS_PENDING_EVIDENCE'",
        'Build-EvidenceArchive',
        '$report.evidence_verified_commit=Assert-RemoteBlobs',
        "`$report.job_state='PASS'",
        '$report.completion_commit=Sync-And-Push',
        '$report.completion_verified_commit=Assert-RemoteBlobs',
        "`$completionPushed=`$true",
        '$report.job_state=Get-AuthoritativeState'
    ) -Message 'R7 job can mark authoritative PASS before verified evidence and completion publication.'
    Assert-Check ($jobText -match [regex]::Escape("'EVIDENCE_PUBLISH_FAIL'")) 'R7 job lacks an evidence-publication failure state.'
    Assert-Check ($jobText -match [regex]::Escape("if(`$report.job_state -ne 'PASS'){throw")) 'R7 job can return success for a non-PASS job state.'
    Assert-Check ($jobText -match '(?i)completion(?:_relative|Path|\.json)') 'R7 job lacks a separate completion receipt path.'
    Assert-Check ($jobText -match '(?i)verified_evidence_commit') 'R7 completion receipt does not reference verified evidence.'
    Assert-Check ($jobText -match '(?i)evidence_sha256') 'R7 completion receipt does not bind evidence bytes.'

    $jobPass = [pscustomobject]@{ job_state = 'PASS'; evidence_relative_path = 'soak/r7/evidence.zip' }
    $receiptPass = [pscustomobject]@{ status = 'PASS'; verified_evidence_commit = 'abc123'; evidence_sha256 = ('a' * 64); evidence_relative_path = 'soak/r7/evidence.zip' }
    Assert-Check (Test-AuthoritativePassState $jobPass $receiptPass) 'Authoritative completion fixture did not pass.'
    foreach ($fault in @(
        [pscustomobject]@{ job_state = 'FAIL'; evidence_relative_path = 'soak/r7/evidence.zip' },
        [pscustomobject]@{ job_state = 'EVIDENCE_PUBLISH_FAIL'; evidence_relative_path = 'soak/r7/evidence.zip' },
        [pscustomobject]@{ job_state = 'PASS'; evidence_relative_path = 'soak/r7/evidence.zip' }
    )) {
        $receipt = if ($fault.job_state -eq 'PASS') { [pscustomobject]@{ status = 'FAIL'; verified_evidence_commit = $null; evidence_sha256 = $null; evidence_relative_path = 'soak/r7/evidence.zip' } } else { $receiptPass }
        Assert-Check (-not (Test-AuthoritativePassState $fault $receipt)) "Fault state $($fault.job_state) could produce authoritative PASS."
    }
    [pscustomobject]@{ runtime = $PSVersionTable.PSEdition; version = $PSVersionTable.PSVersion.ToString(); parsed_scripts = @($scripts.Name | Sort-Object); verdict = 'PASS' }
}

$resolvedRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
if ($Child) {
    $result = Invoke-ChildPreflight -Root $resolvedRoot
    $result | ConvertTo-Json -Depth 6 -Compress
    return
}

if ($RequireDualRuntime) {
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
    foreach ($psHostExe in @($windowsPowerShell, $pwsh)) {
        Assert-Check (Test-Path -LiteralPath $psHostExe -PathType Leaf) "Required PowerShell host is absent: $psHostExe"
        & $psHostExe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -PackageRoot $resolvedRoot -Child
        if ($LASTEXITCODE -ne 0) { throw "R7 harness child preflight failed in $psHostExe with exit code $LASTEXITCODE." }
    }
    Write-Output 'R7 harness preflight PASS in Windows PowerShell 5.1 and pwsh 7.'
    return
}

$result = Invoke-ChildPreflight -Root $resolvedRoot
$result | ConvertTo-Json -Depth 6 -Compress
Write-Output "R7 harness preflight PASS in current runtime $($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)."
