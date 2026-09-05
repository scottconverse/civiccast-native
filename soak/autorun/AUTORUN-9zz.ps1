# AUTORUN-9zz (soak8-e1acfe6) -- read-only: what restarted the workers once in the long-item phase
# of soak #4 (after the 22:22Z plan boundary)? STARTING/TRANSITIONING lines with last_error, reload /
# rollover / Content-reload / Live source lines, and worker process start times. Changes nothing.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9zz soak #4 boundary-phase restart diag", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$out += "## gst workers: pid, start time (UTC), cpu s, rss, threads"
$out += '```'
foreach ($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'egress\gst\worker\.py' })) {
  $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  if ($gp) { $out += "pid=$($p.ProcessId) started=$($gp.StartTime.ToUniversalTime().ToString('HH:mm:ss'))Z cpu_s=$([math]::Round($gp.CPU,1)) rss_mb=$([math]::Round($gp.WorkingSet64/1MB)) threads=$($gp.Threads.Count)" }
}
$out += '```'
$log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$lines = @(Get-Content $log -Tail 60000 -ErrorAction SilentlyContinue | Where-Object { $_ -match '^2026-09-05 (16:[1-5]|17:)' })
$out += "## lines since 16:10 local (22:10Z): $($lines.Count)"
$out += "## STARTING / TRANSITIONING / STOPPED / FALLBACK (with last_error)"
$out += '```'
$out += ($lines | Where-Object { $_ -match 'egress state -> (STARTING|TRANSITIONING|STOPPED|FALLBACK_SLATE|DRAINING)' } | ForEach-Object { $_.Substring(0, [Math]::Min(420, $_.Length)) } | Select-Object -Last 60)
$out += '```'
$out += "## reload / rollover / Content-reload / Live source / exited / plan lines"
$out += '```'
$out += ($lines | Where-Object { $_ -match 'reload|rollover|Content-reload|Live source|exited|plan |segment\(s\)|horizon|EOS' -and $_ -notmatch 'egress state -> ON_AIR' } | ForEach-Object { $_.Substring(0, [Math]::Min(400, $_.Length)) } | Select-Object -Last 60)
$out += '```'
foreach ($id in 'public','education','government') {
  $out += "## $id gst-worker.stderr.log (last 25)"
  $out += '```'
  $out += (Get-Content "C:\ProgramData\CivicCast\data\egress\$id\logs\gst-worker.stderr.log" -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
  $out += '```'
}
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9zz-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9zz-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9zz boundary-phase restart diag $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
