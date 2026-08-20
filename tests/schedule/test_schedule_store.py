# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""PostgresScheduleStore unit tests against ephemeral SQLite.

The DB-level conflict-detection contract is asserted exclusively against
real Postgres (testcontainers, in ``tests/schedule/test_real_postgres.py``).
This module exercises everything else: create / list / get / cancel,
state transitions, and the structural CHECK constraints.

SQLite cannot enforce the btree_gist EXCLUDE constraint — overlapping
premiere events on the same channel WILL succeed here. Don't write
conflict-rejection assertions against this fixture; write them against
the real-Postgres fixture instead. (``live`` was retired in migration
0005; only premiere occupies a time range.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from civiccast.schedule.models import (
    _SCHEDULE_STATES,
    SCHEDULE_MODE_EMBARGO,
    SCHEDULE_MODE_PREMIERE,
    SCHEDULE_STATE_CANCELLED,
    SCHEDULE_STATE_PUBLISHED,
    SCHEDULE_STATE_SCHEDULED,
    ScheduleItem,
    ScheduleItemCreate,
)
from civiccast.schedule.store import (
    PostgresScheduleStore,
    ScheduleItemNotFoundError,
)


def _future(hours: int = 1) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


def _payload(
    *,
    asset_id: str = "abc-123",
    channel_id: str = "gov-ch12",
    mode: str = SCHEDULE_MODE_PREMIERE,
    scheduled_at: datetime | None = None,
    duration_seconds: int | None = 3600,
    notes: str | None = None,
) -> ScheduleItemCreate:
    if mode == SCHEDULE_MODE_EMBARGO:
        duration_seconds = None
    return ScheduleItemCreate(
        asset_id=asset_id,
        channel_id=channel_id,
        mode=mode,
        scheduled_at=scheduled_at or _future(),
        duration_seconds=duration_seconds,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# TestCreate
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_returns_response_with_uuid_and_default_state(
        self, schedule_session_factory
    ) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        result = store.create(_payload())
        assert result.id is not None
        assert result.state == SCHEDULE_STATE_SCHEDULED
        assert result.mode == SCHEDULE_MODE_PREMIERE
        assert result.asset_id == "abc-123"
        assert result.channel_id == "gov-ch12"

    def test_create_normalizes_scheduled_at_to_utc(self, schedule_session_factory) -> None:
        from datetime import timezone

        pacific = timezone(timedelta(hours=-7))
        when_pacific = datetime(2026, 5, 15, 11, 0, 0, tzinfo=pacific)
        store = PostgresScheduleStore(schedule_session_factory)
        result = store.create(_payload(scheduled_at=when_pacific))
        # 11:00 Pacific is 18:00 UTC.
        assert result.scheduled_at.utcoffset() == timedelta(0)
        assert result.scheduled_at.hour == 18

    def test_create_embargo_keeps_duration_null(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        result = store.create(_payload(mode=SCHEDULE_MODE_EMBARGO))
        assert result.mode == SCHEDULE_MODE_EMBARGO
        assert result.duration_seconds is None


# ---------------------------------------------------------------------------
# TestList
# ---------------------------------------------------------------------------


class TestList:
    def test_list_empty_returns_empty(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        assert store.list() == []

    def test_list_returns_chronological(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        # Insert out of order.
        store.create(_payload(scheduled_at=_future(hours=4)))
        store.create(_payload(scheduled_at=_future(hours=1), channel_id="edu-ch14"))
        store.create(_payload(scheduled_at=_future(hours=2), channel_id="gov-ch12-alt"))
        results = store.list()
        assert len(results) == 3
        assert results[0].scheduled_at < results[1].scheduled_at < results[2].scheduled_at

    def test_list_filtered_by_channel(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        store.create(_payload(channel_id="gov-ch12", scheduled_at=_future(hours=1)))
        store.create(_payload(channel_id="edu-ch14", scheduled_at=_future(hours=2)))
        store.create(_payload(channel_id="gov-ch12", scheduled_at=_future(hours=3)))
        gov = store.list(channel_id="gov-ch12")
        assert {r.channel_id for r in gov} == {"gov-ch12"}
        assert len(gov) == 2

    def test_list_filtered_by_state(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        first = store.create(_payload(scheduled_at=_future(hours=1)))
        store.create(_payload(channel_id="edu-ch14", scheduled_at=_future(hours=2)))
        store.cancel(first.id)
        scheduled = store.list(states=(SCHEDULE_STATE_SCHEDULED,))
        cancelled = store.list(states=(SCHEDULE_STATE_CANCELLED,))
        assert len(scheduled) == 1
        assert len(cancelled) == 1
        assert cancelled[0].id == first.id

    def test_list_unknown_state_raises_value_error(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        with pytest.raises(ValueError, match="Unknown schedule state"):
            store.list(states=("aired",))


# ---------------------------------------------------------------------------
# TestGet
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_returns_item_when_present(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())
        fetched = store.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_returns_none_when_absent(self, schedule_session_factory) -> None:
        import uuid

        store = PostgresScheduleStore(schedule_session_factory)
        assert store.get(uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# TestCancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_transitions_scheduled_to_cancelled(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())
        assert created.state == SCHEDULE_STATE_SCHEDULED
        cancelled = store.cancel(created.id)
        assert cancelled.state == SCHEDULE_STATE_CANCELLED
        assert cancelled.id == created.id

    def test_cancel_idempotent_on_already_cancelled(self, schedule_session_factory) -> None:
        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())
        store.cancel(created.id)
        # Second cancel must not raise; returns the current state.
        result = store.cancel(created.id)
        assert result.state == SCHEDULE_STATE_CANCELLED

    def test_cancel_missing_raises(self, schedule_session_factory) -> None:
        import uuid

        store = PostgresScheduleStore(schedule_session_factory)
        with pytest.raises(ScheduleItemNotFoundError):
            store.cancel(uuid.uuid4())

    def test_cancel_transitions_published_to_cancelled(self, schedule_session_factory) -> None:
        """Commit-to-Air state machine (spec test f): cancel must work from
        BOTH ``scheduled`` and ``published`` — a committed/auto-approved
        airing can still be pulled."""
        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())
        store.mark_published([created.id])
        published = store.get(created.id)
        assert published is not None
        assert published.state == SCHEDULE_STATE_PUBLISHED
        cancelled = store.cancel(created.id)
        assert cancelled.state == SCHEDULE_STATE_CANCELLED

    def test_mark_published_returns_rows_transitioned(self, schedule_session_factory) -> None:
        """PE-2: mark_published reports how many rows it actually flipped.

        The single-item ``UPDATE ... WHERE state='scheduled'`` is the
        Commit-to-Air concurrency gate — a scheduled row flips (returns 1), and
        anything already off ``scheduled`` (already published, unknown id) or an
        empty batch matches nothing (returns 0), which is how CommitService
        detects a lost race and refuses to double-dispatch.
        """
        import uuid as _uuid

        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())
        assert store.mark_published([created.id]) == 1
        # Second call: the row is already published, WHERE clause matches nothing.
        assert store.mark_published([created.id]) == 0
        # Unknown id: nothing to flip.
        assert store.mark_published([_uuid.uuid4()]) == 0
        # Empty batch: 0, no DB round-trip.
        assert store.mark_published([]) == 0

    def test_commit_to_air_is_atomic_flip_plus_report(self, schedule_session_factory) -> None:
        """PE-2 crash-safety: commit_to_air flips scheduled->published AND writes
        the pending report in ONE transaction, or does neither — an item can
        never end up published without a durable approval report, and a lost
        race persists no orphan report."""
        from civiccast.schedule.commit_models import CommitToAirReport

        store = PostgresScheduleStore(schedule_session_factory)
        created = store.create(_payload())

        def _report(report_id: str) -> CommitToAirReport:
            now = datetime.now(UTC)
            return CommitToAirReport(
                report_id=report_id,
                channel_id="gov-ch12",
                occurrence_id="occ-1",
                schedule_item_id=str(created.id),
                asset_id="abc-123",
                title="A Program",
                scheduled_at=_future(),
                duration_seconds=3600,
                approved_by_operator_id="dana",
                approved_at=now,
                created_at=now,
                updated_at=now,
            )

        # Win: the flip and the report land together.
        assert store.commit_to_air(created.id, _report("ctar_win")) is True
        won = store.get(created.id)
        assert won is not None and won.state == SCHEDULE_STATE_PUBLISHED
        assert store.get_commit_report("ctar_win") is not None

        # Loss: already published -> False, and NOTHING new is written (no orphan
        # report, item unchanged).
        assert store.commit_to_air(created.id, _report("ctar_loss")) is False
        assert store.get_commit_report("ctar_loss") is None
        assert store.get(created.id).state == SCHEDULE_STATE_PUBLISHED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# TestStructuralCheckConstraints
# ---------------------------------------------------------------------------


class TestStructuralCheckConstraints:
    """Locks: the SA-level CheckConstraints fire on direct row inserts.

    These guard against a future change that would let the Pydantic
    validators be bypassed (e.g., a new code path that builds
    ``ScheduleItem`` rows directly). The DB-level constraint is the last
    line of defense.
    """

    def test_invalid_mode_rejected(self, schedule_session_factory) -> None:
        from sqlalchemy.exc import IntegrityError

        from civiccast.schedule.models import ScheduleItem

        with schedule_session_factory() as sess:
            sess.add(
                ScheduleItem(
                    asset_id="abc",
                    channel_id="gov-ch12",
                    mode="rerun",  # not allowed
                    scheduled_at=_future(),
                    duration_seconds=3600,
                )
            )
            with pytest.raises(IntegrityError):
                sess.commit()

    def test_embargo_with_duration_rejected_at_db(self, schedule_session_factory) -> None:
        from sqlalchemy.exc import IntegrityError

        from civiccast.schedule.models import ScheduleItem

        with schedule_session_factory() as sess:
            sess.add(
                ScheduleItem(
                    asset_id="abc",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_EMBARGO,
                    scheduled_at=_future(),
                    duration_seconds=3600,  # not allowed for embargo
                )
            )
            with pytest.raises(IntegrityError):
                sess.commit()

    def test_premiere_without_duration_rejected_at_db(self, schedule_session_factory) -> None:
        from sqlalchemy.exc import IntegrityError

        from civiccast.schedule.models import ScheduleItem

        with schedule_session_factory() as sess:
            sess.add(
                ScheduleItem(
                    asset_id="abc",
                    channel_id="gov-ch12",
                    mode=SCHEDULE_MODE_PREMIERE,
                    scheduled_at=_future(),
                    duration_seconds=None,  # not allowed for premiere
                )
            )
            with pytest.raises(IntegrityError):
                sess.commit()


# ---------------------------------------------------------------------------
# TestQA005FindConflictingRelaxedState — unit-level lock on the QA-005 retry
# ---------------------------------------------------------------------------


class TestQA005FindConflictingRelaxedState:
    """Locks: ``_find_conflicting`` returns ``None`` under the strict
    default-state filter when the conflicting row has transitioned out
    of ``scheduled``, and returns the conflicting row when called with
    the broadened ``states=_SCHEDULE_STATES`` filter.

    Real-Postgres race coverage (EXCLUDE rejection + concurrent cancel
    between rejection and lookup) lives in
    :mod:`tests.schedule.test_real_postgres`. This module exercises the
    helper's filter behavior in isolation so a regression in the strict-
    vs-relaxed dispatch is caught at unit-test speed.
    """

    def _seed_premiere(
        self,
        schedule_session_factory,
        *,
        state: str,
        scheduled_at: datetime,
    ) -> ScheduleItem:
        """Insert a premiere row directly via the SA model so we can
        seed states the public ``store.create`` path won't produce
        (e.g., a freshly-inserted row in ``cancelled`` state)."""
        with schedule_session_factory() as sess:
            row = ScheduleItem(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                state=state,
                scheduled_at=scheduled_at,
                scheduled_at_end=scheduled_at + timedelta(seconds=3600),
                duration_seconds=3600,
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            return row

    def test_strict_filter_misses_cancelled_row(self, schedule_session_factory) -> None:
        target = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)
        self._seed_premiere(
            schedule_session_factory,
            state=SCHEDULE_STATE_CANCELLED,
            scheduled_at=target,
        )
        store = PostgresScheduleStore(schedule_session_factory)
        result = store._find_conflicting(
            channel_id="gov-ch12",
            scheduled_at=target,
            duration_seconds=3600,
        )
        # Default states=(SCHEDULE_STATE_SCHEDULED,) misses the cancelled row.
        assert result is None

    def test_relaxed_filter_returns_cancelled_row(self, schedule_session_factory) -> None:
        target = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)
        seeded = self._seed_premiere(
            schedule_session_factory,
            state=SCHEDULE_STATE_CANCELLED,
            scheduled_at=target,
        )
        store = PostgresScheduleStore(schedule_session_factory)
        result = store._find_conflicting(
            channel_id="gov-ch12",
            scheduled_at=target,
            duration_seconds=3600,
            states=_SCHEDULE_STATES,
        )
        assert result is not None
        assert result.id == seeded.id
        # Response carries the state so the caller can compose a
        # state-aware error message ("was cancelled during your request").
        assert result.state == SCHEDULE_STATE_CANCELLED

    def test_relaxed_filter_returns_published_row(self, schedule_session_factory) -> None:
        target = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)
        seeded = self._seed_premiere(
            schedule_session_factory,
            state=SCHEDULE_STATE_PUBLISHED,
            scheduled_at=target,
        )
        store = PostgresScheduleStore(schedule_session_factory)
        result = store._find_conflicting(
            channel_id="gov-ch12",
            scheduled_at=target,
            duration_seconds=3600,
            states=_SCHEDULE_STATES,
        )
        assert result is not None
        assert result.id == seeded.id
        assert result.state == SCHEDULE_STATE_PUBLISHED

    def test_strict_filter_still_returns_scheduled_row(self, schedule_session_factory) -> None:
        # Sanity: the default strict filter still works for the
        # common case (conflicting row is in scheduled state).
        target = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)
        self._seed_premiere(
            schedule_session_factory,
            state=SCHEDULE_STATE_SCHEDULED,
            scheduled_at=target,
        )
        store = PostgresScheduleStore(schedule_session_factory)
        result = store._find_conflicting(
            channel_id="gov-ch12",
            scheduled_at=target,
            duration_seconds=3600,
        )
        assert result is not None
        assert result.state == SCHEDULE_STATE_SCHEDULED


class TestPublishedBlocksOverlap:
    """Locks: ``_find_conflicting``'s DEFAULT state filter now includes
    ``published`` (was: ``(SCHEDULE_STATE_SCHEDULED,)`` only), so a
    scheduled premiere that overlaps an already-published, airing
    premiere on the same channel is detected as a conflict without the
    caller having to pass the broadened ``states=`` kwarg. Migration
    0071_published_blocks_overlap rebuilds the real-Postgres EXCLUDE
    constraint to match (covered in ``tests/schedule/test_real_postgres.py``);
    this is the app-level (SQLite) half of the same contract.
    """

    def _seed_premiere(
        self,
        schedule_session_factory,
        *,
        state: str,
        scheduled_at: datetime,
    ) -> ScheduleItem:
        with schedule_session_factory() as sess:
            row = ScheduleItem(
                asset_id="abc-123",
                channel_id="gov-ch12",
                mode=SCHEDULE_MODE_PREMIERE,
                state=state,
                scheduled_at=scheduled_at,
                scheduled_at_end=scheduled_at + timedelta(seconds=3600),
                duration_seconds=3600,
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            return row

    def test_default_filter_detects_overlapping_published_row(
        self, schedule_session_factory
    ) -> None:
        target = datetime(2026, 5, 15, 18, 0, 0, tzinfo=UTC)
        seeded = self._seed_premiere(
            schedule_session_factory,
            state=SCHEDULE_STATE_PUBLISHED,
            scheduled_at=target,
        )
        store = PostgresScheduleStore(schedule_session_factory)
        result = store._find_conflicting(
            channel_id="gov-ch12",
            scheduled_at=target,
            duration_seconds=3600,
        )
        assert result is not None
        assert result.id == seeded.id
        assert result.state == SCHEDULE_STATE_PUBLISHED
