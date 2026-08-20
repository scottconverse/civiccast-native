# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the pure S15 pipeline-description builders (no ``gi`` import)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from civiccast.egress.gst.pipeline import (
    EncodeProfile,
    PlayoutSource,
    _is_multicast,
    build_playout_pipeline_desc,
    encoder_chain,
    gst_sink_element,
)
from civiccast.egress.models import EgressSinkSpec


def _udp(uri: str = "udp://10.0.0.5:5000", label: str = "headend") -> EgressSinkSpec:
    return EgressSinkSpec(kind="udp-ts", label=label, uri=uri)


def _file(uri: str = "file:///tmp/capture.ts", label: str = "cap") -> EgressSinkSpec:
    return EgressSinkSpec(kind="file", label=label, uri=uri)


# --- gst_sink_element --------------------------------------------------------


def test_udp_ts_sink_element() -> None:
    assert gst_sink_element(_udp()) == "udpsink host=10.0.0.5 port=5000"


def test_udp_ts_multicast_sink_element() -> None:
    element = gst_sink_element(_udp(uri="udp://239.1.2.3:5000"))
    assert "udpsink host=239.1.2.3 port=5000" in element
    assert "auto-multicast=true" in element


def test_file_sink_element_keeps_posix_path() -> None:
    assert gst_sink_element(_file()) == "filesink location=/tmp/capture.ts"


def test_srt_sink_element() -> None:
    spec = EgressSinkSpec(kind="srt", label="srt", uri="srt://host:7001")
    assert gst_sink_element(spec) == 'srtsink uri="srt://host:7001"'


def test_sdi_sink_rejected() -> None:
    spec = SimpleNamespace(kind="sdi", uri="decklink://card0")
    with pytest.raises(ValueError, match="sdi"):
        gst_sink_element(spec)  # type: ignore[arg-type]


def test_rtmp_sink_rejected() -> None:
    spec = SimpleNamespace(kind="rtmp", uri="rtmp://host/app")
    with pytest.raises(ValueError, match="rtmp"):
        gst_sink_element(spec)  # type: ignore[arg-type]


# --- encoder_chain -----------------------------------------------------------


def test_encoder_chain_default_openh264_contains_profile() -> None:
    chain = encoder_chain(
        EncodeProfile(width=1920, height=1080, fps=30, video_bitrate_kbps=8000, gop_size=60)
    )
    assert "openh264enc" in chain
    assert "bitrate=8000" in chain
    assert "key-int-max=60" not in chain
    assert "width=1920,height=1080,framerate=30/1" in chain
    assert "h264parse config-interval=-1" in chain


def test_encoder_chain_explicit_x264_contains_x264_controls() -> None:
    chain = encoder_chain(EncodeProfile(encoder="x264enc", video_bitrate_kbps=8000, gop_size=60))
    assert "x264enc" in chain
    assert "bitrate=8000" in chain
    assert "key-int-max=60" in chain


def test_encoder_chain_hardware_encoder() -> None:
    chain = encoder_chain(EncodeProfile(encoder="nvh264enc", video_bitrate_kbps=6000))
    assert "nvh264enc bitrate=6000" in chain
    assert "x264enc" not in chain
    assert "h264parse config-interval=-1" in chain


def test_encoder_chain_hevc_uses_h265parse() -> None:
    chain = encoder_chain(EncodeProfile(encoder="nvh265enc"))
    assert "h265parse config-interval=-1" in chain
    assert "h264parse" not in chain


def test_is_multicast_ipv4_and_ipv6() -> None:
    assert _is_multicast("239.1.2.3") is True
    assert _is_multicast("224.0.0.1") is True
    assert _is_multicast("10.0.0.5") is False
    assert _is_multicast("ff02::1") is True
    assert _is_multicast("2001:db8::1") is False


# --- build_playout_pipeline_desc --------------------------------------------


def test_build_single_sink_has_no_tee() -> None:
    desc = build_playout_pipeline_desc(
        sources=[PlayoutSource("program", "videotestsrc is-live=true")],
        profile=EncodeProfile(),
        sinks=[_file()],
    )
    assert "input-selector name=sel" in desc
    assert "mpegtsmux name=mux" in desc
    assert "filesink location=/tmp/capture.ts" in desc
    assert "videotestsrc is-live=true ! sel.sink_0" in desc
    assert "tee name=t" not in desc


def test_build_multi_sink_uses_tee() -> None:
    desc = build_playout_pipeline_desc(
        sources=[PlayoutSource("program", "videotestsrc")],
        profile=EncodeProfile(),
        sinks=[_file(), _udp()],
    )
    assert "tee name=t" in desc
    assert desc.count("t. ! queue !") == 2


def test_build_multiple_sources_get_indexed_pads() -> None:
    sources = [
        PlayoutSource(name, f"videotestsrc pattern={index}")
        for index, name in enumerate(["program", "filler", "slate"])
    ]
    desc = build_playout_pipeline_desc(sources=sources, profile=EncodeProfile(), sinks=[_file()])
    assert "sel.sink_0" in desc
    assert "sel.sink_1" in desc
    assert "sel.sink_2" in desc


def test_build_rejects_empty_sources_or_sinks() -> None:
    with pytest.raises(ValueError, match="source"):
        build_playout_pipeline_desc(sources=[], profile=EncodeProfile(), sinks=[_file()])
    with pytest.raises(ValueError, match="sink"):
        build_playout_pipeline_desc(
            sources=[PlayoutSource("p", "videotestsrc")], profile=EncodeProfile(), sinks=[]
        )
