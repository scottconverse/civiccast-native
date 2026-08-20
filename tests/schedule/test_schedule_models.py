# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pydantic validation tests for the schedule models.

The Pydantic surface enforces the same mode↔duration coupling rule the
DB-level CHECK constraint enforces (migration 0003 + 0005): premiere must
carry a duration ≤ 14 days; embargo must not. ``live`` was retired in
migration 0005 (audit-team v0.3.0 ENG-004); Sprint 0.5 live-ingest will
model live events separately. These tests pin that contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from civiccast.schedule.models import (
    SCHEDULE_MODE_EMBARGO,
    SCHEDULE_MODE_PREMIERE,
    SCHEDULE_STATE_SCHEDULED,
    ScheduleItemCreate,
)


def _future() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


class TestScheduleItemCreateMode:
    """Locks: mode must be one of the three known values; everything else 422."""

    def test_live_mode_with_duration_accepts(self) -> None:
        ScheduleItemCreate(
            asset_id="abc-123",
            channel_id="gov-ch12",
            mode=SCHEDULE_MODE_PREMIERE,
            scheduled_at=_future(),
            duration_seconds=3600,
        )  # must not raise

    def test_premiere_mode_with_duration_accepts(self) -> None:
        ScheduleItemCreate(
            asset_id="abc-123",
            channel_id="gov-ch12",
            mode=SCHEDULE_MODE_PREMIERE,
            scheduled_at=_future(),
            duration_seconds=1800,
        )

    def test_embargo_mode_without_duration_accepts(self) -> None:
        ScheduleItemCreate(
            asset_id="abc-123",
            channel_id="gov-ch12",
            mode=SCHEDULE_MODE_EMBARGO,
            scheduled_at=_future(),
        )

    def test_unknown_mode_rejected(self) -> None:
        with pytest.raises(ValidationError, match="mode must be one of"):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode="rerun",  # not a real mode
                scheduled_at=_future(),
                duration_seconds=600,
            )


class TestScheduleItemDurationCoupling:
    """Locks: duration↔mode coupling per spec §1070."""

    def test_live_without_duration_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds is required"):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=_future(),
            )

    def test_premiere_without_duration_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duration_seconds is required"):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=_future(),
            )

    def test_embargo_with_duration_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must be None for embargo"):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_EMBARGO,
                scheduled_at=_future(),
                duration_seconds=3600,  # not allowed
            )

    def test_zero_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=_future(),
                duration_seconds=0,
            )


class TestScheduleItemTimezone:
    """Locks: scheduled_at must be timezone-aware. Naive datetimes 422."""

    def test_naive_scheduled_at_rejected(self) -> None:
        naive = datetime(2026, 5, 15, 18, 0, 0)  # no tzinfo
        with pytest.raises(ValidationError, match="timezone-aware"):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                scheduled_at=naive,
                duration_seconds=600,
            )

    def test_aware_scheduled_at_in_non_utc_tz_accepts(self) -> None:
        # Operator might submit a Pacific-time datetime; the API accepts
        # any aware tz and the store normalizes to UTC at persistence time.
        from datetime import timezone

        pacific = timezone(timedelta(hours=-7))
        ScheduleItemCreate(
            asset_id="abc-123",
            channel_id="gov-ch12",
            mode=SCHEDULE_MODE_PREMIERE,
            scheduled_at=datetime(2026, 5, 15, 18, 0, 0, tzinfo=pacific),
            duration_seconds=600,
        )


class TestScheduleItemSlugPatterns:
    """Locks: asset_id and channel_id slug patterns."""

    def test_asset_id_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleItemCreate(
                asset_id="ABC-123",  # uppercase
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_EMBARGO,
                scheduled_at=_future(),
            )

    def test_channel_id_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleItemCreate(
                asset_id="abc-123",
                channel_id="GOV-CH12",  # uppercase
                mode=SCHEDULE_MODE_EMBARGO,
                scheduled_at=_future(),
            )


class TestStateMachineConstants:
    """Locks: state-machine constants are stable. The DB CHECK constraint
    in migration 0003 hard-codes these values; they cannot change without
    a follow-up migration."""

    def test_default_state_is_scheduled(self) -> None:
        assert SCHEDULE_STATE_SCHEDULED == "scheduled"

    def test_modes_stable(self) -> None:
        # Audit-team v0.3.0 ENG-004: 'live' was retired from the enum
        # in migration 0005. Surviving modes are premiere + embargo.
        assert SCHEDULE_MODE_PREMIERE == "premiere"
        assert SCHEDULE_MODE_EMBARGO == "embargo"


class TestAssetStateWidening:
    """Locks: Sprint 0.4 Slice 1 Commit 2 widens ``_ASSET_STATES`` to
    include ``recorded``. The DB CHECK constraint is widened by migration
    0006 (real-Postgres-tested in tests/schedule/test_real_postgres.py).
    The SA ``__table_args__`` CheckConstraint string is widened in the
    same commit so SQLite test paths exercise the widened CHECK via
    ``Base.metadata.create_all`` -- this test pins that surface.
    """

    def test_recorded_state_is_in_the_asset_states_tuple(self) -> None:
        from civiccast.schedule.models import (
            _ASSET_STATES,
            ASSET_STATE_RECORDED,
        )

        assert ASSET_STATE_RECORDED == "recorded"
        assert ASSET_STATE_RECORDED in _ASSET_STATES
        # The four pre-existing states must remain.
        assert "pending_ingest" in _ASSET_STATES
        assert "ingesting" in _ASSET_STATES
        assert "validated" in _ASSET_STATES
        assert "rejected" in _ASSET_STATES
        assert len(_ASSET_STATES) == 5

    def test_sa_model_checkconstraint_string_includes_recorded(self) -> None:
        from civiccast.schedule.models import Asset

        constraint_strings = [
            str(c.sqltext)
            for c in Asset.__table__.constraints
            if hasattr(c, "sqltext") and c.name == "assets_state_check"
        ]
        assert len(constraint_strings) == 1, (
            "Expected exactly one assets_state_check constraint on the "
            f"Asset table; found {len(constraint_strings)}."
        )
        constraint_sql = constraint_strings[0]
        # The widened CHECK must name every state including 'recorded'.
        for state in ("pending_ingest", "ingesting", "validated", "rejected", "recorded"):
            assert state in constraint_sql, (
                f"State {state!r} missing from assets_state_check CHECK "
                f"constraint SQL: {constraint_sql}"
            )

    def test_sqlite_create_all_accepts_recorded_asset(self, engine) -> None:
        """SQLite test path exercises the widened CHECK via the SA model.

        On Postgres the CHECK is enforced by migration 0006. On SQLite,
        Base.metadata.create_all builds the table from the SA
        ``__table_args__``, so the widened CHECK constraint ships
        identically without running the Alembic migration.

        Uses the conftest.py:engine fixture (bind_engine + create_all
        with the proven civiccast-schema-on-SQLite plumbing) rather than
        building a fresh engine here.
        """
        from sqlalchemy.orm import Session

        from civiccast.schedule.models import Asset

        with Session(bind=engine) as sess:
            sess.add(
                Asset(
                    asset_id="sqlite-recorded",
                    title="SQLite recorded asset",
                    state="recorded",
                )
            )
            sess.commit()

            row = sess.get(Asset, "sqlite-recorded")
            assert row is not None
            assert row.state == "recorded"
