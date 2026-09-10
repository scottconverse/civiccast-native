# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""beta.5 walkthrough F-21: the rehearsal result is reported apart from the gate.

The readiness headline used to say "Private rehearsal is blocked because a
required broadcast item is not ready" while its detail lines said the
rehearsal ran, passed preflight, finalized a recording and loaded the
resident preview. ``RehearsalReport`` now carries ``rehearsal_result`` (what
the run did) and ``gate`` (which required items block), and the message
names the blocking items.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.installer.models import RehearsalReport, SystemHealthReport
from civiccast.installer.service import (
    _rehearsal_report_from_health,
    build_broadcast_gate,
    build_rehearsal_report,
    build_system_health_report,
)

_STARTED = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_station_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Never read the developer machine's real station state: an unset-up
    # station makes every setup check red, a set-up one makes them green.
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv("CIVICCAST_TESTER_OPS_STATE_PATH", str(tmp_path / "ops-state.json"))
    monkeypatch.setenv("CIVICCAST_BACKUP_DIR", str(tmp_path / "backups"))


def _blocked_health() -> SystemHealthReport:
    # recording_target_count=0 leaves "Local recording" (required) red; on an
    # un-set-up station the setup checks are red as well.
    return build_system_health_report(
        profile="public-meetings",
        live_source_count=1,
        recording_target_count=0,
        live_preflight_ready=True,
        recording_write_probe_ready=True,
        resident_preview_confirmed=True,
    )


def _required_red(health: SystemHealthReport) -> list[str]:
    return [check.id for check in health.checks if check.required and check.color == "red"]


def test_broadcast_gate_names_required_red_items_only() -> None:
    health = _blocked_health()
    expected_red = [check for check in health.checks if check.required and check.color == "red"]

    gate = build_broadcast_gate(health)

    assert gate.color == "red"
    assert expected_red, "fixture must leave at least one required check red"
    assert [item.id for item in gate.blocking] == [check.id for check in expected_red]
    assert "recording-path" in [item.id for item in gate.blocking]
    assert all(item.color == "red" and item.next_step for item in gate.blocking)
    assert all(item.color == "yellow" for item in gate.attention)
    plural = "item" if len(expected_red) == 1 else "items"
    assert gate.summary == (
        f"{len(expected_red)} required {plural} not ready: "
        + ", ".join(check.label for check in expected_red)
        + "."
    )
    # Optional/advanced checks never enter the gate.
    optional_ids = {check.id for check in health.checks if not check.required}
    assert optional_ids.isdisjoint({item.id for item in gate.blocking + gate.attention})


def test_passed_rehearsal_with_red_gate_says_rehearsal_passed_and_names_the_items() -> None:
    report = _rehearsal_report_from_health(
        rehearsal_id="rehearsal-abc",
        started_at=_STARTED,
        health=_blocked_health(),
        evidence=["Live preflight passed for the selected sample."],
        private_session_id="rehearsal-abc",
        recording_asset_id="rehearsal-abc",
        recording_uri="file:///C:/station/rehearsal.mp4",
        resident_preview_proof="Resident preview loaded",
    )

    assert isinstance(report, RehearsalReport)
    assert report.rehearsal_result == "passed"
    assert report.status == "blocked"
    assert report.safe_to_broadcast == "red"
    names = ", ".join(item.label for item in report.gate.blocking)
    count = len(report.gate.blocking)
    assert "Local recording" in names
    assert report.message == (
        f"Rehearsal passed, but the broadcast gate has {count} required "
        f"{'item' if count == 1 else 'items'} not ready: {names}."
    )
    assert "blocked" not in report.message
    assert report.next_step.startswith(f"Fix {names}")
    assert report.next_step.endswith(", then run the check again.")


def test_single_blocking_item_next_step_carries_its_fix_hint() -> None:
    health = _blocked_health()
    only = next(c for c in health.checks if c.id == "recording-path")
    health = health.model_copy(
        update={
            "checks": [
                c
                if c.id == only.id or not (c.required and c.color == "red")
                else c.model_copy(update={"color": "green", "state": "ready"})
                for c in health.checks
            ]
        }
    )
    assert _required_red(health) == [only.id]

    report = _rehearsal_report_from_health(
        rehearsal_id="rehearsal-abc",
        started_at=_STARTED,
        health=health,
        evidence=[],
        recording_asset_id="rehearsal-abc",
    )

    assert [item.id for item in report.gate.blocking] == [only.id]
    assert report.gate.summary == f"1 required item not ready: {only.label}."
    assert report.message == (
        f"Rehearsal passed, but the broadcast gate has 1 required item not ready: {only.label}."
    )
    assert report.next_step == (
        f"Fix {only.label} ({only.next_step.rstrip('.')}), then run the check again."
    )


def test_rehearsal_that_never_ran_is_reported_as_not_run_with_the_items_named() -> None:
    report = _rehearsal_report_from_health(
        rehearsal_id="rehearsal-abc",
        started_at=_STARTED,
        health=_blocked_health(),
        evidence=[],
    )

    assert report.rehearsal_result == "not_run"
    assert report.status == "blocked"
    names = ", ".join(item.label for item in report.gate.blocking)
    count = len(report.gate.blocking)
    assert report.message == (
        f"Private rehearsal is blocked because a required broadcast "
        f"{'item' if count == 1 else 'items'} is not ready: {names}."
    )


def test_explicit_failed_result_survives_a_message_override() -> None:
    report = _rehearsal_report_from_health(
        rehearsal_id="rehearsal-abc",
        started_at=_STARTED,
        health=_blocked_health(),
        evidence=["Rehearsal stopped: disk full"],
        private_session_id="rehearsal-abc",
        recording_uri="file:///C:/station/rehearsal.mp4",
        message_override="Private rehearsal could not complete: disk full.",
        rehearsal_result="failed",
    )

    assert report.rehearsal_result == "failed"
    assert report.message == "Private rehearsal could not complete: disk full."
    assert "recording-path" in [item.id for item in report.gate.blocking]


def test_build_rehearsal_report_evaluates_the_gate_without_claiming_a_run() -> None:
    report = build_rehearsal_report(live_source_count=1, recording_target_count=0)

    assert report.rehearsal_result == "not_run"
    assert report.gate.color == report.safe_to_broadcast
    assert report.gate.blocking


def test_gate_without_red_items_has_no_blocking_entries() -> None:
    health = _blocked_health()
    health = health.model_copy(
        update={
            "checks": [
                c.model_copy(update={"color": "green", "state": "ready"})
                if c.required and c.color == "red"
                else c
                for c in health.checks
            ],
            "safe_to_broadcast": "yellow",
        }
    )
    gate = build_broadcast_gate(health)

    assert gate.blocking == []
    if gate.attention:
        needs = "item still needs" if len(gate.attention) == 1 else "items still need"
        assert gate.summary.startswith(f"{len(gate.attention)} required {needs} attention")
    else:
        assert gate.summary == "All required items are ready."
