# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 runtime evidence and deterministic release rejection."""

from __future__ import annotations

from importlib import import_module


class TestRuntimeEvidenceMachineLine:
    def test_faster_whisper_evidence_line_when_release_runtime_reports(self) -> None:
        evidence_module = import_module("civiccast.ai_runtime.evidence")

        evidence = evidence_module.RuntimeEvidence(
            runtime="faster-whisper",
            model="whisper-large-v3",
            compute="int8",
            digest=None,
            runtime_version="faster-whisper 1.2.1",
            manifest_source="docs/releases/evidence/v1.1-real-ai-proof.json",
        )

        line = evidence.to_machine_line()

        assert "runtime=faster-whisper" in line
        assert "model=whisper-large-v3" in line
        assert "compute=int8" in line
        assert "runtime_version=" in line
        assert "C:\\" not in line
        assert "token" not in line.lower()

    def test_ollama_evidence_line_when_live_model_reports_digest(self) -> None:
        evidence_module = import_module("civiccast.ai_runtime.evidence")

        evidence = evidence_module.RuntimeEvidence(
            runtime="ollama",
            model="gemma4:e4b",
            compute=None,
            digest="sha256:" + ("a" * 64),
            runtime_version="ollama 0.7.0",
            manifest_source="ollama:/api/show/gemma4:e4b",
        )

        line = evidence.to_machine_line()

        assert "runtime=ollama" in line
        assert "model=gemma4:e4b" in line
        assert "digest=sha256:" in line
        assert "manifest_source=ollama:/api/show/gemma4:e4b" in line

    def test_ollama_cloud_evidence_line_for_hosted_summary_tier(self) -> None:
        # S13: the hosted summary tier (gemma4:31b-cloud) reports a distinct
        # provider so its release evidence is attributable. The de-pinned release
        # gate accepts model=<tag>+digest on this provider; this proves the line
        # is producible (not a false-green contract).
        evidence_module = import_module("civiccast.ai_runtime.evidence")

        evidence = evidence_module.RuntimeEvidence(
            runtime="ollama-cloud",
            model="gemma4:31b-cloud",
            compute=None,
            digest="sha256:" + ("c" * 64),
            runtime_version="ollama-cloud",
            manifest_source="ollama-cloud:/api/show/gemma4:31b-cloud",
        )

        line = evidence.to_machine_line()

        assert "runtime=ollama-cloud" in line
        assert "model=gemma4:31b-cloud" in line
        assert "digest=sha256:" in line


class TestDeterministicAdaptersAreTestOnly:
    def test_release_proof_rejects_deterministic_runtime_when_evidence_is_checked(
        self,
    ) -> None:
        evidence_module = import_module("civiccast.ai_runtime.evidence")

        evidence = evidence_module.RuntimeEvidence(
            runtime="deterministic-test",
            model="deterministic-fixture-no-real-model",
            compute=None,
            digest=None,
            runtime_version="test-only",
            manifest_source="tests",
        )

        result = evidence_module.reject_deterministic_release_evidence([evidence])

        assert result.status == "failed"
        assert "deterministic-test" in result.operator_action
        assert "Run the self-hosted RTX proof" in result.operator_action
