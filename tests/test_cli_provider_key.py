# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI: `civiccast model set-provider-key` — the headless/air-gap path to store a
cloud provider key (S13 DONE-10).

The command is the offline counterpart to the staff API: it writes the provider key to
the keyring write-only and NEVER prints it. These tests patch the keyring functions to
an in-memory dict so no real OS keyring is touched, and assert the key never appears in
the command output.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import civiccast.ai_models.secrets as provider_secrets
from civiccast.cli import app


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store: dict[str, str] = {}
    monkeypatch.setattr(provider_secrets, "save_provider_secret", store.__setitem__)
    monkeypatch.setattr(
        provider_secrets, "delete_provider_secret", lambda ref: store.pop(ref, None)
    )
    return store


def test_set_provider_key_with_option_stores_and_redacts(fake_keyring: dict[str, str]) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["model", "set-provider-key", "openrouter", "--key", "sk-or-supersecret"],
    )
    assert result.exit_code == 0, result.output
    assert fake_keyring["openrouter-key"] == "sk-or-supersecret"
    # The secret is NEVER echoed to stdout.
    assert "sk-or-supersecret" not in result.output
    assert "stored" in result.output


def test_set_provider_key_reads_from_env(
    fake_keyring: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_API_KEY", "oc-env-secret")
    runner = CliRunner()
    result = runner.invoke(app, ["model", "set-provider-key", "ollama-cloud"])
    assert result.exit_code == 0, result.output
    assert fake_keyring["ollama-cloud-key"] == "oc-env-secret"
    assert "oc-env-secret" not in result.output


def test_set_provider_key_clear_removes_it(fake_keyring: dict[str, str]) -> None:
    fake_keyring["openrouter-key"] = "sk-or-secret"
    runner = CliRunner()
    result = runner.invoke(app, ["model", "set-provider-key", "openrouter", "--clear"])
    assert result.exit_code == 0, result.output
    assert "openrouter-key" not in fake_keyring
    assert "cleared" in result.output


def test_set_provider_key_json_reports_boolean_only(fake_keyring: dict[str, str]) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["model", "set-provider-key", "openrouter", "--key", "sk-or-secret", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {"provider": "openrouter", "stored": True}
    assert "sk-or-secret" not in result.output


def test_set_provider_key_unknown_provider_fails(fake_keyring: dict[str, str]) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["model", "set-provider-key", "not-a-provider", "--key", "x"])
    assert result.exit_code == 1
    assert fake_keyring == {}


def test_set_provider_key_missing_key_fails(fake_keyring: dict[str, str]) -> None:
    # No --key and no env var -> a clear error, nothing stored.
    runner = CliRunner()
    result = runner.invoke(app, ["model", "set-provider-key", "openrouter"])
    assert result.exit_code == 1
    assert fake_keyring == {}
