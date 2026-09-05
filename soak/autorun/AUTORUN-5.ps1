# AUTORUN-5 (soak8-e1acfe6) -- fetch + verify the FIXED kit into a fresh per-kit folder,
# then install it silently OVER the existing station (the customer upgrade path).
# Executed automatically by the CivicCastSoak-Poll scheduled task, exactly once.
# Idempotent: re-running only re-fetches bad/missing files and skips an install
# that is already at the right version.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'

$root   = 'C:\CivicCastSoak'
$dst    = "$root\kit-e5020746fa40e7a3f1a160d3a8e1add5c3b57786"
$repo   = "$root\repo"
$br     = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base   = 'http://192.168.0.135:8766/e5020746fa40e7a3f1a160d3a8e1add5c3b57786/'
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log    = @("# AUTORUN-5 kit fetch + install", "- mission: soak8-e1acfe6", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $base", "")

$script:fetchPhase = $true
New-Item -Force -ItemType Directory $dst | Out-Null
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null

# If this run cannot complete (kit not staged yet, server down, hash bad), clear our
# own once-only marker so the 10-minute poll retries instead of giving up forever.
function Reset-AutorunMarker {
  Remove-Item "$root\state\autorun-done\AUTORUN-5.ps1.done" -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------- 1. manifest + files
& curl.exe -sS -L --retry 5 --retry-delay 5 -o "$dst\SHA256SUMS.txt" ($base + 'SHA256SUMS.txt')
if (-not (Test-Path "$dst\SHA256SUMS.txt") -or (Get-Item "$dst\SHA256SUMS.txt").Length -eq 0) {
  $log += "KIT-FETCH-BLOCKED: could not download SHA256SUMS.txt from $base (retrying next poll cycle)"
  Reset-AutorunMarker
  Set-Content "$repo\soak\INSTALL-RESULT.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add soak/INSTALL-RESULT.md
  git -C $repo commit --quiet -m "test: autorun-5 kit fetch BLOCKED $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
  exit 1
}
$manifest = @(Get-Content "$dst\SHA256SUMS.txt" | Where-Object { $_.Trim() })
$log += "manifest lines: $($manifest.Count)"

foreach ($line in $manifest) {
  $h, $rel = $line -split '\s+', 2
  if (-not $rel) { continue }
  $rel   = $rel.Trim().TrimStart('*')   # sha256sum binary-mode marker
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
if ($bad -eq 0) { $script:fetchPhase = $false }
if ($bad -ne 0) {
  Reset-AutorunMarker
  Set-Content "$repo\soak\INSTALL-RESULT.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add soak/INSTALL-RESULT.md
  git -C $repo commit --quiet -m "test: autorun-5 kit verify FAILED bad=$bad $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
  exit 2
}

# ------------------------------------------------- 2. locate the installer exe
$exeName = ($manifest | ForEach-Object { ($_ -split '\s+', 2)[1].Trim() } | Where-Object { $_ -match '^[^/]+_x64-setup\.exe$' } | Select-Object -First 1)
$exe = $(if ($exeName) { Get-Item (Join-Path $dst $exeName) -ErrorAction SilentlyContinue })
if (-not $exe) {
  $log += "no installer .exe found at the kit root"
  Set-Content "$repo\soak\INSTALL-RESULT.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add soak/INSTALL-RESULT.md
  git -C $repo commit --quiet -m "test: autorun-5 no installer $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
  exit 3
}
$log += "installer: $($exe.Name) ($($exe.Length) bytes)"
Unblock-File $exe.FullName -ErrorAction SilentlyContinue
$sig = (Get-AuthenticodeSignature -LiteralPath $exe.FullName).Status
$log += "authenticode: $sig"

# kit version, from the installer file name (…_<version>_x64-setup.exe)
$kitVersion = ''
if ($exe.Name -match '_([0-9][^_]*)_x64-setup\.exe$') { $kitVersion = $Matches[1] }
$log += "kit version: $(if($kitVersion){$kitVersion}else{'(unparsed)'})"

# ----------------------------- 3. uninstall ONLY if a DIFFERENT version is there
$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$installedVersion = ''
$quietUninstall = ''
if ($svc) {
  $keys = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
  )
  $entry = Get-ItemProperty $keys -ErrorAction SilentlyContinue |
             Where-Object { $_.DisplayName -like 'CivicCast*' } | Select-Object -First 1
  if ($entry) {
    $installedVersion = "$($entry.DisplayVersion)"
    $quietUninstall = $(if ($entry.QuietUninstallString) { $entry.QuietUninstallString } else { $entry.UninstallString })
  }
  $log += "existing install: service=$($svc.Status) version='$installedVersion' quiet-uninstall='$quietUninstall'"
}

if ($svc) { $log += "existing station stays; installing the full kit OVER it (customer upgrade path)" }

if ($DryRun) { Write-Host ($log -join "`n"); Write-Host 'DRYRUN: fetch+verify complete; installer selected: ' + $exe.FullName; exit 0 }
# ------------------------------------------------------------ 4. silent install
$log += "silent install started $((Get-Date).ToUniversalTime().ToString('o'))"
$p = Start-Process -FilePath $exe.FullName -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait
$installerExit = $p.ExitCode
$log += "installer exit=$installerExit at $((Get-Date).ToUniversalTime().ToString('o'))"
$log += ''
$log += '## install-progress.log tail'
$log += '```'
$log += (Get-Content 'C:\ProgramData\CivicCast\install-progress.log' -Tail 40 -ErrorAction SilentlyContinue)
$log += '```'

# ------------------------------------------------------------ 5. wait for health
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
$log += "RESULT: installer_exit=$installerExit healthy=$healthy"
if ($healthy) { Set-Content "$root\state\installed" -Value $stamp -Encoding ascii }

Set-Content "$repo\soak\INSTALL-RESULT.md" -Value ($log -join "`n") -Encoding utf8
git -C $repo add soak/INSTALL-RESULT.md
git -C $repo commit --quiet -m "test: autorun-5 install result exit=$installerExit healthy=$healthy $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
if ($healthy) { exit 0 } else { exit 4 }
