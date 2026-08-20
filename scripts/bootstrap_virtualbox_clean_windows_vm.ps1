# SPDX-License-Identifier: Apache-2.0
# Prepare a non-admin Windows VirtualBox guest for CivicCast cleanroom tests.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$tools = Join-Path $env:USERPROFILE "Tools"
$downloads = Join-Path $tools "downloads"
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

function Get-File {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [string]$OutFile
    )

    if (Test-Path $OutFile) {
        Write-Host "Using existing $OutFile"
        return
    }

    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
}

function Add-UserPath {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )

    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    foreach ($path in $Paths) {
        if ($currentUserPath -notlike "*$path*") {
            $currentUserPath = if ($currentUserPath) { "$currentUserPath;$path" } else { $path }
        }
    }
    [Environment]::SetEnvironmentVariable("Path", $currentUserPath, "User")
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $currentUserPath
}

Write-Host "CivicCast VM bootstrap started $(Get-Date -Format o)"

$gitInstaller = Join-Path $downloads "PortableGit-2.54.0-64-bit.7z.exe"
Get-File `
    -Url "https://github.com/git-for-windows/git/releases/download/v2.54.0.windows.1/PortableGit-2.54.0-64-bit.7z.exe" `
    -OutFile $gitInstaller

$gitDir = Join-Path $tools "Git"
if (-not (Test-Path (Join-Path $gitDir "cmd\git.exe"))) {
    Write-Host "Extracting PortableGit"
    Remove-Item -Recurse -Force $gitDir -ErrorAction SilentlyContinue
    $gitArgs = "-y -o`"$gitDir`""
    $process = Start-Process -FilePath $gitInstaller -ArgumentList $gitArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "PortableGit extraction failed with exit code $($process.ExitCode)"
    }
}

$pythonInstaller = Join-Path $downloads "python-3.12.10-amd64.exe"
Get-File `
    -Url "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" `
    -OutFile $pythonInstaller

$pythonDir = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"
if (-not (Test-Path (Join-Path $pythonDir "python.exe"))) {
    Write-Host "Installing Python per-user"
    $pythonArgs = "/quiet InstallAllUsers=0 TargetDir=`"$pythonDir`" PrependPath=1 Include_launcher=0 Include_pip=1 Include_test=0"
    $process = Start-Process -FilePath $pythonInstaller -ArgumentList $pythonArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "Python installer failed with exit code $($process.ExitCode)"
    }
}

$nodeRoot = Join-Path $tools "node-v22"
if (-not (Test-Path (Join-Path $nodeRoot "node.exe"))) {
    $nodeIndex = Invoke-RestMethod "https://nodejs.org/dist/index.json"
    $latestNode = $nodeIndex |
        Where-Object { $_.version -like "v22.*" -and $_.files -contains "win-x64-zip" } |
        Select-Object -First 1
    if (-not $latestNode) {
        throw "Could not find latest Node v22 win-x64 zip"
    }

    $nodeVersion = $latestNode.version
    $nodeZip = Join-Path $downloads "node-$nodeVersion-win-x64.zip"
    Get-File -Url "https://nodejs.org/dist/$nodeVersion/node-$nodeVersion-win-x64.zip" -OutFile $nodeZip

    Write-Host "Installing Node $nodeVersion from zip"
    $extractRoot = Join-Path $tools "node-extract"
    Remove-Item -Recurse -Force $extractRoot -ErrorAction SilentlyContinue
    Expand-Archive -Path $nodeZip -DestinationPath $extractRoot -Force
    $extractedDir = Get-ChildItem $extractRoot -Directory | Select-Object -First 1
    Move-Item -Force $extractedDir.FullName $nodeRoot
    Remove-Item -Recurse -Force $extractRoot
}

$python = Join-Path $pythonDir "python.exe"
$uv = Join-Path $env:APPDATA "Python\Python312\Scripts\uv.exe"

Add-UserPath -Paths @(
    (Join-Path $gitDir "cmd"),
    $pythonDir,
    (Join-Path $pythonDir "Scripts"),
    (Join-Path $env:APPDATA "Python\Python312\Scripts"),
    $nodeRoot
)

Write-Host "Installing uv"
& $python -m pip install --user --upgrade pip uv
if ($LASTEXITCODE -ne 0) {
    throw "uv install failed with exit code $LASTEXITCODE"
}

Write-Host "Versions:"
& (Join-Path $gitDir "cmd\git.exe") --version
& $python --version
& (Join-Path $nodeRoot "node.exe") --version
& (Join-Path $nodeRoot "npm.cmd") --version
& $uv --version

Write-Host "CivicCast VM bootstrap complete $(Get-Date -Format o)"
