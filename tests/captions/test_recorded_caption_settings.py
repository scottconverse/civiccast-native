# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persistence and staff API checks for recorded-caption settings."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.captions.settings import (
    RecordedCaptionSettings,
    RecordedCaptionSettingsStore,
)

pytestmark = pytest.mark.usefixtures("deterministic_staff_token")

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def test_first_explicit_save_pins_environment_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_JOB", "off")
    monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", "off")
    defaults = RecordedCaptionSettings.from_env()
    path = tmp_path / "station-state" / "offline-caption-settings.json"
    store = RecordedCaptionSettingsStore(path, defaults=defaults)

    assert store.save(defaults) is True
    assert path.is_file()

    monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_JOB", "inline")
    monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", "on")
    reloaded = RecordedCaptionSettingsStore(
        path,
        defaults=RecordedCaptionSettings(enabled=True, languages=("en", "es")),
    )
    assert reloaded.load() == defaults
    assert store.save(defaults) is False


def test_caption_settings_staff_api_reads_and_persists_explicit_settings(
    tmp_path: Path,
) -> None:
    app = create_app()
    settings = RecordedCaptionSettings(enabled=False, languages=("en",))
    store_path = tmp_path / "offline-caption-settings.json"
    store = RecordedCaptionSettingsStore(store_path, defaults=settings)
    app.state.recorded_caption_settings_store = store

    with TestClient(app, headers=_STAFF_HEADERS) as client:
        initial = client.get("/api/staff/captions/settings")
        assert initial.status_code == 200
        assert initial.json() == {
            "enabled": False,
            "languages": ["en"],
            "completion_requirement": "all_selected_languages",
        }

        saved = client.put("/api/staff/captions/settings", json=initial.json())
        assert saved.status_code == 200
        assert saved.json() == initial.json()

    assert store_path.is_file()
    assert (
        RecordedCaptionSettingsStore(
            store_path,
            defaults=RecordedCaptionSettings(enabled=True, languages=("en", "es")),
        ).load()
        == settings
    )
