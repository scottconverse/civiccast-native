# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Startup housekeeping must not hold the control plane's air path."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from civiccast.app import _maybe_start_background_supervisors
from civiccast.health_schema import HealthSchemaOwner


def _app(*hooks):
    app = SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            durable_storage_active=True,
            supervisor_mode="normal",
            background_supervisors=[],
            startup_condition_hooks=list(hooks),
        )
    )
    app.state.health_schema_owner = HealthSchemaOwner(
        app.state, sync_storage=lambda: None, source=lambda: None, ttl_seconds=5
    )
    return app


def test_fast_startup_hook_still_completes_before_startup_returns(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_STARTUP_HOOK_TIMEOUT_SECONDS", "1")
    finished = threading.Event()

    app = _app(lambda: finished.set())
    try:
        _maybe_start_background_supervisors(app)
        assert finished.is_set()
        assert app.state.startup_condition_hooks == []
    finally:
        assert app.state.health_schema_owner.close(1)


def test_stalled_startup_hook_cannot_hold_startup_past_bound(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_STARTUP_HOOK_TIMEOUT_SECONDS", "0.02")
    entered = threading.Event()
    release = threading.Event()

    def stalled() -> None:
        entered.set()
        release.wait(2)

    app = _app(stalled)
    try:
        started = time.monotonic()
        _maybe_start_background_supervisors(app)
        elapsed = time.monotonic() - started
        assert entered.wait(0.5)
        assert elapsed < 0.5
        assert app.state.startup_condition_hooks == []
        assert not app.state.health_schema_owner.close(0.01)
    finally:
        release.set()
        for thread in app.state.health_schema_owner._owned_threads:
            thread.join(1)
            assert not thread.is_alive()
        assert app.state.health_schema_owner.close(1)
