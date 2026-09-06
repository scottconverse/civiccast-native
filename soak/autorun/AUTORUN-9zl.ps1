# AUTORUN-9zl (soak8-e1acfe6) -- after the CLEAN install of 609273d (9zj saw no ON_AIR within 3 min) the three channels did not come back
# ON_AIR by themselves. Send the operator "start" command to each channel (the same
# POST /api/staff/egress/channels/<id>/commands {action:start} AUTORUN-9e used), poll the
# per-channel /state endpoint for up to 6 minutes, and only when ALL THREE are ON_AIR archive
# soak #1's probes, reset the relaunch counters and write a fresh state\soak-started.
# Executed automatically by the CivicCastSoak-Poll scheduled task, exactly once.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$sha   = '609273da22b968b8ed9320dfc158d67b01eb30b3'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log   = @("# AUTORUN-9zl restart channels after the CLEAN install of 609273d (9zj saw no ON_AIR within 3 min), then restart the soak", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$channels = 'public','education','government'

function Publish-Log([string]$msg) {
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\RESTART-RESULT-9zl.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add -A soak
  git -C $repo commit --quiet -m "test: autorun-9zl $msg $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}
function Invoke-Api([string]$Method, [string]$Url, $BodyObj) {
  $r = [ordered]@{ status = 0; body_raw = '' }
  try {
    $p = @{ Uri = $Url; Method = $Method; Headers = @{ Authorization = "Bearer $token" }; TimeoutSec = 60; UseBasicParsing = $true }
    if ($null -ne $BodyObj) { $p.ContentType = 'application/json'; $p.Body = ($BodyObj | ConvertTo-Json -Depth 6 -Compress) }
    $resp = Invoke-WebRequest @p
    $r.status = [int]$resp.StatusCode; $r.body_raw = "$($resp.Content)"
  } catch {
    $r.status = $(try { [int]$_.Exception.Response.StatusCode } catch { -1 })
    $r.body_raw = $(try { $_.ErrorDetails.Message } catch { "$($_.Exception.Message)" })
  }
  return $r
}

# -------------------------------------------------------------- 0. preconditions
$tokenFile = "$root\state\token"
if (-not (Test-Path $tokenFile)) { $log += 'no state\token; cannot call the API'; Publish-Log 'no token'; exit 6 }
$token = (Get-Content $tokenFile -Raw).Trim()
try { $h = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 15 } catch { $log += "health: $($_.Exception.Message)"; Publish-Log 'health unreachable'; exit 4 }
$log += "health: status=$($h.status) version=$($h.version) schema=$($h.schema)"

$log += '## channel state BEFORE'
foreach ($id in $channels) {
  $st = Invoke-Api 'Get' "$base/api/staff/egress/channels/$id/state" $null
  $log += "$id : $($st.status) $($st.body_raw.Substring(0, [Math]::Min(300, $st.body_raw.Length)))"
}
$cfg = Invoke-Api 'Get' "$base/api/staff/egress/channels" $null
$log += "GET /api/staff/egress/channels -> $($cfg.status) $($cfg.body_raw.Substring(0, [Math]::Min(600, $cfg.body_raw.Length)))"

if ($DryRun) { Write-Host ($log -join "`n"); Write-Host 'DRYRUN: stopping before the start commands'; exit 0 }

# ------------------------------------------------------------------ 1. start
$log += '## start commands'
foreach ($id in $channels) {
  $r = Invoke-Api 'Post' "$base/api/staff/egress/channels/$id/commands" (@{ action = 'start' })
  $log += "start $id -> $($r.status) $($r.body_raw.Substring(0, [Math]::Min(300, $r.body_raw.Length)))"
}

# ------------------------------------------- 2. poll per-channel state, up to 6 min
$deadline = (Get-Date).AddMinutes(6)
$onAir = @()
do {
  $onAir = @()
  foreach ($id in $channels) {
    try {
      $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$id/state" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20
      if ("$($st.state)" -eq 'ON_AIR') { $onAir += $id }
    } catch { }
  }
  if ($onAir.Count -ge 3) { break }
  Start-Sleep -Seconds 15
} while ((Get-Date) -lt $deadline)
$log += '## channel state AFTER (poll up to 6 min)'
foreach ($id in $channels) {
  $st = Invoke-Api 'Get' "$base/api/staff/egress/channels/$id/state" $null
  $log += "$id : $($st.status) $($st.body_raw.Substring(0, [Math]::Min(300, $st.body_raw.Length)))"
}
$log += "ON_AIR: $($onAir.Count)/3 [$($onAir -join ', ')]"
if ($onAir.Count -lt 3) { Publish-Log "start sent but only $($onAir.Count)/3 ON_AIR; soak NOT restarted"; exit 5 }

# ------------------------- 3. archive soak #1 history, reset counters, restart soak
$arch = "$repo\soak\archive-609273d-prev-soak"
New-Item -Force -ItemType Directory "$arch\egress" | Out-Null
Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue | Move-Item -Destination "$arch\egress" -Force
Get-ChildItem "$repo\soak" -Filter 'SOAK-REPORT-*.md' -File -ErrorAction SilentlyContinue | Move-Item -Destination $arch -Force
if (Test-Path "$repo\soak\final-verdict.json") { Move-Item "$repo\soak\final-verdict.json" "$arch\final-verdict.json" -Force }
foreach ($f in 'last-pid-*.txt','relaunch-count-*.txt','last-errors-*.json','last-cpu-sample.json','last-rollup-hours','last-egress-run') {
  Get-ChildItem "$root\state" -Filter $f -File -ErrorAction SilentlyContinue | Remove-Item -Force
}
$startIso = (Get-Date).ToUniversalTime().ToString('o')
Set-Content "$root\state\soak-started" -Value $startIso -Encoding ascii
$log += "old probes archived to soak/archive-609273d-prev-soak; counters reset; soak #5 started $startIso on kit $sha"
Publish-Log "soak #5 STARTED on kit $sha after channel restart"
exit 0
