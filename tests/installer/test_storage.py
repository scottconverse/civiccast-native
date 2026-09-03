# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from civiccast import schema_check
from civiccast.db.guarded_connect import DatabaseMissingError
from civiccast.installer import storage
from civiccast.installer.storage import (
    ManagedStorageError,
    durable_storage_status,
    ensure_managed_storage,
    managed_storage_status,
    sqlite_database_url,
)


def _touch_sqlite_url(database_url: str) -> None:
    prefix = "sqlite:///"
    assert database_url.startswith(prefix)
    Path(database_url[len(prefix) :]).touch()


def test_managed_storage_status_reports_not_configured(tmp_path: Path) -> None:
    status = managed_storage_status(tmp_path)

    assert status.status == "not_configured"
    assert status.migrations_applied is False
    assert status.database_url == sqlite_database_url(tmp_path / "data" / "civiccast.sqlite3")
    assert status.upload_dir == str(tmp_path / "uploads")
    assert "Prepare storage" in status.next_step


def test_ensure_managed_storage_writes_config_without_leaking_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    migrated: list[str] = []

    def fake_migration(database_url: str) -> None:
        migrated.append(database_url)
        _touch_sqlite_url(database_url)

    monkeypatch.setattr(storage, "_run_migrations", fake_migration)

    status = ensure_managed_storage(storage_dir=tmp_path)

    assert status.status == "ready"
    assert migrated == [status.database_url]
    assert (tmp_path / "managed-storage.json").exists()
    assert (tmp_path / "data" / "civiccast.sqlite3").exists()
    assert (tmp_path / "uploads").is_dir()
    assert os.environ.get("DATABASE_URL") is None
    reread = managed_storage_status(tmp_path)
    assert reread.status == "ready"
    assert reread.database_url == status.database_url


_EXTERNAL_URL = "postgresql://civiccast:pw@db.example.gov:5432/civiccast"


def _inject_db_revision(monkeypatch: pytest.MonkeyPatch, outcome: object) -> list[str]:
    """Fake the ONE real database touch the probe makes.

    ``civiccast.installer.storage._probe_external_database`` imports
    ``read_db_revision`` from :mod:`civiccast.schema_check` inside the function
    body, so patching the module attribute replaces the seam at call time. This
    is the connect-and-read boundary: everything the probe does with the answer
    -- the bounded execution, the missing-database classification, the
    alembic-head comparison -- still runs for real. No live Postgres needed.
    """

    calls: list[str] = []

    def fake_read_db_revision(database_url: str) -> str | None:
        calls.append(database_url)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]

    monkeypatch.setattr(schema_check, "read_db_revision", fake_read_db_revision)
    return calls


def test_durable_storage_status_preserves_external_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The external URL is still reported verbatim -- when the DB is healthy.

    UPDATED (was: this test asserted ``status == "ready"`` for a
    ``DATABASE_URL`` that was never connected to). That assertion encoded the
    defect: the external branch returned ``status="ready"``,
    ``migrations_applied=True`` unconditionally, with no connection attempt and
    no schema check, so on native -- where ``DATABASE_URL`` is ALWAYS set by
    the supervisor -- a stopped database still reported green. The URL
    pass-through this test actually exists to pin is unchanged; readiness is
    now earned by an executed probe, injected here.
    """

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(monkeypatch, schema_check.expected_migration_head())

    status = durable_storage_status(tmp_path)

    assert status.status == "ready"
    assert status.migrations_applied is True
    assert status.database_url == _EXTERNAL_URL
    assert status.storage_dir == "configured by DATABASE_URL"


def test_unreachable_external_database_is_never_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stopped database is the defect's headline case."""

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(
        monkeypatch,
        OperationalError("connect", {}, ConnectionRefusedError("refused")),
    )

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_UNREACHABLE
    assert status.status != "ready"
    assert status.migrations_applied is False
    assert "could not reach its database" in status.operator_message


def test_schema_behind_external_database_is_never_ready(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The worst masked case: auth works, tokens work, migrations are missing.

    <installer-path-audit MA-06> The revision injected here is now a REAL
    ancestor from this build's own migration graph, not the invented string
    ``"0001_an_ancestor_revision"``. That string was never in the graph, so it
    describes an UNKNOWN revision -- which is the "ahead" case (a newer build
    migrated this database), not the "behind" case this test is named for. The
    old fixture could only ever have proved the two-state collapse the finding
    is about.
    """

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(monkeypatch, _a_real_ancestor_revision())

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_SCHEMA_BEHIND
    assert status.migrations_applied is False
    assert "older version of CivicCast" in status.operator_message
    # ...and it must be distinguishable from "unreachable", not collapsed.
    assert status.status != storage.EXTERNAL_DATABASE_UNREACHABLE


def _a_real_ancestor_revision() -> str:
    """Any revision in this build's graph that is NOT the head.

    Read from the graph rather than hardcoded so it cannot go stale, and so
    the "behind" and "ahead" tests below are genuinely different inputs rather
    than two invented strings.
    """

    head = schema_check.expected_migration_head()
    ancestors = sorted(schema_check.known_revisions() - {head})
    assert ancestors, "this build's migration graph has only one revision"
    return ancestors[0]


def test_schema_ahead_external_database_is_never_ready_and_says_so_honestly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """<installer-path-audit MA-06> A database a NEWER build migrated.

    There used to be no ``ahead`` state at all: any non-equal revision was
    ``behind``, and the operator was told to "bring the CivicCast database up
    to date". On an ahead database that advice CANNOT WORK -- ``alembic
    upgrade head`` cannot locate a revision this build's graph does not
    contain, so it fails. This is also exactly the state a failed rollback
    leaves behind (new schema, old binary), which is what the D3 halt path is
    designed around, so it is not hypothetical.
    """

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(monkeypatch, "9999_a_revision_from_a_future_build")

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_SCHEMA_AHEAD
    assert status.status != storage.EXTERNAL_DATABASE_SCHEMA_BEHIND
    assert status.migrations_applied is False
    assert "NEWER version of CivicCast" in status.operator_message
    assert "Updating the database will NOT fix this" in status.next_step
    assert status.status in storage.EXTERNAL_DATABASE_NOT_READY_STATUSES


def test_external_database_with_no_alembic_version_table_is_schema_behind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``read_db_revision`` returns None for an empty database. Not ready."""

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(monkeypatch, None)

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_SCHEMA_BEHIND
    assert status.migrations_applied is False


def test_missing_external_database_is_its_own_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Postgres answered; the named database does not exist (SQLSTATE 3D000).

    Never ordinary unreachability -- restarting Postgres cannot fix it, so the
    operator copy must not tell anyone to try.
    """

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    _inject_db_revision(monkeypatch, DatabaseMissingError("3D000"))

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_MISSING
    assert status.migrations_applied is False
    assert "does not exist" in status.operator_message
    assert "running" not in status.next_step


def test_malformed_external_database_url_is_misconfigured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No seam needed: ``make_url`` rejects this before any connect."""

    monkeypatch.setenv("DATABASE_URL", "this is not a database address")

    status = durable_storage_status(tmp_path)

    assert status.status == storage.EXTERNAL_DATABASE_MISCONFIGURED
    assert status.migrations_applied is False
    assert "not in a form CivicCast understands" in status.operator_message


def test_every_external_outcome_is_distinguishable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The four outcomes must not collapse into one status or one message."""

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    seen: dict[str, tuple[str, str]] = {}
    for name, outcome in (
        ("current", schema_check.expected_migration_head()),
        ("behind", "0001_an_ancestor_revision"),
        ("unreachable", OperationalError("connect", {}, ConnectionRefusedError("refused"))),
        ("missing", DatabaseMissingError("3D000")),
    ):
        storage.reset_external_database_probe_cache()
        with monkeypatch.context() as patched:
            _inject_db_revision(patched, outcome)
            status = durable_storage_status(tmp_path)
        seen[name] = (status.status, status.operator_message)

    assert len({value[0] for value in seen.values()}) == 4
    assert len({value[1] for value in seen.values()}) == 4
    assert seen["current"][0] == "ready"
    assert all(value[0] != "ready" for name, value in seen.items() if name != "current")


def test_external_database_probe_cannot_hang_the_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A blackholed database must not hang ``/installer/summary``.

    Executed, not asserted from the constant: the injected seam blocks for far
    longer than any operator would wait, and the call must still return -- with
    an honest "unreachable" -- inside the hard ceiling
    ``run_bounded`` enforces. Uses a real sleep because the whole point is that
    the ceiling holds against a callee that ignores every timeout hint, which
    is precisely what BLOCKER #52 measured psycopg v3 doing on this platform.
    """

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    monkeypatch.setattr(storage, "_EXTERNAL_DATABASE_PROBE_CEILING_SECONDS", 0.5)

    def blackholed(database_url: str) -> str | None:
        time.sleep(30)
        return "never-reached"

    monkeypatch.setattr(schema_check, "read_db_revision", blackholed)

    started = time.monotonic()
    status = durable_storage_status(tmp_path)
    elapsed = time.monotonic() - started

    assert status.status == storage.EXTERNAL_DATABASE_UNREACHABLE
    assert status.migrations_applied is False
    assert elapsed < 5.0, f"probe was not bounded: {elapsed:.1f}s"


def test_external_database_probe_is_memoized_between_polls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The GUI polls this endpoint; one probe must serve several polls."""

    monkeypatch.setenv("DATABASE_URL", _EXTERNAL_URL)
    calls = _inject_db_revision(monkeypatch, schema_check.expected_migration_head())

    first = durable_storage_status(tmp_path)
    second = durable_storage_status(tmp_path)

    assert first.status == "ready"
    assert second.status == "ready"
    assert len(calls) == 1

    storage.reset_external_database_probe_cache()
    durable_storage_status(tmp_path)
    assert len(calls) == 2


def test_managed_sqlite_path_never_probes_an_external_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Requirement (c): the managed branch's behaviour is unchanged.

    Both managed shapes are covered -- no ``DATABASE_URL`` at all, and a
    ``DATABASE_URL`` that MATCHES the managed one -- and neither may reach the
    external probe, whose seam is replaced here with a hard failure.
    """

    def must_not_run(database_url: str) -> str | None:
        raise AssertionError(f"managed storage must not probe {database_url!r}")

    monkeypatch.setattr(schema_check, "read_db_revision", must_not_run)
    monkeypatch.setattr(storage, "_run_migrations", lambda url: _touch_sqlite_url(url))

    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert durable_storage_status(tmp_path).status == "not_configured"

    prepared = ensure_managed_storage(storage_dir=tmp_path)
    monkeypatch.setenv("DATABASE_URL", prepared.database_url)
    managed = durable_storage_status(tmp_path)

    assert managed.status == "ready"
    assert managed.migrations_applied is True
    assert managed.storage_dir == str(tmp_path)
    assert managed.operator_message == "CivicCast local durable storage is ready."


def test_durable_storage_status_returns_managed_status_when_env_matches_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_migration(database_url: str) -> None:
        _touch_sqlite_url(database_url)

    monkeypatch.setattr(storage, "_run_migrations", fake_migration)
    prepared = ensure_managed_storage(storage_dir=tmp_path)
    monkeypatch.setenv("DATABASE_URL", prepared.database_url)

    status = durable_storage_status(tmp_path)

    assert status.status == "ready"
    assert status.storage_dir == str(tmp_path)
    assert status.upload_dir == str(tmp_path / "uploads")
    assert status.database_path == prepared.database_path


def test_managed_storage_status_rejects_invalid_config(tmp_path: Path) -> None:
    (tmp_path / "managed-storage.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ManagedStorageError, match="not a JSON object"):
        managed_storage_status(tmp_path)


def test_migrations_can_use_packaged_alembic_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, str] = {}

    class FakeConfig:
        def __init__(self, path: str) -> None:
            observed["path"] = path

        def set_main_option(self, key: str, value: str) -> None:
            observed[key] = value

    def fake_upgrade(cfg: FakeConfig, revision: str) -> None:
        observed["revision"] = revision
        _touch_sqlite_url(observed["sqlalchemy.url"])

    monkeypatch.setattr(storage, "_ALEMBIC_INI", tmp_path / "missing-alembic.ini")
    monkeypatch.setattr(storage, "Config", FakeConfig)
    monkeypatch.setattr(storage.command, "upgrade", fake_upgrade)

    status = ensure_managed_storage(storage_dir=tmp_path)

    assert status.status == "ready"
    assert observed["revision"] == "head"
    assert observed["path"].endswith("civiccast/alembic/alembic.ini") or observed["path"].endswith(
        "civiccast\\alembic\\alembic.ini"
    )
    assert observed["script_location"].endswith("civiccast/alembic") or observed[
        "script_location"
    ].endswith("civiccast\\alembic")
    assert "schedule" in observed["version_locations"]
    assert "migrations" in observed["version_locations"]


def test_packaged_alembic_fallback_applies_module_migrations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(storage, "_ALEMBIC_INI", tmp_path / "missing-alembic.ini")

    status = ensure_managed_storage(storage_dir=tmp_path)

    database_path = tmp_path / "data" / "civiccast.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
    finally:
        connection.close()
    assert status.status == "ready"
    assert "assets" in tables
