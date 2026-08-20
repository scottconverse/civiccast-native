# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Analytics store regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pytest import MonkeyPatch

from civiccast.analytics.store import AnalyticsStore
from civiccast.app_platform.models import AnalyticsEvent


def test_analytics_store_persists_only_aggregate_safe_fields(tmp_path) -> None:
    state_path = tmp_path / "analytics-events.json"
    store = AnalyticsStore(state_path)
    occurred_at = datetime.now(UTC).isoformat()

    retained = store.record_event(
        AnalyticsEvent(
            event_id="download-one",
            event_name="podcast_download",
            occurred_at=occurred_at,
            app_target="web_pwa",
            channel_id="public",
            content_id="episode-one",
            anonymous_session_id="session-not-retained",
            hashed_viewer_id="hash-not-retained",
            properties={
                "download_count": 3,
                "podcast_download": True,
                "country": "US",
                "unknown_safe_label": "ignored",
            },
        )
    )
    reloaded = AnalyticsStore(state_path)
    report = reloaded.report(range_days=30)

    assert retained.properties == {
        "download_count": 3,
        "podcast_download": True,
        "country": "US",
    }
    assert "session-not-retained" not in state_path.read_text(encoding="utf-8")
    assert "hash-not-retained" not in state_path.read_text(encoding="utf-8")
    assert "unknown_safe_label" not in state_path.read_text(encoding="utf-8")
    assert report.podcast_downloads[0].key == "episode-one"
    assert report.podcast_downloads[0].count == 3


def test_analytics_store_prunes_events_past_retention_window(
    tmp_path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ANALYTICS_RETENTION_DAYS", "1")
    state_path = tmp_path / "analytics-events.json"
    store = AnalyticsStore(state_path)

    store.record_event(
        AnalyticsEvent(
            event_id="old-event",
            event_name="playback_start",
            occurred_at=datetime.now(UTC) - timedelta(days=3),
            app_target="web_pwa",
            content_id="old-video",
        )
    )
    store.record_event(
        AnalyticsEvent(
            event_id="fresh-event",
            event_name="playback_start",
            occurred_at=datetime.now(UTC),
            app_target="web_pwa",
            content_id="fresh-video",
        )
    )

    payload = state_path.read_text(encoding="utf-8")

    assert "fresh-event" in payload
    assert "old-event" not in payload


def test_asset_view_seconds_computed_from_playback_complete_position_seconds(
    tmp_path,
) -> None:
    """The real web-app producer (HlsPlayer) never sends view_seconds/
    duration_seconds — it sends position_seconds on playback_heartbeat and
    playback_complete. The store must derive view-seconds from
    playback_complete's position_seconds so real production traffic isn't
    permanently reported as 0 watch time."""
    store = AnalyticsStore(tmp_path / "analytics-events.json")
    now = datetime.now(UTC)

    store.record_event(
        AnalyticsEvent(
            event_id="start-1",
            event_name="playback_start",
            occurred_at=now,
            app_target="web_pwa",
            content_id="vod-1",
        )
    )
    store.record_event(
        AnalyticsEvent(
            event_id="heartbeat-1",
            event_name="playback_heartbeat",
            occurred_at=now,
            app_target="web_pwa",
            content_id="vod-1",
            properties={"position_seconds": 60},
        )
    )
    store.record_event(
        AnalyticsEvent(
            event_id="complete-1",
            event_name="playback_complete",
            occurred_at=now,
            app_target="web_pwa",
            content_id="vod-1",
            properties={"position_seconds": 240},
        )
    )

    report = store.report(range_days=30)
    asset = next(point for point in report.asset_views if point.content_id == "vod-1")
    # Only playback_complete's position_seconds counts as watch time (the
    # heartbeat is a running position, not an incremental duration — summing
    # it too would over-count).
    assert asset.view_seconds == 240


def test_analytics_store_does_not_prune_on_every_fresh_write(
    tmp_path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_ANALYTICS_RETENTION_DAYS", "1")
    monkeypatch.setattr("civiccast.analytics.store._RETENTION_PRUNE_WRITE_INTERVAL", 10)
    state_path = tmp_path / "analytics-events.json"
    store = AnalyticsStore(state_path)

    store.record_event(
        AnalyticsEvent(
            event_id="fresh-event-one",
            event_name="playback_start",
            occurred_at=datetime.now(UTC),
            app_target="web_pwa",
            content_id="fresh-video-one",
        )
    )
    store.record_event(
        AnalyticsEvent(
            event_id="fresh-event-two",
            event_name="playback_start",
            occurred_at=datetime.now(UTC),
            app_target="web_pwa",
            content_id="fresh-video-two",
        )
    )

    assert store._writes_since_retention_prune == 2
