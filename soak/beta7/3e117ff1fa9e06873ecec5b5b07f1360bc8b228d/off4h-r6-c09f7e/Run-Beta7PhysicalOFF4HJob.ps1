# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([Parameter(Mandatory)][string]$IdentityPath,[switch]$DryRun)
$ErrorActionPreference='Stop'
$expectedSourceSha='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$id=& (Join-Path $PSScriptRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $IdentityPath
$packageProof=& (Join-Path $PSScriptRoot 'Test-Beta7HarnessPackage.ps1') -PackageRoot $PSScriptRoot -IdentityPath $IdentityPath
if($DryRun){Write-Output 'DRYRUN VERIFIED: exact R6 identity, harness, and authoritative completion plan passed; no mutation performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This R6 soak job targets DESKTOP-VBMA6O5 only.'}
. (Join-Path $PSScriptRoot 'Beta7Tester.Common.ps1')

$missionRoot=[string]$id.mission_state_root
$taskName=[string]$id.task_name
$outputName='physical-soak-off4h-r6-c09f7e'
$outputRoot=Join-Path $missionRoot $outputName
$returnRepo=[string]$id.return_repo_path
$relativeRoot=[string]$id.evidence_relative_root
$jobRelative="$relativeRoot/job.json"
$archiveRelative="$relativeRoot/evidence.zip"
$completionRelative="$relativeRoot/COMPLETION.json"
$jobPath=Join-Path $returnRepo ($jobRelative -replace '/','\')
$archivePath=Join-Path $returnRepo ($archiveRelative -replace '/','\')
$completionPath=Join-Path $returnRepo ($completionRelative -replace '/','\')
$jobLog=Join-Path $missionRoot "$outputName-job.log"
$latchPath=Join-Path $missionRoot 'RUN-CONSUMED.json'
$report=[ordered]@{schema='civiccast-beta7-physical-job-v3';hostname=[string]$env:COMPUTERNAME;source_sha=[string]$id.candidate_source_sha;mission_nonce=[string]$id.mission_nonce;harness_source_commit=[string]$id.harness_source_commit;harness_manifest_sha256=$packageProof.manifest_sha256;evidence_relative_path=$archiveRelative;completion_relative_path=$completionRelative;job_started_utc=[datetime]::UtcNow.ToString('o');job_state='STARTED';minutes=240;phases=@('OFF');result=$null;error=$null}

function Write-JsonUtf8NoBom($Object,[string]$Path){
    New-Item -ItemType Directory -Path (Split-Path $Path) -Force|Out-Null
    [IO.File]::WriteAllText($Path,($Object|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
}
function New-RunLatch {
    $payload=@{schema='civiccast-beta7-run-consumed-v1';mission_nonce=[string]$id.mission_nonce;source_sha=[string]$id.candidate_source_sha;hostname=[string]$env:COMPUTERNAME;consumed_utc=[datetime]::UtcNow.ToString('o');task_name=$taskName}|ConvertTo-Json -Compress
    $stream=$null
    try{
        $stream=[IO.File]::Open($latchPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $bytes=[Text.UTF8Encoding]::new($false).GetBytes($payload)
        $stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)
    }catch{throw 'R6 nonce has already been consumed or its durable latch could not be created.'}
    finally{if($stream){$stream.Dispose()}}
}
function Disable-OwnTask {
    $task=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop|Out-Null
    $observed=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if("$($observed.State)" -ne 'Disabled'){throw 'R6 task did not become Disabled at entry.'}
    $report.task_entry=@{previous_state=[string]$task.State;disabled_state=[string]$observed.State;at=[datetime]::UtcNow.ToString('o')}
}
function Write-Job {Write-JsonUtf8NoBom $report $jobPath}
function Sync-And-Push([string[]]$Paths,[string]$Message){
    $lastError=$null
    for($attempt=1;$attempt -le 3;$attempt++){
        try{
            $null=Invoke-Beta5Git -Repository $returnRepo -Arguments @('pull','--rebase','--autostash','origin',[string]$id.return_branch)
            $null=Invoke-Beta5Git -Repository $returnRepo -Arguments (@('add','-f','--')+$Paths)
            $status=@(Invoke-Beta5Git -Repository $returnRepo -Arguments (@('status','--porcelain','--')+$Paths))
            if($status.Count){$null=Invoke-Beta5Git -Repository $returnRepo -Arguments (@('commit','--only','-s','-m',$Message,'--')+$Paths)}
            $null=Invoke-Beta5Git -Repository $returnRepo -Arguments @('push','origin',[string]$id.return_branch)
            return (Invoke-Beta5Git -Repository $returnRepo -Arguments @('rev-parse','HEAD')|Select-Object -First 1).Trim()
        }catch{$lastError=$_.Exception.Message;if($attempt -lt 3){Start-Sleep -Seconds (2*$attempt)}}
    }
    throw "Evidence publication failed after three attempts: $lastError"
}
function Assert-RemoteBlobs([string[]]$Paths){
    $null=Invoke-Beta5Git -Repository $returnRepo -Arguments @('fetch','origin',[string]$id.return_branch)
    $remote=(Invoke-Beta5Git -Repository $returnRepo -Arguments @('rev-parse',"origin/$($id.return_branch)")|Select-Object -First 1).Trim()
    foreach($path in $Paths){
        $local=(Invoke-Beta5Git -Repository $returnRepo -Arguments @('rev-parse',":$path")|Select-Object -First 1).Trim()
        $observed=(Invoke-Beta5Git -Repository $returnRepo -Arguments @('rev-parse',"$remote`:$path")|Select-Object -First 1).Trim()
        if($local -cne $observed){throw "Remote evidence blob does not match the exact committed bytes: $path"}
    }
    return $remote
}
function Build-EvidenceArchive {
    if(Test-Path -LiteralPath $archivePath){throw 'Evidence archive already exists; preserve it.'}
    New-Item -ItemType Directory -Path (Split-Path $archivePath) -Force|Out-Null
    Add-Type -AssemblyName System.IO.Compression;Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive=[IO.Compression.ZipFile]::Open($archivePath,[IO.Compression.ZipArchiveMode]::Create)
    try{
        if(Test-Path -LiteralPath $outputRoot){
            foreach($file in @(Get-ChildItem -LiteralPath $outputRoot -Recurse -File|Where-Object{$_.FullName -notmatch '[\\/]all-raw[\\/]'})){
                $relative='run/'+($file.FullName.Substring($outputRoot.Length).TrimStart('\','/') -replace '\','/')
                $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$file.FullName,$relative,[IO.Compression.CompressionLevel]::Optimal)
            }
        }
        foreach($file in @(Get-ChildItem -LiteralPath $PSScriptRoot -File)){
            $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$file.FullName,('harness/'+$file.Name),[IO.Compression.CompressionLevel]::Optimal)
        }
        if(Test-Path -LiteralPath $jobLog){$null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$jobLog,'job.log',[IO.Compression.CompressionLevel]::Optimal)}
    }finally{$archive.Dispose()}
    $item=Get-Item -LiteralPath $archivePath
    if($item.Length -ge 90MB){throw 'Evidence archive exceeds the Git size bound; local evidence is preserved.'}
    [pscustomobject]@{size_bytes=[int64]$item.Length;sha256=(Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()}
}
function Get-AuthoritativeState([bool]$CollectionPass,[bool]$CleanupPass,[bool]$EvidenceBuilt,[bool]$EvidencePushed,[bool]$EvidenceVerified,[bool]$CompletionPushed){
    if($CollectionPass -and $CleanupPass -and $EvidenceBuilt -and $EvidencePushed -and $EvidenceVerified -and $CompletionPushed){return 'PASS'}
    if($CollectionPass -and $CleanupPass){return 'EVIDENCE_PUBLISH_FAIL'}
    return 'FAIL'
}

$finalFailure=$null
$collectionPass=$false;$cleanupPass=$false;$evidenceBuilt=$false;$evidencePushed=$false;$evidenceVerified=$false;$completionPushed=$false
try{
    New-RunLatch
    Disable-OwnTask
    $upgrade=Get-Content -LiteralPath (Join-Path $missionRoot 'upgrade-result.json') -Raw|ConvertFrom-Json
    if("$($upgrade.status)" -ne 'PASS' -or "$($upgrade.candidate_source_sha)" -ne $expectedSourceSha){throw 'Exact installed-byte adoption receipt has not passed.'}
    foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha')){if("$($id.$field)" -ne $expectedSourceSha){throw "Candidate identity field $field is not exact."}}
    if("$($id.gate_a_verdict)" -ne 'PASS' -or [int]$id.planned_seconds -ne 14400){throw 'Gate A or four-hour duration binding is invalid.'}
    $installed=Assert-Beta5InstalledIdentity -Identity $id -InstallRoot ([string]$id.install_root)
    foreach($entry in $id.actual_runtime_file_sha256.PSObject.Properties){
        $filePath=Join-Path (Join-Path ([string]$id.install_root) 'runtime') ($entry.Name -replace '/','\')
        if((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne "$($entry.Value)"){throw "Installed runtime changed after R6 adoption: $($entry.Name)"}
    }
    $report.installed_identity=@{version=[string]$id.installed_version;installer_sha256=[string]$id.actual_installer_sha256;app_pack_source_sha=[string]$id.native_app_payload_source_sha;runtime_file_sha256=$id.actual_runtime_file_sha256;service_process_id=[int]$installed.service_process_id;verified_utc=[datetime]::UtcNow.ToString('o')}
    if(Test-Path -LiteralPath $outputRoot){throw 'R6 output already exists; preserve it and do not replay.'}
    if(Test-Path -LiteralPath $returnRepo){throw 'R6 return checkout already exists; preserve it and do not replay.'}
    $previousEap=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$cloneOutput=@(& git clone --quiet --depth 1 --single-branch --branch $id.return_branch $id.return_repository_url $returnRepo 2>&1);$cloneExit=$LASTEXITCODE}finally{$ErrorActionPreference=$previousEap}
    if($cloneExit -ne 0){throw "Could not clone the R6 evidence return branch: $($cloneOutput -join ' ')"}
    foreach($key in @('user.name','user.email')){
        $value=(Invoke-Beta5Git -Repository 'C:\CivicCastSoak\repo' -Arguments @('config','--get',$key)|Select-Object -First 1).Trim()
        if(-not $value){throw "Tester Git identity is missing $key"}
        $null=Invoke-Beta5Git -Repository $returnRepo -Arguments @('config',$key,$value)
    }
    Write-Job
    $report.started_commit=Sync-And-Push @($jobRelative) 'test: beta.7 R6 physical soak STARTED'
    $report.started_verified_commit=Assert-RemoteBlobs @($jobRelative)
    if([string]$report.started_verified_commit -cne [string]$report.started_commit){throw 'Initial STARTED receipt was not verified at its pushed commit.'}
    $startBlob=(Invoke-Beta5Git -Repository $returnRepo -Arguments @('rev-parse',"$($report.started_verified_commit)`:$jobRelative")|Select-Object -First 1).Trim()
    Write-Beta5JsonAtomic @{schema='civiccast-beta7-start-verified-v1';status='STARTED_AND_REMOTELY_VERIFIED';candidate_source_sha=[string]$id.candidate_source_sha;mission_nonce=[string]$id.mission_nonce;harness_source_commit=[string]$id.harness_source_commit;job_state='STARTED';job_started_utc=[string]$report.job_started_utc;remote_commit=[string]$report.started_verified_commit;remote_blob=$startBlob;job_relative_path=$jobRelative;verified_utc=[datetime]::UtcNow.ToString('o')} (Join-Path $missionRoot 'START-VERIFIED.json')
    $phaseReceipt={
    param($phase,$begin,$end)
    $report.current_phase=[string]$phase
    $report.measured_phase_begin_utc=$begin.ToString('o')
    $report.measured_phase_planned_end_utc=$end.ToString('o')
    Write-Job
    $report.phase_commit=Sync-And-Push @($jobRelative) 'test: beta.7 R6 measured phase READY'
    $report.phase_verified_commit=Assert-RemoteBlobs @($jobRelative)
    if([string]$report.phase_verified_commit -cne [string]$report.phase_commit){throw 'Measured phase receipt was not verified at its pushed commit.'}
    return [pscustomobject]@{status='PHASE_READY_AND_REMOTELY_VERIFIED';candidate_source_sha=[string]$id.candidate_source_sha;phase=[string]$phase;begin_utc=$begin.ToString('o');end_utc=$end.ToString('o');remote_commit=[string]$report.phase_verified_commit}
}
    $expectedElements=@{}
    foreach($phaseProperty in $id.expected_elements_per_phase.PSObject.Properties){$phaseMap=@{};foreach($channelProperty in $phaseProperty.Value.PSObject.Properties){$phaseMap[$channelProperty.Name]=@($channelProperty.Value|ForEach-Object{[int]$_})};$expectedElements[$phaseProperty.Name]=$phaseMap}
    & (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoakR6.ps1') -BaseUrl 'http://127.0.0.1:8000' -OutputRoot $outputRoot -SourceSha $id.candidate_source_sha -Minutes 240 -Mode OFF -RequireTransportAdmission -ExpectedElementsPerPhase $expectedElements -OnPhaseStarted $phaseReceipt *> $jobLog
    $runs=@(Get-ChildItem -LiteralPath $outputRoot -Directory)
    if($runs.Count -ne 1){throw 'R6 physical output does not contain exactly one run.'}
    $run=$runs[0].FullName
    $report.result=Get-Content -LiteralPath (Join-Path $run 'VERDICT.json') -Raw|ConvertFrom-Json
    if("$($report.result.verdict)" -ne 'TIMING_LIFETIME_TRANSPORT_PASS'){throw 'R6 physical checks did not pass.'}
    if(-not(Test-Path -LiteralPath (Join-Path $run 'STOP-VERIFIED.json') -PathType Leaf) -or (Test-Path -LiteralPath (Join-Path $run 'STOP-FAILED.json') -PathType Leaf) -or -not(Test-Path -LiteralPath (Join-Path $run 'SCHEDULE-CLEANUP-VERIFIED.json') -PathType Leaf) -or (Test-Path -LiteralPath (Join-Path $run 'SCHEDULE-CLEANUP-FAILED.json') -PathType Leaf)){throw 'R6 terminal channel and owned-schedule cleanup is not verified.'}
    $collectionPass=$true;$cleanupPass=$true
    $report.job_state='COLLECTION_PASS_PENDING_EVIDENCE';$report.collection_finished_utc=[datetime]::UtcNow.ToString('o')
    $report.evidence=Build-EvidenceArchive;$evidenceBuilt=$true
    Write-Job;$report.evidence_commit=Sync-And-Push @($jobRelative,$archiveRelative) 'test: beta.7 R6 collection and evidence uploaded';$evidencePushed=$true
    $report.evidence_verified_commit=Assert-RemoteBlobs @($jobRelative,$archiveRelative);$evidenceVerified=$true
    $completion=[ordered]@{schema='civiccast-beta7-authoritative-completion-v1';status='PASS';verdict='PASS';candidate_source_sha=[string]$id.candidate_source_sha;mission_nonce=[string]$id.mission_nonce;hostname=[string]$env:COMPUTERNAME;harness_source_commit=[string]$id.harness_source_commit;harness_manifest_sha256=$packageProof.manifest_sha256;verified_evidence_commit=[string]$report.evidence_verified_commit;evidence_relative_path=$archiveRelative;evidence_sha256=[string]$report.evidence.sha256;evidence_size_bytes=[int64]$report.evidence.size_bytes;cleanup_receipts=@('STOP-VERIFIED.json','SCHEDULE-CLEANUP-VERIFIED.json');completed_utc=[datetime]::UtcNow.ToString('o')}
    Write-JsonUtf8NoBom $completion $completionPath
    # job.json and COMPLETION.json become visible in one atomic Git ref update.
    # A remote PASS therefore cannot exist without its authoritative receipt.
    $report.job_state='PASS';Write-Job
    $report.completion_commit=Sync-And-Push @($jobRelative,$completionRelative) 'test: beta.7 R6 authoritative PASS completion'
    $report.completion_verified_commit=Assert-RemoteBlobs @($jobRelative,$completionRelative)
    if([string]$report.completion_verified_commit -cne [string]$report.completion_commit){throw 'Final authoritative completion was not verified at its pushed commit.'}
    $completionPushed=$true
    $report.job_state=Get-AuthoritativeState $collectionPass $cleanupPass $evidenceBuilt $evidencePushed $evidenceVerified $completionPushed
    $report.finished_utc=[datetime]::UtcNow.ToString('o')
}catch{
    $finalFailure=[string]$_.Exception.Message
    $report.job_state=Get-AuthoritativeState $collectionPass $cleanupPass $evidenceBuilt $evidencePushed $evidenceVerified $completionPushed
    $report.error=$finalFailure;$report.finished_utc=[datetime]::UtcNow.ToString('o')
    if(Test-Path -LiteralPath (Join-Path $returnRepo '.git')){
        try{
            if(-not $evidenceBuilt -and -not(Test-Path -LiteralPath $archivePath) -and ((Test-Path -LiteralPath $outputRoot) -or (Test-Path -LiteralPath $jobLog))){$report.evidence=Build-EvidenceArchive;$evidenceBuilt=$true}
            Write-Job
            $failurePaths=@($jobRelative);if($evidenceBuilt){$failurePaths+=$archiveRelative}
            $report.failure_commit=Sync-And-Push $failurePaths 'test: beta.7 R6 physical soak FAIL'
        }catch{[IO.File]::WriteAllText((Join-Path $missionRoot "$outputName-publish-error.txt"),([string]$_.Exception.Message),[Text.UTF8Encoding]::new($false))}
    }
}
Write-Beta5JsonAtomic $report (Join-Path $missionRoot "$outputName-job.json")
if($report.job_state -ne 'PASS'){throw "R6 physical soak did not pass: $finalFailure"}
