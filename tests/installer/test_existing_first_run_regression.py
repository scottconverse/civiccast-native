# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression contracts preserving existing first-run installer behavior."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer.model_bundle import (
    BundleModel,
    V11ModelBundleManifest,
    verify_airgapped_install,
)
from civiccast.installer.service import build_first_run_plan, run_first_health_check


class TestExistingFirstRunRegression:
    def test_current_seven_step_plan_survives_installer_expansion(self) -> None:
        service = importlib.import_module("civiccast.installer.service")
        plan = build_first_run_plan(profile="public-meetings", recommended_tier="tier-1-plus")

        assert [step.id for step in plan.steps] == [
            "profile",
            "hardware",
            "storage",
            "operator-account",
            "publish-targets",
            "models",
            "health",
        ]
        summary = service.build_installer_summary()
        assert {lane.id for lane in summary.lanes} == {
            "platform",
            "runtime",
            "ffmpeg",
            "ndi",
            "storage",
            "secrets",
            "service",
            "dashboard",
        }

    def test_placeholder_credentials_remain_rejected_when_new_lanes_exist(
        self, monkeypatch
    ) -> None:
        service = importlib.import_module("civiccast.installer.service")
        monkeypatch.setenv("CIVICCAST_PORTAL_TOKEN", "placeholder-token")
        monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "placeholder-ia-key")
        monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "placeholder-youtube-secret")
        monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "placeholder-webhook-secret")

        report = run_first_health_check(profile="public-meetings")

        assert report.ready is False
        checked = {check.id: check for check in report.checks}
        assert checked["portal"].state == "credential_or_secret_required"
        assert checked["internet-archive"].state == "credential_or_secret_required"
        assert checked["youtube"].state == "credential_or_secret_required"
        assert checked["subscriber-notifications"].state == "credential_or_secret_required"
        summary = service.build_installer_summary()
        assert "credentials" not in {lane.id for lane in summary.lanes}

    def test_v12_api_preserves_nas_real_io_proof_failure(self, monkeypatch) -> None:
        service = importlib.import_module("civiccast.installer.service")
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", "Z:/definitely-not-present-civiccast")
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/first-run/wizard-v1.2")

        assert response.status_code == 200
        gates = {gate["name"]: gate for gate in response.json()["gates"]}
        assert gates["Local NAS"]["status"] == "failed"
        assert "CIVICCAST_NAS_ARCHIVE_PATH" in gates["Local NAS"]["operator_action"]
        summary = service.build_installer_summary()
        assert summary.ready is False

    def test_offline_bundle_hash_behavior_still_uses_real_file_io(self, tmp_path: Path) -> None:
        model_state = importlib.import_module("civiccast.installer.model_state")
        model_file = tmp_path / "whisper-large-v3.tar.zst"
        model_file.write_bytes(b"offline bundle bytes")
        digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
        manifest = V11ModelBundleManifest(
            output_dir=tmp_path,
            models=(
                BundleModel(
                    name="whisper-large-v3",
                    filename=model_file.name,
                    source="fixture",
                    license="fixture",
                    size_bytes=model_file.stat().st_size,
                    sha256=digest,
                ),
            ),
        )

        result = verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
            manifest=manifest,
        )

        assert result.status == "ok"
        assert digest in result.operator_action
        installer_result = model_state.import_offline_model_bundle(
            bundle_dir=tmp_path,
            expected_hashes={model_file.name: digest},
        )
        assert installer_result.status == "complete"
