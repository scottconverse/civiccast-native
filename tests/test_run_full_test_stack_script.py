# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Windows full-stack proof runner."""

from __future__ import annotations

from pathlib import Path


def test_full_stack_runner_isolates_pytest_temp_root() -> None:
    script = Path("scripts/run_full_test_stack.ps1").read_text(encoding="utf-8")

    assert "$previousPytestDebugTempRoot = $env:PYTEST_DEBUG_TEMPROOT" in script
    assert (
        '$pytestTempBase = Join-Path ([System.IO.Path]::GetTempPath()) "civiccast-pytest"' in script
    )
    assert "$env:PYTEST_DEBUG_TEMPROOT = Join-Path $pytestTempBase $runId" in script
    assert "New-Item -ItemType Directory -Force -Path $env:PYTEST_DEBUG_TEMPROOT" in script
    assert "$env:PYTEST_DEBUG_TEMPROOT = $previousPytestDebugTempRoot" in script


def test_full_stack_skip_ledger_fails_unknown_skips_closed() -> None:
    script = Path("scripts/run_full_test_stack.ps1").read_text(encoding="utf-8")

    assert '$classification = "required_stage_skip_unclassified"' in script
    assert "$requiredForStage = $true" in script
    assert '$classification = "non_required_environment_bound"' in script
    assert "required_for_stage = $requiredForStage" in script


def test_full_stack_skip_ledger_scope_text_is_stage_neutral() -> None:
    script = Path("scripts/run_full_test_stack.ps1").read_text(encoding="utf-8")

    skip_policy = script[
        script.index("function Read-PytestSkipLedger") : script.index("function Get-SourceState")
    ]
    assert "Stage 1" not in skip_policy
    assert "local gate" in skip_policy


def test_operator_fullstack_runs_serial_for_stable_evidence() -> None:
    script = Path("scripts/run_full_test_stack.ps1").read_text(encoding="utf-8")

    assert "function Invoke-CheckedInDirectory" in script
    assert "Push-Location $WorkingDirectory" in script
    assert "Pop-Location" in script
    assert (
        'Invoke-CheckedInDirectory "civiccast/apps/portal-operator" "npx.cmd" "playwright"'
        in script
    )
    assert '"--grep" "@fullstack" "--project=chromium" "--workers=1"' in script
    assert (
        '"npm.cmd" "--prefix" "civiccast/apps/portal-operator" "run" "test:fullstack"' not in script
    )
