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
    [switch]$SelfTest
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
$channels = @(@{id='public';port=9001}, @{id='education';port=9002}, @{id='government';port=9003})
$phases = if ($Mode -eq 'Both') { @('ON','OFF') } else { @($Mode) }
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
function Save-Result($Value, [string]$RelativePath) {
    $destination = Join-Path $runRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $destination -Encoding utf8
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
function Stop-OwnedChannels {
    foreach ($channel in $owned) {
        Invoke-Station POST "/api/staff/egress/channels/$channel/commands" @{action='stop'} | Out-Null
    }
    $deadline = [datetime]::UtcNow.AddMinutes(2)
    do {
        $remaining = @()
        foreach ($channel in $owned) {
            $state = Invoke-Station GET "/api/staff/egress/channels/$channel/state"
            if ($state -and ($state.state -ne 'STOPPED' -or $state.pid)) { $remaining += $channel }
        }
        if (-not $remaining.Count) { return }
        Start-Sleep -Seconds 2
    } while ([datetime]::UtcNow -lt $deadline)
    throw "Owned channels did not stop: $($remaining -join ',')"
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
        [pscustomobject]@{channel=$slot.channel_id; scheduled_at=$slot.scheduled_at; asset_id=$slot.asset_id;
            expected_label=$slot.asset_label; delay_seconds=$delay; pass=($null -ne $delay -and $delay -le 30)}
    }
}
if ($SelfTest) {
    $plan = @([pscustomobject]@{channel_id='public';scheduled_at='2026-09-11T12:00:00Z';asset_id='test-a';asset_label='A'})
    $begin = [datetimeoffset]::Parse('2026-09-11T11:59:00Z').UtcDateTime
    $end = $begin.AddMinutes(3)
    foreach ($delay in @(10,30,31,301)) {
        $samples = @([pscustomobject]@{channel='public';source_label='A';at=$begin.AddMinutes(1).AddSeconds($delay).ToString('o')})
        $grade = @(Get-BoundaryGrades $plan $samples $begin $end)
        if ($grade.Count -ne 1 -or $grade[0].pass -ne ($delay -le 30)) { throw "Boundary fixture failed at $delay seconds" }
    }
    Save-Result @{verdict='PASS';checks='Boundary observations at10/30/31/301 seconds'} 'SELF-TEST.json'
    return
}
. (Join-Path $PSScriptRoot 'FixedBetaTransportProbe.ps1')
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
try {
    if (-not (Test-Path -LiteralPath $TspExe -PathType Leaf)) { throw "Installed transport probe is absent: $TspExe" }
    if (-not (Test-Path -LiteralPath $TokenPath -PathType Leaf)) { throw "Existing tester token is absent: $TokenPath" }
    $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
    if (-not $token) { throw 'Existing tester token file is empty.' }
    $health = Invoke-Station GET '/health'
    if ($health.status -ne 'healthy' -or $health.schema -ne 'current' -or $health.version -ne '1.0.0-beta.6') { throw 'Installed fixed beta health/version/schema is not ready.' }
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
    $scheduleStart = [datetime]::UtcNow.AddMinutes(15)
    $slotCount = [int][math]::Ceiling(($Minutes*$phases.Count+60)/5)
    $scheduleEnd = $scheduleStart.AddMinutes(5*$slotCount)
    $overlaps = @()
    foreach ($channel in $channels) {
        $existing = @(Invoke-Station GET "/api/staff/schedule?channel_id=$($channel.id)")
        $overlaps += @($existing | Where-Object {
            $_.scheduled_at -and ("$($_.state)" -notin @('cancelled','canceled','done','completed')) -and
            ([datetimeoffset]::Parse($_.scheduled_at).UtcDateTime -lt $scheduleEnd) -and
            ([datetimeoffset]::Parse($_.scheduled_at).UtcDateTime.AddSeconds([double]$(if($_.duration_seconds){$_.duration_seconds}else{300})) -gt $scheduleStart)
        } | ForEach-Object { [pscustomobject]@{channel_id=$channel.id;schedule_id=$_.id;state=$_.state;scheduled_at=$_.scheduled_at;duration_seconds=$_.duration_seconds;asset_id=$_.asset_id} })
    }
    if ($overlaps.Count) {
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
            $remaining += @($rows | Where-Object {
                $_.scheduled_at -and ("$($_.state)" -notin @('cancelled','canceled','done','completed')) -and
                ([datetimeoffset]::Parse($_.scheduled_at).UtcDateTime -lt $scheduleEnd) -and
                ([datetimeoffset]::Parse($_.scheduled_at).UtcDateTime.AddSeconds([double]$(if($_.duration_seconds){$_.duration_seconds}else{300})) -gt $scheduleStart)
            })
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
            Invoke-Station POST '/api/staff/playout/commit' @{channel_id=$channel.id;occurrence_id="$runId-$($channel.id)-$i";schedule_item_id=[string]$item.id} | Out-Null
            $observed = Invoke-Station GET "/api/staff/schedule/$($item.id)"
            if ($observed.state -ne 'published' -or $observed.asset_id -ne $asset.id) { throw "Slot $($item.id) is not published as intended." }
            $plan += [pscustomobject]@{channel_id=$channel.id;schedule_id=$item.id;asset_id=$asset.id;asset_label=$asset.title;scheduled_at=$at}
        }
        Write-ProgressLog "Published $slotCount five-minute slots for $($channel.id)"
    }
    Save-Result $plan 'published-plan.json'
    foreach ($phase in $phases) {
        if ($owned.Count) { Stop-OwnedChannels }
        # Include startup/preload proof for any reload that commits after the
        # measured window begins; intentional previous-phase Stop is excluded.
        $offsets = Get-LogOffsets
        $enabled = $phase -eq 'ON'
        Invoke-Station PUT '/api/staff/station/profile' @{live_captions_enabled=$enabled} | Out-Null
        $profile = Invoke-Station GET '/api/staff/station/profile'
        if ($profile.live_captions_enabled -ne $enabled) { throw 'Caption-mode readback mismatch.' }
        Save-Result @{phase=$phase;captions_enabled=$profile.live_captions_enabled} "$phase/profile.json"
        foreach ($channel in $channels) {
            $config = @{channel_id=$channel.id;enabled=$true;auto_start=$true;allow_software_fallback=$false;fill_policy='slate';slate_message="Owned $runId";
                sinks=@(@{kind='udp-ts';label=$runId;uri="udp://127.0.0.1:$($channel.port)";latency_ms=2000;loudness_regime='inherit';eas_tone_strip_enabled=$true})}
            Invoke-Station PUT "/api/staff/egress/channels/$($channel.id)/config" $config | Out-Null
            if ($owned -notcontains $channel.id) { $owned += $channel.id }
            Invoke-Station POST "/api/staff/egress/channels/$($channel.id)/commands" @{action='start'} | Out-Null
        }
        $deadline = [datetime]::UtcNow.AddMinutes(15)
        do {
            $states = @($channels | ForEach-Object { Invoke-Station GET "/api/staff/egress/channels/$($_.id)/state" })
            $ready = $states.Count -eq 3 -and @($states | Where-Object { $_.state -ne 'ON_AIR' -or -not $_.pid }).Count -eq 0
            if ($ready) { break }
            Start-Sleep -Seconds 10
        } while ([datetime]::UtcNow -lt $deadline)
        if (-not $ready) { throw "${phase}: all three channels did not reach ON_AIR." }
        # Setup must not count as the two-hour programme window. At most the
        # explicit 15-minute publication margin is spent on slate beforehand.
        while ([datetime]::UtcNow -lt $scheduleStart) { Start-Sleep -Seconds 2 }
        $begin = [datetime]::UtcNow
        $end = $begin.AddMinutes($Minutes)
        if ($scheduleStart.AddMinutes(5*$slotCount) -lt $end.AddMinutes(1)) { throw 'Published horizon does not cover the full measured phase.' }
        Save-Result @{phase=$phase;begin=$begin.ToString('o');planned_end=$end.ToString('o');source_sha=$SourceSha} "$phase/SOAK-START.json"
        $samples = [Collections.Generic.List[object]]::new()
        $captionSamples = [Collections.Generic.List[object]]::new()
        $expectedPids = @{}
        $nextCaption = $begin
        $nextProgress = $begin
        $nextTransport = $begin
        $transportRound = 0
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
            }
            foreach ($probeChannel in @($transportPending.Keys)) {
                $transportResult = Complete-FixedBetaTransportProbe $transportPending[$probeChannel]
                if ($null -ne $transportResult) {
                    $transportGrades.Add($transportResult)
                    $transportPending.Remove($probeChannel)
                    Save-Result @($transportGrades.ToArray()) "$phase/transport-results.json"
                    if ($transportResult.verdict -ne 'PASS') { throw "$phase transport proof failed for ${probeChannel}: $($transportResult.reason)" }
                }
            }
            if ($tick -ge $nextTransport -and $tick -lt $end.AddSeconds(-60)) {
                if ($transportPending.Count) { throw 'Previous transport probes did not finish before the next collection.' }
                foreach ($channel in $channels) {
                    $transportPending[$channel.id] = Start-FixedBetaTransportProbe -TspExe $TspExe -Port $channel.port -OutputDirectory (Join-Path $runRoot "$phase/transport/$transportRound") -Label $channel.id
                }
                $transportRound++
                $nextTransport = $nextTransport.AddMinutes(30)
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
        $grades = @(Get-BoundaryGrades $plan $samples $begin $end)
        $channelGrades = @()
        foreach ($channel in $channels) {
            $items = @($grades | Where-Object { $_.channel -eq $channel.id })
            $passed = @($items | Where-Object { $_.pass }).Count
            $rate = if ($items.Count) { 100*$passed/$items.Count } else { 0 }
            $channelGrades += @{channel=$channel.id;boundaries=$items.Count;passed=$passed;percent=$rate;pass=($items.Count -ge [math]::Floor($Minutes/5)-1 -and $rate -ge 95)}
        }
        $logs = @(Copy-PhaseLogs $phase $offsets)
        $badLines = @()
        foreach ($log in $logs) {
            $badLines += @($log.text -split "`n" | Where-Object { $_ -match 'WORKER_RESULT|reload-commit-timeout|no output for 10 seconds|unexpected.*exit|CTRL watchdog' })
        }
        $workerLogs = @($logs | Where-Object { $_.path -match 'gst-worker\.stdout\.log$' })
        $transportComplete = $transportPending.Count -eq 0
        foreach ($channel in $channels) {
            $proofCount = @($transportGrades.ToArray() | Where-Object { $_.label -eq $channel.id -and $_.verdict -eq 'PASS' }).Count
            if ($proofCount -lt [math]::Ceiling($Minutes/30)) { $transportComplete = $false }
        }
        $verdict = if (@($channelGrades | Where-Object { -not $_.pass }).Count -eq 0 -and $workerLogs.Count -ge 3 -and $badLines.Count -eq 0 -and $transportComplete) { 'PASS' } else { 'FAIL' }
        Save-Result @{verdict=$verdict;scope='Programme timing, uninterrupted worker lifetime and sampled UDP transport';source_sha=$SourceSha;begin=$begin.ToString('o');end=[datetime]::UtcNow.ToString('o');
            channels=$channelGrades;boundaries=$grades;worker_log_count=$workerLogs.Count;failure_lines=$badLines;
            transport_complete=$transportComplete;transport_results=@($transportGrades.ToArray());caption_evidence='Recorded separately; inspect cadence, FAIL visibility and documented zero-cue issue before release';remaining='Run existing preroll log grader and assess caption proof'} "$phase/VERDICT.json"
        if ($verdict -ne 'PASS') { throw "$phase programme/lifetime soak failed." }
        Write-ProgressLog "$phase measured soak finished; programme/lifetime grade PASS"
    }
    Save-Result @{verdict='TIMING_LIFETIME_TRANSPORT_PASS';phases=$phases;source_sha=$SourceSha;remaining='Preroll log grade and caption assessment'} 'VERDICT.json'
} catch {
    Save-Result @{verdict='FAIL';source_sha=$SourceSha;error=$_.Exception.Message} 'VERDICT.json'
    throw
} finally {
    foreach ($probe in @($transportPending.Values)) {
        try { Stop-FixedBetaTransportProbe $probe }
        catch { Write-ProgressLog "Transport probe cleanup failed: $($_.Exception.GetType().Name)" }
    }
    if ($owned.Count -and $token) {
        try { Stop-OwnedChannels; Save-Result @{stopped=$owned;at=[datetime]::UtcNow.ToString('o')} 'STOP-VERIFIED.json' }
        catch { Save-Result @{error=$_.Exception.Message;channels=$owned} 'STOP-FAILED.json' }
    }
    foreach ($folder in @('logs','data/egress')) {
        $path = Join-Path $ProgramDataRoot $folder
        if (Test-Path -LiteralPath $path) {
            $destination = Join-Path $runRoot "all-raw/$folder"
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Copy-Item -LiteralPath $path -Destination (Split-Path $destination) -Recurse -Force
        }
    }
    $token=$null
}
