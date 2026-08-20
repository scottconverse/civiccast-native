# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.facility.router import get_facility_router_store
from civiccast.facility.store import InMemoryFacilityRouterStore


def _client() -> TestClient:
    # SEC-1 added Depends(require_any_role(...)) to the mutating routes
    # below (meeting_operator/support_admin), so this needs the full app
    # (central bearer-token auth) plus a role-carrying token rather than a
    # bare-router FastAPI() instance. Same pattern as
    # tests/programlog/test_router.py: create_app() + dependency_overrides
    # for the DI seam + the deterministic all-roles "operator" token that
    # tests/conftest.py enables via CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN.
    app = create_app()
    app.dependency_overrides[get_facility_router_store] = InMemoryFacilityRouterStore.default
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def test_router_inventory_lists_operator_safe_devices() -> None:
    response = _client().get("/api/staff/facility/router-inventory")

    assert response.status_code == 200
    body = response.json()
    assert body["endpoints"][0]["vendor"] == "blackmagic-design"
    assert body["endpoints"][0]["host"] == "192.0.2.10"
    assert body["sources"][0]["label"] == "Bulletin board"
    assert "hardware send is not performed" in body["proof_boundary"]


def test_router_take_plan_previews_command_without_sending() -> None:
    response = _client().post(
        "/api/staff/facility/router-take-plan",
        json={
            "request_id": "take-api-1",
            "endpoint_id": "control-room-router",
            "source_id": "council-chamber",
            "destination_id": "civiccast-capture",
            "requested_by": "operator-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command_preview"] == "VIDEO OUTPUT ROUTING:\\n7 1\\n\\n"
    assert body["ready_to_send"] is True
    assert "hardware connection" in body["proof_boundary"]


def test_router_take_plan_returns_404_for_missing_source() -> None:
    response = _client().post(
        "/api/staff/facility/router-take-plan",
        json={
            "request_id": "take-api-2",
            "endpoint_id": "control-room-router",
            "source_id": "missing",
            "destination_id": "civiccast-capture",
            "requested_by": "operator-1",
        },
    )

    assert response.status_code == 404
    assert "router source" in response.json()["detail"]


def test_router_schedule_plan_previews_automatic_take_without_sending() -> None:
    response = _client().post(
        "/api/staff/facility/router-schedule-plan",
        json={
            "request_id": "schedule-take-api-1",
            "schedule_item_id": "schedule-1",
            "channel_id": "gov-ch12",
            "starts_at": "2026-06-01T18:00:00Z",
            "endpoint_id": "control-room-router",
            "source_id": "council-chamber",
            "destination_id": "civiccast-capture",
            "requested_by": "scheduler",
            "preroll_seconds": 15,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schedule_item_id"] == "schedule-1"
    assert body["scheduled_take_at"] == "2026-06-01T17:59:45Z"
    assert body["automatic_take_ready"] is True
    assert body["take_plan"]["scheduled_for"] == "2026-06-01T17:59:45Z"
    assert "no hardware command is sent" in body["proof_boundary"]


def test_router_panel_is_mobile_friendly() -> None:
    response = _client().get("/api/staff/facility/router-panel")

    assert response.status_code == 200
    body = response.json()
    assert body["mobile_columns"] == 2
    assert body["buttons"][0]["requires_confirmation"] is True
    assert body["buttons"][0]["enabled"] is True


def test_router_panel_returns_404_for_missing_endpoint() -> None:
    response = _client().get("/api/staff/facility/router-panel?endpoint_id=missing")

    assert response.status_code == 404
    assert "router endpoint" in response.json()["detail"]
