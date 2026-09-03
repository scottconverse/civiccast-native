# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""End-to-end D3 upgrade engine proof against a real Postgres (Gate A run
33681670855 regression test, required test (2) from the fix's directive).

Every other D3 upgrade test (``tests/native/test_upgrade_orchestrator.py``,
``test_upgrade_seams.py``, ...) drives the orchestrator or a single seam
builder over FAKE seams or a mocked ``alembic.command.upgrade`` -- none of
them actually run a database from one real migration revision to another
through the REAL production seam bundle (:func:`build_default_seams`). That
blind spot is exactly how the D3 root cause (the pre-upgrade restore-drill
comparing the restored copy against the wrong revision) shipped: every
existing Postgres restore-drill test builds its manifest at the CURRENT head
(``tests/dr/test_postgres_restore.py``'s fixtures all call ``_run_migrations``
to head before backing up), so none of them ever exercised a drill running
DURING a real migration.

This test closes that gap: migrate a real Postgres database to head, step it
back one REAL revision (``alembic downgrade -1``, matching the shape of
"a database at the OLD version's schema, about to be upgraded"), then run
the actual ``civiccast.native.upgrade`` engine over it through
:func:`build_default_seams` + :func:`adapt_flat_installer_layout` (the exact
production seam bundle and layout the shipping NSIS installer uses -- see
``civiccast/apps/installer/src-tauri/nsis-hooks-bootstrap.nsh``'s
``--flat-installer-layout`` invocation). Asserts the run reaches
``UpgradePhase.COMPLETE`` (not the false ``ROLLED_BACK`` Gate A run
33681670855 produced) and that ``post_schema_revision`` lands exactly on
:func:`civiccast.schema_check.expected_migration_head`.

Boundary: gated exactly like ``tests/dr/test_postgres_restore.py`` (Docker
reachable) PLUS the Postgres client tools (``pg_dump``/``pg_dumpall``/
``pg_restore``/``psql``) on THIS machine's PATH -- unlike the DR suite, this
test does not shell those tools through ``docker exec`` (the production seam
bundle uses one ``database_url`` for both the CLI tools' ``--host``/
``--port`` parsing AND direct SQLAlchemy connections, which only lines up
with a single reachable Postgres -- exactly production's shape, and exactly
what a host-mapped testcontainers port plus host-installed client tools
reproduces without needing to touch the seam contract itself).
``CIVICCAST_RUN_POSTGRES_TESTS=1`` marks this required in CI's Postgres lane;
see ``civiccast/native/upgrade`` module docs for what is and is not covered
elsewhere.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from civiccast.native.upgrade.models import UpgradeContext, UpgradePhase, UpgradePlan
from civiccast.native.upgrade.orchestrator import run_upgrade
from civiccast.native.upgrade.seams import adapt_flat_installer_layout, build_default_seams
from civiccast.schema_check import _alembic_runtime_paths, expected_migration_head, read_db_revision
from tests.support.docker_engine import docker_engine_available

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    _TESTCONTAINERS_OK = True
except ImportError:
    _TESTCONTAINERS_OK = False
    PostgresContainer = None  # type: ignore[misc,assignment]

_PG_CLIENT_TOOLS = ("pg_dump", "pg_dumpall", "pg_restore", "psql")


def _skip_if_env_not_ready() -> None:
    missing_tools = [tool for tool in _PG_CLIENT_TOOLS if shutil.which(tool) is None]
    if not _TESTCONTAINERS_OK or not docker_engine_available() or missing_tools:
        reason = []
        if not _TESTCONTAINERS_OK or not docker_engine_available():
            reason.append("Docker unavailable")
        if missing_tools:
            reason.append(f"Postgres client tools not on PATH: {missing_tools}")
        detail = "; ".join(reason)
        if os.environ.get("CIVICCAST_RUN_POSTGRES_TESTS"):
            pytest.fail(f"D3 upgrade engine Postgres test required by env but {detail}")
        pytest.skip(f"{detail}; the real D3 upgrade engine path is not exercised in this sandbox")


@pytest.fixture
def postgres_container() -> Iterator[str]:
    """Yields the HOST-reachable connection URL (matches production's single
    "one reachable Postgres, no container indirection" shape -- see the
    module docstring for why this test does not use a docker-exec prefix)."""

    _skip_if_env_not_ready()
    assert PostgresContainer is not None
    container = PostgresContainer("postgres:17", driver="psycopg")
    container.start()
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _migrate_to_head(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    ini, script_location, version_locations = _alembic_runtime_paths()
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(script_location.resolve()))
    cfg.set_main_option(
        "version_locations", "\n".join(str(path.resolve()) for path in version_locations)
    )
    cfg.set_main_option("path_separator", "newline")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def _downgrade_one_revision(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    ini, script_location, version_locations = _alembic_runtime_paths()
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(script_location.resolve()))
    cfg.set_main_option(
        "version_locations", "\n".join(str(path.resolve()) for path in version_locations)
    )
    cfg.set_main_option("path_separator", "newline")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "-1")


def test_upgrade_engine_migrates_a_real_database_from_n_minus_1_to_head(
    postgres_container: str, tmp_path: Path
) -> None:
    postgres_url = postgres_container

    _migrate_to_head(postgres_url)
    head_revision = expected_migration_head()
    _downgrade_one_revision(postgres_url)
    starting_revision = read_db_revision(postgres_url)
    assert starting_revision is not None
    assert starting_revision != head_revision, (
        "the downgrade must have actually landed on a DIFFERENT (older) real "
        "revision -- otherwise this test proves nothing about crossing a "
        "migration boundary"
    )

    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ")  # adapt_flat_installer_layout only checks is_dir()

    context = UpgradeContext(
        install_root=str(install_root),
        state_root=str(tmp_path / "state"),
        database_url=postgres_url,
        owner_run_id="gate-a-run-33681670855-regression",
    )
    base_seams = build_default_seams(
        context,
        payload_source=str(runtime),
        drain_and_verify_quiescence=lambda: True,
        health_gate=lambda: True,
        stop_service=lambda: None,
    )
    # The interlock seams cross into a REAL machine-wide HKLM registry key
    # (civiccast.native.win_probes) -- orthogonal to the D3 database-revision
    # correctness this test proves, and unsafe to touch unconditionally from
    # a test run (elevation, and a shared machine-wide key). Faked here the
    # same way test_upgrade_orchestrator.py fakes it for every other
    # orchestrator test; every OTHER seam (backup, restore, migrate,
    # schema_revision, junction/tree selection) is the real production
    # wiring this test exists to exercise.
    base_seams = dataclasses.replace(
        base_seams, acquire_interlock=lambda: None, release_interlock=lambda: None
    )
    seams = adapt_flat_installer_layout(base_seams, context)

    plan = UpgradePlan(old_version="n-minus-1", new_version="gate-a-33681670855-fixed")

    outcome = run_upgrade(plan, context, seams)

    assert outcome.phase is UpgradePhase.COMPLETE, (
        f"expected COMPLETE, got {outcome.phase} -- journal error: {outcome.journal.error!r}; "
        f"history: {outcome.journal.history!r}"
    )
    assert outcome.journal.post_schema_revision == head_revision
    assert outcome.journal.backup is not None
    assert outcome.journal.backup.verified is True
    assert outcome.journal.backup.restore_drill_ok is True, (
        "the pre-upgrade backup's restore-drill must have passed against the SOURCE "
        "revision (Fix A) -- a False here means the D3 root cause (comparing the "
        "restored pre-upgrade copy against the wrong, newer, code-head revision) "
        "regressed"
    )

    assert read_db_revision(postgres_url) == head_revision, (
        "the live database's revision (read independently of the journal) must "
        "actually be at the code's migration head after a COMPLETE outcome"
    )
