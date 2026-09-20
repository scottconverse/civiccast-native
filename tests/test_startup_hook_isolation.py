# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Startup housekeeping must not hold the control plane's air path."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from civiccast.app import _maybe_start_background_supervisors


def _app(*hooks):
    return SimpleNamespace(
        state=SimpleNamespace(
            lifespan_started=True,
            supervisor_mode="normal",
            background_supervisors=[],
            startup_condition_hooks=list(hooks),
        )
    )


def test_fast_startup_hook_still_completes_before_startup_returns(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_STARTUP_HOOK_TIMEOUT_SECONDS", "1")
    finished = threading.Event()

    _maybe_start_background_supervisors(_app(lambda: finished.set()))

    assert finished.is_set()


def test_stalled_startup_hook_cannot_hold_startup_past_bound(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_STARTUP_HOOK_TIMEOUT_SECONDS", "0.02")
    entered = threading.Event()
    release = threading.Event()

    def stalled() -> None:
        entered.set()
        release.wait(2)

    started = time.monotonic()
    _maybe_start_background_supervisors(_app(stalled))
    elapsed = time.monotonic() - started

    assert entered.wait(0.5)
    assert elapsed < 0.5
    release.set()
