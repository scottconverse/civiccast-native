# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HlsSink must preserve A/53 CEA-608/708 captions in its emitted HLS.

The rolling live-HLS sink is a public playback surface. A known-positive
captioned MPEG-TS fed through the sink's own ``output_args()`` must still
carry decodable captions; a known-negative fixture must stay caption-free.

No caption *text* is asserted or persisted here; cue counts only.

Executable selection: these tests resolve an FFmpeg that ACTUALLY carries a
usable H.264 encoder rather than trusting bare PATH ``ffmpeg`` (a host's first
``ffmpeg`` may be a build without ``libopenh264``). Resolution order:
1. the packaged station FFmpeg under ``CIVICCAST_GSTREAMER_RUNTIME_ROOT``;
2. ``shutil.which("ffmpeg")``.
The chosen binary is probed with the product's own ``resolve_h264_encoder`` and
the resolved encoder name is asserted non-empty: a host with no usable H.264
encoder FAILS LOUDLY (no silent skip masking a broken proof).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from civiccast.egress.caption_proof import decode_embedded_captions
from civiccast.egress.models import EgressSinkSpec
from civiccast.egress.sinks import HlsSink, build_sink
from civiccast.stream._ffmpeg import resolve_h264_encoder

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None and os.environ.get("CIVICCAST_GSTREAMER_RUNTIME_ROOT") is None,
    reason="no ffmpeg on PATH and no packaged runtime root declared",
)


def _packaged_ffmpeg_dir() -> Path | None:
    """The packaged FFmpeg bin dir, per install_layout.InstallLayout.

    Always ``<install_root>/dependencies/ffmpeg/bin`` -- a sibling of the
    runtime dir -- regardless of which root shape the env var named.
    """
    candidates = []
    if _install_root is not None:
        candidates.append(_install_root / "dependencies" / "ffmpeg" / "bin")
    if _VERSION_ROOT is not None:
        candidates.append(_VERSION_ROOT.parent / "dependencies" / "ffmpeg" / "bin")
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file():
            return candidate
    return None


def _packaged_ffmpeg() -> Path | None:
    """The packaged station FFmpeg, when a runtime root is declared.

    Uses the shipped layout (install_layout.InstallLayout.ffmpeg_bin_dir):
    ``<install_root>/dependencies/ffmpeg/bin/ffmpeg.exe``. The declared
    ``CIVICCAST_GSTREAMER_RUNTIME_ROOT`` is the version root
    (``<install_root>/runtime``), so the FFmpeg tree is one level up.
    """
    directory = _packaged_ffmpeg_dir()
    if directory is None:
        return None
    candidate = directory / "ffmpeg.exe"
    return candidate if candidate.is_file() else None


def _selected_ffmpeg() -> str:
    """Resolve an FFmpeg that truly carries a usable H.264 encoder.

    Prefers the packaged station binary; falls back to PATH. Records the choice
    and proves a real encoder is present via the product's own resolver, so a
    missing/broken encoder is a hard failure, not a skip.
    """
    packaged = _packaged_ffmpeg()
    path = str(packaged) if packaged is not None else shutil.which("ffmpeg")
    assert path, "no FFmpeg executable available (packaged or PATH)"
    encoder = resolve_h264_encoder(ffmpeg_path=path)
    assert encoder, f"FFmpeg {path!r} advertises no usable H.264 encoder"
    print(f"[hls-sink-captions] ffmpeg={path} h264_encoder={encoder}")
    return path


_FIXTURES = Path(__file__).parent / "fixtures"
_POSITIVE = _FIXTURES / "cea708_test_caption.mpegts"
_NEGATIVE = _FIXTURES / "cea708_no_captions.mpegts"


def _hls_via_sink(input_ts: Path, out_dir: Path) -> Path:
    """Run ffmpeg with the sink's real output_args() and return the HLS dir."""
    sink = build_sink(EgressSinkSpec(kind="hls", label="Web", uri=str(out_dir)))
    assert isinstance(sink, HlsSink)
    result = subprocess.run(
        [
            _selected_ffmpeg(),
            "-hide_banner",
            "-nostats",
            "-v",
            "error",
            "-y",
            "-i",
            str(input_ts),
            *sink.output_args(),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return out_dir


def _manifest_segments(out_dir: Path) -> list[Path]:
    manifest = (out_dir / "playlist.m3u8").read_text(encoding="utf-8")
    return [
        out_dir / line.strip() for line in manifest.splitlines() if line.strip().endswith(".ts")
    ]


def _all_ts_bytes(out_dir: Path) -> Path:
    """Concatenate HLS segments into one probe input for caption decode."""
    concat = out_dir / "_all.ts"
    segments = _manifest_segments(out_dir)
    assert segments, f"no TS segments referenced by {out_dir / 'playlist.m3u8'}"
    with concat.open("wb") as handle:
        for segment in segments:
            handle.write(segment.read_bytes())
    return concat


def _probe_streams(ts: Path) -> set[tuple[str, str]]:
    probe = subprocess.run(
        [
            _selected_ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name",
            "-of",
            "json",
            str(ts),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {(s["codec_type"], s["codec_name"]) for s in json.loads(probe.stdout)["streams"]}


def test_known_positive_captions_survive_hls_sink(tmp_path: Path) -> None:
    """The sink must not strip embedded CEA captions from a positive input."""
    before = decode_embedded_captions(_POSITIVE, source_id="input-positive")
    assert len(before) >= 1, "fixture precondition: known-positive input has no cues"

    out_dir = _hls_via_sink(_POSITIVE, tmp_path / "hls-positive")
    after = decode_embedded_captions(_all_ts_bytes(out_dir), source_id="output-positive")

    assert len(after) >= 1, (
        "HlsSink output lost the input's embedded CEA captions; "
        f"input cues={len(before)} output cues={len(after)}"
    )


def test_known_negative_captions_stay_absent_through_hls_sink(tmp_path: Path) -> None:
    """Sensitivity control: a caption-free input must not gain captions."""
    before = decode_embedded_captions(_NEGATIVE, source_id="input-negative")
    assert before == [], "fixture precondition: known-negative input has cues"

    out_dir = _hls_via_sink(_NEGATIVE, tmp_path / "hls-negative")
    after = decode_embedded_captions(_all_ts_bytes(out_dir), source_id="output-negative")

    assert after == [], f"caption-free input gained {len(after)} cue(s) at the sink"


def _encode_source(path: Path, *, gop: int, seconds: int = 12) -> None:
    """Encode a testclip with a chosen IDR interval (frames between intra)."""
    ffmpeg = _selected_ffmpeg()
    encoder = resolve_h264_encoder(ffmpeg_path=ffmpeg)
    encode = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30",
            "-t",
            str(seconds),
            "-c:v",
            encoder,
            "-g",
            str(gop),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert encode.returncode == 0, encode.stderr


def test_hls_sink_segment_cadence_tracks_upstream_idr_interval(tmp_path: Path) -> None:
    """Copy-based HlsSink cadence mirrors the upstream IDR interval.

    The sink copies (so A/53 captions survive) and therefore cannot force
    keyframes; the ~2s HLS promise depends on the upstream encoder holding a
    <=2s IDR cadence. This proves BOTH directions:

    * a conforming 2s-GOP upstream -> ~2s segments (the contract); and
    * a 10s-GOP upstream -> long segments (the failure mode the paired
      gst/graph.py gop-size pin exists to prevent).

    Without the second case this test could not detect a regression that let
    the upstream GOP drift -- i.e. it would be insensitive.
    """
    conforming = tmp_path / "gop2s.ts"
    _encode_source(conforming, gop=60)
    conforming_segments = _manifest_segments(_hls_via_sink(conforming, tmp_path / "hls-ok"))
    assert len(conforming_segments) >= 4, (
        "a 2s-IDR upstream must yield >=4 ~2s HLS segments across 12s; "
        f"got {len(conforming_segments)}"
    )

    drifting = tmp_path / "gop10s.ts"
    _encode_source(drifting, gop=300)
    drifting_segments = _manifest_segments(_hls_via_sink(drifting, tmp_path / "hls-drift"))
    assert len(drifting_segments) < len(conforming_segments), (
        "sensitivity control failed: a 10s-GOP upstream produced the same "
        f"segment count ({len(drifting_segments)}) as a 2s-GOP upstream, so "
        "this test cannot detect a cadence regression"
    )


def test_hls_sink_output_keeps_av_and_playable(tmp_path: Path) -> None:
    """Guard the non-caption contract: H.264 video + AAC audio still present.

    The caption fixtures are video-only, so build a small A/V source: the sink
    must not silently drop the audio stream while changing the video path.
    """
    av_src = tmp_path / "av.ts"
    ffmpeg = _selected_ffmpeg()
    encoder = resolve_h264_encoder(ffmpeg_path=ffmpeg)
    encode = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "4",
            "-c:v",
            encoder,
            "-g",
            "60",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(av_src),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert encode.returncode == 0, encode.stderr

    out_dir = _hls_via_sink(av_src, tmp_path / "hls-av")
    kinds = _probe_streams(_all_ts_bytes(out_dir))
    assert ("video", "h264") in kinds, kinds
    assert ("audio", "aac") in kinds, kinds


# --- Integrated packaged-GStreamer proof -------------------------------------
#
# The fixture-based tests above prove the SINK preserves already-embedded
# captions. This one proves the FULL production path on this host: the packaged
# GStreamer openh264enc configured by ``encode_chain_specs`` (gop-size pinned
# to 2s) plus the CEA embed leg emits A/53 SEI, and the ACTUAL HlsSink copy
# path carries it into multiple ~2s, independently playable HLS segments.
#
# Gated on the packaged GStreamer runtime + its python GI bindings actually
# being present: that is a genuine capability boundary (the bundled _gi
# extension is CPython-3.12-specific). When the capability IS present the test
# FAILS on any defect -- it never skips a real failure.

# CIVICCAST_GSTREAMER_RUNTIME_ROOT may name EITHER the install root
# (``<install>``) OR the version root (``<install>/runtime``). Both are real
# shipped shapes: civiccast.native.gstreamer_runtime calls the version root its
# ``version_root`` argument, while install_layout.InstallLayout treats the
# install root as the parent of ``runtime``. We accept both and derive
# everything by the same relative arithmetic the product uses:
#   interpreter : <version_root>/python.exe   (== <install>/runtime/python.exe)
#   gstreamer   : <version_root>/dependencies/gstreamer/...
#   ffmpeg      : <install_root>/dependencies/ffmpeg/bin/ffmpeg.exe
# No synthetic root is invented; a shape not present on disk yields unavailable.
_DECLARED_ROOT = os.environ.get("CIVICCAST_GSTREAMER_RUNTIME_ROOT")


def _resolve_roots() -> tuple[Path | None, Path | None]:
    """Return (install_root, version_root) from the declared env, or Nones.

    Tries the declared path as a version root first (``<root>/python.exe`` and
    ``<root>/dependencies/gstreamer``), then as an install root
    (``<root>/runtime/python.exe`` and ``<root>/runtime/dependencies/gstreamer``).
    """
    if not _DECLARED_ROOT:
        return None, None
    declared = Path(_DECLARED_ROOT)
    if (declared / "python.exe").is_file() and (declared / "dependencies" / "gstreamer").is_dir():
        return declared.parent, declared
    runtime = declared / "runtime"
    if (runtime / "python.exe").is_file() and (runtime / "dependencies" / "gstreamer").is_dir():
        return declared, runtime
    return declared, None


_install_root, _VERSION_ROOT = _resolve_roots()
_GST_ROOT = _VERSION_ROOT / "dependencies" / "gstreamer" if _VERSION_ROOT else None
_GST_BIN = _GST_ROOT / "bin" if _GST_ROOT else None
_GST_PY = _GST_ROOT / "python" if _GST_ROOT else None
_GST_TYPELIB = _GST_ROOT / "lib" / "girepository-1.0" if _GST_ROOT else None
_GST_PLUGINS = _GST_ROOT / "lib" / "gstreamer-1.0" if _GST_ROOT else None
_GST_PYTHON = _VERSION_ROOT / "python.exe" if _VERSION_ROOT else None

_GST_AVAILABLE = bool(
    _GST_BIN
    and _GST_BIN.is_dir()
    and _GST_PY
    and _GST_PY.is_dir()
    and _GST_PYTHON
    and _GST_PYTHON.is_file()
)


_GST_EMITTER = '''# emitted by the packaged CPython 3.12 interpreter
import os, sys, time
# VERSION_ROOT is the directory holding python.exe + dependencies/gstreamer
# (i.e. <install_root>/runtime); the parent resolves and passes it explicitly.
VERSION_ROOT = os.environ["CIVICCAST_GST_VERSION_ROOT"]
GSTBIN = os.path.join(VERSION_ROOT, "dependencies", "gstreamer", "bin")
os.environ["GI_TYPELIB_PATH"] = os.path.join(VERSION_ROOT, "dependencies", "gstreamer", "lib", "girepository-1.0")
os.environ["GST_PLUGIN_PATH"] = os.path.join(VERSION_ROOT, "dependencies", "gstreamer", "lib", "gstreamer-1.0")
os.environ["PYGI_DLL_DIRS"] = GSTBIN
os.environ["PATH"] = GSTBIN + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, os.path.join(VERSION_ROOT, "dependencies", "gstreamer", "python"))
sys.path.insert(0, os.environ["CIVICCAST_REPO_ROOT"])
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
Gst.init(None)
from civiccast.egress.gst.graph import encode_chain_specs

out_path, embed = sys.argv[1], sys.argv[2] == "1"
gop_size = next(s.props["gop-size"] for s in encode_chain_specs(fps=30, gop=60) if s.factory == "openh264enc")

pipe = Gst.Pipeline.new("gst-e2e")
src = Gst.ElementFactory.make("videotestsrc"); src.set_property("num-buffers", 150); src.set_property("is-live", False)
cap = Gst.ElementFactory.make("capsfilter"); cap.set_property("caps", Gst.Caps.from_string("video/x-raw,format=I420,width=320,height=180,framerate=30/1"))
enc = Gst.ElementFactory.make("openh264enc"); enc.set_property("bitrate", 800000); enc.set_property("gop-size", gop_size)
parse = Gst.ElementFactory.make("h264parse")
mux = Gst.ElementFactory.make("mpegtsmux")
sink = Gst.ElementFactory.make("filesink"); sink.set_property("location", out_path)
chain = [src, cap, enc, parse]; links = [(src, cap), (cap, enc), (enc, parse)]
appsrc = cf = comb = None
if embed:
    comb = Gst.ElementFactory.make("cccombiner")
    ins = Gst.ElementFactory.make("h264ccinserter"); ins.set_property("remove-caption-meta", True)
    parse2 = Gst.ElementFactory.make("h264parse")
    appsrc = Gst.ElementFactory.make("appsrc"); appsrc.set_property("is-live", False); appsrc.set_property("format", Gst.Format.TIME); appsrc.set_property("do-timestamp", False); appsrc.set_property("caps", Gst.Caps.from_string("text/x-raw,format=(string)utf8"))
    tt = Gst.ElementFactory.make("tttocea608"); tt.set_property("mode", "pop-on")
    cc = Gst.ElementFactory.make("ccconverter")
    cf = Gst.ElementFactory.make("capsfilter"); cf.set_property("caps", Gst.Caps.from_string("closedcaption/x-cea-708,format=(string)cc_data,framerate=(fraction)30/1"))
    chain += [comb, ins, parse2, mux, sink, appsrc, tt, cc, cf]
    links += [(parse, comb), (comb, ins), (ins, parse2), (parse2, mux), (mux, sink), (appsrc, tt), (tt, cc), (cc, cf)]
else:
    chain += [mux, sink]; links += [(parse, mux), (mux, sink)]
for e in chain: pipe.add(e)
for a, b in links: assert a.link(b), (a.get_name(), b.get_name())
if embed:
    cp = comb.request_pad_simple("caption"); assert cp is not None
    assert cf.get_static_pad("src").link(cp) == Gst.PadLinkReturn.OK
pipe.set_state(Gst.State.PLAYING)
if embed:
    text = os.environ.get("CIVICCAST_INTEGRATION_CUE", "CIVICCAST INTEGRATION CUE")
    buf = Gst.Buffer.new_allocate(None, len(text), None); buf.fill(0, text.encode())
    buf.pts = 0; buf.duration = 3 * Gst.SECOND
    appsrc.emit("push-buffer", buf)
bus = pipe.get_bus(); deadline = time.time() + 30
while time.time() < deadline:
    msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
    if msg:
        if msg.type == Gst.MessageType.ERROR:
            print("GST_ERROR", msg.parse_error(), file=sys.stderr); sys.exit(3)
        break
    time.sleep(0.05)
pipe.set_state(Gst.State.NULL)
assert os.path.getsize(out_path) > 0
print("GST_EMIT_OK", os.path.getsize(out_path))
'''


def _gstreamer_python() -> Path:
    """The packaged CPython that owns the bundled GI extension (3.12 ABI).

    It lives at ``<version_root>/python.exe`` -- the same directory
    ``CIVICCAST_GSTREAMER_RUNTIME_ROOT`` names.
    """
    assert _GST_PYTHON and _GST_PYTHON.is_file(), (
        f"packaged interpreter not found at {_GST_PYTHON}; "
        "CIVICCAST_GSTREAMER_RUNTIME_ROOT must name the install root or its runtime dir"
    )
    return _GST_PYTHON


def _emit_captioned_gstreamer_ts(out_path: Path, *, embed_caption: bool) -> None:
    """Emit a real MPEG-TS through the packaged GStreamer openh264 encoder.

    The bundled GI bindings are CPython-3.12-only, so this runs the emit step
    in the packaged 3.12 interpreter as a subprocess, passing this repo root
    (and, for the positive case, the cue text) through the environment. The
    gop-size comes from the product's own ``encode_chain_specs`` so the emitted
    cadence is the real contracted 2s value.
    """
    assert _GST_AVAILABLE, "packaged GStreamer runtime unavailable"
    runner = out_path.parent / "gst_emitter.py"
    runner.write_text(_GST_EMITTER, encoding="utf-8")
    assert _VERSION_ROOT is not None, "packaged GStreamer version root unresolved"
    env = dict(os.environ)
    env["CIVICCAST_REPO_ROOT"] = str(Path(__file__).resolve().parents[2])
    env["CIVICCAST_INTEGRATION_CUE"] = _INTEGRATION_CUE
    env["CIVICCAST_GST_VERSION_ROOT"] = str(_VERSION_ROOT)
    # A PYTHONPATH inherited from the parent (e.g. a dev checkout) would shadow
    # the packaged `gi`; drop it so the child imports the bundled bindings.
    env.pop("PYTHONPATH", None)
    emit = subprocess.run(
        [str(_gstreamer_python()), str(runner), str(out_path), "1" if embed_caption else "0"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert emit.returncode == 0, f"GStreamer emit failed:\n{emit.stdout}\n{emit.stderr}"
    assert "GST_EMIT_OK" in emit.stdout, f"GStreamer emit produced no marker:\n{emit.stdout}\n{emit.stderr}"


_INTEGRATION_CUE = "CIVICCAST INTEGRATION CUE"


def _hls_segment_caption_count(out_dir: Path) -> int:
    segments = _manifest_segments(out_dir)
    assert segments, f"no HLS segments referenced by {out_dir / 'playlist.m3u8'}"
    concat = out_dir / "_integrated_all.ts"
    concat.write_bytes(b"".join(segment.read_bytes() for segment in segments))
    return len(decode_embedded_captions(concat, source_id="gst-integrated"))


@pytest.mark.skipif(
    not _GST_AVAILABLE,
    reason=(
        "packaged GStreamer runtime + bundled GI python not declared "
        "(set CIVICCAST_GSTREAMER_RUNTIME_ROOT and bootstrap the 3.12 GI path)"
    ),
)
def _selected_ffprobe() -> str:
    """The ffprobe matching the selected ffmpeg (packaged or PATH)."""
    ffmpeg = Path(_selected_ffmpeg())
    name = "ffprobe.exe" if ffmpeg.name.lower().endswith(".exe") else "ffprobe"
    return str(ffmpeg.with_name(name))


def _segment_duration_seconds(segment: Path) -> float:
    """Container duration of one HLS segment, via the selected ffprobe."""
    ffprobe = _selected_ffprobe()
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(segment)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    return float(out.stdout.strip())


def _segment_frame_info(segment: Path) -> list[tuple[bool, float]]:
    """(is_keyframe, pts_seconds) for each video frame in a segment."""
    ffprobe = _selected_ffprobe()
    out = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=key_frame,best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(segment),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0, out.stderr
    frames: list[tuple[bool, float]] = []
    for line in out.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2 or not parts[1]:
            continue
        frames.append((parts[0] == "1", float(parts[1])))
    return frames


def _assert_independently_decodable(segment: Path) -> None:
    """Full decode of the segment alone must succeed with no errors.

    An independently-decodable HLS segment is the actual playback contract;
    keyframe-at-start alone is a weaker proxy. Run the selected ffmpeg over
    just this segment so a missing SPS/PPS or dropped IDR fails loudly.
    """
    result = subprocess.run(
        [_selected_ffmpeg(), "-hide_banner", "-v", "error", "-i", str(segment), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"{segment.name} did not decode standalone: {result.stderr}"
    assert result.stderr.strip() == "", f"{segment.name} decoded with errors: {result.stderr}"


def test_packaged_gstreamer_to_hls_sink_preserves_captions_and_cadence(tmp_path: Path) -> None:
    """Real packaged GStreamer -> real HlsSink copy -> captioned, playable HLS.

    Positive: the CEA embed leg's A/53 SEI survives the sink into decodable
    captions. Negative control: the SAME pipeline without the embed leg yields
    none, proving the positive result is not a sink/decoder artifact.

    Cadence/playability asserted per segment (not just ">=2 files"):
      * first segment ~2s (HlsSink.segment_seconds, tolerance-bounded);
      * EACH segment begins on a keyframe (IDR at start);
      * EACH segment fully decodes standalone with no errors;
      * video PTS are strictly increasing across the segment sequence.

    Rolling-window (delete_segments rotation over time) is NOT asserted here --
    this source is finite/short. That contract is covered by
    tests/egress/test_hls_sink_live_playability.py
    (``test_hls_sink_produces_rolling_playable_live_manifest``), which asserts
    ``rotated`` (later segment set != first) and per-duration <= 1.5x target.
    """
    positive_src = tmp_path / "captioned.ts"
    _emit_captioned_gstreamer_ts(positive_src, embed_caption=True)
    positive_dir = _hls_via_sink(positive_src, tmp_path / "hls-positive-gst")
    assert _hls_segment_caption_count(positive_dir) >= 1, (
        "packaged GStreamer A/53 captions did not survive the HlsSink copy path"
    )

    negative_src = tmp_path / "uncaptioned.ts"
    _emit_captioned_gstreamer_ts(negative_src, embed_caption=False)
    negative_dir = _hls_via_sink(negative_src, tmp_path / "hls-negative-gst")
    assert _hls_segment_caption_count(negative_dir) == 0, (
        "caption-free GStreamer source gained captions through the sink"
    )

    # The emitted openh264 GOP is 60 frames @30fps = 2s (the value our
    # encode_chain_specs pins), so a ~3s captioned source must segment into
    # more than one piece, the first of which is ~2s.
    segments = _manifest_segments(positive_dir)
    assert len(segments) >= 2, (
        f"expected >=2 HLS segments from the 2s-GOP GStreamer source; got {len(segments)}"
    )

    tolerance = 0.5 * HlsSink.segment_seconds
    first_duration = _segment_duration_seconds(segments[0])
    assert abs(first_duration - HlsSink.segment_seconds) <= tolerance, (
        f"first HLS segment is {first_duration:.3f}s, not ~{HlsSink.segment_seconds}s "
        f"(+/-{tolerance}s) -- the upstream 2s IDR cadence did not drive the cut"
    )

    last_pts = None
    for segment in segments:
        assert segment.stat().st_size > 0, f"{segment.name} is empty"
        frames = _segment_frame_info(segment)
        assert frames, f"{segment.name} has no video frames"
        is_keyframe, first_pts = frames[0]
        assert is_keyframe, f"{segment.name} does not start on a keyframe (IDR)"
        _assert_independently_decodable(segment)
        if last_pts is not None:
            assert first_pts > last_pts, (
                f"{segment.name} PTS {first_pts:.3f} does not advance past the "
                f"previous segment's {last_pts:.3f}"
            )
        last_pts = frames[-1][1]


