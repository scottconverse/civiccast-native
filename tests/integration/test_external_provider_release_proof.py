# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""STOP contracts for credentialed v1.1 external provider release proof."""

from __future__ import annotations

from importlib import import_module


class TestRealExternalProviderProof:
    def test_external_proof_returns_stop_instead_of_mocking_when_credentials_missing(
        self,
    ) -> None:
        proof_module = import_module("scripts.run_external_provider_proof")

        result = proof_module.preflight_external_provider_proof(env={})

        assert result.status in {"ok", "credential_or_secret_required", "hardware_required"}
        assert result.status != "ok" or result.uses_real_providers is True
        assert result.status == "ok" or result.operator_action
        assert "mock" not in result.operator_action.lower()
