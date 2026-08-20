# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.2 local-CA mTLS service."""

from __future__ import annotations

from importlib import import_module

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID


def _authority_module():
    return import_module("civiccast.certs.authority")


def _pem_private_key_marker() -> str:
    return "BEGIN " + "PRIVATE " + "KEY"


def _private_key_marker() -> str:
    return "PRIVATE " + "KEY"


class TestLocalCAService:
    def test_new_ca_can_be_created_in_install_root(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)

        status = service.create_ca(common_name="CivicCast Local CA")

        assert status.ca_certificate_path.exists()
        assert status.fingerprint_sha256
        assert status.private_key_path is None

    def test_ca_certificate_is_inspectable_without_private_key_material(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")

        status = service.inspect_ca()
        serialized = status.model_dump_json()

        assert "CivicCast Local CA" in serialized
        assert _pem_private_key_marker() not in serialized
        assert _private_key_marker() not in serialized

    def test_required_service_certificates_include_expected_identity_sans(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")

        issued = service.issue_service_certificate("civiccast-api")

        assert issued.service_identity == "civiccast-api"
        assert "civiccast-api" in issued.subject_alternative_names
        assert issued.certificate_path.exists()
        assert issued.private_key_path is None

    def test_service_certificates_include_tls_key_usage_for_mtls(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")

        api = service.issue_service_certificate("civiccast-api")
        nats = service.issue_service_certificate("nats")

        api_cert = x509.load_pem_x509_certificate(api.certificate_path.read_bytes())
        nats_cert = x509.load_pem_x509_certificate(nats.certificate_path.read_bytes())

        assert (
            ExtendedKeyUsageOID.CLIENT_AUTH
            in api_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        )
        assert (
            ExtendedKeyUsageOID.SERVER_AUTH
            in nats_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        )

    def test_status_responses_expose_paths_fingerprints_and_expiry_only(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")

        issued = service.issue_service_certificate("nats")
        payload = issued.model_dump()

        assert payload["certificate_path"]
        assert payload["fingerprint_sha256"]
        assert payload["not_after"]
        assert "private_key" not in payload
        assert "private_key_pem" not in payload

    def test_repeated_inspect_calls_are_idempotent(self, tmp_path) -> None:
        authority = _authority_module()
        service = authority.LocalCertificateAuthority(tmp_path)
        service.create_ca(common_name="CivicCast Local CA")
        service.issue_service_certificate("civiccast-worker")

        first = service.inspect_service_certificate("civiccast-worker")
        second = service.inspect_service_certificate("civiccast-worker")

        assert first == second
