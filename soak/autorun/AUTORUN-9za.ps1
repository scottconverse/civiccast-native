# AUTORUN-9za (soak8-e1acfe6) -- CLEAN REINSTALL of the 91caebc kit on this tester box.
# Why: the same-version upgrade (e502074 -> 91caebc, both 1.0.0-beta.5) left the OLD app payload in place
# never stored here, so first-admin returns 409 and no soak can start. On a tester box
# the honest fix is: quiet uninstall, remove the station data, install the same kit fresh.
# The kit is already verified on disk (AUTORUN-5). No download. Reports to the branch.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'
$root   = 'C:\CivicCastSoak'
$repo   = "$root\repo"
$br     = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$kit    = "$root\kit-609273da22b968b8ed9320dfc158d67b01eb30b3"
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log    = @("# AUTORUN-9 clean reinstall", "- mission: soak8-e1acfe6", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $kit", "- DryRun: $DryRun", "")

function Save-Report([string[]]$Lines, [string]$Name, [string]$Message) {
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\$Name" -Value ($Lines -join "`n") -Encoding utf8
  if ($DryRun) { Write-Host "[DRYRUN] would commit $Name"; return }
  git -C $repo add "soak/$Name"
  git -C $repo commit --quiet -m $Message
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

# ------------------------------------------------------------- 1. the installer
$exe = Get-Item "$kit\CivicCast (Native)_1.0.0-beta.5_x64-setup.exe" -ErrorAction SilentlyContinue
if (-not $exe) {
  $log += "STALLED: kit installer not found under $kit (AUTORUN-5 must have fetched it)"
  Save-Report -Lines $log -Name 'REINSTALL-RESULT-9za.md' -Message "test: autorun-9 blocked (no kit) $stamp soak8-e1acfe6"
  exit 2
}
$log += "installer: $($exe.Name) ($($exe.Length) bytes) sha256=$((Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash.ToLower())"

# ------------------------------------------------------------- 2. quiet uninstall
$keys = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$entry = Get-ItemProperty $keys -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'CivicCast*' } | Select-Object -First 1
$quiet = $(if ($entry) { if ($entry.QuietUninstallString) { $entry.QuietUninstallString } else { $entry.UninstallString } } else { '' })
$log += "existing: version='$($entry.DisplayVersion)' quiet-uninstall='$quiet'"
$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
if ($svc) { $log += "service before: $($svc.Status)" }

if ($DryRun) {
  $log += "[DRYRUN] would run the quiet uninstaller, remove C:\ProgramData\CivicCast, then run '$($exe.FullName)' /S /D=C:\CivicCastHostStore\install"
  Save-Report -Lines $log -Name 'REINSTALL-RESULT-9za.md' -Message "test: autorun-9 dry-run $stamp soak8-e1acfe6"
  Write-Host ($log -join "`n"); exit 0
}

if ($quiet) {
  try {
    if ($svc -and $svc.Status -ne 'Stopped') { Stop-Service -Name 'CivicCastSupervisor' -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 10 }
    $cmd = $quiet.Trim()
    if ($cmd.StartsWith('"')) { $endQuote = $cmd.IndexOf('"', 1); $file = $cmd.Substring(1, $endQuote - 1); $args = $cmd.Substring($endQuote + 1).Trim() }
    else { $parts = $cmd -split ' ', 2; $file = $parts[0]; $args = $(if ($parts.Count -gt 1) { $parts[1] } else { '' }) }
    $u = $(if ($args) { Start-Process -FilePath $file -ArgumentList $args -PassThru -Wait } else { Start-Process -FilePath $file -PassThru -Wait })
    $null = $u.Handle
    $log += "uninstaller exit=$($u.ExitCode)"
    Start-Sleep -Seconds 20
  } catch { $log += "uninstall attempt failed: $($_.Exception.Message)" }
} else {
  $log += "no uninstall string found; proceeding to data removal + fresh install"
}
$svcAfter = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$log += "service after uninstall: $(if ($svcAfter) { $svcAfter.Status } else { 'absent' })"

# ------------------------------------------------------------- 3. remove station data (tester box only)
foreach ($d in 'C:\ProgramData\CivicCast', 'C:\CivicCastHostStore\install') {
  if (Test-Path $d) {
    try { Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction Stop; $log += "removed $d" } catch { $log += "could not fully remove ${d}: $($_.Exception.Message)" }
  } else { $log += "absent: $d" }
}

# ------------------------------------------------------------- 4. fresh silent install
$log += "silent install started $((Get-Date).ToUniversalTime().ToString('o'))"
$p = Start-Process -FilePath $exe.FullName -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait
$null = $p.Handle
$installerExit = $p.ExitCode
$log += "installer exit=$installerExit at $((Get-Date).ToUniversalTime().ToString('o'))"
$log += ''
$log += '## install-progress.log tail'
$log += '```'
$log += (Get-Content 'C:\ProgramData\CivicCast\install-progress.log' -Tail 25 -ErrorAction SilentlyContinue)
$log += '```'

# ------------------------------------------------------------- 5. wait for health
$health = $null
for ($i = 0; $i -lt 60; $i++) {
  try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10
    if ($health.status -eq 'healthy' -and "$($health.schema)" -eq 'current') { break }
  } catch { }
  Start-Sleep -Seconds 30
}
$log += ''
$log += '## /health'
$log += '```json'
$log += ($health | ConvertTo-Json -Depth 6)
$log += '```'
$healthy = ($health -and $health.status -eq 'healthy')
$log += "RESULT: installer_exit=$installerExit healthy=$healthy fresh_install=True"
# A fresh station has no admin yet; clear any stale token so the channel script does first-admin.
Remove-Item "$root\state\token" -Force -ErrorAction SilentlyContinue
Remove-Item "$root\state\soak-started" -Force -ErrorAction SilentlyContinue
if ($healthy) { Set-Content "$root\state\installed" -Value $stamp -Encoding ascii }
Save-Report -Lines $log -Name 'REINSTALL-RESULT-9za.md' -Message "test: autorun-9za clean reinstall exit=$installerExit healthy=$healthy $stamp soak8-e1acfe6"
if ($healthy) { exit 0 } else { exit 4 }
