# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the pure supervisor state logic (slice:ws5-supervisor).

Pins the four properties the spec's build-step 1 requires (P1 totality, P2
maintenance-never-starts-workers, P3 dependent-restart-ordering, P4 no
blocked->ready shortcut), the precedence rules, and the D5 pure helpers.
Nothing here touches a process, a pipe, or the registry.
"""

from __future__ import annotations

import itertools

import pytest

from civiccast.native.supervisor.config import STARTUP_ORDER
from civiccast.native.supervisor.states import (
    ChildState,
    SupervisorEvent,
    SupervisorState,
    _all_events,
    _all_states,
    backoff_base_seconds,
    is_restart_storm,
    restart_eligible,
    supervisor_transition,
    workers_permitted,
)

ALL_STATES = _all_states()
ALL_EVENTS = _all_events()


# --------------------------------------------------------------------------
# P1 -- totality
# --------------------------------------------------------------------------


def test_p1_transition_is_total_over_the_product() -> None:
    for state, event in itertools.product(ALL_STATES, ALL_EVENTS):
        result = supervisor_transition(state, event)
        assert result in ALL_STATES, f"({state}, {event}) -> {result!r} is not a valid state"


# --------------------------------------------------------------------------
# P2 -- maintenance never permits workers (and only serving states do)
# --------------------------------------------------------------------------


def test_p2_maintenance_never_permits_workers() -> None:
    assert workers_permitted("maintenance") is False


def test_p2_only_ready_and_degraded_permit_workers() -> None:
    for state in ALL_STATES:
        expected = state in {"ready", "degraded"}
        assert workers_permitted(state) is expected, state


# --------------------------------------------------------------------------
# P3 -- dependent restart ordering
# --------------------------------------------------------------------------


def _states(**overrides: ChildState) -> dict[str, ChildState]:
    base: dict[str, ChildState] = dict.fromkeys(STARTUP_ORDER, "stopped")
    base.update(overrides)
    return base


def test_p3_first_child_is_always_eligible() -> None:
    # postgres has no predecessor: eligible regardless of the others.
    assert restart_eligible("postgres", _states(), STARTUP_ORDER) is True


def test_p3_dependent_blocked_until_all_predecessors_ready() -> None:
    # control_plane needs postgres ready. NATS JetStream was removed from the
    # product (owner decision 2026-08-20; see ADR 0023, which supersedes ADR
    # 0001), so STARTUP_ORDER is the two-link chain (postgres, control_plane)
    # -- control_plane's only predecessor is postgres now.
    assert restart_eligible("control_plane", _states(postgres="starting"), STARTUP_ORDER) is False
    assert restart_eligible("control_plane", _states(postgres="ready"), STARTUP_ORDER) is True


def test_p3_missing_predecessor_is_not_ready_fail_closed() -> None:
    # A predecessor absent from the map counts as not-ready.
    assert restart_eligible("control_plane", {}, STARTUP_ORDER) is False


# --------------------------------------------------------------------------
# P4 -- no blocked -> ready shortcut
# --------------------------------------------------------------------------


def test_p4_no_event_moves_a_blocked_state_straight_to_ready() -> None:
    for blocked in ("blocked_wsl_active", "blocked_probe_unavailable"):
        for event in ALL_EVENTS:
            assert supervisor_transition(blocked, event) != "ready", (blocked, event)


def test_p4_blocked_release_goes_to_starting_not_ready() -> None:
    for blocked in ("blocked_wsl_active", "blocked_probe_unavailable"):
        assert supervisor_transition(blocked, "guard_clear") == "starting"


# --------------------------------------------------------------------------
# Precedence and specific transitions
# --------------------------------------------------------------------------


def test_stopping_is_absorbing() -> None:
    for event in ALL_EVENTS:
        assert supervisor_transition("stopping", event) == "stopping"


def test_stop_wins_from_every_live_state() -> None:
    for state in ALL_STATES:
        if state == "stopping":
            continue
        assert supervisor_transition(state, "stop") == "stopping"


def test_interlock_held_dominates_blocked_and_degraded() -> None:
    # maintenance > blocked_* > degraded: interlock_held moves to maintenance
    # from any live, non-stopping state (including the blocked states).
    for state in ALL_STATES:
        if state == "stopping":
            continue
        assert supervisor_transition(state, "interlock_held") == "maintenance"


def test_maintenance_holds_until_interlock_frees() -> None:
    for event in ALL_EVENTS:
        expected = {
            "interlock_freed_clear": "starting",
            "interlock_freed_blocked_wsl": "blocked_wsl_active",
            "interlock_freed_blocked_probe": "blocked_probe_unavailable",
            "stop": "stopping",
            "interlock_held": "maintenance",
        }.get(event, "maintenance")
        assert supervisor_transition("maintenance", event) == expected, event


def test_guard_block_dominates_degraded() -> None:
    assert supervisor_transition("degraded", "guard_block_wsl") == "blocked_wsl_active"
    assert supervisor_transition("degraded", "guard_block_probe") == "blocked_probe_unavailable"


def test_blocked_states_can_replace_each_other_latest_guard_wins() -> None:
    assert (
        supervisor_transition("blocked_wsl_active", "guard_block_probe")
        == "blocked_probe_unavailable"
    )
    assert (
        supervisor_transition("blocked_probe_unavailable", "guard_block_wsl")
        == "blocked_wsl_active"
    )


def test_normal_lifecycle() -> None:
    assert supervisor_transition("starting", "children_ready") == "ready"
    assert supervisor_transition("ready", "dependency_lost") == "starting"
    assert supervisor_transition("degraded", "recovered") == "ready"
    assert supervisor_transition("ready", "restart_storm") == "degraded"
    assert supervisor_transition("starting", "restart_storm") == "degraded"


def test_interlock_freed_clear_is_noop_when_not_in_maintenance() -> None:
    # A clear verdict bundled with an interlock-release we were not holding
    # changes nothing outside maintenance (we are already running normally).
    assert supervisor_transition("ready", "interlock_freed_clear") == "ready"
    assert supervisor_transition("degraded", "interlock_freed_clear") == "degraded"
    assert supervisor_transition("starting", "interlock_freed_clear") == "starting"


# --------------------------------------------------------------------------
# WS5-RAT-002 -- leaving maintenance re-samples the guard; a block masked
# while the interlock was held is never erased by event ordering (fail-open
# regression the design ratification found and executed).
# --------------------------------------------------------------------------


def _seq(start: SupervisorState, *events: SupervisorEvent) -> SupervisorState:
    state = start
    for event in events:
        state = supervisor_transition(state, event)
    return state


def test_rat002_wsl_block_during_maintenance_is_resurfaced_at_exit() -> None:
    # The exact sequence the ratification executed: ready -> interlock_held ->
    # maintenance -> guard_block_wsl (ignored, freeze holds) -> release. The
    # release carries the re-sampled verdict and MUST route to blocked, never
    # fall through to starting.
    assert (
        _seq("ready", "interlock_held", "guard_block_wsl", "interlock_freed_blocked_wsl")
        == "blocked_wsl_active"
    )


def test_rat002_probe_block_during_maintenance_is_resurfaced_at_exit() -> None:
    assert (
        _seq("ready", "interlock_held", "guard_block_probe", "interlock_freed_blocked_probe")
        == "blocked_probe_unavailable"
    )


def test_rat002_clean_exit_only_on_a_clear_release_verdict() -> None:
    assert _seq("ready", "interlock_held", "interlock_freed_clear") == "starting"


def test_rat002_block_discovered_only_at_release_still_halts() -> None:
    # Nothing happened during maintenance, but the fresh release-time evaluation
    # finds WSL active / a probe unavailable (it changed during the window).
    assert _seq("ready", "interlock_held", "interlock_freed_blocked_wsl") == "blocked_wsl_active"
    assert (
        _seq("ready", "interlock_held", "interlock_freed_blocked_probe")
        == "blocked_probe_unavailable"
    )


def test_rat002_only_a_clear_verdict_leaves_maintenance_toward_starting() -> None:
    # The structural guarantee: enumerate every event; the ONLY one that moves
    # maintenance -> starting (a writer-capable state) is the clear verdict.
    to_starting = [e for e in ALL_EVENTS if supervisor_transition("maintenance", e) == "starting"]
    assert to_starting == ["interlock_freed_clear"]


def test_rat002_blocked_outcome_before_during_and_at_release() -> None:
    # before: a block, then interlock_held -> maintenance dominates (freeze wins)
    assert _seq("ready", "guard_block_wsl", "interlock_held") == "maintenance"
    # during: a block while held is ignored (freeze holds; nothing transmits)
    assert _seq("ready", "interlock_held", "guard_block_wsl") == "maintenance"
    # at release: the verdict is carried and persists past the exit
    assert (
        _seq("ready", "interlock_held", "guard_block_wsl", "interlock_freed_blocked_wsl")
        == "blocked_wsl_active"
    )


# --------------------------------------------------------------------------
# D5 pure helpers
# --------------------------------------------------------------------------


def test_is_restart_storm_boundary() -> None:
    window, threshold, now = 600.0, 5, 1_000.0
    # Exactly threshold restarts inside the window -> storm.
    inside = [now - 10 * i for i in range(threshold)]  # 5 restarts, all recent
    assert is_restart_storm(inside, now, window, threshold) is True
    # One fewer -> not a storm.
    assert is_restart_storm(inside[:-1], now, window, threshold) is False


def test_is_restart_storm_ignores_events_outside_the_window() -> None:
    window, threshold, now = 600.0, 5, 1_000.0
    old = [now - 700.0 - i for i in range(10)]  # all older than the window
    assert is_restart_storm(old, now, window, threshold) is False
    # Leading edge is inclusive: an event exactly window_seconds ago counts.
    on_edge = [now - window] + [now - 1.0 * i for i in range(threshold - 1)]
    assert is_restart_storm(on_edge, now, window, threshold) is True


def test_backoff_base_schedule() -> None:
    initial, cap = 1.0, 30.0
    assert backoff_base_seconds(0, initial, cap) == 1.0
    assert backoff_base_seconds(1, initial, cap) == 2.0
    assert backoff_base_seconds(2, initial, cap) == 4.0
    assert backoff_base_seconds(5, initial, cap) == 30.0  # 32 capped to 30
    assert backoff_base_seconds(50, initial, cap) == 30.0  # stays capped
    assert backoff_base_seconds(-3, initial, cap) == 1.0  # negative clamps to attempt 0


@pytest.mark.parametrize("attempt", [0, 1, 2, 3, 10])
def test_backoff_never_exceeds_cap(attempt: int) -> None:
    assert backoff_base_seconds(attempt, 1.0, 30.0) <= 30.0
