# AUTORUN-9j (soak8-e1acfe6) -- SECOND SOAK: fetch + verify kit 91caebccc6a6decef476fea5cd785a9ff19abfe6 (main with the
# caption-tap fix, PR #172), install it silently OVER the running e502074 station (customer
# upgrade path), wait for health + all three channels ON_AIR, then archive the first soak's
# probe history and reset the relaunch counters so AUTORUN-3 starts a fresh 2-hour verdict.
# Executed automatically by the CivicCastSoak-Poll scheduled task, exactly once.
# Idempotent: re-running only re-fetches bad/missing files.
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'

$root   = 'C:\CivicCastSoak'
$sha    = '91caebccc6a6decef476fea5cd785a9ff19abfe6'
$dst    = "$root\kit-$sha"
$repo   = "$root\repo"
$br     = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base   = "http://192.168.0.135:8766/$sha/"
$stamp  = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$log    = @("# AUTORUN-9j second soak: kit fetch + upgrade install + soak reset", "- mission: soak8-e1acfe6 (second soak, kit $sha)", "- host: $env:COMPUTERNAME", "- utc: $stamp", "- kit: $base", "")

New-Item -Force -ItemType Directory $dst | Out-Null
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null

function Reset-AutorunMarker {
  Remove-Item "$root\state\autorun-done\AUTORUN-9j.ps1.done" -Force -ErrorAction SilentlyContinue
}
function Publish-Log([string]$msg) {
  Set-Content "$repo\soak\INSTALL-RESULT-9j.md" -Value ($log -join "`n") -Encoding utf8
  git -C $repo add soak/INSTALL-RESULT-9j.md
  git -C $repo commit --quiet -m "test: autorun-9j $msg $stamp soak8-e1acfe6"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}

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

$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
if ($svc) { $log += "existing station: service=$($svc.Status); installing the full kit OVER it (customer upgrade path)" }
else { $log += "WARNING: no CivicCastSupervisor service found; this becomes a fresh install" }

if ($DryRun) { Write-Host ($log -join "`n"); Write-Host ('DRYRUN: fetch+verify complete; installer selected: ' + $exe.FullName); exit 0 }

# ------------------------------------------------------------ 3. silent install
$log += "silent install started $((Get-Date).ToUniversalTime().ToString('o'))"
$p = Start-Process -FilePath $exe.FullName -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru
$null = $p.Handle
$p.WaitForExit()
$installerExit = $p.ExitCode
$log += "installer exit=$installerExit at $((Get-Date).ToUniversalTime().ToString('o'))"
$log += ''
$log += '## install-progress.log tail'
$log += '```'
$log += (Get-Content 'C:\ProgramData\CivicCast\install-progress.log' -Tail 40 -ErrorAction SilentlyContinue)
$log += '```'

# ------------------------------------------------------------ 4. wait for health
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
$log += "install RESULT: installer_exit=$installerExit healthy=$healthy"
if (-not $healthy) { Publish-Log "install result exit=$installerExit healthy=False"; exit 4 }

# ------------------------------------------- 5. wait for all three channels ON_AIR
$tokenFile = "$root\state\token"
$onAir = @()
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  for ($i = 0; $i -lt 20; $i++) {
    $onAir = @()
    try {
      $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/staff/egress/channels' -Headers $hdr -TimeoutSec 20
      $chans = $(if ($r.PSObject.Properties.Name -contains 'channels') { $r.channels } elseif ($r.PSObject.Properties.Name -contains 'items') { $r.items } else { $r })
      foreach ($c in @($chans)) {
        $st = $(if ($c.PSObject.Properties.Name -contains 'state') { $c.state } elseif ($c.PSObject.Properties.Name -contains 'engine_state') { $c.engine_state } else { '' })
        if ("$st" -eq 'ON_AIR') { $onAir += "$($c.id)$($c.channel_id)" }
      }
    } catch { $log += "channels poll: $($_.Exception.Message)" }
    if ($onAir.Count -ge 3) { break }
    Start-Sleep -Seconds 30
  }
  $log += "channels ON_AIR after upgrade: $($onAir.Count) [$($onAir -join ', ')]"
} else {
  $log += "no state\token file; cannot poll channels via API"
}
$log += '## raw channel state (egress state.json per channel)'
$log += '```'
foreach ($id in 'public','education','government') {
  $sf = "C:\ProgramData\CivicCast\data\egress\$id\state.json"
  $log += "$id : $(if (Test-Path $sf) { (Get-Content $sf -Raw).Substring(0, [Math]::Min(300, (Get-Content $sf -Raw).Length)) } else { 'missing' })"
}
$log += '```'
if ($onAir.Count -lt 3) { Publish-Log "upgrade ok but only $($onAir.Count)/3 channels ON_AIR; soak NOT restarted"; exit 5 }

# ------------------------------- 6. archive soak #1 history, reset counters, restart soak
$arch = "$repo\soak\archive-e502074-soak1"
New-Item -Force -ItemType Directory $arch | Out-Null
New-Item -Force -ItemType Directory "$arch\egress" | Out-Null
Get-ChildItem "$repo\soak\egress" -Filter 'egress-*.json' -File -ErrorAction SilentlyContinue | Move-Item -Destination "$arch\egress" -Force
Get-ChildItem "$repo\soak" -Filter 'SOAK-REPORT-*.md' -File -ErrorAction SilentlyContinue | Move-Item -Destination $arch -Force
if (Test-Path "$repo\soak\final-verdict.json") { Move-Item "$repo\soak\final-verdict.json" "$arch\final-verdict.json" -Force }
foreach ($f in 'last-pid-*.txt','relaunch-count-*.txt','last-errors-*.json','last-cpu-sample.json','last-rollup-hours','last-egress-run') {
  Get-ChildItem "$root\state" -Filter $f -File -ErrorAction SilentlyContinue | Remove-Item -Force
}
$startIso = (Get-Date).ToUniversalTime().ToString('o')
Set-Content "$root\state\soak-started" -Value $startIso -Encoding ascii
Set-Content "$root\state\installed" -Value $stamp -Encoding ascii
$log += "soak #1 history archived to soak/archive-e502074-soak1; counters reset; soak #2 started $startIso on kit $sha"
git -C $repo add -A soak
Publish-Log "second soak STARTED on kit $sha (installer exit=$installerExit)"
exit 0
