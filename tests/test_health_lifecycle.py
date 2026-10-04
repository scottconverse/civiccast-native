# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Actual app-function lifecycle interleavings, with finite fake preparation."""

from __future__ import annotations

import ast
import inspect
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from civiccast.health_schema import HealthSchemaOwner
from civiccast.platform.worker_runtime import ThreadSupervisor
from civiccast.schema_check import SchemaStatus


def test_managed_constructor_does_not_wait_for_preparation(monkeypatch, tmp_path):
    import civiccast.app as module

    for name in (
        "DATABASE_URL",
        "CIVICCAST_ALLOW_EPHEMERAL_STORES",
        "CIVICCAST_NATIVE_STATION_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    entered, release, constructed = threading.Event(), threading.Event(), threading.Event()
    apps, errors = [], []
    url = "sqlite:///:memory:"
    monkeypatch.setattr(module, "load_managed_database_url", lambda: url)
    monkeypatch.setattr(module, "_managed_upload_dir_if_ready", lambda: None)
    monkeypatch.setattr(module, "load_managed_upload_dir", lambda: None)
    monkeypatch.setattr(module, "_maybe_start_finalization_worker", lambda app: None)
    monkeypatch.setattr(module, "_maybe_start_background_supervisors", lambda app: None)
    monkeypatch.setattr(module, "_ensure_default_local_recording_target", lambda app: None)
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )

    def prepare():
        entered.set()
        assert release.wait(8)
        return SimpleNamespace(database_url=url)

    monkeypatch.setattr(module, "ensure_managed_storage", prepare)

    def construct():
        try:
            apps.append(module.create_app())
        except Exception as exc:
            errors.append(exc)
        finally:
            constructed.set()

    thread = threading.Thread(target=construct)
    thread.start()
    try:
        assert constructed.wait(2), "managed preparation must not block create_app"
        assert not entered.is_set() and not errors
        app = apps[0]
        app.state.lifespan_started = True
        app.state.health_schema_owner.request()
        assert entered.wait(1)
        with TestClient(app) as client:
            assert client.get("/health").json()["status"] == "degraded"
            release.set()
            deadline = time.monotonic() + 2
            body = client.get("/health").json()
            while body["status"] != "healthy" and time.monotonic() < deadline:
                time.sleep(0.01)
                body = client.get("/health").json()
            assert body["status"] == "healthy"
            assert body["schema_db_revision"] == body["schema_expected_head"] == "head"
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        for app in apps:
            assert app.state.health_schema_owner.close(2)
        from civiccast.db import reset_engine

        reset_engine()
        monkeypatch.delenv("DATABASE_URL", raising=False)


def _app():
    state = SimpleNamespace(
        durable_storage_lock=threading.RLock(),
        durable_storage_active=False,
        durable_storage_wired_url="db",
        durable_storage_backfill=lambda: None,
        lifespan_started=True,
        supervisor_mode="normal",
        startup_condition_hooks=[],
    )
    owner = HealthSchemaOwner(state, sync_storage=lambda: None, source=lambda: "db", ttl_seconds=5)
    state.health_schema_owner = owner
    return SimpleNamespace(state=state), owner


def test_close_between_activation_check_and_commit_is_terminal(monkeypatch):
    import civiccast.app as module

    monkeypatch.setenv("DATABASE_URL", "db")
    app, owner = _app()
    for name in (
        "_configure_upload_dir",
        "_ensure_default_local_recording_target",
        "_maybe_start_finalization_worker",
        "_maybe_start_background_supervisors",
        "_refresh_schema_status",
    ):
        monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_managed_upload_dir_if_ready", lambda: None)
    checked, resume = threading.Event(), threading.Event()
    target = getattr(module, "_perform_durable_store_wiring", module._install_durable_store_wiring)
    source_lines, first = inspect.getsourcelines(target)
    source = "".join(source_lines)
    tree = ast.parse(source)
    # Gate the actual commit call in the repair, or the old unprotected write.
    calls = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "publish_storage"
    ]
    line = (
        (
            calls[0]
            if calls
            else next(
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and isinstance(n.targets[0], ast.Attribute)
                and n.targets[0].attr == "durable_storage_error"
                and isinstance(n.value, ast.Constant)
                and n.value.value is None
            )
        )
        + first
        - 1
    )
    errors = []

    def activate():
        def trace(frame, event, arg):
            if (
                frame.f_code.co_name == target.__name__
                and event == "line"
                and frame.f_lineno == line
            ):
                checked.set()
                assert resume.wait(3)
            return trace

        sys.settrace(trace)
        try:
            module._install_durable_store_wiring(app, "db")
        except Exception as exc:
            errors.append(exc)
        finally:
            sys.settrace(None)

    thread = threading.Thread(target=activate)
    thread.start()
    try:
        assert checked.wait(1)
        app.state.lifespan_started = False
        owner.close(0.01)
        resume.set()
        thread.join(2)
        assert not thread.is_alive() and not errors
        assert app.state.durable_storage_active is False, "closed owner must never publish active"
    finally:
        resume.set()
        thread.join(2)
        assert owner.close(2)


def test_nested_preparation_exception_keeps_shutdown_accounting():
    _unused_app, owner = _app()
    with owner.operation() as allowed:
        assert allowed
        with pytest.raises(ValueError), owner.operation() as nested:
            assert nested
            raise ValueError("finite fake preparation")
        assert not owner.close(0)
    assert owner.close(0)


def test_finalization_preparation_is_outside_terminal_lock(monkeypatch):
    import civiccast.app as module
    import civiccast.live.finalization_worker as finalization

    app, owner = _app()
    app.state.durable_storage_active = True
    entered, release, started = threading.Event(), threading.Event(), threading.Event()
    supervisor = finalization.FinalizationWorkerSupervisor(
        lambda: None, SimpleNamespace(mode="inline", poll_seconds=1, settle_seconds=1)
    )
    app.state.finalization_worker_supervisor = supervisor

    def prepare(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(run_forever=lambda **kw: (started.set(), kw["stop_event"].wait(3)))

    monkeypatch.setattr(finalization, "build_worker", prepare)
    thread = threading.Thread(target=lambda: module._maybe_start_finalization_worker(app))
    thread.start()
    try:
        assert entered.wait(1)
        # This would deadlock if arbitrary build_worker held the owner lock.
        assert owner.request().state == "unknown"
        assert not owner.close(0.01)
        release.set()
        thread.join(2)
        assert not thread.is_alive() and not started.is_set()
    finally:
        release.set()
        thread.join(2)
        supervisor.stop(0.1)
        assert owner.close(1)


def test_supervisor_default_start_remains_compatible():
    started = threading.Event()
    supervisor = ThreadSupervisor(
        name="u86-default",
        enabled=True,
        poll_seconds=1,
        run_forever=lambda **kw: (started.set(), kw["stop_event"].wait(2)),
    )
    try:
        supervisor.start()
        assert started.wait(1)
        thread = supervisor._thread
        supervisor.start()
        assert supervisor._thread is thread
    finally:
        supervisor.stop(1)
    assert thread is not None and not thread.is_alive()


def test_slow_prewarm_cannot_start_worker_after_shutdown(monkeypatch):
    import civiccast.app as module

    app, owner = _app()
    app.state.durable_storage_active = True
    entered, release = threading.Event(), threading.Event()
    started = threading.Event()
    supervisor = ThreadSupervisor(
        name="u86-fake",
        enabled=True,
        poll_seconds=1,
        run_forever=lambda **kwargs: (started.set(), kwargs["stop_event"].wait(3)),
    )
    app.state.background_supervisors = [supervisor]

    def prepare(app):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(module, "_prewarm_native_live_caption_runtime", prepare)
    thread = threading.Thread(target=lambda: module._maybe_start_background_supervisors(app))
    thread.start()
    try:
        assert entered.wait(1)
        app.state.lifespan_started = False
        close_result = owner.close(0.01)
        supervisor.stop(0.01)
        release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert not started.is_set(), "prewarm resume must not start after stop"
        assert close_result is False, "close must account for unfinished prewarm"
    finally:
        release.set()
        thread.join(2)
        supervisor.stop(0.1)
        assert owner.close(2)


def test_owned_housekeeping_hook_does_not_starve_schema_refresh(monkeypatch):
    now = [0.0]
    calls = []
    state = SimpleNamespace(
        lifespan_started=True, durable_storage_active=True, durable_storage_url="db"
    )
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: (calls.append(source), SchemaStatus("current", "head", "head"))[1],
    )
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "db", ttl_seconds=5, clock=lambda: now[0]
    )
    entered, release = threading.Event(), threading.Event()
    hook = threading.Thread(target=lambda: (entered.set(), release.wait(3)))
    try:
        owner.request()
        owner._thread.join(1)
        assert calls == ["db"]
        assert owner.start_hook(hook) and entered.wait(1)
        now[0] = 6
        owner.request()
        deadline = time.monotonic() + 1
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert calls == ["db", "db"], "housekeeping must not occupy schema refresh slot"
        assert not owner.close(0.01), "unfinished hook remains shutdown-owned"
    finally:
        release.set()
        if hook.ident is not None:
            hook.join(1)
        assert owner.close(2)


@pytest.mark.parametrize("preactivated", [False, True])
@pytest.mark.parametrize("close_held", [False, True])
def test_actual_lifespan_does_not_compete_with_owned_worker_preparation(
    monkeypatch, tmp_path, preactivated, close_held
):
    """Both fast activation and preactivated storage must yield before build."""
    import socket

    import httpx
    import uvicorn

    import civiccast.app as module
    import civiccast.live.finalization_worker as final
    from civiccast.db import reset_engine
    from tests.support.hermetic_state import hermetic_environment

    for key, value in hermetic_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "off")
    monkeypatch.delenv("CIVICCAST_NATIVE_STATION_ROOT", raising=False)
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setattr(module, "_ensure_default_local_recording_target", lambda app: None)
    monkeypatch.setattr("civiccast.egress.automation.reap_predecessor_relays", lambda **kw: [])
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    # All real supervisors retain their start/admission logic, but bodies are
    # finite fake work: no station, external DB, native or GPU activity.
    original_start = ThreadSupervisor.start

    def safe_start(self, **kwargs):
        self._run_forever = lambda **kw: kw["stop_event"].wait(8)
        return original_start(self, **kwargs)

    monkeypatch.setattr(ThreadSupervisor, "start", safe_start)
    entered, release, worker_started = threading.Event(), threading.Event(), threading.Event()
    builds, prepares = [], []

    def held_build(*args, **kwargs):
        builds.append(threading.current_thread().name)
        entered.set()
        assert release.wait(8)
        return SimpleNamespace(
            run_forever=lambda **kw: (worker_started.set(), kw["stop_event"].wait(8))
        )

    monkeypatch.setattr(final, "build_worker", held_build)
    app = module.create_app()
    app.state.durable_storage_backfill = lambda: None
    app.state.startup_condition_hooks = []
    if preactivated:
        app.state.activate_durable_storage("sqlite:///:memory:")
        assert app.state.durable_storage_active
        assert not entered.is_set(), "activation before lifespan must not build workers"
    # Exercise actual prewarm once-only behavior with a fake runtime.
    app.state.caption_tap_worker = SimpleNamespace(
        _runtime=SimpleNamespace(prepare=lambda: prepares.append("prepared"))
    )
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    original_request = app.state.health_schema_owner.request

    def fast_request(**kwargs):
        result = original_request(**kwargs)
        if kwargs.get("invalidate") and threading.current_thread().name == "u86-lifespan-http":
            assert entered.wait(2), "owner must prepare even preactivated storage"
            assert app.state.durable_storage_active
        return result

    monkeypatch.setattr(app.state.health_schema_owner, "request", fast_request)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, ws="none", log_level="error"))
    thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]), name="u86-lifespan-http"
    )
    try:
        thread.start()
        assert entered.wait(2)
        deadline = time.monotonic() + 1
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "lifespan must yield while actual worker preparation is held"
        with httpx.Client(timeout=1, trust_env=False) as client:
            body = client.get(f"http://127.0.0.1:{port}/health").json()
            assert body["status"] == "degraded"
            assert body["schema"] == "unknown"
            assert body["schema_db_revision"] == "none"
            assert body["schema_expected_head"] == "unknown"
        assert builds == ["civiccast-health-schema"]
        assert prepares == [] and not worker_started.is_set()
        if close_held:
            assert not app.state.health_schema_owner.close(0.01)
        release.set()
        if close_held:
            app.state.health_schema_owner._thread.join(2)
            assert not app.state.health_schema_owner._thread.is_alive()
            assert not worker_started.is_set() and prepares == []
            assert not app.state.durable_storage_active
        else:
            assert worker_started.wait(1)
            deadline = time.monotonic() + 1
            while not prepares and time.monotonic() < deadline:
                time.sleep(0.01)
            assert prepares == ["prepared"]
            # Re-enter the owner callback for already-active storage: no
            # duplicate build or prewarm, and fresh attestation converges.
            original_request(invalidate=True)
            deadline = time.monotonic() + 2
            while app.state.schema_status.state != "current" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert app.state.health_schema_owner._thread.is_alive(), "active cadence remains owned"
            with httpx.Client(timeout=1, trust_env=False) as client:
                body = client.get(f"http://127.0.0.1:{port}/health").json()
            assert body["status"] == "healthy"
            assert body["schema_db_revision"] == body["schema_expected_head"] == "head"
            assert len(builds) == 1 and prepares == ["prepared"]
    finally:
        release.set()
        server.should_exit = True
        if thread.ident is not None:
            thread.join(5)
        listener.close()
        assert not thread.is_alive()
        assert app.state.health_schema_owner.close(3)
        assert app.state.as_run_outbox.close()
        with socket.socket() as probe:
            probe.settimeout(0.1)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
        reset_engine()
