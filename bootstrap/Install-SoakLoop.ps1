<#
.SYNOPSIS
  CivicCast fleet soak mission soak8-e1acfe6 -- one-shot bootstrap.

.DESCRIPTION
  Installs the repo-checker LOOP FIRST, then proves it before returning.
  After this script prints "LOOP PROVEN" no human is needed again: the
  coordinator ships further orders as soak/autorun/AUTORUN-<n>.ps1 on the
  directives branch and the poll task executes them.

  Idempotent. Safe to re-run. PowerShell 5.1 only. Run ELEVATED.

  Correct on ANY pre-existing state: a leftover single-branch clone from an
  earlier mission is detected and replaced, and a narrow fetch refspec is
  widened, so origin/main and this mission's branch always resolve.

.PARAMETER DryRun
  Parse/plan only: create no tasks, clone nothing, touch no state. Used by the
  coordinator to smoke-test this file without side effects.

.PARAMETER SkipTasks
  Do the clones, write the loop scripts, and run the proof by invoking the
  scripts directly instead of registering scheduled tasks. Needs no elevation.
  Coordinator test mode -- pair with CIVICCAST_SOAK_NO_AUTORUN=1 to exercise the
  loop on a machine that must not have the product installed onto it.
#>
[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$SkipTasks,
  [string]$Root = 'C:\CivicCastSoak'
)

$ErrorActionPreference = 'Stop'
$Mission        = 'soak8-e1acfe6'
$DirectiveBranch= 'soak8-e1acfe6-directives'
$RepoUrl        = 'https://github.com/scottconverse/civiccast-native.git'
$TesterBranch   = "tester/soak8-e1acfe6-$env:COMPUTERNAME"

function Say($m) { Write-Host "[soak8] $m" }
function Stamp   { (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') }

Say "mission=$Mission root=$Root branch=$TesterBranch dryrun=$($DryRun.IsPresent)"

# ---------------------------------------------------------------- 0. elevation
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun -and -not $SkipTasks) {
  Write-Host "LOOP FAILED: not elevated. Re-run this script in an ELEVATED PowerShell (Run as administrator)."
  exit 2
}

# ------------------------------------------- 1. clear ANY previous mission loop
Say 'unregistering any previous CivicCastSoak-* scheduled tasks'
if (-not $DryRun) {
  Get-ScheduledTask -TaskName 'CivicCastSoak-*' -ErrorAction SilentlyContinue | ForEach-Object {
    Say "  unregister $($_.TaskName)"
    Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false -ErrorAction SilentlyContinue
  }
}

# ------------------------------------------------------------------ 2. folders
foreach ($d in 'bin','state','state\autorun-done','reports','reports\heartbeats','directives','repo') {
  $p = Join-Path $Root $d
  if (-not $DryRun) { New-Item -Force -ItemType Directory $p | Out-Null }
}
Say "folders ready under $Root"

# --------------------------------------------------------------------- 3. git
$gitOk = $false
try { & git --version *>$null; $gitOk = ($LASTEXITCODE -eq 0) } catch { $gitOk = $false }
if (-not $gitOk) {
  Say 'git not found -- installing via winget'
  if (-not $DryRun) {
    & winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
    $extra = @("$env:ProgramFiles\Git\cmd", "$env:LOCALAPPDATA\Programs\Git\cmd")
    foreach ($e in $extra) { if (Test-Path $e) { $env:Path = "$env:Path;$e" } }
    try { & git --version *>$null; $gitOk = ($LASTEXITCODE -eq 0) } catch { $gitOk = $false }
  }
  if (-not $gitOk -and -not $DryRun) {
    Write-Host "LOOP FAILED: git is not installed and 'winget install --id Git.Git' did not make it available on PATH."
    exit 3
  }
}
Say "git available: $(if($gitOk){'yes'}else{'dry-run-skipped'})"

# ------------------------------------------------------- 4. clones and branch
$dir  = Join-Path $Root 'directives'
$repo = Join-Path $Root 'repo'
if (-not $DryRun) {
  # --- directives clone -------------------------------------------------------
  # A previous mission left a SINGLE-BRANCH clone here whose refspec only knows
  # ITS branch. Detect that and re-clone rather than fetching into a clone that
  # can never resolve origin/<this mission's branch>.
  $dirStale = $true
  if (Test-Path (Join-Path $dir '.git')) {
    $head    = (& git -C $dir rev-parse --abbrev-ref HEAD 2>$null)
    $refspec = (& git -C $dir config --get-all remote.origin.fetch 2>$null) -join ' '
    $urlOk   = ((& git -C $dir config --get remote.origin.url 2>$null) -like '*civiccast-native*')
    if ($urlOk -and "$head".Trim() -eq $DirectiveBranch -and
        ("$refspec" -like "*$DirectiveBranch*" -or "$refspec" -like '*refs/heads/`**')) { $dirStale = $false }
    if ($dirStale) { Say "existing $dir is from another mission (head='$head' refspec='$refspec') -- re-cloning" }
  }
  if ($dirStale) {
    Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    Say 'cloning directives branch (single-branch)'
    & git clone --quiet --single-branch --branch $DirectiveBranch $RepoUrl $dir
    if ($LASTEXITCODE -ne 0) { Write-Host "LOOP FAILED: could not clone $DirectiveBranch into $dir"; exit 4 }
  }
  # FETCH_HEAD, never origin/<branch>: correct in a single-branch clone whatever
  # remote-tracking refs happen to exist.
  & git -C $dir fetch --quiet origin $DirectiveBranch
  if ($LASTEXITCODE -ne 0) { Write-Host "LOOP FAILED: could not fetch $DirectiveBranch in $dir"; exit 4 }
  & git -C $dir reset --quiet --hard FETCH_HEAD
  Say "directives clone on $DirectiveBranch @ $((& git -C $dir rev-parse --short HEAD))"

  # --- full repo clone --------------------------------------------------------
  if (-not (Test-Path (Join-Path $repo '.git'))) {
    Say 'cloning full repo (all branches -- the tester branch lives here)'
    Remove-Item $repo -Recurse -Force -ErrorAction SilentlyContinue
    & git clone --quiet $RepoUrl $repo
    if ($LASTEXITCODE -ne 0) { Write-Host "LOOP FAILED: could not clone the full repo into $repo"; exit 5 }
  }
  # A leftover clone may carry a NARROW refspec (single-branch). Force the full
  # one -- set, not add -- so origin/main and every other branch resolve.
  & git -C $repo config remote.origin.url $RepoUrl
  & git -C $repo config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  & git -C $repo fetch --quiet --prune origin
  if ($LASTEXITCODE -ne 0) { Write-Host "LOOP FAILED: could not fetch origin in $repo"; exit 5 }
  & git -C $repo config user.name  "soak-tester-$env:COMPUTERNAME"
  & git -C $repo config user.email 'soak-tester@civiccast.invalid'

  $checkedOut = $false
  if (& git -C $repo ls-remote --heads origin $TesterBranch) {
    & git -C $repo fetch --quiet origin $TesterBranch
    if ($LASTEXITCODE -eq 0) {
      & git -C $repo checkout --quiet -B $TesterBranch FETCH_HEAD
      if ($LASTEXITCODE -eq 0) { $checkedOut = $true; Say 'tester branch resumed from its remote head' }
    }
  }
  if (-not $checkedOut) {
    & git -C $repo rev-parse --verify --quiet origin/main *>$null
    if ($LASTEXITCODE -eq 0) {
      & git -C $repo checkout --quiet -B $TesterBranch origin/main
      if ($LASTEXITCODE -eq 0) { $checkedOut = $true }
    }
  }
  if (-not $checkedOut) {
    Say 'origin/main did not resolve -- falling back to an explicit fetch of main'
    & git -C $repo fetch --quiet origin main
    if ($LASTEXITCODE -eq 0) {
      & git -C $repo checkout --quiet -B $TesterBranch FETCH_HEAD
      if ($LASTEXITCODE -eq 0) { $checkedOut = $true }
    }
  }
  if (-not $checkedOut) {
    Write-Host "LOOP FAILED: could not create or check out $TesterBranch in $repo (neither its remote head, origin/main, nor an explicit fetch of main resolved)."
    exit 5
  }
  Set-Content (Join-Path $Root 'state\mission.txt') -Value $Mission -Encoding ascii
  Say "tester branch checked out: $TesterBranch @ $((& git -C $repo rev-parse --short HEAD))"
}

# ------------------------------------------------------------- 5. loop scripts
$pollScript = @'
# CivicCastSoak-Poll -- fetch directives, detect pointer change, EXECUTE new autoruns.
$ErrorActionPreference = 'Continue'
$root='C:\CivicCastSoak'; $d="$root\directives"; $repo="$root\repo"
$branch='soak8-e1acfe6-directives'; $mission='soak8-e1acfe6'
$br="tester/soak8-e1acfe6-$env:COMPUTERNAME"
$repoUrl='https://github.com/scottconverse/civiccast-native.git'
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
# The directives clone may be a leftover from ANOTHER mission whose refspec only
# knows its own branch -- re-clone rather than fetch into something that can never
# resolve this branch. Then always reset to FETCH_HEAD, never origin/<branch>.
$dirStale = $true
if (Test-Path "$d\.git") {
  $head    = (git -C $d rev-parse --abbrev-ref HEAD 2>$null)
  $refspec = (git -C $d config --get-all remote.origin.fetch 2>$null) -join ' '
  if ("$head".Trim() -eq $branch -and ("$refspec" -like "*$branch*" -or "$refspec" -like '*refs/heads/`**')) { $dirStale = $false }
}
if ($dirStale) {
  Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
  git clone --quiet --single-branch --branch $branch $repoUrl $d | Out-Null
}
git -C $d fetch --quiet origin $branch
if ($LASTEXITCODE -ne 0) { Add-Content "$root\reports\poll.log" "$stamp FETCH FAILED for $branch"; exit 1 }
git -C $d reset --quiet --hard FETCH_HEAD
$cur=''
$m = Select-String -Path "$d\LATEST-TEST-DIRECTIVE.md" -Pattern '^Current:\s*(\S+)' -ErrorAction SilentlyContinue
if ($m) { $cur = $m.Matches[0].Groups[1].Value }
$seenFile="$root\state\last-directive.txt"
$seen = $(if (Test-Path $seenFile) { (Get-Content $seenFile -Raw) } else { '' })
Add-Content "$root\reports\poll.log" "$stamp current=$cur seen=$($seen.Trim())"
if ($cur -and ($cur.Trim() -ne $seen.Trim())) {
  Set-Content $seenFile -Value $cur -Encoding ascii
  Set-Content "$root\state\NEW-DIRECTIVE.txt" -Value "$cur`n$stamp" -Encoding ascii
  $n = ($cur -replace '[^0-9]','')
  if (-not $n) { $n = '0' }
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  Set-Content "$repo\soak\AUTO-ACK-$n.md" -Value "# AUTO-ACK $n`n- Mission: $mission`n- Hostname: $env:COMPUTERNAME`n- UTC: $stamp`n- Received: $cur (scheduled poll task; autoruns execute automatically)" -Encoding utf8
  git -C $repo add "soak/AUTO-ACK-$n.md"
  git -C $repo commit --quiet -m "test: auto-ack $cur $mission $stamp"
  git -C $repo push --quiet origin $br 2>&1 | Out-Null
}
# --- executor: run each AUTORUN-*.ps1 from the directives branch exactly once ---
$ranDir="$root\state\autorun-done"
New-Item -Force -ItemType Directory $ranDir | Out-Null
# Safety valve: CIVICCAST_SOAK_NO_AUTORUN=1 exercises the whole loop (fetch, ack,
# push, heartbeat) WITHOUT executing mission autoruns -- how the coordinator tests
# this loop on a machine that must not be installed onto.
$noAutorun = ($env:CIVICCAST_SOAK_NO_AUTORUN -eq '1')
if ($noAutorun) { Add-Content "$root\reports\poll.log" "$stamp CIVICCAST_SOAK_NO_AUTORUN=1 -- autorun execution suppressed" }
Get-ChildItem "$d\soak\autorun" -Filter 'AUTORUN-*.ps1' -ErrorAction SilentlyContinue |
  Where-Object { -not $noAutorun } | Sort-Object Name | ForEach-Object {
  $mark = Join-Path $ranDir ($_.Name + '.done')
  if (-not (Test-Path $mark)) {
    Set-Content $mark -Value $stamp -Encoding ascii
    $log = "$root\reports\$($_.BaseName)-$stamp.log"
    Add-Content "$root\reports\poll.log" "$stamp EXECUTING $($_.Name) -> $log"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $_.FullName *> $log
    Add-Content "$root\reports\poll.log" "$stamp FINISHED $($_.Name) exit=$LASTEXITCODE"
    try {
      New-Item -Force -ItemType Directory "$repo\soak\autorun-logs" | Out-Null
      Copy-Item $log "$repo\soak\autorun-logs\" -Force
      git -C $repo add soak/autorun-logs
      git -C $repo commit --quiet -m "test: autorun log $($_.BaseName) $stamp soak8-e1acfe6"
      git -C $repo push --quiet origin $br 2>&1 | Out-Null
    } catch { }
  }
}
# --- recurring step: egress/TSDuck verify, once the soak is running ---
if ((Test-Path "$d\soak\autorun\AUTORUN-3.ps1") -and -not $noAutorun) {
  if (Test-Path "$root\state\soak-started") {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$d\soak\autorun\AUTORUN-3.ps1" *> "$root\reports\egress-$stamp.log"
  }
}
'@

$hbScript = @'
# CivicCastSoak-Heartbeat -- health + resources + per-channel engine/egress state.
$ErrorActionPreference = 'Continue'
$root='C:\CivicCastSoak'; $repo="$root\repo"; $mission='soak8-e1acfe6'
$br="tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$base='http://127.0.0.1:8000'
$health=$null
try { $health = Invoke-RestMethod -Uri "$base/health" -TimeoutSec 10 } catch { $health = @{ status='unreachable'; error="$($_.Exception.Message)" } }
$svc = Get-Service -Name 'CivicCastSupervisor' -ErrorAction SilentlyContinue
$procs = Get-Process -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessName -match '^(python|pythonw|uvicorn|ffmpeg|gst-launch-1\.0|civiccast|CivicCast)' } |
  Select-Object ProcessName, Id, @{n='rss_mb';e={[math]::Round($_.WorkingSet64/1MB)}}, @{n='cpu_s';e={[math]::Round($_.CPU,1)}}
$cpu = 0
try { $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples[0].CookedValue } catch { }
$os = Get-CimInstance Win32_OperatingSystem
$disk = Get-PSDrive C
# --- per-channel egress + engine state (needs the staff token) ---
$channels = @('public','education','government')
$egress = @()
$tokenFile = "$root\state\token"
$tok = $(if (Test-Path $tokenFile) { (Get-Content $tokenFile -Raw).Trim() } else { '' })
if ($tok) {
  $hdr = @{ Authorization = "Bearer $tok" }
  foreach ($c in $channels) {
    $row = [ordered]@{ channel_id=$c; state=$null; engine=$null; last_error=$null; sink_connected=$null; worker_processes=$null; error=$null }
    try {
      $st = Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$c/state" -Headers $hdr -TimeoutSec 15
      $row.state = $st.state
      $row.last_error = $st.last_error
      if ($st.PSObject.Properties.Name -contains 'engine') { $row.engine = $st.engine }
    } catch { $row.error = "state: $($_.Exception.Message)" }
    try {
      $hl = @(Invoke-RestMethod -Uri "$base/api/staff/egress/channels/$c/health?limit=1" -Headers $hdr -TimeoutSec 15)
      if ($hl.Count -gt 0) {
        $row.sink_connected = $hl[0].sink_connected
        if (-not $row.engine -and ($hl[0].PSObject.Properties.Name -contains 'engine')) { $row.engine = $hl[0].engine }
        if (-not $row.state) { $row.state = $hl[0].state }
      }
    } catch { $row.error = "$($row.error); health: $($_.Exception.Message)" }
    $egress += $row
  }
}
# Which engine is REALLY running, independent of what the API says.
$gst = @(Get-Process -Name 'gst-launch-1.0' -ErrorAction SilentlyContinue).Count
$ff  = @(Get-Process -Name 'ffmpeg' -ErrorAction SilentlyContinue).Count
$engineObserved = [ordered]@{ gst_launch_processes=$gst; ffmpeg_processes=$ff
  inferred = $(if ($gst -gt 0 -and $ff -eq 0) { 'gstreamer' } elseif ($ff -gt 0 -and $gst -eq 0) { 'ffmpeg-fallback' } elseif ($gst -gt 0 -and $ff -gt 0) { 'mixed' } else { 'none-running' }) }
$hb = [ordered]@{
  schema='civiccast-native-fleet-heartbeat-v1'; mission=$mission; hostname=$env:COMPUTERNAME; utc=$stamp
  health=$health
  db_revision=$(if ($health -and ($health.PSObject.Properties.Name -contains 'db_revision')) { $health.db_revision } else { $null })
  service=$(if($svc){$svc.Status.ToString()}else{'not-registered'})
  cpu_pct=[math]::Round($cpu,1)
  mem_free_mb=[math]::Round($os.FreePhysicalMemory/1KB)
  disk_free_gb=[math]::Round($disk.Free/1GB,1)
  uptime_min=[math]::Round(((Get-Date)-$os.LastBootUpTime).TotalMinutes)
  processes=@($procs)
  engine_observed=$engineObserved
  egress_channels=@($egress)
  soak_started=$(Test-Path "$root\state\soak-started")
}
$file="$root\reports\heartbeats\heartbeat-$stamp.json"
$hb | ConvertTo-Json -Depth 8 | Set-Content $file -Encoding utf8
New-Item -Force -ItemType Directory "$repo\soak\heartbeats" | Out-Null
Copy-Item $file "$repo\soak\heartbeats\" -Force
git -C $repo add soak/heartbeats
git -C $repo commit --quiet -m "test: soak heartbeat $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
'@

$bootScript = @'
# CivicCastSoak-Boot -- at logon: record the boot, then heartbeat immediately.
$ErrorActionPreference = 'Continue'
$root='C:\CivicCastSoak'; $repo="$root\repo"
$br="tester/soak8-e1acfe6-$env:COMPUTERNAME"
Start-Sleep -Seconds 120
$stamp=(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Add-Content "$repo\soak\BOOTS.md" "- $stamp boot marker (machine restarted; soak8-e1acfe6 tasks resumed)"
git -C $repo add soak/BOOTS.md
git -C $repo commit --quiet -m "test: boot marker $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
& "$root\bin\heartbeat.ps1"
'@

$binDir = Join-Path $Root 'bin'
if (-not $DryRun) {
  Set-Content (Join-Path $binDir 'poll-directives.ps1') -Value ($pollScript -replace [regex]::Escape("`$root='C:\CivicCastSoak'"), ("`$root='" + $Root + "'")) -Encoding ascii
  Set-Content (Join-Path $binDir 'heartbeat.ps1')       -Value ($hbScript   -replace [regex]::Escape("`$root='C:\CivicCastSoak'"), ("`$root='" + $Root + "'")) -Encoding ascii
  Set-Content (Join-Path $binDir 'boot-marker.ps1')     -Value ($bootScript -replace [regex]::Escape("`$root='C:\CivicCastSoak'"), ("`$root='" + $Root + "'")) -Encoding ascii
}
Say 'loop scripts written (poll-directives.ps1, heartbeat.ps1, boot-marker.ps1)'

# every emitted script must parse before we register a task around it
foreach ($f in 'poll-directives.ps1','heartbeat.ps1','boot-marker.ps1') {
  $path = Join-Path $binDir $f
  if ($DryRun) {
    $src = $(switch ($f) { 'poll-directives.ps1' { $pollScript } 'heartbeat.ps1' { $hbScript } 'boot-marker.ps1' { $bootScript } })
    $errs = $null; $toks = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($src, [ref]$toks, [ref]$errs)
  } else {
    $errs = $null; $toks = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$toks, [ref]$errs)
  }
  if ($errs -and $errs.Count -gt 0) {
    Write-Host "LOOP FAILED: generated script $f does not parse: $($errs[0].Message)"
    exit 6
  }
  Say "  parse OK: $f"
}

# ---------------------------------------------------------------- 6. the tasks
$ps = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$taskSpecs = @(
  @{ n='CivicCastSoak-Poll';      f='poll-directives.ps1'; every=10 },
  @{ n='CivicCastSoak-Heartbeat'; f='heartbeat.ps1';       every=30 },
  @{ n='CivicCastSoak-Boot';      f='boot-marker.ps1';     every=0  }
)
if ($SkipTasks) { Say 'SkipTasks: not registering scheduled tasks (test mode)' }
if (-not $DryRun -and -not $SkipTasks) {
  $pr = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
  $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
           -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew
  foreach ($t in $taskSpecs) {
    if ($t.every -gt 0) {
      $tr = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
              -RepetitionInterval (New-TimeSpan -Minutes $t.every) -RepetitionDuration (New-TimeSpan -Days 60)
    } else {
      $tr = New-ScheduledTaskTrigger -AtLogOn
    }
    $a = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File $binDir\$($t.f)"
    Unregister-ScheduledTask -TaskName $t.n -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $t.n -Action $a -Trigger $tr -Principal $pr -Settings $set | Out-Null
    Say "  registered $($t.n)"
  }
  Get-ScheduledTask -TaskName 'CivicCastSoak-*' | Select-Object TaskName, State | Format-Table | Out-String | Write-Host
} else {
  foreach ($t in $taskSpecs) { Say "  [dry-run] would register $($t.n) (every $($t.every) min)" }
}

# --------------------------------------------------- 7. PROVE the loop, or fail
if ($DryRun) {
  Write-Host 'DRY RUN COMPLETE -- nothing was installed. Re-run without -DryRun on the tester box.'
  exit 0
}

Say 'proving the loop: running Poll and Heartbeat once, then watching the remote branch'
if ($SkipTasks) {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$binDir\poll-directives.ps1"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$binDir\heartbeat.ps1"
} else {
  Start-ScheduledTask -TaskName 'CivicCastSoak-Poll'
  Start-Sleep -Seconds 15
  Start-ScheduledTask -TaskName 'CivicCastSoak-Heartbeat'
}

$deadline = (Get-Date).AddMinutes(3)
$sawAck = $false; $sawHb = $false
while ((Get-Date) -lt $deadline -and (-not ($sawAck -and $sawHb))) {
  Start-Sleep -Seconds 15
  # Explicit fetch + FETCH_HEAD: a remote-tracking ref may not exist yet for a
  # branch this clone has never seen.
  & git -C $repo fetch --quiet origin $TesterBranch 2>&1 | Out-Null
  if ($LASTEXITCODE -eq 0) {
    $names = @(& git -C $repo ls-tree -r --name-only FETCH_HEAD 2>$null)
    if ($names -contains 'soak/AUTO-ACK-1.md') { $sawAck = $true }
    if ($names | Where-Object { $_ -like 'soak/heartbeats/heartbeat-*.json' }) { $sawHb = $true }
  }
  Say "  watching remote: ack=$sawAck heartbeat=$sawHb"
}

if ($sawAck -and $sawHb) {
  Write-Host ''
  Write-Host "LOOP PROVEN"
  Write-Host "  branch:     $TesterBranch"
  Write-Host "  ack:        soak/AUTO-ACK-1.md"
  Write-Host "  heartbeat:  soak/heartbeats/heartbeat-*.json"
  Write-Host "  poll:       every 10 min (reads directives, EXECUTES new AUTORUN-*.ps1)"
  Write-Host "  heartbeat:  every 30 min"
  Write-Host "The mission now runs itself. Nothing further is required from you."
  exit 0
}

$reason = @()
if (-not $sawAck) { $reason += 'soak/AUTO-ACK-1.md never appeared on the remote tester branch (poll task did not push)' }
if (-not $sawHb)  { $reason += 'no soak/heartbeats/heartbeat-*.json on the remote tester branch (heartbeat task did not push)' }
$remoteProbe = ''
try { $remoteProbe = (& git -C $repo ls-remote --heads origin $TesterBranch) -join ' ' } catch { $remoteProbe = "ls-remote failed: $($_.Exception.Message)" }
$pollTail = @(Get-Content "$Root\reports\poll.log" -Tail 10 -ErrorAction SilentlyContinue)
$taskInfo = (Get-ScheduledTask -TaskName 'CivicCastSoak-*' -ErrorAction SilentlyContinue | Get-ScheduledTaskInfo |
  Select-Object TaskName, LastRunTime, LastTaskResult | Format-Table | Out-String)

# Push the failure report ourselves -- a human relaying it is exactly what this
# mission exists to avoid. Best-effort: if the push is what's broken, the console
# output above is still the record.
try {
  New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
  $rep = @("# LOOP FAILED -- $Mission bootstrap", "", "- Hostname: $env:COMPUTERNAME", "- UTC: $(Stamp)",
           "- Bootstrap: $PSCommandPath", "") + @($reason | ForEach-Object { "- reason: $_" }) +
         @("", "## remote branch probe", '```', "$remoteProbe", '```',
           "", "## poll log tail", '```') + $pollTail + @('```', "", "## scheduled tasks", '```', $taskInfo, '```')
  Set-Content "$repo\soak\LOOP-FAILED.md" -Value ($rep -join "`n") -Encoding utf8
  & git -C $repo add soak/LOOP-FAILED.md
  & git -C $repo commit --quiet -m "test: LOOP FAILED report $(Stamp) $Mission"
  & git -C $repo push --quiet origin $TesterBranch 2>&1 | Out-Null
} catch { }

Write-Host ''
Write-Host 'LOOP FAILED'
foreach ($r in $reason) { Write-Host "  reason: $r" }
Write-Host "  remote branch probe: $(if($remoteProbe){$remoteProbe}else{'(branch does not exist on origin)'})"
Write-Host "  poll log tail:"
$pollTail | ForEach-Object { Write-Host "    $_" }
Write-Host "  last task results:"
Write-Host $taskInfo
Write-Host "  MOST LIKELY CAUSE: 'git push' has no stored GitHub credential for this user."
Write-Host "  Fix: run once, interactively, as the SAME user --"
Write-Host "    git -C $repo push -u origin $TesterBranch"
Write-Host "  complete the GitHub sign-in it asks for, then re-run this bootstrap."
exit 7

