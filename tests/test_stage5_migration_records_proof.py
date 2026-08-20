# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the Stage 5 migration/archive/records proof."""

from __future__ import annotations

from pathlib import Path

from scripts.run_stage5_migration_records_proof import build_stage5_migration_records_proof


def test_stage5_proof_covers_migration_records_and_producer_surfaces(
    tmp_path: Path,
) -> None:
    proof = build_stage5_migration_records_proof(
        artifact_root=tmp_path,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage5"},
        test_result={"status": "passed", "command": "pytest stage5", "log": "pytest.log"},
    )

    # ponytail: overall status is "blocked" because campus_access has no real
    # education/campus package yet (item 24 is unbuilt) — that is the honest,
    # intended outcome, not a regression. See
    # test_stage5_campus_access_reports_missing_not_passed below.
    assert proof["stage_id"] == "3.6-stage5"
    assert proof["summary"]["migration_files"] >= 8
    assert proof["summary"]["feature_surfaces"] >= 7
    assert proof["summary"]["focused_test_status"] == "passed"
    assert {check["id"] for check in proof["checks"]} >= {
        "stage5-current-source",
        "stage5-migration-files",
        "stage5-archive-records",
        "stage5-recording-producer-workflow",
        "stage5-programlog-asrun",
        "stage5-campus-access",
        "stage5-focused-tests",
        "stage5-proof-boundary",
    }
    non_campus_checks = {
        check["id"]: check["status"]
        for check in proof["checks"]
        if check["id"] != "stage5-campus-access"
    }
    assert all(status == "passed" for status in non_campus_checks.values())
    assert "does not claim station migration execution" in "\n".join(proof["not_claimed"]).lower()
    assert (tmp_path / "stage5-migration-records-proof.json").is_file()
    assert (tmp_path / "stage5-feature-inventory.json").is_file()


def test_stage5_campus_access_reports_missing_not_passed(tmp_path: Path) -> None:
    """campus_access must not pass just because the unrelated civiccast/paywall
    module exists — the education/campus package itself has zero code."""

    proof = build_stage5_migration_records_proof(
        artifact_root=tmp_path,
        source_state={"head": "a" * 40, "dirty": False, "branch": "stage5"},
        test_result={"status": "passed", "command": "pytest stage5", "log": "pytest.log"},
    )

    campus_check = next(check for check in proof["checks"] if check["id"] == "stage5-campus-access")
    assert campus_check["status"] == "blocked"
    assert proof["status"] == "blocked"


def test_stage5_proof_blocks_dirty_source_or_missing_tests(tmp_path: Path) -> None:
    proof = build_stage5_migration_records_proof(
        artifact_root=tmp_path,
        source_state={"head": "b" * 40, "dirty": True, "branch": "stage5"},
        test_result={"status": "not-run", "command": "pytest stage5", "log": ""},
    )

    assert proof["status"] == "blocked"
    blocked = {check["id"] for check in proof["checks"] if check["status"] == "blocked"}
    assert {"stage5-current-source", "stage5-focused-tests"}.issubset(blocked)
