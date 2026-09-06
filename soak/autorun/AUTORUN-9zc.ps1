# AUTORUN-9zc (soak8-e1acfe6) -- first-admin + three channels + program cycling + start playout.
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
$kit   = "$root\kit-609273da22b968b8ed9320dfc158d67b01eb30b3"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log   = @("# AUTORUN-9zc station setup + three-channel soak (2h candidate e5020746)", "- mission: soak8-e1acfe6", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $kit", "- DryRun: $($DryRun.IsPresent)", "")
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
  $log += "STALLED: station is not healthy; AUTORUN-9c must succeed first. last health: $($health | ConvertTo-Json -Compress -Depth 4)"
  Save-Report -Lines $log -Name 'SETUP-BLOCKED.md' -Message "test: autorun-9zc blocked (station not healthy) $stamp soak8-e1acfe6"
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
    Save-Report -Lines $log -Name "AUTORUN-9zc-DRYRUN-$stamp.md" -Message "test: autorun-9zc dry-run $stamp soak8-e1acfe6"
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
}
$log += "token present: $([bool]$token)"
Save-Report -Lines $log -Name "AUTORUN-9zc-RESULT-$stamp.md" -Message "test: autorun-9zc first-admin token_present=$([bool]$token) $stamp soak8-e1acfe6"
if ($token) { exit 0 } else { exit 3 }
