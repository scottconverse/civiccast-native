# AUTORUN-7 (soak8-e1acfe6) -- diagnostics only: push the poll log tail, the reports
# folder listing, the tail of every autorun log, the channel list from the station,
# and the last 60 lines of the control-plane log. No installs, no channel changes.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-7 diagnostics", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")

$out += "## poll.log (last 40)"
$out += '```'
$out += (Get-Content "$root\reports\poll.log" -Tail 40 -ErrorAction SilentlyContinue)
$out += '```'

$out += "## reports folder"
$out += '```'
$out += (Get-ChildItem "$root\reports" -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 30 | ForEach-Object { "$($_.LastWriteTimeUtc.ToString('o'))  $($_.Length)  $($_.FullName.Substring($root.Length))" })
$out += '```'

$out += "## state folder"
$out += '```'
$out += (Get-ChildItem "$root\state" -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object { "$($_.LastWriteTimeUtc.ToString('o'))  $($_.FullName.Substring($root.Length))" })
$out += '```'

foreach ($log in (Get-ChildItem "$root\reports" -Filter 'AUTORUN-*.log' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 4)) {
  $out += "## $($log.Name) (last 60)"
  $out += '```'
  $out += (Get-Content $log.FullName -Tail 60 -ErrorAction SilentlyContinue)
  $out += '```'
}

$out += "## station"
$out += '```'
try { $h = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10; $out += ($h | ConvertTo-Json -Compress -Depth 4) } catch { $out += "health: $($_.Exception.Message)" }
$tokenFile = "$root\state\token"
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  try { $ch = Invoke-RestMethod -Uri "$base/api/staff/egress/channels" -Headers $hdr -TimeoutSec 15; $out += "channels: " + ($ch | ConvertTo-Json -Compress -Depth 4) } catch { $out += "channels: $($_.Exception.Message)" }
} else { $out += "no staff token on disk (AUTORUN-6 did not reach first-admin)" }
$out += '```'

$out += "## control_plane-app.log (last 60)"
$out += '```'
$out += (Get-Content 'C:\ProgramData\CivicCast\logs\control_plane-app.log' -Tail 60 -ErrorAction SilentlyContinue)
$out += '```'

New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-7 diagnostics $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
