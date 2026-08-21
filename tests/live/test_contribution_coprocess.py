# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3d — VDO.Ninja + coturn co-process supervision.

Covers civiccast.live.contribution.coprocess: settings env parsing (incl. the
typo-must-not-enable guard), the per-process poll lifecycle (blocked / running /
backed-off restart), co-process-down + TURN-unreachable alerts, diagnostics, the
run_forever loop, and the active-supervisor diagnostics snapshot. Process
starters + the TURN probe are injected — no real binaries are spawned.
"""

from __future__ import annotations

import pytest

from civiccast.live.contribution.coprocess import (
    ALERT_COPROCESS_DOWN,
    ALERT_TURN_UNREACHABLE,
    ContributionCoprocessSettings,
    ContributionCoprocessSupervisor,
    clear_active_supervisor,
    contribution_diagnostics_snapshot,
    contribution_turn_connectivity_test,
    set_active_supervisor,
)


class _FakeProc:
    _next_pid = 41000

    def __init__(self, args):
        self.args = args
        _FakeProc._next_pid += 1
        self.pid = _FakeProc._next_pid
        self.create_time = 1_234_567_890.0
        self._alive = True
        self.terminated = False

    def poll(self):
        return None if self._alive else 1

    def die(self):
        self._alive = False

    def terminate(self):
        self.terminated = True
        self._alive = False


class _Starter:
    def __init__(self):
        self.started: list[_FakeProc] = []

    def __call__(self, args):
        proc = _FakeProc(args)
        self.started.append(proc)
        return proc


def _settings(**kw) -> ContributionCoprocessSettings:
    base = {"enabled": True, "vdo_command": ("vdo",), "coturn_command": ("turnserver",)}
    base.update(kw)
    return ContributionCoprocessSettings(**base)


# --- settings ----------------------------------------------------------------


def test_settings_from_env_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CIVICCAST_REMOTE_CONTRIBUTION", raising=False)
    assert ContributionCoprocessSettings.from_env().enabled is False


def test_settings_typo_does_not_silently_enable(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION", "yes")
    with pytest.raises(ValueError, match="must be 'on' or 'off'"):
        ContributionCoprocessSettings.from_env()


def test_settings_parses_commands_and_turn(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_REMOTE_CONTRIBUTION", "on")
    monkeypatch.setenv("CIVICCAST_VDO_COMMAND", "node server.js --port 8443")
    monkeypatch.setenv("CIVICCAST_TURN_PORT", "3479")
    s = ContributionCoprocessSettings.from_env()
    assert s.enabled is True
    assert s.vdo_command == ("node", "server.js", "--port", "8443")
    assert s.turn_port == 3479


# --- per-process lifecycle ---------------------------------------------------


def test_blocked_when_command_missing() -> None:
    sup = ContributionCoprocessSupervisor(_settings(vdo_command=None, coturn_command=("t",)))
    sup.ensure_running()
    diag = sup.diagnostics()
    assert diag.vdo_process_up is False
    assert "not running" in diag.detail


def test_starts_and_reports_running() -> None:
    starter = _Starter()
    sup = ContributionCoprocessSupervisor(
        _settings(), process_starter=starter, turn_probe=lambda h, p: True
    )
    sup.ensure_running()
    diag = sup.diagnostics()
    assert diag.vdo_process_up and diag.coturn_process_up
    assert diag.turn_reachable is True
    assert len(starter.started) == 2  # vdo + coturn


def test_death_triggers_backoff_then_restart_and_alert() -> None:
    starter = _Starter()
    now = [100.0]
    alerts: list[tuple[str, str]] = []
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None),  # only vdo, to isolate
        process_starter=starter,
        monotonic=lambda: now[0],
        alert_hook=lambda k, d: alerts.append((k, d)),
        turn_probe=lambda h, p: True,
    )
    sup.ensure_running()
    assert starter.started[0].poll() is None  # running
    # Kill it; next tick must go to restarting + emit a co-process-down alert.
    starter.started[0].die()
    sup.ensure_running()
    assert any(k == ALERT_COPROCESS_DOWN for k, _ in alerts)
    assert sup.diagnostics().vdo_process_up is False
    # Before the 5s backoff elapses, still restarting (no new proc).
    now[0] += 1.0
    sup.ensure_running()
    assert len(starter.started) == 1
    # After backoff, it respawns.
    now[0] += 10.0
    sup.ensure_running()
    assert len(starter.started) == 2
    assert sup.diagnostics().vdo_process_up is True


def test_turn_unreachable_alerts_on_transition() -> None:
    starter = _Starter()
    alerts: list[tuple[str, str]] = []
    reachable = [True]
    sup = ContributionCoprocessSupervisor(
        _settings(),
        process_starter=starter,
        turn_probe=lambda h, p: reachable[0],
        alert_hook=lambda k, d: alerts.append((k, d)),
    )
    sup.ensure_running()
    assert not any(k == ALERT_TURN_UNREACHABLE for k, _ in alerts)
    reachable[0] = False
    sup.ensure_running()
    assert sum(k == ALERT_TURN_UNREACHABLE for k, _ in alerts) == 1
    # Stays unreachable: no duplicate alert (transition-only; the hub de-dupes too).
    sup.ensure_running()
    assert sum(k == ALERT_TURN_UNREACHABLE for k, _ in alerts) == 1


def test_diagnostics_disabled_is_honest() -> None:
    sup = ContributionCoprocessSupervisor(_settings(enabled=False))
    diag = sup.diagnostics()
    assert diag.turn_reachable is False
    assert "disabled" in diag.detail


def test_stop_terminates_when_no_identity() -> None:
    starter = _Starter()
    sup = ContributionCoprocessSupervisor(
        _settings(), process_starter=starter, turn_probe=lambda h, p: True
    )
    sup.ensure_running()
    procs = list(starter.started)
    sup.stop()
    assert all(p.terminated for p in procs)
    assert sup.diagnostics().vdo_process_up is False


def test_stop_uses_verify_and_kill_when_create_time_is_available(monkeypatch) -> None:
    import civiccast.live.contribution.coprocess as cp

    kill_calls: list[tuple[int, float]] = []
    starter = _Starter()

    def _fake_create_time(pid: int) -> float | None:
        for p in starter.started:
            if p.pid == pid:
                return p.create_time
        return None

    monkeypatch.setattr(cp, "_process_create_time", _fake_create_time)
    monkeypatch.setattr(
        cp,
        "verify_and_kill_process",
        lambda pid, ct: kill_calls.append((pid, ct)),
    )

    sup = ContributionCoprocessSupervisor(
        _settings(), process_starter=starter, turn_probe=lambda h, p: True
    )
    sup.ensure_running()
    procs = list(starter.started)
    sup.stop()

    # When create_time is available, the identity-safe path (verify_and_kill_process)
    # must be used — not proc.terminate().
    assert all(not p.terminated for p in procs), (
        "terminate() was called; verify_and_kill_process should have been used instead"
    )
    assert len(kill_calls) == len(procs), (
        f"Expected {len(procs)} verify_and_kill_process calls; got {len(kill_calls)}"
    )
    for proc in procs:
        assert any(pid == proc.pid and ct == proc.create_time for pid, ct in kill_calls), (
            f"Expected verify_and_kill_process({proc.pid!r}, {proc.create_time!r}) "
            f"but calls were {kill_calls!r}"
        )


# --- run_forever loop --------------------------------------------------------


class _StopAfter:
    def __init__(self, n: int) -> None:
        self.calls = 0
        self.ticks = 0
        self._n = n

    def is_set(self) -> bool:
        self.calls += 1
        return self.calls > self._n

    def wait(self, _seconds: float) -> None:
        self.ticks += 1


def test_run_forever_ticks_until_stopped() -> None:
    starter = _Starter()
    sup = ContributionCoprocessSupervisor(
        _settings(), process_starter=starter, turn_probe=lambda h, p: True
    )
    stop = _StopAfter(3)
    sup.run_forever(poll_seconds=0.01, stop_event=stop)
    assert stop.ticks == 3  # ticked 3 times then is_set() returned True


def test_run_forever_survives_a_tick_exception() -> None:
    boom = ContributionCoprocessSupervisor(_settings())

    def _raise() -> None:
        raise RuntimeError("kaboom")

    boom.ensure_running = _raise  # type: ignore[method-assign]
    stop = _StopAfter(2)
    boom.run_forever(poll_seconds=0.01, stop_event=stop)  # must not propagate
    assert stop.ticks == 2


# --- active-supervisor diagnostics snapshot ---------------------------------


def test_active_supervisor_snapshot() -> None:
    clear_active_supervisor()
    assert "not running" in contribution_diagnostics_snapshot().detail
    sup = ContributionCoprocessSupervisor(
        _settings(), process_starter=_Starter(), turn_probe=lambda h, p: True
    )
    sup.ensure_running()
    set_active_supervisor(sup)
    try:
        assert contribution_diagnostics_snapshot().vdo_process_up is True
    finally:
        clear_active_supervisor()


# --- external-TURN posture (owner-approved: documented external TURN, PR #9) -


def test_external_turn_is_probed_even_with_no_local_coturn_process() -> None:
    """coturn has no native Windows build (civiccast/installer/
    contribution_install.py); CIVICCAST_COTURN_COMMAND is left unset and the
    operator points CIVICCAST_TURN_HOST/PORT at a documented external server.
    The reachability probe must still run -- this was the bug: it used to be
    gated on a LOCAL coturn process being 'running', which can never happen
    when coturn_command is None, so the probe (and the alert) silently never
    fired for the exact posture PR #9 declared supported."""
    starter = _Starter()
    probed: list[tuple[str, int]] = []

    def probe(host: str, port: int) -> bool:
        probed.append((host, port))
        return True

    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None, turn_host="turn.example.org", turn_port=3478),
        process_starter=starter,
        turn_probe=probe,
    )
    sup.ensure_running()
    assert probed == [("turn.example.org", 3478)]
    diag = sup.diagnostics()
    assert diag.turn_reachable is True
    assert diag.coturn_process_up is False  # honest -- no local process, never claimed
    assert diag.turn_host == "turn.example.org"
    assert diag.turn_port == 3478
    assert "external (documented)" in diag.ice_summary


def test_external_turn_unreachable_still_alerts() -> None:
    alerts: list[tuple[str, str]] = []
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None),
        process_starter=_Starter(),
        turn_probe=lambda h, p: False,
        alert_hook=lambda k, d: alerts.append((k, d)),
    )
    sup.ensure_running()
    assert any(k == ALERT_TURN_UNREACHABLE for k, _ in alerts)


def test_diagnostics_healthy_for_external_turn_does_not_report_coturn_down() -> None:
    # Before the fix, a station correctly configured for external TURN would
    # show "one or more co-processes are not running" forever (coturn's local
    # process is never up by design) -- a false negative baked into the
    # honest posture. It must read as healthy once vdo is up and TURN reachable.
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None), process_starter=_Starter(), turn_probe=lambda h, p: True
    )
    sup.ensure_running()
    diag = sup.diagnostics()
    assert diag.detail == ""


def test_local_coturn_still_gates_the_probe_until_it_is_up() -> None:
    # When coturn IS locally managed (Linux/macOS) but hasn't started yet,
    # there is nothing to probe against -- unaffected by the external-TURN fix.
    sup = ContributionCoprocessSupervisor(
        _settings(vdo_command=None, coturn_command=("t-does-not-exist",)),
        turn_probe=lambda h, p: pytest.fail("must not probe before coturn is up"),
    )
    sup.ensure_running()
    diag = sup.diagnostics()
    assert diag.turn_reachable is False
    assert diag.coturn_process_up is False


# --- on-demand "Test TURN connectivity" (operator console button) -----------


def test_test_turn_connectivity_probes_immediately() -> None:
    reachable = [False]
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None), turn_probe=lambda h, p: reachable[0]
    )
    # No ensure_running() tick at all -- the button must not depend on the
    # background poll having run first.
    diag = sup.test_turn_connectivity()
    assert diag.turn_reachable is False

    reachable[0] = True
    diag = sup.test_turn_connectivity()
    assert diag.turn_reachable is True


def test_test_turn_connectivity_does_not_emit_an_alert() -> None:
    alerts: list[tuple[str, str]] = []
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None),
        turn_probe=lambda h, p: False,
        alert_hook=lambda k, d: alerts.append((k, d)),
    )
    sup.test_turn_connectivity()
    assert alerts == []


def test_active_supervisor_connectivity_test_snapshot() -> None:
    clear_active_supervisor()
    assert "not running" in contribution_turn_connectivity_test().detail
    sup = ContributionCoprocessSupervisor(
        _settings(coturn_command=None), turn_probe=lambda h, p: True
    )
    set_active_supervisor(sup)
    try:
        diag = contribution_turn_connectivity_test()
        assert diag.turn_reachable is True
    finally:
        clear_active_supervisor()
