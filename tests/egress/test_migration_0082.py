# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0082 (graphics-overlay operator control) applies and reverses against a
real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the MIGRATION were broken. This test drives the actual alembic upgrade and reflects
the columns -- the only thing that proves ``0082`` itself produces them -- and the
downgrade removes them (reversibility).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_COLS = {"graphics_overlay_enabled", "graphics_overlay_lower_third_text"}
_PRIOR_HEAD = "0081_summary_generation_jobs"


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {col["name"] for col in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def test_migration_0082_adds_then_removes_graphics_overlay_columns(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0082.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    cols = _columns(url, "egress_configs")
    assert cols >= _COLS, f"0082 did not add {_COLS} to egress_configs (has {cols})"

    # reversibility: downgrading past 0082 removes exactly what it added
    command.downgrade(cfg, _PRIOR_HEAD)
    remaining = _columns(url, "egress_configs")
    assert not (_COLS & remaining), f"0082 downgrade left {_COLS & remaining}"
