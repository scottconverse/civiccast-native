# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression: ``civiccast/app.py``'s durable-store engine must normalize a
bare ``postgresql://`` DATABASE_URL to the psycopg v3 driver.

Live-proven defect (Sandbox gauntlet run 19, ``control_plane.log``): the
control plane crash-looped at import with ``ModuleNotFoundError: No module
named 'psycopg2'``. Chain: ``civiccast/app.py``'s ``_install_durable_store_
wiring`` (the native durable-store wiring path every non-sqlite native
install goes through) calls ``_create_database_engine(database_url)`` with
the raw registry URL form ``postgresql://...`` the installer persists (see
``civiccast/native/supervisor/service_env.py``) straight into
``create_engine(...)`` -- SQLAlchemy resolves the driver-less ``postgresql``
scheme to the psycopg2 dialect (``create_engine``'s default dialect
selection), but this project ships ONLY psycopg v3 (ADR 0008,
``psycopg[binary]>=3.2``) -- psycopg2 is never installed in the native
payload (nor, as it happens, in this dev venv -- see ``requirements-native-
app.txt``). ``civiccast/db/url.py``'s ``normalize_database_url`` is the
repo's existing, already-proven fix for exactly this class of bug (beta
BLOCKER #51; applied at the supervisor provider, the D3 upgrade engine, and
``schema_check.read_db_revision`` -- see that module's docstring for the
full list) -- ``_create_database_engine`` is the one durable-store call site
that predates the native port and never got it.

No real Postgres needed: ``sqlalchemy.create_engine()`` resolves and
constructs the DBAPI module at ENGINE CONSTRUCTION, not at connect time --
that is exactly why the bare scheme's ``ModuleNotFoundError`` fires (and is
reproducible here) without opening a socket.
"""

from __future__ import annotations

import pytest

from civiccast.app import _create_database_engine

_RAW_POSTGRES_URL = "postgresql://u:p@127.0.0.1:5432/db"


def test_create_database_engine_normalizes_bare_postgresql_scheme() -> None:
    """The engine built from a bare ``postgresql://`` URL must resolve to
    the psycopg v3 driver, not the uninstalled psycopg2 dialect -- asserted
    at the actual ``Engine.url``/dialect boundary the ModuleNotFoundError
    comes from, not a mocked call site."""

    engine = _create_database_engine(_RAW_POSTGRES_URL)
    try:
        assert engine.url.get_driver_name() == "psycopg"
        assert engine.dialect.driver == "psycopg"
    finally:
        engine.dispose()


def test_create_database_engine_preserves_credentials_when_normalizing() -> None:
    """normalize_database_url renders with hide_password=False deliberately
    -- silently corrupting the credential while fixing the driver would be a
    worse outcome than the bug this fixes. Guards against a normalization
    that fixes the driver but breaks auth."""

    engine = _create_database_engine(_RAW_POSTGRES_URL)
    try:
        assert engine.url.username == "u"
        assert engine.url.password == "p"
        assert engine.url.host == "127.0.0.1"
        assert engine.url.port == 5432
        assert engine.url.database == "db"
    finally:
        engine.dispose()


def test_create_database_engine_leaves_explicit_driver_untouched() -> None:
    """An operator/deployment that already names a driver explicitly (e.g.
    an already-normalized URL, or a deliberate psycopg2 pin) must not be
    rewritten -- normalize_database_url is a no-op for any URL that already
    names a driver."""

    engine = _create_database_engine("postgresql+psycopg://u:p@127.0.0.1:5432/db")
    try:
        assert engine.url.get_driver_name() == "psycopg"
    finally:
        engine.dispose()


def test_create_database_engine_sqlite_branch_is_unaffected() -> None:
    """The sqlite branch (default first-mile install) never touches
    normalize_database_url (non-Postgres schemes pass through unchanged) --
    this locks that the fix is scoped to the postgres branch only."""

    engine = _create_database_engine("sqlite:///:memory:")
    try:
        assert engine.url.get_driver_name() in {"pysqlite", "sqlite"}
    finally:
        engine.dispose()


@pytest.mark.parametrize("driver_module_name", ["psycopg2"])
def test_psycopg2_is_not_the_installed_driver(driver_module_name: str) -> None:
    """Documents the payload/venv reality this regression depends on: if
    psycopg2 ever became available again, this test alone would not catch a
    reintroduced unnormalized create_engine call (SQLAlchemy would happily
    resolve it) -- it exists only so a future reader sees explicitly that
    the driver-selection assertions above are meaningful in THIS
    environment, not a no-op because both drivers are present."""

    import importlib

    with pytest.raises(ImportError):
        importlib.import_module(driver_module_name)
