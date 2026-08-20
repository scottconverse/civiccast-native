# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Cache-contract tests for the CDN-edge simulator (0.2.0 Tier A).

Two layers:

* unit-level, against :class:`~civiccast.load.cache_edge.CachingEdgeASGI`
  wrapping a tiny synthetic origin -- exact, deterministic assertions about
  the caching contract itself (segment immutability, the falsification of the
  bug ``cache_control()`` fixes);
* integration-level, against the real switch-validation harness
  (:func:`~civiccast.load.switch_lab.build_switch_lab` with ``cache_edge=True``)
  -- proving the edge is correctly wired in front of ``/cdn-edge`` and that a
  real end-to-end ramp still holds its guarantees (freshness, O(1) origin
  offload, clean eviction) with the edge in the path.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

from civiccast.common.trusted_proxy import reset_trusted_proxy_cache
from civiccast.load.cache_edge import CachingEdgeASGI
from civiccast.load.lab import RollingStation
from civiccast.load.switch_lab import (
    ManualClock,
    _PerRequestPeerASGI,
    _viewer_ip,
    build_switch_lab,
    simulate_switch,
)
from civiccast.stream.cdn import cache_control

_SEQ_RE = re.compile(r"^#EXT-X-MEDIA-SEQUENCE:(\d+)", re.MULTILINE)
# No end anchor: HLS allows CRLF line endings (RFC 8216), and RollingStation's
# manifest writer emits them on Windows (Path.write_text's default newline
# translation) -- an end anchor would silently stop matching there.
_SEG_NAME_RE = re.compile(r"seg\d+\.ts")
_MAX_AGE_MANIFEST = 1  # matches cache_control()'s "max-age=1" for *.m3u8


def _seq(manifest_text: str) -> int:
    match = _SEQ_RE.search(manifest_text)
    assert match is not None, manifest_text
    return int(match.group(1))


def _segment_names(manifest_text: str) -> list[str]:
    return _SEG_NAME_RE.findall(manifest_text)


def _path(resolved_url: str, base_url: str) -> str:
    return resolved_url[len(base_url) :] if resolved_url.startswith(base_url) else resolved_url


@pytest.fixture
def _clean_proxy_env(monkeypatch: Any) -> Any:
    """Neutral trusted-proxy env so each viewer's distinct peer IP is the
    client, and pin the local media base URL to the in-process origin (same
    setup as ``tests/load/test_switch_lab.py``)."""
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


class _FakeOrigin:
    """A minimal ASGI origin for unit-testing :class:`CachingEdgeASGI`: serves a
    fixed body with the real :func:`cache_control` header for the path, and
    records every request it actually receives -- ground truth for asserting
    what the edge did and did not forward."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.body = b"origin-body"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope["path"]
        self.calls.append(path)
        headers = [(b"cache-control", cache_control(path).encode())]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": self.body})


# ---------------------------------------------------------------------------
# Unit-level: the caching contract itself
# ---------------------------------------------------------------------------


def test_segment_immutability_one_origin_fetch_for_n_viewers() -> None:
    """N viewers fetching the same immutable segment cost the origin exactly 1
    fetch -- this is where the CDN offload actually comes from."""
    origin = _FakeOrigin()
    edge = CachingEdgeASGI(origin, clock=ManualClock())
    client = TestClient(edge)

    n = 10
    for _ in range(n):
        resp = client.get("/live/lab/seg000000001.ts")
        assert resp.status_code == 200
        assert resp.content == origin.body

    assert origin.calls.count("/live/lab/seg000000001.ts") == 1
    assert edge.origin_fetches["segment"] == 1
    assert edge.edge_hits["segment"] >= n - 1


def test_falsifies_the_bug_class_without_the_cache_control_fix(tmp_path: Path) -> None:
    """The exact failure ``cache_control()`` exists to prevent: a provider edge
    with NO real Cache-Control from the origin falls back to its own default
    TTL (``default_ttl_seconds`` simulates that), and keeps serving a stale
    manifest that references a segment the real origin has since evicted.

    This is the RED that makes the lab load-bearing: if the edge could not
    reproduce this failure, it could not prove the fix either.
    """
    live_dir = tmp_path / "live"
    station = RollingStation(live_dir, window=3, segment_bytes=16)
    station.bootstrap()
    initial_names = {p.name for p in live_dir.glob("seg*.ts")}

    # A real Starlette app (not bare StaticFiles) so a miss after eviction comes
    # back as a normal 404 response rather than an unhandled HTTPException --
    # matching how StaticFiles is always actually mounted in production.
    origin = Starlette()
    origin.mount("/", StaticFiles(directory=live_dir))  # no Cache-Control at all -- pre-fix shape
    clock = ManualClock()
    edge = CachingEdgeASGI(origin, clock=clock, default_ttl_seconds=60)
    client = TestClient(edge)

    first = client.get("/playlist.m3u8")
    assert first.status_code == 200
    first_seq = _seq(first.text)
    first_segments = set(_segment_names(first.text))
    assert first_segments <= initial_names

    # Roll the real station far enough that the whole first-fetched window is
    # evicted from disk (the live broadcast has genuinely moved on).
    for _ in range(6):
        station.roll()
    remaining = {p.name for p in live_dir.glob("seg*.ts")}
    assert not (first_segments & remaining), "test setup: those segments should be gone"

    clock.advance(10)  # well within the simulated 60s provider-default TTL
    stale = client.get("/playlist.m3u8")
    assert stale.status_code == 200
    assert _seq(stale.text) == first_seq, (
        "expected the edge to still be serving the STALE cached manifest -- "
        "this is the stall the real cache_control() header prevents"
    )

    # The stale manifest names a segment the real origin has already deleted.
    evicted_segment = next(iter(first_segments))
    missing = client.get(f"/{evicted_segment}")
    assert missing.status_code == 404, (
        "falsification failed: the lab should reproduce a stale manifest "
        "pointing at an evicted segment, but the fetch succeeded"
    )


# ---------------------------------------------------------------------------
# Integration-level: through the real switch-validation harness
# ---------------------------------------------------------------------------


def test_manifest_freshness_bound_after_switch(tmp_path: Path, _clean_proxy_env: Any) -> None:
    """max-age=1 bounds manifest staleness to at most ceil(max_age /
    sync_interval) rolls -- never unboundedly stale, only by the cache's own
    freshness window plus how often the origin actually changes."""
    tick_interval = 0.4
    clock = ManualClock()
    lab = build_switch_lab(
        tmp_path / "live",
        tmp_path / "cdn",
        threshold=1,
        buffer_seconds=0.0,
        tick_interval=tick_interval,
        clock=clock,
        cache_edge=True,
    )
    client = TestClient(lab.app)
    bound = math.ceil(_MAX_AGE_MANIFEST / tick_interval)

    for cycle in range(10):
        clock.advance(tick_interval)
        resolved = client.get(lab.current_url()).json()["manifest_url"]
        true_seq = lab.station.media_sequence  # live state BEFORE this cycle's roll
        resp = client.get(_path(resolved, lab.base_url))
        assert resp.status_code == 200
        lag = true_seq - _seq(resp.text)
        assert 0 <= lag <= bound, f"cycle {cycle}: lag={lag} exceeds bound={bound}"
        lab.station.roll()


def test_origin_offload_scales_with_time_not_viewer_count(
    tmp_path: Path, _clean_proxy_env: Any
) -> None:
    """The whole point of the edge: origin load must scale with wall-clock
    rolls, not with how many viewers are watching. Ramp ~30 viewers, each
    fetching the manifest AND every segment it names (real player traffic),
    through the caching edge post-switch."""
    tick_interval = 1.0
    viewers = 30
    cycles = 8
    clock = ManualClock()
    lab = build_switch_lab(
        tmp_path / "live",
        tmp_path / "cdn",
        threshold=5,
        buffer_seconds=0.0,
        tick_interval=tick_interval,
        clock=clock,
        cache_edge=True,
    )
    client = TestClient(_PerRequestPeerASGI(lab.app))
    requested_segments: set[str] = set()

    for _cycle in range(cycles):
        clock.advance(tick_interval)
        for i in range(viewers):
            headers = {"x-lab-viewer-ip": _viewer_ip(i)}
            resolved = client.get(lab.current_url(), headers=headers).json()["manifest_url"]
            path = _path(resolved, lab.base_url)
            resp = client.get(path, headers=headers)
            assert resp.status_code == 200
            if path.startswith("/cdn-edge"):
                seg_dir = path.rsplit("/", 1)[0]
                for name in _segment_names(resp.text):
                    requested_segments.add(name)
                    seg_resp = client.get(f"{seg_dir}/{name}", headers=headers)
                    assert seg_resp.status_code == 200
        lab.station.roll()

    edge = lab.cache_edge
    assert edge is not None
    assert requested_segments, "test setup: the ramp never reached the CDN"

    # Manifest origin fetches scale with elapsed cycles/rolls (time), not with
    # the 30-viewers-per-cycle traffic that actually hit the edge.
    assert edge.origin_fetches["manifest"] <= cycles + 1, edge.origin_fetches
    assert edge.origin_fetches["manifest"] < viewers, edge.origin_fetches

    # Segment origin fetches: exactly the distinct segments real traffic ever
    # named -- immutable caching means every repeat after the first is a hit.
    assert edge.origin_fetches["segment"] == len(requested_segments)
    assert edge.edge_hits["segment"] > edge.origin_fetches["segment"]


def test_eviction_safety_bounded_blips_through_full_cycle(
    tmp_path: Path, _clean_proxy_env: Any
) -> None:
    """Engage -> release -> evict, driven through the caching edge. The
    switch's correctness (release + full CDN cleanup) must not regress just
    because a caching edge now sits in front of it; any timing blip from
    cache freshness must be bounded, not a stall storm."""
    clock = ManualClock()
    lab = build_switch_lab(
        tmp_path / "live",
        tmp_path / "cdn",
        threshold=4,  # release = max(1, 4 // 2) = 2
        buffer_seconds=0.0,
        tick_interval=1.0,
        clock=clock,
        cache_edge=True,
    )

    engaged = simulate_switch(lab, clock, viewers=6, cycles=6, tick_interval=1.0)
    assert engaged.final_state == "cdn"
    cdn_channel_dir = lab.cdn_dir / "live" / lab.channel_id
    assert list(cdn_channel_dir.glob("*.ts")), "expected segments published to the CDN"
    assert lab.cache_edge is not None
    assert lab.cache_edge.origin_fetches["manifest"] > 0, "edge should have been exercised"

    drained = simulate_switch(lab, clock, viewers=1, cycles=10, tick_interval=1.0)

    assert drained.final_state == "local"
    assert not list(cdn_channel_dir.glob("*.ts")), "CDN segments not evicted on release"
    assert not (cdn_channel_dir / "playlist.m3u8").exists(), "CDN manifest not evicted"
    # Bounded blips: the caching edge must not turn a clean release into a
    # sustained stall storm across either phase.
    assert engaged.stalls <= 1, engaged.stalls
    assert drained.stalls <= 1, drained.stalls
