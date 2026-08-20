# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0039 (S8 alerting tables) applies and reverses against a real DB.

create_all (the store fixture) builds the schema from the ORM, so it would pass even
if the migration itself were broken. This test drives the actual alembic upgrade and
reflects the tables + indexes — the only proof that ``0039`` itself produces the schema —
and the downgrade removes all alerting tables without touching prior tables.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

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


def test_fresh_install_seeded_rule_fires_and_logs_visible_gap_not_silence(
    tmp_path: Path,
) -> None:
    """C1 regression: a station install runs nothing but ``alembic upgrade head``
    and never touches Alert Settings — exactly what ships out of the box. The
    0039 seed leaves every default rule's ``channel_ids`` empty (§6.2: "operator
    configures actual channels post-install"). Prove that on this real,
    migration-built database (not the ORM ``create_all`` shortcut the other
    alerting tests use) an off-air condition still:

    1. Fires a real, queryable ``AlertEvent`` (state="firing") — this is what
       drives the runtime safe-to-air banner red, independent of delivery.
    2. Logs a ``suppressed`` ``AlertEventDelivery`` explaining *why* no operator
       was paged, instead of the pre-fix silent ``return`` that left zero trace
       an alert was even attempted.

    Before the C1 fix this second assertion failed: the evaluator returned
    early on ``if not matched_rule.channel_ids`` and wrote nothing at all,
    so a fresh install's off-air condition vanished without a trace anyone
    (or any self-test / support bundle) could detect.
    """
    # Import here (not at module scope) so this file's alembic-only tests keep
    # working even if the alerting service package changes its import graph.
    from civiccast.alerting.evaluator import AlertEvaluator
    from civiccast.alerting.store import get_alert_events, get_event_deliveries

    url = f"sqlite:///{tmp_path / 'm0039_fresh_install.sqlite'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "head")

    # ORM models are declared against the "civiccast" schema (Base.metadata.schema),
    # but SQLite cannot enforce schema qualifiers, so the migration ran with
    # version_table_schema=None and created unqualified table names (see
    # alembic/env.py). schema_translate_map is the established repo pattern
    # (civiccast/app.py, civiccast/dr/backup.py, tests/live/test_finalization_retry.py,
    # among others) for pointing schema-qualified ORM queries at an unqualified
    # SQLite database in tests.
    engine = create_engine(url, future=True).execution_options(
        schema_translate_map={"civiccast": None}
    )
    try:
        now = datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)
        with Session(engine) as session:
            evaluator = AlertEvaluator(lambda: Session(engine))
            # No alert channel was ever created — this is the out-of-the-box
            # state; only the 0039 seed's rules exist.
            evaluator.evaluate_channel("government", "STOPPED", now=now)

            firing = get_alert_events(session, state="firing")
            assert len(firing) == 1
            assert firing[0].condition == "off-air"
            assert firing[0].rule_id == "default:off-air"

            deliveries = get_event_deliveries(session, firing[0].event_id)
            assert len(deliveries) == 1, (
                "a fresh, never-configured install must log a visible "
                "suppressed-delivery record, never silently drop the alert"
            )
            assert deliveries[0].status == "suppressed"
            assert deliveries[0].alert_channel_id == "unconfigured"
            assert "off-air" in deliveries[0].last_error
    finally:
        engine.dispose()
