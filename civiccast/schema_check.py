# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Startup schema-currency self-diagnosis (audit ENG-004 / walkthrough F-001).

A server deployed on new code against an unmigrated database fails in the
worst possible shape: the endpoints touching new columns 500 while every
dashboard stays green. This module compares the database's alembic revision
against the code's expected head at startup so drift becomes an honest,
visible state. It NEVER auto-migrates - running migrations is an operator
decision and a separate failure domain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from civiccast.db.url import normalize_database_url

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchemaStatus:
    """Outcome of the startup schema-currency comparison."""

    state: str  # "current" | "behind" | "not-configured" | "unknown"
    db_revision: str | None = None
    expected_head: str | None = None


def _alembic_runtime_paths() -> tuple[Path, Path, list[Path]]:
    """Return the ini, script directory, and version dirs for this layout.

    Source-tree runs have ``alembic.ini`` and ``alembic/`` at the repo root.
    Wheel/runtime installs carry the same files under ``civiccast/alembic``.
    Alembic resolves a bare ``script_location = alembic`` relative to the
    current process directory, so the startup health check must pin absolute
    paths before constructing ``ScriptDirectory``.
    """

    package_root = Path(__file__).resolve().parent
    source_root = package_root.parent
    if (source_root / "alembic.ini").is_file() and (source_root / "alembic").is_dir():
        ini = source_root / "alembic.ini"
        script_location = source_root / "alembic"
    else:
        ini = package_root / "alembic" / "alembic.ini"
        script_location = package_root / "alembic"

    version_locations = [script_location / "versions"]
    version_locations.extend(
        sorted(path for path in package_root.glob("*/migrations/versions") if path.is_dir())
    )
    return ini, script_location, version_locations


@lru_cache(maxsize=1)
def expected_migration_head() -> str:
    """The single migration head the running code expects (repo-global)."""

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini, script_location, version_locations = _alembic_runtime_paths()
    config = Config(str(ini))
    config.set_main_option("script_location", str(script_location.resolve()))
    config.set_main_option(
        "version_locations",
        "\n".join(str(path.resolve()) for path in version_locations),
    )
    config.set_main_option("path_separator", "newline")
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected exactly one migration head, found {heads!r}.")
    return heads[0]


def evaluate_schema_currency(db_revision: str | None, expected_head: str) -> SchemaStatus:
    """Pure comparison: None or any non-head revision counts as behind."""

    if db_revision == expected_head:
        return SchemaStatus(state="current", db_revision=db_revision, expected_head=expected_head)
    return SchemaStatus(state="behind", db_revision=db_revision, expected_head=expected_head)


#: Task #55 (audit-lite FINDING-002): a hard wall-clock ceiling on the WHOLE
#: connect-and-read below, enforced by
#: :func:`civiccast.db.guarded_connect.run_bounded` independent of whatever
#: the driver/OS does with a stalled connect -- the same class of gap
#: BLOCKER #52 measured and closed for
#: :func:`civiccast.native.upgrade.pg_lifecycle.real_database_reachable`
#: (``connect_timeout`` alone was measured NOT to reliably bound a
#: blackholed connect on this platform). This seam is the D3 upgrade
#: engine's ``schema_revision`` seam AND the app startup check, and its
#: caller in :func:`civiccast.native.upgrade.orchestrator.run_upgrade`
#: (``journal.pre_schema_revision``) has no bound of its own -- a hang here
#: was previously a hang for that caller too.
_READ_DB_REVISION_CEILING_SECONDS = 15.0


def read_db_revision(database_url: str) -> str | None:
    """Read alembic_version from the configured database (None if absent).

    ``database_url`` is normalized (:func:`civiccast.db.url.
    normalize_database_url`) before it reaches ``create_engine``: a bare
    ``postgresql://`` scheme maps to the (uninstalled) psycopg2 dialect --
    this project ships psycopg v3 only (ADR 0008). This is a shared call
    site: both the startup schema-currency check
    (:func:`check_schema_currency`, called from ``civiccast/app.py``) and the
    D3 upgrade engine's ``schema_revision`` seam
    (:func:`civiccast.native.upgrade.seams.default_schema_revision`) go
    through here, so normalizing once here covers both (beta BLOCKER #51).

    Task #55 (audit-lite FINDING-002): this call is bounded by
    :data:`_READ_DB_REVISION_CEILING_SECONDS` regardless of what the
    underlying driver/OS does with a stalled connect (raises
    ``concurrent.futures.TimeoutError`` if exceeded -- see
    :func:`civiccast.db.guarded_connect.run_bounded`), and a connect failure
    classified (:func:`civiccast.db.guarded_connect.classify_missing_database`)
    as psycopg's ``InvalidCatalogName`` / SQLSTATE ``3D000`` ("the target
    database does not exist" -- BLOCKER #52: D4 provisioning never ran
    ``CREATE DATABASE``) is re-raised as
    :class:`civiccast.db.guarded_connect.DatabaseMissingError` instead of a
    raw, unclassified ``OperationalError`` -- this is the SAME classification
    :mod:`civiccast.native.upgrade.pg_lifecycle`'s reachability pre-check
    already applied, now also covering THIS seam's own real connect attempt
    (previously the only DB touch in the D3 engine's forward path with
    neither the bound nor the classification -- see
    ``civiccast.native.upgrade.orchestrator.run_upgrade``'s unguarded
    ``journal.pre_schema_revision`` call). Every other connect/query failure
    is unchanged: propagated as-is (an ordinary connect failure) or treated
    as "table absent in this namespace" (the per-prefix loop), matching this
    function's pre-existing behavior exactly.
    """

    from civiccast.db.guarded_connect import (
        DatabaseMissingError,
        classify_missing_database,
        run_bounded,
    )

    def _read_once() -> str | None:
        from sqlalchemy import create_engine, text
        from sqlalchemy.exc import DBAPIError

        from civiccast.db import connect_options

        normalized_url = normalize_database_url(database_url)
        engine = create_engine(
            normalized_url,
            poolclass=None,
            **connect_options(normalized_url),
        )
        try:
            try:
                connection_cm = engine.connect()
            except DBAPIError as exc:
                if classify_missing_database(exc):
                    raise DatabaseMissingError(
                        "PostgreSQL is reachable, but the target database named "
                        "in this DATABASE_URL does not exist (SQLSTATE 3D000 / "
                        "InvalidCatalogName). D4 provisioning never created it "
                        "(BLOCKER #52) -- this is not a startup race: retrying "
                        "cannot fix it. Re-run native provisioning "
                        "(civiccast.native.provision) against this cluster to "
                        "create the database, then retry."
                    ) from exc
                raise
            with connection_cm as connection:
                for schema_prefix in ("civiccast.", ""):
                    try:
                        row = connection.execute(
                            text(f"SELECT version_num FROM {schema_prefix}alembic_version")  # noqa: S608 -- fixed identifiers  # nosec B608
                        ).fetchone()
                    except Exception:  # table absent in this namespace
                        connection.rollback()
                        continue
                    return row[0] if row else None
            return None
        finally:
            engine.dispose()

    return run_bounded(_read_once, _READ_DB_REVISION_CEILING_SECONDS)


def check_schema_currency(database_url: str | None) -> SchemaStatus:
    """Full startup check; never raises, never blocks startup."""

    if not database_url:
        return SchemaStatus(state="not-configured")
    try:
        head = expected_migration_head()
        status = evaluate_schema_currency(read_db_revision(database_url), head)
    except Exception:
        _LOG.exception("Schema-currency check failed; reporting 'unknown'.")
        return SchemaStatus(state="unknown")
    if status.state == "behind":
        _LOG.error(
            "DATABASE SCHEMA IS BEHIND THE CODE: db revision %r, expected head %r. "
            "Endpoints touching newer columns will fail until 'alembic upgrade "
            "head' runs. The server will NOT auto-migrate.",
            status.db_revision,
            status.expected_head,
        )
    return status
