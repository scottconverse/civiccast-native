# Exercises the existing dedicated tester through supported APIs after candidate installation.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$BaseUrl,
    [Parameter(Mandatory)][string]$OutputRoot,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceSha,
    [string]$TokenPath = 'C:\CivicCastSoak\state\token',
    [ValidateRange(120,480)][int]$Minutes = 120,
    [ValidateSet('ON','OFF','Both')][string]$Mode = 'Both',
    [string]$ProgramDataRoot = 'C:\ProgramData\CivicCast',
    [string]$TspExe = 'C:\CivicCastHostStore\install\packs\native-server-binaries\payload\tsduck\bin\tsp.exe',
    [switch]$ReplaceOverlappingTestSchedule,
    [string[]]$AllowedOverlapScheduleIds=@(),
    [string]$ExistingRunRoot,
    [switch]$RequireTransportAdmission,
    [scriptblock]$OnPhaseStarted,
    [switch]$SelfTest,
    [hashtable]$ExpectedElementsPerPhase=@{}
)
$ErrorActionPreference = 'Stop'
# Preserve this driver's optional-field handling when invoked by strict helpers.
Set-StrictMode -Off
$expectedTesterHostname = 'DESKTOP-VBMA6O5'
if (-not $SelfTest -and $env:COMPUTERNAME -ine $expectedTesterHostname) { throw "This existing-tester soak targets $expectedTesterHostname only." }
$runId = 'f2hw-' + (Get-Date -Format 'yyMMddHHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6)
$runRoot = Join-Path $OutputRoot $runId
$token = $null
$owned = @()
$transportPending = @{}
$admissionPending = @{}
$cleanupVerified = $false
$cleanupFailure = $null
$barrierConfigs = @{}
$createdScheduleIds = @()
$channels = @(@{id='public';port=9001}, @{id='education';port=9002}, @{id='government';port=9003})
$phases = if ($Mode -eq 'Both') { @('ON','OFF') } else { @($Mode) }
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
function Save-Result($Value, [string]$RelativePath) {
    $destination = Join-Path $runRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $destination -Encoding utf8
}
function ConvertTo-WholeSecondUtc([datetime]$Value) {
    return $Value.ToUniversalTime().AddTicks(-($Value.ToUniversalTime().Ticks % [timespan]::TicksPerSecond))
}
function Write-ProgressLog([string]$Message) {
    $line = (Get-Date -Format 'yyyy-MM-dd h:mm:ss tt') + ' Mountain: ' + $Message
    Add-Content -LiteralPath (Join-Path $runRoot 'progress.log') -Value $line -Encoding utf8
    Write-Host $line
}
function Invoke-Station([string]$Method, [string]$Path, $Body=$null, [int]$Timeout=120) {
    $arguments = @{Method=$Method; Uri=$BaseUrl.TrimEnd('/')+$Path; TimeoutSec=$Timeout; ErrorAction='Stop'}
    if ($token) { $arguments.Headers = @{Authorization='Bearer '+$token} }
    if ($null -ne $Body) { $arguments.ContentType='application/json'; $arguments.Body=$Body | ConvertTo-Json -Depth 12 -Compress }
    # Do not log request/response bodies: bootstrap and authentication responses contain secrets.
    # PowerShell 5.1 emits a REST JSON array as one pipeline object. Capture
    # then return it so collection callers receive its individual rows.
    $response = Invoke-RestMethod @arguments
    return $response
}
function Upload-Sample($File, [string]$AssetId, [string]$Title) {
    Add-Type -AssemblyName System.Net.Http
    $client = [Net.Http.HttpClient]::new()
    $client.Timeout = [timespan]::FromMinutes(20)
    $client.DefaultRequestHeaders.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer',$token)
    $form = [Net.Http.MultipartFormDataContent]::new()
    $stream = [IO.File]::OpenRead($File.FullName)
    try {
        $form.Add([Net.Http.StringContent]::new($AssetId),'asset_id')
        $form.Add([Net.Http.StringContent]::new($Title),'title')
        $form.Add([Net.Http.StreamContent]::new($stream),'file',$File.Name)
        $response = $client.PostAsync($BaseUrl.TrimEnd('/')+'/api/staff/assets/upload',$form).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw "Upload $AssetId returned HTTP $([int]$response.StatusCode)" }
        $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
    } finally { $form.Dispose(); $stream.Dispose(); $client.Dispose() }
}
function Test-QuiescentChannelState($State) {
    if (-not $State) { return $false }
    return ([string]$State.state -eq 'STOPPED') -and -not $State.pid
}
function Test-QuiescentChannelConfig($Config) {
    if (-not $Config) { return $false }
    return [bool]$Config.enabled -and -not [bool]$Config.auto_start
}
function Test-DisabledQuiescentChannelConfig($Config) {
    if (-not $Config) { return $false }
    return (-not [bool]$Config.enabled) -and (-not [bool]$Config.auto_start)
}
function Test-JsonValueEqual($Left, $Right) {
    if ($null -eq $Left -or $null -eq $Right) { return $null -eq $Left -and $null -eq $Right }
    $leftObject=$Left -is [pscustomobject]
    $rightObject=$Right -is [pscustomobject]
    if ($leftObject -or $rightObject) {
        if (-not ($leftObject -and $rightObject)) { return $false }
        $leftNames=@($Left.PSObject.Properties.Name | Sort-Object)
        $rightNames=@($Right.PSObject.Properties.Name | Sort-Object)
        if ($leftNames.Count -ne $rightNames.Count -or (($leftNames -join "`0") -cne ($rightNames -join "`0"))) { return $false }
        foreach ($name in $leftNames) {
            if (-not (Test-JsonValueEqual $Left.$name $Right.$name)) { return $false }
        }
        return $true
    }
    $leftArray=$Left -is [array]
    $rightArray=$Right -is [array]
    if ($leftArray -or $rightArray) {
        if (-not ($leftArray -and $rightArray)) { return $false }
        if ($Left.Count -ne $Right.Count) { return $false }
        for ($i=0; $i -lt $Left.Count; $i++) {
            if (-not (Test-JsonValueEqual $Left[$i] $Right[$i])) { return $false }
        }
        return $true
    }
    return $Left -ceq $Right
}
function Test-ConfigSemanticallyPreserved($Original, $Observed) {
    if (-not $Original -or -not $Observed) { return $false }
    # JSON round-tripping restricts comparison to the API payload surface and
    # makes nested PSCustomObject/array handling deterministic. Property order
    # is ignored by Test-JsonValueEqual; array order and every value are kept.
    $left=$Original | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
    $right=$Observed | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
    $left.PSObject.Properties.Remove('auto_start')
    $right.PSObject.Properties.Remove('auto_start')
    return Test-JsonValueEqual $left $right
}
function Test-ConfigPreservedForBarrier($Original, $Observed) {
    if (-not $Original -or -not $Observed) { return $false }
    $left=$Original | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
    $right=$Observed | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
    $left.PSObject.Properties.Remove('auto_start')
    $right.PSObject.Properties.Remove('auto_start')
    $left.PSObject.Properties.Remove('enabled')
    $right.PSObject.Properties.Remove('enabled')
    return Test-JsonValueEqual $left $right
}
function Get-SupervisorPid {
    $service = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'" -ErrorAction Stop
    if (-not $service -or [int]$service.ProcessId -le 0) { throw 'CivicCastSupervisor has no live process.' }
    return [int]$service.ProcessId
}
function Wait-HealthySupervisor([int]$PreviousPid) {
    $deadline=[datetime]::UtcNow.AddMinutes(2)
    do {
        try {
            $service=Get-Service -Name CivicCastSupervisor -ErrorAction Stop
            $pid=Get-SupervisorPid
            $health=Invoke-Station -Method GET -Path '/health' -Timeout 20
            if ($service.Status -eq 'Running' -and $pid -ne $PreviousPid -and $health.status -eq 'healthy' -and $health.schema -eq 'current' -and $health.version -eq '1.0.0-beta.7') { return $pid }
        } catch { }
        Start-Sleep -Seconds 2
    } while ([datetime]::UtcNow -lt $deadline)
    throw "CivicCastSupervisor did not return healthy with a new PID (previous=$PreviousPid)."
}
function Restart-SupervisorAndVerify([string]$Reason) {
    $oldPid=Get-SupervisorPid
    Write-ProgressLog "Restarting CivicCastSupervisor for $Reason (old_pid=$oldPid)."
    Restart-Service -Name CivicCastSupervisor -Force -ErrorAction Stop
    $newPid=Wait-HealthySupervisor $oldPid
    Save-Result @{reason=$Reason;old_pid=$oldPid;new_pid=$newPid;at=[datetime]::UtcNow.ToString('o')} "barrier-$(([guid]::NewGuid()).ToString('N')).json"
    return $newPid
}
function Set-OwnedChannelsQuiescentIntent {
    foreach ($channel in $owned) {
        $config = Invoke-Station GET "/api/staff/egress/channels/$channel/config"
        if (-not $config -or -not [bool]$config.enabled) { throw "Owned channel $channel must be enabled before it can be quiesced." }
        $originalConfig=$config | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
        $barrierConfigs[$channel]=$originalConfig
        $config.enabled=$false; $config.auto_start=$false
        $written = Invoke-Station PUT "/api/staff/egress/channels/$channel/config" $config
        if (-not (Test-DisabledQuiescentChannelConfig $written) -or -not (Test-ConfigPreservedForBarrier $originalConfig $written)) { throw "Owned channel $channel disabled quiescent intent did not preserve full config." }
        $readback = Invoke-Station GET "/api/staff/egress/channels/$channel/config"
        if (-not (Test-DisabledQuiescentChannelConfig $readback) -or -not (Test-ConfigPreservedForBarrier $originalConfig $readback)) { throw "Owned channel $channel disabled quiescent readback failed." }
    }
}
function Stop-OwnedChannels {
    Set-OwnedChannelsQuiescentIntent
    $null=Restart-SupervisorAndVerify 'disabled-auto-start barrier'
    foreach ($channel in $owned) {
        $restore=$barrierConfigs[$channel] | ConvertTo-Json -Depth 20 -Compress | ConvertFrom-Json
        $restore.enabled=$true; $restore.auto_start=$false
        $written=Invoke-Station PUT "/api/staff/egress/channels/$channel/config" $restore
        if (-not (Test-QuiescentChannelConfig $written) -or -not (Test-ConfigPreservedForBarrier $barrierConfigs[$channel] $written)) { throw "Owned channel $channel restore readback failed." }
        $readback=Invoke-Station GET "/api/staff/egress/channels/$channel/config"
        if (-not (Test-QuiescentChannelConfig $readback) -or -not (Test-ConfigPreservedForBarrier $barrierConfigs[$channel] $readback)) { throw "Owned channel $channel full config did not survive restore." }
    }
    $null=Restart-SupervisorAndVerify 'restored-config barrier'
    $preStates=@{}; $issued=@{}
    foreach ($channel in $owned) {
        $preStates[$channel]=Invoke-Station GET "/api/staff/egress/channels/$channel/state"
        $response=Invoke-Station POST "/api/staff/egress/channels/$channel/commands" @{action='stop'}
        $command=if($response.command){$response.command}else{$response}
        if (-not $command -or "$($command.action)" -ne 'stop' -or -not $command.issued_at) { throw "Stop command for $channel had no verifiable issue receipt." }
        $issued[$channel]=[datetimeoffset]::Parse([string]$command.issued_at).UtcDateTime
    }
    $deadline = [datetime]::UtcNow.AddMinutes(2)
    $consecutive=0
    do {
        Start-Sleep -Seconds 2
        $remaining=@()
        foreach ($channel in $owned) {
            $state=Invoke-Station GET "/api/staff/egress/channels/$channel/state"
            $updated=$null; $before=$null
            try {$updated=[datetimeoffset]::Parse([string]$state.updated_at).UtcDateTime} catch {}
            try {$before=[datetimeoffset]::Parse([string]$preStates[$channel].updated_at).UtcDateTime} catch {}
            if (-not (Test-QuiescentChannelState $state) -or $null -eq $updated -or $updated -le $before -or $updated -le $issued[$channel]) { $remaining += $channel }
        }
        if (-not $remaining.Count) { $consecutive++ } else { $consecutive=0 }
        if ($consecutive -ge 2) {
            foreach($channel in $owned) {
                $finalConfig=Invoke-Station GET "/api/staff/egress/channels/$channel/config"
                if (-not (Test-QuiescentChannelConfig $finalConfig) -or -not (Test-ConfigPreservedForBarrier $barrierConfigs[$channel] $finalConfig)) { throw "Owned channel $channel final stop config verification failed." }
            }
            return
        }
    } while ([datetime]::UtcNow -lt $deadline)
    throw "Owned channels did not reach a post-command STOPPED/no-PID state: $($remaining -join ',')"
}
function Get-BoundaryGrades($Plan, $Samples, [datetime]$Begin, [datetime]$End) {
    foreach ($slot in $Plan) {
        $at = [datetimeoffset]::Parse($slot.scheduled_at).UtcDateTime
        if ($at -lt $Begin -or $at -ge $End) { continue }
        $hit = @($Samples | Where-Object {
            $_.channel -eq $slot.channel_id -and $_.source_label -eq $slot.asset_label -and
            [datetimeoffset]::Parse($_.at).UtcDateTime -ge $at -and
            [datetimeoffset]::Parse($_.at).UtcDateTime -lt $at.AddMinutes(5)
        } | Select-Object -First 1)
        $delay = if ($hit.Count) { ([datetimeoffset]::Parse($hit[0].at).UtcDateTime-$at).TotalSeconds } else { $null }
        $passed = $null -ne $delay -and $delay -le 30
        $explanation = if ($null -eq $delay) { 'missing_observation' } elseif ($delay -le 30) { 'changed_within_30_seconds' } else { 'late_observation' }
        [pscustomobject]@{channel=$slot.channel_id; scheduled_at=$slot.scheduled_at; asset_id=$slot.asset_id;
            expected_label=$slot.asset_label; delay_seconds=$delay; pass=$passed; explanation=$explanation}
    }
}
function Get-Beta7FailureGrades($Logs, $ExpectedElementsPerChannel=@{}) {
    $f1 = @(); $f3 = @(); $transactionErrors = @(); $transactions=@{}; $firing=@{}
    $stdoutCommitCounts=@{}; $diagnosticCommitCounts=@{}; $diagnosticStage=@{}
    foreach ($log in @($Logs)) {
        $channelMatch=[regex]::Match([string]$log.path,'(?i)(public|education|government)')
        $channel = if ($channelMatch.Success) { $channelMatch.Groups[1].Value.ToLowerInvariant() } else { 'unknown' }
        $isStdout=([string]$log.path -match '(?i)gst-worker\.stdout\.log$')
        $isStderr=([string]$log.path -match '(?i)gst-worker\.stderr\.log$')
        foreach ($line in @(([string]$log.text -split "`r?`n"))) {
            if ($line -match '(?i)\bWORKER_RESULT\b') { $f1 += [string]$line }
            if ($line -match '(?i)reload-commit-timeout') { $f1 += [string]$line }
            if ($isStdout -and $line -match 'new leg stream held at its first buffer \((\d+) stream\(s\) still to preroll\) \(reload_id=(\d+)\)') {
                $remaining=[int]$Matches[1]; $reloadId=[string]$Matches[2]; $key="$channel|$reloadId"
                if (-not $transactions.ContainsKey($key)) { $transactions[$key]=@{hold_stage=0;seen_remaining_one=$false;seen_remaining_zero=$false;preroll_valid=$false;fired=$false;rebase_valid=$false} }
                if ($remaining -eq 1) {
                    if ([int]$transactions[$key].hold_stage -ne 0) { $transactionErrors += "Out-of-order first hold receipt on $channel reload_id=$reloadId" }
                    $transactions[$key].seen_remaining_one=$true; $transactions[$key].hold_stage=1
                }
                if ($remaining -eq 0) {
                    if ([int]$transactions[$key].hold_stage -ne 1) { $transactionErrors += "Out-of-order final hold receipt on $channel reload_id=$reloadId" }
                    $transactions[$key].seen_remaining_zero=$true; $transactions[$key].hold_stage=2
                }
            }
            if ($isStdout -and $line -match 'preroll verified \(reload_id=(\d+)\) held_streams=(\d+) timing=([^\s]+)') {
                $reloadId=[string]$Matches[1]; $heldStreams=[int]$Matches[2]; $timing=[string]$Matches[3]; $key="$channel|$reloadId"
                if (-not $transactions.ContainsKey($key)) { $transactions[$key]=@{hold_stage=0;seen_remaining_one=$false;seen_remaining_zero=$false;preroll_valid=$false;fired=$false;rebase_valid=$false} }
                $transactions[$key].preroll_valid=($heldStreams -eq 2 -and $timing -eq 'finite' -and [int]$transactions[$key].hold_stage -eq 2 -and $transactions[$key].seen_remaining_one -and $transactions[$key].seen_remaining_zero)
                if (-not $transactions[$key].preroll_valid) { $transactionErrors += "Invalid preroll receipt on $channel reload_id=$reloadId`: held_streams=$heldStreams timing=$timing remaining_one=$($transactions[$key].seen_remaining_one) remaining_zero=$($transactions[$key].seen_remaining_zero)" }
            }
            if ($isStdout -and $line -match 'CTRL reload: firing \(reload_id=(\d+)\)') {
                $reloadId=[string]$Matches[1]; $key="$channel|$reloadId"
                if (-not $transactions.ContainsKey($key)) { $transactions[$key]=@{hold_stage=0;seen_remaining_one=$false;seen_remaining_zero=$false;preroll_valid=$false;fired=$false;rebase_valid=$false} }
                if (-not $transactions[$key].preroll_valid) { $transactionErrors += "Reload fired before valid preroll on $channel reload_id=$reloadId" }
                $transactions[$key].fired=$true; $firing[$channel]=$reloadId
            }
            if ($isStdout -and $line -match 'finite switch rebased .* streams=(\d+) reload_id=(\d+)') {
                $streams=[int]$Matches[1]; $reloadId=[string]$Matches[2]; $key="$channel|$reloadId"
                if (-not $transactions.ContainsKey($key)) { $transactions[$key]=@{hold_stage=0;seen_remaining_one=$false;seen_remaining_zero=$false;preroll_valid=$false;fired=$false;rebase_valid=$false} }
                $transactions[$key].rebase_valid=($streams -eq 2 -and $transactions[$key].fired -and $transactions[$key].preroll_valid -and $firing.ContainsKey($channel) -and [string]$firing[$channel] -eq $reloadId)
                if (-not $transactions[$key].rebase_valid) { $transactionErrors += "Invalid finite rebase receipt on $channel reload_id=$reloadId`: streams=$streams" }
            }
            if ($isStdout -and $line -match 'CTRL reload committed \(elements=(\d+)\)') {
                $elements=[int]$Matches[1]; $reloadId=if($firing.ContainsKey($channel)){[string]$firing[$channel]}else{$null}; $key=if($reloadId){"$channel|$reloadId"}else{$null}
                if (-not $stdoutCommitCounts.ContainsKey($channel)) { $stdoutCommitCounts[$channel]=0 }; $stdoutCommitCounts[$channel]++
                if (-not $key -or -not $transactions.ContainsKey($key) -or -not $transactions[$key].preroll_valid -or -not $transactions[$key].fired -or -not $transactions[$key].rebase_valid) { $transactionErrors += "Commit lacks a complete reload transaction on $channel reload_id=$reloadId`: $line" }
                $allowed=if($ExpectedElementsPerChannel.ContainsKey($channel)){@($ExpectedElementsPerChannel[$channel] | ForEach-Object {[int]$_})}else{@()}
                if (-not $allowed.Count -or $elements -notin $allowed) { $transactionErrors += "Untrusted or undersized topology on $channel`: elements=$elements allowed=$($allowed -join ',')" }
                if ($key -and $transactions.ContainsKey($key)) { $transactions.Remove($key) }
                if ($firing.ContainsKey($channel)) { $firing.Remove($channel) }
            }
            if ($isStderr -and $line -match 'stage=selector-handoff-confirmed') {
                $diagnosticStage[$channel]=1
            }
            if ($isStderr -and $line -match 'stage=old-tail-detached') {
                if (-not $diagnosticStage.ContainsKey($channel) -or [int]$diagnosticStage[$channel] -ne 1) { $transactionErrors += "old-tail-detached preceded selector handoff on $channel`: $line" }
                $diagnosticStage[$channel]=2
            }
            if ($isStderr -and $line -match 'stage=committed elements=(\d+)') {
                $elements=[int]$Matches[1]
                if (-not $diagnosticCommitCounts.ContainsKey($channel)) { $diagnosticCommitCounts[$channel]=0 }; $diagnosticCommitCounts[$channel]++
                if (-not $diagnosticStage.ContainsKey($channel) -or [int]$diagnosticStage[$channel] -ne 2) { $transactionErrors += "Diagnostic commit lacks selector handoff and old-tail detach on $channel`: $line" }
                $allowed=if($ExpectedElementsPerChannel.ContainsKey($channel)){@($ExpectedElementsPerChannel[$channel] | ForEach-Object {[int]$_})}else{@()}
                if (-not $allowed.Count -or $elements -notin $allowed) { $transactionErrors += "Untrusted diagnostic topology on $channel`: elements=$elements allowed=$($allowed -join ',')" }
                $diagnosticStage[$channel]=0
            }
            if ($line -match '(?i)(?:output stalled|no output for 10\s*seconds|no output for 10s)') { $f3 += [string]$line }
        }
    }
    foreach($channel in @($ExpectedElementsPerChannel.Keys)) {
        $stdoutCount=if($stdoutCommitCounts.ContainsKey($channel)){[int]$stdoutCommitCounts[$channel]}else{0}
        $diagnosticCount=if($diagnosticCommitCounts.ContainsKey($channel)){[int]$diagnosticCommitCounts[$channel]}else{0}
        if ($stdoutCount -ne $diagnosticCount) { $transactionErrors += "Reload receipt count mismatch on $channel`: stdout_commits=$stdoutCount diagnostic_commits=$diagnosticCount" }
    }
    foreach($key in @($transactions.Keys)) { $transactionErrors += "Incomplete reload transaction at EOF: $key" }
    foreach($channel in @($firing.Keys)) { $transactionErrors += "Reload firing stage remained open at EOF: $channel reload_id=$($firing[$channel])" }
    foreach($channel in @($diagnosticStage.Keys)) { if ([int]$diagnosticStage[$channel] -ne 0) { $transactionErrors += "Diagnostic stage remained open at EOF: $channel stage=$($diagnosticStage[$channel])" } }
    [pscustomobject]@{ f1_pass=($f1.Count -eq 0 -and $transactionErrors.Count -eq 0); f1_worker_or_timeout_lines=$f1; f1_commit_without_preroll=$transactionErrors; f3_pass=($f3.Count -eq 0); f3_output_stall_lines=$f3 }
}
function Select-Beta7GradingLogs($MeasuredLogs, $PrerollContextLogs, [bool]$IncludePrerollContext) {
    # Fresh missions grade only bytes written after Get-LogOffsets. Recovery
    # attachment may need the preceding preroll lines for a reload that was
    # already armed when measurement attached, so only that path may add the
    # bounded context tail.
    $selected=@()
    if ($IncludePrerollContext) { $selected += @($PrerollContextLogs) }
    $selected += @($MeasuredLogs)
    return $selected
}
function Get-Beta7WorkerTopologyGrade($Logs, $Channels, $States, $TransportResults, $ExpectedElementsPerChannel) {
    $details=@(); $all=$true
    foreach ($channel in $Channels) {
        $matches=@($Logs | Where-Object { $_.path -match "(?i)(?:^|[\\/])$($channel.id)(?:[\\/]|[-_])" -and $_.path -match '(?i)gst-worker' })
        $state=@($States | Where-Object { $_.channel_id -eq $channel.id -and $_.state -eq 'ON_AIR' -and $_.pid })
        $transport=@($TransportResults | Where-Object { $_.label -eq $channel.id -and $_.verdict -eq 'PASS' })
        $commitCounts=@($Logs | Where-Object { $_.path -match "(?i)(?:^|[\\/])$($channel.id)(?:[\\/]|[-_])" } | ForEach-Object { [regex]::Matches($_.text,'CTRL reload committed \(elements=(\d+)\)') } | ForEach-Object { $_.Groups[1].Value })
        $allowed=if($ExpectedElementsPerChannel.ContainsKey($channel.id)){@($ExpectedElementsPerChannel[$channel.id] | ForEach-Object {[int]$_})}else{@()}
        $ok=$matches.Count -gt 0 -and $state.Count -gt 0 -and $transport.Count -gt 0 -and $commitCounts.Count -gt 0 -and $allowed.Count -gt 0 -and @($commitCounts | Where-Object { [int]$_ -notin $allowed }).Count -eq 0
        $details += @{channel=$channel.id;worker_log_count=$matches.Count;on_air_pid_count=$state.Count;transport_pass_count=$transport.Count;commit_element_counts=$commitCounts;allowed_element_counts=$allowed;pass=$ok}
        if (-not $ok) { $all=$false }
    }
    [pscustomobject]@{pass=$all;channels=$details}
}
function Get-PremiereOverlapRows($Rows, [datetime]$WindowStart, [datetime]$WindowEnd) {
    $result=@()
    foreach($row in @($Rows)) {
        if ("$($row.state)" -in @('cancelled','canceled','done','completed')) { continue }
        if ("$($row.mode)" -ne 'premiere') { continue }
        if (-not $row.scheduled_at) { throw "Premiere row $($row.id) has no scheduled_at." }
        if ($null -eq $row.duration_seconds -or [double]$row.duration_seconds -le 0) { throw "Premiere row $($row.id) has malformed duration_seconds." }
        $start=[datetimeoffset]::Parse([string]$row.scheduled_at).UtcDateTime
        $end=$start.AddSeconds([double]$row.duration_seconds)
        if ($start -lt $WindowEnd -and $end -gt $WindowStart) { $result += $row }
    }
    return $result
}
function Get-TransportRoundSchedule([datetime]$Begin, [int]$DurationMinutes) {
    if ($DurationMinutes -lt 30 -or $DurationMinutes % 30 -ne 0) { throw 'Measured Minutes must be a positive multiple of 30.' }
    $rounds=@()
    for($i=0; $i -lt ($DurationMinutes/30); $i++) {
        $target=$Begin.AddMinutes(30*$i)
        $rounds += [pscustomobject]@{round=$i;offset_minutes=30*$i;target_utc=$target;deadline_utc=$target.AddMinutes(5);estimated_finish_utc=$target.AddSeconds(195)}
    }
    return $rounds
}
function Get-R6OwnedActiveScheduleRows($Rows, [string]$OwnedNotes) {
    return @($Rows | Where-Object {
        [string]$_.notes -ceq $OwnedNotes -and [string]$_.state -in @('scheduled','published')
    })
}
function Remove-RemainingOwnedSchedule {
    $outcomes=@()
    $ownedNotes="Owned $runId"
    $discovered=@()
    foreach($channel in $channels) {
        $rows=@(Invoke-Station GET "/api/staff/schedule?channel_id=$($channel.id)")
        $discovered += @(Get-R6OwnedActiveScheduleRows $rows $ownedNotes | ForEach-Object {
            if(-not $_.id){throw "R6-owned active schedule row on $($channel.id) has no ID."}
            [pscustomobject]@{id=[string]$_.id;channel_id=$channel.id;state=[string]$_.state;scheduled_at=[string]$_.scheduled_at;recorded=([string]$_.id -in @($createdScheduleIds))}
        })
    }
    $duplicateIds=@($discovered | Group-Object id | Where-Object {$_.Count -ne 1})
    if($duplicateIds.Count){throw "R6-owned active schedule IDs are duplicated across channel queries: $($duplicateIds.Name -join ',')."}
    foreach($row in @($discovered)) {
        $scheduleId=[string]$row.id
        $confirmed=Invoke-Station GET "/api/staff/schedule/$scheduleId"
        if([string]$confirmed.notes -cne $ownedNotes){throw "Refusing to cancel schedule $scheduleId with non-owned notes."}
        if([string]$confirmed.state -notin @('scheduled','published')){$outcomes += @{schedule_id=$scheduleId;state=[string]$confirmed.state;action='became_terminal';recorded=[bool]$row.recorded};continue}
        $cancelled=Invoke-Station POST "/api/staff/schedule/$scheduleId/cancel" $null
        $verified=Invoke-Station GET "/api/staff/schedule/$scheduleId"
        if([string]$cancelled.state -ne 'cancelled' -or [string]$verified.state -ne 'cancelled'){throw "Owned schedule $scheduleId did not verify canceled."}
        $outcomes += @{schedule_id=$scheduleId;state='cancelled';action='cancelled';recorded=[bool]$row.recorded}
    }
    $remaining=@()
    foreach($channel in $channels){
        $rows=@(Invoke-Station GET "/api/staff/schedule?channel_id=$($channel.id)")
        $remaining += @(Get-R6OwnedActiveScheduleRows $rows $ownedNotes)
    }
    if($remaining.Count){throw "$($remaining.Count) active R6-owned schedule rows remain after cleanup."}
    return @{verified=$true;recorded_owned_count=$createdScheduleIds.Count;discovered_active_owned_count=$discovered.Count;unrecorded_active_owned_count=@($discovered|Where-Object{-not $_.recorded}).Count;outcomes=$outcomes;active_owned_remaining=0;verified_utc=[datetime]::UtcNow.ToString('o')}
}
if ($SelfTest) {
    $quiescenceFixtures = @(
        @{name='stopped without pid';state=[pscustomobject]@{state='STOPPED';pid=$null};expected=$true},
        @{name='fallback slate without pid';state=[pscustomobject]@{state='FALLBACK_SLATE';pid=$null};expected=$false},
        @{name='fallback slate with pid';state=[pscustomobject]@{state='FALLBACK_SLATE';pid=1234};expected=$false},
        @{name='on air without pid';state=[pscustomobject]@{state='ON_AIR';pid=$null};expected=$false},
        @{name='missing state';state=$null;expected=$false}
    )
    foreach ($fixture in $quiescenceFixtures) {
        if ((Test-QuiescentChannelState $fixture.state) -ne $fixture.expected) {
            throw "Channel quiescence fixture failed: $($fixture.name)"
        }
    }
    $quiescentConfigFixtures = @(
        @{name='disabled with auto-start suppressed';config=[pscustomobject]@{enabled=$false;auto_start=$false};expected=$true},
        @{name='enabled auto-start channel';config=[pscustomobject]@{enabled=$true;auto_start=$true};expected=$false},
        @{name='enabled channel';config=[pscustomobject]@{enabled=$true;auto_start=$false};expected=$false},
        @{name='missing config';config=$null;expected=$false}
    )
    foreach ($fixture in $quiescentConfigFixtures) {
        if ((Test-DisabledQuiescentChannelConfig $fixture.config) -ne $fixture.expected) {
            throw "Channel quiescent-intent fixture failed: $($fixture.name)"
        }
    }
    $canonicalConfig=[pscustomobject]@{channel_id='public';enabled=$true;auto_start=$true;fill_policy='slate';sinks=@([pscustomobject]@{kind='udp-ts';uri='udp://127.0.0.1:9001';latency_ms=2000})}
    $onlyAutoStartChanged=[pscustomobject]@{sinks=@([pscustomobject]@{latency_ms=2000;uri='udp://127.0.0.1:9001';kind='udp-ts'});fill_policy='slate';auto_start=$false;enabled=$true;channel_id='public'}
    if (-not (Test-ConfigSemanticallyPreserved $canonicalConfig $onlyAutoStartChanged)) { throw 'Canonical config comparison rejected an auto_start-only change or property reordering.' }
    $sinkChanged=[pscustomobject]@{channel_id='public';enabled=$true;auto_start=$false;fill_policy='slate';sinks=@([pscustomobject]@{kind='udp-ts';uri='udp://127.0.0.1:9999';latency_ms=2000})}
    if (Test-ConfigSemanticallyPreserved $canonicalConfig $sinkChanged) { throw 'Canonical config comparison accepted a changed nested sink value.' }
    $fieldMissing=[pscustomobject]@{channel_id='public';enabled=$true;auto_start=$false;sinks=@([pscustomobject]@{kind='udp-ts';uri='udp://127.0.0.1:9001';latency_ms=2000})}
    if (Test-ConfigSemanticallyPreserved $canonicalConfig $fieldMissing) { throw 'Canonical config comparison accepted a missing field.' }
    $plan = @([pscustomobject]@{channel_id='public';scheduled_at='2026-09-11T12:00:00Z';asset_id='test-a';asset_label='A'})
    $begin = [datetimeoffset]::Parse('2026-09-11T11:59:00Z').UtcDateTime
    $end = $begin.AddMinutes(3)
    foreach ($delay in @(10,30,31,301)) {
        $samples = @([pscustomobject]@{channel='public';source_label='A';at=$begin.AddMinutes(1).AddSeconds($delay).ToString('o')})
        $grade = @(Get-BoundaryGrades $plan $samples $begin $end)
        if ($grade.Count -ne 1 -or $grade[0].pass -ne ($delay -le 30)) { throw "Boundary fixture failed at $delay seconds" }
    }
    $historical = [pscustomobject]@{path='C:\ProgramData\CivicCast\data\egress\public\logs\gst-worker.stdout.log';text="WORKER_RESULT {'error': None, 'teardown_clean': True}`noutput stalled"}
    $measured = [pscustomobject]@{path='C:\ProgramData\CivicCast\data\egress\public\logs\gst-worker.stdout.log';text='measured window remains healthy'}
    $freshLogs = @(Select-Beta7GradingLogs @($measured) @($historical) $false)
    $freshGrade = Get-Beta7FailureGrades $freshLogs @{public=@(146)}
    if ($freshLogs.Count -ne 1 -or -not $freshGrade.f1_pass -or -not $freshGrade.f3_pass) { throw 'Fresh-run log scoping included pre-measurement history.' }
    $postOffsetLogs = @(Select-Beta7GradingLogs @($historical) @() $false)
    $postOffsetGrade = Get-Beta7FailureGrades $postOffsetLogs @{public=@(146)}
    if ($postOffsetGrade.f1_pass -or $postOffsetGrade.f3_pass) { throw 'Post-offset worker exit/stall fixture did not fail.' }
    $goodStdout=[pscustomobject]@{path='C:\ProgramData\CivicCast\data\egress\public\logs\gst-worker.stdout.log';text=@'
CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll) (reload_id=7)
CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=7)
CTRL reload: new leg preroll verified (reload_id=7) held_streams=2 timing=finite mode=immediate
CTRL reload: firing (reload_id=7)
CTRL reload: finite switch rebased to running time 7.113s mode=immediate streams=2 reload_id=7
CTRL reload committed (elements=146)
'@}
    $goodStderr=[pscustomobject]@{path='C:\ProgramData\CivicCast\data\egress\public\logs\gst-worker.stderr.log';text=@'
CTRL reload diagnostic: stage=selector-handoff-confirmed
CTRL reload diagnostic: stage=old-tail-detached
CTRL reload diagnostic: stage=committed elements=146
'@}
    $goodGrade=Get-Beta7FailureGrades @($goodStdout,$goodStderr) @{public=@(146)}
    if(-not $goodGrade.f1_pass){throw "Complete reload transaction fixture failed: $($goodGrade.f1_commit_without_preroll -join '; ')"}
    $workerErrorGrade=Get-Beta7FailureGrades @([pscustomobject]@{path=$goodStdout.path;text='WORKER_RESULT {"error": null, "teardown_clean": true}'}) @{public=@(146)}
    if($workerErrorGrade.f1_pass){throw 'Any WORKER_RESULT fixture incorrectly passed.'}
    $danglingHold=Get-Beta7FailureGrades @([pscustomobject]@{path=$goodStdout.path;text='CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll) (reload_id=8)'}) @{public=@(146)}
    if($danglingHold.f1_pass -or @($danglingHold.f1_commit_without_preroll | Where-Object {$_ -match 'Incomplete reload transaction at EOF'}).Count -ne 1){throw 'Dangling reload transaction fixture did not produce its exact EOF error.'}
    $danglingFireText=@'
CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll) (reload_id=9)
CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=9)
CTRL reload: new leg preroll verified (reload_id=9) held_streams=2 timing=finite mode=immediate
CTRL reload: firing (reload_id=9)
'@
    $danglingFire=Get-Beta7FailureGrades @([pscustomobject]@{path=$goodStdout.path;text=$danglingFireText}) @{public=@(146)}
    if($danglingFire.f1_pass -or @($danglingFire.f1_commit_without_preroll | Where-Object {$_ -match 'Incomplete reload transaction at EOF'}).Count -ne 1 -or @($danglingFire.f1_commit_without_preroll | Where-Object {$_ -match 'Reload firing stage remained open at EOF'}).Count -ne 1){throw 'Dangling firing fixture did not produce exact EOF errors.'}
    $danglingDiagnostic=Get-Beta7FailureGrades @([pscustomobject]@{path=$goodStderr.path;text='CTRL reload diagnostic: stage=selector-handoff-confirmed'}) @{public=@(146)}
    if($danglingDiagnostic.f1_pass -or @($danglingDiagnostic.f1_commit_without_preroll | Where-Object {$_ -match 'Diagnostic stage remained open at EOF'}).Count -ne 1){throw 'Dangling diagnostic stage fixture did not produce its exact EOF error.'}
    $embargoRows=@([pscustomobject]@{id='embargo';mode='embargo';state='published';scheduled_at='2026-09-11T12:00:00Z';duration_seconds=1},[pscustomobject]@{id='premiere';mode='premiere';state='published';scheduled_at='2026-09-11T12:00:00Z';duration_seconds=300})
    $overlapCheck=@(Get-PremiereOverlapRows $embargoRows ([datetimeoffset]'2026-09-11T11:59:00Z').UtcDateTime ([datetimeoffset]'2026-09-11T12:01:00Z').UtcDateTime)
    if($overlapCheck.Count -ne 1 -or $overlapCheck[0].id -ne 'premiere'){throw 'Embargo row incorrectly participated in overlap scan.'}
    $malformedCaught=$false; try { Get-PremiereOverlapRows @([pscustomobject]@{id='bad';mode='premiere';state='published';scheduled_at='2026-09-11T12:00:00Z';duration_seconds=0}) ([datetimeoffset]'2026-09-11T11:59:00Z').UtcDateTime ([datetimeoffset]'2026-09-11T12:01:00Z').UtcDateTime | Out-Null } catch {$malformedCaught=$true}
    if(-not $malformedCaught){throw 'Malformed premiere duration fixture did not fail.'}
    $roundSchedule=@(Get-TransportRoundSchedule ([datetime]'2026-09-11T12:00:00Z') 240)
    if($roundSchedule.Count -ne 8 -or (@($roundSchedule | ForEach-Object {$_.offset_minutes}) -join ',') -cne '0,30,60,90,120,150,180,210'){throw 'Transport cadence fixture did not produce eight feasible 30-minute offsets.'}
    if(@($roundSchedule | Where-Object {$_.estimated_finish_utc -ge $_.target_utc.AddMinutes(30)}).Count){throw 'Transport cadence fixture is not serialized within its next slot.'}
    $normalized=ConvertTo-WholeSecondUtc ([datetimeoffset]'2026-09-11T12:00:01.9876543Z').UtcDateTime
    if($normalized.Kind -ne [DateTimeKind]::Utc -or $normalized.Ticks % [timespan]::TicksPerSecond -ne 0){throw 'Whole-second schedule normalization fixture failed.'}
    $ownedNotes="Owned $runId"
    $cleanupFixtures=@(
        [pscustomobject]@{id='unrecorded-future';notes=$ownedNotes;state='scheduled';scheduled_at='2099-01-01T00:00:00Z'},
        [pscustomobject]@{id='unrecorded-past';notes=$ownedNotes;state='published';scheduled_at='2000-01-01T00:00:00Z'},
        [pscustomobject]@{id='terminal';notes=$ownedNotes;state='completed';scheduled_at='2000-01-01T00:00:00Z'},
        [pscustomobject]@{id='foreign';notes='Owned another-run';state='scheduled';scheduled_at='2099-01-01T00:00:00Z'}
    )
    $cleanupSelected=@(Get-R6OwnedActiveScheduleRows $cleanupFixtures $ownedNotes)
    if(($cleanupSelected.id -join ',') -cne 'unrecorded-future,unrecorded-past'){throw 'Schedule cleanup discovery fixture did not select every active exact-notes row regardless of recorded ID or wall-clock time.'}
    foreach($bad in @(
        @{name='zero held streams';stdout=[pscustomobject]@{path=$goodStdout.path;text=$goodStdout.text.Replace('held_streams=2','held_streams=0')};stderr=$goodStderr},
        @{name='missing finite rebase';stdout=[pscustomobject]@{path=$goodStdout.path;text=($goodStdout.text -replace '(?m)^CTRL reload: finite switch rebased.*\r?\n?','')};stderr=$goodStderr},
        @{name='mismatched finite rebase';stdout=[pscustomobject]@{path=$goodStdout.path;text=$goodStdout.text.Replace('streams=2 reload_id=7','streams=2 reload_id=8')};stderr=$goodStderr},
        @{name='firing before preroll';stdout=[pscustomobject]@{path=$goodStdout.path;text=@'
CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll) (reload_id=7)
CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=7)
CTRL reload: firing (reload_id=7)
CTRL reload: new leg preroll verified (reload_id=7) held_streams=2 timing=finite mode=immediate
CTRL reload: finite switch rebased to running time 7.113s mode=immediate streams=2 reload_id=7
CTRL reload committed (elements=146)
'@};stderr=$goodStderr},
        @{name='commit before rebase';stdout=[pscustomobject]@{path=$goodStdout.path;text=@'
CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll) (reload_id=7)
CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll) (reload_id=7)
CTRL reload: new leg preroll verified (reload_id=7) held_streams=2 timing=finite mode=immediate
CTRL reload: firing (reload_id=7)
CTRL reload committed (elements=146)
CTRL reload: finite switch rebased to running time 7.113s mode=immediate streams=2 reload_id=7
'@};stderr=$goodStderr},
        @{name='missing selector handoff';stdout=$goodStdout;stderr=[pscustomobject]@{path=$goodStderr.path;text=($goodStderr.text -replace '(?m)^CTRL reload diagnostic: stage=selector-handoff-confirmed\r?\n?','')}}
    )) {
        $badGrade=Get-Beta7FailureGrades @($bad.stdout,$bad.stderr) @{public=@(146)}
        if($badGrade.f1_pass){throw "Invalid reload transaction fixture passed: $($bad.name)"}
    }
    foreach($badElements in @(33,56,74)) {
        $badTopology=[pscustomobject]@{path=$goodStdout.path;text=$goodStdout.text.Replace('elements=146',"elements=$badElements")}
        $badTopologyGrade=Get-Beta7FailureGrades @($badTopology,$goodStderr) @{public=@(146)}
        if($badTopologyGrade.f1_pass -or @($badTopologyGrade.f1_commit_without_preroll | Where-Object {$_ -match 'Untrusted.*topology'}).Count -eq 0){throw "Known undersized topology elements=$badElements incorrectly passed."}
        $topologyGrade=Get-Beta7WorkerTopologyGrade @($badTopology) @([pscustomobject]@{id='public'}) @([pscustomobject]@{channel_id='public';state='ON_AIR';pid=123}) @([pscustomobject]@{label='public';verdict='PASS'}) @{public=@(146)}
        if($topologyGrade.pass){throw "Worker topology grader accepted known undersized elements=$badElements."}
    }
    Save-Result @{verdict='PASS';checks=@('Quiescence requires exact STOPPED with no worker PID','Disabled quiescent intent preserves full config','Two-restart barrier helpers are defined','Canonical full-config comparison ignores only auto_start and property order','Canonical full-config comparison rejects nested changes and missing fields','Boundary observations at 10/30/31/301 seconds','Fresh-run grading excludes pre-measurement history','Any WORKER_RESULT and output stall fail','Incomplete reload transaction/firing/diagnostic EOF fails','Complete reload transaction passes','Zero held streams fails','Missing or mismatched finite rebase fails','Firing before preroll fails','Commit before rebase fails','Missing selector handoff fails','Embargo rows are ignored for premiere overlap','Malformed premiere duration fails','Eight serialized transport offsets fit four hours')} 'SELF-TEST.json'
    return
}
. (Join-Path $PSScriptRoot 'Beta7TransportProbeR6.ps1')
function Get-LogOffsets {
    $offsets = @{}
    foreach ($folder in @('logs','data/egress')) {
        $path = Join-Path $ProgramDataRoot $folder
        if (Test-Path -LiteralPath $path) {
            foreach ($file in Get-ChildItem -LiteralPath $path -Recurse -File -Filter '*.log') { $offsets[$file.FullName]=$file.Length }
        }
    }
    return $offsets
}
function Copy-PhaseLogs([string]$Phase, $Offsets) {
    $result = @()
    $nowFiles = Get-LogOffsets
    foreach ($path in $nowFiles.Keys) {
        $position = if ($Offsets.ContainsKey($path)) { [long]$Offsets[$path] } else { 0L }
        $input = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
        try {
            if ($position -gt $input.Length) { throw "Log rotated/truncated during measured phase: $path" }
            [void]$input.Seek($position,[IO.SeekOrigin]::Begin)
            $reader = [IO.StreamReader]::new($input)
            try { $body = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally { $input.Dispose() }
        $relative = $path.Substring($ProgramDataRoot.TrimEnd('\','/').Length).TrimStart('\','/')
        $destination = Join-Path $runRoot "$Phase/raw/$relative"
        New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
        [IO.File]::WriteAllText($destination,$body,[Text.UTF8Encoding]::new($false))
        $result += [pscustomobject]@{path=$destination;text=$body}
    }
    return $result
}
function Invoke-PremeasurementTopologyProof([string]$Phase, $Plan, $Offsets, $ExpectedElements) {
    # Slice this proof from immediately before the controlled future transition,
    # excluding initial startup commits that do not prove a programme change.
    $transitionOffsets=Get-LogOffsets
    $now=[datetime]::UtcNow
    $targets=@($Plan | Where-Object { ([datetimeoffset]::Parse([string]$_.scheduled_at).UtcDateTime) -gt $now } | Group-Object channel_id | ForEach-Object { $_.Group | Sort-Object {[datetimeoffset]::Parse([string]$_.scheduled_at).UtcDateTime} | Select-Object -First 1 })
    if($targets.Count -ne $channels.Count){throw "$Phase has no future controlled schedule transition for every channel."}
    $target=$targets | ForEach-Object {[datetimeoffset]::Parse([string]$_.scheduled_at).UtcDateTime} | Sort-Object -Descending | Select-Object -First 1
    $captureAt=$target.AddSeconds(90)
    while([datetime]::UtcNow -lt $captureAt){Start-Sleep -Seconds ([math]::Min(5,[math]::Max(1,[int]($captureAt-[datetime]::UtcNow).TotalSeconds)))}
    $profile=Invoke-Station -Method GET -Path '/api/staff/station/profile' -Timeout 20
    if($profile.live_captions_enabled -ne $false){throw "$Phase premeasurement profile is not captions OFF."}
    $envEvidence=@{}
    foreach($name in @('CIVICCAST_CAPTION_TAP','CIVICCAST_CAPTION_TAP_DIR')) {
        $processValue=[Environment]::GetEnvironmentVariable($name,[EnvironmentVariableTarget]::Process)
        $userValue=[Environment]::GetEnvironmentVariable($name,[EnvironmentVariableTarget]::User)
        $machineValue=[Environment]::GetEnvironmentVariable($name,[EnvironmentVariableTarget]::Machine)
        $envEvidence[$name]=@{process_present=($null -ne $processValue);process_value=$processValue;user_present=($null -ne $userValue);user_value=$userValue;machine_present=($null -ne $machineValue);machine_value=$machineValue}
    }
    $logs=@(Copy-PhaseLogs "$Phase-premeasurement" $transitionOffsets)
    $grade=Get-Beta7FailureGrades $logs $ExpectedElements
    $details=@()
    foreach($channel in $channels){
        $channelLogs=@($logs | Where-Object {$_.path -match "(?i)(?:^|[\\/])$($channel.id)(?:[\\/]|[-_])"})
        $commits=@($channelLogs | ForEach-Object {[regex]::Matches([string]$_.text,'CTRL reload committed \(elements=(\d+)\)')} | ForEach-Object {$_.Groups[1].Value})
        $badTopology=@($commits | Where-Object {[int]$_ -ne 146})
        if(-not $commits.Count -or $badTopology.Count -or @($commits | Where-Object {[int]$_ -eq 146}).Count -lt 1){throw "$Phase premeasurement topology proof failed for $($channel.id): expected at least one complete elements=146 transaction."}
        $targetRow=@($targets | Where-Object {$_.channel_id -eq $channel.id})[0]
        $details += @{channel=$channel.id;transition_target_utc=([datetimeoffset]::Parse([string]$targetRow.scheduled_at).UtcDateTime).ToString('o');commit_elements=$commits}
    }
    if(-not $grade.f1_pass -or -not $grade.f3_pass){throw "$Phase premeasurement logs contain a worker result, incomplete transaction, or output stall."}
    foreach($log in $logs){if([string]$log.text -match '(?i)elements=(?:33|56|74)\b|WORKER_RESULT|output stalled|no output for 10\s*(?:seconds|s)'){throw "$Phase premeasurement logs contain forbidden failure evidence."}}
    $evidence=@{phase=$Phase;profile=$profile;captions_off=$true;caption_environment=$envEvidence;controlled_transitions=$details;captured_at=[datetime]::UtcNow.ToString('o');expected_elements=146;failure_grade=$grade}
    Save-Result $evidence "$Phase/PREMEASUREMENT-TOPOLOGY.json"
    return $evidence
}
try {
    if (-not (Test-Path -LiteralPath $TspExe -PathType Leaf)) { throw "Installed transport probe is absent: $TspExe" }
    if (-not (Test-Path -LiteralPath $TokenPath -PathType Leaf)) { throw "Existing tester token is absent: $TokenPath" }
    $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
    if (-not $token) { throw 'Existing tester token file is empty.' }
    $health = Invoke-Station GET '/health'
    if ($health.status -ne 'healthy' -or $health.schema -ne 'current' -or $health.version -ne '1.0.0-beta.7') { throw 'Installed fixed beta health/version/schema is not ready.' }
    $inventory = @(Invoke-Station GET '/api/staff/egress/channels')
    Save-Result @{count=$inventory.Count;channel_ids=@($inventory | ForEach-Object {[string]$_.channel_id})} 'CHANNEL-INVENTORY.json'
    $expectedPorts = @{public=9001;education=9002;government=9003}
    $observed = @($inventory | Where-Object { $_.channel_id -and $expectedPorts.ContainsKey("$($_.channel_id)") })
    if ($inventory.Count -ne 3 -or $observed.Count -ne 3 -or @($observed.channel_id | Sort-Object -Unique).Count -ne 3) { throw 'Existing tester does not expose exactly public/education/government channel configs.' }
    $configSnapshots = @()
    foreach ($channel in $channels) {
        $config = Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/config"
        $sinks = @($config.sinks | Where-Object { $_.kind -eq 'udp-ts' -and $_.uri -eq "udp://127.0.0.1:$($channel.port)" })
        if ($sinks.Count -ne 1) { throw "Existing $($channel.id) config is not bound to UDP $($channel.port)." }
        $configSnapshots += [pscustomobject]@{channel_id=$channel.id;enabled=$config.enabled;auto_start=$config.auto_start;
            allow_software_fallback=$config.allow_software_fallback;fill_policy=$config.fill_policy;
            sinks=@($config.sinks | Select-Object kind,label,uri,latency_ms,loudness_regime,eas_tone_strip_enabled)}
    }
    if ($ExistingRunRoot) {
        if ($RequireTransportAdmission -and $Mode -ne 'Both') { throw 'Transport admission recovery requires the complete ON/OFF mission.' }
        $previousIdentity=Get-Content -LiteralPath (Join-Path $ExistingRunRoot 'IDENTITY.json') -Raw | ConvertFrom-Json
        if ($previousIdentity.source_sha -ne $SourceSha) { throw 'Existing schedule evidence belongs to a different candidate.' }
        $planData=Get-Content -LiteralPath (Join-Path $ExistingRunRoot 'published-plan.json') -Raw | ConvertFrom-Json
        # Windows PowerShell 5.1 preserves a top-level JSON array as one
        # Object[] pipeline item. Explicit enumeration keeps recovery checks
        # operating on individual schedule rows in both supported runtimes.
        $plan=@($planData | ForEach-Object { $_ })
        if ($plan.Count -ne 180 -or @($plan.channel_id | Sort-Object -Unique).Count -ne 3) { throw 'Existing schedule evidence is incomplete.' }
        $times=@($plan | ForEach-Object {[datetimeoffset]::Parse($_.scheduled_at).UtcDateTime} | Sort-Object)
        $scheduleStart=$times[0]
        $scheduleEnd=$times[-1].AddMinutes(5)
        $slotCount=[int](($scheduleEnd-$scheduleStart).TotalMinutes/5)
        if ($scheduleEnd -lt [datetime]::UtcNow.AddMinutes($Minutes*$phases.Count+15)) { throw 'Existing schedule has insufficient remaining horizon for both full phases.' }
        foreach ($channel in $channels) {
            $config=Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/config"
            if ($config.allow_software_fallback) { throw 'Existing playout allows software fallback; cannot attach this GStreamer measurement.' }
        }
        $owned=@($channels.id)
        Save-Result @{run_id=$runId;source_sha=$SourceSha;minutes_per_phase=$Minutes;phases=$phases;attached_schedule_evidence=$ExistingRunRoot;existing_config_snapshots=$configSnapshots} 'IDENTITY.json'
        Save-Result $plan 'published-plan.json'
        Write-ProgressLog 'Attached recovery to existing published schedule and verified configs; stopped workers will start outside measurement.'
    } else {
    $assets = @()
    $assetLabels = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    $assetOffset = 0
    do {
        # The staff API caps pages at 500. Collect usable assets across pages.
        $assetPage = @(Invoke-Station GET "/api/staff/assets?limit=500&offset=$assetOffset")
        $assets += @($assetPage | Where-Object {
            $_.asset_id -and $_.title -and $_.manifest_url -and $_.published_at -and $_.duration_seconds -and [int]$_.duration_seconds -ge 300 -and
            "$($_.state)" -eq 'validated'
        } | Where-Object { $assetLabels.Add([string]$_.title) } | ForEach-Object { [pscustomobject]@{id="$($_.asset_id)";title="$($_.title)"} })
        $assetOffset += $assetPage.Count
    } while ($assets.Count -lt 4 -and $assetPage.Count -eq 500)
    $assets = @($assets | Select-Object -First 4)
    if ($assets.Count -lt 2) { throw 'Two published media assets with distinct source labels and at least five minutes duration are required.' }
    # Publish one continuous horizon covering BOTH measured phases and their startup margins.
    # Reusing it after the intentional mode-change restart avoids overlapping published schedules.
    $scheduleStart = ConvertTo-WholeSecondUtc ([datetime]::UtcNow.AddMinutes(15))
    $slotCount = [int][math]::Ceiling(($Minutes*$phases.Count+60)/5)
    $scheduleEnd = $scheduleStart.AddMinutes(5*$slotCount)
    $overlaps = @()
    foreach ($channel in $channels) {
        $existing = @(Invoke-Station GET "/api/staff/schedule?channel_id=$($channel.id)")
        $overlaps += @(Get-PremiereOverlapRows $existing $scheduleStart $scheduleEnd | ForEach-Object { [pscustomobject]@{channel_id=$channel.id;schedule_id=$_.id;state=$_.state;mode=$_.mode;scheduled_at=$_.scheduled_at;duration_seconds=$_.duration_seconds;asset_id=$_.asset_id;notes=$_.notes} })
    }
    if ($overlaps.Count) {
        $allowedOverlapSet=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach($allowedId in @($AllowedOverlapScheduleIds)){if($allowedId){$null=$allowedOverlapSet.Add([string]$allowedId)}}
        $unapprovedOverlaps=@($overlaps | Where-Object {-not $_.schedule_id -or -not $allowedOverlapSet.Contains([string]$_.schedule_id)})
        if($unapprovedOverlaps.Count){
            Save-Result @{verdict='UNAPPROVED_SCHEDULE_OVERLAP';conflicts=$unapprovedOverlaps;allowed_schedule_id_count=$allowedOverlapSet.Count;action='No cancellation performed.'} 'SCHEDULE-CONFLICT.json'
            throw 'An overlapping schedule row is not bound to the explicitly allowed preserved plan; no rows were cancelled.'
        }
        Save-Result @{verdict='SCHEDULE_CONFLICT';conflicts=$overlaps;replace_switch=$ReplaceOverlappingTestSchedule.IsPresent;action='Cancel only overlapping scheduled or published test rows through the supported store transition.'} 'SCHEDULE-CONFLICT.json'
        if (-not $ReplaceOverlappingTestSchedule) { throw 'Existing future schedule overlaps the requested clean horizon; rerun with -ReplaceOverlappingTestSchedule to cancel only those rows.' }
        if (@($overlaps | Where-Object { $_.state -notin @('scheduled','published') }).Count) { throw 'Overlapping rows contain an unsupported schedule state.' }
        foreach ($row in $overlaps) {
            if (-not $row.schedule_id) { throw "Overlapping $($row.channel_id) row has no cancellable schedule ID." }
            $cancelled = Invoke-Station POST "/api/staff/schedule/$($row.schedule_id)/cancel" $null
            if ("$($cancelled.state)" -ne 'cancelled') { throw "Schedule $($row.schedule_id) did not verify as cancelled." }
        }
        $remaining = @()
        foreach ($channel in $channels) {
            $rows = @(Invoke-Station GET "/api/staff/schedule?channel_id=$($channel.id)")
            $remaining += @(Get-PremiereOverlapRows $rows $scheduleStart $scheduleEnd)
        }
        if ($remaining.Count) { throw 'Overlapping schedule rows remain after supported cancellation; no new horizon was published.' }
    }
    $owned = @($channels.id)
    Save-Result @{run_id=$runId;source_sha=$SourceSha;minutes_per_phase=$Minutes;phases=$phases;health=$health;token_path=$TokenPath;existing_channels=@($inventory | ForEach-Object { $_.channel_id });existing_config_snapshots=$configSnapshots;replace_overlapping_schedule=$ReplaceOverlappingTestSchedule.IsPresent;overlap_rows_cancelled=$overlaps.Count} 'IDENTITY.json'
    Stop-OwnedChannels
    $plan = @()
    foreach ($channel in $channels) {
        for ($i=0; $i -lt $slotCount; $i++) {
            $asset = $assets[$i % $assets.Count]
            $at = $scheduleStart.AddMinutes(5*$i).ToString('o')
            $item = Invoke-Station POST '/api/staff/schedule' @{asset_id=$asset.id;channel_id=$channel.id;mode='premiere';scheduled_at=$at;duration_seconds=300;notes="Owned $runId"}
            if (-not $item.id) { throw 'Schedule POST returned no item id.' }
            $createdScheduleIds += [string]$item.id
            Invoke-Station POST '/api/staff/playout/commit' @{channel_id=$channel.id;occurrence_id="$runId-$($channel.id)-$i";schedule_item_id=[string]$item.id} | Out-Null
            $observed = Invoke-Station GET "/api/staff/schedule/$($item.id)"
            $observedAt=$null; try{$observedAt=[datetimeoffset]::Parse([string]$observed.scheduled_at).UtcDateTime}catch{}
            $plannedAt=[datetimeoffset]::Parse($at).UtcDateTime
            if ($observed.state -ne 'published' -or $observed.mode -ne 'premiere' -or [int]$observed.duration_seconds -ne 300 -or
                [string]$observed.channel_id -ne $channel.id -or [string]$observed.asset_id -ne $asset.id -or
                $null -eq $observedAt -or $observedAt -ne $plannedAt -or [string]$observed.notes -ne "Owned $runId") { throw "Slot $($item.id) failed exact published-plan readback." }
            $plan += [pscustomobject]@{channel_id=[string]$observed.channel_id;schedule_id=[string]$observed.id;asset_id=[string]$observed.asset_id;asset_label=$asset.title;scheduled_at=[string]$observed.scheduled_at;mode=[string]$observed.mode;duration_seconds=[int]$observed.duration_seconds;notes=[string]$observed.notes;state=[string]$observed.state}
        }
        Write-ProgressLog "Published $slotCount five-minute slots for $($channel.id)"
    }
    Save-Result $plan 'published-plan.json'
    }
    foreach ($phase in $phases) {
        if (-not $ExpectedElementsPerPhase.ContainsKey($phase)) { throw "No topology expectations are bound for phase $phase." }
        $phaseExpectedElements=$ExpectedElementsPerPhase[$phase]
        $attachOn=$ExistingRunRoot -and $phase -eq 'ON'
        if ($owned.Count -and -not $attachOn) { Stop-OwnedChannels }
        # Include startup/preload proof for any reload that commits after the
        # measured window begins; intentional previous-phase Stop is excluded.
        $offsets = Get-LogOffsets
        # A reload may already be prerolled when attachment begins. Preserve
        # its preceding context separately from measured failure/lifetime logs.
        if ($attachOn) {
            foreach ($channel in $channels) {
                $workerLog=Join-Path $ProgramDataRoot ("data/egress/$($channel.id)/logs/gst-worker.stdout.log")
                if (Test-Path -LiteralPath $workerLog) {
                    $context=Join-Path $runRoot "$phase/preroll-context/$($channel.id)-stdout.log"
                    New-Item -ItemType Directory -Path (Split-Path $context) -Force | Out-Null
                    Get-Content -LiteralPath $workerLog -Tail 100 | Set-Content -LiteralPath $context -Encoding utf8
                }
            }
        }
        # R6 transport/topology evidence is deliberately captions OFF; caption
        # endpoints remain supporting evidence and never change this grade.
        $enabled = $false
        if (-not $attachOn) { Invoke-Station PUT '/api/staff/station/profile' @{live_captions_enabled=$enabled} | Out-Null }
        $profile = Invoke-Station GET '/api/staff/station/profile'
        if ($profile.live_captions_enabled -ne $enabled) { throw 'Caption-mode readback mismatch.' }
        Save-Result @{phase=$phase;captions_enabled=$profile.live_captions_enabled} "$phase/profile.json"
        if (-not $ExistingRunRoot) {
            foreach ($channel in $channels) {
                $config = @{channel_id=$channel.id;enabled=$true;auto_start=$true;allow_software_fallback=$false;fill_policy='slate';slate_message="Owned $runId";
                    sinks=@(@{kind='udp-ts';label=$runId;uri="udp://127.0.0.1:$($channel.port)";latency_ms=2000;loudness_regime='inherit';eas_tone_strip_enabled=$true})}
                Invoke-Station PUT "/api/staff/egress/channels/$($channel.id)/config" $config | Out-Null
                if ($owned -notcontains $channel.id) { $owned += $channel.id }
                Invoke-Station POST "/api/staff/egress/channels/$($channel.id)/commands" @{action='start'} | Out-Null
            }
        } else {
            # Recovery uses the already-verified configs. R1 left them stopped;
            # OFF also needs a start after the intentional phase transition.
            foreach ($channel in $channels) {
                Invoke-Station POST "/api/staff/egress/channels/$($channel.id)/commands" @{action='start'} | Out-Null
            }
            Write-ProgressLog "$phase recovery started the three existing channel configs; no channel configuration or schedule was changed."
        }
        $startupAnchor=[datetime]::UtcNow
        if ($scheduleStart -gt $startupAnchor) { $startupAnchor=$scheduleStart }
        $deadline=$startupAnchor.AddMinutes(5)
        do {
            $states = @($channels | ForEach-Object { Invoke-Station GET "/api/staff/egress/channels/$($_.id)/state" })
            $startupSnapshot=@($states | ForEach-Object {@{channel_id=[string]$_.channel_id;state=[string]$_.state;pid=$_.pid;source=[string]$_.current_source_label;last_error=[string]$_.last_error}})
            Save-Result @{at=[datetime]::UtcNow.ToString('o');deadline=$deadline.ToString('o');channels=$startupSnapshot} "$phase/STARTUP-STATE.json"
            $ready = $states.Count -eq 3 -and @($states | Where-Object { $_.state -ne 'ON_AIR' -or -not $_.pid }).Count -eq 0
            if ($ready) { break }
            Start-Sleep -Seconds 10
        } while ([datetime]::UtcNow -lt $deadline)
        if (-not $ready) {
            $null=Copy-PhaseLogs "${phase}-startup" $offsets
            throw "${phase}: all three channels did not reach ON_AIR."
        }
        $phasePids=@{}; foreach($state in $states){$phasePids[[string]$state.channel_id]=[int]$state.pid}
        # Do not start transport capture on a merely momentary ON_AIR result.
        # Require a continuous 30-second same-PID stabilization interval first.
        $stableUntil=[datetime]::UtcNow.AddSeconds(30)
        do {
            foreach($stableChannel in $channels) {
                $stableState=Invoke-Station GET "/api/staff/egress/channels/$($stableChannel.id)/state"
                if($stableState.state -ne 'ON_AIR' -or [int]$stableState.pid -ne [int]$phasePids[$stableChannel.id]) { throw "$phase did not remain ON_AIR with the startup PID during 30-second stabilization." }
            }
            $remainingStable=($stableUntil-[datetime]::UtcNow).TotalSeconds
            if($remainingStable -gt 0){Start-Sleep -Seconds ([math]::Min(5,[math]::Ceiling($remainingStable)))}
        } while ([datetime]::UtcNow -lt $stableUntil)
        Save-Result @{stabilized_seconds=30;at=[datetime]::UtcNow.ToString('o');pids=$phasePids} "$phase/STABILIZED.json"
        if ($RequireTransportAdmission) {
            $admissionRounds=@()
            foreach ($channel in $channels) {
                $admissionPending.Clear()
                $admissionPending[$channel.id]=Start-Beta7TransportProbe -TspExe $TspExe -Port $channel.port -OutputDirectory (Join-Path $runRoot "$phase/admission/stabilized") -Label $channel.id
                do {
                    foreach($liveChannel in $channels){
                        $liveState=Invoke-Station GET "/api/staff/egress/channels/$($liveChannel.id)/state"
                        if($liveState.state -ne 'ON_AIR' -or [int]$liveState.pid -ne [int]$phasePids[$liveChannel.id]){throw "$phase worker state/PID changed during serialized transport admission."}
                    }
                    $admissionResult=Complete-Beta7TransportProbe $admissionPending[$channel.id]
                    if ($null -eq $admissionResult) { Start-Sleep -Seconds 1 }
                } while ($null -eq $admissionResult)
                $admissionRounds += [pscustomobject]@{round='stabilized-30s-analyze';excluded_from_verdict=$false;result=$admissionResult}
                $admissionPending.Remove($channel.id)
                if ($admissionResult.verdict -ne 'PASS') { throw "${phase} stabilized transport proof failed for $($channel.id)." }
            }
            Save-Result $admissionRounds "$phase/TRANSPORT-ADMISSION.json"
            Write-ProgressLog "${phase} stabilized 30-second analyze probe passed 0/0/0 on all three channels."
        }
        $premeasurementTopology=Invoke-PremeasurementTopologyProof $phase $plan $offsets $phaseExpectedElements
        # The measured four hours grade only bytes written after the separately
        # passing controlled-transition preflight.
        $offsets=Get-LogOffsets
        # Give the synchronous phase receipt a near-future deadline before the
        # four-hour clock starts.  A missed receipt aborts the phase.
        $begin = [datetime]::UtcNow.AddSeconds(60)
        if($begin -lt $scheduleStart){$begin=$scheduleStart}
        $end = $begin.AddMinutes($Minutes)
        if ($scheduleStart.AddMinutes(5*$slotCount) -lt $end.AddMinutes(1)) { throw 'Published horizon does not cover the full measured phase.' }
        if ($OnPhaseStarted) {
            $receipt=@(& $OnPhaseStarted $phase $begin $end)
            if($receipt.Count -ne 1 -or [string]$receipt[0].status -cne 'PHASE_READY_AND_REMOTELY_VERIFIED' -or
                [string]$receipt[0].candidate_source_sha -cne $SourceSha -or [string]$receipt[0].phase -cne $phase -or
                [string]$receipt[0].begin_utc -cne $begin.ToString('o') -or [string]$receipt[0].end_utc -cne $end.ToString('o') -or
                [string]$receipt[0].remote_commit -notmatch '^[0-9a-f]{40}$'){
                throw "$phase synchronous remotely verified phase receipt is absent or does not bind the exact measurement."
            }
        }
        while ([datetime]::UtcNow -lt $begin) { Start-Sleep -Seconds 2 }
        if([datetime]::UtcNow -gt $begin.AddSeconds(15)){throw "$phase measured begin was missed after its synchronous receipt."}
        Save-Result @{phase=$phase;begin=$begin.ToString('o');planned_end=$end.ToString('o');source_sha=$SourceSha} "$phase/SOAK-START.json"
        $samples = [Collections.Generic.List[object]]::new()
        $captionSamples = [Collections.Generic.List[object]]::new()
        $expectedPids = $phasePids
        $nextCaption = $begin
        $nextProgress = $begin
        $nextHealth = $begin
        $transportSchedule = @(Get-TransportRoundSchedule $begin $Minutes)
        $transportRoundIndex = 0
        $activeTransportRound = $null
        $transportQueue=[Collections.Generic.Queue[object]]::new()
        $transportGrades = [Collections.Generic.List[object]]::new()
        Write-ProgressLog "${phase}: measured $Minutes-minute soak started on all three channels"
        while ([datetime]::UtcNow -lt $end) {
            $tick = [datetime]::UtcNow
            foreach ($channel in $channels) {
                $state = Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/state"
                $process = if ($state.pid) { Get-Process -Id $state.pid -ErrorAction Stop } else { $null }
                $row = [pscustomobject]@{at=[datetime]::UtcNow.ToString('o');channel=$channel.id;state=$state.state;pid=$state.pid;source_label=$state.current_source_label;
                    last_error=$state.last_error;working_set_mb=$(if($process){[math]::Round($process.WorkingSet64/1MB,2)}else{$null})}
                $samples.Add($row)
                $row | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $runRoot "$phase/states.ndjson") -Encoding utf8
                if ($state.state -ne 'ON_AIR' -or -not $process) { throw "$phase channel $($channel.id) stopped producing a live ON_AIR worker." }
                if (-not $expectedPids.ContainsKey($channel.id)) { $expectedPids[$channel.id]=$state.pid }
                if ($state.pid -ne $expectedPids[$channel.id]) { throw "$phase unexpected restart of $($channel.id)." }
                if ($tick -ge $nextCaption) {
                    $status = Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/caption-status"
                    $proofs = @(Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/caption-proofs?limit=20")
                    $entry = [pscustomobject]@{at=[datetime]::UtcNow.ToString('o');channel=$channel.id;status=$status;proofs=$proofs}
                    $captionSamples.Add($entry)
                    $entry | ConvertTo-Json -Depth 16 -Compress | Add-Content -LiteralPath (Join-Path $runRoot "$phase/captions.ndjson") -Encoding utf8
                }
                $profileCheck=Invoke-Station GET '/api/staff/station/profile'
                if($profileCheck.live_captions_enabled -ne $false){throw "$phase station profile changed from captions OFF."}
            }
            foreach ($probeChannel in @($transportPending.Keys)) {
                $transportResult = Complete-Beta7TransportProbe $transportPending[$probeChannel]
                if ($null -ne $transportResult) {
                    $transportResult | Add-Member -NotePropertyName round -NotePropertyValue $activeTransportRound.round -Force
                    $transportResult | Add-Member -NotePropertyName offset_minutes -NotePropertyValue $activeTransportRound.offset_minutes -Force
                    $transportResult | Add-Member -NotePropertyName target_utc -NotePropertyValue ([datetime]$activeTransportRound.target_utc).ToString('o') -Force
                    $transportGrades.Add($transportResult)
                    $transportPending.Remove($probeChannel)
                    Save-Result @($transportGrades.ToArray()) "$phase/transport-results.json"
                    if ($transportResult.verdict -ne 'PASS') { throw "$phase transport proof failed for ${probeChannel}: $($transportResult.reason)" }
                    if($transportQueue.Count){
                        $nextProbeChannel=$transportQueue.Dequeue()
                        $transportPending[$nextProbeChannel.id]=Start-Beta7TransportProbe -TspExe $TspExe -Port $nextProbeChannel.port -OutputDirectory (Join-Path $runRoot "$phase/transport/$($activeTransportRound.round)") -Label $nextProbeChannel.id
                    }
                }
            }
            if (-not $transportPending.Count -and -not $transportQueue.Count -and $transportRoundIndex -lt $transportSchedule.Count -and $tick -ge $transportSchedule[$transportRoundIndex].target_utc) {
                $round=$transportSchedule[$transportRoundIndex]
                if ($tick -gt $round.deadline_utc) { throw "$phase transport round $($round.round) missed its explicit start deadline." }
                if ($transportPending.Count -or $transportQueue.Count) { throw 'Previous serialized transport round did not finish before the next collection.' }
                foreach ($channel in $channels) { $transportQueue.Enqueue($channel) }
                $activeTransportRound=$round
                $nextProbeChannel=$transportQueue.Dequeue()
                $transportPending[$nextProbeChannel.id]=Start-Beta7TransportProbe -TspExe $TspExe -Port $nextProbeChannel.port -OutputDirectory (Join-Path $runRoot "$phase/transport/$($round.round)") -Label $nextProbeChannel.id
                $transportRoundIndex++
            }
            if ($tick -ge $nextHealth) {
                $periodicHealth=Invoke-Station GET '/health'
                if ($periodicHealth.status -ne 'healthy' -or $periodicHealth.schema -ne 'current' -or $periodicHealth.version -ne '1.0.0-beta.7') { throw "$phase periodic health check failed." }
                $periodicHealth | Add-Member -NotePropertyName at -NotePropertyValue ([datetime]::UtcNow.ToString('o')) -Force
                $periodicHealth | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $runRoot "$phase/health.ndjson") -Encoding utf8
                $nextHealth=$tick.AddSeconds(30)
            }
            if ($tick -ge $nextCaption) {
                try {
                    $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
                    $os = Get-CimInstance Win32_OperatingSystem
                    $hardware = @{at=[datetime]::UtcNow.ToString('o');cpu_percent=[double]$cpu.PercentProcessorTime;free_ram_mb=[math]::Round([double]$os.FreePhysicalMemory/1024)}
                } catch { $hardware = @{at=[datetime]::UtcNow.ToString('o');error_type=$_.Exception.GetType().Name} }
                $hardware | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $runRoot "$phase/hardware.ndjson") -Encoding utf8
                $nextCaption=$tick.AddSeconds(30)
            }
            if ($tick -ge $nextProgress) { Write-ProgressLog "${phase}: $([int]($tick-$begin).TotalMinutes)/$Minutes measured minutes"; $nextProgress=$tick.AddMinutes(5) }
            $pause = 10-([datetime]::UtcNow-$tick).TotalSeconds
            if ($pause -gt 0) { Start-Sleep -Milliseconds ([int]($pause*1000)) }
        }
        # The terminal sample is taken before any grading or log copying so a
        # late worker death cannot be hidden by the last periodic observation.
        $finalStates=@(); $finalRows=@()
        foreach($channel in $channels) {
            $finalState=Invoke-Station GET "/api/staff/egress/channels/$($channel.id)/state"
            $finalProcess=$null; if($finalState.pid){try{$finalProcess=Get-Process -Id $finalState.pid -ErrorAction Stop}catch{}}
            $finalRow=[pscustomobject]@{at=[datetime]::UtcNow.ToString('o');channel=$channel.id;state=$finalState.state;pid=$finalState.pid;source_label=$finalState.current_source_label;last_error=$finalState.last_error;live=[bool]$finalProcess}
            $finalRows += $finalRow; $samples.Add($finalRow)
            $finalStates += [pscustomobject]@{channel_id=$channel.id;state=$finalState.state;pid=$finalState.pid;current_source_label=$finalState.current_source_label;last_error=$finalState.last_error}
            $finalRow | ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $runRoot "$phase/states.ndjson") -Encoding utf8
            if($finalState.state -ne 'ON_AIR' -or -not $finalProcess -or [int]$finalState.pid -ne [int]$phasePids[$channel.id]) { throw "$phase final state/PID sample is not ON_AIR with the same live startup PID for $($channel.id)." }
        }
        $states=$finalStates
        Save-Result @{at=[datetime]::UtcNow.ToString('o');channels=$finalRows} "$phase/FINAL-STATE.json"
        $finalHealth=Invoke-Station GET '/health'
        if ($finalHealth.status -ne 'healthy' -or $finalHealth.schema -ne 'current' -or $finalHealth.version -ne '1.0.0-beta.7') { throw "$phase final health check failed." }
        $finalProfile=Invoke-Station GET '/api/staff/station/profile'
        if($finalProfile.live_captions_enabled -ne $false){throw "$phase terminal station profile is not captions OFF."}
        Save-Result @{at=[datetime]::UtcNow.ToString('o');health=$finalHealth;profile=$finalProfile;captions_off=($finalProfile.live_captions_enabled -eq $false)} "$phase/FINAL-HEALTH.json"
        if ($transportPending.Count -or $transportQueue.Count -or $transportRoundIndex -ne $transportSchedule.Count) { throw "$phase transport rounds did not all finish before the measured end." }
        $grades = @(Get-BoundaryGrades $plan $samples $begin $end)
        $channelGrades = @()
        foreach ($channel in $channels) {
            $items = @($grades | Where-Object { $_.channel -eq $channel.id })
            $passed = @($items | Where-Object { $_.pass }).Count
            $rate = if ($items.Count) { 100*$passed/$items.Count } else { 0 }
            $channelGrades += @{channel=$channel.id;boundaries=$items.Count;passed=$passed;percent=$rate;pass=($items.Count -ge [math]::Floor($Minutes/5)-1 -and $rate -ge 95)}
        }
        $contextLogs = @()
        $contextDir = Join-Path $runRoot "$phase/preroll-context"
        if (Test-Path -LiteralPath $contextDir) {
            foreach ($contextFile in @(Get-ChildItem -LiteralPath $contextDir -File -Filter '*.log')) {
                $contextLogs += [pscustomobject]@{path=$contextFile.FullName;text=(Get-Content -LiteralPath $contextFile.FullName -Raw)}
            }
        }
        $measuredLogs = @(Copy-PhaseLogs $phase $offsets)
        $logs = @(Select-Beta7GradingLogs $measuredLogs $contextLogs $attachOn)
        $failureGrades = Get-Beta7FailureGrades $logs $phaseExpectedElements
        $workerTopology = Get-Beta7WorkerTopologyGrade $logs $channels $states $transportGrades.ToArray() $phaseExpectedElements
        $transportComplete = $transportPending.Count -eq 0 -and $transportQueue.Count -eq 0
        foreach ($channel in $channels) {
            $proofCount = @($transportGrades.ToArray() | Where-Object { $_.label -eq $channel.id -and $_.verdict -eq 'PASS' }).Count
            if ($proofCount -ne $transportSchedule.Count) { $transportComplete = $false }
        }
        $f2Pass = @($channelGrades | Where-Object { -not $_.pass }).Count -eq 0
        $verdict = if ($f2Pass -and $workerTopology.pass -and $failureGrades.f1_pass -and $failureGrades.f3_pass -and $transportComplete) { 'PASS' } else { 'FAIL' }
        Save-Result @{verdict=$verdict;scope='Programme timing, uninterrupted worker lifetime and sampled UDP transport';source_sha=$SourceSha;begin=$begin.ToString('o');end=[datetime]::UtcNow.ToString('o');
            channels=$channelGrades;boundaries=$grades;f1=@{pass=$failureGrades.f1_pass;worker_or_timeout_lines=$failureGrades.f1_worker_or_timeout_lines;commit_without_preroll=$failureGrades.f1_commit_without_preroll};f2=@{pass=$f2Pass;minimum_percent=95;boundary_explanations=@($grades | ForEach-Object { @{channel=$_.channel;scheduled_at=$_.scheduled_at;pass=$_.pass;explanation=$_.explanation;delay_seconds=$_.delay_seconds} })};f3=@{pass=$failureGrades.f3_pass;output_stall_lines=$failureGrades.f3_output_stall_lines};worker_topology=$workerTopology;
            transport_complete=$transportComplete;transport_results=@($transportGrades.ToArray());caption_evidence='Captured as supporting evidence; station profile captions-OFF is enforced periodically and terminally.';remaining=$null} "$phase/VERDICT.json"
        if ($verdict -ne 'PASS') { throw "$phase programme/lifetime soak failed." }
        Write-ProgressLog "$phase measured soak finished; programme/lifetime grade PASS"
    }
    Save-Result @{verdict='TIMING_LIFETIME_TRANSPORT_PASS';phases=$phases;source_sha=$SourceSha;remaining=$null} 'VERDICT.json'
} catch {
    Save-Result @{verdict='FAIL';source_sha=$SourceSha;error=$_.Exception.Message} 'VERDICT.json'
    throw
} finally {
    foreach ($probe in @($admissionPending.Values)) {
        try { Stop-Beta7TransportProbe $probe } catch { }
    }
    foreach ($probe in @($transportPending.Values)) {
        try { Stop-Beta7TransportProbe $probe }
        catch { Write-ProgressLog "Transport probe cleanup failed: $($_.Exception.GetType().Name)" }
    }
    # A schedule POST may commit remotely and then fail before its returned ID
    # reaches createdScheduleIds.  Once authenticated, always discover by the
    # exact run-owned notes so that zero recorded IDs cannot skip cleanup.
    if ($token) {
        try { $scheduleCleanup=Remove-RemainingOwnedSchedule; Save-Result $scheduleCleanup 'SCHEDULE-CLEANUP-VERIFIED.json' }
        catch {
            $cleanupFailure="schedule cleanup: $($_.Exception.Message)"
            Save-Result @{verdict='FAIL';error=$cleanupFailure;owned_schedule_ids=$createdScheduleIds} 'SCHEDULE-CLEANUP-FAILED.json'
            Save-Result @{verdict='FAIL';source_sha=$SourceSha;error='cleanup failure';cleanup_error=$cleanupFailure} 'VERDICT.json'
        }
    }
    if ($owned.Count -and $token) {
        try { Stop-OwnedChannels; Save-Result @{stopped=$owned;at=[datetime]::UtcNow.ToString('o')} 'STOP-VERIFIED.json'; $cleanupVerified=$true }
        catch {
            if($cleanupFailure){$cleanupFailure += '; stop cleanup: '+$_.Exception.Message}else{$cleanupFailure=$_.Exception.Message}
            Save-Result @{error=$cleanupFailure;channels=$owned;verdict='STOP-FAILED'} 'STOP-FAILED.json'
            Save-Result @{verdict='FAIL';source_sha=$SourceSha;error='cleanup failure';cleanup_error=$cleanupFailure} 'VERDICT.json'
            throw "Cleanup failed after the soak: $cleanupFailure"
        }
    }
    foreach ($folder in @('logs','data/egress')) {
        $path = Join-Path $ProgramDataRoot $folder
        if (Test-Path -LiteralPath $path) {
            $destination = Join-Path $runRoot "all-raw/$folder"
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Copy-Item -LiteralPath $path -Destination (Split-Path $destination) -Recurse -Force
        }
    }
    if($cleanupFailure){throw "Cleanup failed after the soak: $cleanupFailure"}
    $token=$null
}
