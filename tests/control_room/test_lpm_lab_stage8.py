# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Stage 8 local release-hardening tests for the 3.2 LPM lab."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from civiccast.control_room.lpm_lab import build_lpm_lab_profiles
from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab
from civiccast.control_room.lpm_lab_stage8 import (
    build_stage8_manifest,
    summarize_stage8_events,
)


def _profiles() -> list:
    profiles = build_lpm_lab_profiles()
    return [
        profiles["fixed-studio-livestreaming"],
        profiles["portable-field-kit"],
        profiles["digitization-obs"],
    ]


def test_stage8_manifest_covers_required_local_hardening_artifacts() -> None:
    manifest = build_stage8_manifest(_profiles())

    assert manifest.status == "passed"
    assert set(manifest.profiles) == {
        "fixed-studio-livestreaming",
        "portable-field-kit",
        "digitization-obs",
    }
    required_paths = {artifact.path for artifact in manifest.required_artifacts}
    assert "stage8-proof-matrix.json" in required_paths
    assert "stage8-known-limits.md" in required_paths
    assert "virtual-media-studio-bundle/vstudio-bundle-manifest.json" in required_paths
    assert manifest.manifest_sha256
    assert any(
        "No wall-clock soak is required" in item for item in manifest.local_gate_requirements
    )
    assert any("No elapsed wall-clock soak" in item for item in manifest.not_claimed)
    assert not any("station-device evidence is claimed" in item for item in manifest.release_claims)


def test_stage8_execution_writes_hardening_and_bundle_artifacts(tmp_path: Path) -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage8",
        profile_ids=["all"],
        artifact_root=tmp_path,
    )

    # Overall status is honestly "failed" — several Stage 4-5 required checks
    # (e.g. elgato-obs-source-removed, local-recording-evidence) have no
    # executed fixture yet (fail-loud by design).
    assert result.status == "failed"
    assert result.execution_stage == "stage8"
    assert any(event.check_id == "stage8-release-hardening-manifest" for event in result.events)
    assert any(event.check_id == "stage8-no-wall-clock-soak-claim" for event in result.events)
    stage8_manifest_event = next(
        event for event in result.events if event.check_id == "stage8-release-hardening-manifest"
    )
    assert stage8_manifest_event.details["final_manifest_path"] == "stage8-release-manifest.json"
    assert "artifact_digests" not in stage8_manifest_event.details
    assert (tmp_path / "stage67-soak-plan.json").is_file()
    assert (tmp_path / "stage8-release-manifest.json").is_file()
    assert (tmp_path / "stage8-proof-matrix.json").is_file()
    assert (tmp_path / "stage8-known-limits.md").is_file()
    assert (tmp_path / "stage8-local-operator-handoff.md").is_file()
    bundle_manifest = tmp_path / "virtual-media-studio-bundle" / "vstudio-bundle-manifest.json"
    assert bundle_manifest.is_file()

    manifest = json.loads((tmp_path / "stage8-release-manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(bundle_manifest.read_text(encoding="utf-8"))
    assert manifest["schema_id"] == "civiccast.lpm.stage8.release-hardening.v1"
    assert bundle["schema_id"] == "civiccast.virtual-media-studio.bundle.v1"
    assert "No elapsed wall-clock soak" in "\n".join(manifest["not_claimed"])
    digests = {row["path"]: row for row in manifest["artifact_digests"]}
    assert "stage8-proof-matrix.json" in digests
    assert "virtual-media-studio-bundle/vstudio-bundle-manifest.json" in digests
    for path, row in digests.items():
        artifact = tmp_path / path
        assert artifact.is_file()
        assert row["size_bytes"] == artifact.stat().st_size
        assert len(row["sha256"]) == 64
    assert "This bundle does not run an elapsed wall-clock soak." in "\n".join(
        bundle["not_claimed"]
    )

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Read First - Stage 8 Local Release Hardening" in readme
    assert "no wall-clock soak is claimed" in readme
    limits = (tmp_path / "stage8-known-limits.md").read_text(encoding="utf-8")
    assert "No clean Windows install proof" in limits
    assert "secure listener posture" in limits
    assert "Virtual Media Studio bundle is local lab software" in limits


def test_stage8_subset_run_does_not_require_three_profiles(tmp_path: Path) -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage8",
        profile_ids=["digitization-obs"],
        artifact_root=tmp_path,
    )
    # Overall status is honestly "failed" — same fail-loud reason as
    # test_stage8_execution_writes_hardening_and_bundle_artifacts.
    assert result.status == "failed"
    manifest = json.loads((tmp_path / "stage8-release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["profiles"] == ["digitization-obs"]
    assert "digitization-obs" in "\n".join(manifest["proof_matrix"])


def test_stage8_cli_runs_and_reports_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--execution-stage",
            "stage8",
            "--profile",
            "digitization-obs",
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    # ponytail: returncode 1 is expected — same honest fail-loud reason as
    # test_stage8_execution_writes_hardening_and_bundle_artifacts.
    assert result.returncode == 1
    assert "Execution stage: stage8" in result.stdout
    assert "Stage 8 summary:" in result.stdout
    assert "no wall-clock soak is claimed" in result.stdout


def test_stage8_cli_missing_dependency_is_actionable_without_traceback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    result = subprocess.run(
        [sys.executable, "-S", "-B", str(script), "--list-profiles"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Missing Python dependency" in result.stderr
    assert "uv run python scripts/run_lpm_contract_lab.py" in result.stderr
    assert "Traceback" not in result.stderr


def test_stage8_summary_reports_not_run_when_absent() -> None:
    assert summarize_stage8_events([]) == ["Stage 8 release-hardening: not run."]


def test_local_ci_runner_removes_generated_obs_lab_password_artifact() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = (repo_root / "scripts" / "run_local_3_2_lpm_contract_lab_ci.ps1").read_text(
        encoding="utf-8"
    )

    assert "$env:CIVICAST_OBS_WEBSOCKET_PASSWORD = $script:ObsWebSocketPassword" in script
    assert "Remove-Item Env:\\CIVICAST_OBS_WEBSOCKET_PASSWORD" in script
    assert "Remove-Item -LiteralPath $script:ObsLabAppData -Recurse -Force" in script
