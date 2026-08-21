# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.2 certificate rotation CLI."""

from __future__ import annotations

from typer.testing import CliRunner

from civiccast.cli import app


def _pem_private_key_marker() -> str:
    return "BEGIN " + "PRIVATE " + "KEY"


def _private_key_marker() -> str:
    return "PRIVATE " + "KEY"


class TestCertCLI:
    def test_cert_rotate_invokes_rotation_service(self, monkeypatch, tmp_path) -> None:
        calls: list[str] = []

        def fake_rotate(root, identity):
            calls.append(identity)
            return {"service_identity": identity, "fingerprint_sha256": "a" * 64}

        monkeypatch.setenv("CIVICCAST_CERT_ROOT", str(tmp_path))
        monkeypatch.setattr(
            "civiccast.certs.authority.rotate_service_certificate",
            fake_rotate,
            raising=False,
        )

        result = CliRunner().invoke(app, ["cert", "rotate", "civiccast-api"])

        assert result.exit_code == 0
        assert calls == ["civiccast-api"]

    def test_cert_rotate_emits_no_private_key_material(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("CIVICCAST_CERT_ROOT", str(tmp_path))

        result = CliRunner().invoke(app, ["cert", "rotate", "civiccast-worker", "--json"])

        assert result.exit_code == 0
        assert _pem_private_key_marker() not in result.output
        assert _private_key_marker() not in result.output

    def test_cert_rotate_exits_nonzero_on_blocked_rotation_with_actionable_text(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CERT_ROOT", str(tmp_path))

        result = CliRunner().invoke(app, ["cert", "rotate", "unknown-service"])

        assert result.exit_code != 0
        assert "known service identity" in result.output.lower()
        assert "civiccast cert rotate civiccast-api" in result.output
