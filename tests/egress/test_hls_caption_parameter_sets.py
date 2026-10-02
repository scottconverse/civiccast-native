# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-runtime regression: caption embed must not strip H.264 parameter sets.

The native HLS relay reads the GStreamer engine's MPEG-TS output with ffmpeg.
If the caption inserter path drops SPS/PPS, ffmpeg reports "non-existing PPS 0
referenced" and the video PID is not decodable, which surfaces publicly as an
audio-only HLS window.

Run with the installed runtime:
  & 'C:\\Program Files\\CivicCast (Native)\\runtime\\python.exe' <this file>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

INSTALL = Path(r"C:\Program Files\CivicCast (Native)")
GST_ROOT = INSTALL / "runtime"
GST_BIN = GST_ROOT / "dependencies" / "gstreamer" / "bin"
REPO = Path(__file__).resolve().parents[2]
FFPROBE = INSTALL / "dependencies" / "ffmpeg" / "bin" / "ffprobe.exe"
SOURCE = REPO / "work" / "beta10-public-hls-no-video" / "source.ts"


def _video_streams(output: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(result.stdout or "{}")
    return bool(payload.get("streams")), result.stderr


def main() -> int:
    os.environ["CIVICCAST_GSTREAMER_RUNTIME_ROOT"] = str(GST_ROOT)
    os.environ["PYGI_DLL_DIRS"] = str(GST_BIN)
    os.environ["PATH"] = str(GST_BIN) + os.pathsep + os.environ.get("PATH", "")
    os.environ["GST_PLUGIN_PATH"] = str(GST_ROOT / "dependencies" / "gstreamer" / "lib" / "gstreamer-1.0")
    os.environ["GI_TYPELIB_PATH"] = str(GST_ROOT / "dependencies" / "gstreamer" / "lib" / "girepository-1.0")
    sys.path.insert(0, str(REPO))
    if not SOURCE.exists():
        raise SystemExit(f"source fixture missing: {SOURCE}")
    from civiccast.egress.gst.graph import (
        ElementSpec,
        PlayoutGraph,
        PlaylistLeg,
        SourceLeg,
        audio_encode_specs,
        caption_embed_leg_live,
        encode_chain_specs,
    )
    from civiccast.egress.gst.engine import GstPlayoutEngine

    work = Path(tempfile.mkdtemp(prefix="civiccast-caption-parameter-sets-"))
    output = work / "caption-parameter-sets.ts"
    program = PlaylistLeg(
        label="program",
        subchains=(
            (
                ElementSpec("filesrc", props={"location": SOURCE.resolve().as_posix()}),
                ElementSpec("decodebin"),
                ElementSpec("videoconvert"),
                ElementSpec("videoscale"),
                ElementSpec("videorate"),
                ElementSpec("capsfilter", props={"caps": "video/x-raw,width=1280,height=720,framerate=30/1"}),
            ),
        ),
        audio_tail=(
            ElementSpec("audioconvert"),
            ElementSpec("audioresample"),
            ElementSpec("capsfilter", props={"caps": "audio/x-raw,rate=48000,channels=2"}),
        ),
    )
    graph = PlayoutGraph(
        sources=(program,),
        encoder=encode_chain_specs(width=1280, height=720, fps=30, bitrate_kbps=6000, gop=60),
        mux=ElementSpec("mpegtsmux", name="mux"),
        sinks=((ElementSpec("queue"), ElementSpec("filesink", props={"location": str(output)})),),
        audio_encoder=audio_encode_specs(bitrate_kbps=192, sample_rate=48000),
        captions=caption_embed_leg_live(),
    )
    engine = GstPlayoutEngine(graph)
    try:
        result = engine.run(swaps=0, interval_s=1)
    finally:
        engine.stop()
    if result.get("error") is not None:
        raise SystemExit(f"engine failed: {result}")
    present, stderr = _video_streams(output)
    if not present:
        raise SystemExit(f"RED: caption embed produced no decodable H.264 video PID; stderr={stderr!r}")
    print(f"GREEN: caption embed emitted decodable H.264 at {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
