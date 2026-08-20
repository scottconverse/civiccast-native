# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Stage 6-7 LPM lab soak/station-readiness tests."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from civiccast.control_room.lpm_lab import build_lpm_lab_profiles
from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab
from civiccast.control_room.lpm_lab_stage67 import (
    MIN_SOAK_SECONDS,
    build_field_evidence_template,
    build_stage67_soak_plan,
    build_support_bundle_manifest,
    validate_field_evidence_bundle,
    validate_soak_plan,
)


def _profiles() -> list:
    profiles = build_lpm_lab_profiles()
    return [
        profiles["fixed-studio-livestreaming"],
        profiles["portable-field-kit"],
        profiles["digitization-obs"],
    ]


def test_stage67_soak_plan_covers_all_three_lpm_profiles() -> None:
    plan = build_stage67_soak_plan(_profiles())
    summary = validate_soak_plan(plan)

    assert plan.duration_seconds == MIN_SOAK_SECONDS
    assert summary == {
        "duration_seconds": MIN_SOAK_SECONDS,
        "channel_count": 3,
        "fault_count": 9,
        "support_file_count": 9,
    }
    assert {channel.profile_id for channel in plan.channels} == {
        "fixed-studio-livestreaming",
        "portable-field-kit",
        "digitization-obs",
    }
    assert any(
        fault.fault_id == "fixed-tsr-sidecar-restart"
        for channel in plan.channels
        for fault in channel.faults
    )
    assert any(
        fault.fault_id == "portable-wifi-dropout-recovery"
        for channel in plan.channels
        for fault in channel.faults
    )
    assert any(
        fault.fault_id == "digitization-obs-restart"
        for channel in plan.channels
        for fault in channel.faults
    )


def test_stage67_soak_plan_rejects_faults_that_never_recover() -> None:
    plan = build_stage67_soak_plan(_profiles())
    broken = plan.model_copy(deep=True)
    broken.channels[0].faults[0].recover_at_second = broken.channels[0].faults[0].inject_at_second

    with pytest.raises(ValueError, match="recovery must occur after injection"):
        validate_soak_plan(broken)


def test_stage67_support_bundle_manifest_is_redacted_and_hashed() -> None:
    plan = build_stage67_soak_plan(_profiles())
    manifest = build_support_bundle_manifest(_profiles(), plan)

    assert manifest["schema"] == "civiccast.lpm.support-bundle.v1"
    assert len(manifest["manifest_sha256"]) == 64
    manifest_body = dict(manifest)
    manifest_sha256 = manifest_body.pop("manifest_sha256")
    assert (
        manifest_sha256
        == hashlib.sha256(
            json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    assert all(item["contains_secrets"] is False for item in manifest["files"])
    body = json.dumps(manifest).lower()
    assert "admin/admin" not in body
    assert "password=" not in body
    assert "secret=" not in body
    assert "token=" not in body


def test_stage67_station_template_is_not_accepted_as_station_device_evidence() -> None:
    plan = build_stage67_soak_plan(_profiles())
    manifest = build_support_bundle_manifest(_profiles(), plan)
    template = build_field_evidence_template(_profiles(), manifest)

    issues = validate_field_evidence_bundle(template)

    assert issues
    assert any("station_evidence_status must be station-captured" in issue for issue in issues)
    assert any("operator is required" in issue for issue in issues)
    assert any("device_evidence[0].device_id is required" in issue for issue in issues)
    assert any("media_evidence[0].media_id is required" in issue for issue in issues)
    assert any("media_evidence[0].duration_seconds must be > 0" in issue for issue in issues)
    assert template["station_evidence_status"] == "template-not-station-evidence"


def test_stage67_field_evidence_validator_accepts_complete_future_bundle(
    tmp_path: Path,
) -> None:
    plan = build_stage67_soak_plan(_profiles())
    manifest = build_support_bundle_manifest(_profiles(), plan)
    bundle = build_field_evidence_template(_profiles(), manifest)
    completed = copy.deepcopy(bundle)
    completed["station_evidence_status"] = "station-captured"
    (tmp_path / "devices.json").write_text('{"state":"connected"}\n', encoding="utf-8")
    (tmp_path / "recording.mp4").write_bytes(b"fake field media proof bytes")
    (tmp_path / "support-bundle.zip").write_bytes(b"fake support bundle bytes")
    for profile in completed["profiles"]:
        profile["operator"] = "LPM operator"
        profile["captured_at"] = "2026-07-01T12:00:00Z"
        profile["field_contact"] = "LPM control room"
        profile["device_evidence"] = [
            {
                "device_id": profile["profile_id"] + "-device",
                "proof_type": "state-readback",
                "observed_state": "connected",
                "artifact_path": "devices.json",
                "sha256": _file_sha256(tmp_path / "devices.json"),
                "captured_at": "2026-07-01T12:00:00Z",
            }
        ]
        profile["media_evidence"] = [
            {
                "media_id": profile["profile_id"] + "-recording",
                "proof_type": "recording",
                "duration_seconds": 30,
                "artifact_path": "recording.mp4",
                "sha256": _file_sha256(tmp_path / "recording.mp4"),
                "captured_at": "2026-07-01T12:00:00Z",
            }
        ]
        profile["support_bundle"] = {
            "path": "support-bundle.zip",
            "sha256": _file_sha256(tmp_path / "support-bundle.zip"),
        }

    assert (
        validate_field_evidence_bundle(
            completed,
            evidence_root=tmp_path,
            expected_profile_ids=[profile.profile_id for profile in _profiles()],
            expected_support_manifest_sha256=manifest["manifest_sha256"],
        )
        == []
    )


def test_stage67_field_evidence_validator_rejects_malformed_evidence_items() -> None:
    plan = build_stage67_soak_plan(_profiles())
    manifest = build_support_bundle_manifest(_profiles(), plan)
    bundle = build_field_evidence_template(_profiles(), manifest)
    bundle["station_evidence_status"] = "station-captured"
    profile = bundle["profiles"][0]
    profile["operator"] = "LPM operator"
    profile["captured_at"] = "2026-07-01T12:00:00Z"
    profile["field_contact"] = "LPM control room"
    profile["device_evidence"] = [
        {
            "device_id": "vmix",
            "proof_type": "state-readback",
            "observed_state": "connected",
            "artifact_path": "devices.json",
            "sha256": "not-a-hash",
            "captured_at": "2026-07-01T12:00:00Z",
        }
    ]
    profile["media_evidence"] = [
        {
            "media_id": "clip",
            "proof_type": "recording",
            "duration_seconds": 0,
            "artifact_path": "recording.mp4",
            "sha256": "c" * 64,
            "captured_at": "2026-07-01T12:00:00Z",
        }
    ]
    profile["support_bundle"] = {"path": "support-bundle.zip", "sha256": "a" * 64}

    issues = validate_field_evidence_bundle(bundle)

    assert any("device_evidence[0].sha256 must be" in issue for issue in issues)
    assert any("media_evidence[0].duration_seconds must be > 0" in issue for issue in issues)
    assert any("evidence_root is required" in issue for issue in issues)


def test_stage67_field_evidence_validator_rejects_fake_files_and_profile_drift(
    tmp_path: Path,
) -> None:
    plan = build_stage67_soak_plan(_profiles())
    manifest = build_support_bundle_manifest(_profiles(), plan)
    bundle = build_field_evidence_template(_profiles(), manifest)
    bundle["station_evidence_status"] = "station-captured"
    bundle["profiles"][0]["profile_id"] = "unknown-profile"
    bundle["profiles"][1]["profile_id"] = "portable-field-kit"
    bundle["profiles"][2]["profile_id"] = "portable-field-kit"
    for profile in bundle["profiles"]:
        profile["operator"] = "LPM operator"
        profile["captured_at"] = "not-a-timestamp"
        profile["field_contact"] = "LPM control room"
        profile["device_evidence"] = [
            {
                "device_id": "device",
                "proof_type": "state-readback",
                "observed_state": "connected",
                "artifact_path": "missing-devices.json",
                "sha256": "d" * 64,
                "captured_at": "2026-07-01T12:00:00Z",
            }
        ]
        profile["media_evidence"] = [
            {
                "media_id": "clip",
                "proof_type": "recording",
                "duration_seconds": 30,
                "artifact_path": "../outside.mp4",
                "sha256": "E" * 64,
                "captured_at": "bad-date",
            }
        ]
        profile["support_bundle"] = {"path": "support-bundle.zip", "sha256": "a" * 64}

    issues = validate_field_evidence_bundle(
        bundle,
        evidence_root=tmp_path,
        expected_profile_ids=[profile.profile_id for profile in _profiles()],
        expected_support_manifest_sha256=manifest["manifest_sha256"],
    )

    assert any("profile_id is not a known LPM profile" in issue for issue in issues)
    assert any("duplicates portable-field-kit" in issue for issue in issues)
    assert any("profiles must exactly match selected profiles" in issue for issue in issues)
    assert any("captured_at must be an ISO-8601 timestamp" in issue for issue in issues)
    assert any("path does not exist under evidence_root" in issue for issue in issues)
    assert any("must stay inside evidence_root" in issue for issue in issues)
    assert any("media_evidence[0].sha256 must be" in issue for issue in issues)


def test_cli_help_names_stage67_extra_artifacts() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Stage 6-7 soak plans" in result.stdout
    assert "station-evidence templates" in result.stdout
    assert "plan/rehearsal only" in result.stdout


def test_stage67_execution_appends_soak_and_field_readiness_without_field_claims() -> None:
    result = run_lpm_contract_lab(execution_stage="stage67", profile_ids=["all"])

    # Overall status is honestly "failed" — several Stage 4-5 required checks
    # have no executed fixture behind them (fail-loud by design, see
    # test_lpm_lab_stage45.py).
    assert result.status == "failed"
    assert result.execution_stage == "stage67"
    assert any(
        event.check_id == "vmix-status-xml"
        and event.proof_source == "api-fixture"
        and event.proof_level == "api-contract-proven"
        for event in result.events
    )
    assert any(
        event.check_id == "stage67-three-channel-soak-plan"
        and event.proof_source == "stateful-simulator"
        and event.proof_level == "simulated-proven"
        for event in result.events
    )
    envelope = next(
        event for event in result.events if event.check_id == "stage67-station-evidence-envelope"
    )
    assert envelope.status == "passed"
    assert envelope.proof_source == "station-readiness"
    assert envelope.proof_level == "mocked"
    assert "no station-device label" in (envelope.not_claimed or "").lower()
    assert not any(event.proof_source == "station-device" for event in result.events)
    assert not any(event.proof_level == "station-device-proven" for event in result.events)


def test_stage67_subset_run_does_not_claim_three_profile_parity() -> None:
    result = run_lpm_contract_lab(
        execution_stage="stage67",
        profile_ids=["digitization-obs"],
    )

    soak_event = next(
        event for event in result.events if event.check_id == "stage67-three-channel-soak-plan"
    )
    # Overall run is honestly "failed" (unexecuted Stage 4-5 checks on this
    # profile); the soak-plan event itself passed.
    assert result.status == "failed"
    assert soak_event.status == "passed"
    assert "Selected-profile" in soak_event.claim
    assert "Three-profile" not in soak_event.claim
    assert "LPM lab parity" not in soak_event.claim


def test_stage67_readme_has_soak_and_field_readiness_summary(tmp_path: Path) -> None:
    run_lpm_contract_lab(
        execution_stage="stage67",
        profile_ids=["all"],
        artifact_root=tmp_path,
    )

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Read First - Stage 6-7 Soak And Station Readiness" in readme
    assert "Stage 6 soak is deterministic local rehearsal" in readme
    assert "Station-device labels present: none." in readme
    assert "station-readiness" in readme
    assert (tmp_path / "stage67-soak-plan.json").is_file()
    assert (tmp_path / "support-bundle-manifest.json").is_file()
    assert (tmp_path / "station-evidence-manifest.template.json").is_file()
    assert (tmp_path / "adapter-logs" / "redacted-device-control.log").is_file()
    assert (tmp_path / "proof-log" / "redacted-control-room-actions.jsonl").is_file()
    manifest = json.loads((tmp_path / "support-bundle-manifest.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        listed_path = tmp_path / item["path"]
        assert listed_path.is_file()
        body = listed_path.read_text(encoding="utf-8", errors="ignore").lower()
        assert "admin/admin" not in body
        assert "password=" not in body
        assert "secret=" not in body
        assert "token=" not in body


def test_cli_runs_stage67_and_reports_summary(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--execution-stage",
            "stage67",
            "--profile",
            "all",
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )

    # ponytail: returncode 1 is expected — several Stage 4-5 required checks
    # have no executed fixture yet (fail-loud by design); this test covers
    # CLI output formatting, not overall pass status.
    assert result.returncode == 1
    assert "Execution stage: stage67" in result.stdout
    assert "Stage 6-7 summary:" in result.stdout
    assert "Station-device labels present: none." in result.stdout


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
