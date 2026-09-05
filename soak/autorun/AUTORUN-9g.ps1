# AUTORUN-9g (soak8-e1acfe6) -- read-only diagnostics for the restarts seen in rollup 1:
# worker stderr/stdout logs per channel, control-plane log lines (automation/egress/stall/
# rollover/reload/Unicode), per-process CPU split for the control plane, schedule item counts.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9g restart diagnostics", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")

$out += "## processes (python/ffmpeg/gst) with command lines"
$out += '```'
$out += (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(python|ffmpeg|gst)' } | ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "pid=$($_.ProcessId) ppid=$($_.ParentProcessId) cpu_s=$([math]::Round($p.CPU,1)) rss_mb=$([math]::Round($p.WorkingSet64/1MB)) threads=$($p.Threads.Count) cmd=$($_.CommandLine.Substring(0,[Math]::Min(220,$_.CommandLine.Length)))" })
$out += '```'

foreach ($id in 'public','education','government') {
  $d = "C:\ProgramData\CivicCast\data\egress\$id\logs"
  $out += "## $id worker logs ($d)"
  foreach ($f in 'gst-worker.stderr.log','gst-worker.stdout.log') {
    $out += "### $f (last 40)"
    $out += '```'
    $out += (Get-Content "$d\$f" -Tail 40 -ErrorAction SilentlyContinue)
    $out += '```'
  }
}

$out += "## control_plane-app.log (automation/egress/stall/rollover/reload/Unicode/ERROR, last 120)"
$out += '```'
$out += (Get-Content 'C:\ProgramData\CivicCast\logs\control_plane-app.log' -Tail 4000 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'automation|egress|stall|rollover|reload|Unicode|ERROR|Traceback|relaunch|STOPPED|STARTING' } | Select-Object -Last 120)
$out += '```'

$out += "## control-plane CPU sampling (10 s)"
$cp = Get-Process -Name 'python' -ErrorAction SilentlyContinue | Sort-Object CPU -Descending | Select-Object -First 1
if ($cp) {
  $c0 = $cp.CPU; Start-Sleep -Seconds 10; $cp.Refresh(); $c1 = $cp.CPU
  $out += "pid=$($cp.Id) cpu_seconds_delta_10s=$([math]::Round($c1-$c0,1)) (=> ~$([math]::Round(($c1-$c0)/10*100))% of one core) rss_mb=$([math]::Round($cp.WorkingSet64/1MB)) threads=$($cp.Threads.Count)"
}

$tokenFile = "$root\state\token"
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  $out += "## schedule / channel API"
  $out += '```'
  foreach ($path in '/api/staff/schedule?limit=5', '/api/staff/egress/channels') {
    try { $r = Invoke-WebRequest -Uri ($base + $path) -Headers $hdr -TimeoutSec 20 -UseBasicParsing; $out += "GET $path -> $([int]$r.StatusCode) $($r.Content.Substring(0,[Math]::Min(900,$r.Content.Length)))" } catch { $out += "GET $path -> $($_.Exception.Message)" }
  }
  $out += '```'
}

New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9g-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9g-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9g restart diagnostics $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
