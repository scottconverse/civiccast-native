# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression coverage for civiccast.native.upgrade.seams's DB-touching
default seam builders (beta BLOCKER #51).

The installer persists DATABASE_URL under the bare ``postgresql://`` scheme
(see civiccast.native.supervisor.service_env's registry bridge), which
SQLAlchemy maps to the psycopg2 dialect -- this project ships psycopg v3
only (ADR 0008). These tests assert at the call boundary each seam owns
(alembic's ``Config.sqlalchemy.url``), never internals, and never touch a
real database.
"""

from __future__ import annotations

import pytest

from civiccast.native.upgrade import seams as seams_module
from civiccast.native.upgrade.models import BackupRef, UpgradeContext, UpgradeSeams
from civiccast.native.upgrade.seams import default_migrate


def test_flat_installer_layout_reuses_verified_runtime_without_a_junction(tmp_path) -> None:
    """The NSIS product is flat: service + activation use ``<root>\\runtime``.

    Gate A installs onto a Windows Sandbox mapped folder because the exact
    station kit is too large for the guest disk.  That filesystem rejects
    ``mklink /J``.  More importantly, a junction there would not select the
    product runtime anyway: the real service is registered against the flat
    runtime directory.  The adapter must therefore model that already-staged,
    D2-verified payload without copying it or creating a fictitious selector.
    """

    adapter = getattr(seams_module, "adapt_flat_installer_layout", None)
    assert callable(adapter), "the production flat installer layout needs an explicit seam adapter"

    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ")
    context = UpgradeContext(
        install_root=str(install_root),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )
    forbidden_calls: list[str] = []
    base = UpgradeSeams(
        acquire_interlock=lambda: None,
        release_interlock=lambda: None,
        drain_and_verify_quiescence=lambda: True,
        backup=lambda backup_dir: BackupRef(
            backup_id="b",
            backup_dir=backup_dir,
            manifest_hash="h",
            db_artifact="database.pgdump",
            verified=True,
            restore_drill_ok=True,
        ),
        restore_backup=lambda backup: None,
        lay_tree=lambda version: forbidden_calls.append(f"lay:{version}") or "unused",
        flip_junction=lambda target: forbidden_calls.append(f"flip:{target}"),
        read_junction=lambda: forbidden_calls.append("read") or None,
        migrate=lambda: None,
        health_gate=lambda: True,
        schema_revision=lambda: "head",
        stop_service=lambda: None,
    )

    adapted = adapter(base, context)
    expected = str(runtime.resolve())
    assert adapted.read_junction() == expected
    assert adapted.lay_tree("1.1") == expected
    adapted.flip_junction(expected)
    assert forbidden_calls == []
    assert not (install_root / "current").exists()
    assert not (install_root / "app").exists()

    with pytest.raises(RuntimeError, match="flat runtime payload"):
        adapted.flip_junction(str(tmp_path / "other"))


def test_default_migrate_normalizes_bare_postgresql_scheme_in_alembic_config(
    tmp_path, monkeypatch
) -> None:
    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://civiccast:tr0ub4dor@127.0.0.1:5432/civiccast",
        owner_run_id="run-1",
    )

    captured: dict[str, str] = {}

    def _fake_upgrade(cfg, revision) -> None:  # type: ignore[no-untyped-def]
        captured["url"] = cfg.get_main_option("sqlalchemy.url")

    import alembic.command

    monkeypatch.setattr(alembic.command, "upgrade", _fake_upgrade)

    migrate = default_migrate(context)
    migrate()

    assert captured["url"].startswith("postgresql+psycopg://")
    assert "tr0ub4dor" in captured["url"]  # password must survive, not be corrupted


def test_default_migrate_leaves_explicit_driver_scheme_untouched(tmp_path, monkeypatch) -> None:
    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql+psycopg2://civiccast:secret@127.0.0.1:5432/civiccast",
        owner_run_id="run-1",
    )

    captured: dict[str, str] = {}

    def _fake_upgrade(cfg, revision) -> None:  # type: ignore[no-untyped-def]
        captured["url"] = cfg.get_main_option("sqlalchemy.url")

    import alembic.command

    monkeypatch.setattr(alembic.command, "upgrade", _fake_upgrade)

    migrate = default_migrate(context)
    migrate()

    # An explicit (if presently unsupported by this project's deps) driver
    # choice always wins over normalization.
    assert captured["url"] == context.database_url


# ---------------------------------------------------------------------------
# <installer-path-audit BL-01> The rollback restore, through the REAL seam.
#
# `default_restore_backup` used to be a bare pg_restore into
# `context.database_url` -- the LIVE database, which still holds every object
# in the dump plus whatever the partial migration added -- with no --clean, no
# --if-exists and no --create anywhere. So `pg_restore` replayed CREATE TABLE,
# hit `relation "..." already exists`, --exit-on-error exited nonzero,
# run_postgres_restore raised, and the orchestrator went to _halt. The
# clean-rollback outcome (exit 10) PR #143 was written around was UNREACHABLE
# for every post-migration failure -- while two shipped comments asserted the
# opposite as established fact and reasoned from it.
#
# The audit's other observation is why these tests exist at all: every
# existing test of this seam was `lambda backup: None` or a call recorder, and
# a grep for `restore_backup` under tests/ found no execution of the real
# seam. These drive the real one, with only the two subprocess primitives
# faked.
# ---------------------------------------------------------------------------


def _write_backup(tmp_path, *, artifact_bytes: bytes = b"PGDMP-fake") -> tuple[object, object]:
    """A real backup directory + manifest the restore seam can be pointed at."""
    import hashlib
    import json

    from civiccast.dr.models import BackupManifest, IntegrityManifestEntry
    from civiccast.native.upgrade.models import BackupRef

    dest = tmp_path / "backups" / "pre-1.1"
    dest.mkdir(parents=True)
    (dest / "database.pgdump").write_bytes(artifact_bytes)
    manifest = BackupManifest(
        backup_id="b-1",
        created_at="2026-09-03T00:00:00+00:00",
        engine="postgres",
        db_artifact="database.pgdump",
        tables=[],
        integrity=[
            IntegrityManifestEntry(
                member="database.pgdump",
                sha256=hashlib.sha256(artifact_bytes).hexdigest(),
            )
        ],
    )
    (dest / "manifest.json").write_text(
        json.dumps(json.loads(manifest.model_dump_json())), encoding="utf-8"
    )
    ref = BackupRef(
        backup_id="b-1",
        backup_dir=str(dest),
        manifest_hash="h",
        db_artifact="database.pgdump",
        verified=True,
        restore_drill_ok=True,
    )
    return ref, manifest


def _restore_context(tmp_path) -> UpgradeContext:
    return UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://civiccast:pw@127.0.0.1:5432/civiccast",
        owner_run_id="run-1",
    )


def test_the_expected_head_seam_only_swallows_import_and_io_failures(monkeypatch) -> None:
    """Review of PR #145: the `except Exception` here was fail-open.

    Only the two failures where "unavailable" is the honest answer are
    caught -- alembic missing from the payload, and an unreadable ini/script
    directory. A branched migration graph (`RuntimeError`) must PROPAGATE, so
    the orchestrator records the message that names the heads.
    """
    import civiccast.schema_check as schema_check

    head = seams_module.default_expected_schema_head()

    def _raise(exc: BaseException):  # type: ignore[no-untyped-def]
        def _boom() -> str:
            raise exc

        return _boom

    monkeypatch.setattr(schema_check, "expected_migration_head", _raise(ImportError("no alembic")))
    assert head() is None
    monkeypatch.setattr(schema_check, "expected_migration_head", _raise(OSError("no alembic.ini")))
    assert head() is None

    monkeypatch.setattr(
        schema_check,
        "expected_migration_head",
        _raise(RuntimeError("Expected exactly one migration head, found ['a', 'b'].")),
    )
    with pytest.raises(RuntimeError, match="exactly one migration head"):
        head()


def test_the_production_bundle_always_wires_the_expected_head_seam(tmp_path) -> None:
    """The orchestrator's `seams.expected_schema_head is None` branch is the
    fake-seam case ONLY. If a refactor ever dropped this wiring, production
    would take the UNAVAILABLE path silently."""
    runtime = tmp_path / "install" / "runtime"
    runtime.mkdir(parents=True)
    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )
    bundle = seams_module.build_default_seams(
        context,
        payload_source=str(runtime),
        drain_and_verify_quiescence=lambda: True,
        health_gate=lambda: True,
        stop_service=lambda: None,
    )
    assert bundle.expected_schema_head is not None
    # And it answers with this build's real head, not a placeholder.
    from civiccast.schema_check import expected_migration_head

    assert bundle.expected_schema_head() == expected_migration_head()


def test_bl01_the_rollback_recreates_the_target_before_replaying_the_dump(
    tmp_path, monkeypatch
) -> None:
    """The restore must land in an EMPTY database, in order."""
    order: list[str] = []
    recreate_kwargs: dict[str, object] = {}
    restore_kwargs: dict[str, object] = {}

    def _fake_create_fresh(**kwargs):  # type: ignore[no-untyped-def]
        order.append("create_fresh")
        recreate_kwargs.update(kwargs)
        return "postgresql://civiccast:pw@127.0.0.1:5432/civiccast"

    def _fake_restore(artifact, url, **kwargs):  # type: ignore[no-untyped-def]
        order.append("pg_restore")
        restore_kwargs.update(kwargs)
        restore_kwargs["url"] = url

    monkeypatch.setattr("civiccast.dr.backup.create_fresh_postgres_database", _fake_create_fresh)
    monkeypatch.setattr(seams_module, "run_postgres_restore", _fake_restore)

    ref, _manifest = _write_backup(tmp_path)
    seams_module.default_restore_backup(_restore_context(tmp_path))(ref)

    assert order == ["create_fresh", "pg_restore"], (
        "the target must be dropped and recreated BEFORE the dump is replayed"
    )
    assert recreate_kwargs["database_name"] == "civiccast", (
        "the LIVE database is the target -- restoring into a differently-named one "
        "would leave production untouched"
    )
    assert recreate_kwargs["allow_dropping_the_connection_url_database"] is True, (
        "this is the ONE caller allowed past the same-name guard, and it must say so"
    )
    assert restore_kwargs["single_transaction"] is True, (
        "a mid-replay failure must roll the target back to empty rather than leaving "
        "production half-clobbered"
    )


def test_bl01_the_restore_gives_the_cli_tools_their_own_view_of_the_server(
    tmp_path, monkeypatch
) -> None:
    """The rollback's `psql` and `pg_restore` must parse the URL from THEIR
    side of the connection, not this process's.

    CI regression (Unit tests job 100584596368, and main's own run on
    cbe0014): the restore seam did not accept `command_database_url` at all,
    so it handed `pg_restore` the HOST-reachable URL while running it inside
    the container:

        pg_restore: error: connection to server at "localhost", port 32803
        failed: Connection refused

    `run_postgres_restore` raised, `_rollback` went to `_halt`, and the run
    reported HALTED_RESTORE_FAILED -- BL-01's own symptom, reproduced by
    BL-01's own fix, and the reason its proof test could not execute.

    `default_backup` has always honoured this split; the restore path never
    did, even though `__main__`'s own `_PG_CLIENT_EXECUTABLES` doc names
    "``pg_restore`` again on the rollback path" as one of the four commands
    that has to be resolved.
    """
    recreate_kwargs: dict[str, object] = {}
    restore_kwargs: dict[str, object] = {}

    def _fake_create_fresh(**kwargs):  # type: ignore[no-untyped-def]
        recreate_kwargs.update(kwargs)
        return "postgresql://civiccast:pw@localhost:5432/civiccast"

    def _fake_restore(artifact, url, **kwargs):  # type: ignore[no-untyped-def]
        restore_kwargs.update(kwargs)
        restore_kwargs["url"] = url

    monkeypatch.setattr("civiccast.dr.backup.create_fresh_postgres_database", _fake_create_fresh)
    monkeypatch.setattr(seams_module, "run_postgres_restore", _fake_restore)

    ref, _manifest = _write_backup(tmp_path)
    in_container = "postgresql://civiccast:pw@localhost:5432/civiccast"
    seams_module.default_restore_backup(
        _restore_context(tmp_path),
        pg_restore_command=["docker", "exec", "-i", "c1", "pg_restore"],
        psql_command=["docker", "exec", "-i", "c1", "psql"],
        command_database_url=in_container,
    )(ref)

    assert recreate_kwargs["database_url"] == in_container, (
        "psql runs inside the container, so it must parse the container's own view of "
        "the server -- not this process's host-mapped port"
    )
    assert restore_kwargs["url"] == in_container
    assert recreate_kwargs["psql_command"] == ["docker", "exec", "-i", "c1", "psql"], (
        "and it must use the RESOLVED psql, never dr/backup.py's bare-name PATH fallback"
    )
    # The database NAME is derived from the same URL the tools address, so the
    # same-name guard in create_fresh_postgres_database fires on the value it
    # is actually about.
    assert recreate_kwargs["database_name"] == "civiccast"


def test_bl01_without_a_command_url_the_restore_uses_the_context_url_unchanged(
    tmp_path, monkeypatch
) -> None:
    """The production shape: one reachable Postgres, no container
    indirection, `command_database_url=None`. Behaviour must be exactly what
    it was before the split was threaded through."""
    recreate_kwargs: dict[str, object] = {}
    monkeypatch.setattr(
        "civiccast.dr.backup.create_fresh_postgres_database",
        lambda **kwargs: (
            recreate_kwargs.update(kwargs) or "postgresql://civiccast:pw@127.0.0.1:5432/civiccast"
        ),
    )
    monkeypatch.setattr(seams_module, "run_postgres_restore", lambda *a, **k: None)

    ref, _manifest = _write_backup(tmp_path)
    context = _restore_context(tmp_path)
    seams_module.default_restore_backup(context)(ref)

    assert recreate_kwargs["database_url"] == context.database_url


def test_bl01_the_production_bundle_threads_both_tool_arguments_to_the_restore(
    tmp_path, monkeypatch
) -> None:
    """`build_default_seams` is where both defects actually lived.

    It threaded `command_database_url` and `psql_command` into
    `default_backup` and neither into `default_restore_backup` -- so the
    rollback got a host URL for an in-container tool (the CI failure) AND
    fell back to a bare `psql` resolved through PATH. The installer writes no
    PATH entry and these ship only inside the staged native-server-binaries
    pack, so on a real Windows station that second one is a filename-less
    WinError 2 on the path that runs when an upgrade is already going wrong.
    """
    recreate_kwargs: dict[str, object] = {}
    restore_kwargs: dict[str, object] = {}

    def _fake_create_fresh(**kwargs):  # type: ignore[no-untyped-def]
        recreate_kwargs.update(kwargs)
        return "postgresql://civiccast:pw@localhost:5432/civiccast"

    def _fake_restore(artifact, url, **kwargs):  # type: ignore[no-untyped-def]
        restore_kwargs.update(kwargs)
        restore_kwargs["url"] = url

    monkeypatch.setattr("civiccast.dr.backup.create_fresh_postgres_database", _fake_create_fresh)
    monkeypatch.setattr(seams_module, "run_postgres_restore", _fake_restore)

    runtime = tmp_path / "install" / "runtime"
    runtime.mkdir(parents=True)
    context = _restore_context(tmp_path)
    in_container = "postgresql://civiccast:pw@localhost:5432/civiccast"
    bundle = seams_module.build_default_seams(
        context,
        payload_source=str(runtime),
        drain_and_verify_quiescence=lambda: True,
        health_gate=lambda: True,
        stop_service=lambda: None,
        pg_restore_command=[r"C:\packs\bin\pg_restore.exe"],
        psql_command=[r"C:\packs\bin\psql.exe"],
        command_database_url=in_container,
    )

    ref, _manifest = _write_backup(tmp_path)
    bundle.restore_backup(ref)

    assert recreate_kwargs["psql_command"] == [r"C:\packs\bin\psql.exe"]
    assert restore_kwargs["pg_restore_command"] == [r"C:\packs\bin\pg_restore.exe"]
    assert recreate_kwargs["database_url"] == in_container
    assert restore_kwargs["url"] == in_container


def test_bl01_a_tampered_backup_is_refused_before_the_live_database_is_dropped(
    tmp_path, monkeypatch
) -> None:
    """<installer-path-audit MA-09> ``BackupRef.verified`` was
    ``bool(manifest.integrity)`` -- a non-emptiness check -- and no file's
    bytes were ever re-hashed anywhere in the product. A dump truncated AFTER
    the manifest was written passed ``verified=True``.

    Refusing here, BEFORE the drop, is the load-bearing part: an unusable
    backup must never be the reason a live database is destroyed.
    """
    dropped: list[str] = []
    monkeypatch.setattr(
        "civiccast.dr.backup.create_fresh_postgres_database",
        lambda **kwargs: dropped.append("dropped") or "url",
    )
    monkeypatch.setattr(
        seams_module, "run_postgres_restore", lambda *a, **k: dropped.append("restored")
    )

    ref, _manifest = _write_backup(tmp_path)
    # Truncate the artifact AFTER the manifest recorded its hash.
    (tmp_path / "backups" / "pre-1.1" / "database.pgdump").write_bytes(b"PGDMP")

    with pytest.raises(RuntimeError, match="refusing to drop the live database"):
        seams_module.default_restore_backup(_restore_context(tmp_path))(ref)
    assert dropped == [], "nothing may be dropped or restored over a tampered backup"


def test_bl01_a_missing_artifact_is_refused_before_the_live_database_is_dropped(
    tmp_path, monkeypatch
) -> None:
    dropped: list[str] = []
    monkeypatch.setattr(
        "civiccast.dr.backup.create_fresh_postgres_database",
        lambda **kwargs: dropped.append("dropped") or "url",
    )

    ref, _manifest = _write_backup(tmp_path)
    (tmp_path / "backups" / "pre-1.1" / "database.pgdump").unlink()

    with pytest.raises(RuntimeError, match="does not exist"):
        seams_module.default_restore_backup(_restore_context(tmp_path))(ref)
    assert dropped == []


def test_ma01_the_flat_adapter_marks_the_run_filesystem_rollback_incapable(
    tmp_path,
) -> None:
    """<installer-path-audit MA-01> The adapter's own docstring claimed it
    "cannot silently turn into a general no-op" because it refuses any target
    other than the verified flat runtime -- but that refusal compares the
    argument against a value the SAME adapter produced, so it can never fire
    on the rollback path. Saying so in the bundle is what lets the journal and
    the recovery document stop claiming a revert that did not happen.
    """
    runtime = tmp_path / "install" / "runtime"
    runtime.mkdir(parents=True)
    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )
    base = UpgradeSeams(
        acquire_interlock=lambda: None,
        release_interlock=lambda: None,
        drain_and_verify_quiescence=lambda: True,
        backup=lambda backup_dir: BackupRef(
            backup_id="b",
            backup_dir=backup_dir,
            manifest_hash="h",
            db_artifact="database.pgdump",
            verified=True,
            restore_drill_ok=True,
        ),
        restore_backup=lambda backup: None,
        lay_tree=lambda version: "unused",
        flip_junction=lambda target: None,
        read_junction=lambda: None,
        migrate=lambda: None,
        health_gate=lambda: True,
        schema_revision=lambda: "head",
        stop_service=lambda: None,
    )
    assert base.filesystem_rollback is True, "the generic bundle CAN revert a tree"
    adapted = seams_module.adapt_flat_installer_layout(base, context)
    assert adapted.filesystem_rollback is False
