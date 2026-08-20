# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build operator-safe live ingest plans from relay config rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from civiccast.live.models import (
    RELAY_HEALTH_READY,
    RELAY_MODE_CLOUD_RTMP,
    RELAY_MODE_DIRECT_SYNDICATION,
    RELAY_MODE_LOCAL_RTMP,
    LiveIngestPath,
    LiveIngestPlan,
    LiveRelayConfigResponse,
    LiveRelayHealthValue,
    LiveRelayModeValue,
)


def build_ingest_plan(
    channel_id: str,
    relay_configs: list[LiveRelayConfigResponse],
    *,
    generated_at: datetime | None = None,
) -> LiveIngestPlan:
    """Return a staff-safe ingest plan.

    The plan is intentionally descriptive. It does not include stream keys,
    process handles, or credentials; `credentials_handle` stays in the store
    layer and the operator sees only the actionable path and health state.
    """

    now = generated_at or datetime.now(UTC)
    local_default = LiveIngestPath(
        path_id=f"{channel_id}:local",
        label="Local encoder",
        mode=cast(LiveRelayModeValue, RELAY_MODE_LOCAL_RTMP),
        endpoint_url=f"rtmp://127.0.0.1/live/{channel_id}",
        provider="self-hosted",
        enabled=True,
        health_state=cast(LiveRelayHealthValue, RELAY_HEALTH_READY),
        outbound_only=False,
        requires_inbound_firewall=False,
        operator_action="Point the room encoder at the local CivicCast ingest endpoint.",
        risk_note=None,
    )
    relay_paths = [_relay_path(row) for row in relay_configs if row.enabled]
    ready_relays = [path for path in relay_paths if path.health_state == RELAY_HEALTH_READY]
    recommended_path_id = ready_relays[0].path_id if ready_relays else local_default.path_id
    degraded_count = sum(1 for path in relay_paths if path.health_state != RELAY_HEALTH_READY)
    return LiveIngestPlan(
        channel_id=channel_id,
        generated_at=now,
        local_default=local_default,
        relay_paths=relay_paths,
        recommended_path_id=recommended_path_id,
        degraded_count=degraded_count,
        direct_syndication_available=any(
            path.mode == RELAY_MODE_DIRECT_SYNDICATION for path in relay_paths
        ),
    )


def _relay_path(row: LiveRelayConfigResponse) -> LiveIngestPath:
    if row.mode == RELAY_MODE_CLOUD_RTMP:
        return LiveIngestPath(
            path_id=row.relay_config_id,
            label=row.name,
            mode=row.mode,
            endpoint_url=row.endpoint_url,
            return_playback_url=row.return_playback_url,
            provider=row.provider,
            enabled=row.enabled,
            health_state=row.health_state,
            outbound_only=True,
            requires_inbound_firewall=False,
            operator_action=(
                "Send the room encoder to this relay endpoint. CivicCast reads the "
                "return playback URL for station playout."
            ),
            risk_note=None,
        )
    if row.mode == RELAY_MODE_DIRECT_SYNDICATION:
        return LiveIngestPath(
            path_id=row.relay_config_id,
            label=row.name,
            mode=row.mode,
            endpoint_url=row.endpoint_url,
            return_playback_url=row.return_playback_url,
            provider=row.provider,
            enabled=row.enabled,
            health_state=row.health_state,
            outbound_only=True,
            requires_inbound_firewall=False,
            operator_action=(
                "Send the room encoder directly to the platform endpoint only when "
                "local station hardware is offline."
            ),
            risk_note=(
                "Direct platform mode can bypass local recording unless a separate "
                "recording target is active."
            ),
        )
    return LiveIngestPath(
        path_id=row.relay_config_id,
        label=row.name,
        mode=row.mode,
        endpoint_url=row.endpoint_url,
        return_playback_url=row.return_playback_url,
        provider=row.provider,
        enabled=row.enabled,
        health_state=row.health_state,
        outbound_only=False,
        requires_inbound_firewall=False,
        operator_action="Use this local ingest path when the station network is available.",
        risk_note=None,
    )
