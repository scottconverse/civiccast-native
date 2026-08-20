# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

<#
.SYNOPSIS
Installs Windows accessibility verification tools required by CivicCast release QA.

.DESCRIPTION
CivicCast v0.9 requires a human Windows screen-reader pass with NVDA before
translation/accessibility releases can be called complete. The future
civiccast-installer should call the same winget package id during its Windows
verification-tools step.
#>

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string] $Message)
    Write-Host "[civiccast accessibility-tools] $Message"
}

function Test-Command {
    param([string] $Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command "winget")) {
    throw "winget is required to install NVDA. Install App Installer from Microsoft Store, then rerun this script."
}

$nvdaPath = Join-Path $env:ProgramFiles "NVDA\nvda.exe"
if (Test-Path -LiteralPath $nvdaPath) {
    Write-Step "NVDA already installed at $nvdaPath."
    exit 0
}

Write-Step "Installing NVDA from winget package NVAccess.NVDA."
winget install --id NVAccess.NVDA --exact --silent --accept-package-agreements --accept-source-agreements

if (-not (Test-Path -LiteralPath $nvdaPath)) {
    throw "NVDA installation completed but nvda.exe was not found at $nvdaPath."
}

Write-Step "NVDA installed at $nvdaPath."
