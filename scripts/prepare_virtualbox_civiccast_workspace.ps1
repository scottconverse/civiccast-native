# SPDX-License-Identifier: Apache-2.0
# Clone CivicCast into a prepared Windows VirtualBox guest and install test deps.

[CmdletBinding()]
param(
    [string]$RepoUrl = "https://github.com/scottconverse/civiccast.git",
    [string]$Branch = "main",
    [string]$SourceArchive,
    [string]$WorkRoot = (Join-Path $env:USERPROFILE "CivicCastCleanroom"),
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$tools = Join-Path $env:USERPROFILE "Tools"
$gitDir = Join-Path $tools "Git"
$pythonDir = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"
$nodeRoot = Join-Path $tools "node-v22"
$uv = Join-Path $env:APPDATA "Python\Python312\Scripts\uv.exe"

$env:Path = @(
    (Join-Path $gitDir "cmd"),
    $pythonDir,
    (Join-Path $pythonDir "Scripts"),
    (Join-Path $env:APPDATA "Python\Python312\Scripts"),
    $nodeRoot,
    [Environment]::GetEnvironmentVariable("Path", "Machine"),
    [Environment]::GetEnvironmentVariable("Path", "User")
) -join ";"

$env:GIT_LFS_SKIP_SMUDGE = "1"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

Write-Host "Preparing CivicCast workspace at $WorkRoot"
New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null

$repoDir = Join-Path $WorkRoot "civiccast"
if ($SourceArchive) {
    if (-not (Test-Path $SourceArchive)) {
        throw "Source archive not found: $SourceArchive"
    }

    Write-Host "Expanding source archive $SourceArchive"
    Remove-Item -Recurse -Force $repoDir -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $repoDir | Out-Null
    Expand-Archive -Path $SourceArchive -DestinationPath $repoDir -Force

    $children = Get-ChildItem -Force -Path $repoDir
    if ($children.Count -eq 1 -and $children[0].PSIsContainer -and (Test-Path (Join-Path $children[0].FullName "pyproject.toml"))) {
        $expandedRoot = $children[0].FullName
        Get-ChildItem -Force -Path $expandedRoot | Move-Item -Destination $repoDir
        Remove-Item -Recurse -Force $expandedRoot
    }

    Push-Location $repoDir
    try {
        Invoke-Checked "git" "init"
        Invoke-Checked "git" "config" "user.name" "CivicCast Cleanroom"
        Invoke-Checked "git" "config" "user.email" "cleanroom@example.invalid"
        Invoke-Checked "git" "remote" "add" "origin" $RepoUrl
        Invoke-Checked "git" "checkout" "-B" $Branch
        Invoke-Checked "git" "add" "-A"
        Invoke-Checked "git" "commit" "-m" "Import CivicCast source archive for cleanroom testing"
    }
    finally {
        Pop-Location
    }
}
elseif (Test-Path (Join-Path $repoDir ".git")) {
    Write-Host "Updating existing clone"
    Push-Location $repoDir
    try {
        Invoke-Checked "git" "fetch" "origin" $Branch
        Invoke-Checked "git" "checkout" $Branch
        Invoke-Checked "git" "pull" "--ff-only" "origin" $Branch
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "Cloning $RepoUrl"
    Invoke-Checked "git" "clone" "--branch" $Branch "--single-branch" $RepoUrl $repoDir
}

Push-Location $repoDir
try {
    Invoke-Checked "git" "remote" "-v"
    Invoke-Checked "git" "status" "--short" "--branch"

    if (-not $SkipDependencyInstall) {
        Write-Host "Installing Python dependencies"
        Invoke-Checked $uv "sync" "--all-extras" "--group" "dev"

        foreach ($app in @(
            "civiccast/apps/portal-public",
            "civiccast/apps/portal-operator",
            "civiccast/apps/installer"
        )) {
            Write-Host "Installing Node dependencies for $app"
            Invoke-Checked "npm.cmd" "--prefix" $app "ci" "--no-audit" "--no-fund"
        }

        Write-Host "Installing Playwright Chromium browsers"
        Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/portal-public" "exec" "playwright" "install" "chromium"
        Invoke-Checked "npm.cmd" "--prefix" "civiccast/apps/installer" "exec" "playwright" "install" "chromium"
    }
}
finally {
    Pop-Location
}

Write-Host "CivicCast VM workspace ready: $repoDir"
