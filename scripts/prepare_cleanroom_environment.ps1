# SPDX-License-Identifier: Apache-2.0
# Prepare a local Windows host for CivicCast cleanroom testing.

[CmdletBinding()]
param(
    [switch]$BuildDockerImage,
    [switch]$KeepRepoNodeProcesses
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ">>> $Message"
}

function Require-Command {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command not found: $Name"
    }
    return $command.Source
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments=$true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

Write-Step "Toolchain preflight"
$python = Require-Command "python"
$uv = Require-Command "uv"
$node = Require-Command "node"
$npm = Require-Command "npm.cmd"
$docker = Require-Command "docker"
$cargo = Require-Command "cargo"

Write-Host "repo:   $repoRoot"
Write-Host "python: $python"
Invoke-Checked "python" "--version"
Write-Host "uv:     $uv"
Invoke-Checked "uv" "--version"
Write-Host "node:   $node"
Invoke-Checked "node" "--version"
Write-Host "npm:    $npm"
Invoke-Checked "npm.cmd" "--version"
Write-Host "cargo:  $cargo"
Invoke-Checked "cargo" "--version"
Write-Host "docker: $docker"

Write-Step "Docker daemon preflight"
try {
    docker version | Out-Host
} catch {
    $dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktop) {
        Write-Host "Docker daemon is not reachable. Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        $ready = $false
        foreach ($attempt in 1..24) {
            Start-Sleep -Seconds 5
            try {
                docker version | Out-Null
                $ready = $true
                break
            } catch {
                Write-Host "Waiting for Docker Desktop ($attempt/24)..."
            }
        }
        if (-not $ready) {
            throw "Docker Desktop did not become ready within 2 minutes."
        }
        docker version | Out-Host
    } else {
        throw "Docker daemon is not reachable and Docker Desktop was not found."
    }
}

Write-Step "Python environment sync"
Invoke-Checked "uv" "sync" "--all-extras" "--group" "dev"

Write-Step "Node dependency sync"
if (-not $KeepRepoNodeProcesses) {
    $repoNodeProcesses = Get-CimInstance Win32_Process -Filter "name = 'node.exe'" |
        Where-Object { $_.CommandLine -like "*$repoRoot*" }
    foreach ($process in $repoNodeProcesses) {
        Write-Host "Stopping stale repo Node process: $($process.ProcessId)"
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$apps = @(
    "civiccast/apps/portal-public",
    "civiccast/apps/portal-operator",
    "civiccast/apps/installer"
)
foreach ($app in $apps) {
    Write-Host "npm ci: $app"
    Invoke-Checked "npm.cmd" "--prefix" $app "ci" "--no-audit" "--no-fund"
}

Write-Step "Playwright browser install"
Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-public" "exec" "--" "playwright" "install" "chromium"
Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/installer" "exec" "--" "playwright" "install" "chromium"

if ($BuildDockerImage) {
    Write-Step "Docker cleanroom image build"
    Invoke-Checked "docker" "build" "-f" "docker/cleanroom.Dockerfile" "-t" "civiccast-cleanroom:latest" "."
}

Write-Step "Cleanroom host status"
$vmCommands = @("New-VM", "vmconnect", "WindowsSandbox.exe", "VBoxManage")
foreach ($name in $vmCommands) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        Write-Host "${name}: $($cmd.Source)"
    } else {
        Write-Host "${name}: not available"
    }
}

Write-Host ""
Write-Host "Environment prep complete."
Write-Host "Next Linux/Docker cleanroom run:"
Write-Host "  docker run --rm -v `"${repoRoot}:/work/civiccast:ro`" -v /var/run/docker.sock:/var/run/docker.sock --add-host=host.docker.internal:host-gateway civiccast-cleanroom:latest"
