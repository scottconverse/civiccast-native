# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared real-Postgres test harness.

Two ways to provide the real PostgreSQL server the Docker-gated suites need:

1. ``CIVICCAST_POSTGRES_TEST_URL`` — an admin URL to an already-running
   PostgreSQL server, e.g.::

       postgresql+psycopg://postgres@127.0.0.1:54329/postgres

   Each fixture invocation creates a fresh throwaway database on that server
   and drops it afterward, giving container-equivalent isolation without
   Docker. This is how the suite runs on machines where Docker is unavailable
   (a portable server under ``C:\\CivicCastTester\\tools\\pgsql-17`` works).

2. Fallback: a ``testcontainers`` ``postgres:17`` container (requires Docker).

``CIVICCAST_RUN_POSTGRES_TESTS=1`` keeps its meaning: when neither source is
available the tests FAIL instead of skipping.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, text


def external_admin_url() -> str | None:
    """Return the configured external-server admin URL, if any."""

    return os.environ.get("CIVICCAST_POSTGRES_TEST_URL", "").strip() or None


@contextlib.contextmanager
def fresh_database_from_env() -> Iterator[str | None]:
    """Yield a fresh-database URL on the external server, or None.

    None means no external server is configured and the caller should fall
    back to testcontainers. When a URL is yielded, the database is created on
    entry and dropped (with backends terminated) on exit.
    """

    admin_url = external_admin_url()
    if admin_url is None:
        yield None
        return
    db_name = f"civiccast_test_{uuid.uuid4().hex[:12]}"
    admin_engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        base, _, _ = admin_url.rpartition("/")
        yield f"{base}/{db_name}"
    finally:
        with contextlib.suppress(Exception), admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()
