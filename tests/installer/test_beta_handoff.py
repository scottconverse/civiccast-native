# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the beta tester handoff backend and artifact acquisition path."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

REQUIRED_BETA_LANES = {
    "package-acquisition",
    "clean-windows-install-proof",
    "dependencies",
    "models",
    "nats",
    "mtls",
    "external-providers",
}
SECRET_SENTINELS = {
    "super-secret-ia-key",
    "super-secret-youtube-client-secret",
    "super-secret-webhook-secret",
}
HANDOFF_STATUSES = {
    "passed",
    "blocked",
    "credential_or_secret_required",
    "hardware_required",
}


def _dump_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    assert isinstance(value, dict)
    return value


def _contains_secret(value: object) -> bool:
    return any(secret in json.dumps(value, sort_keys=True) for secret in SECRET_SENTINELS)


class TestBetaHandoffSummaryContract:
    def test_beta_handoff_summary_model_is_closed_and_names_required_lanes(self) -> None:
        models = importlib.import_module("civiccast.installer.models")

        summary_model = models.BetaHandoffSummary
        lane_model = models.BetaHandoffLane
        schema_text = json.dumps(summary_model.model_json_schema(), sort_keys=True)
        lane_schema_text = json.dumps(lane_model.model_json_schema(), sort_keys=True)

        assert summary_model.model_config["extra"] == "forbid"
        assert lane_model.model_config["extra"] == "forbid"
        for lane_id in REQUIRED_BETA_LANES:
            assert lane_id in schema_text
        for status in HANDOFF_STATUSES:
            assert status in lane_schema_text

    def test_builder_reports_fail_closed_lanes_without_secret_values(self, monkeypatch) -> None:
        monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "super-secret-ia-key")
        monkeypatch.setenv(
            "CIVICCAST_YOUTUBE_CLIENT_SECRET",
            "super-secret-youtube-client-secret",
        )
        monkeypatch.setenv(
            "CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET",
            "super-secret-webhook-secret",
        )
        handoff = importlib.import_module("civiccast.installer.handoff")

        summary = handoff.build_beta_handoff_summary()

        payload = _dump_payload(summary)
        lanes = {lane["id"]: lane for lane in payload["lanes"]}
        assert lanes.keys() >= REQUIRED_BETA_LANES
        assert payload["ready"] is False
        for lane in lanes.values():
            assert lane["status"] in HANDOFF_STATUSES
            assert lane["ready"] is (lane["status"] == "passed")
            assert lane["operator_action"]
            assert lane["evidence_target"]
        assert not _contains_secret(payload)

    def test_runtime_only_clean_windows_proof_remains_fail_closed(
        self,
        tmp_path: Path,
    ) -> None:
        handoff = importlib.import_module("civiccast.installer.handoff")
        evidence_path = tmp_path / "clean-windows-install.json"
        evidence_path.write_text(
            json.dumps(
                {
                    "status": "partial",
                    "dry_run": False,
                    "will_boot_vm": False,
                    "vm_booted": False,
                    "release_manifest": "artifacts/release/v1.3.0/civiccast-1.3.0-release-artifacts-manifest.json",
                    "generated_at_unix": 1,
                    "attempts": [],
                }
            ),
            encoding="utf-8",
        )

        lane = handoff._clean_windows_lane(evidence_path)

        payload = _dump_payload(lane)
        assert payload["status"] == "blocked"
        assert payload["ready"] is False
        assert "Runtime-only WSL2 proof" in payload["message"]

    def test_disabled_activitypub_handoff_is_optional_and_routes_to_advanced_guide(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_MODE", "disabled")
        handoff = importlib.import_module("civiccast.installer.handoff")

        payload = _dump_payload(handoff._activitypub_lane())

        assert payload["status"] == "passed"
        assert payload["ready"] is True
        assert "optional" in payload["operator_action"].lower()
        assert "technical administrator" in payload["operator_action"].lower()
        assert "keygen" not in payload["operator_action"].lower()
        assert payload["evidence_target"] == "docs/ops/activitypub-federation.md"

    def test_incomplete_activitypub_handoff_stays_blocked_without_beginner_cli(
        self, monkeypatch
    ) -> None:
        config_module = importlib.import_module("civiccast.activitypub.config")
        incomplete = config_module.ActivityPubConfig(federation_mode="approval-only")
        monkeypatch.setattr(config_module, "load_activitypub_config", lambda: incomplete)
        handoff = importlib.import_module("civiccast.installer.handoff")

        payload = _dump_payload(handoff._activitypub_lane())

        action = payload["operator_action"].lower()
        assert payload["status"] == "blocked"
        assert payload["ready"] is False
        assert "keygen" not in action
        assert "`" not in action
        assert "technical administrator" in action
        assert "advanced federation guide" in action
        assert payload["evidence_target"] == "docs/ops/activitypub-federation.md"


class TestInstallerBetaHandoffApi:
    def test_staff_beta_handoff_route_is_hidden_by_default(self, monkeypatch) -> None:
        """G-10: customer wizards must never see internal release-eng lanes."""
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        monkeypatch.delenv("CIVICCAST_RELEASE_ENGINEERING", raising=False)
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/installer/beta-handoff")

        assert response.status_code == 404

    def test_staff_beta_handoff_route_returns_response_model_payload_when_flagged(
        self, monkeypatch
    ) -> None:
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        monkeypatch.setenv("CIVICCAST_RELEASE_ENGINEERING", "1")
        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/installer/beta-handoff")

        assert response.status_code == 200
        payload = response.json()
        assert payload["ready"] is False
        assert {lane["id"] for lane in payload["lanes"]} >= REQUIRED_BETA_LANES
        assert not _contains_secret(payload)

    def test_staff_beta_handoff_route_is_visible_in_openapi_schema(self) -> None:
        from fastapi.testclient import TestClient

        from civiccast.app import create_app

        client = TestClient(create_app(), headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/openapi.json")

        assert response.status_code == 200
        paths = response.json()["paths"]
        operation = paths["/api/staff/installer/beta-handoff"]["get"]
        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/BetaHandoffSummary")
        assert operation["summary"]


class TestBetaPackageAcquisitionCoherence:
    def test_release_manifest_ties_beta_handoff_artifacts_and_install_command(
        self,
        tmp_path: Path,
    ) -> None:
        builder = importlib.import_module("scripts.build_release_artifacts")
        version = "1.2.0"
        windows_installer = tmp_path / f"civiccast-{version}-windows-setup.exe"
        wheel = tmp_path / f"civiccast-{version}-py3-none-any.whl"
        wheelhouse = tmp_path / "wheelhouse" / "WHEELHOUSE-MANIFEST.json"
        model_manifest = tmp_path / f"civiccast-{version}-model-bundle-manifest.json"
        for artifact in (windows_installer, wheel, model_manifest):
            artifact.write_bytes(f"{artifact.name} bytes".encode())
        wheelhouse.parent.mkdir()
        wheelhouse.write_text(
            json.dumps(
                {
                    "target": "linux-x64-cpython-3.12",
                    "install_command": (
                        "python -m pip install --no-index --find-links wheelhouse "
                        f"wheelhouse/civiccast-{version}-py3-none-any.whl"
                    ),
                    "wheels": [{"filename": wheel.name, "sha256": "0" * 64}],
                }
            ),
            encoding="utf-8",
        )

        manifest_artifact = builder.write_artifact_manifest(
            tmp_path,
            version,
            [
                builder.Artifact(windows_installer, "windows-tauri-installer"),
                builder.Artifact(wheel, "python-wheel"),
                builder.Artifact(wheelhouse, "python-wheelhouse-manifest"),
                builder.Artifact(model_manifest, "model-bundle-manifest"),
            ],
        )

        payload = json.loads(manifest_artifact.path.read_text(encoding="utf-8"))
        acquisition = payload["beta_handoff_acquisition"]
        assert acquisition["windows_installer"]["filename"] == windows_installer.name
        assert acquisition["wheel"]["filename"] == wheel.name
        assert acquisition["wheelhouse"]["filename"] == "wheelhouse/WHEELHOUSE-MANIFEST.json"
        assert acquisition["model_bundle_manifest"]["filename"] == model_manifest.name
        assert acquisition["hashes"]["windows_installer"]
        assert acquisition["hashes"]["wheel"]
        assert acquisition["hashes"]["wheelhouse"]
        assert acquisition["hashes"]["model_bundle_manifest"]
        assert wheel.name in acquisition["install_command"]
