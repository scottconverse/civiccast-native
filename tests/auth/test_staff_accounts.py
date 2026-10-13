# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Station-local staff account and session lifecycle tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from civiccast.app import create_app


def _first_admin_token(client: TestClient) -> str:
    response = client.post(
        "/api/setup/first-admin",
        json={
            "station_name": "Pinegrove School Board",
            "admin_display_name": "Avery Admin",
            "admin_username": "avery",
            "admin_password": "correct horse battery staple",
            "recovery_kit_destination": "printed and stored in the clerk safe",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["operator_console_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_staff_account_login_role_change_and_session_revocation(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    admin_token = _first_admin_token(client)
    admin_headers = _bearer(admin_token)

    created = client.post(
        "/api/staff/auth/accounts",
        headers=admin_headers,
        json={
            "username": "clerk",
            "display_name": "Meeting Clerk",
            "password": "a sufficiently long password",
            "roles": ["meeting_operator"],
        },
    )
    assert created.status_code == 201, created.text
    staff_id = created.json()["operator_id"]
    assert created.json()["roles"] == ["meeting_operator"]
    assert "password_hash" not in created.json()

    login = client.post(
        "/api/staff/auth/login",
        json={"username": "clerk", "password": "a sufficiently long password"},
    )
    assert login.status_code == 200, login.text
    staff_token = login.json()["access_token"]
    staff_headers = _bearer(staff_token)
    identity = client.get("/api/staff/auth/me", headers=staff_headers)
    assert identity.status_code == 200
    assert identity.json()["operator_id"] == staff_id
    assert identity.json()["roles"] == ["meeting_operator"]

    changed = client.patch(
        f"/api/staff/auth/accounts/{staff_id}",
        headers=admin_headers,
        json={"roles": ["records_clerk"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["roles"] == ["records_clerk"]
    assert client.get("/api/staff/auth/me", headers=staff_headers).status_code == 401

    relogin = client.post(
        "/api/staff/auth/login",
        json={"username": "clerk", "password": "a sufficiently long password"},
    )
    assert relogin.status_code == 200
    staff_token = relogin.json()["access_token"]
    sessions = client.get("/api/staff/auth/sessions", headers=admin_headers)
    assert sessions.status_code == 200, sessions.text
    target = next(item for item in sessions.json() if item["operator_id"] == staff_id)
    revoked = client.delete(
        f"/api/staff/auth/sessions/{target['session_id']}",
        headers=admin_headers,
    )
    assert revoked.status_code == 204, revoked.text
    assert client.get("/api/staff/auth/me", headers=_bearer(staff_token)).status_code == 401

    state = json.loads((tmp_path / "station-state.json").read_text(encoding="utf-8"))
    account = next(item for item in state["staff_accounts"] if item["operator_id"] == staff_id)
    assert account["password_hash"] not in str(created.json())
    assert "access_token" not in str(state)


def test_staff_disable_and_password_reset_end_existing_sessions(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    admin_headers = _bearer(_first_admin_token(client))
    created = client.post(
        "/api/staff/auth/accounts",
        headers=admin_headers,
        json={
            "username": "producer",
            "display_name": "Producer",
            "password": "another sufficiently long password",
            "roles": ["publish_operator"],
        },
    )
    assert created.status_code == 201, created.text
    staff_id = created.json()["operator_id"]

    login = client.post(
        "/api/staff/auth/login",
        json={"username": "producer", "password": "another sufficiently long password"},
    )
    assert login.status_code == 200, login.text
    staff_token = login.json()["access_token"]

    reset = client.post(
        f"/api/staff/auth/accounts/{staff_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "replacement sufficiently long password"},
    )
    assert reset.status_code == 204, reset.text
    assert client.get("/api/staff/auth/me", headers=_bearer(staff_token)).status_code == 401
    assert (
        client.post(
            "/api/staff/auth/login",
            json={"username": "producer", "password": "another sufficiently long password"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/staff/auth/login",
            json={"username": "producer", "password": "replacement sufficiently long password"},
        ).status_code
        == 200
    )

    login = client.post(
        "/api/staff/auth/login",
        json={"username": "producer", "password": "replacement sufficiently long password"},
    )
    assert login.status_code == 200
    staff_token = login.json()["access_token"]
    disabled = client.patch(
        f"/api/staff/auth/accounts/{staff_id}",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert client.get("/api/staff/auth/me", headers=_bearer(staff_token)).status_code == 401
    assert (
        client.post(
            "/api/staff/auth/login",
            json={"username": "producer", "password": "replacement sufficiently long password"},
        ).status_code
        == 401
    )


def test_first_admin_and_staff_sessions_expire(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    admin_token = _first_admin_token(client)
    admin_headers = _bearer(admin_token)
    created = client.post(
        "/api/staff/auth/accounts",
        headers=admin_headers,
        json={
            "username": "records",
            "display_name": "Records Clerk",
            "password": "a records clerk password",
            "roles": ["records_clerk"],
        },
    )
    assert created.status_code == 201, created.text
    staff_login = client.post(
        "/api/staff/auth/login",
        json={"username": "records", "password": "a records clerk password"},
    )
    assert staff_login.status_code == 200, staff_login.text
    staff_token = staff_login.json()["access_token"]
    assert staff_login.json()["expires_at"]

    state_path = tmp_path / "station-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expired_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    for entry in state["operator_console"]["tokens"]:
        entry["expires_at"] = expired_at
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert client.get("/api/staff/auth/me", headers=_bearer(admin_token)).status_code == 401
    assert client.get("/api/staff/auth/me", headers=_bearer(staff_token)).status_code == 401


def test_last_setup_admin_cannot_be_disabled_and_reader_cannot_manage_accounts(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    client = TestClient(create_app())
    admin_headers = _bearer(_first_admin_token(client))
    assert client.get("/api/staff/auth/accounts").status_code == 401

    reader = client.post(
        "/api/staff/auth/accounts",
        headers=admin_headers,
        json={
            "username": "viewer",
            "display_name": "Records Reader",
            "password": "a records reader password",
            "roles": ["records_clerk"],
        },
    )
    assert reader.status_code == 201
    reader_login = client.post(
        "/api/staff/auth/login",
        json={"username": "viewer", "password": "a records reader password"},
    )
    assert reader_login.status_code == 200
    assert (
        client.get(
            "/api/staff/auth/accounts",
            headers=_bearer(reader_login.json()["access_token"]),
        ).status_code
        == 403
    )

    created = client.post(
        "/api/staff/auth/accounts",
        headers=admin_headers,
        json={
            "username": "solo-admin",
            "display_name": "Solo Administrator",
            "password": "a sole administrator password",
            "roles": ["setup_admin"],
        },
    )
    assert created.status_code == 201, created.text
    staff_id = created.json()["operator_id"]
    staff_login = client.post(
        "/api/staff/auth/login",
        json={"username": "solo-admin", "password": "a sole administrator password"},
    )
    assert staff_login.status_code == 200
    staff_headers = _bearer(staff_login.json()["access_token"])

    # Exercise the last-admin guard even if the original first-admin record
    # later becomes unreadable: the remaining staff administrator is not
    # allowed to remove the station's final recovery path.
    state_path = tmp_path / "station-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("admin")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    refused = client.patch(
        f"/api/staff/auth/accounts/{staff_id}",
        headers=staff_headers,
        json={"enabled": False},
    )
    assert refused.status_code == 409
    assert "administrator must remain" in refused.json()["detail"]
