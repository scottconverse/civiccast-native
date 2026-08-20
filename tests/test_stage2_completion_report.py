# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 2 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage2_completion_report import build_stage2_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "status": status,
        "source_state": {
            "branch": "local/3.3-stage2-operator-workflow-media-recording",
            "head": head,
            "dirty": dirty,
            "status": " M civiccast/example.py" if dirty else "",
        },
        "summary": {
            "channels": 3,
            "scheduled_items": 18,
            "recording_sources": 8,
            "as_run_entries": 18,
            "support_bundle_files": 6,
            "route_observations": 10,
            "live_workflow_events": 12,
            "failure_drills": 4,
        },
        "checks": [
            {"id": "every-screen-walkthrough", "status": "passed"},
            {"id": "three-channel-station", "status": "passed"},
            {"id": "media-library-and-playout", "status": "passed"},
            {"id": "live-ui-api-workflow", "status": "passed"},
            {"id": "recording-and-ingest", "status": "passed"},
            {"id": "generated-media-record-stop-output", "status": "passed"},
            {"id": "as-run-and-proof", "status": "passed"},
            {"id": "live-failure-scenarios", "status": "passed"},
            {"id": "failure-visibility", "status": "passed"},
            {"id": "support-bundle", "status": "passed"},
        ],
    }


def test_stage2_completion_report_passes_when_operator_proof_is_bound(tmp_path: Path) -> None:
    head = "a" * 40
    proof = tmp_path / "stage2-operator-workflow-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")
    docs = tmp_path / "stage2-operator-workflow.md"
    docs.write_text(
        "\n".join(
            [
                "# Stage 2 Operator Workflow",
                "",
                "three-channel station",
                "media library",
                "recording source",
                "as-run",
                "source-dropout",
                "destination-failure",
                "support bundle",
                "every-screen walkthrough",
                "live workflow rehearsal",
                "record-now",
                "stop recording",
                "failure drill",
            ]
        ),
        encoding="utf-8",
    )

    report = build_stage2_completion_report(
        artifact_root=tmp_path / "report",
        operator_proof=proof,
        operator_docs=docs,
        source_state={"head": head, "dirty": False, "branch": "stage2"},
    )

    assert report["status"] == "passed"
    assert report["summary"] == {
        "channels": 3,
        "scheduled_items": 18,
        "recording_sources": 8,
        "as_run_entries": 18,
        "support_bundle_files": 6,
        "route_observations": 10,
        "live_workflow_events": 12,
        "failure_drills": 4,
    }
    assert report["required_checks"] == [
        {"id": "stage2-current-source", "status": "passed"},
        {"id": "stage2-operator-workflow-proof", "status": "passed"},
        {"id": "stage2-operator-docs", "status": "passed"},
        {"id": "every-screen-walkthrough", "status": "passed"},
        {"id": "three-channel-station", "status": "passed"},
        {"id": "media-library-and-playout", "status": "passed"},
        {"id": "live-ui-api-workflow", "status": "passed"},
        {"id": "recording-and-ingest", "status": "passed"},
        {"id": "generated-media-record-stop-output", "status": "passed"},
        {"id": "as-run-and-proof", "status": "passed"},
        {"id": "live-failure-scenarios", "status": "passed"},
        {"id": "failure-visibility", "status": "passed"},
        {"id": "support-bundle", "status": "passed"},
    ]
    assert (tmp_path / "report" / "stage2-completion-report.json").exists()
    assert (tmp_path / "report" / "stage2-completion-report.md").exists()


def test_stage2_completion_report_blocks_dirty_or_mismatched_operator_proof(
    tmp_path: Path,
) -> None:
    current_head = "b" * 40
    proof = tmp_path / "stage2-operator-workflow-proof.json"
    proof.write_text(
        json.dumps(_proof_payload("c" * 40, dirty=True)),
        encoding="utf-8",
    )

    report = build_stage2_completion_report(
        artifact_root=tmp_path / "report",
        operator_proof=proof,
        operator_docs=tmp_path / "missing-docs.md",
        source_state={"head": current_head, "dirty": False, "branch": "stage2"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert blocked["stage2-operator-workflow-proof"]["notes"]


def test_stage2_completion_report_blocks_current_dirty_source(tmp_path: Path) -> None:
    head = "d" * 40
    proof = tmp_path / "stage2-operator-workflow-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage2_completion_report(
        artifact_root=tmp_path / "report",
        operator_proof=proof,
        operator_docs=tmp_path / "missing-docs.md",
        source_state={
            "head": head,
            "dirty": True,
            "branch": "stage2",
            "status": " M scripts/run_stage2_completion_report.py",
        },
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert blocked["stage2-current-source"]["notes"] == "Current source state is dirty."


def test_stage2_completion_report_blocks_missing_operator_docs(tmp_path: Path) -> None:
    head = "e" * 40
    proof = tmp_path / "stage2-operator-workflow-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage2_completion_report(
        artifact_root=tmp_path / "report",
        operator_proof=proof,
        operator_docs=tmp_path / "missing-docs.md",
        source_state={"head": head, "dirty": False, "branch": "stage2"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert "missing" in blocked["stage2-operator-docs"]["notes"]
