# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure (any-OS) tests for civiccast.native.supervisor.service.

The service orchestration is CI-testable on Linux: the supervisor, the child
runner, and the clock/sleep are all injected fakes, so the graceful stop-chain
ORDERING (control-plane drained first, with its CTRL_BREAK graceful action) and
the per-child 15s-deadline-then-TerminateProcess logic (D5 + RAT-004), the
concrete runner's per-child process-group + graceful-stop-action branching, the
rotating-log configuration, and the singleton construction all run with no Win32
import, no subprocess, and no socket. The real singleton mutex SDDL readback and
the ServiceFramework class shape are proven against real Win32 in
test_supervisor_service_win.py.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from civiccast.native.supervisor import config as config_mod
from civiccast.native.supervisor.children import ChildSpec
from civiccast.native.supervisor.config import (
    DISPLAY_NAME,
    EVENT_LOG_SOURCE,
    SERVICE_NAME,
    SINGLETON_MUTEX_NAME,
    SINGLETON_MUTEX_SDDL,
    SupervisorConfig,
)
from civiccast.native.supervisor.service import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    SVC_STOP_WATCHDOG_ENV_VAR,
    SVC_STOP_WATCHDOG_EXIT_CODE,
    SVC_STOP_WATCHDOG_SECONDS,
    StopWatchdog,
    SupervisorService,
    Win32ChildProcessRunner,
    _DurableRotatingFileHandler,
    _file_backed_popen_factory,
    build_production_service,
    build_singleton_mutex,
    build_stop_watchdog,
    child_log_path,
    configure_logging,
)
from civiccast.native.win_probes import RuntimeOwnerMutex

# ---------------------------------------------------------------------------
# Fakes (no Win32, no subprocess, no socket)
# ---------------------------------------------------------------------------


@dataclass
class FakeHandle:
    pid: int
    kind: str = "argv"  # the graceful-stop action this child would perform


@dataclass
class FakeRunner:
    """Records the ORDER of every graceful-stop and terminate so the stop-chain
    ordering assertions are exact. ``alive`` maps pid -> liveness; a test drives
    the deadline behaviour deterministically by flipping it."""

    events: list[tuple[str, int]] = field(default_factory=list)
    alive: dict[int, bool] = field(default_factory=dict)

    def graceful_stop(self, handle: FakeHandle) -> str:
        self.events.append(("graceful", handle.pid))
        return handle.kind

    def is_alive(self, handle: FakeHandle) -> bool:
        return self.alive.get(handle.pid, False)

    def terminate(self, handle: FakeHandle) -> None:
        self.events.append(("terminate", handle.pid))
        self.alive[handle.pid] = False


@dataclass
class FakeSupervisor:
    """Stands in for core.Supervisor: hands the service a fixed handle map and
    records that graceful_stop() (state transition + Job Object backstop) ran."""

    child_handles: dict[str, FakeHandle]
    started: bool = False
    graceful_stop_calls: int = 0
    run_calls: int = 0
    last_stop_event: object | None = None
    state: str = "starting"

    def start(self) -> None:
        self.started = True
        self.state = "ready"

    def run(self, stop_event: object, *, poll_interval_seconds: float = 1.0) -> None:
        # Mirrors core.Supervisor.run: boot then (in the real thing) tick until
        # the stop event is set. The fake boots and returns -- the run loop
        # itself is proven in test_supervisor_core.py.
        self.run_calls += 1
        self.last_stop_event = stop_event
        self.start()

    def handles(self) -> dict[str, FakeHandle]:
        return dict(self.child_handles)

    def graceful_stop(self) -> None:
        self.graceful_stop_calls += 1
        self.state = "stopping"


class FakeClock:
    """Monotonic fake clock; sleep(dt) advances it so the 15s deadline logic
    runs in microseconds with no real waiting."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt


def _handles() -> dict[str, FakeHandle]:
    return {
        "postgres": FakeHandle(pid=101, kind="argv"),
        "nats": FakeHandle(pid=102, kind="argv"),
        "control_plane": FakeHandle(pid=103, kind="ctrl_break_event"),
    }


def make_service(
    *,
    handles: dict[str, FakeHandle],
    runner: FakeRunner,
    clock: FakeClock | None = None,
    config: SupervisorConfig | None = None,
    control_pipe: object | None = None,
    event_log: object | None = None,
) -> tuple[SupervisorService, FakeSupervisor]:
    clock = clock or FakeClock()
    supervisor = FakeSupervisor(child_handles=handles)
    kwargs: dict[str, object] = {}
    if event_log is not None:
        kwargs["event_log"] = event_log
    service = SupervisorService(
        supervisor=supervisor,  # type: ignore[arg-type]
        runner=runner,
        config=config or SupervisorConfig(),
        clock=clock.now,
        sleep=clock.sleep,
        control_pipe=control_pipe,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )
    return service, supervisor


# ---------------------------------------------------------------------------
# Identity constants (owner-approved 2026-07-20)
# ---------------------------------------------------------------------------


def test_identity_constants_have_the_ratified_values() -> None:
    assert SERVICE_NAME == "CivicCastSupervisor"
    assert DISPLAY_NAME == "CivicCast Native Supervisor"
    assert EVENT_LOG_SOURCE == "CivicCastSupervisor"
    assert SINGLETON_MUTEX_NAME == r"Global\CivicCastSupervisorSingleton"
    # Same restrictive SDDL as WS4's runtime-owner mutex: SYSTEM + Administrators.
    assert SINGLETON_MUTEX_SDDL == "D:P(A;;GA;;;SY)(A;;GA;;;BA)"
    # And it is literally re-used from runtime_guard's constant, not re-typed.
    assert SINGLETON_MUTEX_SDDL == config_mod.MUTEX_SDDL


# ---------------------------------------------------------------------------
# Singleton mutex construction (REUSES RuntimeOwnerMutex)
# ---------------------------------------------------------------------------


def test_build_singleton_mutex_reuses_runtime_owner_mutex_with_singleton_identity() -> None:
    mutex = build_singleton_mutex()

    assert isinstance(mutex, RuntimeOwnerMutex)
    # Constructed with the singleton identity + the restrictive SDDL (no
    # hand-rolled CreateMutex path; the real SDDL readback is a win-test).
    assert mutex._name == SINGLETON_MUTEX_NAME
    assert mutex._sddl == SINGLETON_MUTEX_SDDL


# ---------------------------------------------------------------------------
# Graceful stop chain: ordering (RAT-004) + per-child deadline/terminate (D5)
# ---------------------------------------------------------------------------


def test_stop_chain_drains_control_plane_first_with_its_ctrl_break_action() -> None:
    """RAT-004: the control-plane child is stopped FIRST and its graceful action
    is CTRL_BREAK (ctrl_break_event), so its uvicorn lifespan runs
    stop_all_channels before any infra child is touched."""

    runner = FakeRunner(alive={101: False, 102: False, 103: False})
    service, supervisor = make_service(handles=_handles(), runner=runner)

    results = service.graceful_stop_all()

    # The very first runner action is the control-plane graceful stop...
    assert runner.events[0] == ("graceful", 103)
    # ...and it was the CTRL_BREAK drain action.
    assert results[0].name == "control_plane"
    assert results[0].graceful_kind == "ctrl_break_event"
    # State transition + Job Object backstop ran exactly once, after the chain.
    assert supervisor.graceful_stop_calls == 1


def test_stop_chain_terminates_a_child_that_overruns_its_deadline() -> None:
    """D5 graceful-stop: a child still alive at the 15s deadline is force-stopped
    with TerminateProcess; one that exits in time is not."""

    handles = {
        "postgres": FakeHandle(pid=201, kind="argv"),  # exits promptly
        "nats": FakeHandle(pid=202, kind="argv"),  # hangs -> terminated
        "control_plane": FakeHandle(pid=203, kind="ctrl_break_event"),  # drains + exits
    }
    runner = FakeRunner(alive={201: False, 202: True, 203: False})
    service, _ = make_service(handles=handles, runner=runner)

    results = service.graceful_stop_all()

    by_name = {r.name: r for r in results}
    assert by_name["control_plane"].outcome == "exited"
    assert by_name["control_plane"].graceful_kind == "ctrl_break_event"
    assert by_name["postgres"].outcome == "exited"
    assert by_name["nats"].outcome == "terminated"
    # The hung nats child was actually TerminateProcess'd.
    assert ("terminate", 202) in runner.events
    # Neither the prompt-exit control plane nor postgres was terminated.
    assert ("terminate", 201) not in runner.events
    assert ("terminate", 203) not in runner.events


def test_stop_chain_waits_exactly_up_to_the_configured_deadline() -> None:
    """The deadline is config.graceful_stop_deadline_seconds (15s default): a
    child alive right up to the boundary is polled, not terminated early."""

    handles = {"control_plane": FakeHandle(pid=301, kind="ctrl_break_event")}
    runner = FakeRunner(alive={301: True})  # never exits on its own
    clock = FakeClock()
    config = SupervisorConfig(graceful_stop_deadline_seconds=15.0)
    service, _ = make_service(handles=handles, runner=runner, clock=clock, config=config)

    results = service.graceful_stop_all()

    assert results[0].outcome == "terminated"
    # sleep(1.0) advanced the clock in 1s steps until >= the 15s deadline.
    assert clock.t >= 15.0
    assert ("terminate", 301) in runner.events


def test_stop_chain_skips_children_without_a_live_handle() -> None:
    """A child that was never started (no handle) is skipped, not crashed on."""

    handles = {"control_plane": FakeHandle(pid=401, kind="ctrl_break_event")}
    runner = FakeRunner(alive={401: False})
    service, _ = make_service(handles=handles, runner=runner)

    results = service.graceful_stop_all()

    assert [r.name for r in results] == ["control_plane"]


def test_stop_chain_stops_children_in_reverse_startup_order() -> None:
    """Children are stopped control_plane -> nats -> postgres (reverse of the D6
    startup order), so dependents stop before the infrastructure they use."""

    handles = {
        "postgres": FakeHandle(pid=501, kind="argv"),
        "nats": FakeHandle(pid=502, kind="argv"),
        "control_plane": FakeHandle(pid=503, kind="ctrl_break_event"),
    }
    # All hang so every child is terminated, giving a clean order signal.
    runner = FakeRunner(alive={501: True, 502: True, 503: True})
    service, _ = make_service(handles=handles, runner=runner)

    results = service.graceful_stop_all()

    assert [r.name for r in results] == ["control_plane", "nats", "postgres"]
    graceful_order = [pid for kind, pid in runner.events if kind == "graceful"]
    assert graceful_order == [503, 502, 501]
    terminated_order = [pid for kind, pid in runner.events if kind == "terminate"]
    assert terminated_order == [503, 502, 501]


# ---------------------------------------------------------------------------
# run(): bring up, block on stop, then drain
# ---------------------------------------------------------------------------


def test_run_starts_then_drains_when_stop_requested() -> None:
    handles = {"control_plane": FakeHandle(pid=601, kind="ctrl_break_event")}
    runner = FakeRunner(alive={601: False})
    service, supervisor = make_service(handles=handles, runner=runner)
    # Pre-arm the stop so run() does not block the test.
    service.request_stop()

    service.run()

    assert supervisor.started is True
    assert supervisor.graceful_stop_calls == 1


def test_run_drives_supervisor_run_then_graceful_stop_all() -> None:
    """The service run loop delegates the supervision loop to
    ``Supervisor.run(stop_event)`` (design.md:60) and then runs the graceful
    stop chain -- it no longer bare-``start()``s and idles."""
    handles = {"control_plane": FakeHandle(pid=651, kind="ctrl_break_event")}
    runner = FakeRunner(alive={651: False})
    service, supervisor = make_service(handles=handles, runner=runner)
    service.request_stop()

    service.run()

    # Supervisor.run drove the loop (passed the service's own stop event)...
    assert supervisor.run_calls == 1
    assert supervisor.last_stop_event is service._stop_event
    # ...and the graceful stop chain ran afterwards.
    assert supervisor.graceful_stop_calls == 1


@dataclass
class FakeControlPipe:
    """Records the D7 control-pipe standup/teardown so the service run path's
    open-before / close-after wiring is asserted without real Win32."""

    opened: int = 0
    closed: int = 0
    open_before_close: bool = True

    def open(self) -> object:
        self.opened += 1
        return None

    def close(self) -> None:
        self.closed += 1
        if self.opened == 0:
            self.open_before_close = False


def test_run_opens_the_control_pipe_and_closes_it_on_stop() -> None:
    """D7: the control pipe is stood up before the supervision loop and closed
    on the stop path."""
    handles = {"control_plane": FakeHandle(pid=661, kind="ctrl_break_event")}
    runner = FakeRunner(alive={661: False})
    pipe = FakeControlPipe()
    service, _ = make_service(handles=handles, runner=runner, control_pipe=pipe)
    service.request_stop()

    service.run()

    assert pipe.opened == 1
    assert pipe.closed == 1
    assert pipe.open_before_close is True


def test_control_pipe_open_creates_pipe_and_starts_queue_close_tears_down() -> None:
    """The _ControlPipe lifecycle: open() starts the command queue and creates
    the named pipe; close() closes the pipe handle and stops the queue. Proven
    with fakes (no Win32), which is the lifecycle logic this build unit owns."""
    from civiccast.native.supervisor.service import _ControlPipe

    @dataclass
    class _FakeQueue:
        started: int = 0
        stopped: int = 0

        def start(self) -> None:
            self.started += 1

        def stop(self, *, timeout: float | None = 5.0) -> None:
            self.stopped += 1

    @dataclass
    class _FakeCreateResult:
        ok: bool = True
        degraded: bool = False
        detail: str = "created"

    @dataclass
    class _FakeServer:
        created: int = 0
        closed: int = 0
        accept_calls: int = 0

        def create(self) -> _FakeCreateResult:
            self.created += 1
            return _FakeCreateResult()

        def accept_and_serve_one(self) -> None:
            self.accept_calls += 1
            # Block the accept thread on nothing: return immediately but the
            # loop only continues while _running, so one pass is enough.

        def close(self) -> None:
            self.closed += 1

    queue = _FakeQueue()
    server = _FakeServer()
    pipe = _ControlPipe(server=server, command_queue=queue)  # type: ignore[arg-type]

    result = pipe.open()
    assert result.ok is True
    assert server.created == 1
    assert queue.started == 1

    pipe.close()
    assert server.closed == 1
    assert queue.stopped == 1


def test_build_control_pipe_wires_command_handler_to_the_named_pipe() -> None:
    """build_control_pipe assembles a real PipeServer on the D7 pipe name with a
    CommandQueue bound to the supervisor's command_handler -- constructed without
    touching Win32 (create() is only called at open() time, on Windows)."""
    from civiccast.native.supervisor.config import CONTROL_PIPE_NAME
    from civiccast.native.supervisor.pipe_server import CommandQueue, PipeServer
    from civiccast.native.supervisor.service import _ControlPipe, build_control_pipe

    calls: list[tuple[str, dict[str, object]]] = []

    def handler(command: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append((command, payload))
        return {"ok": True}

    pipe = build_control_pipe(handler, name=CONTROL_PIPE_NAME)  # type: ignore[arg-type]

    assert isinstance(pipe, _ControlPipe)
    assert isinstance(pipe._server, PipeServer)
    assert pipe._server._name == CONTROL_PIPE_NAME
    assert isinstance(pipe._queue, CommandQueue)
    # The queue is wired to the supplied handler (drive it directly to prove it).
    assert pipe._queue.submit("status", {"cmd": "status", "v": 1}) == {"ok": True}
    assert calls == [("status", {"cmd": "status", "v": 1})]
    pipe._queue.stop()


# ---------------------------------------------------------------------------
# Concrete runner: process-group branching + per-child graceful-stop dispatch
# ---------------------------------------------------------------------------


def _spec(name: str, *, new_process_group: bool, kind: str, argv_template: list[str]) -> ChildSpec:
    return ChildSpec(
        name=name,  # type: ignore[arg-type]
        argv=["exe"],
        new_process_group=new_process_group,
        graceful_stop_kind=kind,  # type: ignore[arg-type]
        graceful_stop_argv_template=argv_template,
        graceful_stop_deadline_seconds=15.0,
        readiness_budget_seconds=1.0,
    )


def _pg_spec() -> ChildSpec:
    return _spec(
        "postgres",
        new_process_group=False,
        kind="argv",
        argv_template=["pg_ctl", "stop", "-m", "fast"],
    )


def _nats_spec() -> ChildSpec:
    return _spec(
        "nats",
        new_process_group=False,
        kind="argv",
        argv_template=["nats", "--signal", "ldm={pid}"],
    )


def _cp_spec() -> ChildSpec:
    return _spec("control_plane", new_process_group=True, kind="ctrl_break_event", argv_template=[])


@dataclass
class FakePopen:
    pid: int
    poll_result: object | None = None
    terminated: bool = False

    def poll(self) -> object | None:
        return self.poll_result

    def terminate(self) -> None:
        self.terminated = True


def test_runner_gives_only_the_control_plane_its_own_process_group() -> None:
    """RAT-004 depends on the control-plane child living in its OWN process group
    (per spec.new_process_group -- the authoritative source, not a name guess);
    infra children stay in the default group."""

    seen: list[tuple[str, bool]] = []
    pids = iter(range(700, 800))

    def fake_factory(spec: ChildSpec, new_process_group: bool) -> FakePopen:
        seen.append((spec.name, new_process_group))
        return FakePopen(pid=next(pids))

    runner = Win32ChildProcessRunner(popen_factory=fake_factory, ctrl_break_sender=lambda _p: None)

    runner.spawn(_pg_spec())
    runner.spawn(_nats_spec())
    runner.spawn(_cp_spec())

    assert seen == [("postgres", False), ("nats", False), ("control_plane", True)]


def test_runner_graceful_stop_ctrl_breaks_the_control_plane() -> None:
    """The control-plane child's graceful action is a CTRL_BREAK to its group --
    NOT a stop command."""

    ctrl_break_pids: list[int] = []
    stop_commands: list[list[str]] = []
    runner = Win32ChildProcessRunner(
        popen_factory=lambda _spec, _grp: FakePopen(pid=808),
        ctrl_break_sender=ctrl_break_pids.append,
        stop_command_runner=stop_commands.append,
    )
    handle = runner.spawn(_cp_spec())

    kind = runner.graceful_stop(handle)

    assert kind == "ctrl_break_event"
    assert ctrl_break_pids == [808]
    assert stop_commands == []  # no stop command for the control plane


def test_runner_ctrl_break_is_tolerant_of_an_already_gone_process() -> None:
    """A control plane that already exited (spawn/stop race, or the redundant
    re-drain from core.graceful_stop) makes GenerateConsoleCtrlEvent raise
    OSError; the runner must swallow it so the stop path never crashes -- the
    D5 deadline + TerminateProcess and the Job Object backstop still apply."""

    def raising_sender(_pid: int) -> None:
        raise OSError("[WinError 87] the process group no longer exists")

    runner = Win32ChildProcessRunner(
        popen_factory=lambda _spec, _grp: FakePopen(pid=811),
        ctrl_break_sender=raising_sender,
    )
    handle = runner.spawn(_cp_spec())

    # Must NOT raise (neither via graceful_stop nor the protocol send_ctrl_break).
    assert runner.graceful_stop(handle) == "ctrl_break_event"
    runner.send_ctrl_break(handle)


def test_runner_graceful_stop_runs_the_argv_command_for_infra_children() -> None:
    """postgres/nats get a command-based graceful stop (pg_ctl fast stop / nats
    lame-duck), with nats's ``{pid}`` token substituted for the live pid."""

    ctrl_break_pids: list[int] = []
    stop_commands: list[list[str]] = []
    runner = Win32ChildProcessRunner(
        popen_factory=lambda _spec, _grp: FakePopen(pid=909),
        ctrl_break_sender=ctrl_break_pids.append,
        stop_command_runner=stop_commands.append,
    )

    pg_kind = runner.graceful_stop(runner.spawn(_pg_spec()))
    nats_kind = runner.graceful_stop(runner.spawn(_nats_spec()))

    assert pg_kind == "argv"
    assert nats_kind == "argv"
    assert ctrl_break_pids == []  # infra children are NOT ctrl-broken
    assert stop_commands[0] == ["pg_ctl", "stop", "-m", "fast"]
    # nats's {pid} token is substituted with the live child pid (909).
    assert stop_commands[1] == ["nats", "--signal", "ldm=909"]


def test_runner_is_alive_reflects_poll_and_terminate() -> None:
    proc = FakePopen(pid=850, poll_result=None)  # None == still running
    runner = Win32ChildProcessRunner(popen_factory=lambda _spec, _grp: proc)
    handle = runner.spawn(_cp_spec())

    assert runner.is_alive(handle) is True
    runner.terminate(handle)
    assert proc.terminated is True

    proc.poll_result = 0  # exited with code 0
    assert runner.is_alive(handle) is False


def test_g4b_default_stop_command_runner_warns_on_nonzero_returncode_with_output_tail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """G4(b): before this fix, the stop command's subprocess result was
    discarded entirely (``subprocess.run(argv, check=False, timeout=10)``,
    return value never read) -- a FAILED stop command looked IDENTICAL, in
    every log, to a working one. Reproduced for real: nats's own
    ``--signal ldm=<pid>`` locally returns exit code 1 with "Access is
    denied" against the real pack-cache ``nats-server.exe`` binary. The
    runner must now capture the returncode and log a WARNING carrying the
    output tail on a nonzero exit."""

    import civiccast.native.supervisor.service as service_module

    argv = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.write('g4-stop-failure-marker\\n'); sys.exit(7)",
    ]

    with caplog.at_level("WARNING", logger=service_module.LOGGER_NAME):
        service_module._default_stop_command_runner(argv)

    warnings = [r for r in caplog.records if "stop command" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "exited 7" in message
    assert "g4-stop-failure-marker" in message


def test_g4b_default_stop_command_runner_is_silent_on_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A successful stop command (returncode 0) must NOT log a warning --
    only a genuine failure is diagnostic-worthy (G2's once-per-reason
    discipline: never noise on the happy path)."""

    import civiccast.native.supervisor.service as service_module

    argv = [sys.executable, "-c", "pass"]

    with caplog.at_level("WARNING", logger=service_module.LOGGER_NAME):
        service_module._default_stop_command_runner(argv)

    warnings = [r for r in caplog.records if "stop command" in r.getMessage()]
    assert warnings == []


def test_f4_stop_command_runner_is_not_held_by_a_grandchild_inheriting_its_output() -> None:
    """F4 (2026-07-31): the stop-command runner used
    ``subprocess.run(capture_output=True, timeout=10)``. Pipe capture means
    ``communicate()`` must read to EOF -- which needs EVERY inherited write-end
    closed, not just the direct child's -- and on the ``TimeoutExpired`` path
    ``subprocess.run`` does ``kill()`` and then an UNTIMED ``communicate()``.
    Both of this product's stop commands leave a live grandchild holding those
    handles (``pg_ctl`` starts the postmaster; nats's ``--signal`` re-execs), so
    the documented 10s bound could become an unbounded wait -- ON the stop
    chain, inside the stop watchdog's budget, which is exactly what the
    watchdog then force-exited (killing postgres uncleanly).

    Here a stop command exits IMMEDIATELY but leaves a grandchild alive for 15s
    holding its inherited stdout/stderr. The runner must return as soon as the
    command itself exits.

    FALSIFICATION: against the pipe-based implementation this call takes ~15s
    (10s to TimeoutExpired, then the untimed communicate() blocking until the
    grandchild finally exits) AND raises; the elapsed-time assertion below
    fails."""

    import civiccast.native.supervisor.service as service_module

    argv = [
        sys.executable,
        "-c",
        (
            "import subprocess, sys; "
            "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)']); "
            "sys.exit(0)"
        ),
    ]

    started = time.monotonic()
    service_module._default_stop_command_runner(argv)  # must not raise
    elapsed = time.monotonic() - started

    assert elapsed < 8.0, (
        f"the stop command exited immediately, so the runner must return "
        f"immediately -- a live grandchild holding an inherited output handle "
        f"must not extend it (took {elapsed:.1f}s)"
    )


# ---------------------------------------------------------------------------
# Logging config + per-child log paths
# ---------------------------------------------------------------------------


def test_configure_logging_creates_rotating_supervisor_log(tmp_path: Path) -> None:
    logger = configure_logging(log_root=tmp_path)

    handlers = [h for h in logger.handlers if hasattr(h, "maxBytes")]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == LOG_MAX_BYTES == 10 * 1024 * 1024  # type: ignore[attr-defined]
    assert handler.backupCount == LOG_BACKUP_COUNT == 10  # type: ignore[attr-defined]
    assert (tmp_path / "supervisor.log").exists()


def test_configure_logging_is_idempotent_no_handler_stacking(tmp_path: Path) -> None:
    configure_logging(log_root=tmp_path)
    logger = configure_logging(log_root=tmp_path)

    rotating = [h for h in logger.handlers if hasattr(h, "maxBytes")]
    assert len(rotating) == 1  # not stacked across two calls


def test_child_log_path_is_under_the_log_root(tmp_path: Path) -> None:
    assert child_log_path("postgres", log_root=tmp_path) == tmp_path / "postgres.log"
    assert child_log_path("control_plane", log_root=tmp_path) == tmp_path / "control_plane.log"


def test_configure_logging_uses_a_durable_handler(tmp_path: Path) -> None:
    """Diagnosability regression (2026-08-12, TESTER2 b5 evidence):
    supervisor.log was independently observed at 0 bytes for a 5+ hour run
    even though the evidence separately quotes one verbatim supervisor line
    -- it reached a sink SOMEWHERE. Fails on the pre-fix base, which wires a
    plain ``RotatingFileHandler`` that never fsyncs, leaving the file's
    on-disk, externally-observable size dependent on OS/filesystem timing
    for the life of the (never-closed) handle."""

    logger = configure_logging(log_root=tmp_path)

    rotating = [h for h in logger.handlers if hasattr(h, "maxBytes")]
    assert len(rotating) == 1
    assert isinstance(rotating[0], _DurableRotatingFileHandler)


def test_durable_handler_fsyncs_after_every_record(tmp_path: Path, monkeypatch) -> None:
    """Pins the actual durability mechanism (not just the class name): every
    emitted record must trigger an ``os.fsync`` of the file's live
    descriptor, so an external size/content check can never observe a state
    older than the last log call while the handle is still open."""

    fsynced_fds: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        fsynced_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy_fsync)

    logger = configure_logging(log_root=tmp_path)
    logger.warning("canary line for the fsync regression test")

    assert len(fsynced_fds) == 1

    log_path = tmp_path / "supervisor.log"
    # The write must be visible to a FRESH read handle without closing the
    # logger's own handler -- exactly the cross-process "how many bytes is
    # this file" check a tester's evidence-gathering script performs while
    # the service is still running.
    assert b"canary line for the fsync regression test" in log_path.read_bytes()


def test_durable_handler_emit_survives_fsync_failure(tmp_path: Path, monkeypatch) -> None:
    """The fsync step is best-effort: a platform/stream error durability step
    must never crash the log call itself (e.g. mid-shutdown stream close)."""

    def raising_fsync(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", raising_fsync)

    logger = configure_logging(log_root=tmp_path)
    logger.warning("this must not raise even though fsync fails")  # no exception


# ---------------------------------------------------------------------------
# Production wiring smoke (binds real seams; injects the pending ones)
# ---------------------------------------------------------------------------


def test_build_production_service_returns_a_wired_service() -> None:
    """The production assembler wires a SupervisorService without touching Win32
    at construction (Win32JobObjectApi/Win32ChildProcessRunner import lazily);
    the guard, alerting outbox, and probes are injected."""

    class _Guard:
        pass

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    service = build_production_service(
        logging.getLogger("test.supervisor.service"),
        guard=_Guard(),  # type: ignore[arg-type]
        alert_outbox=_Outbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe should not run at wiring time"),  # type: ignore[arg-type,return-value]
    )

    assert isinstance(service, SupervisorService)


def test_build_production_service_wires_program_data_root_for_egress_workdir() -> None:
    """CC-WS5-003 review-regression pin: ``build_production_service`` must pass
    ``program_data_root`` THROUGH to the wired ``Supervisor`` -- it feeds the
    control plane's ``CIVICCAST_EGRESS_WORK_DIR`` resolution
    (``default_egress_work_dir(program_data_root=...)``). A round-3 edit briefly
    replaced this pass-through with the new postmaster kwargs instead of adding
    alongside them, silently dropping the egress-work-dir security wiring; mypy
    and the isinstance-only wiring test did not catch it (an unused optional
    kwarg). This asserts the value actually reaches the supervisor."""

    class _Guard:
        pass

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    sentinel = r"Z:\sentinel-programdata"
    service = build_production_service(
        logging.getLogger("test.supervisor.service.pdr"),
        guard=_Guard(),  # type: ignore[arg-type]
        alert_outbox=_Outbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe should not run at wiring time"),  # type: ignore[arg-type,return-value]
        program_data_root=sentinel,
    )

    assert service._supervisor._program_data_root == sentinel


def test_build_production_service_wires_postgres_and_nats_log_paths() -> None:
    """Diagnosability regression (2026-08-12, TESTER2 b5 evidence):
    postgres.log/nats.log were observed at 0 bytes for a 5+ hour run.
    ``build_production_service`` must thread each child's OWN log path
    (the SAME path ``child_log_path`` already names) into the Supervisor so
    ``postgres_child_spec``/``nats_child_spec`` can add their ``-l`` flag.
    Fails on the pre-fix base: neither kwarg existed on ``Supervisor`` at
    all, so this always reproduced as ``None``."""

    class _Guard:
        pass

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    sentinel = r"Z:\sentinel-programdata-logs"
    service = build_production_service(
        logging.getLogger("test.supervisor.service.logpaths"),
        guard=_Guard(),  # type: ignore[arg-type]
        alert_outbox=_Outbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe should not run at wiring time"),  # type: ignore[arg-type,return-value]
        program_data_root=sentinel,
    )

    expected_root = Path(sentinel) / "CivicCast" / "logs"
    assert service._supervisor._postgres_log_path == str(expected_root / "postgres.log")
    assert service._supervisor._nats_log_path == str(expected_root / "nats.log")


def test_f1_build_production_service_shares_one_stop_event_with_the_supervisor() -> None:
    """F1 (BLOCKER, 2026-07-31): ``request_stop`` only SET the run loop's Event,
    and nothing inside ``Supervisor.start()``/``tick()`` ever read it -- so one
    in-flight iteration could chain four readiness budgets (60+30+30+60s) before
    the stop chain could begin, blowing the 150s stop watchdog MID-CHAIN, whose
    force-exit closed the Job Object and hard-killed postgres (unclean cluster).

    The production assembly must therefore hand the supervisor an abort seam
    bound to the SAME Event the run loop waits on. Two objects would be a
    silent half-fix: the stop would be visible to one half and invisible to the
    other.

    FALSIFICATION: against the pre-fix tree the supervisor has no ``should_abort``
    at all, so the seam is absent and the assertion below fails."""

    class _Guard:
        pass

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    service = build_production_service(
        logging.getLogger("test.supervisor.service.stopseam"),
        guard=_Guard(),  # type: ignore[arg-type]
        alert_outbox=_Outbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe should not run at wiring time"),  # type: ignore[arg-type,return-value]
    )

    should_abort = service._supervisor._should_abort
    assert should_abort() is False
    service.request_stop()
    assert should_abort() is True, (
        "the supervisor's abort seam must observe the SAME stop event the run "
        "loop waits on -- a second Event would leave start()/tick() blind to a "
        "requested stop, which is the F1 blocker itself"
    )


# ---------------------------------------------------------------------------
# CC-WS5-007 part 2: build_production_service wires the admin verbs
# ---------------------------------------------------------------------------


def test_build_production_service_wires_admin_verbs_to_the_control_pipe() -> None:
    """CC-WS5-007: the mutating admin verbs must be WIRED to real actions, not
    left raising. build_production_service composes the read tier
    (status/version -> core.command_handler) with the admin router
    (start/stop/restart/drain/runtime_set) into the control pipe's command
    queue. Proven here through the ILLEGAL-runtime_set path, which reaches a
    'refused' AdminActionResult without mutating the supervisor or touching the
    registry (so no Win32 is needed to prove the wiring)."""

    from civiccast.native.runtime_guard import GuardMonitorStatus

    class _Guard:
        # status_snapshot (read tier) reads guard.status.last_decision/alert.
        status = GuardMonitorStatus(last_decision=None)

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    service = build_production_service(
        logging.getLogger("test.supervisor.service.admin"),
        guard=_Guard(),  # type: ignore[arg-type]
        alert_outbox=_Outbox(),
        postgres_probe=lambda: True,
        nats_probe=lambda: True,
        health_probe=lambda: pytest.fail("probe should not run at wiring time"),  # type: ignore[arg-type,return-value]
    )

    queue = service._control_pipe._queue  # type: ignore[union-attr]
    try:
        # Admin tier: an illegal runtime_set is a structured 'refused', NOT the
        # ValueError core.command_handler used to raise for every admin verb.
        admin = queue.submit("runtime_set", {"cmd": "runtime_set", "v": 1, "runtime": "bogus"})
        assert admin["verb"] == "runtime_set"
        assert admin["outcome"] == "refused"
        # Read tier still routes to the core snapshot handler.
        read = queue.submit("status", {"cmd": "status", "v": 1})
        assert "state" in read
    finally:
        queue.stop()


# ---------------------------------------------------------------------------
# CC-WS5-007 part 1: the installable SCM entry point
# ---------------------------------------------------------------------------


def test_main_builds_the_service_class_and_forwards_scm_verbs() -> None:
    """The entry point builds the ServiceFramework class (wiring the production
    service_factory) and hands it, with the SCM argv, to
    win32serviceutil.HandleCommandLine -- so install/update/start/stop/remove
    parse. Proven with injected seams so no pywin32/SCM is needed."""

    from civiccast.native.supervisor.service import main

    seen: dict[str, object] = {}
    sentinel_class = type("FakeServiceClass", (), {})

    def fake_class_builder(*, service_factory: object) -> type:
        seen["service_factory"] = service_factory
        return sentinel_class

    def fake_handler(service_class: type, argv: list[str] | None) -> int:
        seen["class"] = service_class
        seen["argv"] = argv
        return 7

    def dummy_factory(_logger: object) -> object:  # pragma: no cover - never invoked
        raise AssertionError("service_factory must not run when only parsing SCM verbs")

    rc = main(
        ["install"],
        service_factory=dummy_factory,  # type: ignore[arg-type]
        class_builder=fake_class_builder,
        command_line_handler=fake_handler,
    )

    assert rc == 7
    assert seen["class"] is sentinel_class
    assert seen["argv"] == ["install"]
    # The class was built wiring the provided production service_factory.
    assert seen["service_factory"] is dummy_factory


def test_main_defaults_to_the_production_service_factory() -> None:
    """When no service_factory is injected, main wires the production factory
    (build_production_service via the dependency provider) into the class."""

    from civiccast.native.supervisor.service import (
        build_production_service_factory,
        main,
    )

    captured: dict[str, object] = {}

    def fake_class_builder(*, service_factory: object) -> type:
        captured["service_factory"] = service_factory
        return type("FakeServiceClass", (), {})

    def fake_handler(service_class: type, argv: list[str] | None) -> int:
        return 0

    main(["remove"], class_builder=fake_class_builder, command_line_handler=fake_handler)

    # A real callable (the production factory), not None.
    assert callable(captured["service_factory"])
    # Sanity: it is the production factory type, exercised below in isolation.
    assert build_production_service_factory is not None


def test_build_production_service_factory_assembles_deps_and_calls_build() -> None:
    """The production service_factory pulls the guard/probes/outbox from the
    injected dependency provider and calls build_production_service -- so the SCM
    entry point ends up with a fully-wired SupervisorService. The provider is a
    seam precisely because assembling the REAL guard/alerting-Session/probes is
    the VM/cross-module integration (disclosed)."""

    from civiccast.native.runtime_guard import GuardMonitorStatus
    from civiccast.native.supervisor.service import (
        ProductionDependencies,
        build_production_service_factory,
    )

    class _Guard:
        status = GuardMonitorStatus(last_decision=None)

    class _Outbox:
        def fire(self, *, summary: str, detail: str) -> None:
            pass

    def provider() -> ProductionDependencies:
        return ProductionDependencies(
            guard=_Guard(),  # type: ignore[arg-type]
            alert_outbox=_Outbox(),  # type: ignore[arg-type]
            postgres_probe=lambda: True,
            nats_probe=lambda: True,
            health_probe=lambda: pytest.fail("probe must not run at wiring time"),  # type: ignore[arg-type,return-value]
            program_data_root=r"Z:\pd",
        )

    factory = build_production_service_factory(dependency_provider=provider)
    service = factory(logging.getLogger("test.entrypoint.factory"))

    assert isinstance(service, SupervisorService)
    assert service._supervisor._program_data_root == r"Z:\pd"


def test_default_dependency_provider_builds_real_deps_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CC-WS5-007 residual acceptance (Codex round-4 Critical): the concrete
    default provider must assemble a real ProductionDependencies from ENV WITHOUT
    raising NotImplementedError, so the module-level SvcDoRun can build a real
    SupervisorService on the default path. Driving the ACTUAL provider far enough
    to prove CONSTRUCTION succeeds is the CI-bound proof; the probes/guard are NOT
    invoked here (they touch Win32/network) -- the live SCM/DB/NATS/control-plane
    run stays owner-VM bound."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    from civiccast.native.supervisor.service import (
        ProductionDependencies,
        default_dependency_provider,
    )

    deps = default_dependency_provider()

    assert isinstance(deps, ProductionDependencies)
    # guard is structurally a GuardLike -- do NOT evaluate it (that fires Win32 probes).
    assert hasattr(deps.guard, "pre_child_start")
    assert hasattr(deps.guard, "evaluate_once")
    assert hasattr(deps.guard, "status")
    assert callable(deps.alert_outbox.fire)
    assert callable(deps.postgres_probe)
    assert callable(deps.nats_probe)
    assert callable(deps.health_probe)
    # Audit A1 convention fix: program_data_root is the ProgramData ROOT (the
    # value children.default_egress_work_dir appends \CivicCast\data\egress to
    # itself). The old provider passed <pd>\CivicCast here, doubling the
    # CivicCast segment in the control plane's egress work dir.
    assert deps.program_data_root == os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    assert not deps.program_data_root.endswith("CivicCast")


def test_default_dependency_provider_normalizes_bare_postgresql_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """beta BLOCKER #51 regression: the installer persists DATABASE_URL under
    the bare ``postgresql://`` scheme (see civiccast.native.supervisor.
    service_env's registry bridge), which SQLAlchemy maps to the uninstalled
    psycopg2 dialect (ADR 0008 ships psycopg v3 only). The provider's
    create_engine call must receive the NORMALIZED (+psycopg) url. Asserts at
    the call boundary (monkeypatched ``create_engine``), never internals --
    no real DB round trip."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://civiccast:tr0ub4dor@127.0.0.1:5432/civiccast")

    import civiccast.native.supervisor.service as service_module

    captured: dict[str, str] = {}

    class _FakeEngine:
        pass

    def _fake_create_engine(url: str, **kwargs: object) -> _FakeEngine:
        captured["url"] = url
        return _FakeEngine()

    monkeypatch.setattr(service_module, "create_engine", _fake_create_engine)
    # sessionmaker(engine, future=True) is called on whatever create_engine
    # returns; the real sessionmaker accepts a plain object fine (it is not
    # invoked until a session is actually opened), so no fake needed there.

    service_module.default_dependency_provider()

    assert captured["url"].startswith("postgresql+psycopg://")
    assert "tr0ub4dor" in captured["url"]  # password must survive, not be corrupted


def test_provider_connect_timeout_pinned_against_env_tuning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sol audit 2026-08-09: CIVICCAST_DB_CONNECT_TIMEOUT tuning must NOT move
    the supervisor's connect bound. The stop watchdog's F1 in-flight term
    derives from _DB_CONNECT_TIMEOUT_SECONDS; at env=60 the reproduced worst
    case (180s) exceeds the 150s watchdog and force-exits a legitimate stop
    chain (red on 20ac2972, green once the call site pins the constant)."""

    monkeypatch.setenv("DATABASE_URL", "postgresql://civiccast:x@127.0.0.1:5432/civiccast")
    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "60")

    import civiccast.native.supervisor.service as service_module

    captured: dict[str, object] = {}

    class _FakeEngine:
        pass

    def _fake_create_engine(url: str, **kwargs: object) -> _FakeEngine:
        captured["kwargs"] = kwargs
        return _FakeEngine()

    monkeypatch.setattr(service_module, "create_engine", _fake_create_engine)
    service_module.default_dependency_provider()

    connect_args = captured["kwargs"]["connect_args"]
    assert connect_args["connect_timeout"] == service_module._DB_CONNECT_TIMEOUT_SECONDS == 10


def test_default_dependency_provider_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real supervisor needs its DB; an unset DATABASE_URL fails LOUDLY with a
    ValueError that NAMES DATABASE_URL rather than silently wiring a session-less
    outbox. This is the ONLY hard-fail in the provider -- everything else is
    constructed by-reference."""

    monkeypatch.delenv("DATABASE_URL", raising=False)

    from civiccast.native.supervisor.service import default_dependency_provider

    with pytest.raises(ValueError, match="DATABASE_URL"):
        default_dependency_provider()


def test_default_dependency_provider_rejects_empty_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty/whitespace DATABASE_URL is treated the same as unset (a real DB
    URL is required), still naming DATABASE_URL in the error."""

    monkeypatch.setenv("DATABASE_URL", "   ")

    from civiccast.native.supervisor.service import default_dependency_provider

    with pytest.raises(ValueError, match="DATABASE_URL"):
        default_dependency_provider()


def test_g2_postgres_probe_wrapper_preserves_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G2: ``postgres_probe`` must NOT catch its own connection exception --
    ``check_postgres_ready`` (children.py) already wraps the probe call in a
    fail-closed ``except Exception`` and formats the exception TEXT into
    ``ReadinessResult.detail``. The old wrapper had a REDUNDANT
    ``except Exception: return False`` one layer too early, which destroyed
    that detail before it ever reached the readiness gate (or G2's new
    logging) -- exactly the blindness that made run 17's diagnosis require a
    from-scratch repro script instead of reading a log. Forces a real,
    fast-failing connection error (an unopenable sqlite path) and asserts the
    RAISED-branch detail (with the real exception text) is what comes out,
    not the generic swallowed-False detail."""

    # An unresolvable host fails at DNS resolution in milliseconds (unlike a
    # closed port, which psycopg waits out to connect_timeout) and produces a
    # distinctive, assertable message -- deterministic and fast either way.
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://civiccast:x@civiccast-g2-probe.invalid/civiccast",
    )

    from civiccast.native.supervisor.children import check_postgres_ready
    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()

    # The wrapper itself must propagate (not swallow) the connection error.
    with pytest.raises(Exception, match="failed to resolve host"):
        deps.postgres_probe()

    # And the readiness gate one layer up must see the real exception text.
    result = check_postgres_ready(deps.postgres_probe)
    assert result.outcome == "not_ready"
    assert "SELECT 1 check raised" in result.detail
    assert "failed to resolve host" in result.detail
    assert "did not succeed" not in result.detail  # the old swallowed-generic detail


def test_g2_nats_probe_wrapper_preserves_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """G2 twin of the postgres test above, for ``nats_probe``. Points at a
    closed loopback port so the real ``nats`` client's connect fails fast
    (bounded by ``_NATS_CONNECT_TIMEOUT_SECONDS``); asserts the wrapper
    propagates rather than swallows, so ``check_nats_ready`` reaches its
    RAISED branch (real exception detail) instead of the generic
    round-trip-did-not-complete detail a swallowed ``False`` produces."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("CIVICCAST_NATS_HOST", "127.0.0.1")
    monkeypatch.setenv("CIVICCAST_NATS_PORT", "18211")  # nothing listens here

    from civiccast.native.supervisor.children import check_nats_ready
    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()

    with pytest.raises(Exception):  # noqa: B017 -- the real nats client's own exception type
        deps.nats_probe()

    result = check_nats_ready(deps.nats_probe)
    assert result.outcome == "not_ready"
    assert "JetStream publish+ack raised" in result.detail
    assert "did not complete" not in result.detail  # the old swallowed-generic detail


def test_default_provider_drives_factory_to_a_real_supervisor_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole default path -- build_production_service_factory()(logger) ->
    default_dependency_provider() -> build_production_service -- now assembles a
    real SupervisorService with NO NotImplementedError, so the module-level
    SvcDoRun in service_host can actually start supervision on the default path."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    from civiccast.native.supervisor.service import build_production_service_factory

    factory = build_production_service_factory()
    service = factory(logging.getLogger("test.entrypoint.default"))

    assert isinstance(service, SupervisorService)


def test_default_provider_outbox_records_a_service_down_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The alert_outbox.fire binding opens a Session and calls
    alerting.store.record_alert_condition with the supervisor restart-escalation
    kind (``service-down``) + source_section='supervisor', passing the fire()
    summary/detail through. Proven with a recording fake (patched on the store
    module) so no real alerting write is needed."""

    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    calls: list[dict[str, object]] = []

    def _record(session: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    import civiccast.alerting.store as store_mod

    monkeypatch.setattr(store_mod, "record_alert_condition", _record)

    from civiccast.native.supervisor.service import default_dependency_provider

    deps = default_dependency_provider()
    deps.alert_outbox.fire(summary="supervisor restart storm", detail="5 restarts")

    assert len(calls) == 1
    assert calls[0]["kind"] == "service-down"
    assert calls[0]["source_section"] == "supervisor"
    assert calls[0]["summary"] == "supervisor restart storm"
    assert calls[0]["detail"] == "5 restarts"


# ---------------------------------------------------------------------------
# CC-WS5-007 part 3: control-pipe standup resilience (retry / degrade / EventLog)
# ---------------------------------------------------------------------------


@dataclass
class _StandupCreateResult:
    """A PipeCreateResult-shaped stand-in (has ``ok``/``detail``) for the pipe
    standup resilience tests."""

    ok: bool
    detail: str = ""


@dataclass
class RaisingControlPipe:
    """open() raises the first ``fail_times`` calls, then returns ok=True. Models
    a transient Win32 standup failure that must not crash the supervision loop."""

    fail_times: int = 1
    opened: int = 0
    closed: int = 0

    def open(self) -> object:
        self.opened += 1
        if self.opened <= self.fail_times:
            raise OSError(f"pipe standup boom {self.opened}")
        return _StandupCreateResult(ok=True, detail="created")

    def close(self) -> None:
        self.closed += 1


@dataclass
class SquattedControlPipe:
    """open() always returns a degraded (ok=False) create -- the D7 squat case,
    which create_control_pipe reports without raising."""

    opened: int = 0
    closed: int = 0

    def open(self) -> object:
        self.opened += 1
        return _StandupCreateResult(ok=False, detail="ACCESS_DENIED: name already exists (squat)")

    def close(self) -> None:
        self.closed += 1


def _cp_handles() -> dict[str, FakeHandle]:
    return {"control_plane": FakeHandle(pid=971, kind="ctrl_break_event")}


def test_run_does_not_crash_when_pipe_standup_raises_and_supervision_still_runs() -> None:
    """FALSIFICATION of the crash the fix closes: with the old bare
    ``self._control_pipe.open()``, a standup that raises propagates out of
    ``run()`` and supervision never starts. The resilient standup must retry and,
    on success, let supervision proceed -- the pipe failing must not kill it."""

    pipe = RaisingControlPipe(fail_times=1)
    runner = FakeRunner(alive={971: False})
    service, supervisor = make_service(handles=_cp_handles(), runner=runner, control_pipe=pipe)
    service.request_stop()

    service.run()  # must NOT raise

    assert supervisor.run_calls == 1  # supervision ran despite the standup failure
    assert pipe.opened == 2  # one raise + one success (retried)
    assert pipe.closed == 1  # still torn down on the stop path


def test_pipe_standup_retry_success_logs_the_failure_to_the_event_log() -> None:
    """A transient standup failure is logged to the Windows Event Log seam
    (servicemanager.LogErrorMsg in production; a recorder here) before the retry
    succeeds -- an operator sees the blip even though it self-healed."""

    events: list[str] = []
    pipe = RaisingControlPipe(fail_times=1)
    runner = FakeRunner(alive={971: False})
    service, _ = make_service(
        handles=_cp_handles(), runner=runner, control_pipe=pipe, event_log=events.append
    )
    service.request_stop()

    service.run()

    assert any("raised" in m for m in events), events


def test_pipe_standup_degrades_when_all_retries_fail_supervision_survives() -> None:
    """DEGRADE: when every bounded retry fails, the supervision loop still runs
    (children keep running, control is unavailable) and the exhaustion is logged
    to the Event Log -- run() never raises."""

    events: list[str] = []
    pipe = RaisingControlPipe(fail_times=99)  # never succeeds
    runner = FakeRunner(alive={971: False})
    service, supervisor = make_service(
        handles=_cp_handles(), runner=runner, control_pipe=pipe, event_log=events.append
    )
    service.request_stop()

    service.run()  # must NOT raise

    assert supervisor.run_calls == 1  # DEGRADE, not crash: supervision ran anyway
    assert pipe.opened == 3  # bounded attempts (default max 3)
    assert any("exhausted" in m.lower() for m in events), events


def test_pipe_standup_retries_a_degraded_squatted_create_then_degrades() -> None:
    """A squatted pipe (create returns ok=False, never raises) is retried with
    bounded backoff and then degraded -- logged to the Event Log, supervision
    continues."""

    events: list[str] = []
    pipe = SquattedControlPipe()
    runner = FakeRunner(alive={971: False})
    service, supervisor = make_service(
        handles=_cp_handles(), runner=runner, control_pipe=pipe, event_log=events.append
    )
    service.request_stop()

    service.run()

    assert supervisor.run_calls == 1
    assert pipe.opened == 3  # retried the degraded create up to the bound
    assert any("degraded" in m.lower() for m in events), events


def test_pipe_standup_clean_open_does_not_touch_the_event_log() -> None:
    """No false alarms: a clean first-attempt standup logs nothing to the Event
    Log and opens exactly once."""

    events: list[str] = []
    pipe = RaisingControlPipe(fail_times=0)  # succeeds immediately
    runner = FakeRunner(alive={971: False})
    service, _ = make_service(
        handles=_cp_handles(), runner=runner, control_pipe=pipe, event_log=events.append
    )
    service.request_stop()

    service.run()

    assert pipe.opened == 1
    assert events == []


# ---------------------------------------------------------------------------
# SvcStop watchdog (gauntlet run 17: SERVICE_STOP_PENDING forever)
# ---------------------------------------------------------------------------
#
# Run 17: the supervisor service wedged in SERVICE_STOP_PENDING with the SCM
# checkpoint stuck at 0x1 for 112+ seconds because SvcDoRun never returned.
# StopWatchdog is the defense in depth that makes "the SCM always reaches
# STOPPED" true even when the NEXT unbounded call is one nobody has found yet.
# Fully injectable, so the force-exit path is proven without killing pytest.


def test_stop_watchdog_fires_loudly_and_force_exits_when_the_stop_never_returns() -> None:
    """The wedge case. An armed, never-disarmed watchdog must: force-exit with
    the reserved exit code, log at ERROR (not INFO, not silently), reach the
    Windows Event Log seam too, and NAME the stop-chain position so the next
    investigator does not start from zero."""

    exits: list[int] = []
    events: list[str] = []
    logger = logging.getLogger("test.stop-watchdog.fire")
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    logger.addHandler(handler)
    try:
        watchdog = StopWatchdog(
            timeout_seconds=0.05,
            position=lambda: "stopping-child:postgres",
            logger=logger,
            event_log=events.append,
            force_exit=exits.append,
        )
        assert watchdog.armed is False
        watchdog.arm()
        assert watchdog.armed is True

        deadline = time.monotonic() + 5.0
        while not exits and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        logger.removeHandler(handler)

    assert exits == [SVC_STOP_WATCHDOG_EXIT_CODE], (
        "the watchdog must force-exit the host so the SCM leaves STOP_PENDING"
    )
    assert watchdog.fired is True
    assert len(records) == 1, f"expected exactly one watchdog log record, got {records!r}"
    assert records[0].levelno >= logging.ERROR, (
        "a fired watchdog is a loud failure, never an INFO-level or silent path"
    )
    assert "stopping-child:postgres" in records[0].getMessage(), (
        "the one log line must carry the best available stop-chain position"
    )
    assert len(events) == 1 and "stopping-child:postgres" in events[0], (
        "the Windows Event Log seam must also receive the firing"
    )


def test_f2_stop_watchdog_reports_service_stopped_before_force_exiting() -> None:
    """F2 (BLOCKER, 2026-07-31): the watchdog force-exited the host WITHOUT ever
    reporting SERVICE_STOPPED, and with a nonzero exit code (88). Service
    registration applies ``sc failure ... actions= restart/5000/...`` together
    with ``sc failureflag 1`` -- and failureflag 1 makes the SCM treat ANY
    nonzero exit as a failure. So a fired watchdog got the service RESTARTED
    about five seconds later, straight into the uninstaller's tree removal:
    the last resort that existed to unblock an uninstall re-blocked it.

    The watchdog must therefore (a) call the SCM status reporter, (b) do so
    BEFORE the force-exit (afterwards there is no process left to report
    anything), and (c) exit ZERO.

    FALSIFICATION: against the pre-fix tree there is no reporter to call and the
    exit code is 88; every assertion below fails."""

    order: list[str] = []
    exits: list[int] = []

    def recording_force_exit(code: int) -> None:
        order.append("force_exit")
        exits.append(code)

    watchdog = StopWatchdog(
        timeout_seconds=0.05,
        position=lambda: "stopping-child:postgres",
        logger=logging.getLogger("test.stop-watchdog.report-stopped"),
        event_log=lambda _m: None,
        force_exit=recording_force_exit,
        report_stopped=lambda: order.append("report_stopped"),
    )
    watchdog.arm()

    deadline = time.monotonic() + 5.0
    while not exits and time.monotonic() < deadline:
        time.sleep(0.01)

    assert order == ["report_stopped", "force_exit"], (
        "SERVICE_STOPPED must be reported to the SCM BEFORE the process is "
        f"force-exited; got {order}"
    )
    assert exits == [0], (
        "the watchdog must exit ZERO: with sc failureflag 1 + actions= "
        "restart/5000, a nonzero exit makes the SCM resurrect the service into "
        f"the uninstall this watchdog fired to unblock; got {exits}"
    )
    assert SVC_STOP_WATCHDOG_EXIT_CODE == 0


def test_f2_a_raising_status_report_still_force_exits() -> None:
    """The report is best-effort. A watchdog that skipped its force-exit because
    the SCM handle was already gone would be no last resort at all."""

    exits: list[int] = []

    def raising_report() -> None:
        raise OSError("the service status handle is gone")

    watchdog = StopWatchdog(
        timeout_seconds=0.05,
        position=lambda: "stop-requested",
        logger=logging.getLogger("test.stop-watchdog.raising-report"),
        event_log=lambda _m: None,
        force_exit=exits.append,
        report_stopped=raising_report,
    )
    watchdog.arm()

    deadline = time.monotonic() + 5.0
    while not exits and time.monotonic() < deadline:
        time.sleep(0.01)

    assert exits == [SVC_STOP_WATCHDOG_EXIT_CODE]


def test_f2_build_stop_watchdog_threads_the_status_reporter_through() -> None:
    """The production assembly must carry the reporter -- a StopWatchdog built
    without one is exactly the pre-F2 behaviour."""

    reports: list[str] = []
    watchdog = build_stop_watchdog(lambda: "x", report_stopped=lambda: reports.append("stopped"))

    assert watchdog._report_stopped is not None
    watchdog._report_stopped()
    assert reports == ["stopped"]


def test_stop_watchdog_disarmed_before_its_deadline_never_fires() -> None:
    """The NORMAL path: SvcDoRun returns, the watchdog is disarmed, and nothing
    is force-exited or logged. A watchdog that fired here would kill healthy
    stops -- the exact failure mode a last resort must not have."""

    exits: list[int] = []
    events: list[str] = []
    watchdog = StopWatchdog(
        timeout_seconds=0.2,
        position=lambda: "stop-chain-complete",
        logger=logging.getLogger("test.stop-watchdog.disarm"),
        event_log=events.append,
        force_exit=exits.append,
    )
    watchdog.arm()
    watchdog.disarm()
    watchdog.disarm()  # idempotent

    time.sleep(0.5)  # well past the deadline it would have fired at

    assert exits == []
    assert events == []
    assert watchdog.fired is False
    assert watchdog.armed is False


def test_stop_watchdog_arm_is_idempotent_so_a_second_svcstop_does_not_stack_timers() -> None:
    """The SCM may deliver more than one stop control. A second ``arm()`` must
    not create a second timer -- two timers would double-fire the force-exit
    and, worse, the first ``disarm()`` would only cancel one of them."""

    exits: list[int] = []
    watchdog = StopWatchdog(
        timeout_seconds=0.05,
        position=lambda: "stop-requested",
        logger=logging.getLogger("test.stop-watchdog.idempotent"),
        event_log=lambda _m: None,
        force_exit=exits.append,
    )
    watchdog.arm()
    watchdog.arm()
    watchdog.disarm()

    time.sleep(0.3)

    assert exits == [], "one disarm must cancel everything a repeated arm created"


def test_stop_watchdog_survives_a_position_probe_that_raises() -> None:
    """The position probe is best-effort diagnostics. If it raises, the
    force-exit must still happen -- a broken breadcrumb must never restore the
    infinite STOP_PENDING this watchdog exists to end."""

    exits: list[int] = []
    events: list[str] = []

    def exploding_position() -> str:
        raise RuntimeError("service object is half torn down")

    watchdog = StopWatchdog(
        timeout_seconds=0.05,
        position=exploding_position,
        logger=logging.getLogger("test.stop-watchdog.raising-position"),
        event_log=events.append,
        force_exit=exits.append,
    )
    watchdog.arm()

    deadline = time.monotonic() + 5.0
    while not exits and time.monotonic() < deadline:
        time.sleep(0.01)

    assert exits == [SVC_STOP_WATCHDOG_EXIT_CODE]
    assert len(events) == 1 and "unavailable" in events[0]


def test_stop_watchdog_timeout_exceeds_the_bounded_worst_case_of_the_stop_chain() -> None:
    """FALSIFICATION of the timeout VALUE, not just the mechanism. A last
    resort that fires during a legitimately slow stop is a new bug, so the
    constant must exceed the stop chain's own bounded worst case, computed here
    from the SAME numbers the production code uses rather than restated:

      the F1 in-flight supervisor iteration (one readiness probe attempt + one
      poll-interval sleep) + 4 children x (10s bounded stop command + 15s D5
      deadline + 1s poll granularity) + the control-pipe teardown (5s pipe
      close + 5s command-queue join + 5s accept-thread join).

    REDERIVED (2026-07-31, F1). The old computation summed only the last two
    terms (119s) and silently assumed the first was ZERO -- but nothing inside
    ``Supervisor.start()``/``tick()`` read the stop event, so the work already
    in flight when SvcStop landed could chain FOUR readiness budgets
    (60+30+30+60 = 180s) before the stop chain even began. The biggest term in
    the system was the one the derivation left out, which is how the watchdog
    could fire MID-CHAIN and hard-kill the postgres cluster. With the
    ``should_abort`` seam that term collapses to one probe attempt plus one
    poll sleep, and is now carried explicitly."""

    import civiccast.native.supervisor.service as service_module

    in_flight_seconds = service_module.SVC_STOP_IN_FLIGHT_ITERATION_SECONDS
    per_child_seconds = (
        service_module.STOP_COMMAND_TIMEOUT_SECONDS
        + SupervisorConfig().graceful_stop_deadline_seconds
        + 1
    )
    children = 4  # control_plane, ollama, nats, postgres
    control_pipe_teardown_seconds = 5 + 5 + 5
    bounded_worst_case = (
        in_flight_seconds + children * per_child_seconds + control_pipe_teardown_seconds
    )

    # The in-flight term is the LONGEST single readiness probe attempt (the DB
    # connect timeout dominates the three 2.0s HTTP/NATS probes) plus one
    # non-interruptible poll-interval sleep.
    probe_attempt_timeouts = (
        service_module._DB_CONNECT_TIMEOUT_SECONDS,
        service_module._NATS_CONNECT_TIMEOUT_SECONDS,
        service_module._HEALTH_HTTP_TIMEOUT_SECONDS,
        service_module._OLLAMA_VERSION_TIMEOUT_SECONDS,
    )
    assert max(probe_attempt_timeouts) == service_module._DB_CONNECT_TIMEOUT_SECONDS, (
        "the in-flight term must be derived from the LONGEST probe attempt"
    )
    assert in_flight_seconds == pytest.approx(11.0)
    assert bounded_worst_case == pytest.approx(130.0)
    assert bounded_worst_case < SVC_STOP_WATCHDOG_SECONDS, (
        f"a {SVC_STOP_WATCHDOG_SECONDS}s watchdog would fire during an ordinary "
        f"four-child stop whose bounded worst case is {bounded_worst_case}s"
    )


def test_build_stop_watchdog_reads_its_timeout_from_the_environment_at_arm_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator must be able to retune (or, with <=0, disable) the watchdog
    on a wedged station without a rebuild."""

    monkeypatch.delenv(SVC_STOP_WATCHDOG_ENV_VAR, raising=False)
    assert build_stop_watchdog(lambda: "x")._timeout_seconds == float(SVC_STOP_WATCHDOG_SECONDS)

    monkeypatch.setenv(SVC_STOP_WATCHDOG_ENV_VAR, "45")
    assert build_stop_watchdog(lambda: "x")._timeout_seconds == 45.0

    monkeypatch.setenv(SVC_STOP_WATCHDOG_ENV_VAR, "not-a-number")
    assert build_stop_watchdog(lambda: "x")._timeout_seconds == float(SVC_STOP_WATCHDOG_SECONDS)


def test_stop_watchdog_with_a_non_positive_timeout_is_disabled_not_instant() -> None:
    """<=0 means DISABLED. It must not mean "fire immediately", which would
    force-exit every stop the instant it was requested."""

    exits: list[int] = []
    watchdog = StopWatchdog(
        timeout_seconds=0,
        position=lambda: "stop-requested",
        logger=logging.getLogger("test.stop-watchdog.disabled"),
        event_log=lambda _m: None,
        force_exit=exits.append,
    )
    watchdog.arm()
    time.sleep(0.3)

    assert watchdog.armed is False
    assert exits == []


# ---------------------------------------------------------------------------
# The stop-chain position breadcrumb the watchdog reports
# ---------------------------------------------------------------------------


def test_stop_position_tracks_the_chain_and_ends_at_complete() -> None:
    """The breadcrumb the watchdog's one log line depends on must actually be
    written by the stop path -- an always-"unknown" position would make a fired
    watchdog useless."""

    runner = FakeRunner(alive={971: False})
    service, _ = make_service(handles=_cp_handles(), runner=runner)

    assert service.stop_position == "not-stopping"
    service.request_stop()
    assert service.stop_position == "stop-requested"

    service.run()

    assert service.stop_position == "stop-chain-complete"


def test_stop_position_names_the_child_whose_stop_is_in_flight() -> None:
    """The run-17 wedge's last log line named a CHILD (``postgres``). If the
    next wedge is inside a child's stop, the watchdog must be able to say
    which one."""

    seen: list[str] = []

    class _ObservingRunner(FakeRunner):
        def graceful_stop(self, handle: FakeHandle) -> str:
            seen.append(service.stop_position)
            return super().graceful_stop(handle)

    runner = _ObservingRunner(alive={971: False})
    service, _ = make_service(handles=_cp_handles(), runner=runner)
    service.request_stop()

    service.run()

    assert seen and all(position.startswith("stopping-child:") for position in seen), seen


# ---------------------------------------------------------------------------
# F-13 (sandbox newcomer re-walk dd7f835f, 2026-08-01): a blank black console
# window titled "...\runtime\python.exe" was left sitting on the operator's
# desktop after install. It was not a stray helper -- it WAS the live control
# plane, the uvicorn process serving 127.0.0.1:8000, and closing it killed the
# station's API. A LocalSystem service has no console of its own for a child to
# inherit, so Windows allocates the child a NEW one unless the spawn says
# otherwise, and python.exe is a console-subsystem executable.
#
# CREATE_NO_WINDOW is this repo's established convention for exactly this --
# pg_ctl_exec.py, installer/service.py, stream/_ffmpeg.py, provision/seams.py,
# egress/gst/strategy.py, certs/authority.py and captions/runtime.py all pass
# it, and three of those have tests asserting they do. The one function that
# launches the supervisor's own children never adopted it.
# ---------------------------------------------------------------------------


def _captured_popen_call(
    monkeypatch: pytest.MonkeyPatch, spec: ChildSpec, *, new_process_group: bool, log_root: Path
) -> dict[str, object]:
    """Drive the REAL production popen factory with subprocess.Popen faked out,
    and return the kwargs it was called with."""

    import subprocess

    captured: dict[str, object] = {}

    def fake_popen(argv: object, **kwargs: object) -> object:
        captured["argv"] = argv
        captured.update(kwargs)
        return FakePopen(pid=4242)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _file_backed_popen_factory(spec, new_process_group, log_root=log_root)
    return captured


# ---------------------------------------------------------------------------
# Gate A run #4 (2026-08-21): every fresh native install failed because
# postgres_child_spec's "-l" target and _file_backed_popen_factory's own
# generic stdio capture were the SAME file. On Windows, pg_ctl's "-l"
# relaunches through cmd.exe ("cmd /c ... >> <file> 2>&1"), and a second
# process reopening a file the supervisor already has open (inherited by
# pg_ctl as its own stdout/stderr) hits ERROR_SHARING_VIOLATION
# deterministically -- confirmed by local repro against the real pg_ctl.exe
# extracted from the failing Gate A kit (same-file: pg_ctl exit 1, identical
# "process cannot access the file" text; split-file: pg_ctl exit 0, clean
# startup). These pin the invariant purely (fake Popen, no real postgres):
# whenever a ChildSpec sets stdio_log_name, _file_backed_popen_factory must
# resolve its OWN capture file from THAT name, never from spec.name.
# ---------------------------------------------------------------------------


def test_file_backed_popen_factory_honors_stdio_log_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = _pg_spec().model_copy(update={"stdio_log_name": "postgres-launcher"})
    call = _captured_popen_call(monkeypatch, spec, new_process_group=False, log_root=tmp_path)

    stdout_handle = call["stdout"]
    assert call["stderr"] is stdout_handle
    resolved = getattr(stdout_handle, "name", None)
    assert resolved == str(tmp_path / "postgres-launcher.log")
    # The invariant: this must NEVER be the same path postgres_child_spec's
    # "-l" flag would target for the same log_root (child_log_path("postgres",
    # log_root=tmp_path)) -- that collision is exactly what caused every
    # fresh install to fail Gate A run #4.
    assert resolved != str(tmp_path / "postgres.log")


def test_file_backed_popen_factory_defaults_to_name_without_stdio_log_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Backward compatibility: every child that never sets ``stdio_log_name``
    (nats, control_plane, and postgres itself when no ``-l`` target is in
    play) keeps resolving its capture file from ``spec.name``, unchanged."""

    for spec in (_pg_spec(), _nats_spec(), _cp_spec()):
        assert spec.stdio_log_name is None
        call = _captured_popen_call(monkeypatch, spec, new_process_group=False, log_root=tmp_path)
        resolved = getattr(call["stdout"], "name", None)
        assert resolved == str(tmp_path / f"{spec.name}.log")


@pytest.mark.windows_only
def test_f13_no_supervisor_child_is_given_a_console_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not create_no_window:
        pytest.skip("CREATE_NO_WINDOW is a Windows-only creation flag")

    for spec, new_process_group in (
        (_pg_spec(), False),
        (_nats_spec(), False),
        (_cp_spec(), True),
    ):
        call = _captured_popen_call(
            monkeypatch, spec, new_process_group=new_process_group, log_root=tmp_path
        )
        flags = call["creationflags"]
        assert isinstance(flags, int)
        assert flags & create_no_window, (
            f"the {spec.name} child is spawned without CREATE_NO_WINDOW. A LocalSystem "
            "service has no console for a child to inherit, so Windows gives a "
            "console-subsystem exe (runtime/python.exe) a NEW visible one. On the "
            "2026-08-01 re-walk that window was the live control plane sitting on the "
            "operator's desktop, and closing it killed the station's API"
        )


@pytest.mark.windows_only
def test_f13_suppressing_the_window_does_not_disturb_the_process_group_or_log_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The two things the spawn already got right must survive the fix:
    RAT-004's control-plane-only process group, and G3's file-backed
    stdout/stderr capture (the flag suppresses a WINDOW, not the streams)."""

    import subprocess

    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if not create_no_window:
        pytest.skip("CREATE_NO_WINDOW is a Windows-only creation flag")

    control_plane = _captured_popen_call(
        monkeypatch, _cp_spec(), new_process_group=True, log_root=tmp_path
    )
    infra = _captured_popen_call(
        monkeypatch, _nats_spec(), new_process_group=False, log_root=tmp_path
    )

    assert control_plane["creationflags"] == create_no_window | new_group, (
        "the control plane must keep its OWN process group (RAT-004's CTRL_BREAK drain "
        "targets it) as well as being windowless"
    )
    assert infra["creationflags"] == create_no_window, (
        "an infra child must NOT be given its own process group -- only the control plane is"
    )
    for call in (control_plane, infra):
        assert call["stdout"] is not None, "G3's file-backed stdout capture must survive"
        assert call["stderr"] is call["stdout"], (
            "stderr must keep sharing the child's log-file handle"
        )
