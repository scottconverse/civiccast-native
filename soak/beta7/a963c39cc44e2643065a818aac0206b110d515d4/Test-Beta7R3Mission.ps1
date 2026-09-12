$ErrorActionPreference='Stop'
$probe=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Beta7TransportProbe.ps1') -Raw
$driver=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-BetaExistingTesterSoak.ps1') -Raw
$job=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Run-Beta7SoakR3Job.ps1') -Raw
$start=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Start-Beta7SoakR3Job.ps1') -Raw
foreach($token in @("'--receive-timeout','10000'",'AddSeconds(60)','started_utc','deadline_utc','completed_utc','elapsed_seconds','report_exists','exit_code')){if($probe -notmatch [regex]::Escape($token)){throw "Probe lifecycle contract missing $token"}}
if($probe -match 'AddSeconds\(180\)'){throw 'R3 may not relax the 60-second hard deadline.'}
foreach($token in @('Queue[object]','activeTransportRound','worker state/PID changed during serialized transport admission','transportQueue.Count -eq 0')){if($driver -notmatch [regex]::Escape($token)){throw "Serialized driver contract missing $token"}}
foreach($token in @('AllowedOverlapScheduleIds','UNAPPROVED_SCHEDULE_OVERLAP','admissionPending.Values')){if($driver -notmatch [regex]::Escape($token)){throw "R3 bounded cancellation/cleanup contract missing $token"}}
if($job -notmatch '-ReplaceOverlappingTestSchedule' -or $job -notmatch [regex]::Escape('-AllowedOverlapScheduleIds $allowedScheduleIds') -or $job -notmatch '-RequireTransportAdmission' -or $job -match '-ExistingRunRoot'){throw 'R3 job is not the authorized bounded fresh-schedule admitted mission.'}
foreach($token in @('a963c39cc44e2643065a818aac0206b110d515d4','candidate_source_sha','build_source_sha','gate_a_source_sha','native_app_payload_source_sha','upgrade-result.json','180 unique schedule IDs')){if(($job+$start) -notmatch [regex]::Escape($token)){throw "R3 identity/plan binding missing $token"}}
if($job -match 'FETCH-INSTALL|Invoke-Beta7TesterUpgrade|clone.*--quiet'){throw 'R3 must not install, fetch a kit, or clone a replacement return repo.'}
foreach($token in @('physical-soak-r3','PhysicalSoak-R3','Run-Beta7SoakR3Job.ps1')){if(($job+$start) -notmatch [regex]::Escape($token)){throw "R3 identity missing $token"}}
& (Join-Path $PSScriptRoot 'Start-Beta7SoakR3Job.ps1') -PackageRoot $PSScriptRoot -DryRun | Out-Null
& (Join-Path $PSScriptRoot 'Run-Beta7SoakR3Job.ps1') -IdentityPath (Join-Path $PSScriptRoot 'run-identity.json') -DryRun | Out-Null
Write-Output 'BETA7_R3_MISSION_SELFTEST_PASS'
