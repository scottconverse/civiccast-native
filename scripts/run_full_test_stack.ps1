# SPDX-License-Identifier: Apache-2.0
# Run the CivicCast local proof stack from a prepared Windows host.

[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$SkipWeb,
    [switch]$SkipInstaller,
    [switch]$IncludeDockerCleanroom
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">>> $Message"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$Arguments
    )

    $script:CommandIndex += 1
    $logName = "{0:D2}-{1}.log" -f $script:CommandIndex, (($Command -replace '[^A-Za-z0-9_.-]', '-') -replace '^-+', '')
    $commandLog = Join-Path $script:ArtifactRoot $logName
    $display = "$Command $($Arguments -join ' ')".Trim()
    Write-Host "`$ $display"
    Add-Content -Encoding UTF8 -Path $script:TranscriptPath -Value "`$ $display"

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $Command @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    foreach ($line in $output) {
        $text = "$line"
        Write-Host $text
        Add-Content -Encoding UTF8 -Path $script:TranscriptPath -Value $text
        Add-Content -Encoding UTF8 -Path $commandLog -Value $text
    }
    if ($exitCode -ne 0) {
        throw "Command failed with exit code ${exitCode}: $display"
    }
    return $commandLog
}

function Invoke-CheckedInDirectory {
    param(
        [Parameter(Mandatory=$true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory=$true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$Arguments
    )

    Push-Location $WorkingDirectory
    try {
        return Invoke-Checked $Command @Arguments
    } finally {
        Pop-Location
    }
}

function Read-PytestSkipLedger {
    param([string]$LogPath)
    if (-not $LogPath -or -not (Test-Path -LiteralPath $LogPath)) {
        return @()
    }
    $ledger = @()
    foreach ($line in Get-Content -LiteralPath $LogPath) {
        if ($line -notmatch '^SKIPPED \[(\d+)\] ([^:]+):(\d+): (.+)$') {
            continue
        }
        $count = [int]$Matches[1]
        $path = $Matches[2]
        $reason = $Matches[4]
        $classification = "required_stage_skip_unclassified"
        $requiredForStage = $true
        $equivalentProof = "unclassified skip; treat as required until an explicit local-gate scope policy allows it"
        if ($reason -match "Postgres") {
            $classification = "non_required_environment_bound"
            $requiredForStage = $false
            $equivalentProof = "operator fullstack Playwright and SQLite migration proof cover the local app path; external Postgres remains optional for this local gate"
        } elseif ($reason -match "GStreamer|gst|CC embed") {
            $classification = "non_required_environment_bound"
            $requiredForStage = $false
            $equivalentProof = "this local gate does not claim live GStreamer caption embedding; installed-app and first-run proofs are covered separately"
        } elseif ($reason -match "TSDUCK|network") {
            $classification = "non_required_environment_bound"
            $requiredForStage = $false
            $equivalentProof = "network-gated TSDuck pin verification is not a required local gate capability"
        } elseif ($reason -match "WSL2") {
            $classification = "non_required_environment_bound"
            $requiredForStage = $false
            $equivalentProof = "WSL2 behavior is covered by clean Windows dependency-absent setup proof and WSL2 fresh-user install/import proof"
        } elseif ($reason -match "XDG") {
            $classification = "non_required_environment_bound"
            $requiredForStage = $false
            $equivalentProof = "non-Windows XDG branch is outside the Windows local gate"
        }
        $ledger += [ordered]@{
            count = $count
            path = $path
            reason = $reason
            classification = $classification
            required_for_stage = $requiredForStage
            equivalent_or_scope_evidence = $equivalentProof
        }
    }
    return $ledger
}

function Get-SourceState {
    $json = & uv run python scripts/collect_source_state.py
    if ($LASTEXITCODE -ne 0) {
        throw "Source-state collection failed while writing full-stack summary."
    }
    return $json | ConvertFrom-Json
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$artifactRoot = Join-Path $repoRoot "artifacts/test-runs/$runId"
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$transcriptPath = Join-Path $artifactRoot "transcript.log"
$summaryPath = Join-Path $artifactRoot "summary.json"
$script:ArtifactRoot = $artifactRoot
$script:TranscriptPath = $transcriptPath
$script:CommandIndex = 0
$status = "running"
$failure = $null
$pytestLog = $null

Write-Host "CivicCast test run: $runId"
Write-Host "Artifacts: $artifactRoot"

try {
    if (-not $SkipPython) {
        Write-Step "Python policy, typing, and tests"
        $null = Invoke-Checked "uv" "run" "ruff" "check" "civiccast" "tests"
        $null = Invoke-Checked "uv" "run" "ruff" "format" "--check" "."
        $null = Invoke-Checked "uv" "run" "mypy" "civiccast"
        $previousPytestDebugTempRoot = $env:PYTEST_DEBUG_TEMPROOT
        $pytestTempBase = Join-Path ([System.IO.Path]::GetTempPath()) "civiccast-pytest"
        $env:PYTEST_DEBUG_TEMPROOT = Join-Path $pytestTempBase $runId
        New-Item -ItemType Directory -Force -Path $env:PYTEST_DEBUG_TEMPROOT | Out-Null
        try {
            $pytestLog = Invoke-Checked "uv" "run" "pytest" "-q" "--tb=short"
        } finally {
            $env:PYTEST_DEBUG_TEMPROOT = $previousPytestDebugTempRoot
        }
    }

    if (-not $SkipWeb) {
        Write-Step "Public portal build and Playwright"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-public" "run" "build"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-public" "run" "test:a11y"

        Write-Step "Operator portal build and Playwright"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-operator" "run" "build"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-operator" "run" "test:a11y"
        $null = Invoke-CheckedInDirectory "civiccast/apps/portal-operator" "npx.cmd" "playwright" "test" "--grep" "@fullstack" "--project=chromium" "--workers=1"
    }

    if (-not $SkipInstaller) {
        Write-Step "Installer web shell build and Playwright"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/installer" "run" "build"
        $null = Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/installer" "run" "test:e2e"
    }

    if ($IncludeDockerCleanroom) {
        Write-Step "Docker cleanroom full install gate"
        $null = Invoke-Checked "docker" "build" "-f" "docker/cleanroom.Dockerfile" "-t" "civiccast-cleanroom:latest" "."
        $null = Invoke-Checked "docker" "run" "--rm" `
            "-v" "${repoRoot}:/work/civiccast:ro" `
            "-v" "/var/run/docker.sock:/var/run/docker.sock" `
            "--add-host=host.docker.internal:host-gateway" `
            "civiccast-cleanroom:latest"
    }

    $status = "passed"
} catch {
    $status = "failed"
    $failure = $_.Exception.Message
    throw
} finally {
    $skipLedger = Read-PytestSkipLedger $pytestLog
    [ordered]@{
        run_id = $runId
        status = $status
        generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        repo_root = "$repoRoot"
        artifact_root = "$artifactRoot"
        transcript = "$transcriptPath"
        source_state = Get-SourceState
        skip_python = [bool]$SkipPython
        skip_web = [bool]$SkipWeb
        skip_installer = [bool]$SkipInstaller
        include_docker_cleanroom = [bool]$IncludeDockerCleanroom
        skip_ledger = [ordered]@{
            status = if ($skipLedger.Count -eq 0) { "none" } else { "classified" }
            total_skipped = ($skipLedger | ForEach-Object { $_.count } | Measure-Object -Sum).Sum
            required_skipped = ($skipLedger | Where-Object { $_.required_for_stage } | ForEach-Object { $_.count } | Measure-Object -Sum).Sum
            entries = @($skipLedger)
        }
        failure = $failure
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $summaryPath
}

Write-Step "Complete"
Write-Host "Test stack completed. Artifacts root: $artifactRoot"
