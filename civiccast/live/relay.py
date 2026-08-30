# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Build operator-safe live ingest plans from configured sources + relay rows.

Bug B5 (live-path investigation, native beta candidate #17): this module's
``local_default`` used to be the ONLY path a channel's ingest plan ever
offered unless a :class:`~civiccast.live.models.LiveRelayConfig` row
existed -- and it was a hardcoded ``rtmp://127.0.0.1/live/{channel_id}``
placeholder that no process in this product has ever listened on
(CivicCast ships no RTMP broker; see ``civiccast.live.source_probe``'s
module docstring). Meanwhile the operator's actual configured
:class:`~civiccast.live.models.LiveSource` rows -- the ones Run Meeting
and pre-flight already use -- were never read here at all. Net effect,
proven live: an operator who adds a real SRT/RTSP/NDI/SRT encoder source
in Run Meeting has no way to make live-takeover
(``civiccast.egress.takeover_service.TakeoverService.take`` ->
:func:`civiccast.egress.live_takeover.build_live_takeover_source_plan`,
which selects from exactly this plan's ``local_default``/``relay_paths``)
actually use it -- the two systems never agreed on what "the channel's
source" even is.

Fix: :func:`build_ingest_plan` now also takes the channel's real
``LiveSource`` rows and turns each into a selectable
:class:`~civiccast.live.models.LiveIngestPath` (:func:`_source_path`),
ranked ahead of the legacy local default exactly like a ready relay
already was. ``local_default`` stops claiming ``ready``/``enabled`` for an
address nothing serves -- it is kept only so a station with zero
configured sources still gets a ``recommended_path_id`` to point
somewhere, and it now tells the operator to add a real source instead of
implying the placeholder itself works.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from civiccast.live.models import (
    RELAY_HEALTH_NOT_CONFIGURED,
    RELAY_HEALTH_READY,
    RELAY_MODE_CLOUD_RTMP,
    RELAY_MODE_DIRECT_SYNDICATION,
    RELAY_MODE_LOCAL_RTMP,
    LiveIngestPath,
    LiveIngestPlan,
    LiveRelayConfigResponse,
    LiveRelayHealthValue,
    LiveRelayModeValue,
    LiveSourceResponse,
)


def build_ingest_plan(
    channel_id: str,
    relay_configs: list[LiveRelayConfigResponse],
    *,
    live_sources: list[LiveSourceResponse] | None = None,
    generated_at: datetime | None = None,
) -> LiveIngestPlan:
    """Return a staff-safe ingest plan.

    The plan is intentionally descriptive. It does not include stream keys,
    process handles, or credentials; `credentials_handle` stays in the store
    layer and the operator sees only the actionable path and health state.

    ``live_sources`` should be every :class:`LiveSourceResponse` row
    configured for ``channel_id`` (``LiveSourceStore.list(channel_id=...)``).
    Each becomes a ready, selectable path -- the same rows the pre-flight
    ``live_source`` check and Run Meeting already treat as the station's
    real, operator-configured inputs.
    """

    now = generated_at or datetime.now(UTC)
    local_default = LiveIngestPath(
        path_id=f"{channel_id}:local",
        label="Legacy local placeholder (unusable)",
        mode=cast(LiveRelayModeValue, RELAY_MODE_LOCAL_RTMP),
        endpoint_url=f"rtmp://127.0.0.1/live/{channel_id}",
        provider="self-hosted",
        enabled=False,
        health_state=cast(LiveRelayHealthValue, RELAY_HEALTH_NOT_CONFIGURED),
        outbound_only=False,
        requires_inbound_firewall=False,
        operator_action=(
            "Add a real meeting source (Setup > Sources, or Run Meeting) -- CivicCast "
            "does not run an RTMP server, so nothing can ever push to this address. "
            "This placeholder stays here only so this plan always has a "
            "recommended_path_id."
        ),
        risk_note=None,
    )
    source_paths = [_source_path(source) for source in (live_sources or [])]
    relay_paths = [*source_paths, *(_relay_path(row) for row in relay_configs if row.enabled)]
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


def _source_path(source: LiveSourceResponse) -> LiveIngestPath:
    """A configured, operator-owned :class:`LiveSource` as a takeover path.

    Reported ``ready`` the same way the legacy ``local_default`` always
    was -- this plan describes WHICH paths exist and are configured, not
    whether media is flowing right now; that verification is pre-flight's
    ``live_source`` check (``civiccast.live.source_probe``) and the egress
    health sample after takeover, both of which already run against this
    exact source. ``mode`` reuses ``local_rtmp`` (this codebase's only
    "operator's own local encoder" mode) even for a non-RTMP scheme --
    SRT/RTSP/NDI sources are equally local-encoder paths; there is no
    separate mode value for them and adding one is a larger, unrelated
    schema change.
    """

    return LiveIngestPath(
        path_id=source.live_source_id,
        label=source.name,
        mode=cast(LiveRelayModeValue, RELAY_MODE_LOCAL_RTMP),
        endpoint_url=source.endpoint_url,
        provider="operator-configured",
        enabled=True,
        health_state=cast(LiveRelayHealthValue, RELAY_HEALTH_READY),
        outbound_only=False,
        # Whether this specific endpoint is reachable only from this machine
        # or exposed to the room network depends on the address the operator
        # entered in Setup (loopback vs. a bindable LAN address); this plan
        # has no way to tell those apart from the URL string alone, so it
        # makes no firewall claim rather than guessing one.
        requires_inbound_firewall=False,
        operator_action=(
            f"Point this {source.source_type.upper()} encoder at {source.endpoint_url!r}, "
            "then run pre-flight to confirm CivicCast can see it before going on air."
        ),
        risk_note=None,
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
