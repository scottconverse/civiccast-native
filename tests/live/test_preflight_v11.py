# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 fourteen-step live and publish pre-flight gates."""

from __future__ import annotations

from importlib import import_module


class TestFourteenStepPreflight:
    def test_preflight_runs_fourteen_checks_in_canonical_order(self) -> None:
        preflight_module = import_module("civiccast.live.preflight_probes")

        plan = preflight_module.build_v11_preflight_plan()

        assert [check.key for check in plan.checks] == [
            "staff_token",
            "cdn",
            "syndication",
            "internet_archive",
            "nas_rsync",
            "nas_zfs",
            "model_warm",
            "caption_runtime",
            "summary_runtime",
            "translation_runtime",
            "portal",
            "loudness",
            "audit_hash_chain",
            "publish_target_test_and_verify",
        ]

    def test_failed_preflight_blocks_live_and_publish_with_operator_action(self) -> None:
        preflight_module = import_module("civiccast.live.preflight_probes")

        decision = preflight_module.evaluate_publish_approval(
            [
                preflight_module.GateResult(
                    key="cdn",
                    status="credential_or_secret_required",
                    operator_action="Add CDN credentials, then rerun pre-flight.",
                )
            ]
        )

        assert decision.live_allowed is False
        assert decision.publish_allowed is False
        assert "rerun pre-flight" in decision.operator_action.lower()


class TestPreflightRealProbeBoundaries:
    def test_placeholder_provider_checks_cannot_pass_release_preflight(self) -> None:
        preflight_module = import_module("civiccast.live.preflight_probes")

        result = preflight_module.evaluate_probe_result(
            key="internet_archive",
            proof_mode="placeholder",
            release_mode=True,
        )

        assert result.status == "failed"
        assert "real provider" in result.operator_action.lower()
