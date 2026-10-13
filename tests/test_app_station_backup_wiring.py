# SPDX-License-Identifier: Apache-2.0
"""Station backup worker lifecycle follows durable storage activation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

import civiccast.app as app_module
import civiccast.dr.station_backup_runtime as backup_runtime
import civiccast.schema_check as schema_check


class _BackupService:
    def __init__(self, name: str, events: list[tuple[str, str]]) -> None:
        self.name = name
        self.events = events

    def start_worker(self) -> None:
        self.events.append(("start", self.name))

    def stop_worker(self) -> None:
        self.events.append(("stop", self.name))


def _isolate_durable_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "_create_database_engine", lambda _url: object())
    monkeypatch.setattr(app_module, "bind_engine", lambda _engine: None)
    monkeypatch.setattr(app_module, "_wire_durable_stores", lambda _app: None)
    monkeypatch.setattr(app_module, "_ensure_default_local_recording_target", lambda _app: None)
    monkeypatch.setattr(app_module, "_refresh_schema_status", lambda _app: None)
    monkeypatch.setattr(schema_check, "check_schema_currency", lambda _url: None)
    monkeypatch.setattr(app_module, "_maybe_start_finalization_worker", lambda _app: None)
    monkeypatch.setattr(app_module, "_maybe_start_background_supervisors", lambda _app: None)


def _run(coro: Any) -> None:
    asyncio.run(coro)


@pytest.mark.parametrize("runtime_flag", ["CIVICCAST_NATIVE_STATION", "CIVICCAST_SUPERVISED"])
def test_late_durable_activation_starts_replacement_and_stops_current_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime_flag: str
) -> None:
    monkeypatch.delenv("CIVICCAST_NATIVE_STATION", raising=False)
    monkeypatch.delenv("CIVICCAST_SUPERVISED", raising=False)
    monkeypatch.setenv(runtime_flag, "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test.invalid/civiccast")
    monkeypatch.setattr(app_module, "_supervisor_mode", lambda: "normal")
    _isolate_durable_wiring(monkeypatch)

    events: list[tuple[str, str]] = []
    services = iter((_BackupService("first", events), _BackupService("second", events)))
    monkeypatch.setattr(backup_runtime, "build_station_backup_service", lambda: next(services))
    app = FastAPI()

    async def exercise() -> None:
        async with app_module._app_lifespan(app):
            app_module._install_durable_store_wiring(
                app, "postgresql://test.invalid/first", upload_dir=str(tmp_path)
            )
            first = app.state.station_backup_service
            app_module._install_durable_store_wiring(
                app, "postgresql://test.invalid/second", upload_dir=str(tmp_path)
            )
            assert app.state.station_backup_service is not first

    _run(exercise())

    assert events == [
        ("start", "first"),
        ("stop", "first"),
        ("start", "second"),
        ("stop", "second"),
    ]


def test_late_durable_activation_keeps_backup_worker_stopped_in_maintenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test.invalid/civiccast")
    monkeypatch.setattr(app_module, "_supervisor_mode", lambda: "maintenance")
    _isolate_durable_wiring(monkeypatch)

    events: list[tuple[str, str]] = []
    monkeypatch.setattr(
        backup_runtime,
        "build_station_backup_service",
        lambda: _BackupService("maintenance", events),
    )
    app = FastAPI()

    async def exercise() -> None:
        async with app_module._app_lifespan(app):
            app_module._install_durable_store_wiring(
                app, "postgresql://test.invalid/civiccast", upload_dir=str(tmp_path)
            )

    _run(exercise())

    assert events == [("stop", "maintenance")]
