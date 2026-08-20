# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for civiccast.db.url.normalize_database_url (beta BLOCKER #51).

Pure string/URL logic, no engine, no DB -- runs on any OS.
"""

from __future__ import annotations

import pytest

from civiccast.db.url import normalize_database_url


def test_plain_postgresql_scheme_is_rewritten_to_psycopg_v3() -> None:
    result = normalize_database_url("postgresql://user:secret@localhost:5432/civiccast")

    assert result.startswith("postgresql+psycopg://")
    # The password must survive in plaintext -- a real connection needs it.
    assert "secret" in result
    assert "user" in result
    assert "localhost" in result
    assert "5432" in result
    assert "civiccast" in result


def test_explicit_psycopg_v3_scheme_is_untouched() -> None:
    original = "postgresql+psycopg://user:secret@localhost:5432/civiccast"

    assert normalize_database_url(original) == original


def test_explicit_psycopg2_scheme_is_untouched() -> None:
    """An explicit (if currently unsupported by this project's deps) driver
    choice always wins over normalization -- never second-guess it."""

    original = "postgresql+psycopg2://user:secret@localhost:5432/civiccast"

    assert normalize_database_url(original) == original


def test_explicit_asyncpg_scheme_is_untouched() -> None:
    original = "postgresql+asyncpg://user:secret@localhost:5432/civiccast"

    assert normalize_database_url(original) == original


def test_sqlite_scheme_is_untouched() -> None:
    original = "sqlite:///C:/ProgramData/CivicCast/data/civiccast.sqlite3"

    assert normalize_database_url(original) == original


def test_in_memory_sqlite_is_untouched() -> None:
    original = "sqlite+pysqlite:///:memory:"

    assert normalize_database_url(original) == original


def test_malformed_url_raises_same_as_make_url() -> None:
    from sqlalchemy.exc import ArgumentError

    with pytest.raises(ArgumentError):
        normalize_database_url("not a url at all")
