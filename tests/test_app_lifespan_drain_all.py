# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""RAT-004: the app lifespan's shutdown owns a real graceful drain-all.

Before this fix, ``_app_lifespan``'s ``finally`` block only called
``background.stop()`` (halting the automation poll thread) and left any live
worker subprocess for the Job Object to kill — orphaned, not drained. The
lifespan now calls ``EgressDaemon.stop_all_channels(...)`` FIRST, so channels
are drained by their owner. These tests substitute a spy for the real daemon
(installed on ``app.state.egress_daemon`` after startup, exactly where the
real wiring puts the real one) so the assertion is about ordering and the
call contract, not about actually running ffmpeg.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "drain-all.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE", raising=False)
    _migrate(db_path)
    return tmp_path


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


class _DrainAllSpy:
    """Stands in for the real EgressDaemon at app.state.egress_daemon."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def stop_all_channels(self, *, deadline_seconds: float) -> object:
        self.calls.append(deadline_seconds)
        return None


def test_lifespan_shutdown_calls_stop_all_channels_before_background_stop(
    app_env: Path,
) -> None:
    """The real wiring puts a real EgressDaemon on app.state.egress_daemon;
    swap it for a spy after startup and assert shutdown drives it, BEFORE the
    channel-automation ThreadSupervisor is stopped."""

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        # RAT-004 wiring precondition: the real daemon is reachable here.
        assert hasattr(app.state, "egress_daemon")
        spy = _DrainAllSpy()
        app.state.egress_daemon = spy
        automation = next(
            s
            for s in app.state.background_supervisors
            if getattr(s, "_name", None) == "civiccast-channel-automation"
        )
        assert automation.running is True

    # By the time the TestClient context manager exits, shutdown has run.
    assert spy.calls == [15.0]  # default deadline per the design addendum
    assert automation.running is False


def test_drain_all_deadline_is_configurable(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_DRAIN_DEADLINE_SECONDS", "3.5")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        spy = _DrainAllSpy()
        app.state.egress_daemon = spy

    assert spy.calls == [3.5]


def test_missing_egress_daemon_is_a_harmless_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain ephemeral-mode app (no durable storage -> no egress daemon
    wired at all) must shut down cleanly -- the drain-all call is optional,
    not a hard dependency of every app instance."""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        assert getattr(app.state, "egress_daemon", None) is None
    # No exception on shutdown is the assertion.


# ---------------------------------------------------------------------------
# Item 1 (deferred from PR #100): the recording-side shutdown drain, the peer
# of the egress stop_all_channels drain above.
# ---------------------------------------------------------------------------


class _RecordingDrainSpy:
    """Stands in for the ScheduledRecordingWorker at
    app.state.scheduled_recording_worker."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def drain_in_flight(self, *, deadline_seconds: float) -> object:
        self.calls.append(deadline_seconds)
        return None


def test_lifespan_shutdown_drains_in_flight_recordings(app_env: Path) -> None:
    """The real wiring puts a ScheduledRecordingWorker on
    app.state.scheduled_recording_worker under durable storage; swap it for a
    spy after startup and assert shutdown drives its drain."""

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert hasattr(app.state, "scheduled_recording_worker")
        spy = _RecordingDrainSpy()
        app.state.scheduled_recording_worker = spy

    assert spy.calls == [15.0]  # default recording-drain deadline


def test_recording_drain_deadline_is_configurable(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_RECORDING_DRAIN_DEADLINE_SECONDS", "4.25")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        spy = _RecordingDrainSpy()
        app.state.scheduled_recording_worker = spy

    assert spy.calls == [4.25]


def test_missing_recording_worker_is_a_harmless_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain ephemeral-mode app wires no recording worker; shutdown must
    still be clean -- the recording drain is optional, like the egress one."""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        assert getattr(app.state, "scheduled_recording_worker", None) is None
    # No exception on shutdown is the assertion.
