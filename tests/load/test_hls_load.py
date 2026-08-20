# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the concurrent HLS live-viewer load generator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from civiccast.load.hls_load import (
    LoadReport,
    _exit_code,
    _percentile,
    _render_report,
    bandwidth_ceiling,
    parse_media_playlist,
    run_load,
)

_MEDIA_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-TARGETDURATION:1\n"
    "#EXT-X-MEDIA-SEQUENCE:1\n"
    "#EXTINF:1.0,\n"
    "seg000000001.ts\n"
    "#EXTINF:1.0,\n"
    "seg000000002.ts\n"
)

_MULTIVARIANT_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
    "720p/playlist.m3u8\n"
)


# --- parsing -----------------------------------------------------------------


def test_parse_media_playlist_reads_segments_and_target_duration() -> None:
    playlist = parse_media_playlist(_MEDIA_PLAYLIST)
    assert playlist.segment_uris == ("seg000000001.ts", "seg000000002.ts")
    assert playlist.target_duration == 1.0
    assert playlist.media_sequence == 1
    assert not playlist.is_endlist
    assert not playlist.is_multivariant


def test_parse_multivariant_playlist_collects_variants_not_segments() -> None:
    playlist = parse_media_playlist(_MULTIVARIANT_PLAYLIST)
    assert playlist.is_multivariant
    assert playlist.variant_uris == ("720p/playlist.m3u8",)
    assert playlist.segment_uris == ()


def test_parse_detects_endlist() -> None:
    assert parse_media_playlist(_MEDIA_PLAYLIST + "#EXT-X-ENDLIST\n").is_endlist


# --- bandwidth ceiling -------------------------------------------------------


def test_bandwidth_ceiling_is_uplink_over_per_viewer() -> None:
    assert bandwidth_ceiling(100, 3) == 33  # a 100 Mbps uplink, 3 Mbps/viewer
    assert bandwidth_ceiling(1000, 5) == 200


def test_bandwidth_ceiling_rejects_nonpositive_bitrate() -> None:
    with pytest.raises(ValueError):
        bandwidth_ceiling(100, 0)


def test_bandwidth_ceiling_rejects_nonpositive_uplink() -> None:
    with pytest.raises(ValueError):
        bandwidth_ceiling(-1000, 5)  # would silently compute a negative ceiling
    with pytest.raises(ValueError):
        bandwidth_ceiling(0, 5)


# --- end-to-end load run against a real ASGI file server ---------------------


def _live_app(live_dir: Path) -> FastAPI:
    app = FastAPI()

    @app.get("/live/{file_path:path}")
    def serve(file_path: str) -> FileResponse:
        candidate = live_dir / file_path
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(candidate)

    return app


def _write_live_dir(tmp_path: Path) -> Path:
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "seg000000001.ts").write_bytes(b"x" * 1000)
    (live_dir / "seg000000002.ts").write_bytes(b"y" * 1000)
    (live_dir / "playlist.m3u8").write_text(_MEDIA_PLAYLIST)
    return live_dir


async def test_run_load_fetches_all_segments_for_every_viewer(tmp_path: Path) -> None:
    live_dir = _write_live_dir(tmp_path)
    transport = httpx.ASGITransport(app=_live_app(live_dir))
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8",
            viewers=5,
            duration_s=0.5,
            client=client,
            uplink_mbps=100,
            per_viewer_mbps=3,
        )

    assert report.viewers == 5
    assert report.manifest_ok >= 5
    assert report.manifest_failed == 0
    # 5 viewers x 2 distinct segments, each fetched once.
    assert report.segments_ok == 10
    assert report.segments_failed == 0
    assert report.stall_rate == 0.0
    assert report.bytes_downloaded == 10 * 1000
    assert report.join_latency_p50_s is not None
    assert report.bandwidth_ceiling_viewers == 33


async def test_run_load_counts_missing_segments_as_hard_stalls(tmp_path: Path) -> None:
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    # Manifest lists two segments but only one exists on disk (the other has
    # "rolled out of the window") -> a hard stall for each viewer.
    (live_dir / "seg000000001.ts").write_bytes(b"x" * 1000)
    (live_dir / "playlist.m3u8").write_text(_MEDIA_PLAYLIST)
    transport = httpx.ASGITransport(app=_live_app(live_dir))
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8",
            viewers=3,
            duration_s=0.5,
            client=client,
        )

    assert report.segments_ok == 3  # seg1 for each of 3 viewers
    assert report.segments_failed == 3  # seg2 missing for each
    assert report.stall_rate > 0.0


# --- multivariant follow (run_load resolves the first variant, then plays it) --


_MASTER_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n"
    "720p/playlist.m3u8\n"
)

_MEDIA_WITH_ENDLIST = _MEDIA_PLAYLIST + "#EXT-X-ENDLIST\n"


async def test_run_load_follows_first_variant_of_a_multivariant_manifest(tmp_path: Path) -> None:
    live_dir = tmp_path / "live"
    (live_dir / "720p").mkdir(parents=True)
    (live_dir / "playlist.m3u8").write_text(_MASTER_PLAYLIST)
    (live_dir / "720p" / "playlist.m3u8").write_text(_MEDIA_WITH_ENDLIST)
    (live_dir / "720p" / "seg000000001.ts").write_bytes(b"x" * 1000)
    (live_dir / "720p" / "seg000000002.ts").write_bytes(b"y" * 1000)

    transport = httpx.ASGITransport(app=_live_app(live_dir))
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=2, duration_s=1.0, client=client
        )

    # Each viewer fetches master + variant (2 manifests) and both variant segments.
    assert report.manifest_ok == 4
    assert report.segments_ok == 4
    assert report.segments_failed == 0


# --- soft stall: a segment that takes longer than one segment-duration to fetch -


_SLOW_MEDIA_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-TARGETDURATION:0.2\n"  # fractional so the test triggers a slow fetch fast
    "#EXT-X-MEDIA-SEQUENCE:1\n"
    "#EXTINF:0.2,\n"
    "seg000000001.ts\n"
    "#EXT-X-ENDLIST\n"
)


def _slow_segment_app(live_dir: Path, *, segment_delay_s: float) -> FastAPI:
    app = FastAPI()

    @app.get("/live/{file_path:path}")
    async def serve(file_path: str) -> FileResponse:
        candidate = live_dir / file_path
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="not found")
        if candidate.suffix == ".ts":
            await asyncio.sleep(segment_delay_s)  # fetch takes > target_duration
        return FileResponse(candidate)

    return app


async def test_run_load_counts_slow_fetches_as_behind_live(tmp_path: Path) -> None:
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    (live_dir / "playlist.m3u8").write_text(_SLOW_MEDIA_PLAYLIST)
    (live_dir / "seg000000001.ts").write_bytes(b"x" * 1000)

    # 0.35s fetch vs a 0.2s segment duration -> the viewer is falling behind live.
    transport = httpx.ASGITransport(app=_slow_segment_app(live_dir, segment_delay_s=0.35))
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=1, duration_s=3.0, client=client
        )

    assert report.segments_ok == 1
    assert report.segments_slow == 1
    assert report.stall_rate > 0.0


# --- transport failures (httpx.HTTPError branches) ---------------------------


def _mock_transport(
    manifest_text: str,
    *,
    fail_manifest: bool = False,
    fail_segment: bool = False,
    manifest_status: int = 200,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".m3u8"):
            if fail_manifest:
                raise httpx.ConnectError("manifest unreachable")
            return httpx.Response(
                manifest_status,
                text=manifest_text,
                headers={"content-type": "application/vnd.apple.mpegurl"},
            )
        if fail_segment:
            raise httpx.ConnectError("segment unreachable")
        return httpx.Response(200, content=b"x" * 500)

    return httpx.MockTransport(handler)


async def test_run_load_records_manifest_transport_errors() -> None:
    transport = _mock_transport(_MEDIA_WITH_ENDLIST, fail_manifest=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=1, duration_s=0.3, client=client
        )
    assert report.manifest_failed >= 1
    assert report.manifest_ok == 0
    assert report.segments_ok == 0


async def test_run_load_records_manifest_non_success_status() -> None:
    transport = _mock_transport(_MEDIA_WITH_ENDLIST, manifest_status=503)
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=1, duration_s=0.3, client=client
        )
    assert report.manifest_failed >= 1
    assert report.segments_ok == 0


_MALFORMED_MEDIA_PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXT-X-TARGETDURATION:\n"  # malformed: no digits after the colon
    "#EXT-X-MEDIA-SEQUENCE:1\n"
    "#EXTINF:1.0,\n"
    "seg000000001.ts\n"
)


async def test_run_load_survives_a_malformed_manifest_without_losing_the_run() -> None:
    # One viewer's manifest parse blows up (ValueError); this must not take
    # down the whole gather()/run -- it should count as a manifest failure,
    # like an unreachable manifest, and the run must still return a report.
    transport = _mock_transport(_MALFORMED_MEDIA_PLAYLIST)
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=3, duration_s=0.3, client=client
        )
    assert report.manifest_failed >= 1
    assert report.segments_ok == 0


async def test_run_load_records_segment_transport_errors() -> None:
    transport = _mock_transport(_MEDIA_WITH_ENDLIST, fail_segment=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://station") as client:
        report = await run_load(
            "http://station/live/playlist.m3u8", viewers=1, duration_s=0.3, client=client
        )
    assert report.manifest_ok >= 1
    assert report.segments_failed >= 1
    assert report.segments_ok == 0


async def test_run_load_rejects_zero_viewers() -> None:
    with pytest.raises(ValueError):
        await run_load("http://station/live/playlist.m3u8", viewers=0, duration_s=0.1)


# --- _percentile edge cases --------------------------------------------------


def test_percentile_of_empty_is_none() -> None:
    assert _percentile([], 50) is None


def test_percentile_of_single_value_is_that_value() -> None:
    assert _percentile([0.5], 95) == 0.5


def test_percentile_interpolates_between_two_values() -> None:
    assert _percentile([10.0, 20.0], 50) == 15.0
    assert _percentile([10.0, 20.0], 95) == 19.5


def test_percentile_interpolates_across_many_values() -> None:
    values = [float(n) for n in range(10)]  # 0.0 .. 9.0
    assert _percentile(values, 95) == pytest.approx(8.55)


# --- LoadReport derived metrics + rendering ----------------------------------


def _report(**overrides: object) -> LoadReport:
    base: dict[str, object] = {
        "viewers": 2,
        "duration_s": 30.0,
        "wall_time_s": 30.0,
        "manifest_ok": 20,
        "manifest_failed": 0,
        "segments_ok": 40,
        "segments_failed": 0,
        "segments_slow": 0,
        "bytes_downloaded": 10_000_000,
        "join_latency_p50_s": 0.01,
        "join_latency_p95_s": 0.02,
    }
    base.update(overrides)
    return LoadReport(**base)  # type: ignore[arg-type]


def test_stall_rate_is_zero_when_no_segments_attempted() -> None:
    assert _report(segments_ok=0, segments_failed=0).stall_rate == 0.0


def test_aggregate_mbps_is_zero_when_no_wall_time() -> None:
    assert _report(wall_time_s=0.0).aggregate_mbps == 0.0


def test_as_dict_is_json_serializable_and_adds_derived_fields() -> None:
    data = _report(bandwidth_ceiling_viewers=33, per_viewer_mbps=3, uplink_mbps=100).as_dict()
    json.dumps(data)  # must not raise
    assert data["stall_rate"] == 0.0
    assert "aggregate_mbps" in data


def test_summary_reports_stalls_latency_and_ceiling() -> None:
    text = _report(
        segments_failed=4, bandwidth_ceiling_viewers=33, per_viewer_mbps=3, uplink_mbps=100
    ).summary()
    assert "viewers=2" in text
    assert "join latency" in text
    assert "bandwidth ceiling" in text


# --- CLI logic seams (exit code + rendering; no asyncio.run in the tests) -----


def test_exit_code_is_zero_on_a_clean_run() -> None:
    assert _exit_code(_report()) == 0


def test_exit_code_is_one_when_viewers_stalled() -> None:
    assert _exit_code(_report(segments_failed=5)) == 1


def test_exit_code_is_one_when_the_manifest_failed() -> None:
    assert _exit_code(_report(manifest_failed=2)) == 1


def test_render_report_json_is_valid_json() -> None:
    payload = json.loads(_render_report(_report(), as_json=True))
    assert payload["viewers"] == 2
    assert "stall_rate" in payload


def test_render_report_text_is_a_human_summary() -> None:
    assert "viewers=2" in _render_report(_report(), as_json=False)
