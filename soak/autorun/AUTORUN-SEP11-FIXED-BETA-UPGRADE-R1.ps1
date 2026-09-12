# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
$ErrorActionPreference='Stop'
$package=Join-Path (Split-Path $PSScriptRoot -Parent) 'fixed-beta\39e7ec3c'
& (Join-Path $package 'Invoke-FixedBetaTesterUpgrade.ps1') -PackageRoot $package
