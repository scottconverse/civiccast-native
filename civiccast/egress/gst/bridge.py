# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bridge: CivicCast egress config/profile → gi-free PlayoutGraph element specs.

Windows-side (imports pydantic models). Maps the durable ``EgressConfig`` — its
codec profile and sink specs — into the structured ``ElementSpec`` pieces the live
engine (``engine.py``) builds from via element factories. The source-segment →
source-leg mapping (the sequential-plan vs parallel-selector reconciliation, design
decision D-S1-6 in the Stage-1 plan) is implemented below in ``graph_from_config`` /
``source_first_element``.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from civiccast.egress.audio_tracks import AudioProgramTrack
from civiccast.egress.errors import SecretUnresolvedError
from civiccast.egress.gst.graph import (
    DEFAULT_H264_ENCODER,
    CaptionEmbedLeg,
    ElementSpec,
    GraphicsOverlayLayer,
    GraphicsOverlayLeg,
    PlaylistLeg,
    PlayoutGraph,
    SecondaryAudioLeg,
    SourceLeg,
    audio_encode_specs,
    caption_embed_leg_from_sidecar,
    caption_embed_leg_live,
    encode_chain_specs,
)
from civiccast.egress.gst.graphics_overlay import render_lower_third_png
from civiccast.egress.gst.pipeline import _is_multicast
from civiccast.egress.hls_relay import hls_relay_uri_for
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.sinks import SecretResolver

_LOG = logging.getLogger(__name__)

#: D45 fix (2026-09-05) hard cap on decoder sub-chains ``graph_from_config``
#: will actually BUILD for one channel's playlist leg, independent of
#: whatever ``max_segments``/``segment_cap`` a source-plan caller used. Each
#: sub-chain is a real decodebin instance (avdec_h264 defaults to
#: max-threads=0, ~20 threads each) built and set to PLAYING together at
#: start -- see ``graph_from_config``'s docstring for the measured cost of
#: skipping this cap (~1200 threads / ~3.5 GB from a 60-segment plan).
MAX_PLAYLIST_SUBCHAINS = 12

#: Sink kinds the GStreamer engine can actually deliver (Task B: an unsupported
#: kind must be refused at config time, not accepted-then-crash at start time —
#: see ``civiccast.egress.router.upsert_config``, which enforces this set
#: whenever ``civiccast.egress.engine_select.gstreamer_engine_selected()`` is
#: true). ``sdi`` sinks never reach ``sink_element_spec`` (skipped in
#: ``sink_branches_from_config``, delivered by the supervised BYO relay
#: instead); ``hls`` sinks are delivered by ``HlsRelaySupervisor`` — real
#: segments + a real manifest via a supervised ffmpeg child, not a native
#: GStreamer HLS element (none ships in the runtime; see
#: ``civiccast.egress.hls_relay``'s module docstring for the empirical proof).
#: ``rtmp`` is the one kind genuinely unimplemented here — Stage 1 ships TS
#: sinks only for this engine (the ffmpeg-concat engine's ``RtmpSink`` already
#: supports it).
SUPPORTED_SINK_KINDS = frozenset({"srt", "local-ts", "udp-ts", "file", "sdi", "hls"})

# CanonicalProfile.video_codec carries an ffmpeg encoder name (the prior pipeline was
# ffmpeg+libx264). The public beta installer ships a bundled GStreamer runtime with
# openh264enc, not GPL x264enc, so legacy/default H.264 profiles map to openh264enc
# unless x264 is explicitly requested.
_FFMPEG_TO_GST_ENCODER = {
    "libx264": DEFAULT_H264_ENCODER,
    "h264": DEFAULT_H264_ENCODER,
    "openh264": DEFAULT_H264_ENCODER,
    "libopenh264": DEFAULT_H264_ENCODER,
    "h264_openh264": DEFAULT_H264_ENCODER,
    "x264": "x264enc",
    "libx265": "x265enc",
    "hevc": "x265enc",
    "h265": "x265enc",
    "h264_nvenc": "nvh264enc",
    "hevc_nvenc": "nvh265enc",
    "h264_vaapi": "vah264enc",
    "hevc_vaapi": "vah265enc",
}

# Native Windows has no VAAPI (Linux-only, needs libva + a DRM render node). The
# GStreamer Media Foundation plugin (gst-plugins-bad) ships mfh264enc/mfh265enc,
# which map onto the same hardware-encode intent VAAPI expresses on Linux.
_WINDOWS_VAAPI_REMAP = {
    "h264_vaapi": "mfh264enc",
    "hevc_vaapi": "mfh265enc",
}


def gst_encoder_name(ffmpeg_codec: str, *, is_windows: bool | None = None) -> str:
    """Map an ffmpeg encoder name to a GStreamer encoder factory.

    On native Windows (``is_windows`` True, or defaulted from ``os.name == "nt"``),
    the Linux-only VAAPI entries remap to the Media Foundation encoders that
    actually exist there; every other codec falls through to the base mapping
    unchanged.
    """
    if is_windows is None:
        is_windows = os.name == "nt"
    normalized = ffmpeg_codec.strip().lower()
    if is_windows and normalized in _WINDOWS_VAAPI_REMAP:
        return _WINDOWS_VAAPI_REMAP[normalized]
    return _FFMPEG_TO_GST_ENCODER.get(normalized, DEFAULT_H264_ENCODER)


_FFMPEG_TO_GST_AUDIO_ENCODER = {
    "aac": "avenc_aac",
    "libfdk_aac": "avenc_aac",
    "voaac": "voaacenc",
}


def gst_audio_encoder_name(ffmpeg_codec: str) -> str:
    """Map an ffmpeg audio codec to a GStreamer AAC encoder (avenc_aac default).

    `faac`/`fdkaacenc` are NOT in stock Ubuntu 24.04; `avenc_aac` (gst-libav) and
    `voaacenc` (gst-plugins-bad, Apache-2.0) are."""
    return _FFMPEG_TO_GST_AUDIO_ENCODER.get(ffmpeg_codec.strip().lower(), "avenc_aac")


# Media Foundation encoders reject the unconstrained pixel format the conform
# capsfilter otherwise leaves open; they require an explicit NV12 input. Pinned MF-only.
_MF_ENCODERS = frozenset({"mfh264enc", "mfh265enc"})


def _apply_encoder_fixups(
    specs: tuple[ElementSpec, ...], encoder: str, bitrate_kbps: int
) -> tuple[ElementSpec, ...]:
    """Encoder-specific corrections kept OUT of the claims-governed ``graph.py``:

    * ``openh264enc`` takes ``bitrate`` in BITS/sec (unlike mf/nv/x264, which use
      kbit/sec), so the profile's kbit/sec value is converted or software encoding
      under-delivers ~2x.
    * Media Foundation encoders need an explicit ``NV12`` input pinned on the conform
      capsfilter; every other encoder negotiates its own format and is left untouched.
    """
    fixed: list[ElementSpec] = []
    for spec in specs:
        caps = str(spec.props.get("caps", ""))
        if spec.factory == "openh264enc" and "bitrate" in spec.props:
            fixed.append(replace(spec, props={**spec.props, "bitrate": bitrate_kbps * 1000}))
        elif (
            encoder in _MF_ENCODERS
            and spec.factory == "capsfilter"
            and caps.startswith("video/x-raw")
            and "format=" not in caps
        ):
            pinned = caps.replace("video/x-raw,", "video/x-raw,format=NV12,", 1)
            fixed.append(replace(spec, props={**spec.props, "caps": pinned}))
        else:
            fixed.append(spec)
    return tuple(fixed)


def encode_chain_from_profile(
    profile: CanonicalProfile, *, cbr: bool = False, encoder_override: str | None = None
) -> tuple[ElementSpec, ...]:
    """``CanonicalProfile`` → conform→encode→parse chain. ``cbr`` adds HRD constant
    bitrate (cable headend tune-in / clean QAM). ``encoder_override`` forces a specific
    GStreamer encoder factory instead of the one the codec maps to (used by the
    native-Windows pre-flight's software fallback); None keeps the mapped encoder.
    Encoder-specific fixups (openh264 bitrate units, MF NV12 input) are applied last."""
    encoder = encoder_override or gst_encoder_name(profile.video_codec)
    specs = encode_chain_specs(
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
        bitrate_kbps=profile.video_bitrate_kbps,
        gop=profile.gop_size,
        encoder=encoder,
        cbr=cbr,
    )
    return _apply_encoder_fixups(specs, encoder, profile.video_bitrate_kbps)


# Live ingest source elements by URI scheme. The v2 `live/` module ingests/records a
# feed; here the *engine* consumes a live feed as a playout source (S15 program/live
# leg). decodebin demuxes+decodes whatever the live element produces (TS over SRT/UDP,
# FLV over RTMP, RTP over RTSP), so the rest of the sub-chain is unchanged.
_LIVE_SOURCE_BY_SCHEME = {
    "srt": ("srtsrc", "uri"),
    "udp": ("udpsrc", "uri"),
    "rtmp": ("rtmpsrc", "location"),
    "rtmps": ("rtmpsrc", "location"),
    "rtsp": ("rtspsrc", "location"),
    "rtsps": ("rtspsrc", "location"),
    "http": ("souphttpsrc", "location"),
    "https": ("souphttpsrc", "location"),
}


def source_first_element(segment: EgressSourceSegment) -> ElementSpec:
    """The head element for one source segment's sub-chain.

    A pre-conformed file segment is a ``filesrc``; a live segment (``kind='live'``)
    maps to the live source element for its URI scheme. The engine plays a live feed
    whenever a live plan is the active program — at start, or applied seamlessly via a
    content-reload takeover (D-S1-6 / Gap 2). The dedicated always-hot ``live`` selector
    role and the operator live-cut control surface are S16 (Production/Control Room).
    """
    if segment.kind == "live":
        scheme = urlsplit(segment.path).scheme.lower()
        mapping = _LIVE_SOURCE_BY_SCHEME.get(scheme)
        if mapping is None:
            raise ValueError(
                f"unsupported live source scheme {scheme!r} for segment {segment.label!r} "
                "(use srt/udp/rtmp/rtsp/http)"
            )
        factory, prop = mapping
        secret_props: dict[str, str] = {}
        if segment.secret_ref:
            if scheme != "srt":
                # WP-07: only SRT has a credential property this engine can set
                # without writing the secret into the URI. Anything else that
                # arrives carrying a handle is a wiring bug upstream, and the
                # safe answer is to refuse the graph rather than to open the
                # feed unauthenticated and call it live.
                raise ValueError(
                    f"live source scheme {scheme!r} for segment {segment.label!r} cannot "
                    "carry a stored credential; only SRT has a passphrase property this "
                    "engine can set without putting the secret in the address"
                )
            # ``srtsrc`` has a first-class ``passphrase`` property, so the
            # secret never touches the URI, the graph file, or a log line --
            # only the handle travels, and the worker resolves it.
            secret_props["passphrase"] = segment.secret_ref
        return ElementSpec(factory, props={prop: segment.path}, secret_props=secret_props)
    return ElementSpec("filesrc", props={"location": segment.path})


def _append_query_param(uri: str, key: str, value: str) -> str:
    """Append a single query parameter to a URI (used to inject an SRT passphrase)."""
    parsed = urlsplit(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append((key, value))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def sink_element_spec(
    spec: EgressSinkSpec, resolve_secret: SecretResolver | None = None
) -> ElementSpec:
    """One ``EgressSinkSpec`` → the GStreamer sink ``ElementSpec`` consuming the TS.

    Structured twin of ``pipeline.gst_sink_element`` (which returns a launch string);
    the engine builds this via element factory + ``set_property`` (no parse_launch).
    Raises for sink kinds that need a non-TS branch (sdi/rtmp). ENG-007: an SRT sink's
    ``secret_ref`` is resolved into the URI's ``passphrase`` (symmetric with the ffmpeg
    ``SrtSink``); an unresolved ref raises ``SecretUnresolvedError`` rather than emitting
    an unauthenticated sink.
    """
    parsed = urlsplit(spec.uri)
    if spec.kind == "file" or (spec.kind == "local-ts" and parsed.scheme == "file"):
        location = parsed.path if parsed.scheme == "file" else spec.uri
        return ElementSpec("filesink", props={"location": location})
    if spec.kind in {"udp-ts", "local-ts"}:
        host = parsed.hostname or "127.0.0.1"
        if parsed.port is None:
            raise ValueError(f"{spec.kind} sink requires an explicit port: {spec.uri}")
        props: dict[str, Any] = {"host": host, "port": parsed.port}
        if _is_multicast(host):
            props["auto-multicast"] = True
        return ElementSpec("udpsink", props=props)
    if spec.kind == "srt":
        uri = spec.uri
        if spec.secret_ref is not None:
            passphrase = resolve_secret(spec.secret_ref) if resolve_secret else None
            if not passphrase:
                raise SecretUnresolvedError(
                    f"secret ref {spec.secret_ref!r} is not resolved for sink {spec.label!r}"
                )
            uri = _append_query_param(uri, "passphrase", passphrase)
        return ElementSpec("srtsink", props={"uri": uri})
    if spec.kind == "hls":
        # DEFECT A: no native GStreamer element in the shipped runtime can
        # actually write HLS segments + a manifest (verified empirically —
        # see civiccast.egress.hls_relay's module docstring: no hlssink/
        # hlssink2/hlssink3/splitmuxsink ships, and gst-libav's avmux_hls
        # writes zero files through a filesink). ``HlsRelaySupervisor.apply``
        # runs before graph assembly (civiccast.egress.daemon._start /
        # _try_content_reload, mirroring civiccast.egress.ts_relay) and
        # rewrites a configured ``hls`` sink to an ordinary ``local-ts`` udp
        # sink aimed at its relay's loopback port, so THIS branch is a
        # fallback safety net (a direct call, or a deployment where the relay
        # could not start) rather than the hot path. It maps to the exact
        # same deterministic loopback port the relay listens on, so even
        # reached directly it produces a genuinely wired udpsink, never a
        # crash — the relay just may not be receiving on the other end yet.
        host_port = urlsplit(hls_relay_uri_for(spec.uri)).netloc
        host, _, port = host_port.partition(":")
        return ElementSpec("udpsink", props={"host": host, "port": int(port)})
    if spec.kind == "rtmp":
        raise ValueError(
            "rtmp sink needs an flvmux branch, not the TS mux — the GStreamer engine ships "
            f"TS sinks only in Stage 1. Supported sink kinds here: {sorted(SUPPORTED_SINK_KINDS)} "
            "(use the ffmpeg-concat engine, CIVICCAST_EGRESS_ENGINE=ffmpeg-concat, for rtmp)."
        )
    if spec.kind == "sdi":
        raise ValueError("sdi output is a pre-mux decklinkvideosink branch, not a TS sink")
    raise ValueError(
        f"unknown sink kind: {spec.kind!r}. Supported sink kinds for the GStreamer engine: "
        f"{sorted(SUPPORTED_SINK_KINDS)}."
    )


def sink_branches_from_config(
    config: EgressConfig, resolve_secret: SecretResolver | None = None
) -> tuple[tuple[ElementSpec, ...], ...]:
    """``EgressConfig.sinks`` → engine sink branches, each ``(queue, <sink element>)``.

    SDI sinks are skipped — SDI is delivered by the supervised BYO relay off the TS
    output (S15 §4 / issue #117), not as an engine sink. Other unsupported kinds
    (rtmp) raise rather than silently drop a configured output. ``resolve_secret`` is
    threaded through for SRT-sink ``secret_ref`` resolution (ENG-007).
    """
    branches: list[tuple[ElementSpec, ...]] = []
    for spec in config.sinks:
        if spec.kind == "sdi":
            continue  # delivered by the supervised relay, not an engine TS sink
        branches.append((ElementSpec("queue"), sink_element_spec(spec, resolve_secret)))
    if not branches:
        raise ValueError("config has no TS-capable sinks for the GStreamer engine")
    return tuple(branches)


@dataclass(frozen=True)
class CaptionEmbedRequest:
    """Per-channel request to embed CEA-708 captions on the gst engine (S11a).

    ``live`` (default) builds an ``appsrc``-fed leg the daemon pushes continuous cues
    into (ASR tap / review queue); ``sidecar`` builds a ``filesrc``+parser leg for a
    finite timed-text file. None of this is on by default — the strategy passes a
    request only when caption embedding is enabled (env ``CIVICCAST_EGRESS_EMBED_CAPTIONS``),
    so the default graph stays byte-identical to today's."""

    mode: Literal["live", "sidecar"] = "live"
    sidecar_path: str | None = None


def caption_embed_leg(request: CaptionEmbedRequest) -> CaptionEmbedLeg:
    """Build the ``CaptionEmbedLeg`` for a request (sidecar needs a path)."""
    if request.mode == "sidecar":
        if not request.sidecar_path:
            raise ValueError("sidecar caption embed requires sidecar_path")
        return caption_embed_leg_from_sidecar(request.sidecar_path)
    return caption_embed_leg_live()


def _secondary_audio_source_chain(source_uri: str) -> tuple[ElementSpec, ...]:
    """``source_uri`` → (source element, decodebin) producing raw audio for a SAP track.

    A file path / ``file://`` URI is a ``filesrc``; a live URI maps to its scheme's
    source element (the same mapping the program live leg uses)."""
    parsed = urlsplit(source_uri)
    scheme = parsed.scheme.lower()
    mapping = _LIVE_SOURCE_BY_SCHEME.get(scheme)
    if mapping is not None:
        factory, prop = mapping
        src = ElementSpec(factory, props={prop: source_uri})
    else:
        location = parsed.path if scheme == "file" else source_uri
        src = ElementSpec("filesrc", props={"location": location})
    return (src, ElementSpec("decodebin"))


def secondary_audio_leg_from_track(
    track: AudioProgramTrack, profile: CanonicalProfile
) -> SecondaryAudioLeg:
    """Map a non-primary AudioProgramTrack to a gst secondary audio leg (a new PID)."""
    if not track.source_uri:
        raise ValueError(f"secondary audio track {track.track_id!r} requires a source_uri")
    return SecondaryAudioLeg(
        label=track.label,
        language=track.language,
        kind=track.kind,
        source=_secondary_audio_source_chain(track.source_uri),
        encoder=audio_encode_specs(
            codec=gst_audio_encoder_name(profile.audio_codec),
            bitrate_kbps=profile.audio_bitrate_kbps,
            sample_rate=profile.audio_sample_rate,
        ),
    )


# S15 graphics-overlay operator control: the lower-third banner's fixed height in
# output pixels (matches graphics_overlay.station_bug_and_lower_third_leg's default).
GRAPHICS_OVERLAY_LOWER_THIRD_HEIGHT = 60


# R3 banner-PNG cleanup: glob for exactly the per-call unique filename this
# module renders below (``<name>.<uuid4-hex>.png``). Shared by
# ``sweep_stale_lower_third_banners`` here and mirrored (as a compiled regex,
# same pattern) by ``engine.py``'s swap/removal-time deletion -- the two never
# need to agree on more than the filename shape, since each guards its own
# lifecycle point.
_LOWER_THIRD_BANNER_GLOB = "graphics-overlay-lower-third.*.png"


def sweep_stale_lower_third_banners(render_dir: Path, *, keep: Path | None) -> None:
    """Delete leftover lower-third banner PNGs from earlier start()/reload()
    cycles in ``render_dir``, keeping only ``keep`` (this call's freshly
    rendered banner, or ``None`` to sweep everything when the overlay is off).

    Only ``graphics_overlay_leg_from_config``'s own ``start()`` caller uses this
    (``sweep_stale=True``) -- a fresh ``start()`` always launches a brand-new
    worker process, so any OLDER banner file in this channel's dir was written
    by a worker that has, by definition, already exited; nothing here can be
    live. A ``reload_content()`` call must NOT sweep: its freshly-rendered
    banner races the still-on-air OLD banner in a different (worker) process,
    and only that worker's own swap-commit (``engine.py``'s
    ``_delete_stale_overlay_png``) can prove the old one is off-air before
    deleting it.

    Best-effort per file: a lingering handle (a slow-to-exit previous worker on
    Windows) fails to unlink and is logged, never raised -- this must never
    block a channel from starting."""
    render_dir = Path(render_dir)
    if not render_dir.is_dir():
        return
    for candidate in render_dir.glob(_LOWER_THIRD_BANNER_GLOB):
        if keep is not None and candidate == keep:
            continue
        try:
            candidate.unlink()
        except OSError as exc:
            print(
                f"WARN: failed to sweep stale graphics-overlay banner PNG {candidate}: {exc!r}",
                flush=True,
            )


def graphics_overlay_leg_from_config(
    config: EgressConfig,
    *,
    render_dir: Path,
    sweep_stale: bool = False,
) -> GraphicsOverlayLeg | None:
    """Build the S15 graphics-overlay leg's lower-third layer from
    ``EgressConfig``'s operator-facing toggle (``graphics_overlay_enabled`` +
    ``graphics_overlay_lower_third_text``), or ``None`` when the toggle is off or
    the text is blank -- so an unconfigured channel's graph is byte-identical to
    before this field existed (matches the ``cg_overlay_image`` / caption-embed
    opt-in pattern elsewhere in this module).

    Renders a fresh banner PNG into ``render_dir`` on every call (the caller passes
    the channel's own work dir), so a channel that is STARTED or CONTENT-RELOADED
    after the operator saves new text picks up the current text. A ``start()`` (a
    fresh pipeline build) always shows it; a ``reload_content()`` on an already-live
    pipeline now re-applies it too, via ``GstPlayoutEngine.reload_graphics_overlay``
    -- the compositor gained a swap-by-layer-name path so a reload's rebuilt banner
    PNG replaces the on-screen one instead of being silently dropped (BLOCKER fix,
    2026-08-30 audit; see that method's docstring).

    ENG-005 (mirrored): the banner filename carries a per-call ``uuid4`` suffix, not
    a fixed name -- a crash-relaunch racing an in-flight reload (or two reloads in
    close succession) must never have one process read a banner PNG the other is
    still mid-write on the same path, which crashed the whole worker at startup on
    a partial-PNG decode failure (MAJOR fix, 2026-08-30 audit).

    R3 (2026-08-31): the per-uuid filename above fixed the partial-read crash but
    left nothing to delete the OLD ones -- a 24/7 station accumulated one PNG per
    start()/content-reload forever, unbounded, on the volume that also holds
    recordings/HLS/the DB. Two independent cleanup points close that: a live
    pipeline's OLD banner is deleted by ``GstPlayoutEngine`` itself the moment a
    reload's NEW layer commits (provably off-air by then -- see
    ``_delete_stale_overlay_png``); and ``sweep_stale=True`` here sweeps any leftover
    banner this channel's dir accumulated from a PREVIOUS (now-exited) worker
    process, keeping only the one this call just rendered.

    Only the lower-third banner is wired here. ``station_bug_and_lower_third_leg``
    (the same PR's station-bug/logo layer) requires a ``logo_path``, and there is no
    operator-facing station-logo config surface yet -- that layer is out of scope
    for this slice.
    """
    render_dir_path = Path(render_dir)
    if not config.graphics_overlay_enabled or not config.graphics_overlay_lower_third_text.strip():
        if sweep_stale:
            sweep_stale_lower_third_banners(render_dir_path, keep=None)
        return None
    text = config.graphics_overlay_lower_third_text.strip()
    profile = config.canonical_profile
    render_dir_path.mkdir(parents=True, exist_ok=True)
    # ENG-005 (mirrored from strategy.reload_content's reload-graph filename): a
    # unique per-call filename so a concurrent build (a crash-relaunch racing a
    # reload) can never read a partially-written PNG on a clobbered fixed path.
    banner_path = render_dir_path / f"graphics-overlay-lower-third.{uuid.uuid4().hex}.png"
    render_lower_third_png(
        banner_path,
        text,
        canvas_width=profile.width,
        banner_height=GRAPHICS_OVERLAY_LOWER_THIRD_HEIGHT,
    )
    if sweep_stale:
        sweep_stale_lower_third_banners(render_dir_path, keep=banner_path)
    return GraphicsOverlayLeg(
        layers=(
            GraphicsOverlayLayer(
                name="lower_third",
                image_path=str(banner_path),
                xpos=0,
                ypos=profile.height - GRAPHICS_OVERLAY_LOWER_THIRD_HEIGHT,
                width=profile.width,
                height=GRAPHICS_OVERLAY_LOWER_THIRD_HEIGHT,
                alpha=1.0,
            ),
        )
    )


def graph_from_config(
    config: EgressConfig,
    source_plan: EgressSourcePlan,
    resolve_secret: SecretResolver | None = None,
    *,
    caption_embed: CaptionEmbedRequest | None = None,
    audio_tracks: list[AudioProgramTrack] | None = None,
    encoder_override: str | None = None,
    cg_overlay_image: Path | None = None,
    graphics_overlay: GraphicsOverlayLeg | None = None,
) -> PlayoutGraph:
    """Assemble a PlayoutGraph for one channel (design D-S1-6, Option A).

    PROGRAM = a gapless playlist leg of the active plan's segments — each segment is
    a ``filesrc`` (pre-conformed file) or a live source element (``kind='live'`` → the
    scheme's source, e.g. ``srtsrc``/``udpsrc``), then ``decodebin`` etc. A live plan
    is played by the engine like any program — at start, or applied seamlessly via a
    content-reload takeover (D-S1-6). SLATE = a black background with the configured
    slate message overlaid. Encoder + TS sinks come from the channel's ``EgressConfig``.
    The dedicated always-hot ``live`` selector role + the operator live-cut control
    surface are S16 (Production/Control Room, an optional later tier).

    D45 fix (2026-09-05): each segment becomes its OWN decoder sub-chain, all
    built and set to PLAYING together (``engine._build_playlist`` /
    ``GstPlayoutEngine`` start), so the segment count IS the pipeline's
    shape. Real-hardware soak evidence measured the cost of an oversized
    plan directly: ~60 segments (a plan sized to
    ``source_plan.PLAN_MIN_SECONDS`` before D45) produced ~1200 avdec_h264
    threads (its default max-threads=0 spins up ~20 per sub-chain) and
    ~3.5 GB on one worker, with the worker relaunching roughly every 30s
    (no TS output landed inside the engine's 10s stall watchdog).
    ``source_plan.build_source_plan_from_schedule`` is fixed at its own
    layer (segment count bounded by ``max_segments``, 8 by default), but
    this cap is defense-in-depth against any caller — present or future —
    that hands this function a plan with more segments than one pipeline can
    safely decode.
    """
    profile = config.canonical_profile
    common_caps = (
        f"video/x-raw,width={profile.width},height={profile.height},framerate={profile.fps}/1"
    )
    common_audio_caps = (
        f"audio/x-raw,rate={profile.audio_sample_rate},channels={profile.audio_channels}"
    )
    program_segments = source_plan.segments
    if len(program_segments) > MAX_PLAYLIST_SUBCHAINS:
        _LOG.warning(
            "Source plan for channel %s carries %d segments, above the "
            "%d-subchain playlist cap; building only the first %d. Each "
            "segment is its own decoder sub-chain built into one pipeline "
            "(see graph_from_config's D45 docstring) -- a plan this large "
            "would spawn thousands of decoder threads on start.",
            config.channel_id,
            len(program_segments),
            MAX_PLAYLIST_SUBCHAINS,
            MAX_PLAYLIST_SUBCHAINS,
        )
        program_segments = program_segments[:MAX_PLAYLIST_SUBCHAINS]
    program = PlaylistLeg(
        label="program",
        subchains=tuple(
            (
                source_first_element(segment),  # filesrc, or a live source by URI scheme
                ElementSpec("decodebin"),
                ElementSpec("videoconvert"),
                ElementSpec("videoscale"),
                ElementSpec("videorate"),
                ElementSpec("capsfilter", props={"caps": common_caps}),
            )
            for segment in program_segments
        ),
        audio_tail=(
            ElementSpec("audioconvert"),
            ElementSpec("audioresample"),
            ElementSpec("capsfilter", props={"caps": common_audio_caps}),
        ),
    )
    # Slate: a solid background using only the base plugin set. The slate MESSAGE
    # (config.slate_message) is rendered as an image via the S6 CG path in a later
    # slice (design D-S1-7) — `textoverlay` (pango) is NOT in stock Ubuntu 24.04
    # gstreamer1.0-plugins-base, so the base slate must not depend on it.
    slate = SourceLeg(
        label="slate",
        elements=(
            ElementSpec("videotestsrc", props={"is-live": True, "pattern": 2}),  # 2 = black
            ElementSpec("capsfilter", props={"caps": common_caps}),
        ),
        audio=(
            ElementSpec("audiotestsrc", props={"is-live": True, "wave": 4}),  # 4 = silence
            ElementSpec("capsfilter", props={"caps": common_audio_caps}),
        ),
    )
    # A cable headend (udp-ts sink) wants constant-bitrate video for clean QAM
    # modulation and mid-stream tune-in; enable HRD-CBR when a udp-ts sink exists.
    headend_cbr = any(sink.kind == "udp-ts" for sink in config.sinks)
    encoder_chain = encode_chain_from_profile(
        profile, cbr=headend_cbr, encoder_override=encoder_override
    )
    if cg_overlay_image is not None:
        # S15 §5 CG-lite: composite the pre-rendered board raster over the output
        # half, before encoding — the caller (strategy) has already probed that
        # gdkpixbufoverlay is registered. Live-video-in-zone (DC-CG1) composits at
        # the LPM-era engine milestone — S15 §5.
        encoder_chain = (
            ElementSpec(
                "gdkpixbufoverlay",
                name="cg_board_overlay",
                props={"location": str(cg_overlay_image)},
            ),
            *encoder_chain,
        )
    return PlayoutGraph(
        sources=(program, slate),
        encoder=encoder_chain,
        audio_encoder=audio_encode_specs(
            codec=gst_audio_encoder_name(profile.audio_codec),
            bitrate_kbps=profile.audio_bitrate_kbps,
            sample_rate=profile.audio_sample_rate,
        ),
        mux=ElementSpec("mpegtsmux", name="mux"),
        sinks=sink_branches_from_config(config, resolve_secret),
        # S11a: CEA-708 embed leg, only when the channel opts in (else byte-identical).
        captions=caption_embed_leg(caption_embed) if caption_embed is not None else None,
        # S15 graphics-overlay operator control: None (default) preserves today's
        # behavior byte-identically -- see graphics_overlay_leg_from_config.
        graphics_overlay=graphics_overlay,
        # S11 gap 9: secondary audio PIDs (SAP / descriptive) — non-primary tracks with a
        # source. Empty = single audio PID (byte-identical to today).
        secondary_audio=tuple(
            secondary_audio_leg_from_track(track, profile)
            for track in (audio_tracks or [])
            if track.kind != "primary" and track.source_uri
        ),
    )
