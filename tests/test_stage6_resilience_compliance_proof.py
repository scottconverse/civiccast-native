# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 6 resilience/compliance proof."""

from __future__ import annotations

from pathlib import Path

from scripts.run_stage6_resilience_compliance_proof import build_stage6_resilience_compliance_proof


def test_stage6_proof_covers_resilience_compliance_and_soak_surfaces(tmp_path: Path) -> None:
    proof = build_stage6_resilience_compliance_proof(
        artifact_root=tmp_path,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage6"},
        test_result={"status": "passed", "command": "pytest stage6", "log": "pytest.log"},
    )

    # Overall status and stage67_lab_status are honestly "blocked"/"failed"
    # because several Stage 4-5 required checks (vmix-*, usb-audio-*, ptz-*,
    # etc.) have no executed fixture yet — fail-loud by design (see
    # test_lpm_lab_stage45.py). Assert the literal honest values so a
    # regression back to a fabricated pass fails this test.
    assert proof["status"] == "blocked"
    assert proof["summary"]["stage67_lab_status"] == "failed"
    assert proof["stage_id"] == "3.8-stage6"
    assert proof["summary"]["feature_surfaces"] >= 7
    assert proof["summary"]["focused_test_status"] == "passed"
    assert {check["id"] for check in proof["checks"]} >= {
        "stage6-current-source",
        "stage6-traffic-headend",
        "stage6-redundancy-recovery",
        "stage6-accessibility-captions",
        "stage6-security-hardening",
        "stage6-eas-compliance",
        "stage6-soak-stress",
        "stage6-focused-tests",
        "stage6-proof-boundary",
    }
    assert "legal caption compliance" in "\n".join(proof["not_claimed"]).lower()
    assert (tmp_path / "stage6-resilience-compliance-proof.json").is_file()
    assert (tmp_path / "lpm-stage67" / "stage67-soak-plan.json").is_file()


def test_stage6_proof_blocks_dirty_source_or_missing_tests(tmp_path: Path) -> None:
    proof = build_stage6_resilience_compliance_proof(
        artifact_root=tmp_path,
        source_state={"head": "b" * 40, "dirty": True, "branch": "stage6"},
        test_result={"status": "not-run", "command": "pytest stage6", "log": ""},
    )

    assert proof["status"] == "blocked"
    blocked = {check["id"] for check in proof["checks"] if check["status"] == "blocked"}
    assert {"stage6-current-source", "stage6-focused-tests"}.issubset(blocked)
