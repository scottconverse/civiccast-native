$ErrorActionPreference='Stop'
$job=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-Beta7SoakR5Job.ps1') -Raw
$start=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakR5Job.ps1') -Raw
foreach($token in @('$r1PlanData=Get-Content','$r1Plan=@($r1PlanData)','-ReplaceOverlappingTestSchedule','-AllowedOverlapScheduleIds $allowedScheduleIds','-RequireTransportAdmission')){if($job -notmatch [regex]::Escape($token)){throw "R5 retained contract missing $token"}}
foreach($token in @('physical-soak-r3-job.json',"job_state -cne 'FAIL'",'source_sha -cne $expectedSourceSha')){if($start -notmatch [regex]::Escape($token)){throw "R5 R3 receipt guard missing $token"}}
if($start -match [regex]::Escape("Join-Path $missionRoot 'physical-soak-r3'")){throw 'R5 incorrectly requires an R3 output directory.'}
if($start -match [regex]::Escape("Join-Path $missionRoot 'physical-soak-r4'")){throw 'R5 incorrectly requires an R4 output directory.'}
foreach($token in @('physical-soak-r5','PhysicalSoak-R5','Run-Beta7SoakR5Job.ps1')){if(($job+$start) -notmatch [regex]::Escape($token)){throw "R5 unique identity missing $token"}}
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('beta7-r5-plan-'+[guid]::NewGuid().ToString('N')+'.json')
try{$rows=@(1..180|%{[pscustomobject]@{schedule_id="schedule-$_"}});$rows|ConvertTo-Json|Set-Content $fixture -Encoding utf8;$data=Get-Content $fixture -Raw|ConvertFrom-Json;$plan=@($data);if($plan.Count-ne 180){throw "PS5 fixture count=$($plan.Count)"}}finally{Remove-Item $fixture -Force -ErrorAction SilentlyContinue}
& (Join-Path $PSScriptRoot 'Start-Beta7SoakR5Job.ps1') -PackageRoot $PSScriptRoot -DryRun|Out-Null
& (Join-Path $PSScriptRoot 'Run-Beta7SoakR5Job.ps1') -IdentityPath (Join-Path $PSScriptRoot 'run-identity.json') -DryRun|Out-Null
'BETA7_R5_MISSION_SELFTEST_PASS'
