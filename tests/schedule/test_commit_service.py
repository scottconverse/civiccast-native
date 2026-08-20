# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the Commit-to-Air dry-run service (S4 slice 2).

Exercises CommitDryRunService against a real PostgresScheduleStore on the
ephemeral SQLite engine: playability checks, conflict detection, gap detection,
channel isolation, and deterministic plan fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from civiccast.schedule.commit_service import CommitDryRunService
from civiccast.schedule.models import Asset, ScheduleItemCreate
from civiccast.schedule.store import (
    PostgresAssetStore,
    PostgresScheduleStore,
    ScheduleItemNotFoundError,
)

_FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
_AIR = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


def _seed_asset(
    factory,  # type: ignore[no-untyped-def]
    asset_id: str,
    *,
    state: str = "validated",
    file_path: str | None = "/media/programs/x.ts",
    duration_seconds: int | None = 3600,
    title: str = "A Program",
) -> None:
    with factory() as session:  # type: Session
        session.add(
            Asset(
                asset_id=asset_id,
                title=title,
                state=state,
                file_path=file_path,
                duration_seconds=duration_seconds,
            )
        )
        session.commit()


def _delete_asset(factory, asset_id: str) -> None:  # type: ignore[no-untyped-def]
    with factory() as session:  # type: Session
        session.execute(delete(Asset).where(Asset.asset_id == asset_id))
        session.commit()


def _make_service(factory) -> tuple[PostgresScheduleStore, CommitDryRunService]:  # type: ignore[no-untyped-def]
    store = PostgresScheduleStore(factory)
    asset_store = PostgresAssetStore(factory)
    service = CommitDryRunService(
        store,
        asset_store,
        clock=lambda: _FIXED_NOW,
        token_factory=lambda: "tok123",
    )
    return store, service


def _create_item(
    store: PostgresScheduleStore,
    *,
    asset_id: str,
    channel_id: str = "public",
    scheduled_at: datetime,
    duration_seconds: int | None = 1800,
    mode: str = "premiere",
):  # type: ignore[no-untyped-def]
    return store.create(
        ScheduleItemCreate(
            asset_id=asset_id,
            channel_id=channel_id,
            mode=mode,  # type: ignore[arg-type]
            scheduled_at=scheduled_at,
            duration_seconds=duration_seconds,
        )
    )


class TestPlayability:
    def test_happy_path_passes_clean(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is True
        assert plan.conflicts_detected == []
        assert plan.gaps_detected == []
        assert plan.missing_media_detail is None
        assert plan.title == "A Program"
        assert plan.asset_id == "prog-1"
        assert plan.duration_seconds == 1800

    def test_missing_schedule_item_raises(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _store, service = _make_service(session_factory)
        with pytest.raises(ScheduleItemNotFoundError):
            service.prepare_commit(
                channel_id="public",
                occurrence_id="occ-1",
                schedule_item_id=uuid.uuid4(),
            )

    def test_missing_asset_fails(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        # Delete the asset after scheduling (no FK) to hit the missing branch.
        _delete_asset(session_factory, "prog-1")
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert plan.missing_media_detail is not None
        assert "does not exist" in plan.missing_media_detail

    def test_unairable_state_fails(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1", state="pending_ingest")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert "pending_ingest" in (plan.missing_media_detail or "")

    def test_no_file_path_fails(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1", file_path=None)
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert "no media file" in (plan.missing_media_detail or "")

    def test_no_duration_fails(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1", duration_seconds=None)
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert "no known duration" in (plan.missing_media_detail or "")

    def test_recorded_state_is_airable(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1", state="recorded")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is True

    def test_cancelled_target_item_fails_dry_run(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        # Legacy finding: the target item's own state (as opposed to OTHER
        # items on the channel) was never checked, so an item cancelled by a
        # different workflow between prepare and commit still "passed" the
        # dry run (playable asset, no time conflicts) — see
        # test_playout_router.py::TestCommit::test_commit_conflict_for_cancelled_target_item
        # for the resulting false-positive queued report this prevents.
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        store.cancel(item.id)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert "cancelled" in (plan.missing_media_detail or "").lower()


class TestConflicts:
    def test_overlapping_premiere_is_a_conflict(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Other")
        store, service = _make_service(session_factory)
        # Existing item 18:00-18:30; proposed 18:15-18:45 overlaps by 15 min.
        _create_item(store, asset_id="prog-2", scheduled_at=_AIR, duration_seconds=1800)
        proposed = _create_item(
            store,
            asset_id="prog-1",
            scheduled_at=_AIR + timedelta(minutes=15),
            duration_seconds=1800,
        )
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert plan.dry_run_passed is False
        assert len(plan.conflicts_detected) == 1
        conflict = plan.conflicts_detected[0]
        assert conflict.existing_asset_id == "prog-2"
        assert conflict.overlap_seconds == 900  # 15 minutes

    def test_excludes_self(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.conflicts_detected == []

    def test_ignores_other_channels(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Gov item")
        store, service = _make_service(session_factory)
        # Overlapping item but on a DIFFERENT channel — not a conflict.
        _create_item(
            store, asset_id="prog-2", channel_id="gov", scheduled_at=_AIR, duration_seconds=1800
        )
        proposed = _create_item(
            store, asset_id="prog-1", channel_id="public", scheduled_at=_AIR, duration_seconds=1800
        )
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert plan.conflicts_detected == []
        assert plan.dry_run_passed is True

    def test_ignores_cancelled_items(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Cancelled")
        store, service = _make_service(session_factory)
        cancelled = _create_item(store, asset_id="prog-2", scheduled_at=_AIR, duration_seconds=1800)
        store.cancel(cancelled.id)
        proposed = _create_item(store, asset_id="prog-1", scheduled_at=_AIR, duration_seconds=1800)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert plan.conflicts_detected == []
        assert plan.dry_run_passed is True

    def test_overlapping_published_item_is_a_conflict(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """Locks: an already-published (approved, airing) premiere now
        blocks an overlapping proposed insert in the dry-run, same as a
        scheduled one (0071_published_blocks_overlap)."""
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Published")
        store, service = _make_service(session_factory)
        published = _create_item(store, asset_id="prog-2", scheduled_at=_AIR, duration_seconds=1800)
        store.mark_published([published.id])
        proposed = _create_item(
            store,
            asset_id="prog-1",
            scheduled_at=_AIR + timedelta(minutes=15),
            duration_seconds=1800,
        )
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert plan.dry_run_passed is False
        assert len(plan.conflicts_detected) == 1
        assert plan.conflicts_detected[0].existing_asset_id == "prog-2"


class TestGaps:
    def test_gap_is_detected_but_does_not_fail(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Earlier")
        store, service = _make_service(session_factory)
        # Prior item ends at 18:00; proposed starts at 18:30 → 30-min gap.
        _create_item(
            store,
            asset_id="prog-2",
            scheduled_at=_AIR - timedelta(minutes=30),
            duration_seconds=1800,
        )
        proposed = _create_item(
            store,
            asset_id="prog-1",
            scheduled_at=_AIR + timedelta(minutes=30),
            duration_seconds=1800,
        )
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        # Gap surfaced, but the dry-run still passes (informational only).
        assert plan.dry_run_passed is True
        assert len(plan.gaps_detected) == 1
        gap = plan.gaps_detected[0]
        assert gap.kind == "gap"
        assert gap.duration_seconds == pytest.approx(1800.0)

    def test_back_to_back_has_no_gap(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2", title="Earlier")
        store, service = _make_service(session_factory)
        # Prior item ends exactly when the proposed item starts.
        _create_item(
            store,
            asset_id="prog-2",
            scheduled_at=_AIR - timedelta(minutes=30),
            duration_seconds=1800,
        )
        proposed = _create_item(store, asset_id="prog-1", scheduled_at=_AIR, duration_seconds=1800)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert plan.gaps_detected == []
        assert plan.dry_run_passed is True

    def test_gap_measured_against_nearest_prior(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "early", title="Early")
        _seed_asset(session_factory, "near", title="Near")
        store, service = _make_service(session_factory)
        # Two prior items; the gap must be measured from the LATER one.
        _create_item(
            store, asset_id="early", scheduled_at=_AIR - timedelta(hours=3), duration_seconds=1800
        )
        _create_item(
            store, asset_id="near", scheduled_at=_AIR - timedelta(minutes=20), duration_seconds=600
        )  # ends 10 min before _AIR
        proposed = _create_item(store, asset_id="prog-1", scheduled_at=_AIR, duration_seconds=1800)
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=proposed.id
        )
        assert len(plan.gaps_detected) == 1
        assert plan.gaps_detected[0].duration_seconds == pytest.approx(600.0)  # 10 min


class TestEmbargoAndProvenance:
    def test_embargo_item_cannot_air(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(
            store, asset_id="prog-1", scheduled_at=_AIR, duration_seconds=None, mode="embargo"
        )
        plan = service.prepare_commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id
        )
        assert plan.dry_run_passed is False
        assert "embargo" in (plan.missing_media_detail or "")
        assert plan.duration_seconds == 0

    def test_plan_carries_provenance_and_deterministic_fields(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public",
            occurrence_id="occ-xyz",
            schedule_item_id=item.id,
            operator_id="dana",
        )
        assert plan.plan_id == "ctap_tok123"
        assert plan.created_at == _FIXED_NOW
        assert plan.occurrence_id == "occ-xyz"
        assert plan.operator_id == "dana"
        assert plan.schedule_item_id == str(item.id)
        assert plan.channel_id == "public"

    def test_request_channel_is_not_authoritative(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        # The schedule item's own channel wins, regardless of the request arg.
        _seed_asset(session_factory, "prog-1")
        store, service = _make_service(session_factory)
        item = _create_item(store, asset_id="prog-1", channel_id="gov", scheduled_at=_AIR)
        plan = service.prepare_commit(
            channel_id="public",  # mismatched on purpose
            occurrence_id="occ-1",
            schedule_item_id=item.id,
        )
        assert plan.channel_id == "gov"
