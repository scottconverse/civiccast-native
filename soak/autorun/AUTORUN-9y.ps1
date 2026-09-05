# AUTORUN-9y (soak8-e1acfe6) -- read-only: why do the GStreamer workers stall/relaunch every ~30 s
# on the clean 91caebc install? Worker stderr/stdout tails, worker thread/RSS growth over 30 s,
# prepared per-plan files, and control-plane plan/segment/prepare/reload lines since 20:16Z.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9y worker stall diag (soak #3, kit 91caebc clean install)", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$out += "## worker processes: threads/RSS now and after 30 s"
$w0 = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'egress\gst\worker\.py' })
$out += '```'
foreach ($p in $w0) { $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($gp) { $out += "t0 pid=$($p.ProcessId) threads=$($gp.Threads.Count) rss_mb=$([math]::Round($gp.WorkingSet64/1MB)) handles=$($gp.HandleCount) cpu_s=$([math]::Round($gp.CPU,1)) started=$($gp.StartTime.ToUniversalTime().ToString('HH:mm:ss'))Z :: $($p.CommandLine.Substring(0,[Math]::Min(200,$p.CommandLine.Length)))" } }
Start-Sleep -Seconds 30
foreach ($p in $w0) { $gp = Get-Process -Id $p.ProcessId -ErrorAction SilentlyContinue; if ($gp) { $out += "t30 pid=$($p.ProcessId) threads=$($gp.Threads.Count) rss_mb=$([math]::Round($gp.WorkingSet64/1MB)) handles=$($gp.HandleCount) cpu_s=$([math]::Round($gp.CPU,1))" } else { $out += "t30 pid=$($p.ProcessId) GONE" } }
$w1 = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'egress\gst\worker\.py' })
$out += "workers now: $($w1.Count) pids=$(($w1 | ForEach-Object { $_.ProcessId }) -join ',')"
$out += (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(ffmpeg|gst)' } | ForEach-Object { "other: pid=$($_.ProcessId) ppid=$($_.ParentProcessId) $($_.Name) :: $($_.CommandLine.Substring(0,[Math]::Min(180,[Math]::Max(0,$_.CommandLine.Length))))" })
$out += '```'
foreach ($id in 'public','education','government') {
  $d = "C:\ProgramData\CivicCast\data\egress\$id"
  $out += "## $id : work dir + worker logs"
  $out += '```'
  $out += (Get-ChildItem $d -Directory -ErrorAction SilentlyContinue | ForEach-Object { "dir $($_.Name): $((Get-ChildItem $_.FullName -File -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum) | ForEach-Object { "files=$($_.Count) bytes=$($_.Sum)" })" })
  $out += (Get-ChildItem "$d\logs" -File -ErrorAction SilentlyContinue | ForEach-Object { "log $($_.Name) $($_.Length) $($_.LastWriteTimeUtc.ToString('HH:mm:ss'))Z" })
  $out += '```'
  foreach ($f in 'gst-worker.stderr.log','gst-worker.stdout.log') {
    $out += "### $id $f (last 60)"
    $out += '```'
    $out += (Get-Content "$d\logs\$f" -Tail 60 -ErrorAction SilentlyContinue | ForEach-Object { $_.Substring(0,[Math]::Min(260,$_.Length)) })
    $out += '```'
  }
}
$log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$tail = @(Get-Content $log -Tail 20000 -ErrorAction SilentlyContinue)
$out += "## control-plane lines since 14:16 local (plan/segment/prepare/reload/rollover/stall/exited), last 150"
$out += '```'
$out += ($tail | Where-Object { $_ -match '^2026-09-05 (14:[1-5]|15:)' -and $_ -match 'plan|segment|prepar|reload|rollover|Content-reload|exited non-zero|CTRL stall|Live source|automation' -and $_ -notmatch 'egress state -> ON_AIR' } | Select-Object -Last 150 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
$out += '```'
$out += "## STARTING lines (relaunch causes) since 14:16 local"
$out += '```'
$out += ($tail | Where-Object { $_ -match 'egress state -> STARTING' -and $_ -match '^2026-09-05 (14:[1-5]|15:)' } | ForEach-Object { $_.Substring(0,[Math]::Min(320,$_.Length)) } | Select-Object -Last 60)
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9y-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9y-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9y worker stall diag $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
