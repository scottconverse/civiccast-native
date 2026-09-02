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
