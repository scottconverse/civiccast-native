# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 2 operator workflow proof runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_stage2_operator_workflow_proof as stage2
from scripts.run_stage2_operator_workflow_proof import build_stage2_operator_workflow_proof


def test_stage2_operator_workflow_proof_covers_daily_station_path(tmp_path: Path) -> None:
    report = build_stage2_operator_workflow_proof(tmp_path)

    assert report["summary"]["channels"] == 3
    assert report["summary"]["scheduled_items"] >= 9
    assert report["summary"]["recording_sources"] >= 8
    assert report["summary"]["as_run_entries"] >= 9
    assert report["summary"]["support_bundle_files"] >= 6
    assert report["summary"]["failure_drills"] >= 4
    checks_by_id = {check["id"]: check["status"] for check in report["checks"]}
    # Exact expectations for the 9 environment-independent checks:
    # live-ui-api-workflow and live-failure-scenarios are always "not-run"
    # (no automated live rehearsal or failure-injection drill exists yet),
    # so the overall status is always honestly "blocked".
    assert checks_by_id == {
        "every-screen-walkthrough": checks_by_id["every-screen-walkthrough"],
        "three-channel-station": "passed",
        "media-library-and-playout": "passed",
        "live-ui-api-workflow": "not-run",
        "recording-and-ingest": "passed",
        "generated-media-record-stop-output": "passed",
        "as-run-and-proof": "passed",
        "live-failure-scenarios": "not-run",
        "failure-visibility": "passed",
        "support-bundle": "passed",
    }
    assert report["status"] == "blocked"
    # every-screen-walkthrough is derived from the real Playwright run in this
    # environment ("passed" with the toolchain installed, "not-run" without);
    # cross-check it against the walkthrough artifact instead of hardcoding.
    walkthrough = json.loads(
        (tmp_path / "support-bundle" / "every-screen-walkthrough.json").read_text(encoding="utf-8")
    )
    assert checks_by_id["every-screen-walkthrough"] == walkthrough["status"]
    assert walkthrough["status"] in {"passed", "not-run"}, walkthrough
    if walkthrough["status"] == "passed":
        assert walkthrough["expected"] > 0
        assert walkthrough["unexpected"] == 0
    assert any("live end-to-end operator rehearsal" in claim for claim in report["not_claimed"])

    support_manifest = tmp_path / "support-bundle" / "manifest.json"
    assert support_manifest.exists()
    payload = json.loads(support_manifest.read_text(encoding="utf-8"))
    assert payload["redaction"] == "secrets omitted"
    assert set(payload["included"]) >= {
        "station-workflow.json",
        "as-run-ledger.json",
        "recording-jobs.json",
        "every-screen-walkthrough.json",
        "live-workflow-rehearsal.json",
        "failure-drills.json",
        "operator-action-list.md",
        "failure-matrix.json",
        "proof-summary.md",
    }


def test_stage2_reports_not_run_when_e2e_toolchain_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The every-screen walkthrough must not claim "passed" just because no
    Playwright toolchain is installed — it must say so honestly."""

    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    result = stage2._run_operator_e2e_suite(Path("does/not/matter"), tmp_path / "report.json")

    assert result["status"] == "not-run"
    assert "node_modules" in result["reason"]


def test_stage2_walkthrough_derives_from_real_e2e_result() -> None:
    fake_result = {"status": "passed", "expected": 200, "unexpected": 0, "specs": []}

    walkthrough = stage2._every_screen_walkthrough(fake_result)

    assert walkthrough["status"] == "passed"
    assert walkthrough["expected"] == 200
    assert "route-table-smoke" in walkthrough["source"]
