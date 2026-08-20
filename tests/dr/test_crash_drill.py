# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Crash-recovery drill: a REAL OS process gets killed; the REAL daemon must relaunch it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from civiccast.dr.crash_drill import run_daemon_crash_restart_drill


def test_daemon_relaunches_a_really_killed_process(tmp_path: Path) -> None:
    result = run_daemon_crash_restart_drill(work_dir=tmp_path)

    assert result.ok, result.detail
    assert "killed" in result.detail
    assert "relaunched" in result.detail
    assert result.duration_seconds >= 0


def test_crash_drill_detects_a_failure_to_reach_on_air(tmp_path: Path, monkeypatch) -> None:
    """FALSIFICATION: if the channel never reaches ON_AIR, the drill must report failure,
    not rubber-stamp a pass. Forced by making the store always report a stuck state."""

    from civiccast.egress.store import InMemoryEgressStore

    original_read_state = InMemoryEgressStore.read_state

    def _stuck_read_state(self, channel_id: str):  # type: ignore[no-untyped-def]
        row = original_read_state(self, channel_id)
        if row is None:
            return None
        return row.model_copy(update={"state": "STARTING"})

    monkeypatch.setattr(InMemoryEgressStore, "read_state", _stuck_read_state)

    result = run_daemon_crash_restart_drill(work_dir=tmp_path, channel_id="dr-drill-2")

    assert not result.ok
    assert "ON_AIR" in result.detail


def test_slow_cleanup_wait_does_not_discard_the_computed_result(
    tmp_path: Path, monkeypatch
) -> None:
    """FALSIFICATION: a child that is slow to die during the drill's own `finally` cleanup
    (plausible under AV interference/system load on Windows station hardware) must not let
    a bare `TimeoutExpired` from the cleanup wait replace the already-computed result."""

    original_wait = subprocess.Popen.wait
    calls = {"n": 0}
    timed_out_proc: dict[str, subprocess.Popen] = {}

    def flaky_wait(self, timeout=None):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:
            # This is the drill's own `finally`-block cleanup wait on the still-live
            # relaunched child — the one this defect lets crash the whole function.
            timed_out_proc["proc"] = self
            raise subprocess.TimeoutExpired(cmd="sleep", timeout=timeout or 0)
        return original_wait(self, timeout=timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", flaky_wait)
    try:
        result = run_daemon_crash_restart_drill(work_dir=tmp_path, channel_id="dr-drill-3")
    finally:
        # The mock never let the real .wait() reap this already-`.kill()`-ed child;
        # reap it for real now so it doesn't linger as an unraisable ResourceWarning.
        if "proc" in timed_out_proc:
            original_wait(timed_out_proc["proc"], timeout=10)

    assert result.ok, result.detail
    assert calls["n"] == 2  # the flaky cleanup wait was actually exercised, exactly once
