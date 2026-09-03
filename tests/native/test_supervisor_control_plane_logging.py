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
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from civiccast.native.supervisor.children import (
    CIVICCAST_SUPERVISED_ENV_VAR,
    control_plane_child_spec,
)
from civiccast.native.supervisor.service import (
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
