# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the gi-free S15 element graph (runs on Windows; no gi)."""

from __future__ import annotations

import dataclasses

import pytest

from civiccast.egress.gst.graph import (
    LIVE_CAPTION_APPSRC_NAME,
    CaptionEmbedLeg,
    ElementSpec,
    PlaylistLeg,
    PlayoutGraph,
    SecondaryAudioLeg,
    SourceLeg,
    audio_encode_specs,
    caption_embed_leg_from_sidecar,
    caption_embed_leg_live,
    demo_test_graph,
    encode_chain_specs,
    graph_from_json,
    graph_to_json,
    source_leg_is_clock_timed,
)


def test_encode_chain_specs_default_openh264_has_h264parse() -> None:
    specs = encode_chain_specs()
    factories = [s.factory for s in specs]
    assert factories == [
        "videoconvert",
        "videoscale",
        "videorate",
        "capsfilter",
        "openh264enc",
        "h264parse",
    ]
    assert specs[-1].props["config-interval"] == -1
    assert specs[4].props["bitrate"] == 4000


def test_encode_chain_specs_explicit_x264_has_x264_controls() -> None:
    specs = encode_chain_specs(encoder="x264enc")
    factories = [s.factory for s in specs]
    assert factories == [
        "videoconvert",
        "videoscale",
        "videorate",
        "capsfilter",
        "x264enc",
        "h264parse",
    ]
    assert specs[4].props["key-int-max"] == 60


def test_encode_chain_specs_hevc_uses_h265parse() -> None:
    specs = encode_chain_specs(encoder="nvh265enc")
    assert specs[-1].factory == "h265parse"
    assert specs[-1].props["config-interval"] == -1
    assert specs[4].factory == "nvh265enc"


def test_encode_chain_specs_cbr_adds_hrd_option_string() -> None:
    specs = encode_chain_specs(encoder="x264enc", cbr=True, bitrate_kbps=6000)
    encoder = next(s for s in specs if s.factory == "x264enc")
    assert "nal-hrd=cbr" in encoder.props["option-string"]
    assert "vbv-maxrate=6000" in encoder.props["option-string"]


def test_encode_chain_specs_no_cbr_has_no_option_string() -> None:
    specs = encode_chain_specs(encoder="x264enc", cbr=False)
    encoder = next(s for s in specs if s.factory == "x264enc")
    assert "option-string" not in encoder.props


def test_audio_encode_specs_structure() -> None:
    specs = audio_encode_specs(codec="avenc_aac", bitrate_kbps=128)
    factories = [s.factory for s in specs]
    assert factories == ["audioconvert", "audioresample", "capsfilter", "avenc_aac", "aacparse"]
    encoder = next(s for s in specs if s.factory == "avenc_aac")
    assert encoder.props["bitrate"] == 128000  # bits/sec


def test_source_leg_audio_field() -> None:
    video_only = SourceLeg("v", (ElementSpec("videotestsrc"),))
    assert video_only.audio == ()
    with_audio = SourceLeg(
        "av", (ElementSpec("videotestsrc"),), audio=(ElementSpec("audiotestsrc"),)
    )
    assert with_audio.audio[0].factory == "audiotestsrc"


def test_capsfilter_caps_string() -> None:
    specs = encode_chain_specs(width=1920, height=1080, fps=30)
    caps = next(s for s in specs if s.factory == "capsfilter")
    assert caps.props["caps"] == "video/x-raw,width=1920,height=1080,framerate=30/1"


def test_demo_test_graph_shape() -> None:
    graph = demo_test_graph(out="/tmp/x.ts", nsrc=3)
    assert len(graph.sources) == 3
    assert graph.mux.factory == "mpegtsmux"
    assert graph.sinks[0][-1].factory == "filesink"
    assert graph.sinks[0][-1].props["location"] == "/tmp/x.ts"
    # each source leg ends on a common caps for renegotiation-free swaps
    for leg in graph.sources:
        assert leg.elements[0].factory == "videotestsrc"
        assert leg.elements[-1].factory == "capsfilter"
        assert leg.elements[-1].props["caps"] == "video/x-raw,width=640,height=360,framerate=30/1"


def test_source_leg_requires_elements() -> None:
    with pytest.raises(ValueError, match="at least one element"):
        SourceLeg("empty", ())


def test_playout_graph_requires_sources_and_sinks() -> None:
    enc = encode_chain_specs()
    mux = ElementSpec("mpegtsmux")
    sinks = ((ElementSpec("filesink", props={"location": "/tmp/x.ts"}),),)
    with pytest.raises(ValueError, match="source"):
        PlayoutGraph(sources=(), encoder=enc, mux=mux, sinks=sinks)
    with pytest.raises(ValueError, match="sink"):
        PlayoutGraph(
            sources=(SourceLeg("s", (ElementSpec("videotestsrc"),)),),
            encoder=enc,
            mux=mux,
            sinks=(),
        )


# --- S11a: CEA-708 caption embed leg --------------------------------------------


def test_caption_embed_leg_live_builds_appsrc_cea708_chain() -> None:
    leg = caption_embed_leg_live()
    assert [s.factory for s in leg.caption_source] == [
        "appsrc",
        "tttocea608",
        "ccconverter",
        "capsfilter",
    ]
    appsrc = leg.caption_source[0]
    assert appsrc.name == LIVE_CAPTION_APPSRC_NAME
    assert appsrc.props["is-live"] is True
    assert appsrc.props["format"] == 3  # GST_FORMAT_TIME
    assert "cc_data" in leg.caption_source[-1].props["caps"]
    assert leg.combiner.factory == "cccombiner"
    assert [s.factory for s in leg.inserter_chain] == ["h264ccinserter", "h264parse"]
    assert leg.inserter_chain[0].props["remove-caption-meta"] is True
    assert leg.inserter_chain[-1].props["config-interval"] == -1


def test_caption_embed_leg_from_sidecar_uses_filesrc_subparse() -> None:
    leg = caption_embed_leg_from_sidecar("/m/cap.vtt")
    assert [s.factory for s in leg.caption_source] == [
        "filesrc",
        "subparse",
        "tttocea608",
        "ccconverter",
        "capsfilter",
    ]
    assert leg.caption_source[0].props["location"] == "/m/cap.vtt"


def test_caption_embed_leg_validates_chains() -> None:
    with pytest.raises(ValueError, match="caption_source"):
        CaptionEmbedLeg(caption_source=())
    with pytest.raises(ValueError, match="inserter_chain"):
        CaptionEmbedLeg(caption_source=(ElementSpec("appsrc"),), inserter_chain=())


def test_graph_json_round_trip_with_captions() -> None:
    base = demo_test_graph(out="/tmp/x.ts", nsrc=2)
    graph = dataclasses.replace(base, captions=caption_embed_leg_live())
    restored = graph_from_json(graph_to_json(graph))
    assert restored.captions is not None
    assert restored.captions.combiner.factory == "cccombiner"
    assert [s.factory for s in restored.captions.caption_source] == [
        "appsrc",
        "tttocea608",
        "ccconverter",
        "capsfilter",
    ]
    assert [s.factory for s in restored.captions.inserter_chain] == [
        "h264ccinserter",
        "h264parse",
    ]


def test_graph_json_round_trip_without_captions_is_none() -> None:
    # Back-compat: a graph (and a pre-S11a serialized graph) with no caption leg
    # round-trips to captions=None — the default path is byte-identical.
    restored = graph_from_json(graph_to_json(demo_test_graph(out="/tmp/x.ts", nsrc=2)))
    assert restored.captions is None
    assert restored.secondary_audio == ()


# --- S11 gap 9: secondary audio (SAP / descriptive) -----------------------------


def _sap_leg() -> SecondaryAudioLeg:
    return SecondaryAudioLeg(
        label="Spanish SAP",
        language="es",
        kind="sap",
        source=(ElementSpec("filesrc", props={"location": "/m/es.aac"}), ElementSpec("decodebin")),
        encoder=audio_encode_specs(),
    )


def test_secondary_audio_leg_validates_chains() -> None:
    with pytest.raises(ValueError, match="source chain"):
        SecondaryAudioLeg(label="x", language="es", source=(), encoder=audio_encode_specs())
    with pytest.raises(ValueError, match="encoder chain"):
        SecondaryAudioLeg(label="x", language="es", source=(ElementSpec("filesrc"),), encoder=())


def test_graph_json_round_trip_with_secondary_audio() -> None:
    base = demo_test_graph(out="/tmp/x.ts", nsrc=2)
    graph = dataclasses.replace(base, secondary_audio=(_sap_leg(),))
    restored = graph_from_json(graph_to_json(graph))
    assert len(restored.secondary_audio) == 1
    leg = restored.secondary_audio[0]
    assert leg.language == "es"
    assert leg.kind == "sap"
    assert leg.source[0].factory == "filesrc"
    assert leg.encoder[-1].factory == "aacparse"


class TestSourceLegIsClockTimed:
    """``source_leg_is_clock_timed`` decides whether a boundary-aligned rollover may
    HOLD the new leg at its first buffer and REBASE its running time onto the outgoing
    leg's end (``GstPlayoutEngine.reload_program``). Both are right for a segment-timed
    leg and wrong for a clock-timed one, so the answer is load-bearing, and it is
    gi-free precisely so it can be pinned here on a bare checkout."""

    def _file_program(self) -> SourceLeg:
        return SourceLeg(
            label="program",
            elements=(
                ElementSpec("filesrc", props={"location": "C:/media/council.ts"}),
                ElementSpec("decodebin"),
                ElementSpec("videoconvert"),
            ),
            audio=(ElementSpec("audioconvert"), ElementSpec("audioresample")),
        )

    def test_a_file_backed_program_leg_is_segment_timed(self) -> None:
        assert source_leg_is_clock_timed(self._file_program()) is False

    def test_a_file_backed_playlist_leg_is_segment_timed(self) -> None:
        leg = PlaylistLeg(
            label="program",
            subchains=(
                (ElementSpec("filesrc", props={"location": "a.ts"}), ElementSpec("decodebin")),
                (ElementSpec("filesrc", props={"location": "b.ts"}), ElementSpec("decodebin")),
            ),
            audio_tail=(ElementSpec("audioconvert"),),
        )
        assert source_leg_is_clock_timed(leg) is False

    def test_a_live_ingest_source_is_clock_timed(self) -> None:
        for factory in ("udpsrc", "srtsrc", "rtspsrc", "decklinkvideosrc"):
            leg = SourceLeg(
                label="program",
                elements=(
                    ElementSpec(factory, props={"uri": "udp://127.0.0.1:5000"}),
                    ElementSpec("decodebin"),
                ),
            )
            assert source_leg_is_clock_timed(leg) is True, factory

    def test_an_is_live_property_is_enough_on_its_own(self) -> None:
        """The slate leg -- ``videotestsrc is-live=true`` -- names no factory from the
        list but is every bit as clock-timed."""
        leg = SourceLeg(
            label="slate",
            elements=(ElementSpec("videotestsrc", props={"is-live": True, "pattern": 2}),),
            audio=(ElementSpec("audiotestsrc", props={"is-live": True, "wave": 4}),),
        )
        assert source_leg_is_clock_timed(leg) is True

    def test_a_clock_timed_AUDIO_chain_alone_makes_the_leg_clock_timed(self) -> None:
        """A leg is only holdable if EVERY one of its streams is: holding the video
        while the audio runs on the clock desyncs them at the switch."""
        leg = SourceLeg(
            label="program",
            elements=(ElementSpec("filesrc", props={"location": "a.ts"}),),
            audio=(ElementSpec("udpsrc", props={"uri": "udp://127.0.0.1:5001"}),),
        )
        assert source_leg_is_clock_timed(leg) is True

    def test_a_playlist_whose_audio_tail_is_clock_timed_counts(self) -> None:
        leg = PlaylistLeg(
            label="program",
            subchains=((ElementSpec("filesrc", props={"location": "a.ts"}),),),
            audio_tail=(ElementSpec("appsrc"),),
        )
        assert source_leg_is_clock_timed(leg) is True

    def test_is_live_false_is_not_treated_as_live(self) -> None:
        """``is-live`` is a real tri-state in a serialized graph: absent, true, or an
        explicit false. Only true counts."""
        leg = SourceLeg(
            label="program",
            elements=(ElementSpec("videotestsrc", props={"is-live": False, "pattern": 0}),),
        )
        assert source_leg_is_clock_timed(leg) is False

    def test_windows_live_capture_devices_are_clock_timed(self) -> None:
        """Physical/OS capture devices (webcam/framegrabber, system audio) are
        always-live, same as decklink*src -- even though no ingest graph builder
        in this repository instantiates one of these yet."""
        for factory in (
            "ksvideosrc",
            "mfvideosrc",
            "dshowvideosrc",
            "wasapi2src",
            "wasapisrc",
            "v4l2src",
        ):
            leg = SourceLeg(
                label="program",
                elements=(ElementSpec(factory),),
            )
            assert source_leg_is_clock_timed(leg) is True, factory

    def test_an_unknown_factory_is_the_fail_safe_segment_timed_default(self) -> None:
        """Documents the chosen behaviour: a factory this module has never heard of
        (not in ``CLOCK_TIMED_SOURCE_FACTORIES`` and carrying no ``is-live`` prop) is
        NOT assumed clock-timed. The fail-safe side is segment-timed (``False``) --
        a boundary-aligned rollover neither holds nor rebases such a leg, which is
        the pre-existing default behaviour, not a live-content hazard. This is the
        opposite of an earlier draft of this module's own docstring, which claimed
        an unknown leg answers ``True``; the code has always returned ``False`` here
        (an empty/no-match ``any()``), and the docstring was the thing that was wrong.

        Also demonstrates that ``interpipesrc`` -- the RidgeRun interpipe plugin --
        is deliberately excluded from ``CLOCK_TIMED_SOURCE_FACTORIES``: it was
        demoted from the shipped GStreamer closure by an owner-confirmed spec
        decision and is not wired into any graph this repository builds, so it is
        treated the same as any other unrecognized factory here.
        """
        for factory in ("some-future-vendor-src", "interpipesrc"):
            leg = SourceLeg(
                label="program",
                elements=(ElementSpec(factory),),
            )
            assert source_leg_is_clock_timed(leg) is False, factory

    def test_the_predicate_survives_a_json_round_trip(self) -> None:
        """The engine answers this question about a leg it just deserialized from a
        reload sidecar, not about one it built in-process -- so the round trip is the
        path that actually matters."""
        leg = SourceLeg(
            label="program",
            elements=(ElementSpec("udpsrc", props={"uri": "udp://127.0.0.1:5000"}),),
        )
        graph = PlayoutGraph(
            sources=(leg,),
            encoder=(ElementSpec("videoconvert"),),
            mux=ElementSpec("mpegtsmux"),
            sinks=((ElementSpec("fakesink"),),),
        )
        restored = graph_from_json(graph_to_json(graph))
        assert source_leg_is_clock_timed(restored.sources[0]) is True
