# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for civiccast.native.models -- the guard's typed shapes.

House convention: pydantic models carry ``model_config = ConfigDict(extra=
"forbid")`` and derived pass/fail is always a ``@property``. These tests pin
MaintenanceRecord's round-trip and the extra="forbid" contract that
win_probes.read_interlock relies on to classify malformed JSON as
"unreadable" (fail-closed) rather than silently accepting drift.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from civiccast.native.models import (
    A1Result,
    A2Result,
    A3Result,
    CutoverJournal,
    CutoverPhaseRecord,
    GuardDecision,
    GuardInputs,
    InterlockRead,
    MaintenanceRecord,
    SelectorRead,
)


def test_maintenance_record_round_trip() -> None:
    record = MaintenanceRecord(
        v=1,
        state="held",
        generation=3,
        owner_run_id="run-abc123",
        taken_utc="2026-07-17T12:00:00Z",
        released_utc=None,
    )
    dumped = record.model_dump_json()
    restored = MaintenanceRecord.model_validate_json(dumped)
    assert restored == record


def test_maintenance_record_release_round_trip() -> None:
    record = MaintenanceRecord(
        v=1,
        state="released",
        generation=3,
        owner_run_id="run-abc123",
        taken_utc="2026-07-17T12:00:00Z",
        released_utc="2026-07-17T12:05:00Z",
    )
    restored = MaintenanceRecord.model_validate_json(record.model_dump_json())
    assert restored.state == "released"
    assert restored.released_utc == "2026-07-17T12:05:00Z"


def test_maintenance_record_rejects_extra_fields() -> None:
    """FALSIFICATION: a MaintenanceRecord JSON blob with an unknown key must be
    rejected by model_validate_json (extra="forbid"), not silently accepted --
    win_probes.read_interlock depends on this to fail-closed on schema drift."""

    payload = {
        "v": 1,
        "state": "held",
        "generation": 1,
        "owner_run_id": "run-x",
        "taken_utc": "2026-07-17T12:00:00Z",
        "released_utc": None,
        "unexpected_field": "should not be tolerated",
    }
    with pytest.raises(ValidationError):
        MaintenanceRecord.model_validate_json(json.dumps(payload))


def test_maintenance_record_rejects_bad_state() -> None:
    with pytest.raises(ValidationError):
        MaintenanceRecord.model_validate_json(
            json.dumps(
                {
                    "v": 1,
                    "state": "bogus",
                    "generation": 1,
                    "owner_run_id": "run-x",
                    "taken_utc": "2026-07-17T12:00:00Z",
                }
            )
        )


def test_maintenance_record_rejects_negative_generation() -> None:
    with pytest.raises(ValidationError):
        MaintenanceRecord(
            v=1,
            state="held",
            generation=-1,
            owner_run_id="run-x",
            taken_utc="2026-07-17T12:00:00Z",
        )


@pytest.mark.parametrize(
    "model_cls,kwargs",
    [
        (
            SelectorRead,
            {"ok": True, "value": "native", "detail": "read HKLM"},
        ),
        (A1Result, {"live_process": "negative", "run_entry": "negative", "detail": "clear"}),
        (A2Result, {"status": "negative", "detail": "inactive"}),
        (A3Result, {"status": "acquired", "detail": "owned"}),
        (
            InterlockRead,
            {"status": "free", "record": None, "detail": "absent"},
        ),
        (
            GuardDecision,
            {
                "action": "start",
                "named_probe": None,
                "message": "all clear",
                "retry_seconds": None,
                "state_name": None,
            },
        ),
    ],
)
def test_models_forbid_extra_fields(model_cls: type, kwargs: dict[str, object]) -> None:
    """FALSIFICATION: every guard model must reject an unknown field -- the
    house extra="forbid" contract applies uniformly, not just to
    MaintenanceRecord."""

    good = model_cls(**kwargs)
    assert good is not None
    with pytest.raises(ValidationError):
        model_cls(**kwargs, bogus_extra_field=True)


def test_guard_inputs_composition() -> None:
    inputs = GuardInputs(
        selector=SelectorRead(ok=True, value="native", detail="ok"),
        wsl_install_detected=False,
        a1=A1Result(live_process="negative", run_entry="negative", detail="clear"),
        a2=A2Result(status="negative", detail="no distro"),
        a3=A3Result(status="acquired", detail="owned"),
        interlock=InterlockRead(status="free", record=None, detail="absent"),
    )
    assert inputs.selector.value == "native"
    with pytest.raises(ValidationError):
        GuardInputs.model_validate({**inputs.model_dump(), "extra_field": 1})


def test_guard_inputs_wsl_install_detected_accepts_none_unknown_state() -> None:
    """F1: wsl_install_detected is a tri-state (bool | None) -- None means
    the install-detection probe itself could not determine an answer
    (timeout/OSError), distinct from a confirmed True/False."""

    inputs = GuardInputs(
        selector=SelectorRead(ok=True, value="absent", detail="ok"),
        wsl_install_detected=None,
        a1=A1Result(live_process="negative", run_entry="negative", detail="clear"),
        a2=A2Result(status="negative", detail="no distro"),
        a3=A3Result(status="acquired", detail="owned"),
        interlock=InterlockRead(status="free", record=None, detail="absent"),
    )
    assert inputs.wsl_install_detected is None


def test_cutover_journal_ok_property_true_when_all_phases_done_no_errors() -> None:
    journal = CutoverJournal(
        v=1,
        run_id="run-1",
        direction="cutover",
        phases=[
            CutoverPhaseRecord(
                phase=i,
                name=f"phase-{i}",
                status="done",
                started_utc="2026-07-17T12:00:00Z",
                finished_utc="2026-07-17T12:01:00Z",
                detail="ok",
                postcondition="satisfied",
            )
            for i in range(1, 6)
        ],
        unloaded_profiles=[],
        errors=[],
    )
    assert journal.ok is True


def test_cutover_journal_ok_property_false_on_error() -> None:
    journal = CutoverJournal(
        v=1,
        run_id="run-1",
        direction="cutover",
        phases=[
            CutoverPhaseRecord(
                phase=1,
                name="phase-1",
                status="failed",
                started_utc="2026-07-17T12:00:00Z",
                finished_utc=None,
                detail="boom",
                postcondition="unsatisfied",
            ),
        ],
        unloaded_profiles=[],
        errors=["phase 1 failed: boom"],
    )
    assert journal.ok is False


def test_cutover_journal_ok_property_false_when_phase_pending() -> None:
    journal = CutoverJournal(
        v=1,
        run_id="run-1",
        direction="rollback",
        phases=[
            CutoverPhaseRecord(
                phase=1,
                name="phase-1",
                status="pending",
                started_utc=None,
                finished_utc=None,
                detail="not yet run",
                postcondition="unsatisfied",
            ),
        ],
        unloaded_profiles=[],
        errors=[],
    )
    assert journal.ok is False


def test_cutover_phase_record_rejects_out_of_range_phase() -> None:
    with pytest.raises(ValidationError):
        CutoverPhaseRecord(
            phase=6,
            name="phase-6",
            status="pending",
            started_utc=None,
            finished_utc=None,
            detail="",
            postcondition="",
        )
    with pytest.raises(ValidationError):
        CutoverPhaseRecord(
            phase=0,
            name="phase-0",
            status="pending",
            started_utc=None,
            finished_utc=None,
            detail="",
            postcondition="",
        )


def test_cutover_phase_record_verified_on_resume_defaults_to_none_and_is_settable() -> None:
    """F2: CutoverPhaseRecord gains verified_on_resume (bool | None) --
    None means no resume-verify has happened yet (fresh execution); True/False
    record the outcome of the last resume-time postcondition re-check."""

    default_record = CutoverPhaseRecord(
        phase=1,
        name="phase-1",
        status="done",
        started_utc="2026-07-17T12:00:00Z",
        finished_utc="2026-07-17T12:01:00Z",
        detail="ok",
        postcondition="satisfied",
    )
    assert default_record.verified_on_resume is None

    verified_record = CutoverPhaseRecord(
        phase=1,
        name="phase-1",
        status="done",
        started_utc="2026-07-17T12:00:00Z",
        finished_utc="2026-07-17T12:01:00Z",
        detail="ok",
        postcondition="satisfied",
        verified_on_resume=True,
    )
    assert verified_record.verified_on_resume is True
