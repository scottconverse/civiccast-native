# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Postgres backup/restore: same testcontainers gate as tests/schedule/test_real_postgres.py.

Boundary: this suite runs only when a container engine (Docker or podman) is
reachable. CI (Linux + Docker) always exercises the Postgres path; locally it
runs wherever an engine is up and skips otherwise — see the delivering PR's
evidence for what was executed on which machine.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from civiccast.db import bind_engine, reset_engine
from civiccast.dr.backup import run_postgres_backup, snapshot_tables
from civiccast.egress.models import CanonicalProfile
from civiccast.installer.storage import _run_migrations
from tests.support.docker_engine import container_cli, docker_engine_available

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
            pytest.fail("Postgres DR-drill test required by env but Docker unavailable")
        pytest.skip("Docker unavailable; the Postgres backup path is not exercised in this sandbox")


@pytest.fixture
def postgres_container() -> Iterator[tuple[str, str]]:
    """Yields (host-side connection url, container id)."""
    _skip_if_no_postgres()
    assert PostgresContainer is not None
    container = PostgresContainer("postgres:17", driver="psycopg")
    container.start()
    try:
        yield container.get_connection_url(), container.get_wrapped_container().id
    finally:
        container.stop()


def test_postgres_backup_snapshot_matches_source(
    postgres_container: tuple[str, str], tmp_path: Path
) -> None:
    postgres_url, container_id = postgres_container
    _run_migrations(postgres_url)
    engine = create_engine(postgres_url, future=True)
    bind_engine(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO civiccast.egress_configs "
                "(channel_id, enabled, auto_start, fill_policy, slate_message, "
                "loudness_target_lufs, loudness_tolerance_lufs, "
                "canonical_profile_json, created_at, updated_at) "
                "VALUES ('gov', true, false, 'slate', 'x', -23.0, 1.0, "
                ":profile, now(), now())"
            ),
            # Postgres enforces the NOT NULL the sqlite drill's store-level
            # seeding filled implicitly — caught by CI's Docker gate, exactly
            # what this test exists for.
            {"profile": CanonicalProfile().model_dump_json()},
        )
    source_snapshot = {t.name: t for t in snapshot_tables(engine)}
    assert source_snapshot["egress_configs"].row_count == 1

    # Dump from INSIDE the container: the server's own pg_dump can never be
    # older than the server (the runner's apt client was — 'server version
    # mismatch' on the first CI run of this gate).
    artifact = run_postgres_backup(
        # In-container view: pg_dump runs INSIDE the server container, where
        # the server is localhost:5432 (the host-mapped port is meaningless there).
        database_url="postgresql://test:test@localhost:5432/test",
        dest_dir=tmp_path / "backup",
        # Exec through the runtime that actually created the container -- podman's
        # containers are not reachable via a `docker` CLI (and vice versa).
        pg_dump_command=[
            container_cli() or "docker",
            "exec",
            "-i",
            "-e",
            "PGPASSWORD=test",
            container_id,
            "pg_dump",
        ],
    )
    assert artifact.exists()
    assert artifact.stat().st_size > 0

    reset_engine()
    engine.dispose()
