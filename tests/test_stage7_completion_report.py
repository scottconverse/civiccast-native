# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 7 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage7_completion_report import build_stage7_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "stage_id": "4.0-stage7",
        "status": status,
        "source_state": {"head": head, "dirty": dirty, "branch": "stage7"},
        "summary": {
            "prior_stage_reports": 6,
            "prior_gauntlet_reports": 6,
            "stage8_status": "passed",
            "release_artifact_status": "passed",
        },
        "checks": [
            {"id": "stage7-current-source", "status": "passed"},
            {"id": "stage7-prior-stage-reports", "status": "passed"},
            {"id": "stage7-prior-gauntlet-reports", "status": "passed"},
            {"id": "stage7-stage8-local-release-hardening", "status": "passed"},
            {"id": "stage7-release-artifacts", "status": "passed"},
            {"id": "stage7-final-installer-lifecycle", "status": "passed"},
            {"id": "stage7-31-item-scope-matrix", "status": "passed"},
            {"id": "stage7-proof-boundary", "status": "passed"},
        ],
        "scope_item_matrix": [
            {"item": str(item), "status": "passed", "evidence": ["proof"]} for item in range(1, 32)
        ],
    }


def _docs(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Stage 7 Final 4.0 Readiness",
                "Stage 1",
                "Stage 2",
                "Stage 3",
                "Stage 4",
                "Stage 5",
                "Stage 6",
                "Stage 8",
                "GauntletGate",
                "release artifacts",
                "installer",
                "final installer lifecycle",
                "31-item",
                "final readiness",
                "not claimed",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_stage7_completion_report_passes_when_proof_and_docs_are_bound(tmp_path: Path) -> None:
    head = "a" * 40
    proof = tmp_path / "stage7-final-readiness-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage7_completion_report(
        artifact_root=tmp_path / "report",
        final_readiness_proof=proof,
        operator_docs=_docs(tmp_path / "stage7.md"),
        source_state={"head": head, "dirty": False, "branch": "stage7"},
    )

    assert report["status"] == "passed"
    assert (tmp_path / "report" / "stage7-completion-report.json").is_file()


def test_stage7_completion_report_blocks_mismatched_proof(tmp_path: Path) -> None:
    proof = tmp_path / "stage7-final-readiness-proof.json"
    proof.write_text(json.dumps(_proof_payload("b" * 40, dirty=True)), encoding="utf-8")

    report = build_stage7_completion_report(
        artifact_root=tmp_path / "report",
        final_readiness_proof=proof,
        operator_docs=_docs(tmp_path / "stage7.md"),
        source_state={"head": "c" * 40, "dirty": False, "branch": "stage7"},
    )

    assert report["status"] == "blocked"
