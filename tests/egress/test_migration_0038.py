# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0038 (S9 reliability fields) applies and reverses against a real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the MIGRATION were broken. This test drives the actual alembic upgrade and reflects
the columns + index — the only thing that proves `0038` itself produces them — and the
downgrade removes them (reversibility).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_HEALTH_COLS = {"schema_version", "proof_events_appended"}
_PROOF_INDEX = "ix_egress_proof_events_channel_observed"


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


def _indexes(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def test_migration_0038_adds_then_removes_reliability_fields(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0038.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    health_cols = _columns(url, "egress_health_samples")
    assert health_cols >= _HEALTH_COLS, (
        f"0038 did not add health cols: {_HEALTH_COLS - health_cols}"
    )
    assert _PROOF_INDEX in _indexes(url, "egress_proof_events"), "0038 did not add the proof index"
    # The pre-rescope co-process columns must NOT be present (they ship with their
    # consumer in build step 7, not as dead schema here).
    assert "sdi_coproc_pid" not in _columns(url, "egress_states")

    # reversibility: downgrading past 0038 removes exactly what it added
    command.downgrade(cfg, "0037_asset_meeting_body")
    assert not (_HEALTH_COLS & _columns(url, "egress_health_samples")), (
        "0038 downgrade left health cols"
    )
    assert _PROOF_INDEX not in _indexes(url, "egress_proof_events"), "0038 downgrade left the index"
