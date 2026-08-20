# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 OpenRouter adapter (mid-tier frontier) — functional, default OFF, opt-in.

OpenAI-compatible wire (``/api/v1/chat/completions``) to an off-box https host
with a Bearer header. NEVER real network in tests: ``urlopen`` is mocked. The
adapter refuses to run unless cloud consent is recorded (the TOS checkbox).
"""

from __future__ import annotations

import io
import json
from decimal import Decimal

import pytest

from civiccast.ai_models.cloud import egress
from civiccast.ai_models.cloud.openrouter import OpenRouterAdapter


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
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(egress, "urlopen", fake_urlopen)
    return captured


_OK_PAYLOAD = {
    "choices": [{"message": {"role": "assistant", "content": "Hola mundo"}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 12},
}


def _adapter(*, consent: bool = True) -> OpenRouterAdapter:
    return OpenRouterAdapter(
        model_key="gemini-2.5-flash-openrouter",
        credential_ref="openrouter-key",
        resolve_secret=lambda ref: "sk-or-secret" if ref == "openrouter-key" else None,
        consent_accepted=consent,
    )


def test_construction_refuses_without_consent() -> None:
    with pytest.raises(egress.CloudConsentRequiredError):
        _adapter(consent=False)


def test_generate_posts_openai_compatible_with_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    adapter = _adapter()

    result = adapter.generate(prompt="hello")

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-secret"
    assert captured["headers"]["Content-type"] == "application/json"
    # OpenAI-compatible body: route slug + messages + deterministic temperature.
    assert captured["body"]["model"] == "google/gemini-2.5-flash"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert captured["body"]["temperature"] == 0
    assert result.text == "Hola mundo"
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 12


def test_generate_reports_per_token_cost_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    result = _adapter().generate(prompt="hello")
    # 42 tokens * 3e-7 USD/token from the catalog.
    assert result.cost_usd == Decimal("42") * Decimal("3e-7")
    assert isinstance(result.cost_usd, Decimal)


def test_generate_raises_when_secret_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_urlopen(monkeypatch, _OK_PAYLOAD)
    adapter = OpenRouterAdapter(
        model_key="gemini-2.5-flash-openrouter",
        credential_ref="missing",
        resolve_secret=lambda ref: None,
        consent_accepted=True,
    )
    with pytest.raises(egress.CloudCredentialError, match=r"credential|key|token"):
        adapter.generate(prompt="hello")


def test_generate_raises_on_malformed_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture_urlopen(monkeypatch, {"choices": [], "usage": {}})
    with pytest.raises(egress.CloudRuntimeUnavailableError):
        _adapter().generate(prompt="hello")


def test_generate_raises_on_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request: object, *, timeout: object = None) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(egress, "urlopen", boom)
    with pytest.raises(egress.CloudRuntimeUnavailableError):
        _adapter().generate(prompt="hello")


def test_adapter_never_targets_loopback() -> None:
    assert "127.0.0.1" not in OpenRouterAdapter.BASE_URL
    assert OpenRouterAdapter.BASE_URL.startswith("https://")
