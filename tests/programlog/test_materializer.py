# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Program-log materializer tests (cable automation CA-1).

The materializer turns enabled slots into real premiere ``schedule_items``
over a rolling horizon, idempotently, and records every skip with an honest
reason instead of crashing the loop.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 -- ATTACH ':memory:' AS civiccast on SQLite connect
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.programlog.materializer import (
    ProgramLogMaterializer,
    ProgramLogSettings,
)
from civiccast.programlog.models import ProgramSlot
from civiccast.programlog.store import PostgresProgramLogStore

_NOW = datetime(2026, 6, 12, 6, 0, tzinfo=UTC)


class _FakeScheduleStore:
    """Schedule-store double recording creates; optionally raising."""

    def __init__(self, *, conflict_on: set[datetime] | None = None) -> None:
        self.created: list[object] = []
        self.cancelled: list[object] = []
        self._conflict_on = conflict_on or set()
        self._next_id = 0

    def create(self, payload):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        from civiccast.schedule.store import ScheduleConflictError

        if payload.scheduled_at in self._conflict_on:
            raise ScheduleConflictError(
                f"Schedule conflict at {payload.scheduled_at.isoformat()}.",
                conflicting_item=None,
            )
        self._next_id += 1
        self.created.append(payload)
        return SimpleNamespace(id=f"sched-{self._next_id}")

    def cancel(self, schedule_id):  # type: ignore[no-untyped-def]
        self.cancelled.append(schedule_id)


class _FakeAssetResolver:
    """Asset-resolver double: known asset ids map to a duration."""

    def __init__(self, durations: dict[str, int | None]) -> None:
        self._durations = durations

    def __call__(self, asset_id: str):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        if asset_id not in self._durations:
            return None
        return SimpleNamespace(
            duration_seconds=self._durations[asset_id],
            state="validated",
            file_path=f"C:/media/{asset_id}.mp4",
        )


@contextmanager
def _sqlite_store() -> Iterator[PostgresProgramLogStore]:
    engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        yield PostgresProgramLogStore(session_factory)
    finally:
        reset_engine()
        engine.dispose()


def _slot(store: PostgresProgramLogStore, **overrides) -> ProgramSlot:  # type: ignore[no-untyped-def]
    defaults = {
        "slot_id": "cps_council",
        "channel_id": "public",
        "asset_id": "council-2026-06-10",
        "title_override": None,
        "recurrence": "daily",
        "first_start_at": datetime(2026, 6, 12, 19, 0, tzinfo=UTC),
        "duration_seconds": None,
        "repeat_until": None,
        "enabled": True,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return store.create_slot(ProgramSlot(**defaults))  # type: ignore[arg-type]


class TestMaterializer:
    def _materializer(
        self,
        store: PostgresProgramLogStore,
        schedule_store: _FakeScheduleStore,
        *,
        durations: dict[str, int | None] | None = None,
        horizon_hours: float = 72.0,
    ) -> ProgramLogMaterializer:
        return ProgramLogMaterializer(
            store,
            schedule_store,
            _FakeAssetResolver(durations or {"council-2026-06-10": 3600}),
            settings=ProgramLogSettings(
                mode="inline", poll_seconds=300.0, horizon_hours=horizon_hours
            ),
        )

    def test_materializes_premiere_items_idempotently(self) -> None:
        with _sqlite_store() as store:
            _slot(store)
            schedule = _FakeScheduleStore()
            materializer = self._materializer(store, schedule)

            first = materializer.run_once(now=_NOW)
            second = materializer.run_once(now=_NOW)

            # 72h horizon from 06:00 on the 12th covers the 12th, 13th, 14th 19:00.
            assert len(first) == 3
            assert second == []
            assert len(schedule.created) == 3
            payload = schedule.created[0]
            assert payload.mode == "premiere"
            assert payload.channel_id == "public"
            assert payload.duration_seconds == 3600
            assert payload.scheduled_at == datetime(2026, 6, 12, 19, 0, tzinfo=UTC)
            occurrences = store.list_occurrences(slot_id="cps_council")
            assert [o.status for o in occurrences] == ["scheduled"] * 3
            assert all(o.schedule_item_id for o in occurrences)

    def test_conflict_is_recorded_not_raised(self) -> None:
        with _sqlite_store() as store:
            _slot(store)
            schedule = _FakeScheduleStore(conflict_on={datetime(2026, 6, 13, 19, 0, tzinfo=UTC)})
            materializer = self._materializer(store, schedule)

            processed = materializer.run_once(now=_NOW)

            statuses = {o.occurrence_start: o.status for o in processed}
            assert statuses[datetime(2026, 6, 13, 19, 0, tzinfo=UTC)] == "skipped_conflict"
            assert statuses[datetime(2026, 6, 12, 19, 0, tzinfo=UTC)] == "scheduled"
            skipped = next(
                o
                for o in store.list_occurrences(slot_id="cps_council")
                if o.status == "skipped_conflict"
            )
            assert "conflict" in skipped.detail.lower()
            # Idempotent: a second run does not retry the recorded skip.
            assert materializer.run_once(now=_NOW) == []

    def test_unknown_asset_is_recorded_as_skipped_asset(self) -> None:
        with _sqlite_store() as store:
            _slot(store, asset_id="never-uploaded", recurrence="once")
            schedule = _FakeScheduleStore()
            materializer = self._materializer(store, schedule)

            processed = materializer.run_once(now=_NOW)

            assert len(processed) == 1
            assert processed[0].status == "skipped_asset"
            assert schedule.created == []

    def test_explicit_duration_overrides_asset_duration(self) -> None:
        with _sqlite_store() as store:
            _slot(store, duration_seconds=1800, recurrence="once")
            schedule = _FakeScheduleStore()
            materializer = self._materializer(store, schedule)

            materializer.run_once(now=_NOW)

            assert schedule.created[0].duration_seconds == 1800

    def test_disable_slot_cancels_only_future_items(self) -> None:
        with _sqlite_store() as store:
            _slot(store)
            schedule = _FakeScheduleStore()
            materializer = self._materializer(store, schedule)
            materializer.run_once(now=_NOW)

            # One occurrence is in the past by the time the slot is disabled.
            later = datetime(2026, 6, 13, 0, 0, tzinfo=UTC)
            cancelled = materializer.disable_slot("cps_council", now=later)

            assert store.get_slot("cps_council").enabled is False  # type: ignore[union-attr]
            future_starts = {o.occurrence_start for o in cancelled}
            assert future_starts == {
                datetime(2026, 6, 13, 19, 0, tzinfo=UTC),
                datetime(2026, 6, 14, 19, 0, tzinfo=UTC),
            }
            assert len(schedule.cancelled) == 2
            statuses = {
                o.occurrence_start: o.status for o in store.list_occurrences(slot_id="cps_council")
            }
            assert statuses[datetime(2026, 6, 12, 19, 0, tzinfo=UTC)] == "scheduled"
            assert statuses[datetime(2026, 6, 13, 19, 0, tzinfo=UTC)] == "cancelled"

    def test_settings_from_env_validates_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_PROGRAM_LOG_WORKER", "always")
        with pytest.raises(ValueError, match="CIVICCAST_PROGRAM_LOG_WORKER"):
            ProgramLogSettings.from_env()
        monkeypatch.setenv("CIVICCAST_PROGRAM_LOG_WORKER", "off")
        monkeypatch.setenv("CIVICCAST_PROGRAM_LOG_HORIZON_HOURS", "24")
        settings = ProgramLogSettings.from_env()
        assert settings.mode == "off"
        assert settings.horizon_hours == 24.0


class TestStoreRoundTrip:
    def test_slot_and_occurrence_round_trip(self) -> None:
        with _sqlite_store() as store:
            slot = _slot(store, recurrence="weekly")
            assert store.get_slot(slot.slot_id) == slot
            assert store.list_slots() == [slot]
            assert store.list_slots(channel_id="public") == [slot]
            assert store.list_slots(channel_id="other") == []

            updated = slot.model_copy(
                update={"enabled": False, "updated_at": _NOW + timedelta(hours=1)}
            )
            store.update_slot(updated)
            assert store.get_slot(slot.slot_id).enabled is False  # type: ignore[union-attr]

            store.delete_slot(slot.slot_id)
            assert store.get_slot(slot.slot_id) is None
