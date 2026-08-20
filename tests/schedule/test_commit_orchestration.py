# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the Commit-to-Air commit orchestration (S4 slice 3).

CommitService.commit composes the dry-run (race check), the report store, and
the PlayoutDispatcher. Exercised against real schedule + asset stores on SQLite
and the real InMemoryEgressStore.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from civiccast.egress.dispatcher import PlayoutDispatcher
from civiccast.egress.store import InMemoryEgressStore
from civiccast.schedule.commit_models import (
    DISPATCH_STATUS_CANCELLED,
    DISPATCH_STATUS_ERROR,
    DISPATCH_STATUS_QUEUED,
    CommitToAirReport,
)
from civiccast.schedule.commit_service import (
    CommitConflictError,
    CommitDryRunService,
    CommitReportNotFoundError,
    CommitService,
)
from civiccast.schedule.models import Asset, ScheduleItemCreate
from civiccast.schedule.store import (
    PostgresAssetStore,
    PostgresScheduleStore,
    ScheduleItemNotFoundError,
)

_FIXED_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
_AIR = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


class _RaisingEgressStore(InMemoryEgressStore):
    """Egress store whose command enqueue fails with a secret-bearing message,
    to prove the orchestration records an error without leaking it."""

    def enqueue_command(self, cmd) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("connect failed: postgres://user:s3cr3t@db.internal/civiccast")


class _RaceLostScheduleStore(PostgresScheduleStore):
    """Simulates losing the Commit-to-Air race (PE-2).

    The dry-run still reads the item as ``scheduled`` (all reads are real), but
    by the time ``commit_to_air`` runs a concurrent commit has already flipped
    the row, so its atomic ``UPDATE ... WHERE state='scheduled'`` matches 0
    rows. Forcing a False return (persisting nothing) exercises exactly the
    true-concurrency window CommitService must refuse.
    """

    def commit_to_air(self, schedule_id, report) -> bool:  # type: ignore[no-untyped-def]
        return False


def _seed_asset(factory, asset_id: str = "prog-1") -> None:  # type: ignore[no-untyped-def]
    with factory() as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title="A Program",
                state="validated",
                file_path="/media/programs/x.ts",
                duration_seconds=3600,
            )
        )
        session.commit()


def _create_item(
    store, *, asset_id="prog-1", channel_id="public", scheduled_at, duration_seconds=1800
):  # type: ignore[no-untyped-def]
    return store.create(
        ScheduleItemCreate(
            asset_id=asset_id,
            channel_id=channel_id,
            mode="premiere",
            scheduled_at=scheduled_at,
            duration_seconds=duration_seconds,
        )
    )


def _build(factory, egress_store=None):  # type: ignore[no-untyped-def]
    schedule_store = PostgresScheduleStore(factory)
    asset_store = PostgresAssetStore(factory)
    dry_run = CommitDryRunService(
        schedule_store, asset_store, clock=lambda: _FIXED_NOW, token_factory=lambda: "tok"
    )
    egress = egress_store if egress_store is not None else InMemoryEgressStore()
    dispatcher = PlayoutDispatcher(egress, clock=lambda: _FIXED_NOW, id_factory=lambda: "cmd1")
    service = CommitService(
        dry_run,
        schedule_store,
        dispatcher,
        clock=lambda: _FIXED_NOW,
        report_id_factory=lambda: "rep1",
    )
    return schedule_store, egress, service


class TestCommitHappyPath:
    def test_commit_persists_queued_report_and_enqueues_command(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory)
        schedule_store, egress, service = _build(session_factory)
        item = _create_item(schedule_store, scheduled_at=_AIR)
        report = service.commit(
            channel_id="public",
            occurrence_id="occ-1",
            schedule_item_id=item.id,
            operator_id="dana",
            operator_notes="airing tonight",
        )
        assert report.report_id == "ctar_rep1"
        assert report.dispatch_status == DISPATCH_STATUS_QUEUED
        assert report.dispatch_timestamp == _FIXED_NOW
        assert report.approved_by_operator_id == "dana"
        assert report.operator_notes == "airing tonight"
        assert report.occurrence_id == "occ-1"
        assert report.conflicts_found == 0
        # The report is durable and the engine got a (start) nudge.
        assert schedule_store.get_commit_report("ctar_rep1") is not None
        pending = egress.pop_pending_commands("public")
        assert len(pending) == 1
        assert pending[0].action == "start"

    def test_commit_lost_race_raises_and_writes_nothing(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        """PE-2: when the atomic publish flips 0 rows (another commit won the
        race after this one's dry-run passed), commit() must raise
        CommitConflictError, persist NO report, and dispatch NO command — the
        loser is fully swallowed instead of double-airing / double-auditing."""
        _seed_asset(session_factory)
        schedule_store = _RaceLostScheduleStore(session_factory)
        asset_store = PostgresAssetStore(session_factory)
        dry_run = CommitDryRunService(
            schedule_store, asset_store, clock=lambda: _FIXED_NOW, token_factory=lambda: "tok"
        )
        egress = InMemoryEgressStore()
        dispatcher = PlayoutDispatcher(egress, clock=lambda: _FIXED_NOW, id_factory=lambda: "cmd1")
        service = CommitService(
            dry_run,
            schedule_store,
            dispatcher,
            clock=lambda: _FIXED_NOW,
            report_id_factory=lambda: "rep1",
        )
        item = _create_item(schedule_store, scheduled_at=_AIR)
        with pytest.raises(CommitConflictError):
            service.commit(
                channel_id="public",
                occurrence_id="occ-1",
                schedule_item_id=item.id,
                operator_id="dana",
            )
        assert schedule_store.list_commit_reports(channel_id="public") == []
        assert egress.pop_pending_commands("public") == []

    def test_commit_is_idempotent_in_storage(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        # A single commit leaves exactly one report row (pending upserted to queued).
        _seed_asset(session_factory)
        schedule_store, _egress, service = _build(session_factory)
        item = _create_item(schedule_store, scheduled_at=_AIR)
        service.commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id, operator_id="dana"
        )
        assert len(schedule_store.list_commit_reports(channel_id="public")) == 1


class TestCommitConflict:
    def test_rerace_conflict_raises_and_writes_nothing(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory, "prog-1")
        _seed_asset(session_factory, "prog-2")
        schedule_store, egress, service = _build(session_factory)
        # An overlapping scheduled premiere makes the re-run dry-run fail.
        _create_item(schedule_store, asset_id="prog-2", scheduled_at=_AIR, duration_seconds=1800)
        proposed = _create_item(
            schedule_store,
            asset_id="prog-1",
            scheduled_at=_AIR + timedelta(minutes=10),
            duration_seconds=1800,
        )
        with pytest.raises(CommitConflictError) as exc:
            service.commit(
                channel_id="public",
                occurrence_id="occ-1",
                schedule_item_id=proposed.id,
                operator_id="dana",
            )
        assert exc.value.plan.conflicts_detected  # carries the plan for the API
        # No report persisted and no command dispatched on conflict.
        assert schedule_store.list_commit_reports(channel_id="public") == []
        assert egress.pop_pending_commands("public") == []

    def test_unplayable_at_commit_raises(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory)
        schedule_store, _egress, service = _build(session_factory)
        item = _create_item(schedule_store, scheduled_at=_AIR)
        # Asset deleted between review and commit → re-run dry-run fails.
        with session_factory() as session:
            from sqlalchemy import delete

            session.execute(delete(Asset).where(Asset.asset_id == "prog-1"))
            session.commit()
        with pytest.raises(CommitConflictError):
            service.commit(
                channel_id="public",
                occurrence_id="occ-1",
                schedule_item_id=item.id,
                operator_id="dana",
            )


class TestCommitDispatchFailure:
    def test_dispatch_failure_records_error_without_leaking(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory)
        schedule_store, _egress, service = _build(
            session_factory, egress_store=_RaisingEgressStore()
        )
        item = _create_item(schedule_store, scheduled_at=_AIR)
        report = service.commit(
            channel_id="public", occurrence_id="occ-1", schedule_item_id=item.id, operator_id="dana"
        )
        assert report.dispatch_status == DISPATCH_STATUS_ERROR
        detail = report.dispatch_error_detail or ""
        # The error is recorded with a helpful, non-leaking message.
        assert "RuntimeError" in detail
        assert "s3cr3t" not in detail
        assert "postgres://" not in detail
        # The report is still durably persisted (error state).
        stored = schedule_store.get_commit_report(report.report_id)
        assert stored is not None
        assert stored.dispatch_status == DISPATCH_STATUS_ERROR


class TestCommitNotFound:
    def test_missing_item_raises(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _schedule_store, _egress, service = _build(session_factory)
        with pytest.raises(ScheduleItemNotFoundError):
            service.commit(
                channel_id="public",
                occurrence_id="occ-1",
                schedule_item_id=uuid.uuid4(),
                operator_id="dana",
            )


def _seed_report(schedule_store, report_id, *, schedule_item_id, channel_id="public"):  # type: ignore[no-untyped-def]
    schedule_store.upsert_commit_report(
        CommitToAirReport(
            report_id=report_id,
            channel_id=channel_id,
            occurrence_id=f"occ-{report_id}",
            schedule_item_id=str(schedule_item_id),
            asset_id="prog-1",
            title="A Program",
            scheduled_at=_AIR,
            duration_seconds=1800,
            approved_by_operator_id="dana",
            approved_at=_FIXED_NOW,
            dispatch_status=DISPATCH_STATUS_QUEUED,
            created_at=_FIXED_NOW,
            updated_at=_FIXED_NOW,
        )
    )


class TestRollback:
    def test_rollback_cancels_item_and_enqueues_handback(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(session_factory)
        schedule_store, egress, service = _build(session_factory)
        item = _create_item(schedule_store, scheduled_at=_AIR)
        _seed_report(schedule_store, "ctar_1", schedule_item_id=item.id)
        report = service.rollback(
            report_id="ctar_1", reason="aired the wrong meeting", operator_id="dana"
        )
        assert report.dispatch_status == DISPATCH_STATUS_CANCELLED
        assert report.rollback_reason == "aired the wrong meeting"
        assert report.rolled_back_at is not None
        # The schedule item is cancelled and the engine got a handback nudge.
        assert schedule_store.get(item.id).state == "cancelled"
        assert len(egress.pop_pending_commands("public")) == 1

    def test_rollback_tolerates_already_gone_item(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        schedule_store, _egress, service = _build(session_factory)
        # Report references a schedule item that does not exist — rollback still
        # succeeds (the airing is undone regardless).
        _seed_report(schedule_store, "ctar_1", schedule_item_id=uuid.uuid4())
        report = service.rollback(report_id="ctar_1", reason="cleanup", operator_id="dana")
        assert report.dispatch_status == DISPATCH_STATUS_CANCELLED

    def test_rollback_unknown_report_raises(self, session_factory) -> None:  # type: ignore[no-untyped-def]
        _schedule_store, _egress, service = _build(session_factory)
        with pytest.raises(CommitReportNotFoundError):
            service.rollback(report_id="ctar_nope", reason="x", operator_id="dana")
