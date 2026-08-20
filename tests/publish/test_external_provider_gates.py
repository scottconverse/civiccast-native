# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 external provider credential, hardware, and deferral gates."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


class TestProviderCredentialGates:
    def test_missing_provider_credentials_return_stop_statuses(self) -> None:
        providers_module = import_module("civiccast.publish.providers")

        for provider in ["internet_archive", "youtube", "email", "webhook", "nas"]:
            result = providers_module.check_provider_credentials(provider, env={})
            assert result.status == "credential_or_secret_required"
            assert provider.replace("_", " ") in result.operator_action.lower()
            assert result.proof_mode != "mock"


class TestProviderHardwareGates:
    def test_missing_local_hardware_returns_hardware_required(self) -> None:
        providers_module = import_module("civiccast.publish.providers")

        result = providers_module.check_nas_hardware(
            mount_path=Path("Z:/missing-nas"),
            require_rsync=True,
            require_zfs=True,
        )

        assert result.status == "hardware_required"
        assert "NAS" in result.operator_action or "ZFS" in result.operator_action


class TestZfsDeferralRequiresScott:
    def test_zfs_deferral_requires_exact_approved_ledger_row(self) -> None:
        providers_module = import_module("civiccast.publish.providers")

        result = providers_module.evaluate_zfs_deferral(
            ledger_path=Path("docs/releases/spec-alignment-ledger-v1.1.md"),
        )

        assert result.status in {"deferred_by_scott", "hardware_required"}
        assert result.status != "deferred_by_scott" or result.approver == "Scott"
        assert result.status != "deferred_by_scott" or "v1.1 local archive peer" in result.text
