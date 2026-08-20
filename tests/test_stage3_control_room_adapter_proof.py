# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 3 control-room adapter proof runner."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage3_control_room_adapter_proof import build_stage3_control_room_adapter_proof


def test_stage3_control_room_adapter_proof_covers_core_adapter_family(
    tmp_path: Path,
) -> None:
    report = build_stage3_control_room_adapter_proof(tmp_path)

    assert report["status"] == "passed"
    assert report["summary"] == {
        "devices": 12,
        "cues": 14,
        "dry_run_plans": 14,
        "test_mode_events": 14,
        "on_air_events": 5,
        "adapter_contracts": 9,
        "failure_modes": 14,
        "audit_records": 19,
    }
    assert report["checks"] == [
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

    support_manifest = tmp_path / "support-bundle" / "manifest.json"
    assert support_manifest.exists()
    manifest = json.loads(support_manifest.read_text(encoding="utf-8"))
    assert manifest["redaction"] == "secrets omitted"
    assert set(manifest["included"]) >= {
        "device-inventory.json",
        "cue-plans.json",
        "cue-audit.json",
        "adapter-contracts.json",
        "failure-matrix.json",
        "operator-action-list.md",
    }
