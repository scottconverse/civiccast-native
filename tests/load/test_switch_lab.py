# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Switch-validation harness tests (0.2.0 Deliverable 2).

These drive the *real* surge path end-to-end through an in-process HTTP-served
CDN edge and assert the switch behaves: it engages under load, and viewers who
follow the switch to the CDN keep getting fresh segments (the CDN copy must not
freeze once the switch stops being driven by local-manifest polls).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from civiccast.common.trusted_proxy import reset_trusted_proxy_cache
from civiccast.load.switch_lab import ManualClock, build_switch_lab, simulate_switch


@pytest.fixture
def _clean_proxy_env(monkeypatch: Any) -> Any:
    """Neutral trusted-proxy env so each viewer's distinct peer IP is the client,
    and pin the local media base URL to the in-process origin."""
    for var in (
        "CIVICCAST_CDN_PROVIDER",
        "CIVICCAST_TRUSTED_PROXY_CIDRS",
        "CIVICCAST_TRUST_PRIVATE_PROXIES",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", "http://lab")
    reset_trusted_proxy_cache()
    yield
    reset_trusted_proxy_cache()


def _build(
    tmp_path: Path, clock: ManualClock, *, threshold: int, buffer_seconds: float = 0.0
) -> Any:
    return build_switch_lab(
        tmp_path / "live",
        tmp_path / "cdn",
        threshold=threshold,
        buffer_seconds=buffer_seconds,
        tick_interval=1.0,
        clock=clock,
    )


def test_ramp_engages_the_switch_to_cdn(tmp_path: Path, _clean_proxy_env: Any) -> None:
    clock = ManualClock()
    lab = _build(tmp_path, clock, threshold=3)

    result = simulate_switch(lab, clock, viewers=5, cycles=8, tick_interval=1.0)

    assert result.switched_to_cdn is True
    assert result.final_state == "cdn"
    assert result.cdn_segment_fetches > 0
    assert "cdn" in result.state_timeline


def test_below_threshold_never_switches(tmp_path: Path, _clean_proxy_env: Any) -> None:
    clock = ManualClock()
    lab = _build(tmp_path, clock, threshold=10)

    result = simulate_switch(lab, clock, viewers=2, cycles=8, tick_interval=1.0)

    assert result.switched_to_cdn is False
    assert result.final_state == "local"
    assert result.cdn_segment_fetches == 0
    assert result.stalls == 0  # local window advances every cycle


def test_delay_buffer_keeps_viewers_local_through_warming(
    tmp_path: Path, _clean_proxy_env: Any
) -> None:
    """The ~15s delay buffer (spec) is the WARMING window: after load crosses the
    threshold, the publisher cold-starts while viewers still get the LOCAL URL,
    and only swap once the buffer elapses. With buffer_seconds=0 the switch would
    flip on the very next tick, so this uses a multi-tick buffer and asserts the
    window actually holds — viewers stay local across several warming ticks before
    any CDN URL is handed out."""
    clock = ManualClock()
    lab = _build(tmp_path, clock, threshold=3, buffer_seconds=5.0)

    result = simulate_switch(lab, clock, viewers=5, cycles=12, tick_interval=1.0)

    # The buffer spanned multiple ticks (not an instant flip) ...
    assert result.state_timeline.count("warming") >= 3, result.state_timeline
    # ... during which viewers were served locally ...
    assert result.local_segment_fetches > 0
    # ... and only after it did the switch reach CDN.
    assert result.switched_to_cdn is True
    assert result.state_timeline.index("cdn") > result.state_timeline.index("warming")


def test_cdn_stays_fresh_after_the_switch(tmp_path: Path, _clean_proxy_env: Any) -> None:
    """The switch is worthless if the CDN copy freezes once viewers move to it.

    After the switch, viewers pull the CDN manifest and stop polling the local
    manifest -- so unless the switch is *driven* independently of that poll, the
    publisher stops syncing and the CDN window freezes, stalling every CDN
    viewer. This asserts the fresh path: viewers ride the switch with no
    sustained stalls.
    """
    clock = ManualClock()
    lab = _build(tmp_path, clock, threshold=3)

    result = simulate_switch(lab, clock, viewers=5, cycles=16, tick_interval=1.0)

    assert result.switched_to_cdn is True
    assert result.stalls == 0, (
        f"CDN froze after the switch: {result.stalls} stalls over "
        f"{result.segment_fetches} fetches; timeline={result.state_timeline}"
    )


def test_switch_releases_to_local_when_the_audience_leaves(
    tmp_path: Path, _clean_proxy_env: Any
) -> None:
    """Hysteresis + zero CDN cost at idle, end-to-end.

    The spec requires the channel to return to local (and stop paying for the
    CDN) once the surge subsides. That release needs a tick that *sees* the load
    fall -- which is only driven while some viewer keeps polling. Ramp past the
    threshold to switch, then drop to a below-release trickle and confirm the
    switch returns to local and evicts everything it pushed to the CDN.
    """
    clock = ManualClock()
    lab = _build(tmp_path, clock, threshold=4)  # release = max(1, 4//2) = 2

    engaged = simulate_switch(lab, clock, viewers=6, cycles=6, tick_interval=1.0)
    assert engaged.final_state == "cdn"
    cdn_channel_dir = lab.cdn_dir / "live" / lab.channel_id
    assert list(cdn_channel_dir.glob("*.ts")), "expected segments published to the CDN"

    # Audience collapses to a single viewer (below release=2). Run past the load
    # monitor's window so the departed viewers age out of the concurrent count.
    drained = simulate_switch(lab, clock, viewers=1, cycles=10, tick_interval=1.0)

    assert drained.final_state == "local"
    assert not list(cdn_channel_dir.glob("*.ts")), "CDN segments not evicted on release"
    assert not (cdn_channel_dir / "playlist.m3u8").exists(), "CDN manifest not evicted"
