# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 provider-credential secrets — keyring-backed, never in the DB.

Mirrors ``civiccast.auth.keyring_store`` / ``control_room.secrets`` in its own
namespace so a provider API key (an OpenRouter / Ollama Cloud token) is stored as
an opaque handle in the OS keyring; the DB only ever holds the ``credential_ref``.
"""

from __future__ import annotations

import pytest

from civiccast.ai_models import secrets as provider_secrets


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FailingKeyring(FakeKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("backend unavailable")


def test_provider_secret_uses_dedicated_namespace() -> None:
    # Must not collide with staff-token / control-room-device namespaces.
    assert provider_secrets.SERVICE_NAME == "civiccast.ai-provider"


def test_provider_secret_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeKeyring()
    monkeypatch.setattr(provider_secrets, "keyring", fake)

    provider_secrets.save_provider_secret("openrouter-key", "sk-or-secret")
    assert provider_secrets.load_provider_secret("openrouter-key") == "sk-or-secret"

    provider_secrets.delete_provider_secret("openrouter-key")
    assert provider_secrets.load_provider_secret("openrouter-key") is None


def test_missing_handle_loads_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_secrets, "keyring", FakeKeyring())
    assert provider_secrets.load_provider_secret("never-saved") is None


def test_backend_failure_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_secrets, "keyring", FailingKeyring())
    with pytest.raises(provider_secrets.ProviderSecretStoreError, match=r"openrouter-key"):
        provider_secrets.save_provider_secret("openrouter-key", "sk-or-secret")
