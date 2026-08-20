# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""M3 regression: the installer persists ``station_timezone`` at first-admin
setup (``civiccast.installer.station_state.complete_first_admin_setup``), but
nothing previously propagated it to the running service -- ``_station_tz()``
only ever read ``CIVICCAST_STATION_TZ``, which the installer never set, so
every station silently ran S18 daypart auto-scheduling on UTC regardless of
what the operator chose during commissioning.

These tests pin the fix directly against ``civiccast.app._station_tz``: the
persisted station-state value is the source of truth when no env override is
present, and ``CIVICCAST_STATION_TZ`` keeps working as an explicit override
(the documented env-var contract in docs/USER-MANUAL.md).
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.delenv("CIVICCAST_STATION_TZ", raising=False)


def _persist_station_timezone(value: str) -> None:
    """Write a minimal station-state JSON as ``complete_first_admin_setup``
    would, isolating this test from the rest of the profile's required
    fields (recovery kit, storage locations, ...)."""

    from civiccast.installer.station_state import _load_raw_state, _save_raw_state

    raw = _load_raw_state()
    station = raw.setdefault("station", {})
    station["station_timezone"] = value
    _save_raw_state(raw)


def test_resolves_persisted_station_timezone_with_no_env_override() -> None:
    _persist_station_timezone("America/Denver")

    from civiccast.app import _station_tz

    assert _station_tz() == ZoneInfo("America/Denver")


def test_env_var_overrides_the_persisted_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _persist_station_timezone("America/Denver")
    monkeypatch.setenv("CIVICCAST_STATION_TZ", "Europe/Berlin")

    from civiccast.app import _station_tz

    assert _station_tz() == ZoneInfo("Europe/Berlin")


def test_defaults_to_utc_before_commissioning() -> None:
    # No station-state.json written yet at all.
    from civiccast.app import UTC, _station_tz

    assert _station_tz() is UTC


def test_local_sentinel_default_falls_back_to_utc() -> None:
    # "local" is the pre-commissioning default persisted by the models
    # (civiccast.installer.models.StationProfile.station_timezone), not a
    # real IANA zone -- must not be mistaken for one.
    _persist_station_timezone("local")

    from civiccast.app import UTC, _station_tz

    assert _station_tz() is UTC


def test_invalid_persisted_zone_falls_back_to_utc_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _persist_station_timezone("Not/A_Real_Zone")

    from civiccast.app import UTC, _station_tz

    with caplog.at_level("WARNING"):
        result = _station_tz()

    assert result is UTC
    assert "Not/A_Real_Zone" in caplog.text


def test_read_station_timezone_reads_only_the_timezone_field(tmp_path: Path) -> None:
    """The reader must not require the full profile (recovery kit id, storage
    locations, etc.) to be present/valid -- a timezone lookup should never
    fail because an unrelated profile field is missing or malformed."""

    from civiccast.installer.station_state import _save_raw_state, read_station_timezone

    _save_raw_state({"station": {"station_timezone": "America/Chicago"}})

    assert read_station_timezone() == "America/Chicago"


def test_read_station_timezone_is_none_before_commissioning() -> None:
    from civiccast.installer.station_state import read_station_timezone

    assert read_station_timezone() is None
