# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 local-CA service certificate rotation."""

from __future__ import annotations

from importlib import import_module


def _authority_module():
    return import_module("civiccast.certs.authority")


def _pem_private_key_marker() -> str:
    return "BEGIN " + "PRIVATE " + "KEY"


def _private_key_marker() -> str:
    return "PRIVATE " + "KEY"


class TestCertificateRotation:
    def test_not_due_certificate_is_reported_healthy(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")
        service.issue_service_certificate("civiccast-api", valid_days=90)

        status = service.rotation_status("civiccast-api")

        assert status.state == "healthy"
        assert status.rotation_due is False

    def test_near_expiry_certificate_reports_rotation_due_with_next_step(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")
        service.issue_service_certificate("civiccast-api", valid_days=3)

        status = service.rotation_status("civiccast-api")

        assert status.state == "rotation_due"
        assert status.rotation_due is True
        assert "civiccast cert rotate civiccast-api" in status.next_step

    def test_rotate_replaces_service_credentials_while_preserving_ca_trust(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")
        before = service.issue_service_certificate("civiccast-worker", valid_days=3)

        after = service.rotate_service_certificate("civiccast-worker")

        assert after.service_identity == "civiccast-worker"
        assert after.issuer_fingerprint_sha256 == before.issuer_fingerprint_sha256
        assert after.fingerprint_sha256 != before.fingerprint_sha256

    def test_retired_credential_metadata_is_available_without_key_contents(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")
        service.issue_service_certificate("civiccast-worker", valid_days=3)

        rotation = service.rotate_service_certificate("civiccast-worker")
        payload = rotation.model_dump_json()

        assert rotation.retired_certificate_fingerprint_sha256
        assert _pem_private_key_marker() not in payload
        assert _private_key_marker() not in payload
