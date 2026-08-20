# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for air-gapped bundle import proof metadata."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path


class TestAirGapImport:
    def test_bundle_import_requires_operator_guide_proof_hashes_and_offline_mode(
        self, tmp_path: Path
    ) -> None:
        airgap = importlib.import_module("civiccast.installer.airgap")
        model_file = tmp_path / "whisper-large-v3.tar.zst"
        model_file.write_bytes(b"offline model bytes")
        digest = hashlib.sha256(model_file.read_bytes()).hexdigest()
        guide = tmp_path / "operator-guide.md"
        guide.write_text("# Offline install\n\nCopy the bundle into the VM.\n", encoding="utf-8")
        proof = tmp_path / "proof.json"
        proof.write_text(
            json.dumps(
                {
                    "operator_guide": guide.name,
                    "artifacts": [{"filename": model_file.name, "sha256": digest}],
                    "network_required": False,
                }
            ),
            encoding="utf-8",
        )

        result = airgap.verify_airgap_bundle(tmp_path, proof_manifest=proof, network_enabled=False)

        assert result.status == "ok"
        assert result.operator_guide == guide.name
        assert result.proof_metadata.artifacts[0].sha256 == digest

    def test_external_provider_credentials_remain_credential_gated(self, tmp_path: Path) -> None:
        airgap = importlib.import_module("civiccast.installer.airgap")

        result = airgap.verify_external_provider_lane(
            provider="internet-archive",
            credentials_present=False,
            offline_mode=True,
        )

        assert result.status == "blocked"
        assert result.reason == "credential_or_secret_required"
        assert "Internet Archive credentials" in result.next_step

    def test_network_enabled_verification_is_rejected(self, tmp_path: Path) -> None:
        airgap = importlib.import_module("civiccast.installer.airgap")

        result = airgap.verify_airgap_bundle(
            tmp_path,
            proof_manifest=tmp_path / "proof.json",
            network_enabled=True,
        )

        assert result.status == "blocked"
        assert result.reason == "network_enabled"
        assert "disable network" in result.next_step.lower()

    def test_missing_proof_metadata_blocks_with_specific_remediation(self, tmp_path: Path) -> None:
        airgap = importlib.import_module("civiccast.installer.airgap")
        guide = tmp_path / "operator-guide.md"
        guide.write_text("# Offline install\n", encoding="utf-8")

        result = airgap.verify_airgap_bundle(
            tmp_path,
            proof_manifest=tmp_path / "missing-proof.json",
            network_enabled=False,
        )

        assert result.status == "blocked"
        assert result.reason == "missing_proof_metadata"
        assert "rebuild the air-gapped bundle" in result.next_step.lower()

    def test_hash_mismatch_blocks_import_and_names_artifact(self, tmp_path: Path) -> None:
        airgap = importlib.import_module("civiccast.installer.airgap")
        model_file = tmp_path / "gemma4-e4b.tar.zst"
        model_file.write_bytes(b"corrupted model bytes")
        guide = tmp_path / "operator-guide.md"
        guide.write_text("# Offline install\n", encoding="utf-8")
        proof = tmp_path / "proof.json"
        proof.write_text(
            json.dumps(
                {
                    "operator_guide": guide.name,
                    "artifacts": [{"filename": model_file.name, "sha256": "0" * 64}],
                    "network_required": False,
                }
            ),
            encoding="utf-8",
        )

        result = airgap.verify_airgap_bundle(tmp_path, proof_manifest=proof, network_enabled=False)

        assert result.status == "blocked"
        assert result.reason == "hash_mismatch"
        assert model_file.name in result.next_step
