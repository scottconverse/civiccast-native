# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 installer local-CA mTLS readiness.

Formerly ``test_nats_mtls_readiness.py``. NATS JetStream was removed from
the product (owner decision 2026-08-20; see ADR 0023, which supersedes ADR
0001), so every NATS-JetStream-specific readiness test (the ``nats-jetstream``
health check, ``check_nats_readiness``, ``BrokerConfig``'s production/NATS
fields) was removed along with it. Local-CA mTLS readiness (``mtls-local-ca``)
stands on its own now, covering only the ``civiccast-api`` and
``civiccast-worker`` service identities.
"""

from __future__ import annotations

from pathlib import Path

from civiccast.installer.service import build_system_health_report, run_first_health_check


def _write_mtls_files(root: Path) -> dict[str, str]:
    ca_file = root / "ca.crt"
    cert_file = root / "client.crt"
    key_file = root / "client.key"
    ca_file.write_text("test ca")
    cert_file.write_text("test cert")
    key_file.write_text("test key")
    return {
        "ca_file": str(ca_file),
        "cert_file": str(cert_file),
        "key_file": str(key_file),
    }


class TestInstallerMTLSReadiness:
    def test_first_run_health_includes_required_mtls_check(self) -> None:
        report = run_first_health_check(profile="public-meetings")
        checked = {check.id: check for check in report.checks}

        assert "mtls-local-ca" in checked
        assert checked["mtls-local-ca"].state != "ok"

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

        def fake_cert_readiness():
            calls.append("certs")
            return True

        monkeypatch.setattr(
            "civiccast.certs.readiness.check_mtls_readiness",
            fake_cert_readiness,
            raising=False,
        )

        report = run_first_health_check(profile="public-meetings")
        checked = {item.id: item for item in report.checks}

        assert checked["mtls-local-ca"].state == "ok"
        assert calls == ["certs"]


class TestSystemHealthAdvancedChecks:
    def test_system_health_includes_advanced_mtls_check(self) -> None:
        report = build_system_health_report()
        checks = {check.id: check for check in report.checks}

        assert "mtls-local-ca" in checks
        assert checks["mtls-local-ca"].required is False

    def test_mtls_remediation_stays_in_advanced_health(self) -> None:
        report = build_system_health_report()
        checks = {check.id: check for check in report.checks}

        assert "civiccast cert rotate" in checks["mtls-local-ca"].next_step.lower()
