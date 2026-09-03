# DIRECTIVE 4 — soak72-9573d4a: install OS-level watchdogs (survive app close and reboot)

Trigger: START NOW

Ack on your branch (soak/ACK-4.md), then do this BEFORE anything else — even before the kit fetch finishes. These are
Windows Scheduled Tasks. They keep polling directives and pushing heartbeats even if the Codex app closes or the box
reboots. They do not depend on you staying alive. Run every command in an ELEVATED PowerShell 5.1.

## 1. Folders and settings
```
$root='C:\CivicCastSoak'; foreach($d in 'bin','state','reports','reports\heartbeats'){ New-Item -Force -ItemType Directory (Join-Path $root $d) | Out-Null }
if (-not (Test-Path "$root\repo\.git")) { git clone https://github.com/scottconverse/civiccast-native.git "$root\repo" }
git -C "$root\repo" fetch origin
$br = "tester/soak72-9573d4a-$env:COMPUTERNAME"
if (git -C "$root\repo" ls-remote --heads origin $br) { git -C "$root\repo" checkout -q $br; git -C "$root\repo" pull -q --ff-only origin $br } else { git -C "$root\repo" checkout -q -b $br; }
git -C "$root\repo" config user.name "soak-tester-$env:COMPUTERNAME"; git -C "$root\repo" config user.email "soak-tester@civiccast.invalid"
Set-Content "$root\state\mission.txt" -Value "soak72-9573d4a" -Encoding ascii
```

## 2. Script: directive poll (every 15 min) — C:\CivicCastSoak\bin\poll-directives.ps1
```
$root='C:\CivicCastSoak'; $d="$root\directives"; $repo="$root\repo"; $br="tester/soak72-9573d4a-$env:COMPUTERNAME"
if (-not (Test-Path "$d\.git")) { git clone --single-branch --branch soak72-9573d4a-directives https://github.com/scottconverse/civiccast-native.git $d | Out-Null }
git -C $d fetch -q origin soak72-9573d4a-directives; git -C $d reset -q --hard origin/soak72-9573d4a-directives
$cur = (Select-String -Path "$d\LATEST-TEST-DIRECTIVE.md" -Pattern '^Current:\s*(\S+)').Matches[0].Groups[1].Value
$seenFile="$root\state\last-directive.txt"; $seen = if (Test-Path $seenFile) { Get-Content $seenFile -Raw } else { '' }
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
Add-Content "$root\reports\poll.log" "$stamp current=$cur seen=$($seen.Trim())"
if ($cur.Trim() -ne $seen.Trim()) {
  Set-Content $seenFile -Value $cur -Encoding ascii
  Set-Content "$root\state\NEW-DIRECTIVE.txt" -Value "$cur`n$stamp" -Encoding ascii
  $n = ($cur -replace '[^0-9]','')
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\AUTO-ACK-$n.md" -Value "# AUTO-ACK $n`n- Hostname: $env:COMPUTERNAME`n- UTC: $stamp`n- Received: $cur (by the scheduled poll task; the agent acts on it when it next runs)" -Encoding utf8
  git -C $repo add soak/AUTO-ACK-$n.md; git -C $repo commit -q -m "test: auto-ack $cur soak72-9573d4a $stamp"; git -C $repo push -q origin $br 2>&1 | Out-Null
}
```
(The agent — you — must still read `C:\CivicCastSoak\state\NEW-DIRECTIVE.txt` whenever it exists, act on the named
directive, write the human ACK-<n>.md, then delete NEW-DIRECTIVE.txt.)

## 3. Script: heartbeat (every 30 min) — C:\CivicCastSoak\bin\heartbeat.ps1
```
$root='C:\CivicCastSoak'; $repo="$root\repo"; $br="tester/soak72-9573d4a-$env:COMPUTERNAME"
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$health = $null; try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 10 } catch { $health = @{ status='unreachable'; error="$($_.Exception.Message)" } }
$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$procs = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(python|uvicorn|ffmpeg|gst-launch-1.0|civiccast|CivicCast)' } | Select-Object ProcessName, Id, @{n='rss_mb';e={[math]::Round($_.WorkingSet64/1MB)}}, @{n='cpu_s';e={[math]::Round($_.CPU,1)}}
$cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue
$mem = Get-CimInstance Win32_OperatingSystem; $disk = Get-PSDrive C
$hb = [ordered]@{ schema='civiccast-native-fleet-heartbeat-v1'; mission='soak72-9573d4a'; hostname=$env:COMPUTERNAME; utc=$stamp
  health=$health; service=$(if($svc){$svc.Status.ToString()}else{'not-registered'}); cpu_pct=[math]::Round($cpu,1)
  mem_free_mb=[math]::Round($mem.FreePhysicalMemory/1KB); disk_free_gb=[math]::Round($disk.Free/1GB,1); processes=@($procs)
  uptime_min=[math]::Round(((Get-Date)-$mem.LastBootUpTime).TotalMinutes) }
$file="$root\reports\heartbeats\heartbeat-$stamp.json"; $hb | ConvertTo-Json -Depth 6 | Set-Content $file -Encoding utf8
New-Item -Force -ItemType Directory "$repo\soak\heartbeats" | Out-Null; Copy-Item $file "$repo\soak\heartbeats\"
git -C $repo add soak/heartbeats; git -C $repo commit -q -m "test: soak heartbeat $stamp soak72-9573d4a"; git -C $repo push -q origin $br 2>&1 | Out-Null
```

## 4. Script: boot marker — C:\CivicCastSoak\bin\boot-marker.ps1
```
$root='C:\CivicCastSoak'; $repo="$root\repo"; $br="tester/soak72-9573d4a-$env:COMPUTERNAME"
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'); Start-Sleep -Seconds 120
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Add-Content "$repo\soak\BOOTS.md" "- $stamp boot marker (machine restarted; heartbeat task resumes)"
git -C $repo add soak/BOOTS.md; git -C $repo commit -q -m "test: boot marker $stamp soak72-9573d4a"; git -C $repo push -q origin $br 2>&1 | Out-Null
& "$root\bin\heartbeat.ps1"
```

## 5. Write the three scripts, then register the tasks (elevated)
Save each code block above to its path with `Set-Content -Encoding ascii`. Then:
```
$ps = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$pr = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$s  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
foreach ($t in @(
  @{ n='CivicCastSoak-Poll';      f='poll-directives.ps1'; tr=(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 30)) },
  @{ n='CivicCastSoak-Heartbeat'; f='heartbeat.ps1';       tr=(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 30)) },
  @{ n='CivicCastSoak-Boot';      f='boot-marker.ps1';     tr=(New-ScheduledTaskTrigger -AtLogOn) }
)) {
  $a = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoak\bin\$($t.f)"
  Unregister-ScheduledTask -TaskName $t.n -Confirm:$false -ErrorAction SilentlyContinue
  Register-ScheduledTask -TaskName $t.n -Action $a -Trigger $t.tr -Principal $pr -Settings $s | Out-Null
}
Get-ScheduledTask -TaskName 'CivicCastSoak-*' | Select-Object TaskName, State
Start-ScheduledTask -TaskName 'CivicCastSoak-Poll'; Start-Sleep 20; Start-ScheduledTask -TaskName 'CivicCastSoak-Heartbeat'
```
Then confirm on the repo: within 2 minutes your branch must show `soak/AUTO-ACK-4.md` (from the poll task) and a
`soak/heartbeats/heartbeat-*.json` (from the heartbeat task). If either is missing, run the script by hand
(`powershell -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoak\bin\heartbeat.ps1`), read its error, fix, and
commit what you found to soak/WATCHDOG-SETUP.md. If `git push` needs a sign-in, the credential you already used for
ACK-1/2 is stored for this user, so the tasks (same user) reuse it.

## 6. Then continue
Go back to the kit: DIRECTIVE-3 (evidence + zip route) → DIRECTIVE-2 (verify, silent install) → DIRECTIVE-1 (the
soak itself). The heartbeat task reports `health.status = unreachable` until the station is installed; that is
expected and is not a stall. Once the station is up, its `status`/`schema` fields appear in every heartbeat.
Never wait for a human.
