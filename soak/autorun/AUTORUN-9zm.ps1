# AUTORUN-9zm (soak8-e1acfe6) -- read-only: is the caption-tap fix (PR #172, kit 91caebc) active?
# The first soak #2 rollup still shows the control plane near 2.9 cores. Capture: caption
# runtime-status.json per channel, caption/overload/pause/stall/relaunch log lines and counts,
# the station profile (live_captions_enabled), and a 10 s per-process CPU sample. Changes nothing.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9zm soak #5 first-30-min relaunch diag (clean install of 609273d, #174 on disk)", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")

$out += "## caption runtime-status.json files (anywhere under ProgramData\CivicCast)"
$out += '```'
$files = @(Get-ChildItem 'C:\ProgramData\CivicCast' -Recurse -Filter 'runtime-status.json' -File -ErrorAction SilentlyContinue)
$out += "found: $($files.Count)"
foreach ($f in $files) { $out += "$($f.FullName) $($f.LastWriteTimeUtc.ToString('o'))"; $out += (Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue) }
$out += '```'

$log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$tail = @(Get-Content $log -Tail 12000 -ErrorAction SilentlyContinue)
$out += "## control_plane-app.log (last 6000 lines) counts"
$out += '```'
$pats = [ordered]@{ caption_tap='captions.tap_worker'; overload='Caption tap overload'; paused='paus'; within_capacity='within-capacity|within capacity'; live_captions_disabled='live caption|live_captions'; critical='CRITICAL'; warning='WARNING'; stall='stall'; relaunch='relaunch'; unicode='UnicodeEncodeError'; traceback='Traceback' }
foreach ($k in $pats.Keys) { $out += "$k = $(@($tail | Where-Object { $_ -match $pats[$k] }).Count)" }
$out += "first line: $(if ($tail.Count) { $tail[0].Substring(0,[Math]::Min(60,$tail[0].Length)) })"
$out += "last line:  $(if ($tail.Count) { $tail[-1].Substring(0,[Math]::Min(60,$tail[-1].Length)) })"
$out += '```'
$out += "## STARTING/TRANSITIONING/STOPPED/FALLBACK lines with last_error since 20:20 local (02:20Z)"
$out += '```'
$out += ($tail | Where-Object { $_ -match 'egress state -> (STARTING|STOPPED|FALLBACK_SLATE|DRAINING)' -and $_ -match '^2026-09-05 (20|21):' } | Select-Object -Last 40 | ForEach-Object { $_.Substring(0, [Math]::Min(420, $_.Length)) })
$out += '```'
$out += "## rollover / reload / Content-reload / EOS / plan lines since 02:20Z"
$out += '```'
$out += ($tail | Where-Object { $_ -match 'rollover|reload|Content-reload|EOS|exited|segment\(s\)|PlaylistCap|clamp' -and $_ -match '^2026-09-05 (20|21):' -and $_ -notmatch 'egress state -> ON_AIR' } | Select-Object -Last 40 | ForEach-Object { $_.Substring(0, [Math]::Min(300, $_.Length)) })
$out += '```'
$out += "## worker processes: threads/RSS/start"
$out += '```'
foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'egress\gst\worker\.py' })) { $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($gp) { $out += "pid=$($p.ProcessId) started=$($gp.StartTime.ToUniversalTime().ToString('HH:mm:ss'))Z threads=$($gp.Threads.Count) rss_mb=$([math]::Round($gp.WorkingSet64/1MB)) cpu_s=$([math]::Round($gp.CPU,1))" } }
$out += '```'
foreach ($id in 'public','education','government') {
  $out += "## $id gst-worker.stderr.log (last 15)"
  $out += '```'
  $out += (Get-Content "C:\ProgramData\CivicCast\data\egress\$id\logs\gst-worker.stderr.log" -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
  $out += '```'
}
foreach ($k in 'caption_tap','stall','relaunch','critical','warning') {
  $hits = @($tail | Where-Object { $_ -match $pats[$k] } | Select-Object -Last 30)
  $out += "## $k (last 30)"
  $out += '```'
  $out += ($hits | ForEach-Object { $_.Substring(0, [Math]::Min(260, $_.Length)) })
  $out += '```'
}

$out += "## station profile / channel state"
$out += '```'
$tokenFile = "$root\state\token"
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  foreach ($path in '/api/staff/station/profile', '/api/staff/egress/channels/public/state', '/api/staff/egress/channels/education/state', '/api/staff/egress/channels/government/state') {
    try { $r = Invoke-WebRequest -Uri ($base + $path) -Headers $hdr -TimeoutSec 20 -UseBasicParsing; $out += "GET $path -> $([int]$r.StatusCode) $($r.Content.Substring(0,[Math]::Min(900,$r.Content.Length)))" } catch { $out += "GET $path -> $($_.Exception.Message)" }
  }
} else { $out += 'no state\token' }
$out += '```'

$out += "## per-process CPU (10 s sample) with command lines"
$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(python|ffmpeg|gst|pythonservice)' })
$s0 = @{}; foreach ($p in $procs) { $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($gp) { $s0[$p.ProcessId] = $gp.CPU } }
Start-Sleep -Seconds 10
$out += '```'
foreach ($p in $procs) {
  $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  if (-not $gp) { continue }
  $d = $gp.CPU - $s0[$p.ProcessId]
  $cmd = "$($p.CommandLine)"; if ($cmd.Length -gt 150) { $cmd = $cmd.Substring(0,150) }
  $out += "pid=$($p.ProcessId) ppid=$($p.ParentProcessId) cpu_pct=$([math]::Round($d/10*100)) rss_mb=$([math]::Round($gp.WorkingSet64/1MB)) threads=$($gp.Threads.Count) :: $cmd"
}
$out += '```'

New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9zm-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9zm-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9zm caption-tap fix check $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
