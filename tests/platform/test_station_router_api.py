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
        response = client.put(
            "/api/staff/station/profile", json={"not_a_real_field": "nope"}
        )
        assert response.status_code == 422
