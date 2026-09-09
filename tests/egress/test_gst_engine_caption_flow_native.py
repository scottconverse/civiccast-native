# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-runtime caption scheduling regression, separate from reload retirement."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.egress import test_gst_engine_wsl as native

pytestmark = pytest.mark.skipif(
    not (native._wsl_gi_available() and native._cc_embed_elements_available()),
    reason="caption flow proof requires the real bundled GStreamer caption runtime",
)


def test_live_caption_queue_probe_releases_real_event_reservations(tmp_path: Path) -> None:
    """Prove the real queue-source probe, not merely the GI-free gate in isolation."""
    from civiccast.egress.gst.engine import GstPlayoutEngine

    graph = native._filesink_graph(
        replace(native._av_demo_graph(), captions=native.graphmod.caption_embed_leg_live()),
        tmp_path / "caption-flow.ts",
    )
    engine = GstPlayoutEngine(graph)
    gate = engine._caption_gap_gate
    reserve = Mock(wraps=gate.reserve)
    forwarded = Mock(wraps=gate.entered_downstream)
    gate.reserve = reserve
    gate.entered_downstream = forwarded
    try:
        queue = engine.pipeline.get_by_name("caption_flow_queue")
        assert queue is not None
        assert queue.get_property("max-size-buffers") == 200
        assert queue.get_property("max-size-bytes") == 10_485_760
        assert queue.get_property("max-size-time") == 1_000_000_000
        assert int(queue.get_property("leaky")) == 0
        result = engine.run(swaps=0, interval_s=1)
        assert result["error"] is None, result
        assert result["teardown_clean"] is True, result
        reserved = {call.args[0] for call in reserve.call_args_list}
        observed = {call.args[0] for call in forwarded.call_args_list}
        assert len(observed) >= 2, "prime and heartbeat never traversed the real queue probe"
        assert observed <= reserved, "a forwarded GAP lacked its prior admission reservation"
        assert gate.pending is None
        assert gate.reserve(12345) is False, "stop must leave GAP admissions closed"
        assert engine._caption_gap_probe is None
        assert engine._caption_gap_heartbeat_id is None
    finally:
        engine.stop()


def test_three_captioned_workers_finish_complex_playlist_without_reload(tmp_path: Path) -> None:
    """Keep caption embed and rolling audio capture on during noisy video.

    The exact beta.5 baseline intermittently stopped delivering caption GAPs
    and stalled output without any reload command. Repeat three concurrent
    channels three times: ordinary bars alternate with high-complexity snow.
    No debug logging, artificial sleeps in the media path, or disabled captions
    may substitute for successful complete playback.
    """
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe is required to verify complete A/V capture")
    clips = [tmp_path / f"segment-{index}.ts" for index in range(4)]
    for index, clip in enumerate(clips):
        native._write_short_av_ts_clip(
            clip, seconds=2.5, pattern=(0, 1)[index % 2], video_caps=native._PRODUCTION_CAPS
        )

    for attempt in range(3):
        workers = []
        try:
            for index in range(3):
                channel = tmp_path / f"attempt-{attempt + 1}-channel-{index + 1}"
                channel.mkdir()
                capture = channel / "output.ts"
                tap = channel / "caption-tap"
                graph = native._production_pressure_playlist_graph(
                    clips, out_ts=capture, audio_tap_dir=tap
                )
                process, control, log = native._launch_worker(channel, graph, capture)
                workers.append((process, control, log, capture, tap))
            for process, _control, log, capture, tap in workers:
                code = process.wait(timeout=40)
                output = log.read_text(encoding="utf-8", errors="replace")
                assert code == 0, output
                assert "CTRL stall:" not in output, output
                assert "'teardown_clean': True" in output, output
                native._assert_continuous(capture, output, require_audio_pid=True)
                probe = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "packet=codec_type,pts_time,duration_time",
                        "-show_packets",
                        "-of",
                        "json",
                        str(capture),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                # TS stream metadata may legitimately omit audio duration. Measure
                # the actual timestamped packet span of EACH elementary stream.
                packets = json.loads(probe.stdout)["packets"]
                for kind in ("video", "audio"):
                    selected = [packet for packet in packets if packet["codec_type"] == kind]
                    assert selected, f"no {kind} packets"
                    starts = [float(packet["pts_time"]) for packet in selected]
                    ends = [
                        float(packet["pts_time"]) + float(packet["duration_time"])
                        for packet in selected
                    ]
                    span = max(ends) - min(starts)
                    assert span >= 9.5, f"{kind} truncated to {span:.3f}s"
                assert list(tap.glob("chunk-*.wav")), output
                assert not list(tap.glob("*.partial")), output
        finally:
            for process, *_rest in workers:
                native._reap(process)
