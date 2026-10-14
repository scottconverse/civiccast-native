# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Local-anchor migration preserves legacy intent until station-aware pinning."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_local_anchor_migration_preserves_legacy_row_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'm0091.sqlite'}"
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0090_egress_command_history_storage")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO channel_program_slots "
                "(slot_id, channel_id, asset_id, recurrence, first_start_at, enabled, created_at, updated_at) "
                "VALUES ('legacy', 'public', 'asset', 'weekly', '2026-06-12 01:00:00', true, '2026-06-01', '2026-06-01')"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT first_start_at, recurrence_anchor_local FROM channel_program_slots WHERE slot_id='legacy'"
            )
        ).one()
        assert row == ("2026-06-12 01:00:00", None)
    command.downgrade(cfg, "0090_egress_command_history_storage")
    assert "recurrence_anchor_local" not in {
        column["name"] for column in inspect(engine).get_columns("channel_program_slots")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM channel_program_slots")) == 1
    engine.dispose()
