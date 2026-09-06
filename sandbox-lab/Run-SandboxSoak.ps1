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
# prerequisite), 3 Windows Sandbox already running (busy guard), 4 stall (a
# phase bound was exceeded and this run's own recorded PID(s) were
# successfully stopped, evidence preserved), 5 a stall/quiet-share fired but
# ownership of the live sandbox process(es) could not be positively
# attributed to this run (no PIDs were ever recorded, none of them are
# still alive, or WindowsSandboxRemoteSession/WindowsSandboxServer are gone
# while vmmemWindowsSandbox is still alive -- ambiguous, fail closed) --
# nothing is killed, evidence preserved, 6 HARNESS_ERROR: the mapped output
# folder went quiet (no new soak-log.txt/summary.json/phase-marker mtime)
# while the in-sandbox shipper's own heartbeat kept advancing -- the guest
# is alive and the mirror channel is fine, so the wedge is somewhere this
# harness cannot diagnose from the host side alone; never reported as a
# product FAIL (mirrors Host-Launch-Sandbox-Test.ps1:175-178's
# HOST-QUIET-SHARE.txt contract) -- also used when the in-sandbox script
# itself determines its own setup could not guarantee full schedule
# coverage for -Minutes and reports verdict=HARNESS_ERROR in VERDICT.txt.
param(
    [Parameter(Mandatory = $true)]
    [string]$Sha,

    [int]$Minutes = 15,

    [string]$KitRoot = 'C:\CivicCastTester\kit-safe',

    # NOT defaulted to $PSScriptRoot here: Windows PowerShell 5.1 (not
    # pwsh/PS7) evaluates param-block default-value expressions with
    # $PSScriptRoot UNSET whenever the same param block also declares a
    # [Parameter(Mandatory=$true)] parameter (confirmed by direct repro --
    # a minimal script with a mandatory -Sha and `[string]$Root =
    # $PSScriptRoot` prints Root=[] under `powershell.exe -File ... -Sha x`,
    # while the identical script under `pwsh` and any script WITHOUT the
    # mandatory parameter both resolve Root correctly). $PSScriptRoot IS
    # reliably populated once the script BODY starts executing in both
    # engines, so this defaults empty here and is resolved just below.
    [string]$Root = '',

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

    # Minutes from launch within which at least one main-thread file
    # (soak-log.txt/summary.json/a phase marker) must exist. Windows
    # Sandbox itself measured 30-60s to boot before its LogonCommand script
    # even starts; this must clear that comfortably. Absence of a file
    # before this bound is NORMAL, never a stall (see HostLiveness.ps1's
    # header for the run-3 bug this fixes: absence was previously treated
    # as staleness from t=0, firing ~40s after launch).
    [int]$BootBoundMinutes = 5,

    # Round-6 item 1: passed through to In-Sandbox-Soak.ps1's own
    # -SeamlessReload switch, which exports
    # CIVICCAST_EGRESS_SEAMLESS_RELOAD=1 at machine scope before starting
    # the station service (PR #176, head 20f316f -- unmerged as of this
    # writing; the env var name/contract is taken as given from the
    # coordinator, not independently verified against this checkout).
    [switch]$SeamlessReload,

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

if (-not $Root) { $Root = $PSScriptRoot }
if (-not $Root) { $Root = (Get-Location).Path }
Write-Step "Root: $Root, Sha: $Sha, Minutes: $Minutes (SOAK minutes), KitRoot: $KitRoot, SeamlessReload: $($SeamlessReload.IsPresent), DryRun: $($DryRun.IsPresent)"

$hostLivenessPath = Join-Path $Root 'scripts\HostLiveness.ps1'
if (-not (Test-Path $hostLivenessPath)) {
    Exit-HarnessError "HostLiveness.ps1 not found at $hostLivenessPath"
}
. $hostLivenessPath

# --------------------------------------------------------------------------
# 1a. Refuse if Windows Sandbox is already running (Gate A owns it, and
#     Codex uses it too). Process name list is the PROVEN one from
#     Host-Launch-Sandbox-Test.ps1:183-188, used for BOTH the busy-detection
#     check below AND (later) to discover this run's OWN sandbox PIDs right
#     after launch -- it is never itself the kill target. WindowsSandbox.exe
#     (the launcher stub) and vmwp are deliberately excluded: Gate A's own
#     $SandboxProcessNames never includes either, and Stop-Process is never
#     called by bare image name anywhere in this script (see Invoke-
#     SandboxKill below, Host-Launch-Sandbox-Test.ps1:670-689's pattern) --
#     only by a PID this run itself recorded.
# --------------------------------------------------------------------------
$SandboxProcessNames = @('WindowsSandboxClient', 'WindowsSandboxRemoteSession', 'WindowsSandboxServer', 'vmmemWindowsSandbox')

# -DryRun never launches a sandbox, so it has nothing to be busy-guarded
# against -- exempting it lets a dry run validate config (kit hash, .wsb
# render, script parse-checks, the HttpClientHandler self-check) while a
# real run is in progress on this shared box, instead of refusing outright
# with no way to tell "config is broken" from "something else is busy".
if (-not $DryRun) {
    $existing = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
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
} else {
    Write-Step "DryRun: skipping the busy guard (a dry run never launches a sandbox, so there is nothing to guard)."
}

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
$seamlessReloadArg = $(if ($SeamlessReload) { '-SeamlessReload' } else { '' })
$template = Get-Content -Path $templatePath -Raw -Encoding UTF8
$rendered = $template `
    -replace [regex]::Escape('{{KIT_ROOT}}'), $kitDir `
    -replace [regex]::Escape('{{OUTPUT_DIR}}'), $outputDir `
    -replace [regex]::Escape('{{SCRIPTS_DIR}}'), $scriptsDir `
    -replace [regex]::Escape('{{MINUTES}}'), "$Minutes" `
    -replace [regex]::Escape('{{SEAMLESS_RELOAD_ARG}}'), $seamlessReloadArg

$wsbPath = Join-Path $Root "CivicCastSandboxSoak-$runName.wsb"
Set-Content -Path $wsbPath -Value $rendered -Encoding UTF8
Write-Step "Rendered $wsbPath"

$logonCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\CivicCastSoakScripts\In-Sandbox-Soak.ps1 -Minutes $Minutes $seamlessReloadArg"
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

# Round-8 finding 10: also parse-check RestartClassifier.ps1 (a new
# dependency In-Sandbox-Soak.ps1 dot-sources, shipped into the sandbox
# alongside SoakVerdict.ps1) and HostLiveness.ps1 (dot-sourced by THIS host
# script itself, near the top -- a syntax error there would already have
# surfaced at that dot-source before this block even runs, but checking it
# here too keeps one single place that answers "is everything in this
# deployment parseable" for both the guest-shipped and host-only files).
$scriptsToCheck = @(
    (Join-Path $scriptsDir 'In-Sandbox-Soak.ps1'),
    (Join-Path $scriptsDir 'SoakVerdict.ps1'),
    (Join-Path $scriptsDir 'RestartClassifier.ps1'),
    (Join-Path $scriptsDir 'HostLiveness.ps1')
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

# --------------------------------------------------------------------------
# 3b. System.Net.Http self-check (round-3 item a). Run 2 against kit 609273d
# failed every asset upload in 15ms with "status= body=" -- the real cause,
# buried in the transcript and dropped by the old catch block, was
# TerminatingError(New-Object): "Cannot find type
# [System.Net.Http.HttpClientHandler]: verify that the assembly containing
# this type is loaded." Windows PowerShell 5.1 on THIS host is the same
# engine Windows Sandbox's guest runs (not pwsh 7, which the AUTORUN-9m/9e
# scripts this lane ports from apparently ran under on the tester box, or
# they would have hit this too) -- so this check runs the exact
# `Add-Type -AssemblyName System.Net.Http; New-Object ...HttpClientHandler`
# sequence via `powershell.exe`, catching this whole class of error before
# ever launching a sandbox that would otherwise burn its full install+health
# time only to fail at the very first upload.
# --------------------------------------------------------------------------
Write-Step "Checking System.Net.Http.HttpClientHandler availability under Windows PowerShell 5.1 (the guest's engine)..."
$httpCheckScript = 'try { Add-Type -AssemblyName System.Net.Http; $h = New-Object System.Net.Http.HttpClientHandler; $h.Dispose(); Write-Output "OK" } catch { Write-Output "FAIL: $($_.Exception.GetType().Name): $($_.Exception.Message)" }'
$httpCheckOut = & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $httpCheckScript 2>&1
$httpCheckOutStr = ($httpCheckOut | Out-String).Trim()
if ($httpCheckOutStr -match '^OK') {
    Write-Step "System.Net.Http.HttpClientHandler self-check: OK"
} else {
    Exit-HarnessError "System.Net.Http.HttpClientHandler self-check FAILED under Windows PowerShell 5.1: $httpCheckOutStr -- every asset upload would fail this exact way inside the sandbox; not launching"
}

if ($DryRun) {
    Write-Step "DRY RUN complete. Kit verified ($verifiedCount files), .wsb rendered at $wsbPath, both in-sandbox scripts parse cleanly, HttpClientHandler self-check OK."
    Write-Step "Would launch: Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList `"$wsbPath`""
    Write-Step "Would poll for: $outputDir\VERDICT.txt (phase bounds: install=${InstallBoundMinutes}m, health=${HealthBoundMinutes}m after install, rollup-stall=${RollupStallMinutes}m once soak_start_utc is set, generic quiet-bound=${QuietMinutes}m throughout)"
    Write-Step "Output directory prepared at: $outputDir (empty -- no sandbox launched)"
    exit 0
}

# --------------------------------------------------------------------------
# 4. Kill helper. NEVER Stop-Process by bare image name (N3 / Gate A's own
#    discipline, Host-Launch-Sandbox-Test.ps1:670-689): only PIDs THIS RUN
#    recorded right after its own launch ($launchedPids, captured below)
#    are ever eligible. If none of those PIDs are still alive, or if
#    ownership cannot be positively attributed, NOTHING is touched -- fail
#    closed, exit 5.
# --------------------------------------------------------------------------
function Invoke-SandboxKill {
    param([int[]]$LaunchedPids, [string]$OutputDir)

    if ($LaunchedPids.Count -eq 0) {
        $msg = "no sandbox PID(s) were ever recorded for this run's own launch -- refusing to kill anything by name"
        Set-Content -Path (Join-Path $OutputDir 'FOREIGN-SANDBOX-SESSION.txt') -Value $msg -Encoding UTF8
        Write-Warning "[Run-SandboxSoak] $msg"
        return [pscustomobject]@{ ok = $false; foreign = $true; remaining = @() }
    }

    $currentNamed = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
    $ownProcs = @($currentNamed | Where-Object { $LaunchedPids -contains $_.Id })
    $ownedTypeNames = @($ownProcs | Select-Object -ExpandProperty ProcessName -Unique)
    $ownsRemoteSessionOrServer = ($ownedTypeNames -contains 'WindowsSandboxRemoteSession') -or ($ownedTypeNames -contains 'WindowsSandboxServer')
    $anyVmmemAlive = @(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -gt 0

    # N4: RemoteSession/Server (the only two names with a meaningful
    # per-session identity) are NOT among this run's own live, recorded
    # processes, but SOMETHING is still running under vmmemWindowsSandbox --
    # teardown already in progress, or a separate VM this run cannot
    # positively claim. Ambiguous. Fail closed.
    if (-not $ownsRemoteSessionOrServer -and $anyVmmemAlive) {
        $lines = @(
            "ambiguous_sandbox_state_utc=$((Get-Date).ToUniversalTime().ToString('o'))"
            "launched_pids=$($LaunchedPids -join ', ')"
            "reason=WindowsSandboxRemoteSession/WindowsSandboxServer are not among this run's recorded, still-alive PID(s), but vmmemWindowsSandbox is alive -- cannot positively attribute it to this run. Refusing to kill anything."
        )
        Set-Content -Path (Join-Path $OutputDir 'FOREIGN-SANDBOX-SESSION.txt') -Value ($lines -join "`n") -Encoding UTF8
        foreach ($l in $lines) { Write-Warning "[Run-SandboxSoak] $l" }
        return [pscustomobject]@{ ok = $false; foreign = $true; remaining = @() }
    }

    if ($ownProcs.Count -eq 0) {
        Write-Warning "[Run-SandboxSoak] none of this run's recorded sandbox PID(s) ($($LaunchedPids -join ', ')) are still running under a sandbox process name -- nothing to stop (already exited, or the PID list is stale). Leaving any other sandbox processes untouched."
        return [pscustomobject]@{ ok = $true; foreign = $false; remaining = @() }
    }

    # Coordinator confirmed directly (unelevated host, this box): Stop-Process
    # against vmmemWindowsSandbox returns "Access is denied" -- it is a
    # protected VM-worker process an unelevated Windows PowerShell session
    # cannot terminate. NEVER attempt it (a failed attempt is also wasted
    # time and a confusing warning line for no effect). Kill only the
    # process types that actually respond to an unelevated Stop-Process --
    # WindowsSandboxClient/WindowsSandboxRemoteSession/WindowsSandboxServer
    # -- then wait for vmmemWindowsSandbox to exit ON ITS OWN once its
    # parent session is gone (a real elevated operator/helper can clear a
    # lingering one; that is out of band from this script).
    $killableProcs = @($ownProcs | Where-Object { $_.ProcessName -ne 'vmmemWindowsSandbox' })
    $killed = @()
    foreach ($p in $killableProcs) {
        try {
            Stop-Process -Id $p.Id -Force -ErrorAction Stop
            $killed += "$($p.ProcessName)(pid=$($p.Id))"
        } catch {
            Write-Warning "[Run-SandboxSoak] failed to stop $($p.ProcessName) pid=$($p.Id): $_"
        }
    }
    Write-Step "Killed (by recorded PID only, vmmemWindowsSandbox excluded -- cannot be stopped from an unelevated host): $(if ($killed.Count -gt 0) { $killed -join ', ' } else { '(none -- all failed to stop)' })"

    $pollDeadline = (Get-Date).AddSeconds(180)
    $vmmemGone = $false
    while ((Get-Date) -lt $pollDeadline) {
        if (@(Get-Process -Name 'vmmemWindowsSandbox' -ErrorAction SilentlyContinue).Count -eq 0) { $vmmemGone = $true; break }
        Start-Sleep -Seconds 5
    }
    $remaining = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
    if ($vmmemGone) {
        Write-Step "vmmemWindowsSandbox exited on its own (polled up to 3 minutes) once its parent session was stopped."
    } else {
        Write-Warning "[Run-SandboxSoak] vmmemWindowsSandbox is still running after 3 minutes -- LINGERING. This host cannot stop it unelevated (Access is denied); clear it with the elevated helper. Exit code is unaffected by this -- the run's own verdict/stall classification is unchanged."
    }
    Write-Step "Remaining sandbox process(es): $(if ($remaining.Count -gt 0) { ($remaining | ForEach-Object { "$($_.ProcessName)(pid=$($_.Id))" }) -join ', ' } else { 'none' })"
    return [pscustomobject]@{ ok = $true; foreign = $false; remaining = $remaining; vmmem_lingering = (-not $vmmemGone) }
}

function Write-StallAndExit {
    param([string]$Reason, [int[]]$LaunchedPids, [string]$OutputDir)
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    Set-Content -Path (Join-Path $OutputDir 'STALL.txt') -Value "stall_detected_utc=$ts reason=$Reason" -Encoding UTF8
    Write-Warning "[Run-SandboxSoak] STALL: $Reason -- attempting to kill this run's own sandbox process(es)."
    $killResult = Invoke-SandboxKill -LaunchedPids $LaunchedPids -OutputDir $OutputDir
    if ($killResult.foreign) { exit 5 }
    exit 4
}

function Write-QuietShareAndExit {
    <#
      N1/N6: a stale share with a LIVE shipper heartbeat is a broken
      guest-to-host channel (or a station genuinely wedged in a way this
      harness cannot diagnose from the host side) -- never a station-
      acceptance FAIL, mirroring Host-Launch-Sandbox-Test.ps1:175-178's
      HOST-QUIET-SHARE.txt / HARNESS_ERROR contract exactly. The sandbox is
      still killed (by recorded PID only, same as a real stall) so the
      resource is reclaimed, but the exit code and marker name say
      HARNESS_ERROR, not FAIL.
    #>
    param([string]$Reason, [int[]]$LaunchedPids, [string]$OutputDir)
    $ts = (Get-Date).ToUniversalTime().ToString('o')
    $markerBody = @(
        "host_quiet_share_utc=$ts"
        "reason=$Reason"
        "verdict_class=harness-error (NOT a station-acceptance FAIL -- no product conclusion can be drawn from a run whose evidence channel went quiet while the guest process was still alive)"
    ) -join [Environment]::NewLine
    Set-Content -Path (Join-Path $OutputDir 'HOST-QUIET-SHARE.txt') -Value $markerBody -Encoding UTF8
    Write-Warning "[Run-SandboxSoak] HARNESS_ERROR (quiet share): $Reason"
    Invoke-SandboxKill -LaunchedPids $LaunchedPids -OutputDir $OutputDir | Out-Null
    exit 6
}

# --------------------------------------------------------------------------
# 5. Launch, record this run's own sandbox PID(s), then wait for VERDICT.txt
#    enforcing separate phase deadlines (installer bound from launch,
#    station-healthy bound from install-done, rollup-stall bound once the
#    soak clock starts) PLUS a generic MAIN-THREAD quiet-liveness backstop
#    that covers every phase, including setup (first-admin/asset-upload/
#    schedule/channel-start) which has no dedicated bound of its own.
#
#    N1: main-thread liveness is soak-log.txt/summary.json/phase markers
#    ONLY -- never _SHIPPER-HEARTBEAT.txt, which the shipper process
#    rewrites every ~15s REGARDLESS of whether the main script is making
#    any progress at all, so including it in the same max() means the
#    bound can never fire while the shipper itself is alive. The shipper
#    heartbeat is read SEPARATELY, exactly once main-thread liveness has
#    already gone stale, purely to classify what kind of stall this is:
#    heartbeat also stale -> the channel/guest is genuinely wedged ->
#    HARNESS_ERROR (Write-QuietShareAndExit); heartbeat still fresh -> the
#    channel is fine but the guest script itself stopped progressing ->
#    a real stall (Write-StallAndExit).
# --------------------------------------------------------------------------
$launchTimeUtc = (Get-Date).ToUniversalTime()
Write-Step "Launching Windows Sandbox ($wsbPath) at $($launchTimeUtc.ToString('o'))..."
Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList "`"$wsbPath`"" | Out-Null
# WindowsSandbox.exe is a launcher stub: it starts the VM and exits almost
# immediately by design (Host-Launch-Sandbox-Test.ps1:495-499's own note).
# Give the real VM processes a moment to appear, then record THIS run's own
# PID(s) -- the busy guard above already proved none of $SandboxProcessNames
# was running immediately before this script launched one, and Windows
# Sandbox is strictly single-instance system-wide, so every PID captured
# here belongs to the VM this script just started.
Start-Sleep -Seconds 5
$launchedProcs = @(Get-Process -Name $SandboxProcessNames -ErrorAction SilentlyContinue)
if ($launchedProcs.Count -eq 0) {
    Exit-HarnessError "no Windows Sandbox VM process found a few seconds after launch -- the Sandbox feature may not be enabled, or the .wsb failed to parse"
}
$launchedPids = @($launchedProcs | Select-Object -ExpandProperty Id)
Write-Step "Recorded this run's own sandbox process PID(s): $($launchedPids -join ', ')"

$verdictTxtPath = Join-Path $outputDir 'VERDICT.txt'
$verdictJsonPath = Join-Path $outputDir 'VERDICT.json'
$rollupsDir = Join-Path $outputDir 'rollups'
$installDoneMarker = Join-Path $outputDir 'PHASE-INSTALL-DONE.json'
$healthyMarker = Join-Path $outputDir 'PHASE-HEALTHY.json'
$soakStartMarker = Join-Path $outputDir 'SOAK-START.json'

function Get-MainThreadLivenessUtc {
    <#
      N1: main-thread progress ONLY -- soak-log.txt, summary.json, and the
      phase markers the guest's own execution thread writes as it advances.
      Deliberately excludes _SHIPPER-HEARTBEAT.txt (see the shipper-vs-
      main-thread comment above section 5). Returns $null before the first
      of these files exists.
    #>
    param([string]$OutputDir)
    $candidates = @('soak-log.txt', 'summary.json', 'PHASE-INSTALL-DONE.json', 'PHASE-HEALTHY.json', 'SOAK-START.json') | ForEach-Object { Join-Path $OutputDir $_ }
    $times = @($candidates | Where-Object { Test-Path $_ } | ForEach-Object { (Get-Item $_).LastWriteTimeUtc })
    if ($times.Count -eq 0) { return $null }
    return ($times | Sort-Object -Descending | Select-Object -First 1)
}

function Get-ShipperHeartbeatUtc {
    param([string]$OutputDir)
    $p = Join-Path $OutputDir '_SHIPPER-HEARTBEAT.txt'
    if (-not (Test-Path $p)) { return $null }
    return (Get-Item $p).LastWriteTimeUtc
}

$phase = 'installing'
$installDeadlineUtc = $launchTimeUtc.AddMinutes($InstallBoundMinutes)
$healthDeadlineUtc = $null
$lastRollupCount = 0
$lastRollupProgressUtc = $null

Write-Step "Waiting for VERDICT.txt. Phase bounds: install<=${InstallBoundMinutes}m (from launch), health<=${HealthBoundMinutes}m (from install-done), rollup-stall<=${RollupStallMinutes}m (once soak_start_utc is set), boot-bound<=${BootBoundMinutes}m (at least one main-thread file must exist), generic main-thread quiet-bound<=${QuietMinutes}m thereafter (every phase; shipper heartbeat used only to classify quiet-share vs. genuine stall)."

while ($true) {
    if (Test-Path $verdictTxtPath) { break }

    # Classification via Get-SandboxLivenessVerdict (HostLiveness.ps1) --
    # NEVER inline here again. The run-3 bug lived in exactly this spot: a
    # local `$quietMinutes` (elapsed time) and the `$QuietMinutes` parameter
    # (the threshold) are THE SAME VARIABLE to PowerShell (case-insensitive
    # names), so the very first loop iteration's elapsed-time assignment
    # clobbered the threshold down to ~0, firing a false quiet-share ~40s
    # after launch, before the guest had even booted. Routing through a
    # separate, unit-tested function with distinctly-named parameters
    # closes both that bug and the "absence == staleness from t=0" bug in
    # the same fix -- see HostLiveness.ps1's own header and
    # Test-HostLiveness.ps1's regression-guard scenario.
    $mainThreadUtc = Get-MainThreadLivenessUtc -OutputDir $outputDir
    $heartbeatUtc = Get-ShipperHeartbeatUtc -OutputDir $outputDir
    $livenessSplat = @{ NowUtc = (Get-Date).ToUniversalTime(); LaunchUtc = $launchTimeUtc; BootBoundMinutes = $BootBoundMinutes; QuietMinutes = $QuietMinutes }
    if ($mainThreadUtc) { $livenessSplat['MainThreadNewestUtc'] = $mainThreadUtc }
    if ($heartbeatUtc) { $livenessSplat['HeartbeatNewestUtc'] = $heartbeatUtc }
    $liveness = Get-SandboxLivenessVerdict @livenessSplat
    if ($liveness.verdict -eq 'guest-never-started') {
        Write-QuietShareAndExit -Reason $liveness.reason -LaunchedPids $launchedPids -OutputDir $outputDir
    } elseif ($liveness.verdict -eq 'stall') {
        Write-StallAndExit -Reason $liveness.reason -LaunchedPids $launchedPids -OutputDir $outputDir
    } elseif ($liveness.verdict -eq 'quiet-share') {
        Write-QuietShareAndExit -Reason $liveness.reason -LaunchedPids $launchedPids -OutputDir $outputDir
    }
    # else 'alive' -- fall through to the phase-specific checks below.

    if ($phase -eq 'installing') {
        if (Test-Path $installDoneMarker) {
            $phase = 'awaiting-health'
            $healthDeadlineUtc = (Get-Item $installDoneMarker).LastWriteTimeUtc.AddMinutes($HealthBoundMinutes)
            Write-Step "phase -> awaiting-health (health bound: $($healthDeadlineUtc.ToString('o')))"
        } elseif ((Get-Date).ToUniversalTime() -gt $installDeadlineUtc) {
            Write-StallAndExit -Reason "installer bound (${InstallBoundMinutes}m from launch $($launchTimeUtc.ToString('o'))) exceeded -- PHASE-INSTALL-DONE.json never appeared" -LaunchedPids $launchedPids -OutputDir $outputDir
        }
    } elseif ($phase -eq 'awaiting-health') {
        if (Test-Path $healthyMarker) {
            $phase = 'awaiting-soak-start'
            Write-Step "phase -> awaiting-soak-start (generic quiet-bound covers first-admin/assets/schedule/channel-start from here)"
        } elseif ((Get-Date).ToUniversalTime() -gt $healthDeadlineUtc) {
            Write-StallAndExit -Reason "station-healthy bound (${HealthBoundMinutes}m from install-done) exceeded -- PHASE-HEALTHY.json never appeared" -LaunchedPids $launchedPids -OutputDir $outputDir
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
                Write-StallAndExit -Reason "no new rollup file for >= ${RollupStallMinutes} minute(s) (rollup_count=$rollupCount)" -LaunchedPids $launchedPids -OutputDir $outputDir
            }
        }
    }

    Start-Sleep -Seconds 15
}

# N7: require a genuinely non-empty VERDICT.txt before trusting it -- a
# shipper tick can in principle land VERDICT.txt on the share a moment
# before its content is fully flushed. Re-read for up to 10s; if it is
# STILL empty, fall back to VERDICT.json (written locally in the same
# breath as VERDICT.txt -- see In-Sandbox-Soak.ps1) and reconstruct the
# verdict line from its fields rather than trusting an empty file.
Write-Step "VERDICT.txt found -- confirming it is non-empty..."
$verdictText = $null
$verdictReadDeadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $verdictReadDeadline) {
    $candidate = $null
    try { $candidate = Get-Content -Path $verdictTxtPath -Raw -ErrorAction Stop } catch { }
    if (-not [string]::IsNullOrWhiteSpace($candidate)) { $verdictText = $candidate; break }
    Start-Sleep -Milliseconds 500
}
if ([string]::IsNullOrWhiteSpace($verdictText)) {
    Write-Warning "[Run-SandboxSoak] VERDICT.txt was still empty after a 10s re-read -- falling back to VERDICT.json."
    if (Test-Path $verdictJsonPath) {
        try {
            $vj = Get-Content -Path $verdictJsonPath -Raw | ConvertFrom-Json
            $verdictText = "verdict=$($vj.verdict) reason=$($vj.reason) cycles_total=$($vj.cycles_total) cycles_evaluated=$($vj.cycles_evaluated)"
        } catch {
            Write-QuietShareAndExit -Reason "VERDICT.txt is empty and VERDICT.json failed to parse ($_) -- no trustworthy verdict content reached the host" -LaunchedPids $launchedPids -OutputDir $outputDir
        }
    } else {
        Write-QuietShareAndExit -Reason "VERDICT.txt is empty and VERDICT.json does not exist -- no trustworthy verdict content reached the host" -LaunchedPids $launchedPids -OutputDir $outputDir
    }
}

Write-Host ""
Write-Host "=== SANDBOX SOAK VERDICT ===" -ForegroundColor Cyan
Write-Host $verdictText
if (Test-Path $verdictJsonPath) {
    Write-Host "Full verdict: $verdictJsonPath"
}
Write-Host "Evidence: $outputDir"

# Round-3(c): confirmed directly that the sandbox does NOT tear itself down
# just because the LogonCommand script exited -- run 2 left
# WindowsSandboxRemoteSession/WindowsSandboxServer/vmmemWindowsSandbox all
# alive well after VERDICT.txt was written, and the previous version of
# this block only logged "still shutting down" and left them running
# forever. In-Sandbox-Soak.ps1 now asks the GUEST OS itself to shut down
# (shutdown.exe /s /t 5) right after its final flush, on every exit path.
# This host side gives that a bounded 3-minute window to actually happen,
# then force-kills anything of this run's own recorded PIDs still alive
# (never by bare name -- same Invoke-SandboxKill as the stall path).
Write-Step "Waiting up to 3 minutes for this run's own sandbox process(es) to exit (guest requested its own shutdown)..."
$teardownDeadline = (Get-Date).AddMinutes(3)
$allExited = $false
while ((Get-Date) -lt $teardownDeadline) {
    if (@(Get-Process -Id $launchedPids -ErrorAction SilentlyContinue).Count -eq 0) { $allExited = $true; break }
    Start-Sleep -Seconds 5
}
if ($allExited) {
    Write-Step "This run's own sandbox process(es) exited on their own within 3 minutes."
} else {
    Write-Warning "[Run-SandboxSoak] This run's own sandbox process(es) did not exit within 3 minutes of the guest's requested shutdown -- force-killing (by recorded PID only)."
    Invoke-SandboxKill -LaunchedPids $launchedPids -OutputDir $outputDir | Out-Null
}

if ($verdictText -match 'verdict=HARNESS_ERROR') {
    Write-Host "[Run-SandboxSoak] HARNESS_ERROR (see VERDICT.json for the reason -- reported by the in-sandbox script itself, e.g. insufficient schedule coverage; not a product FAIL)" -ForegroundColor Yellow
    exit 6
} elseif ($verdictText -match 'verdict=PASS') {
    Write-Host "[Run-SandboxSoak] PASS" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[Run-SandboxSoak] FAIL" -ForegroundColor Red
    exit 1
}
