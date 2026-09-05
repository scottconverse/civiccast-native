# AUTORUN-9q (soak8-e1acfe6) -- read-only: which civiccast code is actually installed after the
# 91caebc upgrade? Hash + mtime of key files under the install tree vs the same files inside the
# kit's app-payload pack, plus the install/upgrade journals. Changes nothing.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9q installed-code check after the 91caebc upgrade", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$inst = 'C:\CivicCastHostStore\install'
$out += "## install tree"
$out += '```'
$out += (Get-ChildItem $inst -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Attributes) $($_.LastWriteTimeUtc.ToString('o')) $(if ($_.LinkType) { '-> ' + ($_.Target -join ',') })" })
$out += (Get-ChildItem 'C:\CivicCastHostStore' -ErrorAction SilentlyContinue | ForEach-Object { "hoststore: $($_.Name) $($_.Attributes) $($_.LastWriteTimeUtc.ToString('o')) $(if ($_.LinkType) { '-> ' + ($_.Target -join ',') })" })
$out += '```'
$out += "## key source files in the installed runtime"
$out += '```'
foreach ($rel in 'captions\tap_worker.py','captions\tap_backoff.py','captions\runtime.py','captions\live_sidecar.py','app.py','_native_version.py','egress\automation.py','egress\gst\strategy.py','installer\station_state.py') {
  $f = Join-Path "$inst\runtime\Lib\site-packages\civiccast" $rel
  if (Test-Path $f) { $out += "$rel $((Get-Item $f).Length) $((Get-Item $f).LastWriteTimeUtc.ToString('o')) sha256=$((Get-FileHash $f -Algorithm SHA256).Hash.ToLower())" } else { $out += "$rel MISSING" }
}
$out += "grep tap_worker.py for 'Caption tap overload' CRITICAL vs 'paused':"
$tw = "$inst\runtime\Lib\site-packages\civiccast\captions\tap_worker.py"
if (Test-Path $tw) {
  $c = Get-Content $tw -Raw
  $hasBackoff = [bool]($c -match 'CaptionBackoffPolicy')
  $hasPaused = [bool]($c -match 'paused')
  $hasCritical = [bool]($c -match '_LOG\.critical')
  $out += "  has CaptionBackoffPolicy=$hasBackoff  has paused=$hasPaused  has _LOG.critical=$hasCritical"
}
$out += '```'
$out += "## the same files inside the kit's app-payload pack (if it is a zip)"
$out += '```'
$kit = "$root\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6"
$pack = Get-ChildItem "$kit\packs" -Filter 'native-app-payload*.ccpack' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pack) {
  $out += "pack: $($pack.FullName) $($pack.Length) bytes sha256=$((Get-FileHash $pack.FullName -Algorithm SHA256).Hash.ToLower())"
  try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [System.IO.Compression.ZipFile]::OpenRead($pack.FullName)
    $hits = $z.Entries | Where-Object { $_.FullName -match 'civiccast/captions/(tap_worker|tap_backoff)\.py$|civiccast/_native_version\.py$' }
    foreach ($e in $hits) {
      $tmp = Join-Path $env:TEMP ("9q-" + [IO.Path]::GetFileName($e.FullName))
      [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $tmp, $true)
      $out += "$($e.FullName) $($e.Length) sha256=$((Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower())"
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
    $z.Dispose()
  } catch { $out += "zip read failed: $($_.Exception.Message)" }
} else { $out += 'no native-app-payload pack in the kit' }
$out += '```'
$out += "## journals: upgrade + provision + install-progress (payload/pack/route lines)"
$out += '```'
foreach ($d in 'C:\ProgramData\CivicCast\upgrade','C:\ProgramData\CivicCast\provision') {
  $out += "### $d"
  $out += (Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 8 | ForEach-Object { "$($_.FullName.Substring(24)) $($_.Length) $($_.LastWriteTimeUtc.ToString('o'))" })
  foreach ($jf in (Get-ChildItem $d -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 2)) { $out += "#### $($jf.Name)"; $out += (Get-Content $jf.FullName -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { $_.Substring(0,[Math]::Min(220,$_.Length)) }) }
}
$out += "### install-progress.log (payload/pack/route/skip/same lines, last 60)"
$out += (Get-Content 'C:\ProgramData\CivicCast\install-progress.log' -ErrorAction SilentlyContinue | Where-Object { $_ -match 'payload|pack|route|skip|same|junction|tree|D3|D4|step' } | Select-Object -Last 60 | ForEach-Object { $_.Substring(0,[Math]::Min(220,$_.Length)) })
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9q-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9q-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9q installed-code check $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
