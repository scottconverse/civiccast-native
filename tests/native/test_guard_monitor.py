# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for civiccast.native.runtime_guard.GuardMonitor.

Pure -- fake probes throughout, no Windows dependency. Exercises D5
continuous enforcement: AC3 (keeper appears mid-operation), AC7 (selector
flips to wsl mid-operation), AC9 (a2 unreadable -> blocked + alert-after-3,
both directions), and the abandoned-mutex re-verify path (AC3c shape).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from civiccast.native import runtime_guard
from civiccast.native.models import (
    A1Result,
    A2Result,
    A3Result,
    GuardDecision,
    InterlockRead,
    SelectorRead,
)
from civiccast.native.runtime_guard import GuardMonitor


class FakeClock:
    def __init__(self, start_second: int = 0) -> None:
        self._second = start_second

    def __call__(self) -> datetime:
        self._second += 1
        return datetime(2026, 7, 17, 12, 0, self._second % 60, tzinfo=UTC)


class FakeStopEvent:
    """Deterministic, sleep-free stand-in for threading.Event: is_set()
    stays False until `stop_after` calls to wait() have happened, matching
    the "N synthetic intervals" pattern the brief calls for."""

    def __init__(self, stop_after: int) -> None:
        self._remaining = stop_after
        self.wait_calls = 0

    def is_set(self) -> bool:
        return self._remaining <= 0

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls += 1
        self._remaining -= 1
        return self._remaining <= 0


def _clear_selector() -> SelectorRead:
    return SelectorRead(ok=True, value="native", detail="ok")


def _absent_selector() -> SelectorRead:
    """Chain I: an A2 the guard cannot READ still WITHHOLDS the start on every
    selector state except an EXPLICIT ``native`` -- there is no authority
    artifact to stand a degraded start on. The A2-unreadable tests below keep
    their original subject (the alert threshold, the raise mapping) by running
    on this still-blocking cell; the explicitly-native cell gets its own tests.
    ``_make_monitor``'s ``wsl_install_detector`` already answers a CONFIRMED
    ``False``, so this reaches the same native path decide() row 7 (absent, no
    WSL install) authorizes.
    """

    return SelectorRead(ok=True, value="absent", detail="ActiveRuntime value missing")


def _clear_a1() -> A1Result:
    return A1Result(live_process="negative", run_entry="negative", detail="clear")


def _clear_a2() -> A2Result:
    return A2Result(status="negative", detail="inactive")


def _clear_a3() -> A3Result:
    return A3Result(status="acquired", detail="owned")


def _free_interlock() -> InterlockRead:
    return InterlockRead(status="free", record=None, detail="absent")


def _make_monitor(
    *,
    selector_reader: Callable[[], SelectorRead] | None = None,
    a1_probe: Callable[[], A1Result] | None = None,
    a2_probe: Callable[[], A2Result] | None = None,
    mutex: Callable[[], A3Result] | None = None,
    interlock_reader: Callable[[], InterlockRead] | None = None,
    wsl_install_detector: Callable[[], bool] | None = None,
    interval_seconds: float = 30.0,
) -> GuardMonitor:
    return GuardMonitor(
        selector_reader=selector_reader or _clear_selector,
        a1_probe=a1_probe or _clear_a1,
        a2_probe=a2_probe or _clear_a2,
        mutex=mutex or _clear_a3,
        interlock_reader=interlock_reader or _free_interlock,
        wsl_install_detector=wsl_install_detector or (lambda: False),
        clock=FakeClock(),
        interval_seconds=interval_seconds,
    )


def test_evaluate_once_returns_decision_and_updates_status() -> None:
    monitor = _make_monitor()
    decision = monitor.evaluate_once()
    assert decision.action == "start"
    assert monitor.status.last_decision == decision
    assert monitor.status.last_evaluated_utc is not None
    assert monitor.status.consecutive_blocked_probe_unavailable == 0
    assert monitor.status.alert is False
    assert monitor.logs  # at least one log line recorded


def test_pre_child_start_is_the_same_evaluation_as_evaluate_once() -> None:
    monitor = _make_monitor()
    decision = monitor.pre_child_start()
    assert decision.action == "start"
    assert monitor.status.last_decision == decision


def test_ac9_a2_unreadable_alerts_after_three_then_restored_negative_starts() -> None:
    """AC9 shape, both directions in one test: a2 unreadable => blocked +
    retry 10 + alert after 3 consecutive; a2 restored-negative => start."""

    calls = {"n": 0}

    def flaky_a2() -> A2Result:
        calls["n"] += 1
        return A2Result(status="unreadable", detail=f"wsl.exe timeout #{calls['n']}")

    monitor = _make_monitor(a2_probe=flaky_a2, selector_reader=_absent_selector)

    d1 = monitor.evaluate_once()
    assert d1.action == "blocked_probe_unavailable"
    assert d1.retry_seconds == 10
    assert monitor.status.consecutive_blocked_probe_unavailable == 1
    assert monitor.status.alert is False

    d2 = monitor.evaluate_once()
    assert d2.action == "blocked_probe_unavailable"
    assert monitor.status.consecutive_blocked_probe_unavailable == 2
    assert monitor.status.alert is False

    d3 = monitor.evaluate_once()
    assert d3.action == "blocked_probe_unavailable"
    assert monitor.status.consecutive_blocked_probe_unavailable == 3
    assert monitor.status.alert is True
    assert any("ALERT" in line for line in monitor.logs)

    # Now restore: a2 goes readable-negative.
    monitor2_a2_calls = {"n": 0}

    def restored_a2() -> A2Result:
        monitor2_a2_calls["n"] += 1
        return A2Result(status="negative", detail="inactive")

    monitor._a2_probe = restored_a2  # test reaches into the injected seam directly
    d4 = monitor.evaluate_once()
    assert d4.action == "start"
    assert monitor.status.consecutive_blocked_probe_unavailable == 0
    assert monitor.status.alert is False


def test_ac3_shape_keeper_appears_mid_operation_triggers_controlled_stop_within_one_interval() -> (
    None
):
    """AC3 shape: keeper starts AFTER native is up -> D5 detects within one
    evaluation (one interval), transmission children stop (via the
    on_state_change callback), state=blocked_wsl_active."""

    calls = {"n": 0}

    def flipping_a1() -> A1Result:
        calls["n"] += 1
        if calls["n"] == 1:
            return _clear_a1()
        return A1Result(
            live_process="positive", run_entry="negative", detail="wsl.exe keeper pid 999"
        )

    monitor = _make_monitor(a1_probe=flipping_a1)
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=2)

    monitor.run(stop_event, seen.append)

    assert len(seen) == 1
    decision = seen[0]
    assert decision.action == "refuse"
    assert decision.named_probe == "A1"
    assert decision.state_name == "blocked_wsl_active"


def test_ac7_shape_selector_flip_to_wsl_mid_operation_triggers_controlled_stop() -> None:
    """AC7: selector tampering mid-operation (flip to wsl while native
    transmits) -> D5 controlled stop within one probe interval."""

    calls = {"n": 0}

    def flipping_selector() -> SelectorRead:
        calls["n"] += 1
        if calls["n"] == 1:
            return _clear_selector()
        return SelectorRead(ok=True, value="wsl", detail="tampered mid-operation")

    monitor = _make_monitor(selector_reader=flipping_selector)
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=2)

    monitor.run(stop_event, seen.append)

    assert len(seen) == 1
    decision = seen[0]
    assert decision.action == "never_start"
    assert decision.state_name == "blocked_wsl_active"
    assert "wsl" in decision.message


def test_run_does_not_fire_callback_when_nothing_changes() -> None:
    monitor = _make_monitor()
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=3)

    monitor.run(stop_event, seen.append)

    assert seen == []
    assert monitor.status.last_decision is not None
    assert monitor.status.last_decision.action == "start"


def test_run_does_not_fire_callback_on_the_first_ever_refusal() -> None:
    """The controlled-stop callback is a MID-OPERATION concept (was_started
    -> now not started). A refusal on the very first evaluation (nothing was
    ever running) must not fire on_state_change."""

    monitor = _make_monitor(
        a1_probe=lambda: A1Result(
            live_process="positive", run_entry="negative", detail="keeper up from the start"
        )
    )
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=2)

    monitor.run(stop_event, seen.append)

    assert seen == []


def test_abandoned_mutex_with_a2_positive_refuses_named_a2() -> None:
    """AC3c shape: a3 abandoned + a2 positive => refuse (via evaluate_once,
    fake probes). decide()'s ordering catches the a2-positive case at step 6
    before the a3 branch is even reached, so the probe named is "A2"."""

    monitor = _make_monitor(
        mutex=lambda: A3Result(status="acquired_abandoned", detail="prior owner crashed"),
        a2_probe=lambda: A2Result(status="positive", detail="civiccast.service active"),
    )
    decision = monitor.evaluate_once()
    assert decision.action == "refuse"
    assert decision.named_probe == "A2"


def test_abandoned_mutex_with_a2_unreadable_blocks() -> None:
    """AC3c shape: a3 abandoned + a2 unreadable => blocked (D4's mandatory
    re-verify cannot confirm the service is inactive)."""

    monitor = _make_monitor(
        mutex=lambda: A3Result(status="acquired_abandoned", detail="prior owner crashed"),
        a2_probe=lambda: A2Result(status="unreadable", detail="wsl.exe timed out"),
    )
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"


def test_abandoned_mutex_with_a2_negative_starts() -> None:
    """AC3c shape, the passing direction: a3 abandoned + a2 readable-negative
    => start (the re-verify confirms the service really is inactive)."""

    monitor = _make_monitor(
        mutex=lambda: A3Result(status="acquired_abandoned", detail="prior owner crashed")
    )
    decision = monitor.evaluate_once()
    assert decision.action == "start"


# --------------------------------------------------------------------------
# F6: probe exceptions must not kill the D5 loop. Every one of GuardMonitor's
# injected probes is wrapped in try/except Exception, mapping a raise to that
# probe's own non-authorizing state (never letting the exception propagate
# out of _compose_inputs / evaluate_once / run).
# --------------------------------------------------------------------------


def _raising_probe(*_args: object, **_kwargs: object) -> object:
    raise RuntimeError("probe exploded")


def test_f6_selector_reader_raise_maps_to_unreadable_selector_blocks() -> None:
    monitor = _make_monitor(selector_reader=_raising_probe)
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"
    assert decision.named_probe == "selector"


def test_f6_a1_probe_raise_does_not_crash_and_degrades() -> None:
    """A1 raising maps to A1Result(live_process="error", run_entry="error")
    -- decide()'s own D3 row 9 (A1 error + readable-negative A2) is a
    DEGRADED START, not a block; F6's guarantee is that the monitor survives
    the raise and produces this legitimate decision rather than crashing."""

    monitor = _make_monitor(a1_probe=_raising_probe)
    decision = monitor.evaluate_once()
    assert decision.action == "start_degraded"
    assert decision.named_probe == "A1"


def test_f6_a2_probe_raise_maps_to_unreadable_a2_blocks() -> None:
    monitor = _make_monitor(a2_probe=_raising_probe, selector_reader=_absent_selector)
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"
    assert decision.named_probe == "A2"


def test_f6_a2_probe_raise_under_an_explicit_native_selector_degrades_not_blocks() -> None:
    """The SAME F6 mapping (a raise never escapes the monitor; it becomes an
    ``unreadable`` A2) under the one selector state chain I changed: the
    station starts degraded naming A2 instead of being withheld, and the
    exception text still reaches the message so the log can show it."""

    monitor = _make_monitor(a2_probe=_raising_probe)
    decision = monitor.evaluate_once()
    assert decision.action == "start_degraded"
    assert decision.named_probe == "A2"
    assert "probe-degraded" in decision.message
    assert "A2 probe raised" in decision.message


def test_f6_mutex_raise_maps_to_a3_error_blocks() -> None:
    monitor = _make_monitor(mutex=_raising_probe)
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"
    assert decision.named_probe == "A3"


def test_f6_interlock_reader_raise_maps_to_unreadable_interlock_blocks() -> None:
    monitor = _make_monitor(interlock_reader=_raising_probe)
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"
    assert decision.named_probe == "interlock"


def test_f6_wsl_install_detector_raise_maps_to_unknown_state_blocks() -> None:
    """The wsl_install_detector raise maps to wsl_install_detected=None
    (F1's tri-state UNKNOWN) -- only observable when the selector reads
    "absent" (decide()'s row 4 is the only row that consults it)."""

    monitor = _make_monitor(
        selector_reader=lambda: SelectorRead(ok=True, value="absent", detail="absent"),
        wsl_install_detector=_raising_probe,
    )
    decision = monitor.evaluate_once()
    assert decision.action == "blocked_probe_unavailable"
    assert decision.named_probe == "wsl_install_detected"


def test_f6_run_survives_repeated_raises_and_still_alerts_after_three() -> None:
    """F6's core D5 guarantee: the monitor loop does not die from a probe
    raise, across N synthetic intervals -- and the existing alert-after-3
    consecutive blocked_probe_unavailable behavior still fires."""

    monitor = _make_monitor(interlock_reader=_raising_probe)
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=5)

    monitor.run(stop_event, seen.append)  # must not raise

    assert monitor.status.consecutive_blocked_probe_unavailable == 5
    assert monitor.status.alert is True
    assert any("ALERT" in line for line in monitor.logs)


# --------------------------------------------------------------------------
# "Also" (r12 remedy): 3 mutation probes for GuardMonitor plumbing. Each
# mutates a specific behavior and proves a named test-shaped assertion
# actually breaks under that mutation -- the same AC8-negative-control
# pattern already used in test_guard_table.py, applied to GuardMonitor.
# --------------------------------------------------------------------------


def test_mutation_probe_controlled_stop_callback_suppressed_is_caught() -> None:
    """Mutation: on_state_change is silently swallowed inside run() (as if
    the controlled-stop callback were suppressed). FALSIFICATION: this must
    make the AC3-shaped assertion (test_ac3_shape_...'s "callback fires
    within one interval") fail -- proving that test actually bites."""

    class SuppressedCallbackMonitor(GuardMonitor):
        def run(self, stop_event: object, on_state_change: object) -> None:  # type: ignore[override]
            # Mutation: the controlled-stop callback is never invoked.
            super().run(stop_event, lambda _decision: None)  # type: ignore[arg-type]

    calls = {"n": 0}

    def flipping_a1() -> A1Result:
        calls["n"] += 1
        if calls["n"] == 1:
            return _clear_a1()
        return A1Result(
            live_process="positive", run_entry="negative", detail="wsl.exe keeper pid 999"
        )

    monitor = SuppressedCallbackMonitor(
        selector_reader=_clear_selector,
        a1_probe=flipping_a1,
        a2_probe=_clear_a2,
        mutex=_clear_a3,
        interlock_reader=_free_interlock,
        wsl_install_detector=lambda: False,
        clock=FakeClock(),
    )

    def _assert_ac3_callback_fires() -> None:
        seen: list[GuardDecision] = []
        stop_event = FakeStopEvent(stop_after=2)
        monitor.run(stop_event, seen.append)
        assert len(seen) == 1

    with pytest.raises(AssertionError):
        _assert_ac3_callback_fires()


def test_mutation_probe_alert_threshold_off_by_one_both_directions_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: ALERT_AFTER_CONSECUTIVE_BLOCKED off by one, in EITHER
    direction. FALSIFICATION: this must make an AC9-shaped "alerts exactly
    after 3 consecutive blocked_probe_unavailable results" assertion fail --
    proving the existing test pins the exact threshold, not just
    "eventually alerts"."""

    def _assert_alerts_exactly_after_three() -> None:
        calls = {"n": 0}

        def flaky_a2() -> A2Result:
            calls["n"] += 1
            return A2Result(status="unreadable", detail=f"wsl.exe timeout #{calls['n']}")

        monitor = _make_monitor(a2_probe=flaky_a2, selector_reader=_absent_selector)
        monitor.evaluate_once()
        assert monitor.status.alert is False
        monitor.evaluate_once()
        assert monitor.status.alert is False
        monitor.evaluate_once()
        assert monitor.status.alert is True

    # Baseline: passes with the real threshold (3) -- the control proves the
    # assertion helper itself is not vacuously true.
    _assert_alerts_exactly_after_three()

    try:
        # Mutation A: threshold too LOW (2) -- alerts one evaluation early.
        monkeypatch.setattr(runtime_guard, "ALERT_AFTER_CONSECUTIVE_BLOCKED", 2)
        with pytest.raises(AssertionError):
            _assert_alerts_exactly_after_three()
    finally:
        monkeypatch.setattr(runtime_guard, "ALERT_AFTER_CONSECUTIVE_BLOCKED", 3)

    try:
        # Mutation B: threshold too HIGH (4) -- never alerts within 3 evaluations.
        monkeypatch.setattr(runtime_guard, "ALERT_AFTER_CONSECUTIVE_BLOCKED", 4)
        with pytest.raises(AssertionError):
            _assert_alerts_exactly_after_three()
    finally:
        monkeypatch.setattr(runtime_guard, "ALERT_AFTER_CONSECUTIVE_BLOCKED", 3)


def test_mutation_probe_pre_child_start_bypassing_decide_is_caught() -> None:
    """Mutation: pre_child_start() always returns "start", bypassing
    decide() (and therefore every probe) entirely. FALSIFICATION: this must
    make an AC2-shaped "pre_child_start refuses when a live keeper is
    present" assertion fail -- proving a test exercising the D5 pre-start
    hook actually bites, not just evaluate_once()."""

    class BypassingMonitor(GuardMonitor):
        def pre_child_start(self) -> GuardDecision:  # type: ignore[override]
            return GuardDecision(
                action="start",
                named_probe=None,
                message="mutated bypass",
                retry_seconds=None,
                state_name=None,
            )

    monitor = BypassingMonitor(
        selector_reader=_clear_selector,
        a1_probe=lambda: A1Result(
            live_process="positive", run_entry="negative", detail="wsl.exe keeper pid 1234"
        ),
        a2_probe=_clear_a2,
        mutex=_clear_a3,
        interlock_reader=_free_interlock,
        wsl_install_detector=lambda: False,
        clock=FakeClock(),
    )

    def _assert_pre_child_start_refuses_on_live_keeper() -> None:
        decision = monitor.pre_child_start()
        assert decision.action == "refuse"
        assert decision.named_probe == "A1"

    with pytest.raises(AssertionError):
        _assert_pre_child_start_refuses_on_live_keeper()


def test_chain_i_a_degraded_start_still_controlled_stops_when_a2_turns_positive() -> None:
    """D5 continuous enforcement is NOT weakened by chain I's degraded start.

    ``start_degraded`` is in ``_STARTED_ACTIONS``, so a station that started on
    an unreadable A2 keeps being re-probed every interval -- and the moment A2
    becomes READABLE-POSITIVE (a real live WSL transmitter, not probe noise)
    the monitor fires the controlled stop within ONE interval, exactly as it
    would from a plain ``start``. This is the boundary the owner decision
    explicitly refused to move.
    """

    calls = {"n": 0}

    def a2_unreadable_then_positive() -> A2Result:
        calls["n"] += 1
        if calls["n"] == 1:
            return A2Result(status="unreadable", detail="wsl.exe timed out")
        return A2Result(status="positive", detail="civiccast.service active")

    monitor = _make_monitor(a2_probe=a2_unreadable_then_positive)
    seen: list[GuardDecision] = []
    stop_event = FakeStopEvent(stop_after=2)

    monitor.run(stop_event, seen.append)

    # First evaluation authorized a DEGRADED start (the chain I cell)...
    assert "action=start_degraded" in monitor.logs[0]
    assert "named_probe=A2" in monitor.logs[0]
    # ...and the second, on a readable-positive A2, controlled-stopped.
    assert len(seen) == 1
    decision = seen[0]
    assert decision.action == "refuse"
    assert decision.named_probe == "A2"
    assert decision.state_name == "blocked_wsl_active"


def test_chain_i_the_degraded_decision_is_recorded_in_the_monitor_log_with_probe_and_reason() -> (
    None
):
    """The owner decision requires the unreadability to be RECORDED, not
    swallowed: the monitor's own log line must carry the action, the named
    probe, and the reason. (The supervisor-side WARNING is pinned separately
    in tests/native/test_supervisor_core.py.)"""

    monitor = _make_monitor(
        a2_probe=lambda: A2Result(status="unreadable", detail="wsl.exe timed out after 5.0s")
    )
    decision = monitor.evaluate_once()

    assert decision.action == "start_degraded"
    line = monitor.logs[-1]
    assert "action=start_degraded" in line
    assert "named_probe=A2" in line
    assert "wsl.exe timed out after 5.0s" in line
    # A degraded start is NOT a blocked one: it must never advance the
    # alert-after-3 counter that AC9 owns.
    assert monitor.status.consecutive_blocked_probe_unavailable == 0
    assert monitor.status.alert is False
