# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Public app-platform router tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app
from civiccast.app_platform import router as app_platform_router

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}
_ANALYTICS_HEADERS = {"X-CivicCast-Analytics-Key": "test-analytics-key"}


def _client(monkeypatch: MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    monkeypatch.setenv(
        "CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS",
        "https://portal.example.test",
    )
    return TestClient(create_app())


def test_app_platform_config_exposes_shared_station_contract(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/public/app/config?station_name=Longmont%20Lab")

    assert response.status_code == 200
    payload = response.json()
    assert payload["station_name"] == "Longmont Lab"
    assert payload["default_channel_id"] == "public"
    assert payload["build_profile"]["platform_targets"] == [
        "web_pwa",
        "roku",
        "tvos",
        "fire_tv",
        "android_tv",
        "android_mobile",
        "ios_ipados",
    ]
    assert [channel["channel_id"] for channel in payload["channels"]] == [
        "public",
        "education",
        "government",
    ]


def test_staff_app_config_updates_public_station_contract(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.patch(
        "/api/staff/app/config",
        headers=_STAFF_HEADERS,
        json={
            "station_name": "Longmont Public Apps",
            "default_channel_id": "government",
            "analytics_enabled": True,
            "app_name": "Longmont Channels",
            "store_ready": True,
            "store_notes": "Store packaging proof is controlled by later app-shell stages.",
        },
    )
    public = client.get("/api/public/app/config")

    assert response.status_code == 200
    assert response.json()["build_profile"]["app_name"] == "Longmont Channels"
    assert public.status_code == 200
    payload = public.json()
    assert payload["station_name"] == "Longmont Public Apps"
    assert payload["default_channel_id"] == "government"
    assert payload["analytics_enabled"] is True
    assert payload["build_profile"]["store_ready"] is True


def test_staff_app_config_requires_ga4_privacy_notice(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    blocked = client.patch(
        "/api/staff/app/config",
        headers=_STAFF_HEADERS,
        json={
            "analytics_enabled": True,
            "ga4_measurement_id": "G-ABC12345",
        },
    )
    allowed = client.patch(
        "/api/staff/app/config",
        headers=_STAFF_HEADERS,
        json={
            "analytics_enabled": True,
            "ga4_measurement_id": "G-ABC12345",
            "analytics_privacy_notice_url": "/privacy#analytics",
        },
    )

    assert blocked.status_code == 422
    assert "privacy" in str(blocked.json()["detail"])
    assert allowed.status_code == 200
    assert allowed.json()["ga4_measurement_id"] == "G-ABC12345"


def test_staff_app_config_persists_across_app_restart(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "app-platform-config.json"
    monkeypatch.setenv("CIVICCAST_APP_PLATFORM_CONFIG_PATH", str(config_path))
    client = _client(monkeypatch)

    response = client.patch(
        "/api/staff/app/config",
        headers=_STAFF_HEADERS,
        json={
            "station_name": "Restart Safe Station",
            "default_channel_id": "education",
            "app_name": "Restart Safe Apps",
        },
    )
    restarted = TestClient(create_app())
    public = restarted.get("/api/public/app/config")

    assert response.status_code == 200
    assert config_path.exists()
    assert public.status_code == 200
    payload = public.json()
    assert payload["station_name"] == "Restart Safe Station"
    assert payload["default_channel_id"] == "education"
    assert payload["build_profile"]["app_name"] == "Restart Safe Apps"


def test_staff_app_config_rejects_unknown_default_channel(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.patch(
        "/api/staff/app/config",
        headers=_STAFF_HEADERS,
        json={"default_channel_id": "missing"},
    )

    assert response.status_code == 422


def test_app_platform_channel_endpoints_share_channel_contract(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    channel = client.get("/api/public/app/channels/government")
    live = client.get("/api/public/app/channels/government/live")
    schedule = client.get("/api/public/app/channels/government/schedule")
    epg = client.get("/api/public/app/channels/government/schedule/epg")
    catalog = client.get("/api/public/app/channels/government/catalog")
    playlists = client.get("/api/public/app/channels/government/catalog/playlists")
    now_next = client.get("/api/public/app/channels/government/now-next")

    assert channel.status_code == 200
    assert channel.json()["app_targets"][-2:] == ["cg", "epg"]
    assert live.status_code == 200
    live_payload = live.json()
    assert live_payload["state"] == "fallback"
    assert live_payload["playback_url"].endswith("/embed.m3u8")
    assert live_payload["fallback_reason"] == "live source missing heartbeat"
    assert schedule.status_code == 200
    schedule_payload = schedule.json()
    assert schedule_payload[0]["kind"] == "fallback"
    assert schedule_payload[0]["playback_url"].endswith("/embed.m3u8")
    assert schedule_payload[0]["proof_boundary"] == "playout-plan-to-public-schedule-feed"
    assert epg.status_code == 200
    epg_payload = epg.json()
    assert epg_payload["export_targets"][-2:] == ["cg", "epg"]
    assert "tvguide_xlist" in epg_payload["export_formats"]
    assert epg_payload["items"] == schedule_payload
    assert catalog.status_code == 200
    catalog_payload = catalog.json()
    assert catalog_payload["items"][0]["playback_policy"]["access_tier"] == "public"
    assert catalog_payload["items"][0]["playback_policy"]["public_record_required"] is True
    assert catalog_payload["items"][0]["thumbnail_url"].endswith("-meeting.jpg")
    assert catalog_payload["items"][0]["captions"][0]["language"] == "en"
    assert catalog_payload["playlists"][0]["playlist_id"] == "government-recent"
    assert playlists.status_code == 200
    assert [playlist["playlist_id"] for playlist in playlists.json()] == [
        "government-recent",
        "government-public-records",
        "government-bulletins",
    ]
    assert now_next.status_code == 200
    assert now_next.json()["current"]["channel_id"] == "government"


def test_staff_channel_branding_updates_public_channel_contract(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.patch(
        "/api/staff/app/channels/government/branding",
        headers=_STAFF_HEADERS,
        json={
            "display_name": "City Government Live",
            "short_name": "City Gov",
            "color": "#114488",
            "logo_text": "CG",
        },
    )
    public = client.get("/api/public/app/channels/government")

    assert response.status_code == 200
    assert public.status_code == 200
    branding = public.json()["branding"]
    # configured_at is an explicit stored fact (PR #132 second re-review):
    # every save through this endpoint stamps it, regardless of the values
    # chosen -- checked separately below since its value is a request-time
    # timestamp, not a literal to hardcode.
    configured_at = branding.pop("configured_at")
    assert branding == {
        "display_name": "City Government Live",
        "short_name": "City Gov",
        "color": "#114488",
        "logo_text": "CG",
        "logo_url": None,
    }
    assert configured_at is not None


def test_staff_channel_branding_save_equal_to_default_is_still_configured(
    monkeypatch: MonkeyPatch,
) -> None:
    # PR #132 second re-review, reproduced live by the reviewer: an operator
    # who opens Channel Ops and explicitly saves branding equal to the
    # compile-time default (a plausible choice -- e.g. keeping the default
    # color) must be recorded as configured, not silently indistinguishable
    # from a station that never visited the screen.
    client = _client(monkeypatch)

    response = client.patch(
        "/api/staff/app/channels/public/branding",
        headers=_STAFF_HEADERS,
        json={
            "display_name": "Public Channel",
            "short_name": "Public",
            "color": "#2458A6",
            "logo_text": "PUBLIC",
        },
    )
    public = client.get("/api/public/app/channels/public")

    assert response.status_code == 200
    assert public.status_code == 200
    branding = public.json()["branding"]
    assert branding["configured_at"] is not None
    assert branding["display_name"] == "Public Channel"
    assert branding["color"] == "#2458A6"
    assert branding["logo_text"] == "PUBLIC"


def test_app_platform_catalog_filters_and_sorts_deterministically(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    recent = client.get(
        "/api/public/app/channels/public/catalog",
        params={"playlist_id": "public-recent"},
    )
    public_records = client.get(
        "/api/public/app/channels/public/catalog",
        params={"playlist_id": "public-public-records"},
    )
    bulletins = client.get(
        "/api/public/app/channels/public/catalog",
        params={"topic": "bulletin", "sort": "title_asc"},
    )

    assert recent.status_code == 200
    assert [item["publish_state"] for item in recent.json()["items"]] == [
        "published",
        "published",
    ]
    assert public_records.status_code == 200
    assert [item["item_id"] for item in public_records.json()["items"]] == [
        "public-sample-meeting",
    ]
    assert public_records.json()["items"][0]["playback_policy"]["public_archive_complete"] is True
    assert bulletins.status_code == 200
    assert [item["item_id"] for item in bulletins.json()["items"]] == [
        "public-bulletin-update",
    ]


def test_app_platform_catalog_applies_playback_policy_without_gating_public_records(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    gated = client.post(
        "/api/staff/playback-policy/asset/public-bulletin-update",
        headers=_STAFF_HEADERS,
        json={
            "access_tier": "invite_only",
            "invite_group_id": "members",
            "authenticated_rss_enabled": True,
            "preroll": {
                "enabled": True,
                "creatives": [
                    {
                        "creative_id": "station-card",
                        "kind": "graphic",
                        "asset_url": "/media/preroll/station-card.png",
                        "duration_seconds": 10,
                        "skippable_after_seconds": 5,
                        "accessible_label": "Station announcement",
                    }
                ],
            },
        },
    )
    public_record_override = client.post(
        "/api/staff/playback-policy/asset/public-sample-meeting",
        headers=_STAFF_HEADERS,
        json={"access_tier": "invite_only", "invite_group_id": "members"},
    )
    catalog = client.get("/api/public/app/channels/public/catalog")

    assert gated.status_code == 200
    assert public_record_override.status_code == 200
    assert catalog.status_code == 200
    by_id = {item["item_id"]: item for item in catalog.json()["items"]}
    bulletin_policy = by_id["public-bulletin-update"]["playback_policy"]
    assert bulletin_policy["access_tier"] == "invite_only"
    assert bulletin_policy["entitlement_required"] == "members"
    assert bulletin_policy["preroll_sequence"]["creatives"][0]["creative_id"] == "station-card"
    assert bulletin_policy["preroll"]["kind"] == "graphic"
    public_record_policy = by_id["public-sample-meeting"]["playback_policy"]
    assert public_record_policy["access_tier"] == "public"
    assert public_record_policy["entitlement_required"] is None
    assert public_record_policy["public_record_required"] is True


def test_app_platform_catalog_inherits_channel_playback_policy(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    policy = client.post(
        "/api/staff/playback-policy/channel/public",
        headers=_STAFF_HEADERS,
        json={
            "access_tier": "authenticated",
            "authenticated_rss_enabled": True,
        },
    )
    catalog = client.get("/api/public/app/channels/public/catalog")

    assert policy.status_code == 200
    assert catalog.status_code == 200
    by_id = {item["item_id"]: item for item in catalog.json()["items"]}
    assert by_id["public-bulletin-update"]["playback_policy"]["access_tier"] == "authenticated"
    assert by_id["public-sample-meeting"]["playback_policy"]["access_tier"] == "public"


def test_app_platform_public_live_state_exposes_playback_metadata(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/public/app/channels/public/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "on_air"
    assert payload["playback_url"] == "/api/public/channels/public/live.m3u8"
    assert payload["source_ref"] == "live-source-public"
    assert payload["caption_tracks"][0]["url"] == "/api/public/channels/public/captions.vtt"
    assert payload["audio_tracks"][0]["url"] == "/api/public/channels/public/audio.m3u8"


def test_app_platform_epg_xlist_export(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/public/app/channels/government/schedule/epg/xlist")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<tvguide-xlist" in response.text
    assert '<channel id="government">' in response.text
    assert "<programme " in response.text


def test_app_platform_analytics_ingest_acknowledges_safe_public_event(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "playback-start-one",
            "event_name": "playback_start",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "channel_id": "public",
            "content_id": "public-sample-meeting",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {"button_name": "Watch now", "player_variant": "default"},
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload == {
        "event_id": "playback-start-one",
        "accepted": True,
        "retained_fields": [
            "event_id",
            "event_name",
            "occurred_at",
            "app_target",
            "channel_id",
            "content_id",
            "properties",
        ],
        "proof_boundary": "privacy-safe-contract-no-direct-viewer-identifiers",
    }


def test_app_platform_analytics_ingest_allows_public_allowlisted_origin(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers={"Origin": "https://portal.example.test"},
        json={
            "event_id": "playback-start-public-origin",
            "event_name": "playback_start",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
        },
    )

    assert response.status_code == 202


def test_app_platform_analytics_ingest_rejects_disallowed_origin(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers={"Origin": "https://evil.example.test"},
        json={
            "event_id": "playback-start-disallowed-origin",
            "event_name": "playback_start",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
        },
    )

    assert response.status_code == 403


def test_app_platform_analytics_ingest_accepts_and_drops_when_unconfigured(
    monkeypatch: MonkeyPatch,
) -> None:
    # F-RC3-3: analytics is opt-in, best-effort telemetry. On a default station
    # it is not configured, and the public portal fires an event on every page
    # load. That must be a clean 202 no-op (event dropped, nothing stored) — not
    # a 503 that noises up every page load.
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", raising=False)
    monkeypatch.delenv("CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS", raising=False)
    client = TestClient(create_app())

    response = client.post(
        "/api/public/app/analytics/events",
        json={
            "event_id": "playback-start-unconfigured",
            "event_name": "playback_start",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["proof_boundary"] == "analytics-disabled-event-dropped"
    assert body["retained_fields"] == []


def test_app_platform_analytics_ingest_rejects_direct_identifiers(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "unsafe-search-one",
            "event_name": "search",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {"viewer_email": "resident@example.test"},
        },
    )

    assert response.status_code == 422


def test_app_platform_analytics_ingest_rejects_oversized_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "oversized-properties-one",
            "event_name": "playback_heartbeat",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {f"extra_{idx}": idx for idx in range(40)},
        },
    )

    assert response.status_code == 422


def test_app_platform_analytics_ingest_rejects_oversized_body_before_parse(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers={
            **_ANALYTICS_HEADERS,
            "Content-Type": "application/json",
        },
        content=b'{"event_id": "oversized-body",' + (b'"padding":' + b'"x"' * 20000),
    )

    assert response.status_code == 413


def test_app_platform_analytics_ingest_rejects_overlong_property_key(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "overlong-property-key",
            "event_name": "playback_heartbeat",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {"x" * 81: "value"},
        },
    )

    assert response.status_code == 422


def test_app_platform_analytics_ingest_rejects_overlong_property_string(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "overlong-property-value",
            "event_name": "playback_heartbeat",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {"device": "x" * 501},
        },
    )

    assert response.status_code == 422


def test_app_platform_analytics_ingest_rejects_nested_property_value(
    monkeypatch: MonkeyPatch,
) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "nested-property-value",
            "event_name": "playback_heartbeat",
            "occurred_at": "2026-05-31T18:00:00Z",
            "app_target": "web_pwa",
            "anonymous_session_id": "anonymous-session-123",
            "properties": {"device": {"kind": "desktop"}},
        },
    )

    assert response.status_code == 422


def test_app_platform_analytics_ingest_rate_limits_by_client_ip_not_session(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "2")
    client = _client(monkeypatch)

    def post_event(event_id: str, session_id: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers={"Origin": "https://portal.example.test"},
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": session_id,
                "properties": {"view_seconds": 10},
            },
        )

    assert post_event("rate-limit-one", "anonymous-session-001").status_code == 202
    assert post_event("rate-limit-two", "anonymous-session-002").status_code == 202
    limited = post_event("rate-limit-three", "anonymous-session-003")

    assert limited.status_code == 429


def test_app_platform_analytics_ingest_honors_x_forwarded_for_from_private_proxy(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    monkeypatch.setenv(
        "CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS",
        "https://portal.example.test",
    )
    client = TestClient(create_app(), client=("10.0.0.12", 50000))

    def post_event(event_id: str, forwarded_for: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers={
                "Origin": "https://portal.example.test",
                "X-Forwarded-For": forwarded_for,
            },
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": "anonymous-session-123",
            },
        )

    assert post_event("private-proxy-one", "198.51.100.10").status_code == 202
    assert post_event("private-proxy-two", "198.51.100.10").status_code == 429
    assert post_event("private-proxy-three", "198.51.100.11").status_code == 202


def test_app_platform_analytics_ingest_uses_rightmost_visitor_from_appending_proxy(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    monkeypatch.setenv(
        "CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS",
        "https://portal.example.test",
    )
    client = TestClient(create_app(), client=("10.0.0.12", 50000))

    def post_event(event_id: str, forwarded_for: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers={
                "Origin": "https://portal.example.test",
                "X-Forwarded-For": forwarded_for,
            },
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": "anonymous-session-123",
            },
        )

    assert post_event("rightmost-real-one", "198.51.100.200, 198.51.100.10").status_code == 202
    assert post_event("rightmost-real-two", "198.51.100.201, 198.51.100.10").status_code == 429


def test_app_platform_analytics_ingest_ignores_forged_x_forwarded_for_from_public_peer(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    monkeypatch.setenv(
        "CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS",
        "https://portal.example.test",
    )
    client = TestClient(create_app(), client=("8.8.8.8", 50000))

    def post_event(event_id: str, forwarded_for: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers={
                "Origin": "https://portal.example.test",
                "X-Forwarded-For": forwarded_for,
            },
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": "anonymous-session-123",
            },
        )

    assert post_event("public-peer-one", "198.51.100.10").status_code == 202
    assert post_event("public-peer-two", "198.51.100.11").status_code == 429


def test_app_platform_analytics_ingest_honors_configured_trusted_proxy_cidr(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CIVICCAST_ANALYTICS_TRUSTED_PROXY_CIDRS", "8.8.8.0/24")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    monkeypatch.setenv(
        "CIVICCAST_PUBLIC_ANALYTICS_ALLOWED_ORIGINS",
        "https://portal.example.test",
    )
    client = TestClient(create_app(), client=("8.8.8.8", 50000))

    def post_event(event_id: str, forwarded_for: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers={
                "Origin": "https://portal.example.test",
                "X-Forwarded-For": forwarded_for,
            },
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": "anonymous-session-123",
            },
        )

    assert post_event("trusted-proxy-one", "198.51.100.10").status_code == 202
    assert post_event("trusted-proxy-two", "198.51.100.10").status_code == 429
    assert post_event("trusted-proxy-three", "198.51.100.11").status_code == 202


def test_app_platform_analytics_ingest_trusted_key_uses_higher_rate_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("CIVICCAST_TRUSTED_ANALYTICS_RATE_LIMIT_PER_MINUTE", "2")
    client = _client(monkeypatch)

    def post_event(event_id: str):
        return client.post(
            "/api/public/app/analytics/events",
            headers=_ANALYTICS_HEADERS,
            json={
                "event_id": event_id,
                "event_name": "playback_heartbeat",
                "occurred_at": "2026-05-31T18:00:00Z",
                "app_target": "web_pwa",
                "anonymous_session_id": "anonymous-session-123",
            },
        )

    assert post_event("trusted-rate-one").status_code == 202
    assert post_event("trusted-rate-two").status_code == 202
    assert post_event("trusted-rate-three").status_code == 429


def test_app_platform_analytics_rate_limit_prunes_empty_buckets() -> None:
    buckets = {
        "client:stale": app_platform_router.AnalyticsRateLimitBucket(requests=[]),
        "client:active": app_platform_router.AnalyticsRateLimitBucket(requests=[10.0]),
    }

    app_platform_router.prune_analytics_rate_limit_buckets(
        buckets,
        now=70.0,
        window_seconds=60,
        max_buckets=10,
    )

    assert buckets == {}


def test_app_platform_analytics_rate_limit_prune_is_throttled() -> None:
    state = SimpleNamespace()

    assert app_platform_router._analytics_rate_limit_prune_due(
        state,
        now=100.0,
        bucket_count=1,
        max_buckets=10,
    )
    assert not app_platform_router._analytics_rate_limit_prune_due(
        state,
        now=101.0,
        bucket_count=1,
        max_buckets=10,
    )
    assert app_platform_router._analytics_rate_limit_prune_due(
        state,
        now=101.0,
        bucket_count=11,
        max_buckets=10,
    )
    state.public_analytics_rate_limit_last_pruned_at = 100.0
    assert app_platform_router._analytics_rate_limit_prune_due(
        state,
        now=131.0,
        bucket_count=1,
        max_buckets=10,
    )


def test_app_platform_analytics_ingest_rejects_oversized_body_without_content_length(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    app = create_app()
    received_messages = 0
    sent_messages: list[dict[str, object]] = []
    chunks = [b"x" * 10_000, b"x" * 7_000, b"x" * 10_000]

    async def receive() -> dict[str, object]:
        nonlocal received_messages
        body = chunks[received_messages]
        received_messages += 1
        return {
            "type": "http.request",
            "body": body,
            "more_body": received_messages < len(chunks),
        }

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/public/app/analytics/events",
        "raw_path": b"/api/public/app/analytics/events",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"x-civiccast-analytics-key", b"test-analytics-key"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))

    status_message = next(
        message for message in sent_messages if message["type"] == "http.response.start"
    )
    assert status_message["status"] == 413
    assert received_messages == 2


def test_app_platform_analytics_ingest_stops_reading_on_mid_body_disconnect(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_PUBLIC_ANALYTICS_KEY", "test-analytics-key")
    app = create_app()
    received_messages = 0
    sent_messages: list[dict[str, object]] = []
    messages = [
        {"type": "http.request", "body": b'{"event_id":', "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, object]:
        nonlocal received_messages
        message = messages[received_messages]
        received_messages += 1
        return message

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/public/app/analytics/events",
        "raw_path": b"/api/public/app/analytics/events",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"x-civiccast-analytics-key", b"test-analytics-key"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))

    assert received_messages == 2


def test_staff_analytics_report_is_aggregate_only(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)
    occurred_at = datetime.now(UTC).isoformat()

    response = client.post(
        "/api/public/app/analytics/events",
        headers=_ANALYTICS_HEADERS,
        json={
            "event_id": "analytics-report-one",
            "event_name": "playback_heartbeat",
            "occurred_at": occurred_at,
            "app_target": "web_pwa",
            "channel_id": "public",
            "content_id": "public-sample-meeting",
            "anonymous_session_id": "anonymous-session-123",
            "hashed_viewer_id": "hashed-viewer-not-retained",
            "properties": {
                "view_seconds": 30,
                "concurrent_viewers": 12,
                "country": "US",
                "state": "CO",
                "device_type": "desktop",
                "caption_language": "en",
                "audio_track": "program",
                "unknown_safe_label": "ignored",
            },
        },
    )
    report = client.get(
        "/api/staff/analytics/reports/overview",
        headers=_STAFF_HEADERS,
        params={"range_days": 30},
    )

    assert response.status_code == 202
    assert report.status_code == 200
    payload = report.json()
    assert payload["privacy_boundary"] == "aggregate-only-no-session-ip-or-viewer-identity"
    assert "anonymous_session_id" not in payload["retained_fields"]
    assert "hashed_viewer_id" not in payload["retained_fields"]
    assert payload["asset_views"][0]["view_seconds"] == 30
    assert payload["live_concurrent_viewers"][0]["peak_concurrent_viewers"] == 12
    assert {"dimension": "geography", "key": "US", "count": 1} in payload["geography"]
    assert {"dimension": "device", "key": "desktop", "count": 1} in payload["device_breakdown"]
    assert {"dimension": "caption", "key": "en", "count": 1} in payload["caption_usage"]


def test_app_platform_missing_channel_is_404(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/public/app/channels/missing")

    assert response.status_code == 404


def test_app_platform_openapi_exports_contracts(monkeypatch: MonkeyPatch) -> None:
    client = _client(monkeypatch)

    schema = client.get("/openapi.json").json()

    assert "/api/public/app/config" in schema["paths"]
    assert "StationAppConfig" in schema["components"]["schemas"]
    assert "StationAppConfigUpdate" in schema["components"]["schemas"]
    assert "ChannelPublicConfig" in schema["components"]["schemas"]
    assert "ChannelBrandingUpdate" in schema["components"]["schemas"]
    assert "SmartPlaylistDefinition" in schema["components"]["schemas"]
    assert "VodCatalogResponse" in schema["components"]["schemas"]
    assert "EpgScheduleResponse" in schema["components"]["schemas"]
    assert "AnalyticsEvent" in schema["components"]["schemas"]
    assert "AnalyticsIngestResponse" in schema["components"]["schemas"]
    assert "/api/public/app/analytics/events" in schema["paths"]
    assert "/api/public/app/channels/{channel_id}/schedule/epg" in schema["paths"]
    assert "/api/staff/app/config" in schema["paths"]
