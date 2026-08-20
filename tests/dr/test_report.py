# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Orchestration + rendering: run_full_drill and render_markdown/write_report."""

from __future__ import annotations

import json
from pathlib import Path

from civiccast.dr.report import render_markdown, run_full_drill, write_report


def test_run_full_drill_passes_end_to_end(seeded_station_db: Path, tmp_path: Path) -> None:
    report = run_full_drill(
        database_url=f"sqlite:///{seeded_station_db}",
        backup_dir=tmp_path / "backup",
        work_dir=tmp_path / "work",
    )

    assert report.ok
    assert report.restore.ok
    assert report.crash.ok
    assert report.honest_notes  # never silently drops the honesty statement


def test_render_markdown_is_two_voice(seeded_station_db: Path, tmp_path: Path) -> None:
    report = run_full_drill(
        database_url=f"sqlite:///{seeded_station_db}",
        backup_dir=tmp_path / "backup",
        work_dir=tmp_path / "work",
    )
    md = render_markdown(report)

    assert "Plain-language verdict" in md
    assert "Technical detail" in md
    assert "PASSED" in md
    assert "Honest boundaries" in md


def test_write_report_produces_readable_markdown_and_valid_json(
    seeded_station_db: Path, tmp_path: Path
) -> None:
    report = run_full_drill(
        database_url=f"sqlite:///{seeded_station_db}",
        backup_dir=tmp_path / "backup",
        work_dir=tmp_path / "work",
    )
    md_path, json_path = write_report(report, tmp_path / "out")

    assert md_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["restore"]["schema_ok"] is True
