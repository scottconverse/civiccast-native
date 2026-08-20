# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8 alert-channel credential store tests."""

from __future__ import annotations

from civiccast.alerting.credentials import (
    FileCredentialStore,
    InMemoryCredentialStore,
    _default_path,
    credential_reader,
)


class TestInMemoryCredentialStore:
    def test_put_get_delete_round_trip(self) -> None:
        store = InMemoryCredentialStore()
        assert store.get("h1") is None
        store.put("h1", {"url": "https://x", "secret": "s"})
        assert store.get("h1") == {"url": "https://x", "secret": "s"}
        assert store.delete("h1") is True
        assert store.get("h1") is None
        assert store.delete("h1") is False

    def test_get_returns_a_copy(self) -> None:
        store = InMemoryCredentialStore()
        store.put("h1", {"k": "v"})
        got = store.get("h1")
        assert got is not None
        got["k"] = "mutated"
        assert store.get("h1") == {"k": "v"}  # internal copy untouched


class TestFileCredentialStore:
    def test_round_trip_persists_to_file(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        store = FileCredentialStore(path)
        assert store.get("smtp") is None
        store.put("smtp", {"smtp_host": "mail", "smtp_password": "pw"})
        assert path.exists()
        # A fresh instance reads the same file.
        assert FileCredentialStore(path).get("smtp") == {"smtp_host": "mail", "smtp_password": "pw"}

    def test_delete(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        store = FileCredentialStore(path)
        store.put("a", {"x": "1"})
        store.put("b", {"y": "2"})
        assert store.delete("a") is True
        assert store.get("a") is None
        assert store.get("b") == {"y": "2"}  # other entry intact
        assert store.delete("missing") is False

    def test_corrupt_file_reads_as_empty(self, tmp_path) -> None:
        path = tmp_path / "creds.json"
        path.write_text("{not json", encoding="utf-8")
        assert FileCredentialStore(path).get("anything") is None

    def test_values_coerced_to_strings(self, tmp_path) -> None:
        store = FileCredentialStore(tmp_path / "creds.json")
        store.put("h", {"port": 587})  # type: ignore[dict-item]
        assert store.get("h") == {"port": "587"}


class TestDefaultPath:
    def test_explicit_file_env(self) -> None:
        p = _default_path({"CIVICCAST_ALERT_CREDENTIALS_FILE": "/tmp/x/creds.json"})
        assert p.name == "creds.json"

    def test_config_dir_env(self) -> None:
        p = _default_path({"CIVICCAST_CONFIG_DIR": "/etc/civiccast"})
        assert p.name == "alert-credentials.json"
        assert "civiccast" in str(p).lower()


def test_credential_reader_delegates() -> None:
    store = InMemoryCredentialStore()
    store.put("h1", {"k": "v"})
    reader = credential_reader(store)
    assert reader("h1") == {"k": "v"}
    assert reader("missing") is None
