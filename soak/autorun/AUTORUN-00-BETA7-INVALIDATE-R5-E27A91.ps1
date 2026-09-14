# Stop and invalidate the flawed R5 physical test before issuing a replacement.
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference='Stop'

$expectedHost='DESKTOP-VBMA6O5'
$taskName='CivicCast-Beta7-3e117ff1-OFF4H-R5-E27A91'
$missionNonce='BETA7-3E117FF1-OFF4H-R5-E27A91'
$missionRoot='C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r5-e27a91'
$outputName='physical-soak-off4h-r5-e27a91'
$returnRepo='C:\CivicCastSoak\repo'
$returnBranch='tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
$relativeJob='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/job.json'
$relativeReport='soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r5-e27a91/INVALIDATED.json'
$baseUrl='http://127.0.0.1:8000'
$tokenPath='C:\CivicCastSoak\state\token'
$owned=@('public','education','government')

if($DryRun){
    if(-not(Test-Path -LiteralPath $PSCommandPath -PathType Leaf)){throw 'Invalidation script path is absent.'}
    if($taskName -notmatch 'R5-E27A91$' -or $missionNonce -notmatch 'R5-E27A91$'){throw 'R5 identity binding is inconsistent.'}
    Write-Output 'DRYRUN VERIFIED: R5 invalidation bindings passed; no mutation performed.'
    return
}
if($env:COMPUTERNAME -ine $expectedHost){throw "This invalidation order targets $expectedHost only."}
if(-not(Test-Path -LiteralPath $tokenPath -PathType Leaf)){throw "Tester token is absent: $tokenPath"}
$token=(Get-Content -LiteralPath $tokenPath -Raw).Trim()
if(-not $token){throw 'Tester token is empty.'}

function Invoke-Station([string]$Method,[string]$Path,$Body=$null,[int]$TimeoutSec=120){
    $arguments=@{Method=$Method;Uri=$baseUrl.TrimEnd('/')+$Path;TimeoutSec=$TimeoutSec;ErrorAction='Stop';Headers=@{Authorization='Bearer '+$token}}
    if($null -ne $Body){$arguments.ContentType='application/json';$arguments.Body=$Body|ConvertTo-Json -Depth 20 -Compress}
    Invoke-RestMethod @arguments
}
function Test-JsonValueEqual($Left,$Right){
    if($null -eq $Left -or $null -eq $Right){return $null -eq $Left -and $null -eq $Right}
    $leftObject=$Left -is [pscustomobject];$rightObject=$Right -is [pscustomobject]
    if($leftObject -or $rightObject){
        if(-not($leftObject -and $rightObject)){return $false}
        $leftNames=@($Left.PSObject.Properties.Name|Sort-Object);$rightNames=@($Right.PSObject.Properties.Name|Sort-Object)
        if($leftNames.Count -ne $rightNames.Count -or (($leftNames-join "`0") -cne ($rightNames-join "`0"))){return $false}
        foreach($name in $leftNames){if(-not(Test-JsonValueEqual $Left.$name $Right.$name)){return $false}}
        return $true
    }
    $leftArray=$Left -is [array];$rightArray=$Right -is [array]
    if($leftArray -or $rightArray){
        if(-not($leftArray -and $rightArray)){return $false}
        if($Left.Count -ne $Right.Count){return $false}
        for($index=0;$index -lt $Left.Count;$index++){if(-not(Test-JsonValueEqual $Left[$index] $Right[$index])){return $false}}
        return $true
    }
    return $Left -ceq $Right
}
function Test-ConfigPreservedExceptControl($Original,$Observed){
    $left=$Original|ConvertTo-Json -Depth 20 -Compress|ConvertFrom-Json
    $right=$Observed|ConvertTo-Json -Depth 20 -Compress|ConvertFrom-Json
    foreach($name in @('enabled','auto_start')){$left.PSObject.Properties.Remove($name);$right.PSObject.Properties.Remove($name)}
    Test-JsonValueEqual $left $right
}
function Get-ServiceIdentity {
    $service=Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction Stop
    if($service.State -ne 'Running' -or [int]$service.ProcessId -le 0){throw 'CivicCastSupervisor is not running.'}
    $process=Get-Process -Id ([int]$service.ProcessId) -ErrorAction Stop
    [pscustomobject]@{pid=[int]$service.ProcessId;started_utc=$process.StartTime.ToUniversalTime().ToString('o');path=[string]$service.PathName}
}
function Wait-HealthyService([int]$PreviousPid){
    $deadline=[datetime]::UtcNow.AddMinutes(3);$lastError=$null
    do{
        try{
            $health=Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 10 -ErrorAction Stop
            $identity=Get-ServiceIdentity
            if($identity.pid -ne $PreviousPid -and $health.status -eq 'healthy' -and "$($health.schema)" -eq 'current' -and "$($health.version)" -eq '1.0.0-beta.7'){
                return [pscustomobject]@{service=$identity;health=$health}
            }
        }catch{$lastError=$_.Exception.Message}
        Start-Sleep -Seconds 2
    }while([datetime]::UtcNow -lt $deadline)
    throw "CivicCastSupervisor did not return as exact beta.7 with a new PID. Last error: $lastError"
}
function Restart-AndVerify([int]$PreviousPid){
    Restart-Service -Name 'CivicCastSupervisor' -Force -ErrorAction Stop
    Wait-HealthyService -PreviousPid $PreviousPid
}
function Set-ControlConfig([hashtable]$Originals,[bool]$Enabled){
    foreach($channel in $owned){
        $config=$Originals[$channel]|ConvertTo-Json -Depth 20 -Compress|ConvertFrom-Json
        $config.enabled=$Enabled;$config.auto_start=$false
        $written=Invoke-Station PUT "/api/staff/egress/channels/$channel/config" $config
        if([bool]$written.enabled -ne $Enabled -or [bool]$written.auto_start){throw "Control config did not persist for $channel."}
        if(-not(Test-ConfigPreservedExceptControl $Originals[$channel] $written)){throw "Non-control config changed for $channel."}
        $readback=Invoke-Station GET "/api/staff/egress/channels/$channel/config"
        if([bool]$readback.enabled -ne $Enabled -or [bool]$readback.auto_start){throw "Control config readback failed for $channel."}
        if(-not(Test-ConfigPreservedExceptControl $Originals[$channel] $readback)){throw "Non-control config readback changed for $channel."}
    }
}
function Stop-AndAcknowledgeChannels([hashtable]$Originals){
    $receipts=@{};$beforeStates=@{}
    foreach($channel in $owned){
        $beforeStates[$channel]=Invoke-Station GET "/api/staff/egress/channels/$channel/state"
        $response=Invoke-Station POST "/api/staff/egress/channels/$channel/commands" @{action='stop'}
        if(-not $response.queued -or "$($response.command.action)" -ne 'stop' -or -not $response.command.command_id){throw "Stop command was not queued for $channel."}
        $receipts[$channel]=$response.command
    }
    $deadline=[datetime]::UtcNow.AddMinutes(3);$states=@{}
    do{
        $remaining=@()
        foreach($channel in $owned){
            $state=Invoke-Station GET "/api/staff/egress/channels/$channel/state"
            $issued=[datetimeoffset]::Parse([string]$receipts[$channel].issued_at).UtcDateTime
            $beforeUpdated=[datetimeoffset]::Parse([string]$beforeStates[$channel].updated_at).UtcDateTime
            $updated=[datetimeoffset]::Parse([string]$state.updated_at).UtcDateTime
            if("$($state.state)" -eq 'STOPPED' -and -not $state.pid -and $updated -gt $issued -and $updated -gt $beforeUpdated){$states[$channel]=$state}else{$remaining+=$channel}
        }
        if(-not $remaining.Count){break}
        Start-Sleep -Seconds 2
    }while([datetime]::UtcNow -lt $deadline)
    if($remaining.Count){throw "Terminal stop commands were not acknowledged by state updates for: $($remaining -join ',')."}
    foreach($channel in $owned){
        $config=Invoke-Station GET "/api/staff/egress/channels/$channel/config"
        if(-not[bool]$config.enabled -or [bool]$config.auto_start){throw "Final config is not enabled=true, auto_start=false for $channel."}
        if(-not(Test-ConfigPreservedExceptControl $Originals[$channel] $config)){throw "Final non-control config changed for $channel."}
    }
    [pscustomobject]@{states_before_command=$beforeStates;commands=$receipts;acknowledged_states=$states}
}
function Stop-R5TaskAndProcesses {
    $task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if($task){
        Disable-ScheduledTask -TaskName $taskName -ErrorAction Stop|Out-Null
    }
    $deadline=[datetime]::UtcNow.AddMinutes(2)
    do{
        $task=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        $running=@(Get-CimInstance Win32_Process -ErrorAction Stop|Where-Object{
            $_.CommandLine -and $_.CommandLine.IndexOf($missionRoot,[StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf($outputName,[StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        foreach($process in $running){
            $null=& "$env:SystemRoot\System32\taskkill.exe" /PID ([string]$process.ProcessId) /T /F 2>&1
            if($LASTEXITCODE -notin @(0,128)){throw "taskkill failed for exact R5 process $($process.ProcessId) with exit $LASTEXITCODE."}
        }
        if($task){Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue}
        if(((-not $task) -or "$($task.State)" -eq 'Disabled') -and -not $running.Count){return [pscustomobject]@{task_present=[bool]$task;task_state=if($task){[string]$task.State}else{'Absent'}}}
        Start-Sleep -Seconds 2
    }while([datetime]::UtcNow -lt $deadline)
    throw 'R5 scheduled task or its exact job process remained running.'
}
function Cancel-R5OwnedSchedule {
    $outputRoot=Join-Path $missionRoot $outputName
    $runs=if(Test-Path -LiteralPath $outputRoot){@(Get-ChildItem -LiteralPath $outputRoot -Directory)}else{@()}
    if($runs.Count -gt 1){throw 'R5 output contains more than one run directory.'}
    if(-not $runs.Count){return [pscustomobject]@{run_id=$null;planned=0;cancelled=@();outstanding=@();note='No R5 run directory existed.'}}
    $identityPath=Join-Path $runs[0].FullName 'IDENTITY.json';$planPath=Join-Path $runs[0].FullName 'published-plan.json'
    if(-not(Test-Path -LiteralPath $identityPath -PathType Leaf)){return [pscustomobject]@{run_id=$null;planned=0;cancelled=@();outstanding=@();note='R5 run had no identity receipt.'}}
    $runIdentity=Get-Content -LiteralPath $identityPath -Raw|ConvertFrom-Json
    $runId=[string]$runIdentity.run_id
    if(-not $runId){throw 'R5 run identity has no run_id.'}
    if("$($runIdentity.source_sha)" -ne '3e117ff1fa9e06873ecec5b5b07f1360bc8b228d' -or [int]$runIdentity.minutes_per_phase -ne 240 -or (@($runIdentity.phases) -join ',') -ne 'OFF'){throw 'R5 run identity does not match the exact candidate, duration, and captions-OFF phase.'}
    $plan=if(Test-Path -LiteralPath $planPath -PathType Leaf){@(Get-Content -LiteralPath $planPath -Raw|ConvertFrom-Json)}else{@()}
    $planIds=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $planById=@{}
    foreach($entry in $plan){
        if(-not $entry.schedule_id -or -not $planIds.Add([string]$entry.schedule_id)){throw 'R5 published plan contains a missing or duplicate schedule ID.'}
        $planById[[string]$entry.schedule_id]=$entry
    }
    $cancelled=[Collections.Generic.List[object]]::new();$outstanding=[Collections.Generic.List[object]]::new()
    foreach($channel in $owned){
        $rows=@(Invoke-Station GET "/api/staff/schedule?channel_id=$channel")
        foreach($row in @($rows|Where-Object{"$($_.notes)" -ceq "Owned $runId" -and "$($_.state)" -in @('scheduled','published')})){
            if(-not $planIds.Contains([string]$row.id)){$outstanding.Add($row);continue}
            $expected=$planById[[string]$row.id]
            $actualAt=[datetimeoffset]::Parse([string]$row.scheduled_at).UtcDateTime
            $expectedAt=[datetimeoffset]::Parse([string]$expected.scheduled_at).UtcDateTime
            if("$($row.channel_id)" -ne "$($expected.channel_id)" -or "$($row.asset_id)" -ne "$($expected.asset_id)" -or $actualAt -ne $expectedAt -or "$($row.mode)" -ne 'premiere' -or [int]$row.duration_seconds -ne 300){throw "R5 live schedule $($row.id) does not match its preserved plan and fixed premiere contract."}
            $result=Invoke-Station POST "/api/staff/schedule/$($row.id)/cancel" $null
            if("$($result.state)" -ne 'cancelled'){throw "R5 schedule $($row.id) did not cancel."}
            $cancelled.Add([pscustomobject]@{channel_id=$channel;schedule_id=[string]$row.id;state=[string]$result.state})
        }
    }
    if($outstanding.Count){throw "R5 has $($outstanding.Count) exact-owned live schedule rows absent from its published plan; they were preserved for investigation."}
    [pscustomobject]@{run_id=$runId;planned=$planIds.Count;cancelled=@($cancelled);outstanding=@();note='Only exact R5-owned rows present in the preserved published plan were cancelled.'}
}
function Publish-Invalidation($Report){
    if(-not(Test-Path -LiteralPath (Join-Path $returnRepo '.git'))){throw 'Tester evidence repository is absent.'}
    function Invoke-Git([string[]]$Arguments){
        $output=@(& git -C $returnRepo @Arguments 2>&1)
        if($LASTEXITCODE -ne 0){throw "git $($Arguments -join ' ') failed: $($output -join ' ')"}
        $output
    }
    $synced=$false;$lastSyncError=$null
    for($attempt=1;$attempt -le 3 -and -not $synced;$attempt++){
        try{$null=Invoke-Git @('pull','--rebase','--autostash','origin',$returnBranch);$synced=$true}catch{$lastSyncError=$_.Exception.Message;if($attempt -lt 3){Start-Sleep -Seconds (2*$attempt)}}
    }
    if(-not $synced){throw "Could not synchronize tester evidence after three attempts: $lastSyncError"}
    $target=Join-Path $returnRepo ($relativeReport -replace '/','\')
    $jobTarget=Join-Path $returnRepo ($relativeJob -replace '/','\')
    New-Item -ItemType Directory -Path (Split-Path $target) -Force|Out-Null
    if(Test-Path -LiteralPath $target -PathType Leaf){throw 'An R5 invalidation receipt already exists; preserve and inspect it instead of overwriting.'}
    if(Test-Path -LiteralPath $jobTarget -PathType Leaf){
        $existingJob=Get-Content -LiteralPath $jobTarget -Raw|ConvertFrom-Json
        if("$($existingJob.mission_nonce)" -ne $missionNonce -or "$($existingJob.job_state)" -eq 'INVALIDATED'){throw 'Existing R5 job record belongs to another mission or is already invalidated; preserve it.'}
    }
    [IO.File]::WriteAllText($target,($Report|ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
    $job=[ordered]@{hostname=$Report.hostname;source_sha=$Report.candidate_source_sha;mission_nonce=$Report.mission_nonce;job_started_utc=$Report.started_utc;job_state=if($Report.status -eq 'R5_INVALIDATED'){'INVALIDATED'}else{'INVALIDATION_FAILED'};result=$null;error=if($Report.error){$Report.error}else{'R5 harness invalidated by independent audit; it is not release evidence.'};finished_utc=$Report.finished_utc;invalidation_receipt='INVALIDATED.json'}
    [IO.File]::WriteAllText($jobTarget,($job|ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
    $null=Invoke-Git @('add','-f','--',$relativeReport,$relativeJob)
    $null=Invoke-Git @('commit','--only','-s','-m','test: invalidate flawed beta.7 R5 gate','--',$relativeReport,$relativeJob)
    $pushed=$false;$lastPushError=$null
    for($attempt=1;$attempt -le 3 -and -not $pushed;$attempt++){
        try{
            if($attempt -gt 1){$null=Invoke-Git @('pull','--rebase','--autostash','origin',$returnBranch)}
            $null=Invoke-Git @('push','origin',$returnBranch);$pushed=$true
        }catch{$lastPushError=$_.Exception.Message;if($attempt -lt 3){Start-Sleep -Seconds (2*$attempt)}}
    }
    if(-not $pushed){throw "Could not push tester invalidation after three attempts: $lastPushError"}
    $null=Invoke-Git @('fetch','origin',$returnBranch)
    $remoteCommit=(Invoke-Git @('rev-parse',"origin/$returnBranch")|Select-Object -First 1).Trim()
    $remoteReceiptBlob=(Invoke-Git @('rev-parse',"$remoteCommit`:$relativeReport")|Select-Object -First 1).Trim()
    $remoteJobBlob=(Invoke-Git @('rev-parse',"$remoteCommit`:$relativeJob")|Select-Object -First 1).Trim()
    $localReceiptBlob=(Invoke-Git @('rev-parse',":$relativeReport")|Select-Object -First 1).Trim()
    $localJobBlob=(Invoke-Git @('rev-parse',":$relativeJob")|Select-Object -First 1).Trim()
    if($remoteReceiptBlob -cne $localReceiptBlob -or $remoteJobBlob -cne $localJobBlob){throw 'Remote invalidation blobs do not match the exact local receipt and job record.'}
    $remoteJob=@(Invoke-Git @('show',"$remoteCommit`:$relativeJob")) -join "`n"
    if($remoteJob -notmatch '"job_state"\s*:\s*"INVALIDATED"' -and $Report.status -eq 'R5_INVALIDATED'){throw 'Remote R5 job record was not invalidated.'}
    $remoteCommit
}

$directiveRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$directiveCommit=(& git -C $directiveRoot rev-parse HEAD).Trim()
if($LASTEXITCODE -ne 0){throw 'Could not bind the invalidation order to its directive commit.'}
$report=[ordered]@{schema='civiccast-beta7-test-invalidation-v1';status='INVALIDATION_STARTED';hostname=[string]$env:COMPUTERNAME;mission_nonce=$missionNonce;candidate_source_sha='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d';directive_commit=$directiveCommit;invalid_reasons=@('stale-auto-start race','non-stall worker exit false pass','final sample gap','cleanup false pass','evidence publication false pass','embargo overlap false fail','unbound harness/topology provenance','impossible transport cadence: six possible rounds but eight required');started_utc=[datetime]::UtcNow.ToString('o');script_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()}
$failure=$null
try{
    $report.task=Stop-R5TaskAndProcesses
    $originals=@{}
    foreach($channel in $owned){$originals[$channel]=Invoke-Station GET "/api/staff/egress/channels/$channel/config"}
    $before=Get-ServiceIdentity
    Set-ControlConfig -Originals $originals -Enabled $false
    $disabledRestart=Restart-AndVerify -PreviousPid $before.pid
    Set-ControlConfig -Originals $originals -Enabled $true
    $enabledRestart=Restart-AndVerify -PreviousPid $disabledRestart.service.pid
    $report.service_barrier=@{before=$before;disabled_restart=$disabledRestart.service;enabled_restart=$enabledRestart.service}
    $report.terminal_before_schedule_cleanup=Stop-AndAcknowledgeChannels -Originals $originals
    $report.schedule_cleanup=Cancel-R5OwnedSchedule
    $report.terminal_final=Stop-AndAcknowledgeChannels -Originals $originals
    $report.status='R5_INVALIDATED'
}catch{
    $failure=[string]$_.Exception.Message
    $report.status='INVALIDATION_FAILED';$report.error=$failure
}
$report.finished_utc=[datetime]::UtcNow.ToString('o')
$report.remote_commit=Publish-Invalidation $report
Write-Output ($report|ConvertTo-Json -Depth 20)
if($failure){throw "R5 invalidation failed after publishing its receipt: $failure"}
