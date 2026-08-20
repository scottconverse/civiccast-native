# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 slice 4 — wire summary/translate/captions to the operator-selected model.

The three feature adapters must consult :class:`AiModelService`'s effective model
instead of their hard-coded tags. When no operator selection exists, the resolved
runtime tag MUST equal each feature's *current* catalog default (behavior-preserving
w.r.t. whatever the catalog names as the default at any given time):

* summary (>=16GB RAM)  -> ``gemma4:12b``     (adaptive default)
* summary (<16GB RAM)   -> ``gemma4:e4b``     (adaptive default)
* translation           -> ``translategemma:4b``
* captions              -> ``medium``         (faster-whisper id; ``whisper-`` stripped)

The slug->tag resolution lives at this wiring boundary (the catalog ``model_id``),
NOT inside the adapters; the captions ``whisper-`` prefix is stripped here so the
``FasterWhisperRuntime`` loads whatever the catalog's effective captions tag names.
As of OWNER-DECISION-caption-adaptive-tier.md (2026-07-30, BINDING) the catalog
default is the caption FLOOR tier (``whisper-medium-faster`` -> ``medium``), not
large-v3 -- see ``civiccast.ai_models.catalog._DEFAULT_KEY["captions"]``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.ai_models.service import AiModelService
from civiccast.ai_models.store import AiModelStore
from civiccast.db import Base


def _service(tmp_path: Path, *, system_ram_total_gb: int = 8) -> AiModelService:
    eng = create_engine(f"sqlite:///{tmp_path / 'wiring.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    return AiModelService(AiModelStore(factory), system_ram_total_gb=system_ram_total_gb)


# --- runtime-tag resolution (the wiring boundary) ----------------------------


class TestResolveRuntimeTag:
    def test_summary_default_8gb_is_e4b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=8)
        assert resolve_runtime_tag(service, "summary") == "gemma4:e4b"

    def test_summary_default_16gb_is_12b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=16)
        assert resolve_runtime_tag(service, "summary") == "gemma4:12b"

    def test_translation_default_is_translategemma_4b(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        assert resolve_runtime_tag(service, "translation") == "translategemma:4b"

    def test_captions_default_strips_whisper_prefix(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        # Catalog default model_id is ``whisper-medium`` (the floor tier, bound by
        # OWNER-DECISION-caption-adaptive-tier.md 2026-07-30); faster-whisper loads
        # ``medium``.
        assert resolve_runtime_tag(service, "captions") == "medium"

    def test_operator_selection_overrides_summary_tag(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path, system_ram_total_gb=8)
        service.select_model("summary", "gemma4-12b-ollama")
        assert resolve_runtime_tag(service, "summary") == "gemma4:12b"

    def test_operator_selection_overrides_translation_tag(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import resolve_runtime_tag

        service = _service(tmp_path)
        # gemma4-31b-cloud is a cloud tier -> consent is required to persist it.
        service.select_model("translation", "gemma4-31b-cloud", consent_accepted=True)
        assert resolve_runtime_tag(service, "translation") == "gemma4:31b-cloud"


# --- summary adapter seam ----------------------------------------------------


class TestSummaryAdapterSeam:
    def test_for_release_accepts_model_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        adapter = summary_module.OllamaSummaryModel.for_release(model_tag="gemma4:12b")
        assert captured["model"] == "gemma4:12b"
        assert adapter.model_tag == "gemma4:12b"

    def test_for_release_default_preserves_e4b(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        adapter = summary_module.OllamaSummaryModel.for_release()
        assert captured["model"] == "gemma4:e4b"
        assert adapter.model_tag == "gemma4:e4b"

    def test_build_summary_model_uses_service_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_models.runtime import build_summary_model
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.summary import ollama as summary_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("a" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)

        service = _service(tmp_path, system_ram_total_gb=16)
        adapter = build_summary_model(service)
        assert adapter.model_tag == "gemma4:12b"
        assert captured["model"] == "gemma4:12b"


# --- translation adapter seam ------------------------------------------------


class TestTranslationAdapterSeam:
    def test_for_release_accepts_model_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        provider = translate_module.OllamaSpanishTranslator.for_release(
            model_tag="translategemma:4b"
        )
        assert captured["model"] == "translategemma:4b"
        assert provider.model_tag == "translategemma:4b"

    def test_for_release_default_preserves_translategemma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        provider = translate_module.OllamaSpanishTranslator.for_release()
        assert captured["model"] == "translategemma:4b"
        assert provider.model_tag == "translategemma:4b"

    def test_build_translator_uses_service_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.ai_models.runtime import build_translator
        from civiccast.ai_runtime.ollama_client import OllamaModelManifest
        from civiccast.translate import ollama as translate_module

        captured: dict[str, str] = {}

        def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
            captured["model"] = model
            return OllamaModelManifest(
                model=model,
                digest="sha256:" + ("b" * 64),
                runtime_version="ollama 0.9.0",
                manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
                details={},
            )

        monkeypatch.setattr(translate_module, "get_ollama_model_manifest", fake_manifest)

        service = _service(tmp_path)
        provider = build_translator(service)
        assert provider.model_tag == "translategemma:4b"
        assert captured["model"] == "translategemma:4b"


# --- captions runtime seam ---------------------------------------------------


class TestCaptionsRuntimeSeam:
    def test_build_caption_runtime_uses_service_default(self, tmp_path: Path) -> None:
        from civiccast.ai_models.runtime import build_caption_runtime
        from civiccast.captions.runtime import FasterWhisperRuntime

        service = _service(tmp_path)
        runtime = build_caption_runtime(service)
        assert isinstance(runtime, FasterWhisperRuntime)
        # No selection -> the catalog default, which is now the floor tier (medium)
        # per OWNER-DECISION-caption-adaptive-tier.md (2026-07-30, BINDING).
        assert runtime.model_size_or_path == "medium"
