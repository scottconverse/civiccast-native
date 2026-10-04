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


@pytest.fixture
def flat_recovery_case(tmp_path, monkeypatch):
    from civiccast.native.upgrade import flat_recovery as recovery

    # Pure filesystem/order proof, not Windows ACL/SCM/database integration.
    monkeypatch.setattr(recovery, "_harden_state_root_acl", lambda path: None)
    install = tmp_path / "install"
    (install / "runtime").mkdir(parents=True)
    payload = install / "runtime" / "product.py"
    payload.write_bytes(b"previous application")
    state = tmp_path / "recovery"
    events = []
    revision = ["old-head"]
    backup = BackupRef(
        backup_id="owned-backup",
        backup_dir=str(state / "database"),
        manifest_hash="a" * 64,
        db_artifact="database.dump",
        verified=True,
        restore_drill_ok=True,
    )

    def restore_database(ref):
        events.append("database")
        assert payload.read_bytes() == b"replacement application"
        revision[0] = "old-head"

    def verify_previous(version, schema):
        events.append("verify")
        return (
            version == "1"
            and schema == "old-head"
            and payload.read_bytes() == b"previous application"
        )

    seams = recovery.FlatRecoverySeams(
        expected_install_root=install,
        expected_state_root=state,
        assert_owner=lambda owner: None,
        contain=lambda: events.append("contain"),
        capture_registration=lambda: {
            "install_root": str(install),
            "start": "auto",
            "running": True,
        },
        restore_registration=lambda registration: events.append("registration"),
        capture_config=lambda path: path.mkdir(),
        restore_config=lambda path: events.append("config"),
        backup=lambda directory: backup,
        verify_backup=lambda ref: None,
        restore_database=restore_database,
        schema_revision=lambda: revision[0],
        verify_previous_identity=verify_previous,
        reactivate=lambda registration: events.append("reactivate"),
    )
    return recovery, install, payload, state, seams, events, revision


def test_flat_outer_owner_restores_database_before_previous_application(flat_recovery_case):
    recovery, install, payload, state, seams, events, revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    payload.write_bytes(b"replacement application")
    recovery.mark_database_mutation(state, "owned-installer", seams)
    revision[0] = "new-head"
    result = recovery.recover(state, "owned-installer", seams)
    assert result.phase == "restored"
    assert payload.read_bytes() == b"previous application"
    assert events.index("database") < events.index("verify") < events.index("reactivate")
    assert (
        install.parent / ".install.failed-owned-installer" / "runtime" / "product.py"
    ).read_bytes() == b"replacement application"


def test_flat_outer_owner_rejects_owner_path_escape_before_containment(flat_recovery_case):
    recovery, install, _payload, state, seams, events, _revision = flat_recovery_case
    with pytest.raises(recovery.FlatRecoveryError, match="owner"):
        recovery.prepare(
            install_root=install,
            state_root=state,
            owner="../other",
            old_version="1",
            new_version="2",
            seams=seams,
        )
    assert not events
    assert not state.exists()


def test_flat_outer_owner_never_reactivates_after_failed_database_restore(flat_recovery_case):
    from dataclasses import replace

    recovery, install, payload, state, seams, events, revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    payload.write_bytes(b"replacement application")
    recovery.mark_database_mutation(state, "owned-installer", seams)
    revision[0] = "new-head"

    def fail(ref):
        raise RuntimeError("database restore failed")

    with pytest.raises(RuntimeError, match="database restore failed"):
        recovery.recover(state, "owned-installer", replace(seams, restore_database=fail))
    assert recovery.load(state, "owned-installer", seams).phase == "halted"
    assert payload.read_bytes() == b"replacement application"
    assert "reactivate" not in events


def test_flat_outer_owner_contains_even_when_terminal_journal_cannot_persist(
    flat_recovery_case, monkeypatch
):
    recovery, install, payload, state, seams, events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    payload.write_bytes(b"replacement application")
    persist = recovery._persist

    def failing_persist(journal):
        if journal.phase in {"restored", "halted"}:
            raise OSError("terminal journal unavailable")
        persist(journal)

    monkeypatch.setattr(recovery, "_persist", failing_persist)
    with pytest.raises(OSError, match="terminal journal unavailable"):
        recovery.recover(state, "owned-installer", seams)
    assert "reactivate" in events
    assert events[-1] == "contain", "failed journal persistence skipped writer containment"


def test_flat_outer_owner_rejects_tampered_sibling_before_containment(flat_recovery_case):
    recovery, install, _payload, state, seams, events, _revision = flat_recovery_case
    journal = recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="1",
        seams=seams,
    )
    assert journal.backup is not None  # Same-version repair is not DB-backup NOOP.
    recovery.mark_replacement(state, "owned-installer", seams)
    journal = recovery.load(state, "owned-installer", seams)
    journal.failed_tree = str(install.parent / "unrelated-application")
    recovery._persist(journal)
    before = list(events)
    with pytest.raises(recovery.FlatRecoveryError, match="owner"):
        recovery.recover(state, "owned-installer", seams)
    assert events == before


def test_flat_outer_owner_refuses_reparse_journal_before_read(flat_recovery_case, monkeypatch):
    import stat
    from pathlib import Path
    from types import SimpleNamespace

    recovery, install, _payload, state, seams, _events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    journal_path = state / "flat-install-recovery.json"
    original = Path.lstat

    def reparse_stat(path, *args, **kwargs):
        if path == journal_path:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse_stat)
    with pytest.raises(recovery.FlatRecoveryError, match="reparse"):
        recovery.load(state, "owned-installer", seams)


def test_flat_outer_owner_checks_snapshot_before_replacement(flat_recovery_case):
    recovery, install, _payload, state, seams, _events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    (state / "previous-application" / "runtime" / "product.py").write_bytes(
        b"damaged recovery point"
    )
    with pytest.raises(recovery.FlatRecoveryError, match="snapshot"):
        recovery.mark_replacement(state, "owned-installer", seams)
    assert recovery.load(state, "owned-installer", seams).phase == "prepared"


def test_flat_outer_owner_recovers_absent_application_after_interrupted_replacement(
    flat_recovery_case,
):
    recovery, install, payload, state, seams, events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    retained = install.with_name("retained-interrupted-application")
    install.rename(retained)
    assert not install.exists()
    restored = recovery.recover(state, "owned-installer", seams)
    assert restored.phase == "restored"
    assert payload.read_bytes() == b"previous application"
    assert (retained / "runtime/product.py").read_bytes() == b"previous application"
    assert events[-1] == "reactivate"


def test_flat_outer_owner_binds_install_root_independently_of_journal(flat_recovery_case):
    recovery, install, _payload, state, seams, events, _revision = flat_recovery_case
    journal = recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    journal.install_root = str(install.parent / "different-install")
    recovery._persist(journal)
    before = list(events)
    with pytest.raises(recovery.FlatRecoveryError, match="bound"):
        recovery.load(state, "owned-installer", seams)
    assert events == before


def test_flat_outer_owner_binds_registration_root_before_containment(flat_recovery_case):
    recovery, install, _payload, state, seams, events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    journal = recovery.load(state, "owned-installer", seams)
    journal.registration["install_root"] = str(install.with_name("foreign-install"))
    recovery._persist(journal)
    events.clear()
    with pytest.raises(recovery.FlatRecoveryError, match="registration root"):
        recovery.recover(state, "owned-installer", seams)
    assert events == []


def test_flat_installer_parent_is_observed_not_claimed(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from civiccast.native.upgrade import flat_recovery_entry as entry

    expected = tmp_path / "setup.exe"
    other = tmp_path / "other.exe"
    parent = SimpleNamespace(
        pid=123, create_time=lambda: 10.0, exe=lambda: str(expected), oneshot=nullcontext
    )
    monkeypatch.setattr(entry.os, "getppid", lambda: 123)
    monkeypatch.setattr(entry.psutil, "Process", lambda pid: parent)
    identity = entry.observe_installer_parent(expected)
    entry.require_current_installer_parent(identity)
    with pytest.raises(entry.FlatRecoveryError, match="expected installer"):
        entry.observe_installer_parent(other)
    # Same PID and pathname are not enough after process recycling.
    parent.create_time = lambda: 11.0
    assert entry.installer_parent_alive(identity) is False
    with pytest.raises(entry.FlatRecoveryError, match="admitted"):
        entry.require_current_installer_parent(identity)


def test_flat_installer_parent_unreadable_is_not_reclaimable(tmp_path, monkeypatch):
    from civiccast.native.upgrade import flat_recovery_entry as entry

    identity = entry.InstallerParent(pid=123, birth=10.0, executable=str(tmp_path / "setup.exe"))

    def denied(pid):
        raise entry.psutil.AccessDenied(pid)

    monkeypatch.setattr(entry.psutil, "Process", denied)
    assert entry.installer_parent_alive(identity) is None

    def gone(pid):
        raise entry.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(entry.psutil, "Process", gone)
    assert entry.installer_parent_alive(identity) is False


def test_flat_installer_parent_matches_actual_process_incarnation():
    """Exercise OS observation, without registry/service or installer mutations."""
    from pathlib import Path

    from civiccast.native.upgrade import flat_recovery_entry as entry

    process = entry.psutil.Process(entry.os.getppid())
    expected = Path(process.exe())
    identity = entry.observe_installer_parent(expected)
    assert identity.pid == process.pid
    assert identity.birth == process.create_time()
    assert entry.installer_parent_alive(identity) is True
    entry.require_current_installer_parent(identity)


def test_flat_parent_interlock_uses_actual_os_incarnation_before_write(monkeypatch):
    from pathlib import Path

    from civiccast.native.models import MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    process = entry.psutil.Process(entry.os.getppid())
    parent = entry.observe_installer_parent(Path(process.exe()))
    calls = []

    def take(owner, *, owner_pid):
        calls.append((owner, owner_pid))
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=3,
            owner_run_id=owner,
            owner_pid=owner_pid,
            taken_utc="synthetic",
            released_utc=None,
        )

    monkeypatch.setattr(entry, "take_interlock", take)
    record = entry.take_installer_interlock(parent, "installer-owned")
    assert calls == [("installer-owned", process.pid)]
    assert record.owner_pid == process.pid and record.generation == 3
    calls.clear()
    recycled = parent.model_copy(update={"birth": parent.birth + 1})
    with pytest.raises(entry.FlatRecoveryError, match="admitted"):
        entry.take_installer_interlock(recycled, "installer-owned")
    assert calls == []


def test_flat_admission_serializes_intent_before_physical_lease(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from pathlib import Path

    from civiccast.native.models import InterlockRead, MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    parent = entry.observe_installer_parent(Path(entry.psutil.Process(entry.os.getppid()).exe()))
    root, install = tmp_path / "admission", tmp_path / "installation"
    events = []
    current = InterlockRead(status="free", record=None, detail="synthetic")

    @contextmanager
    def mutex():
        events.append("locked")
        try:
            yield
        finally:
            events.append("unlocked")

    def take(observed, owner):
        nonlocal current
        assert (root / "installer-admission.json").is_file(), (
            "intent must be durable before D7 write"
        )
        intent = entry.load_installer_admission(
            expected_install_root=install,
            expected_admission_root=root,
            expected_state_root=root / "recovery-owner",
        )
        assert intent.phase == "intent" and intent.parent == observed
        assert events == ["locked"]  # durable intent precedes physical mutation under the mutex
        events.append("taken")
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner,
            owner_pid=observed.pid,
            taken_utc="synthetic",
        )
        current = InterlockRead(status="held", record=record, detail="synthetic")
        return record

    monkeypatch.setattr(entry, "installer_admission_mutex", mutex)
    monkeypatch.setattr(entry, "read_interlock", lambda: current)
    monkeypatch.setattr(entry, "take_installer_interlock", take)
    admission = entry.admit_installer(
        parent=parent,
        owner="owner",
        expected_install_root=install,
        admission_root=root,
    )
    assert admission.phase == "held" and admission.generation == 1
    assert events == ["locked", "taken", "unlocked"]
    with pytest.raises(entry.FlatRecoveryError, match="unsettled"):
        entry.admit_installer(
            parent=parent,
            owner="other",
            expected_install_root=install,
            admission_root=root,
        )
    assert events.count("taken") == 1  # another installer may not replace the protected owner


def test_flat_admission_durable_parent_is_separate_from_uncaptured_recovery(tmp_path):
    from pathlib import Path

    from civiccast.native.upgrade import flat_recovery_entry as entry

    parent = entry.observe_installer_parent(Path(entry.psutil.Process(entry.os.getppid()).exe()))
    root = tmp_path / "admission"
    install = tmp_path / "installation"
    recovery = root / "recovery-owner"
    admission = entry.InstallerAdmission(
        parent=parent,
        owner="owner",
        generation=1,
        install_root=str(install),
        admission_root=str(root),
        state_root=str(recovery),
        phase="intent",
    )
    entry.persist_installer_admission(admission)
    loaded = entry.load_installer_admission(
        expected_install_root=install,
        expected_admission_root=root,
        expected_state_root=recovery,
    )
    assert loaded == admission
    assert not recovery.exists()  # core.prepare owns first creation, not admission/executor staging
    with pytest.raises(entry.FlatRecoveryError, match="root binding"):
        entry.load_installer_admission(
            expected_install_root=tmp_path / "foreign",
            expected_admission_root=root,
            expected_state_root=recovery,
        )
    with pytest.raises(entry.FlatRecoveryError, match="distinct"):
        entry.persist_installer_admission(admission.model_copy(update={"state_root": str(root)}))


@pytest.mark.parametrize(
    "field,value",
    [("owner_run_id", "other"), ("generation", 3), ("owner_pid", 456), ("state", "released")],
)
def test_flat_borrowed_interlock_rechecks_exact_lease(tmp_path, monkeypatch, field, value):
    from civiccast.native.models import InterlockRead, MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    parent = entry.InstallerParent(pid=123, birth=10.0, executable=str(tmp_path / "setup.exe"))
    monkeypatch.setattr(entry, "require_current_installer_parent", lambda actual: None)
    record = MaintenanceRecord(
        v=1, state="held", generation=2, owner_run_id="installer", taken_utc="now", owner_pid=123
    )

    def read():
        return InterlockRead(status="held", record=record, detail="test")

    def forbidden():
        pytest.fail("borrowed D3 must not take or release the physical lease")

    seams = UpgradeSeams(
        acquire_interlock=forbidden,
        release_interlock=forbidden,
        drain_and_verify_quiescence=lambda: True,
        backup=lambda version: None,
        restore_backup=lambda backup: None,
        lay_tree=lambda version: "tree",
        flip_junction=lambda tree: None,
        read_junction=lambda: "tree",
        migrate=lambda: None,
        health_gate=lambda: True,
        schema_revision=lambda: "head",
        stop_service=lambda: None,
    )
    borrowed = entry.borrow_installer_interlock(
        seams, parent=parent, owner="installer", generation=2, read=read
    )
    borrowed.acquire_interlock()
    borrowed.release_interlock()
    setattr(record, field, value)
    with pytest.raises(entry.FlatRecoveryError, match="lease identity"):
        borrowed.acquire_interlock()
    with pytest.raises(entry.FlatRecoveryError, match="lease identity"):
        borrowed.release_interlock()


@pytest.mark.parametrize("failure", [False, True])
def test_flat_restore_privilege_is_scoped_and_restored(monkeypatch, failure):
    import sys
    from types import SimpleNamespace

    from civiccast.native.upgrade import flat_recovery_entry as entry

    events = []
    original = [("restore-luid", 0)]
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            GetCurrentProcess=lambda: "process",
            SetLastError=lambda value: None,
            GetLastError=lambda: 0,
            CloseHandle=lambda handle: events.append(("close", handle)),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(
            TOKEN_ADJUST_PRIVILEGES=32,
            TOKEN_QUERY=8,
            SE_PRIVILEGE_ENABLED=2,
        ),
    )

    def adjust(token, disable, privileges):
        events.append(("adjust", token, disable, privileges))
        return original

    monkeypatch.setitem(
        sys.modules,
        "win32security",
        SimpleNamespace(
            OpenProcessToken=lambda process, access: "token",
            LookupPrivilegeValue=lambda system, name: "restore-luid",
            AdjustTokenPrivileges=adjust,
        ),
    )
    try:
        with entry.restore_security_privilege():
            events.append(("body",))
            if failure:
                raise ValueError("synthetic-body")
    except ValueError:
        assert failure
    assert events == [
        ("adjust", "token", False, [("restore-luid", 2)]),
        ("body",),
        ("adjust", "token", False, original),
        ("close", "token"),
    ]


def test_flat_restore_privilege_missing_refuses_before_body(monkeypatch):
    import sys
    from types import SimpleNamespace

    from civiccast.native.upgrade import flat_recovery_entry as entry

    events = []
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            GetCurrentProcess=lambda: "process",
            GetLastError=lambda: 1300,
            SetLastError=lambda value: None,
            CloseHandle=lambda token: events.append("closed"),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(
            TOKEN_ADJUST_PRIVILEGES=32,
            TOKEN_QUERY=8,
            SE_PRIVILEGE_ENABLED=2,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32security",
        SimpleNamespace(
            OpenProcessToken=lambda *args: "token",
            LookupPrivilegeValue=lambda *args: "restore-luid",
            AdjustTokenPrivileges=lambda *args: events.append("adjust") or [],
        ),
    )
    with (
        pytest.raises(entry.FlatRecoveryError, match="privilege"),
        entry.restore_security_privilege(),
    ):
        events.append("body")
    assert events == ["adjust", "adjust", "closed"]


@pytest.mark.parametrize(
    "mode", ["absent", "nonzero", "timeout", "bootstrap", "overlap", "collision"]
)
def test_flat_executor_requires_verified_python_before_old_install_touch(
    tmp_path, monkeypatch, mode
):
    import hashlib
    from pathlib import Path
    from types import SimpleNamespace

    from civiccast.native.upgrade import flat_recovery_entry as entry

    bootstrap = tmp_path / "incoming.exe"
    bootstrap.write_bytes(b"synthetic verified bootstrap boundary")
    app = tmp_path / (
        "CivicCast Native.exe" if mode == "collision" else "native-app-payload.ccpack"
    )
    server = tmp_path / "native-server-binaries.ccpack"
    app.write_bytes(b"synthetic app")
    server.write_bytes(b"synthetic server")
    state = tmp_path / "protected-state"
    state.mkdir()
    monkeypatch.setattr(entry, "_harden_state_root_acl", lambda path: None)
    monkeypatch.setenv("PGSERVICE", "synthetic-foreign-service")
    monkeypatch.setenv("pgOptions", "synthetic-foreign-options")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert Path(args[0]).read_bytes() == bootstrap.read_bytes()
        assert kwargs["creationflags"] == (
            entry.subprocess.CREATE_NO_WINDOW if entry.os.name == "nt" else 0
        )
        assert kwargs["stdout"] == kwargs["stderr"] == entry.subprocess.DEVNULL
        assert not any(
            name.upper().startswith("PG") for name in kwargs.get("env", entry.os.environ)
        )
        assert entry.os.environ["PGSERVICE"] == "synthetic-foreign-service"
        if mode == "timeout":
            raise entry.subprocess.TimeoutExpired(args, 600)
        destination = Path(args[args.index("--destination") + 1])
        destination.mkdir(exist_ok=True)
        return SimpleNamespace(returncode=1 if mode == "nonzero" else 0)

    monkeypatch.setattr(entry.subprocess, "run", run)
    expected = {
        "absent": "interpreter",
        "nonzero": "signed pack verification failed",
        "timeout": "did not complete",
        "bootstrap": "bootstrap binding",
        "overlap": "overlaps",
        "collision": "interpreter",
    }[mode]
    with pytest.raises(entry.FlatRecoveryError, match=expected):
        entry.stage_recovery_executor(
            bootstrap=bootstrap,
            expected_bootstrap_sha256=(
                "0" * 64
                if mode == "bootstrap"
                else hashlib.sha256(bootstrap.read_bytes()).hexdigest()
            ),
            app_pack=app,
            server_pack=server,
            state_root=state,
            expected_install_root=state if mode == "overlap" else tmp_path / "old-install",
            owner="installer-owned",
        )
    assert (
        len(calls)
        == {"absent": 2, "nonzero": 1, "timeout": 1, "bootstrap": 0, "overlap": 0, "collision": 2}[
            mode
        ]
    )


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows file DACL contract")
def test_flat_outer_owner_preserves_original_file_dacl(flat_recovery_case):
    import win32security

    from civiccast.native.upgrade.journal import _current_process_sid_sddl

    recovery, install, payload, state, seams, _events, _revision = flat_recovery_case
    original = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;;GA;;;{_current_process_sid_sddl()})", win32security.SDDL_REVISION_1
    )
    flags = win32security.DACL_SECURITY_INFORMATION
    win32security.SetFileSecurity(
        str(payload), flags | win32security.PROTECTED_DACL_SECURITY_INFORMATION, original
    )

    def descriptor():
        return win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            win32security.GetFileSecurity(str(payload), flags), win32security.SDDL_REVISION_1, flags
        )

    before = descriptor()
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    payload.write_bytes(b"replacement application")
    recovery.recover(state, "owned-installer", seams)
    assert descriptor() == before, "restored bytes inherited a different application DACL"


@pytest.mark.parametrize(
    "fault", [None, "directory", "executable", "birth", "malformed", "process-directory"]
)
def test_flat_verification_postmaster_is_exact_owned_incarnation(tmp_path, monkeypatch, fault):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from civiccast.native.upgrade import flat_recovery_entry as entry

    data = tmp_path / "scratch-pgdata"
    data.mkdir()
    executable = tmp_path / "old-tools" / "postgres.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"synthetic admitted tool boundary")
    (data / "postmaster.pid").write_text(
        "malformed"
        if fault == "malformed"
        else f"123\n{tmp_path if fault == 'directory' else data}\n101\n",
        encoding="utf-8",
    )
    process = SimpleNamespace(
        pid=123,
        oneshot=lambda: nullcontext(),
        create_time=lambda: 99.0 if fault == "birth" else 101.5,
        exe=lambda: str(tmp_path / "foreign.exe" if fault == "executable" else executable),
        cmdline=lambda: [
            str(executable),
            "-D",
            str(tmp_path if fault == "process-directory" else data),
        ],
    )
    monkeypatch.setattr(entry.psutil, "Process", lambda pid: process)
    if fault is None:
        identity = entry.verification_postmaster(data, executable, started_after=100.0)
        assert identity.pid == 123 and identity.birth == 101.5
        assert identity.executable == str(executable)
    else:
        with pytest.raises(entry.FlatRecoveryError):
            entry.verification_postmaster(data, executable, started_after=100.0)


@pytest.mark.parametrize("body_failure", [False, True])
def test_flat_verification_target_reaps_only_bound_private_cluster(
    tmp_path, monkeypatch, body_failure
):
    from types import SimpleNamespace

    from civiccast.native import pg_ctl_exec, pgdata_acl
    from civiccast.native.upgrade import flat_recovery_entry as entry

    tools = tmp_path / "retained-old-tools"
    tools.mkdir()
    suffix = ".exe" if entry.os.name == "nt" else ""
    for name in ("initdb", "pg_ctl", "postgres"):
        (tools / f"{name}{suffix}").write_bytes(b"synthetic independently admitted tool")
    root = tmp_path / "private-verifier"
    events = []
    identity = entry.InstallerParent(
        pid=123, birth=101, executable=str(tools / f"postgres{suffix}")
    )

    def command(argv, **kwargs):
        assert not any(name.upper().startswith("PG") for name in kwargs["env"])
        assert kwargs["timeout_seconds"] in (120.0, 75.0, 45.0)
        events.append(argv)
        if "start" in argv:
            (root / "pgdata" / "postmaster.pid").write_text("synthetic-bound-pidfile")
        if "stop" in argv:
            (root / "pgdata" / "postmaster.pid").unlink()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(pg_ctl_exec, "run_captured_argv", command)
    monkeypatch.setattr(pgdata_acl, "normalize_pgdata_acl", lambda path: None)
    monkeypatch.setattr(entry, "verification_postmaster", lambda *args, **kwargs: identity)
    monkeypatch.setattr(entry, "installer_parent_alive", lambda observed: False)
    monkeypatch.setenv("PGSERVICE", "synthetic-unrelated-service")
    try:
        with entry.disposable_verification_target(
            old_pg_bin=tools, scratch_root=root, expected_install_root=tmp_path / "installation"
        ) as target:
            assert target.expected_pgdata == root / "pgdata"
            assert "127.0.0.1" in target.database_url
            assert "civiccast_verifier" in target.database_url
            assert "synthetic-unrelated-service" not in target.database_url
            if body_failure:
                raise RuntimeError("synthetic verifier body failure")
    except RuntimeError as exc:
        assert body_failure and str(exc) == "synthetic verifier body failure"
    assert len(events) == 3 and events[-1][1] == "stop", (
        "owned verifier must stop on every body exit"
    )
    assert events[-1][events[-1].index("-D") + 1] == str(root / "pgdata")
    assert not (root / "pgdata" / "postmaster.pid").exists()
    assert entry.os.environ["PGSERVICE"] == "synthetic-unrelated-service"


def test_flat_previous_tools_survive_replaceable_install_tree(tmp_path):
    from civiccast.native.upgrade import flat_recovery_entry as entry

    install = tmp_path / "install"
    distribution = install / "server" / "pgsql"
    tools = distribution / "bin"
    tools.mkdir(parents=True)
    for name in (
        "initdb.exe",
        "pg_ctl.exe",
        "postgres.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "psql.exe",
    ):
        (tools / name).write_bytes(name.encode())
    (distribution / "share").mkdir()
    (distribution / "share" / "postgres.bki").write_bytes(b"old support data")
    retained = entry.retain_previous_postgres_tools(
        pg_bin=tools, expected_install_root=install, destination=tmp_path / "retained"
    )
    install.rename(tmp_path / "installer-replaced-tree")
    assert (retained / "postgres.exe").read_bytes() == b"postgres.exe"
    assert (retained.parent / "share" / "postgres.bki").read_bytes() == b"old support data"


def test_flat_previous_tool_retention_refuses_source_change(tmp_path, monkeypatch):
    from civiccast.native.upgrade import flat_recovery_entry as entry

    install = tmp_path / "install"
    tools = install / "server" / "pgsql" / "bin"
    tools.mkdir(parents=True)
    for name in (
        "initdb.exe",
        "pg_ctl.exe",
        "postgres.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "psql.exe",
    ):
        (tools / name).write_bytes(name.encode())
    copy = entry.shutil.copytree

    def mutate_after_copy(*args, **kwargs):
        result = copy(*args, **kwargs)
        (tools / "postgres.exe").write_bytes(b"changed old executable")
        return result

    monkeypatch.setattr(entry.shutil, "copytree", mutate_after_copy)
    with pytest.raises(entry.FlatRecoveryError, match="byte verification"):
        entry.retain_previous_postgres_tools(
            pg_bin=tools, expected_install_root=install, destination=tmp_path / "retained"
        )


def test_flat_previous_tool_retention_never_copies_pgdata(tmp_path):
    from civiccast.native.upgrade import flat_recovery_entry as entry

    install = tmp_path / "install"
    tools = install / "server" / "pgsql" / "bin"
    tools.mkdir(parents=True)
    for name in (
        "initdb.exe",
        "pg_ctl.exe",
        "postgres.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "psql.exe",
    ):
        (tools / name).write_bytes(name.encode())
    (tools.parent / "PG_VERSION").write_bytes(b"17")
    target = tmp_path / "retained"
    with pytest.raises(entry.FlatRecoveryError, match="not an old-tool distribution"):
        entry.retain_previous_postgres_tools(
            pg_bin=tools, expected_install_root=install, destination=target
        )
    assert not target.exists()


@pytest.mark.parametrize("terminal", [False, True])
def test_flat_admission_release_requires_durable_terminal_journal(
    flat_recovery_case, monkeypatch, terminal
):
    from contextlib import nullcontext

    from civiccast.native.models import InterlockRead, MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    recovery, install, _payload, state, seams, _events, _revision = flat_recovery_case
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    if terminal:
        recovery.mark_replacement(state, "owned-installer", seams)
        recovery.commit(state, "owned-installer", seams)
    parent = entry.observe_installer_parent(
        entry.Path(entry.psutil.Process(entry.os.getppid()).exe())
    )
    admission = entry.InstallerAdmission(
        parent=parent,
        owner="owned-installer",
        generation=7,
        install_root=str(install),
        admission_root=str(state.parent / "admission"),
        state_root=str(state),
        phase="held",
    )
    record = MaintenanceRecord(
        v=1,
        state="held",
        generation=7,
        owner_run_id="owned-installer",
        owner_pid=parent.pid,
        taken_utc="synthetic",
    )
    events = []
    monkeypatch.setattr(entry, "installer_admission_mutex", nullcontext)
    monkeypatch.setattr(entry, "load_installer_admission", lambda **_: admission)
    monkeypatch.setattr(
        entry,
        "read_interlock",
        lambda: InterlockRead(status="held", record=record, detail="synthetic"),
    )
    monkeypatch.setattr(
        entry, "persist_installer_admission", lambda saved: events.append(saved.phase)
    )

    def release(**kwargs):
        assert kwargs == {"owner_run_id": "owned-installer"}
        assert events == ["committed"], "terminal admission must be durable before writer release"
        events.append("release")
        return record.model_copy(update={"state": "released"})

    monkeypatch.setattr(entry, "release_interlock", release)
    if terminal:
        settled = entry.settle_installer_admission(admission=admission, seams=seams)
        assert settled.phase == "committed" and events == ["committed", "release"]
    else:
        with pytest.raises(entry.FlatRecoveryError, match="durably terminal"):
            entry.settle_installer_admission(admission=admission, seams=seams)
        assert events == [], "nonterminal recovery must never release writers"


@pytest.mark.parametrize("alive", [True, None, False])
def test_flat_settled_admission_archive_requires_old_parent_absence(
    flat_recovery_case, tmp_path, monkeypatch, alive
):
    from contextlib import nullcontext
    from dataclasses import replace

    from civiccast.native.models import InterlockRead, MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    recovery, install, _payload, _state, seams, _events, _revision = flat_recovery_case
    root = tmp_path / "admission"
    root.mkdir()
    state = root / "recovery-owned-installer"
    seams = replace(seams, expected_state_root=state)
    recovery.prepare(
        install_root=install,
        state_root=state,
        owner="owned-installer",
        old_version="1",
        new_version="2",
        seams=seams,
    )
    recovery.mark_replacement(state, "owned-installer", seams)
    recovery.commit(state, "owned-installer", seams)
    parent = entry.observe_installer_parent(
        entry.Path(entry.psutil.Process(entry.os.getppid()).exe())
    )
    admission = entry.InstallerAdmission(
        parent=parent,
        owner="owned-installer",
        generation=7,
        install_root=str(install),
        admission_root=str(root),
        state_root=str(state),
        phase="committed",
    )
    entry.persist_installer_admission(admission)
    record = MaintenanceRecord(
        v=1,
        state="released",
        generation=7,
        owner_run_id="owned-installer",
        owner_pid=parent.pid,
        taken_utc="synthetic",
        released_utc="synthetic",
    )
    monkeypatch.setattr(entry, "installer_admission_mutex", nullcontext)
    monkeypatch.setattr(entry, "installer_parent_alive", lambda _: alive)
    monkeypatch.setattr(
        entry,
        "read_interlock",
        lambda: InterlockRead(status="free", record=record, detail="synthetic"),
    )
    active = root / "installer-admission.json"
    original = active.read_bytes()
    if alive is False:
        archived = entry.archive_settled_installer_admission(admission=admission, seams=seams)
        assert archived.read_bytes() == original and not active.exists()
        assert recovery.load(state, "owned-installer", seams).phase == "committed"
    else:
        with pytest.raises(entry.FlatRecoveryError, match="definitively settled"):
            entry.archive_settled_installer_admission(admission=admission, seams=seams)
        assert active.read_bytes() == original


@pytest.mark.parametrize(
    ("old_alive", "changed"),
    [
        (True, None),
        (None, None),
        (False, None),
        (False, "generation"),
        (False, "owner_pid"),
        (False, "owner_run_id"),
    ],
)
def test_flat_interrupted_adoption_retains_exact_original_lease(
    tmp_path, monkeypatch, old_alive, changed
):
    from contextlib import nullcontext

    from civiccast.native.models import InterlockRead, MaintenanceRecord
    from civiccast.native.upgrade import flat_recovery_entry as entry

    actor = entry.observe_installer_parent(
        entry.Path(entry.psutil.Process(entry.os.getppid()).exe())
    )
    old = actor.model_copy(update={"pid": actor.pid + 100000})
    root, install = tmp_path / "admission", tmp_path / "install"
    root.mkdir()
    state = root / "recovery-owner"
    previous = entry.InstallerAdmission(
        parent=old,
        owner="owner",
        generation=9,
        install_root=str(install),
        admission_root=str(root),
        state_root=str(state),
        phase="held",
    )
    active = root / "installer-admission.json"
    active.write_text(previous.model_dump_json(), encoding="utf-8")
    original = active.read_bytes()
    lease = MaintenanceRecord(
        v=1,
        state="held",
        generation=9,
        owner_run_id="owner",
        owner_pid=old.pid,
        taken_utc="synthetic",
    )
    if changed is not None:
        lease = lease.model_copy(update={changed: "foreign" if changed == "owner_run_id" else 99})
    real_alive = entry.installer_parent_alive
    monkeypatch.setattr(entry, "installer_admission_mutex", nullcontext)
    monkeypatch.setattr(
        entry,
        "installer_parent_alive",
        lambda parent: old_alive if parent == old else real_alive(parent),
    )
    monkeypatch.setattr(
        entry,
        "read_interlock",
        lambda: InterlockRead(status="held", record=lease, detail="synthetic"),
    )
    if old_alive is False and changed is None:
        adopted = entry.adopt_interrupted_installer(
            previous=previous,
            actor=actor,
            expected_install_root=install,
            expected_admission_root=root,
            expected_state_root=state,
        )
        assert adopted.parent == old and adopted.recovery_actor == actor
        assert adopted.owner == "owner" and adopted.generation == 9
        assert entry.read_interlock().record == lease, (
            "adoption must not rewrite the physical lease"
        )
        assert (
            entry.load_installer_admission(
                expected_install_root=install,
                expected_admission_root=root,
                expected_state_root=state,
            )
            == adopted
        )
    else:
        expected = "ownership changed" if old_alive is False else "definitively gone"
        with pytest.raises(entry.FlatRecoveryError, match=expected):
            entry.adopt_interrupted_installer(
                previous=previous,
                actor=actor,
                expected_install_root=install,
                expected_admission_root=root,
                expected_state_root=state,
            )
        assert active.read_bytes() == original
