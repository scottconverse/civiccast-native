# SPDX-License-Identifier: Apache-2.0
# Local-only CivicCast 3.2 LPM contract-lab runner.
#
# This script is intentionally local. It must not push, merge, tag, open PRs,
# publish releases, or mutate the live GitHub beta stream.

[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"
$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">>> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Body
    )

    Write-Step $Name
    $script:StepIndex += 1
    $safeName = ($Name.ToLowerInvariant() -replace '[^a-z0-9]+', '-').Trim('-')
    $logPath = Join-Path $artifactRoot ("{0:D2}-{1}.log" -f $script:StepIndex, $safeName)
    "Step: $Name" | Set-Content -LiteralPath $logPath -Encoding utf8
    "" | Add-Content -LiteralPath $logPath -Encoding utf8

    $global:LASTEXITCODE = 0
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & $Body *>&1
        $stepExitCode = $LASTEXITCODE
        foreach ($item in $output) {
            Write-Host (($item | Out-String).TrimEnd())
        }
        $output | Out-File -FilePath $logPath -Append -Encoding utf8
    } catch {
        $errorText = $_ | Out-String
        Write-Host $errorText
        $errorText | Out-File -FilePath $logPath -Append -Encoding utf8
        throw
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($stepExitCode -ne 0) {
        throw "Local CI step failed: $Name"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

if ($Python -ne "") {
    $script:PythonExe = $Python
    $script:PythonArgsPrefix = @()
} elseif (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $script:PythonExe = "uv"
    $script:PythonArgsPrefix = @("run", "python")
} else {
    $script:PythonExe = "python"
    $script:PythonArgsPrefix = @()
}

function Invoke-Python {
    param([string[]]$Arguments)
    & $script:PythonExe @($script:PythonArgsPrefix + $Arguments)
}

function Copy-DirectorySnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }

    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    $destinationFull = [System.IO.Path]::GetFullPath($Destination)
    New-Item -ItemType Directory -Force -Path $destinationFull | Out-Null
    & robocopy $sourceFull $destinationFull /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
    $robocopyExit = $LASTEXITCODE
    if ($robocopyExit -gt 7) {
        throw "robocopy failed while copying $Source to $Destination with exit code $robocopyExit"
    }
    $global:LASTEXITCODE = 0
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMs = 2000
    )

    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            $client.Close()
            return $false
        }
        $client.EndConnect($async)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

$script:ObsWebSocketStartedProcessId = $null
$script:ObsLabAppData = $null
$script:ObsWebSocketPassword = $null

function New-LocalLabSecret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

function Start-LocalObsWebSocketLab {
    if (Test-TcpPort -HostName "127.0.0.1" -Port 4455 -TimeoutMs 3000) {
        Write-Host "OBS websocket TCP endpoint already reachable at 127.0.0.1:4455."
        cmd /c "exit 0"
        return
    }

    $obsExeCandidates = @(
        "C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        "C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"
    )
    $obsExe = $obsExeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $obsExe) {
        Write-Host "OBS Studio executable not found. Install OBS before requiring Stage 4 software-lab proof."
        cmd /c "exit 1"
        return
    }

    $script:ObsLabAppData = Join-Path $artifactRoot "obs-lab-appdata"
    $obsConfigDir = Join-Path $script:ObsLabAppData "obs-studio\plugin_config\obs-websocket"
    New-Item -ItemType Directory -Force -Path $obsConfigDir | Out-Null
    $script:ObsWebSocketPassword = New-LocalLabSecret
    $env:CIVICAST_OBS_WEBSOCKET_PASSWORD = $script:ObsWebSocketPassword
    [ordered]@{
        server_enabled = $true
        server_port = 4455
        auth_required = $true
        server_password = $script:ObsWebSocketPassword
        first_load = $false
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $obsConfigDir "config.json") -Encoding utf8

    $psi = [System.Diagnostics.ProcessStartInfo]::new()
    $psi.FileName = $obsExe
    $psi.WorkingDirectory = Split-Path -Parent $obsExe
    $psi.UseShellExecute = $false
    $null = $psi.ArgumentList.Add("--disable-shutdown-check")
    $null = $psi.ArgumentList.Add("--minimize-to-tray")
    $psi.Environment["APPDATA"] = $script:ObsLabAppData
    $obsProcess = [System.Diagnostics.Process]::Start($psi)
    $script:ObsWebSocketStartedProcessId = $obsProcess.Id
    Start-Sleep -Seconds 8

    if (Test-TcpPort -HostName "127.0.0.1" -Port 4455 -TimeoutMs 3000) {
        Write-Host "OBS websocket TCP endpoint reachable at 127.0.0.1:4455."
        cmd /c "exit 0"
    } else {
        Write-Host "OBS websocket TCP endpoint is not reachable at 127.0.0.1:4455."
        cmd /c "exit 1"
    }
}

function Restore-LocalObsWebSocketLab {
    if ($script:ObsWebSocketStartedProcessId) {
        $startedProcess = Get-Process -Id $script:ObsWebSocketStartedProcessId -ErrorAction SilentlyContinue
        if ($startedProcess) {
            Stop-Process -Id $script:ObsWebSocketStartedProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped OBS process started by this runner: $script:ObsWebSocketStartedProcessId"
        }
    }
    if ($script:ObsLabAppData -and (Test-Path -LiteralPath $script:ObsLabAppData)) {
        Write-Host "Removing isolated OBS lab APPDATA from evidence root: $script:ObsLabAppData"
        Remove-Item -LiteralPath $script:ObsLabAppData -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item Env:\CIVICAST_OBS_WEBSOCKET_PASSWORD -ErrorAction SilentlyContinue
    $script:ObsWebSocketPassword = $null
}

function Test-TrackedAndUntrackedWhitespace {
    $scopedPaths = @(
        "civiccast/control_room/lpm_lab.py",
        "civiccast/control_room/lpm_lab_harness.py",
        "civiccast/control_room/lpm_lab_stage45.py",
        "civiccast/control_room/lpm_lab_stage67.py",
        "civiccast/control_room/lpm_lab_stage8.py",
        "docs/spec/3.2-lpm-livestreaming-contract-lab.md",
        "scripts/run_lpm_contract_lab.py",
        "scripts/run_lpm_contract_lab_wall_clock_soak.py",
        "scripts/run_local_3_2_lpm_contract_lab_ci.ps1",
        "tools/virtual-media-studio/README.md",
        "tools/virtual-media-studio/civiccast-vstudio.py",
        "tools/virtual-media-studio/vstudio/bundle.py",
        "tools/virtual-media-studio/vstudio/cli.py",
        "tools/virtual-media-studio/vstudio/models.py",
        "tools/virtual-media-studio/vstudio/probes.py",
        "tools/virtual-media-studio/vstudio/registry.py",
        "tools/virtual-media-studio/vstudio/profile_packs/lpm.py",
        "tests/control_room/test_lpm_lab_profiles.py",
        "tests/control_room/test_lpm_lab_harness.py",
        "tests/control_room/test_lpm_lab_stage45.py",
        "tests/control_room/test_lpm_lab_stage67.py",
        "tests/control_room/test_lpm_lab_stage8.py",
        "tests/control_room/test_lpm_lab_wall_clock_soak.py",
        "tests/tools/test_virtual_media_studio.py"
    )

    git diff --check
    if ($LASTEXITCODE -ne 0) {
        return
    }

    $hasError = $false
    foreach ($path in $scopedPaths) {
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $lineNumber = 0
        foreach ($line in Get-Content -LiteralPath $path) {
            $lineNumber += 1
            if ($line -match '\s+$') {
                Write-Host ("{0}:{1}: trailing whitespace" -f $path, $lineNumber)
                $hasError = $true
            }
        }
        $bytes = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $path))
        if ($bytes.Length -gt 0 -and $bytes[$bytes.Length - 1] -ne 10) {
            Write-Host ("{0}: missing final newline" -f $path)
            $hasError = $true
        }
    }

    if ($hasError) {
        cmd /c "exit 1"
    } else {
        cmd /c "exit 0"
    }
}

function Reset-LocalCiArtifactRoot {
    param([string]$Path)
    $repoArtifactsLocalCi = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "artifacts/local-ci"))
    $resolved = if ([System.IO.Path]::IsPathRooted($Path)) {
        [System.IO.Path]::GetFullPath($Path)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Path))
    }
    $allowedPrefix = $repoArtifactsLocalCi.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($allowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean artifact root outside repo artifacts/local-ci: $resolved"
    }
    if ([System.IO.Path]::GetFileName($resolved) -eq "") {
        throw "Refusing to clean an unnamed artifact root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        $emptyDir = Join-Path ([System.IO.Path]::GetTempPath()) ("civiccast-empty-" + [System.Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Force -Path $emptyDir | Out-Null
        try {
            & robocopy $emptyDir $resolved /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Host
            $robocopyExit = $LASTEXITCODE
            if ($robocopyExit -gt 7) {
                throw "robocopy failed while clearing artifact root $resolved with exit code $robocopyExit"
            }
            $global:LASTEXITCODE = 0
            Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path -LiteralPath $resolved) {
                [System.IO.Directory]::Delete($resolved, $true)
            }
        } finally {
            Remove-Item -LiteralPath $emptyDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
if ($ArtifactRoot -ne "") {
    $artifactRoot = $ArtifactRoot
} else {
    $artifactRoot = Join-Path $repoRoot "artifacts/local-ci/3.2-lpm-contract-lab-$runId"
}
Reset-LocalCiArtifactRoot -Path $artifactRoot
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$script:StepIndex = 0
$transcriptPath = Join-Path $artifactRoot "transcript.txt"
Start-Transcript -Path $transcriptPath -Force | Out-Null

try {
Write-Host "CivicCast 3.2 LPM contract-lab local CI"
Write-Host "Repo: $repoRoot"
Write-Host "Artifacts: $artifactRoot"
Write-Host "Policy: local only; no push, no merge, no tag"
$env:PYTEST_ADDOPTS = "--basetemp `"$artifactRoot\pytest-tmp`""

Invoke-Checked "Record git status" {
    Invoke-Python @(
        "scripts/collect_source_state.py",
        "--artifact-root",
        $artifactRoot
    )
}

Invoke-Checked "Verify runner is local-only" {
    $publishPatterns = @("git\s+pu" + "sh", "git\s+mer" + "ge", "git\s+ta" + "g", "gh\s+pr", "gh\s+release")
    $scriptLines = Get-Content -LiteralPath $PSCommandPath | Where-Object {
        $_ -notmatch '^\s*#' -and $_ -notmatch 'publishPatterns'
    }
    foreach ($line in $scriptLines) {
        foreach ($pattern in $publishPatterns) {
            if ($line -match $pattern) {
                Write-Host "Forbidden publish command found in runner: $line"
                cmd /c "exit 1"
                return
            }
        }
    }
    cmd /c "exit 0"
}

Invoke-Checked "Whitespace check" {
    Test-TrackedAndUntrackedWhitespace
}

Invoke-Checked "Python LPM lab tests" {
    Invoke-Python @(
        "-m",
        "pytest",
        "-q",
        "tests/control_room/test_lpm_lab_profiles.py",
        "tests/control_room/test_lpm_lab_harness.py",
        "tests/control_room/test_lpm_lab_stage45.py",
        "tests/control_room/test_lpm_lab_stage67.py",
        "tests/control_room/test_lpm_lab_stage8.py",
        "tests/control_room/test_lpm_lab_wall_clock_soak.py"
    )
}

Invoke-Checked "First-run attestation tests" {
    Invoke-Python @(
        "-m",
        "pytest",
        "-q",
        "tests/installer/test_isolated_first_run_attestation.py"
    )
}

Invoke-Checked "Virtual Media Studio tests" {
    Invoke-Python @(
        "-m",
        "pytest",
        "-q",
        "tests/tools/test_virtual_media_studio.py"
    )
}

Invoke-Checked "Virtual Media Studio type checks" {
    Invoke-Python @(
        "-m",
        "mypy",
        "tools/virtual-media-studio"
    )
}

Invoke-Checked "Broader control-room schema tests" {
    Invoke-Python @(
        "-m",
        "pytest",
        "-q",
        "tests/control_room",
        "tests/test_openapi_artifacts.py",
        "tests/test_openapi_artifacts_v11.py",
        "tests/test_schema_check.py",
        "tests/test_schema_fidelity.py"
    )
}

Invoke-Checked "Python scoped coverage artifact (no threshold)" {
    $coverageRoot = Join-Path $artifactRoot "coverage"
    New-Item -ItemType Directory -Force -Path $coverageRoot | Out-Null
    Write-Host "Coverage output is an artifact-only snapshot; no percentage threshold is enforced by this local runner."
    Invoke-Python @(
        "-m",
        "pytest",
        "-q",
        "--cov=civiccast",
        "--cov-report=xml:$coverageRoot/coverage.xml",
        "--cov-report=html:$coverageRoot/html",
        "--cov-report=term-missing",
        "tests/control_room",
        "tests/installer/test_isolated_first_run_attestation.py",
        "tests/tools/test_virtual_media_studio.py",
        "tests/test_openapi_artifacts.py",
        "tests/test_openapi_artifacts_v11.py",
        "tests/test_schema_check.py",
        "tests/test_schema_fidelity.py"
    )
}

Invoke-Checked "Portal control-room focused tests" {
    & npm.cmd --prefix "civiccast/apps/portal-operator" run test:unit -- --run ControlRoomScreen.test.tsx ControlRoomSetupScreen.test.tsx ControlRoomReadinessPanel.test.tsx
}

Invoke-Checked "Portal full unit tests" {
    & npm.cmd --prefix "civiccast/apps/portal-operator" run test:unit
}

Invoke-Checked "Portal production build" {
    & npm.cmd --prefix "civiccast/apps/portal-operator" run build
}

Invoke-Checked "Portal lint" {
    & npm.cmd --prefix "civiccast/apps/portal-operator" run lint
}

Invoke-Checked "Portal control-room Playwright a11y" {
    $playwrightResults = Join-Path $repoRoot "civiccast/apps/portal-operator/test-results"
    $playwrightReport = Join-Path $repoRoot "civiccast/apps/portal-operator/playwright-report"
    Remove-Item -LiteralPath $playwrightResults -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $playwrightReport -Recurse -Force -ErrorAction SilentlyContinue
    $env:CIVICAST_KEEP_PASSING_UI_EVIDENCE = "1"
    try {
        & npm.cmd --prefix "civiccast/apps/portal-operator" run test:a11y -- e2e/control-room-readiness.spec.ts
    } finally {
        Remove-Item Env:CIVICAST_KEEP_PASSING_UI_EVIDENCE -ErrorAction SilentlyContinue
    }
    $evidenceRoot = Join-Path $artifactRoot "portal-control-room-playwright-evidence"
    Copy-DirectorySnapshot -Source $playwrightResults -Destination (Join-Path $evidenceRoot "test-results")
    Copy-DirectorySnapshot -Source $playwrightReport -Destination (Join-Path $evidenceRoot "playwright-report")
}

Invoke-Checked "Portal full-stack browser tests" {
    $playwrightResults = Join-Path $repoRoot "civiccast/apps/portal-operator/test-results"
    $playwrightReport = Join-Path $repoRoot "civiccast/apps/portal-operator/playwright-report"
    Remove-Item -LiteralPath $playwrightResults -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $playwrightReport -Recurse -Force -ErrorAction SilentlyContinue
    $env:CIVICAST_KEEP_PASSING_UI_EVIDENCE = "1"
    $oldCi = $env:CI
    $env:CI = "1"
    try {
        & npm.cmd --prefix "civiccast/apps/portal-operator" run test:fullstack
    } finally {
        Remove-Item Env:CIVICAST_KEEP_PASSING_UI_EVIDENCE -ErrorAction SilentlyContinue
        if ($null -eq $oldCi) {
            Remove-Item Env:CI -ErrorAction SilentlyContinue
        } else {
            $env:CI = $oldCi
        }
    }
    $evidenceRoot = Join-Path $artifactRoot "portal-fullstack-playwright-evidence"
    Copy-DirectorySnapshot -Source $playwrightResults -Destination (Join-Path $evidenceRoot "test-results")
    Copy-DirectorySnapshot -Source $playwrightReport -Destination (Join-Path $evidenceRoot "playwright-report")
}

Invoke-Checked "Run LPM contract lab" {
    $labRoot = Join-Path $artifactRoot "contract-lab"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "all",
        "--artifact-root",
        $labRoot,
        "--force-clean"
    )
}

Invoke-Checked "Run Virtual Media Studio smoke" {
    $labRoot = Join-Path $artifactRoot "virtual-media-studio-smoke"
    Invoke-Python @(
        "tools/virtual-media-studio/civiccast-vstudio.py",
        "run",
        "--profile",
        "all",
        "--scenario",
        "smoke",
        "--artifact-root",
        $labRoot,
        "--force-clean"
    )
}

Invoke-Checked "Prepare local OBS websocket software lab" {
    Start-LocalObsWebSocketLab
}

Invoke-Checked "Run Virtual Media Studio software probes" {
    $labRoot = Join-Path $artifactRoot "virtual-media-studio-probes"
    Invoke-Python @(
        "tools/virtual-media-studio/civiccast-vstudio.py",
        "probe",
        "all",
        "--artifact-root",
        $labRoot,
        "--force-clean"
    )
}

Invoke-Checked "Run Stage 4-5 executable fixtures and software probes" {
    $labRoot = Join-Path $artifactRoot "contract-lab-stage45"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "all",
        "--artifact-root",
        $labRoot,
        "--execution-stage",
        "stage45",
        "--force-clean",
        "--probe-real-software"
    )
}

Invoke-Checked "Run Stage 4 OBS software proof hard gate" {
    $labRoot = Join-Path $artifactRoot "contract-lab-stage45-obs"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "digitization-obs",
        "--artifact-root",
        $labRoot,
        "--execution-stage",
        "stage45",
        "--force-clean",
        "--probe-real-software",
        "--require-software-lab"
    )
}

Invoke-Checked "Run Stage 4 all-profile OBS and vMix software proof hard gate" {
    $labRoot = Join-Path $artifactRoot "contract-lab-stage45-all-software"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "all",
        "--artifact-root",
        $labRoot,
        "--execution-stage",
        "stage45",
        "--force-clean",
        "--probe-real-software",
        "--require-software-lab"
    )
}

Invoke-Checked "Run Stage 6-7 soak and station-readiness rehearsal" {
    $labRoot = Join-Path $artifactRoot "contract-lab-stage67"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "all",
        "--artifact-root",
        $labRoot,
        "--execution-stage",
        "stage67",
        "--force-clean",
        "--probe-real-software"
    )
}

Invoke-Checked "Run Stage 8 local release-hardening package" {
    $labRoot = Join-Path $artifactRoot "contract-lab-stage8"
    Invoke-Python @(
        "scripts/run_lpm_contract_lab.py",
        "--profile",
        "all",
        "--artifact-root",
        $labRoot,
        "--execution-stage",
        "stage8",
        "--force-clean",
        "--probe-real-software"
    )
}

Write-Step "Complete"
Write-Host "Local 3.2 LPM contract-lab runner completed."
Write-Host "Artifacts: $artifactRoot"

$summary = [ordered]@{
    run_id = $runId
    repo = "$repoRoot"
    branch = (& git branch --show-current)
    head = (& git rev-parse HEAD).Trim()
    dirty = ((& git status --porcelain=v1 -uall) -join "").Trim().Length -gt 0
    source_state = (Get-Content -Raw -LiteralPath (Join-Path $artifactRoot "source-state.json") | ConvertFrom-Json)
    artifact_root = "$artifactRoot"
    result = "passed"
    completed_at = (Get-Date).ToString("o")
}
$summary | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $artifactRoot "summary.json") -Encoding utf8
} finally {
    Restore-LocalObsWebSocketLab
    Stop-Transcript | Out-Null
}
