# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Wall-clock LPM soak runner tests."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.run_lpm_contract_lab_wall_clock_soak import (
    MARKER,
    SoakConfig,
    run_wall_clock_soak,
)


@dataclass
class FakeClock:
    monotonic_seconds: float = 0.0
    wall_seconds: int = 0

    def monotonic(self) -> float:
        return self.monotonic_seconds

    def sleep(self, seconds: float) -> None:
        self.monotonic_seconds += seconds
        self.wall_seconds += int(seconds)

    def wall_clock(self) -> datetime:
        return datetime(2026, 7, 2, tzinfo=UTC) + timedelta(seconds=self.wall_seconds)


def _fake_result(status: str = "passed", issues: list[str] | None = None) -> Any:
    return SimpleNamespace(
        status=status,
        execution_stage="stage8",
        profiles=["fixed-studio-livestreaming", "portable-field-kit", "digitization-obs"],
        events=[object(), object()],
        issues=issues or [],
    )


def test_wall_clock_soak_runs_until_requested_duration(tmp_path: Path) -> None:
    fake_clock = FakeClock()
    calls: list[dict[str, Any]] = []

    def fake_runner(**kwargs: Any) -> Any:
        calls.append(kwargs)
        fake_clock.monotonic_seconds += 0.25
        return _fake_result()

    summary = run_wall_clock_soak(
        SoakConfig(
            artifact_root=tmp_path,
            duration_seconds=10,
            interval_seconds=3,
            profiles=["all"],
            probe_real_software=True,
            require_software_lab=True,
        ),
        lab_runner=fake_runner,
        clock=fake_clock.monotonic,
        sleeper=fake_clock.sleep,
        wall_clock=fake_clock.wall_clock,
    )

    assert summary["status"] == "passed"
    assert summary["elapsed_seconds"] >= 10
    assert summary["cycle_count"] >= 4
    assert summary["passed_cycle_count"] == summary["cycle_count"]
    assert summary["failed_cycle_count"] == 0
    assert (tmp_path / MARKER).is_file()
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "README.md").is_file()
    assert all(call["execution_stage"] == "stage8" for call in calls)
    assert all(call["probe_real_software"] is True for call in calls)
    assert all(call["require_software_lab"] is True for call in calls)
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["status"] == "passed"


def test_wall_clock_soak_fails_when_a_cycle_fails(tmp_path: Path) -> None:
    fake_clock = FakeClock()
    calls = 0

    def fake_runner(**_: Any) -> Any:
        nonlocal calls
        calls += 1
        fake_clock.monotonic_seconds += 0.25
        if calls == 2:
            return _fake_result(status="failed", issues=["software probe failed"])
        return _fake_result()

    summary = run_wall_clock_soak(
        SoakConfig(artifact_root=tmp_path, duration_seconds=5, interval_seconds=2),
        lab_runner=fake_runner,
        clock=fake_clock.monotonic,
        sleeper=fake_clock.sleep,
        wall_clock=fake_clock.wall_clock,
    )

    assert summary["status"] == "failed"
    assert summary["failed_cycle_count"] == 1
    assert any("cycle 2 status was failed" in issue for issue in summary["issues"])
    assert any("software probe failed" in issue for issue in summary["issues"])


def test_wall_clock_soak_refuses_unmarked_force_clean(tmp_path: Path) -> None:
    (tmp_path / "existing.txt").write_text("do not delete me\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not marked"):
        run_wall_clock_soak(
            SoakConfig(
                artifact_root=tmp_path,
                duration_seconds=1,
                interval_seconds=1,
                force_clean=True,
            ),
            lab_runner=lambda **_: _fake_result(),
        )


def test_wall_clock_soak_cli_help() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab_wall_clock_soak.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--duration-seconds" in result.stdout
    assert "Default: 14400 seconds" in result.stdout
    assert "hours" in result.stdout
