# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 installer NATS and mTLS readiness."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from civiccast.installer.service import build_system_health_report, run_first_health_check
from civiccast.platform.broker_config import (
    BrokerConfig,
    BrokerReadinessError,
    check_nats_readiness,
)


def _write_mtls_files(root: Path) -> dict[str, str]:
    ca_file = root / "ca.crt"
    cert_file = root / "client.crt"
    key_file = root / "client.key"
    ca_file.write_text("test ca")
    cert_file.write_text("test cert")
    key_file.write_text("test key")
    return {
        "nats_ca_file": str(ca_file),
        "nats_client_cert_file": str(cert_file),
        "nats_client_key_file": str(key_file),
        "CIVICCAST_NATS_CA_FILE": str(ca_file),
        "CIVICCAST_NATS_CLIENT_CERT_FILE": str(cert_file),
        "CIVICCAST_NATS_CLIENT_KEY_FILE": str(key_file),
    }


class TestInstallerNATSMTLSReadiness:
    def test_first_run_health_includes_required_nats_and_mtls_checks(self) -> None:
        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        assert {"nats-jetstream", "mtls-local-ca"} <= set(checked)
        assert checked["nats-jetstream"].state != "ok"
        assert checked["mtls-local-ca"].state != "ok"

    def test_missing_nats_config_blocks_with_specific_remediation(self, monkeypatch) -> None:
        monkeypatch.delenv("CIVICCAST_NATS_URL", raising=False)

        report = run_first_health_check(profile="public-meetings")
        check = {item.id: item for item in report.checks}["nats-jetstream"]

        assert check.state in {"failed", "error", "credential_or_secret_required"}
        assert "CIVICCAST_NATS_URL" in check.message
        assert "set CIVICCAST_NATS_URL" in check.next_step.lower()

    def test_unreachable_nats_blocks_with_connection_guidance(self, monkeypatch, tmp_path) -> None:
        paths = _write_mtls_files(tmp_path)
        monkeypatch.setenv("CIVICCAST_NATS_URL", "tls://127.0.0.1:9")
        monkeypatch.setenv("CIVICCAST_NATS_STREAM", "CIVICCAST_EVENTS")
        monkeypatch.setenv("CIVICCAST_NATS_CA_FILE", paths["CIVICCAST_NATS_CA_FILE"])
        monkeypatch.setenv(
            "CIVICCAST_NATS_CLIENT_CERT_FILE", paths["CIVICCAST_NATS_CLIENT_CERT_FILE"]
        )
        monkeypatch.setenv(
            "CIVICCAST_NATS_CLIENT_KEY_FILE", paths["CIVICCAST_NATS_CLIENT_KEY_FILE"]
        )

        report = run_first_health_check(profile="public-meetings")
        check = {item.id: item for item in report.checks}["nats-jetstream"]

        assert check.state in {"failed", "error"}
        assert "unreachable" in check.message.lower() or "connection" in check.message.lower()
        assert "nats" in check.next_step.lower()

    def test_nats_url_must_use_tls_for_mtls_transport(self, monkeypatch, tmp_path) -> None:
        paths = _write_mtls_files(tmp_path)
        monkeypatch.setenv("CIVICCAST_NATS_URL", "nats://127.0.0.1:4222")
        monkeypatch.setenv("CIVICCAST_NATS_STREAM", "CIVICCAST_EVENTS")
        monkeypatch.setenv("CIVICCAST_NATS_CA_FILE", paths["CIVICCAST_NATS_CA_FILE"])
        monkeypatch.setenv(
            "CIVICCAST_NATS_CLIENT_CERT_FILE", paths["CIVICCAST_NATS_CLIENT_CERT_FILE"]
        )
        monkeypatch.setenv(
            "CIVICCAST_NATS_CLIENT_KEY_FILE", paths["CIVICCAST_NATS_CLIENT_KEY_FILE"]
        )

        report = run_first_health_check(profile="public-meetings")
        check = {item.id: item for item in report.checks}["nats-jetstream"]

        assert check.state in {"failed", "error"}
        assert "tls://" in f"{check.message} {check.next_step}"

    def test_invalid_stream_subject_config_names_bad_field(self, monkeypatch) -> None:
        monkeypatch.setenv("CIVICCAST_NATS_URL", "nats://127.0.0.1:4222")
        monkeypatch.setenv("CIVICCAST_NATS_STREAM", "raw-events")

        report = run_first_health_check(profile="public-meetings")
        check = {item.id: item for item in report.checks}["nats-jetstream"]

        assert check.state in {"failed", "error"}
        assert "CIVICCAST_NATS_STREAM" in f"{check.message} {check.next_step}"

    def test_missing_or_expired_service_certificates_block_with_rotate_guidance(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CERT_ROOT", str(tmp_path))

        report = run_first_health_check(profile="public-meetings")
        check = {item.id: item for item in report.checks}["mtls-local-ca"]

        assert check.state in {"failed", "error"}
        assert "certificate" in check.message.lower()
        assert "civiccast cert rotate" in check.next_step

    def test_checks_become_ok_only_after_readiness_functions_prove_state(self, monkeypatch) -> None:
        calls: list[str] = []

        def fake_nats_readiness():
            calls.append("nats")
            return True

        def fake_cert_readiness():
            calls.append("certs")
            return True

        monkeypatch.setattr(
            "civiccast.platform.broker_config.check_nats_readiness",
            fake_nats_readiness,
            raising=False,
        )
        monkeypatch.setattr(
            "civiccast.certs.readiness.check_mtls_readiness",
            fake_cert_readiness,
            raising=False,
        )

        report = run_first_health_check(profile="public-meetings")
        checked = {item.id: item for item in report.checks}

        assert checked["nats-jetstream"].state == "ok"
        assert checked["mtls-local-ca"].state == "ok"
        assert calls == ["nats", "certs"]

    def test_reachable_socket_without_jetstream_stream_proof_stays_blocked(
        self, monkeypatch, tmp_path
    ) -> None:
        paths = _write_mtls_files(tmp_path)

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        class NoStreamJetStream:
            pass

        monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: FakeSocket())

        with pytest.raises(BrokerReadinessError, match="stream/subject validation failed"):
            check_nats_readiness(
                BrokerConfig(
                    mode="production",
                    nats_url="tls://127.0.0.1:4222",
                    stream_name="CIVICCAST_EVENTS",
                    durable_name="civiccast-publish",
                    nats_ca_file=paths["nats_ca_file"],
                    nats_client_cert_file=paths["nats_client_cert_file"],
                    nats_client_key_file=paths["nats_client_key_file"],
                ),
                jetstream=NoStreamJetStream(),
            )


class TestSystemHealthAdvancedChecks:
    def test_system_health_includes_advanced_broker_and_mtls_checks(self) -> None:
        report = build_system_health_report()
        checks = {check.id: check for check in report.checks}

        assert {"nats-jetstream", "mtls-local-ca"} <= set(checks)
        assert checks["nats-jetstream"].required is False
        assert checks["mtls-local-ca"].required is False

    def test_broker_and_mtls_remediation_stays_in_advanced_health(self) -> None:
        report = build_system_health_report()
        checks = {check.id: check for check in report.checks}

        assert "nats" in checks["nats-jetstream"].next_step.lower()
        assert "civiccast cert rotate" in checks["mtls-local-ca"].next_step.lower()
