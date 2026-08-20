# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8 alert-channel credential store (separate from the subscriber stack).

Alert channels reference a secret by ``credential_handle``; the secret value
(SMTP password, webhook signing secret, SMS provider key) lives here, never in
the ``alert_channels`` table and never returned by the API. The store is a local
0600 JSON file — the same local-secret-file pattern the subscriber stack uses
(``subscribe-secrets.json``) — so it is portable (no OS keyring backend needed)
and CI-safe. ``InMemoryCredentialStore`` backs tests.

OD / no-cross-stack-PII: this store is alert-only. The subscriber dispatch never
reads it and it never references subscription rows.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Protocol

GetCredential = Callable[[str], "dict[str, str] | None"]


class CredentialStore(Protocol):
    def get(self, handle: str) -> dict[str, str] | None: ...
    def put(self, handle: str, secret: Mapping[str, str]) -> None: ...
    def delete(self, handle: str) -> bool: ...


class InMemoryCredentialStore:
    """Volatile credential store for tests and throwaway development."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}

    def get(self, handle: str) -> dict[str, str] | None:
        value = self._store.get(handle)
        return dict(value) if value is not None else None

    def put(self, handle: str, secret: Mapping[str, str]) -> None:
        self._store[handle] = {str(k): str(v) for k, v in secret.items()}

    def delete(self, handle: str) -> bool:
        return self._store.pop(handle, None) is not None


class FileCredentialStore:
    """0600 JSON file mapping ``credential_handle`` -> secret dict.

    Path resolution (mirrors the subscriber secret file): an explicit
    ``CIVICCAST_ALERT_CREDENTIALS_FILE``, else ``CIVICCAST_CONFIG_DIR`` /
    ``alert-credentials.json``, else ``~/.civiccast/alert-credentials.json``.
    """

    def __init__(self, path: Path | None = None, *, env: Mapping[str, str] | None = None) -> None:
        self._path = path or _default_path(env if env is not None else os.environ)

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with suppress(OSError):
            self._path.chmod(0o600)

    def get(self, handle: str) -> dict[str, str] | None:
        value = self._load().get(handle)
        if not isinstance(value, dict):
            return None
        return {str(k): str(v) for k, v in value.items()}

    def put(self, handle: str, secret: Mapping[str, str]) -> None:
        data = self._load()
        data[handle] = {str(k): str(v) for k, v in secret.items()}
        self._save(data)

    def delete(self, handle: str) -> bool:
        data = self._load()
        if handle not in data:
            return False
        del data[handle]
        self._save(data)
        return True


def _default_path(env: Mapping[str, str]) -> Path:
    configured = env.get("CIVICCAST_ALERT_CREDENTIALS_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    config_dir = env.get("CIVICCAST_CONFIG_DIR", "").strip()
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".civiccast"
    return base / "alert-credentials.json"


def credential_reader(store: CredentialStore) -> GetCredential:
    """Adapt a CredentialStore to the ``GetCredential`` callable the senders use."""

    def reader(handle: str) -> dict[str, str] | None:
        return store.get(handle)

    return reader
