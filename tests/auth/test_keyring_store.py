# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Keyring-backed staff token helper tests."""

from __future__ import annotations

import importlib
from types import ModuleType

import pytest


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


def _module() -> ModuleType:
    try:
        return importlib.import_module("civiccast.auth.keyring_store")
    except ModuleNotFoundError:  # pragma: no cover - red state before implementation
        pytest.fail("civiccast.auth.keyring_store must provide keyring-backed staff token helpers.")


def test_staff_token_round_trip_uses_configured_keyring_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    fake = FakeKeyring()
    monkeypatch.setattr(module, "keyring", fake)

    module.save_staff_token("operator-a", "token-secret-a")

    assert module.load_staff_token("operator-a") == "token-secret-a"
    module.delete_staff_token("operator-a")
    assert module.load_staff_token("operator-a") is None


def test_keyring_backend_failure_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "keyring", FailingKeyring())

    with pytest.raises(module.KeyringStoreError, match=r"keyring.*operator-a"):
        module.save_staff_token("operator-a", "token-secret-a")
