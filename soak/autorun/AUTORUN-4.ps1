# AUTORUN-4 (soak8-e1acfe6) -- first-admin + three channels + program cycling + start playout.
# Renamed from the held AUTORUN-2 for the e5020746 (1.0.0-beta.5 candidate) 2-hour soak.
# Executed automatically by the CivicCastSoak-Poll task, once. Idempotent.
# NOTHING here forces an encoder engine: the channel configs leave the engine at
# the shipped default (GStreamer) so this soak measures the real thing.
param(
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'

$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$kit   = "$root\kit-e5020746fa40e7a3f1a160d3a8e1add5c3b57786"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log   = @("# AUTORUN-4 station setup + three-channel soak (2h candidate e5020746)", "- mission: soak8-e1acfe6", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $kit", "- DryRun: $($DryRun.IsPresent)", "")
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
New-Item -Force -ItemType Directory "$root\state" | Out-Null

function Save-Report {
  param([string[]]$Lines, [string]$Name, [string]$Message)
  Set-Content "$repo\soak\$Name" -Value ($Lines -join "`n") -Encoding utf8
  if ($DryRun) {
    Write-Host "[DRYRUN] would git add/commit/push soak/$Name -- '$Message'"
    return
  }
  git -C $repo add "soak/$Name"
  git -C $repo commit --quiet -m $Message
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

# ------------------------------------------------------------ 0. station is up?
$health = $null
for ($i = 0; $i -lt 40; $i++) {
  try { $health = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10; if ($health.status -eq 'healthy') { break } } catch { }
  Start-Sleep -Seconds 30
}
if (-not $health -or $health.status -ne 'healthy') {
  $log += "STALLED: station is not healthy; AUTORUN-1 must succeed first. last health: $($health | ConvertTo-Json -Compress -Depth 4)"
  Save-Report -Lines $log -Name 'SETUP-BLOCKED.md' -Message "test: autorun-4 blocked (station not healthy) $stamp soak8-e1acfe6"
  exit 1
}
$log += "station healthy; schema=$($health.schema) db_revision=$($health.db_revision)"

# --------------------------------------------------- 1. first-admin (loopback)
$tokenFile = "$root\state\token"
$token = ''
if (Test-Path $tokenFile) { $token = (Get-Content $tokenFile -Raw).Trim() }

if (-not $token) {
  # POST /api/setup/first-admin -- loopback-admitted before staff auth exists.
  # Body = civiccast.installer.models.FirstAdminSetupRequest (extra="forbid").
  $pwd = 'Soak8!' + ([guid]::NewGuid().ToString('N').Substring(0, 18))
  $body = [ordered]@{
    station_name              = "Soak8 $env:COMPUTERNAME"
    admin_display_name        = 'Soak Operator'
    admin_username            = 'soakadmin'
    admin_password            = $pwd
    recovery_kit_destination  = 'held by the fleet coordinator (automated soak; not printed)'
    default_channel_id        = 'government'
    station_timezone          = 'local'
    channel_count             = 3
    sample_content_enabled    = $false
    initial_schedule_enabled  = $false
    operation_mode            = 'test'
  } | ConvertTo-Json -Depth 5
  if ($DryRun) {
    $log += "[DRYRUN] would POST $base/api/setup/first-admin with body:"
    $log += '```json'
    $log += $body
    $log += '```'
    $log += '[DRYRUN] stopping before any HTTP write or git push -- no further setup performed.'
    Save-Report -Lines $log -Name "AUTORUN-4-DRYRUN-$stamp.md" -Message "test: autorun-4 dry-run $stamp soak8-e1acfe6"
    exit 0
  }
  try {
    $resp = Invoke-RestMethod -Method Post -Uri "$base/api/setup/first-admin" -ContentType 'application/json' -Body $body -TimeoutSec 120
    $token = $resp.operator_console_token
    $log += "first-admin: complete (status=$($resp.status))"
  } catch {
    $detail = ''
    try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    $log += "first-admin POST failed: $($_.Exception.Message) :: $detail"
    if ("$detail" -match 'already') { $log += "(station was already set up; a token is required to continue)" }
  }
  if ($token) {
    Set-Content $tokenFile -Value $token -Encoding ascii
    # restrict: SYSTEM + Administrators + this user only
    try {
      & icacls.exe $tokenFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" "SYSTEM:(F)" "Administrators:(F)" | Out-Null
    } catch { }
    # never commit the credentials -- record only that they exist
    Set-Content "$root\state\admin-username" -Value 'soakadmin' -Encoding ascii
    $log += "operator console token stored at $tokenFile (ACL restricted); password NOT committed"
  }
} elseif ($DryRun) {
  $log += "[DRYRUN] existing token found at $tokenFile -- would reuse it, no first-admin POST needed."
  $log += '[DRYRUN] stopping before any HTTP write or git push -- no further setup performed.'
  Save-Report -Lines $log -Name "AUTORUN-4-DRYRUN-$stamp.md" -Message "test: autorun-4 dry-run $stamp soak8-e1acfe6"
  exit 0
}

if (-not $token) {
  $log += 'STALLED: no staff token. Ship a follow-up autorun with a recovery path.'
  $log += ''
  $log += '## openapi paths mentioning setup/first-admin'
  try {
    $oa = Invoke-RestMethod -Uri "$base/openapi.json" -TimeoutSec 30
    $log += ($oa.paths.PSObject.Properties.Name | Where-Object { $_ -match 'setup|first-admin|login' })
  } catch { $log += "openapi read failed: $($_.Exception.Message)" }
  Save-Report -Lines $log -Name 'SETUP-BLOCKED.md' -Message "test: autorun-4 blocked (no token) $stamp soak8-e1acfe6"
  exit 2
}
$hdr = @{ Authorization = "Bearer $token" }

# --------------------------------------------------- 2. the four sample videos
$samples = @(Get-ChildItem "$kit\samples" -Filter '*.mp4' -File -ErrorAction SilentlyContinue | Sort-Object Name)
$log += "samples found: $($samples.Count)"
foreach ($s in $samples) { $log += "  - $($s.Name) ($([math]::Round($s.Length/1MB)) MB)" }
if ($samples.Count -lt 1) {
  $log += "STALLED: no sample videos in the kit (expected 4 under $kit\samples\)."
  Save-Report -Lines $log -Name 'SETUP-BLOCKED.md' -Message "test: autorun-4 blocked (no samples) $stamp soak8-e1acfe6"
  exit 3
}

# ------------------------------------------------------- 3. three egress channels
# Engine: NOT specified anywhere below -- the station's shipped default (GStreamer)
# is what we want to soak. allow_software_fallback stays FALSE so a missing hardware
# encoder fails loud instead of silently degrading and hiding the thing we test.
$channelSpecs = @(
  @{ id = 'public';     name = 'Public';     port = 9001; offsetMin = 0  },
  @{ id = 'education';  name = 'Education';  port = 9002; offsetMin = 7  },
  @{ id = 'government'; name = 'Government'; port = 9003; offsetMin = 14 }
)
$log += ''
$log += '## channel configs'
foreach ($c in $channelSpecs) {
  $cfg = [ordered]@{
    channel_id             = $c.id
    enabled                = $true
    auto_start             = $true
    allow_software_fallback= $false
    fill_policy            = 'slate'
    sinks = @(
      [ordered]@{
        kind       = 'udp-ts'
        label      = "$($c.name) UDP TS"
        uri        = "udp://127.0.0.1:$($c.port)?pkt_size=1316"
        latency_ms = 2000
      }
    )
  } | ConvertTo-Json -Depth 6
  if ($DryRun) {
    $log += "[DRYRUN] would PUT $base/api/staff/egress/channels/$($c.id)/config with body:"
    $log += '```json'
    $log += $cfg
    $log += '```'
    continue
  }
  try {
    $r = Invoke-RestMethod -Method Put -Uri "$base/api/staff/egress/channels/$($c.id)/config" -Headers $hdr `
           -ContentType 'application/json' -Body $cfg -TimeoutSec 60
    $log += "PUT config $($c.id): ok (sinks=$(@($r.sinks).Count), udp 127.0.0.1:$($c.port))"
  } catch {
    $detail = ''
    try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    $log += "PUT config $($c.id) FAILED: $($_.Exception.Message) :: $detail"
  }
}

if ($DryRun) {
  $log += ''
  $log += '[DRYRUN] stopping before any HTTP write or git push -- assets, schedule, and start-playout are not executed.'
  Save-Report -Lines $log -Name "AUTORUN-4-DRYRUN-$stamp.md" -Message "test: autorun-4 dry-run $stamp soak8-e1acfe6"
  exit 0
}

# --------------------------- 4. register the samples and cycle them per channel
# Asset + schedule shapes are read from the live openapi so a contract change is
# reported, never guessed silently.
$assetPost = $null; $schedulePost = $null
try {
  $oa = Invoke-RestMethod -Uri "$base/openapi.json" -TimeoutSec 60
  $assetPost    = $oa.paths.'/api/staff/assets'.post
  $schedulePost = $oa.paths.'/api/staff/schedule'.post
} catch { $log += "openapi read failed: $($_.Exception.Message)" }

$log += ''
$log += '## asset + schedule contracts (from the live openapi)'
$log += '```json'
$log += ("POST /api/staff/assets: "   + ($assetPost    | ConvertTo-Json -Depth 6 -Compress))
$log += ("POST /api/staff/schedule: " + ($schedulePost | ConvertTo-Json -Depth 6 -Compress))
$log += '```'

$assetIds = @()
foreach ($s in $samples) {
  try {
    $ab = [ordered]@{ title = $s.BaseName; source_path = $s.FullName } | ConvertTo-Json -Depth 4
    $a = Invoke-RestMethod -Method Post -Uri "$base/api/staff/assets" -Headers $hdr -ContentType 'application/json' -Body $ab -TimeoutSec 120
    $id = $(if ($a.asset_id) { $a.asset_id } else { $a.id })
    if ($id) {
      $assetIds += [pscustomobject]@{ id = $id; name = $s.BaseName }
      $log += "asset registered: $($s.Name) -> $id"
      try { Invoke-RestMethod -Method Post -Uri "$base/api/staff/assets/$id/package" -Headers $hdr -TimeoutSec 600 | Out-Null } catch { $log += "  package call: $($_.Exception.Message)" }
    }
  } catch {
    $detail = ''
    try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    $log += "asset register FAILED for $($s.Name): $($_.Exception.Message) :: $detail"
  }
}

# Program cycling: each channel walks the sample videos, one program change every
# 20 minutes, for a 2h15m window (6 slots per channel = 2 hours of programming),
# with the three channels offset 0 / 7 / 14 minutes so their transitions never
# coincide and every channel's last slot still starts well inside the window
# (max offset 14 min + 5 min start delay + 5*20 min = 119 min < 135 min), so
# every channel is actively playing something through the AUTORUN-3 T+2h verdict.
$startUtc = (Get-Date).ToUniversalTime()
$slotsPerChannel = 6
$sched = @("# soak8-e1acfe6 channel schedule (2h candidate e5020746)", "- host: $env:COMPUTERNAME", "- soak start (UTC): $($startUtc.ToString('o'))",
           "- program change: every 20 minutes per channel, $slotsPerChannel slots (~2 h), 2h15m window",
           "- stagger: public +0 min, education +7 min, government +14 min",
           "- engine: station default (GStreamer); ffmpeg is NOT forced anywhere",
           "", "| channel | slot | start (UTC) | video |", "|---|---|---|---|")
$made = 0
foreach ($c in $channelSpecs) {
  for ($slot = 0; $slot -lt $slotsPerChannel; $slot++) {
    $when = $startUtc.AddMinutes(5 + $c.offsetMin + ($slot * 20))
    $vid  = $samples[$slot % $samples.Count]
    $aid  = ($assetIds | Where-Object { $_.name -eq $vid.BaseName } | Select-Object -First 1).id
    $sched += "| $($c.id) | $slot | $($when.ToString('yyyy-MM-ddTHH:mm:ssZ')) | $($vid.Name) |"
    if ($aid) {
      $sb = [ordered]@{ channel_id = $c.id; asset_id = $aid; scheduled_start = $when.ToString('o') } | ConvertTo-Json -Depth 4
      try { Invoke-RestMethod -Method Post -Uri "$base/api/staff/schedule" -Headers $hdr -ContentType 'application/json' -Body $sb -TimeoutSec 60 | Out-Null; $made++ }
      catch {
        if ($slot -eq 0) {
          $detail = ''
          try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
          $log += "schedule POST FAILED ($($c.id) slot 0): $($_.Exception.Message) :: $detail"
        }
      }
    }
  }
}
$log += "schedule items created: $made (of $(3 * $slotsPerChannel) planned)"

# --------------------------------------------------------------- 5. start playout
foreach ($c in $channelSpecs) {
  try {
    Invoke-RestMethod -Method Post -Uri "$base/api/staff/egress/channels/$($c.id)/commands" -Headers $hdr `
      -ContentType 'application/json' -Body (@{ action = 'start' } | ConvertTo-Json) -TimeoutSec 60 | Out-Null
    $log += "start queued: $($c.id)"
  } catch {
    $detail = ''
    try { $detail = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    $log += "start FAILED $($c.id): $($_.Exception.Message) :: $detail"
  }
}

Start-Sleep -Seconds 60
$log += ''
$log += '## engine actually running, per channel (first read)'
foreach ($c in $channelSpecs) {
  try {
    $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/state" -Headers $hdr -TimeoutSec 20
    $log += "$($c.id): state=$($st.state) engine=$($st.engine) last_error=$($st.last_error)"
  } catch { $log += "$($c.id): state read failed: $($_.Exception.Message)" }
}
$gst = @(Get-Process -Name 'gst-launch-1.0' -ErrorAction SilentlyContinue).Count
$ff  = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
$log += "observed worker processes: gst-launch-1.0=$gst ffmpeg=$ff"

# ---------------------------------------------------------------- 6. start clock
Set-Content "$root\state\soak-started" -Value $startUtc.ToString('o') -Encoding ascii
Save-Report -Lines $sched -Name 'CHANNEL-SCHEDULE.md' -Message "test: autorun-4 channel schedule $stamp soak8-e1acfe6"
$startDoc = @("# soak8-e1acfe6 SOAK START (candidate e5020746, 2h)", "", "- host: $env:COMPUTERNAME",
  "- soak clock start (UTC): $($startUtc.ToString('o'))",
  "- planned duration: 2 hours (final verdict at T+2h; polling continues forever after)",
  "- channels: public/9001, education/9002, government/9003 (udp-ts)",
  "- engine: station default (GStreamer). Every heartbeat reports the engine actually running per channel.")
Save-Report -Lines $startDoc -Name 'SOAK-START.md' -Message "test: autorun-4 soak start $stamp soak8-e1acfe6"
Save-Report -Lines $log -Name "AUTORUN-4-RESULT-$stamp.md" -Message "test: autorun-4 result $stamp soak8-e1acfe6"
exit 0
