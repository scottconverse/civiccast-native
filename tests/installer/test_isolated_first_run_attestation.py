# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from scripts.collect_source_state import collect_source_state
from scripts.run_isolated_first_run_attestation import run_attestation


def test_first_setup_reaches_a_real_published_recording(tmp_path: Path) -> None:
    """Follow the supported local setup path, without external providers."""
    import subprocess

    from fastapi.testclient import TestClient

    from civiccast.app import create_app
    from civiccast.db.session import reset_engine
    from scripts.run_isolated_first_run_attestation import (
        _ENV_KEYS,
        _install_isolated_env,
        _restore_env,
    )

    original = {key: os.environ.get(key) for key in _ENV_KEYS}
    profile = tmp_path / "first-recording"
    profile.mkdir()
    try:
        reset_engine()
        _install_isolated_env(profile)
        with TestClient(create_app()) as client:
            storage = client.post("/api/setup/storage", json={})
            assert storage.status_code == 200, storage.text
            assert storage.json()["status"] == "ready"
            setup = client.post(
                "/api/setup/first-admin",
                json={
                    "station_name": "Isolated recording station",
                    "admin_display_name": "Setup operator",
                    "admin_username": "setup-operator",
                    "admin_password": "First-recording-test-password-2026",
                    "recovery_kit_destination": "offline test safe",
                    "default_channel_id": "government",
                    "public_base_url": "http://127.0.0.1:8000",
                },
            )
            assert setup.status_code == 200, setup.text
            headers = {"Authorization": f"Bearer {setup.json()['operator_console_token']}"}
            acknowledged = client.post(
                "/api/setup/recovery-kit/acknowledge", json={"confirmed": True}, headers=headers
            )
            assert acknowledged.status_code == 200, acknowledged.text
            sample = client.post("/api/staff/installer/source-setup/sample-upload", headers=headers)
            assert sample.status_code == 200, sample.text
            asset_id = sample.json()["asset_id"]
            package = client.post(f"/api/staff/assets/{asset_id}/package", headers=headers)
            assert package.status_code == 200, package.text
            assert package.json()["manifest_url"]
            assert package.json()["published_at"] is None
            approved = client.post(
                f"/api/staff/publish/assets/{asset_id}/approve",
                headers=headers,
                json={
                    "operator_id": "setup-operator",
                    "operator_display_name": "Setup operator",
                    "approved_surface_ids": ["portal"],
                },
            )
            assert approved.status_code == 200, approved.text
            assets = [
                asset
                for asset in client.get("/api/public/assets").json()
                if asset["asset_id"] == asset_id
            ]
            assert assets, "First setup did not publish the local welcome recording."
            asset = assets[0]
            assert asset["published_at"] and asset["manifest_url"]
            manifest = client.get(asset["manifest_url"])
            assert manifest.status_code == 200, manifest.text
            # Follow the actual resident master -> rendition -> media path.
            from urllib.parse import urljoin

            rendition_uri = next(
                line for line in manifest.text.splitlines() if line and not line.startswith("#")
            )
            rendition_url = urljoin(asset["manifest_url"], rendition_uri)
            rendition = client.get(rendition_url)
            assert rendition.status_code == 200, rendition.text
            segment_uri = next(
                line for line in rendition.text.splitlines() if line and not line.startswith("#")
            )
            segment = client.get(urljoin(rendition_url, segment_uri))
            assert segment.status_code == 200
            capture = tmp_path / "resident-segment.ts"
            capture.write_bytes(segment.content)
            decoded = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(capture),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
            )
            assert decoded.returncode == 0, decoded.stderr
    finally:
        reset_engine()
        _restore_env(original)


def test_source_state_uses_cleanroom_ci_sha_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_sha = "A" * 40

    monkeypatch.setenv("CIVICAST_CI_SOURCE_SHA", expected_sha)

    with pytest.raises(RuntimeError, match="git branch --show-current failed"):
        collect_source_state(repo_root=tmp_path)


def test_isolated_first_run_attestation_writes_redacted_evidence(
    tmp_path: Path,
) -> None:
    original_database_url = os.environ.get("DATABASE_URL")
    artifact_root = tmp_path / "artifacts"
    profile_root = tmp_path / "profile"
    preexisting_workers = [
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith("civiccast-") and thread.is_alive()
    ]
    assert preexisting_workers == [], (
        "the first-run attestation requires an isolated process; "
        f"pre-existing CivicCast workers: {preexisting_workers}"
    )
    thread_ids_before = {thread.ident for thread in threading.enumerate()}

    evidence = run_attestation(artifact_root=artifact_root, profile_root=profile_root)

    assert evidence["verdict"] == "pass"
    assert evidence["steps"]["storage_before"]["status"] == "not_configured"
    assert evidence["steps"]["storage_ready"]["status"] == "ready"
    assert evidence["steps"]["first_admin"]["status"] == "complete"
    assert evidence["steps"]["first_admin"]["recovery_code_count"] == 8
    assert evidence["steps"]["recovery_acknowledge"]["recovery_kit_acknowledged"] is True
    assert evidence["steps"]["login"]["status"] == "authenticated"
    assert evidence["steps"]["station_after"]["setup_complete"] is True
    assert len(evidence["source_state"]["head"]) == 40
    assert len(evidence["source_state"]["status_sha256"]) == 64
    assert len(evidence["source_state"]["diff_sha256"]) == 64
    assert evidence["source_state"]["diff_sha256"] == collect_source_state()["diff_sha256"]
    assert (artifact_root / "first-run-attestation.json").is_file()
    assert (artifact_root / "first-run-attestation.md").is_file()
    assert evidence["isolation"]["transient_profile_retained"] is False
    assert not profile_root.exists()

    redacted_json = (artifact_root / "first-run-attestation.json").read_text(encoding="utf-8")
    redacted_payload = json.loads(redacted_json)
    assert "Correct-Horse-Battery-Staple-2026" not in redacted_json
    assert "isolated-first-run-attestation-nonce" not in redacted_json
    assert "ccst_" not in redacted_json
    assert "CC-" not in redacted_json
    assert os.environ.get("DATABASE_URL") == original_database_url
    attestation_md = (artifact_root / "first-run-attestation.md").read_text(encoding="utf-8")
    assert "Source diff SHA256" in attestation_md

    assert redacted_payload["files"]["station_state"]["path"] == str(
        profile_root / "station-state.json"
    )
    leaked_workers = [
        thread.name
        for thread in threading.enumerate()
        if thread.ident not in thread_ids_before and thread.name.startswith("civiccast-")
    ]
    assert leaked_workers == []
