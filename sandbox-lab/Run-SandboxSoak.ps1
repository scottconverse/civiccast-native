# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Run-SandboxSoak.ps1 -- host orchestrator for the LOCAL Windows Sandbox
# soak lane. Finds bugs on HALO in ~15 SOAK minutes instead of on the tester
# box in hours, by driving a real silent install + station start +
# sample-content playout inside a disposable Windows Sandbox VM, using a
# kit already verified on disk (no download here -- see -KitRoot).
#
# This lane is deliberately separate from sandbox-lab/Run-GateA.ps1 (the
# full station-acceptance release gate): Gate A proves release-candidate
# readiness end to end (dirty lane, download-only lane, cross-version
# upgrade, 20+ minute soak) and is the thing that actually gates a release.
# This lane is a FAST, LOCAL pre-check -- same install/health/channel-start
# code paths (reused from In-Sandbox-Report.ps1 and the soak8 AUTORUN
# scripts, see In-Sandbox-Soak.ps1's own header), much shorter default
# duration, judged by the same SoakVerdict.ps1 logic Test-SoakVerdict.ps1
# unit-tests.
#
# -Minutes is SOAK minutes, measured inside the sandbox from
# soak_start_utc (health OK + all 3 channels configured/started + at least
# one confirmed ON_AIR) -- NOT wall-clock minutes from launch. Install alone
# measured 13m05s on the first real run against kit 609273d (05:02:30 ->
# 05:15:35, exit 0); a wall-clock-from-launch deadline would have declared
# that install a stall before it ever got a chance to finish.
#
# Usage:
#   pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> [-Minutes 15] [-KitRoot C:\CivicCastTester\kit-safe]
#   pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> -DryRun
#
# Exit codes: 0 PASS, 1 FAIL, 2 harness/setup error (bad kit, missing
# prerequisite), 3 Windows Sandbox already running (busy guard), 4 stall
# (a phase bound was exceeded -- sandbox killed, evidence preserved), 5 a
# stall fired but the matching sandbox process(es) were NOT launched by
# this run (StartTime predates our own launch) -- refuses to touch them,
# evidence preserved, nothing killed.
param(
    [Parameter(Mandatory = $true)]
    [string]$Sha,

    [int]$Minutes = 15,

    [string]$KitRoot = 'C:\CivicCastTester\kit-safe',

    [string]$Root = $PSScriptRoot,

    # Phase bounds (minutes). Keep these in sync with In-Sandbox-Soak.ps1's
    # own $InstallBoundMinutes/$HealthBoundMinutes -- the in-sandbox
    # watchdog is a second, independent backstop using the same numbers,
    # not a substitute for this host-side guard.
    [int]$InstallBoundMinutes = 20,
    [int]$HealthBoundMinutes = 10,

    # Minutes with no new rollup file under output\rollups\ once the soak
    # clock has started (SOAK-START.json present) before this script
    # declares a stall. Rollups land every 3 minutes inside the sandbox, so
    # 6 minutes is two missed checkpoints.
    [int]$RollupStallMinutes = 6,

    # Generic backstop liveness bound (minutes), mirrors Host-Launch-
    # Sandbox-Test.ps1's own -QuietShareMinutes: the newest mtime among
    # soak-log.txt / summary.json / _SHIPPER-HEARTBEAT.txt in the output
    # folder must advance at least this often, in EVERY phase, independent
    # of the phase-specific bounds above. Catches a hang the phase bounds
    # don't yet have a marker for (e.g. mid first-admin/asset-upload/
    # schedule/commit/channel-start, between PHASE-HEALTHY.json and
    # SOAK-START.json).
    [int]$QuietMinutes = 15,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[Run-SandboxSoak] $Message" -ForegroundColor Cyan
}

function Exit-HarnessError {
    <#
      NEVER use Write-Error here: with $ErrorActionPreference = 'Stop' (set
      above), Write-Error's non-terminating error is PROMOTED to terminating
      and thrown immediately -- there is no try/catch around these call
      sites, so the throw unwinds past the `exit $Code` statement entirely
      and the process actually exits 1 (PowerShell's default for an
      unhandled terminating error) regardless of what $Code says. Measured:
      every Exit-HarnessError call exited 1 in both PS 5.1 and PS 7 before
      this fix, never the documented 2. [Console]::Error.WriteLine is a
      plain write -- it cannot become a terminating error under any
      $ErrorActionPreference.
    #>
    param([string]$Message, [int]$Code = 2)
    [Console]::Error.WriteLine("[Run-SandboxSoak] ERROR: $Message")
    exit $Code
}

if (-not $Root) { $Root = (Get-Location).Path }
Write-Step "Root: $Root, Sha: $Sha, Minutes: $Minutes (SOAK minutes), KitRoot: $KitRoot, DryRun: $($DryRun.IsPresent)"

# --------------------------------------------------------------------------
# 1a. Refuse if Windows Sandbox is already running (Gate A owns it, and
#     Codex uses it too). Process name list is the PROVEN one from
#     Host-Launch-Sandbox-Test.ps1:183-188 -- NOT the ad hoc
#     ('WindowsSandbox','WindowsSandboxClient') list this script started
#     with, which is exactly why the first real run's stall-kill left
#     WindowsSandboxRemoteSession/WindowsSandboxServer/vmmemWindowsSandbox
#     running: those three names were never in the kill target at all.
#     WindowsSandbox.exe itself is excluded from the BUSY-detection list on
#     purpose (Host-Launch-Sandbox-Test.ps1's own note: it is a launcher
#     stub that starts the VM and exits almost immediately, so its absence
#     proves nothing about whether a session is live) but IS included in
#     the kill target list below for thoroughness, along with vmwp (the
#     VM worker process; Host-Launch-Sandbox-Test.ps1:501 checks it
#     alongside WindowsSandboxRemoteSession/WindowsSandboxServer as its own
#     "is the VM actually alive" signal).
# --------------------------------------------------------------------------
$BusyGuardProcNames = @('WindowsSandboxClient', 'WindowsSandboxRemoteSession', 'WindowsSandboxServer', 'vmmemWindowsSandbox')
$KillTargetProcNames = @('WindowsSandbox', 'WindowsSandboxClient', 'WindowsSandboxRemoteSession', 'WindowsSandboxServer', 'vmmemWindowsSandbox', 'vmwp')

$existing = @(Get-Process -Name $BusyGuardProcNames -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
    Write-Host "[Run-SandboxSoak] Windows Sandbox is already running -- refusing to start (Gate A / another agent may own it):" -ForegroundColor Yellow
    foreach ($p in $existing) {
        $cmdLine = $null
        try {
            $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.Id)" -ErrorAction SilentlyContinue
            if ($cim) { $cmdLine = $cim.CommandLine }
        } catch { }
        Write-Host ("  pid={0} name={1} owner_cmdline={2}" -f $p.Id, $p.ProcessName, $(if ($cmdLine) { $cmdLine } else { '<unavailable>' }))
    }
    exit 3
}
Write-Step "Windows Sandbox is not currently running -- proceeding."

# --------------------------------------------------------------------------
# 1b. Verify the kit: $KitRoot\$Sha must exist, carry SHA256SUMS.txt, and
#     every listed file must hash-match (Get-FileHash, since this is
#     PowerShell, not `sha256sum -c` -- same semantics: `<hex> *<relpath>`
#     per line, hex must match, every listed file must be present).
# --------------------------------------------------------------------------
$kitDir = Join-Path $KitRoot $Sha
if (-not (Test-Path $kitDir)) {
    Exit-HarnessError "kit directory does not exist: $kitDir"
}
$sumsPath = Join-Path $kitDir 'SHA256SUMS.txt'
if (-not (Test-Path $sumsPath)) {
    Exit-HarnessError "SHA256SUMS.txt missing at $sumsPath"
}

Write-Step "Verifying kit against $sumsPath ..."
$sumLines = Get-Content -Path $sumsPath -Encoding UTF8 | Where-Object { $_.Trim().Length -gt 0 }
$verifyFailures = @()
$verifiedCount = 0
foreach ($line in $sumLines) {
    # Format: <64-hex-char hash> *<relative path>  (binary-mode sha256sum).
    $m = [regex]::Match($line, '^([0-9a-fA-F]{64})\s+\*?(.+)$')
    if (-not $m.Success) {
        $verifyFailures += "unparsable SHA256SUMS.txt line: $line"
        continue
    }
    $expectedHash = $m.Groups[1].Value.ToLowerInvariant()
    $relPath = $m.Groups[2].Value
    $filePath = Join-Path $kitDir $relPath
    if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
        $verifyFailures += "listed file missing: $relPath"
        continue
    }
    $actualHash = (Get-FileHash -LiteralPath $filePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        $verifyFailures += "hash MISMATCH for $relPath (expected $expectedHash, got $actualHash)"
        continue
    }
    $verifiedCount++
}
Write-Step "Kit verification: $verifiedCount file(s) hash-matched, $($verifyFailures.Count) failure(s)."
if ($verifyFailures.Count -gt 0) {
    foreach ($f in $verifyFailures) { Write-Warning $f }
    Exit-HarnessError "kit verification failed against $sumsPath ($($verifyFailures.Count) failure(s) -- see warnings above)"
}

$installerExe = Get-ChildItem -Path $kitDir -Filter '*setup.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installerExe) {
    Exit-HarnessError "no *setup.exe found directly under $kitDir (bad kit layout)"
}
$samplesDir = Join-Path $kitDir 'samples'
$sampleCount = @(Get-ChildItem -Path $samplesDir -Filter '*.mp4' -File -ErrorAction SilentlyContinue).Count
Write-Step "Kit layout: installer=$($installerExe.Name), samples\*.mp4 count=$sampleCount"
if ($sampleCount -lt 1) {
    Exit-HarnessError "no sample videos found under $samplesDir -- this kit cannot drive the soak's sample-content playout"
}

# --------------------------------------------------------------------------
# 2. Render the .wsb from the template. Output folder is timestamped +
#    short-sha-scoped so successive runs never collide or silently overwrite
#    each other's evidence.
# --------------------------------------------------------------------------
# Deliberately NOT sandbox-lab\output\ -- that directory is Gate A's own
# (Host-Launch-Sandbox-Test.ps1 WIPES everything under it except .gitkeep at
# the start of every Gate A run). Sharing it here would let a Gate A run
# started while this soak's evidence is still being written silently delete
# that evidence out from under it. This lane gets its own per-run root.
$shortSha = $Sha.Substring(0, [Math]::Min(7, $Sha.Length))
$utcStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
$runName = "soak-$shortSha-$utcStamp"
$outputDir = Join-Path $Root "soak-output\$runName"
$scriptsDir = Join-Path $Root 'scripts'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null

$templatePath = Join-Path $Root 'CivicCastSandboxSoak.wsb.template'
if (-not (Test-Path $templatePath)) {
    Exit-HarnessError "template not found: $templatePath"
}
$template = Get-Content -Path $templatePath -Raw -Encoding UTF8
$rendered = $template `
    -replace [regex]::Escape('{{KIT_ROOT}}'), $kitDir `
    -replace [regex]::Escape('{{OUTPUT_DIR}}'), $outputDir `
    -replace [regex]::Escape('{{SCRIPTS_DIR}}'), $scriptsDir `
    -replace [regex]::Escape('{{MINUTES}}'), "$Minutes"

$wsbPath = Join-Path $Root "CivicCastSandboxSoak-$runName.wsb"
Set-Content -Path $wsbPath -Value $rendered -Encoding UTF8
Write-Step "Rendered $wsbPath"

$logonCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes $Minutes"
Write-Step "LogonCommand: $logonCommand"

# --------------------------------------------------------------------------
# 3. Parse-check both in-sandbox scripts before ever launching anything --
#    a syntax error inside the sandbox is otherwise invisible until the
#    watchdog times out much later.
# --------------------------------------------------------------------------
function Test-ScriptParses {
    param([string]$Path)
    $errors = $null
    $tokens = $null
    if (-not (Test-Path $Path)) {
        return [pscustomobject]@{ path = $Path; ok = $false; errors = @("file not found: $Path") }
    }
    $null = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if ($errors -and $errors.Count -gt 0) {
        return [pscustomobject]@{ path = $Path; ok = $false; errors = @($errors | ForEach-Object { "$($_.Message) at line $($_.Extent.StartLineNumber)" }) }
    }
    return [pscustomobject]@{ path = $Path; ok = $true; errors = @() }
}

$scriptsToCheck = @(
    (Join-Path $scriptsDir 'In-Sandbox-Soak.ps1'),
    (Join-Path $scriptsDir 'SoakVerdict.ps1')
)
$parseResults = @($scriptsToCheck | ForEach-Object { Test-ScriptParses -Path $_ })
$parseOk = -not @($parseResults | Where-Object { -not $_.ok }).Count
foreach ($r in $parseResults) {
    if ($r.ok) {
        Write-Step "Parse OK: $($r.path)"
    } else {
        Write-Warning "Parse FAILED: $($r.path)"
        foreach ($e in $r.errors) { Write-Warning "  $e" }
    }
}
if (-not $parseOk) {
    Exit-HarnessError "one or more in-sandbox scripts failed to parse -- see warnings above"
}

if ($DryRun) {
    Write-Step "DRY RUN complete. Kit verified ($verifiedCount files), .wsb rendered at $wsbPath, both in-sandbox scripts parse cleanly."
    Write-Step "Would launch: Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList `"$wsbPath`""
    Write-Step "Would poll for: $outputDir\VERDICT.txt (phase bounds: install=${InstallBoundMinutes}m, health=${HealthBoundMinutes}m after install, rollup-stall=${RollupStallMinutes}m once soak_start_utc is set, generic quiet-bound=${QuietMinutes}m throughout)"
    Write-Step "Output directory prepared at: $outputDir (empty -- no sandbox launched)"
    exit 0
}

# --------------------------------------------------------------------------
# 4. Kill helper -- used by every stall path below. Only ever touches
#    process(es) this run itself launched: WindowsSandboxRemoteSession and
#    WindowsSandboxServer are the two names in $KillTargetProcNames that
#    reliably carry a readable, non-system StartTime, so ownership is keyed
#    on THOSE (must both have StartTime >= our own launch time, minus a
#    small clock-skew buffer). vmmemWindowsSandbox and vmwp are
#    system-owned VM worker processes with no reliably readable StartTime
#    (measured directly on this box: vmmemWindowsSandbox reports an empty
#    StartTime) -- they are never checked for ownership themselves, only
#    killed/verified-gone AFTER the named two are confirmed ours, on the
#    understanding that they belong to whichever session's
#    RemoteSession/Server process they are currently paired with.
# --------------------------------------------------------------------------
function Invoke-SandboxKill {
    param([datetime]$LaunchTimeUtc, [string[]]$KillNames, [string]$OutputDir)

    $ownershipNames = @('WindowsSandboxRemoteSession', 'WindowsSandboxServer')
    $ownershipProcs = @(Get-Process -Name $ownershipNames -ErrorAction SilentlyContinue)

    if ($ownershipProcs.Count -gt 0) {
        $foreign = @($ownershipProcs | Where-Object {
            $st = $null
            try { $st = $_.StartTime.ToUniversalTime() } catch { $st = $null }
            (-not $st) -or ($st -lt $LaunchTimeUtc.AddSeconds(-5))
        })
        if ($foreign.Count -gt 0) {
            $lines = @(
                "foreign_sandbox_session_detected_utc=$((Get-Date).ToUniversalTime().ToString('o'))"
                "our_launch_utc=$($LaunchTimeUtc.ToString('o'))"
            )
            foreach ($f in $foreign) {
                $st = $null
                try { $st = $f.StartTime.ToUniversalTime().ToString('o') } catch { $st = '<unreadable>' }
                $lines += "  pid=$($f.Id) name=$($f.ProcessName) start_time_utc=$st -- predates our launch, NOT OURS, refusing to kill anything"
            }
            Set-Content -Path (Join-Path $OutputDir 'FOREIGN-SANDBOX-SESSION.txt') -Value ($lines -join "`n") -Encoding UTF8
            foreach ($l in $lines) { Write-Warning "[Run-SandboxSoak] $l" }
            return [pscustomobject]@{ ok = $false; foreign = $true; vmmem_gone = $null; remaining = @() }
        }
    }

    $procs = @(Get-Process -Name $KillNames -ErrorAction SilentlyContinue)
    $killed = @()
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.Id -Force -ErrorAction Stop
            $killed += "$($p.ProcessName)(pid=$($p.Id))"
        } catch {
            Write-Warning "[Run-SandboxSoak] failed to stop $($p.ProcessName) pid=$($p.Id): $_"
        }
    }
    Write-Step "Killed: $(if ($killed.Count -gt 0) { $killed -join ', ' } else { '(nothing matched)' })"

    $pollDeadline = (Get-Date).AddSeconds(60)
    $vmmemGone = $false
    while ((Get-Date) -lt $pollDeadline) {
        if (@(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -eq 0) { $vmmemGone = $true; break }
        Start-Sleep -Seconds 2
    }
    $remaining = @(Get-Process -Name $KillNames -ErrorAction SilentlyContinue)
    Write-Step "vmmemWindowsSandbox gone (polled up to 60s): $vmmemGone. Remaining sandbox process(es): $(if ($remaining.Count -gt 0) { ($remaining | ForEach-Object { "$($_.ProcessName)(pid=$($_.Id))" }) -join ', ' } else { 'none' })"
    return [pscustomobject]@{ ok = $true; foreign = $false; vmmem_gone = $vmmemGone; remaining = $remaining }
}

function Write-StallAndExit {
    param([string]$Reason, [datetime]$LaunchTimeUtc, [string]$OutputDir, [string[]]$KillNames)
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    $stallBody = "stall_detected_utc=$ts reason=$Reason"
    Set-Content -Path (Join-Path $OutputDir 'STALL.txt') -Value $stallBody -Encoding UTF8
    Write-Warning "[Run-SandboxSoak] STALL: $stallBody -- attempting to kill the sandbox."
    $killResult = Invoke-SandboxKill -LaunchTimeUtc $LaunchTimeUtc -KillNames $KillNames -OutputDir $OutputDir
    if ($killResult.foreign) {
        exit 5
    }
    exit 4
}

# --------------------------------------------------------------------------
# 5. Launch and wait for VERDICT.txt, enforcing separate phase deadlines
#    (installer bound from launch, station-healthy bound from install-done,
#    rollup-stall bound once the soak clock starts) PLUS a generic
#    quiet-liveness backstop that covers every phase, including the setup
#    phase between healthy and soak-start that has no dedicated bound of its
#    own (first-admin, asset upload, schedule/commit, channel config/start,
#    ON_AIR poll).
# --------------------------------------------------------------------------
$launchTimeUtc = (Get-Date).ToUniversalTime()
Write-Step "Launching Windows Sandbox ($wsbPath) at $($launchTimeUtc.ToString('o'))..."
Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList "`"$wsbPath`"" | Out-Null

$verdictTxtPath = Join-Path $outputDir 'VERDICT.txt'
$verdictJsonPath = Join-Path $outputDir 'VERDICT.json'
$rollupsDir = Join-Path $outputDir 'rollups'
$installDoneMarker = Join-Path $outputDir 'PHASE-INSTALL-DONE.json'
$healthyMarker = Join-Path $outputDir 'PHASE-HEALTHY.json'
$soakStartMarker = Join-Path $outputDir 'SOAK-START.json'

function Get-LatestLivenessUtc {
    <#
      Generic liveness signal: the newest mtime among the files the shipper
      mirrors out every ~15s, mirroring Host-Launch-Sandbox-Test.ps1's own
      _SHIPPER-HEARTBEAT.txt-driven quiet-share detector. Returns $null if
      none of the files exist yet (before the first shipper tick lands).
    #>
    param([string]$OutputDir)
    $candidates = @('soak-log.txt', 'summary.json', '_SHIPPER-HEARTBEAT.txt') | ForEach-Object { Join-Path $OutputDir $_ }
    $times = @($candidates | Where-Object { Test-Path $_ } | ForEach-Object { (Get-Item $_).LastWriteTimeUtc })
    if ($times.Count -eq 0) { return $null }
    return ($times | Sort-Object -Descending | Select-Object -First 1)
}

$phase = 'installing'
$installDeadlineUtc = $launchTimeUtc.AddMinutes($InstallBoundMinutes)
$healthDeadlineUtc = $null
$lastRollupCount = 0
$lastRollupProgressUtc = $null
$lastGenericProgressUtc = $launchTimeUtc

Write-Step "Waiting for VERDICT.txt. Phase bounds: install<=${InstallBoundMinutes}m (from launch), health<=${HealthBoundMinutes}m (from install-done), rollup-stall<=${RollupStallMinutes}m (once soak_start_utc is set), generic-quiet<=${QuietMinutes}m (every phase)."

while ($true) {
    if (Test-Path $verdictTxtPath) { break }

    $liveUtc = Get-LatestLivenessUtc -OutputDir $outputDir
    if ($liveUtc -and $liveUtc -gt $lastGenericProgressUtc) { $lastGenericProgressUtc = $liveUtc }
    $genericStalledMin = ((Get-Date).ToUniversalTime() - $lastGenericProgressUtc).TotalMinutes
    if ($genericStalledMin -ge $QuietMinutes) {
        Write-StallAndExit -Reason "no new soak-log.txt/summary.json/_SHIPPER-HEARTBEAT.txt mtime for >= ${QuietMinutes} minute(s) (generic quiet-liveness bound, phase=$phase)" -LaunchTimeUtc $launchTimeUtc -OutputDir $outputDir -KillNames $KillTargetProcNames
    }

    if ($phase -eq 'installing') {
        if (Test-Path $installDoneMarker) {
            $phase = 'awaiting-health'
            $healthDeadlineUtc = (Get-Item $installDoneMarker).LastWriteTimeUtc.AddMinutes($HealthBoundMinutes)
            Write-Step "phase -> awaiting-health (health bound: $($healthDeadlineUtc.ToString('o')))"
        } elseif ((Get-Date).ToUniversalTime() -gt $installDeadlineUtc) {
            Write-StallAndExit -Reason "installer bound (${InstallBoundMinutes}m from launch $($launchTimeUtc.ToString('o'))) exceeded -- PHASE-INSTALL-DONE.json never appeared" -LaunchTimeUtc $launchTimeUtc -OutputDir $outputDir -KillNames $KillTargetProcNames
        }
    } elseif ($phase -eq 'awaiting-health') {
        if (Test-Path $healthyMarker) {
            $phase = 'awaiting-soak-start'
            Write-Step "phase -> awaiting-soak-start (generic quiet-bound covers first-admin/assets/schedule/channel-start from here)"
        } elseif ((Get-Date).ToUniversalTime() -gt $healthDeadlineUtc) {
            Write-StallAndExit -Reason "station-healthy bound (${HealthBoundMinutes}m from install-done) exceeded -- PHASE-HEALTHY.json never appeared" -LaunchTimeUtc $launchTimeUtc -OutputDir $outputDir -KillNames $KillTargetProcNames
        }
    } elseif ($phase -eq 'awaiting-soak-start') {
        if (Test-Path $soakStartMarker) {
            $phase = 'running'
            $lastRollupProgressUtc = (Get-Date).ToUniversalTime()
            Write-Step "phase -> running (soak clock started; rollup-stall bound now armed at ${RollupStallMinutes}m)"
        }
    } elseif ($phase -eq 'running') {
        $rollupCount = 0
        if (Test-Path $rollupsDir) {
            $rollupCount = @(Get-ChildItem -Path $rollupsDir -Filter '*.json' -File -ErrorAction SilentlyContinue).Count
        }
        if ($rollupCount -gt $lastRollupCount) {
            $lastRollupCount = $rollupCount
            $lastRollupProgressUtc = (Get-Date).ToUniversalTime()
        }
        if ($lastRollupProgressUtc) {
            $rollupStalledMin = ((Get-Date).ToUniversalTime() - $lastRollupProgressUtc).TotalMinutes
            if ($rollupStalledMin -ge $RollupStallMinutes) {
                Write-StallAndExit -Reason "no new rollup file for >= ${RollupStallMinutes} minute(s) (rollup_count=$rollupCount)" -LaunchTimeUtc $launchTimeUtc -OutputDir $outputDir -KillNames $KillTargetProcNames
            }
        }
    }

    Start-Sleep -Seconds 15
}

Write-Step "VERDICT.txt found."
$verdictText = Get-Content -Path $verdictTxtPath -Raw
Write-Host ""
Write-Host "=== SANDBOX SOAK VERDICT ===" -ForegroundColor Cyan
Write-Host $verdictText
if (Test-Path $verdictJsonPath) {
    Write-Host "Full verdict: $verdictJsonPath"
}
Write-Host "Evidence: $outputDir"

# Sandbox tears itself down once the LogonCommand's script exits; give it a
# short grace window, then confirm.
Start-Sleep -Seconds 5
$stillRunning = @(Get-Process -Name $KillTargetProcNames -ErrorAction SilentlyContinue)
if ($stillRunning.Count -gt 0) {
    Write-Step "Sandbox process(es) still shutting down ($($stillRunning.Count)) -- not force-closing; a normal completion tears down on its own."
}

if ($verdictText -match 'verdict=PASS') {
    Write-Host "[Run-SandboxSoak] PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[Run-SandboxSoak] FAIL" -ForegroundColor Red
    exit 1
}
