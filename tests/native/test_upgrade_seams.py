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

from civiccast.native.upgrade.models import UpgradeContext
from civiccast.native.upgrade.seams import default_migrate


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
