# AUTORUN-9zzz (soak8-e1acfe6) -- read-only: what happens right after each Content-reload prepare?
# prepared/ dir listing with mtimes per channel, daemon log lines in the 20 s after each
# 'Content-reload source preparation' line, worker stdout head/tail. Changes nothing.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9zzz post-prepare diag", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
foreach ($id in 'public','education','government') {
  $d = "C:\ProgramData\CivicCast\data\egress\$id"
  $out += "## $id : work dir tree (files with mtime, newest 30)"
  $out += '```'
  $out += (Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 30 | ForEach-Object { "$($_.LastWriteTimeUtc.ToString('HH:mm:ss'))Z $($_.Length) $($_.FullName.Substring($d.Length+1))" })
  $out += (Get-ChildItem $d -Directory -Recurse -ErrorAction SilentlyContinue | ForEach-Object { "dir $($_.FullName.Substring($d.Length+1)) files=$((Get-ChildItem $_.FullName -File -ErrorAction SilentlyContinue).Count)" })
  $out += '```'
  $out += "### $id worker stdout (first 12 + last 12 lines)"
  $out += '```'
  $so = @(Get-Content "$d\logs\gst-worker.stdout.log" -ErrorAction SilentlyContinue)
  $out += ($so | Select-Object -First 12 | ForEach-Object { $_.Substring(0,[Math]::Min(240,$_.Length)) })
  $out += '...'
  $out += ($so | Select-Object -Last 12 | ForEach-Object { $_.Substring(0,[Math]::Min(240,$_.Length)) })
  $out += '```'
}
$log = @(Get-Content 'C:\ProgramData\CivicCast\logs\control_plane-app.log' -Tail 30000 -ErrorAction SilentlyContinue)
$out += "## daemon lines within 25 s after each 'Content-reload source preparation' (last 6 preparations)"
$out += '```'
$idx = @(); for ($i = 0; $i -lt $log.Count; $i++) { if ($log[$i] -match 'Content-reload source preparation') { $idx += $i } }
foreach ($i in ($idx | Select-Object -Last 6)) {
  $out += "=== $($log[$i].Substring(0,[Math]::Min(200,$log[$i].Length)))"
  $t0 = $null; try { $t0 = [datetime]::ParseExact($log[$i].Substring(0,19), 'yyyy-MM-dd HH:mm:ss', $null) } catch {}
  for ($j = $i + 1; $j -lt [Math]::Min($log.Count, $i + 400); $j++) {
    $l = $log[$j]; if ($l -match 'egress state -> ON_AIR') { continue }
    $tj = $null; try { $tj = [datetime]::ParseExact($l.Substring(0,19), 'yyyy-MM-dd HH:mm:ss', $null) } catch {}
    if ($t0 -and $tj -and ($tj - $t0).TotalSeconds -gt 25) { break }
    $out += "  " + $l.Substring(0,[Math]::Min(300,$l.Length))
  }
}
$out += '```'
$out += "## daemon lines mentioning reload (not state writes), last 30"
$out += '```'
$out += ($log | Where-Object { $_ -match 'reload' -and $_ -notmatch 'egress state ->' } | Select-Object -Last 30 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9zzz-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9zzz-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9zzz post-prepare diag $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
