# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-winreg test for civiccast.native.supervisor.service_env
(beta BLOCKER #48).

``win`` appears in this module's own filename (house convention, see
``tests/native/test_win_probes.py`` / ``test_supervisor_service_win.py``) so
``-k "not win"`` deselects it honestly. Skipped entirely on non-Windows.

Proves the REAL ``read_database_url_from_registry`` winreg read path against a
TEMPORARY key created under ``HKEY_CURRENT_USER`` (never HKLM -- an ordinary
non-elevated token can create/delete its own HKCU subtree) with the reader
parameterized by ``root``/``key_path``, mirroring
``tests/native/test_win_probes.py``'s ``hkcu_test_key`` fixture pattern
exactly.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real winreg round-trip"),
]

if os.name == "nt":
    import winreg

    from civiccast.native.supervisor.service_env import (
        DATABASE_URL_REGISTRY_VALUE_NAME,
        read_database_url_from_registry,
    )


def _unique_test_key_path() -> str:
    return rf"Software\CivicCastServiceEnvTest\{uuid.uuid4().hex}"


@pytest.fixture
def hkcu_test_key():
    key_path = _unique_test_key_path()
    yield key_path
    with subprocess_suppress():
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)


class subprocess_suppress:
    """Tiny local suppress-OSError context manager for teardown cleanup
    (mirrors test_win_probes.py's identical helper)."""

    def __enter__(self) -> subprocess_suppress:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)  # type: ignore[arg-type]


def test_registry_value_absent_when_key_missing(hkcu_test_key: str) -> None:
    result = read_database_url_from_registry(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result is None


def test_registry_value_absent_when_key_exists_but_value_missing(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE):
        pass
    result = read_database_url_from_registry(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result is None


def test_registry_value_round_trips_a_real_written_url(hkcu_test_key: str) -> None:
    written = "postgresql://civiccast:s3cret@127.0.0.1:5432/civiccast"
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, DATABASE_URL_REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, written)

    result = read_database_url_from_registry(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result == written


def test_registry_value_blank_string_reads_as_absent(hkcu_test_key: str) -> None:
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, hkcu_test_key, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, DATABASE_URL_REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, "   ")

    result = read_database_url_from_registry(root=winreg.HKEY_CURRENT_USER, key_path=hkcu_test_key)
    assert result is None
