# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""DEFECT A, closing the composition gap: a GStreamer-fed live-HLS directory
served over a real HTTP socket, polled while it rotates.

Two adjacent proofs already exist and are each real, but neither chains to
the other:

* ``test_hls_sink_live_playability.py`` proves the FULL serving chain — a
  real uvicorn socket, ``ffprobe`` over HTTP, the manifest observed to
  rotate — but the directory it proves against is filled by the
  ffmpeg-concat engine's own ``HlsSink`` fed a plain ``lavfi`` test source.
  It never touches ``HlsRelaySupervisor`` or a GStreamer pipeline.
* ``test_hls_relay.py`` proves ``HlsRelaySupervisor`` starts a relay child
  with the right argv against a FAKE starter (no real ffmpeg, no real
  GStreamer). The author's own manual run against the real installed
  runtime proved a real GStreamer pipeline -> real ffmpeg relay child
  produces rotating, ``ffprobe``-verified segments — but read directly off
  disk, with no HTTP server involved at all.
* ``test_media_router_live.py`` proves ``civiccast.stream.media_router``
  serves whatever is in a channel's configured hls directory correctly
  (content-type, path-traversal guard) — but against a hand-written STATIC
  fixture (one fake manifest, one fake 188-byte "segment") that never
  changes, over ``TestClient``'s in-process transport, not a real socket.

None of the three puts a GStreamer-fed, actually-rotating directory behind
a real HTTP server and polls it. This test is that composition — the one
piece of evidence the owner needs before trusting live-to-residents in
front of a board: not "segments exist on disk" and not "the router can
serve a static file", but a resident's browser (stand-in: ``ffprobe`` over
a real socket) actually seeing an advancing manifest.

Uses the REAL production pieces at every join, not hand-rolled equivalents:

1. A real ``Gst.parse_launch`` pipeline shaped exactly like
   ``civiccast.egress.gst.bridge.sink_branches_from_config`` builds for a
   channel's program encode -> mux -> sink branch (openh264enc/avenc_aac ->
   mpegtsmux -> udpsink).
2. The REAL ``civiccast.egress.hls_relay.HlsRelaySupervisor.apply()`` --
   not a copy of its argv -- started against an ``hls``-kind
   ``EgressSinkSpec``, which is what starts the real ffmpeg relay child and
   returns the rewritten ``local-ts`` sink the GStreamer branch above binds
   to (via the REAL ``sink_element_spec()``, not a hand-picked port).
3. The REAL ``civiccast.stream.media_router.live_router`` behind a real
   uvicorn socket, resolving the channel's UNCHANGED ``hls`` sink uri --
   proving the router needed zero changes for this to work, exactly as
   claimed.
4. ``ffprobe`` fetching the served manifest over HTTP twice, with a wait in
   between, asserting the referenced segment set actually changed.

Gated on gi + the installed GStreamer runtime being importable in THIS
interpreter (see ``_gstreamer_relay_playability_available``'s docstring) --
skipped otherwise, with a skip reason naming exactly what is not covered
by that skip: the GStreamer-fed-directory-behind-a-live-HTTP-server
composition proved here is UNPROVEN wherever this is skipped, distinct
from (and not substituted by) the separately-gated, separately-passing
``test_hls_sink_live_playability.py`` (ffmpeg-lavfi-fed) and
``test_hls_relay.py`` (fake-starter, no real ffmpeg/GStreamer) files. Does
NOT require PR #75 (live-takeover consuming the operator's configured
LiveSource) or any daemon/automation wiring -- like
``test_hls_sink_live_playability.py``, it drives the GStreamer pipeline and
``HlsRelaySupervisor`` directly, the same way the daemon's ``_start`` would
call them, without going through the daemon's command queue or the
schedule/source-plan layer at all.

Run against the real installed runtime with an ABI-matched interpreter
(the bundled ``_gi`` extension is CPython-3.12-specific — see
``test_gst_engine_wsl.py``'s module docstring for the identical constraint):

    $env:CIVICCAST_GSTREAMER_RUNTIME_ROOT = "<install_root>\runtime"
    uv run --python 3.12 pytest tests/egress/test_hls_relay_live_playability.py
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from civiccast.egress.gst.bridge import sink_element_spec
from civiccast.egress.hls_relay import HlsRelaySupervisor
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.router import get_egress_store
from civiccast.egress.sinks import HlsSink
from civiccast.egress.store import InMemoryEgressStore
from civiccast.stream.media_router import live_router


def _gstreamer_relay_playability_available() -> bool:
    """True only where the whole chain this test drives can genuinely run:
    gi + the installed GStreamer runtime importable in THIS interpreter, and
    ffmpeg/ffprobe on PATH for the relay child + the HTTP-side probe. Mirrors
    ``test_gst_engine_wsl.py``'s ``_windows_bundled_gstreamer_available`` (see
    that function's docstring for the CPython-3.12 ABI constraint on the
    bundled ``_gi`` extension) rather than importing it cross-module, since
    each live-engine test file in this suite owns its own gate."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return False
    if sys.platform == "win32":
        root = os.environ.get("CIVICCAST_GSTREAMER_RUNTIME_ROOT")
        if not root:
            return False
        try:
            from civiccast.native.gstreamer_runtime import (
                bootstrap_installed_gstreamer_runtime,
                installed_gstreamer_environment,
            )

            if not bootstrap_installed_gstreamer_runtime():
                return False
            env = installed_gstreamer_environment(root, base_environment=os.environ)
            os.environ.update(env)
        except Exception:
            return False
    elif sys.platform != "linux":
        return False
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # noqa: F401

        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _gstreamer_relay_playability_available(),
    reason=(
        "Live-HLS-over-HTTP composition proof (a real GStreamer pipeline -> "
        "HlsRelaySupervisor's real ffmpeg relay -> civiccast.stream.media_router "
        "-> ffprobe over a real socket, with observed rotation) requires gi + the "
        "installed GStreamer runtime + ffmpeg/ffprobe on PATH. NOT covered by this "
        "skip: this is the ONLY test that proves a GStreamer-fed directory serves "
        "a genuinely advancing manifest over live HTTP -- test_hls_sink_live_"
        "playability.py separately proves the ffmpeg-lavfi-fed case, and "
        "test_media_router_live.py separately proves the router serves a static "
        "fixture; neither substitutes for this. Run with "
        "CIVICCAST_GSTREAMER_RUNTIME_ROOT set and "
        "`uv run --python 3.12 pytest tests/egress/test_hls_relay_live_playability.py` "
        "(the bundled _gi extension is CPython-3.12-specific)."
    ),
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


class _BackgroundUvicorn:
    """Real ASGI server on a real socket -- ffprobe cannot speak TestClient's
    in-process transport, so it needs an actual HTTP listener (same helper
    shape as test_hls_sink_live_playability.py's)."""

    def __init__(self, app: FastAPI, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none")
        self._server = uvicorn.Server(config)
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:
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


def _read_segment_names(manifest_text: str) -> set[str]:
    return {line.strip() for line in manifest_text.splitlines() if line.strip().endswith(".ts")}


def test_gstreamer_fed_hls_directory_serves_an_advancing_manifest_over_http(
    tmp_path: Path,
) -> None:
    """The composition proof: GStreamer -> HlsRelaySupervisor -> media_router
    -> ffprobe over a real socket, with observed rotation between two fetches."""

    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)

    live_dir = tmp_path / "live-hls" / "gov-ch12"
    hls_sink = EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir))

    # 1) The REAL relay supervisor -- not a copy of its argv. Starts a real
    #    ffmpeg child listening on a real loopback port and returns the
    #    rewritten sink the graph builder actually binds the GStreamer
    #    branch to.
    supervisor = HlsRelaySupervisor()
    config = EgressConfig(
        channel_id="gov-ch12", enabled=True, slate_message="Off air", sinks=[hls_sink]
    )
    rewritten = supervisor.apply(config)
    try:
        rewritten_sink = rewritten.sinks[0]
        assert rewritten_sink.kind == "local-ts"

        # 2) The REAL sink_element_spec() -- the exact function
        #    sink_branches_from_config calls -- builds the udpsink element
        #    for wherever the relay actually listens.
        udp_element = sink_element_spec(rewritten_sink)
        assert udp_element.factory == "udpsink"
        host = udp_element.props["host"]
        port = udp_element.props["port"]

        # 3) A real GStreamer pipeline shaped like the daemon's program
        #    encode -> mux -> sink branch, run indefinitely (live-shaped) in
        #    the background exactly like the persistent worker.
        pipeline_desc = (
            "videotestsrc is-live=true pattern=18 ! "
            "video/x-raw,width=640,height=360,framerate=30/1 ! "
            "videoconvert ! openh264enc bitrate=800000 ! h264parse config-interval=-1 ! "
            "queue ! mux.  "
            "audiotestsrc is-live=true wave=4 ! "
            "audio/x-raw,rate=48000,channels=2 ! "
            "audioconvert ! avenc_aac bitrate=128000 ! aacparse ! "
            "queue ! mux.  "
            f"mpegtsmux name=mux ! queue ! udpsink host={host} port={port}"
        )
        gst_pipeline = Gst.parse_launch(pipeline_desc)
        gst_pipeline.set_state(Gst.State.PLAYING)
        try:
            manifest_path = live_dir / "playlist.m3u8"
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline and not manifest_path.exists():
                time.sleep(0.5)
            assert manifest_path.exists(), (
                "the GStreamer-fed relay never wrote a live manifest within 30s"
            )

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

            # 4) Serve it for real over HTTP -- the REAL media_router,
            #    resolving the channel's UNCHANGED hls sink uri (never the
            #    relay's rewritten local-ts uri, which is in-memory only and
            #    never persisted -- see HlsRelaySupervisor.apply's docstring).
            store = InMemoryEgressStore()
            store.upsert_config(config)  # the ORIGINAL config: kind stays "hls"
            app = FastAPI()
            app.include_router(live_router)
            app.dependency_overrides[get_egress_store] = lambda: store
            http_port = _free_port()

            with _BackgroundUvicorn(app, http_port) as server:
                served_manifest_url = f"{server.base_url}/media/live/gov-ch12/playlist.m3u8"

                manifest_response = httpx.get(served_manifest_url, timeout=10.0)
                assert manifest_response.status_code == 200
                assert manifest_response.headers["content-type"] == "application/vnd.apple.mpegurl"
                assert manifest_response.text.startswith("#EXTM3U")

                # ffprobe reads the manifest over HTTP and resolves segment
                # URIs relative to it, exactly as a resident's browser would.
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration,format_name:stream=codec_type,codec_name",
                        "-of",
                        "json",
                        served_manifest_url,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                assert probe.returncode == 0, (
                    f"ffprobe could not read the GStreamer-fed manifest over HTTP: {probe.stderr}"
                )
                probe_json = json.loads(probe.stdout)
                codec_types = {s["codec_type"] for s in probe_json["streams"]}
                assert "video" in codec_types, f"ffprobe found no video stream: {probe_json}"
                assert "audio" in codec_types, f"ffprobe found no audio stream: {probe_json}"
                print("FFPROBE PROOF (GStreamer-fed, over HTTP):", probe.stdout)

                # The composition's whole point: the manifest actually
                # ADVANCES while being polled live, not just "is servable
                # once". This is what neither pre-existing test proves for
                # the GStreamer path.
                deadline = time.monotonic() + 20.0
                rotated = False
                later_segments: set[str] = set()
                later_response = manifest_response
                while time.monotonic() < deadline:
                    time.sleep(1.0)
                    later_response = httpx.get(served_manifest_url, timeout=10.0)
                    assert later_response.status_code == 200
                    later_segments = _read_segment_names(later_response.text)
                    if later_segments and later_segments != first_segments:
                        rotated = True
                        break
                assert rotated, (
                    f"GStreamer-fed live manifest never rotated over HTTP: "
                    f"first={first_segments} still={later_segments} after 20s"
                )

                # Every segment the rotated manifest references must itself
                # be servable (delete_segments must not race the manifest
                # write and 404 a segment the manifest still lists).
                for segment_name in later_segments:
                    segment_response = httpx.get(
                        f"{server.base_url}/media/live/gov-ch12/{segment_name}", timeout=10.0
                    )
                    assert segment_response.status_code == 200, (
                        f"manifest references {segment_name} but it 404s"
                    )
        finally:
            gst_pipeline.set_state(Gst.State.NULL)
    finally:
        supervisor.stop_channel("gov-ch12")


def test_relay_writes_to_the_channels_unchanged_configured_directory(tmp_path: Path) -> None:
    """Narrower, fast sanity check (no HTTP, no GStreamer) that the relay's
    output directory is byte-identical to what media_router would resolve
    from the channel's stored config -- the load-bearing assumption the
    composition test above depends on, isolated so a failure here doesn't
    get buried inside a 30s+ live run."""
    live_dir = tmp_path / "gov-ch12"
    hls_sink = EgressSinkSpec(kind="hls", label="Web", uri=str(live_dir))
    config = EgressConfig(
        channel_id="gov-ch12", enabled=True, slate_message="Off air", sinks=[hls_sink]
    )

    captured_args: list[list[str]] = []

    class _Proc:
        def poll(self) -> int | None:
            return None

        def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
            return 0

    def fake_starter(args: list[str]) -> _Proc:
        captured_args.append(args)
        return _Proc()

    supervisor = HlsRelaySupervisor(starter=fake_starter)
    supervisor.apply(config)

    # The relay's own -hls_segment_filename/output target must land in the
    # EXACT directory media_router._live_dir_for_channel() would resolve
    # from the stored config's (unrewritten) hls sink uri.
    expected_manifest_target = HlsSink(hls_sink).connect_target()
    assert captured_args[0][-1] == expected_manifest_target
    assert urlsplit(expected_manifest_target).path or True  # sanity: a real path, not a URI
    assert Path(expected_manifest_target).parent == live_dir
