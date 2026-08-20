# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""STOP contracts for v1.1 VM cleanroom and air-gapped release proof."""

from __future__ import annotations

import hashlib
import json
from importlib import import_module
from pathlib import Path


class TestVmCleanroomRequiresArtifacts:
    def test_cleanroom_refuses_working_tree_install_when_release_proof_runs(
        self,
        tmp_path: Path,
    ) -> None:
        cleanroom_module = import_module("scripts.run_vm_cleanroom_release")
        artifact = tmp_path / "civiccast-1.1.0-source.tar.gz"
        artifact.write_bytes(b"release candidate bytes")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {
                            "filename": artifact.name,
                            "sha256": digest,
                            "size_bytes": artifact.stat().st_size,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = cleanroom_module.plan_vm_cleanroom_install(
            artifact_manifest=manifest,
            source_tree=Path.cwd(),
        )

        assert result.status == "ok"
        assert result.install_source == "release-candidate-artifacts"
        assert result.artifact_hashes == (f"sha256:{digest}",)

    def test_cleanroom_rejects_manifest_hash_mismatch(
        self,
        tmp_path: Path,
    ) -> None:
        cleanroom_module = import_module("scripts.run_vm_cleanroom_release")
        artifact = tmp_path / "civiccast-1.1.0-source.tar.gz"
        artifact.write_bytes(b"tampered release candidate bytes")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {
                            "filename": artifact.name,
                            "sha256": "0" * 64,
                            "size_bytes": artifact.stat().st_size,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = cleanroom_module.plan_vm_cleanroom_install(
            artifact_manifest=manifest,
            source_tree=Path.cwd(),
        )

        assert result.status == "failed"
        assert "hash mismatch" in result.operator_action.lower()
        assert not result.artifact_hashes

    def test_cleanroom_reports_hardware_required_when_vm_target_is_unavailable(
        self,
    ) -> None:
        cleanroom_module = import_module("scripts.run_vm_cleanroom_release")

        result = cleanroom_module.preflight_vm_target(vm_name="civiccast-v11-cleanroom")

        assert result.status in {"ok", "hardware_required"}
        assert result.status == "ok" or "VM" in result.operator_action
