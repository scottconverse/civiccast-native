# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 4 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage4_completion_report import build_stage4_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "stage_id": "3.5-stage4",
        "status": status,
        "source_state": {"head": head, "dirty": dirty, "branch": "stage4"},
        "summary": {
            "profiles": 3,
            "events": 120,
            "api_fixture_events": 20,
            "stateful_simulator_events": 45,
            "software_probe_events": 3,
            "bundle_files": 5,
        },
        "checks": [
            {"id": "stage4-current-source", "status": "passed"},
            {"id": "stage4-lpm-stage45-lab", "status": "passed"},
            {"id": "stage4-virtual-media-studio-bundle", "status": "passed"},
            {"id": "stage4-proof-boundary", "status": "passed"},
        ],
    }


def _docs(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Stage 4 Virtual Media Studio",
                "virtual media studio",
                "stage 4",
                "stage 4-5",
                "lpm contract lab",
                "OBS",
                "vMix",
                "ATEM",
                "VISCA",
                "NDI",
                "DeckLink",
                "USB capture",
                "software probe",
                "station-device evidence",
                "not claimed",
                "support bundle",
                "reusable bundle",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_stage4_completion_report_passes_when_proof_and_docs_are_bound(tmp_path: Path) -> None:
    head = "a" * 40
    proof = tmp_path / "stage4-virtual-lab-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage4_completion_report(
        artifact_root=tmp_path / "report",
        virtual_lab_proof=proof,
        operator_docs=_docs(tmp_path / "stage4.md"),
        source_state={"head": head, "dirty": False, "branch": "stage4"},
    )

    assert report["status"] == "passed"
    assert report["required_checks"] == [
        {"id": "stage4-current-source", "status": "passed"},
        {"id": "stage4-virtual-lab-proof", "status": "passed"},
        {"id": "stage4-virtual-lab-docs", "status": "passed"},
        {"id": "stage4-lpm-stage45-lab", "status": "passed"},
        {"id": "stage4-virtual-media-studio-bundle", "status": "passed"},
        {"id": "stage4-proof-boundary", "status": "passed"},
    ]
    assert (tmp_path / "report" / "stage4-completion-report.json").is_file()
    assert (tmp_path / "report" / "stage4-completion-report.md").is_file()


def test_stage4_completion_report_blocks_mismatched_or_dirty_proof(tmp_path: Path) -> None:
    proof = tmp_path / "stage4-virtual-lab-proof.json"
    proof.write_text(json.dumps(_proof_payload("b" * 40, dirty=True)), encoding="utf-8")

    report = build_stage4_completion_report(
        artifact_root=tmp_path / "report",
        virtual_lab_proof=proof,
        operator_docs=_docs(tmp_path / "stage4.md"),
        source_state={"head": "c" * 40, "dirty": False, "branch": "stage4"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert blocked["stage4-virtual-lab-proof"]["notes"]
