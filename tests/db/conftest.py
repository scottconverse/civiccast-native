# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-test fixtures for the civiccast.db wiring tests.

These tests use a real Postgres testcontainer instead of SQLite so the
integration layer exercises the same database family as operator installs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base, bind_engine, get_session, install_alembic_compat, reset_engine
from tests.support.docker_engine import docker_engine_available

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    _TESTCONTAINERS_OK = True
except ImportError:
    _TESTCONTAINERS_OK = False
    PostgresContainer = None  # type: ignore[misc,assignment]


def _docker_available() -> bool:
    return docker_engine_available()


def _skip_if_no_postgres() -> None:
    if not _TESTCONTAINERS_OK or not _docker_available():
        if os.environ.get("CIVICCAST_RUN_POSTGRES_TESTS"):
            pytest.fail("Postgres tests required by env but Docker unavailable")
        pytest.skip("Docker unavailable; db integration tests require Postgres testcontainers")


# Resolve sqlalchemy.url from DATABASE_URL when alembic.ini leaves it empty.
# Per ADR 0008. Idempotent. Tests that build alembic Config(...) directly
# rely on this being installed; conftest is the single install point for the
# test suite (matching the explicit-install posture introduced in this rung).
install_alembic_compat()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    from tests._postgres_harness import fresh_database_from_env

    with fresh_database_from_env() as external_url:
        if external_url is not None:
            yield external_url
            return
        _skip_if_no_postgres()
        assert PostgresContainer is not None
        container = PostgresContainer("postgres:17", driver="psycopg")
        container.start()
        try:
            yield container.get_connection_url()
        finally:
            container.stop()


@pytest.fixture
def engine(postgres_url: str) -> Iterator[Engine]:
    """Build a fresh Postgres engine, bind it as the module engine, and reset."""

    eng = create_engine(postgres_url, future=True)
    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = postgres_url
    bind_engine(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS civiccast CASCADE"))
        conn.execute(text("CREATE SCHEMA civiccast"))
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS civiccast CASCADE"))
        eng.dispose()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Yield a Session bound to the per-test Postgres engine and close it."""

    sess = Session(bind=engine)
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    """Build a fresh app with get_session overridden to use the Postgres engine."""

    from civiccast.app import create_app

    app = create_app()

    def _override() -> Iterator[Session]:
        s = Session(bind=engine)
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
