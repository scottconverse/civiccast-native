# AUTORUN-3 (soak8-e1acfe6) -- egress proof: TSDuck on the three UDP sinks, which
# engine is really running per channel, worker-restart (relaunch) tracking per
# channel, CPU/RSS of the worker processes, 30-minute rollups, T+2h verdict.
# Run by the CivicCastSoak-Poll task every cycle once C:\CivicCastSoak\state\soak-started
# exists; self-throttled to ~30 minutes. Fails CLOSED: an empty/absent tsp report is a
# failure, never a pass.
#
# Per-channel state read each cycle: GET /api/staff/egress/channels/<id>/state,
# which serializes civiccast.egress.models.EgressStateRow (models.py, main civiccast-native
# checkout at C:\Users\scott\Desktop\Code\civiccast-native):
#   - state                 models.py:512
#   - current_source_label  models.py:513
#   - pid                   models.py:516
#   - last_error            models.py:517
param(
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'

$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$kit   = "$root\kit-e5020746fa40e7a3f1a160d3a8e1add5c3b57786"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$now   = (Get-Date).ToUniversalTime()

if (-not (Test-Path "$root\state\soak-started")) { exit 0 }

# ------------------------------------------------------------------- throttle
$lastFile = "$root\state\last-egress-run"
if (Test-Path $lastFile) {
  $last = $null
  try { $last = [datetime]::Parse((Get-Content $lastFile -Raw).Trim()).ToUniversalTime() } catch { }
  if ($last -and ($now - $last).TotalMinutes -lt 28) { exit 0 }
}
if (-not $DryRun) { Set-Content $lastFile -Value $now.ToString('o') -Encoding ascii }

$outDir = "$root\reports\egress\$stamp"
New-Item -Force -ItemType Directory $outDir | Out-Null
New-Item -Force -ItemType Directory "$repo\soak\egress" | Out-Null

# --------------------------------------------------------------- find tsp.exe
# Primary: the new kit dir (kit-e5020746...). Fallback: Get-ChildItem for
# tsp.exe anywhere under C:\CivicCastHostStore (the installed payload) if the
# kit-relative path is absent -- covers a kit that shipped without the tsduck
# subtree, or a kit dir that was cleaned up after install.
$tspCandidates = @(
  "$kit\packs\native-server-binaries\payload\tsduck\bin\tsp.exe",
  'C:\CivicCastHostStore\install\packs\native-server-binaries\payload\tsduck\bin\tsp.exe',
  'C:\CivicCastHostStore\install\tsduck\bin\tsp.exe',
  'C:\Program Files\CivicCast (Native)\tsduck\bin\tsp.exe'
)
$tsp = $tspCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tsp) {
  $found = Get-ChildItem -Path 'C:\CivicCastHostStore' -Filter 'tsp.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { $tsp = $found.FullName }
}
if (-not $tsp) {
  # last resort: still search the kit dir itself, in case its layout moved
  $found = Get-ChildItem -Path $kit -Filter 'tsp.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($found) { $tsp = $found.FullName }
}

# ------------------------------------------------ Test-TsProof (mirrors sandbox-lab)
function Test-TsProof {
  param([string]$TspExe, [int]$Port, [int]$Seconds, [string]$OutDir, [string]$Label)
  $result = [ordered]@{
    label = $Label; port = $Port; tsp_found = $false; ran = $false; timed_out = $false
    exit_code = $null; report_found = $false; report_bytes = $null; packets_total = $null
    invalid_syncs = $null; transport_errors = $null; discontinuities = $null
    pcr_pts_drift_ms = $null; verdict = 'not-run'
  }
  if (-not $TspExe -or -not (Test-Path $TspExe)) { $result.verdict = 'not-run: tsp.exe not found'; return $result }
  $result.tsp_found = $true
  $report = Join-Path $OutDir "tsduck-$Label-report.json"
  $stdout = Join-Path $OutDir "tsduck-$Label.stdout.log"
  $stderr = Join-Path $OutDir "tsduck-$Label.stderr.log"
  $tspArgs = @('-I','ip',"$Port",'--buffer-size','16777216','-P','until','--seconds',"$Seconds",'-P','analyze','--json','--output-file',$report,'-O','drop')
  try {
    $proc = Start-Process -FilePath $TspExe -ArgumentList $tspArgs -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    # PS 5.1: ExitCode is $null unless the handle was cached before exit (Gate A #158).
    $null = $proc.Handle
    try { if (-not $proc.WaitForExit(($Seconds + 20) * 1000)) { throw 'timeout' } }
    catch {
      $result.timed_out = $true
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
      Wait-Process -Id $proc.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    $proc.Refresh(); $result.ran = $true
    if (-not $result.timed_out) { $result.exit_code = $proc.ExitCode }
  } catch { $result.verdict = "error: $_"; return $result }
  if ($result.timed_out) { $result.verdict = 'fail-timed-out'; return $result }
  if ($null -eq $result.exit_code -or [int]$result.exit_code -ne 0) { $result.verdict = "fail-exit-$($result.exit_code)"; return $result }
  if (-not (Test-Path $report)) { $result.verdict = 'fail-no-report'; return $result }
  $result.report_found = $true
  $result.report_bytes = (Get-Item $report).Length
  if ($result.report_bytes -le 0) { $result.verdict = 'fail-empty-report'; return $result }
  try { $j = Get-Content $report -Raw | ConvertFrom-Json } catch { $result.verdict = 'fail-unparsable-report'; return $result }
  $ts = $j.ts
  if (-not $ts) { $result.verdict = 'fail-no-ts-section'; return $result }
  $result.packets_total    = $ts.packets
  $result.invalid_syncs    = $ts.invalid_syncs
  $result.transport_errors = $ts.transport_errors
  $result.discontinuities  = $ts.pcr_discontinuities
  if ($null -eq $result.discontinuities) { $result.discontinuities = $ts.discontinuities }
  if (-not $result.packets_total -or [int]$result.packets_total -le 0) { $result.verdict = 'fail-zero-packets'; return $result }
  $clean = ([int]$result.invalid_syncs -eq 0) -and ([int]$result.transport_errors -eq 0) -and ([int]$result.discontinuities -eq 0)
  $result.verdict = $(if ($clean) { 'pass' } else { 'fail-stream-errors' })
  return $result
}

# ------------------------------------------------------- worker-restart tracking
# Persist the last-known pid per channel under state\ ; a pid change (old pid
# non-null, new pid non-null, and they differ) counts as one relaunch. Also
# keep the last 3 non-empty last_error strings per channel.
function Update-RelaunchTracking {
  param([string]$ChannelId, [Nullable[int]]$NewPid, [string]$LastError, [string]$StateRoot)
  $pidFile   = Join-Path $StateRoot "last-pid-$ChannelId.txt"
  $countFile = Join-Path $StateRoot "relaunch-count-$ChannelId.txt"
  $errFile   = Join-Path $StateRoot "last-errors-$ChannelId.json"

  $prevPid = $null
  if (Test-Path $pidFile) { try { $prevPid = [int](Get-Content $pidFile -Raw).Trim() } catch { $prevPid = $null } }
  $count = 0
  if (Test-Path $countFile) { try { $count = [int](Get-Content $countFile -Raw).Trim() } catch { $count = 0 } }

  $relaunched = $false
  if ($null -ne $NewPid) {
    if ($null -ne $prevPid -and $prevPid -ne $NewPid) {
      $count++
      $relaunched = $true
    }
    Set-Content $pidFile -Value "$NewPid" -Encoding ascii
    Set-Content $countFile -Value "$count" -Encoding ascii
  }

  $errs = @()
  if (Test-Path $errFile) { try { $errs = @(Get-Content $errFile -Raw | ConvertFrom-Json) } catch { $errs = @() } }
  if ("$LastError".Trim().Length -gt 0) {
    $errs = @($LastError) + @($errs) | Select-Object -First 3
    $errs | ConvertTo-Json -Depth 3 | Set-Content $errFile -Encoding utf8
  }

  return [pscustomobject]@{
    prev_pid = $prevPid; new_pid = $NewPid; relaunched_this_cycle = $relaunched
    relaunches_total = $count; last_errors = @($errs)
  }
}

# ---------------------------------------------- worker process CPU% + RSS sample
# Get-Process gives cumulative CPU seconds, not a %. We approximate CPU% by
# diffing against the previous cycle's cumulative CPU seconds and the wall
# time elapsed since that sample (this cycle is throttled to ~30 min, so the
# window is known). RSS is the process WorkingSet64 at sample time.
function Get-WorkerSample {
  param([string]$StateRoot, [datetime]$Now)
  $procs = @(Get-Process -Name 'python','gst-launch-1.0','ffmpeg' -ErrorAction SilentlyContinue)
  # GStreamer playout workers are python.exe processes running civiccast\egress\gst\worker.py (not gst-launch).
  $gstWorkers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'egress\\gst\\worker\.py' })
  $sampleFile = Join-Path $StateRoot 'last-cpu-sample.json'
  $prev = $null
  if (Test-Path $sampleFile) { try { $prev = Get-Content $sampleFile -Raw | ConvertFrom-Json } catch { $prev = $null } }
  $prevAt = $null
  if ($prev -and $prev.utc) { try { $prevAt = [datetime]::Parse($prev.utc).ToUniversalTime() } catch { $prevAt = $null } }
  $elapsedSec = $(if ($prevAt) { ($Now - $prevAt).TotalSeconds } else { $null })

  $rows = @()
  foreach ($p in $procs) {
    $cpuSecTotal = $(if ($p.CPU) { [double]$p.CPU } else { 0.0 })
    $prevCpu = $null
    if ($prev -and $prev.processes) {
      $match = @($prev.processes | Where-Object { $_.pid -eq $p.Id })
      if ($match.Count -gt 0) { $prevCpu = [double]$match[0].cpu_seconds_total }
    }
    $cpuPct = $null
    if ($null -ne $prevCpu -and $elapsedSec -and $elapsedSec -gt 0) {
      $cpuPct = [math]::Round((($cpuSecTotal - $prevCpu) / $elapsedSec) * 100, 2)
    }
    $rows += [ordered]@{
      name = $p.ProcessName; pid = $p.Id
      cpu_seconds_total = $cpuSecTotal; cpu_pct_since_last_sample = $cpuPct
      rss_bytes = $p.WorkingSet64
    }
  }
  $sampleOut = [ordered]@{ utc = $Now.ToString('o'); processes = @($rows) }
  if (-not $DryRun) { $sampleOut | ConvertTo-Json -Depth 6 | Set-Content $sampleFile -Encoding utf8 }
  return [pscustomobject]@{ elapsed_seconds_since_last_sample = $elapsedSec; processes = @($rows) }
}

# ------------------------------------------------------------ probe all three
$channelSpecs = @(
  @{ id = 'public';     port = 9001 },
  @{ id = 'education';  port = 9002 },
  @{ id = 'government'; port = 9003 }
)
$tokenFile = "$root\state\token"
$tok = $(if (Test-Path $tokenFile) { (Get-Content $tokenFile -Raw).Trim() } else { '' })
$hdr = $(if ($tok) { @{ Authorization = "Bearer $tok" } } else { $null })

$workerSample = Get-WorkerSample -StateRoot "$root\state" -Now $now

$rows = @()
foreach ($c in $channelSpecs) {
  $ts = Test-TsProof -TspExe $tsp -Port $c.port -Seconds 30 -OutDir $outDir -Label $c.id
  $row = [ordered]@{
    channel_id = $c.id; port = $c.port; tsduck = $ts
    engine_state = $null; engine = $null; last_error = $null; sink_connected = $null; api_error = $null
    current_source_label = $null; pid = $null
    relaunch = $null
  }
  if ($hdr) {
    try {
      $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/state" -Headers $hdr -TimeoutSec 20
      $row.engine_state           = $st.state
      $row.last_error             = $st.last_error
      $row.current_source_label   = $st.current_source_label
      $row.pid                    = $st.pid
      if ($st.PSObject.Properties.Name -contains 'engine') { $row.engine = $st.engine }
      # The state row carries the playout worker pid; the process name tells the engine:
      # python.exe = the GStreamer worker (civiccast\egress\gst\worker.py), ffmpeg.exe = ffmpeg.
      if (-not $row.engine -and $st.PSObject.Properties.Name -contains 'pid' -and $st.pid) {
        $wp = Get-Process -Id ([int]$st.pid) -ErrorAction SilentlyContinue
        if ($wp) {
          if ($wp.ProcessName -match '^python') { $row.engine = 'gstreamer' }
          elseif ($wp.ProcessName -match '^ffmpeg') { $row.engine = 'ffmpeg' }
          else { $row.engine = "unknown:$($wp.ProcessName)" }
        }
      }
    } catch { $row.api_error = "state: $($_.Exception.Message)" }
    try {
      $hl = @(Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/health?limit=1" -Headers $hdr -TimeoutSec 20)
      if ($hl.Count -gt 0) {
        $row.sink_connected = $hl[0].sink_connected
        if (-not $row.engine -and ($hl[0].PSObject.Properties.Name -contains 'engine')) { $row.engine = $hl[0].engine }
      }
    } catch { $row.api_error = "$($row.api_error); health: $($_.Exception.Message)" }
  }
  $newPid = $(if ($row.pid) { [int]$row.pid } else { $null })
  $row.relaunch = Update-RelaunchTracking -ChannelId $c.id -NewPid $newPid -LastError "$($row.last_error)" -StateRoot "$root\state"
  $rows += $row
}

$gst = @(Get-Process -Name 'gst-launch-1.0' -ErrorAction SilentlyContinue).Count
$ff  = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
# GStreamer workers are python worker.py processes, not gst-launch: count them as the engine.
$gst = [int]$gst + $gstWorkers.Count
$engineObserved = [ordered]@{
  gst_launch_processes = $gst; ffmpeg_processes = $ff; gst_worker_processes = $gstWorkers.Count; gst_worker_pids = @($gstWorkers | ForEach-Object { $_.ProcessId })
  inferred = $(if ($gst -gt 0 -and $ff -eq 0) { 'gstreamer' } elseif ($ff -gt 0 -and $gst -eq 0) { 'ffmpeg-fallback' } elseif ($gst -gt 0 -and $ff -gt 0) { 'mixed' } else { 'none-running' })
}

# per-cycle pass criterion: every channel ON_AIR on gstreamer, tsp passes, and
# no relaunch observed THIS cycle. (Cumulative relaunch counts are reported
# regardless of pass/fail -- they are diagnostic, not silently dropped.)
$cycleAllOnAirGst = -not @($rows | Where-Object {
  $_.engine_state -ne 'ON_AIR' -or (($_.engine) -and ($_.engine -ne 'gstreamer'))
}).Count
$cycleAllTspPass = -not @($rows | Where-Object { $_.tsduck.verdict -ne 'pass' }).Count
$cycleNoRelaunch = -not @($rows | Where-Object { $_.relaunch.relaunched_this_cycle }).Count
$cyclePass = $cycleAllOnAirGst -and $cycleAllTspPass -and $cycleNoRelaunch

$doc = [ordered]@{
  schema = 'civiccast-native-soak-egress-v2'; mission = 'soak8-e1acfe6'
  hostname = $env:COMPUTERNAME; utc = $stamp
  tsp_exe = $(if ($tsp) { $tsp } else { 'not-found' })
  engine_observed = $engineObserved
  worker_processes = $workerSample
  channels = @($rows)
  cycle_all_on_air_gstreamer = $cycleAllOnAirGst
  cycle_all_tsp_pass = $cycleAllTspPass
  cycle_no_relaunch = $cycleNoRelaunch
  overall = $(if ($cyclePass) { 'pass' } else { 'fail' })
}
if ($DryRun) {
  Write-Host "[DRYRUN] would write $repo\soak\egress\egress-$stamp.json and git add/commit/push. overall=$($doc.overall)"
} else {
  $doc | ConvertTo-Json -Depth 8 | Set-Content "$repo\soak\egress\egress-$stamp.json" -Encoding utf8
  git -C $repo add soak/egress
  git -C $repo commit --quiet -m "test: egress proof $stamp soak8-e1acfe6 ($($doc.overall))"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

# -------------------------------------------------------------- 30-min rollup
$startUtc = [datetime]::Parse((Get-Content "$root\state\soak-started" -Raw).Trim()).ToUniversalTime()
$elapsedH = ($now - $startUtc).TotalHours
$rollFile = "$root\state\last-rollup-hours"
$lastRoll = $(if (Test-Path $rollFile) { [double](Get-Content $rollFile -Raw) } else { 0 })
$rollupIntervalH = 0.5   # 30 minutes (was 4 hours for the 8h schedule)
if ([math]::Floor($elapsedH / $rollupIntervalH) -gt [math]::Floor($lastRoll / $rollupIntervalH)) {
  if (-not $DryRun) { Set-Content $rollFile -Value $elapsedH -Encoding ascii }
  $all = @(Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue)
  $hbs = @(Get-ChildItem "$repo\soak\heartbeats" -Filter 'heartbeat-*.json' -File -ErrorAction SilentlyContinue)
  $fails = 0
  foreach ($f in $all) { try { if ((Get-Content $f.FullName -Raw | ConvertFrom-Json).overall -ne 'pass') { $fails++ } } catch { $fails++ } }
  $md = @("# soak8-e1acfe6 rollup -- $env:COMPUTERNAME -- $stamp", "",
    "- soak start (UTC): $($startUtc.ToString('o'))",
    "- elapsed: $([math]::Round($elapsedH,2)) h of 2",
    "- egress probes: $($all.Count), failing: $fails",
    "- heartbeats: $($hbs.Count)",
    "- engine observed now: $($engineObserved.inferred) (gst=$gst ffmpeg=$ff)", "",
    "## worker process CPU/RSS (this probe)", "")
  foreach ($wp in $workerSample.processes) {
    $md += "- $($wp.name) (pid $($wp.pid)): cpu%=$($wp.cpu_pct_since_last_sample) cpu_seconds_total=$($wp.cpu_seconds_total) rss_mb=$([math]::Round($wp.rss_bytes/1MB,1))"
  }
  $md += ""
  $md += "## per-channel, this probe"
  $md += ""
  foreach ($r in $rows) {
    $md += "- **$($r.channel_id)** (udp $($r.port)): tsduck=$($r.tsduck.verdict), packets=$($r.tsduck.packets_total), invalid_syncs=$($r.tsduck.invalid_syncs), transport_errors=$($r.tsduck.transport_errors), discontinuities=$($r.tsduck.discontinuities), engine_state=$($r.engine_state), engine=$($r.engine), pid=$($r.pid), relaunches_total=$($r.relaunch.relaunches_total), relaunched_this_cycle=$($r.relaunch.relaunched_this_cycle), last_errors=$($r.relaunch.last_errors -join ' | ')"
  }
  if ($DryRun) {
    Write-Host "[DRYRUN] would write $repo\soak\SOAK-REPORT-$env:COMPUTERNAME-$stamp.md and git add/commit/push."
  } else {
    Set-Content "$repo\soak\SOAK-REPORT-$env:COMPUTERNAME-$stamp.md" -Value ($md -join "`n") -Encoding utf8
    git -C $repo add soak/
    git -C $repo commit --quiet -m "test: soak rollup $stamp soak8-e1acfe6"
    git -C $repo push --quiet origin $br 2>&1 | Out-Null
  }
}

# ------------------------------------------------------------ T+2h final verdict
if ($elapsedH -ge 2 -and -not (Test-Path "$repo\soak\final-verdict.json")) {
  $all = @(Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue)
  $egressFailures = @()
  $perChannelEngine = @{}
  $perChannelRelaunches = @{}
  $perChannelLastErrors = @{}
  $anyNotOnAirGst = @()
  foreach ($f in $all) {
    try {
      $j = Get-Content $f.FullName -Raw | ConvertFrom-Json
      foreach ($ch in $j.channels) {
        if (-not $perChannelEngine.ContainsKey($ch.channel_id)) { $perChannelEngine[$ch.channel_id] = @() }
        $e = $(if ($ch.engine) { "$($ch.engine)" } else { "$($j.engine_observed.inferred)" })
        if ($perChannelEngine[$ch.channel_id] -notcontains $e) { $perChannelEngine[$ch.channel_id] += $e }
        if ($ch.tsduck.verdict -ne 'pass') {
          $egressFailures += [ordered]@{ utc = $j.utc; channel_id = $ch.channel_id; verdict = $ch.tsduck.verdict; last_error = $ch.last_error }
        }
        if ($ch.engine_state -ne 'ON_AIR' -or ($e -and $e -ne 'gstreamer')) {
          $anyNotOnAirGst += [ordered]@{ utc = $j.utc; channel_id = $ch.channel_id; engine_state = $ch.engine_state; engine = $e }
        }
      }
    } catch { }
  }
  # live relaunch counts / last-errors come from the persisted per-channel
  # state files, which are the running cumulative counters this whole soak.
  foreach ($c in $channelSpecs) {
    $countFile = "$root\state\relaunch-count-$($c.id).txt"
    $errFile   = "$root\state\last-errors-$($c.id).json"
    $perChannelRelaunches[$c.id] = $(if (Test-Path $countFile) { [int](Get-Content $countFile -Raw).Trim() } else { 0 })
    $perChannelLastErrors[$c.id] = $(if (Test-Path $errFile) { @(Get-Content $errFile -Raw | ConvertFrom-Json) } else { @() })
  }
  $totalRelaunches = ($perChannelRelaunches.Values | Measure-Object -Sum).Sum
  $hbs = @(Get-ChildItem "$repo\soak\heartbeats" -Filter 'heartbeat-*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)
  $expectedHb = [math]::Floor($elapsedH * 2)
  $verdict = [ordered]@{
    schema = 'civiccast-native-fleet-soak-verdict-v2'
    mission = 'soak8-e1acfe6'
    hostname = $env:COMPUTERNAME
    utc = $stamp
    planned_hours = 2
    actual_hours = [math]::Round($elapsedH, 2)
    soak_start_utc = $startUtc.ToString('o')
    engine_per_channel = $perChannelEngine
    engine_observed_final = $engineObserved
    egress_probes = $all.Count
    egress_failures = @($egressFailures)
    not_on_air_gstreamer_events = @($anyNotOnAirGst)
    relaunches_per_channel = $perChannelRelaunches
    relaunches_total = $totalRelaunches
    last_errors_per_channel = $perChannelLastErrors
    heartbeats_written = $hbs.Count
    heartbeats_expected = $expectedHb
    gaps = @($(if ($hbs.Count -lt $expectedHb - 1) { "heartbeat gap: $($hbs.Count) written vs ~$expectedHb expected" }))
    verdict = $(if (@($egressFailures).Count -eq 0 -and @($anyNotOnAirGst).Count -eq 0 -and $totalRelaunches -eq 0 -and $hbs.Count -ge $expectedHb - 1) { 'PASS' } else { 'FAIL' })
    note = 'PASS requires: all channels ON_AIR on GStreamer at every cycle, tsp pass every cycle, and zero relaunches per channel. Relaunch/error counts are reported either way, never suppressed. Polling does NOT stop here -- a published verdict ends this mission data collection, never polling duty.'
  }
  if ($DryRun) {
    Write-Host "[DRYRUN] would write $repo\soak\final-verdict.json and git add/commit/push. verdict=$($verdict.verdict)"
  } else {
    $verdict | ConvertTo-Json -Depth 8 | Set-Content "$repo\soak\final-verdict.json" -Encoding utf8
    git -C $repo add soak/final-verdict.json
    git -C $repo commit --quiet -m "test: FINAL VERDICT $($verdict.verdict) $stamp soak8-e1acfe6"
    git -C $repo push --quiet origin $br 2>&1 | Out-Null
  }
}
exit 0
