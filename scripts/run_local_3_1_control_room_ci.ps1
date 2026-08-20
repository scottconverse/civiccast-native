# SPDX-License-Identifier: Apache-2.0
# Local-only CivicCast 3.1 control-room runner.
#
# This script is intentionally a local development runner. It must not push,
# merge, tag, open PRs, or mutate the live GitHub beta release stream.

[CmdletBinding()]
param(
    [switch]$DocsOnly,
    [switch]$SkipPython,
    [switch]$SkipWeb,
    [switch]$SkipOpenApi,
    [switch]$IncludeLiveObs,
    [switch]$IncludeLiveVmix,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

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
        & $Body *>&1 | Tee-Object -FilePath $logPath -Append
    } catch {
        $_ | Out-String | Tee-Object -FilePath $logPath -Append
        throw
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
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

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$artifactRoot = Join-Path $repoRoot "artifacts/local-ci/3.1-control-room-$runId"
New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
$script:StepIndex = 0
$transcriptPath = Join-Path $artifactRoot "transcript.txt"
Start-Transcript -Path $transcriptPath -Force | Out-Null

Write-Host "CivicCast 3.1 local control-room CI"
Write-Host "Repo: $repoRoot"
Write-Host "Artifacts: $artifactRoot"
Write-Host "Policy: local only; no push, no merge, no tag"

Invoke-Checked "Record git status" {
    git status --short --branch | Tee-Object -FilePath (Join-Path $artifactRoot "git-status.txt")
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
    git diff --check
}

if (-not $SkipPython -and -not $DocsOnly) {
    Invoke-Checked "Python control-room tests" {
        Invoke-Python @("-m", "pytest", "-q", "tests/control_room")
    }

    Invoke-Checked "Python policy slice" {
        Invoke-Python @("-m", "pytest", "-q", "tests/auth/test_staff_token_lifecycle.py", "tests/platform/test_audit_chain.py")
    }
}

if (-not $SkipOpenApi -and -not $DocsOnly) {
    Invoke-Checked "OpenAPI artifact check" {
        if ($script:PythonExe -eq "uv" -and $script:PythonArgsPrefix.Count -eq 2) {
            cmd.exe /d /c "uv run python scripts/generate-openapi-artifacts.py --check 2>&1"
        } else {
            Invoke-Python @("scripts/generate-openapi-artifacts.py", "--check")
        }
        if ($LASTEXITCODE -eq 0) {
            Write-Host "OpenAPI artifact check passed."
        }
    }
}

if (-not $SkipWeb -and -not $DocsOnly) {
    Invoke-Checked "Operator portal control-room tests" {
        npm.cmd --prefix civiccast/apps/portal-operator run test:unit -- ControlRoom client.test
    }
}

if ($IncludeLiveObs) {
    Invoke-Checked "Live OBS proof placeholder" {
        Write-Host "Live OBS proof is not implemented yet. Add the opt-in test command here when the adapter lands."
        cmd /c "exit 1"
    }
}

if ($IncludeLiveVmix) {
    Invoke-Checked "Live vMix proof placeholder" {
        Write-Host "Live vMix proof is not implemented yet. Add the opt-in test command here when the adapter lands."
        cmd /c "exit 1"
    }
}

Write-Step "Complete"
Write-Host "Local 3.1 control-room runner completed."
Write-Host "Artifacts: $artifactRoot"

$summary = [ordered]@{
    run_id = $runId
    repo = "$repoRoot"
    branch = (& git branch --show-current)
    artifact_root = "$artifactRoot"
    docs_only = [bool]$DocsOnly
    skip_python = [bool]$SkipPython
    skip_web = [bool]$SkipWeb
    skip_openapi = [bool]$SkipOpenApi
    include_live_obs = [bool]$IncludeLiveObs
    include_live_vmix = [bool]$IncludeLiveVmix
    result = "passed"
    completed_at = (Get-Date).ToString("o")
}
$summary | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $artifactRoot "summary.json") -Encoding utf8
Stop-Transcript | Out-Null
