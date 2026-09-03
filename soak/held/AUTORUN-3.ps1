# AUTORUN-3 (soak8-e1acfe6) -- egress proof: TSDuck on the three UDP sinks, which
# engine is really running per channel, drift/continuity, 4-hour rollups, T+8h verdict.
# Run by the CivicCastSoak-Poll task every cycle once C:\CivicCastSoak\state\soak-started
# exists; self-throttled to ~30 minutes. Fails CLOSED: an empty/absent tsp report is a
# failure, never a pass.
$ErrorActionPreference = 'Continue'

$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$kit   = "$root\kit"
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
Set-Content $lastFile -Value $now.ToString('o') -Encoding ascii

$outDir = "$root\reports\egress\$stamp"
New-Item -Force -ItemType Directory $outDir | Out-Null
New-Item -Force -ItemType Directory "$repo\soak\egress" | Out-Null

# --------------------------------------------------------------- find tsp.exe
$tspCandidates = @(
  "$kit\packs\native-server-binaries\payload\tsduck\bin\tsp.exe",
  'C:\CivicCastHostStore\install\packs\native-server-binaries\payload\tsduck\bin\tsp.exe',
  'C:\CivicCastHostStore\install\tsduck\bin\tsp.exe',
  'C:\Program Files\CivicCast (Native)\tsduck\bin\tsp.exe'
)
$tsp = $tspCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $tsp) {
  $found = Get-ChildItem -Path @("$kit", 'C:\CivicCastHostStore') -Filter 'tsp.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
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
    try { Wait-Process -Id $proc.Id -Timeout ($Seconds + 20) -ErrorAction Stop }
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

# ------------------------------------------------------------ probe all three
$channelSpecs = @(
  @{ id = 'public';     port = 9001 },
  @{ id = 'education';  port = 9002 },
  @{ id = 'government'; port = 9003 }
)
$tokenFile = "$root\state\token"
$tok = $(if (Test-Path $tokenFile) { (Get-Content $tokenFile -Raw).Trim() } else { '' })
$hdr = $(if ($tok) { @{ Authorization = "Bearer $tok" } } else { $null })

$rows = @()
foreach ($c in $channelSpecs) {
  $ts = Test-TsProof -TspExe $tsp -Port $c.port -Seconds 30 -OutDir $outDir -Label $c.id
  $row = [ordered]@{
    channel_id = $c.id; port = $c.port; tsduck = $ts
    engine_state = $null; engine = $null; last_error = $null; sink_connected = $null; api_error = $null
  }
  if ($hdr) {
    try {
      $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/state" -Headers $hdr -TimeoutSec 20
      $row.engine_state = $st.state
      $row.last_error   = $st.last_error
      if ($st.PSObject.Properties.Name -contains 'engine') { $row.engine = $st.engine }
    } catch { $row.api_error = "state: $($_.Exception.Message)" }
    try {
      $hl = @(Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/health?limit=1" -Headers $hdr -TimeoutSec 20)
      if ($hl.Count -gt 0) {
        $row.sink_connected = $hl[0].sink_connected
        if (-not $row.engine -and ($hl[0].PSObject.Properties.Name -contains 'engine')) { $row.engine = $hl[0].engine }
      }
    } catch { $row.api_error = "$($row.api_error); health: $($_.Exception.Message)" }
  }
  $rows += $row
}

$gst = @(Get-Process -Name 'gst-launch-1.0' -ErrorAction SilentlyContinue).Count
$ff  = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
$engineObserved = [ordered]@{
  gst_launch_processes = $gst; ffmpeg_processes = $ff
  inferred = $(if ($gst -gt 0 -and $ff -eq 0) { 'gstreamer' } elseif ($ff -gt 0 -and $gst -eq 0) { 'ffmpeg-fallback' } elseif ($gst -gt 0 -and $ff -gt 0) { 'mixed' } else { 'none-running' })
}

$doc = [ordered]@{
  schema = 'civiccast-native-soak-egress-v1'; mission = 'soak8-e1acfe6'
  hostname = $env:COMPUTERNAME; utc = $stamp
  tsp_exe = $(if ($tsp) { $tsp } else { 'not-found' })
  engine_observed = $engineObserved
  channels = @($rows)
  overall = $(if (@($rows | Where-Object { $_.tsduck.verdict -ne 'pass' }).Count -eq 0) { 'pass' } else { 'fail' })
}
$doc | ConvertTo-Json -Depth 8 | Set-Content "$repo\soak\egress\egress-$stamp.json" -Encoding utf8
git -C $repo add soak/egress
git -C $repo commit --quiet -m "test: egress proof $stamp soak8-e1acfe6 ($($doc.overall))"
git -C $repo push --quiet origin $br 2>&1 | Out-Null

# --------------------------------------------------------------- 4-hour rollup
$startUtc = [datetime]::Parse((Get-Content "$root\state\soak-started" -Raw).Trim()).ToUniversalTime()
$elapsedH = ($now - $startUtc).TotalHours
$rollFile = "$root\state\last-rollup-hours"
$lastRoll = $(if (Test-Path $rollFile) { [double](Get-Content $rollFile -Raw) } else { 0 })
if ([math]::Floor($elapsedH / 4) -gt [math]::Floor($lastRoll / 4)) {
  Set-Content $rollFile -Value $elapsedH -Encoding ascii
  $all = @(Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue)
  $hbs = @(Get-ChildItem "$repo\soak\heartbeats" -Filter 'heartbeat-*.json' -File -ErrorAction SilentlyContinue)
  $fails = 0
  foreach ($f in $all) { try { if ((Get-Content $f.FullName -Raw | ConvertFrom-Json).overall -ne 'pass') { $fails++ } } catch { $fails++ } }
  $md = @("# soak8-e1acfe6 rollup -- $env:COMPUTERNAME -- $stamp", "",
    "- soak start (UTC): $($startUtc.ToString('o'))",
    "- elapsed: $([math]::Round($elapsedH,2)) h of 8",
    "- egress probes: $($all.Count), failing: $fails",
    "- heartbeats: $($hbs.Count)",
    "- engine observed now: $($engineObserved.inferred) (gst=$gst ffmpeg=$ff)", "",
    "## per-channel, this probe", "")
  foreach ($r in $rows) {
    $md += "- **$($r.channel_id)** (udp $($r.port)): tsduck=$($r.tsduck.verdict), packets=$($r.tsduck.packets_total), invalid_syncs=$($r.tsduck.invalid_syncs), transport_errors=$($r.tsduck.transport_errors), discontinuities=$($r.tsduck.discontinuities), engine_state=$($r.engine_state), engine=$($r.engine), last_error=$($r.last_error)"
  }
  Set-Content "$repo\soak\SOAK-REPORT-$env:COMPUTERNAME-$stamp.md" -Value ($md -join "`n") -Encoding utf8
  git -C $repo add soak/
  git -C $repo commit --quiet -m "test: soak rollup $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

# ------------------------------------------------------------ T+8h final verdict
if ($elapsedH -ge 8 -and -not (Test-Path "$repo\soak\final-verdict.json")) {
  $all = @(Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue)
  $egressFailures = @()
  $perChannelEngine = @{}
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
      }
    } catch { }
  }
  $hbs = @(Get-ChildItem "$repo\soak\heartbeats" -Filter 'heartbeat-*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name)
  $expectedHb = [math]::Floor($elapsedH * 2)
  $verdict = [ordered]@{
    schema = 'civiccast-native-fleet-soak-verdict-v1'
    mission = 'soak8-e1acfe6'
    hostname = $env:COMPUTERNAME
    utc = $stamp
    planned_hours = 8
    actual_hours = [math]::Round($elapsedH, 2)
    soak_start_utc = $startUtc.ToString('o')
    engine_per_channel = $perChannelEngine
    engine_observed_final = $engineObserved
    egress_probes = $all.Count
    egress_failures = @($egressFailures)
    heartbeats_written = $hbs.Count
    heartbeats_expected = $expectedHb
    gaps = @($(if ($hbs.Count -lt $expectedHb - 1) { "heartbeat gap: $($hbs.Count) written vs ~$expectedHb expected" }))
    verdict = $(if (@($egressFailures).Count -eq 0 -and $hbs.Count -ge $expectedHb - 1) { 'PASS' } else { 'FAIL' })
    note = 'Polling does NOT stop here. A published verdict ends this mission data collection, never polling duty.'
  }
  $verdict | ConvertTo-Json -Depth 8 | Set-Content "$repo\soak\final-verdict.json" -Encoding utf8
  git -C $repo add soak/final-verdict.json
  git -C $repo commit --quiet -m "test: FINAL VERDICT $($verdict.verdict) $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}
exit 0
