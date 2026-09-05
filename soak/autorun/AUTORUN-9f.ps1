# AUTORUN-9f (soak8-e1acfe6) -- read the RAW channel state after AUTORUN-9e (config+start OK,
# state poll came back empty), list engine processes, tail the control-plane log, and if
# every channel is ON_AIR write state\soak-started so the recurring verify begins.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9f channel state diagnostics", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$token = ''
if (Test-Path "$root\state\token") { $token = (Get-Content "$root\state\token" -Raw).Trim() }
$hdr = @{ Authorization = "Bearer $token" }

function Get-Raw([string]$Url, [hashtable]$Headers) {
  try {
    $r = Invoke-WebRequest -Uri $Url -Headers $Headers -TimeoutSec 20 -UseBasicParsing
    return @{ status = [int]$r.StatusCode; body = [string]$r.Content }
  } catch {
    $st = $null; $body = ''
    try { $st = [int]$_.Exception.Response.StatusCode; $sr = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); $body = $sr.ReadToEnd() } catch { }
    return @{ status = $st; body = ($body + ' ' + $_.Exception.Message) }
  }
}

$onAir = 0
foreach ($id in 'public','education','government') {
  $out += "## $id"
  foreach ($path in "/api/staff/egress/channels/$id/state", "/api/staff/egress/channels/$id/health?limit=1", "/api/public/egress/channels/$id/now", "/api/staff/egress/channels/$id/config") {
    $r = Get-Raw -Url ($base + $path) -Headers $hdr
    $out += "GET $path -> $($r.status)"
    $out += '```json'
    $out += ($r.body.Substring(0, [Math]::Min(1500, $r.body.Length)))
    $out += '```'
    if ($path -like '*/state' -and $r.status -eq 200 -and $r.body -match '"state"\s*:\s*"ON_AIR"') { $onAir++ }
  }
}
$out += "## channel list"
$r = Get-Raw -Url "$base/api/staff/egress/channels" -Headers $hdr
$out += "GET /api/staff/egress/channels -> $($r.status)"
$out += '```json'; $out += ($r.body.Substring(0, [Math]::Min(2500, $r.body.Length))); $out += '```'

$out += "## engine processes"
$out += '```'
$out += (Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'python|gst|ffmpeg' } | ForEach-Object { "$($_.ProcessName) pid=$($_.Id) rss_mb=$([math]::Round($_.WorkingSet64/1MB)) cpu_s=$([math]::Round($_.CPU,1))" })
$out += '```'

$out += "## control_plane-app.log (egress lines, last 80)"
$out += '```'
$out += (Get-Content 'C:\ProgramData\CivicCast\logs\control_plane-app.log' -Tail 400 -ErrorAction SilentlyContinue | Where-Object { $_ -match 'egress|automation|gst|rollover|reload' } | Select-Object -Last 80)
$out += '```'

$out += "## verdict"
$out += "channels ON_AIR: $onAir / 3"
if ($onAir -ge 3) {
  Set-Content "$root\state\soak-started" -Value ((Get-Date).ToUniversalTime().ToString('o')) -Encoding ascii
  $out += "soak-started WRITTEN at $((Get-Date).ToUniversalTime().ToString('o')) -- AUTORUN-3 verify begins next poll; verdict at T+2h"
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\SOAK-START.md" -Value (@("# soak8-e1acfe6 soak start (AUTORUN-9f)", "- soak clock start (UTC): $((Get-Date).ToUniversalTime().ToString('o'))", "- channels: public/9001, education/9002, government/9003 (udp-ts), all ON_AIR at start", "- engine: station default (GStreamer); AUTORUN-3 reports the engine actually running per channel every poll") -join "`n") -Encoding utf8
  git -C $repo add soak/SOAK-START.md
} else {
  $out += "soak-started NOT written (need all three ON_AIR)"
}
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9f-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9f-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9f channel state diagnostics on_air=$onAir $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
