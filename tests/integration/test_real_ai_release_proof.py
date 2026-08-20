# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""STOP contracts for v1.1 real AI release proof without live credentials."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


class TestRealCaptionWerGate:
    def test_caption_proof_returns_stop_when_rtx_or_fixture_ledger_is_missing(
        self,
    ) -> None:
        proof_module = import_module("scripts.run_real_ai_release_proof")

        result = proof_module.preflight_caption_proof(
            fixture_ledger=Path("docs/releases/evidence/v1.1-fixture-license-ledger.md"),
            require_self_hosted_rtx=True,
        )

        assert result.status in {"ok", "hardware_required", "credential_or_secret_required"}
        assert result.status != "ok" or result.wer_percent <= 50
        assert result.status == "ok" or result.operator_action


class TestOllamaSummaryReleaseGate:
    def test_summary_proof_returns_stop_when_ollama_or_model_is_missing(self) -> None:
        proof_module = import_module("scripts.run_real_ai_release_proof")

        result = proof_module.preflight_ollama_summary_proof(model="gemma4:e4b")

        assert result.status in {"ok", "hardware_required", "credential_or_secret_required"}
        assert result.status != "ok" or result.sourced_claim_refusal_pass_rate == 1.0
        assert result.status == "ok" or "gemma4:e4b" in result.operator_action


class TestOllamaTranslationBleuGate:
    def test_translation_proof_returns_stop_when_ollama_or_model_is_missing(self) -> None:
        proof_module = import_module("scripts.run_real_ai_release_proof")

        result = proof_module.preflight_ollama_translation_proof(
            model="translategemma:4b",
        )

        assert result.status in {"ok", "hardware_required", "credential_or_secret_required"}
        assert result.status != "ok" or result.bleu >= 5
        assert result.status == "ok" or "translategemma:4b" in result.operator_action
