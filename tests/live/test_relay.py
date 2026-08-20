# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure ingest-plan tests for v1.8.7 remote relay planning."""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.live.models import LiveRelayConfigResponse
from civiccast.live.relay import build_ingest_plan


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


def test_ingest_plan_preserves_local_default_when_no_relays() -> None:
    plan = build_ingest_plan(
        "gov-ch12",
        [],
        generated_at=datetime(2026, 5, 31, 19, 0, tzinfo=UTC),
    )

    assert plan.recommended_path_id == "gov-ch12:local"
    assert plan.local_default.mode == "local_rtmp"
    assert plan.local_default.outbound_only is False
    assert plan.local_default.requires_inbound_firewall is False
    assert plan.relay_paths == []


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
