# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.1 first-run wizard and typed gate results."""

from __future__ import annotations

from importlib import import_module


class TestFirstRunWizardSteps:
    def test_wizard_steps_cover_release_proof_dependencies_in_stable_order(
        self,
    ) -> None:
        wizard_module = import_module("civiccast.installer.wizard")

        plan = wizard_module.build_v11_first_run_wizard()

        assert [step.key for step in plan.steps] == [
            "cdn",
            "syndication",
            "internet_archive",
            "nas",
            "staff_token",
            "model_download",
            "portal",
            "publish_target_test_and_verify",
        ]
        assert plan.supported_states == {"loading", "success", "empty", "error", "partial"}

    def test_missing_staff_token_fails_closed_with_actionable_copy(self) -> None:
        wizard_module = import_module("civiccast.installer.wizard")

        result = wizard_module.verify_staff_token_step(tokens=None)

        assert result.status == "credential_or_secret_required"
        assert "CIVICCAST_STAFF_TOKENS" in result.operator_action
        assert "set" in result.operator_action.lower()
