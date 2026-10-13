# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0090 adds and removes the index used by command-history pruning."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
_INDEX = "ix_egress_commands_channel_consumed_issued"


def test_migration_0090_adds_then_removes_command_history_index(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0090.sqlite'}"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)

    command.upgrade(cfg, "head")
    engine = create_engine(url, future=True)
    try:
        indexes = {item["name"] for item in inspect(engine).get_indexes("egress_commands")}
    finally:
        engine.dispose()
    assert _INDEX in indexes

    command.downgrade(cfg, "0089_contribution_media_control_requests")
    engine = create_engine(url, future=True)
    try:
        indexes_after = {item["name"] for item in inspect(engine).get_indexes("egress_commands")}
    finally:
        engine.dispose()
    assert _INDEX not in indexes_after
