# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 hash-chain audit verification and doctor output."""

from __future__ import annotations

from importlib import import_module


class TestDoctorAuditHashChain:
    def test_doctor_audit_detects_tampered_hash_chain(self) -> None:
        audit_module = import_module("civiccast.platform.audit")

        result = audit_module.verify_hash_chain(
            [
                {"id": "a", "hash": "sha256:aaa", "previous_hash": None},
                {"id": "b", "hash": "sha256:bbb", "previous_hash": "sha256:wrong"},
            ]
        )

        assert result.status == "failed"
        assert "tamper" in result.operator_action.lower()
        assert "civiccast doctor audit" in result.command

    def test_doctor_audit_reports_missing_links_with_repair_guidance(self) -> None:
        audit_module = import_module("civiccast.platform.audit")

        result = audit_module.verify_hash_chain(
            [{"id": "b", "hash": "sha256:bbb", "previous_hash": "sha256:missing"}]
        )

        assert result.status == "failed"
        assert "missing" in result.operator_action.lower()
        assert "restore" in result.operator_action.lower()
