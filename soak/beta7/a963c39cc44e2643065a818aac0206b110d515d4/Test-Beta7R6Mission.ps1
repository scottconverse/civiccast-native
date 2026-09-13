$ErrorActionPreference='Stop'
$classifier=Join-Path $PSScriptRoot 'TSDuckReportClassifierR6.ps1'
$probe=Join-Path $PSScriptRoot 'Beta7TransportProbeR6.ps1'
. $classifier
. $probe
function New-Report([int[]]$Discontinuities,[int]$Invalid=0,[int]$Transport=0){
    $ids=@(0,32,65,66);$rows=@()
    for($i=0;$i-lt$ids.Count;$i++){$rows+=[pscustomobject]@{id=$ids[$i];packets=[pscustomobject]@{discontinuities=$Discontinuities[$i]}}}
    [pscustomobject]@{ts=[pscustomobject]@{packets=[pscustomobject]@{total=12000;'invalid-syncs'=$Invalid;'transport-errors'=$Transport}};pids=$rows}
}
$zero=Get-Beta7TransportGrade (New-Report @(0,0,0,0)) public 9001
if($zero.verdict-ne'PASS'-or$zero.discontinuities-ne 0){throw 'Zero-counter report did not pass exactly.'}
$join=Get-Beta7TransportGrade (New-Report @(1,1,1,1)) public 9001
if($join.verdict-ne'FAIL'-or$join.discontinuities-ne 4){throw 'Raw discontinuities were incorrectly excused.'}
$mixed=Get-Beta7TransportGrade (New-Report @(1,1,0,1)) education 9002
if($mixed.verdict-ne'FAIL'-or$mixed.discontinuities-ne 3){throw 'Mixed continuity counts were incorrectly excused.'}
$real=Get-Beta7TransportGrade (New-Report @(1,1,2,1)) government 9003
if($real.verdict-ne'FAIL'-or$real.discontinuities-ne 5){throw 'Continuity value above one was incorrectly excused.'}
$invalid=Get-Beta7TransportGrade (New-Report @(1,1,1,1) 1 0) public 9001
if($invalid.verdict-ne'FAIL'){throw 'Invalid sync was incorrectly excused by join classification.'}
$job=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-Beta7SoakR6Job.ps1') -Raw
$start=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakR6Job.ps1') -Raw
$driver=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoakR6.ps1') -Raw
$probeText=Get-Content -LiteralPath $probe -Raw
foreach($token in @("'-P','until','--seconds','35','-P','skip','--seconds','5'",'[ValidateSet(0,5)][int]$WarmupSeconds=5')){if($probeText-notmatch[regex]::Escape($token)){throw "R6 acquisition discard missing $token"}}
foreach($token in @("acquisition-diagnostic'){0}else{5}",'-WarmupSeconds $warmupSeconds')){if($driver-notmatch[regex]::Escape($token)){throw "R6 diagnostic/verdict warmup binding missing $token"}}
foreach($token in @('physical-soak-r5','Preserved R5 plan','Run-BetaExistingTesterSoakR6.ps1','-ReplaceOverlappingTestSchedule','-AllowedOverlapScheduleIds $allowedScheduleIds','-RequireTransportAdmission')){if($job-notmatch[regex]::Escape($token)){throw "R6 retained contract missing $token"}}
foreach($token in @('physical-soak-r5-job.json',"job_state -cne 'FAIL'",'source_sha -cne $expectedSourceSha','ON transport admission did not produce a clean 0/0/0 round on all three channels.')){if($start-notmatch[regex]::Escape($token)){throw "R6 R5 failure guard missing $token"}}
foreach($token in @('Run-BetaExistingTesterSoakR6.ps1','Beta7TransportProbeR6.ps1','TSDuckReportClassifierR6.ps1','physical-soak-r6','PhysicalSoak-R6')){if(($job+$start)-notmatch[regex]::Escape($token)){throw "R6 unique identity missing $token"}}
& (Join-Path $PSScriptRoot 'Start-Beta7SoakR6Job.ps1') -PackageRoot $PSScriptRoot -DryRun|Out-Null
& (Join-Path $PSScriptRoot 'Run-Beta7SoakR6Job.ps1') -IdentityPath (Join-Path $PSScriptRoot 'run-identity.json') -DryRun|Out-Null
'BETA7_R6_MISSION_SELFTEST_PASS'
