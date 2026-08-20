# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Zero-spend enforcement for the Tier B real-edge ramp: the budget is a
pre-flight refusal, not a hope."""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest

from civiccast.load import real_edge_ramp
from civiccast.load.real_edge_ramp import OpProjection, Tier, preflight, run_tier


def test_projection_math_scales_with_viewers_and_duration() -> None:
    p = OpProjection.project(
        [Tier(1000, 300.0)], segment_sample_rate=0.05, publish_total_seconds=360.0
    )
    assert p.class_b == 150_000 + 7_500  # manifest polls + 5% sampled segments
    assert p.class_a < 1_000  # publisher writes are tiny


def test_preflight_allows_the_planned_run_within_caps() -> None:
    tiers = [Tier(50, 120.0), Tier(200, 120.0), Tier(1000, 300.0)]
    p = preflight(tiers, segment_sample_rate=0.05)
    assert p.class_b < 200_000  # ~2% of the monthly free tier


def test_preflight_refuses_a_run_that_would_cost_money() -> None:
    # 5,000 viewers for 2 hours ≈ 9.4M reads — past the cap, REFUSED.
    with pytest.raises(SystemExit, match="REFUSED"):
        preflight([Tier(5000, 7200.0)], segment_sample_rate=0.05)


def test_preflight_refuses_excess_writes_too() -> None:
    with pytest.raises(SystemExit, match="REFUSED"):
        preflight(
            [Tier(1, 100_000.0)], segment_sample_rate=0.0, max_class_b=10**9, max_class_a=1000
        )


# --- connection pool sizing (must scale with the tier, not cap at 512) -------


class _FakePublisher:
    latest_sequence = 0


class _CapturingAsyncClient:
    """Records the httpx.Limits it was built with; every request errors out
    immediately so run_tier's viewer loop exits fast without real network."""

    captured: ClassVar[list[httpx.Limits]] = []

    def __init__(self, *, timeout: float, limits: httpx.Limits) -> None:
        _CapturingAsyncClient.captured.append(limits)

    async def __aenter__(self) -> _CapturingAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str) -> httpx.Response:
        raise httpx.ConnectError("no network in this test")


async def test_run_tier_sizes_the_connection_pool_to_the_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingAsyncClient.captured = []
    monkeypatch.setattr(real_edge_ramp.httpx, "AsyncClient", _CapturingAsyncClient)

    await run_tier(
        "http://edge/playlist.m3u8",
        _FakePublisher(),
        Tier(1000, 0.05),
        segment_sample_rate=0.0,
    )

    assert _CapturingAsyncClient.captured[0].max_connections == 1008  # tier.viewers + 8
