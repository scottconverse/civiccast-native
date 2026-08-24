# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""BUG C2 fix — the as-run durable outbox (S23 §6.1).

Drives :class:`~civiccast.reporting.asrun_outbox.AsRunOutbox` directly (unit
level) and through :class:`~civiccast.reporting.asrun_recorder.
StoreAsRunRecorder` (integration level) against the exact scenario the fix
targets: the as-run ledger — the station's legal as-aired record — used to
silently lose entries on a DB hiccup during playout (bare
``except Exception: log and continue``). Proves:

* a DB failure during playout journals the event instead of dropping it;
* the failure raises a visible ``asrun-outbox-degraded`` health condition on
  the existing alert hub, not just a log line;
* the backlog drains once the DB returns, and the health condition resolves;
* no duplicates land in the store on a redundant drain;
* nothing is lost across a simulated crash between the DB write committing
  and the local journal being marked drained.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.alerting.store import get_alert_events
from civiccast.db import Base
from civiccast.reporting.asrun_outbox import (
    AsRunOutbox,
    make_append_op,
    make_close_op,
)
from civiccast.reporting.asrun_recorder import StoreAsRunRecorder
from civiccast.reporting.models import AsRunLogEntry
from civiccast.reporting.store import ReportingStore

_ASRUN_KIND = "asrun-outbox-degraded"
_ASRUN_REF = "station:asrun-outbox"


class _FlakyReportingStore:
    """Wraps a real :class:`ReportingStore`; toggles write failures on
    demand to simulate "the DB is unreachable during playout" without
    tearing down the underlying SQLite engine (which the outbox's own
    journal is independent of anyway — only the *store* side goes down)."""

    def __init__(self, inner: ReportingStore) -> None:
        self._inner = inner
        self.fail = False

    def append_as_run(self, entry: AsRunLogEntry) -> AsRunLogEntry:
        if self.fail:
            raise RuntimeError("simulated DB outage: append_as_run")
        return self._inner.append_as_run(entry)

    def close_entry(self, *, entry_id: str, actual_end: datetime, duration_s: int) -> None:
        if self.fail:
            raise RuntimeError("simulated DB outage: close_entry")
        self._inner.close_entry(entry_id=entry_id, actual_end=actual_end, duration_s=duration_s)

    def get_entry(self, entry_id: str) -> AsRunLogEntry | None:
        return self._inner.get_entry(entry_id)

    def list_as_run(self, station_id: str, **kwargs: object) -> list[AsRunLogEntry]:
        return self._inner.list_as_run(station_id, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def db(tmp_path: Path) -> Iterator[tuple[ReportingStore, object]]:
    """One shared engine/session_factory for both the reporting tables
    (``as_run_log``) and the alerting tables (``alert_events``) — the same
    single-``session_factory`` shape ``build_channel_automation`` wires in
    production."""

    eng = create_engine(f"sqlite:///{tmp_path / 'app.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ReportingStore(factory), factory
    finally:
        eng.dispose()


def _entry(entry_id: str = "asrun-1", channel_id: str = "gov") -> AsRunLogEntry:
    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    return AsRunLogEntry(
        entry_id=entry_id,
        station_id="civiccast-station",
        channel_id=channel_id,
        asset_id="asset-a",
        actual_start=t0,
        actual_end=t0,
        duration_s=0,
        source_kind="program",
        verified=True,
    )


# --------------------------------------------------------------------------- #
# Unit level: AsRunOutbox directly
# --------------------------------------------------------------------------- #


def test_db_failure_journals_instead_of_dropping(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """A DB failure during the opportunistic drain must never raise, and the
    event must stay journaled — not silently dropped."""

    store, factory = db
    flaky = _FlakyReportingStore(store)
    flaky.fail = True
    outbox = AsRunOutbox(flaky, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)  # type: ignore[arg-type]

    entry = _entry()
    outbox.append_and_drain(make_append_op(entry))  # must not raise

    assert outbox.pending_count() == 1
    assert store.get_entry(entry.entry_id) is None  # not in the real store yet


def test_db_failure_raises_visible_health_condition(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """A drain failure must surface through the existing alert hub — not
    just a log line (this is the "instead of silence" half of the fix)."""

    store, factory = db
    flaky = _FlakyReportingStore(store)
    flaky.fail = True
    outbox = AsRunOutbox(flaky, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)  # type: ignore[arg-type]

    outbox.append_and_drain(make_append_op(_entry()))

    with factory() as session:
        firing = get_alert_events(session, state="firing")
    matches = [e for e in firing if e.condition == _ASRUN_KIND and e.resource_ref == _ASRUN_REF]
    assert len(matches) == 1
    assert "1 as-aired event" in matches[0].summary


def test_backlog_drains_after_db_returns_and_alert_resolves(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """Once the DB is reachable again, the periodic/opportunistic drain
    clears the backlog and the degraded condition resolves."""

    store, factory = db
    flaky = _FlakyReportingStore(store)
    flaky.fail = True
    outbox = AsRunOutbox(flaky, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)  # type: ignore[arg-type]

    entry = _entry()
    outbox.append_and_drain(make_append_op(entry))
    assert outbox.pending_count() == 1

    # DB comes back.
    flaky.fail = False
    drained = outbox.drain_once()

    assert drained == 1
    assert outbox.pending_count() == 0
    assert store.get_entry(entry.entry_id) is not None

    with factory() as session:
        firing = get_alert_events(session, state="firing")
        resolved = get_alert_events(session, state="resolved")
    assert not [e for e in firing if e.condition == _ASRUN_KIND]
    assert [e for e in resolved if e.condition == _ASRUN_KIND and e.resource_ref == _ASRUN_REF]


def test_redundant_drain_does_not_duplicate_or_respam_alerts(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """Draining an already-empty outbox repeatedly (the periodic poll tick
    in steady state) must not create duplicate store rows or duplicate
    resolve events."""

    store, factory = db
    flaky = _FlakyReportingStore(store)
    outbox = AsRunOutbox(flaky, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)  # type: ignore[arg-type]

    entry = _entry()
    outbox.append_and_drain(make_append_op(entry))
    assert len(store.list_as_run("civiccast-station")) == 1

    # Several more idle ticks (nothing pending) — the real-world periodic
    # ChannelAutomationService.run_once cadence.
    for _ in range(5):
        assert outbox.drain_once() == 0

    assert len(store.list_as_run("civiccast-station")) == 1
    with factory() as session:
        all_events = get_alert_events(session)
    # No firing OR resolved event at all — nothing ever failed.
    assert not [e for e in all_events if e.condition == _ASRUN_KIND]


def test_no_loss_no_duplicates_across_simulated_crash(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """Simulates a crash between the DB write committing and the local
    journal row being marked drained: a fresh AsRunOutbox opened against the
    same journal file must replay the row exactly once (no loss, because it
    is still ``drained_at IS NULL``; no duplicate, because both
    ``append_as_run`` and ``close_entry`` are idempotent by construction)."""

    store, factory = db
    outbox_path = tmp_path / "outbox.sqlite3"
    outbox = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)

    entry = _entry()
    op = make_append_op(entry)
    # Journal the op, then apply it directly to the store (as drain_once
    # would) WITHOUT marking it drained -- simulating the process dying in
    # the gap between "DB commit succeeded" and "local mark-drained
    # committed".
    outbox._journal(op)
    outbox._apply(op.kind, op.payload_json)
    del outbox  # the "crash": no close(), no drained_at update

    assert len(store.list_as_run("civiccast-station")) == 1  # the DB write really did land

    # A new process opens the same journal file and replays at startup.
    resumed = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)
    replayed = resumed.replay_pending()

    assert replayed == 1
    assert resumed.pending_count() == 0
    # Still exactly one row -- append_as_run's upsert-by-entry_id absorbed
    # the replay without creating a duplicate.
    entries = store.list_as_run("civiccast-station")
    assert len(entries) == 1
    assert entries[0].entry_id == entry.entry_id


def test_construction_does_not_replay_pending_rows(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """App-factory contract (test_app_wiring.py::test_create_app_does_not_
    call_engine_connect): AsRunOutbox.__init__ must never touch the store —
    build_channel_automation constructs it synchronously inside
    civiccast.app.create_app(), a path that must never open a DB connection.
    A pending row left by a prior process must still be sitting there,
    undrained, right after construction."""

    store, factory = db
    outbox_path = tmp_path / "outbox.sqlite3"
    # Leave a row pending, the same way the crash-simulation tests do.
    setup = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)
    op = make_append_op(_entry())
    setup._journal(op)
    del setup  # no drain, no replay -- purely journaled

    fresh = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)

    assert fresh.pending_count() == 1  # construction alone did not touch it
    assert store.list_as_run("civiccast-station") == []  # store untouched


def test_ensure_started_replays_once_then_behaves_as_drain_once(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """ensure_started() is what StoreAsRunRecorder's first opportunistic
    write and ChannelAutomationService.run_once's first poll tick call
    (never AsRunOutbox.__init__ / build_channel_automation directly — see
    the module docstring). It must perform the crash-recovery replay
    exactly once, then fall back to an ordinary drain_once on every later
    call, even if more rows show up in between."""

    store, factory = db
    outbox_path = tmp_path / "outbox.sqlite3"
    setup = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)
    leftover = make_append_op(_entry(entry_id="asrun-leftover"))
    setup._journal(leftover)
    del setup

    outbox = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)
    replay_calls: list[int] = []
    real_replay = outbox.replay_pending

    def counting_replay() -> int:
        replay_calls.append(1)
        return real_replay()

    outbox.replay_pending = counting_replay  # type: ignore[method-assign]

    # First call: the leftover row is still pending (construction didn't
    # touch it) -- ensure_started() must perform the real replay.
    assert outbox.pending_count() == 1
    first = outbox.ensure_started()
    assert first == 1
    assert len(replay_calls) == 1
    assert outbox.pending_count() == 0
    assert len(store.list_as_run("civiccast-station")) == 1

    # A second row arrives later (a normal new transition, not a crash
    # leftover). ensure_started() must NOT replay again -- just drain it
    # once, same as a routine automation poll tick / opportunistic write.
    outbox._journal(make_append_op(_entry(entry_id="asrun-later", channel_id="edu")))
    second = outbox.ensure_started()
    assert second == 1
    assert len(replay_calls) == 1  # still only the one real replay call
    assert len(store.list_as_run("civiccast-station")) == 2


def test_close_op_replay_is_idempotent_across_simulated_crash(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """Same crash simulation, but for a close op — close_entry's
    ``WHERE duration_s == 0`` guard must make the replayed close a no-op
    rather than re-mutating an already-closed row."""

    store, factory = db
    outbox_path = tmp_path / "outbox.sqlite3"
    outbox = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)

    entry = _entry()
    store.append_as_run(entry)  # pre-existing open row, as the recorder would leave it

    t_close = entry.actual_start + timedelta(minutes=10)
    close_op = make_close_op(
        channel_id="gov", entry_id=entry.entry_id, actual_end=t_close, duration_s=600
    )
    outbox._journal(close_op)
    outbox._apply(close_op.kind, close_op.payload_json)
    del outbox

    closed = store.get_entry(entry.entry_id)
    assert closed is not None
    assert closed.duration_s == 600

    resumed = AsRunOutbox(store, db_path=outbox_path, alert_session_factory=factory)
    replayed = resumed.replay_pending()

    assert replayed == 1
    still_closed = store.get_entry(entry.entry_id)
    assert still_closed is not None
    assert still_closed.duration_s == 600  # unchanged — the guarded UPDATE no-op'd
    assert still_closed.actual_end == t_close


def test_exactly_once_event_id_dedupes_repeated_journal_calls(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """Re-journaling the identical op (same entry_id => same event_id) is a
    no-op at the journal layer -- the exactly-once contract."""

    store, factory = db
    outbox = AsRunOutbox(store, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)
    entry = _entry()
    op = make_append_op(entry)

    outbox.append_and_drain(op)
    outbox.append_and_drain(op)  # identical event_id, replayed by an over-eager caller
    outbox.append_and_drain(op)

    assert outbox.pending_count() == 0
    assert len(store.list_as_run("civiccast-station")) == 1


# --------------------------------------------------------------------------- #
# Integration level: StoreAsRunRecorder driving the outbox
# --------------------------------------------------------------------------- #


def test_recorder_survives_db_outage_and_recovers(
    db: tuple[ReportingStore, object], tmp_path: Path
) -> None:
    """End-to-end: the recorder (as the playout engine drives it) records a
    transition while the DB is down, does not raise, then the next
    transition — after the DB returns — proves both the durable outbox and
    the open/close stitch survived the outage without losing the first row.
    """

    store, factory = db
    flaky = _FlakyReportingStore(store)
    outbox = AsRunOutbox(flaky, db_path=tmp_path / "outbox.sqlite3", alert_session_factory=factory)  # type: ignore[arg-type]
    recorder = StoreAsRunRecorder(store, station_id="civiccast-station", outbox=outbox)  # type: ignore[arg-type]

    t0 = datetime(2026, 6, 18, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=30)

    flaky.fail = True
    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-a",
        source_label="A",
        actual_start=t0,
        proof_event_id="proof-1",
    )
    # Playout is unaffected: no exception, and the open-row bookkeeping still
    # advanced so the engine's stitch contract holds once the DB returns.
    assert "gov" in recorder._open
    assert store.list_as_run("civiccast-station") == []  # nothing durable yet

    with factory() as session:
        firing = get_alert_events(session, state="firing")
    assert [e for e in firing if e.condition == _ASRUN_KIND]

    flaky.fail = False
    recorder.record_transition(
        channel_id="gov",
        source_kind="program",
        asset_id="asset-b",
        source_label="B",
        actual_start=t1,
        proof_event_id="proof-2",
    )

    entries = store.list_as_run("civiccast-station")
    assert len(entries) == 2
    by_asset = {e.asset_id: e for e in entries}
    assert by_asset["asset-a"].actual_end == t1
    assert by_asset["asset-a"].duration_s == 30 * 60
    assert by_asset["asset-b"].duration_s == 0

    with factory() as session:
        firing = get_alert_events(session, state="firing")
        resolved = get_alert_events(session, state="resolved")
    assert not [e for e in firing if e.condition == _ASRUN_KIND]
    assert [e for e in resolved if e.condition == _ASRUN_KIND]


def test_recorder_default_outbox_is_isolated_and_side_effect_free(
    db: tuple[ReportingStore, object],
) -> None:
    """Constructing a recorder WITHOUT an injected outbox (every pre-existing
    unit test's call shape) must not touch the real station-data-dir
    journal path -- proves the ephemeral-path default stays isolated."""

    from civiccast.reporting.asrun_outbox import default_asrun_outbox_path

    store, _factory = db
    recorder = StoreAsRunRecorder(store, station_id="civiccast-station")

    assert recorder._outbox._db_path != default_asrun_outbox_path()
    recorder.record_transition(
        channel_id="gov",
        source_kind="slate",
        asset_id=None,
        source_label="Slate",
        actual_start=datetime(2026, 6, 18, 9, 0, tzinfo=UTC),
        proof_event_id="proof-x",
    )
    assert len(store.list_as_run("civiccast-station")) == 1
