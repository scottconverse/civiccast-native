# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$DryRun,[switch]$SelfTest)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

$expectedHost='DESKTOP-VBMA6O5'
$expectedSource='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$expectedMission='BETA7-3E117FF1-OFF4H-R15-4F9B22'
$expectedEvidenceSha='ee2edeb12d701d460f607acf4a400a180698107f9dcf5948464945c685ceb6d1'
$missionRoot='C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r15-4f9b22'
$r15Output=Join-Path $missionRoot 'physical-soak-off4h-r15-4f9b22'
$r15Job=Join-Path $missionRoot 'physical-soak-off4h-r15-4f9b22-job.json'
$r15EvidenceRelative='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r15-4f9b22/evidence.zip'
$returnBranch='tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$publishRoot='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r15-4f9b22/posthoc-r16-r1'

function Write-JsonNoBom($Value,[string]$Path){
    New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force|Out-Null
    [IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
}
function Invoke-CheckedGit([string]$Repository,[string[]]$Arguments){
    $previous=$ErrorActionPreference
    try{$ErrorActionPreference='Continue';$output=@(& git -C $Repository @Arguments 2>&1);$exit=$LASTEXITCODE}
    finally{$ErrorActionPreference=$previous}
    if($exit -ne 0){throw "Git failed ($exit): git $($Arguments -join ' ') :: $($output -join ' ')"}
    return $output
}
function Get-SelectedLogs([string]$AllRaw){
    $selected=@()
    foreach($channel in @('public','education','government')){
        $dir=Join-Path $AllRaw "data\egress\$channel\logs"
        foreach($base in @('gst-worker.stdout.log','gst-worker.stderr.log')){
            if(Test-Path -LiteralPath $dir){
                $selected+=@(Get-ChildItem -LiteralPath $dir -File|Where-Object{$_.Name -eq $base -or $_.Name -match ('^'+[regex]::Escape($base)+'\.\d+$')})
            }
        }
    }
    $controlDir=Join-Path $AllRaw 'logs'
    if(Test-Path -LiteralPath $controlDir){
        foreach($base in @('control_plane-app.log','control_plane.log')){
            $selected+=@(Get-ChildItem -LiteralPath $controlDir -File|Where-Object{$_.Name -eq $base -or $_.Name -match ('^'+[regex]::Escape($base)+'\.\d+$')})
        }
    }
    return @($selected|Sort-Object FullName -Unique)
}
function Copy-SelectedLogs([string]$AllRaw,[string]$Bundle){
    $files=@(Get-SelectedLogs $AllRaw)
    if($files.Count -lt 8){throw "Expected six worker logs and both control-plane families; found $($files.Count) files."}
    $workerCounts=@{}
    foreach($channel in @('public','education','government')){
        $workerCounts[$channel]=@($files|Where-Object{$_.FullName -match "(?i)[\\/]$channel[\\/]logs[\\/]gst-worker\.(stdout|stderr)\.log$"}).Count
        if($workerCounts[$channel] -ne 2){throw "Expected exact stdout/stderr worker snapshot for $channel."}
    }
    foreach($base in @('control_plane-app.log','control_plane.log')){
        if(@($files|Where-Object{$_.Name -eq $base}).Count -ne 1){throw "Expected active $base in the terminal snapshot."}
    }
    if(@($files|Where-Object{$_.Name -match '^control_plane-app\.log\.\d+$'}).Count -lt 1){throw 'Expected at least one rotated control_plane-app.log generation.'}
    $copied=@()
    foreach($file in $files){
        $relative=$file.FullName.Substring($AllRaw.TrimEnd('\','/').Length).TrimStart('\','/')
        $destination=Join-Path $Bundle $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force|Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
        $copied+=[pscustomobject]@{relative_path=$relative.Replace('\','/');size_bytes=[int64]$file.Length;last_write_utc=$file.LastWriteTimeUtc.ToString('o');sha256=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    return $copied
}
function New-Zip([string]$Source,[string]$Destination){
    if(Test-Path -LiteralPath $Destination){throw 'Posthoc archive already exists; preserve it.'}
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force|Out-Null
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($Source,$Destination,[IO.Compression.CompressionLevel]::Optimal,$false)
    $item=Get-Item -LiteralPath $Destination
    if($item.Length -ge 90MB){throw 'Posthoc archive exceeds the Git size bound.'}
    return [pscustomobject]@{size_bytes=[int64]$item.Length;sha256=(Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()}
}

if($DryRun){
    [pscustomobject]@{status='DRYRUN_VERIFIED';hostname=$expectedHost;candidate_source_sha=$expectedSource;mission_nonce=$expectedMission;source='preserved R15 all-raw terminal snapshot';station_changes=$false;rerun=$false;publish_root=$publishRoot}|ConvertTo-Json -Compress
    return
}
if($SelfTest){
    $tokens=$null;$parseErrors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($PSCommandPath,[ref]$tokens,[ref]$parseErrors)
    if(@($parseErrors).Count){throw "Collector has parse errors: $($parseErrors.Message -join '; ')"}
    $forbidden=@('Start-Service','Stop-Service','Restart-Service','Invoke-RestMethod','Start-ScheduledTask','Register-ScheduledTask','Unregister-ScheduledTask')
    $commands=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()}|Where-Object{$_})
    if(@($commands|Where-Object{$_ -in $forbidden}).Count){throw 'Collector contains a station or task mutation command.'}
    $temp=Join-Path ([IO.Path]::GetTempPath()) ('civiccast-r16-selftest-'+[guid]::NewGuid().ToString('N'))
    try{
        $all=Join-Path $temp 'all-raw';$bundle=Join-Path $temp 'bundle'
        foreach($channel in @('public','education','government')){
            $dir=Join-Path $all "data\egress\$channel\logs";New-Item -ItemType Directory -Path $dir -Force|Out-Null
            [IO.File]::WriteAllText((Join-Path $dir 'gst-worker.stdout.log'),"$channel stdout",[Text.UTF8Encoding]::new($false))
            [IO.File]::WriteAllText((Join-Path $dir 'gst-worker.stderr.log'),"$channel stderr",[Text.UTF8Encoding]::new($false))
        }
        $logs=Join-Path $all 'logs';New-Item -ItemType Directory -Path $logs -Force|Out-Null
        foreach($name in @('control_plane-app.log','control_plane-app.log.1','control_plane-app.log.2','control_plane.log')){[IO.File]::WriteAllText((Join-Path $logs $name),$name,[Text.UTF8Encoding]::new($false))}
        [IO.File]::WriteAllText((Join-Path $logs 'unrelated-secret.log'),'must not copy',[Text.UTF8Encoding]::new($false))
        $copied=@(Copy-SelectedLogs $all $bundle)
        if($copied.Count -ne 10 -or @($copied|Where-Object{$_.relative_path -match 'unrelated'}).Count){throw 'Bounded log selection failed.'}
        Write-JsonNoBom @{files=$copied} (Join-Path $bundle 'LOG-INVENTORY.json')
        $zip=New-Zip $bundle (Join-Path $temp 'proof.zip')
        $archive=[IO.Compression.ZipFile]::OpenRead((Join-Path $temp 'proof.zip'))
        try{if(@($archive.Entries).Count -ne 11){throw 'Self-test archive entry count is wrong.'}}finally{$archive.Dispose()}
        [pscustomobject]@{status='SELFTEST_PASS';selected_files=$copied.Count;archive_sha256=$zip.sha256}|ConvertTo-Json -Compress
    }finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Recurse -Force}}
    return
}

if($env:COMPUTERNAME -ine $expectedHost){throw 'R16 posthoc collector targets DESKTOP-VBMA6O5 only.'}
if(-not(Test-Path -LiteralPath $r15Job -PathType Leaf)){throw 'Exact R15 terminal job receipt is absent.'}
$job=Get-Content -LiteralPath $r15Job -Raw|ConvertFrom-Json
if([string]$job.source_sha -cne $expectedSource -or [string]$job.mission_nonce -cne $expectedMission -or [string]$job.job_state -cne 'FAIL' -or [string]$job.error -cne 'Log rotated/truncated during measured phase: C:\ProgramData\CivicCast\logs\control_plane-app.log'){throw 'R15 terminal job does not match the exact harness-only failure.'}
$oldReturn=Join-Path $missionRoot 'return-repo'
$oldEvidence=Join-Path $oldReturn ($r15EvidenceRelative -replace '/','\')
if(-not(Test-Path -LiteralPath $oldEvidence -PathType Leaf) -or (Get-FileHash -LiteralPath $oldEvidence -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedEvidenceSha){throw 'Exact published R15 evidence archive is absent or changed.'}
$runs=@(Get-ChildItem -LiteralPath $r15Output -Directory)
if($runs.Count -ne 1){throw 'R15 output does not contain exactly one preserved run.'}
$run=$runs[0].FullName
$allRaw=Join-Path $run 'all-raw'
if(-not(Test-Path -LiteralPath $allRaw -PathType Container)){throw 'R15 terminal all-raw snapshot is absent.'}
$soakStart=Get-Content -LiteralPath (Join-Path $run 'OFF\SOAK-START.json') -Raw|ConvertFrom-Json
$finalState=Get-Content -LiteralPath (Join-Path $run 'OFF\FINAL-STATE.json') -Raw|ConvertFrom-Json
$localVerdict=Get-Content -LiteralPath (Join-Path $run 'VERDICT.json') -Raw|ConvertFrom-Json
if([string]$soakStart.source_sha -cne $expectedSource -or @($finalState.channels).Count -ne 3 -or [string]$localVerdict.source_sha -cne $expectedSource -or [string]$localVerdict.verdict -cne 'FAIL' -or [string]$localVerdict.error -cne [string]$job.error){throw 'R15 run identity, final state, or local terminal verdict is not exact.'}

$output=Join-Path $missionRoot 'posthoc-r16-r1'
if(Test-Path -LiteralPath $output){throw 'R16 posthoc output already exists; preserve it.'}
$bundle=Join-Path $output 'bundle';New-Item -ItemType Directory -Path $bundle -Force|Out-Null
$files=@(Copy-SelectedLogs $allRaw $bundle)
$allInventory=@(Get-ChildItem -LiteralPath $allRaw -Recurse -File|Where-Object{$_.Name -match '\.log(?:\.\d+)?$'}|ForEach-Object{[pscustomobject]@{relative_path=$_.FullName.Substring($allRaw.TrimEnd('\','/').Length).TrimStart('\','/').Replace('\','/');size_bytes=[int64]$_.Length;last_write_utc=$_.LastWriteTimeUtc.ToString('o');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}})
Write-JsonNoBom @{schema='civiccast-beta7-r15-posthoc-log-inventory-v1';source_sha=$expectedSource;mission_nonce=$expectedMission;r15_evidence_sha256=$expectedEvidenceSha;r15_run_id=$runs[0].Name;soak_begin=[string]$soakStart.begin;soak_planned_end=[string]$soakStart.planned_end;selected_files=$files;all_terminal_logs=$allInventory;collected_utc=[datetime]::UtcNow.ToString('o')} (Join-Path $bundle 'LOG-INVENTORY.json')
$zipLocal=Join-Path $output 'worker-and-rotation-logs.zip';$zip=New-Zip $bundle $zipLocal
$report=[ordered]@{schema='civiccast-beta7-r15-posthoc-collection-v1';status='COLLECTED';hostname=[string]$env:COMPUTERNAME;candidate_source_sha=$expectedSource;mission_nonce=$expectedMission;r15_evidence_sha256=$expectedEvidenceSha;r15_run_id=$runs[0].Name;source_snapshot='terminal all-raw copied by R15 after channel stop';selected_file_count=$files.Count;all_log_count=$allInventory.Count;archive_sha256=$zip.sha256;archive_size_bytes=$zip.size_bytes;station_changes=$false;rerun=$false;collected_utc=[datetime]::UtcNow.ToString('o')}
$reportLocal=Join-Path $output 'REPORT.json';Write-JsonNoBom $report $reportLocal

$returnRepo=Join-Path $output 'return-repo'
$cloneParent=Split-Path -Parent $returnRepo;New-Item -ItemType Directory -Path $cloneParent -Force|Out-Null
$previous=$ErrorActionPreference
try{$ErrorActionPreference='Continue';$cloneOutput=@(& git clone --quiet --depth 1 --single-branch --branch $returnBranch 'https://github.com/scottconverse/civiccast-native.git' $returnRepo 2>&1);$cloneExit=$LASTEXITCODE}
finally{$ErrorActionPreference=$previous}
if($cloneExit -ne 0){throw "Could not clone tester evidence branch: $($cloneOutput -join ' ')"}
foreach($key in @('user.name','user.email')){$value=(Invoke-CheckedGit 'C:\CivicCastSoak\repo' @('config','--get',$key)|Select-Object -First 1).Trim();if(-not $value){throw "Tester Git identity lacks $key"};$null=Invoke-CheckedGit $returnRepo @('config',$key,$value)}
$reportRelative="$publishRoot/REPORT.json";$zipRelative="$publishRoot/worker-and-rotation-logs.zip"
$reportDest=Join-Path $returnRepo ($reportRelative -replace '/','\');$zipDest=Join-Path $returnRepo ($zipRelative -replace '/','\')
New-Item -ItemType Directory -Path (Split-Path -Parent $reportDest) -Force|Out-Null
Copy-Item -LiteralPath $reportLocal -Destination $reportDest;Copy-Item -LiteralPath $zipLocal -Destination $zipDest
$null=Invoke-CheckedGit $returnRepo @('pull','--rebase','origin',$returnBranch)
$null=Invoke-CheckedGit $returnRepo @('add','-f','--',$reportRelative,$zipRelative)
$null=Invoke-CheckedGit $returnRepo @('commit','--only','-s','-m','test: recover beta.7 R15 terminal worker logs','--',$reportRelative,$zipRelative)
$pushed=$false;$lastPushError=$null
for($attempt=1;$attempt -le 3;$attempt++){
    try{$null=Invoke-CheckedGit $returnRepo @('push','origin',$returnBranch);$pushed=$true;break}
    catch{$lastPushError=$_.Exception.Message;if($attempt -lt 3){$null=Invoke-CheckedGit $returnRepo @('pull','--rebase','origin',$returnBranch);Start-Sleep -Seconds (2*$attempt)}}
}
if(-not $pushed){throw "Posthoc evidence push failed after three attempts: $lastPushError"}
$null=Invoke-CheckedGit $returnRepo @('fetch','origin',$returnBranch)
$remote=(Invoke-CheckedGit $returnRepo @('rev-parse',"origin/$returnBranch")|Select-Object -First 1).Trim()
foreach($path in @($reportRelative,$zipRelative)){$local=(Invoke-CheckedGit $returnRepo @('rev-parse',":$path")|Select-Object -First 1).Trim();$remoteBlob=(Invoke-CheckedGit $returnRepo @('rev-parse',"$remote`:$path")|Select-Object -First 1).Trim();if($local -cne $remoteBlob){throw "Remote posthoc blob mismatch: $path"}}
[pscustomobject]@{status='COLLECTED_AND_REMOTELY_VERIFIED';candidate_source_sha=$expectedSource;remote_commit=$remote;archive_sha256=$zip.sha256;selected_file_count=$files.Count;station_changes=$false;rerun=$false}|ConvertTo-Json -Compress
