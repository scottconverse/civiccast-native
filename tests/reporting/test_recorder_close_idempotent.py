# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 §6.1 — recorder close is idempotent + immutable on a re-closed row.

E-3 (perf) + E-4 (correctness) refactor: ``_close_locked`` used to do a
``get_entry`` SELECT followed by an ``append_as_run`` UPDATE. Two DB
round-trips per close on the playout thread, and worse: a post-commit
teardown failure left the ``self._open`` map populated, so a subsequent
close would re-fetch the (already-closed) row and overwrite ``actual_end``
with the later transition's time — silently erasing the first close from
the append-only ledger.

The fix is:

1. Pop ``self._open`` BEFORE the DB call so a teardown failure cannot leak a
   stale handle.
2. Replace the SELECT+UPDATE pair with a single :meth:`ReportingStore.close_entry`
   that does ``UPDATE … WHERE entry_id = :id AND duration_s = 0`` — so a
   second close (race, retry, manual replay) is a no-op rather than a
   mutation. The append-only contract is now enforced in SQL.

T-6 (clock-skew branch): if the close timestamp is earlier than the open
``actual_start`` (NTP step-back, immediate re-transition), ``_close_locked``
clamps ``duration_s = 0`` and ``actual_end = actual_start`` rather than
allowing a negative duration that would either crash hours-by-category SUM
or under-report total air time.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.reporting.asrun_recorder import StoreAsRunRecorder
from civiccast.reporting.store import ReportingStore


@pytest.fixture
def reporting_store(tmp_path: Path) -> Iterator[ReportingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'reporting.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ReportingStore(factory)
    finally:
        eng.dispose()


def test_close_is_idempotent_under_second_call(reporting_store: ReportingStore) -> None:
    """A second ``close_open`` after the row is already closed must not mutate
    the stored ``actual_end`` — even if a stale handle resurrects somehow.

    Drives the second close by reaching into ``self._open`` directly to simulate
    a teardown that failed to pop the handle on the first close. The SQL guard
    ``WHERE duration_s == 0`` makes the second UPDATE a no-op.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=30)
    t_later = t1 + timedelta(minutes=10)

    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-a",
        source_label="A",
        actual_start=t0,
        proof_event_id="proof-1",
    )
    recorder.close_open(channel_id="gov", actual_end=t1)
    rows_after_first_close = reporting_store.list_as_run("civiccast-station")
    assert len(rows_after_first_close) == 1
    assert rows_after_first_close[0].actual_end == t1
    assert rows_after_first_close[0].duration_s == 30 * 60

    # Now simulate a stale handle (the pre-fix bug): force the open map back
    # to the previously-closed entry and call close_open again with a later
    # timestamp. The SQL guard must reject the mutation.
    entry_id = rows_after_first_close[0].entry_id
    recorder._open["gov"] = (entry_id, t0)
    recorder.close_open(channel_id="gov", actual_end=t_later)

    rows_after_second_close = reporting_store.list_as_run("civiccast-station")
    assert len(rows_after_second_close) == 1
    # actual_end is unchanged — the second close was a no-op (idempotent).
    assert rows_after_second_close[0].actual_end == t1
    assert rows_after_second_close[0].duration_s == 30 * 60


def test_close_does_not_resurrect_pop(reporting_store: ReportingStore) -> None:
    """After a successful close, ``self._open`` no longer has the channel —
    a subsequent ``close_open`` is a noop without ever touching SQL.

    Validates the E-4 pop-before-commit ordering: even a post-commit teardown
    failure would not leave a stale handle.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-a",
        source_label="A",
        actual_start=t0,
        proof_event_id="proof-1",
    )
    assert "gov" in recorder._open
    recorder.close_open(channel_id="gov", actual_end=t0 + timedelta(minutes=15))
    assert "gov" not in recorder._open


def test_close_uses_single_session_call(
    reporting_store: ReportingStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-3: a close should be exactly one DB round-trip (the single UPDATE),
    not the prior SELECT-then-UPDATE pair. Counts ``close_entry`` calls.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-a",
        source_label="A",
        actual_start=t0,
        proof_event_id="proof-1",
    )

    real_close = reporting_store.close_entry
    calls: list[dict[str, object]] = []

    def counting_close(*, entry_id: str, actual_end: datetime, duration_s: int) -> None:
        calls.append({"entry_id": entry_id, "actual_end": actual_end, "duration_s": duration_s})
        real_close(entry_id=entry_id, actual_end=actual_end, duration_s=duration_s)

    monkeypatch.setattr(reporting_store, "close_entry", counting_close)
    recorder.close_open(channel_id="gov", actual_end=t0 + timedelta(minutes=5))
    assert len(calls) == 1
    assert calls[0]["duration_s"] == 5 * 60


def test_close_with_earlier_actual_end_clamps_to_zero_duration(
    reporting_store: ReportingStore,
) -> None:
    """T-6: a clock-skew / immediate-retransition close where ``actual_end``
    is earlier than ``actual_start`` must clamp ``duration_s=0`` and
    ``actual_end == actual_start`` — never a negative duration that would
    crash hours-by-category SUM or under-report total air time.
    """
    recorder = StoreAsRunRecorder(reporting_store, station_id="civiccast-station")
    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-a",
        source_label="A",
        actual_start=t0,
        proof_event_id="proof-1",
    )
    # NTP corrected backward by 5s — the close is now before the open.
    recorder.close_open(channel_id="gov", actual_end=t0 - timedelta(seconds=5))

    rows = reporting_store.list_as_run("civiccast-station")
    assert len(rows) == 1
    # The recorder clamps: actual_end == actual_start; duration_s == 0. The
    # store's close_entry write is gated by the open-row SQL guard, but the
    # row was open here so the clamp values are what land.
    assert rows[0].actual_end == t0
    assert rows[0].duration_s == 0


def test_horizon_continuation_is_one_play_but_repeat_is_another(
    reporting_store: ReportingStore,
) -> None:
    recorder = StoreAsRunRecorder(reporting_store)
    start = datetime(2026, 10, 30, tzinfo=UTC)
    for seconds, offset in ((0, 0), (30, 30), (60, 60), (90, 0)):
        recorder.record_transition(
            channel_id="gov",
            source_kind="program",
            asset_id="asset-a",
            source_label="A",
            actual_start=start + timedelta(seconds=seconds),
            proof_event_id=f"proof-{seconds}",
            schedule_item_id="occurrence-a",
            source_offset_seconds=offset,
        )
    recorder.close_open(channel_id="gov", actual_end=start + timedelta(seconds=120))
    rows = reporting_store.list_as_run("civiccast-station")
    assert len(rows) == 2
    assert [row.duration_s for row in rows] == [90, 30]


def test_repeated_short_program_with_increasing_late_offsets_is_separate_airings(reporting_store):
    recorder = StoreAsRunRecorder(reporting_store)
    start = datetime(2026, 10, 30, tzinfo=UTC)
    # R7's increasing join offsets previously merged the first three repeats.
    for index, offset in enumerate((3.583484, 3.614415, 6.251983, 0.410173)):
        occurrence = start + timedelta(seconds=38 * index)
        actual = occurrence + timedelta(seconds=offset)
        recorder.record_transition(
            channel_id="education",
            source_kind="program",
            asset_id="asset-a",
            source_label="Short program",
            actual_start=actual,
            proof_event_id=f"repeat-{index}",
            schedule_item_id="same-schedule-row",
            source_offset_seconds=offset,
            schedule_occurrence_start=occurrence,
        )
        # A conform-horizon event within this repeat must not invent another airing.
        recorder.record_transition(
            channel_id="education",
            source_kind="program",
            asset_id="asset-a",
            source_label="Short program",
            actual_start=actual + timedelta(seconds=10),
            proof_event_id=f"horizon-{index}",
            schedule_item_id="same-schedule-row",
            source_offset_seconds=offset + 10,
            schedule_occurrence_start=occurrence,
        )
    recorder.close_open(channel_id="education", actual_end=start + timedelta(seconds=152))
    rows = sorted(
        reporting_store.list_as_run("civiccast-station"), key=lambda row: row.actual_start
    )
    assert len(rows) == 4
    assert [row.scheduled_start for row in rows] == [
        start + timedelta(seconds=38 * i) for i in range(4)
    ]
    assert [row.duration_s for row in rows] == [38, 40, 32, 37]
