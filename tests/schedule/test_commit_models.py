# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Model contract tests for the commit-to-air entities (S4 slice 1).

Covers Pydantic validation, the ephemeral dry-run plan shape, and the
SA-row <-> Pydantic round-trip including the SQLite tz-reattach contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from civiccast.schedule.commit_models import (
    DISPATCH_STATUS_PENDING,
    DISPATCH_STATUS_QUEUED,
    CommitToAirPlan,
    CommitToAirReport,
    CommitToAirReportRow,
    PlayoutEventPlan,
    ScheduleConflict,
)

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)


def _report(**overrides: object) -> CommitToAirReport:
    base: dict[str, object] = {
        "report_id": "ctar_abc123",
        "channel_id": "public",
        "occurrence_id": "occ-public-2026-06-15T18:00:00Z",
        "schedule_item_id": "550e8400-e29b-41d4-a716-446655440000",
        "asset_id": "city-council-2026-06-15",
        "title": "City Council — June 15",
        "scheduled_at": datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC),
        "duration_seconds": 5400,
        "approved_by_operator_id": "dana",
        "approved_at": _NOW,
        "conflicts_found": 0,
        "gaps_found": 0,
        "dispatch_status": DISPATCH_STATUS_QUEUED,
        "dispatch_error_detail": None,
        "dispatch_timestamp": _NOW,
        "operator_notes": "Looks good, airing tonight.",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return CommitToAirReport(**base)  # type: ignore[arg-type]


class TestScheduleConflict:
    def test_constructs_with_overlap(self) -> None:
        conflict = ScheduleConflict(
            existing_schedule_item_id="550e8400-e29b-41d4-a716-446655440000",
            existing_asset_id="other",
            existing_asset_title="Other meeting",
            existing_scheduled_at=datetime(2026, 6, 15, 17, 30, tzinfo=UTC),
            existing_duration_seconds=3600,
            proposed_scheduled_at=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            proposed_duration_seconds=5400,
            overlap_seconds=1800,
        )
        assert conflict.overlap_seconds == 1800

    def test_rejects_negative_overlap(self) -> None:
        with pytest.raises(ValidationError):
            ScheduleConflict(
                existing_schedule_item_id="x",
                existing_asset_id="y",
                existing_asset_title="z",
                existing_scheduled_at=_NOW,
                existing_duration_seconds=10,
                proposed_scheduled_at=_NOW,
                proposed_duration_seconds=10,
                overlap_seconds=-1,
            )


class TestPlayoutEventPlan:
    def test_gap_segment(self) -> None:
        gap = PlayoutEventPlan(
            kind="gap",
            starts_at=datetime(2026, 6, 15, 17, 55, tzinfo=UTC),
            ends_at=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            duration_seconds=300.0,
            label="Dead air before City Council",
        )
        assert gap.kind == "gap"
        assert gap.duration_seconds == 300.0

    def test_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValidationError):
            PlayoutEventPlan(
                kind="filler",  # type: ignore[arg-type]
                starts_at=_NOW,
                ends_at=_NOW,
                duration_seconds=0.0,
            )


class TestCommitToAirPlan:
    def test_dry_run_plan_round_trips_through_json(self) -> None:
        plan = CommitToAirPlan(
            plan_id="ctap_xyz",
            channel_id="public",
            occurrence_id="occ-1",
            schedule_item_id="550e8400-e29b-41d4-a716-446655440000",
            asset_id="city-council-2026-06-15",
            title="City Council",
            scheduled_at=datetime(2026, 6, 15, 18, 0, tzinfo=UTC),
            duration_seconds=5400,
            dry_run_passed=False,
            conflicts_detected=[
                ScheduleConflict(
                    existing_schedule_item_id="550e8400-e29b-41d4-a716-446655440000",
                    existing_asset_id="other",
                    existing_asset_title="Other",
                    existing_scheduled_at=_NOW,
                    existing_duration_seconds=600,
                    proposed_scheduled_at=_NOW,
                    proposed_duration_seconds=5400,
                    overlap_seconds=600,
                )
            ],
            missing_media_detail=None,
            gaps_detected=[
                PlayoutEventPlan(
                    kind="gap",
                    starts_at=_NOW,
                    ends_at=_NOW + timedelta(seconds=2),
                    duration_seconds=2.0,
                )
            ],
            created_at=_NOW,
            operator_id="dana",
        )
        restored = CommitToAirPlan.model_validate_json(plan.model_dump_json())
        assert restored == plan
        assert restored.dry_run_passed is False
        assert restored.conflicts_detected[0].overlap_seconds == 600

    def test_defaults_empty_detection_lists(self) -> None:
        plan = CommitToAirPlan(
            plan_id="ctap_xyz",
            channel_id="public",
            occurrence_id="occ-1",
            schedule_item_id="s-1",
            asset_id="a-1",
            title="t",
            scheduled_at=_NOW,
            duration_seconds=60,
            dry_run_passed=True,
            created_at=_NOW,
        )
        assert plan.conflicts_detected == []
        assert plan.gaps_detected == []
        assert plan.operator_id is None


class TestCommitToAirReport:
    def test_default_dispatch_status_is_pending(self) -> None:
        report = _report()
        report2 = CommitToAirReport(
            report_id="ctar_2",
            channel_id="public",
            occurrence_id="occ-1",
            schedule_item_id="s-1",
            asset_id="a-1",
            title="t",
            scheduled_at=_NOW,
            duration_seconds=60,
            approved_by_operator_id="dana",
            approved_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert report.dispatch_status == DISPATCH_STATUS_QUEUED
        assert report2.dispatch_status == DISPATCH_STATUS_PENDING

    def test_rejects_unknown_dispatch_status(self) -> None:
        with pytest.raises(ValidationError):
            _report(dispatch_status="airborne")

    def test_accepts_cancelled_status(self) -> None:
        # 'cancelled' must be a valid status (rollback path); the four-value
        # spec CHECK was reconciled to the five-value superset.
        assert _report(dispatch_status="cancelled").dispatch_status == "cancelled"


class TestRowRoundTrip:
    def test_from_report_to_report_is_identity(self) -> None:
        report = _report()
        row = CommitToAirReportRow.from_report(report)
        assert row.to_report() == report

    def test_to_report_reattaches_utc_on_naive_datetimes(self) -> None:
        # Simulate SQLite's tz-stripping round-trip: build a row whose
        # datetimes are naive, then confirm to_report() re-attaches UTC so
        # the API contract presents aware datetimes regardless of backend.
        row = CommitToAirReportRow.from_report(_report())
        row.scheduled_at = datetime(2026, 6, 15, 18, 0, 0)  # naive
        row.approved_at = datetime(2026, 6, 15, 12, 0, 0)  # naive
        row.dispatch_timestamp = datetime(2026, 6, 15, 12, 0, 0)  # naive
        row.created_at = datetime(2026, 6, 15, 12, 0, 0)  # naive
        row.updated_at = datetime(2026, 6, 15, 12, 0, 0)  # naive
        restored = row.to_report()
        assert restored.scheduled_at.tzinfo is not None
        assert restored.scheduled_at == datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)
        assert restored.approved_at.tzinfo == UTC
        assert restored.dispatch_timestamp is not None
        assert restored.dispatch_timestamp.tzinfo == UTC

    def test_from_report_normalizes_non_utc_offset_to_utc(self) -> None:
        # An aware datetime in a non-UTC offset is normalized to UTC at the
        # persistence boundary (mirrors ScheduleItem create).
        eastern = timezone(timedelta(hours=-5))
        report = _report(
            scheduled_at=datetime(2026, 6, 15, 13, 0, 0, tzinfo=eastern),
        )
        row = CommitToAirReportRow.from_report(report)
        assert row.scheduled_at == datetime(2026, 6, 15, 18, 0, 0, tzinfo=UTC)

    def test_to_report_preserves_none_dispatch_timestamp(self) -> None:
        report = _report(dispatch_timestamp=None, dispatch_status=DISPATCH_STATUS_PENDING)
        row = CommitToAirReportRow.from_report(report)
        assert row.dispatch_timestamp is None
        assert row.to_report().dispatch_timestamp is None
