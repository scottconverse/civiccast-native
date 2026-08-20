# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI coverage for cable file-package generation."""

from __future__ import annotations

from typer.testing import CliRunner

from civiccast.cli import app


def test_cable_package_cli_outputs_json_result(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    captions = tmp_path / "meeting.vtt"
    media.write_bytes(b"mp4 bytes")
    captions.write_text("WEBVTT\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "cable",
            "package",
            "--asset-id",
            "council-2026-05-08",
            "--title",
            "Council - May 8, 2026",
            "--media",
            str(media),
            "--captions",
            str(captions),
            "--output-dir",
            str(tmp_path / "out"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"status": "ok"' in result.stdout
    assert "council-2026-05-08-cable-package.zip" in result.stdout


def test_cable_ndi_plan_cli_outputs_json_plan(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    media.write_bytes(b"mp4 bytes")

    result = CliRunner().invoke(
        app,
        [
            "cable",
            "ndi-plan",
            "--media",
            str(media),
            "--ndi-name",
            "CivicCast Council Room",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"status": "planned"' in result.stdout
    assert '"proof_boundary": "command-plan-and-runtime-readiness"' in result.stdout
    assert "libndi_newtek" in result.stdout


def test_cable_ndi_plan_cli_reports_actionable_error_without_traceback(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "cable",
            "ndi-plan",
            "--media",
            str(tmp_path / "missing.mp4"),
            "--ndi-name",
            "CivicCast Council Room",
        ],
    )

    assert result.exit_code == 1
    assert "NDI output plan: BLOCKED" in result.stdout
    assert "source media is missing" in result.stdout
    assert "Traceback" not in result.stdout
