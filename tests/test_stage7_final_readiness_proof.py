# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 7 final readiness proof."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_stage7_final_readiness_proof import (
    BETA_4_SCOPE_ITEMS,
    _release_manifest_path,
    build_stage7_final_readiness_proof,
)


def _write_stage(path: Path, stage_id: str) -> Path:
    path.mkdir(parents=True)
    (path / f"{stage_id}-completion-report.json").write_text(
        json.dumps({"status": "passed", "source_state": {"head": "a" * 40, "dirty": False}}),
        encoding="utf-8",
    )
    return path / f"{stage_id}-completion-report.json"


def _write_gate(path: Path) -> Path:
    path.mkdir(parents=True)
    report = path / "00-gate-report.md"
    report.write_text(
        "\n".join(
            [
                "Verdict: PASS",
                "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
                "Lanes: lite, walkthrough, full",
                "Skipped/Waived Required Checks: none",
                "Source HEAD: " + "a" * 40,
            ]
        ),
        encoding="utf-8",
    )
    return report


def _write_final_gate(path: Path, head: str = "a" * 40) -> Path:
    path.mkdir(parents=True)
    report = path / "00-gate-report.md"
    report.write_text(
        "\n".join(
            [
                "Verdict: PASS",
                "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
                "Lanes: lite, walkthrough, full",
                "Skipped/Waived Required Checks: none",
                "Source HEAD: " + head,
            ]
        ),
        encoding="utf-8",
    )
    return report


def _write_final_lifecycle(path: Path, head: str = "a" * 40) -> Path:
    checks = [
        "clean-install",
        "first-run",
        "repair",
        "release-artifact-binding",
        "uninstall",
        "reinstall",
        "upgrade",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_state": {"head": head, "dirty": False, "branch": "stage7"},
                "checks": [
                    {
                        "id": check_id,
                        "status": "passed",
                        "evidence": f"artifacts/final-lifecycle/{check_id}.json",
                    }
                    for check_id in checks
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_full_stack(path: Path, head: str = "a" * 40, status: str = "passed") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "source_state": {
                    "head": head,
                    "dirty": False,
                    "branch": "stage7",
                    "status_sha256": "0" * 64,
                    "diff_sha256": "1" * 64,
                    "untracked_content_sha256": "2" * 64,
                },
                "skip_python": False,
                "skip_web": False,
                "skip_installer": False,
                "skip_ledger": {
                    "status": "classified",
                    "total_skipped": 19,
                    "required_skipped": 0,
                    "entries": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_cleanroom(path: Path, head: str = "a" * 40, status: str = "passed") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "source_state": {
                    "head": head,
                    "dirty": False,
                    "branch": "stage7",
                    "status_sha256": "0" * 64,
                    "diff_sha256": "1" * 64,
                    "untracked_content_sha256": "2" * 64,
                },
                "skip_ledger": {
                    "status": "classified",
                    "total_skipped": 19,
                    "required_skipped": 0,
                    "entries": [],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_clean_windows_core(path: Path, head: str = "a" * 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "core_reached",
                "core_feature_reached": True,
                "source_state": {"head": head, "dirty": False, "branch": "stage7"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_upgrade_matrix(path: Path, head: str = "a" * 40) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": "passed",
                "source_head": head,
                "source_state": {
                    "head": head,
                    "dirty": False,
                    "branch": "stage7",
                    "status_sha256": "0" * 64,
                    "diff_sha256": "1" * 64,
                    "untracked_content_sha256": "2" * 64,
                },
                "required_upgrade_origins_from_spec": ["3.0", "3.1", "3.2"],
                "executable_upgrade_origins": ["3.0.0-beta1", "3.2.0-beta1", "3.3.0"],
                "non_applicable_origins": ["3.1"],
                "rows": [
                    {"from_version": "3.0.0-beta1", "status": "passed"},
                    {
                        "from_version": "3.1",
                        "status": "not_applicable",
                        "note": "No CivicCast 3.1 release line was found locally.",
                    },
                    {"from_version": "3.2.0-beta1", "status": "passed"},
                    {"from_version": "3.3.0", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_stage7_final_readiness_aggregates_prior_stages_and_stage8(tmp_path: Path) -> None:
    stage_reports = [_write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)]
    gauntlet_reports = [_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)]
    lifecycle = _write_final_lifecycle(tmp_path / "final-lifecycle.json")
    full_stack = _write_full_stack(tmp_path / "full-stack-summary.json")
    cleanroom = _write_cleanroom(tmp_path / "cleanroom-summary.json")
    final_gate = _write_final_gate(tmp_path / "final-gate")
    clean_windows = _write_clean_windows_core(tmp_path / "clean-windows-rendered.json")
    upgrade_matrix = _write_upgrade_matrix(tmp_path / "upgrade-matrix-proof.json")

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=stage_reports,
        gauntlet_reports=gauntlet_reports,
        final_installer_lifecycle_proof=lifecycle,
        full_stack_evidence=full_stack,
        cleanroom_evidence=cleanroom,
        final_gauntlet_report=final_gate,
        clean_windows_rendered_evidence=clean_windows,
        upgrade_matrix_evidence=upgrade_matrix,
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    # stage8_status is honestly "failed" and scope_items_passed is 27/31 (not
    # 31/31) because several Stage 4-5 required checks (vmix-*, usb-audio-*,
    # ptz-*, etc.) have no executed fixture yet — fail-loud by design (see
    # test_lpm_lab_stage45.py). Assert the literal honest values so a
    # regression back to a fabricated pass fails this test.
    assert proof["status"] == "blocked"
    assert proof["summary"]["stage8_status"] == "failed"
    assert proof["summary"]["scope_items_passed"] == 27
    assert proof["stage_id"] == "4.0-stage7"
    assert proof["summary"]["prior_stage_reports"] == 6
    assert proof["summary"]["prior_gauntlet_reports"] == 6
    assert proof["summary"]["release_artifact_status"] == "passed"
    assert proof["summary"]["final_installer_lifecycle_status"] == "passed"
    assert proof["summary"]["full_stack_status"] == "passed"
    assert proof["summary"]["cleanroom_status"] == "passed"
    assert proof["summary"]["final_gauntlet_status"] == "passed"
    assert proof["summary"]["clean_windows_core_status"] == "passed"
    assert proof["summary"]["upgrade_matrix_status"] == "passed"
    assert proof["summary"]["native_windows_installer_status"] == "not-found"
    assert len(proof["scope_item_matrix"]) == 31
    assert {item["item"] for item in proof["scope_item_matrix"]} == set(BETA_4_SCOPE_ITEMS)
    assert (tmp_path / "final" / "stage8-local-release" / "stage8-release-manifest.json").is_file()
    assert (tmp_path / "final" / "stage7-final-readiness-proof.json").is_file()


def test_stage7_final_readiness_blocks_missing_upgrade_matrix(tmp_path: Path) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    upgrade_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-upgrade-matrix"
    )
    assert proof["status"] == "blocked"
    assert proof["summary"]["upgrade_matrix_status"] == "not-found"
    assert upgrade_check["status"] == "blocked"


def test_stage7_final_readiness_blocks_stale_upgrade_matrix(tmp_path: Path) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        upgrade_matrix_evidence=_write_upgrade_matrix(
            tmp_path / "upgrade-matrix-proof.json", head="0" * 40
        ),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    upgrade_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-upgrade-matrix"
    )
    assert proof["status"] == "blocked"
    assert upgrade_check["status"] == "blocked"
    assert "current source head" in upgrade_check["notes"]


def test_stage7_final_readiness_blocks_upgrade_matrix_dirty_state_mismatch(
    tmp_path: Path,
) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        upgrade_matrix_evidence=_write_upgrade_matrix(tmp_path / "upgrade-matrix-proof.json"),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "9" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    upgrade_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-upgrade-matrix"
    )
    assert proof["status"] == "blocked"
    assert upgrade_check["status"] == "blocked"
    assert "status_sha256" in upgrade_check["notes"]


def test_stage7_final_readiness_blocks_cleanroom_without_skip_ledger(tmp_path: Path) -> None:
    cleanroom = _write_cleanroom(tmp_path / "cleanroom-summary.json")
    payload = json.loads(cleanroom.read_text(encoding="utf-8"))
    del payload["skip_ledger"]
    cleanroom.write_text(json.dumps(payload), encoding="utf-8")

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=cleanroom,
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        upgrade_matrix_evidence=_write_upgrade_matrix(tmp_path / "upgrade-matrix-proof.json"),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    cleanroom_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-current-cleanroom"
    )
    assert proof["status"] == "blocked"
    assert cleanroom_check["status"] == "blocked"
    assert "skip_ledger is missing" in cleanroom_check["notes"]


def test_stage7_final_readiness_blocks_missing_release_and_lifecycle_result(
    tmp_path: Path,
) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path,
        stage_reports=[],
        gauntlet_reports=[],
        source_state={"head": "b" * 40, "dirty": False, "branch": "stage7"},
        release_result={"status": "not-run", "command": "build release", "manifest": ""},
    )

    assert proof["status"] == "blocked"
    blocked = {check["id"] for check in proof["checks"] if check["status"] == "blocked"}
    assert {
        "stage7-prior-stage-reports",
        "stage7-release-artifacts",
        "stage7-final-installer-lifecycle",
    }.issubset(blocked)


def test_stage7_final_readiness_blocks_stale_final_lifecycle_proof(
    tmp_path: Path,
) -> None:
    stage_reports = [_write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)]
    gauntlet_reports = [_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)]
    lifecycle = _write_final_lifecycle(tmp_path / "final-lifecycle.json", head="0" * 40)
    full_stack = _write_full_stack(tmp_path / "full-stack-summary.json")

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=stage_reports,
        gauntlet_reports=gauntlet_reports,
        final_installer_lifecycle_proof=lifecycle,
        full_stack_evidence=full_stack,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage7"},
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    lifecycle_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-final-installer-lifecycle"
    )
    assert proof["status"] == "blocked"
    assert lifecycle_check["status"] == "blocked"
    assert "current source head" in lifecycle_check["notes"]


def test_stage7_final_readiness_blocks_stale_full_stack_evidence(
    tmp_path: Path,
) -> None:
    stage_reports = [_write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)]
    gauntlet_reports = [_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)]

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=stage_reports,
        gauntlet_reports=gauntlet_reports,
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json", head="0" * 40),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    full_stack_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-current-full-stack"
    )
    item_31 = next(row for row in proof["scope_item_matrix"] if row["item"].startswith("31 "))
    assert proof["status"] == "blocked"
    assert full_stack_check["status"] == "blocked"
    assert "current source head" in full_stack_check["notes"]
    assert item_31["status"] == "blocked"


def test_stage7_final_readiness_blocks_skipped_full_stack_lanes(tmp_path: Path) -> None:
    full_stack = _write_full_stack(tmp_path / "full-stack-summary.json")
    summary = json.loads(full_stack.read_text(encoding="utf-8"))
    summary["skip_web"] = True
    full_stack.write_text(json.dumps(summary), encoding="utf-8")

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=full_stack,
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    full_stack_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-current-full-stack"
    )
    assert proof["status"] == "blocked"
    assert full_stack_check["status"] == "blocked"
    assert "skipped required lanes" in full_stack_check["notes"]


def test_stage7_final_readiness_blocks_stale_current_final_gauntlet(
    tmp_path: Path,
) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate", head="0" * 40),
        source_state={
            "head": "a" * 40,
            "dirty": False,
            "branch": "stage7",
            "status_sha256": "0" * 64,
            "diff_sha256": "1" * 64,
            "untracked_content_sha256": "2" * 64,
        },
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    final_gate_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-current-final-gauntlet"
    )
    assert proof["status"] == "blocked"
    assert final_gate_check["status"] == "blocked"
    assert "current source head" in final_gate_check["notes"]


def test_stage7_final_readiness_blocks_missing_current_cleanroom(tmp_path: Path) -> None:
    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage7"},
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    cleanroom_check = next(
        check for check in proof["checks"] if check["id"] == "stage7-current-cleanroom"
    )
    assert proof["status"] == "blocked"
    assert cleanroom_check["status"] == "blocked"


def test_stage7_final_readiness_blocks_dependency_absent_clean_windows_as_core_ready(
    tmp_path: Path,
) -> None:
    clean_windows = tmp_path / "clean-windows-rendered.json"
    clean_windows.write_text(
        json.dumps(
            {
                "status": "passed_with_elevation_boundary",
                "source_state": {"head": "a" * 40, "dirty": False, "branch": "stage7"},
            }
        ),
        encoding="utf-8",
    )

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=[
            _write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)
        ],
        gauntlet_reports=[_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)],
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=clean_windows,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage7"},
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    item_2 = next(row for row in proof["scope_item_matrix"] if row["item"].startswith("2 "))
    assert proof["status"] == "blocked"
    assert proof["clean_windows_rendered"]["core_feature_reached"] is False
    assert item_2["status"] == "blocked"


def test_stage7_release_manifest_detection_uses_repo_manifest_name(tmp_path: Path) -> None:
    manifest = tmp_path / "civiccast-4.0.0-release-artifacts-manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    assert _release_manifest_path(tmp_path) == manifest


def test_stage7_final_readiness_records_native_windows_installer_when_present(
    tmp_path: Path,
) -> None:
    stage_reports = [_write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)]
    gauntlet_reports = [_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)]
    native_root = tmp_path / "final" / "native-windows-installer"
    installer = native_root / "civiccast-4.0.0-rc.2-windows-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    (native_root / "civiccast-4.0.0-rc.2-release-artifacts-manifest.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "kind": "windows-tauri-installer",
                        "filename": installer.name,
                        "size_bytes": installer.stat().st_size,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=stage_reports,
        gauntlet_reports=gauntlet_reports,
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage7"},
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    assert proof["summary"]["native_windows_installer_status"] == "passed"
    assert proof["native_windows_installer"]["installer"] == str(installer)
    assert not any("native Windows installer execution" in item for item in proof["not_claimed"])


def test_stage7_final_readiness_accepts_explicit_native_windows_manifest(
    tmp_path: Path,
) -> None:
    stage_reports = [_write_stage(tmp_path / f"stage-{idx}", f"stage{idx}") for idx in range(1, 7)]
    gauntlet_reports = [_write_gate(tmp_path / f"gate-{idx}") for idx in range(1, 7)]
    native_root = tmp_path / "existing-native-installer"
    installer = native_root / "civiccast-4.0.0-rc.2-windows-setup.exe"
    installer.parent.mkdir(parents=True)
    installer.write_bytes(b"installer")
    manifest = native_root / "civiccast-4.0.0-rc.2-release-artifacts-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "kind": "windows-tauri-installer",
                        "filename": installer.name,
                        "size_bytes": installer.stat().st_size,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    proof = build_stage7_final_readiness_proof(
        artifact_root=tmp_path / "final",
        stage_reports=stage_reports,
        gauntlet_reports=gauntlet_reports,
        final_installer_lifecycle_proof=_write_final_lifecycle(tmp_path / "final-lifecycle.json"),
        full_stack_evidence=_write_full_stack(tmp_path / "full-stack-summary.json"),
        cleanroom_evidence=_write_cleanroom(tmp_path / "cleanroom-summary.json"),
        final_gauntlet_report=_write_final_gate(tmp_path / "final-gate"),
        clean_windows_rendered_evidence=_write_clean_windows_core(
            tmp_path / "clean-windows-rendered.json"
        ),
        native_installer_manifest=manifest,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage7"},
        release_result={
            "status": "passed",
            "command": "build release",
            "manifest": "manifest.json",
        },
    )

    assert proof["summary"]["native_windows_installer_status"] == "passed"
    assert proof["native_windows_installer"]["manifest"] == str(manifest)
    assert proof["native_windows_installer"]["installer"] == str(installer)
