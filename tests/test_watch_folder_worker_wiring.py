# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S7 watch-folder daemon: app-lifespan wiring.

Confirms ``civiccast.app.create_app()`` actually registers the daemon as a
``ThreadSupervisor`` (mirroring ``tests/test_app_maintenance_mode.py``'s
``_named_supervisor`` idiom) -- the earlier build (PR #19) left the config
CRUD/UI wired but no daemon to wire in the first place, so this is the test
that would have caught that gap. Also pins the RAT-001 fail-closed posture
(maintenance/unknown supervisor mode holds the daemon back, same as every
other worker) and the env-gated off switch.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "watch-folder-wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", raising=False)
    monkeypatch.delenv("CIVICCAST_WATCH_FOLDER_WORKER", raising=False)
    _migrate(db_path)
    return tmp_path


def _named_supervisor(app: object, name: str) -> object:
    supervisors = getattr(app.state, "background_supervisors", [])  # type: ignore[attr-defined]
    matches = [s for s in supervisors if getattr(s, "_name", None) == name]
    assert matches, f"no background supervisor named {name!r} in {supervisors!r}"
    return matches[0]


def test_watch_folder_worker_is_registered_and_runs_by_default(app_env: Path) -> None:
    from civiccast.app import create_app
    from civiccast.schedule.watch_folder_worker import WatchFolderWorker

    app = create_app()

    assert isinstance(getattr(app.state, "watch_folder_worker", None), WatchFolderWorker)
    supervisor = _named_supervisor(app, "civiccast-watch-folder-worker")
    supervisor.start()
    try:
        assert supervisor.running is True
    finally:
        supervisor.stop()


def test_watch_folder_worker_off_mode_does_not_start(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_WATCH_FOLDER_WORKER", "off")

    from civiccast.app import create_app

    app = create_app()
    supervisor = _named_supervisor(app, "civiccast-watch-folder-worker")
    supervisor.start()
    try:
        assert supervisor.running is False
    finally:
        supervisor.stop()


def test_watch_folder_worker_held_back_in_maintenance_mode(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RAT-001: the fail-closed maintenance freeze covers every background
    supervisor, not a hand-picked subset -- this pins the watch-folder
    daemon is one of the ones it actually covers."""

    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE", "maintenance")
    monkeypatch.setenv("CIVICCAST_SUPERVISOR_MODE_CONTRACT", "1")

    from fastapi.testclient import TestClient

    from civiccast.app import create_app

    app = create_app()
    with TestClient(app):
        supervisor = _named_supervisor(app, "civiccast-watch-folder-worker")
        assert supervisor.running is False


def test_watch_folder_worker_settings_from_env_defaults() -> None:
    from civiccast.schedule.watch_folder_worker import (
        WATCH_FOLDER_WORKER_MODE_INLINE,
        WatchFolderWorkerSettings,
    )

    settings = WatchFolderWorkerSettings()
    assert settings.mode == WATCH_FOLDER_WORKER_MODE_INLINE
    assert settings.poll_seconds == 2.0
    assert settings.max_concurrent_folders == 4
    assert settings.upload_dir is None


def test_watch_folder_worker_settings_from_env_rejects_bad_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from civiccast.schedule.watch_folder_worker import WatchFolderWorkerSettings

    monkeypatch.setenv("CIVICCAST_WATCH_FOLDER_WORKER", "sideways")
    with pytest.raises(ValueError, match="CIVICCAST_WATCH_FOLDER_WORKER"):
        WatchFolderWorkerSettings.from_env()
