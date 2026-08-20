# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""``civiccast dr run-drill`` CLI: real exit codes, not just importability."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from civiccast.cli import app


def test_run_drill_exits_zero_and_writes_report(seeded_station_db: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "dr",
            "run-drill",
            "--out",
            str(out_dir),
            "--database-url",
            f"sqlite:///{seeded_station_db}",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "PASSED" in result.stdout
    payload = json.loads((out_dir / "dr-drill-report.json").read_text(encoding="utf-8"))
    assert payload["restore"]["schema_ok"] is True


def test_run_drill_rejects_unsupported_scheme(tmp_path: Path) -> None:
    """Postgres is a supported scheme (ws2-postgres-restore); anything else
    (e.g. mysql) still gets an upfront, controlled rejection rather than an
    attempted connection."""
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "dr",
            "run-drill",
            "--out",
            str(tmp_path / "out"),
            "--database-url",
            "mysql://user:pass@localhost/civiccast",
        ],
    )
    assert result.exit_code == 2
    assert "Unsupported DATABASE_URL scheme" in result.stdout


def test_run_drill_requires_a_database_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    runner = CliRunner()
    result = runner.invoke(app, ["dr", "run-drill", "--out", str(tmp_path / "out")])
    assert result.exit_code == 2
    assert "DATABASE_URL" in result.stdout


def test_run_drill_exits_one_on_failure(seeded_station_db: Path, tmp_path: Path) -> None:
    """FALSIFICATION at the CLI layer: a failing drill must exit non-zero.

    A fresh backup always matches its own just-taken snapshot, so a real
    restore-mismatch can't be forced from the outside without corrupting the
    live db mid-drill (racy). Instead this forces the crash-drill leg to
    report failure and confirms the CLI's exit-code/FAILED-banner wiring
    reacts to ``report.ok`` rather than always printing PASSED — the same
    "watch it fail" proof as the module-level tests, at the CLI boundary.
    """
    import civiccast.dr.report as report_module
    from civiccast.dr.models import CrashDrillReport, CrashDrillResult

    real_run_full_drill = report_module.run_full_drill

    def _fake_run_full_drill(**kwargs):  # type: ignore[no-untyped-def]
        report = real_run_full_drill(**kwargs)
        return report.model_copy(
            update={
                "crash": CrashDrillReport(
                    results=[
                        CrashDrillResult(
                            name="daemon_crash_restart",
                            ok=False,
                            detail="forced failure for CLI exit-code test",
                            duration_seconds=0.0,
                        )
                    ]
                )
            }
        )

    # Patched at the source module since civiccast.cli's command body does
    # `from civiccast.dr.report import run_full_drill` at call time.
    report_module.run_full_drill = _fake_run_full_drill  # type: ignore[assignment]
    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "dr",
                "run-drill",
                "--out",
                str(tmp_path / "out2"),
                "--database-url",
                f"sqlite:///{seeded_station_db}",
            ],
        )
    finally:
        report_module.run_full_drill = real_run_full_drill  # type: ignore[assignment]

    assert result.exit_code == 1
    assert "FAILED" in result.stdout
