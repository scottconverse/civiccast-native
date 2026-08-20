# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 Ollama Cloud adapter (gemma4:31b-cloud) — functional, default OFF, opt-in.

Real HTTP shape (``/api/generate``, same wire as local Ollama + a Bearer header to
an off-box https host), but NEVER real network in tests: ``urlopen`` is mocked.
The adapter refuses to run unless cloud consent is recorded (the TOS checkbox).
"""

from __future__ import annotations

import io
import json
from decimal import Decimal

import pytest

from civiccast.ai_models.cloud import egress
from civiccast.ai_models.cloud.ollama_cloud import OllamaCloudAdapter


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
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(egress, "urlopen", fake_urlopen)
    return captured


_OK_PAYLOAD = {
    "response": "Hola mundo",
    "prompt_eval_count": 42,
    "eval_count": 8,
}


def _adapter(*, consent: bool = True) -> OllamaCloudAdapter:
    return OllamaCloudAdapter(
        model_key="gemma4-31b-cloud",
        credential_ref="ollama-cloud-key",
        resolve_secret=lambda ref: "oc-secret-token" if ref == "ollama-cloud-key" else None,
        consent_accepted=consent,
    )


def test_construction_refuses_without_consent() -> None:
    with pytest.raises(egress.CloudConsentRequiredError):
        _adapter(consent=False)


def test_generate_posts_to_allowlisted_https_host_with_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    adapter = _adapter()

    result = adapter.generate(prompt="hello")

    assert captured["url"] == "https://ollama.com/api/generate"
    assert captured["method"] == "POST"
    # urllib title-cases header keys.
    assert captured["headers"]["Authorization"] == "Bearer oc-secret-token"
    assert captured["headers"]["Content-type"] == "application/json"
    # Same wire shape as local Ollama: model tag, non-streaming, deterministic.
    assert captured["body"]["model"] == "gemma4:31b-cloud"
    assert captured["body"]["prompt"] == "hello"
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"]["temperature"] == 0
    # Response + realized token counts surfaced.
    assert result.text == "Hola mundo"
    assert result.prompt_tokens == 42
    assert result.completion_tokens == 8


def test_generate_reports_per_token_cost_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    result = _adapter().generate(prompt="hello")
    # 50 tokens * 1e-7 USD/token from the catalog.
    assert result.cost_usd == Decimal("50") * Decimal("1e-7")
    assert isinstance(result.cost_usd, Decimal)


def test_generate_raises_when_secret_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    adapter = OllamaCloudAdapter(
        model_key="gemma4-31b-cloud",
        credential_ref="missing",
        resolve_secret=lambda ref: None,
        consent_accepted=True,
    )
    with pytest.raises(egress.CloudCredentialError, match=r"credential|key|token"):
        adapter.generate(prompt="hello")


def test_generate_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: object, *, timeout: object = None) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(egress, "urlopen", boom)
    with pytest.raises(egress.CloudRuntimeUnavailableError):
        _adapter().generate(prompt="hello")


def test_generate_raises_on_missing_response_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 200 with no ``response`` field (or a non-string one) is a malformed payload,
    # not a usable completion — it must surface as a typed runtime error, not silently
    # produce empty output (matches the OpenRouter no-content coverage).
    _capture_urlopen(monkeypatch, {"prompt_eval_count": 5, "eval_count": 2})
    with pytest.raises(egress.CloudRuntimeUnavailableError, match=r"response text"):
        _adapter().generate(prompt="hello")


def test_generate_raises_on_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ollama Cloud returning a JSON array/scalar (not an object) is malformed.
    captured: dict = {}

    def fake_urlopen(request: object, *, timeout: object = None) -> _FakeResponse:
        captured["url"] = request.full_url
        return _FakeResponse(json.dumps(["unexpected", "array"]).encode("utf-8"))

    monkeypatch.setattr(egress, "urlopen", fake_urlopen)
    with pytest.raises(egress.CloudRuntimeUnavailableError, match=r"non-object JSON"):
        _adapter().generate(prompt="hello")


def test_adapter_never_targets_loopback() -> None:
    # The adapter's base URL is the off-box provider host, not 127.0.0.1.
    assert "127.0.0.1" not in OllamaCloudAdapter.BASE_URL
    assert OllamaCloudAdapter.BASE_URL.startswith("https://")


def test_feature_scoped_adapter_resolves_tag_and_cost_via_that_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # gemma4-31b-cloud is offered for both summary and translation; constructing the
    # adapter with feature="translation" resolves the runtime tag + cost via that
    # feature's tier (M6: never a wrong-feature copy).
    captured = _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    adapter = OllamaCloudAdapter(
        model_key="gemma4-31b-cloud",
        credential_ref="ollama-cloud-key",
        resolve_secret=lambda ref: "oc-secret-token",
        consent_accepted=True,
        feature="translation",
    )
    result = adapter.generate(prompt="hello")
    assert captured["body"]["model"] == "gemma4:31b-cloud"
    assert result.cost_usd == Decimal("50") * Decimal("1e-7")
