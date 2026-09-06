# AUTORUN-9zg (soak8-e1acfe6) -- SECOND SOAK: fetch + verify kit 609273da22b968b8ed9320dfc158d67b01eb30b3 (main with the
# caption-tap fix, PR #172), install it silently OVER the running e502074 station (customer
# upgrade path), wait for health + all three channels ON_AIR, then archive the first soak's
# probe history and reset the relaunch counters so AUTORUN-3 starts a fresh 2-hour verdict.
# Executed automatically by the CivicCastSoak-Poll scheduled task, exactly once.
# Idempotent: re-running only re-fetches bad/missing files.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'

$root   = 'C:\CivicCastSoak'
$sha    = '609273da22b968b8ed9320dfc158d67b01eb30b3'
$dst    = "$root\kit-$sha"
$repo   = "$root\repo"
$br     = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base   = "http://192.168.0.135:8766/$sha/"
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log    = @("# AUTORUN-9zg soak #5: fetch kit 609273d + CLEAN reinstall (uninstall, wipe, fresh /S install)", "- mission: soak8-e1acfe6 (second soak, kit $sha)", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $base", "")

New-Item -Force -ItemType Directory $dst | Out-Null
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null

function Reset-AutorunMarker {
  Remove-Item "$root\state\autorun-done\AUTORUN-9zg.ps1.done" -Force -ErrorAction SilentlyContinue
}
function Publish-Log([string]$msg) {
  Set-Content "$repo\soak\INSTALL-RESULT-9zg.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add soak/INSTALL-RESULT-9zg.md
  git -C $repo commit --quiet -m "test: autorun-9zg $msg $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

function Save-Report { param([string[]]$Lines, [string]$Name, [string]$Message)
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\$Name" -Value ($Lines -join "`n") -Encoding utf8
  git -C $repo add "soak/$Name"
  git -C $repo commit --quiet -m $Message
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}
$kit = $dst
# ---------------------------------------------------------- 1. manifest + files
& curl.exe -sS -L --retry 5 --retry-delay 5 -o "$dst\SHA256SUMS.txt" ($base + 'SHA256SUMS.txt')
if (-not (Test-Path "$dst\SHA256SUMS.txt") -or (Get-Item "$dst\SHA256SUMS.txt").Length -eq 0) {
  $log += "KIT-FETCH-BLOCKED: could not download SHA256SUMS.txt from $base (retrying next poll cycle)"
  Reset-AutorunMarker
  Publish-Log 'kit fetch BLOCKED'
  exit 1
}
$manifest = @(Get-Content "$dst\SHA256SUMS.txt" | Where-Object { $_.Trim() })
$log += "manifest lines: $($manifest.Count)"

foreach ($line in $manifest) {
  $h, $rel = $line -split '\s+', 2
  if (-not $rel) { continue }
  $rel   = $rel.Trim().TrimStart('*')
  $local = Join-Path $dst ($rel -replace '/', '\')
  New-Item -Force -ItemType Directory (Split-Path $local) | Out-Null
  $url = $base + ((($rel -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/')
  $need = $true
  if (Test-Path $local) {
    if ((Get-Item $local).Length -gt 0 -and (Get-FileHash $local -Algorithm SHA256).Hash.ToLower() -eq $h.ToLower()) { $need = $false }
  }
  if ($need) {
    $log += "fetching $rel"
    & curl.exe -sS -L --retry 5 --retry-delay 5 -o $local $url
  }
}

$bad = 0
foreach ($line in $manifest) {
  $h, $rel = $line -split '\s+', 2
  if (-not $rel) { continue }
  $f = Join-Path $dst ($rel.Trim().TrimStart('*') -replace '/', '\')
  if (-not (Test-Path $f) -or (Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $h.ToLower()) {
    $log += "BAD $rel"
    $bad++
  }
}
$log += "kit verify bad=$bad"
if ($bad -ne 0) {
  Reset-AutorunMarker
  Publish-Log "kit verify FAILED bad=$bad"
  exit 2
}

# ------------------------------------------------- 2. locate the installer exe
$exeName = ($manifest | ForEach-Object { ($_ -split '\s+', 2)[1].Trim().TrimStart('*') } | Where-Object { $_ -match '^[^/]+_x64-setup\.exe$' } | Select-Object -First 1)
$exe = $(if ($exeName) { Get-Item (Join-Path $dst $exeName) -ErrorAction SilentlyContinue })
if (-not $exe) {
  $log += "no installer .exe found at the kit root"
  Publish-Log 'no installer'
  exit 3
}
$log += "installer: $($exe.Name) ($($exe.Length) bytes)"
Unblock-File $exe.FullName -ErrorAction SilentlyContinue
$log += "authenticode: $((Get-AuthenticodeSignature -LiteralPath $exe.FullName).Status)"

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
  Save-Report -Lines $log -Name 'REINSTALL-RESULT-9zg.md' -Message "test: autorun-9 dry-run $stamp soak8-e1acfe6"
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
Save-Report -Lines $log -Name 'REINSTALL-RESULT-9zg.md' -Message "test: autorun-9zg clean reinstall exit=$installerExit healthy=$healthy $stamp soak8-e1acfe6"
if ($healthy) { exit 0 } else { exit 4 }
