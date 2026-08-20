# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 5 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage5_completion_report import build_stage5_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "stage_id": "3.6-stage5",
        "status": status,
        "source_state": {"head": head, "dirty": dirty, "branch": "stage5"},
        "summary": {
            "migration_files": 8,
            "feature_surfaces": 7,
            "focused_test_status": "passed",
        },
        "checks": [
            {"id": "stage5-current-source", "status": "passed"},
            {"id": "stage5-migration-files", "status": "passed"},
            {"id": "stage5-archive-records", "status": "passed"},
            {"id": "stage5-recording-producer-workflow", "status": "passed"},
            {"id": "stage5-programlog-asrun", "status": "passed"},
            {"id": "stage5-campus-access", "status": "passed"},
            {"id": "stage5-focused-tests", "status": "passed"},
            {"id": "stage5-proof-boundary", "status": "passed"},
        ],
    }


def _docs(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Stage 5 Migration Archive Records Producer Campus",
                "migration",
                "archive",
                "records",
                "recording",
                "producer",
                "agenda",
                "program log",
                "as-run",
                "metadata",
                "paywall",
                "campus",
                "retention",
                "focused tests",
                "station migration execution",
                "not claimed",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_stage5_completion_report_passes_when_proof_and_docs_are_bound(tmp_path: Path) -> None:
    head = "a" * 40
    proof = tmp_path / "stage5-migration-records-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage5_completion_report(
        artifact_root=tmp_path / "report",
        migration_records_proof=proof,
        operator_docs=_docs(tmp_path / "stage5.md"),
        source_state={"head": head, "dirty": False, "branch": "stage5"},
    )

    assert report["status"] == "passed"
    assert (tmp_path / "report" / "stage5-completion-report.json").is_file()
    assert (tmp_path / "report" / "stage5-completion-report.md").is_file()
    assert [check["id"] for check in report["required_checks"]] == [
        "stage5-current-source",
        "stage5-migration-records-proof",
        "stage5-operator-docs",
        "stage5-migration-files",
        "stage5-archive-records",
        "stage5-recording-producer-workflow",
        "stage5-programlog-asrun",
        "stage5-campus-access",
        "stage5-focused-tests",
        "stage5-proof-boundary",
    ]


def test_stage5_completion_report_blocks_mismatched_proof(tmp_path: Path) -> None:
    proof = tmp_path / "stage5-migration-records-proof.json"
    proof.write_text(json.dumps(_proof_payload("b" * 40, dirty=True)), encoding="utf-8")

    report = build_stage5_completion_report(
        artifact_root=tmp_path / "report",
        migration_records_proof=proof,
        operator_docs=_docs(tmp_path / "stage5.md"),
        source_state={"head": "c" * 40, "dirty": False, "branch": "stage5"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert blocked["stage5-migration-records-proof"]["notes"]
