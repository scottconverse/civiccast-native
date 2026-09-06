# AUTORUN-9zb (soak8-e1acfe6) -- clear the persisted first-admin marker and restart the station.
# Why: first-admin answers 409 even on a freshly reinstalled station because
# station-state.json (civiccast/installer/station_state.py:488-496) lives under the
# SERVICE account's %LOCALAPPDATA%\CivicCast and survives uninstall + data removal.
# Tester box only. Reports soak/STATE-RESET-RESULT.md. No channel changes.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log   = @("# AUTORUN-9zb station-state reset", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- DryRun: $DryRun", "")

function Save-Report([string[]]$Lines, [string]$Name, [string]$Message) {
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\$Name" -Value ($Lines -join "`n") -Encoding utf8
  if ($DryRun) { Write-Host "[DRYRUN] would commit $Name"; return }
  git -C $repo add "soak/$Name"
  git -C $repo commit --quiet -m $Message
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

$candidates = @(
  "$env:SystemRoot\System32\config\systemprofile\AppData\Local\CivicCast\station-state.json",
  "$env:SystemRoot\SysWOW64\config\systemprofile\AppData\Local\CivicCast\station-state.json",
  "$env:ProgramData\CivicCast\station-state.json"
)
$candidates += (Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object { "$($_.FullName)\AppData\Local\CivicCast\station-state.json" })
$found = @($candidates | Where-Object { Test-Path -LiteralPath $_ })
$log += "station-state.json candidates found: $($found.Count)"
foreach ($f in $found) { $log += "  - $f ($((Get-Item -LiteralPath $f).LastWriteTimeUtc.ToString('o')), $((Get-Item -LiteralPath $f).Length) bytes)" }
if ($found.Count -eq 0) { $log += "NOTE: no station-state.json found; the 409 must come from somewhere else (see product router)." }

$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$log += "service before: $(if ($svc) { $svc.Status } else { 'absent' })"

if ($DryRun) {
  $log += "[DRYRUN] would stop the service, rename each found file to *.bak-$stamp, start the service, wait for /health"
  Save-Report -Lines $log -Name 'STATE-RESET-RESULT-9zb.md' -Message "test: autorun-9zb dry-run $stamp soak8-e1acfe6"
  Write-Host ($log -join "`n"); exit 0
}

if ($svc -and $svc.Status -ne 'Stopped') { Stop-Service -Name 'CivicCastSupervisor' -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 15 }
$log += "service after stop: $((Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue).Status)"
foreach ($f in $found) {
  try { Rename-Item -LiteralPath $f -NewName ("station-state.json.bak-" + $stamp) -ErrorAction Stop; $log += "renamed $f" }
  catch { $log += "could not rename ${f}: $($_.Exception.Message)" }
}
Start-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$health = $null
for ($i = 0; $i -lt 40; $i++) {
  try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10; if ($health.status -eq 'healthy') { break } } catch { }
  Start-Sleep -Seconds 15
}
$healthy = ($health -and $health.status -eq 'healthy')
$log += "service after start: $((Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue).Status) healthy=$healthy"
# Probe the setup state so the next autorun's odds are known before it runs.
try { $ss = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/setup/station-state' -TimeoutSec 15; $log += "station-state endpoint: " + ($ss | ConvertTo-Json -Compress -Depth 5) } catch { $log += "station-state endpoint: $($_.Exception.Message)" }
Remove-Item "$root\state\token" -Force -ErrorAction SilentlyContinue
$log += "RESULT: healthy=$healthy files_reset=$($found.Count)"
Save-Report -Lines $log -Name 'STATE-RESET-RESULT-9zb.md' -Message "test: autorun-9zb state reset healthy=$healthy files=$($found.Count) $stamp soak8-e1acfe6"
if ($healthy) { exit 0 } else { exit 4 }
