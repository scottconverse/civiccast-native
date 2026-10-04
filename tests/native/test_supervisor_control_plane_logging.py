# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the control-plane child's INFO file logging (Gate A T4 fix,
2026-09): ``service.configure_control_plane_logging`` (the low-level
attach) and ``civiccast.app._maybe_configure_control_plane_logging`` (the
guarded call site inside the uvicorn ``--factory`` entrypoint,
``create_app``).

Bug this closes: the supervisor HOST process configures a rotating
``civiccast`` package logger (``service.configure_logging``), but that call
was never reached inside the SEPARATE ``python -m uvicorn
civiccast.app:create_app`` child process the supervisor spawns for the
control plane -- so every INFO record the egress daemon and the FastAPI app
emit was silently dropped. Gate A's T4 probe found
``engine_state=FALLBACK_SLATE`` on both the beta.3 and beta.4 kits with no
diagnostic trail explaining why.

Pure (any-OS) tests: no Win32, no subprocess, no real ``%ProgramData%``
writes -- ``log_root``/the env var are always injected or monkeypatched.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from uvicorn.config import LOGGING_CONFIG

from civiccast.native.supervisor.children import (
    CIVICCAST_SUPERVISED_ENV_VAR,
    control_plane_child_spec,
)
from civiccast.native.supervisor.service import (
    CONTROL_PLANE_HTTP_LOG_NAME,
    CONTROL_PLANE_LOG_NAME,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    PACKAGE_LOGGER_NAME,
    _DurableRotatingFileHandler,
    configure_control_plane_logging,
)

# ---------------------------------------------------------------------------
# service.configure_control_plane_logging
# ---------------------------------------------------------------------------


def test_http_logging_does_not_force_fsync_but_app_logging_stays_durable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import civiccast.native.supervisor.service as service_module

    configure_control_plane_logging(log_root=tmp_path)
    calls: list[int] = []
    monkeypatch.setattr(service_module.os, "fsync", calls.append)
    logging.getLogger("uvicorn.access").info("access-canary")
    logging.getLogger("uvicorn.error").error("error-canary")
    assert calls == []
    logging.getLogger("civiccast").info("durable-canary")
    assert len(calls) == 1


def test_uvicorn_records_rotate_without_console_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import civiccast.native.supervisor.service as service_module

    names = ("civiccast", "uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    try:
        # Real Uvicorn console configuration used before its app factory runs.
        # Apply only Uvicorn's logger/console shape, without dictConfig closing
        # or disabling unrelated pytest/application handlers process-wide.
        for name, config in LOGGING_CONFIG["loggers"].items():
            logger = logging.getLogger(name)
            logger.handlers = [
                logging.StreamHandler(sys.stderr) for _ in config.get("handlers", [])
            ]
            logger.setLevel(config.get("level", logging.NOTSET))
            logger.propagate = config.get("propagate", True)
        monkeypatch.setattr(service_module, "LOG_MAX_BYTES", 256)
        monkeypatch.setattr(service_module, "LOG_BACKUP_COUNT", 2)
        configure_control_plane_logging(log_root=tmp_path)
        configure_control_plane_logging(log_root=tmp_path)
        handler = logging.getLogger("uvicorn").handlers[0]
        assert type(handler) is logging.handlers.RotatingFileHandler
        assert isinstance(logging.getLogger("civiccast").handlers[0], _DurableRotatingFileHandler)
        for name in names[1:]:
            assert logging.getLogger(name).handlers == [handler]
        fsync_calls: list[int] = []
        monkeypatch.setattr(service_module.os, "fsync", fsync_calls.append)
        for index in range(20):
            logging.getLogger("uvicorn.access").info(
                '%s - "%s %s HTTP/%s" %d', "client", "GET", "/health", "1.1", 200
            )
            logging.getLogger("uvicorn.error").error("error-canary-%02d", index)
        assert fsync_calls == []
        logging.getLogger("civiccast").info("durable-canary")
        assert len(fsync_calls) == 1
        files = list(tmp_path.glob(f"{CONTROL_PLANE_HTTP_LOG_NAME}*"))
        assert len(files) == 3
        assert all(path.stat().st_size < 256 for path in files)
        content = "".join(path.read_text(encoding="utf-8") for path in files)
        assert content.count("error-canary-19") == 1
        assert "GET /health HTTP/1.1" in content
        captured = capsys.readouterr()
        assert captured.out == captured.err == ""
    finally:
        current = {h for name in names for h in logging.getLogger(name).handlers}
        original = {h for handlers, _, _ in saved.values() for h in handlers}
        for name, (handlers, level, propagate) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
        for handler in current - original:
            handler.close()


def test_configure_control_plane_logging_creates_its_own_rotating_log(tmp_path: Path) -> None:
    logger = configure_control_plane_logging(log_root=tmp_path)

    assert logger.name == PACKAGE_LOGGER_NAME
    assert logger.level == logging.INFO
    handlers = [h for h in logger.handlers if hasattr(h, "maxBytes")]
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, _DurableRotatingFileHandler)
    assert handler.maxBytes == LOG_MAX_BYTES
    assert handler.backupCount == LOG_BACKUP_COUNT
    assert (tmp_path / CONTROL_PLANE_LOG_NAME).exists()


def test_configure_control_plane_logging_uses_a_distinct_file_from_stdout_capture(
    tmp_path: Path,
) -> None:
    """``CONTROL_PLANE_LOG_NAME`` must never equal ``control_plane.log`` --
    that is the child runner's raw OS-level stdout/stderr redirect for this
    SAME process; a second handler opening that path would race the
    redirect's open handle on every rotation rename (Windows)."""

    assert CONTROL_PLANE_LOG_NAME != "control_plane.log"

    configure_control_plane_logging(log_root=tmp_path)

    assert not (tmp_path / "control_plane.log").exists()
    assert (tmp_path / CONTROL_PLANE_LOG_NAME).exists()


def test_configure_control_plane_logging_is_idempotent_no_handler_stacking(
    tmp_path: Path,
) -> None:
    configure_control_plane_logging(log_root=tmp_path)
    logger = configure_control_plane_logging(log_root=tmp_path)

    rotating = [h for h in logger.handlers if hasattr(h, "maxBytes")]
    assert len(rotating) == 1


def test_configure_control_plane_logging_routes_egress_daemon_records(tmp_path: Path) -> None:
    """The egress daemon logs under ``civiccast.egress.daemon`` -- a child of
    the ``civiccast`` package root this function configures. Proves an
    INFO-level daemon record actually reaches the file (the whole point:
    before this fix, nothing above WARNING reached any control-plane log at
    all)."""

    configure_control_plane_logging(log_root=tmp_path)

    logging.getLogger("civiccast.egress.daemon").info(
        "channel gov: egress state -> FALLBACK_SLATE (source=-, pid=-, last_error=canary)"
    )

    content = (tmp_path / CONTROL_PLANE_LOG_NAME).read_text(encoding="utf-8")
    assert "FALLBACK_SLATE" in content
    assert "canary" in content


# ---------------------------------------------------------------------------
# children.control_plane_child_spec: the env-var signal
# ---------------------------------------------------------------------------


def test_control_plane_child_spec_sets_supervised_env_var_unconditionally() -> None:
    normal = control_plane_child_spec()
    maintenance = control_plane_child_spec(mode="maintenance")

    assert normal.env[CIVICCAST_SUPERVISED_ENV_VAR] == "1"
    assert maintenance.env[CIVICCAST_SUPERVISED_ENV_VAR] == "1"


# ---------------------------------------------------------------------------
# civiccast.app._maybe_configure_control_plane_logging: the guarded call site
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_control_plane_logging_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ModuleType]:
    """``civiccast.app`` tracks "already configured this process" in a
    module-global -- reset it around each test so tests don't leak state
    into each other, and always leave the env var unset afterwards."""

    import civiccast.app as app_module

    monkeypatch.setattr(app_module, "_control_plane_logging_configured", False)
    monkeypatch.delenv(CIVICCAST_SUPERVISED_ENV_VAR, raising=False)
    yield app_module


def test_unsupervised_process_never_configures_control_plane_logging(
    _reset_control_plane_logging_guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default posture (no env var set -- a test run, a bare dev
    ``uvicorn`` invocation, anything not launched by the supervisor) must
    never touch ``%ProgramData%\\CivicCast\\logs``: calling ``create_app()``
    happens constantly in the test suite, and configuring real logging paths
    every time would create real directories a test run has no business
    writing."""

    app_module = _reset_control_plane_logging_guard
    calls: list[None] = []

    def _spy() -> logging.Logger:
        calls.append(None)
        return logging.getLogger("civiccast")

    # Patch the lazy import target so a real ProgramData write can never
    # happen even if the guard is broken.
    import civiccast.native.supervisor.service as service_module

    monkeypatch.setattr(service_module, "configure_control_plane_logging", _spy)

    app_module._maybe_configure_control_plane_logging()

    assert calls == []


def test_supervised_process_configures_control_plane_logging_exactly_once(
    _reset_control_plane_logging_guard: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the diagnosis asked for directly: the control-plane
    entrypoint configures the ``civiccast`` logger with a file handler
    EXACTLY once, even across multiple ``create_app()``-shaped calls (a
    uvicorn reload, or any other reason the factory runs twice in one
    process) -- never zero (the bug), never more than one (wasted re-opens
    of the log file)."""

    app_module = _reset_control_plane_logging_guard
    monkeypatch.setenv(CIVICCAST_SUPERVISED_ENV_VAR, "1")

    calls: list[None] = []

    def _spy() -> logging.Logger:
        calls.append(None)
        return logging.getLogger("civiccast")

    import civiccast.native.supervisor.service as service_module

    monkeypatch.setattr(service_module, "configure_control_plane_logging", _spy)

    app_module._maybe_configure_control_plane_logging()
    app_module._maybe_configure_control_plane_logging()
    app_module._maybe_configure_control_plane_logging()

    assert len(calls) == 1
