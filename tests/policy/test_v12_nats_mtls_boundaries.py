# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy contracts for v1.2 NATS and mTLS implementation boundaries."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "civiccast"


class TestBrokerImportBoundary:
    def test_concrete_nats_adapter_is_the_only_provider_import_surface(self) -> None:
        adapter = import_module("civiccast.platform.nats_broker")
        violations: list[str] = []
        provider_imports: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            relative = path.relative_to(ROOT)
            # Skip vendored third-party trees (e.g. the TSR sidecar's
            # node_modules), which may contain Python-2 tooling scripts that
            # ast.parse cannot read and that are not CivicCast source.
            if "node_modules" in relative.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                if any(name == "nats" or name.startswith("nats.") for name in imported):
                    provider_imports.append(relative.as_posix())
                    if not relative.as_posix().startswith("civiccast/platform/"):
                        violations.append(relative.as_posix())

        assert adapter.__name__ == "civiccast.platform.nats_broker"
        assert provider_imports == ["civiccast/platform/nats_broker.py"]
        assert violations == []

    def test_publish_code_does_not_contain_raw_provider_subjects(self) -> None:
        registry = import_module("civiccast.platform.broker_config")
        publish_files = sorted((SOURCE_ROOT / "publish").rglob("*.py"))
        leaked = [
            path.relative_to(ROOT).as_posix()
            for path in publish_files
            if "civiccast.publish.asset." in path.read_text(encoding="utf-8")
        ]

        assert registry.BROKER_SUBJECT_REGISTRY.require_subject("publish.asset.approved")
        assert leaked == []


class TestPrivateKeyBoundary:
    def test_public_certificate_status_models_do_not_serialize_private_key_fields(self) -> None:
        models = import_module("civiccast.certs.models")

        public_models = (
            models.CertificateAuthorityStatus,
            models.ServiceCertificateStatus,
            models.CertificateRotationStatus,
            models.MTLSReadinessSummary,
        )
        for model in public_models:
            field_names = set(model.model_fields)
            assert "private_key" not in field_names
            assert "private_key_path" not in field_names
            assert "private_key_pem" not in field_names


class TestReleaseVerificationCoverage:
    def test_verify_release_invokes_nats_mtls_test_groups(self) -> None:
        script = (ROOT / "scripts" / "verify-release.sh").read_text(encoding="utf-8")

        assert "tests/platform/test_nats_broker_config.py" in script
        assert "tests/platform/test_nats_broker_adapter.py" in script
        assert "tests/certs/test_local_ca.py" in script
        assert "tests/certs/test_cert_rotation.py" in script
        assert "tests/installer/test_nats_mtls_readiness.py" in script
        assert "tests/policy/test_v12_nats_mtls_boundaries.py" in script
