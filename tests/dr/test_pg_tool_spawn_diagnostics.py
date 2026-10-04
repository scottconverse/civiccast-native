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
from subprocess import CompletedProcess

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


@pytest.mark.parametrize("operation", ["dump", "restore", "drill-create"])
def test_pg_tools_preserve_explicit_secure_connection_options(tmp_path, monkeypatch, operation):
    from civiccast.dr import backup, restore_drill

    url = (
        _URL
        + "?sslmode=verify-full&sslrootcert=C%3A%2Fowned%2Fca.pem&channel_binding=require&options=-c%20statement_timeout%3D15000"
    )
    calls = []

    def spawn(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return CompletedProcess(argv, 0, stdout=b"UTF8|C|C\n", stderr=b"")

    monkeypatch.setattr(backup, "_spawn_pg_tool", spawn)
    monkeypatch.setenv("PGSERVICE", "unrelated-host-service")
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.setenv("PGOPTIONS", "-c role=unrelated_role")
    if operation == "dump":
        backup.run_postgres_backup(database_url=url, dest_dir=tmp_path)
    elif operation == "restore":
        artifact = tmp_path / "database.pgdump"
        artifact.write_bytes(b"synthetic dump")
        backup.run_postgres_restore(artifact, url)
    else:
        restored = backup.create_fresh_postgres_database(database_url=url)
        assert "sslmode=verify-full" in restored
        assert "sslmode=verify-full" in restore_drill._with_database_name(url, "scratch")
    assert calls
    for argv, env in calls:
        assert env["PGSSLMODE"] == "verify-full"
        assert env["PGSSLROOTCERT"] == "C:/owned/ca.pem"
        assert env["PGCHANNELBINDING"] == "require"
        assert env["PGOPTIONS"] == "-c statement_timeout=15000"
        assert "PGSERVICE" not in env
        assert "tr0ub4dor-marker-51c9" not in " ".join(argv)


@pytest.mark.parametrize(
    "query",
    [
        "service=other",
        "hostaddr=10.0.0.1",
        "sslmode=require&sslmode=disable",
        "options=-c%20role%3Dsuperuser",
    ],
)
def test_pg_tools_refuse_unsafe_or_ambiguous_query_before_spawn(tmp_path, monkeypatch, query):
    from civiccast.dr import backup

    monkeypatch.setattr(backup, "_spawn_pg_tool", lambda *_args, **_kwargs: pytest.fail("spawned"))
    with pytest.raises(ValueError):
        backup.run_postgres_backup(database_url=_URL + "?" + query, dest_dir=tmp_path / "no-io")
    assert not (tmp_path / "no-io").exists()


@pytest.mark.parametrize("driver", ["pg8000", "asyncpg"])
def test_secure_drill_does_not_strip_options_to_please_incompatible_driver(driver):
    from civiccast.dr import restore_drill

    url = _URL.replace("postgresql://", "postgresql+" + driver + "://")
    with pytest.raises(ValueError, match="libpq verification driver"):
        restore_drill._verification_engine_url(url + "?sslmode=verify-full")


@pytest.mark.parametrize(
    "variable",
    [
        "PGHOSTADDR",
        "PGOPTIONS",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGPASSFILE",
        "PGPASSWORD",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "PGSSLKEY",
        "PGSSLCRL",
        "PGCHANNELBINDING",
        "PGTARGETSESSIONATTRS",
    ],
)
def test_drill_refuses_conflicting_ambient_defaults_before_connection(
    tmp_path, monkeypatch, variable
):
    from datetime import UTC, datetime

    from civiccast.dr import restore_drill
    from civiccast.dr.models import BackupManifest

    marker = "synthetic-sensitive-ambient-marker"
    monkeypatch.setenv(variable, marker)
    monkeypatch.setattr(restore_drill, "create_engine", lambda *_a, **_kw: pytest.fail("connected"))
    manifest = BackupManifest(
        backup_id="synthetic",
        created_at=datetime.now(UTC),
        engine="postgres",
        db_artifact="synthetic.dump",
    )
    with pytest.raises(ValueError, match=variable) as error:
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path, manifest=manifest, source_database_url=_URL
        )
    assert marker not in str(error.value)
    import os

    assert os.environ[variable] == marker


def test_full_backup_refuses_ambient_service_before_directory_io(tmp_path, monkeypatch):
    from civiccast.dr.backup import run_full_backup

    monkeypatch.setenv("PGSERVICE", "synthetic-sensitive-service-marker")
    destination = tmp_path / "no-io"
    with pytest.raises(ValueError, match="PGSERVICE") as error:
        run_full_backup(database_url=_URL, dest_dir=destination)
    assert not destination.exists()
    assert "synthetic-sensitive-service-marker" not in str(error.value)


def test_matching_explicit_pg_defaults_remain_admitted(monkeypatch):
    from civiccast.dr.backup import _admit_postgres_environment, _parse_postgres_url

    conn = _parse_postgres_url(_URL)
    for key, value in {
        "PGHOST": conn["host"],
        "PGUSER": conn["user"],
        "PGDATABASE": conn["dbname"],
        "PGPASSWORD": conn["password"],
        "PGSSLMODE": "verify-full",
        "PGOPTIONS": "-c statement_timeout=15000",
    }.items():
        monkeypatch.setenv(key, value)
    _admit_postgres_environment(
        _URL + "?sslmode=verify-full&options=-c%20statement_timeout%3D15000"
    )


def test_malformed_pg_query_refuses_without_leaking_raw_field(tmp_path):
    from civiccast.dr import backup

    with pytest.raises(ValueError) as error:
        backup.run_postgres_backup(
            database_url=_URL + "?synthetic-sensitive-marker", dest_dir=tmp_path / "no-io"
        )
    assert "synthetic-sensitive-marker" not in str(error.value)
    assert not (tmp_path / "no-io").exists()


def test_differing_explicit_timeout_is_refused_before_io(tmp_path, monkeypatch):
    from civiccast.dr import backup, restore_drill

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "10")
    url = _URL + "?connect_timeout=15"
    with pytest.raises(ValueError, match="connect_timeout"):
        backup.run_postgres_backup(database_url=url, dest_dir=tmp_path / "no-io")
    with pytest.raises(ValueError, match="connect_timeout"):
        restore_drill._verification_engine_url(url)
    assert not (tmp_path / "no-io").exists()


def test_matching_timeout_has_same_effective_tool_and_driver_value(monkeypatch):
    from sqlalchemy import create_engine

    from civiccast.db import connect_options
    from civiccast.dr import backup, restore_drill

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "10")
    url = _URL + "?connect_timeout=10"
    engine = create_engine(restore_drill._verification_engine_url(url), **connect_options(url))
    try:
        _, parameters = engine.dialect.create_connect_args(engine.url)
        parameters.update(connect_options(url)["connect_args"])
        assert (
            str(parameters["connect_timeout"])
            == backup._postgres_tool_environment(url)["PGCONNECT_TIMEOUT"]
            == "10"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("query", ["", "?connect_timeout=20"])
def test_global_timeout_tool_and_driver_parity(monkeypatch, query):
    from civiccast.db import connect_options
    from civiccast.dr.backup import _postgres_tool_environment

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    url = _URL + query
    assert (
        _postgres_tool_environment(url)["PGCONNECT_TIMEOUT"]
        == str(connect_options(url)["connect_args"]["connect_timeout"])
        == "20"
    )


@pytest.mark.parametrize("query", ["", "?connect_timeout=10"])
def test_explicit_local_timeout_overrides_global_without_mutation(monkeypatch, query):
    import os

    from civiccast.dr import backup, restore_drill

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    url = _URL + query
    backup._admit_postgres_environment(url, timeout_seconds=10)
    assert backup._postgres_tool_environment(url, timeout_seconds=10)["PGCONNECT_TIMEOUT"] == "10"
    assert restore_drill._verification_engine_url(url, timeout_seconds=10)
    assert os.environ["CIVICCAST_DB_CONNECT_TIMEOUT"] == "20"


def test_local_timeout_refuses_explicit_global_value(monkeypatch):
    from civiccast.dr.backup import _postgres_query_options

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    with pytest.raises(ValueError, match="connect_timeout"):
        _postgres_query_options(_URL + "?connect_timeout=20", timeout_seconds=10)


def test_revision_reader_consumes_local_bound_without_global_mutation(monkeypatch):
    import os

    import sqlalchemy

    from civiccast import schema_check

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    seen = []

    def factory(url, **kwargs):
        seen.append(kwargs["connect_args"]["connect_timeout"])
        raise RuntimeError("revision engine construction observed")

    monkeypatch.setattr(sqlalchemy, "create_engine", factory)
    with pytest.raises(RuntimeError, match="revision engine construction"):
        schema_check.read_db_revision(_URL + "?connect_timeout=10", timeout_seconds=10)
    assert seen == [10]
    assert os.environ["CIVICCAST_DB_CONNECT_TIMEOUT"] == "20"
