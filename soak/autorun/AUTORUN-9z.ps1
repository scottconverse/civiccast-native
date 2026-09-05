# AUTORUN-9z (soak8-e1acfe6) -- three-channel soak with beta.5-shaped API bodies.
# Renamed successor to AUTORUN-9d: 9d's channel-config PUT and asset-create POST
# bodies were beta.3-shaped (JSON POST /api/staff/assets with {title,source_path},
# and a config PUT missing slate_message/loudness_regime/eas_tone_strip_enabled)
# and got HTTP 422 on EVERY write against this beta.5 candidate (e5020746) -- so
# 9d never actually configured, staged, or started anything, yet it still wrote
# C:\CivicCastSoak\state\soak-started (08:27:39Z), which made AUTORUN-3's T+2h
# verdict logic count a soak that never began. Section 0 below removes that
# stale state before doing anything else.
#
# The bodies below are copied from the PROVEN-WORKING lanes in the main repo
# checkout's sandbox harness (C:\Users\scott\Desktop\Code\civiccast-native\
# sandbox-lab\scripts\In-Sandbox-Report.ps1, T4 block ~line 3560-3710) and the
# T6 engine-soak lane on branch feat/gate-a-engine-soak (same filename, in the
# worktree this run's context was built from; T6 block ~line 3860-4620,
# search 'soak-public'/'t6Channels'):
#   - asset registration is POST /api/staff/assets/upload (MULTIPART: asset_id,
#     title, file) -- NOT the JSON POST /api/staff/assets 9d used. That JSON
#     route/body shape does not exist for this API version; multipart upload
#     is the only asset-creation path the harness ever found working.
#     (Invoke-AssetUpload, harness lines 1572-1607.)
#   - channel config PUT body includes slate_message and, per sink,
#     loudness_regime='inherit' + eas_tone_strip_enabled=$true, which 9d's
#     body omitted (harness T4 block, lines 3663-3680; T6 block, lines
#     3349-3362 -- T6 additionally sets auto_start=$true and
#     allow_software_fallback=$true, which is what this soak wants since it
#     measures the shipped engine end to end rather than proving the engine
#     route exists).
#   - schedule + Commit-to-Air: a bare POST /api/staff/schedule item is
#     created 'scheduled' and is NEVER picked up by the engine on its own --
#     it must be followed by POST /api/staff/playout/commit
#     (channel_id/occurrence_id/schedule_item_id) to flip it to 'published'
#     before egress/source_plan.py will resolve it (harness T6 block, lines
#     4210-4287). 9d never committed its schedule items at all.
#   - scheduling+commit for ALL channels happens BEFORE any channel is
#     configured/started (harness T6 block, lines 4094-4148, B-B rationale):
#     starting first and then posting ~100s of schedule+commit items against
#     an already-ON_AIR channel dispatches each commit as a "reload" nudge
#     (civiccast/egress/dispatcher.py) -- a reload storm. Configuring channels
#     while still STOPPED means each commit's dispatch is a no-op "start"
#     enqueue that just waits for the real config+start below.
#
# Channel ids/ports are UNCHANGED from AUTORUN-9d (public/9001, education/9002,
# government/9003) -- NOT the harness's own 'soak-*'/19011-19013 ids, which
# exist there only to avoid colliding with the harness's OWN separate T4 lane
# using 'government'/19003 in the same sandbox run. No such T4 lane runs on
# this tester box, so there is nothing to collide with; keeping 9d's ids/ports
# means AUTORUN-3's existing per-channel state files (last-pid-<id>.txt,
# relaunch-count-<id>.txt, last-errors-<id>.json, all keyed off
# public/education/government) keep working unchanged.
param(
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Net.Http

$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$kit   = "$root\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log   = @("# AUTORUN-9z soak #2: reschedule the approved soak assets on kit 91caebc, start, restart the soak clock", "- mission: soak8-e1acfe6", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $kit", "- DryRun: $($DryRun.IsPresent)", "")
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

# Generic JSON API call, ported from the sandbox harness's Invoke-CivicCastApi
# (In-Sandbox-Report.ps1 lines 1515-1567): on a non-2xx, catch the
# WebException and read $_.Exception.Response.GetResponseStream() so the
# ACTUAL response body (e.g. a 422's field-level validation detail) lands in
# the report instead of just the bare status code -- the specific gap that
# made AUTORUN-9d's 422s blind.
function Invoke-CivicCastApi {
  param(
    [string]$Method,
    [string]$Url,
    [object]$BodyObj = $null,
    [string]$BearerToken = $null,
    [int]$TimeoutSec = 60
  )
  $result = [ordered]@{
    method = $Method; url = $Url; status = $null; ok = $false
    body_raw = $null; body_json = $null; error = $null
  }
  try {
    $headers = @{}
    if ($BearerToken) { $headers['Authorization'] = "Bearer $BearerToken" }
    $params = @{
      Uri = $Url; Method = $Method; Headers = $headers; UseBasicParsing = $true
      TimeoutSec = $TimeoutSec; ErrorAction = 'Stop'
    }
    if ($null -ne $BodyObj) {
      $params['Body'] = ($BodyObj | ConvertTo-Json -Depth 10)
      $params['ContentType'] = 'application/json'
    }
    $resp = Invoke-WebRequest @params
    $result.status = [int]$resp.StatusCode
    $result.body_raw = [string]$resp.Content
    $result.ok = $true
  } catch {
    $we = $_.Exception
    if ($we.Response) {
      try {
        $result.status = [int]$we.Response.StatusCode
        $stream = $we.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $result.body_raw = $reader.ReadToEnd()
      } catch { }
    }
    $result.error = "$_"
  }
  if ($result.body_raw) {
    try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch { }
  }
  return $result
}

# Multipart asset upload, ported from the harness's Invoke-AssetUpload
# (In-Sandbox-Report.ps1 lines 1572-1607) -- Windows PowerShell 5.1's
# Invoke-WebRequest has no -Form parameter (PowerShell 6+ only), so
# multipart/form-data is built by hand via System.Net.Http.MultipartFormDataContent.
function Invoke-AssetUpload {
  param([string]$BaseUrl, [string]$Token, [string]$AssetId, [string]$Title, [string]$FilePath, [int]$TimeoutSec = 900)
  $url = "$BaseUrl/api/staff/assets/upload"
  $result = [ordered]@{ method = 'POST'; url = $url; status = $null; ok = $false; body_raw = $null; body_json = $null; error = $null }
  try {
    $handler = New-Object System.Net.Http.HttpClientHandler
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
    $client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer', $Token)
    $content = New-Object System.Net.Http.MultipartFormDataContent
    $content.Add((New-Object System.Net.Http.StringContent($AssetId)), 'asset_id')
    $content.Add((New-Object System.Net.Http.StringContent($Title)), 'title')
    $fileBytes = [System.IO.File]::ReadAllBytes($FilePath)
    $fileContent = New-Object System.Net.Http.ByteArrayContent(,$fileBytes)
    try { $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('video/mp4') } catch { }
    $content.Add($fileContent, 'file', [System.IO.Path]::GetFileName($FilePath))
    $resp = $client.PostAsync($url, $content).Result
    $result.status = [int]$resp.StatusCode
    $result.body_raw = $resp.Content.ReadAsStringAsync().Result
    $result.ok = $resp.IsSuccessStatusCode
    try { $client.Dispose() } catch { }
  } catch {
    $result.error = "$_"
  }
  if ($result.body_raw) {
    try { $result.body_json = $result.body_raw | ConvertFrom-Json -ErrorAction Stop } catch { }
  }
  return $result
}

function Get-Mp4DurationSeconds {
  param([string]$FfprobeExe, [string]$FilePath, [int]$DefaultSeconds = 30)
  if (-not $FfprobeExe -or -not (Test-Path $FfprobeExe) -or -not (Test-Path $FilePath)) { return $DefaultSeconds }
  try {
    $out = & $FfprobeExe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $FilePath 2>$null
    $first = ($out | Select-Object -First 1)
    $val = [double]0
    if ([double]::TryParse($first, [ref]$val) -and $val -gt 0) { return [int][Math]::Ceiling($val) }
  } catch { }
  return $DefaultSeconds
}

# ------------------------------------------------------- 0. clear stale soak-clock state
# AUTORUN-9d wrote soak-started (08:27:39Z) even though every config PUT
# 422'd -- no channel was ever actually configured or started. AUTORUN-3's
# recurring verify gates on soak-started existing and derives its 30-min
# throttle and T+2h final verdict from it, so left in place it would count a
# soak that never began and eventually publish a false verdict. Removed
# BEFORE any HTTP write (and only logged, never actually removed, under
# -DryRun) so a stale prior run can never produce that false verdict.
$staleFiles = @(
  "$root\state\soak-started",
  "$root\state\last-egress-run",
  "$root\state\last-rollup-hours",
  "$repo\soak\final-verdict.json"
)
$log += ''
$log += '## stale soak-clock state (from the 9d run that never actually started anything)'
foreach ($sf in $staleFiles) {
  if (Test-Path $sf) {
    if ($DryRun) {
      $log += "[DRYRUN] would remove stale state file: $sf"
    } else {
      Remove-Item -Force $sf -ErrorAction SilentlyContinue
      $log += "removed stale state file: $sf"
    }
  } else {
    $log += "stale state file not present (nothing to remove): $sf"
  }
}

# ------------------------------------------------------------ 1. station is up?
$health = $null
for ($i = 0; $i -lt 40; $i++) {
  try { $health = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10; if ($health.status -eq 'healthy') { break } } catch { }
  Start-Sleep -Seconds 30
}
if (-not $health -or $health.status -ne 'healthy') {
  $log += "STALLED: station is not healthy. last health: $($health | ConvertTo-Json -Compress -Depth 4)"
  Save-Report -Lines $log -Name 'SETUP-BLOCKED-9z.md' -Message "test: autorun-9z blocked (station not healthy) $stamp soak8-e1acfe6"
  exit 1
}
$log += "station healthy; schema=$($health.schema) db_revision=$($health.db_revision)"

# --------------------------------------------------------- 2. staff bearer token
# A staff token is already stored on this box (station was set up by a prior
# run) -- no first-admin call here, unlike AUTORUN-9d.
$tokenFile = "$root\state\token"
$token = ''
if (Test-Path $tokenFile) { $token = (Get-Content $tokenFile -Raw).Trim() }
if (-not $token) {
  $log += "STALLED: no staff token at $tokenFile. AUTORUN-9e does not perform first-admin -- a prior setup run must have stored one."
  Save-Report -Lines $log -Name 'SETUP-BLOCKED-9z.md' -Message "test: autorun-9z blocked (no token) $stamp soak8-e1acfe6"
  exit 2
}
$log += "staff token loaded from $tokenFile"

# --------------------------------------------------------- 3. the sample videos
$samples = @(Get-ChildItem "$kit\samples" -Filter '*.mp4' -File -ErrorAction SilentlyContinue | Sort-Object Name)
$log += "samples found: $($samples.Count)"
foreach ($s in $samples) { $log += "  - $($s.Name) ($([math]::Round($s.Length/1MB)) MB)" }
if ($samples.Count -lt 1) {
  $log += "STALLED: no sample videos in the kit (expected samples under $kit\samples\)."
  Save-Report -Lines $log -Name 'SETUP-BLOCKED-9z.md' -Message "test: autorun-9z blocked (no samples) $stamp soak8-e1acfe6"
  exit 3
}

$ffprobeCandidates = @(
  "$kit\packs\native-server-binaries\payload\ffmpeg\bin\ffprobe.exe",
  'C:\CivicCastHostStore\install\packs\native-server-binaries\payload\ffmpeg\bin\ffprobe.exe',
  'C:\CivicCastHostStore\install\ffmpeg\bin\ffprobe.exe',
  'C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffprobe.exe',
  'C:\Program Files\CivicCast (Native)\ffmpeg\bin\ffprobe.exe'
)
$ffprobeExe = $ffprobeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$log += "ffprobe: $(if ($ffprobeExe) { $ffprobeExe } else { 'not found -- falling back to a 30s default duration per clip' })"

# ------------------------------------------------------- 4. three egress channels
# Ids/ports unchanged from AUTORUN-9d: public/9001, education/9002,
# government/9003 (see file header for why these ids, not the harness's own
# 'soak-*'/19011-19013, are correct here).
$channelSpecs = @(
  @{ id = 'public';     name = 'Public';     port = 9001 },
  @{ id = 'education';  name = 'Education';  port = 9002 },
  @{ id = 'government'; name = 'Government'; port = 9003 }
)

# Config PUT body -- copied from the harness's PROVEN-WORKING T6 lane
# (In-Sandbox-Report.ps1, feat/gate-a-engine-soak worktree, ~lines 3349-3362),
# not AUTORUN-9d's body, which 422'd on every channel. Differences from 9d's
# body: slate_message added; each sink gains loudness_regime='inherit' and
# eas_tone_strip_enabled=$true; allow_software_fallback is $true (T6's value)
# rather than 9d's $false, matching the proven body exactly rather than
# reintroducing a field this run has no independent evidence for.
$channelConfigBodies = @{}
$log += ''
$log += '## channel config PUT bodies (built now; PUT deferred to after scheduling -- see file header B-B rationale)'
foreach ($c in $channelSpecs) {
  $cfg = [ordered]@{
    channel_id              = $c.id
    enabled                 = $true
    auto_start               = $true
    allow_software_fallback = $true
    fill_policy             = 'slate'
    slate_message           = 'Soak8 AUTORUN-9e -- three-channel product-engine soak.'
    sinks = @(
      [ordered]@{
        kind                   = 'udp-ts'
        label                  = "soak8-9e-$($c.id)"
        uri                    = "udp://127.0.0.1:$($c.port)"
        latency_ms             = 2000
        loudness_regime        = 'inherit'
        eas_tone_strip_enabled = $true
      }
    )
  }
  $channelConfigBodies[$c.id] = $cfg
  $log += "config body for $($c.id):"
  $log += '```json'
  $log += ($cfg | ConvertTo-Json -Depth 6)
  $log += '```'
}

# ------------------------------------------------------------- 5. asset bodies
# Asset creation is POST /api/staff/assets/upload (MULTIPART: asset_id, title,
# file) -- the harness's Invoke-AssetUpload, NOT AUTORUN-9d's JSON POST
# /api/staff/assets {title, source_path}, which does not exist for this API
# version (that is very likely the actual source of 9d's 422 on that call).
$stagedClips = @($samples | Select-Object -First 4 | ForEach-Object { $_.FullName })
$log += ''
$log += '## asset upload call (per staged clip)'
$log += 'POST $base/api/staff/assets/upload -- multipart/form-data: fields asset_id, title, file=<clip bytes>, Authorization: Bearer <token>'
$log += "staged clip count (cap 4): $($stagedClips.Count)"
foreach ($cp in $stagedClips) { $log += "  - $cp" }

# ------------------------------------------------------------- 6. schedule/commit bodies
# Coverage: 2h + 15m per channel (2h soak + 15m margin), scheduled_at starting
# 60s before the channel is actually started so item 0 is already current the
# moment the engine resolves its source plan (build_source_plan_from_schedule's
# _current_item_index needs scheduled_at <= now). A bare POST /api/staff/
# schedule item is created 'scheduled' and is NEVER picked up by the engine on
# its own -- POST /api/staff/playout/commit (Commit-to-Air) flips it to
# 'published', which is what 9d's flow never did.
$soakMin = 120
$log += ''
$log += '## schedule item body (per item) -- POST $base/api/staff/schedule'
$log += '```json'
$log += (([ordered]@{ asset_id = '<asset_id>'; channel_id = '<channel_id>'; mode = 'premiere'; scheduled_at = '<iso8601 utc>'; duration_seconds = '<int, from ffprobe>'; notes = 'Soak8 AUTORUN-9z soak #2 on kit 91caebc' }) | ConvertTo-Json -Depth 4)
$log += '```'
$log += '## commit-to-air body (per item) -- POST $base/api/staff/playout/commit'
$log += '```json'
$log += (([ordered]@{ channel_id = '<channel_id>'; occurrence_id = '<per-item id>'; schedule_item_id = '<from the schedule POST response>' }) | ConvertTo-Json -Depth 4)
$log += '```'
$log += "schedule window: $soakMin + 15 minutes per channel, back-to-back using each clip's real ffprobe duration, cycling the staged clips"

if ($DryRun) {
  $log += ''
  $log += '[DRYRUN] stopping before the first HTTP write (asset upload, config PUT, schedule/commit POST, and channel start are not executed). Health check and token/file reads above are the only I/O performed.'
  Save-Report -Lines $log -Name "AUTORUN-9z-DRYRUN-$stamp.md" -Message "test: autorun-9z dry-run $stamp soak8-e1acfe6"
  exit 0
}

# --------------------------------- 7. reuse the assets AUTORUN-9u uploaded + approved
# They live in Postgres and survived the upgrade. Pick every soak8-9u-* asset in a
# ready state; duration from the asset record if present, else ffprobe of the matching
# sample clip (title carries the clip basename), else 30 s.
$assets = @()
$aList = Invoke-CivicCastApi -Method 'Get' -Url "$base/api/staff/assets?limit=200" -BearerToken $token
$log += "GET /api/staff/assets?limit=200 -> $($aList.status) $($aList.body_raw.Substring(0, [Math]::Min(400, $aList.body_raw.Length)))"
$items = @()
if ($aList.body_json) {
  if ($aList.body_json.PSObject.Properties.Name -contains 'items') { $items = @($aList.body_json.items) }
  elseif ($aList.body_json.PSObject.Properties.Name -contains 'assets') { $items = @($aList.body_json.assets) }
  elseif ($aList.body_json -is [array]) { $items = @($aList.body_json) }
}
$log += "asset records returned: $($items.Count)"
$seenIds = @{}
foreach ($it in $items) {
  $id = $(if ($it.PSObject.Properties.Name -contains 'asset_id' -and $it.asset_id) { "$($it.asset_id)" } else { "$($it.id)" })
  if ($id -notlike 'soak8-9u-*') { continue }
  if ($seenIds.ContainsKey($id)) { continue }
  $seenIds[$id] = $true
  $st = "$($it.state)"
  if ($st -ne 'validated' -and $st -ne 'recorded') { $log += "skip $id state=$st"; continue }
  $dur = 0
  if ($it.PSObject.Properties.Name -contains 'duration_seconds' -and $it.duration_seconds) { $dur = [double]$it.duration_seconds }
  if ($dur -le 0) {
    foreach ($smp in $samples) {
      $bn = [System.IO.Path]::GetFileNameWithoutExtension($smp.Name)
      if ("$($it.title)" -like "*$bn*") { $dur = Get-Mp4DurationSeconds -FfprobeExe $ffprobeExe -FilePath $smp.FullName -DefaultSeconds 30; break }
    }
  }
  if ($dur -le 0) { $log += "skip ${id}: no duration on the record and no ffprobe"; continue }
  $assets += [ordered]@{ id = $id; duration_seconds = $dur }
  $log += "asset reused: $id (duration_seconds=$dur, state=$st, title=$($it.title))"
}

if ($assets.Count -eq 0) {
  $log += "STALLED: no assets reached the ready+approved state; scheduling/config/start skipped."
  Save-Report -Lines $log -Name 'SETUP-BLOCKED-9z.md' -Message "test: autorun-9z blocked (no assets ready) $stamp soak8-e1acfe6"
  exit 4
}

# Longest clip first, so item 0 (the one closest to the channel's actual
# start) has the most run room to still be current.
if ($assets.Count -gt 1) {
  $longestIdx = 0
  for ($li = 1; $li -lt $assets.Count; $li++) {
    if ([double]$assets[$li].duration_seconds -gt [double]$assets[$longestIdx].duration_seconds) { $longestIdx = $li }
  }
  if ($longestIdx -ne 0) {
    $longestAsset = $assets[$longestIdx]
    $assets = @($longestAsset) + @($assets | Where-Object { $_ -ne $longestAsset })
  }
}

# ------------------------------- 8. schedule + Commit-to-Air, ALL channels, BEFORE start
# Anchored at the start of THIS phase (not asset-staging time, which can take
# minutes) so item 0's scheduled_at (phase-start - 60s) is still current the
# moment the channel is actually started right after this phase completes.
$schedulingPhaseStart = Get-Date
$scheduleStart = $schedulingPhaseStart
$scheduleEnd = $scheduleStart.AddMinutes($soakMin + 15)
$scheduleCapPerChannel = 2000
$sched = @("# soak8-e1acfe6 channel schedule (soak #4 real durations, kit 91caebc, AUTORUN-9z)", "- host: $env:COMPUTERNAME", "- soak scheduling phase start (UTC): $($scheduleStart.ToString('o'))",
           "- coverage: $soakMin + 15 minutes per channel, back-to-back (0s gap), real ffprobe durations, cycling staged clips",
           "- engine: GStreamer (allow_software_fallback=true; not forced away from the shipped default)",
           "", "| channel | items | committed | first item asset |", "|---|---|---|---|")
$scheduleTooLong = $false
$channelScheduleCounts = @{}
foreach ($c in $channelSpecs) {
  $cursor = $scheduleStart.AddSeconds(-60)
  $assetIdx = 0
  $scheduled = 0
  $committed = 0
  $scheduleFailed = 0
  $commitFailed = 0
  while (($cursor -lt $scheduleEnd) -and ($scheduled -lt $scheduleCapPerChannel)) {
    $asset = $assets[$assetIdx % $assets.Count]
    $itemBody = [ordered]@{
      asset_id         = $asset.id
      channel_id       = $c.id
      mode             = 'premiere'
      scheduled_at     = $cursor.ToUniversalTime().ToString('o')
      duration_seconds = [int]$asset.duration_seconds
      notes            = 'Soak8 AUTORUN-9z soak #2 on kit 91caebc'
    }
    $itemR = Invoke-CivicCastApi -Method 'Post' -Url "$base/api/staff/schedule" -BodyObj $itemBody -BearerToken $token
    if ($itemR.status -eq 201 -and $itemR.body_json -and $itemR.body_json.id) {
      $scheduled++
      $occId = "soak8-9z-$($c.id)-$scheduled"
      $commitBody = [ordered]@{
        channel_id       = $c.id
        occurrence_id    = $occId
        schedule_item_id = "$($itemR.body_json.id)"
      }
      $commitR = Invoke-CivicCastApi -Method 'Post' -Url "$base/api/staff/playout/commit" -BodyObj $commitBody -BearerToken $token
      if ($commitR.status -eq 201) {
        $committed++
      } else {
        $commitFailed++
        if ($commitFailed -le 3) { $log += "schedule commit FAILED channel=$($c.id) schedule_item_id=$($itemR.body_json.id) status=$($commitR.status) body=$($commitR.body_raw)" }
      }
    } else {
      $scheduleFailed++
      if ($scheduleFailed -le 3) { $log += "schedule item FAILED channel=$($c.id) asset=$($asset.id) status=$($itemR.status) body=$($itemR.body_raw)" }
    }
    $cursor = $cursor.AddSeconds([int]$asset.duration_seconds)
    $assetIdx++
  }
  $channelScheduleCounts[$c.id] = @{ scheduled = $scheduled; committed = $committed }
  if (($cursor -lt $scheduleEnd) -and ($scheduled -ge $scheduleCapPerChannel)) {
    $scheduleTooLong = $true
    $log += "schedule_too_long channel=$($c.id) scheduled=$scheduled cap=$scheduleCapPerChannel"
  }
  $sched += "| $($c.id) | $scheduled | $committed | $($assets[0].id) |"
  $log += "channel=$($c.id) schedule_items_created=$scheduled schedule_items_committed=$committed schedule_items_commit_failed=$commitFailed schedule_items_failed=$scheduleFailed"
}
Save-Report -Lines $sched -Name 'CHANNEL-SCHEDULE-9z.md' -Message "test: autorun-9z channel schedule $stamp soak8-e1acfe6"

if ($scheduleTooLong) {
  $log += "STALLED: at least one channel could not be scheduled to cover the full $($soakMin+15)-minute window within the $scheduleCapPerChannel-item cap. Channels are NOT configured or started."
  Save-Report -Lines $log -Name 'SETUP-BLOCKED-9z.md' -Message "test: autorun-9z blocked (schedule too long) $stamp soak8-e1acfe6"
  exit 5
}

# ---------------------------------- 9. NOW configure + start each channel
$channelResults = @{}
foreach ($c in $channelSpecs) {
  $configUrl = "$base/api/staff/egress/channels/$($c.id)/config"
  $commandsUrl = "$base/api/staff/egress/channels/$($c.id)/commands"
  $cfgR = Invoke-CivicCastApi -Method 'Put' -Url $configUrl -BodyObj $channelConfigBodies[$c.id] -BearerToken $token
  $configOk = ($cfgR.status -eq 200)
  if (-not $configOk) {
    $log += "PUT config $($c.id) FAILED: status=$($cfgR.status) body=$($cfgR.body_raw)"
  } else {
    $log += "PUT config $($c.id): ok (udp 127.0.0.1:$($c.port))"
  }
  $startOk = $false
  if ($configOk) {
    $startR = Invoke-CivicCastApi -Method 'Post' -Url $commandsUrl -BodyObj (@{ action = 'start' }) -BearerToken $token
    $startOk = ($startR.status -eq 202)
    if (-not $startOk) {
      $log += "start command $($c.id) FAILED: status=$($startR.status) body=$($startR.body_raw)"
    } else {
      $log += "start queued: $($c.id)"
    }
  }
  $channelResults[$c.id] = [ordered]@{ config_ok = $configOk; start_ok = $startOk; state = $null; pid = $null; last_error = $null }
}

# ------------------------------- 10. poll for ON_AIR, up to 3 minutes, before
# setting the soak-clock start. A run whose config PUTs 422 again must NOT
# get a soak-started file written -- that is exactly what happened last time.
$onAirDeadline = (Get-Date).AddMinutes(6)
$anyOnAir = $false
do {
  foreach ($c in $channelSpecs) {
    try {
      $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$($c.id)/state" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 20
      $channelResults[$c.id].state = $st.state
      $channelResults[$c.id].pid = $st.pid
      $channelResults[$c.id].last_error = $st.last_error
      if ($st.state -eq 'ON_AIR') { $anyOnAir = $true }
    } catch {
      $channelResults[$c.id].last_error = "state read failed: $($_.Exception.Message)"
    }
  }
  if ($anyOnAir -and (@($channelResults.Values | Where-Object { $_.state -eq 'ON_AIR' }).Count -ge 3)) { break }
  if ((Get-Date) -ge $onAirDeadline) { break }
  Start-Sleep -Seconds 15
} while ((Get-Date) -lt $onAirDeadline)

$log += ''
$log += '## per-channel state/pid after start (poll up to 3 minutes for ON_AIR)'
foreach ($c in $channelSpecs) {
  $cr = $channelResults[$c.id]
  $log += "$($c.id): config_ok=$($cr.config_ok) start_ok=$($cr.start_ok) state=$($cr.state) pid=$($cr.pid) last_error=$($cr.last_error)"
}
$gst = @(Get-Process -Name 'gst-launch-1.0' -ErrorAction SilentlyContinue).Count
$ff  = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
$log += "observed worker processes: gst-launch-1.0=$gst ffmpeg=$ff"

# ------------------------- 10b. archive soak #1 history + reset the relaunch counters
if ($anyOnAir) {
  $arch = "$repo\soak\archive-e502074-soak1"
  New-Item -Force -ItemType Directory "$arch\egress" | Out-Null
  Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue | Move-Item -Destination "$arch\egress" -Force
  Get-ChildItem "$repo\soak" -Filter 'SOAK-REPORT-*.md' -File -ErrorAction SilentlyContinue | Move-Item -Destination $arch -Force
  if (Test-Path "$repo\soak\final-verdict.json") { Move-Item "$repo\soak\final-verdict.json" "$arch\final-verdict.json" -Force }
  foreach ($f in 'last-pid-*.txt','relaunch-count-*.txt','last-errors-*.json','last-cpu-sample.json','last-rollup-hours','last-egress-run') {
    Get-ChildItem "$root\state" -Filter $f -File -ErrorAction SilentlyContinue | Remove-Item -Force
  }
  git -C $repo add -A soak | Out-Null
  $log += "soak #3 (30-s items) probes archived to soak/archive-91caebc-soak3-30s-items; relaunch/pid/rollup counters reset"
}

# ---------------------------------------------------------------- 11. start clock
if ($anyOnAir) {
  $startUtc = (Get-Date).ToUniversalTime()
  Set-Content "$root\state\soak-started" -Value $startUtc.ToString('o') -Encoding ascii
  $log += "soak-started WRITTEN (UTC): $($startUtc.ToString('o')) -- at least one channel confirmed ON_AIR"
  $startDoc = @("# soak8-e1acfe6 SOAK START (soak #4 real durations, kit 91caebc, 2h, AUTORUN-9z)", "", "- host: $env:COMPUTERNAME",
    "- soak clock start (UTC): $($startUtc.ToString('o'))",
    "- planned duration: 2 hours (final verdict at T+2h; polling continues forever after)",
    "- channels: public/9001, education/9002, government/9003 (udp-ts)",
    "- engine: station default (GStreamer), allow_software_fallback=true.")
  Save-Report -Lines $startDoc -Name 'SOAK-START-9z.md' -Message "test: autorun-9z soak start $stamp soak8-e1acfe6"
} else {
  $log += "soak-started NOT written -- no channel confirmed ON_AIR within 3 minutes. AUTORUN-3 will not run its egress probes/rollup/verdict against a soak that never actually started."
}

Save-Report -Lines $log -Name "AUTORUN-9z-RESULT-$stamp.md" -Message "test: autorun-9z result $stamp soak8-e1acfe6"
exit 0
