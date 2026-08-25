# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Run-GateA.ps1 -- host orchestrator for Gate A, the automated station-
# acceptance release gate. Runs ON THE HOST (not in Sandbox).
#
# What it does, in order:
#   1. Resolve the candidate kit -- either download it via `gh run download`
#      (-RunId, a single throttled stream -- fine for manual/local use) or
#      use an already-extracted directory (-KitDir, the shape
#      gate-a-station-acceptance.yml hands in after its own parallel,
#      chunked actions/download-artifact@v4 fetch -- see that workflow's
#      header for why the workflow no longer calls -RunId itself).
#      With -KitDir, -SourceSha and -RunId are accepted as optional metadata
#      so the verdict JSON still carries the candidate sha and run id even
#      though this script did not do the resolving itself.
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
#   8. Print the verdict and exit 0 (PASS), 1 (FAIL), or 2 (not a
#      station-acceptance finding at all -- BUSY because Windows Sandbox
#      stayed occupied by another process and this run never launched, a
#      quiet/wedged mapped output folder mid-run, a plain timeout, no VM, a
#      missing prerequisite, or a bad kit layout). None of those is ever
#      reported as a FAIL: a run whose evidence never reached the host
#      supports no conclusion about the product at all.
#
# Requires on PATH: gh (GitHub CLI, only for -RunId), uv (for the Python
# judge). Must run on a Windows host with the Windows Sandbox feature
# enabled -- see docs/ops/gate-a.md for the runner setup
# (sandbox-lab/runner/Install-GateARunner.ps1).

[CmdletBinding(DefaultParameterSetName = 'ByRunId')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'ByRunId')]
    [Parameter(Mandatory = $false, ParameterSetName = 'ByKitDir')]
    [Nullable[long]]$RunId,

    [Parameter(Mandatory = $true, ParameterSetName = 'ByKitDir')]
    [string]$KitDir,

    # Optional metadata, -KitDir only: the caller (gate-a-station-
    # acceptance.yml) already resolved the candidate sha itself to name the
    # `native-beta-kit-<sha>` artifact for download, so it hands that same
    # sha back here rather than making this script re-derive it. When
    # omitted, the kit's own station\native-station-bundle-report.json is
    # tried next, then the -KitDir leaf directory name, then
    # 'unknown-local'.
    [Parameter(ParameterSetName = 'ByKitDir')]
    [string]$SourceSha,

    [string]$Root = $PSScriptRoot,
    [int]$SoakMinutes = 20,
    # Passed straight through to Host-Launch-Sandbox-Test.ps1. It must stay
    # ABOVE In-Sandbox-Report.ps1's -MaxScriptMinutes (150) so the
    # in-sandbox watchdog always fires first and the host's own bound is the
    # last resort. Raised 120 -> 170 with that default under
    # <gate-a-mapped-folder-stalls>: at 120 the host would have given up
    # BEFORE the watchdog it depends on, turning every long run into an
    # unexplained host timeout. Three numbers, one setting -- 150 (in
    # sandbox) < 170 (host poll), and the host's -QuietShareMinutes ends a
    # dead channel long before either.
    [int]$TimeoutMinutes = 170,
    [string]$Repo = 'scottconverse/civiccast-native',

    # Passed straight through to Host-Launch-Sandbox-Test.ps1: minutes to
    # wait for Windows Sandbox to become free before giving up. Windows
    # Sandbox is a single-instance-per-machine resource shared with an
    # independent, unrelated build system on this box -- see that script's
    # header and docs/ops/gate-a.md for the shared-sandbox guard. This is a
    # wait BEFORE the run starts and is deliberately not part of the
    # 150/170 budget ordering above, which governs a run already underway.
    [int]$SandboxWaitMinutes = 90,

    # Passed straight through to Host-Launch-Sandbox-Test.ps1: minutes of no
    # change anywhere under output\, with our own VM still alive, before the
    # run is declared a harness error rather than waited out to
    # -TimeoutMinutes. See that script's quiet-share detector and
    # docs/ops/gate-a.md, "Mapped-folder stalls".
    [int]$QuietShareMinutes = 15
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

# PowerShell variable names are case-insensitive, so the working variable
# below (`$sourceSha`) and the `-SourceSha` parameter are THE SAME variable
# -- capture the caller's value under a distinct name before it gets reset,
# or `$sourceSha = $null` two lines down silently wipes out -SourceSha.
$callerSourceSha = $SourceSha

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

    if ($RunId) {
        $resolvedRunId = $RunId
    }

    if ($callerSourceSha) {
        # Caller (gate-a-station-acceptance.yml) already resolved this
        # itself to name the artifact it downloaded -- trust it outright.
        $sourceSha = $callerSourceSha
        Write-Step "Using caller-supplied source_sha=$sourceSha"
    } else {
        # No -SourceSha given: try the kit's own build report next (best
        # effort -- as of this writing native-station-bundle-report.json's
        # schema in scripts/build_native_station_bundle.py does not carry a
        # sha-shaped field, so this is forward-looking, not a currently
        # populated path), then fall back to sniffing the -KitDir leaf name
        # against the kit-staging\<sha>\ convention, then give up honestly.
        $reportPath = Get-ChildItem -Path $kitSourceDir -Filter 'native-station-bundle-report.json' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($reportPath) {
            try {
                $report = Get-Content -Path $reportPath.FullName -Raw | ConvertFrom-Json
                $candidate = $report.source_sha
                if (-not $candidate) { $candidate = $report.git_sha }
                if ($candidate -and ($candidate -match '^[0-9a-f]{7,40}$')) {
                    $sourceSha = $candidate
                    Write-Step "Recovered source_sha=$sourceSha from $($reportPath.FullName)"
                }
            } catch {
                Write-Warning "Could not parse $($reportPath.FullName) for a source_sha: $_"
            }
        }

        if (-not $sourceSha) {
            $leaf = Split-Path -Leaf $kitSourceDir
            if ($leaf -match '^[0-9a-f]{7,40}$') {
                $sourceSha = $leaf
            } else {
                $sourceSha = 'unknown-local'
            }
        }
    }
    Write-Step "Using pre-extracted kit at $kitSourceDir (source_sha=$sourceSha, run_id=$resolvedRunId)"
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

Write-Step "Launching Host-Launch-Sandbox-Test.ps1 (TimeoutMinutes=$TimeoutMinutes, SoakMinutes=$SoakMinutes, SandboxWaitMinutes=$SandboxWaitMinutes, QuietShareMinutes=$QuietShareMinutes)..."
& $launcherPath -Root $Root -TimeoutMinutes $TimeoutMinutes -SoakMinutes $SoakMinutes -SandboxWaitMinutes $SandboxWaitMinutes -QuietShareMinutes $QuietShareMinutes
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

# --------------------------------------------------------------------------
# 6a. Host-launcher exit 3 = Windows Sandbox stayed busy (owned by another,
#     independent process on this shared box) for the entire
#     -SandboxWaitMinutes wait window, and the launcher backed off without
#     ever touching it. This is a harness-busy outcome, not a station-
#     acceptance FAIL -- write a BUSY verdict document (same shape family as
#     gate-a-verdict.json, so CI can find and read it the same way) and exit
#     2 (harness error), never 1 (product FAIL).
# --------------------------------------------------------------------------

if ($launcherExit -eq 3) {
    Write-Warning "[Run-GateA] Windows Sandbox stayed busy for the entire ${SandboxWaitMinutes}m wait window (owned by another process on this shared box, e.g. a rival build system) -- this is a harness-busy outcome, not a station-acceptance FAIL."

    # Mirror scripts/gate_a_verdict.py's own SANDBOX-BUSY.txt short-circuit
    # shape (including the "detail" field) so a BUSY verdict document looks
    # the same regardless of which of the two writers produced it.
    $busyDetail = "Host-Launch-Sandbox-Test.ps1 exited 3 (Windows Sandbox still busy after waiting ${SandboxWaitMinutes}m)"
    $busyDetailPath = Join-Path $outputDir 'SANDBOX-BUSY.txt'
    if (Test-Path $busyDetailPath) {
        $fileDetail = (Get-Content -Path $busyDetailPath -Raw).Trim()
        if ($fileDetail) { $busyDetail = $fileDetail }
    }

    $busyVerdict = [ordered]@{
        schema_version = 1
        source_sha     = $sourceSha
        run_id         = $resolvedRunId
        verdict        = "BUSY"
        reason         = "sandbox-busy-other-user"
        detail         = $busyDetail
        checks         = @{}
        station_up     = $null
        station_boot_seconds = $null
        station_first_healthy_utc = $null
        evidence_dir   = $(if ($hasEvidence) { $evidenceDir } else { $null })
        judged_utc     = (Get-Date).ToUniversalTime().ToString('o')
    }
    if ($hasEvidence) {
        $busyVerdictDir = $evidenceDir
    } else {
        $busyVerdictDir = $outputDir
    }
    if (-not (Test-Path $busyVerdictDir)) {
        New-Item -ItemType Directory -Force -Path $busyVerdictDir | Out-Null
    }
    $busyVerdictPath = Join-Path $busyVerdictDir 'gate-a-verdict.json'
    ($busyVerdict | ConvertTo-Json -Depth 8) | Set-Content -Path $busyVerdictPath -Encoding UTF8

    Write-Host ""
    Write-Host "=== GATE A VERDICT ===" -ForegroundColor Cyan
    Get-Content -Path $busyVerdictPath -Raw | Write-Host
    Write-Host "Evidence: $busyVerdictDir"
    Write-Host "[Run-GateA] BUSY -- Windows Sandbox occupied by another process; harness did not run" -ForegroundColor Yellow
    exit 2
}

if ($launcherExit -ne 0) {
    # Launcher exit codes: 1 = no VM after launch; 2 = timed out waiting for
    # DONE.json; 3 = sandbox stayed busy, handled above; 4 = the mapped
    # output folder went quiet while our own VM was alive (see
    # Host-Launch-Sandbox-Test.ps1's quiet-share detector, which also drops
    # HOST-QUIET-SHARE.txt into output\ so the judge can name the cause).
    # Every one of them is a harness error, not a station-acceptance FAIL --
    # exit 2 regardless of what the judge says about the partial evidence.
    # Still worth judging that evidence for forensics.
    if ($launcherExit -eq 4) {
        Write-Warning "[Run-GateA] The sandbox's mapped output folder went quiet while the VM was alive -- broken evidence channel, no product conclusion available. See HOST-QUIET-SHARE.txt in the evidence directory."
    }
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
} elseif ($judgeExit -eq 2) {
    # One of the judge's two non-verdicts: HARNESS_ERROR (HOST-QUIET-SHARE.txt
    # -- the evidence channel broke mid-run) or BUSY (SANDBOX-BUSY.txt -- the
    # run never started; normally already handled by the launcherExit -eq 3
    # branch above, so reaching it here means the marker was found on
    # otherwise-clean evidence). Either way NO product conclusion can be
    # drawn. Deliberately not printed as FAIL: calling a broken harness a
    # station-acceptance failure is precisely the authored-truth failure
    # mode Gate A exists to eliminate, in the opposite direction.
    Write-Warning "[Run-GateA] HARNESS ERROR -- see gate-a-verdict.json's harness_error field; this is NOT a station-acceptance FAIL"
    exit 2
} else {
    Write-Warning "[Run-GateA] Judge exited with unexpected code $judgeExit (treated as harness error)"
    exit 2
}

exit $judgeExit
