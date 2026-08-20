# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.2 air-gapped VM proof runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import run_airgap_vm_proof as proof


def _write_release_manifest(tmp_path: Path) -> Path:
    artifact = tmp_path / "civiccast-1.1.1-py3-none-any.whl"
    artifact.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "release-manifest.json"
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
    return manifest


def _write_model_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "model-bundle"
    bundle.mkdir()
    for filename in (
        "whisper-large-v3.tar.zst",
        "gemma4-e4b.tar.zst",
        "translategemma-4b.tar.zst",
    ):
        (bundle / filename).write_bytes(f"{filename} bytes".encode())
    return bundle


def _write_wheelhouse(release_dir: Path) -> Path:
    wheelhouse = release_dir / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "civiccast-1.1.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel bytes")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
        json.dumps(
            {
                "target": "linux-x64-cpython-3.12",
                "wheels": [
                    {
                        "filename": wheel.name,
                        "sha256": digest,
                        "size_bytes": wheel.stat().st_size,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return wheelhouse


class TestAirgapVmProofHostChecks:
    def test_release_manifest_hash_mismatch_blocks(self, tmp_path: Path) -> None:
        artifact = tmp_path / "civiccast-1.1.1-py3-none-any.whl"
        artifact.write_bytes(b"tampered")
        manifest = tmp_path / "release-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {
                            "filename": artifact.name,
                            "sha256": "0" * 64,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = proof.verify_release_manifest(tmp_path, manifest.name)

        assert result.status == "blocked"
        assert "hash mismatch" in result.detail

    def test_model_bundle_requires_all_three_real_model_artifacts(self, tmp_path: Path) -> None:
        bundle = tmp_path / "model-bundle"
        bundle.mkdir()
        (bundle / "whisper-large-v3.tar.zst").write_bytes(b"caption")

        result = proof.verify_model_bundle(bundle)

        assert result.status == "blocked"
        assert "gemma4-e4b.tar.zst" in result.detail
        assert "translategemma-4b.tar.zst" in result.detail

    def test_missing_wheelhouse_blocks_full_airgap_install_claim(self, tmp_path: Path) -> None:
        result = proof.check_offline_wheelhouse(tmp_path)

        assert result.status == "blocked"
        assert "network-disabled VM cannot install CivicCast" in result.detail

    def test_wheelhouse_manifest_hash_mismatch_blocks(self, tmp_path: Path) -> None:
        wheelhouse = tmp_path / "wheelhouse"
        wheelhouse.mkdir()
        wheel = wheelhouse / "civiccast-1.1.1-py3-none-any.whl"
        wheel.write_bytes(b"tampered")
        (wheelhouse / "WHEELHOUSE-MANIFEST.json").write_text(
            json.dumps({"wheels": [{"filename": wheel.name, "sha256": "0" * 64}]}),
            encoding="utf-8",
        )

        result = proof.check_offline_wheelhouse(tmp_path)

        assert result.status == "blocked"
        assert "hash mismatch" in result.detail

    def test_wheelhouse_manifest_real_hash_passes(self, tmp_path: Path) -> None:
        _write_wheelhouse(tmp_path)

        result = proof.check_offline_wheelhouse(tmp_path)

        assert result.status == "passed"
        assert "civiccast-1.1.1-py3-none-any.whl=sha256:" in result.detail

    def test_full_host_proof_writes_blocked_evidence_until_wheelhouse_exists(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        manifest = _write_release_manifest(tmp_path)
        bundle = _write_model_bundle(tmp_path)
        evidence = tmp_path / "evidence.md"
        monkeypatch.setattr(
            proof,
            "wsl_available",
            lambda vm_name: proof.ProofCheck("WSL2 VM target", "passed", f"{vm_name} available"),
        )

        result = proof.run_proof(
            vm_name="Ubuntu",
            release_dir=tmp_path,
            bundle_dir=bundle,
            manifest_name=manifest.name,
            evidence_path=evidence,
            execute_vm=False,
        )

        assert result.status == "blocked"
        assert evidence.exists()
        text = evidence.read_text(encoding="utf-8")
        assert "offline Python dependency wheelhouse" in text
        assert "Not executed; rerun with --execute-vm" in text

    def test_full_proof_passes_when_wheelhouse_and_vm_install_pass(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        manifest = _write_release_manifest(tmp_path)
        bundle = _write_model_bundle(tmp_path)
        _write_wheelhouse(tmp_path)
        evidence = tmp_path / "evidence.md"
        monkeypatch.setattr(
            proof,
            "wsl_available",
            lambda vm_name: proof.ProofCheck("WSL2 VM target", "passed", f"{vm_name} available"),
        )
        monkeypatch.setattr(
            proof,
            "run_wsl_network_isolation_check",
            lambda vm_name, *, release_dir, bundle_dir: proof.ProofCheck(
                "VM network-isolated install",
                "passed",
                f"{vm_name} installed from {release_dir} and verified {bundle_dir}",
            ),
        )

        result = proof.run_proof(
            vm_name="Ubuntu",
            release_dir=tmp_path,
            bundle_dir=bundle,
            manifest_name=manifest.name,
            evidence_path=evidence,
            execute_vm=True,
        )

        assert result.status == "passed"
        text = evidence.read_text(encoding="utf-8")
        assert "VM network-isolated install" in text
        assert "application wheel, dependency wheelhouse, and offline model bundle" in text


class TestAirgapVmProofShellSafety:
    def test_bash_quoting_handles_single_quotes(self) -> None:
        assert proof._quote_bash("path/with'quote") == "'path/with'\"'\"'quote'"

    def test_windows_path_to_wsl_path_preserves_spaces(self) -> None:
        converted = proof._windows_path_to_wsl(
            Path("C:/Users/scott/OneDrive/Desktop/Claude/CivicCast/artifacts/model-bundle")
        )

        assert (
            converted
            == "/mnt/c/Users/scott/OneDrive/Desktop/Claude/CivicCast/artifacts/model-bundle"
        )
