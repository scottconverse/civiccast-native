# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure/cross-platform tests for civiccast.native.supervisor.service_env
(beta BLOCKER #48: the SCM host never bridged the installer-persisted
``DatabaseUrl`` registry value into the service process's environment, so
``default_dependency_provider`` always crashed with "DATABASE_URL is unset").

No real ``winreg`` here -- ``ensure_database_url_env`` takes an injectable
``registry_reader`` fake. The real winreg round-trip is
``tests/native/test_service_env_win.py`` (Windows-only, temporary HKCU key).
This module itself has no Windows-only imports and collects/runs on any OS.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from civiccast.native.supervisor.service_env import (
    DATABASE_URL_ENV_VAR,
    DATABASE_URL_REGISTRY_KEY,
    DATABASE_URL_REGISTRY_VALUE_NAME,
    DatabaseUrlUnavailableError,
    ensure_database_url_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_RUST_WRITER_PATH = (
    REPO_ROOT
    / "civiccast"
    / "apps"
    / "installer"
    / "src-tauri"
    / "src"
    / "native_service_registration.rs"
)


# ---------------------------------------------------------------------------
# Cross-language pin: the Python registry constants must match the Rust
# writer's constants byte-for-byte (native_service_registration.rs is the
# source of truth for this registry location; nothing else may drift from it).
# ---------------------------------------------------------------------------


def test_registry_constants_pinned_to_rust_writer() -> None:
    rust_source = _RUST_WRITER_PATH.read_text(encoding="utf-8")

    key_match = re.search(r'pub const DATABASE_URL_KEY: &str = r"([^"]+)";', rust_source)
    value_name_match = re.search(
        r'pub const DATABASE_URL_VALUE_NAME: &str = "([^"]+)";', rust_source
    )
    assert key_match, f"DATABASE_URL_KEY constant not found in {_RUST_WRITER_PATH}"
    assert value_name_match, f"DATABASE_URL_VALUE_NAME constant not found in {_RUST_WRITER_PATH}"

    assert key_match.group(1) == DATABASE_URL_REGISTRY_KEY
    assert value_name_match.group(1) == DATABASE_URL_REGISTRY_VALUE_NAME


# ---------------------------------------------------------------------------
# ensure_database_url_env: env-wins / registry-fallback / fail-loud
# ---------------------------------------------------------------------------


def test_env_already_set_wins_registry_not_consulted_env_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV_VAR, "postgresql://operator-override/db")

    def _reader_must_not_be_called() -> str | None:
        raise AssertionError("registry_reader must not be called when DATABASE_URL is already set")

    ensure_database_url_env(registry_reader=_reader_must_not_be_called)

    assert os.environ[DATABASE_URL_ENV_VAR] == "postgresql://operator-override/db"


def test_env_unset_registry_has_value_env_gets_populated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    ensure_database_url_env(registry_reader=lambda: "postgresql://from-registry/db")

    assert os.environ[DATABASE_URL_ENV_VAR] == "postgresql://from-registry/db"


def test_env_blank_string_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitespace-only env var must not win over the registry -- matches
    default_dependency_provider's own ``.strip()`` emptiness check."""

    monkeypatch.setenv(DATABASE_URL_ENV_VAR, "   ")

    ensure_database_url_env(registry_reader=lambda: "postgresql://from-registry/db")

    assert os.environ[DATABASE_URL_ENV_VAR] == "postgresql://from-registry/db"


def test_env_unset_registry_missing_raises_naming_path_and_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with pytest.raises(DatabaseUrlUnavailableError) as exc_info:
        ensure_database_url_env(registry_reader=lambda: None)

    message = str(exc_info.value)
    assert DATABASE_URL_ENV_VAR in message
    assert DATABASE_URL_REGISTRY_KEY in message
    assert DATABASE_URL_REGISTRY_VALUE_NAME in message
    # Env must be left untouched on the failure path.
    assert DATABASE_URL_ENV_VAR not in os.environ


def test_env_unset_registry_empty_string_also_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with pytest.raises(DatabaseUrlUnavailableError):
        ensure_database_url_env(registry_reader=lambda: "")

    assert DATABASE_URL_ENV_VAR not in os.environ


# ---------------------------------------------------------------------------
# Task #55 (audit-lite FINDING-004): one log line naming which source won --
# never the resolved value.
# ---------------------------------------------------------------------------


def test_env_override_logs_environment_as_the_winning_source_never_the_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(DATABASE_URL_ENV_VAR, "postgresql://operator-override:hunter2@h/db")

    with caplog.at_level("INFO", logger="civiccast.native.supervisor.service_env"):
        ensure_database_url_env(registry_reader=lambda: "postgresql://from-registry/db")

    messages = [record.getMessage() for record in caplog.records]
    assert any("environment" in message.lower() for message in messages)
    assert not any("hunter2" in message for message in messages)
    assert not any("://" in message for message in messages)


def test_registry_fallback_logs_registry_as_the_winning_source_never_the_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with caplog.at_level("INFO", logger="civiccast.native.supervisor.service_env"):
        ensure_database_url_env(registry_reader=lambda: "postgresql://from-registry:s3cr3t@h/db")

    messages = [record.getMessage() for record in caplog.records]
    assert any("registry" in message.lower() for message in messages)
    assert any(DATABASE_URL_REGISTRY_KEY in message for message in messages)
    assert any(DATABASE_URL_REGISTRY_VALUE_NAME in message for message in messages)
    assert not any("s3cr3t" in message for message in messages)
    assert not any("://" in message for message in messages)


def test_fail_loud_path_logs_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Neither branch's log line fires when both sources are empty -- only
    the (already-tested) raised exception surfaces that condition."""

    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with (
        caplog.at_level("INFO", logger="civiccast.native.supervisor.service_env"),
        pytest.raises(DatabaseUrlUnavailableError),
    ):
        ensure_database_url_env(registry_reader=lambda: None)

    assert caplog.records == []


def test_error_message_never_contains_a_url_looking_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """The raised message must never carry a secret-bearing URL -- only the
    registry path and the env var NAME. There is no legitimate value to embed
    on this failure path (registry_reader returned nothing), so this asserts
    the message contains no ``://`` scheme separator at all."""

    monkeypatch.delenv(DATABASE_URL_ENV_VAR, raising=False)

    with pytest.raises(DatabaseUrlUnavailableError) as exc_info:
        ensure_database_url_env(registry_reader=lambda: None)

    assert "://" not in str(exc_info.value)
