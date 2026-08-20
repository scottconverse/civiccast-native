# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.live_takeover import build_live_takeover_source_plan
from civiccast.live.models import (
    RELAY_HEALTH_DEGRADED,
    RELAY_HEALTH_READY,
    RELAY_MODE_CLOUD_RTMP,
    RELAY_MODE_LOCAL_RTMP,
    LiveIngestPath,
    LiveIngestPlan,
)


def _path(
    path_id: str,
    *,
    label: str = "Council chamber",
    health_state: str = RELAY_HEALTH_READY,
    return_playback_url: str | None = "srt://127.0.0.1:19002",
) -> LiveIngestPath:
    return LiveIngestPath(
        path_id=path_id,
        label=label,
        mode=RELAY_MODE_CLOUD_RTMP if return_playback_url else RELAY_MODE_LOCAL_RTMP,
        endpoint_url=f"rtmp://127.0.0.1/live/{path_id}",
        return_playback_url=return_playback_url,
        provider="self-hosted",
        enabled=True,
        health_state=health_state,  # type: ignore[arg-type]
        outbound_only=bool(return_playback_url),
        requires_inbound_firewall=False,
        operator_action="Point the room encoder at this path.",
        risk_note=None,
    )


def _plan(*, path: LiveIngestPath | None = None) -> LiveIngestPlan:
    selected = path or _path("gov:relay")
    return LiveIngestPlan(
        channel_id="gov",
        generated_at=datetime(2026, 6, 5, 12, 0, tzinfo=UTC),
        local_default=_path("gov:local", return_playback_url=None),
        relay_paths=[selected],
        recommended_path_id=selected.path_id,
        degraded_count=0,
        direct_syndication_available=False,
    )


def test_build_live_takeover_source_plan_uses_ready_recommended_path() -> None:
    plan = build_live_takeover_source_plan(channel_id="gov", ingest_plan=_plan())

    assert plan.channel_id == "gov"
    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert segment.label == "Live: Council chamber"
    assert segment.path == "srt://127.0.0.1:19002"
    assert segment.kind == "live"
    assert segment.source_ref == "gov:relay"


def test_build_live_takeover_source_plan_falls_back_to_endpoint_for_local_path() -> None:
    plan = build_live_takeover_source_plan(
        channel_id="gov",
        ingest_plan=_plan(),
        path_id="gov:local",
    )

    assert plan.segments[0].path == "rtmp://127.0.0.1/live/gov:local"
    assert plan.segments[0].kind == "live"


def test_build_live_takeover_source_plan_fails_closed_for_unready_path() -> None:
    with pytest.raises(SourcePrepareError, match="not ready"):
        build_live_takeover_source_plan(
            channel_id="gov",
            ingest_plan=_plan(path=_path("gov:relay", health_state=RELAY_HEALTH_DEGRADED)),
        )


def test_build_live_takeover_source_plan_rejects_wrong_channel() -> None:
    with pytest.raises(SourcePrepareError, match="does not match"):
        build_live_takeover_source_plan(channel_id="schools", ingest_plan=_plan())
