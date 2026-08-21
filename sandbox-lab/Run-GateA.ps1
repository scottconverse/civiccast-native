# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Run-GateA.ps1 -- host orchestrator for Gate A, the automated station-
# acceptance release gate. Runs ON THE HOST (not in Sandbox).
#
# What it does, in order:
#   1. Resolve the candidate kit -- either download it (-RunId) or use an
#      already-extracted directory (-KitDir).
#   2. Validate the kit layout (glob for the installer, don't assume a name;
#      confirm the station bundle is present).
#   3. Point sandbox-lab\kit-download at the resolved kit via an NTFS
#      directory junction (never a copy -- the assembled kit is ~20+ GB;
#      see native-beta-candidate-artifacts.yml's own header for why these
#      artifacts are that large).
#   4. Reset hoststore\ (every gate run is a FRESH install -- a stale
#      persistent install directory would silently skip install evidence).
#   5. Run Host-Launch-Sandbox-Test.ps1, which itself clears output\, writes
#      SOAK_MINUTES.txt, renders the .wsb from its template, launches the
#      Sandbox, and polls for the authoritative DONE.json completion signal.
#   6. Judge the result with scripts/gate_a_verdict.py (fail-closed).
#   7. Copy output\ to evidence\<source_sha>\<utc-timestamp>\ regardless of
#      verdict -- a FAIL needs its evidence preserved at least as much as a
#      PASS does.
#   8. Print the verdict and exit 0 (PASS), 1 (FAIL), or 2 (harness error --
#      timeout, no VM, missing prerequisite, bad kit layout).
#
# Requires on PATH: gh (GitHub CLI, only for -RunId), uv (for the Python
# judge). Must run on a Windows host with the Windows Sandbox feature
# enabled -- see docs/ops/gate-a.md for the runner setup
# (sandbox-lab/runner/Install-GateARunner.ps1).

[CmdletBinding(DefaultParameterSetName = 'ByRunId')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'ByRunId')]
    [long]$RunId,

    [Parameter(Mandatory = $true, ParameterSetName = 'ByKitDir')]
    [string]$KitDir,

    [string]$Root = $PSScriptRoot,
    [int]$SoakMinutes = 20,
    [int]$TimeoutMinutes = 120,
    [string]$Repo = 'scottconverse/civiccast-native'
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[Run-GateA] $Message" -ForegroundColor Cyan
}

function Exit-HarnessError {
    param([string]$Message)
    Write-Error "[Run-GateA] HARNESS ERROR: $Message"
    exit 2
}

Write-Step "Root: $Root"
Write-Step "SoakMinutes=$SoakMinutes TimeoutMinutes=$TimeoutMinutes Repo=$Repo"

# --------------------------------------------------------------------------
# 1. Resolve the candidate kit.
# --------------------------------------------------------------------------

$sourceSha = $null
$kitSourceDir = $null
$resolvedRunId = $null

if ($PSCmdlet.ParameterSetName -eq 'ByRunId') {
    $resolvedRunId = $RunId
    $ghCmd = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $ghCmd) {
        Exit-HarnessError "gh (GitHub CLI) not found on PATH -- required to resolve -RunId $RunId"
    }

    Write-Step "Resolving head SHA for run $RunId in $Repo..."
    $runJson = & gh run view $RunId -R $Repo --json 'headSha,status,conclusion,workflowName' 2>&1
    if ($LASTEXITCODE -ne 0) {
        Exit-HarnessError "gh run view $RunId failed: $runJson"
    }
    $runInfo = $runJson | ConvertFrom-Json
    $sourceSha = $runInfo.headSha
    if (-not $sourceSha) {
        Exit-HarnessError "gh run view $RunId returned no headSha"
    }
    Write-Step "Run $RunId ($($runInfo.workflowName)): status=$($runInfo.status) conclusion=$($runInfo.conclusion) headSha=$sourceSha"
    if ($runInfo.conclusion -and $runInfo.conclusion -ne 'success') {
        Write-Warning "Run $RunId did not conclude 'success' (conclusion=$($runInfo.conclusion)) -- judging it anyway since -RunId was explicit, but its kit may be incomplete or absent."
    }

    $stagingDir = Join-Path $Root "kit-staging\$sourceSha"
    $alreadyStaged = (Test-Path $stagingDir) -and ((Get-ChildItem -Path $stagingDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
    if ($alreadyStaged) {
        Write-Step "Kit already staged at $stagingDir -- skipping download."
    } else {
        $artifactName = "native-beta-kit-$sourceSha"
        Write-Step "Downloading artifact $artifactName from run $RunId into $stagingDir..."
        New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
        $dl = & gh run download $RunId -R $Repo -n $artifactName -D $stagingDir 2>&1
        if ($LASTEXITCODE -ne 0) {
            Exit-HarnessError "gh run download failed for artifact $artifactName (run $RunId): $dl"
        }
        Write-Step "Download complete."
    }
    $kitSourceDir = $stagingDir
} else {
    if (-not (Test-Path $KitDir)) {
        Exit-HarnessError "-KitDir does not exist: $KitDir"
    }
    $kitSourceDir = (Resolve-Path $KitDir).Path
    # Best-effort SHA recovery for an already-extracted kit: the assembled
    # kit itself carries no receipt (that lives in the separate
    # native-beta-candidate artifact), so this is "unknown-local" unless the
    # caller's directory name IS the sha (kit-staging\<sha>\ convention).
    $leaf = Split-Path -Leaf $kitSourceDir
    if ($leaf -match '^[0-9a-f]{7,40}$') {
        $sourceSha = $leaf
    } else {
        $sourceSha = 'unknown-local'
    }
    Write-Step "Using pre-extracted kit at $kitSourceDir (source_sha=$sourceSha)"
}

# --------------------------------------------------------------------------
# 2. Validate the kit layout. Glob for the installer -- never a hard-coded
#    filename, since the version string changes every candidate.
# --------------------------------------------------------------------------

$installerExe = Get-ChildItem -Path $kitSourceDir -Filter '*setup.exe' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installerExe) {
    Exit-HarnessError "No *setup.exe found anywhere under $kitSourceDir -- bad or incomplete kit"
}
$stationIndex = Get-ChildItem -Path $kitSourceDir -Filter 'station-index.json' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $stationIndex) {
    Exit-HarnessError "No station-index.json found anywhere under $kitSourceDir -- bad or incomplete kit (K1 activation will fail loud on this)"
}
Write-Step "Kit validated: installer=$($installerExe.Name), station bundle=$($stationIndex.Directory.FullName)"

# --------------------------------------------------------------------------
# 3. Point kit-download\ at the resolved kit via a directory junction --
#    never a copy. Reset it first so a stale junction from a prior run can
#    never silently point at the wrong kit.
# --------------------------------------------------------------------------

$kitDownload = Join-Path $Root 'kit-download'
if (Test-Path $kitDownload) {
    $item = Get-Item $kitDownload -Force
    if ($item.LinkType) {
        # Junction/symlink: remove the link itself, never recurse into the target.
        $item.Delete()
    } else {
        Remove-Item -Path $kitDownload -Recurse -Force -ErrorAction SilentlyContinue
    }
}
New-Item -ItemType Junction -Path $kitDownload -Target $kitSourceDir | Out-Null
Write-Step "kit-download -> $kitSourceDir (junction)"

# --------------------------------------------------------------------------
# 4. Reset hoststore\ -- every gate run is a fresh install.
# --------------------------------------------------------------------------

$hoststore = Join-Path $Root 'hoststore'
if (Test-Path $hoststore) {
    Get-ChildItem -Path $hoststore -Force | Where-Object { $_.Name -ne '.gitkeep' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Force -Path $hoststore | Out-Null
}
Write-Step "hoststore reset (fresh-install guarantee)"

# --------------------------------------------------------------------------
# 5. Run the host launcher. It clears output\, writes SOAK_MINUTES.txt,
#    renders the .wsb, launches Sandbox, and polls for DONE.json.
# --------------------------------------------------------------------------

$launcherPath = Join-Path $Root 'Host-Launch-Sandbox-Test.ps1'
if (-not (Test-Path $launcherPath)) {
    Exit-HarnessError "Host-Launch-Sandbox-Test.ps1 not found at $launcherPath"
}

Write-Step "Launching Host-Launch-Sandbox-Test.ps1 (TimeoutMinutes=$TimeoutMinutes, SoakMinutes=$SoakMinutes)..."
& $launcherPath -Root $Root -TimeoutMinutes $TimeoutMinutes -SoakMinutes $SoakMinutes
$launcherExit = $LASTEXITCODE
Write-Step "Host launcher exited with code $launcherExit"

$outputDir = Join-Path $Root 'output'

# --------------------------------------------------------------------------
# 6+7. Judge the run (if there's anything to judge) and always preserve
#      evidence, regardless of verdict.
# --------------------------------------------------------------------------

$utcStamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ')
$evidenceDir = Join-Path $Root "evidence\$sourceSha\$utcStamp"

$hasEvidence = (Test-Path $outputDir) -and ((Get-ChildItem -Path $outputDir -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
if ($hasEvidence) {
    New-Item -ItemType Directory -Force -Path (Split-Path $evidenceDir -Parent) | Out-Null
    Copy-Item -Path $outputDir -Destination $evidenceDir -Recurse -Force
    Write-Step "Evidence copied to $evidenceDir"
} else {
    Write-Warning "output\ is empty or missing -- nothing to copy to evidence\, nothing to judge."
}

if ($launcherExit -ne 0) {
    # 1 = timed out waiting for DONE.json, no clean VM close. Still worth
    # judging whatever partial evidence exists (it will fail-closed on the
    # missing files), but the run itself is a harness error, not a
    # station-acceptance FAIL -- exit 2 regardless of what the judge says.
    if ($hasEvidence) {
        $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($uvCmd) {
            $forensicRepoRoot = Split-Path $Root -Parent
            $forensicJudgePath = Join-Path $forensicRepoRoot 'scripts\gate_a_verdict.py'
            Write-Step "Running the verdict judge on partial evidence for forensics (harness did not complete cleanly)..."
            & uv run --project $forensicRepoRoot python $forensicJudgePath $evidenceDir --source-sha $sourceSha --run-id "$resolvedRunId" --out (Join-Path $evidenceDir 'gate-a-verdict.json') 2>&1 | Write-Host
        }
    }
    Exit-HarnessError "Host-Launch-Sandbox-Test.ps1 did not complete cleanly (exit $launcherExit) -- see $evidenceDir"
}

if (-not $hasEvidence) {
    Exit-HarnessError "Host launcher reported success but output\ is empty -- cannot judge"
}

$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCmd) {
    Exit-HarnessError "uv not found on PATH -- required to run scripts/gate_a_verdict.py"
}

$repoRoot = Split-Path $Root -Parent
$judgePath = Join-Path $repoRoot 'scripts\gate_a_verdict.py'
if (-not (Test-Path $judgePath)) {
    Exit-HarnessError "Judge module not found at $judgePath"
}

$verdictPath = Join-Path $evidenceDir 'gate-a-verdict.json'
Write-Step "Judging $evidenceDir ..."
& uv run --project $repoRoot python $judgePath $evidenceDir --source-sha $sourceSha --run-id "$resolvedRunId" --out $verdictPath
$judgeExit = $LASTEXITCODE

# --------------------------------------------------------------------------
# 8. Print the verdict and exit with the judge's own code.
# --------------------------------------------------------------------------

if (Test-Path $verdictPath) {
    Write-Host ""
    Write-Host "=== GATE A VERDICT ===" -ForegroundColor Cyan
    Get-Content -Path $verdictPath -Raw | Write-Host
    Write-Host "Evidence: $evidenceDir"
}

if ($judgeExit -eq 0) {
    Write-Host "[Run-GateA] PASS" -ForegroundColor Green
} elseif ($judgeExit -eq 1) {
    Write-Host "[Run-GateA] FAIL" -ForegroundColor Red
} else {
    Write-Warning "[Run-GateA] Judge exited with unexpected code $judgeExit (treated as harness error)"
    exit 2
}

exit $judgeExit
