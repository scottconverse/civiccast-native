# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from scripts.collect_source_state import collect_source_state
from scripts.run_isolated_first_run_attestation import run_attestation


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
