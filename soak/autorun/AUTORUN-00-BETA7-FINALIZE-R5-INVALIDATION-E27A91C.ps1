# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Publish the R5 invalidation only after read-only recovery verification.
[CmdletBinding()]
param([switch]$DryRun)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$expectedHost = 'DESKTOP-VBMA6O5'
$candidateSourceSha = '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$taskName = 'CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91'
$missionNonce = 'BETA7-3E117FF1-OFF4H-R5-E27A91'
$missionRoot = 'C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r5-e27a91'
$outputName = 'physical-soak-off4h-r5-e27a91'
$returnRepo = 'C:\CivicCastSoak\repo'
$directiveRepo = 'C:\CivicCastSoak\directives'
$directiveBranch = 'soak8-e1acfe6-directives'
$returnRepositoryUrl = 'https://github.com/scottconverse/civiccast-native.git'
$returnBranch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$relativeRoot = 'soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91'
$relativeJob = "$relativeRoot/job.json"
$relativeReceipt = "$relativeRoot/INVALIDATED.json"
$directiveRelative = 'soak/DIRECTIVE-BETA7-FINALIZE-R5-INVALIDATION-E27A91C.md'
$scriptRelative = 'soak/autorun/AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91C.ps1'
$baseUrl = 'http://127.0.0.1:8000'
$tokenPath = 'C:\CivicCastSoak\state\token'
$previousDoneMarker = 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-INVALIDATE-R5-E27A91.ps1.done'
$failedFinalizerDoneMarker = 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91.ps1.done'
$failedFinalizerBDoneMarker = 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91B.ps1.done'
$ownedChannels = @('public', 'education', 'government')
$invalidReasons = @(
    'stale auto-start race',
    'non-stall worker exit false pass',
    'final sample gap',
    'cleanup false pass',
    'evidence publication false pass',
    'embargo overlap false fail',
    'unbound harness and topology provenance',
    'impossible transport cadence'
)

function Get-StringSha256([string]$Value) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

function Get-FileProof([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required R5 file is absent: $Path" }
    $item = Get-Item -LiteralPath $Path
    [pscustomobject][ordered]@{
        path = $Path
        size_bytes = [int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

function ConvertTo-NativeArgument([string]$Value) {
    if ($null -eq $Value) { throw 'Native arguments cannot be null.' }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = New-Object Text.StringBuilder
    $null = $builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes++
            continue
        }
        if ($character -eq '"') {
            if ($backslashes) { $null = $builder.Append('\', 2 * $backslashes) }
            $null = $builder.Append('\"')
            $backslashes = 0
            continue
        }
        if ($backslashes) {
            $null = $builder.Append('\', $backslashes)
            $backslashes = 0
        }
        $null = $builder.Append($character)
    }
    if ($backslashes) { $null = $builder.Append('\', 2 * $backslashes) }
    $null = $builder.Append('"')
    $builder.ToString()
}

function Invoke-NativeGit {
    param(
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Arguments,
        [int]$TimeoutSeconds = 120,
        [int[]]$SuccessExitCodes = @(0)
    )
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        throw "Git working directory is absent: $WorkingDirectory"
    }
    $gitCommand = Get-Command git.exe -ErrorAction Stop
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $gitCommand.Source
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.Arguments = (($Arguments | ForEach-Object { ConvertTo-NativeArgument ([string]$_) }) -join ' ')
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw 'Could not start git.exe.' }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            try { $process.Kill() } catch { }
            throw "git $($Arguments[0]) exceeded its $TimeoutSeconds-second bound."
        }
        $process.WaitForExit()
        $stdout = [string]$stdoutTask.Result
        $stderr = [string]$stderrTask.Result
        $exitCode = [int]$process.ExitCode
        if ($exitCode -notin $SuccessExitCodes) {
            $detail = (($stderr, $stdout | Where-Object { $_ }) -join "`n").Trim()
            if ($detail.Length -gt 4000) { $detail = $detail.Substring(0, 4000) }
            throw "git $($Arguments[0]) failed with exit $exitCode. $detail"
        }
        [pscustomobject]@{ exit_code = $exitCode; stdout = $stdout; stderr = $stderr }
    }
    finally { $process.Dispose() }
}

function Get-GitText([string]$WorkingDirectory, [string[]]$Arguments, [int]$TimeoutSeconds = 120) {
    (Invoke-NativeGit -WorkingDirectory $WorkingDirectory -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds).stdout.Trim()
}

function Write-Utf8JsonAtomic($Value, [string]$Path, [int]$Depth = 30) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temporary = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth $Depth), [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Set-JsonProperty($Object, [string]$Name, $Value) {
    if ($Object.PSObject.Properties[$Name]) { $Object.$Name = $Value }
    else { $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value }
}

function Invoke-StationReadOnly([string]$Path, [string]$Token) {
    $arguments = @{
        Method = 'GET'
        Uri = $baseUrl.TrimEnd('/') + $Path
        TimeoutSec = 30
        ErrorAction = 'Stop'
        Headers = @{ Authorization = 'Bearer ' + $Token }
    }
    Invoke-RestMethod @arguments
}

function Get-DirectiveBinding {
    $resolvedRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    if (-not $resolvedRoot.Equals($directiveRepo, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recovery order must run from the tester directive checkout $directiveRepo."
    }
    $branch = Get-GitText $resolvedRoot @('rev-parse', '--abbrev-ref', 'HEAD')
    if ($branch -cne $directiveBranch) { throw "Tester directive checkout is on $branch, not $directiveBranch." }
    $origin = Get-GitText $resolvedRoot @('remote', 'get-url', 'origin')
    if ($origin.TrimEnd('/') -cne $returnRepositoryUrl -and $origin.TrimEnd('/') -cne "$returnRepositoryUrl.git") {
        throw "Tester checkout origin is not $returnRepositoryUrl."
    }
    foreach ($path in @($scriptRelative, $directiveRelative)) {
        $null = Invoke-NativeGit -WorkingDirectory $resolvedRoot -Arguments @('ls-files', '--error-unmatch', '--', $path)
    }
    $status = Get-GitText $resolvedRoot @('status', '--porcelain=v1', '--', $scriptRelative, $directiveRelative)
    if ($status) { throw 'Recovery order or directive differs from the committed HEAD bytes.' }
    [pscustomobject][ordered]@{
        repository = $returnRepositoryUrl
        directive_branch = $directiveBranch
        directive_commit = Get-GitText $resolvedRoot @('rev-parse', 'HEAD')
        script = Get-FileProof $PSCommandPath
        directive = Get-FileProof (Join-Path $resolvedRoot ($directiveRelative -replace '/', '\'))
    }
}

function Get-R5LocalVerification {
    $installedIdentityPath = Join-Path $missionRoot 'bin\run-identity.json'
    $localJobPath = Join-Path $missionRoot "$outputName-job.json"
    $outputRoot = Join-Path $missionRoot $outputName
    $installedIdentity = Get-Content -LiteralPath $installedIdentityPath -Raw | ConvertFrom-Json
    foreach ($field in @('candidate_source_sha', 'build_source_sha', 'gate_a_source_sha', 'native_app_payload_source_sha')) {
        if ([string]$installedIdentity.$field -cne $candidateSourceSha) { throw "Installed R5 identity field $field is not the exact candidate." }
    }
    $installedPhaseNames = @($installedIdentity.expected_elements_per_phase.PSObject.Properties.Name | Sort-Object)
    if ([string]$installedIdentity.mission_nonce -cne $missionNonce -or
        [string]$installedIdentity.task_name -cne $taskName -or
        [string]$installedIdentity.return_branch -cne $returnBranch -or
        [string]$installedIdentity.evidence_relative_root -cne $relativeRoot -or
        [int]$installedIdentity.minutes_per_phase -ne 240 -or
        ($installedPhaseNames -join ',') -cne 'OFF') {
        throw 'Installed R5 identity does not match the exact mission contract.'
    }
    $localJob = Get-Content -LiteralPath $localJobPath -Raw | ConvertFrom-Json
    if ([string]$localJob.source_sha -cne $candidateSourceSha -or
        [string]$localJob.mission_nonce -cne $missionNonce -or
        [string]$localJob.job_state -cne 'FAIL') {
        throw 'Local R5 job receipt is not the exact failed candidate mission.'
    }
    if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) { throw 'R5 physical output root is absent.' }
    $runs = @(Get-ChildItem -LiteralPath $outputRoot -Directory)
    if ($runs.Count -ne 1) { throw "R5 physical output must contain exactly one run directory; observed $($runs.Count)." }
    $runIdentityPath = Join-Path $runs[0].FullName 'IDENTITY.json'
    $planPath = Join-Path $runs[0].FullName 'published-plan.json'
    $runVerdictPath = Join-Path $runs[0].FullName 'VERDICT.json'
    $profilePath = Join-Path $runs[0].FullName 'OFF\profile.json'
    $stopVerifiedPath = Join-Path $runs[0].FullName 'STOP-VERIFIED.json'
    $stopFailedPath = Join-Path $runs[0].FullName 'STOP-FAILED.json'
    $runIdentity = Get-Content -LiteralPath $runIdentityPath -Raw | ConvertFrom-Json
    if (-not [string]$runIdentity.run_id -or
        [string]$runIdentity.source_sha -cne $candidateSourceSha -or
        [int]$runIdentity.minutes_per_phase -ne 240 -or
        (@($runIdentity.phases) -join ',') -cne 'OFF') {
        throw 'R5 run identity does not match the exact source, duration, and captions-OFF phase.'
    }
    if (Test-Path -LiteralPath $stopFailedPath -PathType Leaf) { throw 'R5 output contains STOP-FAILED.json.' }
    $runVerdict = Get-Content -LiteralPath $runVerdictPath -Raw | ConvertFrom-Json
    if ([string]$runVerdict.verdict -cne 'FAIL') { throw 'R5 run verdict is not FAIL.' }
    $profile = Get-Content -LiteralPath $profilePath -Raw | ConvertFrom-Json
    if ([bool]$profile.captions_enabled) { throw 'R5 run profile is not captions OFF.' }
    # Windows PowerShell 5.1 preserves a top-level JSON array as one Object[]
    # pipeline item.  Explicitly enumerate it so each plan row is validated.
    $planData = Get-Content -LiteralPath $planPath -Raw | ConvertFrom-Json
    $plan = @($planData | ForEach-Object { $_ })
    if (-not $plan.Count) { throw 'R5 published plan is empty.' }
    $planIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($entry in $plan) {
        if (-not [string]$entry.schedule_id -or -not $planIds.Add([string]$entry.schedule_id)) {
            throw 'R5 published plan contains a missing or duplicate schedule ID.'
        }
        if ([string]$entry.channel_id -notin $ownedChannels) { throw 'R5 published plan contains an unowned channel.' }
    }
    [pscustomobject][ordered]@{
        previous_invalidation_done_marker = Get-FileProof $previousDoneMarker
        failed_receipt_finalizer_done_marker = Get-FileProof $failedFinalizerDoneMarker
        failed_receipt_finalizer_b_done_marker = Get-FileProof $failedFinalizerBDoneMarker
        installed_identity = Get-FileProof $installedIdentityPath
        local_job = Get-FileProof $localJobPath
        run_identity = Get-FileProof $runIdentityPath
        published_plan = Get-FileProof $planPath
        run_verdict = Get-FileProof $runVerdictPath
        captions_off_profile = Get-FileProof $profilePath
        stop_verified = Get-FileProof $stopVerifiedPath
        stop_failed_absent = $true
        run_directory = $runs[0].Name
        run_id = [string]$runIdentity.run_id
        expected_notes = "Owned $([string]$runIdentity.run_id)"
        schedule_id_count = $planIds.Count
        schedule_ids = @($planIds | Sort-Object)
    }
}

function Get-R5TesterVerification($LocalVerification) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task -or [string]$task.State -cne 'Disabled') { throw "Exact R5 task is not present in Disabled state: $taskName" }
    $matchingProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $commandLine = [string]$_.CommandLine
        $commandLine -and
        $commandLine.IndexOf($missionRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
        ($commandLine.IndexOf($outputName, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
         $commandLine.IndexOf($taskName, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($matchingProcesses.Count) { throw "Exact R5 job process is still present: $($matchingProcesses.ProcessId -join ',')." }
    if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) { throw "Tester token is absent: $tokenPath" }
    $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
    if (-not $token) { throw 'Tester token is empty.' }
    $planIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($scheduleId in @($LocalVerification.schedule_ids)) { $null = $planIds.Add([string]$scheduleId) }
    $configs = [Collections.Generic.List[object]]::new()
    $states = [Collections.Generic.List[object]]::new()
    $scheduleChecks = [Collections.Generic.List[object]]::new()
    foreach ($channel in $ownedChannels) {
        $config = Invoke-StationReadOnly "/api/staff/egress/channels/$channel/config" $token
        if ([bool]$config.enabled -ne $true -or [bool]$config.auto_start -ne $false) {
            throw "R5 recovery config is not enabled=true, auto_start=false for $channel."
        }
        $configJson = $config | ConvertTo-Json -Depth 20 -Compress
        $configs.Add([pscustomobject][ordered]@{
            channel_id = $channel
            enabled = [bool]$config.enabled
            auto_start = [bool]$config.auto_start
            full_config_sha256 = Get-StringSha256 $configJson
        })
        $state = Invoke-StationReadOnly "/api/staff/egress/channels/$channel/state" $token
        if ([string]$state.state -cne 'STOPPED' -or $null -ne $state.pid) {
            throw "R5 recovery state is not STOPPED with no PID for $channel."
        }
        $states.Add([pscustomobject][ordered]@{
            channel_id = $channel
            state = [string]$state.state
            pid = $null
            updated_at = [string]$state.updated_at
        })
        $rows = @(Invoke-StationReadOnly "/api/staff/schedule?channel_id=$channel" $token)
        $liveRows = @($rows | Where-Object { [string]$_.state -in @('scheduled', 'published') })
        $matching = @($liveRows | Where-Object {
            ([string]$_.notes -ceq [string]$LocalVerification.expected_notes) -or
            ($_.id -and $planIds.Contains([string]$_.id))
        })
        if ($matching.Count) {
            throw "R5 still has live scheduled/published rows for ${channel}: $($matching.id -join ',')."
        }
        $scheduleChecks.Add([pscustomobject][ordered]@{
            channel_id = $channel
            live_scheduled_or_published_rows_checked = $liveRows.Count
            exact_r5_notes = [string]$LocalVerification.expected_notes
            exact_r5_schedule_ids_checked = $planIds.Count
            exact_r5_live_matches = @()
        })
    }
    [pscustomobject][ordered]@{
        task = [pscustomobject][ordered]@{ name = $taskName; present = $true; state = [string]$task.State }
        process_match = [pscustomobject][ordered]@{
            mission_root = $missionRoot
            output_name = $outputName
            task_name = $taskName
            matching_process_ids = @()
        }
        channel_configs = @($configs)
        channel_states = @($states)
        schedule = @($scheduleChecks)
        mutation_performed = $false
    }
}

function Reset-AuthorizedPublicationTargets {
    $statusText = Get-GitText $returnRepo @('status', '--porcelain=v1', '--untracked-files=all')
    $allowed = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $null = $allowed.Add($relativeJob)
    $null = $allowed.Add($relativeReceipt)
    foreach ($line in @($statusText -split "`r?`n" | Where-Object { $_ })) {
        if ($line.Length -lt 4) { throw "Unparseable tester Git status row: $line" }
        $path = $line.Substring(3).Trim('"') -replace '\\', '/'
        if (-not $allowed.Contains($path)) { throw "Tester return checkout has an unrelated change: $path" }
    }
    $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('reset', '--quiet', 'HEAD', '--', $relativeJob, $relativeReceipt)
    foreach ($path in @($relativeJob, $relativeReceipt)) {
        $headPath = "HEAD`:$path"
        $present = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('cat-file', '-e', $headPath) -SuccessExitCodes @(0, 1, 128)
        $fullPath = Join-Path $returnRepo ($path -replace '/', '\')
        if ($present.exit_code -eq 0) {
            $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('checkout', '--', $path)
        }
        elseif (Test-Path -LiteralPath $fullPath -PathType Leaf) {
            Remove-Item -LiteralPath $fullPath -Force
        }
    }
    $remaining = Get-GitText $returnRepo @('status', '--porcelain=v1', '--untracked-files=all')
    if ($remaining) { throw 'Tester return checkout was not clean after resetting only the authorized publication targets.' }
}

function Invoke-BoundedPull {
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('pull', '--rebase', 'origin', $returnBranch) -TimeoutSeconds 120
            return
        }
        catch {
            $lastError = $_.Exception.Message
            if ($attempt -lt 3) { Start-Sleep -Seconds (2 * $attempt) }
        }
    }
    throw "Could not synchronize tester evidence after three bounded attempts: $lastError"
}

function Invoke-BoundedPush {
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            if ($attempt -gt 1) { Invoke-BoundedPull }
            $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('push', 'origin', $returnBranch) -TimeoutSeconds 120
            return
        }
        catch {
            $lastError = $_.Exception.Message
            if ($attempt -lt 3) { Start-Sleep -Seconds (2 * $attempt) }
        }
    }
    throw "Could not push tester invalidation after three bounded attempts: $lastError"
}

function Publish-R5Invalidation($Verification, $DirectiveBinding) {
    if (-not (Test-Path -LiteralPath (Join-Path $returnRepo '.git') -PathType Container)) {
        throw 'Tester evidence repository is absent.'
    }
    $branch = Get-GitText $returnRepo @('rev-parse', '--abbrev-ref', 'HEAD')
    if ($branch -cne $returnBranch) { throw "Tester evidence checkout is on $branch, not $returnBranch." }
    $returnOrigin = Get-GitText $returnRepo @('remote', 'get-url', 'origin')
    if ($returnOrigin.TrimEnd('/') -cne $returnRepositoryUrl -and $returnOrigin.TrimEnd('/') -cne "$returnRepositoryUrl.git") { throw "Tester evidence checkout origin is not $returnRepositoryUrl." }
    Reset-AuthorizedPublicationTargets
    Invoke-BoundedPull
    $verifiedUtc = [datetime]::UtcNow.ToString('o')
    $verificationPayload = [pscustomobject][ordered]@{
        verified_utc = $verifiedUtc
        directive = $DirectiveBinding
        local_r5 = $Verification.local_r5
        tester = $Verification.tester
    }
    $verificationJson = $verificationPayload | ConvertTo-Json -Depth 40 -Compress
    $receipt = [pscustomobject][ordered]@{
        schema = 'civiccast-beta7-test-invalidation-v2'
        status = 'R5_INVALIDATED'
        recovery_order = 'BETA7-FINALIZE-R5-INVALIDATION-E27A91C'
        hostname = [string]$env:COMPUTERNAME
        mission_nonce = $missionNonce
        candidate_source_sha = $candidateSourceSha
        task_state = [string]$Verification.tester.task.state
        terminal_cleanup_verified = $true
        schedule_cleanup_verified = $true
        invalid_reasons = $invalidReasons
        verification_payload_sha256 = Get-StringSha256 $verificationJson
        verification = $verificationPayload
        publication = [pscustomobject][ordered]@{
            repository = $returnRepositoryUrl
            branch = $returnBranch
            job_path = $relativeJob
            receipt_path = $relativeReceipt
        }
    }
    $receiptPath = Join-Path $returnRepo ($relativeReceipt -replace '/', '\')
    $jobPath = Join-Path $returnRepo ($relativeJob -replace '/', '\')
    Write-Utf8JsonAtomic $receipt $receiptPath 40
    $receiptSha256 = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if (Test-Path -LiteralPath $jobPath -PathType Leaf) {
        $job = Get-Content -LiteralPath $jobPath -Raw | ConvertFrom-Json
        if ([string]$job.source_sha -cne $candidateSourceSha -or [string]$job.mission_nonce -cne $missionNonce) {
            throw 'Existing remote-path R5 job does not belong to the exact candidate mission.'
        }
    }
    else {
        $job = [pscustomobject][ordered]@{
            hostname = [string]$env:COMPUTERNAME
            source_sha = $candidateSourceSha
            mission_nonce = $missionNonce
            job_started_utc = $null
        }
    }
    Set-JsonProperty $job 'job_state' 'INVALIDATED'
    Set-JsonProperty $job 'result' $null
    Set-JsonProperty $job 'error' 'R5 acceptance harness invalidated; this run is not release evidence.'
    Set-JsonProperty $job 'finished_utc' $verifiedUtc
    Set-JsonProperty $job 'invalidation_receipt' 'INVALIDATED.json'
    Set-JsonProperty $job 'invalidation_receipt_sha256' $receiptSha256
    Set-JsonProperty $job 'invalidation_verification_sha256' ([string]$receipt.verification_payload_sha256)
    Set-JsonProperty $job 'invalidation_directive_commit' ([string]$DirectiveBinding.directive_commit)
    Set-JsonProperty $job 'invalidation_recovery_order' ([string]$receipt.recovery_order)
    Write-Utf8JsonAtomic $job $jobPath 30
    $jobSha256 = (Get-FileHash -LiteralPath $jobPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('add', '-f', '--', $relativeReceipt, $relativeJob)
    $stagedReceiptBlob = Get-GitText $returnRepo @('rev-parse', ":$relativeReceipt")
    $stagedJobBlob = Get-GitText $returnRepo @('rev-parse', ":$relativeJob")
    $userName = Get-GitText $returnRepo @('config', '--get', 'user.name')
    $userEmail = Get-GitText $returnRepo @('config', '--get', 'user.email')
    if (-not $userName -or -not $userEmail) { throw 'Tester Git identity is incomplete.' }
    $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @(
        'commit', '--only', '-s', '-m', 'test:finalize-beta7-r5-invalidation-e27a91', '--', $relativeReceipt, $relativeJob
    ) -TimeoutSeconds 120
    Invoke-BoundedPush
    $null = Invoke-NativeGit -WorkingDirectory $returnRepo -Arguments @('fetch', 'origin', $returnBranch) -TimeoutSeconds 120
    $remoteCommit = Get-GitText $returnRepo @('rev-parse', "origin/$returnBranch")
    $remoteReceiptBlob = Get-GitText $returnRepo @('rev-parse', "$remoteCommit`:$relativeReceipt")
    $remoteJobBlob = Get-GitText $returnRepo @('rev-parse', "$remoteCommit`:$relativeJob")
    if ($remoteReceiptBlob -cne $stagedReceiptBlob -or $remoteJobBlob -cne $stagedJobBlob) {
        throw 'Remote invalidation blobs do not match the exact staged local receipt and job blobs.'
    }
    $remoteJob = (Get-GitText $returnRepo @('show', "$remoteCommit`:$relativeJob")) | ConvertFrom-Json
    $remoteReceipt = (Get-GitText $returnRepo @('show', "$remoteCommit`:$relativeReceipt")) | ConvertFrom-Json
    if ([string]$remoteJob.job_state -cne 'INVALIDATED' -or
        [string]$remoteJob.source_sha -cne $candidateSourceSha -or
        [string]$remoteJob.mission_nonce -cne $missionNonce -or
        [string]$remoteJob.invalidation_receipt_sha256 -cne $receiptSha256 -or
        [string]$remoteReceipt.status -cne 'R5_INVALIDATED' -or
        [string]$remoteReceipt.mission_nonce -cne $missionNonce -or
        [string]$remoteReceipt.candidate_source_sha -cne $candidateSourceSha) {
        throw 'Remote invalidation content failed its terminal semantic check.'
    }
    [pscustomobject][ordered]@{
        status = 'R5_INVALIDATION_PUBLISHED_AND_VERIFIED'
        mission_nonce = $missionNonce
        candidate_source_sha = $candidateSourceSha
        invalidation_receipt_sha256 = $receiptSha256
        invalidated_job_sha256 = $jobSha256
        staged_receipt_blob = $stagedReceiptBlob
        staged_job_blob = $stagedJobBlob
        remote_receipt_blob = $remoteReceiptBlob
        remote_job_blob = $remoteJobBlob
        remote_commit = $remoteCommit
        directive_commit = [string]$DirectiveBinding.directive_commit
        verified_utc = [datetime]::UtcNow.ToString('o')
    }
}

function Assert-DryRunContract {
    if ($expectedHost -cne 'DESKTOP-VBMA6O5' -or
        $candidateSourceSha -cne '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d' -or
        $missionNonce -cne 'BETA7-3E117FF1-OFF4H-R5-E27A91' -or
        $taskName -cne 'CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91' -or
        $returnBranch -cne 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5' -or
        $directiveRepo -cne 'C:\CivicCastSoak\directives' -or
        $directiveBranch -cne 'soak8-e1acfe6-directives' -or
        $previousDoneMarker -cne 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-INVALIDATE-R5-E27A91.ps1.done' -or
        $failedFinalizerDoneMarker -cne 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91.ps1.done' -or
        $failedFinalizerBDoneMarker -cne 'C:\CivicCastSoak\state\autorun-done\AUTORUN-00-BETA7-FINALIZE-R5-INVALIDATION-E27A91B.ps1.done' -or
        ($ownedChannels -join ',') -cne 'public,education,government') {
        throw 'Recovery order constants are not the exact R5 tester identity.'
    }
    if ($relativeJob -cne "$relativeRoot/job.json" -or $relativeReceipt -cne "$relativeRoot/INVALIDATED.json") {
        throw 'Recovery publication paths are inconsistent.'
    }
    # Match the actual archived R5 plan schema. Ownership notes were sent to
    # the API but were not copied into published-plan.json; live ownership is
    # checked later from the schedule response using the derived run note and
    # these preserved schedule IDs.
    $planFixtureData = '[{"channel_id":"public","schedule_id":"fixture-public","asset_id":"asset-public","asset_label":"Public fixture","scheduled_at":"2026-09-14T04:42:55Z"},{"channel_id":"education","schedule_id":"fixture-education","asset_id":"asset-education","asset_label":"Education fixture","scheduled_at":"2026-09-14T04:47:55Z"}]' | ConvertFrom-Json
    $planFixture = @($planFixtureData | ForEach-Object { $_ })
    if (
        $planFixture.Count -ne 2 -or
        (@($planFixture.channel_id) -join ',') -cne 'public,education' -or
        (@($planFixture.schedule_id) -join ',') -cne 'fixture-public,fixture-education' -or
        $planFixture[0].PSObject.Properties.Name -contains 'notes'
    ) {
        throw 'Top-level JSON plan arrays are not enumerated compatibly in this PowerShell runtime.'
    }
    $tokens = $null
    $parseErrors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($PSCommandPath, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw "Recovery order has parse errors: $($parseErrors.Message -join '; ')" }
    $functionNames = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $true) | ForEach-Object Name)
    foreach ($required in @('Invoke-NativeGit', 'Get-DirectiveBinding', 'Get-R5LocalVerification', 'Get-R5TesterVerification', 'Publish-R5Invalidation')) {
        if ($required -notin $functionNames) { throw "Recovery order is missing required function $required." }
    }
    $commandNames = @($ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() })
    foreach ($forbidden in @('Restart-Service', 'Stop-Service', 'Start-Service', 'Disable-ScheduledTask', 'Stop-ScheduledTask', 'Unregister-ScheduledTask', 'taskkill.exe')) {
        if ($forbidden -in $commandNames) { throw "Recovery order contains forbidden tester mutation command $forbidden." }
    }
    $source = [IO.File]::ReadAllText($PSCommandPath)
    $stationFunction = 'Invoke-' + 'StationReadOnly'
    $mutatingVerbs = 'PO' + 'ST|PU' + 'T|PAT' + 'CH|DEL' + 'ETE'
    $apiMutationPattern = $stationFunction + '\s+[^\r\n]*(?:' + $mutatingVerbs + ')|/can' + 'cel'
    if ($source -match $apiMutationPattern) { throw 'Recovery order contains a tester API mutation path.' }
    if ($source -notmatch "Method\s*=\s*'GET'" -or $source -match ("Method\s*=\s*'(?:" + $mutatingVerbs + ")'")) {
        throw 'Recovery station helper is not structurally GET-only.'
    }
    [pscustomobject][ordered]@{
        status = 'DRYRUN_VERIFIED'
        mission_nonce = $missionNonce
        candidate_source_sha = $candidateSourceSha
        tester_api_calls = 0
        tester_mutations = 0
        git_invocations = 0
        publication_paths = @($relativeJob, $relativeReceipt)
        checks = @('exact constants', 'PowerShell AST parse', 'required functions', 'no service/task/process mutation commands', 'no tester API mutation calls')
    }
}

if ($DryRun) {
    Assert-DryRunContract | ConvertTo-Json -Depth 10
    return
}

if ($env:COMPUTERNAME -ine $expectedHost) { throw "This recovery order targets $expectedHost only." }
$directiveBinding = Get-DirectiveBinding
$localVerification = Get-R5LocalVerification
$testerVerification = Get-R5TesterVerification $localVerification
$verification = [pscustomobject][ordered]@{ local_r5 = $localVerification; tester = $testerVerification }
$result = Publish-R5Invalidation $verification $directiveBinding
$result | ConvertTo-Json -Depth 20
