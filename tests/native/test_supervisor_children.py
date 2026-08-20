# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.native.supervisor.children (slice:ws5-supervisor, r2-children).

Pure -- every child's launch is a ChildSpec (argv/env/cwd + graceful-stop shape),
never a real subprocess; every readiness gate is exercised through an injected
stub check (DB SELECT 1, JetStream publish+ack, GET /health), never a real
socket. Covers:

* ChildSpec / GracefulStopAction construction validators (extra=forbid, shape).
* The three real child contracts (postgres, nats, control_plane) per
  r2-children's exact commands, incl. the RAT-001 maintenance env contract and
  the egress-workdir AC.
* Per-child readiness: ready / not_ready / timeout (poll_until_ready with a
  fake clock+sleep -- no real waiting).
* The RAT-001 maintenance-readiness gate's fail-closed matrix.
* D5 restart backoff+jitter bounds and the restart-storm predicate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.native.supervisor.children import (
    ChildSpec,
    ControlPlaneHealthProbe,
    GracefulStopAction,
    backoff_with_jitter,
    check_control_plane_maintenance_ready,
    check_control_plane_ready,
    check_nats_ready,
    check_postgres_ready,
    control_plane_child_spec,
    default_egress_work_dir,
    default_upload_dir,
    graceful_stop_action,
    nats_child_spec,
    poll_until_ready,
    postgres_child_spec,
    read_postmaster_pid,
    restart_storm_check,
)
from civiccast.native.supervisor.config import SupervisorConfig
from civiccast.native.supervisor.states import backoff_base_seconds

# ---------------------------------------------------------------------------
# ChildSpec / GracefulStopAction construction validators
# ---------------------------------------------------------------------------


def test_childspec_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ChildSpec(
            name="postgres",
            argv=["pg_ctl"],
            graceful_stop_kind="argv",
            graceful_stop_argv_template=["pg_ctl", "stop", "-m", "fast"],
            graceful_stop_deadline_seconds=15.0,
            readiness_budget_seconds=60.0,
            bogus_field="nope",  # type: ignore[call-arg]
        )


def test_childspec_argv_kind_requires_nonempty_template() -> None:
    with pytest.raises(ValidationError):
        ChildSpec(
            name="postgres",
            argv=["pg_ctl"],
            graceful_stop_kind="argv",
            graceful_stop_argv_template=[],
            graceful_stop_deadline_seconds=15.0,
            readiness_budget_seconds=60.0,
        )


def test_childspec_ctrl_break_kind_forbids_template() -> None:
    with pytest.raises(ValidationError):
        ChildSpec(
            name="control_plane",
            argv=["python"],
            graceful_stop_kind="ctrl_break_event",
            graceful_stop_argv_template=["should", "not", "be", "here"],
            graceful_stop_deadline_seconds=15.0,
            readiness_budget_seconds=30.0,
        )


def test_graceful_stop_action_argv_requires_argv() -> None:
    with pytest.raises(ValidationError):
        GracefulStopAction(kind="argv", argv=None, target_pid=None)


def test_graceful_stop_action_ctrl_break_requires_pid() -> None:
    with pytest.raises(ValidationError):
        GracefulStopAction(kind="ctrl_break_event", argv=None, target_pid=None)


def test_graceful_stop_action_argv_forbids_pid() -> None:
    with pytest.raises(ValidationError):
        GracefulStopAction(kind="argv", argv=["a"], target_pid=123)


# ---------------------------------------------------------------------------
# postgres: graceful stop shape ('pg_ctl stop -m fast', spec-supervisor.md D5)
# ---------------------------------------------------------------------------


def test_postgres_child_spec_readiness_budget_matches_d6_default() -> None:
    spec = postgres_child_spec(data_dir=r"C:\ProgramData\CivicCast\data\pg")
    assert spec.name == "postgres"
    assert spec.readiness_budget_seconds == 60.0
    assert spec.new_process_group is False


def test_postgres_graceful_stop_argv_matches_spec_text_verbatim() -> None:
    spec = postgres_child_spec(pg_ctl_path=r"C:\pg\bin\pg_ctl.exe", data_dir=r"C:\data\pg")
    action = graceful_stop_action(spec, pid=999)
    assert action.kind == "argv"
    assert action.argv is not None
    # spec-supervisor.md D5's exact text: "pg_ctl stop -m fast" must appear,
    # in order, as a suffix of the stop argv.
    assert action.argv[-4:] == [r"C:\pg\bin\pg_ctl.exe", "stop", "-m", "fast"] or (
        "stop" in action.argv and action.argv[-2:] == ["-m", "fast"]
    )
    assert action.target_pid is None


def test_postgres_graceful_stop_argv_does_not_depend_on_pid() -> None:
    spec = postgres_child_spec(data_dir=r"C:\data\pg")
    a1 = graceful_stop_action(spec, pid=111)
    a2 = graceful_stop_action(spec, pid=222)
    assert a1.argv == a2.argv


def test_postgres_child_spec_omits_l_flag_by_default() -> None:
    """Backward compatibility: no log_path means the pre-fix argv shape,
    unchanged (still relies on the generic inherited-stdio capture)."""

    spec = postgres_child_spec(data_dir=r"C:\data\pg")
    assert "-l" not in spec.argv


def test_postgres_child_spec_log_path_adds_l_flag() -> None:
    """Diagnosability regression (2026-08-12, TESTER2 b5 evidence):
    postgres.log was observed at 0 bytes for a 5+ hour run. ``pg_ctl -l
    <file>`` makes the postmaster own its log file directly. Fails on the
    pre-fix base (no ``log_path`` parameter exists at all)."""

    spec = postgres_child_spec(
        data_dir=r"C:\data\pg", log_path=r"C:\ProgramData\CivicCast\logs\postgres.log"
    )
    assert "-l" in spec.argv
    assert spec.argv[spec.argv.index("-l") + 1] == r"C:\ProgramData\CivicCast\logs\postgres.log"


# ---------------------------------------------------------------------------
# nats: lame-duck graceful stop ('nats-server --signal ldm=<pid>')
# ---------------------------------------------------------------------------
# These pin the spec-fixed ARGV (and its {pid} substitution) -- nothing more.
# On Windows the command itself fails "Access is denied" pid-independently
# (the flag routes through the SCM and nats is not a registered service), so
# what actually ends this child there is the D5 deadline + TerminateProcess.
# See children.nats_child_spec's stop-template comment for the measurement.


def test_nats_child_spec_defaults() -> None:
    spec = nats_child_spec()
    assert spec.name == "nats"
    assert spec.new_process_group is False


def test_nats_child_spec_omits_l_flag_by_default() -> None:
    spec = nats_child_spec()
    assert "-l" not in spec.argv


def test_nats_child_spec_log_path_adds_l_flag() -> None:
    """Diagnosability regression (2026-08-12, TESTER2 b5 evidence):
    nats.log was observed at 0 bytes for a 5+ hour run. ``nats-server -l
    <file>`` makes nats-server own its log file directly. Fails on the
    pre-fix base (no ``log_path`` parameter exists at all)."""

    spec = nats_child_spec(log_path=r"C:\ProgramData\CivicCast\logs\nats.log")
    assert "-l" in spec.argv
    assert spec.argv[spec.argv.index("-l") + 1] == r"C:\ProgramData\CivicCast\logs\nats.log"


def test_nats_graceful_stop_substitutes_live_pid() -> None:
    spec = nats_child_spec(nats_server_path="nats-server")
    action = graceful_stop_action(spec, pid=4321)
    assert action.kind == "argv"
    assert action.argv == ["nats-server", "--signal", "ldm=4321"]


def test_nats_graceful_stop_pid_changes_with_the_live_child() -> None:
    spec = nats_child_spec()
    a1 = graceful_stop_action(spec, pid=111)
    a2 = graceful_stop_action(spec, pid=222)
    assert a1.argv != a2.argv
    assert a1.argv is not None and "ldm=111" in a1.argv
    assert a2.argv is not None and "ldm=222" in a2.argv


# ---------------------------------------------------------------------------
# control plane: uvicorn + CREATE_NEW_PROCESS_GROUP + CTRL_BREAK_EVENT
# ---------------------------------------------------------------------------


def test_control_plane_child_spec_normal_mode_argv_and_group() -> None:
    spec = control_plane_child_spec(host="127.0.0.1", port=8000)
    assert spec.name == "control_plane"
    assert spec.new_process_group is True
    assert spec.argv[:6] == ["python", "-I", "-u", "-m", "uvicorn", "civiccast.app:create_app"]
    assert "--factory" in spec.argv
    assert "--host" in spec.argv and "127.0.0.1" in spec.argv
    assert "--port" in spec.argv and "8000" in spec.argv


def test_control_plane_child_spec_argv_is_unbuffered() -> None:
    """Diagnosability regression (2026-08-12, TESTER2 b5 evidence):
    control_plane.log was observed at 0 bytes for a 5+ hour run while the
    control plane demonstrably served healthy responses the whole time.
    ``-I`` implies ``-E``, which makes the interpreter ignore
    ``PYTHONUNBUFFERED`` -- so unbuffered stdio for this child can ONLY be
    forced with the explicit ``-u`` flag, never an env var. Fails on the
    pre-fix base (no ``-u`` in argv at all)."""

    spec = control_plane_child_spec()
    assert "-u" in spec.argv
    # -u must be an INTERPRETER flag (before -m), not swallowed as a
    # uvicorn/module argument.
    assert spec.argv.index("-u") < spec.argv.index("-m")


def test_control_plane_normal_mode_env_has_no_maintenance_vars() -> None:
    spec = control_plane_child_spec()
    assert "CIVICCAST_SUPERVISOR_MODE" not in spec.env
    assert "CIVICCAST_SUPERVISOR_MODE_CONTRACT" not in spec.env


def test_control_plane_maintenance_mode_sets_ratified_env_contract() -> None:
    spec = control_plane_child_spec(mode="maintenance")
    assert spec.env["CIVICCAST_SUPERVISOR_MODE"] == "maintenance"
    assert spec.env["CIVICCAST_SUPERVISOR_MODE_CONTRACT"] == "1"


def test_control_plane_graceful_stop_is_ctrl_break_to_the_live_pid() -> None:
    spec = control_plane_child_spec()
    action = graceful_stop_action(spec, pid=5555)
    assert action.kind == "ctrl_break_event"
    assert action.target_pid == 5555
    assert action.argv is None


def test_control_plane_env_always_carries_egress_work_dir() -> None:
    spec = control_plane_child_spec()
    assert "CIVICCAST_EGRESS_WORK_DIR" in spec.env
    assert spec.env["CIVICCAST_EGRESS_WORK_DIR"] == default_egress_work_dir()


def test_egress_work_dir_resolves_under_programdata_civiccast_data() -> None:
    resolved = default_egress_work_dir(program_data_root=r"C:\ProgramData")
    assert resolved == r"C:\ProgramData\CivicCast\data\egress"


def test_control_plane_egress_work_dir_can_be_overridden() -> None:
    spec = control_plane_child_spec(egress_work_dir=r"D:\custom\egress")
    assert spec.env["CIVICCAST_EGRESS_WORK_DIR"] == r"D:\custom\egress"


def test_control_plane_env_always_carries_upload_dir_normal_mode() -> None:
    """The other missing input on a native install: civiccast.app's
    _configure_upload_dir yields to any already-set CIVICCAST_UPLOAD_DIR, so
    it must be set unconditionally here, exactly like the egress work dir."""

    spec = control_plane_child_spec()
    assert "CIVICCAST_UPLOAD_DIR" in spec.env
    assert spec.env["CIVICCAST_UPLOAD_DIR"] == default_upload_dir()


def test_control_plane_env_always_carries_upload_dir_maintenance_mode() -> None:
    spec = control_plane_child_spec(mode="maintenance")
    assert "CIVICCAST_UPLOAD_DIR" in spec.env
    assert spec.env["CIVICCAST_UPLOAD_DIR"] == default_upload_dir()


def test_upload_dir_resolves_under_programdata_civiccast_data() -> None:
    resolved = default_upload_dir(program_data_root=r"C:\ProgramData")
    assert resolved == r"C:\ProgramData\CivicCast\data\uploads"


def test_control_plane_upload_dir_can_be_overridden() -> None:
    spec = control_plane_child_spec(upload_dir=r"D:\custom\uploads")
    assert spec.env["CIVICCAST_UPLOAD_DIR"] == r"D:\custom\uploads"


# ---------------------------------------------------------------------------
# Readiness: postgres SELECT 1 (injected)
# ---------------------------------------------------------------------------


def test_check_postgres_ready_true() -> None:
    result = check_postgres_ready(lambda: True)
    assert result.outcome == "ready"


def test_check_postgres_not_ready_false() -> None:
    result = check_postgres_ready(lambda: False)
    assert result.outcome == "not_ready"


def test_check_postgres_not_ready_on_raise() -> None:
    def _raiser() -> bool:
        raise ConnectionRefusedError("no listener")

    result = check_postgres_ready(_raiser)
    assert result.outcome == "not_ready"
    assert "no listener" in result.detail


# ---------------------------------------------------------------------------
# Readiness: nats authenticated JetStream publish+ack round-trip (injected)
# ---------------------------------------------------------------------------


def test_check_nats_ready_true() -> None:
    assert check_nats_ready(lambda: True).outcome == "ready"


def test_check_nats_not_ready_false() -> None:
    assert check_nats_ready(lambda: False).outcome == "not_ready"


def test_check_nats_not_ready_on_raise() -> None:
    def _raiser() -> bool:
        raise TimeoutError("no ack")

    result = check_nats_ready(_raiser)
    assert result.outcome == "not_ready"
    assert "no ack" in result.detail


# ---------------------------------------------------------------------------
# Readiness: control-plane normal-mode GET /health 200
# ---------------------------------------------------------------------------


def test_check_control_plane_ready_200() -> None:
    probe = ControlPlaneHealthProbe(status_code=200)
    assert check_control_plane_ready(lambda: probe).outcome == "ready"


def test_check_control_plane_not_ready_503() -> None:
    probe = ControlPlaneHealthProbe(status_code=503)
    assert check_control_plane_ready(lambda: probe).outcome == "not_ready"


def test_check_control_plane_not_ready_on_raise() -> None:
    def _raiser() -> ControlPlaneHealthProbe:
        raise ConnectionRefusedError("connection refused")

    result = check_control_plane_ready(_raiser)
    assert result.outcome == "not_ready"


# ---------------------------------------------------------------------------
# Readiness: RAT-001 maintenance-readiness gate, fail-closed matrix
# ---------------------------------------------------------------------------


def _maintenance_probe(**overrides: object) -> ControlPlaneHealthProbe:
    base: dict[str, object] = {
        "status_code": 200,
        "mode": "maintenance",
        "workers_started": False,
        "mutating_disabled": True,
        "mode_contract": 1,
    }
    base.update(overrides)
    return ControlPlaneHealthProbe(**base)  # type: ignore[arg-type]


def test_maintenance_ready_correct_attestation_is_ready() -> None:
    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe())
    assert result.outcome == "ready"


def test_maintenance_ready_fails_closed_when_mode_absent() -> None:
    """FALSIFICATION: a supervisor that treats a missing 'mode' field as
    trustworthy (e.g. defaulting an absent field to 'maintenance') would pass
    this test wrongly ready. An old control plane that has never heard of the
    RAT-001 attestation contract returns a body with no 'mode' key at all --
    this must refuse to advance the health gate, not assume good faith."""

    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(mode=None))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_mode_unknown() -> None:
    """FALSIFICATION: a contract-version mismatch reports mode='unknown'
    (per app.py's _supervisor_mode()); a gate that only excludes 'normal' and
    treats anything-not-normal as good would wrongly pass this."""

    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(mode="unknown"))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_mode_normal() -> None:
    """FALSIFICATION: the exact hole RAT-001 closes -- a control plane started
    WITHOUT the maintenance env reports mode='normal'; the freeze must hold,
    not silently pass because the endpoint answered 200."""

    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(mode="normal"))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_workers_started_true() -> None:
    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(workers_started=True))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_workers_started_none() -> None:
    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(workers_started=None))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_mutating_not_disabled() -> None:
    result = check_control_plane_maintenance_ready(
        lambda: _maintenance_probe(mutating_disabled=False)
    )
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_when_mode_contract_mismatched() -> None:
    """FALSIFICATION: a future incompatible attestation schema bumps
    mode_contract to 2; a gate that ignores the version number would treat an
    incompatible body as satisfied. It must not."""

    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(mode_contract=2))
    assert result.outcome == "not_ready"


def test_maintenance_ready_fails_closed_on_non_200() -> None:
    result = check_control_plane_maintenance_ready(lambda: _maintenance_probe(status_code=503))
    assert result.outcome == "not_ready"


def test_maintenance_ready_not_ready_on_raise() -> None:
    def _raiser() -> ControlPlaneHealthProbe:
        raise ConnectionRefusedError("down")

    assert check_control_plane_maintenance_ready(_raiser).outcome == "not_ready"


# ---------------------------------------------------------------------------
# poll_until_ready: ready / timeout, fake clock+sleep (no real waiting)
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _FakeSleep:
    def __init__(self, clock: _FakeClock, step: float = 1.0) -> None:
        self._clock = clock
        self._step = step
        self.calls = 0

    def __call__(self, seconds: float) -> None:
        self.calls += 1
        self._clock.now += self._step


def test_poll_until_ready_returns_ready_immediately_without_sleeping() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    result = poll_until_ready(
        lambda: check_postgres_ready(lambda: True),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
    )
    assert result.outcome == "ready"
    assert sleep.calls == 0


def test_poll_until_ready_becomes_ready_after_a_few_polls() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock, step=1.0)
    attempts = {"n": 0}

    def flaky_check() -> bool:
        attempts["n"] += 1
        return attempts["n"] >= 3

    result = poll_until_ready(
        lambda: check_postgres_ready(flaky_check),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
        poll_interval_seconds=1.0,
    )
    assert result.outcome == "ready"
    assert attempts["n"] == 3
    assert sleep.calls == 2


def test_poll_until_ready_times_out_within_budget_never_hanging() -> None:
    """FALSIFICATION: a poller that keeps retrying forever when the check
    never succeeds would never return -- this test bounds the number of
    sleep() calls the fake clock permits before the budget is exhausted, so
    an implementation that ignores the clock/budget and loops unboundedly
    fails this test (it would exceed the call cap and hang the test run)."""

    clock = _FakeClock()
    sleep = _FakeSleep(clock, step=10.0)
    result = poll_until_ready(
        lambda: check_postgres_ready(lambda: False),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
        poll_interval_seconds=10.0,
    )
    assert result.outcome == "timeout"
    # 60s budget / 10s step -> at most 6-7 sleeps, never unbounded.
    assert 1 <= sleep.calls <= 7


def test_poll_until_ready_zero_budget_times_out_without_sleeping() -> None:
    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    result = poll_until_ready(
        lambda: check_postgres_ready(lambda: False),
        budget_seconds=0.0,
        clock=clock,
        sleep=sleep,
    )
    assert result.outcome == "timeout"
    assert sleep.calls == 0


def test_poll_until_ready_aborts_mid_poll_on_a_stop_request() -> None:
    """F1 (BLOCKER, 2026-07-31): a stop request must end the poll after the
    IN-FLIGHT probe attempt, not after the budget. Before this seam, one
    supervisor iteration could chain four budgets (60+30+30+60s) with a stop
    already requested -- longer than the 150s stop watchdog, which then fired
    mid-chain and hard-killed the postgres cluster.

    The outcome must be ``aborted``, DISTINCT from ``timeout``: the budget was
    not exhausted and nothing was learned about the child's health, so reading
    this as a readiness failure would arm a restart backoff and log a WARNING
    for a stop we asked for."""

    clock = _FakeClock()
    sleep = _FakeSleep(clock, step=1.0)
    attempts = {"n": 0}
    stopping = {"now": False}

    def check_then_stop() -> bool:
        # The stop lands DURING the first attempt -- the seam must be re-checked
        # after check() returns, not only at the top of the loop.
        attempts["n"] += 1
        stopping["now"] = True
        return False

    result = poll_until_ready(
        lambda: check_postgres_ready(check_then_stop),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
        should_abort=lambda: stopping["now"],
    )

    assert result.outcome == "aborted"
    assert "stop request" in result.detail
    assert attempts["n"] == 1, "the abort must cost at most ONE in-flight probe attempt"
    assert sleep.calls == 0, "an aborted poll must not spend even one more poll interval"


def test_poll_until_ready_with_an_already_set_abort_attempts_no_probe() -> None:
    """A poll ENTERED with a stop already requested costs nothing at all -- the
    seam is checked at the top of the loop as well as after each check."""

    clock = _FakeClock()
    sleep = _FakeSleep(clock)
    attempts = {"n": 0}

    def counting_check() -> bool:
        attempts["n"] += 1
        return True  # would report READY if it were ever called

    result = poll_until_ready(
        lambda: check_postgres_ready(counting_check),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
        should_abort=lambda: True,
    )

    assert result.outcome == "aborted"
    assert attempts["n"] == 0
    assert sleep.calls == 0


def test_poll_until_ready_without_the_abort_seam_is_unchanged() -> None:
    """The seam is OPTIONAL: omitting it keeps the exact pre-F1 budget-only
    behaviour, so every existing caller is untouched."""

    clock = _FakeClock()
    sleep = _FakeSleep(clock, step=10.0)
    result = poll_until_ready(
        lambda: check_postgres_ready(lambda: False),
        budget_seconds=60.0,
        clock=clock,
        sleep=sleep,
        poll_interval_seconds=10.0,
    )
    assert result.outcome == "timeout"


# ---------------------------------------------------------------------------
# D5 restart backoff + jitter bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rng_value", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("attempt", [0, 1, 2, 3, 5, 10])
def test_backoff_with_jitter_stays_within_plus_minus_20_percent(
    rng_value: float, attempt: int
) -> None:
    initial, maximum, jitter = 1.0, 30.0, 0.20
    base = backoff_base_seconds(attempt, initial, maximum)
    delay = backoff_with_jitter(
        attempt,
        initial_seconds=initial,
        max_seconds=maximum,
        jitter_fraction=jitter,
        rng=lambda: rng_value,
    )
    assert base * (1 - jitter) - 1e-9 <= delay <= base * (1 + jitter) + 1e-9


def test_backoff_with_jitter_zero_jitter_returns_exact_base() -> None:
    delay = backoff_with_jitter(
        3, initial_seconds=1.0, max_seconds=30.0, jitter_fraction=0.0, rng=lambda: 0.5
    )
    assert delay == backoff_base_seconds(3, 1.0, 30.0)


def test_backoff_with_jitter_never_negative() -> None:
    delay = backoff_with_jitter(
        0, initial_seconds=1.0, max_seconds=30.0, jitter_fraction=1.0, rng=lambda: 0.0
    )
    assert delay >= 0.0


def test_backoff_with_jitter_capped_at_max_plus_jitter() -> None:
    delay = backoff_with_jitter(
        50, initial_seconds=1.0, max_seconds=30.0, jitter_fraction=0.20, rng=lambda: 1.0
    )
    assert delay == pytest.approx(30.0 * 1.20)


# ---------------------------------------------------------------------------
# D5 restart-storm predicate (reuses states.is_restart_storm via SupervisorConfig)
# ---------------------------------------------------------------------------


def test_restart_storm_check_matches_config_thresholds() -> None:
    config = SupervisorConfig()
    epochs = [float(i) for i in range(5)]  # 5 restarts at t=0..4
    assert restart_storm_check(epochs, now=4.0, config=config) is True


def test_restart_storm_check_false_under_threshold() -> None:
    config = SupervisorConfig()
    epochs = [0.0, 1.0, 2.0]
    assert restart_storm_check(epochs, now=2.0, config=config) is False


def test_restart_storm_check_false_when_restarts_outside_window() -> None:
    """FALSIFICATION: 5 restarts exist in the history, but only after a large
    gap that pushes the first two outside the trailing window -- a predicate
    that counts ALL history rather than the trailing window would wrongly
    report a storm."""

    config = SupervisorConfig()
    epochs = [0.0, 1.0, 700.0, 701.0, 702.0]
    assert restart_storm_check(epochs, now=702.0, config=config) is False


def test_restart_storm_check_uses_custom_config_thresholds() -> None:
    config = SupervisorConfig(restart_storm_threshold=2, restart_storm_window_seconds=10.0)
    assert restart_storm_check([0.0, 1.0], now=1.0, config=config) is True
    assert restart_storm_check([0.0], now=1.0, config=config) is False


# ---------------------------------------------------------------------------
# CC-WS5-003 -- read_postmaster_pid (pure pidfile reader)
# ---------------------------------------------------------------------------


def test_read_postmaster_pid_valid_pidfile_returns_first_line_pid(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "postmaster.pid").write_text("12345\n", encoding="utf-8")
    assert read_postmaster_pid(str(tmp_path)) == 12345


def test_read_postmaster_pid_missing_file_returns_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # No postmaster.pid written into tmp_path.
    assert read_postmaster_pid(str(tmp_path)) is None


def test_read_postmaster_pid_empty_file_returns_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "postmaster.pid").write_text("", encoding="utf-8")
    assert read_postmaster_pid(str(tmp_path)) is None


def test_read_postmaster_pid_garbage_first_line_returns_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "postmaster.pid").write_text("not-a-pid\n5432\n", encoding="utf-8")
    assert read_postmaster_pid(str(tmp_path)) is None


def test_read_postmaster_pid_real_format_multiline_returns_first_line_pid(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The real PostgreSQL postmaster.pid: line 1 is the postmaster pid, followed
    # by the data dir, start epoch, port, socket dir, listen addr, shmem key.
    real = "\n".join(
        [
            "48927",
            "/var/lib/postgresql/data",
            "1721600000",
            "5432",
            "/tmp",
            "127.0.0.1",
            "  5432001   1",
        ]
    )
    (tmp_path / "postmaster.pid").write_text(real + "\n", encoding="utf-8")
    assert read_postmaster_pid(str(tmp_path)) == 48927
