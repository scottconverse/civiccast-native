# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gi-free, pydantic-free element graph for the S15 playout engine.

Importable on BOTH Windows (unit tests + the EgressSinkSpec→graph mapping) and POSIX
(the live engine), because it depends only on the stdlib. The live runtime
(``engine.py``) consumes a ``PlayoutGraph`` and builds GStreamer elements from it via
element factories + ``set_property`` — never string ``parse_launch`` — so URI/path
values can never inject pipeline syntax (audit FINDING-002).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_H264_ENCODER = "openh264enc"


def coerce_serialized_property(
    *,
    key: str,
    value: Any,
    caps_from_string: Callable[[str], Any],
) -> Any:
    """Convert serialized GStreamer property values to their runtime types.

    ``ElementSpec`` must remain JSON-serializable, so GstCaps properties are
    represented as strings in every factory, including both ``capsfilter`` and
    the live-caption ``appsrc``.  PyGObject does not coerce the appsrc string on
    native Windows; convert every string-valued ``caps`` property explicitly.
    """

    if key == "caps" and isinstance(value, str):
        return caps_from_string(value)
    return value


@dataclass(frozen=True)
class ElementSpec:
    """One GStreamer element: factory name + optional element name + properties."""

    factory: str
    name: str | None = None
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceLeg:
    """A hot-swappable source: a linear chain producing raw video.

    The last element's src pad links to one input-selector request sink pad. Source
    legs should end on a common caps (S15 §3 glitch-free-swap rule) so swaps don't
    trigger renegotiation downstream.
    """

    label: str
    elements: tuple[ElementSpec, ...]
    audio: tuple[ElementSpec, ...] = ()  # optional audio chain → the audio selector pad

    def __post_init__(self) -> None:
        if not self.elements:
            raise ValueError(f"SourceLeg {self.label!r} requires at least one element")


@dataclass(frozen=True)
class PlaylistLeg:
    """A source leg that plays sub-chains in sequence via ``concat`` (gapless).

    Each sub-chain is a linear ``ElementSpec`` chain producing raw video (e.g.
    ``filesrc ! decodebin ! videoconvert ! …`` or a finite ``videotestsrc``);
    ``concat`` sequences them with no output restart, and its src feeds one
    input-selector pad. Sub-chains should end on a common caps so neither the
    clip-to-clip boundary nor the role swap triggers renegotiation. This is the
    "program" leg of design D-S1-6 (Option A).
    """

    label: str
    subchains: tuple[tuple[ElementSpec, ...], ...]
    # optional per-clip audio chain (audioconvert..capsfilter) fed by each clip's
    # decodebin audio pad → a parallel audio concat → the audio selector pad
    audio_tail: tuple[ElementSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.subchains:
            raise ValueError(f"PlaylistLeg {self.label!r} requires at least one sub-chain")
        for chain in self.subchains:
            if not chain:
                raise ValueError(f"PlaylistLeg {self.label!r} has an empty sub-chain")


@dataclass(frozen=True)
class CaptionEmbedLeg:
    """CEA-608/708 caption EMBED leg (S11a, GStreamer-native).

    Inserts closed captions as A/53 SEI into the ALREADY-ENCODED H.264 elementary
    stream on the output half (which stays PLAYING across source swaps/reloads)::

        …encoder tail (h264parse) ─► cccombiner.sink ─► h264ccinserter ─► h264parse ─► mux
        caption_source (timed text → tttocea608 → ccconverter → cc_data) ─► cccombiner.caption

    Per the documented gst-plugins-bad pipeline, ``cccombiner`` attaches a
    ``GstVideoCaptionMeta`` to the H.264 buffers and ``h264ccinserter`` serializes that
    meta as CEA-708 SEI (``remove-caption-meta=true`` strips the meta afterwards).
    ``ccconverter`` ships in the same plugin as ``cccombiner`` (no extra availability
    requirement; the doctor lane probes ``GST_CC_ELEMENTS``). The CC text comes from the
    channel caption pipeline (sidecar/ASR/review) — a ``filesrc``+parser for a finite
    sidecar, or a live ``appsrc`` the daemon pushes timed-text cues into
    (``GstPlayoutEngine.push_caption_cue`` via the worker ``caption`` control command).

    Gi-free data only; the live engine (``engine.py``) builds + pad-links this. The live
    run (SEI actually present in the emitted stream) is POSIX/LPM-validated; the decode-back
    proof loop (``caption_proof_worker``) is what flips ``caption_status`` to ``on``.
    """

    caption_source: tuple[ElementSpec, ...]
    combiner: ElementSpec = ElementSpec("cccombiner", name="cccombiner")
    inserter_chain: tuple[ElementSpec, ...] = (
        ElementSpec("h264ccinserter", name="h264ccinserter", props={"remove-caption-meta": True}),
        ElementSpec("h264parse", props={"config-interval": -1}),
    )

    def __post_init__(self) -> None:
        if not self.caption_source:
            raise ValueError("CaptionEmbedLeg requires a caption_source chain")
        if not self.inserter_chain:
            raise ValueError("CaptionEmbedLeg requires an inserter_chain")


@dataclass(frozen=True)
class SecondaryAudioLeg:
    """A secondary audio program (SAP / descriptive) muxed as an ADDITIONAL MPEG-TS
    audio PID (S11 gap 9 — secondary audio / SAP support; the TV "SAP" button).

    ``source`` produces raw audio for this track (e.g. ``filesrc ! decodebin`` or a live
    source ! decodebin); ``encoder`` is the AAC conform→encode→parse chain. ``language``
    is the BCP-47/ISO-639 tag stamped on the PID's language descriptor. Unlike the
    program audio (which swaps with the active video source), a secondary track is its
    own continuous program. Live PID assignment + the language descriptor are
    POSIX/LPM-validated."""

    label: str
    language: str
    source: tuple[ElementSpec, ...]
    encoder: tuple[ElementSpec, ...]
    kind: str = "sap"  # primary | sap | descriptive

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError(f"SecondaryAudioLeg {self.label!r} requires a source chain")
        if not self.encoder:
            raise ValueError(f"SecondaryAudioLeg {self.label!r} requires an encoder chain")


@dataclass(frozen=True)
class AudioTapLeg:
    """Raw program-audio fork consumed by the mandatory live-caption worker."""

    tap_dir: str
    segment_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.tap_dir.strip():
            raise ValueError("AudioTapLeg requires a tap_dir")
        if self.segment_seconds <= 0:
            raise ValueError("AudioTapLeg segment_seconds must be positive")


@dataclass(frozen=True)
class PlayoutGraph:
    """The full playout element graph (gi-free)."""

    sources: tuple[SourceLeg | PlaylistLeg, ...]
    encoder: tuple[ElementSpec, ...]  # videoconvert, videoscale, capsfilter, encoder, parser
    mux: ElementSpec
    sinks: tuple[tuple[ElementSpec, ...], ...]  # each branch = (queue, ..., sink-element)
    audio_encoder: tuple[
        ElementSpec, ...
    ] = ()  # audioconvert..aacenc..aacparse (empty = video-only)
    # Optional raw-audio tee -> appsink -> atomic rolling WAV writer. Native
    # stations always set this; None preserves non-native/dev graph behavior.
    audio_tap: AudioTapLeg | None = None
    # Optional CEA-708 caption embed leg (S11a). None = today's behavior (no captions
    # embedded; the graph is byte-identical to the pre-S11a graph).
    captions: CaptionEmbedLeg | None = None
    # Optional secondary audio programs (S11 gap 9 — SAP / descriptive). Empty = a single
    # audio PID (today's behavior, byte-identical).
    secondary_audio: tuple[SecondaryAudioLeg, ...] = ()

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("PlayoutGraph requires at least one source")
        if not self.sinks:
            raise ValueError("PlayoutGraph requires at least one sink")
        if self.audio_tap is not None and not self.audio_encoder:
            raise ValueError("PlayoutGraph audio_tap requires a program audio encoder")


def encode_chain_specs(
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    bitrate_kbps: int = 4000,
    gop: int = 60,
    encoder: str = DEFAULT_H264_ENCODER,
    cbr: bool = False,
    vbv_bufsize_kbits: int | None = None,
) -> tuple[ElementSpec, ...]:
    """The conform→encode→parse element chain feeding the muxer.

    Mirrors ``pipeline.encoder_chain`` but as structured specs: a parser with
    ``config-interval=-1`` follows H.264/H.265 encoders for headend tune-in.
    ``cbr=True`` adds HRD constant-bitrate rate control when the explicit optional
    ``x264enc`` encoder is selected; the bundled public-beta runtime defaults to
    ``openh264enc`` and does not ship GPL x264.
    """
    caps = f"video/x-raw,width={width},height={height},framerate={fps}/1"
    specs = [
        ElementSpec("videoconvert"),
        ElementSpec("videoscale"),
        ElementSpec("videorate"),
        ElementSpec("capsfilter", props={"caps": caps}),
    ]
    if encoder == "x264enc":
        props = {"tune": "zerolatency", "bitrate": bitrate_kbps, "key-int-max": gop}
        if cbr:
            # cap VBV at the target rate with a ~1s buffer and signal nal-hrd=cbr
            bufsize = vbv_bufsize_kbits or bitrate_kbps
            props["option-string"] = f"vbv-maxrate={bitrate_kbps}:vbv-bufsize={bufsize}:nal-hrd=cbr"
        specs.append(ElementSpec("x264enc", props=props))
    else:
        specs.append(ElementSpec(encoder, props={"bitrate": bitrate_kbps}))
    lowered = encoder.lower()
    if "265" in lowered or "hevc" in lowered:
        specs.append(ElementSpec("h265parse", props={"config-interval": -1}))
    elif "264" in lowered or "avc" in lowered:
        specs.append(ElementSpec("h264parse", props={"config-interval": -1}))
    return tuple(specs)


def audio_encode_specs(
    *, codec: str = "avenc_aac", bitrate_kbps: int = 128, sample_rate: int = 48000
) -> tuple[ElementSpec, ...]:
    """The audio conform→encode→parse chain feeding the muxer's audio pad.

    AAC via ``avenc_aac`` (gst-libav, default) or ``voaacenc`` (gst-plugins-bad,
    Apache-2.0). Encoder ``bitrate`` is bits/sec. ``faac``/``fdkaacenc`` are NOT in
    stock Ubuntu 24.04 — do not assume them.
    """
    return (
        ElementSpec("audioconvert"),
        ElementSpec("audioresample"),
        ElementSpec("capsfilter", props={"caps": f"audio/x-raw,rate={sample_rate}"}),
        ElementSpec(codec, props={"bitrate": bitrate_kbps * 1000}),
        ElementSpec("aacparse"),
    )


# The live caption appsrc element name — the engine looks it up by this name to push
# timed-text cues, and the live builder stamps it, so the two agree without coupling.
LIVE_CAPTION_APPSRC_NAME = "captionsrc"

# tttocea608 emits CEA-608; ccconverter wraps it as the CEA-708 cc_data the A/53 SEI
# carries (608-in-708, the ATSC parity baseline). Mirrors the documented
# gst-plugins-bad h264ccinserter pipeline.
_CEA708_CC_DATA_CAPS = "closedcaption/x-cea-708,format=(string)cc_data,framerate=(fraction)30/1"


def _cea708_caption_tail() -> tuple[ElementSpec, ...]:
    """Timed text → CEA-608 → CEA-708 cc_data, ready for ``cccombiner.caption``."""
    return (
        ElementSpec("tttocea608", name="tttocea608", props={"mode": "pop-on"}),
        ElementSpec("ccconverter"),
        ElementSpec("capsfilter", props={"caps": _CEA708_CC_DATA_CAPS}),
    )


def caption_embed_leg_from_sidecar(
    sidecar_path: str, *, parser: str = "subparse"
) -> CaptionEmbedLeg:
    """A caption embed leg sourced from a finite timed-text sidecar (VOD / proof / test).

    ``filesrc ! subparse`` parses a WebVTT/SRT sidecar into timed text the CEA tail
    converts to cc_data. The sidecar's cues must run on the program's running-time."""
    return CaptionEmbedLeg(
        caption_source=(
            ElementSpec("filesrc", props={"location": sidecar_path}),
            ElementSpec(parser),
            *_cea708_caption_tail(),
        ),
    )


def caption_embed_leg_live(appsrc_name: str = LIVE_CAPTION_APPSRC_NAME) -> CaptionEmbedLeg:
    """A caption embed leg sourced from a live ``appsrc`` the daemon pushes cues into.

    The engine pushes timed-text buffers (PTS+duration) into this appsrc on each
    ``caption`` control command — the 24/7 continuous-caption path (ASR tap / review
    queue). ``format=time`` so cccombiner can schedule the cue against the video PTS."""
    return CaptionEmbedLeg(
        caption_source=(
            ElementSpec(
                "appsrc",
                name=appsrc_name,
                props={
                    "is-live": True,
                    "format": 3,  # GST_FORMAT_TIME
                    "do-timestamp": False,
                    "caps": "text/x-raw,format=(string)utf8",
                },
            ),
            *_cea708_caption_tail(),
        ),
    )


def demo_test_graph(
    *,
    out: str = "/tmp/engine_swap.ts",  # noqa: S108  # nosec B108
    nsrc: int = 3,
    bitrate_kbps: int = 2000,
) -> PlayoutGraph:
    """A self-contained graph (videotestsrc sources → filesink) for engine validation.

    Mirrors the Stage-0 prototype but expressed as a ``PlayoutGraph`` the engine builds
    via element factories. Needs no external media. Source legs end on a common caps
    so swaps are renegotiation-free.
    """
    patterns = [0, 18, 1, 2, 3]
    common_caps = "video/x-raw,width=640,height=360,framerate=30/1"
    sources = tuple(
        SourceLeg(
            label=f"src{i}",
            elements=(
                ElementSpec(
                    "videotestsrc",
                    props={"is-live": True, "pattern": patterns[i % len(patterns)]},
                ),
                ElementSpec("capsfilter", props={"caps": common_caps}),
            ),
        )
        for i in range(nsrc)
    )
    encoder = encode_chain_specs(width=640, height=360, fps=30, bitrate_kbps=bitrate_kbps, gop=30)
    mux = ElementSpec("mpegtsmux", name="mux")
    sinks = ((ElementSpec("queue"), ElementSpec("filesink", props={"location": out})),)
    return PlayoutGraph(sources=sources, encoder=encoder, mux=mux, sinks=sinks)


# --- JSON (de)serialization (gi-free; the strategy writes, the worker reads) ----


def _elem_to_dict(spec: ElementSpec) -> dict[str, Any]:
    return {"factory": spec.factory, "name": spec.name, "props": dict(spec.props)}


def _elem_from_dict(obj: dict[str, Any]) -> ElementSpec:
    return ElementSpec(
        factory=obj["factory"], name=obj.get("name"), props=dict(obj.get("props") or {})
    )


def _captions_to_dict(leg: CaptionEmbedLeg | None) -> dict[str, Any] | None:
    if leg is None:
        return None
    return {
        "caption_source": [_elem_to_dict(e) for e in leg.caption_source],
        "combiner": _elem_to_dict(leg.combiner),
        "inserter_chain": [_elem_to_dict(e) for e in leg.inserter_chain],
    }


def _captions_from_dict(obj: dict[str, Any] | None) -> CaptionEmbedLeg | None:
    if obj is None:
        return None
    return CaptionEmbedLeg(
        caption_source=tuple(_elem_from_dict(e) for e in obj["caption_source"]),
        combiner=_elem_from_dict(obj["combiner"]),
        inserter_chain=tuple(_elem_from_dict(e) for e in obj["inserter_chain"]),
    )


def _secondary_to_dict(leg: SecondaryAudioLeg) -> dict[str, Any]:
    return {
        "label": leg.label,
        "language": leg.language,
        "kind": leg.kind,
        "source": [_elem_to_dict(e) for e in leg.source],
        "encoder": [_elem_to_dict(e) for e in leg.encoder],
    }


def _secondary_from_dict(obj: dict[str, Any]) -> SecondaryAudioLeg:
    return SecondaryAudioLeg(
        label=obj["label"],
        language=obj["language"],
        kind=obj.get("kind", "sap"),
        source=tuple(_elem_from_dict(e) for e in obj["source"]),
        encoder=tuple(_elem_from_dict(e) for e in obj["encoder"]),
    )


def graph_to_json(graph: PlayoutGraph) -> str:
    def src(source: SourceLeg | PlaylistLeg) -> dict[str, Any]:
        if isinstance(source, PlaylistLeg):
            return {
                "type": "playlist",
                "label": source.label,
                "subchains": [[_elem_to_dict(e) for e in ch] for ch in source.subchains],
                "audio_tail": [_elem_to_dict(e) for e in source.audio_tail],
            }
        return {
            "type": "source",
            "label": source.label,
            "elements": [_elem_to_dict(e) for e in source.elements],
            "audio": [_elem_to_dict(e) for e in source.audio],
        }

    return json.dumps(
        {
            "sources": [src(s) for s in graph.sources],
            "encoder": [_elem_to_dict(e) for e in graph.encoder],
            "audio_encoder": [_elem_to_dict(e) for e in graph.audio_encoder],
            "audio_tap": (
                {
                    "tap_dir": graph.audio_tap.tap_dir,
                    "segment_seconds": graph.audio_tap.segment_seconds,
                }
                if graph.audio_tap is not None
                else None
            ),
            "mux": _elem_to_dict(graph.mux),
            "sinks": [[_elem_to_dict(e) for e in branch] for branch in graph.sinks],
            "captions": _captions_to_dict(graph.captions),
            "secondary_audio": [_secondary_to_dict(leg) for leg in graph.secondary_audio],
        },
        indent=2,
    )


def graph_from_json(text: str) -> PlayoutGraph:
    data = json.loads(text)

    def src(obj: dict[str, Any]) -> SourceLeg | PlaylistLeg:
        if obj["type"] == "playlist":
            return PlaylistLeg(
                label=obj["label"],
                subchains=tuple(
                    tuple(_elem_from_dict(e) for e in chain) for chain in obj["subchains"]
                ),
                audio_tail=tuple(_elem_from_dict(e) for e in obj.get("audio_tail", [])),
            )
        return SourceLeg(
            label=obj["label"],
            elements=tuple(_elem_from_dict(e) for e in obj["elements"]),
            audio=tuple(_elem_from_dict(e) for e in obj.get("audio", [])),
        )

    return PlayoutGraph(
        sources=tuple(src(s) for s in data["sources"]),
        encoder=tuple(_elem_from_dict(e) for e in data["encoder"]),
        audio_encoder=tuple(_elem_from_dict(e) for e in data.get("audio_encoder", [])),
        audio_tap=(
            AudioTapLeg(
                tap_dir=data["audio_tap"]["tap_dir"],
                segment_seconds=float(data["audio_tap"]["segment_seconds"]),
            )
            if data.get("audio_tap") is not None
            else None
        ),
        mux=_elem_from_dict(data["mux"]),
        sinks=tuple(tuple(_elem_from_dict(e) for e in branch) for branch in data["sinks"]),
        captions=_captions_from_dict(data.get("captions")),
        secondary_audio=tuple(_secondary_from_dict(obj) for obj in data.get("secondary_audio", [])),
    )
