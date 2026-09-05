# AUTORUN-9k (soak8-e1acfe6) -- read-only: what happened to AUTORUN-9j (upgrade to kit 91caebc)?
# Reports kit folder state, once-only markers, the local INSTALL-RESULT-9j.md if it exists but was
# never pushed, install-progress.log tail, service/health/channel state, processes. No changes.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$sha   = '91caebccc6a6decef476fea5cd785a9ff19abfe6'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9k: what happened to 9j", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$out += "## kit folder $root\kit-$sha"
$out += '```'
$out += (Get-ChildItem "$root\kit-$sha" -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum | ForEach-Object { "files=$($_.Count) bytes=$($_.Sum)" })
$out += (Get-ChildItem "$root\kit-$sha" -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Length)" })
$out += '```'
$out += "## autorun-done markers"
$out += '```'
$out += (Get-ChildItem "$root\state\autorun-done" -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.LastWriteTimeUtc.ToString('o'))" })
$out += '```'
$out += "## state files"
$out += '```'
$out += (Get-ChildItem "$root\state" -File -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Length) $($_.LastWriteTimeUtc.ToString('o')) :: $((Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue) -replace '\s+',' ' | ForEach-Object { $_.Substring(0,[Math]::Min(80,$_.Length)) })" })
$out += '```'
$out += "## local repo: soak/INSTALL-RESULT-9j.md + git status"
$out += '```'
if (Test-Path "$repo\soak\INSTALL-RESULT-9j.md") { $out += (Get-Content "$repo\soak\INSTALL-RESULT-9j.md" -Tail 60) } else { $out += 'INSTALL-RESULT-9j.md: not present locally' }
$out += (git -C $repo status --short 2>&1 | Select-Object -First 20)
$out += (git -C $repo log -3 --format='%cI %s' 2>&1)
$out += '```'
$out += "## poll task log tail (if any)"
$out += '```'
$out += (Get-ChildItem "$root" -Filter '*.log' -File -ErrorAction SilentlyContinue | ForEach-Object { "### $($_.Name)"; Get-Content $_.FullName -Tail 30 -ErrorAction SilentlyContinue })
$out += (Get-ChildItem "$root\logs" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime | Select-Object -Last 3 | ForEach-Object { "### logs\$($_.Name)"; Get-Content $_.FullName -Tail 30 -ErrorAction SilentlyContinue })
$out += '```'
$out += "## install-progress.log tail"
$out += '```'
$out += (Get-Content 'C:\ProgramData\CivicCast\install-progress.log' -Tail 40 -ErrorAction SilentlyContinue)
$out += '```'
$out += "## service / health / processes"
$out += '```'
$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$out += "service: $(if ($svc) { $svc.Status } else { 'absent' })"
try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10; $out += ("health: " + ($h | ConvertTo-Json -Compress -Depth 4)) } catch { $out += "health: $($_.Exception.Message)" }
$out += (Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(python|ffmpeg|gst|CivicCast|.*setup)' } | ForEach-Object { "pid=$($_.ProcessId) ppid=$($_.ParentProcessId) $($_.Name) :: $($_.CommandLine.Substring(0,[Math]::Min(160,[Math]::Max(0,$_.CommandLine.Length))))" })
$out += '```'
$out += "## egress data dir + raw API (channels, schedule, playout state)"
$out += '```'
$out += (Get-ChildItem 'C:\ProgramData\CivicCast\data\egress' -Recurse -Depth 2 -ErrorAction SilentlyContinue | ForEach-Object { "$($_.FullName.Substring(29)) $($_.Length) $($_.LastWriteTimeUtc.ToString('o'))" } | Select-Object -First 40)
$out += (Get-ChildItem 'C:\ProgramData\CivicCast' -Directory -ErrorAction SilentlyContinue | ForEach-Object { "dir: $($_.Name)" })
$tokenFile = "$root\state\token"
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  foreach ($path in '/api/staff/egress/channels', '/api/staff/egress/channels/public', '/api/staff/schedule?limit=5', '/api/staff/playout/state', '/api/staff/station/profile') {
    try { $r = Invoke-WebRequest -Uri ('http://127.0.0.1:8000' + $path) -Headers $hdr -TimeoutSec 20 -UseBasicParsing; $out += "GET $path -> $([int]$r.StatusCode) $($r.Content.Substring(0,[Math]::Min(1500,$r.Content.Length)))" } catch { $out += "GET $path -> $($_.Exception.Message) $(try { $_.ErrorDetails.Message } catch { '' })" }
  }
} else { $out += 'no state\token' }
$out += '```'
$out += "## installed version (uninstall registry)"
$out += '```'
$out += (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'CivicCast*' } | ForEach-Object { "$($_.DisplayName) $($_.DisplayVersion) $($_.InstallDate)" })
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9k-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9k-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9k what happened to 9j $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
