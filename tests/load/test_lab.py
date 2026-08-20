# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the synthetic rolling-station load lab."""

from __future__ import annotations

import asyncio
import itertools
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.load.hls_load import parse_media_playlist
from civiccast.load.lab import (
    RollingStation,
    _roll_forever,
    build_lab_app,
    render_bandwidth_table,
    render_ramp_table,
    run_ramp,
    segment_name,
)

# --- segment naming ----------------------------------------------------------


def test_segment_name_zero_pads_to_nine_digits() -> None:
    assert segment_name(0) == "seg000000000.ts"
    assert segment_name(42) == "seg000000042.ts"
    assert segment_name(123456789) == "seg123456789.ts"


# --- manifest rendering (round-tripped through the harness parser) -----------


def _station(tmp_path: Path, **kwargs: object) -> RollingStation:
    return RollingStation(tmp_path / "live", **kwargs)  # type: ignore[arg-type]


def test_rendered_manifest_is_live_and_parses_back_to_its_segments(tmp_path: Path) -> None:
    station = _station(tmp_path, window=3, segment_bytes=64)
    station.bootstrap()
    text = (station.directory / "playlist.m3u8").read_text(encoding="utf-8")

    parsed = parse_media_playlist(text)
    assert not parsed.is_endlist  # live, never terminated
    assert not parsed.is_multivariant
    assert parsed.target_duration == 2.0
    assert parsed.media_sequence == 0
    assert parsed.segment_uris == (
        "seg000000000.ts",
        "seg000000001.ts",
        "seg000000002.ts",
    )


# --- rolling window ----------------------------------------------------------


def _segment_files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.glob("seg*.ts"))


def test_bootstrap_writes_a_full_window_of_sized_segments(tmp_path: Path) -> None:
    station = _station(tmp_path, window=4, segment_bytes=128)
    station.bootstrap()

    assert station.media_sequence == 0
    assert _segment_files(station.directory) == [segment_name(n) for n in range(4)]
    assert (station.directory / segment_name(0)).stat().st_size == 128


def test_roll_advances_the_window_and_evicts_the_oldest(tmp_path: Path) -> None:
    station = _station(tmp_path, window=3, segment_bytes=64)
    station.bootstrap()

    station.roll()  # append seg3, evict seg0

    assert station.media_sequence == 1
    assert _segment_files(station.directory) == [segment_name(n) for n in (1, 2, 3)]
    parsed = parse_media_playlist((station.directory / "playlist.m3u8").read_text())
    assert parsed.media_sequence == 1
    assert parsed.segment_uris == (segment_name(1), segment_name(2), segment_name(3))


def test_repeated_rolls_hold_the_window_size_constant(tmp_path: Path) -> None:
    station = _station(tmp_path, window=5, segment_bytes=64)
    station.bootstrap()
    for _ in range(20):
        station.roll()

    files = _segment_files(station.directory)
    assert len(files) == 5  # never grows, never shrinks
    assert station.media_sequence == 20
    assert files == [segment_name(n) for n in range(20, 25)]


def test_roll_survives_an_evicted_segment_held_open(tmp_path: Path) -> None:
    # A viewer's FileResponse can still hold the just-evicted segment open;
    # on Windows that blocks unlink (WinError 32). roll() must not raise, and
    # the manifest must stay correct regardless. A later roll cleans it up.
    station = _station(tmp_path, window=2, segment_bytes=64)
    station.bootstrap()  # seg0, seg1
    with (station.directory / segment_name(0)).open("rb"):
        station.roll()  # evicts seg0 while it is open

    parsed = parse_media_playlist((station.directory / "playlist.m3u8").read_text())
    assert parsed.segment_uris == (segment_name(1), segment_name(2))

    station.roll()  # handle released -> deferred delete is retried
    assert not (station.directory / segment_name(0)).exists()


def test_rolling_station_rejects_nonpositive_window_or_segment_bytes(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _station(tmp_path, window=0)
    with pytest.raises(ValueError):
        _station(tmp_path, segment_bytes=0)


# --- _roll_forever must not block the shared event loop ----------------------


class _SlowRollStation:
    """Duck-typed station whose .roll() blocks synchronously, like a Windows
    sharing-violation retry loop (_replace_with_retry's time.sleep) would."""

    target_duration = 0.01

    def __init__(self) -> None:
        self.roll_calls = 0

    def roll(self) -> None:
        self.roll_calls += 1
        time.sleep(0.2)  # simulates the blocking retry path


async def test_roll_forever_does_not_block_the_event_loop() -> None:
    # A ticker coroutine on the same loop should keep ticking at ~10ms while
    # _roll_forever's station.roll() is "busy" for 0.2s. If roll() runs
    # in-coroutine (not offloaded to a thread), the tick gaps balloon to ~0.2s.
    station = _SlowRollStation()
    stop = asyncio.Event()
    ticks: list[float] = []

    async def ticker() -> None:
        for _ in range(15):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    roller = asyncio.create_task(_roll_forever(station, stop))
    await ticker()
    stop.set()
    await roller

    assert station.roll_calls >= 1
    gaps = [b - a for a, b in itertools.pairwise(ticks)]
    assert max(gaps) < 0.15  # no tick was starved by roll()'s blocking sleep


# --- serving through the real live_router ------------------------------------


def _served_station(tmp_path: Path) -> RollingStation:
    station = _station(tmp_path, window=3, segment_bytes=256)
    station.bootstrap()
    return station


def test_lab_app_serves_manifest_with_live_cache_headers(tmp_path: Path) -> None:
    station = _served_station(tmp_path)
    client = TestClient(build_lab_app(station.directory))

    resp = client.get("/media/live/lab/playlist.m3u8")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.apple.mpegurl"
    assert resp.headers["cache-control"] == "public, max-age=1, must-revalidate"
    assert "#EXTM3U" in resp.text


def test_lab_app_serves_segment_bytes_with_immutable_cache(tmp_path: Path) -> None:
    station = _served_station(tmp_path)
    client = TestClient(build_lab_app(station.directory))

    resp = client.get("/media/live/lab/seg000000000.ts")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "video/MP2T"
    assert "immutable" in resp.headers["cache-control"]
    assert len(resp.content) == 256


def test_lab_app_404s_unknown_channel(tmp_path: Path) -> None:
    station = _served_station(tmp_path)
    client = TestClient(build_lab_app(station.directory, channel_id="lab"))

    assert client.get("/media/live/other/playlist.m3u8").status_code == 404


def test_lab_app_404s_missing_file(tmp_path: Path) -> None:
    station = _served_station(tmp_path)
    client = TestClient(build_lab_app(station.directory))

    assert client.get("/media/live/lab/seg000000999.ts").status_code == 404


# --- ramp integration (real router, in-process) ------------------------------


async def test_run_ramp_drives_viewers_against_the_real_router() -> None:
    # One short level; proves station -> real live_router -> run_load wiring.
    reports = await run_ramp(
        [2],
        duration_s=0.1,
        window=3,
        segment_bytes=512,
        uplink_mbps=1000,
        per_viewer_mbps=4.628,
    )

    assert len(reports) == 1
    report = reports[0]
    assert report.viewers == 2
    assert report.manifest_ok >= 2  # each viewer fetched the live manifest
    assert report.segments_ok > 0  # and pulled real segment bytes
    assert report.manifest_failed == 0
    assert report.bandwidth_ceiling_viewers == 216  # 1000 // 4.628


async def test_run_ramp_stays_healthy_across_a_real_roll() -> None:
    # duration > HLS_SEGMENT_DURATION (2s) so the station rolls at ~t=2s while
    # viewers are still fetching through the real live_router -- exercising the
    # concurrent roll-while-read race end-to-end (the WinError 32 path). Each
    # viewer re-polls at t=0 and t=2, so manifest_ok >= 6 proves serving
    # continued across the roll boundary, healthy the whole way.
    reports = await run_ramp([3], duration_s=3.0, window=3, segment_bytes=512)

    assert len(reports) == 1
    report = reports[0]
    assert report.manifest_failed == 0
    assert report.manifest_ok >= 6  # 3 viewers x 2 polls, the second post-roll
    assert report.segments_ok >= 3  # served real segment bytes
    assert report.stall_rate == 0.0  # no viewer fell out of the window or behind live


# --- reporting ---------------------------------------------------------------


def test_render_ramp_table_has_a_row_per_level() -> None:
    from civiccast.load.hls_load import LoadReport

    def _rep(viewers: int) -> LoadReport:
        return LoadReport(
            viewers=viewers,
            duration_s=10.0,
            wall_time_s=10.0,
            manifest_ok=viewers * 5,
            manifest_failed=0,
            segments_ok=viewers * 5,
            segments_failed=0,
            segments_slow=0,
            bytes_downloaded=viewers * 1_000_000,
            join_latency_p50_s=0.01,
            join_latency_p95_s=0.02,
        )

    table = render_ramp_table([_rep(10), _rep(50), _rep(100)])
    lines = table.splitlines()
    assert "viewers" in lines[0]
    # header + separator + 3 data rows
    assert len(lines) == 5
    assert lines[2].split()[0] == "10"
    assert lines[4].split()[0] == "100"


def test_render_bandwidth_table_is_code_derived_from_the_ladder() -> None:
    table = render_bandwidth_table([100, 500, 1000])

    assert "| 1080p |" in table
    assert "| 240p |" in table
    # 1 Gbps / 4.628 Mbps (1080p) == 216 direct viewers, floor.
    row_1080p = next(line for line in table.splitlines() if line.startswith("| 1080p |"))
    assert row_1080p.strip().endswith("| 216 |")
    # 100 Mbps / 4.628 == 21.
    assert "| 21 |" in row_1080p
