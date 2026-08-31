# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live GStreamer playout engine (S15). Imports ``gi``, which native
Windows supplies through the pinned ``gstreamer-*`` PyPI wheels.

Builds the persistent pipeline from a gi-free ``PlayoutGraph`` via element factories
+ ``set_property`` (never string ``parse_launch`` — audit FINDING-002), hot-swaps the
active source through a pluggable ``SwapController`` (default ``InputSelectorSwap`` —
the Stage-0-validated mechanism), and tears down time-bounded so playout can never
hang (the 6h Stage-0 teardown deadlock). The teardown wait is finite; a dedicated
worker process (slice 3) calls ``stop(force_exit_on_hang=True)`` as the hard backstop.
"""

from __future__ import annotations

import base64
import contextlib
import os
import signal
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

_CPU_DECODE_FEATURE_RANK = ",".join(
    (
        "nvh264dec:0",
        "nvh265dec:0",
        "nvav1dec:0",
        "cudah264dec:0",
        "cudah265dec:0",
        "vaapih264dec:0",
        "vaapih265dec:0",
        "vah264dec:0",
        "vah265dec:0",
        "d3d11h264dec:0",
        "d3d11h265dec:0",
    )
)


def _prefer_cpu_decoders_by_default() -> None:
    """Keep decodebin output in system memory unless an operator opts into GPU decode."""
    if os.environ.get("CIVICCAST_GST_ALLOW_HARDWARE_DECODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", _CPU_DECODE_FEATURE_RANK)


_prefer_cpu_decoders_by_default()

from civiccast.native.gstreamer_runtime import bootstrap_installed_gstreamer_runtime  # noqa: E402

bootstrap_installed_gstreamer_runtime()

import gi  # type: ignore[import-not-found] # noqa: E402

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # type: ignore[import-not-found] # noqa: E402

try:  # package context (Windows can't reach here — gi import fails first)
    from civiccast.egress.gst.audio_tap import RollingWavSegmentWriter
    from civiccast.egress.gst.graph import (
        AudioTapLeg,
        CaptionEmbedLeg,
        ElementSpec,
        GraphicsOverlayLeg,
        PlaylistLeg,
        PlayoutGraph,
        SecondaryAudioLeg,
        SourceLeg,
        coerce_serialized_property,
        graph_from_json,
    )
except (
    ImportError
):  # standalone context: the POSIX/Windows GStreamer test adds the gst dir to sys.path
    from audio_tap import RollingWavSegmentWriter  # type: ignore[import-not-found,no-redef]
    from graph import (  # type: ignore[import-not-found,no-redef]
        AudioTapLeg,
        CaptionEmbedLeg,
        ElementSpec,
        GraphicsOverlayLeg,
        PlaylistLeg,
        PlayoutGraph,
        SecondaryAudioLeg,
        SourceLeg,
        coerce_serialized_property,
        graph_from_json,
    )

try:
    from civiccast.egress.gst.control import (
        LIVE_CAPTION_LEAD_MS,
        align_live_caption_pts_ms,
        caption_gap_window_ms,
        install_unix_signal_handlers,
        parse_control_line,
    )
except ImportError:
    from control import (  # type: ignore[import-not-found,no-redef]
        LIVE_CAPTION_LEAD_MS,
        align_live_caption_pts_ms,
        caption_gap_window_ms,
        install_unix_signal_handlers,
        parse_control_line,
    )


class SwapController:
    """Pluggable hot-swap mechanism. Lets GstInterpipe drop in later (S15 §9)."""

    name = "abstract"

    def bind(self, engine: GstPlayoutEngine) -> None:
        raise NotImplementedError

    def swap_to(self, index: int) -> None:
        raise NotImplementedError


class InputSelectorSwap(SwapController):
    """Stage-0-validated swap: set the input-selector's ``active-pad``."""

    name = "input-selector"

    def __init__(self) -> None:
        self._selector: Gst.Element | None = None
        self._pads: list[Gst.Pad] = []
        self._audio_selector: Gst.Element | None = None
        self._audio_pads: list[Gst.Pad] = []

    def bind(self, engine: GstPlayoutEngine) -> None:
        self._selector = engine.selector
        self._pads = engine.selector_sink_pads
        self._audio_selector = engine.audio_selector
        self._audio_pads = engine.audio_sink_pads

    def swap_to(self, index: int) -> None:
        if self._selector is None:
            raise RuntimeError("swap controller not bound to an engine")
        if not 0 <= index < len(self._pads):
            # Clear error instead of a bare IndexError (e.g. swap to a 'live' leg that
            # the 2-leg program+slate graph doesn't have — ENG-004 / TEST-005).
            raise IndexError(f"source index {index} out of range ({len(self._pads)} legs built)")
        self._selector.set_property("active-pad", self._pads[index])
        if self._audio_selector is not None and index < len(self._audio_pads):
            # swap audio atomically with video (seconds-granularity, same thread)
            self._audio_selector.set_property("active-pad", self._audio_pads[index])


class GstPlayoutEngine:
    """One persistent playout pipeline built from a ``PlayoutGraph``."""

    def __init__(
        self,
        graph: PlayoutGraph,
        *,
        swap: SwapController | None = None,
        teardown_timeout_s: float = 5.0,
        reload_timeout_s: float = 10.0,
        stall_timeout_s: float = 10.0,
    ) -> None:
        _prefer_cpu_decoders_by_default()
        Gst.init([])
        self.graph = graph
        self.swap = swap or InputSelectorSwap()
        self.teardown_timeout_s = teardown_timeout_s
        self.reload_timeout_s = reload_timeout_s
        # S9-5: if output (TS buffers past the mux) does not advance for this long while
        # on-air, the pipeline has silently stalled — quit so the daemon restarts the
        # worker to a known state (a live source that freezes without posting an error).
        self.stall_timeout_s = stall_timeout_s
        self.pipeline = Gst.Pipeline.new("civiccast-playout")
        self.mux: Gst.Element | None = None
        self.selector: Gst.Element | None = None
        # S11a: the live caption appsrc (set when the graph has a live caption embed
        # leg) the daemon pushes timed-text cues into via the ``caption`` control command.
        self.caption_appsrc: Gst.Element | None = None
        self._caption_stream_position_ms = 0
        self.selector_sink_pads: list[Gst.Pad] = []
        self.audio_selector: Gst.Element | None = None
        self.audio_sink_pads: list[Gst.Pad] = []
        self.audio_tap_appsink: Gst.Element | None = None
        self.audio_tap_writer: RollingWavSegmentWriter | None = None
        self._error: object | None = None
        self._loop: GLib.MainLoop | None = None
        # S9-5 stall watchdog state (output-buffer progress past the mux).
        self._output_buffers = 0
        self._stall_last_count = 0
        self._stall_last_advance_t = 0.0
        # Per-leg element lists (index-aligned with ``selector_sink_pads``) so a
        # content-reload can dispose the leg it replaces. ``_collecting`` captures the
        # elements built for the current leg; ``_pending_reload`` holds the in-flight
        # reload (None = none settling) so it can be committed, aborted, or superseded.
        self._source_leg_elements: list[list[Gst.Element]] = []
        self._collecting: list[Gst.Element] | None = None
        self._pending_reload: dict[str, Any] | None = None
        # S11 gap 9: language tag events for secondary audio must be pushed AFTER the
        # pipeline reaches PLAYING (push_event at NULL state doesn't flow into mpegtsmux).
        # Stored here during _build(); flushed by _flush_lang_tags() post-_await_playing().
        self._pending_lang_tags: list[tuple[Gst.Element, str]] = []
        self._build()
        self.swap.bind(self)

    # -- construction (element factories + set_property; no parse_launch) --------

    def _make(self, spec: ElementSpec) -> Gst.Element:
        element = Gst.ElementFactory.make(spec.factory, spec.name)
        if element is None:
            raise RuntimeError(f"GStreamer element factory missing: {spec.factory!r}")
        for key, value in spec.props.items():
            element.set_property(
                key,
                coerce_serialized_property(
                    key=key,
                    value=value,
                    caps_from_string=Gst.Caps.from_string,
                ),
            )
        self.pipeline.add(element)
        if self._collecting is not None:
            # Building a source leg — record the element so the leg can be torn down
            # as a unit on a later content-reload.
            self._collecting.append(element)
        return element

    @staticmethod
    def _link(upstream: Gst.Element, downstream: Gst.Element) -> None:
        if not upstream.link(downstream):
            raise RuntimeError(f"failed to link {upstream.get_name()} -> {downstream.get_name()}")

    _DECODERS = ("decodebin", "uridecodebin", "decodebin3")

    def _link_dynamic_video(self, decoder: Gst.Element, downstream: Gst.Element) -> None:
        """Link a decoder's video src pad to ``downstream`` once it appears.

        decodebin exposes pads dynamically (FINDING-203); the audio handler is
        registered separately. A failed link is surfaced (audit M3) rather than
        silently dropped, so a black channel leaves a diagnostic."""
        sink = downstream.get_static_pad("sink")

        def _on_pad_added(_decoder: Gst.Element, pad: Gst.Pad) -> None:
            if sink.is_linked():
                return
            caps = pad.get_current_caps() or pad.query_caps(None)
            if (
                caps is not None
                and caps.to_string().startswith("video/")
                and pad.link(sink) != Gst.PadLinkReturn.OK
            ):
                print(
                    f"WARN: failed to link decoded video pad into {downstream.get_name()}",
                    flush=True,
                )

        decoder.connect("pad-added", _on_pad_added)

    def _link_dynamic_audio(self, decoder: Gst.Element, downstream: Gst.Element) -> None:
        """Link a decoder's audio src pad to ``downstream`` once it appears.

        Registered alongside the video handler on the same decodebin; each handler
        links only its own media type."""
        sink = downstream.get_static_pad("sink")

        def _on_pad_added(_decoder: Gst.Element, pad: Gst.Pad) -> None:
            if sink.is_linked():
                return
            caps = pad.get_current_caps() or pad.query_caps(None)
            if (
                caps is not None
                and caps.to_string().startswith("audio/")
                and pad.link(sink) != Gst.PadLinkReturn.OK
            ):
                print(
                    f"WARN: failed to link decoded audio pad into {downstream.get_name()}",
                    flush=True,
                )

        decoder.connect("pad-added", _on_pad_added)

    def _build_chain(self, specs: tuple[ElementSpec, ...]) -> tuple[Gst.Element, Gst.Element]:
        """Build a linear chain (decodebin links dynamically). Returns (first, last)."""
        elements = [self._make(spec) for spec in specs]
        for upstream, downstream in pairwise(elements):
            if upstream.get_factory().get_name() in self._DECODERS:
                self._link_dynamic_video(upstream, downstream)
            else:
                self._link(upstream, downstream)
        return elements[0], elements[-1]

    def _build_playlist(self, leg: PlaylistLeg) -> tuple[Gst.Element, Gst.Element | None]:
        """Gapless playlist leg: a video ``concat`` (and, when ``audio_tail`` is set,
        a parallel audio ``concat`` fed by each clip's decodebin audio pad) sequence
        the sub-chains. Returns ``(video_concat, audio_concat | None)``."""
        vconcat = self._make(ElementSpec("concat", f"vconcat_{leg.label}"))
        aconcat = (
            self._make(ElementSpec("concat", f"aconcat_{leg.label}")) if leg.audio_tail else None
        )
        for subchain in leg.subchains:
            elements = [self._make(spec) for spec in subchain]
            decoder: Gst.Element | None = None
            for upstream, downstream in pairwise(elements):
                if upstream.get_factory().get_name() in self._DECODERS:
                    decoder = upstream
                    self._link_dynamic_video(upstream, downstream)
                else:
                    self._link(upstream, downstream)
            vsink = vconcat.request_pad_simple("sink_%u")
            if (
                vsink is None
                or elements[-1].get_static_pad("src").link(vsink) != Gst.PadLinkReturn.OK
            ):
                raise RuntimeError(f"failed to link video sub-chain into {vconcat.get_name()}")
            if aconcat is not None and decoder is not None:
                atail = [self._make(spec) for spec in leg.audio_tail]
                for upstream, downstream in pairwise(atail):
                    self._link(upstream, downstream)
                self._link_dynamic_audio(decoder, atail[0])
                asink = aconcat.request_pad_simple("sink_%u")
                if (
                    asink is None
                    or atail[-1].get_static_pad("src").link(asink) != Gst.PadLinkReturn.OK
                ):
                    raise RuntimeError(f"failed to link audio sub-chain into {aconcat.get_name()}")
        return vconcat, aconcat

    def _build_caption_embed(self, leg: CaptionEmbedLeg, video_prev: Gst.Element) -> Gst.Element:
        """S11a: insert the CEA-708 caption embed leg on the output half.

        ``video_prev`` is the encoder chain's tail (h264parse, ALREADY-ENCODED H.264).
        Per the documented gst-plugins-bad pipeline, the encoded video feeds
        ``cccombiner``'s always 'sink' (video) pad while the caption source chain
        (timed text → tttocea608 → ccconverter → cc_data) feeds cccombiner's REQUEST
        'caption' pad; cccombiner attaches a caption meta and ``h264ccinserter``
        serializes it as A/53 SEI. Returns the inserter chain's tail (its src feeds the
        mux). A live ``appsrc`` source is captured into ``self.caption_appsrc`` so the
        daemon can push cues. The live SEI presence is POSIX/LPM-validated."""
        combiner = self._make(leg.combiner)
        self._link(video_prev, combiner)  # encoded H.264 → cccombiner 'sink' (video) pad

        # Caption text chain → cccombiner's request 'caption' pad.
        cap_first, cap_last = self._build_chain(leg.caption_source)
        if cap_first.get_factory().get_name() == "appsrc":
            self.caption_appsrc = cap_first  # daemon pushes cues here (push_caption_cue)
        caption_pad = combiner.request_pad_simple("caption")
        if (
            caption_pad is None
            or cap_last.get_static_pad("src").link(caption_pad) != Gst.PadLinkReturn.OK
        ):
            raise RuntimeError("failed to link caption source into cccombiner 'caption' pad")

        # cccombiner → h264ccinserter (→ h264parse) → [mux, linked by the caller].
        prev = combiner
        for spec in leg.inserter_chain:
            element = self._make(spec)
            self._link(prev, element)
            prev = element
        return prev

    def push_caption_cue(self, *, text: str, pts_seconds: float, duration_seconds: float) -> bool:
        """Push one timed-text caption cue into the live caption appsrc (S11a).

        Returns False if no live caption source is built (no-op). The daemon calls this
        via the ``caption`` control command to feed continuous captions from the channel
        caption pipeline; the buffer carries PTS+duration so cccombiner schedules the
        cue against the video. Live behavior is POSIX/LPM-validated."""
        appsrc = self.caption_appsrc
        if appsrc is None:
            return False
        data = text.encode("utf-8")
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        running_time_ms = self._pipeline_running_time_ms()
        aligned_pts_ms = align_live_caption_pts_ms(
            requested_pts_ms=max(0, round(pts_seconds * 1000)),
            running_time_ms=running_time_ms,
            stream_position_ms=self._caption_stream_position_ms,
        )
        duration_ms = max(0, round(duration_seconds * 1000))
        buf.pts = aligned_pts_ms * Gst.MSECOND
        buf.duration = duration_ms * Gst.MSECOND
        pushed = bool(appsrc.emit("push-buffer", buf) == Gst.FlowReturn.OK)
        if pushed:
            self._caption_stream_position_ms = max(
                self._caption_stream_position_ms,
                aligned_pts_ms + duration_ms,
            )
        return pushed

    def _pipeline_running_time_ms(self) -> int:
        clock = self.pipeline.get_clock()
        if clock is None:
            return 0
        base_time = int(self.pipeline.get_base_time())
        clock_time = int(clock.get_time())
        if clock_time < base_time:
            return 0
        return max(0, round((clock_time - base_time) / int(Gst.MSECOND)))

    def _prime_live_caption_stream(self) -> None:
        """Prime the sparse caption pad with a GAP so PLAYING cannot deadlock."""

        appsrc = self.caption_appsrc
        if appsrc is None:
            return
        self._caption_stream_position_ms = LIVE_CAPTION_LEAD_MS
        if not appsrc.send_event(
            Gst.Event.new_gap(
                0,
                LIVE_CAPTION_LEAD_MS * Gst.MSECOND,
            )
        ):
            raise RuntimeError("failed to prime the live caption stream")

    def _advance_live_caption_gap(self) -> bool:
        """Keep sparse caption time moving when no caption buffer is present."""

        appsrc = self.caption_appsrc
        if appsrc is None:
            return False
        window = caption_gap_window_ms(
            stream_position_ms=self._caption_stream_position_ms,
            running_time_ms=self._pipeline_running_time_ms(),
        )
        if window is None:
            return True
        start_ms, duration_ms = window
        if not appsrc.send_event(
            Gst.Event.new_gap(
                start_ms * Gst.MSECOND,
                duration_ms * Gst.MSECOND,
            )
        ):
            self._error = ("caption-gap", "failed to advance live caption stream")
            if self._loop is not None:
                self._loop.quit()
            return False
        self._caption_stream_position_ms = start_ms + duration_ms
        return True

    def _arm_live_caption_gap_heartbeat(self) -> None:
        if self.caption_appsrc is not None:
            GLib.timeout_add(100, self._advance_live_caption_gap)

    def _build_graphics_overlay(
        self, leg: GraphicsOverlayLeg, video_prev: Gst.Element
    ) -> Gst.Element:
        """S15 graphics-overlay leg: composite the station bug/logo (and any other
        image layer, e.g. a pre-rendered lower-third text banner) over the program
        video on the output half, between the selector and the encoder chain.

        ``video_prev`` is the selector (or whatever upstream element the caller has
        built so far). The base program video and every overlay layer are uploaded to
        D3D11 GPU memory (``d3d11upload``) before their compositor request pad — this
        product's bundled runtime ships no plain ``compositor``/``videomixer``, only
        the D3D11 family (confirmed by a real ``gst-inspect`` enumeration; see
        ``GraphicsOverlayLeg``'s docstring) — and the composited result is downloaded
        back to system memory (``d3d11download``) so the (system-memory) encoder chain
        is unaffected. Returns the tail element (``videoconvert`` after the download)
        the caller links into its encoder chain."""
        compositor = self._make(leg.compositor)

        base_upload = self._make(ElementSpec("d3d11upload", name="graphics_overlay_base_upload"))
        self._link(video_prev, base_upload)
        base_pad = compositor.request_pad_simple("sink_%u")
        if (
            base_pad is None
            or base_upload.get_static_pad("src").link(base_pad) != Gst.PadLinkReturn.OK
        ):
            raise RuntimeError("failed to link program video into the graphics-overlay compositor")

        for layer in leg.layers:
            chain = (
                ElementSpec("filesrc", props={"location": layer.image_path}),
                ElementSpec("decodebin"),
                ElementSpec("videoconvert"),
                ElementSpec("d3d11upload", name=f"graphics_overlay_upload_{layer.name}"),
            )
            _first, layer_tail = self._build_chain(chain)
            layer_pad = compositor.request_pad_simple("sink_%u")
            if (
                layer_pad is None
                or layer_tail.get_static_pad("src").link(layer_pad) != Gst.PadLinkReturn.OK
            ):
                raise RuntimeError(
                    f"failed to link graphics-overlay layer {layer.name!r} into the compositor"
                )
            layer_pad.set_property("xpos", layer.xpos)
            layer_pad.set_property("ypos", layer.ypos)
            if layer.width:
                layer_pad.set_property("width", layer.width)
            if layer.height:
                layer_pad.set_property("height", layer.height)
            layer_pad.set_property("alpha", layer.alpha)
            # A still-image filesrc/decodebin chain EOSes its compositor pad after its
            # single buffer (the bundled runtime ships no `imagefreeze`); repeat-after-eos
            # holds that last buffer on screen instead of dropping the pad — proven live
            # (see the S15 graphics-overlay pipeline proof test).
            layer_pad.set_property("repeat-after-eos", layer.repeat_after_eos)

        download = self._make(ElementSpec("d3d11download", name="graphics_overlay_download"))
        self._link(compositor, download)
        post_convert = self._make(ElementSpec("videoconvert", name="graphics_overlay_post_convert"))
        self._link(download, post_convert)
        return post_convert

    def _build_secondary_audio(self, leg: SecondaryAudioLeg, mux: Gst.Element) -> None:
        """S11 gap 9: build one secondary audio program and mux it as an extra audio PID.

        ``leg.source`` produces raw audio (its tail is typically a ``decodebin`` whose
        audio pad appears dynamically); ``leg.encoder`` is the AAC chain. The encoder
        tail links to the mux, which assigns a new audio PID, and the stream is tagged
        with ``leg.language`` for the PID's ISO-639 language descriptor. Live PID
        assignment + descriptor are POSIX/LPM-validated."""
        src_elements = [self._make(spec) for spec in leg.source]
        for upstream, downstream in pairwise(src_elements):
            if upstream.get_factory().get_name() not in self._DECODERS:
                self._link(upstream, downstream)
        enc_elements = [self._make(spec) for spec in leg.encoder]
        for upstream, downstream in pairwise(enc_elements):
            self._link(upstream, downstream)
        # source tail → encoder head: dynamic when the tail is a decodebin (audio pad
        # arrives later), else a static link.
        src_tail = src_elements[-1]
        if src_tail.get_factory().get_name() in self._DECODERS:
            self._link_dynamic_audio(src_tail, enc_elements[0])
        else:
            self._link(src_tail, enc_elements[0])
        self._link(enc_elements[-1], mux)  # encoder tail → mux (requests a new audio PID)
        self._pending_lang_tags.append((enc_elements[-1], leg.language))

    def _build_audio_tap(self, source: Gst.Element, leg: AudioTapLeg) -> None:
        """Fork selected raw program audio into the atomic rolling WAV writer."""

        writer = RollingWavSegmentWriter(
            leg.tap_dir,
            segment_seconds=leg.segment_seconds,
        )
        specs = (
            ElementSpec("queue", "caption_audio_tap_queue"),
            ElementSpec("audioconvert", "caption_audio_tap_convert"),
            ElementSpec("audioresample", "caption_audio_tap_resample"),
            ElementSpec(
                "capsfilter",
                "caption_audio_tap_caps",
                props={
                    "caps": ("audio/x-raw,format=S16LE,rate=16000,channels=1,layout=interleaved")
                },
            ),
            ElementSpec(
                "appsink",
                "caption_audio_tap_sink",
                props={
                    "emit-signals": True,
                    "sync": False,
                    "max-buffers": 32,
                    "drop": False,
                },
            ),
        )
        elements = [self._make(spec) for spec in specs]
        self._link(source, elements[0])
        for upstream, downstream in pairwise(elements):
            self._link(upstream, downstream)
        appsink = elements[-1]

        def _on_new_sample(sink: Gst.Element) -> Gst.FlowReturn:
            sample = sink.emit("pull-sample")
            if sample is None:
                return Gst.FlowReturn.ERROR
            buffer = sample.get_buffer()
            if buffer is None:
                return Gst.FlowReturn.ERROR
            mapped, map_info = buffer.map(Gst.MapFlags.READ)
            if not mapped:
                return Gst.FlowReturn.ERROR
            try:
                writer.write_pcm_s16le(map_info.data)
            except Exception as exc:
                self._error = f"caption audio tap failed: {exc}"
                print(f"ERROR: {self._error}", flush=True)
                if self._loop is not None:
                    GLib.idle_add(self._loop.quit)
                return Gst.FlowReturn.ERROR
            finally:
                buffer.unmap(map_info)
            return Gst.FlowReturn.OK

        appsink.connect("new-sample", _on_new_sample)
        self.audio_tap_appsink = appsink
        self.audio_tap_writer = writer

    @staticmethod
    def _tag_audio_language(element: Gst.Element, language: str) -> None:
        """Best-effort: stamp the audio stream's ISO-639 language so mpegtsmux writes a
        language descriptor on the PID. Best-effort by design — a tagging hiccup must
        never wedge playout; the live descriptor is POSIX/LPM-validated."""
        try:
            src = element.get_static_pad("src")
            if src is None:
                return
            tags = Gst.TagList.new_empty()
            tags.add_value(Gst.TagMergeMode.REPLACE, "language-code", language)
            src.push_event(Gst.Event.new_tag(tags))  # TAG is a downstream event; push, not send
        except Exception as exc:  # a tagging failure must not kill the channel
            print(f"WARN: secondary audio language tag failed ({language!r}): {exc!r}", flush=True)

    def _flush_lang_tags(self) -> None:
        """Push deferred ISO-639 language TAG events after the pipeline reaches PLAYING.
        Must be called post-_await_playing() so push_event flows into mpegtsmux."""
        for element, language in self._pending_lang_tags:
            self._tag_audio_language(element, language)
        self._pending_lang_tags.clear()

    def _build(self) -> None:
        # Output half (stays PLAYING): selector → encode chain → mux → sink(s).
        self.selector = self._make(ElementSpec("input-selector", "sel"))
        prev = self.selector
        if self.graph.graphics_overlay is not None:
            # S15 graphics-overlay leg: station bug/logo (+ lower-third banner) burned
            # in on the output half, before encode, so it survives every source
            # swap/reload untouched — same insertion point as the S15 §5 CG-lite
            # full-frame board raster in bridge.graph_from_config.
            prev = self._build_graphics_overlay(self.graph.graphics_overlay, prev)
        for spec in self.graph.encoder:
            element = self._make(spec)
            self._link(prev, element)
            prev = element
        mux = self._make(self.graph.mux)
        self.mux = mux  # S9-5: the stall watchdog counts buffers on the mux src pad
        if self.graph.captions is not None:
            # S11a: insert the CEA-708 embed leg between the encoder tail and the mux.
            prev = self._build_caption_embed(self.graph.captions, prev)
        self._link(prev, mux)

        if self.graph.audio_encoder:
            self.audio_selector = self._make(ElementSpec("input-selector", "asel"))
            audio_prev = self.audio_selector
            if self.graph.audio_tap is not None:
                audio_tee = self._make(ElementSpec("tee", "caption_audio_tap_tee"))
                self._link(audio_prev, audio_tee)
                self._build_audio_tap(audio_tee, self.graph.audio_tap)
                audio_prev = audio_tee
            for spec in self.graph.audio_encoder:
                element = self._make(spec)
                self._link(audio_prev, element)
                audio_prev = element
            self._link(audio_prev, mux)  # audio parser → mux (requests an audio sink pad)

        # S11 gap 9: each secondary audio program (SAP / descriptive) is its own
        # continuous source → AAC → an ADDITIONAL mux audio PID (the TV SAP button).
        for secondary in self.graph.secondary_audio:
            self._build_secondary_audio(secondary, mux)

        if len(self.graph.sinks) == 1:
            tail = mux
            for spec in self.graph.sinks[0]:
                element = self._make(spec)
                self._link(tail, element)
                tail = element
        else:
            tee = self._make(ElementSpec("tee", "t"))
            self._link(mux, tee)
            for branch in self.graph.sinks:
                tail = tee  # tee src pads are request pads; link() requests one
                for spec in branch:
                    element = self._make(spec)
                    self._link(tail, element)
                    tail = element

        # Source halves (hot-swappable): each leg → a video (and optional audio) pad.
        for leg in self.graph.sources:
            out_pad, audio_out_pad, elements = self._instantiate_source_leg(leg)
            self._source_leg_elements.append(elements)
            video_sink_pad, audio_sink_pad = self._link_leg_to_selectors(
                leg.label, out_pad, audio_out_pad
            )
            self.selector_sink_pads.append(video_sink_pad)
            if audio_sink_pad is not None:
                self.audio_sink_pads.append(audio_sink_pad)

        if self.selector_sink_pads:
            self.selector.set_property("active-pad", self.selector_sink_pads[0])

    def _instantiate_source_leg(
        self, leg: SourceLeg | PlaylistLeg
    ) -> tuple[Gst.Pad | None, Gst.Pad | None, list[Gst.Element]]:
        """Build one source leg's elements (collected so the leg can be disposed as a
        unit on a content-reload). Returns ``(video_src_pad, audio_src_pad, elements)``."""
        collected: list[Gst.Element] = []
        self._collecting = collected
        try:
            audio_out_pad = None
            if isinstance(leg, PlaylistLeg):
                video_concat, audio_concat = self._build_playlist(leg)
                out_pad = video_concat.get_static_pad("src")
                if audio_concat is not None:
                    audio_out_pad = audio_concat.get_static_pad("src")
            else:
                _first, video_out = self._build_chain(leg.elements)
                out_pad = video_out.get_static_pad("src")
                if leg.audio:
                    _audio_first, audio_out = self._build_chain(leg.audio)
                    audio_out_pad = audio_out.get_static_pad("src")
        finally:
            self._collecting = None
        return out_pad, audio_out_pad, collected

    def _link_leg_to_selectors(
        self, label: str, out_pad: Gst.Pad | None, audio_out_pad: Gst.Pad | None
    ) -> tuple[Gst.Pad, Gst.Pad | None]:
        """Request selector sink pad(s) and link this leg's src pad(s) into them.
        Returns ``(video_sink_pad, audio_sink_pad | None)``; raises on a link failure."""
        selector = self.selector
        if selector is None:
            raise RuntimeError("video selector was not built")
        sink_pad = selector.request_pad_simple("sink_%u")
        try:
            video_linked = (
                out_pad is not None
                and sink_pad is not None
                and out_pad.link(sink_pad) == Gst.PadLinkReturn.OK
            )
        except Exception as exc:  # gi may raise on a caps mismatch
            raise RuntimeError(
                f"failed to link source {label!r} into selector (caps mismatch?): {exc}"
            ) from exc
        if not video_linked:
            raise RuntimeError(f"failed to link source {label!r} into selector (caps mismatch?)")

        audio_sink_pad = None
        audio_selector = self.audio_selector
        if audio_selector is not None:
            # A/V index alignment (audit CRITICAL): when audio is enabled EVERY
            # leg must carry audio so video pad N and audio pad N swap together —
            # a mixed graph would desync the selectors (wrong audio over wrong
            # video, the issue-#56 class).
            if audio_out_pad is None:
                raise RuntimeError(f"audio is enabled but source {label!r} has no audio leg")
            audio_sink_pad = audio_selector.request_pad_simple("sink_%u")
            if audio_sink_pad is None or audio_out_pad.link(audio_sink_pad) != Gst.PadLinkReturn.OK:
                raise RuntimeError(f"failed to link audio for source {label!r}")
        return sink_pad, audio_sink_pad

    # -- runtime -----------------------------------------------------------------

    def _on_bus(self, _bus: Gst.Bus, message: Gst.Message) -> bool:
        if message.type == Gst.MessageType.ERROR:
            # ENG-009: an async error on the not-yet-committed reload leg (e.g. a live
            # source whose connection is refused) must NOT take the channel off air.
            # Abort the reload and keep the current program playing.
            if self._pending_reload is not None and self._belongs_to_pending_reload(message.src):
                err, _debug = message.parse_error()
                print(
                    f"CTRL reload aborted: new program errored before commit: {err}",
                    flush=True,
                )
                self._abort_pending_reload("error")
                return True
            self._error = message.parse_error()
            if self._loop is not None:
                self._loop.quit()
        elif message.type == Gst.MessageType.EOS:
            if self._loop is not None:
                self._loop.quit()
        return True

    # -- S9-5 pipeline supervision: stall watchdog --------------------------------

    def _install_output_counter(self) -> None:
        """Count TS output leaving the mux — the stall watchdog's progress signal.
        A swap/reload keeps the persistent output half PLAYING, so this advances
        through them; it only flatlines on a genuine output stall.

        CRITICAL: past mpegtsmux the data is pushed as ``GstBufferList`` (188-byte TS
        packets batched), NOT individual ``GstBuffer`` — a plain ``BUFFER`` probe never
        fires there and the watchdog would false-fire on perfectly healthy output. The
        mask MUST include ``BUFFER_LIST`` (proven: BUFFER-only counts 0 while the sink
        file grows; BUFFER|BUFFER_LIST counts 99/189/279 over the same window)."""
        if self.mux is None:
            return
        src = self.mux.get_static_pad("src")
        if src is None:
            return

        def _count(_pad: Gst.Pad, _info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
            # One increment per buffer-or-list is enough: the watchdog only needs to
            # see the count ADVANCE, not the exact packet tally.
            #
            # Threading contract: the mux src pad is fed by a single GStreamer streaming
            # thread, so this probe is the ONLY writer of _output_buffers; _check_stall
            # (the GLib main-loop thread) is a reader only. A single-writer int with a
            # plain read needs no lock — the reader may observe a value one behind, which
            # only ever delays a stall verdict by a tick, never causes a false stall.
            self._output_buffers += 1
            return Gst.PadProbeReturn.OK

        src.add_probe(Gst.PadProbeType.BUFFER | Gst.PadProbeType.BUFFER_LIST, _count)

    def _arm_stall_watchdog(self) -> None:
        if self.stall_timeout_s <= 0:
            return
        self._stall_last_count = self._output_buffers
        self._stall_last_advance_t = time.monotonic()
        GLib.timeout_add_seconds(1, self._check_stall)

    def _check_stall(self) -> bool:
        """Quit the run loop if output hasn't advanced for ``stall_timeout_s`` — the
        worker then exits non-zero and the daemon restarts it to a known state. A
        no-op while output is flowing (it resets the timer on every advance)."""
        now = time.monotonic()
        if self._output_buffers != self._stall_last_count:
            self._stall_last_count = self._output_buffers
            self._stall_last_advance_t = now
            return True  # output advancing — keep watching
        if now - self._stall_last_advance_t >= self.stall_timeout_s:
            print(
                f"CTRL stall: no output for {int(self.stall_timeout_s)}s — quitting for daemon restart",
                flush=True,
            )
            self._error = ("stall", "output stalled")  # → worker exits non-zero → restart
            if self._loop is not None:
                self._loop.quit()
            return False  # one-shot: stop the watchdog
        return True

    def _await_playing(self) -> None:
        """Bounded wait for the PLAYING transition so a wedged preroll can't hang the
        run loop before the time-bounded teardown could ever run (audit M1)."""
        result, _current, _pending = self.pipeline.get_state(
            int(self.teardown_timeout_s * Gst.SECOND)
        )
        if result not in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.NO_PREROLL):
            raise RuntimeError(
                f"pipeline did not reach PLAYING within {self.teardown_timeout_s}s "
                f"(get_state={result.value_nick})"
            )

    def run(self, *, swaps: int, interval_s: int) -> dict[str, Any]:
        """Start PLAYING, swap the active source ``swaps`` times every ``interval_s``
        seconds, then stop. Returns a result dict; never blocks indefinitely."""
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus)
        loop = GLib.MainLoop()  # before PLAYING so a startup bus ERROR isn't swallowed
        self._loop = loop
        self._prime_live_caption_stream()
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline failed to reach PLAYING")
        self._await_playing()
        self._arm_live_caption_gap_heartbeat()
        self._flush_lang_tags()  # push deferred secondary-audio ISO-639 descriptors
        state = {"n": 0, "cur": 0}
        nsrc = len(self.selector_sink_pads)

        def _tick() -> bool:
            if state["n"] >= swaps:
                loop.quit()
                return False
            state["cur"] = (state["cur"] + 1) % nsrc
            self.swap.swap_to(state["cur"])
            state["n"] += 1
            return True

        GLib.timeout_add_seconds(interval_s, _tick)
        GLib.timeout_add_seconds(interval_s * (swaps + 4), lambda: (loop.quit(), False)[1])
        loop.run()
        clean = self.stop()
        return {"swaps": state["n"], "error": self._error, "teardown_clean": clean}

    def run_forever(self, *, control_fifo: str | None = None) -> dict[str, Any]:
        """Run the channel until EOS, a pipeline error, SIGINT/SIGTERM, or a control
        ``stop``. Production mode for the per-channel worker. If ``control_fifo`` is
        given, newline commands (``swap <index>``, ``reload <graph.json>``, ``stop``)
        drive seamless role swaps and program content-reloads (D-S1-6: change the
        active source in place, never a restart). SIGTERM — what the daemon's
        ``terminate()`` sends — also quits and tears down gracefully (time-bounded
        ``→NULL`` with force-exit so the worker can never hang)."""
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus)
        self._install_output_counter()  # S9-5: count TS buffers past the mux
        loop = GLib.MainLoop()  # before PLAYING so a startup bus ERROR isn't swallowed
        self._loop = loop
        self._prime_live_caption_stream()
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("pipeline failed to reach PLAYING")
        self._await_playing()
        self._arm_live_caption_gap_heartbeat()
        self._flush_lang_tags()  # push deferred secondary-audio ISO-639 descriptors
        self._arm_stall_watchdog()  # S9-5: quit (→ daemon restart) on a silent output stall

        keepalive_fd = self._watch_control_fifo(control_fifo) if control_fifo else None

        install_unix_signal_handlers(
            GLib,
            signal_numbers=(signal.SIGINT, signal.SIGTERM),
            quit_loop=loop.quit,
        )
        loop.run()
        if keepalive_fd is not None:
            with contextlib.suppress(OSError):
                os.close(keepalive_fd)
        clean = self.stop(force_exit_on_hang=True)
        return {"error": self._error, "teardown_clean": clean}

    def _watch_control_fifo(self, path: str) -> int:
        """Watch a control FIFO for swap/stop commands. Returns a keepalive write fd
        (held open so the read end never EOFs when external writers come and go)."""
        open_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        read_fd = os.open(path, open_flags)
        keepalive_fd = os.open(path, os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
        channel = GLib.IOChannel.unix_new(read_fd)
        channel.set_encoding(None)
        channel.set_buffered(False)

        def _on_ctrl(_channel: GLib.IOChannel, condition: GLib.IOCondition) -> bool:
            if condition & GLib.IOCondition.IN:
                try:
                    data = os.read(read_fd, 4096)
                except BlockingIOError:
                    return True
                for line in data.decode("utf-8", "replace").splitlines():
                    self._dispatch_control(line)
            return True  # keep watching

        GLib.io_add_watch(
            channel,
            GLib.PRIORITY_DEFAULT,
            GLib.IOCondition.IN | GLib.IOCondition.HUP,
            _on_ctrl,
        )
        return keepalive_fd

    def _dispatch_control(self, line: str) -> None:
        command = parse_control_line(line)
        if command is None:
            return
        if command[0] == "swap":
            try:
                self.swap.swap_to(command[1])
                print(f"CTRL swap {command[1]} applied", flush=True)
            except Exception as exc:
                print(f"CTRL swap {command[1]} failed: {exc!r}", flush=True)
        elif command[0] == "reload":
            try:
                with Path(command[1]).open(encoding="utf-8") as handle:
                    new_graph = graph_from_json(handle.read())
                with contextlib.suppress(OSError):
                    Path(command[1]).unlink()  # one-shot graph file: consume it after read
                self.reload_program(new_graph.sources[0])
                print(f"CTRL reload armed ({command[1]})", flush=True)
            except Exception as exc:  # a bad reload must not kill the channel
                print(f"CTRL reload failed: {exc!r}", flush=True)
        elif command[0] == "caption":
            # ("caption", pts_ms, dur_ms, b64text) — push one cue into the live appsrc.
            try:
                text = base64.b64decode(command[3]).decode("utf-8", "replace")
                pushed = self.push_caption_cue(
                    text=text,
                    pts_seconds=command[1] / 1000.0,
                    duration_seconds=command[2] / 1000.0,
                )
                if not pushed:
                    print("CTRL caption dropped: no live caption source", flush=True)
            except Exception as exc:  # a bad caption must never kill the channel
                print(f"CTRL caption failed: {exc!r}", flush=True)
        elif command[0] == "stop":
            print("CTRL stop", flush=True)
            if self._loop is not None:
                self._loop.quit()

    # -- content-reload (D-S1-6): rebuild the program leg while output stays PLAYING --

    def reload_program(self, new_leg: SourceLeg | PlaylistLeg) -> None:
        """Replace the program leg (source index 0) with ``new_leg`` seamlessly.

        Builds the new leg on the live PLAYING pipeline, prerolls it, and switches the
        selector(s) to it on the new leg's FIRST BUFFER (via a pad probe → main-loop
        idle, so the run loop is never blocked waiting on preroll). The old leg is
        disposed only after the switch commits.

        The reload can never wedge the channel (the engine's "playout can never wedge"
        invariant). Three escape hatches cover every way a switch might not happen:
        (a) a bounded watchdog aborts the reload if the new leg never delivers a first
        buffer (a live source that connects but never rolls); (b) a synchronous
        build/preroll failure aborts cleanly and re-raises (the current program keeps
        playing); (c) an async bus error on the uncommitted new leg aborts via
        ``_on_bus`` rather than taking output down. A newer reload arriving while one is
        still settling SUPERSEDES it (the old in-flight leg is aborted) — a due program
        is never silently dropped."""
        if self.selector is None or not self.selector_sink_pads:
            raise RuntimeError("engine not built; cannot reload")
        if self._pending_reload is not None:
            # Supersede the still-settling reload with this newer one (never drop a
            # program change). The superseded leg is disposed before we build the new.
            print("CTRL reload superseding a still-settling reload", flush=True)
            self._abort_pending_reload("superseded")

        old_video_pad = self.selector_sink_pads[0]
        old_audio_pad = self.audio_sink_pads[0] if self.audio_sink_pads else None
        old_elements = self._source_leg_elements[0]

        # Build + link the new leg. A failure here has committed no state, so the
        # current program keeps playing — just propagate (the caller logs it).
        out_pad, audio_out_pad, new_elements = self._instantiate_source_leg(new_leg)
        new_video_pad, new_audio_pad = self._link_leg_to_selectors(
            "program(reload)", out_pad, audio_out_pad
        )
        pending = {
            "new_video_pad": new_video_pad,
            "new_audio_pad": new_audio_pad,
            "old_video_pad": old_video_pad,
            "old_audio_pad": old_audio_pad,
            "old_elements": old_elements,
            "new_elements": new_elements,
            "probe_id": None,
            "timeout_id": None,
        }
        self._pending_reload = pending
        try:
            # ENG-002: arm the first-buffer probe BEFORE bringing the leg to PLAYING so
            # the genuine first buffer can never slip past an unarmed probe.
            pending["probe_id"] = new_video_pad.add_probe(
                Gst.PadProbeType.BUFFER, self._on_reload_first_buffer
            )
            for element in new_elements:
                element.sync_state_with_parent()  # preroll the new leg
        except Exception:  # ENG-008: a preroll/arm failure must not wedge
            self._abort_pending_reload("build-error")
            raise
        # ENG-001: bound the wait for the new leg's first buffer. If it never arrives,
        # abort rather than pin _pending_reload forever (the old program keeps playing).
        pending["timeout_id"] = GLib.timeout_add_seconds(
            max(1, int(self.reload_timeout_s)), self._on_reload_timeout
        )

    def _on_reload_first_buffer(self, _pad: Gst.Pad, _info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        # Streaming thread: hand the commit to the main loop (no state changes here).
        GLib.idle_add(self._commit_reload)
        return Gst.PadProbeReturn.REMOVE

    def _commit_reload(self) -> bool:
        """Main-loop commit of a reload: switch the selector(s) to the prerolled new
        leg, repoint role index 0 at it, then dispose the old leg. A no-op if the
        reload was aborted/superseded before this fired. ``return False`` so the GLib
        idle source runs once."""
        pending = self._pending_reload
        if pending is None:
            return False  # aborted or superseded before the first buffer landed
        if pending["timeout_id"] is not None:
            GLib.source_remove(pending["timeout_id"])  # committing — cancel the watchdog
        new_video_pad = pending["new_video_pad"]
        new_audio_pad = pending["new_audio_pad"]
        selector = self.selector
        if selector is None:
            self._abort_pending_reload("selector-missing")
            return False
        selector.set_property("active-pad", new_video_pad)
        audio_selector = self.audio_selector
        if new_audio_pad is not None and audio_selector is not None:
            audio_selector.set_property("active-pad", new_audio_pad)
        # Role index 0 (program) now points at the new leg. The swap controller shares
        # these list objects by reference, so an operator role-swap stays correct.
        self.selector_sink_pads[0] = new_video_pad
        if self.audio_sink_pads and new_audio_pad is not None:
            self.audio_sink_pads[0] = new_audio_pad
        self._source_leg_elements[0] = pending["new_elements"]
        self._pending_reload = None
        self._dispose_source_leg(
            pending["old_video_pad"], pending["old_audio_pad"], pending["old_elements"]
        )
        # Element count proves disposal reclaimed (the POSIX leak test asserts it is flat
        # across many reloads — a dispose leak would grow it).
        print(f"CTRL reload committed (elements={self._element_count()})", flush=True)
        return False

    def _on_reload_timeout(self) -> bool:
        """Watchdog: the new reload leg never produced a first buffer in time. Abort so
        the channel isn't wedged on a never-committing reload; the old program keeps
        playing and the next due program can retry."""
        if self._pending_reload is None:
            return False  # already committed/aborted
        print(
            f"CTRL reload aborted: new program produced no buffer within {max(1, int(self.reload_timeout_s))}s; "
            "keeping current program",
            flush=True,
        )
        self._abort_pending_reload("timeout")
        return False  # one-shot

    def _abort_pending_reload(self, reason: str) -> None:
        """Tear down the in-flight (uncommitted) reload leg and clear the pending slot.
        The currently-active program is untouched. Used by supersede, build-error,
        watchdog timeout, and async-error containment."""
        pending = self._pending_reload
        if pending is None:
            return
        self._pending_reload = None
        if pending["probe_id"] is not None:
            with contextlib.suppress(Exception):  # probe may already have auto-removed
                pending["new_video_pad"].remove_probe(pending["probe_id"])
        if pending["timeout_id"] is not None and reason != "timeout":
            # 'timeout' means the watchdog source is firing now (auto-removed on return).
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["timeout_id"])
        self._dispose_source_leg(
            pending["new_video_pad"], pending["new_audio_pad"], pending["new_elements"]
        )

    def _belongs_to_pending_reload(self, src: object) -> bool:
        """True if ``src`` (a bus-message source) is one of the pending reload leg's
        elements or nested under one (e.g. a decodebin-internal decoder)."""
        pending = self._pending_reload
        if pending is None or src is None:
            return False
        new_elements = pending["new_elements"]
        node = src
        while node is not None:
            if node in new_elements:
                return True
            node = node.get_parent() if hasattr(node, "get_parent") else None
        return False

    def _element_count(self) -> int:
        """Count elements currently in the pipeline (for the reload-leak guard)."""
        iterator = self.pipeline.iterate_elements()
        count = 0
        while True:
            result, _element = iterator.next()
            if result != Gst.IteratorResult.OK:
                break
            count += 1
        return count

    def _dispose_source_leg(
        self,
        video_pad: Gst.Pad,
        audio_pad: Gst.Pad | None,
        elements: list[Gst.Element],
    ) -> None:
        """Tear down a now-inactive source leg: unlink from the selector(s), release
        the request pad(s), then NULL + remove its elements. Best-effort — a disposal
        hiccup is logged, never raised, so it can't kill a live channel. (Without this
        a 24/7 channel would leak a leg's elements on every program change.)"""
        try:
            for element in elements:
                element.set_state(Gst.State.NULL)
            for selector, pad in (
                (self.selector, video_pad),
                (self.audio_selector, audio_pad),
            ):
                if selector is None or pad is None:
                    continue
                peer = pad.get_peer()
                if peer is not None:
                    peer.unlink(pad)
                selector.release_request_pad(pad)
            for element in elements:
                self.pipeline.remove(element)
        except Exception as exc:
            print(f"WARN: reload disposal incomplete: {exc!r}", flush=True)

    def stop(self, *, force_exit_on_hang: bool = False) -> bool:
        """Time-bounded teardown. Returns True iff the pipeline reached NULL within
        ``teardown_timeout_s``. With ``force_exit_on_hang`` (worker-process model),
        an incomplete transition triggers ``os._exit(70)`` (nonzero = forced kill, so
        the supervisor doesn't read it as a clean exit) so the process can never hang
        on stuck live-source streaming threads (the Stage-0 lesson)."""
        self.pipeline.set_state(Gst.State.NULL)
        result, _current, _pending = self.pipeline.get_state(
            int(self.teardown_timeout_s * Gst.SECOND)
        )
        clean = bool(result == Gst.StateChangeReturn.SUCCESS)
        if self.audio_tap_writer is not None:
            self.audio_tap_writer.close()
            self.audio_tap_writer = None
        if not clean and force_exit_on_hang:
            os._exit(70)  # nonzero: a forced kill, not a clean exit (audit MINOR)
        return clean
