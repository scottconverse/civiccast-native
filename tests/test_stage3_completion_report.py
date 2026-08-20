# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 3 completion report."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage3_completion_report import build_stage3_completion_report


def _proof_payload(head: str, *, status: str = "passed", dirty: bool = False) -> dict:
    return {
        "status": status,
        "source_state": {
            "branch": "local/3.4-stage3-control-room-device-adapters",
            "head": head,
            "dirty": dirty,
            "status": " M civiccast/example.py" if dirty else "",
        },
        "summary": {
            "devices": 12,
            "cues": 14,
            "dry_run_plans": 14,
            "test_mode_events": 14,
            "on_air_events": 5,
            "adapter_contracts": 9,
            "failure_modes": 14,
            "audit_records": 19,
        },
        "checks": [
            {"id": "device-inventory", "status": "passed"},
            {"id": "cue-builder-dry-run-live-fire", "status": "passed"},
            {"id": "test-mode-and-on-air-mode", "status": "passed"},
            {"id": "safe-state-panic-and-rollback", "status": "passed"},
            {"id": "adapter-vmix-http-api", "status": "passed"},
            {"id": "adapter-obs-websocket-5", "status": "passed"},
            {"id": "adapter-atem-simulator", "status": "passed"},
            {"id": "adapter-visca-udp-52381", "status": "passed"},
            {"id": "adapter-ndi-gateway", "status": "passed"},
            {"id": "adapter-decklink-profile", "status": "passed"},
            {"id": "adapter-usb-capture-profile", "status": "passed"},
            {"id": "adapter-audio-layer", "status": "passed"},
            {"id": "adapter-videohub-router", "status": "passed"},
            {"id": "adapter-encoder-headend", "status": "passed"},
            {"id": "audit-and-source-binding", "status": "passed"},
        ],
    }


def _docs(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "# Stage 3 Control Room",
                "device inventory",
                "cue builder",
                "dry run",
                "live fire",
                "Test Mode",
                "On-Air Mode",
                "safe-state panic",
                "rollback",
                "vMix HTTP/API",
                "OBS obs-websocket 5.x",
                "ATEM simulator",
                "PTZ",
                "VISCA",
                "NDI",
                "DeckLink",
                "audio mixer",
                "Videohub",
                "encoder",
                "destination profiles",
                "ndi discovery",
                "usb capture",
                "router",
                "audit",
                "support bundle",
                "keyring",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_stage3_completion_report_passes_when_proof_and_docs_are_bound(
    tmp_path: Path,
) -> None:
    head = "a" * 40
    proof = tmp_path / "stage3-control-room-adapter-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage3_completion_report(
        artifact_root=tmp_path / "report",
        adapter_proof=proof,
        operator_docs=_docs(tmp_path / "stage3-control-room.md"),
        source_state={"head": head, "dirty": False, "branch": "stage3"},
    )

    assert report["status"] == "passed"
    assert report["summary"]["adapter_contracts"] == 9
    assert report["required_checks"] == [
        {"id": "stage3-current-source", "status": "passed"},
        {"id": "stage3-control-room-adapter-proof", "status": "passed"},
        {"id": "stage3-control-room-docs", "status": "passed"},
        {"id": "device-inventory", "status": "passed"},
        {"id": "cue-builder-dry-run-live-fire", "status": "passed"},
        {"id": "test-mode-and-on-air-mode", "status": "passed"},
        {"id": "safe-state-panic-and-rollback", "status": "passed"},
        {"id": "adapter-vmix-http-api", "status": "passed"},
        {"id": "adapter-obs-websocket-5", "status": "passed"},
        {"id": "adapter-atem-simulator", "status": "passed"},
        {"id": "adapter-visca-udp-52381", "status": "passed"},
        {"id": "adapter-ndi-gateway", "status": "passed"},
        {"id": "adapter-decklink-profile", "status": "passed"},
        {"id": "adapter-usb-capture-profile", "status": "passed"},
        {"id": "adapter-audio-layer", "status": "passed"},
        {"id": "adapter-videohub-router", "status": "passed"},
        {"id": "adapter-encoder-headend", "status": "passed"},
        {"id": "audit-and-source-binding", "status": "passed"},
    ]
    assert (tmp_path / "report" / "stage3-completion-report.json").exists()
    assert (tmp_path / "report" / "stage3-completion-report.md").exists()


def test_stage3_completion_report_blocks_dirty_or_mismatched_proof(
    tmp_path: Path,
) -> None:
    proof = tmp_path / "stage3-control-room-adapter-proof.json"
    proof.write_text(json.dumps(_proof_payload("b" * 40, dirty=True)), encoding="utf-8")

    report = build_stage3_completion_report(
        artifact_root=tmp_path / "report",
        adapter_proof=proof,
        operator_docs=_docs(tmp_path / "stage3-control-room.md"),
        source_state={"head": "c" * 40, "dirty": False, "branch": "stage3"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert blocked["stage3-control-room-adapter-proof"]["notes"]


def test_stage3_completion_report_blocks_missing_docs(tmp_path: Path) -> None:
    head = "d" * 40
    proof = tmp_path / "stage3-control-room-adapter-proof.json"
    proof.write_text(json.dumps(_proof_payload(head)), encoding="utf-8")

    report = build_stage3_completion_report(
        artifact_root=tmp_path / "report",
        adapter_proof=proof,
        operator_docs=tmp_path / "missing.md",
        source_state={"head": head, "dirty": False, "branch": "stage3"},
    )

    assert report["status"] == "blocked"
    blocked = {
        check["id"]: check for check in report["required_checks"] if check["status"] == "blocked"
    }
    assert "missing" in blocked["stage3-control-room-docs"]["notes"]
