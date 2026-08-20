# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Reversibility tests for the schedule module's first Alembic migration.

Mirrors tests/db/test_alembic_env.py:32-35 + :122-146 (Pattern C). Asserts the
`assets` table appears after `command.upgrade(cfg, "head")` against an
ephemeral SQLite DB and is gone after `command.downgrade(cfg, "base")`.

SQLite silently ignores the `civiccast.` schema qualifier; the table lands as
plain `assets`, which is fine for reversibility wiring. Schema-namespace
verification on a real Postgres dialect lives in test_real_postgres.py.

Per plan.md §4 `tests/schedule/test_migration_reversibility.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

# Importing the schedule package's models forces SA model registration with
# Base.metadata; required for the migration's autogen-shape parity even when
# the migration itself is hand-written.
import civiccast.schedule.models  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestUpgradeCreatesAssetsTable:
    def test_upgrade_head_creates_assets_table(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            assert inspect(eng).has_table("assets")
        finally:
            eng.dispose()


class TestDowngradeDropsAssetsTable:
    def test_downgrade_base_drops_assets_table(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            assert not inspect(eng).has_table("assets")
        finally:
            eng.dispose()


class TestUpgradeDowngradeUpgradeCycle:
    """Two full round-trips prove the migration is genuinely reversible
    (not just one-shot upgrade-then-drop). Catches asymmetric DDL bugs."""

    def test_two_full_round_trips_succeed(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            assert not inspect(eng).has_table("assets")
        finally:
            eng.dispose()


# Expected columns of commit_to_air_reports (migration 0040, S4 slice 1).
_COMMIT_REPORT_COLUMNS = {
    "report_id",
    "channel_id",
    "occurrence_id",
    "schedule_item_id",
    "asset_id",
    "title",
    "scheduled_at",
    "duration_seconds",
    "approved_by_operator_id",
    "approved_at",
    "conflicts_found",
    "gaps_found",
    "dispatch_status",
    "dispatch_error_detail",
    "dispatch_timestamp",
    "operator_notes",
    # Added by migration 0041 (S4 slice 5 rollback audit).
    "rollback_reason",
    "rolled_back_at",
    "created_at",
    "updated_at",
}


class TestCommitToAirReportsMigration:
    """0040_commit_to_air_reports adds the table (with its full column set and
    index) on upgrade and removes it on a single-step downgrade, leaving the
    rest of the chain intact. Reflection-based — not merely "no exception"."""

    def test_upgrade_head_creates_table_with_all_columns(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert insp.has_table("commit_to_air_reports")
            cols = {c["name"] for c in insp.get_columns("commit_to_air_reports")}
            assert cols == _COMMIT_REPORT_COLUMNS
            index_names = {ix["name"] for ix in insp.get_indexes("commit_to_air_reports")}
            assert "commit_to_air_reports_channel_approved_idx" in index_names
        finally:
            eng.dispose()

    def test_downgrade_to_0039_drops_the_table(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        # Step back to before 0040 (through 0041); the table must be gone
        # while the rest of the schema (e.g. assets) survives.
        command.downgrade(cfg, "0039_alerting_and_sinkhealth")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert not insp.has_table("commit_to_air_reports")
            assert insp.has_table("assets")
        finally:
            eng.dispose()


class TestCommitRollbackFieldsMigration:
    """0041_commit_rollback_fields adds rollback_reason + rolled_back_at on
    upgrade and removes only those two on a single-step downgrade — the table
    and its other columns survive. Reflection-based."""

    def test_upgrade_head_adds_rollback_columns(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            cols = {c["name"] for c in inspect(eng).get_columns("commit_to_air_reports")}
            assert {"rollback_reason", "rolled_back_at"} <= cols
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_rollback_columns(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        # Step back exactly one revision (0041 -> 0040): the two columns go,
        # the table and its remaining columns stay.
        command.downgrade(cfg, "0040_commit_to_air_reports")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert insp.has_table("commit_to_air_reports")
            cols = {c["name"] for c in insp.get_columns("commit_to_air_reports")}
            assert "rollback_reason" not in cols
            assert "rolled_back_at" not in cols
            assert "report_id" in cols  # the rest of the table survives
        finally:
            eng.dispose()


class TestSchedulingAutomationMigration:
    """0043_scheduling_automation creates the three S18 auto-scheduling tables
    on upgrade and drops exactly those on a single-step downgrade to 0042 — the
    rest of the schema (commit reports, assets) survives. Reflection-based."""

    _TABLES = ("saved_searches", "schedule_blocks", "auto_schedule_rules")

    def test_upgrade_head_creates_the_three_tables_and_indexes(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table)
            block_idx = {ix["name"] for ix in insp.get_indexes("schedule_blocks")}
            assert "schedule_blocks_channel_enabled_idx" in block_idx
            rule_idx = {ix["name"] for ix in insp.get_indexes("auto_schedule_rules")}
            assert "auto_schedule_rules_channel_enabled_idx" in rule_idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        # Step back exactly one revision (0043 -> 0042): the three tables go,
        # the rest of the schema stays.
        command.downgrade(cfg, "0042_takeover_audit_and_command_action")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table)
            assert insp.has_table("commit_to_air_reports")
            assert insp.has_table("assets")
        finally:
            eng.dispose()


class TestMediaIntegrityColumnsMigration:
    """0062_media_integrity_columns (4.0 scope item 5) adds four columns +
    a CHECK constraint + an index to ``assets`` on upgrade, and removes
    exactly those on a single-step downgrade to 0061 — the table and its
    pre-existing columns survive. Uses batch mode (see the migration's own
    comment) because SQLite can't ALTER a CHECK constraint in place;
    reflection-based assertions confirm that path actually works, not just
    "no exception."
    """

    _NEW_COLUMNS = (
        "content_hash",
        "thumbnail_path",
        "file_status",
        "file_status_checked_at",
    )

    def test_upgrade_head_adds_columns_constraint_and_index(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            cols = {c["name"] for c in insp.get_columns("assets")}
            assert cols >= set(self._NEW_COLUMNS)
            index_names = {ix["name"] for ix in insp.get_indexes("assets")}
            assert "assets_content_hash_idx" in index_names
        finally:
            eng.dispose()

    def test_file_status_defaults_to_ok_for_pre_existing_rows(self, tmp_path: Path) -> None:
        """A row inserted with no file_status opinion gets 'ok', not NULL —
        so migrating an existing library doesn't retroactively flag every
        asset as missing."""
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO assets (asset_id, title, state, retention_policy, version) "
                        "VALUES ('legacy-1', 'Legacy', 'validated', 'default', 1)"
                    )
                )
                row = conn.execute(
                    text("SELECT file_status FROM assets WHERE asset_id = 'legacy-1'")
                ).one()
            assert row[0] == "ok"
        finally:
            eng.dispose()

    def test_file_status_check_constraint_rejects_unknown_values(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with pytest.raises(IntegrityError), eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO assets "
                        "(asset_id, title, state, retention_policy, file_status, version) "
                        "VALUES ('bad-1', 'Bad', 'validated', 'default', 'bogus', 1)"
                    )
                )
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_new_columns(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0061_control_room_mode_gate")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            assert insp.has_table("assets")
            cols = {c["name"] for c in insp.get_columns("assets")}
            assert not (set(self._NEW_COLUMNS) & cols)
            assert "asset_id" in cols  # the rest of the table survives
        finally:
            eng.dispose()


class TestGrandfatherScheduledToPublishedMigration:
    """0070_grandfather_scheduled_to_published (Commit-to-Air enforcement,
    owner decision 2026-07-08): a data migration that flips every
    pre-existing ``scheduled`` schedule_items row to ``published`` at
    upgrade time, so a station mid-flight doesn't have its already-approved
    on-air schedule silently stop airing once the gate starts enforcing.
    """

    def test_upgrade_flips_pre_existing_scheduled_rows_to_published(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        # Seed at the migration BEFORE 0070 so the row exists as 'scheduled'
        # when 0070 runs.
        command.upgrade(cfg, "0068_migrate_batches")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO assets (asset_id, title, state, retention_policy, version) "
                        "VALUES ('legacy-1', 'Legacy', 'validated', 'default', 1)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO schedule_items "
                        "(id, asset_id, channel_id, mode, state, scheduled_at, "
                        "duration_seconds, created_at) "
                        "VALUES ('11111111-1111-1111-1111-111111111111', 'legacy-1', "
                        "'gov', 'premiere', 'scheduled', '2026-07-01 18:00:00', "
                        "1800, '2026-06-01 00:00:00')"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO schedule_items "
                        "(id, asset_id, channel_id, mode, state, scheduled_at, "
                        "duration_seconds, created_at) "
                        "VALUES ('22222222-2222-2222-2222-222222222222', 'legacy-1', "
                        "'gov', 'premiere', 'cancelled', '2026-07-02 18:00:00', "
                        "1800, '2026-06-01 00:00:00')"
                    )
                )
        finally:
            eng.dispose()

        command.upgrade(cfg, "head")

        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with eng.begin() as conn:
                rows = conn.execute(text("SELECT id, state FROM schedule_items ORDER BY id")).all()
                states: dict[str, str] = {row[0]: row[1] for row in rows}
            assert states["11111111-1111-1111-1111-111111111111"] == "published"
            # A cancelled row is untouched — the migration only flips 'scheduled'.
            assert states["22222222-2222-2222-2222-222222222222"] == "cancelled"
        finally:
            eng.dispose()

    def test_downgrade_is_a_documented_no_op(self, tmp_path: Path) -> None:
        """Downgrade cannot know which published rows were manually approved
        vs. auto-approved by autoschedule vs. grandfathered by this very
        migration — a no-op is the honest, documented behavior."""
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        # Must not raise.
        command.downgrade(cfg, "0068_migrate_batches")
