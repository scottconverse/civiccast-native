# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Regression: D3 step 3's DB layer must not need ``psycopg2`` (chain K, K1).

Live-proven defect, real hardware R7, 2026-08-01 (request 0053b,
``upgrade-journal.json``)::

    interlock_acquired -- D7a maintenance interlock acquired
    writers_drained    -- writers drained; quiescence verified
    rolled_back        -- rolled back after failure (No module named 'psycopg2');
                          junction/tree reverted (no DB mutation)

The step that was ATTEMPTED when that fired is the one right after
``writers_drained``: D3 step 3, ``BACKUP_VERIFIED``
(:func:`civiccast.native.upgrade.orchestrator._drive_forward`). Its production
seam is :func:`civiccast.native.upgrade.seams.default_backup`, which runs the
WS2 full backup (already normalized -- ``civiccast/dr/backup.py`` line ~617)
and THEN the restore-drill spot check
:func:`civiccast.dr.restore_drill.run_postgres_restore_drill`, whose FIRST
statement is ``create_engine(verify_source_url)`` on the raw, driver-less
``postgresql://`` URL the installer persists to
``HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl``. SQLAlchemy resolves a
driver-less ``postgresql`` scheme to the **psycopg2** dialect and imports it at
ENGINE CONSTRUCTION -- and this product ships psycopg **v3** only (ADR 0008,
``psycopg[binary]>=3.2``; the built app-payload pack contains psycopg 3.3.4 +
psycopg_binary and no psycopg2 whatsoever).

``civiccast/db/url.py``'s docstring listed ``civiccast/dr/restore_drill.py`` as
"still out of scope ... operator/DR-drill only, not on the native
service/control-plane/installer path". That was wrong: D3 step 3 calls it on
every upgrade, before the mutation frontier. This module pins that it is on the
path AND that its DB layer resolves a shipped driver.

Import isolation: ``psycopg2`` is not installed in this venv either (see
``requirements-native-app.txt``), so the defect reproduces natively -- but these
tests install an explicit import block anyway so the proof does not silently
become a no-op on a developer machine that happens to have psycopg2 present.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from importlib.abc import MetaPathFinder
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from civiccast.dr import restore_drill
from civiccast.dr.models import BackupManifest
from civiccast.native.upgrade import seams as upgrade_seams
from civiccast.native.upgrade.models import UpgradeContext

#: The exact URL SHAPE the installer persists and hands the D3 engine: a
#: driver-less `postgresql://`. Port 1 is closed on every Windows host, so a
#: connect attempt is refused immediately -- these tests must fail on
#: DRIVER RESOLUTION or not at all, never on a network timeout.
_BARE_POSTGRES_URL = "postgresql://civiccast:secret@127.0.0.1:1/civiccast"

_PSYCOPG2_MISSING = "No module named 'psycopg2'"


class _BlockedModuleFinder(MetaPathFinder):
    """Raise ``ModuleNotFoundError`` for a module name and its submodules.

    Raising from ``find_spec`` (rather than returning ``None``) reproduces the
    EXACT exception type and message text R7 recorded, independently of
    whether the blocked distribution is installed in the running venv.
    """

    def __init__(self, blocked: str) -> None:
        self._blocked = blocked

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == self._blocked or fullname.startswith(f"{self._blocked}."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)


@contextmanager
def _import_blocked(module_name: str) -> Iterator[None]:
    """Make ``module_name`` unimportable for the duration of the block."""

    finder = _BlockedModuleFinder(module_name)
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == module_name or name.startswith(f"{module_name}.")
    }
    for name in saved:
        del sys.modules[name]
    sys.meta_path.insert(0, finder)
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(saved)
        importlib.invalidate_caches()


def _postgres_manifest() -> BackupManifest:
    """The minimum manifest shape D3 step 3 hands the drill on the Postgres
    lane. Nothing in it is read before the drill's first ``create_engine``."""

    return BackupManifest(
        backup_id="pre-1.0.0-rc15",
        created_at=datetime.now(UTC),
        engine="postgres",
        db_artifact="civiccast.dump",
    )


def test_psycopg2_block_is_effective() -> None:
    """The block itself must work, or every assertion below is vacuous."""

    with _import_blocked("psycopg2"), pytest.raises(ModuleNotFoundError) as excinfo:
        importlib.import_module("psycopg2")
    assert _PSYCOPG2_MISSING in str(excinfo.value)


def test_shipped_psycopg_v3_is_importable() -> None:
    """The driver the product actually ships is present -- so a failure below
    is a wiring defect, not a missing dependency in this environment."""

    assert importlib.import_module("psycopg") is not None


def test_restore_drill_db_layer_runs_without_psycopg2(tmp_path: Path) -> None:
    """RED against the pre-fix tree: D3 step 3's restore drill must reach a
    real CONNECT failure, never a driver-import failure, when psycopg2 is
    absent.

    Pre-fix this raises ``ModuleNotFoundError: No module named 'psycopg2'``
    from ``create_engine`` -- exactly R7's journal entry. Post-fix the engine
    constructs against psycopg v3 and the first real DB touch fails with a
    refused connection, which is the honest outcome for an unreachable host.
    """

    with _import_blocked("psycopg2"), pytest.raises(Exception) as excinfo:
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=_postgres_manifest(),
            source_database_url=_BARE_POSTGRES_URL,
        )

    raised = excinfo.value
    assert not isinstance(raised, ModuleNotFoundError), (
        f"D3 step 3's restore drill resolved the uninstalled psycopg2 dialect: {raised!r}"
    )
    assert _PSYCOPG2_MISSING not in str(raised)


def test_restore_drill_engines_name_the_shipped_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserted at the engine boundary the ModuleNotFoundError comes from:
    every URL the drill hands ``create_engine`` must name a driver, and that
    driver must be the shipped psycopg v3. Independent of whether psycopg2
    happens to be installed, so this pin cannot go quiet."""

    captured: list[str] = []
    real_create_engine = restore_drill.create_engine

    def _spy(url: str, *args: object, **kwargs: object) -> object:
        captured.append(str(url))
        return real_create_engine(url, *args, **kwargs)

    monkeypatch.setattr(restore_drill, "create_engine", _spy)

    # The drill cannot COMPLETE against an unreachable host; what is under
    # test is only the URL each engine is built on, so any raise is expected
    # and is swallowed deliberately rather than asserted on here.
    with suppress(Exception):
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=_postgres_manifest(),
            source_database_url=_BARE_POSTGRES_URL,
        )

    assert captured, "the drill built no engine at all -- the pin would be vacuous"
    for url in captured:
        assert make_url(url).get_driver_name() == "psycopg", (
            f"restore drill built an engine on {url!r}, which SQLAlchemy resolves "
            "to a driver this product does not ship"
        )


def test_restore_drill_normalization_preserves_the_credential(tmp_path: Path) -> None:
    """Normalization must not corrupt the connection credential -- a drill
    that names the right driver but cannot authenticate is a worse outcome
    than the bug it replaces (``civiccast/db/url.py`` makes the same point)."""

    normalized = make_url(restore_drill._verification_engine_url(_BARE_POSTGRES_URL))
    assert normalized.get_driver_name() == "psycopg"
    assert normalized.username == "civiccast"
    assert normalized.password == "secret"
    assert normalized.host == "127.0.0.1"
    assert normalized.port == 1
    assert normalized.database == "civiccast"


def test_d3_step_three_backup_seam_actually_reaches_the_restore_drill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the drill matters: D3 step 3's production backup seam
    calls it. Without this pin, a future refactor could drop the spot check
    and leave the tests above passing while proving nothing about the upgrade
    path."""

    calls: list[str] = []

    def _fake_full_backup(**kwargs: object) -> BackupManifest:
        return _postgres_manifest()

    observed_expected_revision: list[object] = []

    def _fake_drill(**kwargs: object) -> object:
        calls.append(str(kwargs["source_database_url"]))
        # <batch-fix-list item 12> This used to capture ONLY
        # source_database_url, so a refactor that dropped PR #143's own fix --
        # passing the SOURCE database's revision as expected_revision instead
        # of letting the drill default to the NEW code's migration head --
        # passed this test unchanged. That default IS the Gate A run
        # 33681670855 root cause: on any release shipping a migration, the
        # pre-upgrade drill's schema_ok was always False, so the engine rolled
        # back before touching the database. Assert the tuple.
        observed_expected_revision.append(kwargs.get("expected_revision"))
        raise AssertionError("stop: the seam reached the drill")

    monkeypatch.setattr(upgrade_seams, "run_full_backup", _fake_full_backup)
    monkeypatch.setattr(upgrade_seams, "run_postgres_restore_drill", _fake_drill)
    # Gate A run 33681670855 fix (Fix A): _backup now reads the SOURCE
    # database's own current revision (to pass as run_postgres_restore_drill's
    # expected_revision -- the pre-upgrade drill's honest question, "does the
    # restore match what was dumped", not the DR-drill's "does it match
    # today's code") BEFORE calling the drill. That read goes through
    # civiccast.schema_check.read_db_revision, which this test's fake
    # unreachable _BARE_POSTGRES_URL would otherwise hang on for a real
    # bounded-connect timeout (see the module docstring on why port 1 does
    # not refuse immediately in every environment) -- fake it out too so this
    # stays a fast, network-free proof of "the seam reaches the drill".
    monkeypatch.setattr(
        "civiccast.schema_check.read_db_revision", lambda database_url: "fake-source-revision"
    )

    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url=_BARE_POSTGRES_URL,
        owner_run_id="test-run",
    )
    backup = upgrade_seams.default_backup(context)

    with pytest.raises(AssertionError, match="the seam reached the drill"):
        backup(str(tmp_path / "backups" / "pre-1.0.0-rc15"))

    assert calls == [_BARE_POSTGRES_URL]
    assert observed_expected_revision == ["fake-source-revision"], (
        "the pre-upgrade drill must be told the SOURCE database's own revision; letting it "
        "default to the NEW code's migration head is the Gate A run 33681670855 root cause"
    )


def test_an_unreadable_source_revision_fails_the_backup_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """<batch-fix-list item 12> The other half of PR #143's fix, previously
    guarded only by a Docker-gated test.

    When ``read_db_revision`` returns None the seam must NOT fall back to
    ``run_postgres_restore_drill``'s own default (``expected_migration_head()``),
    because that silently reintroduces the exact false negative -- comparing a
    pre-upgrade restore against the NEW code's head -- with no signal that it
    happened because the SOURCE revision could not be read rather than by
    design.
    """
    reached_drill: list[str] = []

    monkeypatch.setattr(upgrade_seams, "run_full_backup", lambda **kwargs: _postgres_manifest())
    monkeypatch.setattr(
        upgrade_seams,
        "run_postgres_restore_drill",
        lambda **kwargs: reached_drill.append("drill"),
    )
    monkeypatch.setattr("civiccast.schema_check.read_db_revision", lambda database_url: None)

    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url=_BARE_POSTGRES_URL,
        owner_run_id="test-run",
    )
    backup_ref = upgrade_seams.default_backup(context)(str(tmp_path / "backups" / "pre-1.0.0-rc15"))

    assert reached_drill == [], "the drill must NOT run against an unknown source revision"
    assert backup_ref.restore_drill_ok is False
    assert backup_ref.restore_drill_errors
    detail = " ".join(backup_ref.restore_drill_errors)
    assert "could not read the source database's own current revision" in detail
    assert "33681670855" in detail, "the failure must name the defect it is refusing to reintroduce"


@pytest.mark.parametrize("local", [False, True])
def test_flat_database_does_not_delegate_to_unscoped_cluster_backup(tmp_path, monkeypatch, local):
    from civiccast.native.upgrade import flat_recovery_database as database
    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError

    calls = []

    def unsafe_backup(**kwargs):
        calls.append("whole-cluster globals and whole-database dump")
        return _postgres_manifest()

    monkeypatch.setattr(database, "run_full_backup", unsafe_backup, raising=False)
    context = database.FlatDatabaseContext(
        database_url=_BARE_POSTGRES_URL,
        pg_bin=tmp_path / "old-tools",
        expected_owned_pgdata=tmp_path / "pgdata" if local else None,
        backup_root=tmp_path / "database",
        expected_schema_revision="old-revision",
        owned_database="civiccast",
        owned_role="civiccast",
        verification_target=database.FlatVerificationTarget(
            "postgresql://verifier@127.0.0.1:56489/postgres", tmp_path / "verifier-pgdata"
        ),
    )
    # The unverified tool paths alone require pre-overwrite refusal. Neither
    # local classification nor a shared service URL authorizes global capture.
    with pytest.raises(FlatRecoveryError):
        database.build_flat_database_seams(context).backup(str(context.backup_root))
    assert not calls


def _flat_context(tmp_path: Path):
    from civiccast.native.upgrade.flat_recovery_database import (
        FlatDatabaseContext,
        FlatVerificationTarget,
    )

    tools = tmp_path / "old-tools"
    tools.mkdir()
    for name in ("pg_dump", "pg_restore", "psql"):
        (tools / (name + (".exe" if os.name == "nt" else ""))).write_bytes(b"admitted old tool")
    return FlatDatabaseContext(
        database_url=_BARE_POSTGRES_URL,
        pg_bin=tools,
        expected_owned_pgdata=None,
        backup_root=tmp_path / "database",
        expected_schema_revision="old-revision",
        owned_database="civiccast",
        owned_role="civiccast",
        verification_target=FlatVerificationTarget(
            "postgresql://verifier@127.0.0.1:56489/postgres", tmp_path / "verifier-pgdata"
        ),
    )


def _scoped_roles():
    from civiccast.dr.models import PostgresRolePrerequisites

    return PostgresRolePrerequisites(
        roles={"civiccast": (False, False, False, True, False, False, -1)},
        memberships=[],
        role_options={"civiccast": (True, None)},
        membership_options=[],
    )


def _flat_reference(context):
    from civiccast.dr.backup import write_integrity_manifest
    from civiccast.dr.models import TableSnapshot
    from civiccast.native.upgrade.flat_recovery_database import _header_hash
    from civiccast.native.upgrade.models import BackupRef

    root = context.backup_root
    root.mkdir()
    (root / "database.pgdump").write_bytes(b"synthetic dump for integrity-unit test only")
    (root / "role-prerequisites.json").write_text(
        _scoped_roles().model_dump_json(), encoding="utf-8"
    )
    manifest = _postgres_manifest().model_copy(
        update={
            "db_artifact": "database.pgdump",
            "globals_artifact": None,
            "role_prerequisites_artifact": "role-prerequisites.json",
            "namespace_extensions": {"plpgsql": ("1.0", "pg_catalog")},
            "tables": [TableSnapshot(name="items", row_count=1, checksum_sha256="a" * 64)],
        }
    )
    receipt = {
        "target": {
            "host": "127.0.0.1",
            "port": 1,
            "database": "civiccast",
            "role": "civiccast",
            "schemas": ["civiccast"],
            "connection_options": {},
        },
        "source_revision": "old-revision",
        "manifest_header_sha256": _header_hash(manifest),
    }
    (root / "namespace-recovery.json").write_text(json.dumps(receipt), encoding="utf-8")
    manifest = manifest.model_copy(update={"integrity": write_integrity_manifest(root)})
    (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return BackupRef(
        backup_id=manifest.backup_id,
        backup_dir=str(root),
        manifest_hash=upgrade_seams._manifest_blob_hash(manifest),
        db_artifact="database.pgdump",
        verified=True,
        restore_drill_ok=True,
    )


@pytest.mark.parametrize("damage", ["table-baseline", "artifact", "path", "drill", "tools"])
def test_flat_database_verification_rejects_changed_contract(tmp_path, damage):
    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError
    from civiccast.native.upgrade.flat_recovery_database import build_flat_database_seams

    context = _flat_context(tmp_path)
    seams = build_flat_database_seams(context)
    reference = _flat_reference(context)
    seams.verify_backup(reference)
    if damage == "table-baseline":
        path = context.backup_root / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tables"][0]["row_count"] = 0
        path.write_text(json.dumps(data), encoding="utf-8")
    elif damage == "artifact":
        (context.backup_root / "database.pgdump").write_bytes(b"changed")
    elif damage == "path":
        reference = reference.model_copy(update={"backup_dir": str(tmp_path / "foreign")})
    elif damage == "drill":
        reference = reference.model_copy(update={"restore_drill_ok": False})
    else:
        tool = context.pg_bin / ("psql.exe" if os.name == "nt" else "psql")
        tool.write_bytes(b"new payload overwrote the old tools")
    with pytest.raises(FlatRecoveryError):
        seams.verify_backup(reference)


def test_flat_database_destination_binding_precedes_connection(tmp_path, monkeypatch):
    from civiccast.native.upgrade import flat_recovery_database as database
    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError

    context = _flat_context(tmp_path)
    seams = database.build_flat_database_seams(context)
    monkeypatch.setattr(
        database, "create_engine", lambda *_args, **_kwargs: pytest.fail("connected")
    )
    with pytest.raises(FlatRecoveryError, match="destination"):
        seams.backup(str(tmp_path / "foreign"))
    assert not (tmp_path / "foreign").exists()
    assert "secret" not in repr(context)


@pytest.mark.parametrize("damage", ["missing", "empty", "malformed", "escape"])
def test_scoped_role_proof_requires_valid_backup_local_artifact(tmp_path, damage):
    artifact = "role-prerequisites.json"
    if damage == "empty":
        (tmp_path / artifact).write_text("", encoding="utf-8")
    elif damage == "malformed":
        (tmp_path / artifact).write_text('{"roles":{}}', encoding="utf-8")
    elif damage == "escape":
        artifact = "../role-prerequisites.json"
        (tmp_path.parent / "role-prerequisites.json").write_text(
            _scoped_roles().model_dump_json(), encoding="utf-8"
        )
    with pytest.raises((ValueError, FileNotFoundError)):
        restore_drill.read_postgres_role_prerequisites(tmp_path, artifact)


@pytest.mark.parametrize(
    "damage", ["attributes", "memberships", "inheritance", "membership-options"]
)
def test_scoped_role_prerequisites_refuse_drift_without_replaying_roles(monkeypatch, damage):
    prerequisites = _scoped_roles()
    monkeypatch.setattr(restore_drill, "_pg_role_attributes", lambda *_: prerequisites.roles)
    monkeypatch.setattr(restore_drill, "_pg_role_memberships", lambda *_: set())
    monkeypatch.setattr(restore_drill, "_pg_role_options", lambda *_: prerequisites.role_options)
    monkeypatch.setattr(restore_drill, "_pg_membership_options", lambda *_: [])
    restore_drill.verify_postgres_role_prerequisites(None, prerequisites)
    if damage == "attributes":
        monkeypatch.setattr(restore_drill, "_pg_role_attributes", lambda *_: {})
    elif damage == "memberships":
        monkeypatch.setattr(
            restore_drill, "_pg_role_memberships", lambda *_: {("civiccast", "foreign")}
        )
    elif damage == "inheritance":
        monkeypatch.setattr(
            restore_drill, "_pg_role_options", lambda *_: {"civiccast": (False, None)}
        )
    else:
        monkeypatch.setattr(
            restore_drill,
            "_pg_membership_options",
            lambda *_: [("civiccast", "foreign", True, True, True)],
        )
    with pytest.raises(ValueError):
        restore_drill.verify_postgres_role_prerequisites(None, prerequisites)


def test_scoped_role_capture_requires_complete_necessary_role_closure(monkeypatch):
    prerequisites = _scoped_roles()
    monkeypatch.setattr(restore_drill, "_pg_relevant_roles", lambda *_, **_kw: {"civiccast"})
    monkeypatch.setattr(restore_drill, "_pg_role_attributes", lambda *_: prerequisites.roles)
    monkeypatch.setattr(restore_drill, "_pg_role_memberships", lambda *_: set())
    monkeypatch.setattr(restore_drill, "_pg_role_options", lambda *_: prerequisites.role_options)
    monkeypatch.setattr(restore_drill, "_pg_membership_options", lambda *_: [])
    captured = restore_drill.capture_postgres_role_prerequisites(None)
    assert captured == prerequisites
    assert set(captured.roles) == {"civiccast"}
    monkeypatch.setattr(restore_drill, "_pg_role_attributes", lambda *_: {})
    with pytest.raises(ValueError, match="could not be read"):
        restore_drill.capture_postgres_role_prerequisites(None)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("127.0.0.1/32", True),
        ("::1/128", True),
        ("127.0.0.1", True),
        ("192.168.1.1/32", False),
        ("::ffff:192.168.1.1/128", False),
        (None, False),
    ],
)
def test_owned_postgres_admission_parses_server_inet_text(address, expected):
    from civiccast.native.upgrade.flat_recovery_database import _loopback_server

    assert _loopback_server(address) is expected


@pytest.mark.parametrize("damage", ["same-source", "remote"])
def test_flat_verifier_target_must_be_independently_disposable(tmp_path, damage):
    from dataclasses import replace

    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError
    from civiccast.native.upgrade.flat_recovery_database import (
        FlatVerificationTarget,
        build_flat_database_seams,
    )

    context = _flat_context(tmp_path)
    target_url = (
        context.database_url
        if damage == "same-source"
        else "postgresql://admin@192.0.2.1:56489/postgres"
    )
    context = replace(
        context,
        verification_target=FlatVerificationTarget(target_url, tmp_path / "verifier-pgdata"),
    )
    with pytest.raises(FlatRecoveryError, match="verification target"):
        build_flat_database_seams(context)


@pytest.mark.parametrize("missing", ["roles", "extensions", "ambiguous-globals"])
def test_separate_namespace_drill_requires_closed_prerequisites_before_connection(
    tmp_path, monkeypatch, missing
):
    from datetime import UTC, datetime

    from civiccast.dr.models import BackupManifest

    manifest = BackupManifest(
        backup_id="synthetic",
        created_at=datetime.now(UTC),
        engine="postgres",
        db_artifact="database.pgdump",
        role_prerequisites_artifact="roles.json",
        namespace_extensions={"plpgsql": ("1.0", "pg_catalog")},
    )
    if missing == "roles":
        manifest = manifest.model_copy(update={"role_prerequisites_artifact": None})
    elif missing == "extensions":
        manifest = manifest.model_copy(update={"namespace_extensions": None})
    else:
        manifest = manifest.model_copy(update={"globals_artifact": "globals.sql"})
    monkeypatch.setattr(restore_drill, "create_engine", lambda *_a, **_kw: pytest.fail("connected"))
    with pytest.raises(ValueError, match="role and extension prerequisites"):
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=manifest,
            source_database_url="postgresql://source@127.0.0.1:56487/source",
            restore_target_database_url="postgresql://verifier@127.0.0.1:56489/postgres",
        )


def test_disposable_roles_reject_incomplete_membership_closure_before_write():
    proof = _scoped_roles().model_copy(update={"memberships": [("civiccast", "unrelated")]})
    with pytest.raises(ValueError, match="incomplete"):
        restore_drill.prepare_disposable_postgres_roles(None, proof)


def test_namespace_role_closure_does_not_read_unrelated_database_grants(monkeypatch):
    monkeypatch.setattr(
        restore_drill, "_pg_database_owner", lambda *_a, **_kw: pytest.fail("database owner")
    )
    monkeypatch.setattr(
        restore_drill, "_pg_database_acl", lambda *_a, **_kw: pytest.fail("database grants")
    )
    monkeypatch.setattr(
        restore_drill, "_pg_table_owners", lambda *_a, **_kw: {"items": "civiccast"}
    )
    monkeypatch.setattr(restore_drill, "_pg_sequence_owners", lambda *_a, **_kw: {})
    monkeypatch.setattr(restore_drill, "_pg_schema_owner", lambda *_a, **_kw: "civiccast")
    for name in (
        "_pg_schema_acl",
        "_pg_table_grants",
        "_pg_sequence_acls",
        "_pg_default_acls",
        "_pg_all_role_membership_edges",
    ):
        monkeypatch.setattr(restore_drill, name, lambda *_a, **_kw: [])
    assert restore_drill._pg_relevant_roles(None, include_database=False) == {"civiccast"}


def test_flat_refuses_global_timeout_before_io(tmp_path, monkeypatch):
    from dataclasses import replace

    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError
    from civiccast.native.upgrade.flat_recovery_database import build_flat_database_seams

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    context = _flat_context(tmp_path)
    context = replace(context, database_url=context.database_url + "?connect_timeout=20")
    with pytest.raises(FlatRecoveryError, match="option admission"):
        build_flat_database_seams(context)
    assert not context.backup_root.exists()


def test_flat_requires_disposable_verifier_before_tool_or_database_io(tmp_path, monkeypatch):
    from dataclasses import replace

    from civiccast.native.upgrade import flat_recovery_database as database
    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError

    context = replace(_flat_context(tmp_path), verification_target=None)
    touched = []
    monkeypatch.setattr(database, "_sha", lambda *_: touched.append("tool hash") or "a" * 64)
    monkeypatch.setattr(database, "create_engine", lambda *_a, **_k: touched.append("database"))
    with pytest.raises(FlatRecoveryError, match="requires an independent disposable verifier"):
        database.build_flat_database_seams(context)
    assert touched == []
    assert not context.backup_root.exists()


@pytest.mark.parametrize("source_host", ["localhost", "::1", "127.0.0.2"])
def test_flat_refuses_loopback_source_cluster_alias_before_database_io(tmp_path, source_host):
    from dataclasses import replace

    from sqlalchemy.engine import URL

    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError
    from civiccast.native.upgrade.flat_recovery_database import build_flat_database_seams

    context = _flat_context(tmp_path)
    context = replace(
        context,
        database_url=URL.create(
            "postgresql+psycopg",
            username="civiccast",
            host=source_host,
            port=56489,
            database="civiccast",
        ).render_as_string(),
    )
    with pytest.raises(FlatRecoveryError, match="not independently disposable"):
        build_flat_database_seams(context)
    assert not context.backup_root.exists()


def test_flat_refuses_known_source_pgdata_as_verifier_before_database_io(tmp_path):
    from dataclasses import replace

    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError
    from civiccast.native.upgrade.flat_recovery_database import build_flat_database_seams

    context = _flat_context(tmp_path)
    context = replace(context, expected_owned_pgdata=context.verification_target.expected_pgdata)
    with pytest.raises(FlatRecoveryError, match="not independently disposable"):
        build_flat_database_seams(context)
    assert not context.backup_root.exists()


@pytest.mark.parametrize("query", ["", "?connect_timeout=10"])
def test_flat_local_bound_reaches_tools_source_verifier_and_drill(tmp_path, monkeypatch, query):
    from dataclasses import replace
    from subprocess import CompletedProcess

    from civiccast.dr.models import TableSnapshot
    from civiccast.native.upgrade import flat_recovery_database as database
    from civiccast.native.upgrade.flat_recovery import FlatRecoveryError

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "20")
    context = _flat_context(tmp_path)
    target = database.FlatVerificationTarget(
        "postgresql://verifier@127.0.0.1:56489/postgres" + query, tmp_path / "verifier"
    )
    context = replace(
        context, database_url=context.database_url + query, verification_target=target
    )
    events = []

    class Result:
        def __init__(self, sql):
            self.sql = sql

        def one(self):
            return ("civiccast", "civiccast", "127.0.0.1/32")

        def scalar_one(self):
            if "EXISTS" in self.sql:
                return False
            return "old-revision" if "version_num" in self.sql else "snapshot-id"

        def all(self):
            return []

    class Source:
        def connect(self):
            return self

        def execution_options(self, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, *args):
            return Result(str(statement))

        def dispose(self):
            pass

    def factory(url, **kwargs):
        events.append((make_url(url).username, kwargs["connect_args"]["connect_timeout"]))
        if make_url(url).username == "verifier":
            raise RuntimeError("verifier construction observed")
        return Source()

    def spawn(argv, **kwargs):
        events.append(("tool", kwargs["env"]["PGCONNECT_TIMEOUT"]))
        return CompletedProcess(argv, 0, b"synthetic dump", b"")

    monkeypatch.setattr(database, "create_engine", factory)
    monkeypatch.setattr(database.subprocess, "run", spawn)
    monkeypatch.setattr(
        database,
        "snapshot_tables",
        lambda *_a, **_k: [TableSnapshot(name="items", row_count=1, checksum_sha256="a" * 64)],
    )
    monkeypatch.setattr(
        database,
        "capture_postgres_namespace_extensions",
        lambda *_: {"plpgsql": ("1.0", "pg_catalog")},
    )
    monkeypatch.setattr(database, "capture_postgres_role_prerequisites", lambda *_: _scoped_roles())
    seams = database.build_flat_database_seams(context)
    with pytest.raises(FlatRecoveryError, match="backup failed"):
        seams.backup(str(context.backup_root))
    assert events == [("civiccast", 10), ("tool", "10"), ("verifier", 10)]

    def drill_factory(url, **kwargs):
        assert kwargs["connect_args"]["connect_timeout"] == 10
        raise RuntimeError("drill source construction observed")

    monkeypatch.setattr(restore_drill, "create_engine", drill_factory)
    with pytest.raises(RuntimeError, match="drill source construction"):
        restore_drill.run_postgres_restore_drill(
            backup_dir=tmp_path,
            manifest=_postgres_manifest(),
            source_database_url=context.database_url,
            timeout_seconds=10,
        )
    assert os.environ["CIVICCAST_DB_CONNECT_TIMEOUT"] == "20"
