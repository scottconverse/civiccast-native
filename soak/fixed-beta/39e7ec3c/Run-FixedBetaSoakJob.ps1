# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([Parameter(Mandatory)][string]$IdentityPath,[switch]$DryRun)
$ErrorActionPreference='Stop'
if($DryRun){Write-Output 'DRYRUN: verify installed identity, publish job receipt, run two120-minute phases, preserve and publish evidence. No actions performed.';return}
if($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5'){throw 'This soak job targets DESKTOP-VBMA6O5 only.'}
. (Join-Path $PSScriptRoot 'Beta5Tester.Common.ps1')
$id=Get-Beta5Identity $IdentityPath
$missionRoot=[string]$id.mission_state_root
$outputRoot=Join-Path $missionRoot 'physical-soak'
$returnRepo=[string]$id.return_repo_path
$relativeRoot='soak/fixed-beta-39e7/physical-soak-r1'
if(Test-Path -LiteralPath $outputRoot){throw 'Physical soak output already exists. Preserve it; do not replay this job.'}
$report=[ordered]@{hostname=[string]$env:COMPUTERNAME;source_sha=[string]$id.candidate_source_sha;job_started_utc=[datetime]::UtcNow.ToString('o');job_state='STARTED';minutes_per_phase=120;phases=@('ON','OFF');result=$null;error=$null}
function Publish-SoakJobReport([switch]$WithArchive){
    $targetRoot=Join-Path $returnRepo $relativeRoot
    New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
    Write-Beta5JsonAtomic $report (Join-Path $targetRoot 'job.json')
    $paths=@("$relativeRoot/job.json")
    if($WithArchive -and (Test-Path -LiteralPath $outputRoot)){
        # Return the measured evidence; full old station logs remain on the tester.
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archivePath=Join-Path $targetRoot 'evidence.zip'
        if(Test-Path -LiteralPath $archivePath){throw 'Evidence archive already exists; preserve it.'}
        $archive=[IO.Compression.ZipFile]::Open($archivePath,[IO.Compression.ZipArchiveMode]::Create)
        try{
            foreach($file in @(Get-ChildItem -LiteralPath $outputRoot -Recurse -File | Where-Object {$_.FullName -notmatch '[\\/]all-raw[\\/]'})){
                $relative=$file.FullName.Substring($outputRoot.Length).TrimStart('\','/') -replace '\\','/'
                $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$file.FullName,$relative,[IO.Compression.CompressionLevel]::Optimal)
            }
            $jobLog=Join-Path $missionRoot 'physical-soak-job.log'
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
    if($upgrade.status -ne 'PASS' -or $upgrade.candidate_source_sha -ne $id.candidate_source_sha){throw 'Exact candidate upgrade has not passed.'}
    $null=Assert-Beta5InstalledIdentity -Identity $id -InstallRoot 'C:\CivicCastHostStore\install'
    foreach($entry in $id.actual_runtime_file_sha256.PSObject.Properties){
        $filePath=Join-Path 'C:\CivicCastHostStore\install\runtime' ($entry.Name -replace '/','\')
        if((Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$entry.Value){throw "Installed runtime changed after verification: $($entry.Name)"}
    }
    $report.installed_identity=@{version=[string]$id.installed_version;installer_sha256=[string]$id.actual_installer_sha256;app_pack_source_sha=[string]$id.native_app_payload_source_sha;runtime_file_sha256=$id.actual_runtime_file_sha256;verified_utc=[datetime]::UtcNow.ToString('o')}
    if(Test-Path -LiteralPath $returnRepo){throw 'Soak return checkout already exists; inspect its state before retry.'}
    $null=Invoke-Beta5Git $missionRoot @('clone','--quiet','--depth','1','--single-branch','--branch',$id.return_branch,$id.return_repository_url,$returnRepo)
    foreach($key in @('user.name','user.email')){
        $value=(Invoke-Beta5Git 'C:\CivicCastSoak\repo' @('config','--get',$key) | Select-Object -First 1).Trim()
        if(-not $value){throw "Tester Git identity is missing $key"}
        $null=Invoke-Beta5Git $returnRepo @('config',$key,$value)
    }
    Publish-SoakJobReport
    $transcript=Join-Path $missionRoot 'physical-soak-job.log'
    & (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoak.ps1') -BaseUrl 'http://127.0.0.1:8000' -OutputRoot $outputRoot -SourceSha $id.candidate_source_sha -Minutes 120 -Mode Both -ReplaceOverlappingTestSchedule *> $transcript
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
    Write-Beta5JsonAtomic $report (Join-Path $missionRoot 'physical-soak-job.json')
    if(Test-Path -LiteralPath (Join-Path $returnRepo '.git')){
        try{Publish-SoakJobReport -WithArchive}
        catch{[IO.File]::WriteAllText((Join-Path $missionRoot 'physical-soak-publish-error.txt'),[string]$_.Exception.Message)}
    }
}
if($report.job_state -eq 'FAIL'){throw 'Physical soak failed. Results are preserved and publication was attempted.'}
