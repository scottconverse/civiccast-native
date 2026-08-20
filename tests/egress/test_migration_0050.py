# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0050 (S11a caption proof samples) creates then drops its table.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the MIGRATION were broken. This drives the actual alembic upgrade and reflects the
table + columns + index — proof that ``0050`` itself produces them — and the downgrade
removes the table (reversibility). The real-Postgres half is covered by
``TestRealPostgresFullMigrationChain``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_TABLE = "egress_caption_proof_samples"
_INDEX = "ix_egress_caption_proof_samples_channel_sampled"
_COLS = {"status", "caption_status", "mode", "decoder_name", "matched_cue_count", "blocker"}


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _tables(url: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {col["name"] for col in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def test_migration_0050_creates_then_drops_caption_proofs(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0050.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    assert _TABLE in _tables(url), "0050 did not create egress_caption_proof_samples"
    cols = _columns(url, _TABLE)
    assert cols >= _COLS, f"0050 missing cols: {_COLS - cols}"
    assert _INDEX in _indexes(url, _TABLE), "0050 did not create the channel/sampled index"

    # reversibility: downgrading past 0050 drops exactly the table it added
    command.downgrade(cfg, "0049_per_sink_loudness")
    assert _TABLE not in _tables(url), "0050 downgrade left the table"
