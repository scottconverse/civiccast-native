# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""0088 seeds missing health rules without replacing operator policy."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_0088_seeds_live_caption_and_eas_warning_rules(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0088_seed.sqlite'}"
    command.upgrade(_cfg(url), "head")

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT condition, severity, enabled, channel_ids_json "
                    "FROM alert_rules WHERE condition IN "
                    "('live-caption-failure', 'eas-source-unavailable')"
                )
            ).all()
        assert {
            (row.condition, row.severity, row.enabled, row.channel_ids_json) for row in rows
        } == {
            ("live-caption-failure", "warning", True, "[]"),
            ("eas-source-unavailable", "warning", True, "[]"),
        }
    finally:
        engine.dispose()


def test_0088_preserves_existing_operator_caption_rule(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0088_operator.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "0087_retention_terms")

    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO alert_rules "
                    "(rule_id, condition, enabled, severity, channel_ids_json, "
                    "dedupe_window_seconds, re_alert_after_seconds, scope_channel_id, "
                    "notify_on_resolve, updated_at, updated_by) "
                    "VALUES ('operator:caption', 'live-caption-failure', true, 'critical', "
                    "'[\"ops\"]', 1200, 7200, 'government', false, "
                    "'2026-10-08T12:00:00+00:00', 'operator:fixture')"
                )
            )
        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT rule_id, severity, channel_ids_json, dedupe_window_seconds, "
                    "re_alert_after_seconds, scope_channel_id, notify_on_resolve, updated_by "
                    "FROM alert_rules WHERE condition = 'live-caption-failure'"
                )
            ).one()
        assert tuple(row) == (
            "operator:caption",
            "critical",
            '["ops"]',
            1200,
            7200,
            "government",
            False,
            "operator:fixture",
        )
    finally:
        engine.dispose()
