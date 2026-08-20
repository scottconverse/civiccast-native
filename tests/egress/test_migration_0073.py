# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0073 (allow_software_fallback; renumbered from 0072 -- see CHANGELOG) applies and reverses against a real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the MIGRATION were broken. This test drives the actual alembic upgrade and reflects
the column -- the only thing that proves ``0073`` itself produces it -- and the
downgrade removes it (reversibility).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_COL = "allow_software_fallback"
_PRIOR_HEAD = "0071_published_blocks_overlap"


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


def test_migration_0072_adds_then_removes_allow_software_fallback(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0072.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    cols = _columns(url, "egress_configs")
    assert _COL in cols, f"0072 did not add {_COL} to egress_configs"

    # reversibility: downgrading past 0072 removes exactly what it added
    command.downgrade(cfg, _PRIOR_HEAD)
    assert _COL not in _columns(url, "egress_configs"), f"0072 downgrade left {_COL}"
