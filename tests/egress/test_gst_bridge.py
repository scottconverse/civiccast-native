# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the egress-config → element-graph bridge (Windows; no gi)."""

from __future__ import annotations

import pytest

from civiccast.egress.errors import SecretUnresolvedError
from civiccast.egress.gst.bridge import (
    encode_chain_from_profile,
    graph_from_config,
    gst_encoder_name,
    sink_branches_from_config,
    sink_element_spec,
    source_first_element,
)
from civiccast.egress.gst.bridge import sink_element_spec as _sink_element_spec
from civiccast.egress.gst.graph import PlaylistLeg, SourceLeg
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    redact_source_uri,
)


def test_gst_encoder_name_maps_ffmpeg_to_gstreamer() -> None:
    assert gst_encoder_name("libx264") == "openh264enc"
    assert gst_encoder_name("h264") == "openh264enc"
    assert gst_encoder_name("openh264") == "openh264enc"
    assert gst_encoder_name("x264") == "x264enc"
    assert gst_encoder_name("h264_nvenc") == "nvh264enc"
    # is_windows=False pins the platform-independent base table (on Windows the
    # positional default remaps vaapi->mediafoundation; see test_gst_bridge_win_remap).
    assert gst_encoder_name("hevc_vaapi", is_windows=False) == "vah265enc"
    assert gst_encoder_name("LIBX264") == "openh264enc"  # case-insensitive
    assert gst_encoder_name("totally-unknown") == "openh264enc"  # safe default


def test_encode_chain_from_profile_libx264_uses_bundled_openh264() -> None:
    profile = CanonicalProfile(
        width=1920, height=1080, fps=30, video_codec="libx264", video_bitrate_kbps=8000, gop_size=60
    )
    specs = encode_chain_from_profile(profile)
    factories = [s.factory for s in specs]
    assert "openh264enc" in factories
    assert factories[-1] == "h264parse"
    encoder = next(s for s in specs if s.factory == "openh264enc")
    # openh264enc bitrate is bits/sec; the profile's 8000 kbit/s converts to 8_000_000.
    assert encoder.props["bitrate"] == 8_000_000
    capsfilter = next(s for s in specs if s.factory == "capsfilter")
    assert capsfilter.props["caps"] == "video/x-raw,width=1920,height=1080,framerate=30/1"


def test_sink_element_spec_udp_multicast() -> None:
    spec = sink_element_spec(EgressSinkSpec(kind="udp-ts", label="h", uri="udp://239.0.0.1:5000"))
    assert spec.factory == "udpsink"
    assert spec.props["host"] == "239.0.0.1"
    assert spec.props["port"] == 5000
    assert spec.props["auto-multicast"] is True


def test_sink_element_spec_file_and_srt() -> None:
    file_spec = sink_element_spec(EgressSinkSpec(kind="file", label="c", uri="file:///tmp/x.ts"))
    assert file_spec.factory == "filesink"
    assert file_spec.props["location"] == "/tmp/x.ts"
    srt_spec = sink_element_spec(EgressSinkSpec(kind="srt", label="s", uri="srt://h:7001"))
    assert srt_spec.factory == "srtsink"
    assert srt_spec.props["uri"] == "srt://h:7001"


def test_sink_element_spec_rejects_rtmp() -> None:
    with pytest.raises(ValueError, match="rtmp"):
        sink_element_spec(EgressSinkSpec(kind="rtmp", label="r", uri="rtmp://h/app"))


def test_sink_branches_from_config_builds_queue_plus_sink_and_skips_sdi() -> None:
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="Please stand by",
        sinks=[
            EgressSinkSpec(kind="udp-ts", label="headend", uri="udp://10.0.0.9:5000"),
            EgressSinkSpec(kind="file", label="capture", uri="file:///tmp/ch1.ts"),
            EgressSinkSpec(kind="sdi", label="sdi-out", uri="decklink://0"),
        ],
    )
    branches = sink_branches_from_config(config)
    assert len(branches) == 2  # sdi skipped
    assert all(branch[0].factory == "queue" for branch in branches)
    assert branches[0][1].factory == "udpsink"
    assert branches[1][1].factory == "filesink"


def test_graph_from_config_builds_program_playlist_and_slate() -> None:
    config = EgressConfig(
        channel_id="ch1",
        enabled=True,
        slate_message="Please stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="ch1",
        segments=[
            EgressSourceSegment(label="clip1", path="/m/clip1.ts", duration_seconds=10),
            EgressSourceSegment(label="clip2", path="/m/clip2.ts", duration_seconds=10),
        ],
    )
    graph = graph_from_config(config, plan)
    program, slate = graph.sources
    assert isinstance(program, PlaylistLeg) and program.label == "program"
    assert len(program.subchains) == 2
    assert program.subchains[0][0].factory == "filesrc"
    assert program.subchains[0][0].props["location"] == "/m/clip1.ts"
    assert any(spec.factory == "decodebin" for spec in program.subchains[0])
    assert isinstance(slate, SourceLeg) and slate.label == "slate"
    # solid base slate (no pango); the slate message is rendered via the S6 CG image path (D-S1-7)
    assert slate.elements[0].factory == "videotestsrc"
    assert graph.mux.factory == "mpegtsmux"
    assert graph.sinks[0][1].factory == "udpsink"


def test_graph_from_config_udp_sink_enables_cbr() -> None:
    config = EgressConfig(
        channel_id="c",
        enabled=True,
        slate_message="x",
        canonical_profile=CanonicalProfile(video_codec="x264"),
        sinks=[EgressSinkSpec(kind="udp-ts", label="h", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="c",
        segments=[EgressSourceSegment(label="s", path="/m/a.ts", duration_seconds=10)],
    )
    graph = graph_from_config(config, plan)
    encoder = next(s for s in graph.encoder if s.factory == "x264enc")
    assert "nal-hrd=cbr" in encoder.props.get("option-string", "")


def test_graph_from_config_file_only_sink_no_cbr() -> None:
    config = EgressConfig(
        channel_id="c",
        enabled=True,
        slate_message="x",
        canonical_profile=CanonicalProfile(video_codec="x264"),
        sinks=[EgressSinkSpec(kind="file", label="f", uri="file:///tmp/o.ts")],
    )
    plan = EgressSourcePlan(
        channel_id="c",
        segments=[EgressSourceSegment(label="s", path="/m/a.ts", duration_seconds=10)],
    )
    graph = graph_from_config(config, plan)
    encoder = next(s for s in graph.encoder if s.factory == "x264enc")
    assert "option-string" not in encoder.props


def test_source_first_element_file_is_filesrc() -> None:
    seg = EgressSourceSegment(label="clip", path="/m/clip.ts", duration_seconds=10)
    spec = source_first_element(seg)
    assert spec.factory == "filesrc"
    assert spec.props["location"] == "/m/clip.ts"


@pytest.mark.parametrize(
    "uri,factory,prop",
    [
        ("srt://headend.example:7001", "srtsrc", "uri"),
        ("udp://239.0.0.5:5000", "udpsrc", "uri"),
        ("rtmp://ingest.example/app/key", "rtmpsrc", "location"),
        ("rtsp://camera.local:554/stream", "rtspsrc", "location"),
        ("https://cdn.example/live.m3u8", "souphttpsrc", "location"),
    ],
)
def test_source_first_element_live_maps_by_scheme(uri, factory, prop) -> None:
    seg = EgressSourceSegment(label="live", path=uri, duration_seconds=1, kind="live")
    spec = source_first_element(seg)
    assert spec.factory == factory
    assert spec.props[prop] == uri


@pytest.mark.parametrize(
    "uri,expected",
    [
        # local paths / file URIs pass through untouched (no network authority)
        ("/m/clip.ts", "/m/clip.ts"),
        ("C:\\media\\clip.ts", "C:\\media\\clip.ts"),
        ("file:///tmp/x.ts", "file:///tmp/x.ts"),
        # userinfo (rtsp credentials) is stripped
        ("rtsp://user:pass@cam.local:554/stream", "rtsp://cam.local:554/stream"),
        # secret query params are redacted, non-secret ones kept
        (
            "srt://h:7001?passphrase=hunter2&latency=120",
            "srt://h:7001?passphrase=%3Credacted%3E&latency=120",
        ),
        ("rtmp://ingest/app?streamkey=abc123", "rtmp://ingest/app?streamkey=%3Credacted%3E"),
        # a clean network URI is unchanged (modulo identity round-trip)
        ("udp://239.0.0.5:5000", "udp://239.0.0.5:5000"),
    ],
)
def test_redact_source_uri(uri, expected) -> None:
    assert redact_source_uri(uri) == expected


def test_srt_sink_resolves_secret_ref_into_passphrase() -> None:
    spec = EgressSinkSpec(kind="srt", label="head", uri="srt://h:7001", secret_ref="SRT_PASS")
    elem = _sink_element_spec(
        spec, resolve_secret=lambda ref: "topsecret" if ref == "SRT_PASS" else None
    )
    assert elem.factory == "srtsink"
    assert "passphrase=topsecret" in elem.props["uri"]


def test_srt_sink_unresolved_secret_raises() -> None:
    spec = EgressSinkSpec(kind="srt", label="head", uri="srt://h:7001", secret_ref="SRT_PASS")
    with pytest.raises(SecretUnresolvedError, match="not resolved"):
        _sink_element_spec(spec, resolve_secret=lambda _ref: None)


def test_srt_sink_without_secret_ref_needs_no_resolver() -> None:
    spec = EgressSinkSpec(kind="srt", label="head", uri="srt://h:7001")
    assert _sink_element_spec(spec).props["uri"] == "srt://h:7001"


def test_source_first_element_rejects_unknown_live_scheme() -> None:
    seg = EgressSourceSegment(label="live", path="ftp://x/y", duration_seconds=1, kind="live")
    with pytest.raises(ValueError, match="unsupported live source scheme"):
        source_first_element(seg)


def test_graph_from_config_plays_a_live_program_plan() -> None:
    """A live source plan (the operator's live cut, applied via start or a content-
    reload takeover) builds a program leg whose source is the live ingest element."""
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="stand by",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label="Live: chamber",
                path="srt://truck.example:7001",
                duration_seconds=1,
                kind="live",
            )
        ],
    )
    graph = graph_from_config(config, plan)
    program = graph.sources[0]
    assert isinstance(program, PlaylistLeg)
    assert program.subchains[0][0].factory == "srtsrc"
    assert program.subchains[0][0].props["uri"] == "srt://truck.example:7001"
    assert any(spec.factory == "decodebin" for spec in program.subchains[0])


def _caption_config_plan() -> tuple[EgressConfig, EgressSourcePlan]:
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="x",
        sinks=[EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    )
    plan = EgressSourcePlan(
        channel_id="gov",
        segments=[EgressSourceSegment(label="s", path="/m/a.ts", duration_seconds=10)],
    )
    return config, plan


def test_graph_from_config_no_caption_embed_by_default() -> None:
    # Default: no caption leg (byte-identical to the pre-S11a graph), encoder unchanged.
    config, plan = _caption_config_plan()
    graph = graph_from_config(config, plan)
    assert graph.captions is None
    assert graph.encoder[-1].factory == "h264parse"


def test_graph_from_config_live_caption_embed() -> None:
    from civiccast.egress.gst.bridge import CaptionEmbedRequest

    config, plan = _caption_config_plan()
    graph = graph_from_config(config, plan, caption_embed=CaptionEmbedRequest(mode="live"))
    assert graph.captions is not None
    assert graph.captions.combiner.factory == "cccombiner"
    assert graph.captions.caption_source[0].factory == "appsrc"
    assert [s.factory for s in graph.captions.inserter_chain] == ["h264ccinserter", "h264parse"]
    # the encoder chain itself is unchanged — the caption leg is inserted at engine
    # build time, between the encoder tail (h264parse) and the mux.
    assert graph.encoder[-1].factory == "h264parse"


def test_graph_from_config_sidecar_caption_embed() -> None:
    from civiccast.egress.gst.bridge import CaptionEmbedRequest

    config, plan = _caption_config_plan()
    graph = graph_from_config(
        config, plan, caption_embed=CaptionEmbedRequest(mode="sidecar", sidecar_path="/m/c.vtt")
    )
    assert graph.captions is not None
    assert graph.captions.caption_source[0].factory == "filesrc"
    assert graph.captions.caption_source[0].props["location"] == "/m/c.vtt"


def test_sidecar_caption_embed_requires_path() -> None:
    from civiccast.egress.gst.bridge import CaptionEmbedRequest, caption_embed_leg

    with pytest.raises(ValueError, match="sidecar_path"):
        caption_embed_leg(CaptionEmbedRequest(mode="sidecar"))


def _audio_track(
    track_id: str, *, kind: str = "sap", source_uri: str | None = "file:///m/es.aac", **kw
):
    from civiccast.egress.audio_tracks import AudioProgramTrack

    base: dict = {
        "track_id": track_id,
        "scope": "channel",
        "target_id": "gov",
        "kind": kind,
        "language": "es",
        "label": "Spanish SAP",
        "source_uri": source_uri,
    }
    base.update(kw)
    return AudioProgramTrack(**base)


def test_graph_from_config_no_secondary_audio_by_default() -> None:
    config, plan = _caption_config_plan()
    graph = graph_from_config(config, plan)
    assert graph.secondary_audio == ()


def test_graph_from_config_builds_secondary_audio_pids() -> None:
    config, plan = _caption_config_plan()
    tracks = [
        _audio_track("t_primary", kind="primary", source_uri=None),  # program audio — skipped
        _audio_track("t_sap", kind="sap", language="es"),
        _audio_track("t_desc", kind="descriptive", language="en", source_uri="file:///m/desc.aac"),
    ]
    graph = graph_from_config(config, plan, audio_tracks=tracks)
    assert len(graph.secondary_audio) == 2  # primary skipped
    kinds = {leg.kind for leg in graph.secondary_audio}
    assert kinds == {"sap", "descriptive"}
    sap = next(leg for leg in graph.secondary_audio if leg.kind == "sap")
    assert sap.language == "es"
    assert sap.source[0].factory == "filesrc"
    assert sap.encoder[-1].factory == "aacparse"


def test_graph_from_config_skips_secondary_track_without_source() -> None:
    config, plan = _caption_config_plan()
    graph = graph_from_config(
        config, plan, audio_tracks=[_audio_track("t", kind="sap", source_uri=None)]
    )
    assert graph.secondary_audio == ()


def test_secondary_audio_leg_from_track_live_uri() -> None:
    from civiccast.egress.gst.bridge import secondary_audio_leg_from_track
    from civiccast.egress.models import CanonicalProfile

    profile = CanonicalProfile(
        width=1280, height=720, fps=30, video_codec="libx264", video_bitrate_kbps=4000, gop_size=60
    )
    leg = secondary_audio_leg_from_track(_audio_track("t", source_uri="srt://dub:7001"), profile)
    assert leg.source[0].factory == "srtsrc"
    assert leg.source[0].props["uri"] == "srt://dub:7001"
    assert leg.source[1].factory == "decodebin"


def test_graph_from_config_wires_audio() -> None:
    config = EgressConfig(
        channel_id="c",
        enabled=True,
        slate_message="x",
        sinks=[EgressSinkSpec(kind="file", label="f", uri="file:///tmp/o.ts")],
    )
    plan = EgressSourcePlan(
        channel_id="c",
        segments=[EgressSourceSegment(label="s", path="/m/a.ts", duration_seconds=10)],
    )
    graph = graph_from_config(config, plan)
    # audio encoder present and ends on aacparse
    assert graph.audio_encoder
    assert graph.audio_encoder[-1].factory == "aacparse"
    assert any(spec.factory == "avenc_aac" for spec in graph.audio_encoder)
    # program (playlist) carries an audio tail; slate carries audiotestsrc — every
    # selector leg has audio so video/audio pad indices stay aligned for swaps
    program, slate = graph.sources
    assert program.audio_tail and program.audio_tail[0].factory == "audioconvert"
    assert slate.audio and slate.audio[0].factory == "audiotestsrc"
