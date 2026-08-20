# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Playback policy router tests."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def _client(monkeypatch: MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    return TestClient(create_app())


def test_staff_policy_update_and_public_evaluation_flow(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    update = client.post(
        "/api/staff/playback-policy/channel/education",
        headers=_STAFF_HEADERS,
        json={"access_tier": "authenticated"},
    )
    anonymous = client.post(
        "/api/public/playback-policy/evaluate",
        json={"asset_id": "workshop", "channel_id": "education"},
    )
    caller_supplied_viewer = client.post(
        "/api/public/playback-policy/evaluate",
        json={
            "asset_id": "workshop",
            "channel_id": "education",
            "viewer": {"account_id": "viewer-one", "display_name": "Viewer One"},
        },
    )
    audit = client.get("/api/staff/playback-policy/audit/events", headers=_STAFF_HEADERS)

    assert update.status_code == 200
    assert anonymous.status_code == 200
    assert anonymous.json()["allowed"] is False
    assert caller_supplied_viewer.status_code == 422
    assert audit.status_code == 200
    assert [event["decision"] for event in audit.json()["events"]] == ["blocked"]


def test_staff_public_record_gate_returns_422(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/staff/playback-policy/asset/council-record",
        headers=_STAFF_HEADERS,
        json={
            "access_tier": "invite_only",
            "invite_group_id": "private",
            "public_record_required": True,
        },
    )

    assert response.status_code == 422
    assert "public-record" in response.text


def test_public_evaluation_accepts_only_signed_viewer_token(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    update = client.post(
        "/api/staff/playback-policy/asset/invited-workshop",
        headers=_STAFF_HEADERS,
        json={"access_tier": "invite_only", "invite_group_id": "board-training"},
    )
    token = client.post(
        "/api/staff/playback-policy/viewer-tokens",
        headers=_STAFF_HEADERS,
        json={
            "account_id": "viewer-one",
            "display_name": "Viewer One",
            "invite_groups": ["board-training"],
        },
    )
    blocked = client.post(
        "/api/public/playback-policy/evaluate",
        json={
            "asset_id": "invited-workshop",
            "channel_id": "education",
            "viewer_token": "not-a-real-token",
        },
    )
    allowed = client.post(
        "/api/public/playback-policy/evaluate",
        json={
            "asset_id": "invited-workshop",
            "channel_id": "education",
            "viewer_token": token.json()["token"],
        },
    )

    assert update.status_code == 200
    assert token.status_code == 200
    assert blocked.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True


def test_playback_policy_openapi_exports_contracts(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    schema = client.get("/openapi.json").json()

    assert "/api/public/playback-policy/evaluate" in schema["paths"]
    assert "/api/staff/playback-policy/{subject_type}/{subject_id}" in schema["paths"]
    assert "PlaybackPolicyEvaluation" in schema["components"]["schemas"]
    assert "PublicPlaybackPolicyEvaluationRequest" in schema["components"]["schemas"]
    assert "ViewerTokenResponse" in schema["components"]["schemas"]
