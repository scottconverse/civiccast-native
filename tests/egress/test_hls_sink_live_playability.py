# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Anti-theater proof: HlsSink produces real, rolling, browser-playable live HLS.

Sprint 0.4 Phase 2 (live HLS packaging). This is the mission's playability
bar: a real ffmpeg process reads a real looping test-pattern source (a
synthetic "live" input — infinite by construction, exactly the shape a live
RTMP/SRT feed would have from the encoder's point of view) and writes a
rolling HLS manifest + segments through ``HlsSink.output_args()`` — the same
output-arg builder the persistent egress encoder uses for a channel with an
``hls`` sink configured (``civiccast.egress.runtime.build_persistent_encoder
_args`` -> ``build_sink`` -> ``HlsSink``, unit-tested directly in
tests/egress/test_contracts.py). This test proves the muxer flags actually
produce a live-updating window, not just that the args parse.

Verifies, in order:
1. The manifest + segments appear on disk within one segment duration.
2. The manifest is served over a REAL HTTP socket by
   ``civiccast.stream.media_router``'s ``/media/live`` mount (not TestClient's
   in-process ASGI transport — ffprobe needs a real socket).
3. ffprobe reads the served manifest over HTTP, resolves relative segment
   URIs exactly as a browser would, and reports a real playable stream.
4. The manifest ROTATES over time: the set of segment filenames referenced
   at t=0 is not the same set referenced ~10s later (old segments drop,
   new ones appear) — proving this is live output, not a static VOD file
   sitting still.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.router import get_egress_store
from civiccast.egress.sinks import HlsSink, build_sink
from civiccast.egress.store import InMemoryEgressStore
from civiccast.stream._ffmpeg import FfmpegProcessHandle, start_ffmpeg
from civiccast.stream.media_router import live_router

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH; live-HLS playability proof skipped",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


class _BackgroundUvicorn:
    """Real ASGI server on a real socket — ffprobe cannot speak TestClient's
    in-process transport, so it needs an actual HTTP listener."""

    def __init__(self, app: FastAPI, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none")
        self._server = uvicorn.Server(config)
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # surfaced to the main thread via __enter__
            self._error = exc

    def __enter__(self) -> _BackgroundUvicorn:
        self._thread.start()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return self
            if self._error is not None:
                raise RuntimeError(f"uvicorn failed to start: {self._error!r}") from self._error
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not report started within 15s")

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10.0)


def _start_live_hls_encoder(live_dir: Path) -> FfmpegProcessHandle:
    """Start a real, persistent ffmpeg process: a looping synthetic test
    pattern (infinite by construction — the same "no defined end" shape a
    live RTMP/SRT feed has) muxed to rolling HLS via HlsSink's own args.

    This exercises HlsSink.output_args() exactly as
    ``civiccast.egress.runtime.build_persistent_encoder_args`` would append
    it to a channel's sink list — the only difference from the real egress
    path is the input side (lavfi test pattern here vs. the encoder's
    conformed concat input in production), which is the live-vs-recorded
    distinction the mission asks this test to stand in for.

    Deliberately does NOT pass ``-c:v``/``-g`` on the input side: production's
    common no-branding path reaches ``HlsSink.output_args()`` via a plain
    ``-c copy`` (see ``egress.runtime._stream_mapping_args``), i.e. with
    whatever GOP the upstream source already has — arbitrarily large, and
    entirely outside HlsSink's control. Using a raw testsrc input (no prior
    encode, so no "coincidentally helpful" GOP either) means this test can
    only pass if HlsSink.output_args() itself forces the keyframe cadence.
    """
    sink = build_sink(EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir)))
    assert isinstance(sink, HlsSink)
    input_args = [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x180:rate=15",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
    ]
    return start_ffmpeg([*input_args, *sink.output_args()])


def _read_segment_names(manifest_text: str) -> set[str]:
    return {line.strip() for line in manifest_text.splitlines() if line.strip().endswith(".ts")}


def _read_segment_durations(manifest_text: str) -> list[float]:
    """Parse #EXTINF:<seconds>, values in manifest order.

    This is the assertion the keyframe-cadence gap needs: "the segment set
    changed" also passes when segments are 8x too long (fewer, bigger
    segments still eventually rotate) -- only checking the actual duration
    against HlsSink.segment_seconds catches a muxer that's cutting on
    whatever keyframes happen to arrive instead of the requested cadence.
    """
    durations = []
    for line in manifest_text.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            durations.append(float(line.removeprefix("#EXTINF:").rstrip(",")))
    return durations


def test_hls_sink_produces_rolling_playable_live_manifest(tmp_path: Path) -> None:
    """The mission's core proof: real ffmpeg, real rolling HLS, real HTTP,
    real ffprobe, and the manifest actually updates over time."""

    live_dir = tmp_path / "live-hls" / "gov-ch12"
    handle = _start_live_hls_encoder(live_dir)
    try:
        manifest_path = live_dir / "playlist.m3u8"
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and not manifest_path.exists():
            time.sleep(0.2)
        assert manifest_path.exists(), "ffmpeg never wrote a live manifest within 30s"

        # Let a few segments land so the sliding window has real content.
        deadline = time.monotonic() + 20.0
        first_segments: set[str] = set()
        while time.monotonic() < deadline:
            first_segments = _read_segment_names(manifest_path.read_text(encoding="utf-8"))
            if len(first_segments) >= 2:
                break
            time.sleep(0.5)
        assert len(first_segments) >= 2, (
            f"expected at least 2 live segments referenced; got {first_segments}"
        )

        # BLOCKING fix proof: assert real segment duration, not just "some
        # segments exist". Without a forced keyframe cadence, ffmpeg's HLS
        # muxer cuts on whatever keyframe arrives -- previously this produced
        # ~16.67s segments (8x the documented 2s) while still satisfying a
        # "count >= 2" check. HlsSink.segment_seconds is the documented,
        # coded-for target; segments must land close to it.
        first_durations = _read_segment_durations(manifest_path.read_text(encoding="utf-8"))
        assert first_durations, "manifest has no #EXTINF entries to check duration against"
        for duration in first_durations:
            assert duration <= HlsSink.segment_seconds * 1.5, (
                f"segment duration {duration}s is not close to the documented "
                f"{HlsSink.segment_seconds}s target -- the hls muxer is cutting on "
                "whatever keyframe cadence the upstream encode happens to produce, "
                "not the requested -hls_time (missing -force_key_frames/-g control)"
            )

        # Serve it for real over HTTP.
        store = InMemoryEgressStore()
        store.upsert_config(
            EgressConfig(
                channel_id="gov-ch12",
                enabled=True,
                slate_message="Off air",
                sinks=[EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir))],
            )
        )
        app = FastAPI()
        app.include_router(live_router)
        app.dependency_overrides[get_egress_store] = lambda: store
        port = _free_port()

        with _BackgroundUvicorn(app, port) as server:
            served_manifest_url = f"{server.base_url}/media/live/gov-ch12/playlist.m3u8"

            manifest_response = httpx.get(served_manifest_url, timeout=10.0)
            assert manifest_response.status_code == 200
            assert manifest_response.headers["content-type"] == "application/vnd.apple.mpegurl"
            assert manifest_response.text.startswith("#EXTM3U")

            # ffprobe reads the served manifest over HTTP and resolves the
            # segment URIs relative to it, exactly as a browser/hls.js would.
            ffprobe_result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,format_name:stream=codec_type,codec_name,width,height",
                    "-of",
                    "json",
                    served_manifest_url,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert ffprobe_result.returncode == 0, (
                f"ffprobe could not read the served live HLS manifest: {ffprobe_result.stderr}"
            )
            probe_json = json.loads(ffprobe_result.stdout)
            codec_types = {stream["codec_type"] for stream in probe_json["streams"]}
            assert "video" in codec_types, f"ffprobe found no video stream: {probe_json}"
            assert "audio" in codec_types, f"ffprobe found no audio stream: {probe_json}"

            print("FFPROBE PROOF:", ffprobe_result.stdout)

            # The rolling-window proof: wait past several segment durations
            # and confirm the referenced segment set actually changed (old
            # segments dropped by ffmpeg's own delete_segments, new ones
            # appended) -- this is what makes it LIVE output, not a static
            # file that happens to be reachable over HTTP.
            deadline = time.monotonic() + 20.0
            rotated = False
            later_segments: set[str] = set()
            while time.monotonic() < deadline:
                time.sleep(1.0)
                later_response = httpx.get(served_manifest_url, timeout=10.0)
                assert later_response.status_code == 200
                later_segments = _read_segment_names(later_response.text)
                if later_segments and later_segments != first_segments:
                    rotated = True
                    break
            assert rotated, (
                f"live manifest never rotated: first={first_segments} "
                f"still={later_segments} after 20s -- this would mean the "
                f"output is static, not a real rolling live window"
            )
            later_durations = _read_segment_durations(later_response.text)
            for duration in later_durations:
                assert duration <= HlsSink.segment_seconds * 1.5, (
                    f"rotated segment duration {duration}s drifted from the "
                    f"documented {HlsSink.segment_seconds}s target"
                )

            # New segments referenced by the rotated manifest must themselves
            # be servable (delete_segments must not have raced ahead of the
            # manifest write and 404'd a segment the manifest still lists).
            for segment_name in later_segments:
                segment_response = httpx.get(
                    f"{server.base_url}/media/live/gov-ch12/{segment_name}", timeout=10.0
                )
                assert segment_response.status_code == 200, (
                    f"manifest references {segment_name} but it 404s"
                )
    finally:
        handle.terminate(grace_seconds=5.0)
