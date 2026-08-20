# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 Ollama translation proof and test-only fallbacks."""

from __future__ import annotations

from importlib import import_module

from pytest import MonkeyPatch

from civiccast.ai_runtime.ollama_client import OllamaModelManifest


class TestOllamaTranslationProvider:
    def test_translation_default_uses_translategemma_when_release_mode(
        self, monkeypatch: MonkeyPatch
    ) -> None:
        translate_module = import_module("civiccast.translate.ollama")
        manifest = OllamaModelManifest(
            model="translategemma:4b",
            digest="sha256:" + ("b" * 64),
            runtime_version="ollama 0.9.0",
            manifest_source="http://127.0.0.1:11434/api/tags#translategemma:4b",
            details={},
        )

        monkeypatch.setattr(
            translate_module,
            "get_ollama_model_manifest",
            lambda model, *, base_url: manifest,
        )

        provider = translate_module.OllamaSpanishTranslator.for_release()

        assert provider.model_tag == "translategemma:4b"
        assert provider.runtime_evidence.digest.startswith("sha256:")
        assert "runtime=ollama" in provider.runtime_evidence.to_machine_line()

    def test_translation_bleu_floor_is_reported_when_release_gate_runs(self) -> None:
        translate_module = import_module("civiccast.translate.ollama")

        result = translate_module.evaluate_translation_release_gate(
            candidate="La mocion fue aprobada.",
            reference="La mocion fue aprobada.",
            evidence_line="runtime=ollama model=translategemma:4b digest=sha256:" + ("c" * 64),
        )

        assert result.status == "ok"
        assert result.bleu >= 5
        assert result.evidence_line.startswith("runtime=ollama")
