$ErrorActionPreference='Stop'
$job=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-Beta7SoakR4Job.ps1') -Raw
$start=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakR4Job.ps1') -Raw
if($job -notmatch [regex]::Escape('$r1PlanData=Get-Content') -or $job -notmatch [regex]::Escape('$r1Plan=@($r1PlanData)')){throw 'R4 does not use the PS5-safe two-step plan-array conversion.'}
foreach($token in @('-ReplaceOverlappingTestSchedule','-AllowedOverlapScheduleIds $allowedScheduleIds','-RequireTransportAdmission','a963c39cc44e2643065a818aac0206b110d515d4')){if($job -notmatch [regex]::Escape($token)){throw "R4 retained contract missing $token"}}
foreach($token in @('physical-soak-r4','PhysicalSoak-R4','Run-Beta7SoakR4Job.ps1','physical-soak-r3')){if(($job+$start) -notmatch [regex]::Escape($token)){throw "R4 identity/preservation missing $token"}}
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('beta7-r4-plan-'+[guid]::NewGuid().ToString('N')+'.json')
try{
    $rows=@(1..180 | ForEach-Object {[pscustomobject]@{schedule_id="schedule-$_";channel_id=$(if($_ -le 60){'public'}elseif($_ -le 120){'education'}else{'government'})}})
    $rows | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $fixture -Encoding utf8
    $planData=Get-Content -LiteralPath $fixture -Raw | ConvertFrom-Json
    $plan=@($planData)
    if($plan.Count -ne 180 -or @($plan.schedule_id | Sort-Object -Unique).Count -ne 180){throw "PS5 JSON fixture did not unroll to 180 unique rows; count=$($plan.Count)"}
}finally{Remove-Item -LiteralPath $fixture -Force -ErrorAction SilentlyContinue}
& (Join-Path $PSScriptRoot 'Start-Beta7SoakR4Job.ps1') -PackageRoot $PSScriptRoot -DryRun | Out-Null
& (Join-Path $PSScriptRoot 'Run-Beta7SoakR4Job.ps1') -IdentityPath (Join-Path $PSScriptRoot 'run-identity.json') -DryRun | Out-Null
Write-Output 'BETA7_R4_MISSION_SELFTEST_PASS'
