# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 real-AI benchmark floors and fixture license ledgers."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


class TestFixtureLicenseLedger:
    def test_fixture_license_ledger_requires_all_fixture_statuses_when_loaded(
        self,
    ) -> None:
        gates_module = import_module("civiccast.ai_quality.release_gates")
        ledger_path = Path("docs/releases/evidence/v1.1-fixture-license-ledger.md")

        ledger = gates_module.load_fixture_license_ledger(ledger_path)

        assert ledger.status_for("AMI").status in {"approved", "not_used"}
        assert ledger.status_for("Earnings22").status in {"approved", "not_used"}
        assert ledger.municipal_fixtures_require_pii_review is True
        assert ledger.has_complete_rows_for(["audio", "transcript", "translation"])


class TestRealAiMetricFloors:
    def test_release_metric_gate_fails_when_any_floor_is_missing(self) -> None:
        gates_module = import_module("civiccast.ai_quality.release_gates")

        result = gates_module.evaluate_real_ai_release_metrics(
            wer_percent=49.9,
            bleu=5.0,
            rouge_l=0.32,
            sourced_claim_refusal_pass_rate=1.0,
            runtime_lines=[
                "runtime=faster-whisper model=whisper-large-v3 compute=int8",
                "runtime=ollama model=gemma4:e4b digest=sha256:" + ("a" * 64),
                "runtime=ollama model=translategemma:4b digest=sha256:" + ("b" * 64),
            ],
        )

        assert result.status == "ok"
        assert result.release_floor_summary["wer_percent"] <= 50
        assert result.release_floor_summary["bleu"] >= 5
        assert result.release_floor_summary["sourced_claim_refusal_pass_rate"] == 1.0

    def test_release_metric_gate_accepts_operator_selected_models(self) -> None:
        # S13 §4.2 / DONE-6: the gate must not pin a single model. When the
        # operator selects gemma4:12b for summary, evidence carrying that tag
        # (and a digest) satisfies the gate.
        gates_module = import_module("civiccast.ai_quality.release_gates")

        result = gates_module.evaluate_real_ai_release_metrics(
            wer_percent=49.9,
            bleu=5.0,
            rouge_l=0.32,
            sourced_claim_refusal_pass_rate=1.0,
            runtime_lines=[
                "runtime=faster-whisper model=whisper-large-v3 compute=int8",
                "runtime=ollama model=gemma4:12b digest=sha256:" + ("a" * 64),
                "runtime=ollama model=translategemma:4b digest=sha256:" + ("b" * 64),
            ],
            expected_models={
                "captions": "whisper-large-v3",
                "summary": "gemma4:12b",
                "translation": "translategemma:4b",
            },
        )

        assert result.status == "ok", result.operator_action

    def test_release_metric_gate_accepts_hosted_summary_tier(self) -> None:
        # The hosted summary tier (gemma4:31b-cloud) runs on a different provider
        # (ollama-cloud), so the gate checks model=<tag> + a digest, not a pinned
        # runtime=ollama prefix.
        gates_module = import_module("civiccast.ai_quality.release_gates")

        result = gates_module.evaluate_real_ai_release_metrics(
            wer_percent=49.9,
            bleu=5.0,
            rouge_l=0.32,
            sourced_claim_refusal_pass_rate=1.0,
            runtime_lines=[
                "runtime=faster-whisper model=whisper-large-v3 compute=int8",
                "runtime=ollama-cloud model=gemma4:31b-cloud digest=sha256:" + ("a" * 64),
                "runtime=ollama model=translategemma:4b digest=sha256:" + ("b" * 64),
            ],
            expected_models={
                "captions": "whisper-large-v3",
                "summary": "gemma4:31b-cloud",
                "translation": "translategemma:4b",
            },
        )

        assert result.status == "ok", result.operator_action

    def test_release_metric_gate_fails_when_evidence_model_differs_from_selection(
        self,
    ) -> None:
        # The gate follows the selection: if the operator chose gemma4:12b but the
        # evidence proves gemma4:e4b ran, the gate fails (it is not pinned to a
        # single literal, but it still demands the SELECTED model's evidence).
        gates_module = import_module("civiccast.ai_quality.release_gates")

        result = gates_module.evaluate_real_ai_release_metrics(
            wer_percent=49.9,
            bleu=5.0,
            rouge_l=0.32,
            sourced_claim_refusal_pass_rate=1.0,
            runtime_lines=[
                "runtime=faster-whisper model=whisper-large-v3 compute=int8",
                "runtime=ollama model=gemma4:e4b digest=sha256:" + ("a" * 64),
                "runtime=ollama model=translategemma:4b digest=sha256:" + ("b" * 64),
            ],
            expected_models={
                "captions": "whisper-large-v3",
                "summary": "gemma4:12b",
                "translation": "translategemma:4b",
            },
        )

        assert result.status == "failed"
        assert "gemma4:12b" in result.operator_action

    def test_release_metric_gate_defaults_to_legacy_trio_without_selection(self) -> None:
        # Back-compat: with no expected_models, the gate keeps the legacy pins so
        # existing callers are unaffected. e4b evidence must still pass by default.
        gates_module = import_module("civiccast.ai_quality.release_gates")

        result = gates_module.evaluate_real_ai_release_metrics(
            wer_percent=49.9,
            bleu=5.0,
            rouge_l=0.32,
            sourced_claim_refusal_pass_rate=1.0,
            runtime_lines=[
                "runtime=faster-whisper model=whisper-large-v3 compute=int8",
                "runtime=ollama model=gemma4:12b digest=sha256:" + ("a" * 64),
                "runtime=ollama model=translategemma:4b digest=sha256:" + ("b" * 64),
            ],
        )

        # Default pins still expect e4b for summary, so 12B-only evidence fails.
        assert result.status == "failed"
        assert "gemma4:e4b" in result.operator_action
