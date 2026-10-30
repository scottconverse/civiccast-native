# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Upgrade preserves legacy repeat intent until the operator saves a choice."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_repeat_setting_migrates_without_changing_existing_channel(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0098.sqlite'}"
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "0097_agenda_minutes")
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "0098_channel_repeat_schedule")
        column = next(
            c
            for c in inspect(engine).get_columns("egress_configs")
            if c["name"] == "repeat_schedule"
        )
        assert column["nullable"] and column["default"] is None
        with engine.connect() as conn:
            conn.execute(text("SELECT repeat_schedule FROM egress_configs"))
        command.downgrade(cfg, "0097_agenda_minutes")
        assert "repeat_schedule" not in {
            c["name"] for c in inspect(engine).get_columns("egress_configs")
        }
    finally:
        engine.dispose()
