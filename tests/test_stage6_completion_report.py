# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 6 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage6_completion_report import build_stage6_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "stage_id": "3.8-stage6",
        "status": status,
        "source_state": {"head": head, "dirty": dirty, "branch": "stage6"},
        "summary": {
            "feature_surfaces": 7,
            "stage67_lab_status": "passed",
            "focused_test_status": "passed",
        },
        "checks": [
            {"id": "stage6-current-source", "status": "passed"},
            {"id": "stage6-traffic-headend", "status": "passed"},
            {"id": "stage6-redundancy-recovery", "status": "passed"},
            {"id": "stage6-accessibility-captions", "status": "passed"},
            {"id": "stage6-security-hardening", "status": "passed"},
            {"id": "stage6-eas-compliance", "status": "passed"},
            {"id": "stage6-soak-stress", "status": "passed"},
            {"id": "stage6-focused-tests", "status": "passed"},
            {"id": "stage6-proof-boundary", "status": "passed"},
        ],
    }


def _docs(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Stage 6 Traffic SCTE Redundancy Accessibility Security Soak",
                "traffic",
                "SCTE",
                "headend",
                "redundancy",
                "recovery",
                "disaster",
                "accessibility",
                "captions",
                "EAS",
                "security",
                "auth",
                "soak",
                "stress",
                "focused tests",
                "legal caption compliance",
                "not claimed",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_stage6_completion_report_passes_when_proof_and_docs_are_bound(tmp_path: Path) -> None:
    head = "a" * 40
    proof = tmp_path / "stage6-resilience-compliance-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage6_completion_report(
        artifact_root=tmp_path / "report",
        resilience_compliance_proof=proof,
        operator_docs=_docs(tmp_path / "stage6.md"),
        source_state={"head": head, "dirty": False, "branch": "stage6"},
    )

    assert report["status"] == "passed"
    assert (tmp_path / "report" / "stage6-completion-report.json").is_file()
    assert [check["id"] for check in report["required_checks"]] == [
        "stage6-current-source",
        "stage6-resilience-compliance-proof",
        "stage6-operator-docs",
        "stage6-traffic-headend",
        "stage6-redundancy-recovery",
        "stage6-accessibility-captions",
        "stage6-security-hardening",
        "stage6-eas-compliance",
        "stage6-soak-stress",
        "stage6-focused-tests",
        "stage6-proof-boundary",
    ]


def test_stage6_completion_report_blocks_mismatched_proof(tmp_path: Path) -> None:
    proof = tmp_path / "stage6-resilience-compliance-proof.json"
    proof.write_text(json.dumps(_proof_payload("b" * 40, dirty=True)), encoding="utf-8")

    report = build_stage6_completion_report(
        artifact_root=tmp_path / "report",
        resilience_compliance_proof=proof,
        operator_docs=_docs(tmp_path / "stage6.md"),
        source_state={"head": "c" * 40, "dirty": False, "branch": "stage6"},
    )

    assert report["status"] == "blocked"
