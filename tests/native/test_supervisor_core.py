# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.native.supervisor.core (slice:ws5-supervisor).

The Supervisor orchestration is PURE and CI-testable on any OS: every probe,
child-runner, guard, clock, and alert transport is an injected fake, so the
control logic that drives the states.py machine runs on Linux with no Windows
import, no subprocess, and no socket. The Windows-only real bits (Job Object,
named pipe) are covered by the wave-1 ``*_win.py`` suites and are not required
here.

Covers the RAT-002 three exit routings; maintenance entry + the fail-closed
maintenance-readiness gate; the D6 startup order and dependent-restart-after-
dependency-ready ordering; restart-storm -> degraded + a fired alert; the
drain-all CTRL_BREAK trigger + Job Object backstop; the pre_child_start guard
gate on a transmission child; and the status-snapshot / command-handler shape.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from civiccast.native.models import (
    A1Result,
    A2Result,
    A3Result,
    GuardDecision,
    InterlockRead,
    SelectorRead,
)
from civiccast.native.runtime_guard import GuardMonitor, GuardMonitorStatus
from civiccast.native.supervisor.children import ChildSpec, ControlPlaneHealthProbe
from civiccast.native.supervisor.config import SupervisorConfig
from civiccast.native.supervisor.core import (
    ChildProcessRunner,
    StatusSnapshot,
    Supervisor,
    _guard_block_event,
    _interlock_freed_event,
)

# ---------------------------------------------------------------------------
# Fakes (no Win32, no subprocess, no socket)
# ---------------------------------------------------------------------------


@dataclass
class FakeHandle:
    pid: int


@dataclass
class FakeRunner:
    """Records every spawn/ctrl-break/terminate; hands out FakeHandles with
    monotonically increasing pids. ``alive`` maps pid -> liveness so a test can
    drive the drain-all exit behaviour deterministically."""

    spawned: list[ChildSpec] = field(default_factory=list)
    ctrl_break_pids: list[int] = field(default_factory=list)
    terminated_pids: list[int] = field(default_factory=list)
    graceful_stopped_pids: list[int] = field(default_factory=list)
    opened_existing_pids: list[int] = field(default_factory=list)
    alive: dict[int, bool] = field(default_factory=dict)
    _next_pid: int = 1000

    def spawn(self, spec: ChildSpec) -> FakeHandle:
        self._next_pid += 1
        self.spawned.append(spec)
        self.alive[self._next_pid] = True
        return FakeHandle(pid=self._next_pid)

    def open_existing(self, pid: int) -> FakeHandle:
        # CC-WS5-003: open a DURABLE handle to an already-running process (the
        # postmaster). Records the pid, marks it alive, and hands back a distinct
        # handle carrying exactly that pid -- so a test can assert the launcher
        # was swapped for the postmaster and drive the postmaster's liveness.
        self.opened_existing_pids.append(pid)
        self.alive[pid] = True
        return FakeHandle(pid=pid)

    def is_alive(self, handle: FakeHandle) -> bool:
        return self.alive.get(handle.pid, False)

    def send_ctrl_break(self, handle: FakeHandle) -> None:
        self.ctrl_break_pids.append(handle.pid)

    def terminate(self, handle: FakeHandle) -> None:
        self.terminated_pids.append(handle.pid)
        self.alive[handle.pid] = False

    def graceful_stop(self, handle: FakeHandle) -> object:
        # The postmaster-containment rollback path: records the pid so a test
        # can assert postgres was asked to tear ITSELF down (reaping its
        # workers) before the TerminateProcess fallback.
        self.graceful_stopped_pids.append(handle.pid)
        self.alive[handle.pid] = False
        return "argv"

    @property
    def spawned_names(self) -> list[str]:
        return [spec.name for spec in self.spawned]


class FakeGuard:
    """A stand-in for GuardMonitor: pre_child_start / evaluate_once return a
    preset GuardDecision and count their invocations."""

    def __init__(self, decision: GuardDecision) -> None:
        self.decision = decision
        self.status = GuardMonitorStatus(last_decision=decision)
        self.pre_child_start_calls = 0
        self.evaluate_once_calls = 0

    def pre_child_start(self) -> GuardDecision:
        self.pre_child_start_calls += 1
        return self.decision

    def evaluate_once(self) -> GuardDecision:
        self.evaluate_once_calls += 1
        self.status.last_decision = self.decision
        return self.decision


@dataclass
class FakeOutbox:
    fired: list[dict[str, str]] = field(default_factory=list)

    def fire(self, *, summary: str, detail: str) -> None:
        self.fired.append({"summary": summary, "detail": detail})


class FakeJobApi:
    """A JobObjectApi that never touches Win32. Records assigned pids; reports
    no straggler job (the common kill-on-close-already-reaped case)."""

    def __init__(self) -> None:
        self.assigned_pids: list[int] = []
        self.created = False
        self.closed = False
        self.open_existing_calls = 0

    def create_job(self, name: str) -> object:
        self.created = True
        return object()

    def configure_kill_on_close_no_breakaway(self, handle: object) -> None:
        return None

    def assign_process(self, handle: object, pid: int) -> None:
        self.assigned_pids.append(pid)

    def is_process_in_job(self, handle: object, pid: int) -> bool:
        return pid in self.assigned_pids

    def is_process_in_any_job(self, pid: int) -> bool:
        return pid in getattr(self, "any_job_pids", set())

    def close_job(self, handle: object) -> None:
        self.closed = True

    def open_existing_job(self, name: str) -> object | None:
        self.open_existing_calls += 1
        return None

    def list_job_process_ids(self, handle: object) -> list[int]:
        return []

    def terminate_job(self, handle: object, exit_code: int) -> None:
        return None


class FakeClock:
    """A monotonic fake clock; ``sleep(dt)`` advances it so poll_until_ready's
    deadline logic runs in microseconds with no real waiting."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


class FlakyProbe:
    """G1 repro seam: a readiness probe that is UNREADY for its first
    ``misses`` calls, then READY forever after -- i.e. the dependency is only
    transiently unready across ``Supervisor.start()``'s own readiness poll,
    and has fully recovered by the time the tick loop starts reconciling.
    Models run 17: nats recovered within seconds, but control_plane was never
    even ATTEMPTED again for the life of the service."""

    def __init__(self, misses: int) -> None:
        self.misses = misses
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.misses


# ---------------------------------------------------------------------------
# Decision / probe builders
# ---------------------------------------------------------------------------


def guard_decision(action: str, state_name: str | None) -> GuardDecision:
    return GuardDecision(
        action=action,  # type: ignore[arg-type]
        named_probe=None,
        message=f"test decision action={action} state_name={state_name}",
        retry_seconds=10 if action == "blocked_probe_unavailable" else None,
        state_name=state_name,
    )


def normal_health() -> ControlPlaneHealthProbe:
    return ControlPlaneHealthProbe(status_code=200, mode="normal")


def unready_health() -> ControlPlaneHealthProbe:
    """A control plane that answers but is NOT ready (health probe fails), so a
    readiness poll times out -> the child is left alive-but-unready."""
    return ControlPlaneHealthProbe(status_code=503, mode="normal")


def _det_rng() -> float:
    """A deterministic jitter RNG: 0.5 -> zero jitter (base delay unchanged), so
    the backoff schedule is exact and assertable under test."""
    return 0.5


def _fresh_postmaster_pid_reader(start: int = 90000) -> Callable[[], int | None]:
    """CC-WS5-003: a default fake ``postmaster_pid_reader`` that yields a FRESH,
    distinct pid each call (simulating a new postmaster.pid on every postgres
    launch), well clear of FakeRunner's launcher pid range (1001+). Distinct-per-
    launch is what lets a restart test see the postmaster pid change."""

    counter = {"n": start}

    def reader() -> int | None:
        counter["n"] += 1
        return counter["n"]

    return reader


def maintenance_health() -> ControlPlaneHealthProbe:
    return ControlPlaneHealthProbe(
        status_code=200,
        mode="maintenance",
        workers_started=False,
        mutating_disabled=True,
        mode_contract=1,
    )


def make_supervisor(
    *,
    guard: FakeGuard | None = None,
    runner: FakeRunner | None = None,
    outbox: FakeOutbox | None = None,
    job_api: FakeJobApi | None = None,
    clock: FakeClock | None = None,
    postgres_ready: bool = True,
    health=normal_health,
    interlock: str = "free",
    interlock_reader: Callable[[], str] | None = None,
    config: SupervisorConfig | None = None,
    rng: Callable[[], float] = _det_rng,
    postmaster_pid_reader: Callable[[], int | None] | None = None,
    control_plane_env: dict[str, str] | None = None,
    should_abort: Callable[[], bool] | None = None,
    postgres_log_path: str | None = None,
) -> Supervisor:
    guard = guard or FakeGuard(guard_decision("start", None))
    runner = runner or FakeRunner()
    outbox = outbox or FakeOutbox()
    job_api = job_api or FakeJobApi()
    clock = clock or FakeClock()
    reader = interlock_reader if interlock_reader is not None else (lambda: interlock)
    # CC-WS5-003: default the postmaster pid resolver to a fresh-pid fake so the
    # postgres launcher->postmaster swap succeeds in every existing test (the real
    # default would read pgdata/postmaster.pid off disk -> None -> fail closed).
    pm_reader = (
        postmaster_pid_reader
        if postmaster_pid_reader is not None
        else _fresh_postmaster_pid_reader()
    )
    return Supervisor(
        config=config or SupervisorConfig(),
        guard=guard,
        job_api=job_api,
        runner=runner,
        alert_outbox=outbox,
        postgres_probe=lambda: postgres_ready,
        health_probe=health,
        clock=clock.now,
        sleep=clock.sleep,
        interlock_reader=reader,  # type: ignore[arg-type,return-value]
        should_abort=should_abort,
        rng=rng,
        postmaster_pid_reader=pm_reader,
        program_data_root=r"C:\ProgramData",
        postgres_data_dir="pgdata",
        control_plane_env=control_plane_env,
        postgres_log_path=postgres_log_path,
    )


# ---------------------------------------------------------------------------
# Adjacent diagnosability fix (2026-08-12, TESTER2 b5 evidence): postgres_log_path
# threaded from Supervisor into postgres_child_spec's own ``-l`` flag.
# ---------------------------------------------------------------------------


def test_postgres_log_path_reaches_the_spawned_spec() -> None:
    """Fails on the pre-fix base: Supervisor had no ``postgres_log_path``
    parameter at all, so ``_spec_for("postgres")`` could never request a
    ``-l`` flag regardless of what the service layer wanted to pass."""

    runner = FakeRunner()
    sup = make_supervisor(
        runner=runner, postgres_log_path=r"C:\ProgramData\CivicCast\logs\postgres.log"
    )

    sup.start_child("postgres")

    spawned = next(spec for spec in runner.spawned if spec.name == "postgres")
    assert "-l" in spawned.argv
    assert (
        spawned.argv[spawned.argv.index("-l") + 1] == r"C:\ProgramData\CivicCast\logs\postgres.log"
    )


def test_postgres_log_path_is_optional() -> None:
    """No log path (the pre-existing call shape, e.g. every OTHER
    make_supervisor() call in this file) must reproduce the prior argv
    exactly -- no ``-l`` flag, no behavior change for callers that don't
    opt in."""

    runner = FakeRunner()
    sup = make_supervisor(runner=runner)

    sup.start_child("postgres")

    postgres_spec = next(spec for spec in runner.spawned if spec.name == "postgres")
    assert "-l" not in postgres_spec.argv


# ---------------------------------------------------------------------------
# RAT-002 -- the three maintenance-exit routings
# ---------------------------------------------------------------------------


def test_rat002_interlock_freed_clear_routes_to_starting() -> None:
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(guard=guard)
    sup.force_state("maintenance")

    event = sup.on_interlock_freed()

    assert guard.evaluate_once_calls == 1
    assert event == "interlock_freed_clear"
    assert sup.state == "starting"


def test_rat002_interlock_freed_blocked_wsl_routes_to_blocked_wsl() -> None:
    guard = FakeGuard(guard_decision("refuse", "blocked_wsl_active"))
    sup = make_supervisor(guard=guard)
    sup.force_state("maintenance")

    event = sup.on_interlock_freed()

    assert event == "interlock_freed_blocked_wsl"
    assert sup.state == "blocked_wsl_active"


def test_rat002_interlock_freed_blocked_probe_routes_to_blocked_probe() -> None:
    guard = FakeGuard(guard_decision("blocked_probe_unavailable", "blocked_probe_unavailable"))
    sup = make_supervisor(guard=guard)
    sup.force_state("maintenance")

    event = sup.on_interlock_freed()

    assert event == "interlock_freed_blocked_probe"
    assert sup.state == "blocked_probe_unavailable"


def test_rat002_does_not_spawn_writer_child_before_evaluation() -> None:
    """RAT-002 load-bearing: the held->freed edge performs exactly ONE guard
    evaluation and MUST NOT advance a writer-capable child before it."""
    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    sup = make_supervisor(guard=guard, runner=runner)
    sup.force_state("maintenance")

    sup.on_interlock_freed()

    assert guard.evaluate_once_calls == 1
    assert runner.spawned == []  # no child advanced by the edge itself


def test_interlock_freed_nonstart_action_fails_closed_to_blocked_wsl() -> None:
    """CC-WS5-012: routing is on ACTION, not state_name. A non-start action
    (here ``refuse``) with an unrecognized/unexpected state_name no longer RAISES
    (the old fail-closed-by-raise, which crashed the tick loop on a real
    ``never_start``/``refuse`` whose state_name is ``None``). It fail-closes to
    the WSL block: a non-start verdict never advances a writer-capable state,
    however its state_name is labeled."""
    guard = FakeGuard(guard_decision("refuse", "some_unknown_state"))
    sup = make_supervisor(guard=guard)
    sup.force_state("maintenance")

    event = sup.on_interlock_freed()

    assert event == "interlock_freed_blocked_wsl"
    assert sup.state == "blocked_wsl_active"


# ---------------------------------------------------------------------------
# Maintenance entry + fail-closed readiness (RAT-001)
# ---------------------------------------------------------------------------


def test_maintenance_entry_launches_control_plane_with_maintenance_env() -> None:
    runner = FakeRunner()
    sup = make_supervisor(runner=runner, health=maintenance_health)

    sup.enter_maintenance()

    assert sup.state == "maintenance"
    cp = next(s for s in runner.spawned if s.name == "control_plane")
    assert cp.env["CIVICCAST_SUPERVISOR_MODE"] == "maintenance"
    assert cp.env["CIVICCAST_SUPERVISOR_MODE_CONTRACT"] == "1"


def test_control_plane_child_carries_egress_work_dir_into_programdata() -> None:
    runner = FakeRunner()
    sup = make_supervisor(runner=runner, health=maintenance_health)

    sup.enter_maintenance()

    cp = next(s for s in runner.spawned if s.name == "control_plane")
    assert cp.env["CIVICCAST_EGRESS_WORK_DIR"] == r"C:\ProgramData\CivicCast\data\egress"


def test_control_plane_child_inherits_the_verified_native_station_environment() -> None:
    runner = FakeRunner()
    station_env = {
        "CIVICCAST_NATIVE_STATION": "1",
        "CIVICCAST_CAPTION_TAP": "inline",
        "CIVICCAST_WHISPER_MODEL_PATH": r"C:\Program Files\CivicCast\model",
        "CIVICCAST_EGRESS_ENGINE": "gstreamer",
        "CIVICCAST_EGRESS_EMBED_CAPTIONS": "1",
    }
    sup = make_supervisor(
        runner=runner,
        health=maintenance_health,
        control_plane_env=station_env,
    )

    sup.enter_maintenance()

    cp = next(s for s in runner.spawned if s.name == "control_plane")
    assert station_env.items() <= cp.env.items()
    assert cp.env["CIVICCAST_SUPERVISOR_MODE"] == "maintenance"


def test_maintenance_readiness_fail_closed_stays_maintenance() -> None:
    """A control plane that reports normal mode (no maintenance attestation)
    never satisfies the maintenance-readiness gate -> the freeze holds."""
    sup = make_supervisor(health=normal_health)

    result = sup.enter_maintenance()

    assert sup.state == "maintenance"
    assert result.outcome != "ready"


def test_maintenance_readiness_satisfied_when_attested() -> None:
    sup = make_supervisor(health=maintenance_health)

    result = sup.enter_maintenance()

    assert result.outcome == "ready"
    # Even when the maintenance gate is satisfied, we STAY in maintenance --
    # workers are never permitted there (property P2).
    assert sup.state == "maintenance"
    assert sup.workers_permitted() is False


# ---------------------------------------------------------------------------
# D6 startup order + dependent restart
# ---------------------------------------------------------------------------


def test_startup_order_brings_up_pg_cp_in_order() -> None:
    runner = FakeRunner()
    sup = make_supervisor(runner=runner)

    sup.start()

    assert runner.spawned_names == ["postgres", "control_plane"]
    assert sup.state == "ready"


def test_startup_assigns_every_child_to_the_job_object() -> None:
    runner = FakeRunner()
    job_api = FakeJobApi()
    sup = make_supervisor(runner=runner, job_api=job_api)

    sup.start()

    # One assigned pid per direct child; sweep ran before spawning.
    assert len(job_api.assigned_pids) == 2
    assert job_api.open_existing_calls >= 1


def test_control_plane_not_eligible_until_postgres_ready() -> None:
    """D6: control_plane may (re)start only after ALL predecessors are ready.
    With postgres not ready, a control_plane restart is refused as
    not_eligible."""
    sup = make_supervisor()
    sup.start()  # everyone ready

    # postgres leaves ready; control_plane's dependency is now unmet.
    sup.on_dependency_lost("postgres")
    outcome = sup.try_restart_child("control_plane")

    assert outcome.status == "not_eligible"


def test_dependent_restart_after_dependency_reenters_ready() -> None:
    runner = FakeRunner()
    sup = make_supervisor(runner=runner)
    sup.start()
    spawn_count_after_start = len(runner.spawned)

    sup.on_dependency_lost("postgres")
    # Bring the dependency (postgres) back to ready first...
    assert sup.try_restart_child("postgres").status == "started_ready"
    # ...only now is control_plane eligible to restart.
    cp_outcome = sup.try_restart_child("control_plane")

    assert cp_outcome.status == "started_ready"
    assert len(runner.spawned) == spawn_count_after_start + 2


# ---------------------------------------------------------------------------
# G1 (BLOCKER) -- a never-attempted child must still be retried once its
# dependency recovers. Verified diagnosis (run 17): STARTUP_ORDER children
# boot-initialize to 'stopped'; _needs_restart treats 'stopped' as a
# deliberate stop and never retries it. When start() bails early because a
# child missed its readiness budget, every later child in STARTUP_ORDER is
# left at that boot-time 'stopped' and is NEVER attempted again for the life
# of the service, even after the blocking dependency recovers.
# ---------------------------------------------------------------------------


def test_g1_child_never_attempted_after_start_early_bail_is_retried_once_dependency_recovers() -> (
    None
):
    """Repro of run 17's exact wedge: postgres misses ONLY start()'s own 60s
    readiness budget (transient), then answers ready forever after. Before the
    fix, start()'s early bail (core.py: STARTUP_ORDER[:-1] loop) never even
    attempts control_plane, and it is left at its boot-time 'stopped' init --
    'stopped' is fail-closed-retry-exempt (deliberate stop / the ollama skip),
    so _needs_restart never retries it and control_plane is never spawned in
    15 minutes (900 ticks) of 1 Hz supervision, despite postgres being healthy
    the entire time the tick loop ran. After the fix, STARTUP_ORDER children
    boot into a distinct 'pending' (retry-eligible) state, so the tick loop's
    recovery path picks control_plane up as soon as postgres is ready again."""

    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    clock = FakeClock()
    # POSTGRES_READY_BUDGET_SECONDS is 60s at a 1s poll interval -> EXACTLY 61
    # check() calls inside start()'s own poll_until_ready (deadline computed
    # once at t=0; the t==deadline call is still made before the timeout
    # check). 61 misses keeps postgres unready for the ENTIRETY of start(),
    # then healthy for every tick loop call after -- i.e. transiently unready
    # only during start().
    postgres_probe = FlakyProbe(misses=61)
    sup = Supervisor(
        config=SupervisorConfig(),
        guard=guard,
        job_api=FakeJobApi(),
        runner=runner,
        alert_outbox=FakeOutbox(),
        postgres_probe=postgres_probe,
        health_probe=normal_health,
        clock=clock.now,
        sleep=clock.sleep,
        interlock_reader=lambda: "free",
        rng=_det_rng,
        postmaster_pid_reader=_fresh_postmaster_pid_reader(),
        program_data_root=r"C:\ProgramData",
    )

    sup.start()
    # postgres missed start()'s own readiness budget -> start() bails before
    # ever attempting control_plane (D6 order: postgres, control_plane).
    assert sup.state == "starting"
    assert "control_plane" not in runner.spawned_names
    assert postgres_probe.calls == postgres_probe.misses, (
        "test setup: start()'s readiness budget must have exhausted exactly at "
        "the misses boundary, so every call after this point returns ready"
    )

    for _ in range(900):  # the 15-minute 1 Hz supervision loop of run 17
        sup.tick(now=clock.now())
        clock.sleep(1.0)

    assert "control_plane" in runner.spawned_names, (
        "control_plane was NEVER EVEN ATTEMPTED after postgres recovered -- the "
        "never-attempted-children-are-never-retried wedge (G1)"
    )
    assert sup.state == "ready"
    assert sup.child_state("control_plane") == "ready"


# ---------------------------------------------------------------------------
# G2 (observability) -- core.py had ZERO logging; run 17's diagnosis needed a
# from-scratch repro script instead of a log line. Each of the three warning
# sites is latched: emitted once per DISTINCT reason, never once per tick.
# ---------------------------------------------------------------------------

_CORE_LOGGER_NAME = "civiccast.native.supervisor.core"


def test_g2a_start_bail_warns_once_per_distinct_reason_not_every_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """G2(a): start()'s early-bail WARNING must be latched by reason (child +
    status + detail). The SAME reason on a second start() attempt must not
    double-log; a genuinely DIFFERENT reason (bail at a different child) must
    log again."""

    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    clock = FakeClock()
    probes = {"postgres": False}
    sup = Supervisor(
        config=SupervisorConfig(),
        guard=guard,
        job_api=FakeJobApi(),
        runner=runner,
        alert_outbox=FakeOutbox(),
        postgres_probe=lambda: probes["postgres"],
        health_probe=normal_health,
        clock=clock.now,
        sleep=clock.sleep,
        interlock_reader=lambda: "free",
        rng=_det_rng,
        postmaster_pid_reader=_fresh_postmaster_pid_reader(),
        program_data_root=r"C:\ProgramData",
    )

    with caplog.at_level("WARNING", logger=_CORE_LOGGER_NAME):
        sup.start()  # postgres never ready -> bails at postgres
        assert sup.state == "starting"
        bail_records = [r for r in caplog.records if "startup halted at child" in r.getMessage()]
        assert len(bail_records) == 1
        assert "startup halted at child postgres" in bail_records[0].getMessage()

        # Same scenario, same reason: a second start() attempt must NOT re-log.
        sup.start()
        bail_records = [r for r in caplog.records if "startup halted at child" in r.getMessage()]
        assert len(bail_records) == 1, "an unchanged bail reason must not be re-logged"

        # A genuinely different reason (postgres now ready, so it bails at
        # control_plane's guard instead) must log again.
        probes["postgres"] = True
        guard.decision = guard_decision("refuse", None)
        sup.start()
        bail_records = [r for r in caplog.records if "startup halted at child" in r.getMessage()]
        assert len(bail_records) == 2, "a genuinely different bail reason must log again"
        assert "startup halted at child control_plane" in bail_records[1].getMessage()


def test_g2b_guard_withheld_warns_once_per_distinct_reason_not_every_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """G2(b): the guard-withheld branch's WARNING must be latched -- a guard
    block that holds the SAME verdict across many ticks logs once; a verdict
    that actually changes logs again."""

    guard = FakeGuard(guard_decision("refuse", None))
    sup = make_supervisor(guard=guard)

    with caplog.at_level("WARNING", logger=_CORE_LOGGER_NAME):
        sup.start()
        assert sup.state == "starting"
        withheld = [r for r in caplog.records if "start withheld by guard" in r.getMessage()]
        assert len(withheld) == 1

        # The tick loop retries the withheld start every tick (F-REV-3); the
        # SAME guard verdict must not re-log on each retry.
        for t in range(1, 6):
            sup.tick(now=float(t))
        withheld = [r for r in caplog.records if "start withheld by guard" in r.getMessage()]
        assert len(withheld) == 1, (
            "an unchanged guard-withheld reason must not be re-logged per tick"
        )

        # A genuinely different (still non-start) verdict must log again.
        guard.decision = guard_decision("refuse", "blocked_wsl_active")
        sup.tick(now=6.0)
        withheld = [r for r in caplog.records if "start withheld by guard" in r.getMessage()]
        assert len(withheld) == 2, "a genuinely different guard-withheld reason must log again"


def test_g2c_restart_not_ready_warns_once_per_distinct_detail_not_every_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """G2(c): the not_ready restart WARNING must be latched -- a child that
    fails its readiness poll the SAME way on every backoff cycle logs once,
    not once per attempt; a genuinely different failure detail logs again."""

    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    clock = FakeClock()
    health_status = {"code": 200}
    sup = Supervisor(
        config=SupervisorConfig(),
        guard=guard,
        job_api=FakeJobApi(),
        runner=runner,
        alert_outbox=FakeOutbox(),
        postgres_probe=lambda: True,
        health_probe=lambda: ControlPlaneHealthProbe(status_code=health_status["code"]),
        clock=clock.now,
        sleep=clock.sleep,
        interlock_reader=lambda: "free",
        rng=_det_rng,
        postmaster_pid_reader=_fresh_postmaster_pid_reader(),
        program_data_root=r"C:\ProgramData",
    )
    sup.start()
    assert sup.state == "ready"

    cp_pid = sup.handles()["control_plane"].pid
    runner.alive[cp_pid] = False
    sup.on_dependency_lost("control_plane")
    assert sup.state == "starting"
    health_status["code"] = 503  # answers, but never attests ready

    with caplog.at_level("WARNING", logger=_CORE_LOGGER_NAME):
        for _ in range(80):
            clock.sleep(1.0)
            sup.tick(now=clock.now())

        not_ready = [
            r
            for r in caplog.records
            if "restart of child control_plane not ready" in r.getMessage()
        ]
        assert len(not_ready) == 1, (
            "an unchanged not_ready detail must not be re-logged per attempt"
        )
        # Prove multiple restart attempts genuinely happened with that SAME
        # detail (otherwise the assertion above would be vacuous).
        assert runner.spawned_names.count("control_plane") >= 3

        # A genuinely different failure detail (a different HTTP status) must
        # log again.
        health_status["code"] = 500
        for _ in range(80):
            clock.sleep(1.0)
            sup.tick(now=clock.now())
        not_ready = [
            r
            for r in caplog.records
            if "restart of child control_plane not ready" in r.getMessage()
        ]
        assert len(not_ready) == 2, "a genuinely different not_ready detail must log again"


# ---------------------------------------------------------------------------
# Restart storm -> degraded + alert
# ---------------------------------------------------------------------------


def test_restart_storm_demotes_to_degraded_and_fires_alert() -> None:
    outbox = FakeOutbox()
    sup = make_supervisor(outbox=outbox)
    sup.start()  # ready

    # Five restarts inside the 10-minute window (default threshold 5).
    for epoch in (0.0, 10.0, 20.0, 30.0, 40.0):
        sup.record_restart(epoch)
    storm = sup.evaluate_restart_storm(now=40.0)

    assert storm is True
    assert sup.state == "degraded"
    assert len(outbox.fired) == 1


def test_no_restart_storm_below_threshold_stays_ready() -> None:
    outbox = FakeOutbox()
    sup = make_supervisor(outbox=outbox)
    sup.start()

    for epoch in (0.0, 10.0, 20.0):  # only 3, below threshold
        sup.record_restart(epoch)
    storm = sup.evaluate_restart_storm(now=20.0)

    assert storm is False
    assert sup.state == "ready"
    assert outbox.fired == []


def test_recovery_retries_a_stuck_restart_until_ready_not_wedged_in_starting() -> None:
    """F-REV-3 (double-review): a restart that does NOT succeed synchronously (the
    guard is transiently blocked, or a readiness budget times out) must be RETRIED
    on a later tick, not wedge the machine in ``starting`` forever. Reproduces the
    reviewer's exact scenario: control_plane dies while the guard is blocked for one
    tick, then the guard clears."""

    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    sup = make_supervisor(guard=guard, runner=runner)
    sup.start()
    assert sup.state == "ready"
    cp_pid = sup.handles()["control_plane"].pid

    # CC-WS5-002 reconcile: the death moves the machine to ``starting`` FIRST (a
    # recovery is now in progress). This isolates F-REV-3's concern -- the
    # recovery path's handling of a guard-WITHHELD restart -- from the new
    # continuous dual-runtime guard, which is deliberately gated to ready/degraded
    # and does NOT run in ``starting`` (a guard refuse observed while SERVING is a
    # dual-runtime BLOCK, covered by test_midop_wsl_activation_*; that is not what
    # this test is about). ``on_dependency_lost`` is exactly what the reconciler
    # calls on a detected death (ready -> starting, child failed).
    runner.alive[cp_pid] = False
    sup.on_dependency_lost("control_plane")
    assert sup.state == "starting"

    # The guard is transiently blocked on this tick: the writer-capable restart is
    # WITHHELD (nothing spawned), so it must NOT arm the backoff and must be
    # retried freely on a later tick -- not wedge the machine in ``starting``.
    guard.decision = guard_decision("refuse", "blocked_wsl_active")
    sup.tick(now=1.0)
    assert sup.state == "starting"  # writer-capable restart withheld -> not yet ready
    assert runner.spawned_names.count("control_plane") == 1  # nothing spawned (withheld)

    # The guard clears; a LATER tick MUST retry the withheld restart and return to
    # ready -- with the pre-fix code, tick() never re-enters recovery from
    # "starting", so this stayed stuck forever.
    guard.decision = guard_decision("start", None)
    sup.tick(now=2.0)
    assert sup.state == "ready", "recovery must retry the stuck restart, not wedge in 'starting'"
    assert sup.workers_permitted() is True
    assert runner.spawned_names.count("control_plane") == 2  # boot + one successful retry


def test_restart_storm_alert_fires_once_not_every_tick_while_degraded() -> None:
    """F-REV-4 (double-review): the storm alert fires ONCE on the edge into
    ``degraded`` -- not again on every subsequent tick while degraded with no new
    child death. The pre-fix loop called evaluate_restart_storm unconditionally
    each tick, flooding the alert transport (~one DB row per tick) for the life of
    the window."""

    outbox = FakeOutbox()
    sup = make_supervisor(outbox=outbox)
    sup.start()  # ready

    # Pre-load five restart epochs inside the 10-minute window (default threshold 5).
    for epoch in (0.0, 10.0, 20.0, 30.0, 40.0):
        sup.record_restart(epoch)

    # A tick with NO new death trips the storm on the edge: degraded + exactly one alert.
    sup.tick(now=40.0)
    assert sup.state == "degraded"
    assert len(outbox.fired) == 1

    # Five MORE ticks, still no new death, still inside the window -> must NOT re-fire.
    for t in (41.0, 42.0, 43.0, 44.0, 45.0):
        sup.tick(now=t)
    assert len(outbox.fired) == 1, (
        "storm alert must fire once on the edge into degraded, not every tick while degraded"
    )


# ---------------------------------------------------------------------------
# CC-WS5-005 -- live-unready recovery, jittered backoff, dependent restart,
# recovered dispatch
# ---------------------------------------------------------------------------


def test_live_unready_child_is_terminated_and_retried_to_ready() -> None:
    """CC-WS5-005 sub-fix 1 (live-unready wedge): ``start_child`` leaves a child
    that missed its readiness budget ALIVE (a real process) but ``child_state``
    ``"failed"``. A later tick, with health now good, must TERMINATE the stale
    process and restart it to ready. The pre-fix ``_recover_dead_children`` acted
    ONLY on a DEAD handle, so the live-but-unready child was wedged forever."""
    runner = FakeRunner()
    clock = FakeClock()
    health_ready = {"v": False}

    def health() -> ControlPlaneHealthProbe:
        return normal_health() if health_ready["v"] else unready_health()

    sup = make_supervisor(runner=runner, clock=clock, health=health)
    sup.start()

    # control_plane was spawned but never reached ready within budget: alive + failed.
    assert sup.child_state("control_plane") == "failed"
    stale = sup.handles()["control_plane"]
    stale_pid = stale.pid
    assert runner.is_alive(stale) is True
    assert sup.state == "starting"

    # Health recovers; a tick must terminate the stale pid and restart to ready.
    health_ready["v"] = True
    sup.tick(now=clock.now())

    assert stale_pid in runner.terminated_pids, "the stale live-unready process must be terminated"
    assert sup.child_state("control_plane") == "ready"
    assert sup.handles()["control_plane"].pid != stale_pid, (
        "a fresh process must replace the stale one"
    )
    assert sup.state == "ready"


def test_backoff_schedule_retries_on_exponential_epochs_and_resets_on_ready() -> None:
    """CC-WS5-005 sub-fix 2 (per-child jittered backoff): a child that keeps
    failing readiness is retried on the D5 exponential backoff schedule
    (deterministic rng=0.5 -> zero jitter -> base delays 2, 4, 8, ... capped at
    max), NOT on every tick; the schedule RESETS the moment the child reaches
    ready. Pre-fix, ``_recover_dead_children`` called ``try_restart_child`` every
    single tick with no backoff at all."""
    runner = FakeRunner()
    clock = FakeClock()
    health_ready = {"v": False}

    def health() -> ControlPlaneHealthProbe:
        return normal_health() if health_ready["v"] else unready_health()

    sup = make_supervisor(runner=runner, clock=clock, health=health, rng=_det_rng)
    sup.start()  # control_plane fails readiness -> alive + failed, state "starting"

    def cp_spawns() -> int:
        return runner.spawned_names.count("control_plane")

    assert cp_spawns() == 1  # only the boot spawn so far

    # next_retry_epoch starts at 0.0 -> the first retry is eligible immediately.
    sup.tick(now=0.0)
    assert cp_spawns() == 2  # retry #1 (attempt 1 -> next_retry 0 + 2 = 2)

    sup.tick(now=1.0)
    assert cp_spawns() == 2  # 1.0 < 2.0 -> NOT eligible; no spawn (this is the fix)

    sup.tick(now=2.0)
    assert cp_spawns() == 3  # 2.0 >= 2.0 -> retry #2 (attempt 2 -> next_retry 2 + 4 = 6)

    sup.tick(now=5.0)
    assert cp_spawns() == 3  # 5.0 < 6.0 -> no spawn

    sup.tick(now=6.0)
    assert cp_spawns() == 4  # 6.0 >= 6.0 -> retry #3 (attempt 3 -> next_retry 6 + 8 = 14)

    # The backoff advanced to attempt 3 with the next retry scheduled at t=14.
    assert sup._backoff["control_plane"].attempt == 3
    assert sup._backoff["control_plane"].next_retry_epoch == 14.0

    # Health recovers; the next eligible retry reaches ready and RESETS the schedule.
    health_ready["v"] = True
    sup.tick(now=14.0)
    assert sup.child_state("control_plane") == "ready"
    assert sup.state == "ready"
    assert sup._backoff["control_plane"].attempt == 0
    assert sup._backoff["control_plane"].next_retry_epoch == 0.0


def test_dependency_death_restarts_downstream_children_in_startup_order() -> None:
    """CC-WS5-005 sub-fix 3 (dependent restart, D6): when a dependency dies and is
    relaunched, every DOWNSTREAM child (later in STARTUP_ORDER) must ALSO be
    restarted -- in order -- so it rebinds to the fresh dependency. Pre-fix,
    killing postgres relaunched ONLY postgres and left control_plane bound
    to its stale pid."""
    runner = FakeRunner()
    sup = make_supervisor(runner=runner)
    sup.start()
    assert sup.state == "ready"

    pg_pid = sup.handles()["postgres"].pid
    cp_pid = sup.handles()["control_plane"].pid
    spawns_after_boot = len(runner.spawned)

    # postgres dies.
    runner.alive[pg_pid] = False
    sup.tick(now=0.0)

    assert sup.state == "ready"
    # Both carry FRESH pids...
    assert sup.handles()["postgres"].pid != pg_pid
    assert sup.handles()["control_plane"].pid != cp_pid
    # ...the stale downstream process was terminated to rebind it, and...
    assert cp_pid in runner.terminated_pids
    # ...the restart ran in D6 order (postgres -> control_plane).
    assert runner.spawned_names[spawns_after_boot:] == ["postgres", "control_plane"]


def test_recovered_event_dispatched_once_after_return_to_fresh_readiness() -> None:
    """CC-WS5-005 sub-fix 4 (recovered dispatch): a supervisor already in
    ``degraded`` that watches a failed child return to FRESH readiness must
    dispatch the ``recovered`` event EXACTLY ONCE (degraded -> ready). Pre-fix,
    production recovery never dispatched ``recovered`` and stayed wedged in
    degraded even once every child was healthy again."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard)
    sup.start()
    # Enter degraded as if a prior restart storm had demoted us (service stays up).
    sup.force_state("degraded")

    # Record every dispatched event to prove "recovered" fires exactly once.
    dispatched: list[str] = []
    original_dispatch = sup._dispatch

    def recording_dispatch(event: str) -> str:
        dispatched.append(event)
        return original_dispatch(event)  # type: ignore[arg-type]

    sup._dispatch = recording_dispatch  # type: ignore[assignment,method-assign]

    # control_plane dies; a tick recovers it to fresh readiness -> recovered.
    runner.alive[_cp_pid(sup)] = False
    sup.tick(now=1.0)

    assert sup.state == "ready"
    assert dispatched.count("recovered") == 1

    # A subsequent healthy tick (no fresh recovery) must NOT re-dispatch recovered.
    sup.tick(now=2.0)
    assert dispatched.count("recovered") == 1


# ---------------------------------------------------------------------------
# Guard pre_child_start gate on a transmission (writer-capable) child
# ---------------------------------------------------------------------------


def test_pre_child_start_gates_transmission_child_on_blocked_guard() -> None:
    """A blocked guard verdict must stop the control-plane (writer-capable)
    child from starting -- it is never spawned."""
    guard = FakeGuard(guard_decision("blocked_probe_unavailable", "blocked_probe_unavailable"))
    runner = FakeRunner()
    sup = make_supervisor(guard=guard, runner=runner)
    # Bring postgres up so control_plane is dependency-eligible.
    assert sup.start_child("postgres").status == "started_ready"

    outcome = sup.start_child("control_plane")

    assert outcome.status == "guard_blocked"
    assert guard.pre_child_start_calls == 1
    assert "control_plane" not in runner.spawned_names


def test_pre_child_start_allows_transmission_child_when_guard_starts() -> None:
    guard = FakeGuard(guard_decision("start", None))
    runner = FakeRunner()
    sup = make_supervisor(guard=guard, runner=runner)
    sup.start_child("postgres")

    outcome = sup.start_child("control_plane")

    assert outcome.status == "started_ready"
    assert guard.pre_child_start_calls == 1
    assert "control_plane" in runner.spawned_names


def test_infra_children_do_not_call_the_guard() -> None:
    """postgres is not writer-capable -- its start never invokes the
    transmission guard gate."""
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(guard=guard)

    sup.start_child("postgres")

    assert guard.pre_child_start_calls == 0


# ---------------------------------------------------------------------------
# Drain-all (RAT-004)
# ---------------------------------------------------------------------------


def test_drain_all_sends_ctrl_break_to_control_plane() -> None:
    runner = FakeRunner()
    sup = make_supervisor(runner=runner)
    sup.start()
    cp_pid = next(h.pid for name, h in sup.handles().items() if name == "control_plane")
    # The control plane exits promptly on CTRL_BREAK (its lifespan drains).
    runner.alive[cp_pid] = False

    sup.graceful_stop()

    assert sup.state == "stopping"
    assert cp_pid in runner.ctrl_break_pids


def test_drain_all_closes_job_object_as_backstop_after_deadline() -> None:
    runner = FakeRunner()
    job_api = FakeJobApi()
    sup = make_supervisor(runner=runner, job_api=job_api)
    sup.start()
    cp_pid = next(h.pid for name, h in sup.handles().items() if name == "control_plane")
    # A hung control plane that never exits on CTRL_BREAK: the Job Object is
    # the backstop after the graceful deadline.
    runner.alive[cp_pid] = True

    sup.graceful_stop()

    assert cp_pid in runner.ctrl_break_pids
    assert job_api.closed is True


# ---------------------------------------------------------------------------
# Status snapshot + command handler shape (read tier for the pipe)
# ---------------------------------------------------------------------------


def test_status_snapshot_shape() -> None:
    sup = make_supervisor()
    sup.start()

    snap = sup.status_snapshot()

    assert isinstance(snap, StatusSnapshot)
    assert snap.state == "ready"
    assert snap.workers_permitted is True
    assert {c.name for c in snap.children} == {"postgres", "control_plane"}
    assert all(c.state == "ready" for c in snap.children)
    assert snap.guard_last_action == "start"
    assert snap.protocol_version == 1


def test_command_handler_status_returns_snapshot_dict() -> None:
    sup = make_supervisor()
    sup.start()

    result = sup.command_handler("status", {"cmd": "status", "v": 1})

    assert result["state"] == "ready"
    assert result["protocol_version"] == 1
    assert isinstance(result["children"], list)


def test_command_handler_version_returns_version_dict() -> None:
    sup = make_supervisor()

    result = sup.command_handler("version", {"cmd": "version", "v": 1})

    assert result["protocol_version"] == 1
    assert "version" in result


def test_runner_protocol_is_structural() -> None:
    """FakeRunner satisfies the ChildProcessRunner Protocol structurally."""
    runner: ChildProcessRunner = FakeRunner()
    assert runner is not None


# ---------------------------------------------------------------------------
# Wave-3: the reconciliation run() loop (closes design.md:56/60 F-REV-1)
# ---------------------------------------------------------------------------


class FakeStopEvent:
    """A threading.Event stand-in whose ``wait()`` returns False ``false_count``
    times (each a run-loop tick), then True (stop requested) -- so ``run()``
    exits deterministically after exactly ``false_count`` ticks, no real clock."""

    def __init__(self, *, false_count: int) -> None:
        self.false_count = false_count
        self.wait_calls = 0

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls += 1
        return self.wait_calls > self.false_count


def _cp_pid(sup: Supervisor) -> int:
    return next(h.pid for name, h in sup.handles().items() if name == "control_plane")


def test_run_boots_then_ticks_until_stop_set() -> None:
    """run() calls start() (D5/D6 boot to ready) and then ticks once per
    stop_event.wait()==False, exiting when the stop_event is set."""
    runner = FakeRunner()
    reader_calls = {"n": 0}

    def reader() -> str:
        reader_calls["n"] += 1
        return "free"

    sup = make_supervisor(runner=runner, interlock_reader=reader)
    stop = FakeStopEvent(false_count=3)

    sup.run(stop, poll_interval_seconds=0.0)  # type: ignore[arg-type]

    # Booted through the D6 order.
    assert runner.spawned_names == ["postgres", "control_plane"]
    assert sup.state == "ready"
    # Ran exactly three ticks (poll_interlock reads the interlock once per tick),
    # then the fourth wait() returned True and the loop exited.
    assert stop.wait_calls == 4
    # CC-WS5-001 reconcile: start() now polls+enforces the interlock ONCE before
    # the writer-capable control plane (boot-time fail-closed check), so the
    # reader is read once at boot plus once per tick: 1 + 3 = 4.
    assert reader_calls["n"] == 4


def test_tick_recovers_a_dead_child() -> None:
    """AC2: a child that left ready on a tick is detected (on_dependency_lost),
    counted (record_restart), and restarted (try_restart_child), recovering the
    supervisor to ready."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard)
    sup.start()
    assert sup.state == "ready"

    cp_pid = _cp_pid(sup)
    spawn_before = len(runner.spawned)
    guard_calls_before = guard.pre_child_start_calls
    runner.alive[cp_pid] = False  # the control plane dies

    sup.tick(now=100.0)

    # try_restart_child spawned a fresh, guard-gated control_plane...
    assert len(runner.spawned) == spawn_before + 1
    assert guard.pre_child_start_calls == guard_calls_before + 1
    assert _cp_pid(sup) != cp_pid
    # record_restart recorded exactly one restart in the D5 window...
    assert sup.status_snapshot().restart_count_window == 1
    # ...and readiness was re-established.
    assert sup.state == "ready"


def test_tick_fires_restart_storm_after_repeated_child_deaths() -> None:
    """AC3: killing the control plane on five successive ticks crosses the D5
    storm threshold (5/600s) -> demote to degraded + EXACTLY ONE alert."""
    runner = FakeRunner()
    outbox = FakeOutbox()
    sup = make_supervisor(runner=runner, outbox=outbox)
    sup.start()

    for i in range(5):
        runner.alive[_cp_pid(sup)] = False
        sup.tick(now=float(i))

    assert sup.status_snapshot().restart_count_window == 5
    assert sup.state == "degraded"
    assert len(outbox.fired) == 1


def test_tick_in_blocked_state_does_no_child_churn() -> None:
    """A blocked_* state owns transmission-halt; while the guard STILL blocks,
    tick must NOT recover children there (only ready/degraded reconcile child
    liveness). CC-WS5-012: the blocked-state guard reconciliation recovers ONLY
    on a start-authorizing verdict; a still-non-start verdict (here ``refuse``)
    holds the block and does no child churn, even for a dead child."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard)
    sup.start()  # boot to ready with the CP up (clear guard)
    guard.decision = guard_decision("refuse", "blocked_wsl_active")  # guard still blocks
    sup.force_state("blocked_wsl_active")
    runner.alive[_cp_pid(sup)] = False  # even a dead child must not be restarted
    spawn_before = len(runner.spawned)

    sup.tick(now=0.0)

    assert len(runner.spawned) == spawn_before
    assert sup.state == "blocked_wsl_active"


def test_reconcile_maintenance_idempotent_no_double_cp_spawn() -> None:
    """While the interlock is held, repeated ticks must not respawn the already-
    ready maintenance control plane (idempotent reconcile)."""
    runner = FakeRunner()
    reads = iter(["held", "held", "held"])
    sup = make_supervisor(
        runner=runner, health=maintenance_health, interlock_reader=lambda: next(reads)
    )
    sup.enter_maintenance()
    assert sup.state == "maintenance"
    assert runner.spawned_names.count("control_plane") == 1

    sup.tick(now=0.0)
    sup.tick(now=1.0)

    assert sup.state == "maintenance"
    assert runner.spawned_names.count("control_plane") == 1


def test_resume_to_serving_restarts_only_control_plane_not_infra() -> None:
    """F-REV-2 falsification (the reviewer's exact repro): after entering
    maintenance, the interlock held->free edge on a CLEAR guard verdict must
    resume to serving by restarting ONLY the control plane in normal mode --
    postgres stays alive+ready and is NOT respawned."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    reads = iter(["held", "free"])
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads),
    )

    result = sup.enter_maintenance()
    assert result.outcome == "ready"
    assert sup.state == "maintenance"

    def count(name: str) -> int:
        return runner.spawned_names.count(name)

    assert count("postgres") == 1
    assert count("control_plane") == 1

    # Tick 1: interlock reads held -> records the held edge, reconcile is a no-op.
    sup.tick(now=0.0)
    assert sup.state == "maintenance"
    assert count("control_plane") == 1

    # Tick 2: held->free edge with a clear verdict -> resume to serving.
    sup.tick(now=1.0)

    assert count("postgres") == 1  # infra NOT respawned
    assert count("control_plane") == 2  # restarted once, normal mode
    assert sup.state == "ready"
    assert sup.workers_permitted() is True


# ---------------------------------------------------------------------------
# CC-WS5-001 -- maintenance must never leave a NORMAL (writer-capable) control
# plane live, and must never duplicate-spawn the maintenance control plane.
# ---------------------------------------------------------------------------


def test_boot_held_interlock_starts_maintenance_cp_not_normal() -> None:
    """CC-WS5-001 (Codex CRITICAL): a boot-HELD interlock must NEVER boot a
    normal writer-capable control plane. start() polls+enforces the interlock
    BEFORE the writer child -> exactly ONE control-plane spawn, in MAINTENANCE
    mode, and the machine holds in ``maintenance``."""
    runner = FakeRunner()
    sup = make_supervisor(runner=runner, health=maintenance_health, interlock="held")

    sup.start()

    assert sup.state == "maintenance"
    cp_specs = [s for s in runner.spawned if s.name == "control_plane"]
    assert len(cp_specs) == 1  # exactly one CP spawned
    # ...and it is the READ-ONLY maintenance control plane, not the writer one.
    assert cp_specs[0].env.get("CIVICCAST_SUPERVISOR_MODE") == "maintenance"
    assert sup.workers_permitted() is False


def test_ready_to_held_replaces_normal_cp_with_maintenance_cp() -> None:
    """CC-WS5-001 (Codex CRITICAL): a ready NORMAL control plane whose interlock
    flips HELD must have its normal pid TERMINATED and replaced by a DISTINCT
    maintenance-mode CP pid; the machine holds in ``maintenance`` (writers
    gated)."""
    runner = FakeRunner()
    reads = iter(["free", "held", "held"])  # boot free (normal CP), then held
    sup = make_supervisor(
        runner=runner, health=maintenance_health, interlock_reader=lambda: next(reads)
    )

    sup.start()
    assert sup.state == "ready"
    normal_pid = _cp_pid(sup)

    sup.tick(now=0.0)  # interlock flips held -> maintenance; reconcile replaces CP

    assert sup.state == "maintenance"
    assert normal_pid in runner.terminated_pids  # the writer pid was terminated
    maint_pid = _cp_pid(sup)
    assert maint_pid != normal_pid  # a DISTINCT maintenance pid replaced it
    maint_spec = next(s for s in reversed(runner.spawned) if s.name == "control_plane")
    assert maint_spec.env.get("CIVICCAST_SUPERVISOR_MODE") == "maintenance"
    assert sup.workers_permitted() is False


def test_unattested_maintenance_cp_no_duplicate_spawn_over_ticks() -> None:
    """CC-WS5-001 (Codex CRITICAL): an unattested (never-ready) maintenance
    control plane must stay exactly ONE live handle over repeated held ticks --
    the old reconcile respawned it EVERY tick (unbounded duplicate control
    planes). normal_health never satisfies the maintenance attestation gate, so
    the CP is held ``starting`` and must be re-polled, never re-spawned."""
    runner = FakeRunner()
    sup = make_supervisor(runner=runner, health=normal_health, interlock_reader=lambda: "held")

    sup.enter_maintenance()
    assert sup.state == "maintenance"
    assert sup.child_state("control_plane") != "ready"  # unattested (fail-closed)
    assert runner.spawned_names.count("control_plane") == 1

    sup.tick(now=0.0)
    sup.tick(now=1.0)
    sup.tick(now=2.0)

    assert sup.state == "maintenance"
    assert runner.spawned_names.count("control_plane") == 1  # NO duplicate spawns
    live_cp = [h for name, h in sup.handles().items() if name == "control_plane"]
    assert len(live_cp) == 1  # exactly one live handle


# ---------------------------------------------------------------------------
# CC-WS5-002 -- the continuous dual-runtime guard must run WHILE serving and
# stop the writer on a mid-operation WSL activation / selector flip.
# ---------------------------------------------------------------------------

_GUARD_INTERVAL = SupervisorConfig().guard_interval_seconds


def test_midop_wsl_activation_blocks_and_stops_control_plane() -> None:
    """CC-WS5-002 (Codex CRITICAL): a ready supervisor whose guard seam flips
    start->refuse (WSL activated mid-operation) must, after >= guard_interval,
    drive ``blocked_wsl_active`` AND terminate the control-plane pid -- a
    controlled stop, NOT waiting for a child restart. Codex's exact repro (ticks
    with state stuck ``ready`` and evaluate_once never called) now fails."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"
    cp_pid = _cp_pid(sup)
    evals_before = guard.evaluate_once_calls

    # Mid-operation WSL activation: the raw guard now REFUSES (state_name is the
    # mid-op WSL-active relabel the supervisor routes on).
    guard.decision = guard_decision("refuse", "blocked_wsl_active")

    sup.tick(now=_GUARD_INTERVAL)

    assert guard.evaluate_once_calls == evals_before + 1  # continuous guard ran
    assert sup.state == "blocked_wsl_active"  # routed via guard_block_wsl
    assert cp_pid in runner.terminated_pids  # writer CP controlled-stopped
    assert "control_plane" not in sup.handles()  # handle dropped


def test_midop_wsl_activation_with_real_guard_shape_routes_on_action_not_state_name() -> None:
    """CC-WS5-002 fail-OPEN regression (hostile-review hardening): the REAL
    ``GuardMonitor.evaluate_once`` returns a mid-operation WSL flip as
    ``action="refuse", state_name=None`` -- the ``blocked_wsl_active`` relabel is
    applied ONLY inside ``GuardMonitor.run`` (``_mid_operation_decision``), which
    the supervisor does not use. ``_guard_block_event`` therefore MUST route on
    ``action`` (not ``state_name``): routing on ``state_name`` would raise on this
    real shape and crash the tick loop (a native writer keeps running while WSL is
    active = fail-OPEN). This pins that with the real ``state_name=None`` shape --
    the other WSL test uses a fake that populates ``state_name`` and would pass
    even under the crashing state_name-router, so it does not guard this."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"
    cp_pid = _cp_pid(sup)

    # The real raw-guard shape for a mid-op WSL activation: refuse, state_name None.
    guard.decision = guard_decision("refuse", None)

    sup.tick(now=_GUARD_INTERVAL)  # must NOT raise; must block + stop the writer

    assert sup.state == "blocked_wsl_active"  # routed via action, not state_name
    assert cp_pid in runner.terminated_pids  # writer controlled-stopped (not fail-open)
    assert "control_plane" not in sup.handles()


def test_midop_selector_flip_blocks_probe_unavailable_and_stops_writer() -> None:
    """CC-WS5-002: a selector flip surfacing ``blocked_probe_unavailable``
    likewise stops the writer and drives the probe-unavailable blocked state."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    cp_pid = _cp_pid(sup)

    guard.decision = guard_decision("blocked_probe_unavailable", "blocked_probe_unavailable")

    sup.tick(now=_GUARD_INTERVAL)

    assert sup.state == "blocked_probe_unavailable"
    assert cp_pid in runner.terminated_pids


def test_midop_guard_clear_while_serving_evaluates_but_does_not_block() -> None:
    """CC-WS5-002: while serving, the continuous guard IS evaluated (per the new
    cadence) but a clear (start) verdict is a no-op -- the CP keeps running and
    the machine stays ready."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    cp_pid = _cp_pid(sup)
    evals_before = guard.evaluate_once_calls

    sup.tick(now=_GUARD_INTERVAL)

    assert guard.evaluate_once_calls == evals_before + 1  # guard ran
    assert sup.state == "ready"  # clear verdict -> no block
    assert cp_pid not in runner.terminated_pids
    assert _cp_pid(sup) == cp_pid  # same CP still live


def test_continuous_guard_is_throttled_to_guard_interval() -> None:
    """CC-WS5-002 integration caution: the tick guard-check is THROTTLED to
    guard_interval_seconds -- many ticks within one interval evaluate the guard
    at most once; crossing the interval evaluates it again."""
    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    evals_before = guard.evaluate_once_calls

    sup.tick(now=0.0)  # first serving check -> evaluates
    sup.tick(now=1.0)  # within interval -> skipped
    sup.tick(now=_GUARD_INTERVAL - 0.001)  # still within interval -> skipped

    assert guard.evaluate_once_calls == evals_before + 1

    sup.tick(now=_GUARD_INTERVAL)  # crosses the interval -> evaluates again

    assert guard.evaluate_once_calls == evals_before + 2


# ---------------------------------------------------------------------------
# CC-WS5-012 -- the maintenance-release FALSE-CLEAR wedge. The held->freed edge
# must route on the guard ACTION (mirroring _guard_block_event), not on
# state_name: the REAL guard returns a held/mid-op WSL block as
# action="never_start"/"refuse" with state_name=None, which the old state_name
# router false-cleared to interlock_freed_clear -> starting -> permanent wedge.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,state_name,expected_event",
    [
        # A real WSL/never_start block: state_name is None on the raw verdict.
        ("never_start", None, "interlock_freed_blocked_wsl"),
        ("refuse", None, "interlock_freed_blocked_wsl"),
        ("refuse_instruct", None, "interlock_freed_blocked_wsl"),
        # The probe-unavailable verdict carries its own state_name.
        ("blocked_probe_unavailable", "blocked_probe_unavailable", "interlock_freed_blocked_probe"),
        # Only a start-authorizing action clears to starting.
        ("start", None, "interlock_freed_clear"),
        ("start_degraded", None, "interlock_freed_clear"),
    ],
)
def test_ccws5_012_interlock_freed_event_routes_on_action_not_state_name(
    action: str, state_name: str | None, expected_event: str
) -> None:
    """CC-WS5-012 routing table (the auditor's): _interlock_freed_event must
    route on decision.action, EXACTLY mirroring _guard_block_event. never_start/
    None and refuse/None (the real raw WSL-block shapes, state_name=None) route
    to the WSL block -- NOT the old false-clear (state_name is None -> clear)."""

    event = _interlock_freed_event(guard_decision(action, state_name))
    assert event == expected_event


def test_ccws5_012_maintenance_release_never_start_routes_blocked_wsl_not_false_clear() -> None:
    """CC-WS5-012 (Codex MAJOR) -- the auditor's deterministic wedge repro.

    Drive to maintenance; the interlock frees while the REAL guard returns the
    held/mid-op WSL block shape (action="never_start", state_name=None). The
    freed edge must route on ACTION -> blocked_wsl_active (the maintenance CP is
    controlled-stopped, no writer spawned), NOT false-clear to starting. The old
    state_name router mapped None -> interlock_freed_clear -> starting, where
    _resume_to_serving terminated the maintenance CP, start_child correctly
    withheld the writer (control_plane left 'stopped'), and _needs_restart
    returned False for 'stopped' -> the machine wedged in 'starting' forever.

    Then the guard clears and the interlock re-frees clear -> _resume_to_serving
    restarts the normal control plane -> ready (recovery, never wedged)."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("never_start", None))
    reads = iter(["held", "free", "held", "free"])
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads),
    )

    sup.enter_maintenance()
    assert sup.state == "maintenance"
    maint_pid = _cp_pid(sup)
    spawns_before = len(runner.spawned)

    # Tick 1: interlock reads held (records the held edge; reconcile no-op).
    sup.tick(now=0.0)
    assert sup.state == "maintenance"

    # Tick 2: held->free edge, guard still returns never_start/None.
    sup.tick(now=1.0)

    # Routed on action -> the WSL block, NOT a false clear to starting.
    assert sup.state == "blocked_wsl_active"
    # The read-only maintenance CP is controlled-stopped; no writer spawned.
    assert maint_pid in runner.terminated_pids
    assert "control_plane" not in sup.handles()
    assert len(runner.spawned) == spawns_before

    # Recovery: the guard clears; a re-held then re-freed interlock resumes.
    guard.decision = guard_decision("start", None)
    sup.tick(now=2.0)  # held -> re-enter maintenance, relaunch the maintenance CP
    assert sup.state == "maintenance"
    sup.tick(now=3.0)  # free + clear verdict -> resume to serving

    assert sup.state == "ready"
    assert sup.child_state("control_plane") == "ready"
    assert sup.workers_permitted() is True


def test_ccws5_012_resume_withheld_start_is_restartable_not_wedged() -> None:
    """CC-WS5-012 restartability (auditor acceptance): when _resume_to_serving's
    normal-mode start is guard-WITHHELD, control_plane must be left 'starting'
    (no live handle) -- NOT 'stopped'. 'stopped' makes _needs_restart return
    False, so the withheld child is never retried and the machine wedges in
    'starting'. 'starting' with no handle makes _needs_restart True, so a later
    serving/starting tick retries it once the guard clears."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("never_start", None))  # withholds the normal start
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    # Bring postgres/maintenance-CP up, then take the resume edge directly.
    sup.enter_maintenance()
    assert sup.child_state("control_plane") == "ready"
    sup.force_state("starting")  # the interlock_freed_clear edge already advanced here
    sup._resume_to_serving()

    # The guard withheld the writer: left restartable ('starting'), never wedged.
    assert sup.child_state("control_plane") == "starting"
    assert "control_plane" not in sup.handles()
    assert sup._needs_restart("control_plane") is True

    # A later tick with the guard cleared retries the withheld start -> ready.
    guard.decision = guard_decision("start", None)
    sup.tick(now=100.0)

    assert sup.child_state("control_plane") == "ready"
    assert sup.state == "ready"


# ---------------------------------------------------------------------------
# CC-WS5-013 -- composition tests against a REAL runtime_guard.GuardMonitor.
# The 002 regression uses a FakeGuard; these build an ACTUAL GuardMonitor with
# fake zero-arg seams so its real evaluate_once() decision-shape is pinned
# against drift, on BOTH the continuous-guard path (_guard_block_event) and the
# maintenance-release path (_interlock_freed_event).
# ---------------------------------------------------------------------------


def _guard_clock() -> datetime:
    return datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


def _clear_a1() -> A1Result:
    return A1Result(live_process="negative", run_entry="negative", detail="clear")


def _clear_a2() -> A2Result:
    return A2Result(status="negative", detail="inactive")


def _clear_a3() -> A3Result:
    return A3Result(status="acquired", detail="owned")


def _free_interlock() -> InterlockRead:
    return InterlockRead(status="free", record=None, detail="absent")


def _make_real_guard(
    *,
    selector: Callable[[], SelectorRead],
    a1: Callable[[], A1Result] | None = None,
    a2: Callable[[], A2Result] | None = None,
    mutex: Callable[[], A3Result] | None = None,
    wsl_install_detector: Callable[[], bool | None] | None = None,
) -> GuardMonitor:
    """An ACTUAL GuardMonitor over fake zero-arg seams (no Windows, no I/O)."""
    return GuardMonitor(
        selector_reader=selector,
        a1_probe=a1 or _clear_a1,
        a2_probe=a2 or _clear_a2,
        mutex=mutex or _clear_a3,
        interlock_reader=_free_interlock,
        wsl_install_detector=wsl_install_detector or (lambda: False),
        clock=_guard_clock,
    )


def _selector(value: str, *, ok: bool = True) -> Callable[[], SelectorRead]:
    return lambda: SelectorRead(ok=ok, value=value if ok else None, detail=f"selector={value}")


def _a1_keeper_live() -> A1Result:
    return A1Result(live_process="positive", run_entry="negative", detail="live keeper")


def test_ccws5_013_real_guard_never_start_shape_and_routing() -> None:
    """CC-WS5-013: a real GuardMonitor whose selector reads 'wsl' yields the
    exact raw shape action='never_start', state_name=None -- and BOTH routers
    send it to the WSL block (continuous: guard_block_wsl; release:
    interlock_freed_blocked_wsl)."""
    guard = _make_real_guard(selector=_selector("wsl"))
    decision = guard.evaluate_once()

    assert decision.action == "never_start"
    assert decision.state_name is None  # the drift the state_name router mis-routed
    assert _guard_block_event(decision) == "guard_block_wsl"
    assert _interlock_freed_event(decision) == "interlock_freed_blocked_wsl"


def test_ccws5_013_real_guard_refuse_shape_and_routing() -> None:
    """CC-WS5-013: a real GuardMonitor with A1 keeper activity yields
    action='refuse', state_name=None -- BOTH routers send it to the WSL block."""
    guard = _make_real_guard(selector=_selector("native"), a1=_a1_keeper_live)
    decision = guard.evaluate_once()

    assert decision.action == "refuse"
    assert decision.state_name is None
    assert _guard_block_event(decision) == "guard_block_wsl"
    assert _interlock_freed_event(decision) == "interlock_freed_blocked_wsl"


def test_ccws5_013_real_guard_blocked_probe_shape_and_routing() -> None:
    """CC-WS5-013: a real GuardMonitor with an unreadable selector yields
    action='blocked_probe_unavailable' with a matching state_name -- BOTH
    routers send it to the probe block."""
    guard = _make_real_guard(selector=_selector("native", ok=False))
    decision = guard.evaluate_once()

    assert decision.action == "blocked_probe_unavailable"
    assert decision.state_name == "blocked_probe_unavailable"
    assert _guard_block_event(decision) == "guard_block_probe"
    assert _interlock_freed_event(decision) == "interlock_freed_blocked_probe"


def test_ccws5_013_real_guard_clear_shape_and_release_routing() -> None:
    """CC-WS5-013: an all-clear real GuardMonitor yields action='start',
    state_name=None -- the release path routes it to interlock_freed_clear."""
    guard = _make_real_guard(selector=_selector("native"))
    decision = guard.evaluate_once()

    assert decision.action == "start"
    assert decision.state_name is None
    assert _interlock_freed_event(decision) == "interlock_freed_clear"


def test_ccws5_013_real_guard_drives_supervisor_continuous_block() -> None:
    """CC-WS5-013 composition (continuous path): a REAL GuardMonitor wired as
    the supervisor's guard. Boot clear (selector native), then flip the selector
    to 'wsl' mid-operation -> the continuous serving tick routes the real
    never_start/None verdict to blocked_wsl_active and controlled-stops the
    writer (would be fail-OPEN if _guard_block_event routed on state_name)."""
    runner = FakeRunner()
    selector_value = {"v": "native"}
    guard = _make_real_guard(
        selector=lambda: SelectorRead(
            ok=True, value=selector_value["v"], detail=f"selector={selector_value['v']}"
        )
    )
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"
    cp_pid = _cp_pid(sup)

    selector_value["v"] = "wsl"  # WSL activates mid-operation
    sup.tick(now=_GUARD_INTERVAL)

    assert sup.state == "blocked_wsl_active"
    assert cp_pid in runner.terminated_pids
    assert "control_plane" not in sup.handles()


def test_ccws5_013_real_guard_drives_supervisor_maintenance_release_block() -> None:
    """CC-WS5-013 composition (maintenance-release path): a REAL GuardMonitor
    reading selector 'wsl' (never_start/None). At the maintenance held->freed
    edge on_interlock_freed's real evaluate_once must route on action ->
    blocked_wsl_active, NOT false-clear to starting (the CC-WS5-012 wedge)."""
    runner = FakeRunner()
    guard = _make_real_guard(selector=_selector("wsl"))
    reads = iter(["held", "free"])
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads),
    )

    sup.enter_maintenance()
    assert sup.state == "maintenance"
    maint_pid = _cp_pid(sup)

    sup.tick(now=0.0)  # held edge
    sup.tick(now=1.0)  # held->free edge, real never_start verdict

    assert sup.state == "blocked_wsl_active"
    assert maint_pid in runner.terminated_pids


# ---------------------------------------------------------------------------
# CC-WS5-010 -- status_snapshot() must be a lock-free CONSISTENT snapshot. The
# old membership-test-then-index (name in self._handles ... self._handles[name])
# raced a concurrent handle removal between the two into a KeyError, which the
# CommandQueue turned into a transient status:error.
# ---------------------------------------------------------------------------


class _DeletingOnContains(dict):  # type: ignore[type-arg]
    """A _handles stand-in that simulates a concurrent removal between the
    membership test and the index: __contains__ reports the target present ONCE
    and deletes it as a side effect, so a following self._handles[target] raises
    KeyError (the exact F-REV-5 interleaving)."""

    def __init__(self, *args: object, target: str, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._target = target
        self._armed = True

    def __contains__(self, key: object) -> bool:
        present = super().__contains__(key)
        if key == self._target and self._armed and present:
            self._armed = False
            del self[key]  # concurrent removal fires between test and index
            return True
        return present


def test_ccws5_010_status_snapshot_survives_concurrent_handle_removal() -> None:
    """CC-WS5-010: status_snapshot must not raise KeyError when a handle is
    removed between the membership test and the index. The lock-free
    copy-then-build snapshots self._handles into a local ONCE, so a concurrent
    mutation cannot tear a membership/index pair. The pre-fix build
    (name in self._handles then self._handles[name]) raised KeyError here."""

    runner = FakeRunner()
    sup = make_supervisor(runner=runner, health=maintenance_health)
    sup.start()
    assert sup.state == "ready"

    # Swap in a _handles whose __contains__ deletes control_plane mid-read.
    hostile = _DeletingOnContains(sup.handles(), target="control_plane")
    sup._handles = hostile  # type: ignore[assignment]

    snapshot = sup.status_snapshot()  # must NOT raise KeyError

    assert isinstance(snapshot, StatusSnapshot)
    # Every child is present in the snapshot exactly once, consistently.
    names = [c.name for c in snapshot.children]
    assert names == ["postgres", "control_plane"]
    cp_view = next(c for c in snapshot.children if c.name == "control_plane")
    assert cp_view.pid is None or isinstance(cp_view.pid, int)


# ---------------------------------------------------------------------------
# CC-WS5-003 -- durable PostgreSQL postmaster ownership. ``pg_ctl start -w`` is a
# SHORT-LIVED launcher that self-exits once the postmaster is up; the durable
# postmaster's pid lives in <data_dir>/postmaster.pid. The supervisor must
# CONTAIN + MONITOR the postmaster, not the launcher.
# ---------------------------------------------------------------------------


def test_ccws5_003_postgres_swaps_launcher_for_postmaster_and_assigns_postmaster() -> None:
    """PROCESS IDENTITY: postgres readiness resolves the postmaster pid P, opens a
    durable handle to P, assigns P (NOT the launcher L) to the Job Object, and
    swaps handles["postgres"] to the P handle. Pre-fix, the launcher L was the
    handle assigned + monitored (the postmaster was never contained)."""

    runner = FakeRunner()
    job_api = FakeJobApi()
    postmaster_pid = 4242  # P, the durable postmaster (distinct from launcher L)
    sup = make_supervisor(
        runner=runner, job_api=job_api, postmaster_pid_reader=lambda: postmaster_pid
    )

    outcome = sup.start_child("postgres")

    launcher_pid = 1001  # FakeRunner hands the first spawn (the pg_ctl launcher) pid 1001
    assert outcome.status == "started_ready"
    # open_existing(P) was called with the postmaster pid, exactly once.
    assert runner.opened_existing_pids == [postmaster_pid]
    # The Job Object contained P, NOT the launcher L.
    assert postmaster_pid in job_api.assigned_pids
    assert launcher_pid not in job_api.assigned_pids
    # The monitored handle is the postmaster; postgres is ready; outcome pid is P.
    assert sup.handles()["postgres"].pid == postmaster_pid
    assert sup.child_state("postgres") == "ready"
    assert outcome.pid == postmaster_pid


def test_ccws5_003_no_spurious_relaunch_when_launcher_exits_but_postmaster_alive() -> None:
    """THE STORM REPRO: with the postmaster handle P alive but the pg_ctl -w
    launcher L self-exited (its normal behaviour), three ticks must NOT relaunch
    postgres (spawn count stays 1) and must not cascade dependent restarts -- the
    monitored handle is the durable postmaster, not the self-exiting launcher.
    Pre-fix, L was monitored, so L's self-exit read as a death and relaunched
    postgres every tick."""

    runner = FakeRunner()
    postmaster_pid = 55555
    sup = make_supervisor(runner=runner, postmaster_pid_reader=lambda: postmaster_pid)
    sup.start()
    assert sup.state == "ready"
    # The monitored postgres handle is the postmaster, not the launcher.
    assert sup.handles()["postgres"].pid == postmaster_pid

    cp_pid = sup.handles()["control_plane"].pid

    # The pg_ctl -w launcher (first spawn, pid 1001) self-exits after the
    # postmaster is up. The postmaster (55555) stays alive.
    launcher_pid = 1001
    assert launcher_pid in runner.alive
    runner.alive[launcher_pid] = False

    for t in (0.0, 1.0, 2.0):
        sup.tick(now=t)

    assert runner.spawned_names.count("postgres") == 1, (
        "launcher self-exit must NOT relaunch postgres"
    )
    assert sup.state == "ready"
    assert sup.child_state("postgres") == "ready"
    # No dependent-restart cascade: control_plane was never terminated.
    assert cp_pid not in runner.terminated_pids
    assert sup.handles()["control_plane"].pid == cp_pid


def test_ccws5_003_pidfile_unresolvable_fails_closed_no_false_ready() -> None:
    """FAIL CLOSED: an unresolvable postmaster.pid (reader -> None) must NOT accept
    postgres ready while only the self-exiting launcher is contained. start_child
    returns not_ready + child_state failed, never opens a bogus handle, and full
    bring-up HALTS (no children_ready, no control_plane start)."""

    runner = FakeRunner()
    sup = make_supervisor(runner=runner, postmaster_pid_reader=lambda: None)

    outcome = sup.start_child("postgres")

    assert outcome.status == "not_ready"
    assert sup.child_state("postgres") == "failed"
    assert runner.opened_existing_pids == []  # never opened a handle on an unresolved pid

    # Full start() must halt bring-up on the fail-closed postgres.
    runner2 = FakeRunner()
    sup2 = make_supervisor(runner=runner2, postmaster_pid_reader=lambda: None)
    sup2.start()

    assert sup2.state != "ready"
    assert sup2.child_state("postgres") == "failed"
    assert "control_plane" not in runner2.spawned_names


def test_ccws5_003_real_postmaster_death_recovers_with_new_swap_and_rebinds_dependents() -> None:
    """RECOVERY: when the durable postmaster P dies, a tick detects the death
    (on_dependency_lost), restarts postgres (fresh launcher + a NEW postmaster
    swap P'), and rebinds the downstream children (D6) to the replacement. The
    postmaster handle -- not the launcher -- is what liveness monitoring watches."""

    runner = FakeRunner()
    postmaster_pids = iter([1111, 2222])
    sup = make_supervisor(runner=runner, postmaster_pid_reader=lambda: next(postmaster_pids))
    sup.start()
    assert sup.state == "ready"
    assert sup.handles()["postgres"].pid == 1111
    cp_pid = sup.handles()["control_plane"].pid

    # The real postmaster dies.
    runner.alive[1111] = False
    sup.tick(now=0.0)

    assert sup.state == "ready"
    # A fresh postmaster was resolved, opened, and swapped in.
    assert runner.opened_existing_pids == [1111, 2222]
    assert sup.handles()["postgres"].pid == 2222
    # Dependents rebound in D6 order (terminated + fresh pids).
    assert cp_pid in runner.terminated_pids
    assert sup.handles()["control_plane"].pid != cp_pid


# ---------------------------------------------------------------------------
# CC-WS5-007 part 2: restart_control_plane (the admin ``restart`` verb action)
# ---------------------------------------------------------------------------


def test_restart_control_plane_terminates_the_live_cp_and_restarts_it() -> None:
    """The admin ``restart`` verb's core action: a controlled restart of the
    control plane terminates the live CP handle, drops it, and re-runs the
    guard-gated start_child, leaving a FRESH ready CP (no handle accumulation)."""

    runner = FakeRunner()
    sup = make_supervisor(guard=FakeGuard(guard_decision("start", None)), runner=runner)
    sup.start()
    assert sup.state == "ready"
    cp_before = sup.handles()["control_plane"].pid

    outcome = sup.restart_control_plane()

    assert outcome.status == "started_ready"
    assert cp_before in runner.terminated_pids
    assert sup.handles()["control_plane"].pid != cp_before
    assert sup.child_state("control_plane") == "ready"


def test_restart_control_plane_is_guard_gated() -> None:
    """FALSIFICATION: a restart the D9 pre-start guard withholds does NOT bring a
    writer-capable CP back -- it returns ``guard_blocked`` and leaves no CP
    handle, so the admin router reports 'refused', never a false 'applied'."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(guard=guard, runner=runner)
    sup.start()
    cp_before = sup.handles()["control_plane"].pid
    # The guard flips to a WSL-active block between boot and the restart.
    guard.decision = guard_decision("refuse", "blocked_wsl_active")

    outcome = sup.restart_control_plane()

    assert outcome.status == "guard_blocked"
    assert cp_before in runner.terminated_pids
    assert sup.handles().get("control_plane") is None


def test_restart_control_plane_only_touches_the_control_plane() -> None:
    """Infra (postgres) is untouched by a control-plane restart -- its
    handle and pid are unchanged."""

    runner = FakeRunner()
    sup = make_supervisor(guard=FakeGuard(guard_decision("start", None)), runner=runner)
    sup.start()
    pg_before = sup.handles()["postgres"].pid

    sup.restart_control_plane()

    assert sup.handles()["postgres"].pid == pg_before
    assert pg_before not in runner.terminated_pids


# ---------------------------------------------------------------------------
# CC-WS5-012 (round 4) -- the blocked-state RECOVERY LIVENESS wedge. A block that
# clears must RE-EVALUATE the guard while blocked and recover WITHOUT a second
# interlock cycle. The round-3 fix corrected the block ROUTING (action, not
# state_name); this pins that a cleared block does not WEDGE the machine.
# ---------------------------------------------------------------------------


def test_ccws5_012_blocked_wsl_clears_and_recovers_without_second_interlock_cycle() -> None:
    """CC-WS5-012 (round 4, auditor repro): after a maintenance release into
    blocked_wsl_active (real never_start/None), flipping the guard to a
    start-authorizing verdict with the interlock CONTINUOUSLY FREE must, after
    >= guard_interval, drive one tick that dispatches guard_clear -> starting and
    RECOVERS to ready -- NO second held->free interlock cycle. Pre-fix, tick did
    no guard reconciliation in a blocked state, so the machine stayed
    blocked_wsl_active forever (the control plane stopped)."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("never_start", None))
    reads = iter(["held", "free"])  # exactly ONE interlock cycle, then stays free
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads, "free"),
    )

    sup.enter_maintenance()
    assert sup.state == "maintenance"

    sup.tick(now=0.0)  # reads held -> maintenance reconcile
    assert sup.state == "maintenance"
    sup.tick(now=1.0)  # reads free -> on_interlock_freed -> blocked_wsl_active
    assert sup.state == "blocked_wsl_active"
    assert "control_plane" not in sup.handles()

    # The WSL condition clears. NO second interlock cycle is supplied.
    guard.decision = guard_decision("start", None)
    spawns_before = len(runner.spawned)

    # A tick within the throttle interval does NOT re-evaluate -> stays blocked.
    sup.tick(now=1.0 + _GUARD_INTERVAL - 0.001)
    assert sup.state == "blocked_wsl_active"

    # A tick at/after the interval reconciles the guard while blocked: the
    # start-authorizing verdict dispatches guard_clear -> starting -> recovers.
    sup.tick(now=1.0 + _GUARD_INTERVAL)

    assert sup.state == "ready"
    assert sup.child_state("control_plane") == "ready"
    assert sup.workers_permitted() is True
    assert len(runner.spawned) > spawns_before  # the writer CP was re-spawned


def test_ccws5_012_blocked_probe_clears_and_recovers_without_second_interlock_cycle() -> None:
    """CC-WS5-012 (round 4): the same blocked-state recovery on the OTHER blocked
    kind -- blocked_probe_unavailable -> guard_clear -> starting -> ready."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("blocked_probe_unavailable", "blocked_probe_unavailable"))
    reads = iter(["held", "free"])
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads, "free"),
    )

    sup.enter_maintenance()
    sup.tick(now=0.0)
    sup.tick(now=1.0)
    assert sup.state == "blocked_probe_unavailable"
    assert "control_plane" not in sup.handles()

    guard.decision = guard_decision("start", None)
    sup.tick(now=1.0 + _GUARD_INTERVAL)

    assert sup.state == "ready"
    assert sup.child_state("control_plane") == "ready"
    assert sup.workers_permitted() is True


def test_ccws5_012_blocked_guard_reconcile_is_throttled_to_guard_interval() -> None:
    """CC-WS5-012 (round 4) throttle: the blocked-state guard reconciliation
    reuses the SAME throttle as the serving-state continuous guard
    (guard_interval_seconds) -- many ticks within one interval evaluate the guard
    at most once; crossing the interval evaluates it again. A still-non-start
    verdict never clears the block."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"

    # Enter the blocked state via the continuous serving guard (mid-op WSL flip);
    # this eval sets the throttle epoch at now == _GUARD_INTERVAL.
    guard.decision = guard_decision("refuse", "blocked_wsl_active")
    sup.tick(now=_GUARD_INTERVAL)
    assert sup.state == "blocked_wsl_active"
    evals_after_block = guard.evaluate_once_calls

    # Ticks within the same interval do NOT re-evaluate the blocked guard.
    sup.tick(now=_GUARD_INTERVAL + 1.0)
    sup.tick(now=_GUARD_INTERVAL + 2.0)
    assert guard.evaluate_once_calls == evals_after_block

    # Crossing the interval evaluates once more (still refuse -> stays blocked).
    sup.tick(now=2 * _GUARD_INTERVAL)
    assert guard.evaluate_once_calls == evals_after_block + 1
    assert sup.state == "blocked_wsl_active"


def test_ccws5_012_blocked_reconcile_reroutes_shape_but_never_false_clears() -> None:
    """CC-WS5-012 (round 4): while blocked, a still-non-start verdict of a
    DIFFERENT shape re-routes the block (wsl -> probe) but NEVER clears -- only a
    start-authorizing verdict releases to starting."""

    runner = FakeRunner()
    guard = FakeGuard(guard_decision("start", None))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"
    guard.decision = guard_decision("refuse", "blocked_wsl_active")
    sup.tick(now=_GUARD_INTERVAL)  # WSL flip -> blocked_wsl_active
    assert sup.state == "blocked_wsl_active"

    # The block SHAPE changes to probe-unavailable (still a non-start verdict).
    guard.decision = guard_decision("blocked_probe_unavailable", "blocked_probe_unavailable")
    sup.tick(now=2 * _GUARD_INTERVAL)

    assert sup.state == "blocked_probe_unavailable"  # re-routed, not cleared
    assert sup.workers_permitted() is False


# ---------------------------------------------------------------------------
# CC-WS5-013 (round 4) -- the real-GuardMonitor periodic-CLEAR proof on BOTH the
# serving path and the new blocked-state reconciliation path. The round-3
# real-guard tests pinned the BLOCK shapes; these pin the CLEAR shape composed
# end-to-end through a tick.
# ---------------------------------------------------------------------------


def test_ccws5_013_real_guard_clear_drives_serving_tick_stays_ready() -> None:
    """CC-WS5-013 (serving CLEAR path): a REAL GuardMonitor returning a
    start-authorizing verdict (selector native, all clear) drives a serving tick
    that STAYS ready -- the continuous guard evaluates but does not block, and
    the control plane is never controlled-stopped."""

    runner = FakeRunner()
    guard = _make_real_guard(selector=_selector("native"))
    sup = make_supervisor(runner=runner, guard=guard, health=maintenance_health)

    sup.start()
    assert sup.state == "ready"
    cp_pid = _cp_pid(sup)

    sup.tick(now=_GUARD_INTERVAL)

    assert sup.state == "ready"
    assert cp_pid not in runner.terminated_pids
    assert _cp_pid(sup) == cp_pid


def test_ccws5_013_real_guard_clear_drives_blocked_reconcile_recovery() -> None:
    """CC-WS5-013 (blocked CLEAR path): a REAL GuardMonitor whose selector flips
    wsl->native (never_start -> start). At the maintenance-release edge the WSL
    read blocks (blocked_wsl_active); after the selector clears, a blocked tick
    reconciles the REAL guard, dispatches guard_clear -> starting, and recovers
    to ready with the writer CP back up -- WITHOUT a second interlock cycle."""

    runner = FakeRunner()
    selector_value = {"v": "wsl"}
    guard = _make_real_guard(
        selector=lambda: SelectorRead(
            ok=True, value=selector_value["v"], detail=f"selector={selector_value['v']}"
        )
    )
    reads = iter(["held", "free"])
    sup = make_supervisor(
        runner=runner,
        guard=guard,
        health=maintenance_health,
        interlock_reader=lambda: next(reads, "free"),
    )

    sup.enter_maintenance()
    sup.tick(now=0.0)  # held
    sup.tick(now=1.0)  # free -> real never_start -> blocked_wsl_active
    assert sup.state == "blocked_wsl_active"

    selector_value["v"] = "native"  # WSL deactivates; the real guard now clears
    sup.tick(now=1.0 + _GUARD_INTERVAL)

    assert sup.state == "ready"
    assert sup.child_state("control_plane") == "ready"
    assert sup.workers_permitted() is True


# ---------------------------------------------------------------------------
# CC-WS5-015 -- the postmaster attachment (open_existing / assign_child) must be
# inside an exception boundary: a real OpenProcess / AssignProcessToJobObject
# fault must FAIL CLOSED (postgres not_ready, retryable) rather than escape
# start_child -> tick -> run and EXIT supervision, and must never leave a
# swapped-but-uncontained postmaster handle.
# ---------------------------------------------------------------------------


class _OpenExistingFaultRunner(FakeRunner):
    """A FakeRunner whose ``open_existing`` raises while ``fault`` is True -- the
    real ``win32api.OpenProcess`` Access-denied fault CC-WS5-015 must contain."""

    fault: bool = True

    def open_existing(self, pid: int) -> FakeHandle:
        if self.fault:
            raise OSError(5, "Access is denied opening the postmaster")
        return super().open_existing(pid)


class _AssignFaultJobApi(FakeJobApi):
    """A FakeJobApi whose ``assign_process`` raises for the postmaster pid -- the
    real ``AssignProcessToJobObject`` fault CC-WS5-015 must contain + roll back."""

    def __init__(self, *, raise_for_pid: int) -> None:
        super().__init__()
        self._raise_for_pid = raise_for_pid

    def assign_process(self, handle: object, pid: int) -> None:
        if pid == self._raise_for_pid:
            raise OSError(5, "AssignProcessToJobObject failed for the postmaster")
        super().assign_process(handle, pid)


def test_ccws5_015_postmaster_open_fault_fails_closed_not_ready_and_retryable() -> None:
    """CC-WS5-015: a real OpenProcess fault on the postmaster must NOT escape
    start_child. It fails CLOSED (postgres not_ready + failed, no bogus handle
    swapped in), and a later reconcile tick retries once the fault clears."""

    runner = _OpenExistingFaultRunner()
    postmaster_pid = 4242
    sup = make_supervisor(runner=runner, postmaster_pid_reader=lambda: postmaster_pid)

    outcome = sup.start_child("postgres")  # must NOT raise

    assert outcome.status == "not_ready"
    assert sup.child_state("postgres") == "failed"
    # No postmaster handle was swapped in without containment.
    assert postmaster_pid not in [h.pid for h in sup.handles().values()]
    assert runner.opened_existing_pids == []  # the raising open recorded nothing

    # Observable + retryable: clear the fault; a later reconcile tick retries.
    runner.fault = False
    sup.tick(now=100.0)  # state is 'starting' (initial) -> _recover_dead_children

    assert sup.child_state("postgres") == "ready"
    assert sup.handles()["postgres"].pid == postmaster_pid


def test_ccws5_015_postmaster_assign_fault_fails_closed_and_rolls_back() -> None:
    """CC-WS5-015: a real Job-assign fault on the postmaster must NOT escape and
    must NOT leave a swapped-but-uncontained handle -- the swap is committed only
    AFTER assign_child succeeds, and a failed assign rolls back (terminates) the
    opened handle so nothing is tracked uncontained and nothing leaks."""

    postmaster_pid = 4242
    runner = FakeRunner()
    job_api = _AssignFaultJobApi(raise_for_pid=postmaster_pid)
    sup = make_supervisor(
        runner=runner, job_api=job_api, postmaster_pid_reader=lambda: postmaster_pid
    )

    outcome = sup.start_child("postgres")  # must NOT raise

    assert outcome.status == "not_ready"
    assert sup.child_state("postgres") == "failed"
    # The postmaster handle was opened but NEVER committed as the tracked handle.
    assert postmaster_pid not in [h.pid for h in sup.handles().values()]
    # Orphan-leak fix: the rollback asks postgres to tear ITSELF down (pg_ctl
    # stop reaps the background workers + shared memory) BEFORE the
    # single-pid TerminateProcess fallback. Terminate alone strands the
    # workers, which is the field "pre-existing shared memory block is still
    # in use" poisoning every later start attempt.
    assert postmaster_pid in runner.graceful_stopped_pids
    # Force fallback still ran after the graceful stop (no leak either way).
    assert postmaster_pid in runner.terminated_pids
    # The Job Object never recorded the postmaster (assign raised before commit).
    assert postmaster_pid not in job_api.assigned_pids


class _SequencedRunner(FakeRunner):
    """Records the ORDER of stop-path calls -- the orphan-leak fix's property
    is sequencing (postgres's own stop BEFORE the force fallback), which the
    per-list records on FakeRunner cannot pin."""

    def __init__(self) -> None:
        super().__init__()
        self.call_sequence: list[tuple[str, int]] = []

    def graceful_stop(self, handle: FakeHandle) -> object:
        self.call_sequence.append(("graceful_stop", handle.pid))
        return super().graceful_stop(handle)

    def terminate(self, handle: FakeHandle) -> None:
        self.call_sequence.append(("terminate", handle.pid))
        super().terminate(handle)


def test_postmaster_assign_fault_rollback_orders_graceful_stop_before_terminate() -> None:
    """Orphan-leak fix, load-bearing property = ORDER: the containment-fault
    rollback must issue postgres's own stop (which makes the postmaster reap
    its background workers and release shared memory) BEFORE the single-pid
    TerminateProcess fallback. Terminate-first kills the postmaster and
    strands the workers -- the field defect this fix closes.

    FALSIFICATION: against the pre-fix tree the postmaster's sequence is
    ``[("terminate", pid)]`` only, so this assertion fails."""

    postmaster_pid = 4243
    runner = _SequencedRunner()
    job_api = _AssignFaultJobApi(raise_for_pid=postmaster_pid)
    sup = make_supervisor(
        runner=runner, job_api=job_api, postmaster_pid_reader=lambda: postmaster_pid
    )

    outcome = sup.start_child("postgres")  # must NOT raise

    assert outcome.status == "not_ready"
    events = [event for event in runner.call_sequence if event[1] == postmaster_pid]
    assert events == [("graceful_stop", postmaster_pid), ("terminate", postmaster_pid)]


def test_postmaster_assign_fault_logs_containment_forensics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The fault-site diagnostic: winerror + job-membership facts are logged AT
    the fault (while the postmaster is alive), so the next field reproduction
    of the reinstall ACCESS_DENIED loop proves -- not infers -- whether the
    postmaster sits in a foreign job or our own surviving one.

    FALSIFICATION: against the pre-fix tree no forensics line is logged at all
    (the except block terminated silently), so the length assertion fails."""

    postmaster_pid = 4244
    runner = FakeRunner()
    job_api = _AssignFaultJobApi(raise_for_pid=postmaster_pid)
    sup = make_supervisor(
        runner=runner, job_api=job_api, postmaster_pid_reader=lambda: postmaster_pid
    )

    with caplog.at_level(logging.WARNING, logger="civiccast.native.supervisor.core"):
        sup.start_child("postgres")

    forensics = [
        record.getMessage()
        for record in caplog.records
        if "containment fault forensics" in record.getMessage()
    ]
    assert len(forensics) == 1
    message = forensics[0]
    assert f"(pid {postmaster_pid})" in message
    # OSError(5, ...) carries no ``winerror`` attribute; the dual extraction
    # (attribute, then args[0]) must surface the 5 -- the real
    # ``pywintypes.error`` path carries the attribute directly.
    assert "winerror=5" in message
    # The membership facts that separate foreign-job from own-job inheritance.
    assert "in_this_job=False" in message
    assert "named_job=" in message


# ---------------------------------------------------------------------------
# F1 (BLOCKER, 2026-07-31): a stop request must interrupt an IN-FLIGHT
# start()/tick(), not only the gap between ticks
# ---------------------------------------------------------------------------
#
# The service layer's run loop is ``while not stop_event.wait(1.0): tick()``,
# and ``request_stop`` only sets that Event. Nothing inside start()/tick() read
# it, so ONE iteration could chain four readiness budgets (postgres 60s + nats
# 30s + control_plane 30s + ollama 60s) with the stop already requested -- up to
# ~180s before the stop chain could even begin, which is longer than the 150s
# stop watchdog. The watchdog then fired MID-CHAIN and force-exited the host,
# closing the Job Object and hard-killing postgres into an unclean cluster.
#
# The fix is the ``should_abort`` seam, checked between children and inside
# every readiness poll. These tests pin BOTH: that an in-flight iteration ends
# within one probe attempt, and that no further child is started after a stop.


def test_f1_start_child_readiness_poll_aborts_on_a_stop_request_mid_poll() -> None:
    """The unit at the heart of F1: a start whose readiness probe is failing
    must END when a stop is requested DURING the poll -- after the in-flight
    probe attempt, not after the child's full 60s budget.

    FALSIFICATION: against the pre-fix tree (no ``should_abort``) this poll runs
    to the budget, so the elapsed fake time is >= 60s and the status is
    ``not_ready``; both assertions below fail."""

    clock = FakeClock()
    stopping = {"now": False}
    attempts = {"n": 0}

    def probe_then_stop() -> bool:
        # One probe ATTEMPT costs 2 fake seconds, and the stop request lands
        # DURING it -- the hardest case: the seam must be re-checked after
        # check() returns, not only at the top of the loop.
        attempts["n"] += 1
        clock.t += 2.0
        stopping["now"] = True
        return False

    sup = make_supervisor(clock=clock, should_abort=lambda: stopping["now"])
    sup._postgres_probe = probe_then_stop  # type: ignore[assignment]

    outcome = sup.start_child("postgres")

    assert outcome.status == "aborted", (
        "a start cut short by a stop request is NOT a readiness failure: reporting "
        "not_ready arms the D5 backoff and logs a WARNING for a stop we asked for"
    )
    assert attempts["n"] == 1, f"the abort must cost at most ONE probe attempt; got {attempts['n']}"
    assert clock.t == 2.0, (
        f"the in-flight iteration must end within one probe attempt (2.0s here), "
        f"not the 60s postgres readiness budget; elapsed {clock.t}s"
    )
    # Nothing about the child's health was learned -> no state churn, and the
    # handle stays tracked so the service's stop chain can stop what was spawned.
    assert sup.child_state("postgres") == "starting"
    assert "postgres" in sup.handles()


def test_f1_start_aborts_between_children_when_a_stop_is_requested() -> None:
    """``start()`` must check the stop seam BETWEEN children. Before F1, a stop
    arriving while postgres was coming up still cost nats's 30s budget and the
    control plane's 30s budget before ``run()`` could reach the stop chain."""

    runner = FakeRunner()
    stopping = {"now": False}
    sup = make_supervisor(runner=runner, should_abort=lambda: stopping["now"])

    original_start_child = sup.start_child

    def start_child_then_stop(name: str, **kwargs: object) -> object:
        outcome = original_start_child(name, **kwargs)  # type: ignore[arg-type]
        if name == "postgres":
            stopping["now"] = True  # the stop lands right after postgres is up
        return outcome

    sup.start_child = start_child_then_stop  # type: ignore[assignment,method-assign]
    sup.start()

    assert runner.spawned_names == ["postgres"], (
        "no child may be STARTED after a stop was requested -- every one of them "
        "would only have to be stopped again, at the cost of its readiness budget "
        f"on the stop's critical path; spawned {runner.spawned_names}"
    )
    assert sup.state == "starting"  # never reached children_ready


def test_f1_recovery_aborts_between_children_when_a_stop_is_requested() -> None:
    """The tick loop's recovery path is the OTHER place one iteration chains
    readiness budgets (each ``_attempt_restart`` runs a full ``start_child``).
    A stop must be honoured between children there too."""

    runner = FakeRunner()
    stopping = {"now": True}  # a stop is already pending when the tick begins
    sup = make_supervisor(runner=runner, should_abort=lambda: stopping["now"])

    # Boot cleanly first (no stop pending), then request the stop.
    stopping["now"] = False
    sup.start()
    assert sup.state == "ready"
    spawned_at_boot = list(runner.spawned_names)

    # Every child dies at once, then the stop lands.
    for handle in sup.handles().values():
        runner.alive[handle.pid] = False
    stopping["now"] = True

    sup.tick(now=100.0)

    assert runner.spawned_names == spawned_at_boot, (
        "a tick that begins after a stop request must start nothing; it would "
        f"only spawn children the stop chain must immediately stop again; got "
        f"{runner.spawned_names}"
    )


def test_f1_default_supervisor_never_aborts() -> None:
    """The seam defaults to "no stop requested, ever", so every caller that does
    not wire it (the upgrade tooling, most tests) keeps the exact pre-F1
    behaviour -- a bring-up that completes."""

    runner = FakeRunner()
    sup = make_supervisor(runner=runner)  # no should_abort

    sup.start()

    assert runner.spawned_names == ["postgres", "control_plane"]
    assert sup.state == "ready"


def test_chain_i_a_degraded_guard_verdict_starts_the_child_and_warns_with_probe_and_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Chain I: ``start_degraded`` AUTHORIZES the start (it is already in
    ``_GUARD_START_ACTIONS``), and the probe the guard could not trust must be
    recorded as a structured WARNING rather than vanishing into a silent
    success. This is the line an R7-shaped station will now emit instead of
    "start withheld by guard".
    """

    decision = GuardDecision(
        action="start_degraded",
        named_probe="A2",
        message=(
            "probe-degraded: A2 in-distro service status unreadable (wsl.exe timed out after "
            "5.0s); the explicitly written selector ActiveRuntime=native is the authority basis "
            "for this start; starting with reduced confidence, re-probe per D5."
        ),
        retry_seconds=None,
        state_name=None,
    )
    sup = make_supervisor(guard=FakeGuard(decision), runner=FakeRunner())

    with caplog.at_level("WARNING", logger=_CORE_LOGGER_NAME):
        sup.start()

    assert sup.state != "starting", "a degraded verdict must not withhold the station"
    degraded = [
        r for r in caplog.records if "started with a degraded guard verdict" in r.getMessage()
    ]
    assert len(degraded) == 1, "a degraded start must be logged exactly once per spawn attempt"
    message = degraded[0].getMessage()
    assert degraded[0].levelname == "WARNING"
    assert "child control_plane" in message
    assert "action=start_degraded" in message
    assert "named_probe=A2" in message
    assert "A2 in-distro service status unreadable" in message
    assert "wsl.exe timed out after 5.0s" in message
    # It must NOT masquerade as the withhold line the tester greps for.
    assert not [r for r in caplog.records if "start withheld by guard" in r.getMessage()]


def test_chain_i_a_plain_start_verdict_logs_no_degraded_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Negative control: the degraded WARNING must fire ONLY for a degraded
    verdict, so its presence in a real log is evidence and not noise."""

    sup = make_supervisor(guard=FakeGuard(guard_decision("start", None)), runner=FakeRunner())

    with caplog.at_level("WARNING", logger=_CORE_LOGGER_NAME):
        sup.start()

    assert not [
        r for r in caplog.records if "started with a degraded guard verdict" in r.getMessage()
    ]


class _ForeignJobApi(_AssignFaultJobApi):
    """assign_process raises ACCESS_DENIED for the postmaster while the pid is
    provably a member of SOME (foreign) job -- TESTER4's field state."""

    def __init__(self, *, raise_for_pid: int) -> None:
        super().__init__(raise_for_pid=raise_for_pid)
        self.any_job_pids = {raise_for_pid}


def test_postmaster_foreign_job_membership_is_accepted_and_postgres_reaches_ready() -> None:
    """CC-PG-JOB end-to-end at the core seam: the postmaster's ACCESS_DENIED
    with proven foreign-job membership is ACCEPTED at the postgres call site
    (the only opt-in), the swap commits, postgres reports started_ready, and
    the rollback (graceful stop + terminate) never runs.

    FALSIFICATION: against the acceptance-less tree this outcome is
    ``not_ready`` with the postmaster terminated -- both assertions below
    fail."""

    postmaster_pid = 4245
    runner = FakeRunner()
    job_api = _ForeignJobApi(raise_for_pid=postmaster_pid)
    sup = make_supervisor(
        runner=runner, job_api=job_api, postmaster_pid_reader=lambda: postmaster_pid
    )

    outcome = sup.start_child("postgres")

    assert outcome.status == "started_ready"
    assert sup.child_state("postgres") == "ready"
    # The tracked handle IS the postmaster (swap committed).
    assert sup.handles()["postgres"].pid == postmaster_pid
    # No rollback ran: postgres was neither gracefully stopped nor terminated.
    assert postmaster_pid not in runner.graceful_stopped_pids
    assert postmaster_pid not in runner.terminated_pids
