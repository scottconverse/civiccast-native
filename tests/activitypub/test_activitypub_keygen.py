# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""POST /api/staff/activitypub/keygen -- the "Generate station key" button.

Field evidence (candidate #17): turning federation on used to require typing
a raw `civiccast activitypub keygen ...` shell command shown on-screen. This
endpoint generates the same key material through a button instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app

_AUTH = {"Authorization": "Bearer operator-token-a"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    with TestClient(create_app()) as test_client:
        yield test_client


class TestActivityPubKeygen:
    def test_generates_a_real_key_and_never_shows_a_cli_command(self, client: TestClient) -> None:
        response = client.post("/api/staff/activitypub/keygen", headers=_AUTH)

        assert response.status_code == 200
        body = response.json()
        assert body["already_existed"] is False
        assert "BEGIN PUBLIC KEY" in body["public_key_pem"]
        assert body["private_key_path"].endswith("activitypub-station-key.pem")
        assert Path(body["private_key_path"]).exists()
        assert "civiccast activitypub keygen" not in body["next_step"]
        assert "civiccast activitypub keygen" not in str(body)

    def test_returns_the_env_settings_needed_to_apply_it(self, client: TestClient) -> None:
        body = client.post("/api/staff/activitypub/keygen", headers=_AUTH).json()

        assert body["env_settings"]["CIVICCAST_ACTIVITYPUB_MODE"] == "approval-only"
        assert (
            body["env_settings"]["CIVICCAST_ACTIVITYPUB_PRIVATE_KEY_PATH"]
            == body["private_key_path"]
        )
        assert body["env_settings"]["CIVICCAST_ACTIVITYPUB_AUTHORIZED_FETCH"] == "1"

    def test_calling_it_again_reuses_the_existing_key_instead_of_replacing_it(
        self, client: TestClient
    ) -> None:
        first = client.post("/api/staff/activitypub/keygen", headers=_AUTH).json()
        second = client.post("/api/staff/activitypub/keygen", headers=_AUTH).json()

        assert first["already_existed"] is False
        assert second["already_existed"] is True
        assert second["public_key_pem"] == first["public_key_pem"]

    def test_requires_setup_admin_role(self, client: TestClient) -> None:
        response = client.post("/api/staff/activitypub/keygen")
        assert response.status_code == 401

    def test_status_reports_whether_a_station_key_already_exists(self, client: TestClient) -> None:
        before = client.get("/api/staff/activitypub/status", headers=_AUTH).json()
        assert before["has_station_key"] is False

        client.post("/api/staff/activitypub/keygen", headers=_AUTH)

        after = client.get("/api/staff/activitypub/status", headers=_AUTH).json()
        assert after["has_station_key"] is True
