# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Program-log staff API tests (cable automation CA-1)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 -- ATTACH ':memory:' AS civiccast on SQLite connect
from civiccast.app import create_app
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.programlog.materializer import ProgramLogMaterializer, ProgramLogSettings
from civiccast.programlog.router import (
    get_program_log_asset_titler,
    get_program_log_materializer,
    get_program_log_store,
)
from civiccast.programlog.store import PostgresProgramLogStore
from civiccast.schedule.router import get_schedule_store


class _FakeScheduleStore:
    def __init__(self) -> None:
        self.created: list[object] = []
        self.cancelled: list[object] = []
        self._next = 0

    def create(self, payload):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        self._next += 1
        self.created.append(payload)
        return SimpleNamespace(id=f"sched-{self._next}")

    def cancel(self, schedule_id):  # type: ignore[no-untyped-def]
        self.cancelled.append(schedule_id)


def _asset_resolver(asset_id: str):  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    if asset_id == "missing-asset":
        return None
    return SimpleNamespace(
        title="Council Meeting",
        duration_seconds=3600,
        state="validated",
        file_path=f"C:/media/{asset_id}.mp4",
    )


@contextmanager
def _client() -> Iterator[tuple[TestClient, _FakeScheduleStore]]:
    # TestClient runs handlers on a thread pool; a shared StaticPool
    # connection (check_same_thread=False) keeps the ATTACHed civiccast
    # schema visible across threads (same posture as the schedule router
    # tests).
    from contextlib import suppress

    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(engine)
    with engine.connect() as conn:
        with suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        store = PostgresProgramLogStore(session_factory)
        schedule = _FakeScheduleStore()
        materializer = ProgramLogMaterializer(
            store,
            schedule,
            _asset_resolver,
            settings=ProgramLogSettings(mode="inline", poll_seconds=300.0, horizon_hours=72.0),
        )
        app = create_app()
        app.dependency_overrides[get_program_log_store] = lambda: store
        app.dependency_overrides[get_program_log_materializer] = lambda: materializer
        app.dependency_overrides[get_program_log_asset_titler] = lambda: _asset_resolver
        yield (
            TestClient(app, headers={"Authorization": "Bearer operator-token-a"}),
            schedule,
        )
    finally:
        reset_engine()
        engine.dispose()


def _create_payload(**overrides):  # type: ignore[no-untyped-def]
    first_start_at = datetime.now(UTC) + timedelta(hours=1)
    payload = {
        "channel_id": "public",
        "asset_id": "council-2026-06-10",
        "recurrence": "daily",
        # Seed relative to "now" (first_start_at = now + 1h, above) so the single
        # `once` airing always lands inside the materializer's forward horizon. A
        # fixed calendar date here was a time-bomb: once the date slipped into the
        # past the `once` slot stopped materializing and the staff log / public
        # guide came back empty. Production's forward window is correct; only the
        # seed needed to follow now.
        "first_start_at": first_start_at.isoformat(),
    }
    payload.update(overrides)
    return payload


def test_create_slot_materializes_and_log_shows_entries() -> None:
    with _client() as (client, schedule):
        created = client.post("/api/staff/programlog/slots", json=_create_payload())
        assert created.status_code == 200
        slot = created.json()
        assert slot["slot_id"].startswith("cps_")
        assert len(schedule.created) >= 1

        log = client.get("/api/staff/programlog/channels/public/log")
        assert log.status_code == 200
        entries = log.json()
        assert len(entries) >= 1
        assert entries[0]["status"] == "scheduled"
        assert entries[0]["asset_id"] == "council-2026-06-10"
        assert entries[0]["schedule_item_id"]

        listed = client.get("/api/staff/programlog/slots", params={"channel_id": "public"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_unknown_slot_is_404_and_unplayable_asset_is_recorded() -> None:
    with _client() as (client, _schedule):
        assert client.get("/api/staff/programlog/slots/cps_nope").status_code == 404

        created = client.post(
            "/api/staff/programlog/slots",
            json=_create_payload(asset_id="missing-asset", recurrence="once"),
        )
        assert created.status_code == 200
        log = client.get("/api/staff/programlog/channels/public/log").json()
        assert log[0]["status"] == "skipped_asset"
        assert "not playable" in log[0]["detail"]


def test_disable_cancels_future_airings() -> None:
    with _client() as (client, schedule):
        slot = client.post("/api/staff/programlog/slots", json=_create_payload()).json()

        disabled = client.post(f"/api/staff/programlog/slots/{slot['slot_id']}/disable")

        assert disabled.status_code == 200
        cancelled = disabled.json()
        assert len(cancelled) >= 1
        assert all(o["status"] == "cancelled" for o in cancelled)
        assert len(schedule.cancelled) == len(cancelled)
        assert (
            client.get(f"/api/staff/programlog/slots/{slot['slot_id']}").json()["enabled"] is False
        )


def test_naive_datetime_is_rejected() -> None:
    with _client() as (client, _schedule):
        response = client.post(
            "/api/staff/programlog/slots",
            json=_create_payload(first_start_at="2026-06-12T19:00:00"),
        )
        assert response.status_code == 422


def test_public_guide_serves_sanitized_airable_entries_only() -> None:
    """CA-5: residents see WHAT AIRS — never skips, ids, or internal detail."""

    with _client() as (client, _schedule):
        client.post("/api/staff/programlog/slots", json=_create_payload())
        client.post(
            "/api/staff/programlog/slots",
            json=_create_payload(asset_id="missing-asset", recurrence="once"),
        )

        guide = client.get("/api/public/programlog/channels/public/guide")

        assert guide.status_code == 200
        entries = guide.json()
        assert len(entries) >= 1
        first = entries[0]
        # Sanitized shape: display fields only — no ids, no skip detail.
        assert set(first.keys()) == {"title", "starts_at", "duration_seconds", "channel_id"}
        assert first["channel_id"] == "public"
        assert first["title"] == "Council Meeting"
        assert first["duration_seconds"] == 3600
        # The skipped (unplayable) slot never leaks to residents.
        assert not any("skipped" in str(entry).lower() for entry in entries)
        assert not any("missing-asset" in str(entry) for entry in entries)


def test_public_guide_uses_title_override_when_present() -> None:
    with _client() as (client, _schedule):
        client.post(
            "/api/staff/programlog/slots",
            json=_create_payload(recurrence="once", title_override="Council Replay"),
        )

        entries = client.get("/api/public/programlog/channels/public/guide").json()

        assert entries[0]["title"] == "Council Replay"


def test_endpoints_503_without_durable_storage() -> None:
    app = create_app()
    client = TestClient(app, headers={"Authorization": "Bearer operator-token-a"})
    response = client.get("/api/staff/programlog/slots")
    assert response.status_code == 503


class _ManualScheduleStore:
    """Schedule store stub exposing list() with manual (slotless) items — the
    F-RC4-2 path that CommitToAirPanel reads via channel_log()."""

    def __init__(self, items: list[object]) -> None:
        self._items = items

    def list(self, *, channel_id=None, states=None):  # type: ignore[no-untyped-def]
        out = []
        for it in self._items:
            if channel_id is not None and it.channel_id != channel_id:
                continue
            if states is not None and it.state not in states:
                continue
            out.append(it)
        return out


def _manual_item(**overrides):  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    base = {
        "id": "sched-manual-1",
        "channel_id": "government",
        "asset_id": "council-2026-06-10",
        "asset_title": "Council Meeting",
        "scheduled_at": datetime.now(UTC) + timedelta(hours=2),
        "duration_seconds": 3600,
        "state": "scheduled",
        "mode": "premiere",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@contextmanager
def _client_with_schedule(items):  # type: ignore[no-untyped-def]
    """Like _client() but also wires a schedule store exposing list()."""
    with _client() as (client, _fake):
        client.app.dependency_overrides[get_schedule_store] = lambda: _ManualScheduleStore(items)
        yield client


def test_manual_schedule_item_appears_in_channel_log_as_committable() -> None:
    # F-RC4-2: a manually-scheduled premiere (no recurring slot) must show up
    # in the channel log so Commit-to-Air can put it on air. Before the fix it
    # was structurally invisible (channel_log only iterated slot occurrences).
    item = _manual_item()
    with _client_with_schedule([item]) as client:
        entries = client.get(
            "/api/staff/programlog/channels/government/log", params={"hours": 24}
        ).json()

    assert len(entries) == 1
    entry = entries[0]
    assert entry["schedule_item_id"] == "sched-manual-1"
    assert entry["status"] == "manual"
    assert entry["occurrence_id"] == "manual:sched-manual-1"
    assert entry["asset_id"] == "council-2026-06-10"
    assert entry["channel_id"] == "government"


def test_manual_item_out_of_window_or_wrong_channel_is_excluded() -> None:
    far = _manual_item(id="sched-far", scheduled_at=datetime.now(UTC) + timedelta(hours=100))
    other = _manual_item(id="sched-other", channel_id="public")
    cancelled = _manual_item(id="sched-cancelled", state="cancelled")
    with _client_with_schedule([far, other, cancelled]) as client:
        entries = client.get(
            "/api/staff/programlog/channels/government/log", params={"hours": 24}
        ).json()
    # far = past horizon, other = different channel, cancelled = not a committable state.
    assert entries == []


def test_manual_item_covered_by_a_slot_occurrence_is_not_double_counted() -> None:
    # A slot-materialized premiere already has a SlotOccurrence carrying its
    # schedule_item_id; the manual pass must NOT also emit a synthetic row.
    with _client() as (client, _schedule):
        client.post(
            "/api/staff/programlog/slots",
            json=_create_payload(recurrence="once"),
        )
        log = client.get("/api/staff/programlog/channels/public/log").json()
        assert len(log) >= 1
        slot_item_id = log[0]["schedule_item_id"]
        assert slot_item_id

        # Now expose that SAME schedule item through the manual list() path.
        same = _manual_item(id=str(slot_item_id), channel_id="public")
        client.app.dependency_overrides[get_schedule_store] = lambda: _ManualScheduleStore([same])
        deduped = client.get("/api/staff/programlog/channels/public/log").json()

    ids = [e["schedule_item_id"] for e in deduped]
    assert ids.count(str(slot_item_id)) == 1
    assert not any(e["occurrence_id"] == f"manual:{slot_item_id}" for e in deduped)


def test_channel_log_surfaces_a_manual_item_from_the_REAL_schedule_store() -> None:
    """Drive channel_log through the real PostgresScheduleStore, not a fake.

    Every other manual-item test above injects a hand-rolled fake schedule
    store, so none of them can catch drift between what channel_log calls --
    ``list(channel_id=..., states=("scheduled", "published"))`` returning
    objects with ``.id/.channel_id/.asset_id/.asset_title/.scheduled_at/
    .duration_seconds`` -- and what the real store actually offers. A fake that
    agrees with the caller proves only that the caller agrees with itself; the
    F-RC4-2 outage was exactly this kind of contract gap between two components
    that each passed their own tests.
    """
    from contextlib import suppress

    from sqlalchemy.pool import StaticPool

    from civiccast.schedule.models import Asset, ScheduleItemCreate
    from civiccast.schedule.store import PostgresScheduleStore

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(engine)
    with engine.connect() as conn:
        with suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        with session_factory() as session:
            session.add(
                Asset(
                    asset_id="council-2026-06-10",
                    title="Council Meeting",
                    state="validated",
                    file_path="/media/programs/council.ts",
                    duration_seconds=3600,
                )
            )
            session.commit()

        real_schedule = PostgresScheduleStore(session_factory)
        scheduled_at = datetime.now(UTC) + timedelta(hours=2)
        created = real_schedule.create(
            ScheduleItemCreate(
                asset_id="council-2026-06-10",
                channel_id="government",
                mode="premiere",
                scheduled_at=scheduled_at,
                duration_seconds=3600,
            )
        )

        app = create_app()
        app.dependency_overrides[get_program_log_store] = lambda: PostgresProgramLogStore(
            session_factory
        )
        app.dependency_overrides[get_program_log_asset_titler] = lambda: _asset_resolver
        app.dependency_overrides[get_schedule_store] = lambda: real_schedule
        client = TestClient(app, headers={"Authorization": "Bearer operator-token-a"})

        response = client.get("/api/staff/programlog/channels/government/log")
        assert response.status_code == 200, response.text
        log = response.json()
    finally:
        reset_engine()
        engine.dispose()

    manual = [e for e in log if e["status"] == "manual"]
    assert len(manual) == 1, log
    entry = manual[0]
    # Commit-to-Air needs a real schedule_item_id; the synthetic occurrence_id
    # is opaque provenance and is never looked up.
    assert entry["schedule_item_id"] == str(created.id)
    assert entry["occurrence_id"] == f"manual:{created.id}"
    assert entry["channel_id"] == "government"
    assert entry["asset_id"] == "council-2026-06-10"
    assert entry["duration_seconds"] == 3600
    assert entry["slot_id"] == ""
