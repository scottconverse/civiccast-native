# SPDX-License-Identifier: Apache-2.0
# Heartbeat script for the 4h soak. Called every 30 minutes by the tester
# loop. Writes one JSON file per heartbeat to $Run/heartbeats/ AND commits
# + pushes a "test: soak heartbeat" record to the tester branch.
#
# Inputs (env, set by the parent script):
#   $env:NONCE         - the directive nonce; echoed verbatim.
#   $env:TARGET_COMMIT - the dev-side target commit hash.
#   $env:RUN_ROOT      - $Root\soak-4h-run (heartbeats land here).
#   $env:DIRECTIVE_REPO - $Root\civiccast (the tester worktree).
#   $env:BASE_URL      - http://127.0.0.1:8000.
#   $env:TOKEN         - the staff token (CIVICCAST_STAFF_TOKENS slug).
#
# This script does NOT manage the 30-minute cadence — the parent loop does.

param(
    [Parameter(Mandatory=$true)] [int]$HeartbeatIndex
)

$ErrorActionPreference = "Stop"
$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$FileName = "$Stamp-heartbeat-$HeartbeatIndex-$([guid]::NewGuid().ToString('N')).json"
$LocalOut = Join-Path $env:RUN_ROOT "heartbeats\$FileName"
$RepoRelativeOut = "tester-handoff/v3.0/heartbeats/$FileName"
$RepoOut = Join-Path $env:DIRECTIVE_REPO $RepoRelativeOut
$TesterBranch = "tester/v3.0-finish-line-4h-soak"
$null = New-Item -ItemType Directory -Force -Path (Split-Path $LocalOut -Parent)
$null = New-Item -ItemType Directory -Force -Path (Split-Path $RepoOut -Parent)

# Sample process RSS for every PID we tracked at start.
$Procs = @{}
foreach ($name in @("uvicorn", "ffmpeg", "python")) {
    $list = @()
    foreach ($p in (Get-Process -Name $name -ErrorAction SilentlyContinue)) {
        $list += @{ pid = $p.Id; rss_bytes = $p.WorkingSet64; cpu = $p.CPU }
    }
    $Procs[$name] = $list
}

# Probe /api/health and retain the body for endpoint-shape proof.
$Health = @{ status = "unreachable"; http_status = $null; body = $null; detail = $null }
try {
    $h = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "$env:BASE_URL/api/health"
    $Health.http_status = $h.StatusCode
    $Health.status = if ($h.StatusCode -eq 200) { "pass" } else { "fail" }
    try {
        $Health.body = $h.Content | ConvertFrom-Json
    } catch {
        $Health.body = $h.Content
    }
} catch {
    $Health.status = "fail"
    $Health.detail = $_.Exception.Message
}

# Run the three synthetic-probe shell scripts; collect exit codes.
$ProbeResults = @{}
$ProbesDir = Join-Path $env:DIRECTIVE_REPO "tester-handoff\v3.0\soak-4h\synthetic-probes"

function Resolve-BashRunner {
    $gitBash = "C:\Program Files\Git\bin\bash.exe"
    if (Test-Path $gitBash) {
        return @{ Kind = "git-bash"; Exe = $gitBash }
    }
    # PowerShell Core on Linux exposes the runner as `bash`, while Windows
    # commonly exposes `bash.exe`. Resolve the portable command name first;
    # the System32 compatibility shim is still excluded below.
    $bashCommand = Get-Command bash -ErrorAction SilentlyContinue
    if ($bashCommand -and ($bashCommand.Source -notmatch "\\Windows\\System32\\bash.exe$")) {
        return @{ Kind = "bash"; Exe = $bashCommand.Source }
    }
    $wslCommand = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($wslCommand) {
        return @{ Kind = "wsl"; Exe = $wslCommand.Source }
    }
    throw "No usable bash runner found. Install Git for Windows or WSL."
}

function Convert-PathForBashRunner {
    param(
        [Parameter(Mandatory=$true)] [hashtable]$Runner,
        [Parameter(Mandatory=$true)] [string]$Path
    )
    if ($Runner.Kind -ne "wsl") {
        return $Path
    }
    $converted = & $Runner.Exe wslpath -a $Path 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $converted) {
        throw "Failed to convert Windows path for WSL bash: $Path"
    }
    return ($converted | Select-Object -First 1)
}

foreach ($p in @("paywall.sh", "recording.sh", "agenda.sh")) {
    $path = Join-Path $ProbesDir $p
    if (-not (Test-Path $path)) {
        $ProbeResults[$p] = "missing"
        continue
    }
    if (-not $BashRunner) {
        $BashRunner = Resolve-BashRunner
    }
    $bashPath = Convert-PathForBashRunner -Runner $BashRunner -Path $path
    if ($BashRunner.Kind -eq "wsl") {
        $probeOut = & $BashRunner.Exe bash $bashPath 2>&1
    } else {
        $probeOut = & $BashRunner.Exe $bashPath 2>&1
    }
    $ProbeResults[$p] = @{
        exit_code = $LASTEXITCODE
        runner = $BashRunner.Exe
        output_tail = ($probeOut | Select-Object -Last 5) -join "`n"
    }
}

# Verify the live UDP egress streams and persist a per-channel artifact.
$EgressVerify = @{ status = "missing"; exit_code = $null; output_tail = ""; artifact = $null }
$VerifyScript = Join-Path $env:DIRECTIVE_REPO "tester-handoff\v3.0\soak-4h\scripts\verify-egress.ps1"
if (Test-Path $VerifyScript) {
    $PowerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($PowerShellCommand) {
        $PowerShellExe = $PowerShellCommand.Source
        $PowerShellArgs = @("-NoProfile", "-File", $VerifyScript, "-HeartbeatIndex", "$HeartbeatIndex", "-Stamp", $Stamp)
    } else {
        $PowerShellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
        $PowerShellArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $VerifyScript, "-HeartbeatIndex", "$HeartbeatIndex", "-Stamp", $Stamp)
    }
    $verifyOut = & $PowerShellExe @PowerShellArgs 2>&1
    $verifyExit = $LASTEXITCODE
    $EgressVerify = @{
        status = if ($verifyExit -eq 0) { "pass" } elseif ($verifyExit -eq 2) { "not-run" } else { "fail" }
        exit_code = $verifyExit
        output_tail = ($verifyOut | Select-Object -Last 5) -join "`n"
        artifact = (Join-Path $env:RUN_ROOT "egress-verify\egress-verify-$Stamp.json")
    }
}

$body = @{
    schema = "civiccast-soak-heartbeat-v1"
    nonce = $env:NONCE
    target_commit = $env:TARGET_COMMIT
    heartbeat_index = $HeartbeatIndex
    utc = $Stamp
    health = $Health
    egress_state = $EgressVerify
    processes = $Procs
    probes = $ProbeResults
} | ConvertTo-Json -Depth 6

$LocalTemp = "$LocalOut.tmp"
$RepoTemp = "$RepoOut.tmp"
try {
    Set-Content -LiteralPath $LocalTemp -Value $body -Encoding utf8
    Move-Item -LiteralPath $LocalTemp -Destination $LocalOut -Force
    Copy-Item -LiteralPath $LocalOut -Destination $RepoTemp -Force
    Move-Item -LiteralPath $RepoTemp -Destination $RepoOut -Force
} finally {
    Remove-Item -LiteralPath $LocalTemp, $RepoTemp -Force -ErrorAction SilentlyContinue
}

function Invoke-GitChecked {
    param(
        [Parameter(Mandatory=$true)] [string]$Step,
        [Parameter(Mandatory=$true)] [string[]]$Arguments
    )
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & git @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        $detail = ($output | Select-Object -Last 10) -join "`n"
        throw "$Step failed with exit code $exitCode.`n$detail"
    }
    return @($output)
}

function Get-RemoteBranchSha {
    param([Parameter(Mandatory=$true)] [string]$Branch)
    $remoteRef = "refs/heads/$Branch"
    $lines = Invoke-GitChecked -Step "git ls-remote" -Arguments @(
        "ls-remote", "--heads", "origin", $remoteRef
    )
    $refMatches = @()
    foreach ($line in $lines) {
        $fields = @($line.ToString().Trim() -split "\s+")
        if ($fields.Count -eq 2 -and
            $fields[0] -match "^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$" -and
            $fields[1] -eq $remoteRef) {
            $refMatches += $fields[0].ToLowerInvariant()
        }
    }
    if ($refMatches.Count -ne 1) {
        throw "git ls-remote did not return exactly one valid $remoteRef entry"
    }
    return $refMatches[0]
}

# Commit + push the heartbeat to the tester branch.
Push-Location $env:DIRECTIVE_REPO
try {
    $preCommitHead = Invoke-GitChecked -Step "git rev-parse HEAD" -Arguments @(
        "rev-parse", "HEAD"
    )
    $preCommitSha = ($preCommitHead | Select-Object -First 1).ToString().Trim().ToLowerInvariant()
    $remoteBeforeSha = Get-RemoteBranchSha -Branch $TesterBranch
    if ($preCommitSha -ne $remoteBeforeSha) {
        Remove-Item -LiteralPath $RepoOut -Force -ErrorAction SilentlyContinue
        throw "local HEAD must match origin/$TesterBranch before heartbeat publication; local: $preCommitSha; remote: $remoteBeforeSha"
    }
    $null = Invoke-GitChecked -Step "git add" -Arguments @("add", "--", $RepoRelativeOut)
    $stagedPaths = @(
        Invoke-GitChecked -Step "git diff --cached" -Arguments @(
            "diff", "--cached", "--name-only"
        ) | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ }
    )
    if ($stagedPaths.Count -ne 1 -or $stagedPaths[0] -ne $RepoRelativeOut) {
        $null = Invoke-GitChecked -Step "git reset heartbeat" -Arguments @(
            "reset", "--", $RepoRelativeOut
        )
        Remove-Item -LiteralPath $RepoOut -Force -ErrorAction SilentlyContinue
        throw "heartbeat must be the only staged path; staged: $($stagedPaths -join ', ')"
    }
    $DisabledHooksDir = Join-Path $env:RUN_ROOT ".heartbeat-hooks-disabled-$([guid]::NewGuid().ToString('N'))"
    $null = New-Item -ItemType Directory -Force -Path $DisabledHooksDir
    try {
        $null = Invoke-GitChecked -Step "git commit" -Arguments @(
            "-c", "user.email=tester@msi.local",
            "-c", "user.name=CivicCast Tester",
            "-c", "core.hooksPath=$DisabledHooksDir",
            "commit", "-m", "test: soak heartbeat $Stamp $env:NONCE"
        )
    } finally {
        Remove-Item -LiteralPath $DisabledHooksDir -Force -ErrorAction SilentlyContinue
    }
    $committedPaths = @(
        Invoke-GitChecked -Step "git diff-tree" -Arguments @(
            "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "HEAD"
        ) | ForEach-Object { $_.ToString().Trim() } | Where-Object { $_ }
    )
    if ($committedPaths.Count -ne 1 -or $committedPaths[0] -ne $RepoRelativeOut) {
        throw "heartbeat commit contains unexpected paths: $($committedPaths -join ', ')"
    }
    $expectedBlob = Invoke-GitChecked -Step "git hash-object" -Arguments @(
        "hash-object", "--path", $RepoRelativeOut, $RepoOut
    )
    $committedBlob = Invoke-GitChecked -Step "git rev-parse" -Arguments @(
        "rev-parse", "HEAD:$RepoRelativeOut"
    )
    if (($expectedBlob | Select-Object -First 1).ToString().Trim() -ne
        ($committedBlob | Select-Object -First 1).ToString().Trim()) {
        throw "Committed heartbeat does not match the just-written JSON: $RepoRelativeOut"
    }
    $localHead = Invoke-GitChecked -Step "git rev-parse HEAD" -Arguments @(
        "rev-parse", "HEAD"
    )
    $localSha = ($localHead | Select-Object -First 1).ToString().Trim().ToLowerInvariant()
    try {
        $null = Invoke-GitChecked -Step "git push" -Arguments @(
            "push", "origin", "${localSha}:refs/heads/$TesterBranch"
        )
    } catch {
        $pushFailure = $_
        try {
            $remoteAfterFailure = Get-RemoteBranchSha -Branch $TesterBranch
        } catch {
            throw $pushFailure
        }
        if ($remoteAfterFailure -eq $preCommitSha) {
            $currentHead = Invoke-GitChecked -Step "git rev-parse HEAD after failed push" -Arguments @(
                "rev-parse", "HEAD"
            )
            $currentHeadSha = ($currentHead | Select-Object -First 1).ToString().Trim().ToLowerInvariant()
            if ($currentHeadSha -ne $localSha) {
                throw "local HEAD changed during failed heartbeat push; preserving current: $currentHeadSha; heartbeat: $localSha"
            }
            $null = Invoke-GitChecked -Step "git reset failed heartbeat" -Arguments @(
                "reset", "--mixed", $preCommitSha
            )
            Remove-Item -LiteralPath $RepoOut -Force -ErrorAction SilentlyContinue
            throw $pushFailure
        }
        if ($remoteAfterFailure -ne $localSha) {
            throw "git push failed and origin/$TesterBranch moved to unexpected commit $remoteAfterFailure"
        }
    }
    $remoteSha = Get-RemoteBranchSha -Branch $TesterBranch
    if ($localSha -ne $remoteSha) {
        throw "Pushed heartbeat commit was not verified on origin/$TesterBranch"
    }
} finally {
    Pop-Location
}

Write-Host "heartbeat $HeartbeatIndex written and pushed: origin/${TesterBranch}:$RepoRelativeOut commit $localSha (local: $LocalOut)"
