# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([Parameter(Mandatory)][string]$IdentityPath,[switch]$DryRun)
$ErrorActionPreference='Stop'
if($DryRun){$null=& (Join-Path $PSScriptRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $IdentityPath;Write-Output 'DRYRUN VERIFIED: exact finalized identity and 240-minute captions-OFF job plan passed; no mutation performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This soak job targets DESKTOP-VBMA6O5 only.'}
. (Join-Path $PSScriptRoot 'Beta7Tester.Common.ps1')
$id=& (Join-Path $PSScriptRoot 'Assert-Beta7CandidateBinding.ps1') -IdentityPath $IdentityPath
$expectedSourceSha='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$missionRoot=[string]$id.mission_state_root
$outputRoot=Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d'
$returnRepo=[string]$id.return_repo_path
$relativeRoot='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r4-c83f2d'
if(Test-Path -LiteralPath $outputRoot){throw 'Physical soak output already exists. Preserve it; do not replay this job.'}
$report=[ordered]@{hostname=[string]$env:COMPUTERNAME;source_sha=[string]$id.candidate_source_sha;mission_nonce=[string]$id.mission_nonce;job_started_utc=[datetime]::UtcNow.ToString('o');job_state='STARTED';minutes=240;phases=@('OFF');result=$null;error=$null}
function Publish-SoakJobReport([switch]$WithArchive){
    $targetRoot=Join-Path $returnRepo $relativeRoot
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    Write-Beta5JsonAtomic $report (Join-Path $targetRoot 'job.json')
    $paths=@("$relativeRoot/job.json")
    if($WithArchive -and (Test-Path -LiteralPath $outputRoot)){
        # Return the measured evidence; full old station logs remain on the tester.
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archivePath=Join-Path $targetRoot 'evidence.zip'
        if(Test-Path -LiteralPath $archivePath){throw 'Evidence archive already exists; preserve it.'}
        $archive=[IO.Compression.ZipFile]::Open($archivePath,[IO.Compression.ZipArchiveMode]::Create)
        try{
            foreach($file in @(Get-ChildItem -LiteralPath $outputRoot -Recurse -File | Where-Object {$_.FullName -notmatch '[\\/]all-raw[\\/]'})){
                $relative=$file.FullName.Substring($outputRoot.Length).TrimStart('\','/') -replace '\\','/'
                $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$file.FullName,$relative,[IO.Compression.CompressionLevel]::Optimal)
            }
            $jobLog=Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d-job.log'
            if(Test-Path -LiteralPath $jobLog){$null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$jobLog,'job.log',[IO.Compression.CompressionLevel]::Optimal)}
        }finally{$archive.Dispose()}
        if((Get-Item -LiteralPath $archivePath).Length -ge 90MB){throw 'Evidence archive exceeds Git size bound; preserve local files for separate retrieval.'}
        $paths+="$relativeRoot/evidence.zip"
    }
    $null=Invoke-Beta5Git $returnRepo (@('add','-f','--')+$paths)
    $null=Invoke-Beta5Git $returnRepo (@('commit','--only','-s','-m',"test: fixed beta physical soak $($report.job_state)",'--')+$paths)
    try{$null=Invoke-Beta5Git $returnRepo @('push','origin',$id.return_branch)}
    catch{
        $null=Invoke-Beta5Git $returnRepo @('pull','--rebase','origin',$id.return_branch)
        $null=Invoke-Beta5Git $returnRepo @('push','origin',$id.return_branch)
    }
}
try{
    $upgrade=Get-Content -LiteralPath (Join-Path $missionRoot 'upgrade-result.json') -Raw | ConvertFrom-Json
    foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha')){if([string]$id.$field -cne $expectedSourceSha){throw "Candidate identity field $field is not the exact authorized 3e117ff1 candidate."}}
    if($upgrade.status -cne 'PASS' -or [string]$upgrade.candidate_source_sha -cne $expectedSourceSha){throw 'Exact 3e117ff1 candidate upgrade receipt has not passed.'}
    if ("$($id.gate_a_verdict)" -cne 'PASS') { throw 'Gate A verdict must be PASS before soak.' }
    if([int]$id.planned_seconds -ne 14400){throw 'Identity is not bound to the required four measured captions-OFF hours.'}
    $null=Assert-Beta5InstalledIdentity -Identity $id -InstallRoot ([string]$id.install_root)
    foreach($entry in $id.actual_runtime_file_sha256.PSObject.Properties){
        $filePath=Join-Path (Join-Path ([string]$id.install_root) 'runtime') ($entry.Name -replace '/','\')
        if((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.Value){throw "Installed runtime changed after verification: $($entry.Name)"}
    }
    $report.installed_identity=@{version=[string]$id.installed_version;installer_sha256=[string]$id.actual_installer_sha256;app_pack_source_sha=[string]$id.native_app_payload_source_sha;runtime_file_sha256=$id.actual_runtime_file_sha256;verified_utc=[datetime]::UtcNow.ToString('o')}
    if(Test-Path -LiteralPath $returnRepo){throw 'Candidate-specific return checkout already exists; preserve it and do not replay this mission.'}
    $null=Invoke-Beta5Git $missionRoot @('clone','--quiet','--depth','1','--single-branch','--branch',$id.return_branch,$id.return_repository_url,$returnRepo)
    foreach($key in @('user.name','user.email')){
        $value=(Invoke-Beta5Git 'C:\CivicCastSoak\repo' @('config','--get',$key) | Select-Object -First 1).Trim()
        if(-not $value){throw "Tester Git identity is missing $key"}
        $null=Invoke-Beta5Git $returnRepo @('config',$key,$value)
    }
    Publish-SoakJobReport
    $transcript=Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d-job.log'
    $phaseReceipt={param($phase,$begin,$end)
        $report.current_phase=[string]$phase
        $report.measured_phase_begin_utc=$begin.ToString('o')
        $report.measured_phase_planned_end_utc=$end.ToString('o')
        Publish-SoakJobReport
    }
    $expectedElements=@{}
    foreach($phaseProperty in $id.expected_elements_per_phase.PSObject.Properties){
        $phaseMap=@{}
        foreach($channelProperty in $phaseProperty.Value.PSObject.Properties){$phaseMap[$channelProperty.Name]=@($channelProperty.Value | ForEach-Object {[int]$_})}
        $expectedElements[$phaseProperty.Name]=$phaseMap
    }
    # No overlap IDs are authorized. The corrected driver fails before cancellation
    # if any live schedule row overlaps this fresh candidate-owned horizon.
    & (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoakR6.ps1') -BaseUrl 'http://127.0.0.1:8000' -OutputRoot $outputRoot -SourceSha $id.candidate_source_sha -Minutes 240 -Mode OFF -ReplaceOverlappingTestSchedule -RequireTransportAdmission -ExpectedElementsPerPhase $expectedElements -OnPhaseStarted $phaseReceipt *> $transcript
    $runs=@(Get-ChildItem -LiteralPath $outputRoot -Directory)
    if($runs.Count -ne 1){throw 'Physical soak output does not contain exactly one run.'}
    $report.result=Get-Content -LiteralPath (Join-Path $runs[0].FullName 'VERDICT.json') -Raw | ConvertFrom-Json
    if($report.result.verdict -ne 'TIMING_LIFETIME_TRANSPORT_PASS'){throw 'Physical timing/lifetime/transport checks did not pass.'}
    $report.job_state='COLLECTION_PASS'
}catch{
    $report.job_state='FAIL'
    $report.error=[string]$_.Exception.Message
}finally{
    $report.finished_utc=[datetime]::UtcNow.ToString('o')
    Write-Beta5JsonAtomic $report (Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d-job.json')
    if(Test-Path -LiteralPath (Join-Path $returnRepo '.git')){
        try{Publish-SoakJobReport -WithArchive}
        catch{
            [IO.File]::WriteAllText((Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d-publish-error.txt'),[string]$_.Exception.Message)
            try{Publish-SoakJobReport}catch{[IO.File]::AppendAllText((Join-Path $missionRoot 'physical-soak-off4h-r4-c83f2d-publish-error.txt'),"`nStatus publication also failed: "+[string]$_.Exception.Message)}
        }
    }
}
if($report.job_state -eq 'FAIL'){throw 'Physical soak failed. Results are preserved and publication was attempted.'}
