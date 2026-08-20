# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Stage-completion gate (mechanical checks). See
# docs/ops/stage-completion-gate.md for the full gate including the human
# steps (runtime walkthrough + declared environment gaps).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/run_stage_gate.ps1 `
#       -Python <path-to-venv-python> -MypyTargets "civiccast/live civiccast/app.py"

param(
    [string]$Python = "python",
    [string]$MypyTargets = "civiccast",
    [string[]]$PytestExclusions = @(
        "tests/platform/test_nats_broker_real.py",
        "tests/schedule/test_schedule_conflict_properties.py"
    )
)

$ErrorActionPreference = "Continue"
$failures = @()

function Invoke-GateCheck {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: $Name" -ForegroundColor Red
        $script:failures += $Name
    } else {
        Write-Host "PASS: $Name" -ForegroundColor Green
    }
}

Invoke-GateCheck "Full pytest (0 failures; named exclusions only)" {
    $ignores = $PytestExclusions | ForEach-Object { "--ignore=$_" }
    & $Python -m pytest -q @ignores
}

Invoke-GateCheck "Alembic single head" {
    $heads = & $Python -m alembic heads
    Write-Host $heads
    $count = @($heads | Where-Object { $_ -match "\(head\)" }).Count
    if ($count -ne 1) {
        Write-Host "Expected exactly 1 head; found $count."
        cmd /c "exit 1"
    } else {
        cmd /c "exit 0"
    }
}

Invoke-GateCheck "Repo-wide ruff check" {
    & $Python -m ruff check .
}

Invoke-GateCheck "Ruff format check (repo-wide)" {
    & $Python -m ruff format --check .
}

Invoke-GateCheck "Mypy (stage scope: $MypyTargets)" {
    & $Python -m mypy $MypyTargets.Split(" ")
}

Invoke-GateCheck "OpenAPI artifact check" {
    & $Python scripts/generate-openapi-artifacts.py --check
}

Invoke-GateCheck "git diff --check (whitespace)" {
    git diff --check
}

Write-Host ""
Write-Host "Reminder (human gate steps, not run here):" -ForegroundColor Yellow
Write-Host " 7. Runtime walkthrough: boot the deployed app and drive the stage's headline flow over HTTP."
Write-Host " 8. Result file must cite the full-suite count and declare environment gaps (no Docker / no Node / ...)."

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "STAGE GATE FAILED: $($failures -join '; ')" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "STAGE GATE (mechanical checks) PASSED." -ForegroundColor Green
exit 0
