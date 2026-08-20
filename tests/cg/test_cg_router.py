# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def test_multi_zone_snapshot_public_route(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    response = client.get("/api/public/cg/channels/public/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel_id"] == "public"
    assert payload["template"]["template_id"] == "standard-community-board"
    assert payload["hls_render_path"] == "/api/public/cg/channels/public/stream.m3u8"
    assert {zone["kind"] for zone in payload["zones"]} >= {
        "primary",
        "ticker",
        "schedule",
        "logo",
        "audio",
        "alert",
    }


def test_feed_catalog_public_route(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    response = client.get("/api/public/cg/channels/public/feeds")

    assert response.status_code == 200
    payload = response.json()
    assert payload["channel_id"] == "public"
    assert {adapter["kind"] for adapter in payload["adapters"]} == {
        "rss",
        "ical",
        "weather",
        "social",
    }
    assert payload["proof_boundary"] == "configured-feed-adapters-to-approved-cg-zone-items"


def test_template_library_and_portal_display_routes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    templates = client.get("/api/public/cg/channels/public/templates")
    display = client.get("/api/public/cg/channels/public/display")

    assert templates.status_code == 200
    assert templates.json()["active_template_id"] == "standard-community-board"
    assert len(templates.json()["templates"]) == 3
    assert display.status_code == 200
    display_payload = display.json()
    assert display_payload["snapshot"]["template"]["template_id"] == "standard-community-board"
    assert display_payload["template_library"]["templates"]
    assert display_payload["approved_bulletins"]["approved_zone_items"]
    assert display_payload["render_plan"]["manifest_url"].endswith("/stream.m3u8")

    alternate = client.get(
        "/api/public/cg/channels/public/display?template_id=schedule-forward-board"
    )
    assert alternate.status_code == 200
    assert alternate.json()["snapshot"]["template"]["template_id"] == "schedule-forward-board"


def test_bulletins_routes_separate_public_approved_view_from_staff_queue(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    public = client.get("/api/public/cg/channels/public/bulletins")
    staff = client.get("/api/staff/cg/channels/public/bulletins", headers=_STAFF_HEADERS)

    assert public.status_code == 200
    public_payload = public.json()
    assert [submission["state"] for submission in public_payload["submissions"]] == ["scheduled"]
    assert public_payload["approved_zone_items"][0]["content"]["submission_id"] == "arts-fair"
    assert (
        public_payload["proof_boundary"] == "approved-community-bulletins-to-public-cg-zone-items"
    )
    assert staff.status_code == 200
    staff_payload = staff.json()
    assert [submission["state"] for submission in staff_payload["submissions"]] == [
        "scheduled",
        "needs_changes",
    ]


def test_hls_render_plan_and_manifest_routes(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    client = TestClient(create_app())

    plan = client.get("/api/public/cg/channels/public/render-plan")
    manifest = client.get("/api/public/cg/channels/public/stream.m3u8")

    assert plan.status_code == 200
    assert plan.json()["manifest_url"] == "/api/public/cg/channels/public/stream.m3u8"
    assert plan.json()["linear_overlay_contract_url"].endswith("/overlay-contract")
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    assert "#EXTM3U" in manifest.text
    assert "/api/public/cg/channels/public/segments/cg-00001.ts" in manifest.text

    overlay_contract = client.get("/api/public/cg/channels/public/overlay-contract")
    assert overlay_contract.status_code == 200
    assert overlay_contract.json()["snapshot_url"] == "/api/public/cg/channels/public/snapshot"
    assert overlay_contract.json()["format"] == "json-overlay-v1"
