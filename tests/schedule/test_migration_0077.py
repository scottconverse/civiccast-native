# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0077 creates the five S7 tables + the archival/legal-hold columns.

Drives the real migration through Alembic against a fresh sqlite fixture DB
(not ``create_all`` -- that builds the *current* ORM schema and would never
catch a broken migration file), then asserts both directions: upgrade adds
every table/column, downgrade removes them cleanly, and upgrading again
from a clean base still lands at the same head.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_PARENT_REVISION = "0078_agenda_item_confidence"
_REVISION = "0077_media_lifecycle"

_NEW_TABLES = (
    "media_ingest_jobs",
    "transcode_jobs",
    "asset_readiness",
    "watch_folder_configs",
    "asset_retention_policies",
    "asset_archive_proofs",
    "media_lifecycle_audit_log",
)


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_creates_every_s7_table_and_asset_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "0077_up.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _PARENT_REVISION)

    engine = create_engine(url, future=True)
    try:
        before = set(inspect(engine).get_table_names())
        for table in _NEW_TABLES:
            assert table not in before, f"{table} should not exist before 0077"
        asset_cols_before = {c["name"] for c in inspect(engine).get_columns("assets")}
        assert "legal_hold" not in asset_cols_before
    finally:
        engine.dispose()

    command.upgrade(_cfg(url), _REVISION)

    engine = create_engine(url, future=True)
    try:
        after = set(inspect(engine).get_table_names())
        for table in _NEW_TABLES:
            assert table in after, f"{table} missing after upgrading to 0077"
        asset_cols_after = {c["name"] for c in inspect(engine).get_columns("assets")}
        assert "legal_hold" in asset_cols_after
        assert "legal_hold_reason" in asset_cols_after
    finally:
        engine.dispose()


def test_downgrade_removes_every_s7_table_and_asset_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "0077_down.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _REVISION)

    command.downgrade(_cfg(url), _PARENT_REVISION)

    engine = create_engine(url, future=True)
    try:
        after_down = set(inspect(engine).get_table_names())
        for table in _NEW_TABLES:
            assert table not in after_down, f"{table} still present after downgrade"
        asset_cols = {c["name"] for c in inspect(engine).get_columns("assets")}
        assert "legal_hold" not in asset_cols
        assert "legal_hold_reason" not in asset_cols
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "0077_roundtrip.db"
    url = f"sqlite:///{db_path}"
    cfg = _cfg(url)

    command.upgrade(cfg, _REVISION)
    command.downgrade(cfg, _PARENT_REVISION)
    command.upgrade(cfg, _REVISION)

    engine = create_engine(url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        for table in _NEW_TABLES:
            assert table in tables
    finally:
        engine.dispose()
