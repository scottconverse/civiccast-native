# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 E1/T1 — tier-aware dispatch: a cloud selection routes through the cloud adapter.

The runtime wiring used to build ONLY the local loopback adapters, so selecting a
hosted tier sent a cloud tag to 127.0.0.1 and failed (the cloud adapters were
orphaned). These tests prove the dispatch seam now branches on the effective tier's
provider:

* a LOCAL selection still builds the loopback Ollama adapter (behavior-preserving);
* a CLOUD selection builds a cloud-backed shim whose ``generate`` egresses to the
  provider HTTPS host with a Bearer header (NOT loopback) and returns a
  ``CloudGenerationResult``-derived output;
* a cloud selection without a stored credential surfaces ``CloudCredentialError``
  through the feature build path.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.ai_models.cloud import egress
from civiccast.ai_models.cloud.egress import CloudCredentialError
from civiccast.ai_models.dispatch import (
    CloudSummaryModel,
    CloudTranslator,
    build_summary_model,
    build_translator,
)
from civiccast.ai_models.service import AiModelService
from civiccast.ai_models.store import AiModelStore
from civiccast.captions.models import CaptionCue
from civiccast.db import Base


def _service(tmp_path: Path, *, system_ram_total_gb: int = 8) -> AiModelService:
    eng = create_engine(f"sqlite:///{tmp_path / 'dispatch.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    return AiModelService(
        AiModelStore(factory),
        system_ram_total_gb=system_ram_total_gb,
        read_first_run_override=lambda _feature: None,
    )


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _capture_urlopen(monkeypatch: pytest.MonkeyPatch, payload: dict) -> dict:
    captured: dict = {}

    def fake_urlopen(request: object, *, timeout: object = None) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8")) if request.data else None
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(egress, "urlopen", fake_urlopen)
    return captured


_SUMMARY_JSON = json.dumps({"narrative": "Council met.", "sourced_claims": []})
_OLLAMA_CLOUD_OK = {"response": _SUMMARY_JSON, "prompt_eval_count": 40, "eval_count": 10}
_OPENROUTER_OK = {
    "choices": [{"message": {"role": "assistant", "content": "Hola mundo"}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 12},
}

_CUES = [
    CaptionCue(
        cue_id="c1",
        start_seconds=0.0,
        end_seconds=2.0,
        text="welcome to the meeting",
        confidence=0.95,
    )
]


# --- summary: cloud selection routes to the cloud adapter ---------------------


def test_local_summary_selection_builds_local_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civiccast.ai_runtime.ollama_client import OllamaModelManifest
    from civiccast.summary import ollama as summary_module

    def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
        return OllamaModelManifest(
            model=model,
            digest="sha256:" + ("a" * 64),
            runtime_version="ollama 0.9.0",
            manifest_source=f"http://127.0.0.1:11434/api/tags#{model}",
            details={},
        )

    monkeypatch.setattr(summary_module, "get_ollama_model_manifest", fake_manifest)
    service = _service(tmp_path, system_ram_total_gb=8)
    adapter = build_summary_model(service)
    # No selection -> local loopback adapter, today's behavior unchanged.
    assert isinstance(adapter, summary_module.OllamaSummaryModel)
    assert adapter.model_tag == "gemma4:e4b"


def test_cloud_summary_selection_routes_to_cloud_host_with_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_urlopen(monkeypatch, _OLLAMA_CLOUD_OK)
    service = _service(tmp_path)
    service.select_model("summary", "gemma4-31b-cloud", consent_accepted=True)

    adapter = build_summary_model(service, resolve_secret=lambda ref: "oc-secret-token")
    assert isinstance(adapter, CloudSummaryModel)

    output = adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")

    # The request egressed to the cloud HTTPS host with a Bearer header — NOT loopback.
    assert captured["url"] == "https://ollama.com/api/generate"
    assert captured["headers"]["Authorization"] == "Bearer oc-secret-token"
    assert "127.0.0.1" not in captured["url"]
    assert captured["body"]["model"] == "gemma4:31b-cloud"
    # The CloudGenerationResult text was adapted to the summary JSON protocol.
    assert output == {"narrative": "Council met.", "sourced_claims": []}


def test_cloud_summary_without_credential_surfaces_credential_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_urlopen(monkeypatch, _OLLAMA_CLOUD_OK)
    service = _service(tmp_path)
    service.select_model("summary", "gemma4-31b-cloud", consent_accepted=True)

    adapter = build_summary_model(service, resolve_secret=lambda ref: None)
    with pytest.raises(CloudCredentialError):
        adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")


# --- translation: cloud selection routes to the frontier adapter --------------


def test_local_translation_selection_builds_local_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civiccast.ai_runtime.ollama_client import OllamaModelManifest
    from civiccast.translate import ollama as translate_module

    def fake_manifest(model: str, *, base_url: str) -> OllamaModelManifest:
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
    assert isinstance(provider, translate_module.OllamaSpanishTranslator)
    assert provider.model_tag == "translategemma:4b"


def test_cloud_translation_selection_routes_to_cloud_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_urlopen(monkeypatch, _OLLAMA_CLOUD_OK)
    service = _service(tmp_path)
    service.select_model("translation", "gemma4-31b-cloud", consent_accepted=True)

    provider = build_translator(service, resolve_secret=lambda ref: "oc-secret-token")
    assert isinstance(provider, CloudTranslator)

    text = provider.translate_text("hello", source_language="en", target_language="es")
    assert captured["url"] == "https://ollama.com/api/generate"
    assert captured["headers"]["Authorization"] == "Bearer oc-secret-token"
    assert "127.0.0.1" not in captured["url"]
    assert text == _SUMMARY_JSON  # the canned ``response`` is echoed through translate


def test_cloud_translation_without_credential_surfaces_credential_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_urlopen(monkeypatch, _OLLAMA_CLOUD_OK)
    service = _service(tmp_path)
    service.select_model("translation", "gemma4-31b-cloud", consent_accepted=True)

    provider = build_translator(service, resolve_secret=lambda ref: None)
    with pytest.raises(CloudCredentialError):
        provider.translate_text("hello", source_language="en", target_language="es")


def test_openrouter_frontier_summary_routes_to_openrouter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_urlopen(monkeypatch, _OPENROUTER_OK)
    service = _service(tmp_path)
    service.select_model("summary", "gemini-2.5-flash-openrouter", consent_accepted=True)

    adapter = build_summary_model(service, resolve_secret=lambda ref: "sk-or-secret")
    assert isinstance(adapter, CloudSummaryModel)
    # The OpenRouter body is the model's content; here it is not summary JSON, so the
    # summary parser returns the empty-refusal shape — the routing is what we assert.
    adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-secret"
    assert captured["body"]["model"] == "google/gemini-2.5-flash"
