# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""3.2 LPM Lab harness tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from civiccast.control_room.lpm_lab import build_lpm_lab_profiles
from civiccast.control_room.lpm_lab_harness import ARTIFACT_MARKER, run_lpm_contract_lab


def test_lpm_contract_lab_writes_checkable_artifacts(tmp_path: Path) -> None:
    result = run_lpm_contract_lab(artifact_root=tmp_path, run_id="test-run")

    assert result.status == "passed"
    assert result.profiles == [
        "fixed-studio-livestreaming",
        "portable-field-kit",
        "digitization-obs",
    ]
    assert (tmp_path / "summary.json").is_file()
    assert (tmp_path / "events.json").is_file()
    assert (tmp_path / "profiles.json").is_file()
    assert (tmp_path / "README.md").is_file()

    loaded = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert loaded["status"] == "passed"
    assert loaded["run_id"] == "test-run"


def test_empty_profile_selection_is_rejected_before_green_result() -> None:
    with pytest.raises(ValueError, match="At least one LPM Lab profile is required"):
        run_lpm_contract_lab(profile_ids=[])


def test_all_profile_selection_must_be_used_alone() -> None:
    with pytest.raises(ValueError, match="Use --profile all by itself"):
        run_lpm_contract_lab(profile_ids=["all", "digitization-obs"])


def test_every_required_device_check_is_emitted() -> None:
    result = run_lpm_contract_lab()
    emitted = {(event.profile_id, event.device_id, event.check_id) for event in result.events}

    for profile in build_lpm_lab_profiles().values():
        for device in profile.devices:
            for check_id in device.required_checks:
                assert (profile.profile_id, device.contract_id, check_id) in emitted


def test_fixed_studio_simulation_covers_decklink_and_ptz_failure_modes(tmp_path: Path) -> None:
    result = run_lpm_contract_lab(
        profile_ids=["fixed-studio-livestreaming"], artifact_root=tmp_path
    )
    checks = {event.check_id for event in result.events}

    assert "decklink-driver-missing" in checks
    assert "decklink-card-absent" in checks
    assert "decklink-channel-absent" in checks
    assert "decklink-mode-mismatch" in checks
    assert "decklink-signal-unlocked" in checks
    assert "recording-decklink-preset-argv" in checks
    assert "visca-udp-52381-ack" in checks
    assert "visca-timeout" in checks
    assert "visca-command-not-executable" in checks
    assert "ndi-source-disappears" in checks
    assert "ndi-source-reappears" in checks
    assert "ptz-credentials-rotated" in checks
    assert "tsr-sidecar-restart" in checks


def test_portable_field_kit_simulation_covers_no_decklink_no_ptz_and_wifi() -> None:
    result = run_lpm_contract_lab(profile_ids=["portable-field-kit"])
    device_ids = {event.device_id for event in result.events}
    checks = {event.check_id for event in result.events}

    assert not any("decklink" in device_id for device_id in device_ids)
    assert not any("ptz" in device_id for device_id in device_ids)
    assert "wifi-latency-injection" in checks
    assert "wifi-dropout" in checks
    assert "dns-failure" in checks
    assert "castr-unreachable" in checks
    assert "youtube-destination-confirmed" in checks
    assert "usb-capture-absent" in checks
    assert "recording-dshow-preset-argv" in checks
    assert "usb-capture-usb-reset" in checks
    assert "vmix-laptop-resource-ceiling" in checks
    assert "atem-absent" in checks


def test_digitization_obs_simulation_covers_obs_protocol_and_capture_absence() -> None:
    result = run_lpm_contract_lab(profile_ids=["digitization-obs"])
    checks = {event.check_id for event in result.events}

    assert "obs-websocket-5-contract" in checks
    assert "obs-websocket-disabled" in checks
    assert "obs-wrong-password" in checks
    assert "obs-protocol-mismatch" in checks
    assert "obs-source-missing" in checks
    assert "obs-source-removed" in checks
    assert "obs-recording-state" in checks
    assert "obs-restart" in checks
    assert "usb-capture-absent" in checks
    assert "local-recording-evidence" in checks


def test_unknown_profile_is_rejected_before_artifact_claim(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown LPM Lab profile"):
        run_lpm_contract_lab(profile_ids=["fixed-studio"], artifact_root=tmp_path)


def test_contract_lab_artifacts_do_not_contain_secret_values(tmp_path: Path) -> None:
    run_lpm_contract_lab(artifact_root=tmp_path)
    body = "\n".join(path.read_text(encoding="utf-8").lower() for path in tmp_path.iterdir())

    assert "admin/admin" not in body
    assert "password=" not in body
    assert "secret=" not in body
    assert "token=" not in body


def test_reused_artifact_root_fails_without_explicit_force_clean(tmp_path: Path) -> None:
    stale = tmp_path / "stale.txt"
    stale.write_text("old proof", encoding="utf-8")

    with pytest.raises(FileExistsError, match="force_clean=True"):
        run_lpm_contract_lab(artifact_root=tmp_path)


def test_force_clean_removes_stale_artifacts_and_records_cleanup(tmp_path: Path) -> None:
    run_lpm_contract_lab(artifact_root=tmp_path)
    stale = tmp_path / "stale.txt"
    stale.write_text("old proof", encoding="utf-8")

    run_lpm_contract_lab(artifact_root=tmp_path, force_clean=True)

    assert not stale.exists()
    assert (tmp_path / ARTIFACT_MARKER).is_file()
    assert (tmp_path / "artifact-root-cleanup.json").is_file()
    assert (tmp_path / "summary.json").is_file()


def test_force_clean_refuses_unmarked_artifact_roots(tmp_path: Path) -> None:
    (tmp_path / "stale.txt").write_text("not our artifact root", encoding="utf-8")

    with pytest.raises(ValueError, match="not marked"):
        run_lpm_contract_lab(artifact_root=tmp_path, force_clean=True)


def test_readme_exposes_proof_label_claim_observed_and_not_claimed(tmp_path: Path) -> None:
    run_lpm_contract_lab(artifact_root=tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")

    assert "Proof label" in readme
    assert "Evidence source" in readme
    assert "Claim" in readme
    assert "Observed" in readme
    assert "Not claimed" in readme
    assert (
        "This is local contract-lab evidence. It does not include station-device evidence."
        in readme
    )
    assert "not clean Windows install proof" in readme
    assert "not real OBS/vMix/NDI software proof" in readme
    assert "not a beta/release publication decision" in readme
    assert "Proof Label Legend" in readme
    assert "Profile Boundaries" in readme
    assert "Digitization OBS proof is not a live production-switching proof" in readme


def test_stage1_events_use_check_catalog_not_fixture_or_simulator_claims() -> None:
    result = run_lpm_contract_lab()

    device_events = [event for event in result.events if event.device_id != "profile"]
    assert device_events
    assert {event.proof_level for event in device_events} == {"mocked"}
    assert {event.proof_source for event in device_events} <= {"check-catalog", "profile-contract"}
    assert not any(
        event.proof_source in {"api-fixture", "stateful-simulator"} for event in device_events
    )


def test_cli_expected_errors_do_not_render_tracebacks(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    unknown = subprocess.run(
        [
            sys.executable,
            str(script),
            "--profile",
            "fixed-studio",
            "--artifact-root",
            str(tmp_path / "unknown-profile"),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unknown.returncode == 2
    assert "Traceback" not in unknown.stderr
    assert "Unknown LPM Lab profile" in unknown.stderr
    assert "fixed-studio-livestreaming" in unknown.stderr

    stale_root = tmp_path / "stale-root"
    stale_root.mkdir()
    (stale_root / "stale.txt").write_text("old proof", encoding="utf-8")
    stale = subprocess.run(
        [sys.executable, str(script), "--artifact-root", str(stale_root)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale.returncode == 2
    assert "Traceback" not in stale.stderr
    assert "--force-clean" in stale.stderr


def test_cli_lists_known_profiles() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run_lpm_contract_lab.py"

    result = subprocess.run(
        [sys.executable, str(script), "--list-profiles"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "fixed-studio-livestreaming" in result.stdout
    assert "portable-field-kit" in result.stdout
    assert "digitization-obs" in result.stdout
