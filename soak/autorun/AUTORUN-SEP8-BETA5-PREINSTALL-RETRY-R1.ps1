# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# One authorized retry of the failed pre-install verification. No blind replay.
[CmdletBinding()]
param([switch] $DryRun)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$dispatcher = Join-Path $PSScriptRoot '..\beta5\retry-install\Invoke-Beta5PreinstallRetry.ps1'
if ($DryRun) { & $dispatcher; return }
& $dispatcher -Execute
