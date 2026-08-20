# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0039 (S8 alerting tables) applies and reverses against a real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the migration itself were broken. This test drives the actual alembic upgrade and
reflects the tables + indexes — the only proof that ``0039`` itself produces the schema —
and the downgrade removes all alerting tables without touching prior tables.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The six tables added by 0039.
_ALERTING_TABLES = {
    "alert_rules",
    "alert_channels",
    "alert_events",
    "alert_event_deliveries",
    "system_resource_samples",
    "system_self_tests",
}

# Indexes added by 0039.
_ALERTING_INDEXES = {
    "alert_events": "ix_alert_events_dedupe",
    "alert_event_deliveries": "ix_alert_event_deliveries_event_id",
    "system_resource_samples": "ix_system_resource_samples_sampled_at",
    "system_self_tests": "ix_system_self_tests_started_at",
}

# A prior-migration table that must survive a 0039 downgrade.
_PRIOR_TABLE = "egress_health_samples"

# §6.2 default rules seeded by 0039.
_EXPECTED_SEED_CONDITIONS = {
    "off-air",
    "encoder-death",
    "server-crash",
    "relay-blocked",
    "missing-media",
    "db-unreachable",
    "service-down",
    "commit-failure",
    "compliance-probe-fail",
    "schema-drift",
    "takeover-stuck-2h",
    "disk-low",
    "clock-skew",
    "ai-runtime-down",
}


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


def _indexes(url: str, table: str) -> set[str]:
    engine = create_engine(url, future=True)
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _alert_rule_conditions(url: str) -> set[str]:
    """Return the set of seeded condition values from alert_rules."""
    from sqlalchemy import text

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT condition FROM alert_rules")).fetchall()
        return {r[0] for r in rows}
    finally:
        engine.dispose()


def test_migration_0039_adds_alerting_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0039.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")

    tables = _tables(url)
    missing = _ALERTING_TABLES - tables
    assert not missing, f"0039 did not create tables: {missing}"


def test_migration_0039_adds_alerting_indexes(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0039_idx.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")

    for table, index_name in _ALERTING_INDEXES.items():
        indexes = _indexes(url, table)
        assert index_name in indexes, f"0039 did not create index {index_name} on {table}"


def test_migration_0039_seeds_default_rules(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0039_seed.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")

    seeded = _alert_rule_conditions(url)
    missing = _EXPECTED_SEED_CONDITIONS - seeded
    assert not missing, f"0039 seed missing conditions: {missing}"


def test_migration_0039_downgrade_removes_alerting_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0039_down.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0038_reliability_fields")

    tables = _tables(url)
    leftover = _ALERTING_TABLES & tables
    assert not leftover, f"0039 downgrade left alerting tables: {leftover}"


def test_migration_0039_downgrade_preserves_prior_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm0039_prior.sqlite'}"
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0038_reliability_fields")

    tables = _tables(url)
    assert _PRIOR_TABLE in tables, (
        f"0039 downgrade removed {_PRIOR_TABLE} — it must not touch prior tables"
    )
