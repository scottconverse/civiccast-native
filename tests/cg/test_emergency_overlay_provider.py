# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c: the public CG emergency-overlay endpoint's EAS provider branch (real / 404 / placeholder)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.cg.models import EmergencyOverlay
from civiccast.cg.router import get_eas_overlay_provider, public_router


def _overlay(channel_id: str) -> EmergencyOverlay:
    return EmergencyOverlay(
        overlay_id=f"eas-{channel_id}-a1",
        severity="emergency",
        title="Tornado Warning",
        message="A tornado was detected.",
        instructions="Take shelter now.",
        cellular_fallback_enabled=True,
        aria_live="assertive",
    )


def _client(provider) -> TestClient:
    app = FastAPI()
    app.include_router(public_router)
    if provider is not None:
        app.dependency_overrides[get_eas_overlay_provider] = lambda: provider
    return TestClient(app)


def test_real_overlay_for_channel() -> None:
    client = _client(lambda channel_id: _overlay(channel_id))
    r = client.get("/api/public/cg/emergency-overlay?channel_id=gov")
    assert r.status_code == 200
    assert r.json()["severity"] == "emergency"
    assert r.json()["overlay_id"] == "eas-gov-a1"


def test_404_when_no_active_overlay_for_channel() -> None:
    client = _client(lambda _channel_id: None)
    r = client.get("/api/public/cg/emergency-overlay?channel_id=gov")
    assert r.status_code == 404


def test_placeholder_when_no_channel_id() -> None:
    # back-compat: without channel_id (or provider) the deterministic placeholder serves
    client = _client(lambda _channel_id: None)
    r = client.get("/api/public/cg/emergency-overlay")
    assert r.status_code == 200
    assert r.json()["overlay_id"] == "test-emergency-overlay"


def test_placeholder_when_provider_unwired() -> None:
    r = _client(None).get("/api/public/cg/emergency-overlay?channel_id=gov")
    assert r.status_code == 200  # no provider -> placeholder, channel_id ignored
