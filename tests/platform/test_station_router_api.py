# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API tests for S1's /api/staff/station-box-profile[/readiness] and
/api/staff/station/profile (S1 §4/§8, S1 §9 item 4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.installer.models import FirstAdminSetupRequest
from civiccast.installer.service import complete_first_admin_setup
from civiccast.installer.station_state import resolve_live_captions_enabled

_OPERATOR_HEADERS = {"Authorization": "Bearer operator-token-a"}


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))


def _records_clerk_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS", "records-token-c:records-c:Records C:records_clerk"
    )
    return {"Authorization": "Bearer records-token-c"}


class TestStationBoxProfileApi:
    def test_get_full_profile_200_for_operator(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/station-box-profile")
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == 1
        assert "hardware" in payload
        assert "engine" in payload
        assert "peg_readiness" in payload
        assert payload["peg_readiness"]["overall"] in ("green", "yellow", "red")

    def test_get_readiness_only_200(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/station-box-profile/readiness")
        assert response.status_code == 200
        payload = response.json()
        assert set(payload.keys()) == {"overall", "dimensions"}
        assert payload["overall"] in ("green", "yellow", "red")

    def test_403_for_role_without_diagnostic_access(self, monkeypatch: pytest.MonkeyPatch) -> None:
        headers = _records_clerk_headers(monkeypatch)
        client = TestClient(create_app(), headers=headers)
        response = client.get("/api/staff/station-box-profile")
        assert response.status_code == 403

    def test_readiness_403_for_role_without_diagnostic_access(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers = _records_clerk_headers(monkeypatch)
        client = TestClient(create_app(), headers=headers)
        response = client.get("/api/staff/station-box-profile/readiness")
        assert response.status_code == 403

    def test_401_with_no_token(self) -> None:
        client = TestClient(create_app())
        response = client.get("/api/staff/station-box-profile")
        assert response.status_code == 401

    def test_extra_field_rejected_by_the_model(self) -> None:
        from pydantic import ValidationError

        from civiccast.platform.station_box_profile import PegReadinessRollup

        with pytest.raises(ValidationError):
            PegReadinessRollup(overall="green", dimensions=[], surprise_field="nope")  # type: ignore[call-arg]


class TestStationIdentityProfileApi:
    def _complete_setup(self) -> None:
        complete_first_admin_setup(
            FirstAdminSetupRequest(
                station_name="Pinegrove School Board",
                admin_display_name="Avery Admin",
                admin_username="avery",
                admin_password="correct horse battery staple",
                recovery_kit_destination="safe",
            )
        )

    def test_get_profile_404_before_setup(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/station/profile")
        assert response.status_code == 404

    def test_get_profile_200_after_setup(self) -> None:
        self._complete_setup()
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/station/profile")
        assert response.status_code == 200
        payload = response.json()
        assert payload["station_name"] == "Pinegrove School Board"

    def test_put_profile_updates_name_and_timezone(self) -> None:
        self._complete_setup()
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.put(
            "/api/staff/station/profile",
            json={"station_name": "Pinegrove PEG", "station_timezone": "America/Denver"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["station_name"] == "Pinegrove PEG"
        assert payload["station_timezone"] == "America/Denver"

        follow_up = client.get("/api/staff/station/profile")
        assert follow_up.json()["station_name"] == "Pinegrove PEG"

    def test_put_profile_env_override_wins_over_persisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._complete_setup()
        monkeypatch.setenv("CIVICCAST_STATION_TZ", "America/Chicago")
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.get("/api/staff/station/profile")
        assert response.status_code == 200
        assert response.json()["station_timezone"] == "America/Chicago"

    def test_put_profile_403_for_non_setup_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._complete_setup()
        headers = _records_clerk_headers(monkeypatch)
        client = TestClient(create_app(), headers=headers)
        response = client.put("/api/staff/station/profile", json={"station_name": "Nope"})
        assert response.status_code == 403

    def test_put_profile_404_before_setup(self) -> None:
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.put("/api/staff/station/profile", json={"station_name": "Too Early"})
        assert response.status_code == 404

    def test_put_profile_rejects_unknown_field(self) -> None:
        self._complete_setup()
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        response = client.put("/api/staff/station/profile", json={"not_a_real_field": "nope"})
        assert response.status_code == 422

    def test_live_captions_are_on_by_default_and_can_be_switched_off(self) -> None:
        """The operator switch the live caption tap never had.

        `civiccast.native.station_runtime` hardcodes
        `CIVICCAST_CAPTION_TAP="inline"` for every activated station, so before
        this setting there was no way for an operator to stop live captioning
        on a box where it could not keep up -- which is how a tester station
        ended up burning ~247% of a core on ASR while its three playout workers
        were being restarted by their own stall watchdog.
        """

        self._complete_setup()
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)

        assert client.get("/api/staff/station/profile").json()["live_captions_enabled"] is True

        response = client.put(
            "/api/staff/station/profile",
            json={"live_captions_enabled": False},
        )
        assert response.status_code == 200
        assert response.json()["live_captions_enabled"] is False

        # Persisted, not just echoed: a fresh app must still see it off.
        follow_up = TestClient(create_app(), headers=_OPERATOR_HEADERS).get(
            "/api/staff/station/profile"
        )
        assert follow_up.json()["live_captions_enabled"] is False
        assert resolve_live_captions_enabled() is False

        # And it can be switched back on.
        back_on = client.put(
            "/api/staff/station/profile",
            json={"live_captions_enabled": True},
        )
        assert back_on.json()["live_captions_enabled"] is True
        assert resolve_live_captions_enabled() is True

    def test_editing_another_field_does_not_disturb_the_caption_switch(self) -> None:
        self._complete_setup()
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)
        client.put("/api/staff/station/profile", json={"live_captions_enabled": False})

        client.put("/api/staff/station/profile", json={"station_name": "Pinegrove PEG"})

        payload = client.get("/api/staff/station/profile").json()
        assert payload["station_name"] == "Pinegrove PEG"
        assert payload["live_captions_enabled"] is False

    def test_caption_tap_off_in_the_environment_wins_over_persisted_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Precedence is asymmetric, and only in the safe direction.

        The environment may force live captions OFF; it may never force them
        back ON against an operator who switched them off -- an activated
        native station sets `CIVICCAST_CAPTION_TAP=inline` unconditionally, so
        the reverse precedence would make the switch unreachable on exactly
        the deployments that need it.
        """

        self._complete_setup()
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "off")
        client = TestClient(create_app(), headers=_OPERATOR_HEADERS)

        assert client.get("/api/staff/station/profile").json()["live_captions_enabled"] is False
        assert resolve_live_captions_enabled() is False

        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
        client.put("/api/staff/station/profile", json={"live_captions_enabled": False})
        assert resolve_live_captions_enabled() is False


class TestLiveCaptionSwitchRehydration:
    """An upgrade from a station commissioned before this switch existed.

    A beta.4 station-state file has no ``live_captions_enabled`` key at all.
    Live captions are an accessibility feature, so an absent key MUST read as
    on -- reading it as off would silently stop captioning on every upgraded
    station and no operator would have asked for that.
    """

    def _beta4_shape_state(self) -> None:
        from civiccast.installer.station_state import _save_raw_state

        _save_raw_state(
            {
                "setup_complete": True,
                "station": {
                    "station_name": "Pinegrove School Board",
                    "admin_display_name": "Avery Admin",
                    "admin_username": "avery",
                    "default_channel_id": "government",
                    "public_base_url": None,
                    "station_timezone": "America/Denver",
                    "storage_locations": {
                        "media_library": "C:/CivicCast/media",
                        "recordings": "C:/CivicCast/recordings",
                        "backups": "C:/CivicCast/backups",
                    },
                    "channel_count": 3,
                    "recovery_kit_id": "rk_beta4",
                    "recovery_kit_generated_at": "2026-06-01T00:00:00Z",
                },
            }
        )

    def test_an_absent_key_rehydrates_as_on(self) -> None:
        from civiccast.installer.station_state import (
            read_live_captions_enabled,
            read_station_setup_state,
        )

        self._beta4_shape_state()

        # The raw reader reports "never set", which is NOT the same as False...
        assert read_live_captions_enabled() is None
        # ...the resolver and the rehydrated profile both say ON.
        assert resolve_live_captions_enabled() is True
        state = read_station_setup_state(operator_console_url="http://localhost:8080")
        assert state.profile is not None
        assert state.profile.live_captions_enabled is True

    def test_the_switch_survives_being_set_on_an_upgraded_state_file(self) -> None:
        from civiccast.installer.station_state import (
            StationProfileUpdateRequest,
            update_station_profile_fields,
        )

        self._beta4_shape_state()

        profile = update_station_profile_fields(
            StationProfileUpdateRequest(live_captions_enabled=False)
        )

        assert profile.live_captions_enabled is False
        assert resolve_live_captions_enabled() is False
