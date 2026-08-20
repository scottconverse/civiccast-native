# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0042 (S5 takeover audit + command actions) applies and reverses.

create_all (the store fixture) builds the schema from the ORM, so it would pass
even if the MIGRATION were broken. This drives the actual alembic upgrade and
reflects the table/columns/index — the only thing that proves ``0042`` produces
them — plus a behavioral check that the widened ``egress_commands`` action CHECK
admits ``takeover``/``handback`` (and rejects them again after downgrade).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_TAKEOVER_COLS = {
    "session_id",
    "channel_id",
    "source_ref",
    "source_label",
    "operator_id",
    "operator_name",
    "reason",
    "took_over_at",
    "returned_at",
    "source_plan_json",
    "notes",
}
_TAKEOVER_INDEX = "ix_takeover_audit_channel_took_over"


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _takeover_command_accepted(url: str) -> bool:
    """True if egress_commands accepts an action='takeover' row (CHECK admits it)."""
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO egress_commands "
                    "(command_id, channel_id, action, issued_at, issued_by) "
                    "VALUES ('tk-cmd-1', 'public', 'takeover', "
                    "'2026-06-20 18:00:00+00:00', 'dana')"
                )
            )
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def test_migration_0042_adds_then_removes_takeover_audit_and_actions(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0042.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    engine = create_engine(url, future=True)
    try:
        insp = inspect(engine)
        assert insp.has_table("takeover_audit")
        cols = {c["name"] for c in insp.get_columns("takeover_audit")}
        assert cols == _TAKEOVER_COLS
        index_names = {ix["name"] for ix in insp.get_indexes("takeover_audit")}
        assert _TAKEOVER_INDEX in index_names
    finally:
        engine.dispose()

    # The widened action CHECK admits 'takeover'.
    assert _takeover_command_accepted(url) is True

    # Reversibility: step back one revision (0042 -> 0041).
    command.downgrade(cfg, "0041_commit_rollback_fields")
    engine = create_engine(url, future=True)
    try:
        assert not inspect(engine).has_table("takeover_audit")
    finally:
        engine.dispose()

    # The CHECK is reverted — 'takeover' is rejected again.
    assert _takeover_command_accepted(url) is False
