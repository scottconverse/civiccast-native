# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Role and persistence checks for the network settings staff API."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from civiccast.auth.models import OperatorIdentity
from civiccast.native.network import NetworkSettings, NetworkSettingsStore
from civiccast.native.network_router import router


def test_network_settings_routes_require_read_and_write_roles(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(router)
    app.state.network_settings_store = NetworkSettingsStore(tmp_path / "network.json")

    @app.middleware("http")
    async def test_identity(request: Request, call_next):  # type: ignore[no-untyped-def]
        token = request.headers.get("Authorization", "")
        scopes = {
            "Bearer setup": ("setup_admin",),
            "Bearer support": ("support_admin",),
            "Bearer meeting": ("meeting_operator",),
        }.get(token)
        if scopes:
            request.state.operator_identity = OperatorIdentity(
                operator_id="test-operator",
                operator_display_name="Test operator",
                scopes=scopes,
            )
        return await call_next(request)

    client = TestClient(app)

    assert client.get("/api/staff/network/settings").status_code == 401
    assert (
        client.get(
            "/api/staff/network/settings", headers={"Authorization": "Bearer meeting"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/staff/network/settings", headers={"Authorization": "Bearer support"}
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/staff/network/settings",
            headers={"Authorization": "Bearer support"},
            json={"mode": "loopback"},
        ).status_code
        == 403
    )

    response = client.put(
        "/api/staff/network/settings",
        headers={"Authorization": "Bearer setup"},
        json={
            "mode": "caddy",
            "public_base_url": "https://watch.example.gov",
            "staff_hostname": "staff.example.gov",
            "staff_allowed_cidrs": ["192.168.40.0/24"],
            "upstream_host": "127.0.0.1",
            "upstream_port": 8123,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restart_required"] is True
    assert body["settings"]["public_base_url"] == "https://watch.example.gov"
    assert "https://staff.example.gov" in body["caddyfile"]

    app.state.network_active_settings = NetworkSettings.model_validate(body["settings"])
    reread = client.get("/api/staff/network/settings", headers={"Authorization": "Bearer support"})
    assert reread.status_code == 200
    assert reread.json()["settings"] == body["settings"]
    assert reread.json()["restart_required"] is False


def test_invalid_network_settings_are_rejected_without_persisting(tmp_path) -> None:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(router)
    app.state.network_settings_store = NetworkSettingsStore(tmp_path / "network.json")

    @app.middleware("http")
    async def test_identity(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.operator_identity = OperatorIdentity(
            operator_id="test-operator",
            operator_display_name="Test operator",
            scopes=("setup_admin",),
        )
        return await call_next(request)

    response = TestClient(app).put(
        "/api/staff/network/settings",
        json={"mode": "caddy", "public_base_url": "http://watch.example.gov"},
    )
    assert response.status_code == 422
    assert NetworkSettingsStore(tmp_path / "network.json").load() == NetworkSettings()
