# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 4 virtual media studio proof."""

from __future__ import annotations

from pathlib import Path

from scripts.run_stage4_virtual_lab_proof import build_stage4_virtual_lab_proof
from scripts.run_stage4_virtual_lab_proof import main as stage4_main


def test_stage4_virtual_lab_proof_wraps_stage45_lab_and_source_state(tmp_path: Path) -> None:
    proof = build_stage4_virtual_lab_proof(
        artifact_root=tmp_path,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage4"},
    )

    # Overall status is honestly "blocked" — several Stage 4-5 required
    # checks (e.g. vmix-api-disabled, usb-audio-present) have no executed
    # fixture yet, and the harness now fails loudly on that instead of
    # silently dropping it (see tests/control_room/test_lpm_lab_stage45.py).
    assert proof["status"] == "blocked"
    assert proof["stage_id"] == "3.5-stage4"
    assert proof["source_state"]["head"] == "a" * 40
    assert proof["lab"]["execution_stage"] == "stage45"
    assert proof["summary"]["profiles"] == 3
    assert proof["summary"]["api_fixture_events"] >= 10
    assert proof["summary"]["stateful_simulator_events"] >= 20
    assert proof["summary"]["software_probe_events"] >= 2
    assert proof["summary"]["bundle_files"] >= 3
    assert proof["not_claimed"]
    assert "station-device evidence" in "\n".join(proof["not_claimed"]).lower()
    assert (tmp_path / "stage4-virtual-lab-proof.json").is_file()
    assert (tmp_path / "lpm-contract-lab" / "summary.json").is_file()
    assert (tmp_path / "virtual-media-studio-bundle" / "vstudio-bundle-manifest.json").is_file()


def test_stage4_virtual_lab_proof_blocks_dirty_source(tmp_path: Path) -> None:
    proof = build_stage4_virtual_lab_proof(
        artifact_root=tmp_path,
        source_state={"head": "b" * 40, "dirty": True, "branch": "stage4"},
    )

    assert proof["status"] == "blocked"
    assert any(check["id"] == "stage4-current-source" for check in proof["checks"])


def test_stage4_cli_records_software_probe_attempts_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    result = stage4_main(["--artifact-root", str(tmp_path)])

    proof = (tmp_path / "stage4-virtual-lab-proof.json").read_text(encoding="utf-8")
    assert result in {0, 1}
    assert '"software_probe_events": 3' in proof
