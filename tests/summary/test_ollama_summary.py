# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 Ollama summary provenance and validation."""

from __future__ import annotations

from importlib import import_module

from pytest import MonkeyPatch

from civiccast.ai_runtime.ollama_client import OllamaModelManifest


class TestOllamaSummaryProvenance:
    def test_summary_default_uses_live_gemma4_when_release_mode(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        summary_module = import_module("civiccast.summary.ollama")
        manifest = OllamaModelManifest(
            model="gemma4:e4b",
            digest="sha256:" + ("a" * 64),
            runtime_version="ollama 0.9.0",
            manifest_source="http://127.0.0.1:11434/api/tags#gemma4:e4b",
            details={},
        )

        monkeypatch.setattr(
            summary_module,
            "get_ollama_model_manifest",
            lambda model, *, base_url: manifest,
        )

        adapter = summary_module.OllamaSummaryModel.for_release()

        assert adapter.model_tag == "gemma4:e4b"
        assert adapter.provenance.digest.startswith("sha256:")
        assert adapter.provenance.ollama_version
        assert adapter.provenance.manifest_source
        assert "runtime=ollama" in adapter.provenance.evidence_line

    def test_summary_refuses_unsupported_claims_when_ollama_output_is_uncited(
        self,
    ) -> None:
        summary_module = import_module("civiccast.summary.ollama")

        result = summary_module.validate_ollama_summary_output(
            transcript_text="The council approved item 4A.",
            model_output="The council approved item 4A and sold the city hall.",
            citations=["The council approved item 4A."],
        )

        assert result.status == "refused"
        assert "unsupported claim" in result.operator_action.lower()
