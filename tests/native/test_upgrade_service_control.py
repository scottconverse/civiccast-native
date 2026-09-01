# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-4 tests for the D3 upgrade engine's three service-control seams.

These prove the LOGIC of the drain / maintenance-health / service-stop seams
(:mod:`civiccast.native.upgrade.service_control`) with fakes injected at the
true OS/DB boundary (SCM, the control pipe, the ``/health`` probe, and the WS2
``snapshot_tables`` digest). The real Win32/Postgres round trips those seams
wrap are the WP-5 live-matrix boundary; here every primitive is a fake, so the
tests exercise the real poll/quiescence/attestation logic, never Win32.

Red-first: written before the seams were wired (WP-3 left them raising
``NotImplementedError`` via ``__main__._resolve_service_control_seams``).
"""

from __future__ import annotations

import subprocess

import pytest

from civiccast.native.supervisor.children import ControlPlaneHealthProbe
from civiccast.native.upgrade.models import UpgradeContext
from civiccast.native.upgrade.service_control import (
    _real_snapshot_digest,
    build_drain_seam,
    build_health_gate_seam,
    build_maintenance_ready_probe,
    build_stop_service_seam,
    classify_writers_active,
    resolve_service_control_seams,
)


class _FakeClock:
    """A monotonic clock a test drives forward one ``tick`` per ``sleep``."""

    def __init__(self) -> None:
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# classify_writers_active — the pure control-pipe status classifier
# ---------------------------------------------------------------------------


def test_classify_writers_active_true_when_workers_permitted() -> None:
    reply = {
        "v": 1,
        "cmd": "status",
        "result": "ok",
        "data": {"state": "ready", "workers_permitted": True},
    }
    assert classify_writers_active(reply) is True


def test_classify_writers_active_false_when_workers_not_permitted() -> None:
    # maintenance / stopping / blocked => workers_permitted False => drained.
    reply = {
        "v": 1,
        "cmd": "status",
        "result": "ok",
        "data": {"state": "maintenance", "workers_permitted": False},
    }
    assert classify_writers_active(reply) is False


def test_classify_writers_active_none_on_non_ok_result() -> None:
    reply = {"v": 1, "cmd": "status", "result": "denied", "detail": "nope"}
    assert classify_writers_active(reply) is None


def test_classify_writers_active_none_on_missing_field() -> None:
    reply = {"v": 1, "cmd": "status", "result": "ok", "data": {"state": "ready"}}
    assert classify_writers_active(reply) is None


# ---------------------------------------------------------------------------
# drain seam
# ---------------------------------------------------------------------------


def _drain(
    writers_active_probe,
    snapshot_digest,
    *,
    clock,
    drain_budget_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
    settle_seconds: float = 0.5,
    quiescence_attempts: int = 3,
):
    return build_drain_seam(
        writers_active_probe=writers_active_probe,
        snapshot_digest=snapshot_digest,
        clock=clock.clock,
        sleep=clock.sleep,
        drain_budget_seconds=drain_budget_seconds,
        poll_interval_seconds=poll_interval_seconds,
        settle_seconds=settle_seconds,
        quiescence_attempts=quiescence_attempts,
    )


def test_drain_true_when_drained_and_quiescent() -> None:
    clock = _FakeClock()
    snaps = ["digestA", "digestA"]
    seam = _drain(lambda: False, lambda: snaps.pop(0), clock=clock)
    assert seam() is True


def test_drain_waits_for_writers_then_confirms() -> None:
    clock = _FakeClock()
    active = [True, True, False]  # drains on the third poll
    snaps = iter(["s", "s"])
    seam = _drain(lambda: active.pop(0), lambda: next(snaps), clock=clock)
    assert seam() is True
    assert active == []  # every pre-drain poll was consumed


def test_drain_false_when_writers_never_drain() -> None:
    clock = _FakeClock()
    snapshot_calls = []

    def _snap() -> str:
        snapshot_calls.append(1)
        return "s"

    seam = _drain(lambda: True, _snap, clock=clock, drain_budget_seconds=5.0)
    assert seam() is False
    # Quiescence is never even sampled if writers never drained (fail-closed).
    assert snapshot_calls == []


def test_drain_false_when_writes_still_landing() -> None:
    clock = _FakeClock()
    counter = [0]

    def _snap() -> str:
        counter[0] += 1
        return f"changing-{counter[0]}"  # every read differs => not quiescent

    seam = _drain(lambda: False, _snap, clock=clock, quiescence_attempts=3)
    assert seam() is False
    assert counter[0] == 6  # 2 snapshots x 3 attempts, all mismatching


def test_drain_retries_quiescence_then_settles() -> None:
    clock = _FakeClock()
    # attempt 1: A != B (write landed mid-settle); attempt 2: C == C (settled).
    values = iter(["A", "B", "C", "C"])
    seam = _drain(lambda: False, lambda: next(values), clock=clock, quiescence_attempts=3)
    assert seam() is True


def test_drain_probe_none_is_not_drained_fail_closed() -> None:
    clock = _FakeClock()
    seam = _drain(lambda: None, lambda: "s", clock=clock, drain_budget_seconds=3.0)
    # An unreadable status is never confirmed-drained; budget exhausts => False.
    assert seam() is False


# ---------------------------------------------------------------------------
# maintenance-ready probe — reuses check_control_plane_maintenance_ready
# ---------------------------------------------------------------------------


def _probe_from(**fields) -> bool:
    health_check = lambda: ControlPlaneHealthProbe(**fields)  # noqa: E731
    return build_maintenance_ready_probe(health_check)()


def test_maintenance_ready_true_on_full_attestation() -> None:
    assert (
        _probe_from(
            status_code=200,
            mode="maintenance",
            workers_started=False,
            mutating_disabled=True,
            mode_contract=1,
        )
        is True
    )


@pytest.mark.parametrize(
    "fields",
    [
        {
            "status_code": 500,
            "mode": "maintenance",
            "workers_started": False,
            "mutating_disabled": True,
            "mode_contract": 1,
        },
        {
            "status_code": 200,
            "mode": "normal",
            "workers_started": False,
            "mutating_disabled": True,
            "mode_contract": 1,
        },
        {
            "status_code": 200,
            "mode": "maintenance",
            "workers_started": True,
            "mutating_disabled": True,
            "mode_contract": 1,
        },
        {
            "status_code": 200,
            "mode": "maintenance",
            "workers_started": False,
            "mutating_disabled": False,
            "mode_contract": 1,
        },
        {
            "status_code": 200,
            "mode": "maintenance",
            "workers_started": False,
            "mutating_disabled": True,
            "mode_contract": 2,
        },
        {"status_code": 200},  # unattested
    ],
)
def test_maintenance_ready_false_on_any_deviation(fields) -> None:
    assert _probe_from(**fields) is False


# ---------------------------------------------------------------------------
# health-gate seam
# ---------------------------------------------------------------------------


def test_health_gate_true_when_ready_after_start() -> None:
    clock = _FakeClock()
    events = []
    seam = build_health_gate_seam(
        ensure_started=lambda: events.append("start"),
        maintenance_ready_probe=lambda: (events.append("probe"), True)[1],
        clock=clock.clock,
        sleep=clock.sleep,
        health_budget_seconds=30.0,
        poll_interval_seconds=1.0,
    )
    assert seam() is True
    # The service is (idempotently) started BEFORE the first readiness probe.
    assert events[0] == "start"
    assert "probe" in events


def test_health_gate_polls_until_ready() -> None:
    clock = _FakeClock()
    ready = [False, False, True]
    seam = build_health_gate_seam(
        ensure_started=lambda: None,
        maintenance_ready_probe=lambda: ready.pop(0),
        clock=clock.clock,
        sleep=clock.sleep,
        health_budget_seconds=30.0,
        poll_interval_seconds=1.0,
    )
    assert seam() is True
    assert ready == []


def test_health_gate_false_when_never_ready() -> None:
    clock = _FakeClock()
    seam = build_health_gate_seam(
        ensure_started=lambda: None,
        maintenance_ready_probe=lambda: False,
        clock=clock.clock,
        sleep=clock.sleep,
        health_budget_seconds=5.0,
        poll_interval_seconds=1.0,
    )
    assert seam() is False


# ---------------------------------------------------------------------------
# stop-service seam
# ---------------------------------------------------------------------------


def test_stop_service_calls_scm_stop() -> None:
    called = []
    seam = build_stop_service_seam(scm_stop=lambda: called.append(1))
    seam()
    assert called == [1]


def test_stop_service_propagates_scm_failure() -> None:
    def _boom() -> None:
        raise RuntimeError("SCM stop failed")

    seam = build_stop_service_seam(scm_stop=_boom)
    with pytest.raises(RuntimeError, match="SCM stop failed"):
        seam()


# ---------------------------------------------------------------------------
# production resolution — the thing __main__ calls
# ---------------------------------------------------------------------------


def _ctx() -> UpgradeContext:
    return UpgradeContext(
        install_root=r"C:\Program Files\CivicCast (Native)",
        state_root=r"C:\ProgramData\CivicCast\upgrade",
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )


def test_resolve_returns_three_real_callables() -> None:
    drain, health, stop = resolve_service_control_seams(_ctx())
    assert callable(drain) and callable(health) and callable(stop)
    # The seams are the REAL production callables now, not the WP-3 stubs: they
    # are distinct objects and resolving them does not raise. (Invoking them
    # would cross the real SCM/pg boundary, which is the WP-5 live matrix.)
    assert drain is not health and health is not stop


# ---------------------------------------------------------------------------
# _real_service_registered_probe (install-only-refusal WP, 2026-07-30):
# distinguishes "definitely not registered" (False, provably no writers can
# be running under it) from "registered, or the SCM query itself is
# ambiguous" (None, stays fail-closed) -- grounded on the same `sc query`
# exit-code contract (0 == exists in any run state, 1060 ==
# ERROR_SERVICE_DOES_NOT_EXIST) that
# civiccast.native.win_probes._default_wsl_service_present already uses for
# the identical "is this Windows service registered" question (see that
# test module's parallel test_default_wsl_service_present_* suite).
# ---------------------------------------------------------------------------


def test_service_registered_probe_1060_is_definite_false() -> None:
    from civiccast.native.upgrade.service_control import _real_service_registered_probe

    def sc_absent(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1060, stdout=b"", stderr=b"does not exist")

    assert _real_service_registered_probe("CivicCastSupervisor", runner=sc_absent) is False


def test_service_registered_probe_exit0_is_none_not_true() -> None:
    """The service EXISTING says nothing about whether its control pipe is
    reachable -- only a definite ABSENCE is decisive here, so an exit-0
    (registered, in some run state) must stay None, never a bare True a
    caller could misread as "writers active"."""

    from civiccast.native.upgrade.service_control import _real_service_registered_probe

    def sc_present(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"STATE: 4 RUNNING", stderr=b"")

    assert _real_service_registered_probe("CivicCastSupervisor", runner=sc_present) is None


def test_service_registered_probe_other_exit_is_none() -> None:
    """A non-0, non-1060 exit (e.g. 5 Access Denied querying the SCM) is
    ambiguous -- we cannot conclude the service is absent -- so None."""

    from civiccast.native.upgrade.service_control import _real_service_registered_probe

    def sc_weird(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 5, stdout=b"", stderr=b"Access is denied")

    assert _real_service_registered_probe("CivicCastSupervisor", runner=sc_weird) is None


def test_service_registered_probe_timeout_is_none() -> None:
    from civiccast.native.upgrade.service_control import _real_service_registered_probe

    def sc_timeout(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, timeout=5.0)

    assert _real_service_registered_probe("CivicCastSupervisor", runner=sc_timeout) is None


def test_service_registered_probe_oserror_is_none() -> None:
    from civiccast.native.upgrade.service_control import _real_service_registered_probe

    def sc_oserror(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise OSError("sc.exe not found")

    assert _real_service_registered_probe("CivicCastSupervisor", runner=sc_oserror) is None


def test_service_registered_probe_queries_pinned_sc_exe_with_the_service_name() -> None:
    from civiccast.native.upgrade.service_control import SC_EXE, _real_service_registered_probe

    seen: list[list[str]] = []

    def spy(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1060, stdout=b"", stderr=b"")

    _real_service_registered_probe("CivicCastSupervisor", runner=spy)
    assert seen
    assert seen[0][0] == str(SC_EXE)
    assert seen[0][1:] == ["query", "CivicCastSupervisor"]


def test_service_stopped_probe_classifies_authoritative_scm_states() -> None:
    from civiccast.native.upgrade.service_control import _real_service_stopped_probe

    assert (
        _real_service_stopped_probe(
            query_status=lambda _name: (0, 1, 0, 0, 0, 0, 0), stopped_state=1
        )
        is True
    )
    assert (
        _real_service_stopped_probe(
            query_status=lambda _name: (0, 4, 0, 0, 0, 0, 0), stopped_state=1
        )
        is False
    )


def test_service_stopped_probe_keeps_unreadable_status_ambiguous() -> None:
    from civiccast.native.upgrade.service_control import _real_service_stopped_probe

    def unreadable(_name: str) -> tuple[int, ...]:
        raise OSError("SCM query failed")

    assert _real_service_stopped_probe(query_status=unreadable, stopped_state=1) is None


# ---------------------------------------------------------------------------
# _real_writers_active_probe's SCM short-circuit (install-only-refusal WP):
# a definite service-absent SCM answer must return False WITHOUT ever
# touching the control pipe; any other SCM answer must fall through to the
# EXACT pre-existing pipe-based behavior, unchanged.
# ---------------------------------------------------------------------------


def test_writers_active_probe_returns_false_immediately_when_service_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit-#35 fix: touching the pipe at all after a real uninstall is
    exactly what used to burn the whole drain budget (every connect attempt
    failed with a transport error, landing in the same fail-closed None
    bucket as a service that is merely unreachable). Proves the pipe is
    never even attempted by making a pipe-client construction attempt fail
    the test outright."""

    import civiccast.native.supervisor.control_client as control_client_module
    from civiccast.native.upgrade.service_control import _real_writers_active_probe

    def _must_not_be_called(**_kwargs: object) -> None:
        raise AssertionError(
            "the control pipe must not be touched when the SCM proves the service is absent"
        )

    monkeypatch.setattr(control_client_module, "build_control_client", _must_not_be_called)

    result = _real_writers_active_probe(service_registered_probe=lambda _name: False)
    assert result is False


def test_writers_active_probe_returns_false_immediately_when_registered_service_is_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install-over-existing stops the old service but deliberately preserves
    its registration so routing still recognizes a real upgrade. A definitive
    SCM STOPPED state is therefore quiescent and must not fall through to the
    now-offline control pipe."""

    import civiccast.native.supervisor.control_client as control_client_module
    from civiccast.native.upgrade.service_control import _real_writers_active_probe

    def _must_not_be_called(**_kwargs: object) -> None:
        raise AssertionError("the control pipe must not be touched for an SCM-STOPPED service")

    monkeypatch.setattr(control_client_module, "build_control_client", _must_not_be_called)

    result = _real_writers_active_probe(
        service_registered_probe=lambda _name: True,
        service_stopped_probe=lambda _name: True,
    )
    assert result is False


def test_writers_active_probe_does_not_trust_ambiguous_stopped_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a definitive STOPPED answer may short-circuit. An unreadable SCM
    state remains fail-closed and must use the authenticated control pipe."""

    import civiccast.native.supervisor.control_client as control_client_module
    from civiccast.native.upgrade.service_control import _real_writers_active_probe

    class _FakeClient:
        def status(self) -> dict[str, object]:
            return {"v": 1, "cmd": "status", "result": "ok", "data": {"workers_permitted": True}}

    monkeypatch.setattr(
        control_client_module, "build_control_client", lambda **_kwargs: _FakeClient()
    )
    result = _real_writers_active_probe(
        service_registered_probe=lambda _name: True,
        service_stopped_probe=lambda _name: None,
    )
    assert result is True


def test_writers_active_probe_falls_through_to_pipe_when_service_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registered service that is not definitively stopped must fall through
    unchanged to the pre-existing pipe-based check (never short-circuited)."""

    import civiccast.native.supervisor.control_client as control_client_module
    from civiccast.native.upgrade.service_control import _real_writers_active_probe

    class _FakeClient:
        def status(self) -> dict[str, object]:
            return {"v": 1, "cmd": "status", "result": "ok", "data": {"workers_permitted": True}}

    monkeypatch.setattr(
        control_client_module, "build_control_client", lambda **_kwargs: _FakeClient()
    )

    result = _real_writers_active_probe(
        service_registered_probe=lambda _name: True,
        service_stopped_probe=lambda _name: False,
    )
    assert result is True  # workers_permitted True => writers ARE active (not drained)


def test_writers_active_probe_falls_through_to_pipe_when_scm_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ambiguous SCM read (None) must ALSO fall through to the
    pre-existing pipe-based check -- only a DEFINITE absence short-circuits."""

    import civiccast.native.supervisor.control_client as control_client_module
    from civiccast.native.upgrade.service_control import _real_writers_active_probe

    class _FakeClient:
        def status(self) -> dict[str, object]:
            return {"v": 1, "cmd": "status", "result": "ok", "data": {"workers_permitted": False}}

    monkeypatch.setattr(
        control_client_module, "build_control_client", lambda **_kwargs: _FakeClient()
    )

    result = _real_writers_active_probe(
        service_registered_probe=lambda _name: None,
        service_stopped_probe=lambda _name: False,
    )
    assert result is False  # drained, via the pipe read, not the short-circuit


def test_real_snapshot_digest_normalizes_bare_postgresql_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """beta BLOCKER #51 regression: ``_real_snapshot_digest``'s create_engine
    call must receive the NORMALIZED url (+psycopg), not the bare
    ``postgresql://`` scheme the installer persists (which SQLAlchemy maps
    to the uninstalled psycopg2 dialect). Monkeypatches
    ``sqlalchemy.create_engine`` (the call boundary this seam owns) and
    ``civiccast.dr.backup.snapshot_tables`` (the boundary it delegates to),
    never internals -- no real DB round trip."""

    import sqlalchemy

    import civiccast.dr.backup as backup_module

    captured: dict[str, str] = {}

    class _FakeEngine:
        def dispose(self) -> None:
            pass

    def _fake_create_engine(url: str, **kwargs: object) -> _FakeEngine:
        captured["url"] = url
        return _FakeEngine()

    monkeypatch.setattr(sqlalchemy, "create_engine", _fake_create_engine)
    monkeypatch.setattr(backup_module, "snapshot_tables", lambda engine: [])

    digest = _real_snapshot_digest("postgresql://u:secret@127.0.0.1/db")

    assert isinstance(digest, str)
    assert captured["url"].startswith("postgresql+psycopg://")
    assert "secret" in captured["url"]  # password must survive, not be corrupted


def test_snapshot_engine_connect_timeout_pinned_against_env_tuning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sol audit 2026-08-09: the quiescence phase makes up to six snapshot
    connections after the drain deadline; CIVICCAST_DB_CONNECT_TIMEOUT=60
    would turn the designed 60s worst case into 360s. The call site pins its
    10s bound (red on 20ac2972, green on the pinned call)."""

    import sqlalchemy

    import civiccast.dr.backup as backup_module

    monkeypatch.setenv("CIVICCAST_DB_CONNECT_TIMEOUT", "60")

    captured: dict[str, object] = {}

    class _FakeEngine:
        def dispose(self) -> None:
            pass

    def _fake_create_engine(url: str, **kwargs: object) -> _FakeEngine:
        captured["kwargs"] = kwargs
        return _FakeEngine()

    monkeypatch.setattr(sqlalchemy, "create_engine", _fake_create_engine)
    monkeypatch.setattr(backup_module, "snapshot_tables", lambda engine: [])

    _real_snapshot_digest("postgresql://u:secret@127.0.0.1/db")

    assert captured["kwargs"]["connect_args"]["connect_timeout"] == 10
