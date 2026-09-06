# AUTORUN-9zn (soak8-e1acfe6) -- read-only: PROOF for item 60 (reload concat name collision).
# Captures each channel's gst-worker.stdout.log (all CTRL reload lines) and the FULL stderr
# grep for GLib 'not unique in bin' / 'parent != NULL' warnings. Changes nothing.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9zn item-60 proof: worker stdout CTRL reload lines + stderr name-collision warnings", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
foreach ($id in 'public','education','government') {
  $d = "C:\ProgramData\CivicCast\data\egress\$id\logs"
  $out += "## $id"
  $out += '```'
  $out += (Get-ChildItem $d -File -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Length) bytes $($_.LastWriteTimeUtc.ToString('HH:mm:ss'))Z" })
  $so = @(Get-Content "$d\gst-worker.stdout.log" -ErrorAction SilentlyContinue)
  $se = @(Get-Content "$d\gst-worker.stderr.log" -ErrorAction SilentlyContinue)
  $out += "stdout lines=$($so.Count) stderr lines=$($se.Count)"
  $out += "stdout 'CTRL reload' counts: aborted=$(@($so | Where-Object { $_ -match 'CTRL reload aborted' }).Count) committed=$(@($so | Where-Object { $_ -match 'CTRL reload committed' }).Count) held=$(@($so | Where-Object { $_ -match 'CTRL reload: new leg stream held' }).Count) any_reload=$(@($so | Where-Object { $_ -match 'CTRL reload' }).Count)"
  $out += "stderr counts: not_unique=$(@($se | Where-Object { $_ -match 'not unique in bin' }).Count) parent_null=$(@($se | Where-Object { $_ -match 'parent != NULL' }).Count) stall=$(@($se | Where-Object { $_ -match 'CTRL stall' }).Count)"
  $out += '```'
  $out += "### $id stdout: CTRL reload lines (last 20)"
  $out += '```'
  $out += ($so | Where-Object { $_ -match 'CTRL reload' } | Select-Object -Last 20 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
  $out += '```'
  $out += "### $id stderr: name-collision / parent warnings (first 12) + first 20 lines of the file"
  $out += '```'
  $out += ($se | Where-Object { $_ -match 'not unique|parent != NULL|g_warning|CRITICAL|assertion' } | Select-Object -First 12 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
  $out += '--- head ---'
  $out += ($se | Select-Object -First 20 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
  $out += '```'
}
$out += "## control-plane: reload / rollover lines (last 12)"
$out += '```'
$out += (Get-Content 'C:\ProgramData\CivicCast\logs\control_plane-app.log' -Tail 20000 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'rollover|Content-reload|reload' -and $_ -notmatch 'egress state ->' } | Select-Object -Last 12 | ForEach-Object { $_.Substring(0,[Math]::Min(300,$_.Length)) })
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9zn-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9zn-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9zn item-60 proof (worker stdout reload lines, stderr collisions) $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
