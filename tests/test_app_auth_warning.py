# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Runtime startup-warning contract for the v0.3 staff-routes-unauth posture.

Closes audit-team v0.3.0 ENG-002 / QA-017 / SEC-001 — the auth posture is
deferred to v0.4 but operators following the README quickstart have no
runtime feedback that ``/api/staff/*`` is exposed without auth. The app
factory now logs a ``WARNING`` at create time pointing at
``docs/ops/staff-route-protection.md`` and an env-var override
(``CIVICCAST_AUTH_ACK=1``) once the operator confirms their protection
posture.
"""

from __future__ import annotations

import logging

import pytest


class TestStaffAuthStartupWarning:
    """Locks: ``create_app()`` emits exactly one startup WARNING that
    names the unauth posture, points at the ops doc, and surfaces the
    suppress-via-env path. The warning suppresses when
    ``CIVICCAST_AUTH_ACK`` is set to any truthy value."""

    def test_warning_emitted_when_ack_unset(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv("CIVICCAST_AUTH_ACK", raising=False)
        # Ensure no DATABASE_URL so the test stays focused on the auth
        # warning and does not pull in any DB I/O.
        monkeypatch.delenv("DATABASE_URL", raising=False)

        from civiccast.app import create_app

        with caplog.at_level(logging.WARNING, logger="civiccast.app"):
            create_app()

        # Exactly one matching warning record.
        matches = [
            r
            for r in caplog.records
            if r.name == "civiccast.app"
            and r.levelno == logging.WARNING
            and "/api/staff/*" in r.getMessage()
        ]
        assert len(matches) == 1, (
            f"Expected exactly one auth-posture warning, got {len(matches)}: "
            f"{[r.getMessage() for r in matches]}"
        )
        msg = matches[0].getMessage()
        assert "docs/ops/staff-route-protection.md" in msg
        assert "CIVICCAST_AUTH_ACK" in msg
        assert "127.0.0.1" in msg or "loopback" in msg.lower()

    def test_warning_suppressed_when_ack_set(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        from civiccast.app import create_app

        with caplog.at_level(logging.WARNING, logger="civiccast.app"):
            create_app()

        matches = [
            r
            for r in caplog.records
            if r.name == "civiccast.app"
            and r.levelno == logging.WARNING
            and "/api/staff/*" in r.getMessage()
        ]
        assert matches == [], (
            "CIVICCAST_AUTH_ACK=1 must suppress the staff-routes-unauth "
            f"warning; got {[r.getMessage() for r in matches]}"
        )
