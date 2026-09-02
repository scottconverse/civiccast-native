# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure ingest-plan tests for v1.8.7 remote relay planning."""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.live.models import LiveRelayConfigResponse, LiveSourceResponse
from civiccast.live.relay import build_ingest_plan


def _source(
    live_source_id: str = "council-room-encoder",
    *,
    source_type: str = "srt",
    endpoint_url: str = "srt://0.0.0.0:9000?mode=listener",
    probe_state: str = "ready",
    probe_observed_at: datetime | None = None,
    probe_detail: str | None = None,
) -> LiveSourceResponse:
    """A configured source, observed-ready *now* unless the caller says otherwise.

    WP-07: the default used to be irrelevant because ``_source_path`` stamped
    ``health_state='ready'`` on every row regardless. It now derives health
    from the observation, so these fixtures have to say what was observed.
    ``probe_observed_at`` defaults to "just now" so a plan built during the
    test is inside the readiness TTL.
    """
    observed_at = probe_observed_at
    if observed_at is None and probe_state == "ready":
        observed_at = datetime.now(UTC)
    return LiveSourceResponse(
        live_source_id=live_source_id,
        channel_id="gov-ch12",
        name="Council Room Encoder",
        source_type=source_type,  # type: ignore[arg-type]
        endpoint_url=endpoint_url,
        credentials_handle=None,
        created_at=datetime(2026, 5, 31, 17, 0, tzinfo=UTC),
        probe_state=probe_state,  # type: ignore[arg-type]
        probe_observed_at=observed_at,
        probe_detail=probe_detail,
        probe_last_success_at=observed_at if probe_state == "ready" else None,
    )


def _relay(
    relay_config_id: str,
    *,
    mode: str = "cloud_rtmp_relay",
    health_state: str = "ready",
    enabled: bool = True,
) -> LiveRelayConfigResponse:
    return LiveRelayConfigResponse(
        relay_config_id=relay_config_id,
        channel_id="gov-ch12",
        name=relay_config_id.replace("-", " ").title(),
        mode=mode,  # type: ignore[arg-type]
        endpoint_url=f"rtmps://relay.example/live/{relay_config_id}",
        return_playback_url="https://cdn.example/live/gov.m3u8",
        provider="project-hosted" if mode == "cloud_rtmp_relay" else "youtube-live",
        credentials_handle="secret-not-rendered",
        enabled=enabled,
        health_state=health_state,  # type: ignore[arg-type]
        last_heartbeat_at=datetime(2026, 5, 31, 18, 0, tzinfo=UTC),
        notes=None,
        created_at=datetime(2026, 5, 31, 17, 0, tzinfo=UTC),
    )


def test_ingest_plan_falls_back_to_local_default_when_nothing_is_configured() -> None:
    """Bug B5: with zero configured LiveSource rows and zero relays, the
    plan still needs a recommended_path_id -- but the legacy placeholder
    must not lie about being usable. CivicCast ships no RTMP broker; this
    address has never had a listener."""
    plan = build_ingest_plan(
        "gov-ch12",
        [],
        generated_at=datetime(2026, 5, 31, 19, 0, tzinfo=UTC),
    )

    assert plan.recommended_path_id == "gov-ch12:local"
    assert plan.local_default.mode == "local_rtmp"
    assert plan.local_default.outbound_only is False
    assert plan.local_default.requires_inbound_firewall is False
    assert plan.local_default.enabled is False
    assert plan.local_default.health_state == "not_configured"
    assert plan.relay_paths == []


def test_configured_live_source_becomes_the_recommended_path() -> None:
    """Bug B5 (the fix): a real, operator-configured LiveSource -- the
    same row Run Meeting and pre-flight already use -- must be a
    selectable, ready takeover path, and must outrank the legacy
    placeholder as the recommendation. This is the split-brain fix: before
    this, live-takeover could never see what an operator configured."""
    plan = build_ingest_plan(
        "gov-ch12",
        [],
        live_sources=[_source()],
        generated_at=datetime(2026, 5, 31, 19, 0, tzinfo=UTC),
    )

    assert plan.recommended_path_id == "council-room-encoder"
    assert len(plan.relay_paths) == 1
    source_path = plan.relay_paths[0]
    assert source_path.path_id == "council-room-encoder"
    assert source_path.endpoint_url == "srt://0.0.0.0:9000?mode=listener"
    assert source_path.enabled is True
    assert source_path.health_state == "ready"
    assert source_path.mode == "local_rtmp"
    # The disabled legacy placeholder is still present (a caller may still
    # explicitly select it by id) but is no longer recommended.
    assert plan.local_default.enabled is False


def test_multiple_configured_sources_all_appear_and_first_is_recommended() -> None:
    plan = build_ingest_plan(
        "gov-ch12",
        [],
        live_sources=[
            _source("camera-a", source_type="rtsp", endpoint_url="rtsp://192.168.1.10/stream"),
            _source("camera-b"),
        ],
    )

    assert {path.path_id for path in plan.relay_paths} == {"camera-a", "camera-b"}
    assert plan.recommended_path_id == "camera-a"


def test_configured_source_outranks_a_degraded_relay() -> None:
    plan = build_ingest_plan(
        "gov-ch12",
        [_relay("project-relay", health_state="degraded")],
        live_sources=[_source()],
    )

    assert plan.recommended_path_id == "council-room-encoder"
    assert plan.degraded_count == 1


def test_ready_cloud_relay_becomes_recommended_outbound_path() -> None:
    plan = build_ingest_plan("gov-ch12", [_relay("project-relay")])

    assert plan.recommended_path_id == "project-relay"
    path = plan.relay_paths[0]
    assert path.outbound_only is True
    assert path.requires_inbound_firewall is False
    assert path.return_playback_url == "https://cdn.example/live/gov.m3u8"
    assert "secret" not in path.model_dump_json()


def test_degraded_relay_does_not_replace_local_recommendation() -> None:
    plan = build_ingest_plan("gov-ch12", [_relay("project-relay", health_state="degraded")])

    assert plan.recommended_path_id == "gov-ch12:local"
    assert plan.degraded_count == 1


def test_direct_syndication_is_available_but_warns_about_recording() -> None:
    plan = build_ingest_plan(
        "gov-ch12",
        [_relay("youtube-backup", mode="direct_syndication")],
    )

    assert plan.direct_syndication_available is True
    assert plan.relay_paths[0].mode == "direct_syndication"
    assert plan.relay_paths[0].risk_note is not None
    assert "recording" in plan.relay_paths[0].risk_note.lower()
