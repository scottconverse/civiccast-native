# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Startup guard for volatile store posture."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_create_app_starts_local_setup_mode_when_database_url_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", raising=False)
    monkeypatch.setenv("CIVICCAST_MANAGED_STORAGE_DIR", str(tmp_path / "managed"))

    from civiccast.app import create_app
    from civiccast.db import reset_engine

    app = create_app()

    assert app.state.store_bundle is not None
    assert not (tmp_path / "managed" / "managed-storage.json").exists()
    assert os.environ.get("DATABASE_URL") is None
    reset_engine()


def test_create_app_allows_explicit_ephemeral_stores_for_tests(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")

    from civiccast.app import create_app

    with caplog.at_level(logging.WARNING, logger="civiccast.app"):
        app = create_app()

    assert app.state.store_bundle is not None
    assert any(
        "volatile in-memory staff stores" in record.getMessage() for record in caplog.records
    )

    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
        assets = client.get("/api/staff/assets")
        schedule = client.get("/api/staff/schedule")

    assert assets.status_code == 200
    assert assets.json() == []
    assert schedule.status_code == 200
    assert schedule.json() == []
