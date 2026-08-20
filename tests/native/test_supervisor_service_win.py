# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-Win32 tests for civiccast.native.supervisor.service.

``win`` appears in this module's own filename (house convention, see
``tests/native/test_win_probes.py`` / ``test_supervisor_job_object_win.py``) so
``-k "not win"`` deselects it honestly. Skipped entirely on non-Windows; on
Windows these create a REAL named mutex and read its REAL DACL back, build the
REAL pywin32 ``ServiceFramework`` subclass, and spawn a REAL child process --
no fakes.

Two things are proven here that the pure suite cannot:

1. The singleton mutex's restrictive SDDL is really enforced by the kernel:
   the DACL reads back with SYSTEM + BUILTIN\\Administrators ACEs and NO
   Everyone (``;;;WD``) ACE. Mirrors the ``test_supervisor_job_object_win`` SD
   readback style, and asserts on SID markers rather than the literal "GA"
   (``ConvertSecurityDescriptorToStringSecurityDescriptor`` normalizes
   ``GENERIC_ALL`` to the object-specific mask on readback -- win_probes
   empirical caution). A UNIQUE object name is used (not the real global
   singleton) so the test never contends for / leaves held the production
   singleton, exactly as the job-object win test uses a unique job name.
2. The ``ServiceFramework`` subclass wires up with the ratified identity
   (``_svc_name_``/``_svc_display_name_``) and the ``SvcDoRun``/``SvcStop``
   methods -- its SHAPE, WITHOUT installing or running it under the SCM
   (instantiation needs ``RegisterServiceCtrlHandler`` under the SCM, so the
   class is introspected, never constructed).

Plus a real spawn/terminate smoke for the concrete child runner.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="Windows-only real Win32 service tests"),
]

if os.name == "nt":
    from civiccast.native.supervisor import service_host
    from civiccast.native.supervisor.children import ChildSpec
    from civiccast.native.supervisor.config import (
        DISPLAY_NAME,
        SERVICE_NAME,
        SINGLETON_MUTEX_SDDL,
    )
    from civiccast.native.supervisor.service import (
        SERVICE_DESCRIPTION,
        SupervisorService,
        Win32ChildProcessRunner,
        build_service_class,
        build_singleton_mutex,
        main,
    )


def _unique_mutex_name() -> str:
    return rf"Global\CivicCastSupervisorSingletonTest-{uuid.uuid4().hex}"


def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 5.0, interval_seconds: float = 0.1
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_seconds)
    return bool(predicate())


# ---------------------------------------------------------------------------
# Singleton mutex: real DACL readback (SYSTEM + Administrators only)
# ---------------------------------------------------------------------------


def test_singleton_mutex_carries_system_and_admins_only_sddl() -> None:
    """The singleton mutex the service acquires uses the SAME restrictive SDDL as
    WS4's runtime-owner mutex. Create it (a first, non-existing instance creates
    the object with the SD -- the DACL check only gates a SECOND open, per the
    win_probes empirical note) and read the DACL back."""

    mutex = build_singleton_mutex(name=_unique_mutex_name(), sddl=SINGLETON_MUTEX_SDDL)
    result = mutex.acquire()
    try:
        assert result.status in ("acquired", "acquired_abandoned"), result.detail
        sddl = mutex.read_dacl_sddl()
        assert ";;;SY)" in sddl, f"SYSTEM ACE missing from singleton DACL: {sddl}"
        assert ";;;BA)" in sddl, f"Administrators ACE missing from singleton DACL: {sddl}"
        assert ";;;WD)" not in sddl, f"Everyone (WD) ACE must be absent: {sddl}"
    finally:
        mutex.release()


def test_singleton_mutex_second_owner_is_refused() -> None:
    """FALSIFICATION of the singleton guarantee: once one owner holds the mutex, a
    SECOND owner is refused. A named mutex is re-entrant WITHIN the owning THREAD,
    so the second acquire must run on a SEPARATE thread to model a real second
    supervisor (a distinct process/thread), not the same thread re-acquiring its
    own handle. On an unelevated token the second open is DACL-denied (winerror 5);
    on a fully elevated token the DACL grants the open but WaitForSingleObject times
    out because the FIRST thread still owns it -- ``win_probes`` classifies both
    ACCESS_DENIED and WAIT_TIMEOUT as ``"denied"`` (see its module note). Either
    tier: the second owner never gets ``acquired``."""

    name = _unique_mutex_name()
    first = build_singleton_mutex(name=name, sddl=SINGLETON_MUTEX_SDDL)
    assert first.acquire().status in ("acquired", "acquired_abandoned")
    try:
        result: dict[str, str] = {}

        def _second_owner() -> None:
            second = build_singleton_mutex(name=name, sddl=SINGLETON_MUTEX_SDDL)
            status = second.acquire().status
            result["status"] = status
            if status in ("acquired", "acquired_abandoned"):
                second.release()  # only release what we actually took

        thread = threading.Thread(target=_second_owner, name="civiccast-second-owner")
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive(), "second-owner thread did not finish within 10s"
        assert result.get("status") == "denied", (
            f"singleton violated: a second owner got {result.get('status')!r}, not 'denied'"
        )
    finally:
        first.release()


# ---------------------------------------------------------------------------
# ServiceFramework class SHAPE (no install, no SCM run)
# ---------------------------------------------------------------------------


def test_service_framework_class_has_ratified_identity_and_lifecycle_methods() -> None:
    import win32serviceutil  # type: ignore[import-not-found]

    def _factory(_logger: object) -> SupervisorService:  # pragma: no cover - never called
        raise AssertionError("service_factory must not run in a shape-only test")

    cls = build_service_class(service_factory=_factory)  # type: ignore[arg-type]

    assert issubclass(cls, win32serviceutil.ServiceFramework)
    assert cls._svc_name_ == SERVICE_NAME
    assert cls._svc_display_name_ == DISPLAY_NAME
    assert callable(cls.SvcDoRun)
    assert callable(cls.SvcStop)


def test_main_entry_point_builds_a_real_service_framework_class_for_the_scm() -> None:
    """CC-WS5-007 part 1: the SCM entry point builds the REAL pywin32
    ServiceFramework subclass and hands it to the command-line dispatcher. Proven
    here against real pywin32 (the class is a genuine
    win32serviceutil.ServiceFramework subclass with the ratified identity),
    stopping short of actually calling HandleCommandLine -- real SCM registration
    needs the SCM/an elevated host and is VM-bound (evidence/PENDING.md). The
    default class_builder (build_service_class) runs for real; only the
    command-line handler is faked so no install/remove touches the machine."""

    import win32serviceutil  # type: ignore[import-not-found]

    captured: dict[str, object] = {}

    def fake_handler(service_class: type, argv: list[str] | None) -> int:
        captured["class"] = service_class
        captured["argv"] = argv
        return 0

    def dummy_factory(_logger: object) -> object:  # pragma: no cover - never invoked
        raise AssertionError("service_factory must not run in an SCM-verb parse")

    rc = main(
        ["install"],
        service_factory=dummy_factory,  # type: ignore[arg-type]
        command_line_handler=fake_handler,
    )

    assert rc == 0
    built = captured["class"]
    assert isinstance(built, type)
    assert issubclass(built, win32serviceutil.ServiceFramework)
    assert built._svc_name_ == SERVICE_NAME
    assert captured["argv"] == ["install"]


# ---------------------------------------------------------------------------
# CC-WS5-007 (CRITICAL): the SCM-registered class must be MODULE-LEVEL and
# import-resolvable by the separate SCM host process. A function-local class
# persists a class string the host cannot resolve, so the service never starts.
# ---------------------------------------------------------------------------


def _class_string_resolves_to_the_same_class(cls: type) -> bool:
    """Reproduce what the SCM host process does: take pywin32's persisted service
    class string (``module.name``), import that module in a fresh namespace, and
    getattr the name. True iff it resolves back to the SAME class object -- i.e.
    the class is a MODULE-GLOBAL the host can find. A function-local class fails
    this (its persisted module has no such global)."""

    import win32serviceutil  # type: ignore[import-not-found]

    class_string = win32serviceutil.GetServiceClassString(cls)
    module_name, _, attr = class_string.rpartition(".")
    try:
        module = import_module(module_name)
    except ImportError:
        return False
    return getattr(module, attr, None) is cls


def test_registered_service_class_string_resolves_across_a_fresh_import() -> None:
    """CC-WS5-007, the auditor's required separate-process falsification: pywin32
    persists the SCM service class as ``module + cls.__name__`` and the SCM HOST
    (pythonservice.exe, a SEPARATE process) resolves it by importing the module
    and getattr'ing the name. The MODULE-LEVEL ``service_host`` class MUST resolve;
    the old FUNCTION-LOCAL ``build_service_class`` class must NOT (its persisted
    string names no module-global class, so the host finds nothing and the service
    cannot start). RED against the old shape, GREEN against the new one -- in one
    assertion pair."""

    # GREEN: the module-level registered class resolves to an importable global.
    assert _class_string_resolves_to_the_same_class(service_host.CivicCastSupervisorService)

    # RED against the old shape: the function-local class does NOT resolve.
    def _factory(_logger: object) -> SupervisorService:  # pragma: no cover - never called
        raise AssertionError("factory must not run in a class-string resolution test")

    local_cls = build_service_class(service_factory=_factory)  # type: ignore[arg-type]
    assert not _class_string_resolves_to_the_same_class(local_cls)


def test_service_host_class_has_ratified_identity_and_lifecycle_methods() -> None:
    """The module-level host class is a real ``ServiceFramework`` subclass carrying
    the ratified identity (name/display/description) and the SCM lifecycle
    methods -- introspected, never constructed (instantiation needs the SCM)."""

    import win32serviceutil  # type: ignore[import-not-found]

    cls = service_host.CivicCastSupervisorService
    assert issubclass(cls, win32serviceutil.ServiceFramework)
    assert cls._svc_name_ == SERVICE_NAME
    assert cls._svc_display_name_ == DISPLAY_NAME
    assert cls._svc_description_ == SERVICE_DESCRIPTION
    assert callable(cls.SvcDoRun)
    assert callable(cls.SvcStop)


def test_svc_do_run_builds_dependencies_in_the_host_process() -> None:
    """CC-WS5-007: ``SvcDoRun`` assembles the production service IN THIS (host)
    process via the module-level provider -- NOT from an installer closure that
    cannot cross the process boundary. Proven with a fake provider: the singleton
    is acquired, the service is BUILT in-process, run, and the singleton released.
    (The class is created via ``__new__`` so the SCM-only ``ServiceFramework``
    ``__init__``/``RegisterServiceCtrlHandler`` is bypassed.)"""

    recorded: dict[str, bool] = {}

    class _FakeService:
        def run(self) -> None:
            recorded["ran"] = True

    def fake_factory(_logger: logging.Logger) -> _FakeService:
        recorded["built"] = True
        return _FakeService()

    class _FakeSingleton:
        def acquire(self) -> SimpleNamespace:
            recorded["acquired"] = True
            return SimpleNamespace(status="acquired", detail="ok")

        def release(self) -> None:
            recorded["released"] = True

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    svc._service = None
    svc._singleton = None

    with pytest.MonkeyPatch.context() as mp:
        # BLOCKER #48: DATABASE_URL bridging is this module's own concern
        # (tests/native/test_service_env.py + test_service_env_win.py) --
        # neutralized here so this wiring test isn't coupled to registry state.
        mp.setattr(service_host, "ensure_database_url_env", lambda: None)
        mp.setattr(service_host, "_service_factory", fake_factory)
        mp.setattr(service_host, "build_singleton_mutex", lambda: _FakeSingleton())
        mp.setattr(service_host, "configure_logging", lambda: logging.getLogger("test.host"))
        svc.SvcDoRun()

    assert recorded == {"acquired": True, "built": True, "ran": True, "released": True}
    assert svc._service is not None  # assembled in-process, not a missing closure


def test_svc_do_run_fails_loudly_in_the_host_process_when_the_provider_raises() -> None:
    """CC-WS5-007: the disclosed VM provider raises ``NotImplementedError``; because
    ``SvcDoRun`` calls it IN-PROCESS, that failure surfaces loudly HERE (not as a
    silent missing cross-process closure) and the singleton is still released."""

    released: dict[str, bool] = {}

    def raising_factory(_logger: logging.Logger) -> object:
        raise NotImplementedError("VM-bound dependency provider")

    class _FakeSingleton:
        def acquire(self) -> SimpleNamespace:
            return SimpleNamespace(status="acquired", detail="ok")

        def release(self) -> None:
            released["released"] = True

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    svc._service = None
    svc._singleton = None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_host, "ensure_database_url_env", lambda: None)
        mp.setattr(service_host, "_service_factory", raising_factory)
        mp.setattr(service_host, "build_singleton_mutex", lambda: _FakeSingleton())
        mp.setattr(service_host, "configure_logging", lambda: logging.getLogger("test.host"))
        with pytest.raises(NotImplementedError, match="VM-bound"):
            svc.SvcDoRun()

    assert released.get("released") is True  # released even when the build fails


def test_svc_stop_requests_a_graceful_stop_without_touching_the_scm() -> None:
    """``SvcStop`` forwards to the running service's ``request_stop`` (and signals
    the SCM stop event). Proven via ``__new__`` with a fake service + a stubbed
    ``ReportServiceStatus``/event so no SCM handle is needed."""

    stopped: dict[str, bool] = {}

    class _FakeService:
        def request_stop(self) -> None:
            stopped["requested"] = True

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    svc._service = _FakeService()
    svc._svc_stop_event = None
    svc.ReportServiceStatus = lambda _status: None  # type: ignore[method-assign]

    with pytest.MonkeyPatch.context() as mp:
        import win32event  # type: ignore[import-not-found]

        mp.setattr(win32event, "SetEvent", lambda _evt: None)
        svc.SvcStop()

    assert stopped.get("requested") is True
    svc._disarm_stop_watchdog()  # SvcStop arms a real timer; do not leak it


# ---------------------------------------------------------------------------
# SvcStop watchdog wiring (gauntlet run 17: SERVICE_STOP_PENDING forever)
# ---------------------------------------------------------------------------
#
# The StopWatchdog mechanism itself (fire/disarm/idempotency/timeout value) is
# proven on any OS in tests/native/test_supervisor_service.py. What can only be
# proven HERE is the WIRING into the real pywin32 ServiceFramework subclass the
# SCM actually hosts: SvcStop arms it, SvcDoRun disarms it, and the disarm is
# the OUTERMOST finally so the watchdog is genuinely a last resort.


def test_svc_stop_arms_the_stop_watchdog() -> None:
    """Run 17: SvcStop reported STOP_PENDING and the host then never reached
    STOPPED, because nothing bounded the time SvcDoRun could take. SvcStop must
    now arm the watchdog, and must arm it BEFORE requesting the stop -- the
    bound has to cover the whole chain, including its first step.

    FALSIFICATION: fails against the pre-fix tree, where SvcStop arms nothing."""

    order: list[str] = []

    class _FakeService:
        stop_position = "not-stopping"

        def request_stop(self) -> None:
            order.append("request_stop")

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    svc._service = _FakeService()
    svc._svc_stop_event = None
    svc.ReportServiceStatus = lambda _status: None  # type: ignore[method-assign]

    with pytest.MonkeyPatch.context() as mp:
        import win32event  # type: ignore[import-not-found]

        mp.setattr(win32event, "SetEvent", lambda _evt: None)
        real_build = service_host.build_stop_watchdog

        def recording_build(position, **kwargs):  # type: ignore[no-untyped-def]
            order.append("arm_watchdog")
            return real_build(position, **kwargs)

        mp.setattr(service_host, "build_stop_watchdog", recording_build)
        svc.SvcStop()

    try:
        assert svc._stop_watchdog is not None, (
            "SvcStop must arm a stop watchdog so the SCM cannot be left in "
            "STOP_PENDING forever (gauntlet run 17)"
        )
        assert svc._stop_watchdog.armed is True
        assert order == ["arm_watchdog", "request_stop"], (
            f"the watchdog must be armed BEFORE the stop is requested; got {order}"
        )
        # The position probe must read the LIVE service, not a snapshot.
        assert svc._stop_chain_position() == "not-stopping"
    finally:
        svc._disarm_stop_watchdog()


def test_svc_stop_arming_twice_does_not_stack_watchdogs() -> None:
    """The SCM may deliver a second stop control. The second SvcStop must reuse
    the armed watchdog, or one disarm would leave a live timer behind that
    force-exits a perfectly healthy host."""

    class _FakeService:
        stop_position = "stop-requested"

        def request_stop(self) -> None:
            return None

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    svc._service = _FakeService()
    svc._svc_stop_event = None
    svc.ReportServiceStatus = lambda _status: None  # type: ignore[method-assign]

    with pytest.MonkeyPatch.context() as mp:
        import win32event  # type: ignore[import-not-found]

        mp.setattr(win32event, "SetEvent", lambda _evt: None)
        svc.SvcStop()
        first = svc._stop_watchdog
        svc.SvcStop()
        second = svc._stop_watchdog

    try:
        assert first is second is not None
    finally:
        svc._disarm_stop_watchdog()
    assert svc._stop_watchdog is None


def test_svc_do_run_disarms_the_watchdog_last_on_every_exit_path() -> None:
    """The watchdog must be disarmed by SvcDoRun's OUTERMOST finally: after the
    singleton release, and on the raising path and the singleton-refusal path
    too. A disarm that only runs on the happy path would leave a live
    force-exit timer armed on exactly the failure paths that need bounding
    least -- and one that ran BEFORE the remaining teardown would stop being a
    last resort.

    FALSIFICATION: fails against the pre-fix tree (no _disarm_stop_watchdog)."""

    disarm_order: list[str] = []

    class _RecordingSingleton:
        def acquire(self) -> SimpleNamespace:
            return SimpleNamespace(status="acquired", detail="ok")

        def release(self) -> None:
            disarm_order.append("singleton.release")

    class _FakeService:
        stop_position = "stop-chain-complete"

        def run(self) -> None:
            disarm_order.append("service.run")

    def make_svc() -> object:
        svc = service_host.CivicCastSupervisorService.__new__(
            service_host.CivicCastSupervisorService
        )
        svc._service = None
        svc._singleton = None
        return svc

    # (a) happy path: disarm runs AFTER singleton.release
    svc = make_svc()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service_host, "ensure_database_url_env", lambda: None)
        mp.setattr(service_host, "_service_factory", lambda _logger: _FakeService())
        mp.setattr(service_host, "build_singleton_mutex", lambda: _RecordingSingleton())
        mp.setattr(service_host, "configure_logging", lambda: logging.getLogger("test.host"))
        svc._stop_watchdog = _RecordingWatchdog(disarm_order)  # type: ignore[assignment]
        svc.SvcDoRun()

    assert disarm_order == ["service.run", "singleton.release", "watchdog.disarm"], (
        f"the watchdog disarm must be the LAST teardown step; got {disarm_order}"
    )
    assert svc._stop_watchdog is None

    # (b) raising factory: the watchdog is still disarmed
    disarm_order.clear()
    svc = make_svc()
    with pytest.MonkeyPatch.context() as mp:

        def raising_factory(_logger: logging.Logger) -> object:
            raise NotImplementedError("VM-bound dependency provider")

        mp.setattr(service_host, "ensure_database_url_env", lambda: None)
        mp.setattr(service_host, "_service_factory", raising_factory)
        mp.setattr(service_host, "build_singleton_mutex", lambda: _RecordingSingleton())
        mp.setattr(service_host, "configure_logging", lambda: logging.getLogger("test.host"))
        svc._stop_watchdog = _RecordingWatchdog(disarm_order)  # type: ignore[assignment]
        with pytest.raises(NotImplementedError):
            svc.SvcDoRun()

    assert disarm_order == ["singleton.release", "watchdog.disarm"]

    # (c) singleton refused: the early return still disarms
    disarm_order.clear()
    svc = make_svc()

    class _RefusingSingleton:
        def acquire(self) -> SimpleNamespace:
            return SimpleNamespace(status="refused", detail="another owner")

        def release(self) -> None:  # pragma: no cover - never reached on this path
            disarm_order.append("singleton.release")

    with pytest.MonkeyPatch.context() as mp:
        import servicemanager  # type: ignore[import-untyped]

        mp.setattr(service_host, "ensure_database_url_env", lambda: None)
        mp.setattr(service_host, "build_singleton_mutex", lambda: _RefusingSingleton())
        mp.setattr(service_host, "configure_logging", lambda: logging.getLogger("test.host"))
        mp.setattr(servicemanager, "LogErrorMsg", lambda _m: None)
        svc._stop_watchdog = _RecordingWatchdog(disarm_order)  # type: ignore[assignment]
        svc.SvcDoRun()

    assert disarm_order == ["watchdog.disarm"], (
        "the singleton-refusal early return must not leave a live force-exit timer armed"
    )


class _RecordingWatchdog:
    """Stands in for a real armed StopWatchdog so the ORDER of SvcDoRun's
    teardown steps is observable without a live timer."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def disarm(self) -> None:
        self._sink.append("watchdog.disarm")


# ---------------------------------------------------------------------------
# F2: the watchdog's SCM status report must be wired into BOTH service classes
# ---------------------------------------------------------------------------
#
# The StopWatchdog's own report-then-exit ordering is proven on any OS in
# tests/native/test_supervisor_service.py. What can only be proven HERE is that
# each real ServiceFramework subclass actually HANDS it a reporter bound to that
# instance's own ReportServiceStatus -- a watchdog built without one force-exits
# a host the SCM still believes is STOP_PENDING, which (with sc failureflag 1 +
# actions= restart/5000) is how a fired watchdog resurrected the service into
# the uninstall it fired to unblock.


def _assert_watchdog_reporter_wired(svc: object, *, label: str) -> None:
    """Arm the instance's watchdog through SvcStop, then prove the watchdog it
    built carries a reporter that reports SERVICE_STOPPED on THIS instance."""

    import win32service  # type: ignore[import-not-found]

    reported: list[int] = []
    svc._service = None  # type: ignore[attr-defined]
    svc._svc_stop_event = None  # type: ignore[attr-defined]
    svc.ReportServiceStatus = reported.append  # type: ignore[attr-defined]

    with pytest.MonkeyPatch.context() as mp:
        import win32event  # type: ignore[import-not-found]

        mp.setattr(win32event, "SetEvent", lambda _evt: None)
        svc.SvcStop()  # type: ignore[attr-defined]

    try:
        watchdog = svc._stop_watchdog  # type: ignore[attr-defined]
        assert watchdog is not None
        assert watchdog._report_stopped is not None, (
            f"{label}: the watchdog must be built with an SCM status reporter, or a "
            "force-exit leaves the SCM believing the service is still STOP_PENDING"
        )
        reported.clear()  # drop SvcStop's own STOP_PENDING report
        watchdog._report_stopped()
    finally:
        svc._disarm_stop_watchdog()  # type: ignore[attr-defined]

    assert reported == [win32service.SERVICE_STOPPED], (
        f"{label}: the reporter must report SERVICE_STOPPED on this instance's own "
        f"service handle; got {reported}"
    )


def test_f2_service_host_class_wires_the_watchdog_status_reporter() -> None:
    """The PRODUCTION class the SCM hosts (service_host)."""

    svc = service_host.CivicCastSupervisorService.__new__(service_host.CivicCastSupervisorService)
    _assert_watchdog_reporter_wired(svc, label="service_host.CivicCastSupervisorService")


def test_f2_build_service_class_wires_the_watchdog_status_reporter() -> None:
    """The OTHER ServiceFramework subclass in the tree (service.build_service_class).
    Both sites must be wired -- the prior batch's disarm fix had to touch both
    for the same reason, and a fix applied to only one of them is a fix that
    depends on which class a given install happens to host."""

    def _factory(_logger: object) -> SupervisorService:  # pragma: no cover - never called
        raise AssertionError("service_factory must not run in a wiring test")

    cls = build_service_class(service_factory=_factory)  # type: ignore[arg-type]
    # __new__ (not (), which the SCM-only ServiceFramework.__init__ requires) --
    # the same construction the watchdog tests above use. mypy cannot resolve
    # __new__ through a bare ``type``; the class is built at runtime.
    svc = cls.__new__(cls)  # type: ignore[call-overload]
    _assert_watchdog_reporter_wired(svc, label="build_service_class.CivicCastSupervisorService")


def test_main_default_path_registers_the_module_level_host_class() -> None:
    """CC-WS5-007: ``service.main`` on its DEFAULT path hands the SCM command-line
    handler the MODULE-LEVEL ``service_host.CivicCastSupervisorService`` -- the
    import-resolvable class -- not a function-local one. Only the command-line
    handler is faked so no install/remove touches the machine."""

    captured: dict[str, object] = {}

    def fake_handler(service_class: type, argv: list[str] | None) -> int:
        captured["class"] = service_class
        captured["argv"] = argv
        return 0

    rc = main(["install"], command_line_handler=fake_handler)

    assert rc == 0
    assert captured["class"] is service_host.CivicCastSupervisorService
    assert captured["argv"] == ["install"]


# ---------------------------------------------------------------------------
# Concrete runner: real spawn / is_alive / terminate smoke
# ---------------------------------------------------------------------------


def test_win32_child_runner_spawns_and_terminates_a_real_process() -> None:
    """The default (production) seams spawn a REAL child via subprocess.Popen and
    terminate it. Uses an infra child name (no new process group) so no console
    CTRL_BREAK is involved; the real CTRL_BREAK drain is exercised end to end by
    the control-plane integration, not asserted here."""

    runner = Win32ChildProcessRunner()
    spec = ChildSpec(
        name="nats",  # type: ignore[arg-type]
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        graceful_stop_kind="argv",
        graceful_stop_argv_template=["nats", "--signal", "ldm={pid}"],
        graceful_stop_deadline_seconds=15.0,
        readiness_budget_seconds=1.0,
    )

    handle = runner.spawn(spec)
    try:
        assert runner.is_alive(handle) is True
        runner.terminate(handle)
        assert _wait_until(lambda: not runner.is_alive(handle)), "child must exit after terminate()"
    finally:
        if runner.is_alive(handle):
            runner.terminate(handle)


def test_g3_default_popen_factory_redirects_child_output_to_its_log_file(tmp_path: Path) -> None:
    """G3: ``child_log_path`` was defined but had no caller -- under the SCM
    every child's stdout+stderr (including nats-server's OWN banner, which
    run 17's diagnosis needed and did not have) went to inherited-but-
    unobserved handles and was lost. The DEFAULT (production) popen factory
    must now redirect a REAL child's stdout+stderr into its per-child log
    file, FILE-BACKED (never a pipe -- this repo has already lost real runs
    to pipe inheritance), at the INJECTED log root (mirrors
    ``build_production_service`` threading ``layout.log_root`` through
    rather than re-deriving PROGRAMDATA at call time)."""

    log_root = tmp_path / "logs"
    runner = Win32ChildProcessRunner(log_root=log_root)
    spec = ChildSpec(
        name="nats",  # type: ignore[arg-type]
        argv=[
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('g3-stdout-marker\\n'); sys.stdout.flush(); "
            "sys.stderr.write('g3-stderr-marker\\n'); sys.stderr.flush()",
        ],
        graceful_stop_kind="argv",
        graceful_stop_argv_template=["nats", "--signal", "ldm={pid}"],
        graceful_stop_deadline_seconds=15.0,
        readiness_budget_seconds=1.0,
    )

    handle = runner.spawn(spec)
    try:
        assert _wait_until(lambda: not runner.is_alive(handle)), "the marker-writer child must exit"
    finally:
        if runner.is_alive(handle):
            runner.terminate(handle)

    log_path = log_root / "nats.log"
    assert log_path.exists(), "the per-child log file must exist under the INJECTED log root"
    content = log_path.read_text(encoding="utf-8", errors="replace")
    assert "g3-stdout-marker" in content, "stdout must be captured in the per-child log file"
    assert "g3-stderr-marker" in content, "stderr must be captured in the per-child log file"
