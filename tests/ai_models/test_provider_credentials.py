# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 DONE-10 — the operator path to STORE a cloud provider key makes the hosted
path work end-to-end.

The prior gate flagged that nothing wrote the provider key (``save_provider_secret``
had zero production callers), so an operator could select a cloud tier but never enable
it. These tests prove the new credential write surface closes the loop: save an
``openrouter`` key through the service, then build the dispatch adapter and generate —
the saved key rides the ``Authorization: Bearer`` header to the provider host; with no
saved key the same path raises ``CloudCredentialError``. They also lock the contract
that the key is never returned and that only cloud providers have a credential handle.
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
from civiccast.ai_models.dispatch import build_summary_model, build_translator
from civiccast.ai_models.secrets import ProviderSecretStoreError
from civiccast.ai_models.service import (
    AiModelService,
    InvalidProviderKeyError,
    UnknownProviderError,
)
from civiccast.ai_models.store import AiModelStore
from civiccast.captions.models import CaptionCue
from civiccast.db import Base


def _service(tmp_path: Path, keyring: dict[str, str]) -> AiModelService:
    """A service whose keyring is an in-memory dict (real save/load/delete semantics)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'cred.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    return AiModelService(
        AiModelStore(factory),
        system_ram_total_gb=8,
        read_first_run_override=lambda _f: None,
        save_provider_secret=lambda ref, secret: keyring.__setitem__(ref, secret),
        delete_provider_secret=lambda ref: keyring.pop(ref, None),
        load_provider_secret=lambda ref: keyring.get(ref),
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
    "choices": [{"message": {"role": "assistant", "content": "Hola"}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 12},
}
_CUES = [
    CaptionCue(
        cue_id="c1",
        start_seconds=0.0,
        end_seconds=2.0,
        text="welcome",
        confidence=0.95,
    )
]


def test_saved_openrouter_key_flows_through_dispatch_as_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole point of DONE-10: store the key via the service, then dispatch uses it.
    keyring: dict[str, str] = {}
    captured = _capture_urlopen(monkeypatch, _OPENROUTER_OK)
    svc = _service(tmp_path, keyring)

    svc.save_provider_credential("openrouter", "sk-or-from-operator")
    svc.select_model("summary", "gemini-2.5-flash-openrouter", consent_accepted=True)

    # build_summary_model uses the service's keyring resolver (no resolve_secret override).
    adapter = build_summary_model(svc, resolve_secret=svc._load_provider_secret)
    adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-or-from-operator"


def test_saved_ollama_cloud_key_flows_through_translation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyring: dict[str, str] = {}
    captured = _capture_urlopen(monkeypatch, _OLLAMA_CLOUD_OK)
    svc = _service(tmp_path, keyring)

    svc.save_provider_credential("ollama-cloud", "oc-from-operator")
    svc.select_model("translation", "gemma4-31b-cloud", consent_accepted=True)

    provider = build_translator(svc, resolve_secret=svc._load_provider_secret)
    provider.translate_text("hello", source_language="en", target_language="es")

    assert captured["url"] == "https://ollama.com/api/generate"
    assert captured["headers"]["Authorization"] == "Bearer oc-from-operator"


def test_no_saved_key_surfaces_credential_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyring: dict[str, str] = {}
    _capture_urlopen(monkeypatch, _OPENROUTER_OK)
    svc = _service(tmp_path, keyring)
    svc.select_model("summary", "gemini-2.5-flash-openrouter", consent_accepted=True)

    adapter = build_summary_model(svc, resolve_secret=svc._load_provider_secret)
    with pytest.raises(CloudCredentialError):
        adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")


def test_delete_then_dispatch_surfaces_credential_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keyring: dict[str, str] = {}
    _capture_urlopen(monkeypatch, _OPENROUTER_OK)
    svc = _service(tmp_path, keyring)
    svc.save_provider_credential("openrouter", "sk-or-temp")
    assert svc.provider_credential_stored("openrouter") is True
    svc.delete_provider_credential("openrouter")
    assert svc.provider_credential_stored("openrouter") is False

    svc.select_model("summary", "gemini-2.5-flash-openrouter", consent_accepted=True)
    adapter = build_summary_model(svc, resolve_secret=svc._load_provider_secret)
    with pytest.raises(CloudCredentialError):
        adapter.generate(meeting_id="m1", cues=_CUES, prompt_version="summary-v0.6")


def test_provider_credential_stored_reports_boolean(tmp_path: Path) -> None:
    keyring: dict[str, str] = {}
    svc = _service(tmp_path, keyring)
    assert svc.provider_credential_stored("openrouter") is False
    svc.save_provider_credential("openrouter", "sk-or-x")
    assert svc.provider_credential_stored("openrouter") is True


def test_provider_credential_status_treats_missing_keyring_as_not_stored(
    tmp_path: Path,
) -> None:
    svc = _service(tmp_path, {})
    svc._load_provider_secret = lambda _ref: (_ for _ in ()).throw(  # type: ignore[method-assign]
        ProviderSecretStoreError("No keyring backend available.")
    )

    assert svc.provider_credential_stored("openrouter") is False


def test_cloud_availability_treats_missing_keyring_as_missing_credential(
    tmp_path: Path,
) -> None:
    svc = _service(tmp_path, {})
    svc.select_model("summary", "gemini-2.5-flash-openrouter", consent_accepted=True)

    availability = svc.get_availability(
        list_local_models=lambda: set(),
        resolve_secret=lambda _ref: (_ for _ in ()).throw(
            ProviderSecretStoreError("No keyring backend available.")
        ),
    )

    summary = availability.features["summary"]
    assert summary.runtime_reachable is False
    assert summary.model_present is None
    assert "no provider credential is stored" in summary.detail


def test_save_credential_rejects_unknown_provider(tmp_path: Path) -> None:
    svc = _service(tmp_path, {})
    with pytest.raises(UnknownProviderError):
        svc.save_provider_credential("ollama", "should-not-store")  # local provider
    with pytest.raises(UnknownProviderError):
        svc.provider_credential_stored("bogus")


def test_save_credential_rejects_blank_or_multiline_key(tmp_path: Path) -> None:
    keyring: dict[str, str] = {}
    svc = _service(tmp_path, keyring)
    with pytest.raises(InvalidProviderKeyError):
        svc.save_provider_credential("openrouter", "   ")
    with pytest.raises(InvalidProviderKeyError):
        svc.save_provider_credential("openrouter", "line1\nline2")
    assert keyring == {}  # nothing persisted on a rejected key


def test_saved_key_is_stripped_before_storing(tmp_path: Path) -> None:
    keyring: dict[str, str] = {}
    svc = _service(tmp_path, keyring)
    svc.save_provider_credential("openrouter", "  sk-or-padded  ")
    assert keyring["openrouter-key"] == "sk-or-padded"
