# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""End-to-end Commit-to-Air integration test (S4 slice 7 — S4 close).

Proves the full chain WITHOUT the live GStreamer engine, on any platform:

    operator commit  →  durable report (queued)
                     →  engine command queued (the daemon's input)
                     →  the PROVEN resolver (build_source_plan_from_schedule)
                        picks up the committed item once it reloads

The live airing of that source plan + the 24-hour soak are the WSL / tester-
machine lanes (build step 13) and are NOT exercised here — this test stops at
"the engine will air it on its next resolve", which is the boundary a Windows
dev box can honestly prove.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from civiccast.egress.dispatcher import PlayoutDispatcher
from civiccast.egress.source_plan import build_source_plan_from_schedule
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.commit_models import DISPATCH_STATUS_QUEUED
from civiccast.schedule.commit_service import CommitDryRunService, CommitService
from civiccast.schedule.models import (
    SCHEDULE_STATE_CANCELLED,
    SCHEDULE_STATE_PUBLISHED,
    Asset,
    ScheduleItemCreate,
)
from civiccast.schedule.store import PostgresAssetStore, PostgresScheduleStore

# A fixed "now" so the test is deterministic — the committed item airs at this
# instant; the resolver is queried a few seconds into its window.
_AIR = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


def _state_of(store: PostgresScheduleStore, schedule_id: object) -> str:
    item = store.get(schedule_id)
    assert item is not None
    return item.state


def test_commit_then_engine_resolves_the_committed_item(session_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # A real media file on disk so the proven resolver's _segment_from_item
    # (which checks the file exists) can build a real segment.
    media = tmp_path / "council.ts"
    media.write_bytes(b"\x00" * 4096)

    schedule_store = PostgresScheduleStore(session_factory)
    asset_store = PostgresAssetStore(session_factory)
    with session_factory() as session:
        session.add(
            Asset(
                asset_id="council",
                title="City Council — June 20",
                state="validated",
                file_path=str(media),
                duration_seconds=3600,
            )
        )
        session.commit()

    item = schedule_store.create(
        ScheduleItemCreate(
            asset_id="council",
            channel_id="public",
            mode="premiere",
            scheduled_at=_AIR,
            duration_seconds=3600,
        )
    )

    egress = InMemoryEgressStore()
    service = CommitService(
        CommitDryRunService(
            schedule_store, asset_store, clock=lambda: _AIR, token_factory=lambda: "tok"
        ),
        schedule_store,
        PlayoutDispatcher(egress, clock=lambda: _AIR, id_factory=lambda: "cmd"),
        clock=lambda: _AIR,
        report_id_factory=lambda: "e2e",
    )

    # (1) Operator commits the occurrence to air.
    report = service.commit(
        channel_id="public",
        occurrence_id="occ-e2e",
        schedule_item_id=item.id,
        operator_id="dana",
    )
    assert report.dispatch_status == DISPATCH_STATUS_QUEUED
    assert report.report_id == "ctar_e2e"

    # (1b) Commit-to-Air gate: the commit approved the item, so it is now
    # ``published`` (auto-approved autoschedule items are born this way too;
    # a manually-scheduled item must go through this commit to get here).
    assert _state_of(schedule_store, item.id) == SCHEDULE_STATE_PUBLISHED

    # (2) The egress daemon's command queue received a nudge.
    pending = egress.pop_pending_commands("public")
    assert len(pending) == 1
    assert pending[0].action in ("start", "reload")
    assert pending[0].channel_id == "public"

    # (3) The PROVEN resolver — what the daemon runs on reload — picks up the
    # committed item at its air time and would put it on air. Only
    # ``published`` items are airable (the Commit-to-Air gate).
    plan = build_source_plan_from_schedule(
        channel_id="public",
        schedule_items=schedule_store.list(channel_id="public", states=(SCHEDULE_STATE_PUBLISHED,)),
        asset_resolver=asset_store.get_staff_row,
        now=_AIR + timedelta(seconds=5),
    )
    assert plan is not None, "resolver should resolve the committed item as the current source"
    assert plan.segments[0].source_ref == "council"
    assert plan.segments[0].kind == "program"


def test_rolled_back_item_is_not_resolved_for_air(session_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # After a rollback cancels the schedule item, the resolver must NOT air it —
    # closing the undo half of the loop.
    media = tmp_path / "council.ts"
    media.write_bytes(b"\x00" * 4096)

    schedule_store = PostgresScheduleStore(session_factory)
    asset_store = PostgresAssetStore(session_factory)
    with session_factory() as session:
        session.add(
            Asset(
                asset_id="council",
                title="City Council",
                state="validated",
                file_path=str(media),
                duration_seconds=3600,
            )
        )
        session.commit()

    item = schedule_store.create(
        ScheduleItemCreate(
            asset_id="council",
            channel_id="public",
            mode="premiere",
            scheduled_at=_AIR,
            duration_seconds=3600,
        )
    )
    egress = InMemoryEgressStore()
    service = CommitService(
        CommitDryRunService(
            schedule_store, asset_store, clock=lambda: _AIR, token_factory=lambda: "tok"
        ),
        schedule_store,
        PlayoutDispatcher(egress, clock=lambda: _AIR, id_factory=lambda: "cmd"),
        clock=lambda: _AIR,
        report_id_factory=lambda: "e2e",
    )
    service.commit(
        channel_id="public", occurrence_id="occ-e2e", schedule_item_id=item.id, operator_id="dana"
    )
    assert _state_of(schedule_store, item.id) == SCHEDULE_STATE_PUBLISHED
    service.rollback(report_id="ctar_e2e", reason="aired in error", operator_id="dana")

    # Cancel must work from ``published`` (state machine regression guard,
    # spec test f) — the item is cancelled, not stuck published forever.
    assert _state_of(schedule_store, item.id) == SCHEDULE_STATE_CANCELLED

    # The item is cancelled, so the resolver yields no committed program (slate).
    plan = build_source_plan_from_schedule(
        channel_id="public",
        schedule_items=schedule_store.list(channel_id="public", states=(SCHEDULE_STATE_PUBLISHED,)),
        asset_resolver=asset_store.get_staff_row,
        now=_AIR + timedelta(seconds=5),
    )
    assert plan is None
