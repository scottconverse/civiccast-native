# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Run-SandboxSoak.ps1 -- host orchestrator for the LOCAL 15-minute Windows
# Sandbox soak lane. Finds bugs on HALO in ~15 minutes instead of on the
# tester box in hours, by driving a real silent install + station start +
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
# Usage:
#   pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> [-Minutes 15] [-KitRoot C:\CivicCastTester\kit-safe]
#   pwsh -File sandbox-lab/Run-SandboxSoak.ps1 -Sha <full sha> -DryRun
#
# Exit codes: 0 PASS, 1 FAIL, 2 harness/setup error (bad kit, missing
# prerequisite), 3 Windows Sandbox already running, 4 stall (no rollup
# progress for 6 minutes -- sandbox killed, evidence preserved).
param(
    [Parameter(Mandatory = $true)]
    [string]$Sha,

    [int]$Minutes = 15,

    [string]$KitRoot = 'C:\CivicCastTester\kit-safe',

    [string]$Root = $PSScriptRoot,

    # Minutes with no new rollup file under output\rollups\ (and no VM-alive
    # progress) before this script declares a stall, writes STALL.txt, kills
    # the sandbox, and exits 4. Rollups land every 3 minutes inside the
    # sandbox (see In-Sandbox-Soak.ps1), so 6 minutes is two missed
    # checkpoints -- generous enough to survive one slow tick, tight enough
    # that a genuinely wedged run does not sit there for the full -Minutes
    # + watchdog grace before anyone notices.
    [int]$StallMinutes = 6,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[Run-SandboxSoak] $Message" -ForegroundColor Cyan
}

function Exit-HarnessError {
    param([string]$Message, [int]$Code = 2)
    Write-Error "[Run-SandboxSoak] ERROR: $Message"
    exit $Code
}

if (-not $Root) { $Root = (Get-Location).Path }
Write-Step "Root: $Root, Sha: $Sha, Minutes: $Minutes, KitRoot: $KitRoot, DryRun: $($DryRun.IsPresent)"

# --------------------------------------------------------------------------
# 1a. Refuse if Windows Sandbox is already running (Gate A owns it, and
#     Codex uses it too -- see the caller's own note; this lane never
#     launches over another user's session).
# --------------------------------------------------------------------------
$sandboxProcNames = @('WindowsSandbox', 'WindowsSandboxClient')
# Get-Process (not Get-CimInstance) finds the processes by name reliably
# across PS versions; Get-CimInstance is then used ONLY to recover each
# matched PID's command line for the printed evidence (Get-Process's own
# .Path/-IncludeUserName does not carry the command line on this platform).
$existing = @(Get-Process -Name $sandboxProcNames -ErrorAction SilentlyContinue)
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
#    watchdog times out 25 minutes later.
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
    Write-Step "Would poll for: $outputDir\VERDICT.txt"
    Write-Step "Output directory prepared at: $outputDir (empty -- no sandbox launched)"
    exit 0
}

# --------------------------------------------------------------------------
# 4. Launch and wait for VERDICT.txt, with a stall alarm.
# --------------------------------------------------------------------------
Write-Step "Launching Windows Sandbox ($wsbPath)..."
Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList "`"$wsbPath`"" | Out-Null

$verdictTxtPath = Join-Path $outputDir 'VERDICT.txt'
$verdictJsonPath = Join-Path $outputDir 'VERDICT.json'
$rollupsDir = Join-Path $outputDir 'rollups'
$stallSeconds = [Math]::Max(60, $StallMinutes * 60)
$lastProgressTime = Get-Date
$lastRollupCount = 0
$overallDeadline = (Get-Date).AddMinutes($Minutes + 20)   # generous outer bound past the in-sandbox watchdog's own Minutes+10

Write-Step "Waiting for $verdictTxtPath (stall alarm at ${StallMinutes}m of no rollup progress, outer bound $($overallDeadline.ToString('o')))..."

while ($true) {
    if (Test-Path $verdictTxtPath) { break }

    $rollupCount = 0
    if (Test-Path $rollupsDir) {
        $rollupCount = @(Get-ChildItem -Path $rollupsDir -Filter '*.json' -File -ErrorAction SilentlyContinue).Count
    }
    if ($rollupCount -gt $lastRollupCount) {
        $lastRollupCount = $rollupCount
        $lastProgressTime = Get-Date
    }

    $stalledSeconds = ((Get-Date) - $lastProgressTime).TotalSeconds
    if ($stalledSeconds -ge $stallSeconds) {
        $ts = (Get-Date).ToUniversalTime().ToString('o')
        $stallBody = "stall_detected_utc=$ts rollup_count=$rollupCount stalled_seconds=$([Math]::Round($stalledSeconds, 1)) threshold_seconds=$stallSeconds reason=no new rollup file for >= ${StallMinutes} minute(s)"
        Set-Content -Path (Join-Path $outputDir 'STALL.txt') -Value $stallBody -Encoding UTF8
        Write-Warning "[Run-SandboxSoak] STALL: $stallBody -- killing the sandbox."
        foreach ($name in $sandboxProcNames) {
            Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        }
        exit 4
    }

    if ((Get-Date) -ge $overallDeadline) {
        $ts = (Get-Date).ToUniversalTime().ToString('o')
        $stallBody = "outer_deadline_reached_utc=$ts reason=VERDICT.txt never appeared within Minutes+20 ($($Minutes + 20)m), and the in-sandbox watchdog (Minutes+10) should have already fired -- treating as a stall"
        Set-Content -Path (Join-Path $outputDir 'STALL.txt') -Value $stallBody -Encoding UTF8
        Write-Warning "[Run-SandboxSoak] STALL (outer deadline): $stallBody -- killing the sandbox."
        foreach ($name in $sandboxProcNames) {
            Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        }
        exit 4
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
$stillRunning = @(Get-Process -Name $sandboxProcNames -ErrorAction SilentlyContinue)
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
