# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy contracts for v1.2 mTLS implementation boundaries.

Formerly ``test_v12_nats_mtls_boundaries.py``. NATS JetStream was removed
from the product (owner decision 2026-08-20; see ADR 0023, which supersedes
ADR 0001), so the NATS-specific provider-import-boundary test (which
imported the now-deleted ``civiccast.platform.nats_broker`` module) was
removed along with it. The remaining contracts here are general and were
never NATS-specific.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "civiccast"


class TestBrokerImportBoundary:
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
    def test_verify_release_invokes_mtls_test_groups(self) -> None:
        script = (ROOT / "scripts" / "verify-release.sh").read_text(encoding="utf-8")

        assert "tests/certs/test_local_ca.py" in script
        assert "tests/certs/test_cert_rotation.py" in script
        assert "tests/policy/test_v12_mtls_boundaries.py" in script
