# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A failed pg-tool SPAWN must name the executable it tried to run.

Sandbox run 22 (2026-07-31) cost a full ~20-minute gauntlet run to diagnose:
the D3 upgrade engine's journal recorded only ``"error": "[WinError 2] The
system cannot find the file specified"``. Windows raises that
:class:`FileNotFoundError` with ``filename`` unset and no argv in the message,
so the record identified neither which of the four PostgreSQL client tools had
failed nor what path was attempted -- the actual cause (a bare ``pg_dump``
resolved through a PATH that never contains the staged pack ``bin``
directory) had to be reconstructed by reading source.

Every ``subprocess`` spawn in :mod:`civiccast.dr.backup` must therefore report
``argv[0]``. ``argv[1:]`` is deliberately NOT reported: it carries the host,
port, user and database name parsed out of ``DATABASE_URL``.

No container and no database: these tests only ever reach the spawn, which
fails before any connection is attempted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.dr.backup import (
    create_fresh_postgres_database,
    run_postgres_backup,
    run_postgres_globals_backup,
    run_postgres_restore,
)

_URL = "postgresql://civiccast:tr0ub4dor-marker-51c9@127.0.0.1:5432/civiccast"


def _absent(tmp_path: Path, name: str) -> list[str]:
    """An ABSOLUTE path that certainly does not exist -- the post-fix
    production shape (a resolved staged path), broken."""

    return [str(tmp_path / "no-such-bin" / name)]


def _assert_names_executable(message: str, expected: str) -> None:
    assert expected in message, f"the failure must name argv[0]; got: {message!r}"
    assert "tr0ub4dor-marker-51c9" not in message, "the password must never be echoed"


def test_pg_dump_spawn_failure_names_the_executable(tmp_path: Path) -> None:
    command = _absent(tmp_path, "pg_dump.exe")
    with pytest.raises(FileNotFoundError) as excinfo:
        run_postgres_backup(database_url=_URL, dest_dir=tmp_path / "out", pg_dump_command=command)

    _assert_names_executable(str(excinfo.value), command[0])
    assert "pg_dump" in str(excinfo.value)


def test_pg_dumpall_spawn_failure_names_the_executable(tmp_path: Path) -> None:
    command = _absent(tmp_path, "pg_dumpall.exe")
    with pytest.raises(FileNotFoundError) as excinfo:
        run_postgres_globals_backup(
            database_url=_URL, dest_dir=tmp_path / "out", pg_dumpall_command=command
        )

    _assert_names_executable(str(excinfo.value), command[0])


def test_pg_restore_spawn_failure_names_the_executable(tmp_path: Path) -> None:
    artifact = tmp_path / "database.pgdump"
    artifact.write_bytes(b"PGDMP-not-really")
    command = _absent(tmp_path, "pg_restore.exe")
    with pytest.raises(FileNotFoundError) as excinfo:
        run_postgres_restore(artifact, _URL, pg_restore_command=command)

    _assert_names_executable(str(excinfo.value), command[0])


def test_psql_spawn_failure_names_the_executable(tmp_path: Path) -> None:
    command = _absent(tmp_path, "psql.exe")
    with pytest.raises(FileNotFoundError) as excinfo:
        create_fresh_postgres_database(database_url=_URL, psql_command=command)

    _assert_names_executable(str(excinfo.value), command[0])


def test_bare_name_failure_says_it_was_resolved_through_path(tmp_path: Path) -> None:
    """The exact run-22 shape: a BARE name, which on the install host is
    resolved through a PATH that never contains the staged pack bin
    directory. The message must distinguish that from a resolved-but-absent
    absolute path, because the two have different fixes."""

    with pytest.raises(FileNotFoundError) as excinfo:
        run_postgres_backup(
            database_url=_URL,
            dest_dir=tmp_path / "out",
            pg_dump_command=["civiccast-no-such-tool-3f81"],
        )

    message = str(excinfo.value)
    _assert_names_executable(message, "civiccast-no-such-tool-3f81")
    assert "PATH" in message
