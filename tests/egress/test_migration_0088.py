# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""0088_egress_state_reload_visibility migration.

Drives the real migration through Alembic against a fresh sqlite fixture
DB (not ``create_all`` -- that builds the *current* ORM schema and would
never catch a broken migration file). Covers upgrade, downgrade,
round-trip, single-head, backfill of ``state_entered_at`` from
``updated_at`` for production-shaped existing rows, and that the
pre-existing ``state`` CHECK constraint survives the SQLite batch-mode
table rebuild ``op.batch_alter_table`` performs to add the NOT NULL
column -- same pattern as ``tests/schedule/test_migration_0087.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_PARENT_REVISION = "0087_retention_terms"
_REVISION = "0088_egress_state_reload_visibility"

_NEW_COLUMNS = (
    "state_entered_at",
    "pending_reload_since",
    "pending_reload_deadline",
    "transition_note",
)


def _cfg(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _seed_minimal_egress_states_table(url: str) -> None:
    """Insert a couple of production-shaped ``egress_states`` rows at the
    parent revision, before 0088 runs, so the backfill has real data to
    act on."""
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO egress_states (channel_id, state, "
                    "current_source_label, updated_at) VALUES "
                    "(:channel_id, :state, :label, :updated_at)"
                ),
                [
                    {
                        "channel_id": "gov",
                        "state": "ON_AIR",
                        "label": "Council meeting",
                        "updated_at": "2026-06-05T12:00:00+00:00",
                    },
                    {
                        "channel_id": "public",
                        "state": "STOPPED",
                        "label": None,
                        "updated_at": "2026-06-04T09:30:00+00:00",
                    },
                ],
            )
    finally:
        engine.dispose()


def test_single_head() -> None:
    """This migration's own revision must be the repo-wide single head
    (finalization plan section 7's "single-head assertion" gate) -- it
    re-parented onto 0087_retention_terms, WP-08's own migration."""
    script = ScriptDirectory.from_config(_cfg("sqlite:///:memory:"))
    heads = script.get_heads()
    assert heads == [_REVISION], f"expected a single head {_REVISION!r}, got {heads}"
    assert script.get_revision(_PARENT_REVISION) is not None, (
        f"{_PARENT_REVISION!r} must still be reachable"
    )


def test_upgrade_adds_the_four_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "0088_up.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _PARENT_REVISION)

    engine = create_engine(url, future=True)
    try:
        before = {c["name"] for c in inspect(engine).get_columns("egress_states")}
        for col in _NEW_COLUMNS:
            assert col not in before, f"{col} should not exist before 0088"
    finally:
        engine.dispose()

    command.upgrade(_cfg(url), _REVISION)

    engine = create_engine(url, future=True)
    try:
        after = {c["name"] for c in inspect(engine).get_columns("egress_states")}
        for col in _NEW_COLUMNS:
            assert col in after, f"{col} missing after upgrading to 0088"
    finally:
        engine.dispose()


def test_downgrade_removes_the_four_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "0088_down.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _REVISION)

    command.downgrade(_cfg(url), _PARENT_REVISION)

    engine = create_engine(url, future=True)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("egress_states")}
        for col in _NEW_COLUMNS:
            assert col not in cols, f"{col} still present after downgrade"
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "0088_roundtrip.db"
    url = f"sqlite:///{db_path}"
    cfg = _cfg(url)

    command.upgrade(cfg, _REVISION)
    command.downgrade(cfg, _PARENT_REVISION)
    command.upgrade(cfg, _REVISION)

    engine = create_engine(url, future=True)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("egress_states")}
        for col in _NEW_COLUMNS:
            assert col in cols
    finally:
        engine.dispose()


def test_empty_database_creation_reaches_head(tmp_path: Path) -> None:
    """Finalization plan section 7: 'Empty database creation' gate."""
    db_path = tmp_path / "0088_empty.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), "head")

    engine = create_engine(url, future=True)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("egress_states")}
        for col in _NEW_COLUMNS:
            assert col in cols
    finally:
        engine.dispose()


def test_backfill_state_entered_at_from_updated_at(tmp_path: Path) -> None:
    """An existing row's true state-entry time is not recoverable -- the
    migration backfills ``state_entered_at`` from ``updated_at`` (the
    closest available anchor) for every pre-existing row, and the column
    ends up NOT NULL."""
    db_path = tmp_path / "0088_backfill.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _PARENT_REVISION)
    _seed_minimal_egress_states_table(url)

    command.upgrade(_cfg(url), _REVISION)

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT channel_id, updated_at, state_entered_at, "
                    "pending_reload_since, pending_reload_deadline, transition_note "
                    "FROM egress_states ORDER BY channel_id"
                )
            ).all()
        assert len(rows) == 2
        for row in rows:

            def _as_utc(value: object) -> datetime:
                if isinstance(value, str):
                    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                assert isinstance(value, datetime)
                return value if value.tzinfo else value.replace(tzinfo=UTC)

            assert _as_utc(row.state_entered_at) == _as_utc(row.updated_at)
            # No reload was ever pending for a pre-existing row -- nothing
            # to invent.
            assert row.pending_reload_since is None
            assert row.pending_reload_deadline is None
            assert row.transition_note is None
    finally:
        engine.dispose()

    # NOT NULL: a fresh insert omitting state_entered_at must be rejected.
    engine = create_engine(url, future=True)
    try:
        with engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "INSERT INTO egress_states (channel_id, state, updated_at) "
                        "VALUES ('no-state-entered-at', 'ON_AIR', :updated_at)"
                    ),
                    {"updated_at": "2026-06-05T12:00:00+00:00"},
                )
                raise AssertionError("expected an IntegrityError for a missing state_entered_at")
            except IntegrityError:
                pass
    finally:
        engine.dispose()


def test_state_check_constraint_survives_the_batch_table_rebuild(tmp_path: Path) -> None:
    """SQLite cannot ALTER COLUMN ... SET NOT NULL in place -- ``op.batch_
    alter_table`` rebuilds the whole ``egress_states`` table to apply it.
    The pre-existing ``egress_states_state_check`` CHECK constraint (added
    long before this migration, enforcing the 8-value ``EgressState`` enum)
    must survive that rebuild, not be silently dropped."""
    db_path = tmp_path / "0088_check_constraint.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _REVISION)

    engine = create_engine(url, future=True)
    try:
        with engine.connect() as conn:
            sql = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'egress_states'"
                )
            ).scalar_one()
        assert "egress_states_state_check" in sql
        assert "STOPPED" in sql and "ON_AIR" in sql and "TRANSITIONING" in sql

        with engine.begin() as conn:
            try:
                conn.execute(
                    text(
                        "INSERT INTO egress_states "
                        "(channel_id, state, updated_at, state_entered_at) "
                        "VALUES ('gov', 'BOGUS_STATE', :ts, :ts)"
                    ),
                    {"ts": "2026-06-05T12:00:00+00:00"},
                )
                raise AssertionError(
                    "expected an IntegrityError for a state outside the CHECK enum"
                )
            except IntegrityError:
                pass

        # A legitimate value still inserts fine -- the constraint rejects
        # only invalid values, not everything.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO egress_states "
                    "(channel_id, state, updated_at, state_entered_at) "
                    "VALUES ('gov', 'ON_AIR', :ts, :ts)"
                ),
                {"ts": "2026-06-05T12:00:00+00:00"},
            )
    finally:
        engine.dispose()
