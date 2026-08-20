# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pydantic contract tests for v1.8 app-platform models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from civiccast.app_platform.models import (
    AnalyticsEvent,
    AppBuildProfile,
    CaptionTrack,
    CgFeedSnapshot,
    CgZone,
    ChannelBranding,
    ChannelOutput,
    ChannelPublicConfig,
    ChapterMarker,
    EpgScheduleResponse,
    LiveState,
    PlaybackPolicy,
    PrerollPolicy,
    ScheduleFeedItem,
    SmartPlaylistDefinition,
    SmartPlaylistRule,
    StationAppConfig,
    VodCatalogItem,
)


def _now() -> datetime:
    return datetime(2026, 5, 31, 18, 0, tzinfo=UTC)


def _branding() -> ChannelBranding:
    return ChannelBranding(
        display_name="Government Channel",
        short_name="Gov",
        color="#2458A6",
        logo_text="GOV",
    )


def _channel() -> ChannelPublicConfig:
    return ChannelPublicConfig(
        channel_id="government",
        slug="government",
        kind="government",
        branding=_branding(),
        outputs=[
            ChannelOutput(
                kind="hls",
                label="Public HLS",
                target="/api/public/channels/government/live.m3u8",
                proof_boundary="software-channel-to-hls",
                app_targets=["web_pwa", "roku"],
            )
        ],
        fallback_behavior="Use government slate when no approved program is available.",
        live_state_url="/api/public/app/channels/government/live",
        schedule_feed_url="/api/public/app/channels/government/schedule",
        vod_catalog_url="/api/public/app/channels/government/catalog",
        cg_feed_url="/api/public/app/channels/government/cg",
        app_targets=["web_pwa", "roku"],
    )


def test_station_config_requires_default_channel_to_exist() -> None:
    config = StationAppConfig(
        station_id="station-one",
        station_name="Station One",
        generated_at=_now(),
        default_channel_id="government",
        build_profile=AppBuildProfile(
            tier="branded",
            app_name="Station One",
            platform_targets=["web_pwa", "roku"],
        ),
        channels=[_channel()],
        support_url="https://example.test/support",
        privacy_url="https://example.test/privacy",
    )

    assert config.default_channel_id == "government"
    assert config.channels[0].outputs[0].app_targets == ["web_pwa", "roku"]


def test_station_config_rejects_missing_default_channel() -> None:
    with pytest.raises(ValidationError, match="default_channel_id"):
        StationAppConfig(
            station_id="station-one",
            station_name="Station One",
            generated_at=_now(),
            default_channel_id="public",
            build_profile=AppBuildProfile(
                tier="unbranded",
                app_name="Station One",
                platform_targets=["web_pwa"],
            ),
            channels=[_channel()],
            support_url="https://example.test/support",
            privacy_url="https://example.test/privacy",
        )


def test_playback_policy_rejects_gating_public_records() -> None:
    with pytest.raises(ValidationError, match="public-record assets"):
        PlaybackPolicy(
            access_tier="authenticated",
            public_record_required=True,
            entitlement_required="residents",
        )


def test_preroll_policy_requires_asset_and_duration() -> None:
    preroll = PrerollPolicy(
        kind="graphic",
        asset_url="https://cdn.example.test/preroll.png",
        duration_seconds=10,
        skippable_after_seconds=5,
    )

    assert preroll.kind == "graphic"

    with pytest.raises(ValidationError, match="require asset_url"):
        PrerollPolicy(kind="video", duration_seconds=15)


def test_live_state_requires_playback_url_when_on_air() -> None:
    captions = CaptionTrack(
        track_id="english",
        label="English",
        language="en",
        url="https://cdn.example.test/captions.vtt",
        kind="sidecar",
        default=True,
    )

    live = LiveState(
        state="on_air",
        channel_id="government",
        title="Council Meeting",
        live_session_id="council-2026-05-31",
        playback_url="https://cdn.example.test/live.m3u8",
        started_at=_now(),
        caption_tracks=[captions],
        proof_boundary="live-router-to-public-app",
    )

    assert live.caption_tracks[0].track_id == "english"

    with pytest.raises(ValidationError, match="playback_url"):
        LiveState(
            state="on_air",
            channel_id="government",
            proof_boundary="live-router-to-public-app",
        )


def test_vod_catalog_item_requires_playback_when_published() -> None:
    item = VodCatalogItem(
        item_id="council-meeting",
        asset_id="asset-council-meeting",
        channel_id="government",
        title="Council Meeting",
        playback_url="https://cdn.example.test/council.m3u8",
        publish_state="published",
        playback_policy=PlaybackPolicy(public_record_required=True),
    )

    assert item.playback_policy.access_tier == "public"

    with pytest.raises(ValidationError, match="playback_url"):
        VodCatalogItem(
            item_id="missing-playback",
            asset_id="asset-missing-playback",
            channel_id="government",
            title="Missing Playback",
            publish_state="published",
        )


def test_smart_playlist_rules_validate_supported_fields() -> None:
    playlist = SmartPlaylistDefinition(
        playlist_id="government-public-records",
        label="Public records",
        channel_id="government",
        rules=[
            SmartPlaylistRule(field="channel_id", value="government"),
            SmartPlaylistRule(field="public_record_required", value=True),
        ],
    )

    assert playlist.rules[1].value is True

    with pytest.raises(ValidationError, match="boolean"):
        SmartPlaylistRule(field="public_record_required", value="true")

    with pytest.raises(ValidationError, match="only supported for topic"):
        SmartPlaylistRule(field="series", operator="contains", value="Council")


def test_chapter_marker_requires_end_after_start() -> None:
    ChapterMarker(
        chapter_id="public-comment",
        title="Public Comment",
        start_seconds=120,
        end_seconds=240,
    )

    with pytest.raises(ValidationError, match="end_seconds"):
        ChapterMarker(
            chapter_id="bad-range",
            title="Bad Range",
            start_seconds=240,
            end_seconds=120,
        )


def test_cg_snapshot_requires_unique_zones() -> None:
    zone = CgZone(zone_id="primary", kind="primary", content={"headline": "Tonight"})
    snapshot = CgFeedSnapshot(
        snapshot_id="snapshot-one",
        generated_at=_now(),
        channel_id="government",
        template_id="standard",
        zones=[zone],
        proof_boundary="cg-feed-to-renderer",
    )

    assert snapshot.zones[0].kind == "primary"

    with pytest.raises(ValidationError, match="unique"):
        CgFeedSnapshot(
            snapshot_id="snapshot-two",
            generated_at=_now(),
            channel_id="government",
            template_id="standard",
            zones=[zone, zone],
            proof_boundary="cg-feed-to-renderer",
        )


def test_now_next_schedule_item_is_epg_ready() -> None:
    item = ScheduleFeedItem(
        item_id="council-live",
        channel_id="government",
        kind="live",
        title="Council Meeting",
        starts_at=_now(),
        ends_at=_now().replace(hour=20),
        duration_seconds=7200,
        live_state_url="/api/public/app/channels/government/live",
        playback_url="/api/public/channels/government/live.m3u8",
        captions_available=True,
        public_record_required=True,
        proof_boundary="schedule-to-epg",
    )
    export = EpgScheduleResponse(
        generated_at=_now(),
        channel_id="government",
        items=[item],
        export_targets=["web_pwa", "cg", "epg"],
        export_formats=["json", "tvguide_xlist"],
        proof_boundary="schedule-to-epg-export",
    )

    assert item.kind == "live"
    assert item.public_record_required is True
    assert export.export_targets == ["web_pwa", "cg", "epg"]
    assert export.export_formats == ["json", "tvguide_xlist"]

    with pytest.raises(ValidationError, match="ends_at"):
        ScheduleFeedItem(
            item_id="bad-range",
            channel_id="government",
            kind="live",
            title="Bad Range",
            starts_at=_now(),
            ends_at=_now(),
            duration_seconds=60,
        )


def test_ga4_station_config_requires_privacy_notice() -> None:
    channels = [
        ChannelPublicConfig(
            channel_id="public",
            slug="public",
            kind="public",
            branding=ChannelBranding(
                display_name="Public",
                short_name="Public",
                color="#2458A6",
                logo_text="PUB",
            ),
            fallback_behavior="show bulletin board",
            live_state_url="/api/public/app/channels/public/live",
            schedule_feed_url="/api/public/app/channels/public/schedule",
            vod_catalog_url="/api/public/app/channels/public/catalog",
            app_targets=["web_pwa"],
        )
    ]
    base = {
        "station_id": "station",
        "station_name": "Station",
        "generated_at": _now(),
        "default_channel_id": "public",
        "build_profile": AppBuildProfile(
            tier="unbranded",
            app_name="Station",
            platform_targets=["web_pwa"],
            store_ready=False,
        ),
        "channels": channels,
        "support_url": "/support",
        "privacy_url": "/privacy",
    }

    with pytest.raises(ValidationError, match="analytics_enabled"):
        StationAppConfig.model_validate({**base, "ga4_measurement_id": "G-ABC12345"})

    with pytest.raises(ValidationError, match="privacy_notice"):
        StationAppConfig.model_validate(
            {**base, "analytics_enabled": True, "ga4_measurement_id": "G-ABC12345"}
        )

    config = StationAppConfig.model_validate(
        {
            **base,
            "analytics_enabled": True,
            "ga4_measurement_id": "G-ABC12345",
            "analytics_privacy_notice_url": "/privacy#analytics",
        }
    )
    assert config.ga4_measurement_id == "G-ABC12345"


def test_analytics_event_allows_safe_labels_and_rejects_direct_identifiers() -> None:
    event = AnalyticsEvent(
        event_id="playback-start-one",
        event_name="playback_start",
        occurred_at=_now(),
        app_target="web_pwa",
        anonymous_session_id="anonymous-session-123",
        properties={"button_name": "Watch now", "player_variant": "default"},
    )

    assert event.properties["button_name"] == "Watch now"

    without_session = AnalyticsEvent(
        event_id="playback-start-two",
        event_name="playback_start",
        occurred_at=_now(),
        app_target="web_pwa",
        properties={"button_name": "Watch now"},
    )

    assert without_session.anonymous_session_id is None

    with pytest.raises(ValidationError, match="direct viewer identifiers"):
        AnalyticsEvent(
            event_id="unsafe-event",
            event_name="search",
            occurred_at=_now(),
            app_target="web_pwa",
            anonymous_session_id="anonymous-session-123",
            properties={"viewer_email": "resident@example.test"},
        )


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChannelBranding.model_validate(
            {
                "display_name": "Government Channel",
                "short_name": "Gov",
                "color": "#2458A6",
                "logo_text": "GOV",
                "unexpected": True,
            }
        )
