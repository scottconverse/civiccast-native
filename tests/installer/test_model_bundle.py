# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 offline model bundle manifests and air-gapped install."""

from __future__ import annotations

import hashlib
from importlib import import_module
from pathlib import Path


class TestModelBundleManifest:
    def test_bundle_manifest_names_all_models_with_verified_digests(
        self,
        tmp_path: Path,
    ) -> None:
        bundle_module = import_module("civiccast.installer.model_bundle")
        model_payloads = {
            "whisper-large-v3.tar.zst": b"whisper model bytes",
            "gemma4-12b.tar.zst": b"summary 12b model bytes",
            "gemma4-e4b.tar.zst": b"summary model bytes",
            "translategemma-4b.tar.zst": b"translation model bytes",
        }
        for filename, payload in model_payloads.items():
            (tmp_path / filename).write_bytes(payload)

        manifest = bundle_module.build_v11_model_bundle_manifest(
            output_dir=tmp_path,
        )

        # The air-gapped bundle ships BOTH summary tags so the adaptive 12B/e4b summary
        # default is present offline regardless of detected RAM (S13 E2/T2/Q1).
        assert {model.name for model in manifest.models} == {
            "whisper-large-v3",
            "gemma4:12b",
            "gemma4:e4b",
            "translategemma:4b",
        }
        for model in manifest.models:
            assert model.source
            assert model.license
            assert model.size_bytes > 0
            assert model.sha256
            assert len(model.sha256) == 64
            assert model.sha256 == hashlib.sha256(model_payloads[model.filename]).hexdigest()


class TestOfflineBundleInstall:
    def test_airgapped_install_fails_when_network_is_allowed(
        self,
        tmp_path: Path,
    ) -> None:
        bundle_module = import_module("civiccast.installer.model_bundle")

        result = bundle_module.verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=True,
        )

        assert result.status == "failed"
        assert result.network_allowed is True
        assert "network disabled" in result.operator_action.lower()

    def test_airgapped_install_fails_with_actionable_missing_model_message(
        self,
        tmp_path: Path,
    ) -> None:
        bundle_module = import_module("civiccast.installer.model_bundle")

        result = bundle_module.verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
        )

        assert result.status == "failed"
        assert "missing model" in result.operator_action.lower()
        assert "copy the offline model bundle" in result.operator_action.lower()

    def test_airgapped_install_accepts_exact_files_and_hashes(
        self,
        tmp_path: Path,
    ) -> None:
        bundle_module = import_module("civiccast.installer.model_bundle")
        for filename in (
            "whisper-large-v3.tar.zst",
            "gemma4-12b.tar.zst",
            "gemma4-e4b.tar.zst",
            "translategemma-4b.tar.zst",
        ):
            (tmp_path / filename).write_bytes(f"{filename} bytes".encode())

        result = bundle_module.verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
        )

        assert result.status == "ok"
        assert result.network_allowed is False
        assert "network disabled" in result.operator_action.lower()

    def test_airgapped_install_rejects_hash_mismatch(
        self,
        tmp_path: Path,
    ) -> None:
        bundle_module = import_module("civiccast.installer.model_bundle")
        for filename in (
            "whisper-large-v3.tar.zst",
            "gemma4-12b.tar.zst",
            "gemma4-e4b.tar.zst",
            "translategemma-4b.tar.zst",
        ):
            (tmp_path / filename).write_bytes(f"{filename} bytes".encode())
        manifest = bundle_module.build_v11_model_bundle_manifest(output_dir=tmp_path)
        stale_model = bundle_module.BundleModel(
            name=manifest.models[0].name,
            filename=manifest.models[0].filename,
            source=manifest.models[0].source,
            license=manifest.models[0].license,
            size_bytes=manifest.models[0].size_bytes,
            sha256="0" * 64,
        )
        stale_manifest = bundle_module.V11ModelBundleManifest(
            output_dir=manifest.output_dir,
            models=(stale_model, *manifest.models[1:]),
        )

        result = bundle_module.verify_airgapped_install(
            bundle_dir=tmp_path,
            network_allowed=False,
            manifest=stale_manifest,
        )

        assert result.status == "failed"
        assert "hash mismatches" in result.operator_action.lower()
