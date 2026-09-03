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
reachable) -- the CI Postgres lane (``.github/workflows/ci-test.yml``'s
``Unit tests`` job) never installs Postgres client tools on the runner, so
this test must not assume ``pg_dump``/``pg_dumpall``/``pg_restore``/``psql``
are on the host PATH. It follows the exact same ``docker exec`` pattern
``tests/dr/test_postgres_restore.py`` already proves (see that file's
``_exec_prefix``): every command shells into the SAME testcontainers
container that owns the server, and :func:`civiccast.native.upgrade.seams.
default_backup`'s new ``command_database_url`` parameter (added alongside
this test) lets that in-container URL drive the CLI tools' ``--host``/
``--port`` parsing while ``UpgradeContext.database_url`` stays the
HOST-mapped URL every direct SQLAlchemy touch in this module (the backup
snapshot, the restore drill's own verification reads, ``migrate()``,
``schema_revision()``) needs -- the exact split ``run_full_backup`` and
``run_postgres_restore_drill`` already support and the DR suite already
relies on, now reachable through the real production seam instead of only
through backup.py's lower-level functions directly.
``CIVICCAST_RUN_POSTGRES_TESTS=1`` marks this required in CI's Postgres lane;
see ``civiccast/native/upgrade`` module docs for what is and is not covered
elsewhere.

Marked ``integration`` (registered in ``pyproject.toml``) so
``.github/workflows/ci-test.yml``'s WS4 Windows job (``pytest tests/native -m
"not integration"``) excludes it -- that job's own next step asserts
"nothing may skip" across all of ``tests/native``, and ``windows-latest``
runners do not reliably run Linux containers the way testcontainers needs
this module's Postgres container to. The ubuntu "Unit tests" job runs this
test WITHOUT that exclusion, with ``CIVICCAST_RUN_POSTGRES_TESTS=1`` making
an unreachable Docker daemon there a hard failure rather than a skip (see
that job's own docker-availability guard step) -- the same proven-on-Linux
boundary ``tests/dr/test_postgres_restore.py`` already runs under.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from civiccast.native.upgrade.models import UpgradeContext, UpgradePhase, UpgradePlan
from civiccast.native.upgrade.orchestrator import run_upgrade
from civiccast.native.upgrade.seams import adapt_flat_installer_layout, build_default_seams
from civiccast.schema_check import _alembic_runtime_paths, expected_migration_head, read_db_revision
from tests.support.docker_engine import container_cli, docker_engine_available

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    _TESTCONTAINERS_OK = True
except ImportError:
    _TESTCONTAINERS_OK = False
    PostgresContainer = None  # type: ignore[misc,assignment]

pytestmark = pytest.mark.integration


def _skip_if_no_postgres() -> None:
    if not _TESTCONTAINERS_OK or not docker_engine_available():
        if os.environ.get("CIVICCAST_RUN_POSTGRES_TESTS"):
            pytest.fail("D3 upgrade engine Postgres test required by env but Docker unavailable")
        pytest.skip(
            "Docker unavailable; the real D3 upgrade engine path is not exercised in this sandbox"
        )


@pytest.fixture
def postgres_container() -> Iterator[tuple[str, str]]:
    """Yields (HOST-reachable connection url, container id) -- same shape as
    ``tests/dr/test_postgres_restore.py``'s own fixture."""

    _skip_if_no_postgres()
    assert PostgresContainer is not None
    container = PostgresContainer("postgres:17", driver="psycopg")
    container.start()
    try:
        yield container.get_connection_url(), container.get_wrapped_container().id
    finally:
        container.stop()


def _exec_prefix(container_id: str, binary: str) -> list[str]:
    """``<docker|podman> exec -i -e PGPASSWORD=test <container> <binary>``.

    Identical to ``tests/dr/test_postgres_restore.py``'s own helper of the
    same name -- kept as a local copy rather than a shared import so this
    test file has no cross-directory test-module dependency, matching how
    every other ``tests/dr``/``tests/native`` Postgres-container test in this
    repo defines its own copy.
    """

    return [
        container_cli() or "docker",
        "exec",
        "-i",
        "-e",
        "PGPASSWORD=test",
        container_id,
        binary,
    ]


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
    postgres_container: tuple[str, str], tmp_path: Path
) -> None:
    postgres_url, container_id = postgres_container
    # The in-container view every exec-prefixed CLI tool parses -- the same
    # fixed bootstrap-user URL tests/dr/test_postgres_restore.py uses for its
    # own in-container calls (the testcontainers Postgres image's default
    # user/db is "test"/"test").
    in_container_url = "postgresql://test:test@localhost:5432/test"

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
        pg_dump_command=_exec_prefix(container_id, "pg_dump"),
        pg_dumpall_command=_exec_prefix(container_id, "pg_dumpall"),
        pg_restore_command=_exec_prefix(container_id, "pg_restore"),
        psql_command=_exec_prefix(container_id, "psql"),
        command_database_url=in_container_url,
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


def test_bl01_a_post_migration_failure_rolls_back_cleanly_through_the_real_restore_seam(
    postgres_container: tuple[str, str], tmp_path: Path
) -> None:
    """<installer-path-audit BL-01> The audit's "proof needed", exactly.

    ``default_restore_backup`` restored into ``context.database_url`` -- the
    LIVE database, which still holds every object in the dump PLUS whatever
    the partial migration added -- with no ``--clean``, no ``--if-exists`` and
    no ``--create`` anywhere in the argv. So ``pg_restore`` replayed
    ``CREATE TABLE``, hit ``relation "..." already exists``,
    ``--exit-on-error`` exited nonzero, ``run_postgres_restore`` raised, and
    the orchestrator went to ``_halt``. **The clean-rollback outcome (exit 10)
    that PR #143 was written around was UNREACHABLE for every post-migration
    failure**, while two shipped comments asserted the opposite as established
    fact and reasoned from it -- including the operator text for the brand-new
    exit 124, which tells the operator their database is intact.

    Every existing test of this seam was ``lambda backup: None`` or a call
    recorder; a grep for ``restore_backup`` under ``tests/`` found no
    execution of the real seam at all, which is exactly why this survived.

    This drives the REAL ``default_restore_backup``, over a REAL Postgres,
    with a ``migrate`` seam that lands one migration and THEN raises, and
    asserts all three things the audit asks for: ``ROLLED_BACK`` (not
    ``HALTED_RESTORE_FAILED``), the database back at its pre-upgrade
    revision, and source row parity.
    """
    from sqlalchemy import create_engine, text

    postgres_url, container_id = postgres_container
    in_container_url = "postgresql://test:test@localhost:5432/test"

    _migrate_to_head(postgres_url)
    _downgrade_one_revision(postgres_url)
    pre_revision = read_db_revision(postgres_url)
    assert pre_revision is not None
    assert pre_revision != expected_migration_head()

    # Plant a row so "the database came back" is a claim about DATA, not only
    # about a revision marker.
    engine = create_engine(postgres_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE civiccast.bl01_witness (id integer primary key)"))
            connection.execute(text("INSERT INTO civiccast.bl01_witness (id) VALUES (1), (2), (3)"))
    finally:
        engine.dispose()

    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ")

    context = UpgradeContext(
        install_root=str(install_root),
        state_root=str(tmp_path / "state"),
        database_url=postgres_url,
        owner_run_id="installer-path-audit-bl01",
    )
    base_seams = build_default_seams(
        context,
        payload_source=str(runtime),
        drain_and_verify_quiescence=lambda: True,
        health_gate=lambda: True,
        stop_service=lambda: None,
        pg_dump_command=_exec_prefix(container_id, "pg_dump"),
        pg_dumpall_command=_exec_prefix(container_id, "pg_dumpall"),
        pg_restore_command=_exec_prefix(container_id, "pg_restore"),
        psql_command=_exec_prefix(container_id, "psql"),
        command_database_url=in_container_url,
    )

    real_migrate = base_seams.migrate

    def _migrate_then_fail() -> None:
        # The migration REALLY LANDS first -- this is the post-mutation
        # frontier, which is the only place BL-01's restore is reachable.
        real_migrate()
        raise RuntimeError("injected post-migration failure (the D3 rollback must restore)")

    base_seams = dataclasses.replace(
        base_seams,
        acquire_interlock=lambda: None,
        release_interlock=lambda: None,
        migrate=_migrate_then_fail,
    )
    seams = adapt_flat_installer_layout(base_seams, context)

    outcome = run_upgrade(UpgradePlan(old_version="n-minus-1", new_version="bl01"), context, seams)

    assert outcome.phase is UpgradePhase.ROLLED_BACK, (
        f"expected ROLLED_BACK (exit 10) -- got {outcome.phase} with error "
        f"{outcome.journal.error!r}. HALTED_RESTORE_FAILED here means the restore could not "
        "replay into the live database, which is BL-01 itself"
    )
    assert read_db_revision(postgres_url) == pre_revision, (
        "the database must be back at the PRE-upgrade revision, not the migrated one"
    )

    engine = create_engine(postgres_url, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id FROM civiccast.bl01_witness ORDER BY id")
            ).fetchall()
    finally:
        engine.dispose()
    assert [row[0] for row in rows] == [1, 2, 3], (
        "the planted rows must survive the drop/recreate/restore cycle exactly"
    )


def test_bl01_exit_10_is_the_code_the_cli_reports_for_that_rollback() -> None:
    """The exit code is the half the installer branches on.

    The audit's point is not only that the journal says ROLLED_BACK -- it is
    that ``exit 10`` is REACHABLE for a post-mutation failure at all. This
    pins the mapping the NSIS ladder reads.
    """
    from civiccast.native.upgrade.__main__ import _EXIT_CODES

    assert _EXIT_CODES[UpgradePhase.ROLLED_BACK] == 10
    assert _EXIT_CODES[UpgradePhase.HALTED_RESTORE_FAILED] == 20
