# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real HTTP timeout possibility, not attribution of a station incident.

The DB engine and migration metadata are fake; lifecycle state is test-configured.
Production route, middleware, sync dispatch, schema refresh and bounded guard
remain intact. Lifespan is deliberately off: this is neither a startup nor an
inactive-storage proof. Each case owns a hidden child.
"""

from __future__ import annotations

import inspect
import json
import os
import site
import socket
import subprocess
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest


@pytest.mark.parametrize("case", ["literal", "guard"])
def test_health_socket_timeout_contract(case: str, tmp_path: Path) -> None:
    from tests.support.hermetic_state import hermetic_environment

    child_env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "APPDATA")
        if key in os.environ
    }
    child_env.update(hermetic_environment(tmp_path / "child"))
    child_env.update(CIVICCAST_AUTH_ACK="1", CIVICCAST_ALLOW_EPHEMERAL_STORES="1")
    # Windows venv redirectors spawn another PID. Own the actual interpreter.
    child_env["PYTHONPATH"] = os.pathsep.join(site.getsitepackages())
    command = [sys._base_executable, str(Path(__file__).resolve()), case]
    with subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) as child:
        try:
            output, _ = child.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            child.kill()  # Retained owned handle, never PID/name/port matching.
            output, _ = child.communicate(timeout=3)
            pytest.fail(f"owned child hard deadline; output:\n{output}")
        assert child.poll() is not None
        print(output, end="")
        cleanup = json.loads(output.split("U83_CLEANUP ", 1)[1].splitlines()[0])
        assert cleanup["pid"] == child.pid
        assert cleanup["server_stopped"] and cleanup["fake_workers_stopped"]
        with socket.socket() as probe:
            probe.settimeout(0.2)
            assert probe.connect_ex(("127.0.0.1", cleanup["port"])) != 0
        assert child.returncode == 0, output
    receipt = json.loads(output.split("U83_RECEIPT ", 1)[1].splitlines()[0])
    assert receipt["pid"] == child.pid
    assert receipt["case"] == case
    assert receipt["server_stopped"] and receipt["fake_workers_stopped"]
    with socket.socket() as probe:
        probe.settimeout(0.2)
        assert probe.connect_ex(("127.0.0.1", receipt["port"])) != 0


def _run_case(case: str) -> None:
    # Direct script execution does not inherit pytest's repo path bootstrap.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import sqlite3

    import httpx
    import sqlalchemy
    import uvicorn

    patch = pytest.MonkeyPatch()
    forbidden: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        forbidden.append("unexpected DB/process/startup")
        raise AssertionError(forbidden[-1])

    patch.setattr(sqlite3, "connect", refuse)
    patch.setattr(sqlalchemy, "create_engine", refuse)
    patch.setattr(subprocess, "Popen", refuse)
    # Import/construction must never start a background/native worker.
    patch.setattr(threading.Thread, "start", refuse)
    from civiccast import app as app_module
    from civiccast import schema_check

    for name in (
        "_maybe_start_finalization_worker",
        "_maybe_start_background_supervisors",
        "_prewarm_native_live_caption_runtime",
        "_install_durable_store_wiring",
    ):
        patch.setattr(app_module, name, refuse)
    patch.setattr(app_module, "create_engine", refuse)
    app = app_module.create_app()
    assert not forbidden
    patch.undo()
    # Keep all sentinels after restoring Thread.start for the owned server/guard.
    patch.setattr(sqlite3, "connect", refuse)
    patch.setattr(subprocess, "Popen", refuse)
    patch.setattr(app_module, "create_engine", refuse)
    for name in (
        "_maybe_start_finalization_worker",
        "_maybe_start_background_supervisors",
        "_prewarm_native_live_caption_runtime",
        "_install_durable_store_wiring",
    ):
        patch.setattr(app_module, name, refuse)

    app.state.lifespan_started = True
    app.state.durable_storage_active = True
    app.state.schema_status = schema_check.SchemaStatus(state="unknown")
    app.state.schema_status_checked_monotonic = None
    fake_url = "postgresql+psycopg://u83.invalid/database"
    patch.setenv("DATABASE_URL", fake_url)
    patch.setattr(schema_check, "expected_migration_head", lambda: "u83-head")
    patch.setattr(schema_check, "known_revisions", lambda: frozenset({"u83-head"}))
    assert schema_check._READ_DB_REVISION_CEILING_SECONDS == 15.0
    if case == "guard":
        patch.setattr(schema_check, "_READ_DB_REVISION_CEILING_SECONDS", 0.3)

    entered = threading.Event()
    release = threading.Event()
    disposed = threading.Event()
    release.set()
    timings: dict[str, float] = {}
    count = 0
    fake_threads: list[threading.Thread] = []

    class Connection:
        def __enter__(self) -> Connection:
            fake_threads.append(threading.current_thread())
            timings["read_enter"] = time.monotonic()
            entered.set()
            assert release.wait(12), "fake read gate deadline"
            timings["read_exit"] = time.monotonic()
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def execute(self, *args: Any) -> Connection:
            return self

        def fetchone(self) -> tuple[str]:
            return ("u83-head",)

    class Engine:
        def connect(self) -> Connection:
            return Connection()

        def dispose(self) -> None:
            disposed.set()

    def fake_engine(url: str, **kwargs: Any) -> Engine:
        nonlocal count
        assert url == fake_url
        count += 1
        return Engine()

    patch.setattr(sqlalchemy, "create_engine", fake_engine)
    health_route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    assert health_route.endpoint.__module__ == "civiccast.app"
    assert not inspect.iscoroutinefunction(health_route.endpoint)
    response_events: list[tuple[float, int]] = []

    async def observed(scope: Any, receive: Any, send: Any) -> None:
        async def record(message: Any) -> None:
            if message["type"] == "http.response.start":
                response_events.append((time.monotonic(), message["status"]))
            await send(message)

        await app(scope, receive, record)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(observed, lifespan="off", ws="none", log_level="error"))
    server_errors: list[BaseException] = []

    def serve() -> None:
        try:
            server.run(sockets=[listener])
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=serve, name="u83-owned-http")
    client = httpx.Client(trust_env=False, timeout=httpx.Timeout(5, connect=1))
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and not server_errors and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started and not server_errors
        url = f"http://127.0.0.1:{port}/health"
        control = client.get(url)
        assert control.status_code == 200
        assert control.json()["status"] == "healthy"
        assert control.json()["schema"] == "current"
        assert count == 1
        app.state.schema_status_checked_monotonic = None
        entered.clear()
        disposed.clear()
        release.clear()
        response_events.clear()
        timings["client_start"] = time.monotonic()
        if case == "literal":
            with pytest.raises(httpx.ReadTimeout):
                client.get(url)
            timings["client_timeout"] = time.monotonic()
            assert entered.is_set(), "client expired before fake read entry"
            assert timings["read_enter"] < timings["client_timeout"]
            remaining = timings["read_enter"] + 5.25 - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            timings["release"] = time.monotonic()
            release.set()
            assert disposed.wait(2)
            deadline = time.monotonic() + 2
            while not response_events and time.monotonic() < deadline:
                time.sleep(0.01)
            assert response_events and response_events[0][1] == 200
            assert timings["client_timeout"] < timings["release"] <= timings["read_exit"]
            assert 5 < timings["read_exit"] - timings["read_enter"] < 15
            assert response_events[0][0] >= timings["read_exit"]
            assert schema_check._READ_DB_REVISION_CEILING_SECONDS == 15.0
            cached = client.get(url)
            assert cached.status_code == 200 and cached.json()["schema"] == "current"
            assert cached.json()["status"] == "healthy" and count == 2
        else:
            response = None
            with suppress(httpx.ReadTimeout):
                response = client.get(url, timeout=2)
            assert response is not None, "DB guard must finish before the 2-second client cutoff"
            timings["guard_response"] = time.monotonic()
            assert entered.is_set() and not release.is_set()
            assert response.status_code == 200
            assert response.json()["schema"] == "unknown"
            assert response.json()["status"] == "degraded"
            assert timings["guard_response"] - timings["read_enter"] < 2
        assert count == 2 and not forbidden and not server_errors
    finally:
        release.set()
        for worker_thread in fake_threads:
            worker_thread.join(timeout=2)
        workers_stopped = all(not worker.is_alive() for worker in fake_threads)
        client.close()
        server.should_exit = True
        thread.join(timeout=2)
        listener.close()
        app.state.lifespan_started = False
        patch.undo()
        print(
            "U83_CLEANUP "
            + json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "server_stopped": not thread.is_alive(),
                    "fake_workers_stopped": workers_stopped,
                },
                sort_keys=True,
            )
        )
        assert workers_stopped, "fake guarded worker failed to dispose"
        assert not thread.is_alive(), "owned HTTP thread failed to stop"
    print(
        "U83_RECEIPT "
        + json.dumps(
            {
                "case": case,
                "pid": os.getpid(),
                "executable": sys.executable,
                "python": sys.version,
                "dependency_paths": {"httpx": httpx.__file__, "uvicorn": uvicorn.__file__},
                "route_source": inspect.getsourcefile(health_route.endpoint),
                "port": port,
                "timings": timings,
                "engine_calls": count,
                "response_events": response_events,
                "server_stopped": not thread.is_alive(),
                "fake_workers_stopped": workers_stopped,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    _run_case(sys.argv[1])
