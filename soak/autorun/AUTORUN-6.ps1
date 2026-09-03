# AUTORUN-6: executed by the CivicCastSoak-Poll task (after DIRECTIVE-6 installs the hook) or by the agent.
# Idempotent: verifies the kit, installs silently if the station is not registered, records results to the tester branch.
$root='C:\CivicCastSoak'; $dst="$root\kit"; $repo="$root\repo"; $br="tester/soak72-9573d4a-$env:COMPUTERNAME"
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'); $out="$repo\soak\AUTORUN-6-$stamp.md"; $log=@()
$log += "# AUTORUN-6 $stamp on $env:COMPUTERNAME"
$svc = Get-Service CivicCastSupervisor -ErrorAction SilentlyContinue
if ($svc) { $log += "service already registered: $($svc.Status); nothing to install" }
else {
  $base='http://192.168.0.135:8766/9573d4a82e1e1d9993589f633bad6dacba792afb/'
  New-Item -Force -ItemType Directory $dst | Out-Null
  curl.exe -sS -L -o "$dst\SHA256SUMS.txt" ($base + 'SHA256SUMS.txt')
  $bad=0
  Get-Content "$dst\SHA256SUMS.txt" | ForEach-Object {
    $h,$rel = $_ -split '\s+',2; if (-not $rel) { return }
    $local = Join-Path $dst ($rel -replace '/','\'); New-Item -Force -ItemType Directory (Split-Path $local) | Out-Null
    $url = $base + ((($rel -split '/') | ForEach-Object { [uri]::EscapeDataString($_) }) -join '/')
    if (-not (Test-Path $local) -or (Get-Item $local).Length -eq 0 -or ((Get-FileHash $local -Algorithm SHA256).Hash.ToLower() -ne $h)) {
      curl.exe -sS -L --retry 5 --retry-delay 5 -o $local $url
      if (-not (Test-Path $local) -or ((Get-FileHash $local -Algorithm SHA256).Hash.ToLower() -ne $h)) { $bad++; $log += "BAD $rel" }
    }
  }
  $log += "kit verify bad=$bad"
  if ($bad -eq 0) {
    $exe="$dst\CivicCast (Native)_1.0.0-beta.3_x64-setup.exe"; Unblock-File $exe -ErrorAction SilentlyContinue
    $log += "silent install started $((Get-Date).ToUniversalTime().ToString('o'))"
    $p = Start-Process -FilePath $exe -ArgumentList '/S /D=C:\CivicCastHostStore\install' -PassThru -Wait
    $log += "installer exit=$($p.ExitCode) at $((Get-Date).ToUniversalTime().ToString('o'))"
    $log += "install-progress.log tail:"; $log += (Get-Content C:\ProgramData\CivicCast\install-progress.log -Tail 25 -ErrorAction SilentlyContinue)
    $health=$null; for ($i=0; $i -lt 40; $i++) { try { $health = Invoke-RestMethod http://127.0.0.1:8000/health -TimeoutSec 10; if ($health.status -eq 'healthy') { break } } catch {}; Start-Sleep 30 }
    $log += "health: " + ($health | ConvertTo-Json -Compress -Depth 4)
  }
}
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null; Set-Content $out -Value ($log -join "`n") -Encoding utf8
git -C $repo add soak/; git -C $repo commit -q -m "test: autorun-6 result $stamp soak72-9573d4a"; git -C $repo push -q origin $br 2>&1 | Out-Null
