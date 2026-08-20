# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.native.runtime_cli -- platform-independent.

Every registry/wsl/mutex interaction here goes through injected fakes
(monkeypatched module-level probe bindings, or explicit override callables
passed straight to run_cutover/run_rollback) -- this file has no "win" in
its name deliberately: it is NOT Windows-only and must pass on ubuntu CI's
pure suite too.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from civiccast.native import runtime_cli
from civiccast.native.models import (
    A1Result,
    A2Result,
    A3Result,
    GuardDecision,
    GuardInputs,
    InterlockRead,
    MaintenanceRecord,
    SelectorRead,
)

runner = CliRunner()

# CC-WS4-006: run_rollback's preflight requires a REAL existing file on
# disk -- sys.executable (this venv's python.exe) is guaranteed to exist
# without touching anything test-fixture-specific.
_A_REAL_FILE = sys.executable


def _patch_all_clear_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_cli, "read_selector", lambda: SelectorRead(ok=True, value="native", detail="ok")
    )
    monkeypatch.setattr(
        runtime_cli,
        "probe_keeper",
        lambda: A1Result(live_process="negative", run_entry="negative", detail="clear"),
    )
    monkeypatch.setattr(
        runtime_cli,
        "probe_indistro_services",
        lambda: A2Result(status="negative", detail="inactive"),
    )
    monkeypatch.setattr(runtime_cli, "detect_wsl_install", lambda: False)

    class _FakeMutex:
        def __init__(self, *, name: str = "", sddl: str = "") -> None:
            pass

        def acquire(self, timeout_ms: int = 0) -> A3Result:
            return A3Result(status="acquired", detail="owned")

        def release(self) -> None:
            pass

    monkeypatch.setattr(runtime_cli, "RuntimeOwnerMutex", _FakeMutex)

    # CC-WS4-003: read_interlock/take_interlock/release_interlock are a
    # STATEFUL trio here (not three independent constants) -- run_cutover/
    # run_rollback's interlock bracket reads back what it just took, so a
    # reader permanently pinned to "free" would make the bracket-verify
    # step fail right after a successful OWNED-mode take.
    interlock_state: dict[str, MaintenanceRecord | None] = {"record": None}

    def fake_read_interlock() -> InterlockRead:
        record = interlock_state["record"]
        if record is None or record.state == "released":
            return InterlockRead(status="free", record=None, detail="test fake: free")
        return InterlockRead(status="held", record=record, detail="test fake: held")

    def fake_take_interlock(owner_run_id: str) -> MaintenanceRecord:
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )
        interlock_state["record"] = record
        return record

    def fake_release_interlock() -> MaintenanceRecord:
        current = interlock_state["record"] or MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id="unknown",
            taken_utc="2026-07-18T00:00:00Z",
        )
        released = current.model_copy(
            update={"state": "released", "released_utc": "2026-07-18T00:05:00Z"}
        )
        interlock_state["record"] = released
        return released

    monkeypatch.setattr(runtime_cli, "read_interlock", fake_read_interlock)
    monkeypatch.setattr(runtime_cli, "take_interlock", fake_take_interlock)
    monkeypatch.setattr(runtime_cli, "release_interlock", fake_release_interlock)


def _clear_interlock_kwargs() -> dict[str, object]:
    """CC-WS4-003: default OWNED-mode-clear interlock fakes for direct
    run_cutover/run_rollback calls that are not themselves exercising the
    interlock bracket -- a stateful trio (take -> held; release -> free)
    matching the real take_interlock/read_interlock/release_interlock
    contract, so phases proceed exactly as they did before the interlock
    bracket existed. Independent state per call (each test gets its own)."""

    state: dict[str, MaintenanceRecord | None] = {"record": None}

    def fake_reader() -> InterlockRead:
        record = state["record"]
        if record is None or record.state == "released":
            return InterlockRead(status="free", record=None, detail="test fake: free")
        return InterlockRead(status="held", record=record, detail="test fake: held")

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )
        state["record"] = record
        return record

    def fake_releaser() -> MaintenanceRecord:
        current = state["record"] or MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id="unknown",
            taken_utc="2026-07-18T00:00:00Z",
        )
        released = current.model_copy(
            update={"state": "released", "released_utc": "2026-07-18T00:05:00Z"}
        )
        state["record"] = released
        return released

    return {
        "interlock_reader": fake_reader,
        "interlock_taker": fake_taker,
        "interlock_releaser": fake_releaser,
    }


def _fake_probe_snapshot() -> GuardInputs:
    return GuardInputs(
        selector=SelectorRead(ok=True, value="native", detail="test fake"),
        wsl_install_detected=False,
        a1=A1Result(live_process="negative", run_entry="negative", detail="test fake"),
        a2=A2Result(status="negative", detail="test fake"),
        a3=A3Result(status="acquired", detail="test fake"),
        interlock=InterlockRead(status="free", record=None, detail="test fake"),
    )


def _clear_cutover_kwargs() -> dict[str, object]:
    """CC-WS4-007: ``_clear_interlock_kwargs()`` PLUS a fake
    ``probe_snapshot`` -- cutover's phase 5 defaults to the REAL
    ``_compose_guard_inputs()`` (real registry/wsl/mutex reads) when no
    override is given. Rollback has no phase 5/evidence step and does NOT
    accept a ``probe_snapshot`` kwarg at all -- this helper is cutover-only;
    use ``_clear_interlock_kwargs()`` alone for rollback calls."""

    return {**_clear_interlock_kwargs(), "probe_snapshot": _fake_probe_snapshot}


# --------------------------------------------------------------------------
# status --json round-trips GuardDecision
# --------------------------------------------------------------------------


def test_status_json_round_trips_guard_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_clear_probes(monkeypatch)
    result = runner.invoke(runtime_cli.runtime_app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    decision = GuardDecision.model_validate(payload["decision"])
    assert decision.action == "start"


def test_status_json_nonzero_exit_when_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_clear_probes(monkeypatch)
    monkeypatch.setattr(
        runtime_cli,
        "probe_keeper",
        lambda: A1Result(live_process="positive", run_entry="negative", detail="wsl.exe keeper"),
    )
    result = runner.invoke(runtime_cli.runtime_app, ["status", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    decision = GuardDecision.model_validate(payload["decision"])
    assert decision.action == "refuse"
    assert decision.named_probe == "A1"


def test_status_human_readable_output_mentions_action(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_clear_probes(monkeypatch)
    result = runner.invoke(runtime_cli.runtime_app, ["status"])
    assert result.exit_code == 0, result.output
    assert "start" in result.output.lower()


# --------------------------------------------------------------------------
# probe -- raw GuardInputs diagnostics
# --------------------------------------------------------------------------


def test_probe_json_dumps_guard_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_clear_probes(monkeypatch)
    result = runner.invoke(runtime_cli.runtime_app, ["probe", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selector"]["value"] == "native"
    assert payload["a1"]["live_process"] == "negative"


# --------------------------------------------------------------------------
# run_cutover: journal idempotency, resumability, call-count proof
# --------------------------------------------------------------------------


def test_run_cutover_all_phases_succeed_fresh_journal(tmp_path):
    calls = {"p1": 0, "p2": 0, "p3": 0, "p4": 0}

    def phase1():
        calls["p1"] += 1
        return "no distro registered"

    def phase2():
        calls["p2"] += 1
        return ["SomeSid"], ["UnloadedSid1", "UnloadedSid2"], None

    def phase3():
        calls["p3"] += 1

    def phase4():
        calls["p4"] += 1
        return "distro retained"

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=phase1,
        phase2_remove_run_entries=phase2,
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=phase3,
        phase4_record_retained=phase4,
        **_clear_cutover_kwargs(),
    )
    assert journal.ok is True
    assert [p.status for p in journal.phases] == ["done"] * 5
    assert journal.unloaded_profiles == ["UnloadedSid1", "UnloadedSid2"]
    assert calls == {"p1": 1, "p2": 1, "p3": 1, "p4": 1}

    journal_path = tmp_path / "runtime-cutover-journal.json"
    assert journal_path.exists()
    evidence_files = list(tmp_path.glob("runtime-cutover-evidence-*.json"))
    assert len(evidence_files) == 1
    evidence_md_files = list(tmp_path.glob("runtime-cutover-evidence-*.md"))
    assert len(evidence_md_files) == 1


def test_run_cutover_phase2_failure_then_resume_does_not_redo_phase1() -> None:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp)
        calls = {"p1": 0, "p2": 0}

        def phase1():
            calls["p1"] += 1
            return "no distro registered"

        def phase2_raises():
            calls["p2"] += 1
            raise RuntimeError("simulated registry failure mid-phase")

        interlock_kwargs = _clear_cutover_kwargs()
        journal = runtime_cli.run_cutover(
            state_dir=state_dir,
            phase1_stop_service=phase1,
            phase1_verify=lambda: (True, "verified for test"),
            phase2_remove_run_entries=phase2_raises,
            **interlock_kwargs,
        )
        assert journal.ok is False
        phase_by_number = {p.phase: p for p in journal.phases}
        assert phase_by_number[1].status == "done"
        assert phase_by_number[2].status == "failed"
        assert 2 not in [p.phase for p in journal.phases if p.status == "done"]
        assert any("phase 2 failed" in e for e in journal.errors)
        assert calls == {"p1": 1, "p2": 1}

        def phase2_healthy():
            calls["p2"] += 1
            return [], [], None

        def phase3():
            pass

        def phase4():
            return "retained"

        journal2 = runtime_cli.run_cutover(
            state_dir=state_dir,
            phase1_stop_service=phase1,
            phase1_verify=lambda: (True, "verified for test"),
            phase2_remove_run_entries=phase2_healthy,
            phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
            phase3_write_native=phase3,
            phase4_record_retained=phase4,
            **interlock_kwargs,
        )
        assert journal2.ok is True
        # phase 1 was already "done" -- must NOT be re-invoked.
        assert calls["p1"] == 1
        # phase 2 retried exactly once more (it had failed).
        assert calls["p2"] == 2


def test_run_cutover_phase1_no_distro_is_success_not_failure(tmp_path) -> None:
    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    phase1 = next(p for p in journal.phases if p.phase == 1)
    assert phase1.status == "done"
    assert "no distro registered" in phase1.detail


def test_run_cutover_phase2_fresh_execution_confirms_postcondition_before_done(tmp_path) -> None:
    """CC-WS4-005: phase 2's verify must confirm the no-marker
    postcondition on the FRESH execution before recording done -- an
    action that returns without raising is not proof its postcondition
    actually holds (e.g. a partial hive scan could miss a marker the
    verify's independent re-scan would catch)."""

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (False, "a marker was still found after removal"),
        **_clear_cutover_kwargs(),
    )
    phase2 = next(p for p in journal.phases if p.phase == 2)
    assert phase2.status == "failed"
    assert journal.ok is False


def test_run_cutover_phase2_fresh_execution_passes_when_postcondition_confirmed(tmp_path) -> None:
    """The passing direction: a fresh phase 2 whose verify confirms the
    postcondition holds is recorded done, same as before this fix."""

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    phase2 = next(p for p in journal.phases if p.phase == 2)
    assert phase2.status == "done"
    assert journal.ok is True


# --------------------------------------------------------------------------
# F2: journal resume must RE-VERIFY postconditions, not trust a "done"
# status on faith. A "done" phase's `verify` callable is re-run on every
# resume; a pass skips the phase (as before); a FAIL re-executes it.
# --------------------------------------------------------------------------


def _cutover_kwargs_all_verify_true(**overrides: object) -> dict[str, object]:
    """Baseline: every phase's action is a no-op success and every verify
    trivially passes -- individual tests override just the phase(s) under
    test."""

    base: dict[str, object] = {
        "phase1_stop_service": lambda: "no distro registered",
        "phase1_verify": lambda: (True, "trivially true for test"),
        "phase2_remove_run_entries": lambda: ([], [], None),
        "phase2_verify": lambda: (True, "trivially true for test"),
        "phase3_write_native": lambda: None,
        "phase3_verify": lambda: (True, "trivially true for test"),
        "phase4_record_retained": lambda: "retained",
        "phase4_verify": lambda: (True, "trivially true for test"),
        "phase5_verify": lambda: (True, "trivially true for test"),
        **_clear_cutover_kwargs(),
    }
    base.update(overrides)
    return base


def test_run_cutover_phase3_resume_reverifies_and_reexecutes_if_selector_flipped_back(
    tmp_path,
) -> None:
    """F2 FALSIFICATION -- the reviewer's exact scenario: cutover completes
    phase 3 (selector written "native"), the journal marks it done; the
    selector is then externally flipped back to "wsl" (fake registry
    tampering between runs); a re-run must NOT trust the stale "done"
    status -- phase 3's verify re-checks the postcondition, finds it false,
    and RE-EXECUTES the phase. journal.ok is only true if the FINAL selector
    reads "native"."""

    fake_selector = {"value": "absent"}
    write_calls = {"n": 0}

    def phase3_write_native() -> None:
        write_calls["n"] += 1
        fake_selector["value"] = "native"

    def phase3_verify() -> tuple[bool, str]:
        return fake_selector["value"] == "native", f"selector={fake_selector['value']!r}"

    kwargs = _cutover_kwargs_all_verify_true(
        phase3_write_native=phase3_write_native, phase3_verify=phase3_verify
    )

    journal = runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert journal.ok is True
    assert write_calls["n"] == 1
    phase3 = next(p for p in journal.phases if p.phase == 3)
    assert phase3.status == "done"

    # External tampering between runs: something flips the selector back.
    fake_selector["value"] = "wsl"

    journal2 = runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert write_calls["n"] == 2, (
        "phase 3 must be RE-EXECUTED, not skipped, when resume-verify fails"
    )
    phase3_after = next(p for p in journal2.phases if p.phase == 3)
    assert phase3_after.status == "done"
    assert phase3_after.verified_on_resume is False
    assert fake_selector["value"] == "native", "re-execution must actually fix the tampered state"
    assert journal2.ok is True


def test_run_cutover_phase3_resume_skips_without_reexecuting_when_verify_passes(tmp_path) -> None:
    """F2, the passing direction: when resume-verify confirms the
    postcondition still holds, the phase is skipped (not re-invoked) -- the
    fix must not turn every resume into a full re-run."""

    write_calls = {"n": 0}

    def phase3_write_native() -> None:
        write_calls["n"] += 1

    kwargs = _cutover_kwargs_all_verify_true(phase3_write_native=phase3_write_native)

    runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert write_calls["n"] == 1

    journal2 = runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert write_calls["n"] == 1, "verify passed -- phase 3 must NOT be re-invoked"
    phase3_after = next(p for p in journal2.phases if p.phase == 3)
    assert phase3_after.verified_on_resume is True


def test_run_cutover_phase1_resume_reverifies_and_reexecutes_if_services_now_active(
    tmp_path,
) -> None:
    """F2 FALSIFICATION, the phase-1 case: phase 1 (in-distro disable+stop)
    is marked done, but a resume-time verify finds civiccast* has become
    active again -- must re-execute, never trust the stale "done" record."""

    fake_active = {"value": False}
    stop_calls = {"n": 0}

    def phase1_stop_service() -> str:
        stop_calls["n"] += 1
        fake_active["value"] = False
        return "civiccast* disabled and stopped in-distro"

    def phase1_verify() -> tuple[bool, str]:
        return (not fake_active["value"]), f"civiccast* active={fake_active['value']}"

    kwargs = _cutover_kwargs_all_verify_true(
        phase1_stop_service=phase1_stop_service, phase1_verify=phase1_verify
    )

    journal = runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert stop_calls["n"] == 1
    phase1 = next(p for p in journal.phases if p.phase == 1)
    assert phase1.status == "done"

    # Something re-activated the service after the journal marked done.
    fake_active["value"] = True

    journal2 = runtime_cli.run_cutover(state_dir=tmp_path, **kwargs)
    assert stop_calls["n"] == 2, (
        "phase 1 must be RE-EXECUTED when resume-verify finds services active again"
    )
    phase1_after = next(p for p in journal2.phases if p.phase == 1)
    assert phase1_after.status == "done"
    assert phase1_after.verified_on_resume is False
    assert fake_active["value"] is False


def test_run_rollback_phase2_resume_reverifies_selector(tmp_path) -> None:
    """F2 mirror on the rollback side: phase 2 (selector := wsl) resume-verify
    re-checks the selector reads "wsl"; a tampered-back-to-native selector
    must trigger re-execution."""

    fake_selector = {"value": "native"}
    write_calls = {"n": 0}

    def phase2_write_wsl() -> None:
        write_calls["n"] += 1
        fake_selector["value"] = "wsl"

    def phase2_verify() -> tuple[bool, str]:
        return fake_selector["value"] == "wsl", f"selector={fake_selector['value']!r}"

    interlock_kwargs = _clear_interlock_kwargs()
    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=phase2_write_wsl,
        phase2_verify=phase2_verify,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase3_verify=lambda: (True, "trivially true for test"),
        phase4_restore_run_entry=lambda exe_path: "restored",
        phase4_verify=lambda: (True, "trivially true for test"),
        **interlock_kwargs,
    )
    assert write_calls["n"] == 1
    phase2 = next(p for p in journal.phases if p.phase == 2)
    assert phase2.status == "done"

    fake_selector["value"] = "native"  # external tampering

    journal2 = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=phase2_write_wsl,
        phase2_verify=phase2_verify,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase3_verify=lambda: (True, "trivially true for test"),
        phase4_restore_run_entry=lambda exe_path: "restored",
        phase4_verify=lambda: (True, "trivially true for test"),
        **interlock_kwargs,
    )
    assert write_calls["n"] == 2
    phase2_after = next(p for p in journal2.phases if p.phase == 2)
    assert phase2_after.verified_on_resume is False
    assert fake_selector["value"] == "wsl"


# --------------------------------------------------------------------------
# F1: _default_phase1_stop_service / _default_phase3_reenable_service must
# not conflate an UNKNOWN wsl-install-detection state with a confirmed
# "no distro registered" -- a bare `if not detect_wsl_install():` would
# silently treat None (falsy) the same as False.
# --------------------------------------------------------------------------


def test_default_phase1_stop_service_raises_when_wsl_install_state_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_cli, "detect_wsl_install", lambda: None)
    with pytest.raises(RuntimeError, match="unknown"):
        runtime_cli._default_phase1_stop_service()


def test_run_cutover_phase1_fails_never_done_when_wsl_install_state_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """F1: the cutover phase-1 default action must FAIL (journal status
    "failed", re-run retries) when the install-detection probe cannot
    determine an answer -- never silently record "done" as if there were
    confirmed nothing to stop."""

    monkeypatch.setattr(runtime_cli, "detect_wsl_install", lambda: None)
    journal = runtime_cli.run_cutover(state_dir=tmp_path, **_clear_cutover_kwargs())
    phase1 = next(p for p in journal.phases if p.phase == 1)
    assert phase1.status == "failed"
    assert "unknown" in phase1.detail.lower()
    assert journal.ok is False


def test_default_phase3_reenable_service_raises_when_wsl_install_state_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_cli, "detect_wsl_install", lambda: None)
    with pytest.raises(RuntimeError, match="unknown"):
        runtime_cli._default_phase3_reenable_service()


# --------------------------------------------------------------------------
# run_rollback
# --------------------------------------------------------------------------


def test_run_rollback_all_phases_succeed(tmp_path) -> None:
    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored for invoking user",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is True
    assert journal.direction == "rollback"
    assert [p.status for p in journal.phases] == ["done"] * 4


def test_run_rollback_absent_distro_is_a_failure() -> None:
    """Unlike cutover, an absent distro during rollback's re-enable phase IS
    an error (there is nothing to roll back to)."""

    import tempfile
    from pathlib import Path

    def raising_phase3():
        raise RuntimeError("no CivicCast distro registered -- cannot re-enable services")

    with tempfile.TemporaryDirectory() as tmp:
        journal = runtime_cli.run_rollback(
            state_dir=Path(tmp),
            exe_path=_A_REAL_FILE,
            phase2_write_wsl=lambda: None,
            phase3_reenable_service=raising_phase3,
            phase4_restore_run_entry=lambda exe_path: "restored",
            **_clear_interlock_kwargs(),
        )
    assert journal.ok is False
    phase3 = next(p for p in journal.phases if p.phase == 3)
    assert phase3.status == "failed"


# --------------------------------------------------------------------------
# CC-WS4-006 (round 2, Major -- auditor panel): rollback requires a valid,
# EXISTING keeper exe path -- preflighted BEFORE any mutation -- rather than
# treating an absent path as a normal "Run entry NOT restored" success.
# --------------------------------------------------------------------------


def test_run_rollback_no_exe_path_and_no_journal_recorded_path_fails_before_mutation(
    tmp_path,
) -> None:
    """RED-FIRST control: run_rollback(exe_path=None) with no journal-
    recorded path => nonzero, selector unchanged (the preflight refuses
    before phase 2 -- the selector-mutating phase -- ever runs)."""

    selector_writes: list[str] = []

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=None,
        phase2_write_wsl=lambda: selector_writes.append("wsl"),
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is False
    assert selector_writes == []
    assert any("exe path" in e.lower() for e in journal.errors)


def test_run_rollback_invalid_exe_path_fails_before_mutation(tmp_path) -> None:
    """The other half: an --exe-path that does not exist on disk must ALSO
    refuse before any mutation, not just a wholly-absent one."""

    selector_writes: list[str] = []

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=str(tmp_path / "does-not-exist.exe"),
        phase2_write_wsl=lambda: selector_writes.append("wsl"),
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is False
    assert selector_writes == []
    assert any("does not exist" in e.lower() for e in journal.errors)


def test_run_rollback_valid_exe_path_proceeds(tmp_path) -> None:
    """The passing direction: a real, existing --exe-path lets the phases
    proceed, and the resolved path is bound onto the journal."""

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: f"restored to {exe_path}",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is True
    assert journal.removed_run_entry_exe_path == _A_REAL_FILE
    phase4 = next(p for p in journal.phases if p.phase == 4)
    assert _A_REAL_FILE in phase4.detail


def test_run_rollback_derives_exe_path_from_prior_completed_cutover_journal(tmp_path) -> None:
    """CC-WS4-006: a prior COMPLETED cutover's journal (direction=cutover,
    ok=True) recorded an exe path in phase 2's removal -- a later rollback
    with NO --exe-path must derive it from that journal rather than
    requiring the operator to re-supply it."""

    cutover_journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: (["SomeSid"], [], _A_REAL_FILE),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    assert cutover_journal.ok is True
    assert cutover_journal.removed_run_entry_exe_path == _A_REAL_FILE

    seen_exe_paths: list[str | None] = []
    rollback_journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=None,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: seen_exe_paths.append(exe_path) or "restored",
        **_clear_interlock_kwargs(),
    )
    assert rollback_journal.ok is True
    assert seen_exe_paths == [_A_REAL_FILE]
    assert rollback_journal.removed_run_entry_exe_path == _A_REAL_FILE


# --------------------------------------------------------------------------
# CC-WS4-003 (round 2, Critical): cutover-to-native / rollback-to-wsl must
# run INSIDE the D7a transfer interlock. Default (no --interlock-owner):
# the command takes and holds the interlock itself for the whole
# transaction. Migration case (--interlock-owner + --interlock-generation):
# the command does NOT take its own -- it continuously re-verifies a
# caller-owned held record before every phase and after the selector
# mutation; free/released/unreadable/wrong-owner/generation-drift aborts
# BEFORE any selector mutation.
# --------------------------------------------------------------------------


def test_cutover_owned_mode_takes_interlock_when_none_provided(tmp_path) -> None:
    """RED-FIRST control (a): interlock free at start + no --interlock-owner
    => the command TAKES it itself (take_interlock called, journal records
    the owner/generation it took)."""

    take_calls: list[str] = []

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        take_calls.append(owner_run_id)
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        if not take_calls:
            return InterlockRead(status="free", record=None, detail="not yet taken")
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    def fake_releaser() -> MaintenanceRecord:
        return MaintenanceRecord(
            v=1,
            state="released",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
            released_utc="2026-07-18T00:05:00Z",
        )

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        interlock_taker=fake_taker,
        interlock_reader=fake_reader,
        interlock_releaser=fake_releaser,
        probe_snapshot=_fake_probe_snapshot,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
    )
    assert len(take_calls) == 1
    assert take_calls[0] == journal.run_id
    assert journal.interlock_owner_run_id == journal.run_id
    assert journal.interlock_generation == 1
    assert journal.ok is True


def test_cutover_external_mode_free_record_aborts_before_selector_write(tmp_path) -> None:
    """RED-FIRST control (b): --interlock-owner given but the record reads
    free/released => exit nonzero BEFORE any selector mutation (assert the
    selector-write action was never invoked)."""

    selector_writes: list[str] = []

    def fake_reader() -> InterlockRead:
        return InterlockRead(status="free", record=None, detail="released")

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        interlock_owner="migration-run-1",
        interlock_generation=5,
        interlock_reader=fake_reader,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase3_write_native=lambda: selector_writes.append("native"),
        phase4_record_retained=lambda: "retained",
    )
    assert journal.ok is False
    assert selector_writes == []
    assert journal.phases == []
    assert any("interlock" in e.lower() for e in journal.errors)


def test_cutover_external_mode_generation_drift_mid_transaction_aborts(tmp_path) -> None:
    """RED-FIRST control (c): the interlock's generation drifts mid-
    transaction (simulated during phase 2's action) => abort before
    completion, never reaching phase 3's selector write."""

    state = {"generation": 5}
    selector_writes: list[str] = []

    def fake_reader() -> InterlockRead:
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=state["generation"],
            owner_run_id="migration-run-1",
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    def phase2_action() -> tuple[list[str], list[str], None]:
        state["generation"] = 6  # drift happens during phase 2
        return [], [], None

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        interlock_owner="migration-run-1",
        interlock_generation=5,
        interlock_reader=fake_reader,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=phase2_action,
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: selector_writes.append("native"),
        phase4_record_retained=lambda: "retained",
    )
    assert journal.ok is False
    assert selector_writes == []
    assert 3 not in [p.phase for p in journal.phases if p.status == "done"]
    assert any("generation" in e.lower() for e in journal.errors)


def test_cutover_external_mode_released_mid_transaction_aborts_at_next_boundary(tmp_path) -> None:
    """RED-FIRST control (d): tamper -- the interlock is released
    mid-transaction (simulated during phase 1's action) => the NEXT phase
    boundary (before phase 2) aborts."""

    state = {"status": "held"}
    selector_writes: list[str] = []

    def fake_reader() -> InterlockRead:
        if state["status"] == "held":
            record = MaintenanceRecord(
                v=1,
                state="held",
                generation=5,
                owner_run_id="migration-run-1",
                taken_utc="2026-07-18T00:00:00Z",
            )
            return InterlockRead(status="held", record=record, detail="held")
        return InterlockRead(status="free", record=None, detail="released")

    def phase1_action() -> str:
        state["status"] = "released"  # tamper happens during phase 1
        return "no distro registered"

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        interlock_owner="migration-run-1",
        interlock_generation=5,
        interlock_reader=fake_reader,
        phase1_stop_service=phase1_action,
        phase2_remove_run_entries=lambda: ([], [], None),
        phase3_write_native=lambda: selector_writes.append("native"),
        phase4_record_retained=lambda: "retained",
    )
    assert journal.ok is False
    assert selector_writes == []
    phase1_record = next((p for p in journal.phases if p.phase == 1), None)
    assert phase1_record is not None
    assert phase1_record.status == "done"
    assert 2 not in [p.phase for p in journal.phases if p.status == "done"]


def test_cutover_owned_mode_leaves_interlock_held_on_phase_failure(tmp_path) -> None:
    """A half-done cutover stays frozen (the safe direction): on a phase
    failure, the OWNED-mode interlock must NOT be released."""

    release_calls = {"n": 0}

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id="whatever-run-id-was-taken",
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    def fake_releaser() -> MaintenanceRecord:
        release_calls["n"] += 1
        return MaintenanceRecord(
            v=1, state="released", generation=1, owner_run_id="x", taken_utc="2026-07-18T00:00:00Z"
        )

    def phase2_raises() -> tuple[list[str], list[str]]:
        raise RuntimeError("simulated failure")

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        interlock_taker=fake_taker,
        interlock_reader=fake_reader,
        interlock_releaser=fake_releaser,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=phase2_raises,
    )
    assert journal.ok is False
    assert release_calls["n"] == 0


def test_rollback_owned_mode_takes_interlock_when_none_provided(tmp_path) -> None:
    """CC-WS4-003: rollback-to-wsl gets the same interlock treatment as
    cutover-to-native (it also mutates the selector)."""

    take_calls: list[str] = []

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        take_calls.append(owner_run_id)
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        if not take_calls:
            return InterlockRead(status="free", record=None, detail="not yet taken")
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    def fake_releaser() -> MaintenanceRecord:
        return MaintenanceRecord(
            v=1,
            state="released",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
        )

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        interlock_taker=fake_taker,
        interlock_reader=fake_reader,
        interlock_releaser=fake_releaser,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
    )
    assert len(take_calls) == 1
    assert journal.interlock_owner_run_id == journal.run_id
    assert journal.ok is True


def test_rollback_external_mode_free_record_aborts_before_selector_write(tmp_path) -> None:
    """CC-WS4-003 rollback mirror of control (b)."""

    selector_writes: list[str] = []

    def fake_reader() -> InterlockRead:
        return InterlockRead(status="free", record=None, detail="released")

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        interlock_owner="migration-run-1",
        interlock_generation=5,
        interlock_reader=fake_reader,
        phase2_write_wsl=lambda: selector_writes.append("wsl"),
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
    )
    assert journal.ok is False
    assert selector_writes == []
    assert journal.phases == []


# --------------------------------------------------------------------------
# CLI-level rollback --ack enforcement (AC6)
# --------------------------------------------------------------------------


def test_rollback_refuses_without_ack(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_all_clear_probes(monkeypatch)
    result = runner.invoke(
        runtime_cli.runtime_app, ["rollback-to-wsl", "--state-dir", str(tmp_path)]
    )
    assert result.exit_code != 0
    assert runtime_cli.ROLLBACK_ACK in result.output


def test_rollback_refuses_with_wrong_ack_text(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _patch_all_clear_probes(monkeypatch)
    result = runner.invoke(
        runtime_cli.runtime_app,
        ["rollback-to-wsl", "--ack", "close enough", "--state-dir", str(tmp_path)],
    )
    assert result.exit_code != 0


def test_rollback_with_exact_ack_proceeds_and_transcript_has_boundary_statement(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _patch_all_clear_probes(monkeypatch)
    monkeypatch.setattr(runtime_cli, "_default_phase2_write_wsl", lambda: None)
    monkeypatch.setattr(
        runtime_cli, "_default_phase3_reenable_service", lambda: "civiccast* enabled"
    )
    monkeypatch.setattr(
        runtime_cli,
        "_default_phase4_restore_run_entry",
        lambda exe_path: "restored for invoking user",
    )
    result = runner.invoke(
        runtime_cli.runtime_app,
        [
            "rollback-to-wsl",
            "--ack",
            runtime_cli.ROLLBACK_ACK,
            "--state-dir",
            str(tmp_path),
            "--exe-path",
            _A_REAL_FILE,
        ],
    )
    assert result.exit_code == 0, result.output
    assert runtime_cli.ROLLBACK_ACK in result.output


# --------------------------------------------------------------------------
# CC-WS4-007 (round 2, Major -- auditor panel): durable atomic journal +
# run-bound validated evidence. Malformed journal fails closed and is
# PRESERVED (renamed <journal>.corrupt-N), never silently discarded; an
# existing INCOMPLETE opposite-direction journal refuses unless
# --force-new; journal writes are atomic (temp file + os.replace);
# evidence is validated by schema/run_id/direction/phase-set, never "the
# lexically latest parseable JSON".
# --------------------------------------------------------------------------


def test_run_cutover_malformed_journal_fails_closed_and_is_preserved(tmp_path) -> None:
    """RED-FIRST control: the auditor's literal repro -- a malformed
    ({not-json) journal at the canonical path -- must FAIL CLOSED (nonzero,
    no phases run) and be PRESERVED (renamed <journal>.corrupt-1), never
    silently discarded/overwritten by a fresh run."""

    journal_path = runtime_cli._journal_path(tmp_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text("{not-json", encoding="utf-8")

    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    assert journal.ok is False
    assert journal.phases == []
    assert any("preserved" in e.lower() for e in journal.errors)

    archived = tmp_path / "runtime-cutover-journal.json.corrupt-1"
    assert archived.exists()
    assert archived.read_text(encoding="utf-8") == "{not-json"
    # The canonical path must NOT have been silently recreated with a
    # fresh journal by this failed attempt.
    assert not journal_path.exists()


def test_run_rollback_malformed_journal_fails_closed_and_is_preserved(tmp_path) -> None:
    """CC-WS4-007 rollback mirror."""

    journal_path = runtime_cli._journal_path(tmp_path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_text("{not-json", encoding="utf-8")

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is False
    assert journal.phases == []
    assert any("preserved" in e.lower() for e in journal.errors)
    assert (tmp_path / "runtime-cutover-journal.json.corrupt-1").exists()


def test_run_rollback_refuses_to_replace_incomplete_cutover_journal_without_force_new(
    tmp_path,
) -> None:
    """RED-FIRST control: an existing INCOMPLETE cutover journal (some
    phase failed, journal.ok is False) must NOT be silently replaced by a
    fresh rollback journal -- refuse unless --force-new."""

    def phase2_raises() -> tuple[list[str], list[str], None]:
        raise RuntimeError("simulated failure")

    incomplete_cutover = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=phase2_raises,
        **_clear_interlock_kwargs(),
    )
    assert incomplete_cutover.ok is False

    selector_writes: list[str] = []
    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=lambda: selector_writes.append("wsl"),
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is False
    assert selector_writes == []
    assert any("force-new" in e.lower() for e in journal.errors)

    # The original incomplete cutover journal must be untouched.
    reloaded = runtime_cli._load_journal(runtime_cli._journal_path(tmp_path))
    assert reloaded is not None
    assert reloaded.direction == "cutover"
    assert reloaded.run_id == incomplete_cutover.run_id


def test_run_rollback_force_new_overrides_incomplete_cutover_journal(tmp_path) -> None:
    """The escape hatch: --force-new (force_new=True) explicitly discards
    the incomplete opposite-direction journal and proceeds."""

    def phase2_raises() -> tuple[list[str], list[str], None]:
        raise RuntimeError("simulated failure")

    incomplete_cutover = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=phase2_raises,
        **_clear_interlock_kwargs(),
    )
    assert incomplete_cutover.ok is False

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        force_new=True,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is True
    assert journal.direction == "rollback"
    assert journal.run_id != incomplete_cutover.run_id


def test_run_rollback_after_complete_cutover_does_not_need_force_new(tmp_path) -> None:
    """The normal transition (no --force-new needed): a COMPLETE
    opposite-direction journal is not an in-flight run -- rollback after a
    successful cutover must proceed without --force-new."""

    complete_cutover = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    assert complete_cutover.ok is True

    journal = runtime_cli.run_rollback(
        state_dir=tmp_path,
        exe_path=_A_REAL_FILE,
        phase2_write_wsl=lambda: None,
        phase3_reenable_service=lambda: "civiccast* enabled",
        phase4_restore_run_entry=lambda exe_path: "restored",
        **_clear_interlock_kwargs(),
    )
    assert journal.ok is True
    assert journal.direction == "rollback"


def test_save_journal_writes_atomically_no_tmp_file_left_behind(tmp_path) -> None:
    """CC-WS4-007: _save_journal writes via a temp file + atomic replace --
    no stray .tmp file is left in the directory after a successful save."""

    from civiccast.native.models import CutoverJournal

    journal_path = runtime_cli._journal_path(tmp_path)
    journal = CutoverJournal(
        v=1, run_id="r1", direction="cutover", phases=[], unloaded_profiles=[], errors=[]
    )
    runtime_cli._save_journal(journal_path, journal)

    assert journal_path.exists()
    leftover_tmp_files = list(tmp_path.glob(".*tmp*"))
    assert leftover_tmp_files == []
    reloaded = runtime_cli._load_journal(journal_path)
    assert reloaded == journal


def test_save_journal_cleans_up_tmp_file_on_write_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FALSIFICATION: if the atomic replace step itself fails, the temp
    file must be cleaned up, not left behind as directory litter."""

    from civiccast.native.models import CutoverJournal

    journal_path = runtime_cli._journal_path(tmp_path)
    journal = CutoverJournal(
        v=1, run_id="r1", direction="cutover", phases=[], unloaded_profiles=[], errors=[]
    )

    real_replace = Path.replace

    def failing_replace(self: Path, target: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(Path, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        runtime_cli._save_journal(journal_path, journal)
    monkeypatch.setattr(Path, "replace", real_replace)

    assert not journal_path.exists()
    leftover_tmp_files = list(tmp_path.glob(".*tmp*"))
    assert leftover_tmp_files == []


def test_phase5_verify_rejects_stale_wrong_run_evidence_file(tmp_path) -> None:
    """RED-FIRST control: a stale evidence file from a DIFFERENT run_id
    (but otherwise well-formed) must NOT satisfy phase 5's resume-verify --
    only the ACTUAL run's evidence, matching run_id/direction/phase-set,
    counts. This is the "lexically latest parseable JSON" hazard the fix
    closes: a wrong-run file that merely sorts last must not pass."""

    import json as jsonlib

    state_dir = tmp_path
    # Plant a well-formed-LOOKING but WRONG-RUN evidence file that sorts
    # lexically after any real one (far-future timestamp).
    stale_payload = {
        "v": 1,
        "run_id": "some-other-run-entirely",
        "direction": "cutover",
        "phases": [{"phase": i, "name": f"p{i}", "status": "done"} for i in range(1, 6)],
        "unloaded_profiles": [],
        "errors": [],
        "probe_snapshot": None,
    }
    (state_dir / "runtime-cutover-evidence-99999999T999999Z.json").write_text(
        jsonlib.dumps(stale_payload), encoding="utf-8"
    )

    journal = runtime_cli.run_cutover(
        state_dir=state_dir,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase4_record_retained=lambda: "retained",
        **_clear_cutover_kwargs(),
    )
    assert journal.ok is True
    # The REAL evidence file (this run's own) must have been written and
    # matched -- not the stale wrong-run one.
    real_evidence = [
        p
        for p in state_dir.glob("runtime-cutover-evidence-*.json")
        if p.name != "runtime-cutover-evidence-99999999T999999Z.json"
    ]
    assert len(real_evidence) == 1
    payload = jsonlib.loads(real_evidence[0].read_text(encoding="utf-8"))
    assert payload["run_id"] == journal.run_id
    assert payload["probe_snapshot"] is not None


def test_phase5_verify_rejects_truncated_evidence_on_resume(tmp_path) -> None:
    """RED-FIRST control: on resume, if the evidence file this run wrote
    has since been truncated/corrupted, phase 5's resume-verify must FAIL
    (re-execute), never trust a truncated file as "exists and parses"."""

    kwargs = _clear_cutover_kwargs()
    journal = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase3_verify=lambda: (True, "confirmed selector native (test fake)"),
        phase4_record_retained=lambda: "retained",
        **kwargs,
    )
    assert journal.ok is True

    evidence_files = list(tmp_path.glob("runtime-cutover-evidence-*.json"))
    assert len(evidence_files) == 1
    evidence_files[0].write_text("{truncated", encoding="utf-8")

    # Resume: phase 5's resume-verify must fail (the evidence is now
    # unparseable/truncated) and RE-EXECUTE, writing a fresh valid file.
    journal2 = runtime_cli.run_cutover(
        state_dir=tmp_path,
        phase1_stop_service=lambda: "no distro registered",
        phase2_remove_run_entries=lambda: ([], [], None),
        phase2_verify=lambda: (True, "confirmed no marker (test fake)"),
        phase3_write_native=lambda: None,
        phase3_verify=lambda: (True, "confirmed selector native (test fake)"),
        phase4_record_retained=lambda: "retained",
        **kwargs,
    )
    assert journal2.ok is True
    phase5 = next(p for p in journal2.phases if p.phase == 5)
    assert phase5.verified_on_resume is False


# --------------------------------------------------------------------------
# CC-WS4-009 (round 2b, verification defect): the round-2 error-append
# sites for interlock bracket setup, per-label interlock bracket boundary
# re-verify, and CC-WS4-006 rollback preflight were never cleared on a
# later genuine success -- ONE transient failure made journal.ok
# permanently False even after a fully successful resume, so the OWNED-
# mode release() (gated on journal.ok) never fired and the D7a
# maintenance freeze stayed held indefinitely. See
# ``runtime_cli._clear_stale_errors`` and its call sites.
# --------------------------------------------------------------------------


def test_ws4_009_bracket_boundary_transient_failure_then_resume_clears_and_releases(
    tmp_path,
) -> None:
    """RED-FIRST control (a): a transient bracket re-verify failure
    (interlock unreadable) at the very first phase boundary must NOT make
    journal.ok permanently False once a retry's re-verify actually
    succeeds -- the stale 'interlock bracket failed before phase 1: ...'
    error must clear, so journal.ok flips True and the OWNED-mode release
    fires in the SAME invocation that completes (the CLI's sole exit-code
    gate is `if not journal.ok: raise typer.Exit(code=1)` -- asserting
    journal.ok True here is asserting process exit 0, mirroring every
    other interlock-bracket control test in this file)."""

    take_calls: list[str] = []
    unreadable_once = {"armed": True}

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        take_calls.append(owner_run_id)
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        if not take_calls:
            return InterlockRead(status="free", record=None, detail="not yet taken")
        if unreadable_once["armed"]:
            unreadable_once["armed"] = False
            return InterlockRead(
                status="unreadable",
                record=None,
                detail="transient Maintenance read glitch (test double)",
            )
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    release_calls = {"n": 0}

    def fake_releaser() -> MaintenanceRecord:
        release_calls["n"] += 1
        return MaintenanceRecord(
            v=1,
            state="released",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
            released_utc="2026-07-18T00:05:00Z",
        )

    kwargs = {
        "state_dir": tmp_path,
        "interlock_taker": fake_taker,
        "interlock_reader": fake_reader,
        "interlock_releaser": fake_releaser,
        "probe_snapshot": _fake_probe_snapshot,
        "phase1_stop_service": lambda: "no distro registered",
        "phase1_verify": lambda: (True, "verified for test"),
        "phase2_remove_run_entries": lambda: ([], [], None),
        "phase2_verify": lambda: (True, "confirmed no marker (test fake)"),
        "phase3_write_native": lambda: None,
        "phase3_verify": lambda: (True, "verified for test"),
        "phase4_record_retained": lambda: "retained",
        "phase4_verify": lambda: (True, "verified for test"),
    }

    journal1 = runtime_cli.run_cutover(**kwargs)
    assert journal1.ok is False
    assert journal1.phases == []  # boundary aborts before phase 1 ever runs
    assert any(e.startswith("interlock bracket failed before phase 1:") for e in journal1.errors)
    assert release_calls["n"] == 0
    assert len(take_calls) == 1  # OWNED mode took it once already

    journal2 = runtime_cli.run_cutover(**kwargs)
    assert len(take_calls) == 1  # resume must NOT re-take -- still bound
    assert journal2.errors == []
    assert journal2.ok is True
    assert release_calls["n"] == 1  # the deadlock this round fixes


def test_ws4_009_rollback_preflight_failure_then_resume_clears_and_releases(tmp_path) -> None:
    """RED-FIRST control (b): a failed CC-WS4-006 exe-path preflight (no
    --exe-path anywhere) must not leave journal.ok permanently False once
    a retry supplies a valid path -- the stale 'rollback preflight
    failed: ...' error must clear, and the OWNED-mode release must fire in
    that same invocation."""

    take_calls: list[str] = []

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        take_calls.append(owner_run_id)
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        if not take_calls:
            return InterlockRead(status="free", record=None, detail="not yet taken")
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    release_calls = {"n": 0}

    def fake_releaser() -> MaintenanceRecord:
        release_calls["n"] += 1
        return MaintenanceRecord(
            v=1,
            state="released",
            generation=1,
            owner_run_id=take_calls[-1],
            taken_utc="2026-07-18T00:00:00Z",
            released_utc="2026-07-18T00:05:00Z",
        )

    kwargs = {
        "state_dir": tmp_path,
        "interlock_taker": fake_taker,
        "interlock_reader": fake_reader,
        "interlock_releaser": fake_releaser,
        "phase2_write_wsl": lambda: None,
        "phase3_reenable_service": lambda: "civiccast* enabled",
        "phase4_restore_run_entry": lambda exe_path: "restored",
    }

    journal1 = runtime_cli.run_rollback(exe_path=None, **kwargs)
    assert journal1.ok is False
    phase1 = next(p for p in journal1.phases if p.phase == 1)
    assert phase1.status == "done"
    assert 2 not in [p.phase for p in journal1.phases]
    assert any(e.startswith("rollback preflight failed:") for e in journal1.errors)
    assert release_calls["n"] == 0

    journal2 = runtime_cli.run_rollback(exe_path=_A_REAL_FILE, **kwargs)
    assert len(take_calls) == 1  # resume must NOT re-take -- still bound
    assert journal2.errors == []
    assert journal2.ok is True
    assert journal2.removed_run_entry_exe_path == _A_REAL_FILE
    assert release_calls["n"] == 1  # the deadlock this round fixes


def test_ws4_009_persistent_bracket_failure_never_clears_stale_error(tmp_path) -> None:
    """RED-FIRST control (c), the negative -- the guard must not
    over-clear: a PERSISTENTLY unreadable interlock across retries leaves
    journal.ok False, the stale 'interlock bracket failed before phase 1:
    ...' error present, and the interlock release NEVER attempted --
    clearing only happens on a GENUINE success at that same boundary."""

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        return InterlockRead(
            status="unreadable",
            record=None,
            detail="persistently broken Maintenance read (test double)",
        )

    def fake_releaser() -> MaintenanceRecord:
        raise AssertionError("release must never be attempted while the bracket keeps failing")

    kwargs = {
        "state_dir": tmp_path,
        "interlock_taker": fake_taker,
        "interlock_reader": fake_reader,
        "interlock_releaser": fake_releaser,
        "phase1_stop_service": lambda: "no distro registered",
        "phase2_remove_run_entries": lambda: ([], [], None),
        "phase3_write_native": lambda: None,
        "phase4_record_retained": lambda: "retained",
    }

    journal1 = runtime_cli.run_cutover(**kwargs)
    assert journal1.ok is False
    assert journal1.phases == []
    assert any(e.startswith("interlock bracket failed before phase 1:") for e in journal1.errors)

    journal2 = runtime_cli.run_cutover(**kwargs)
    assert journal2.ok is False
    assert journal2.phases == []
    assert any(e.startswith("interlock bracket failed before phase 1:") for e in journal2.errors)


def test_ws4_009_bracket_per_label_isolation_phase1_success_does_not_clear_phase3(tmp_path) -> None:
    """RED-FIRST control (d): per-label isolation -- a failure recorded at
    boundary "phase 3 (selector write)", followed by a resume where the
    EARLIER "phase 1"/"phase 2" boundaries genuinely succeed but "phase 3"
    fails AGAIN, must leave the "phase 3" entry present -- a success at a
    DIFFERENT label must never clear it."""

    call_count = {"n": 0}
    fail_on = {3, 6}  # run1's phase-3 boundary call, run2's phase-3 boundary call
    taken_owner: dict[str, str | None] = {"id": None}

    def fake_taker(owner_run_id: str) -> MaintenanceRecord:
        taken_owner["id"] = owner_run_id
        return MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=owner_run_id,
            taken_utc="2026-07-18T00:00:00Z",
        )

    def fake_reader() -> InterlockRead:
        call_count["n"] += 1
        if call_count["n"] in fail_on:
            return InterlockRead(
                status="unreadable",
                record=None,
                detail=f"simulated transient failure #{call_count['n']}",
            )
        record = MaintenanceRecord(
            v=1,
            state="held",
            generation=1,
            owner_run_id=taken_owner["id"],
            taken_utc="2026-07-18T00:00:00Z",
        )
        return InterlockRead(status="held", record=record, detail="held")

    def fake_releaser() -> MaintenanceRecord:
        raise AssertionError("release must never fire -- the phase 3 boundary keeps failing")

    kwargs = {
        "state_dir": tmp_path,
        "interlock_taker": fake_taker,
        "interlock_reader": fake_reader,
        "interlock_releaser": fake_releaser,
        "phase1_stop_service": lambda: "no distro registered",
        "phase1_verify": lambda: (True, "verified for test"),
        "phase2_remove_run_entries": lambda: ([], [], None),
        "phase2_verify": lambda: (True, "confirmed no marker (test fake)"),
        "phase3_write_native": lambda: None,
    }

    journal1 = runtime_cli.run_cutover(**kwargs)
    assert journal1.ok is False
    assert {p.phase for p in journal1.phases if p.status == "done"} == {1, 2}
    assert any(
        e.startswith("interlock bracket failed before phase 3 (selector write):")
        for e in journal1.errors
    )

    journal2 = runtime_cli.run_cutover(**kwargs)
    assert call_count["n"] == 6  # proves calls 4 (phase 1) and 5 (phase 2) both ran and succeeded
    assert journal2.ok is False
    assert {p.phase for p in journal2.phases} == {1, 2}
    # The "phase 3" stale entry survives the genuine phase-1/phase-2
    # boundary successes that happened on this resume -- per-label
    # isolation, not a global clear.
    assert any(
        e.startswith("interlock bracket failed before phase 3 (selector write):")
        for e in journal2.errors
    )
    assert not any(
        e.startswith("interlock bracket failed before phase 1:") for e in journal2.errors
    )
    assert not any(
        e.startswith("interlock bracket failed before phase 2:") for e in journal2.errors
    )
