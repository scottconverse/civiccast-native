# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0049 (S11b per-sink loudness) applies and reverses against a real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the MIGRATION were broken. This test drives the actual alembic upgrade and reflects
the columns + the regime CHECK constraint — the only thing that proves ``0049`` itself
produces them — and the downgrade removes them (reversibility). The real-Postgres half
is covered by ``TestRealPostgresFullMigrationChain`` in ``tests/live/test_real_postgres``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_SINK_COLS = {
    "loudness_regime",
    "loudness_target_lufs",
    "loudness_tolerance_lufs",
    "eas_tone_strip_enabled",
}
_REGIME_CHECK = "egress_sinks_loudness_regime_check"


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


def _check_constraints(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {cc["name"] for cc in inspect(engine).get_check_constraints(table)}
    finally:
        engine.dispose()


def test_migration_0049_adds_then_removes_per_sink_loudness(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0049.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    sink_cols = _columns(url, "egress_sinks")
    assert sink_cols >= _SINK_COLS, f"0049 did not add sink cols: {_SINK_COLS - sink_cols}"
    assert _REGIME_CHECK in _check_constraints(url, "egress_sinks"), (
        "0049 did not add the loudness_regime CHECK constraint"
    )

    # reversibility: downgrading past 0049 removes exactly what it added
    command.downgrade(cfg, "0048_remote_contribution")
    assert not (_SINK_COLS & _columns(url, "egress_sinks")), "0049 downgrade left sink cols"
    assert _REGIME_CHECK not in _check_constraints(url, "egress_sinks"), (
        "0049 downgrade left the regime CHECK"
    )
