# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression: ``civiccast.db.session.get_engine`` must normalize a bare
``postgresql://`` DATABASE_URL to the psycopg v3 driver.

Live-proven defect (tonight's scripted product exercise, run-21 row A7):
``<payload>\\python.exe -I -m civiccast.cli token issue --operator-id x
--display-name y --scopes operator --json`` against a registry-form
``DATABASE_URL`` (``postgresql://...``, the exact form the installer
persists -- see ``civiccast/native/supervisor/service_env.py``) died with
``ModuleNotFoundError: No module named 'psycopg2'``. Chain: ``token issue``
-> ``civiccast/cli.py``'s ``_get_staff_token_store`` -> ``civiccast.db.
get_session`` -> :func:`civiccast.db.session.get_engine`, which passed
``DATABASE_URL`` straight into ``create_engine()`` unchanged -- SQLAlchemy
resolves the driver-less ``postgresql`` scheme to the psycopg2 dialect
(``create_engine``'s default dialect selection), but this project ships
ONLY psycopg v3 (ADR 0008, ``psycopg[binary]>=3.2``) -- psycopg2 is never
installed in the native payload.

``civiccast/db/url.py``'s ``normalize_database_url`` is the repo's existing,
already-proven fix for exactly this class of bug (beta BLOCKER #51; see
that module's docstring for the full list of call sites already covered).
``get_engine`` -- the process-wide engine factory every
``civiccast.db.get_session()`` consumer (FastAPI routes AND CLI commands)
builds through -- was the one remaining unnormalized call site this sweep
found; mirrors ``tests/native/test_app_engine_url.py``'s pattern for the
sibling fix in ``civiccast/app.py``'s ``_create_database_engine``.

No real Postgres needed: ``sqlalchemy.create_engine()`` resolves and
constructs the DBAPI module at ENGINE CONSTRUCTION, not at connect time --
that is exactly why the bare scheme's ``ModuleNotFoundError`` fires (and is
reproducible here) without opening a socket.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from civiccast.db.session import get_engine, reset_engine

_RAW_POSTGRES_URL = "postgresql://u:p@127.0.0.1:5432/db"


@pytest.fixture(autouse=True)
def _clean_engine_singleton() -> Iterator[None]:
    """Isolate the module-level engine singleton from the rest of the suite.

    get_engine() memoizes into a module-level slot; other tests/fixtures
    (tests/db/conftest.py's ``engine`` fixture, in particular) bind their
    own engine there. Reset before and after so this test neither inherits
    a stale engine nor leaves one behind for a later test to trip over.
    """
    reset_engine()
    try:
        yield
    finally:
        reset_engine()


def test_get_engine_normalizes_bare_postgresql_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine built from a bare ``postgresql://`` DATABASE_URL must
    resolve to the psycopg v3 driver, not the uninstalled psycopg2 dialect
    -- asserted at the actual ``Engine.url``/dialect boundary the
    ModuleNotFoundError comes from, not a mocked call site."""
    monkeypatch.setenv("DATABASE_URL", _RAW_POSTGRES_URL)

    engine = get_engine()
    try:
        assert engine.url.get_driver_name() == "psycopg"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()


def test_get_engine_preserves_credentials_when_normalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """normalize_database_url renders with hide_password=False deliberately
    -- silently corrupting the credential while fixing the driver would be a
    worse outcome than the bug this fixes. Guards against a normalization
    that fixes the driver but breaks auth."""
    monkeypatch.setenv("DATABASE_URL", _RAW_POSTGRES_URL)

    engine = get_engine()
    try:
        assert engine.url.username == "u"
        assert engine.url.password == "p"
        assert engine.url.host == "127.0.0.1"
        assert engine.url.port == 5432
        assert engine.url.database == "db"
    finally:
        engine.dispose()


def test_get_engine_leaves_explicit_driver_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator/deployment that already names a driver explicitly (e.g.
    an already-normalized URL, or a deliberate psycopg2 pin) must not be
    rewritten -- normalize_database_url is a no-op for any URL that already
    names a driver."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:5432/db")

    engine = get_engine()
    try:
        assert engine.url.get_driver_name() == "psycopg"
    finally:
        engine.dispose()


def test_get_engine_sqlite_url_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-Postgres DATABASE_URL (e.g. a bare sqlite form, if one were ever
    set this way) never touches normalize_database_url -- non-postgres
    schemes pass through unchanged. Locks that the fix is scoped to the
    postgres branch only."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    engine = get_engine()
    try:
        assert engine.url.get_driver_name() in {"pysqlite", "sqlite"}
    finally:
        engine.dispose()
