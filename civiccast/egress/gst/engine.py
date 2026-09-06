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
import json
import math
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

# R3 banner-PNG cleanup: the per-call unique filename ``bridge.py``'s
# ``graphics_overlay_leg_from_config`` renders (``graphics-overlay-lower-third.
# <uuid4-hex>.png``). Deletion of an overlay layer's image file is gated on this
# exact pattern so cleanup can NEVER touch an operator-configured, persistent
# image (e.g. a station-bug/logo ``image_path`` from config) -- only a file this
# module itself renders per-start()/per-reload matches.
_STALE_BANNER_PNG_RE = re.compile(r"^graphics-overlay-lower-third\.[0-9a-f]{32}\.png$")

try:  # package context (see the sibling-import note further down for why both forms)
    from civiccast.egress.gst.decode_policy import (
        demote_hardware_decoders,
        prefer_cpu_decoders_by_default,
    )
except ImportError:  # standalone context: the gst dir is on sys.path
    from decode_policy import (  # type: ignore[import-not-found,no-redef]
        demote_hardware_decoders,
        prefer_cpu_decoders_by_default,
    )

# MUST run before ``gi``/GStreamer is imported below: GST_PLUGIN_FEATURE_RANK is read
# during registry scan, which happens inside Gst.init().
prefer_cpu_decoders_by_default()

from civiccast.native.gstreamer_runtime import bootstrap_installed_gstreamer_runtime  # noqa: E402

bootstrap_installed_gstreamer_runtime()

import gi  # type: ignore[import-not-found] # noqa: E402

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # type: ignore[import-not-found] # noqa: E402

try:  # package context — the native Windows line reaches this branch too:
    # the bundled GStreamer runtime (bootstrapped above) makes the `gi` import
    # succeed there, so `worker.py` must import these modules through the SAME
    # package path or the two halves bind two distinct copies of `PlaylistLeg`
    # (see worker.py's import note — that mismatch was the Gate A T4 defect).
    from civiccast.egress.gst.audio_tap import RollingWavSegmentWriter
    from civiccast.egress.gst.graph import (
        AudioTapLeg,
        CaptionEmbedLeg,
        ElementSpec,
        GraphicsOverlayLayer,
        GraphicsOverlayLeg,
        PlaylistLeg,
        PlayoutGraph,
        SecondaryAudioLeg,
        SourceLeg,
        coerce_serialized_property,
        graph_from_json,
        source_leg_is_clock_timed,
    )
except (
    ImportError
):  # standalone context: the POSIX/Windows GStreamer test adds the gst dir to sys.path
    from audio_tap import RollingWavSegmentWriter  # type: ignore[import-not-found,no-redef]
    from graph import (  # type: ignore[import-not-found,no-redef]
        AudioTapLeg,
        CaptionEmbedLeg,
        ElementSpec,
        GraphicsOverlayLayer,
        GraphicsOverlayLeg,
        PlaylistLeg,
        PlayoutGraph,
        SecondaryAudioLeg,
        SourceLeg,
        coerce_serialized_property,
        graph_from_json,
        source_leg_is_clock_timed,
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

try:
    from civiccast.egress.gst.reload_policy import (
        reload_id_from_sidecar_path,
        reload_switch_is_deferred,
    )
except ImportError:
    from reload_policy import (  # type: ignore[import-not-found,no-redef]
        reload_id_from_sidecar_path,
        reload_switch_is_deferred,
    )

# Item 85: gi-free exit-code contract with the daemon (same reasoning as the
# reload_policy/decode_policy siblings above -- this module must stay
# importable both in package form and by-path, see worker.py's docstring).
try:
    from civiccast.egress.gst.exit_codes import GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE
except ImportError:
    from exit_codes import (  # type: ignore[import-not-found,no-redef]
        GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE,
    )


class PrerollTimeoutError(RuntimeError):
    """The pipeline did not reach PLAYING within the configured preroll bound.

    Distinct from a bare ``RuntimeError`` (item 82, sandbox run 13 evidence) so
    ``worker.py`` can exit with ``GST_PREROLL_TIMEOUT_EXIT_CODE`` — a distinct
    code the daemon's relaunch path (``EgressDaemon._relaunch_after_crash`` /
    ``_begin_relaunch``) reads to treat a slow-but-progressing preroll under
    CPU load as a slow start, not a crash, instead of counting every such exit
    toward the crash-loop force-fallback-slate streak like an ordinary crash.
    """


# Item 82: how long ``_await_playing`` waits for the PLAYING transition before
# giving up. 30s default — generous enough to ride out ordinary CPU-load
# preroll jitter (the measured failure was a 5.0s bound tripping under load),
# never so long that a genuinely wedged pipeline hangs the worker
# indefinitely (the time-bounded-teardown audit finding M1 this method
# already exists for). Configurable per-instance and via env var for ops
# tuning without a code change; clamped to [5, 45]s.
#
# Round-2 review BLOCKER (Opus, PR #183): the upper bound is load-bearing, not
# cosmetic. ``EgressDaemon._relaunch_after_crash`` treats a worker that stayed
# up >= ``_RESTART_STREAK_RESET_UPTIME_S`` (60s) as having had a "healthy run"
# and resets the crash-loop streak to 0 — an unclamped
# ``CIVICCAST_GST_PREROLL_TIMEOUT_S >= 60`` would make a worker that ALWAYS
# preroll-times-out still measure >= 60s of "uptime" on every single exit
# (it dies right at its own configured bound), so the streak would reset on
# every crash and NEVER reach ``_LIVE_SOURCE_FAILURE_FALLBACK_STREAK`` — a
# genuinely dead source would relaunch forever instead of ever landing on
# fallback slate (measured: 40 relaunches, streak stuck at 0). 45s keeps the
# preroll bound comfortably below the 60s reset threshold with margin for
# poll/scheduling jitter, AND the daemon's crash-path exempts a
# ``GST_PREROLL_TIMEOUT_EXIT_CODE`` exit from that healthy-uptime reset
# outright (see ``_relaunch_after_crash``'s own docstring).
#
# Round-3 correction: this clamp and the crash-path exemption above are NOT
# sufficient on their own -- the daemon's SEPARATE alive-poll reset
# (``EgressDaemon._poll_process``) used to fire on wall-clock seconds since
# the worker was SPAWNED, which also counts interpreter start + ``import
# gi``/``Gst.init`` + graph build + this preroll wait itself, none of which is
# air. That overhead is NOT bounded by ``preroll_timeout_s`` and can push a
# worker's total spawn-to-exit lifetime past 60s even while it never once
# reaches PLAYING (measured: alive for 60-62s of poll ticks then a
# preroll-timeout exit, streak stuck at 1, never escalates in 40 cycles) --
# so the 45s clamp and the crash-path exemption alone did NOT close the hole
# either one, individually or together. The real fix is
# ``_await_playing`` emitting a stderr marker only on an ACTUAL PLAYING
# transition (see the ``CTRL preroll: reached PLAYING`` print below), which
# ``EgressDaemon._poll_process`` looks for via
# ``civiccast.egress.health.worker_reached_playing`` and only starts the 60s
# healthy-uptime clock from the moment that evidence is first observed —
# never from spawn time.
#
# Round-4 correction (PR #183 review, BLOCKER REPRODUCED): round-3's fix was
# ITSELF not sufficient -- the marker text above is real, but the daemon's
# per-channel stderr log is a single FIXED PATH opened in APPEND mode and
# never truncated per spawn (``_default_worker_launcher`` in ``strategy.py``,
# ``start_ffmpeg`` in ``_ffmpeg.py`` on the FFmpeg side). Once ANY worker on a
# channel ever printed this marker, it sat in the log forever, and
# ``worker_reached_playing``'s old fixed tail-window read had no way to tell
# "this worker's own marker" apart from "a previous worker's marker still in
# the tail window" -- every later worker was "confirmed on air" on its very
# first poll tick, so the 60s healthy-uptime clock became a spawn clock again
# (measured: 40 relaunches, streak pinned at 1 -- the exact round-2 symptom
# this whole fix chain exists to close, reproduced through the round-3 fix
# unchanged). Closed with two independent anchors, belt and braces:
# ``EgressDaemon._stderr_spawn_offset`` records the log's byte SIZE at this
# worker's own spawn, and ``worker_reached_playing`` /
# ``read_ffmpeg_encoder_metrics_since`` (``civiccast.egress.health``) scan
# ONLY bytes at or after that offset -- a previous worker's marker, which
# always sits before it, is never read at all, not merely filtered out after
# the fact; AND the marker line now carries THIS worker's own pid (see the
# ``os.getpid()`` print below), which the daemon requires to match its
# currently-tracked process before crediting the marker, independent of
# whether the byte offset happens to be right. The fixed 64 KiB tail window
# is gone from this check entirely -- the marker is the OLDEST line a worker
# ever prints, so a small tail window was never actually safe against a
# worker whose own startup chatter grew past it before the first observing
# poll tick, append-log bug aside.
_DEFAULT_PREROLL_TIMEOUT_S = 30.0
_MIN_PREROLL_TIMEOUT_S = 5.0
_MAX_PREROLL_TIMEOUT_S = 45.0
_PREROLL_TIMEOUT_ENV_VAR = "CIVICCAST_GST_PREROLL_TIMEOUT_S"
# How often _await_playing logs the pipeline's still-waiting state while a
# preroll is in flight, so a SLOW preroll is visible on stderr (and in the
# daemon's stderr-tail last_error) well before it either finishes or times
# out — before this fix a preroll wedged anywhere under the bound was
# completely silent until it either succeeded or the worker died.
_PREROLL_POLL_INTERVAL_S = 5.0


def _resolve_preroll_timeout_s(explicit: float | None) -> float:
    """Resolve the PLAYING-preroll bound: an explicit constructor value wins,
    else the ``CIVICCAST_GST_PREROLL_TIMEOUT_S`` env var, else the 30s
    default — always clamped to ``[5, 45]``s. The floor guards against
    false-positiving on ordinary CPU-load preroll jitter (the exact item 82
    failure mode); the ceiling keeps the bound safely under the daemon's 60s
    healthy-uptime streak-reset threshold (see the module-level comment above
    ``_DEFAULT_PREROLL_TIMEOUT_S`` for why an unclamped value there silently
    defeats the crash-loop escalation to fallback slate).

    Round-2 review item 4 (Opus, PR #183): ``min(max(x, lo), hi)`` does NOT
    clamp a NaN -- Python's ``max``/``min`` keep their FIRST argument on any
    comparison against NaN (every comparison with NaN is False), so
    ``min(max(nan, 5.0), 45.0)`` evaluates to ``nan``, not ``5.0``. A NaN
    bound then reaches ``_await_playing``'s ``deadline = time.monotonic() +
    self.preroll_timeout_s`` as NaN, every ``remaining`` comparison against it
    is False, and the loop falls through to the generic pipeline-construction
    ``ValueError`` path instead of ever raising the distinct
    ``PrerollTimeoutError`` -- silently defeating the whole point of this
    fix (a slow start dies as an ORDINARY crash again, indistinguishable from
    a real pipeline failure). ``CIVICCAST_GST_PREROLL_TIMEOUT_S=nan`` parses
    cleanly as a float (Python's ``float("nan")`` succeeds), so it was never
    caught by the existing ``except ValueError`` either. Guarded with
    ``math.isfinite`` before the clamp on both the explicit-arg and env-var
    paths: a non-finite value (NaN or +/-inf) falls back to the 30s default
    with a warning, exactly like any other unusable input."""
    if explicit is not None:
        if not math.isfinite(explicit):
            print(
                f"CTRL preroll: ignoring non-finite preroll_timeout_s={explicit!r}; "
                f"using default {_DEFAULT_PREROLL_TIMEOUT_S}s",
                file=sys.stderr,
                flush=True,
            )
            return _DEFAULT_PREROLL_TIMEOUT_S
        return min(max(explicit, _MIN_PREROLL_TIMEOUT_S), _MAX_PREROLL_TIMEOUT_S)
    raw = os.environ.get(_PREROLL_TIMEOUT_ENV_VAR)
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = math.nan  # falls through to the non-finite branch below
        if not math.isfinite(parsed):
            print(
                f"CTRL preroll: ignoring non-finite {_PREROLL_TIMEOUT_ENV_VAR}={raw!r}; "
                f"using default {_DEFAULT_PREROLL_TIMEOUT_S}s",
                file=sys.stderr,
                flush=True,
            )
            return _DEFAULT_PREROLL_TIMEOUT_S
        return min(max(parsed, _MIN_PREROLL_TIMEOUT_S), _MAX_PREROLL_TIMEOUT_S)
    return _DEFAULT_PREROLL_TIMEOUT_S


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
        defer_switch_timeout_s: float = 900.0,
        preroll_timeout_s: float | None = None,
        commit_timeout_s: float = 15.0,
    ) -> None:
        prefer_cpu_decoders_by_default()
        Gst.init([])
        # Belt-and-suspenders with the env-var rank list above: demote by klass, from
        # the registry that really exists here, so a bundled hardware decoder nobody
        # added to the name list cannot win autoplug (Gate A T4 root cause).
        demoted = demote_hardware_decoders(Gst.Registry.get().get_feature_list(Gst.ElementFactory))
        if demoted:
            print(
                f"CTRL decode: demoted hardware decoders to CPU decode: {','.join(demoted)}",
                file=sys.stderr,
                flush=True,
            )
        self.graph = graph
        self.swap = swap or InputSelectorSwap()
        self.teardown_timeout_s = teardown_timeout_s
        self.reload_timeout_s = reload_timeout_s
        # B3 fix: bounds how long a switch_at_end_of_current=True reload waits for
        # the OUTGOING leg's own EOS once the new leg is already ready, before
        # forcing the switch anyway (never leak two legs held open forever if a
        # schedule item's actual duration runs long or its EOS never arrives).
        # Deliberately much longer than reload_timeout_s -- that timer bounds "is
        # the new leg ready at all", this one bounds "how long is it acceptable to
        # sit on a ready leg waiting for a natural handoff point".
        self.defer_switch_timeout_s = defer_switch_timeout_s
        # S9-5: if output (TS buffers past the mux) does not advance for this long while
        # on-air, the pipeline has silently stalled — quit so the daemon restarts the
        # worker to a known state (a live source that freezes without posting an error).
        self.stall_timeout_s = stall_timeout_s
        # Item 85: bounds ``_commit_reload`` itself -- see ``_arm_commit_watchdog``
        # for why a plain ``GLib.timeout_add`` cannot do this job alone (the
        # measured wedge blocks the very thread that would run it).
        self.commit_timeout_s = commit_timeout_s
        # Item 82: bounded PLAYING-preroll wait (see ``_await_playing`` / the
        # module-level ``_resolve_preroll_timeout_s`` for the constructor-arg /
        # env-var / default resolution and clamp).
        self.preroll_timeout_s = _resolve_preroll_timeout_s(preroll_timeout_s)
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
        # H1 fix (measured 2026-09-06 hardware soak): monotonic sequence number so
        # a ``PlaylistLeg``'s ``concat`` aggregators (``vconcat_<label>``/
        # ``aconcat_<label>``) get a fresh, unique element name on EVERY build --
        # the initial ``_build()`` call AND every later ``reload_program`` rebuild
        # of that same-labeled leg (typically "program"). Before this fix every
        # build reused the bare ``f"vconcat_{leg.label}"`` name, so a reload's
        # rebuilt aggregator collided with the still-live outgoing leg's aggregator
        # of the same name -- see ``_make``'s fail-loud ``pipeline.add`` check
        # above, and ``_build_playlist``'s naming below. Mirrors
        # ``_overlay_layer_seq`` immediately below, same rationale.
        self._source_leg_seq = 0
        self._pending_reload: dict[str, Any] | None = None
        # S15 graphics-overlay reload state (BLOCKER fix, 2026-08-30 audit): the
        # compositor + per-layer-name pad/elements built by ``_build_graphics_overlay``
        # (None/empty when the graph has no overlay leg), plus any swap that is
        # currently settling toward a first-buffer commit -- mirrors
        # ``_source_leg_elements``/``_pending_reload`` above, one entry per layer NAME
        # instead of one leg per role index (see ``reload_graphics_overlay``).
        self._overlay_compositor: Gst.Element | None = None
        self._overlay_layer_pads: dict[str, Gst.Pad] = {}
        self._overlay_layer_elements: dict[str, list[Gst.Element]] = {}
        # R3: the image_path each currently-live layer's chain reads from, so a
        # swap/removal can delete the file it is REPLACING once (and only once)
        # that old chain is fully disposed -- never the file the still-live or
        # about-to-commit chain has open. Index-aligned with
        # ``_overlay_layer_pads``/``_overlay_layer_elements`` by layer name.
        self._overlay_layer_image_paths: dict[str, str] = {}
        self._pending_overlay_swaps: dict[str, dict[str, Any]] = {}
        self._overlay_layer_seq = 0
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
        for key, handle in spec.secret_props.items():
            # WP-07: the graph file on disk carries only an opaque handle; the
            # real secret is fetched from the station's OS credential store
            # here, at element-construction time, and set straight onto the
            # element. It is never logged and never written back anywhere.
            # Fail closed -- a live SRT source whose passphrase cannot be read
            # must not silently start unauthenticated.
            from civiccast.live.secrets import load_live_source_secret

            secret = load_live_source_secret(handle)
            if not secret:
                raise RuntimeError(
                    f"credential handle {handle!r} for {spec.factory} property {key!r} is "
                    "not present in this station's credential store"
                )
            element.set_property(key, secret)
        # H1 fix (measured 2026-09-06 hardware soak, three-channel seamless-rollover
        # stall): ``Gst.Bin.add()`` returns a bool and silently REFUSES a duplicate
        # element name in the same bin ("Name '<name>' is not unique in bin ... not
        # adding") instead of raising -- the discarded return value here used to let
        # a reload's rebuilt concat aggregator (see ``_build_playlist``'s
        # ``_source_leg_seq`` naming below) dangle unlinked in the pipeline: its
        # elements existed but were never actually part of the bin, so the new
        # leg's probes never fired and every reload timed out and was silently
        # retried by automation forever (worker.py's stall watchdog then bounced
        # the channel every ~30s). Fail loud instead: the caller
        # (``reload_program``'s try/except ENG-008 path) aborts the in-flight
        # reload cleanly and the current program keeps playing.
        #
        # Candidate-3 smoke regression (2026-09-06, real GStreamer 1.28.5 on the
        # installed product closure): this check's own contract assumption was
        # wrong for gst-python's ``overrides/Gst.py``, which wraps the raw C
        # ``gst_bin_add()`` -- ``Gst.Bin.add()`` there does NOT return the raw
        # bool at all: it returns ``None`` on SUCCESS and RAISES ``Gst.AddError``
        # on failure (never returns a plain ``False``). ``if not self.pipeline.
        # add(element):`` treated that ``None`` success return as falsy, so the
        # very FIRST element ever added to a freshly built pipeline (the video
        # selector, name "sel") always raised this RuntimeError even though
        # GStreamer's own C code had just logged "added element sel" --
        # confirmed directly: ``pipeline.add(el)`` returned ``None`` on a real
        # add, ``pipeline.iterate_elements()`` showed the element really was a
        # child, and a genuine duplicate raised ``Gst.AddError`` rather than
        # returning ``False``. This broke every initial build against a real,
        # override-wrapped gst-python -- unit tests never caught it because the
        # fake pipeline fixture modeled the assumed (raw-bool) contract, not
        # this one. ``_bin_add`` below normalizes both contracts to a plain
        # bool so this check works against either.
        if not self._bin_add(element):
            raise RuntimeError(
                f"GStreamer refused to add element {spec.factory!r} "
                f"(name={element.get_name()!r}) to the pipeline -- a duplicate "
                "element name already exists in this bin"
            )
        if self._collecting is not None:
            # Building a source leg — record the element so the leg can be torn down
            # as a unit on a later content-reload.
            self._collecting.append(element)
        return element

    def _bin_add(self, element: Gst.Element) -> bool:
        """``self.pipeline.add(element)``, normalized to a plain bool regardless
        of which of TWO real contracts this GStreamer's Python binding follows:

        * the raw C ``gst_bin_add()`` contract (a gboolean return, no
          exception) -- what the fake pipeline fixture in
          ``tests/egress/test_gst_engine_reload_concat_naming.py`` models, and
          what an older/unwrapped binding may still do; or
        * gst-python's ``overrides/Gst.py`` ``Bin.add()`` override -- confirmed
          directly against GStreamer 1.28.5 (the candidate-3 installed
          product's own runtime): returns ``None`` on success and RAISES
          ``Gst.AddError`` on failure, never a bare ``False``.

        ``getattr(Gst, "AddError", ())`` degrades to an empty tuple (an
        ``except ()`` that matches nothing) when this binding has no
        ``AddError`` at all -- e.g. the fake ``Gst`` module the unit tests
        install -- so this helper needs no test-fixture changes to keep
        working against either contract."""
        try:
            added = self.pipeline.add(element)
        except getattr(Gst, "AddError", ()):
            return False
        return added is not False

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
        the sub-chains. Returns ``(video_concat, audio_concat | None)``.

        H1 fix: the aggregators' element names carry ``self._source_leg_seq`` (bumped
        once per call) so a content-reload's rebuilt aggregator for the SAME leg label
        (``reload_program`` always reloads the "program" role) never collides with the
        still-live outgoing leg's aggregator of the same name -- see ``_make``'s
        fail-loud ``pipeline.add`` check and this class's ``_source_leg_seq`` docstring
        for the measured defect this closes."""
        self._source_leg_seq += 1
        seq = self._source_leg_seq
        vconcat = self._make(ElementSpec("concat", f"vconcat_{leg.label}_{seq}"))
        aconcat = (
            self._make(ElementSpec("concat", f"aconcat_{leg.label}_{seq}"))
            if leg.audio_tail
            else None
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
        the caller links into its encoder chain.

        The compositor and each layer's pad/elements are retained on
        ``self._overlay_compositor``/``self._overlay_layer_pads``/
        ``self._overlay_layer_elements`` so a later content-reload
        (``reload_graphics_overlay``) can add/swap/remove layers by name on the
        already-PLAYING pipeline instead of silently ignoring the reload's overlay
        leg (BLOCKER fix, 2026-08-30 audit)."""
        compositor = self._make(leg.compositor)
        self._overlay_compositor = compositor

        base_upload = self._make(ElementSpec("d3d11upload", name="graphics_overlay_base_upload"))
        self._link(video_prev, base_upload)
        base_pad = compositor.request_pad_simple("sink_%u")
        if (
            base_pad is None
            or base_upload.get_static_pad("src").link(base_pad) != Gst.PadLinkReturn.OK
        ):
            raise RuntimeError("failed to link program video into the graphics-overlay compositor")

        for layer in leg.layers:
            layer_pad, elements = self._instantiate_overlay_layer(layer, compositor)
            self._overlay_layer_pads[layer.name] = layer_pad
            self._overlay_layer_elements[layer.name] = elements
            self._overlay_layer_image_paths[layer.name] = layer.image_path

        download = self._make(ElementSpec("d3d11download", name="graphics_overlay_download"))
        self._link(compositor, download)
        post_convert = self._make(ElementSpec("videoconvert", name="graphics_overlay_post_convert"))
        self._link(download, post_convert)
        return post_convert

    def _instantiate_overlay_layer(
        self, layer: GraphicsOverlayLayer, compositor: Gst.Element
    ) -> tuple[Gst.Pad, list[Gst.Element]]:
        """Build one graphics-overlay image layer's still-image chain
        (``filesrc ! decodebin ! videoconvert ! d3d11upload``) and link it into a
        NEW compositor request pad, applying the layer's position/size/alpha/
        repeat-after-eos properties. Shared by the initial ``_build_graphics_overlay``
        (pipeline not yet PLAYING — no explicit state sync needed, the top-level
        ``set_state(PLAYING)`` cascades to every element already added) and by
        ``_swap_overlay_layer`` (the content-reload re-apply path on an
        already-PLAYING pipeline, which arms a first-buffer probe THEN calls
        ``sync_state_with_parent()`` itself — mirrors ``reload_program``'s ENG-002
        ordering, so the caller controls when/whether to sync).

        Element names are suffixed with a monotonic sequence number
        (``self._overlay_layer_seq``) so a reload's rebuilt chain for an
        already-built layer name never collides with the still-live old chain it
        is about to replace. Returns ``(compositor_sink_pad, elements)`` — the
        caller collects/disposes ``elements`` as a unit, exactly like a source leg."""
        self._overlay_layer_seq += 1
        collected: list[Gst.Element] = []
        self._collecting = collected
        try:
            chain = (
                ElementSpec("filesrc", props={"location": layer.image_path}),
                ElementSpec("decodebin"),
                ElementSpec("videoconvert"),
                ElementSpec(
                    "d3d11upload",
                    name=f"graphics_overlay_upload_{layer.name}_{self._overlay_layer_seq}",
                ),
            )
            _first, layer_tail = self._build_chain(chain)
        finally:
            self._collecting = None
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
        return layer_pad, collected

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

    #: ``input-selector`` properties this engine sets DELIBERATELY on every
    #: selector it builds, rather than inheriting whatever the linked GStreamer
    #: build happens to default to. Each is load-bearing for the boundary-aligned
    #: deferred switch (``reload_program(switch_at_end_of_current=True)``):
    #:
    #: * ``sync-streams=True`` — an inactive pad's buffers are held/dropped
    #:   against the ACTIVE stream's running time instead of racing ahead. The
    #:   deferred switch never relies on this (its new leg is held upstream of
    #:   the selector by a blocking pad probe and pushes nothing at all while
    #:   inactive), but leaving it on means a leg that somehow DOES push while
    #:   inactive — a live source on the slate role, say — cannot flood the
    #:   selector.
    #: * ``sync-mode=active-segment`` — sync inactive pads against the active
    #:   pad's SEGMENT running time, not the pipeline clock. The program legs are
    #:   non-live (filesrc→decodebin): their running time is segment-derived and
    #:   does not track the clock when the sinks do not pace the pipeline, so
    #:   ``clock`` mode would compare two unrelated timebases.
    #: * ``cache-buffers=False`` — an inactive pad must NEVER accumulate buffers.
    #:   Caching them is exactly the unbounded-RSS failure the hold-probe design
    #:   exists to avoid on a 24/7 channel: a leg prepared minutes ahead of its
    #:   boundary would otherwise queue every one of those minutes in memory.
    _SELECTOR_PROPS: ClassVar[dict[str, object]] = {
        "sync-streams": True,
        "sync-mode": 0,
        "cache-buffers": False,
    }

    def _make_selector(self, name: str) -> Gst.Element:
        selector = self._make(ElementSpec("input-selector", name))
        for key, value in self._SELECTOR_PROPS.items():
            selector.set_property(key, value)
        return selector

    def _build(self) -> None:
        # Output half (stays PLAYING): selector → encode chain → mux → sink(s).
        self.selector = self._make_selector("sel")
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
            self.audio_selector = self._make_selector("asel")
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
        unit on a content-reload). Returns ``(video_src_pad, audio_src_pad, elements)``.

        F2 fix (hostile-review follow-up, 2026-09-06): a build failure partway
        through (e.g. ``_make``'s fail-loud ``pipeline.add`` check, item 1) used
        to leave whatever elements it HAD already added to the pipeline before
        the failure permanently leaked -- this method's own caller
        (``reload_program``, for a content-reload) has no ``pending`` entry to
        route the cleanup through at this point (that entry is only created
        AFTER this call succeeds), so the disposal has to happen right here,
        at the only place still holding a reference to ``collected``."""
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
        except Exception:
            self._dispose_elements_best_effort(collected)
            raise
        finally:
            self._collecting = None
        return out_pad, audio_out_pad, collected

    def _dispose_elements_best_effort(self, elements: list[Gst.Element]) -> None:
        """NULL + remove a list of elements from the pipeline, swallowing every
        error -- used from an already-failing build/link path (F2 fix) where
        raising a SECOND exception would replace the caller's real one. Mirrors
        ``_dispose_source_leg``'s element half but skips the pad/selector half
        (a caller here never got as far as linking anything to a selector)."""
        for element in elements:
            with contextlib.suppress(Exception):
                element.set_state(Gst.State.NULL)
        for element in elements:
            with contextlib.suppress(Exception):
                self.pipeline.remove(element)

    def _link_leg_to_selectors(
        self, label: str, out_pad: Gst.Pad | None, audio_out_pad: Gst.Pad | None
    ) -> tuple[Gst.Pad, Gst.Pad | None]:
        """Request selector sink pad(s) and link this leg's src pad(s) into them.
        Returns ``(video_sink_pad, audio_sink_pad | None)``; raises on a link failure.

        F2 fix (hostile-review follow-up, 2026-09-06): every raise path below now
        releases whatever selector request pad(s) IT ITSELF already requested
        before failing -- a partial failure (audio raises after video already
        linked, say) used to leave an orphaned, still-requested selector sink
        pad behind forever (a request pad is never automatically released; only
        ``release_request_pad`` frees it). The caller (``reload_program``) still
        disposes the LEG'S ELEMENTS on this raise (see its own try/except); this
        method is only responsible for pads IT requested."""
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
            self._release_selector_pad_best_effort(selector, sink_pad)
            raise RuntimeError(
                f"failed to link source {label!r} into selector (caps mismatch?): {exc}"
            ) from exc
        if not video_linked:
            self._release_selector_pad_best_effort(selector, sink_pad)
            raise RuntimeError(f"failed to link source {label!r} into selector (caps mismatch?)")

        audio_sink_pad = None
        audio_selector = self.audio_selector
        if audio_selector is not None:
            # A/V index alignment (audit CRITICAL): when audio is enabled EVERY
            # leg must carry audio so video pad N and audio pad N swap together —
            # a mixed graph would desync the selectors (wrong audio over wrong
            # video, the issue-#56 class).
            if audio_out_pad is None:
                self._release_selector_pad_best_effort(selector, sink_pad, linked_pad=out_pad)
                raise RuntimeError(f"audio is enabled but source {label!r} has no audio leg")
            audio_sink_pad = audio_selector.request_pad_simple("sink_%u")
            if audio_sink_pad is None or audio_out_pad.link(audio_sink_pad) != Gst.PadLinkReturn.OK:
                self._release_selector_pad_best_effort(selector, sink_pad, linked_pad=out_pad)
                self._release_selector_pad_best_effort(audio_selector, audio_sink_pad)
                raise RuntimeError(f"failed to link audio for source {label!r}")
        return sink_pad, audio_sink_pad

    @staticmethod
    def _release_selector_pad_best_effort(
        selector: Gst.Element, sink_pad: Gst.Pad | None, *, linked_pad: Gst.Pad | None = None
    ) -> None:
        """Unlink (if ``linked_pad`` proves it was actually linked) and release
        one selector request pad, swallowing any error -- called only from an
        already-failing path, so this must never raise a SECOND exception that
        would replace the caller's real one."""
        if sink_pad is None:
            return
        with contextlib.suppress(Exception):
            if linked_pad is not None:
                linked_pad.unlink(sink_pad)
            selector.release_request_pad(sink_pad)

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
            # Mirrors the ENG-009 containment above, but for a still-settling
            # graphics-overlay layer swap (e.g. a reloaded lower-third banner PNG
            # that fails to decode): an async error on the NOT-YET-COMMITTED new
            # layer chain must abort only that swap, never take the channel off air.
            overlay_layer_name = self._belongs_to_pending_overlay_swap(message.src)
            if overlay_layer_name is not None:
                err, _debug = message.parse_error()
                print(
                    f"CTRL graphics-overlay reload for layer {overlay_layer_name!r} aborted: "
                    f"new layer errored before commit: {err}",
                    flush=True,
                )
                self._abort_pending_overlay_swap(overlay_layer_name, reason="error")
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
            # STDERR, not stdout (Gate A T4 visibility fix): the daemon reads the
            # worker's stderr tail into ``last_error`` when the child exits non-zero,
            # so the reason a channel bounced is on the operator's state row instead
            # of only in an uncollected stdout log.
            print(
                # ASCII only: the daemon folds this line into the state row's
                # last_error, which is written to Postgres. A non-ASCII byte here
                # is re-read as U+FFFD (_child_stderr_tail reads errors="replace")
                # and a non-UTF8 client_encoding then fails the whole state write
                # -- see _child_stderr_tail's sanitiser and the T6 soak evidence
                # (soak-120-e502074-20260905).
                f"CTRL stall: no output for {int(self.stall_timeout_s)}s - quitting for daemon restart",
                file=sys.stderr,
                flush=True,
            )
            self._error = ("stall", "output stalled")  # → worker exits non-zero → restart
            if self._loop is not None:
                self._loop.quit()
            return False  # one-shot: stop the watchdog
        return True

    def _await_playing(self) -> None:
        """Bounded wait for the PLAYING transition so a wedged preroll can't hang the
        run loop before the time-bounded teardown could ever run (audit M1).

        Item 82 (sandbox run 13 evidence): a fresh worker under CPU load took
        longer than the old hard-coded 5.0s bound (``teardown_timeout_s``, which
        was never meant to double as a preroll bound) to reach PLAYING, and the
        daemon treated the resulting crash as an ordinary one — a relaunch storm
        against a source that was never actually broken. This now:

        * waits up to ``self.preroll_timeout_s`` (30s default, configurable —
          see ``_resolve_preroll_timeout_s``), polling in
          ``_PREROLL_POLL_INTERVAL_S``-second slices rather than blocking on one
          ``get_state`` call for the whole bound, so a slow-but-progressing
          preroll is VISIBLE on stderr instead of silent until it either
          finishes or the bound is hit;
        * raises the distinct ``PrerollTimeoutError`` (not a bare
          ``RuntimeError``) only once the bound is actually exceeded, so
          ``worker.py`` can exit with a distinct code and the daemon's relaunch
          path can tell a slow start apart from a genuine crash.
        """
        started = time.monotonic()
        deadline = started + self.preroll_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            slice_s = (
                remaining if remaining < _PREROLL_POLL_INTERVAL_S else _PREROLL_POLL_INTERVAL_S
            )
            result, current, pending = self.pipeline.get_state(int(max(slice_s, 0.0) * Gst.SECOND))
            if result in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.NO_PREROLL):
                # Round-2 review BLOCKER (Opus, PR #183, item 1): this line is the
                # ONLY genuine evidence that the pipeline actually reached PLAYING
                # (real output, not merely "the process hasn't exited yet"). The
                # daemon's alive-poll path (``EgressDaemon._poll_process``) used to
                # reset the crash-loop streak on wall-clock seconds since SPAWN,
                # which also counts interpreter start + ``import gi``/``Gst.init``
                # + graph build + this very preroll wait -- none of which is air.
                # Under load that non-air overhead alone can exceed the daemon's
                # 60s healthy-uptime reset threshold, so a worker that has NEVER
                # once reached PLAYING could still get its crash streak reset
                # every cycle (measured: streak stuck at 1, never escalates to
                # fallback slate in 40 cycles). The daemon now greps this exact
                # marker out of the worker's stderr log
                # (``civiccast.egress.health.worker_reached_playing``) and only
                # starts the 60s healthy-uptime clock from the moment it is
                # first observed -- see ``EgressDaemon._poll_process``. ASCII
                # only + a stable prefix: this text is a parsed contract, not
                # just a log line -- changing it silently breaks the daemon's
                # match.
                # Round-4 (PR #183 review, BLOCKER reproduced): the marker
                # now also carries THIS worker's own pid. The daemon's
                # per-channel stderr log is opened in APPEND mode and never
                # truncated per spawn (see ``_default_worker_launcher`` /
                # ``start_ffmpeg``), so a fixed marker string alone let a
                # PREVIOUS worker's own "reached PLAYING" line satisfy a
                # brand-new worker's on-air-evidence check the moment it was
                # spawned. The daemon's primary defense is now anchoring the
                # scan to bytes at or after ITS OWN spawn point
                # (``EgressDaemon._stderr_spawn_offset``); this pid is a
                # second, independent check
                # (``civiccast.egress.health.worker_reached_playing``'s
                # ``expected_pid``) that holds even if the byte offset is
                # ever wrong.
                print(
                    f"CTRL preroll: reached PLAYING after {time.monotonic() - started:.1f}s "
                    f"pid={os.getpid()}",
                    file=sys.stderr,
                    flush=True,
                )
                return
            if result == Gst.StateChangeReturn.FAILURE:
                # Not a slow preroll -- the pipeline itself failed. Distinct from
                # the timeout case: this is a real construction/link problem, not
                # something a slow-start retry would ever recover from.
                raise RuntimeError(
                    f"pipeline failed while waiting for PLAYING (get_state={result.value_nick})"
                )
            now = time.monotonic()
            if now >= deadline:
                raise PrerollTimeoutError(
                    f"pipeline did not reach PLAYING within {self.preroll_timeout_s}s "
                    f"(get_state={result.value_nick})"
                )
            # Round-2 review, item 3: log the CURRENT state too, not just the
            # get_state result and the pending state -- ``current`` is what
            # actually tells an operator whether the pipeline is stuck in
            # NULL/READY (never really started) vs PAUSED (genuinely
            # prerolling, just slowly) while it waits.
            print(
                f"CTRL preroll: still waiting for PLAYING after "
                f"{self.preroll_timeout_s - (deadline - now):.1f}s of "
                f"{self.preroll_timeout_s:.1f}s (get_state={result.value_nick}, "
                f"current={current.value_nick}, pending={pending.value_nick})",
                file=sys.stderr,
                flush=True,
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

    @staticmethod
    def _write_reload_status(channel_dir: Path, *, reload_id: str, result: str) -> None:
        """POSIX FIFO counterpart of ``worker.py``'s ``_write_reload_status``
        (the Windows D2 pipe dispatch's identical helper) -- writes the SAME
        ``<channel_dir>/reload-status.json`` file ``EgressDaemon._poll_reload_
        settlement`` polls, so a reload's eventual settle outcome is reported
        the same way regardless of which control-channel transport dispatched
        it. Atomic write (tmp + replace); best-effort (a write hiccup must
        never crash the channel -- the daemon's own deadline is the backstop
        if a status update never arrives at all)."""
        status_path = channel_dir / "reload-status.json"
        tmp_path = status_path.with_name(status_path.name + ".tmp")
        payload = json.dumps({"id": reload_id, "result": result, "ts": time.time()})
        try:
            tmp_path.write_text(payload, encoding="utf-8")
            tmp_path.replace(status_path)
        except OSError as exc:
            print(f"WARN: failed to write reload-status.json: {exc!r}", flush=True)

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
                reload_path = Path(command[1])
                channel_dir = reload_path.parent
                reload_id = reload_id_from_sidecar_path(command[1])
                with reload_path.open(encoding="utf-8") as handle:
                    new_graph = graph_from_json(handle.read())
                with contextlib.suppress(OSError):
                    reload_path.unlink()  # one-shot graph file: consume it after read

                # Hostile-review follow-up (2026-09-06): the POSIX FIFO path used
                # to call reload_program with no ``on_settled`` at all, so a
                # reload dispatched here NEVER reported its eventual commit/abort
                # -- the daemon's ``_poll_reload_settlement`` would wait out the
                # full 960s deadline and fall back to restart even for a reload
                # that landed perfectly. Write the SAME ``reload-status.json``
                # file the Windows D2 pipe seam's worker.py writes (using the
                # reload id embedded in this sidecar's own filename -- the FIFO
                # has no separate envelope/ack id field to carry the daemon's
                # own id, see ``reload_policy.reload_id_from_sidecar_path``),
                # so the daemon can observe settlement on this platform too.
                def _on_settled(
                    committed: bool,
                    reason: str | None,
                    _channel_dir: Path = channel_dir,
                    _reload_id: str = reload_id,
                ) -> None:
                    result = "applied" if committed else f"aborted:{reason or 'unknown'}"
                    self._write_reload_status(_channel_dir, reload_id=_reload_id, result=result)

                self.reload_program(
                    new_graph.sources[0],
                    switch_at_end_of_current=reload_switch_is_deferred(command[1]),
                    on_settled=_on_settled,
                )
                # BLOCKER fix: a content-reload must also re-apply the graphics-overlay
                # leg (station bug / lower-third) from the SAME reloaded graph — reload
                # used to rebuild only the program leg and silently drop
                # new_graph.graphics_overlay (see reload_graphics_overlay's docstring).
                self.reload_graphics_overlay(new_graph.graphics_overlay)
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

    def reload_program(
        self,
        new_leg: SourceLeg | PlaylistLeg,
        *,
        switch_at_end_of_current: bool = False,
        on_settled: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        """Replace the program leg (source index 0) with ``new_leg`` seamlessly.

        Builds the new leg on the live PLAYING pipeline and prerolls it. The switch
        point depends on ``switch_at_end_of_current`` (B3 fix, kit 4b30c99 soak
        evidence):

        * ``False`` (default, unchanged behavior) — switches the selector(s) to the
          new leg on its FIRST BUFFER (via a pad probe → main-loop idle, so the run
          loop is never blocked waiting on preroll). This is correct for a
          FALLBACK_SLATE gap-replan (issue #157: filler must be interrupted the
          moment a due program is ready) and for an operator-initiated live
          takeover / forced slate (a deliberate "now").
        * ``True`` — a BOUNDARY-ALIGNED switch. The new leg is built and prerolled
          exactly far enough to prove it decodes (its first buffer), then HELD
          there by a blocking pad probe on its own tail src pad; the switch happens
          at the outgoing leg's own end, so the currently-airing item plays out to
          its natural end with no re-decode and no jump. Used for automation's
          seamless plan-rollover reload
          (``ChannelAutomationService._check_plan_rollover``), which is triggered
          well before the live plan's projected end specifically so the new leg has
          time to be ready and WAIT rather than cut in early and truncate the
          still-airing item.

          Three mechanisms make that switch seamless; all three are load-bearing
          and all three were verified against the bundled GStreamer 1.28 runtime
          (``tests/egress/test_gst_engine_wsl.py::
          test_deferred_rollover_switches_at_the_boundary_without_eos``):

          1. **The outgoing leg's EOS is DROPPED, not observed.** ``input-selector``
             forwards EOS from its ACTIVE sink pad straight downstream, so an
             observe-only probe (``PAD_PROBE_REMOVE``/``PASS``) lets EOS reach the
             encoder → ``mpegtsmux`` → the bus, and the run loop quits *before* any
             ``GLib.idle_add`` commit can run — the channel goes STOPPED at every
             single boundary, deterministically. ``_on_outgoing_pad_data`` returns
             ``Gst.PadProbeReturn.DROP`` instead, so the selector never sees the
             EOS at all (it is therefore also never latched as that pad's EOS
             state) and no pipeline-level EOS is ever produced.
          2. **BOTH outgoing pads are probed.** The audio selector's active sink
             pad EOSes independently of video's; an unhandled audio EOS latches the
             mux's audio pad and every post-switch audio buffer is refused. Video
             and audio each get the same drop-probe, and the commit fires on
             whichever end arrives first.
          3. **The new leg's running time is rebased onto the old leg's end.** A
             freshly built leg starts at running time ~0 while the pipeline is
             hours in; without a rebase the output timeline jumps backwards at the
             switch (PCR/PTS discontinuity). ``_commit_reload`` reads the exact end
             running time of the outgoing pad's LAST buffer (``pts + duration`` in
             that pad's own segment — clock-independent, so it is right whether or
             not the sinks pace the pipeline) and applies it with
             ``Gst.Pad.set_offset`` on the new leg's tail src pad. That marks the
             leg's sticky ``SEGMENT`` for re-send, so when the hold probe is
             released the selector receives (and forwards) a segment whose ``base``
             is the old leg's end and output running time continues monotonically
             across the boundary. Setting the offset on the SELECTOR's sink pad
             instead does NOT work — the segment has already crossed that pad by
             then and the stored copy is not rewritten.

          The hold probe is also what bounds the cost of preparing early. A leg
          held for the whole (up to ``defer_switch_timeout_s``) wait decodes one
          buffer plus whatever ``decodebin``'s internal multiqueue admits, then
          blocks its own streaming thread. Without it the leg keeps decoding for
          the entire wait, and the selector throws every frame away. Measured on
          HALO over a 40 s wait, a real 360p H.264 rollover payload behind a
          640x360 channel (three runs each, worker process tree):

              channel alone            5.09 / 5.53 / 6.45 s CPU, RSS +0.3 MiB
              new leg HELD             5.75 / 5.88 / 6.02 s CPU, RSS +52 MiB
              new leg free-running     7.47 / 8.19 / 8.73 s CPU, RSS +57 MiB

          i.e. the held leg's CPU cost sits inside the channel's own run-to-run
          spread while the unheld one adds ~40%, on content chosen to be cheap;
          the saving scales with the payload's decode cost, so a 1080p rollover
          is where it stops being a rounding error. Note it is a CPU saving, not
          a memory one -- the leg's elements and decoder are allocated either
          way. Note also what the unheld case is NOT: ``sync-streams`` (see
          ``_SELECTOR_PROPS``) already paces an inactive pad against the active
          stream, so the old behaviour was a second real-time decode leg, not an
          unbounded burn through the file.

        The reload can never wedge the channel (the engine's "playout can never wedge"
        invariant). Escape hatches cover every way a switch might not happen: (a) a
        bounded watchdog aborts the reload if the new leg never delivers a first
        buffer (a live source that connects but never rolls); (b) a synchronous
        build/preroll failure aborts cleanly and re-raises (the current program keeps
        playing); (c) an async bus error on the uncommitted new leg aborts via
        ``_on_bus`` rather than taking output down; (d) for a deferred switch, a
        second, much longer watchdog (``defer_switch_timeout_s``) forces the switch
        anyway if the outgoing leg's EOS never arrives (a schedule item that runs
        long, or a leg that never naturally EOSes) — the reload always eventually
        commits, it never holds two legs open forever. A newer reload arriving while
        one is still settling SUPERSEDES it (the old in-flight leg is aborted) — a
        due program is never silently dropped.

        ``on_settled`` (item 4, honest ack): an optional ``(committed: bool,
        reason: str | None) -> None`` callback invoked EXACTLY ONCE for this
        specific call's reload -- with ``(True, None)`` from ``_commit_reload``, or
        ``(False, <reason>)`` from ``_abort_pending_reload`` (``reason`` is one of
        "error"/"timeout"/"superseded"/"build-error"/"selector-missing"). This is
        the whole point of the fix: this method itself only ARMS the reload (builds
        + prerolls the new leg and returns) -- the actual commit/abort happens later,
        asynchronously, on the main loop. The D2 Windows worker-pipe dispatch
        (``worker.py``'s ``_dispatch_control_with_ack``) used to ack a ``reload``
        command "applied" the instant this method RETURNED, which is not the same
        thing as the reload having landed -- a channel could be told "applied" for a
        reload that then silently timed out or errored. Passing ``on_settled`` lets
        that dispatch path defer its ack until the reload genuinely lands one way or
        the other. A caller that does not pass it (the POSIX FIFO dispatch path,
        ``_dispatch_control``, which was always fire-and-forget) is unaffected."""
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
        # F2 fix: ``_instantiate_source_leg`` already disposes ITS OWN partial
        # build on a raise (its own try/except); this second layer covers the
        # remaining leak window -- ``_link_leg_to_selectors`` raising AFTER
        # instantiate already succeeded, which would otherwise leave a fully
        # built, still-in-the-pipeline (but never-linked-anywhere) leg behind
        # with nothing left holding a reference to it.
        new_elements: list[Gst.Element] = []
        try:
            out_pad, audio_out_pad, new_elements = self._instantiate_source_leg(new_leg)
            new_video_pad, new_audio_pad = self._link_leg_to_selectors(
                "program(reload)", out_pad, audio_out_pad
            )
        except Exception:
            self._dispose_elements_best_effort(new_elements)
            raise
        pending: dict[str, Any] = {
            "new_video_pad": new_video_pad,
            "new_audio_pad": new_audio_pad,
            "old_video_pad": old_video_pad,
            "old_audio_pad": old_audio_pad,
            "old_elements": old_elements,
            "new_elements": new_elements,
            "probe_id": None,
            "timeout_id": None,
            # Item 4 (honest ack): the caller's completion callback, if any --
            # invoked exactly once by ``_commit_reload`` or ``_abort_pending_reload``.
            "on_settled": on_settled,
            # B3 fix: deferred-switch bookkeeping. "ready"/"eos" both default to
            # True for an immediate switch (switch_at_end_of_current=False), so
            # the `ready and eos` gate reduces to "ready" alone -- committing the
            # instant the new leg's first buffer lands, exactly the pre-existing
            # behavior.
            "switch_at_end_of_current": switch_at_end_of_current,
            "new_leg_ready": False,
            "old_leg_eos": not switch_at_end_of_current,
            "defer_timeout_id": None,
            # Boundary-aligned switch state (deferred reloads only):
            #   new_src_pads   -- the new leg's own tail src pad(s) (video, audio).
            #                     These carry the hold probes AND the running-time
            #                     rebase (Gst.Pad.set_offset), NOT the selector's
            #                     sink pads -- see the docstring, mechanism 3.
            #   hold_probes    -- (pad, probe_id) blocking probes holding the new
            #                     leg at its first buffer.
            #   holds_awaited  -- how many hold probes have not yet fired; the leg
            #                     is "ready" only when EVERY stream has decoded.
            #   boundary_probes-- (pad, probe_id) drop-probes on the OUTGOING pads.
            #   outgoing_end   -- per outgoing pad: running time of the end of its
            #                     last buffer, and the pad's cached segment.
            "new_src_pads": [pad for pad in (out_pad, audio_out_pad) if pad is not None],
            "hold_probes": [],
            "holds_awaited": 0,
            "boundary_probes": [],
            "outgoing_end": {},
        }
        # A clock-timed (live) new leg is ALREADY on the pipeline's running-time
        # base and cannot be paused without going stale, so it is never held and
        # never rebased -- see graph.CLOCK_TIMED_SOURCE_FACTORIES. It still gets
        # the deferred switch and, critically, the outgoing EOS drop below.
        pending["rebase_new_leg"] = switch_at_end_of_current and not source_leg_is_clock_timed(
            new_leg
        )
        self._pending_reload = pending
        try:
            if switch_at_end_of_current:
                # Watch BOTH outgoing pads (video AND audio -- an unhandled audio
                # EOS latches the mux's audio pad just as fatally as a video one
                # takes the whole pipeline down): track each pad's last-buffer end
                # running time (the rebase reference) and DROP its EOS, so no
                # pipeline-level EOS is ever produced at the boundary. Armed for
                # EVERY deferred switch, clock-timed new leg or not.
                for pad in (old_video_pad, old_audio_pad):
                    if pad is None:
                        continue
                    probe_id = pad.add_probe(
                        Gst.PadProbeType.BUFFER | Gst.PadProbeType.EVENT_DOWNSTREAM,
                        self._on_outgoing_pad_data,
                    )
                    pending["boundary_probes"].append((pad, probe_id))
            if pending["rebase_new_leg"]:
                # ENG-002 (boundary form): hold the new leg AT its first buffer.
                # BLOCK|BUFFER lets the sticky STREAM_START/CAPS/SEGMENT through
                # (so the leg is fully linked and negotiated) but blocks the very
                # first buffer, which is both the readiness proof AND the point
                # decoding stops. Armed BEFORE PLAYING so no buffer can slip past.
                for pad in pending["new_src_pads"]:
                    probe_id = pad.add_probe(
                        Gst.PadProbeType.BLOCK | Gst.PadProbeType.BUFFER,
                        self._on_new_leg_hold,
                    )
                    pending["hold_probes"].append((pad, probe_id))
                    pending["holds_awaited"] += 1
            else:
                # No hold: readiness is the new leg's first buffer AT the selector,
                # exactly as the immediate path (and as every reload did before the
                # boundary-aligned switch existed). For a deferred switch this only
                # marks the leg ready -- the commit still waits for the boundary.
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
        # Streaming thread: hand the readiness update to the main loop (no state
        # changes here).
        GLib.idle_add(self._on_new_leg_ready)
        return Gst.PadProbeReturn.REMOVE

    def _on_new_leg_ready(self) -> bool:
        """Main-loop: the new leg's first buffer landed. Cancels the
        new-leg-readiness watchdog (it has done its job); for a deferred switch,
        arms the longer ``defer_switch_timeout_s`` safety watchdog instead of
        committing immediately, and waits for the outgoing leg's EOS."""
        pending = self._pending_reload
        if pending is None:
            return False  # aborted or superseded before the first buffer landed
        if pending["timeout_id"] is not None:
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["timeout_id"])
            pending["timeout_id"] = None
        pending["new_leg_ready"] = True
        if pending["switch_at_end_of_current"] and not pending["old_leg_eos"]:
            pending["defer_timeout_id"] = GLib.timeout_add_seconds(
                max(1, int(self.defer_switch_timeout_s)), self._on_defer_switch_timeout
            )
            return False
        self._commit_reload()
        return False

    def _on_new_leg_hold(self, pad: Gst.Pad, _info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        """Streaming thread, deferred switch: the new leg produced its first buffer
        on ``pad``. Returning from a BLOCK probe leaves the pad BLOCKED (and the
        callback is not re-entered until the probe is removed), which is exactly
        what is wanted: the buffer proves the leg really decodes, and the block
        stops it decoding any further until ``_commit_reload`` releases it. The
        readiness bookkeeping is handed to the main loop -- this thread is now
        parked inside GStreamer and must touch no engine state."""
        pending = self._pending_reload
        if pending is not None:
            for held_pad, _probe_id in pending["hold_probes"]:
                if held_pad is pad:
                    GLib.idle_add(self._on_hold_probe_engaged)
                    break
        return Gst.PadProbeReturn.OK

    def _on_hold_probe_engaged(self) -> bool:
        """Main-loop: one of the deferred reload's streams reached (and is now
        holding at) its first buffer. The leg counts as ready only once EVERY
        stream has -- a video-only readiness signal would let the commit fire
        while the audio leg has not decoded a single frame."""
        pending = self._pending_reload
        if pending is None:
            return False
        pending["holds_awaited"] = max(0, pending["holds_awaited"] - 1)
        print(
            "CTRL reload: new leg stream held at its first buffer "
            f"({pending['holds_awaited']} stream(s) still to preroll)",
            flush=True,
        )
        if pending["holds_awaited"] == 0 and not pending["new_leg_ready"]:
            self._on_new_leg_ready()
        return False

    @staticmethod
    def _buffer_end_running_time(
        pad: Gst.Pad, buffer: Gst.Buffer, segment: Any
    ) -> tuple[int, Any] | None:
        """``(running time just past this buffer's end, segment used)``, or None if
        it cannot be computed. ``segment`` is the caller's cached segment for the
        pad; the pad's sticky SEGMENT is consulted when that cache is cold, because
        a probe armed on an ALREADY-RUNNING pad missed the event itself (the
        outgoing leg has been airing for a while by the time a reload arms this)."""
        if segment is None:
            sticky = pad.get_sticky_event(Gst.EventType.SEGMENT, 0)
            if sticky is None:
                return None
            segment = sticky.parse_segment()
        if buffer.pts == Gst.CLOCK_TIME_NONE:
            return None
        running = segment.to_running_time(Gst.Format.TIME, buffer.pts)
        if running == Gst.CLOCK_TIME_NONE or running < 0:
            return None
        duration = buffer.duration if buffer.duration != Gst.CLOCK_TIME_NONE else 0
        return int(running) + int(duration), segment

    def _on_outgoing_pad_data(self, pad: Gst.Pad, info: Gst.PadProbeInfo) -> Gst.PadProbeReturn:
        """Streaming thread, deferred switch: everything that crosses an OUTGOING
        selector sink pad while the boundary is pending.

        * BUFFER -- record the running time of this buffer's END. That value (not
          the pipeline clock) is the rebase reference the new leg's running time
          continues from, so the seam is correct whether or not the sinks pace the
          pipeline.
        * EOS -- the boundary. DROP it: ``input-selector`` forwards an ACTIVE pad's
          EOS straight downstream to the encoder/mux/bus, which quits the run loop
          before any commit scheduled on the main loop could run (this is the exact
          defect this method exists to close). Dropping also keeps the selector from
          latching the pad as EOS'd. The probe deliberately STAYS installed (DROP,
          not REMOVE) so the OTHER stream's later EOS is dropped too, and the
          drop is UNCONDITIONAL -- it does not consult ``_pending_reload``. This
          probe only ever lives on a pad whose leg is being retired, and the
          window that matters is precisely the one where the reload has just
          committed (``_pending_reload`` back to None) but the old leg has not
          finished being disposed: an audio EOS arriving in THAT window is the
          one that would otherwise still take the channel off air.
        * anything else -- untouched.
        """
        pending = self._pending_reload
        if info.type & Gst.PadProbeType.BUFFER:
            if pending is None:
                return Gst.PadProbeReturn.OK
            state = pending["outgoing_end"].setdefault(pad, {"end": None, "segment": None})
            buffer = info.get_buffer()
            if buffer is not None:
                computed = self._buffer_end_running_time(pad, buffer, state["segment"])
                if computed is not None:
                    state["end"], state["segment"] = computed
            return Gst.PadProbeReturn.OK
        event = info.get_event()
        if event is None:
            return Gst.PadProbeReturn.OK
        if event.type == Gst.EventType.EOS:
            GLib.idle_add(self._on_old_leg_eos)
            return Gst.PadProbeReturn.DROP
        if event.type == Gst.EventType.SEGMENT and pending is not None:
            state = pending["outgoing_end"].setdefault(pad, {"end": None, "segment": None})
            state["segment"] = event.parse_segment()
        return Gst.PadProbeReturn.OK

    def _on_old_leg_eos(self) -> bool:
        """Main-loop: the outgoing leg reached its own natural end. Commits now if
        the new leg is already ready; otherwise just records it -- the reload was
        triggered well before this point specifically so the new leg should already
        be ready, but if the schedule/preparer ran unexpectedly long the commit
        still waits for genuine readiness rather than switching to a leg with
        nothing buffered yet.

        Known residual, disclosed rather than papered over: in THAT ordering the
        outgoing leg has ended and its EOS has been dropped, so nothing is feeding
        the selector until the new leg becomes ready. Output freezes for the gap.
        If readiness never comes at all, ``_on_reload_timeout`` disposes the new leg
        and the frozen old one stays active -- at which point the S9-5 stall
        watchdog (``stall_timeout_s``, 10s) sees output stop advancing and quits so
        the daemon restarts the channel to a known state. A bounded freeze then a
        restart is the fail-safe end of this path; the alternative (forwarding the
        EOS) is an immediate, unconditional restart at EVERY boundary, which is the
        defect. Closing the gap properly means switching to slate for the interval,
        which is a separate change."""
        pending = self._pending_reload
        if pending is None:
            return False  # aborted or superseded before this fired
        pending["old_leg_eos"] = True
        if pending["new_leg_ready"]:
            self._commit_reload()
        return False

    def _on_defer_switch_timeout(self) -> bool:
        """Safety watchdog (B3 fix): the outgoing leg's EOS never arrived within
        ``defer_switch_timeout_s`` of the new leg becoming ready. Force the switch
        rather than hold two legs open indefinitely -- the reload always eventually
        commits."""
        pending = self._pending_reload
        if pending is None or not pending["switch_at_end_of_current"]:
            return False  # already committed/aborted, or not a deferred reload
        pending["defer_timeout_id"] = None
        if pending["old_leg_eos"]:
            return False  # EOS + commit already landed via the normal path
        print(
            f"CTRL reload: outgoing leg produced no EOS within "
            f"{max(1, int(self.defer_switch_timeout_s))}s of the new leg being ready; "
            "forcing the switch",
            flush=True,
        )
        pending["old_leg_eos"] = True
        self._commit_reload()
        return False  # one-shot

    def _arm_commit_watchdog(self) -> threading.Timer:
        """Item 85 (sandbox runs 12/14/15): ``_commit_reload`` must never be able to
        hang the worker forever. Seven soaks recorded the SAME wedge: the last line
        either worker ever printed was "boundary switch rebased...", then nothing --
        the process stayed alive but the pipe control reader stopped answering
        (the ordering bug this item fixes; see ``_commit_reload``'s reordering and
        ``_dispose_source_leg``'s unlink-before-NULL change).

        A ``GLib.timeout_add_seconds`` source is USELESS as the sole guard here: if
        the wedge is (as measured) the GLib main-loop thread itself blocked inside a
        synchronous GStreamer call (``Gst.Element.set_state``/``get_state`` in
        ``_dispose_source_leg``), the main loop never gets a turn to run ANY of its
        own timeout sources -- the same thread is stuck. Only a real OS-level
        thread, independent of the GLib loop, is guaranteed to fire regardless of
        what the main-loop thread is doing. Cancelled by the caller once
        ``_commit_reload`` actually returns; a commit that finishes in time never
        prints anything from this thread and never calls ``os._exit``."""

        def _on_commit_wedged() -> None:
            print(
                "CTRL reload: commit did not finish within "
                f"{self.commit_timeout_s:.0f}s - quitting for daemon restart",
                file=sys.stderr,
                flush=True,
            )
            self._error = ("reload-commit-timeout", "commit did not complete in time")
            # Best-effort, bounded attempt at a graceful pipeline teardown -- never
            # awaited: ``set_state`` itself does not block (only ``get_state``
            # does), so this cannot turn into a second wedge on this watchdog
            # thread. If the main thread is genuinely stuck inside GStreamer, this
            # request may never be serviced either; the os._exit below is what
            # actually guarantees the process goes away.
            with contextlib.suppress(Exception):
                self.pipeline.set_state(Gst.State.NULL)
            os._exit(int(GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE))

        timer = threading.Timer(max(1.0, self.commit_timeout_s), _on_commit_wedged)
        timer.daemon = True
        timer.start()
        return timer

    def _commit_reload(self) -> bool:
        """Main-loop commit of a reload: switch the selector(s) to the prerolled new
        leg, repoint role index 0 at it, then dispose the old leg. A no-op if the
        reload was aborted/superseded before this fired. ``return False`` so a GLib
        timeout/idle source that calls this directly runs once.

        Item 85 root-cause fix: the hold probes on the new leg's tail pad(s) are
        released BEFORE the selector's ``active-pad`` is ever touched -- the exact
        invariant ``_abort_pending_reload`` already documents ("a held pad has a
        GStreamer streaming thread parked inside the blocking probe... releasing
        first lets those threads unwind normally") but this method used to violate:
        it switched ``active-pad`` onto the new leg, THEN released its holds, THEN
        disposed the old leg -- so the old leg's streaming thread could end up
        parked inside input-selector's ``sync-streams`` pacing wait (paced against
        the now-active new pad, which had not yet been allowed to produce anything)
        at the exact moment ``_dispose_source_leg`` called the old leg's elements'
        synchronous ``set_state(NULL)``, wedging the GLib main-loop thread inside
        that call forever -- the seven-soak failure this whole item exists to fix.
        Wrapped in a real-OS-thread watchdog (``_arm_commit_watchdog``) as the
        backstop for a wedge this reordering does not anticipate."""
        pending = self._pending_reload
        if pending is None:
            return False  # aborted or superseded before the first buffer landed
        watchdog = self._arm_commit_watchdog()
        try:
            return self._commit_reload_body(pending)
        finally:
            watchdog.cancel()

    def _commit_reload_body(self, pending: dict[str, Any]) -> bool:
        for timeout_key in ("timeout_id", "defer_timeout_id"):
            if pending[timeout_key] is not None:
                with contextlib.suppress(Exception):
                    GLib.source_remove(pending[timeout_key])
        new_video_pad = pending["new_video_pad"]
        new_audio_pad = pending["new_audio_pad"]
        selector = self.selector
        if selector is None:
            self._abort_pending_reload("selector-missing")
            return False
        if pending["rebase_new_leg"]:
            # Rebase the held leg onto the outgoing leg's end BEFORE anything of it
            # crosses the selector (mechanism 3 in reload_program's docstring).
            # ONE offset for both streams -- the max of the two outgoing ends -- so
            # neither video nor audio can start EARLIER than where its own stream
            # stopped: a backwards step is what breaks PCR/CC, whereas a sub-frame
            # forward step is absorbed by the mux.
            observed = [
                state["end"]
                for state in pending["outgoing_end"].values()
                if state["end"] is not None
            ]
            switch_running_time = (
                max(observed)
                if observed
                # No buffer was ever observed on the outgoing pads (a leg that
                # EOS'd immediately, or a forced switch before any buffer): fall
                # back to the pipeline's own running time. Never 0 -- that would
                # rewind the output timeline by the whole uptime.
                else self._pipeline_running_time_ms() * int(Gst.MSECOND)
            )
            for pad in pending["new_src_pads"]:
                # NB: the leg's OWN tail src pad, not the selector's sink pad --
                # set_offset there marks the leg's sticky SEGMENT for re-send, so
                # the selector receives a segment whose base is the old leg's end.
                # On the selector's sink pad the segment has already crossed and
                # the stored copy is not rewritten (measured, GStreamer 1.28.5).
                with contextlib.suppress(Exception):
                    pad.set_offset(switch_running_time)
            print(
                "CTRL reload: boundary switch rebased to running time "
                f"{switch_running_time / Gst.SECOND:.3f}s",
                flush=True,
            )
        print("CTRL reload: switching selector", flush=True)
        # Item 85 root-cause fix: release the new leg's hold probes BEFORE the
        # selector's active-pad is touched at all -- NOT last, as this method used
        # to. A held pad has a GStreamer streaming thread parked inside the
        # blocking probe (mirrors ``_abort_pending_reload``'s identical invariant);
        # releasing it first lets that thread unwind and start delivering buffers
        # normally (input-selector silently drops what arrives on a non-active
        # pad -- releasing before the switch is NOT a functional no-op, it is what
        # keeps the leg's own streaming thread from ever blocking on
        # ``sync-streams`` pacing against a switch that has not happened yet). Only
        # once that thread is free do we actually flip ``active-pad``.
        self._release_hold_probes(pending)
        print("CTRL reload: holds released", flush=True)
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
        print("CTRL reload: old leg disposed", flush=True)
        # Only NOW may the outgoing pads' EOS-drop probes go: the retiring leg can
        # still emit an EOS (the audio stream typically ends a beat after video)
        # right up until it is unlinked and NULLed, and one that escaped between
        # the commit above and this line would take the channel off air just as
        # surely as one at the boundary itself.
        for pad, probe_id in pending["boundary_probes"]:
            with contextlib.suppress(Exception):  # probe may already have auto-removed
                pad.remove_probe(probe_id)
        # Element count proves disposal reclaimed (the POSIX leak test asserts it is flat
        # across many reloads — a dispose leak would grow it).
        print(f"CTRL reload committed (elements={self._element_count()})", flush=True)
        # Item 4 (honest ack): tell the caller the reload actually landed. Fired
        # last, after every other commit side-effect, and guarded so a callback
        # failure (e.g. the worker's pipe write) can never re-wedge a reload that
        # has, in every other respect, already committed cleanly.
        on_settled = pending["on_settled"]
        if on_settled is not None:
            with contextlib.suppress(Exception):
                on_settled(True, None)
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
        for pad, probe_id in pending["boundary_probes"]:
            with contextlib.suppress(Exception):
                pad.remove_probe(probe_id)
        # MUST run before _dispose_source_leg below: a held pad has a GStreamer
        # streaming thread parked inside the blocking probe, and tearing the leg
        # down around a still-installed block is how a "disposal" turns into a
        # wedge. Releasing first lets those threads unwind normally.
        self._release_hold_probes(pending)
        if pending["timeout_id"] is not None and reason != "timeout":
            # 'timeout' means the watchdog source is firing now (auto-removed on return).
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["timeout_id"])
        if pending["defer_timeout_id"] is not None:
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["defer_timeout_id"])
        self._dispose_source_leg(
            pending["new_video_pad"], pending["new_audio_pad"], pending["new_elements"]
        )
        # Item 4 (honest ack): tell the caller this reload did NOT land, and why --
        # ``reason`` is one of "error"/"timeout"/"superseded"/"build-error"/
        # "selector-missing" (the strings each call site above passes).
        on_settled = pending["on_settled"]
        if on_settled is not None:
            with contextlib.suppress(Exception):
                on_settled(False, reason)

    @staticmethod
    def _release_hold_probes(pending: dict[str, Any]) -> None:
        """Remove the blocking probes holding a deferred reload's new leg, letting
        its streaming thread(s) run again. Idempotent (the list is emptied), and
        best-effort per pad -- a leg must never stay wedged because one probe id
        was already gone."""
        for pad, probe_id in pending["hold_probes"]:
            with contextlib.suppress(Exception):
                pad.remove_probe(probe_id)
        pending["hold_probes"] = []

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
        """Tear down a now-inactive source leg: FLUSH + unlink from the selector(s)
        and release the request pad(s) BEFORE NULLing its elements, then remove
        them. Best-effort — a disposal hiccup is logged, never raised, so it can't
        kill a live channel. (Without this a 24/7 channel would leak a leg's
        elements on every program change.)

        Item 85 root-cause fix: unlink + release_request_pad now run BEFORE
        ``set_state(Gst.State.NULL)``, not after. The old ordering called
        ``set_state(NULL)`` on a leg's elements while that leg's streaming thread
        could still be parked inside input-selector's own sink-pad wait (paced
        against the sibling stream by ``sync-streams``, or simply still delivering
        its last few buffers to a pad the selector no longer forwards) --
        ``set_state(NULL)`` blocks the calling thread until every streaming thread
        touching that element has actually returned from its current callback, so
        a thread parked inside the SELECTOR's own wait (not this leg's element at
        all) could never be woken by NULLing the leg's own elements, and the GLib
        main-loop thread calling this hung forever (the exact seven-soak wedge).
        Sending FLUSH_START on the sink pad BEFORE unlinking wakes any streaming
        thread blocked in that pad's wait (GstInputSelector's sync-streams
        condvar checks the pad's flushing flag and is broadcast on FLUSH_START);
        unlinking and releasing the request pad immediately after, still before
        the leg's own elements are ever told to NULL, means that thread has
        nothing left to block on by the time ``set_state(NULL)`` runs."""
        try:
            for selector, pad in (
                (self.selector, video_pad),
                (self.audio_selector, audio_pad),
            ):
                if selector is None or pad is None:
                    continue
                with contextlib.suppress(Exception):
                    pad.send_event(Gst.Event.new_flush_start())
                peer = pad.get_peer()
                if peer is not None:
                    peer.unlink(pad)
                with contextlib.suppress(Exception):
                    pad.send_event(Gst.Event.new_flush_stop(True))
                selector.release_request_pad(pad)
            for element in elements:
                element.set_state(Gst.State.NULL)
            for element in elements:
                self.pipeline.remove(element)
        except Exception as exc:
            print(f"WARN: reload disposal incomplete: {exc!r}", flush=True)

    # -- content-reload (S15 BLOCKER fix): re-apply the graphics-overlay leg too --

    def _belongs_to_pending_overlay_swap(self, src: object) -> str | None:
        """The layer NAME whose still-settling swap ``src`` (a bus-message source)
        belongs to, or None. Mirrors ``_belongs_to_pending_reload``, one pending
        swap per layer name instead of a single pending reload."""
        if src is None:
            return None
        for layer_name, entry in self._pending_overlay_swaps.items():
            node = src
            while node is not None:
                if node in entry["new_elements"]:
                    return layer_name
                node = node.get_parent() if hasattr(node, "get_parent") else None
        return None

    def reload_graphics_overlay(self, new_leg: GraphicsOverlayLeg | None) -> None:
        """Re-apply the S15 graphics-overlay leg on a content-reload.

        BLOCKER fix (2026-08-30 audit): a content-reload used to rebuild ONLY the
        program source leg (``reload_program``) and silently drop
        ``new_graph.graphics_overlay`` — an operator's mid-broadcast lower-third
        text update never took effect until a full restart, even though the API +
        UI advertise a content-reload as the way to apply it (see
        ``civiccast.egress.router.update_graphics_overlay`` and
        ``bridge.graphics_overlay_leg_from_config``, which re-renders a fresh
        banner PNG on every call specifically so a reload can pick it up).

        For every layer NAME present in ``new_leg`` this builds a fresh image
        chain and swaps it in for that name's currently-live layer (or adds it, if
        the name is new) via ``_swap_overlay_layer`` — the exact first-buffer-probe
        pattern ``reload_program`` uses for the video source leg, so there is never
        a frame where the OLD and NEW image for the SAME layer are both composited
        (a visible double-exposure), and a build/preroll failure never disturbs the
        already-on-air overlay. A layer name no longer present in ``new_leg`` (the
        operator removed a layer, or turned the whole overlay off) is dropped via
        ``_remove_overlay_layer``. The lower-third's operative case — the SAME
        layer name (``"lower_third"``) with a freshly-rendered PNG at a new path —
        is exactly a swap-by-name.

        If the engine was built WITHOUT a graphics-overlay leg at all (no
        compositor exists in this pipeline's topology —
        ``self._overlay_compositor is None``), a reload cannot safely splice a
        D3D11 compositor into an already-running pipeline; this is logged and
        skipped, matching ``PlayoutGraph.graphics_overlay``'s documented
        "None preserves today's behavior" contract — a channel that wants to ADD an
        overlay where none existed needs a fresh start, not a reload."""
        if self._overlay_compositor is None:
            if new_leg is not None:
                print(
                    "WARN: content-reload carried a graphics-overlay update but this "
                    "channel's pipeline was built without an overlay compositor -- a "
                    "fresh start is required to add one; skipping.",
                    flush=True,
                )
            return
        new_layers_by_name = {
            layer.name: layer for layer in (new_leg.layers if new_leg is not None else ())
        }
        for name in list(self._overlay_layer_pads):
            if name not in new_layers_by_name:
                self._remove_overlay_layer(name)
        # A layer name can be PENDING (a not-yet-committed ADD, i.e. one never in
        # ``_overlay_layer_pads`` because this is its first-ever reload) without the
        # loop above ever seeing it -- close that gap here so a layer removed before
        # its own add commits doesn't orphan a settling swap forever.
        for name in list(self._pending_overlay_swaps):
            if name not in new_layers_by_name and name not in self._overlay_layer_pads:
                self._abort_pending_overlay_swap(name, reason="removed")
        for layer in new_layers_by_name.values():
            self._swap_overlay_layer(layer)

    def _swap_overlay_layer(self, layer: GraphicsOverlayLayer) -> None:
        """Build a fresh image chain for ``layer`` onto a new compositor pad, and
        commit it in place of that layer name's current pad on the new chain's
        first buffer. Mirrors ``reload_program``'s ENG-001/ENG-002/ENG-008 handling
        (bounded watchdog, probe-armed-before-preroll, build-error containment) —
        see that method's docstring for the rationale of each."""
        compositor = self._overlay_compositor
        if compositor is None:
            return  # defensive; reload_graphics_overlay already gates this
        if layer.name in self._pending_overlay_swaps:
            # Supersede a still-settling swap for this same layer name (never drop
            # a due overlay change) — the superseded chain is disposed first.
            print(
                f"CTRL graphics-overlay reload superseding a still-settling swap "
                f"for layer {layer.name!r}",
                flush=True,
            )
            self._abort_pending_overlay_swap(layer.name, reason="superseded")
        new_pad, new_elements = self._instantiate_overlay_layer(layer, compositor)
        entry: dict[str, Any] = {
            "layer": layer,
            "new_pad": new_pad,
            "new_elements": new_elements,
            "probe_id": None,
            "timeout_id": None,
        }
        self._pending_overlay_swaps[layer.name] = entry
        try:
            # ENG-002 (mirrored): arm the first-buffer probe BEFORE PLAYING so the
            # genuine first buffer can never slip past an unarmed probe.
            entry["probe_id"] = new_pad.add_probe(
                Gst.PadProbeType.BUFFER,
                lambda _pad, _info, name=layer.name: self._on_overlay_first_buffer(name),
            )
            for element in new_elements:
                element.sync_state_with_parent()  # preroll the new layer chain
        except Exception:  # ENG-008 (mirrored): a preroll/arm failure must not wedge
            self._abort_pending_overlay_swap(layer.name, reason="build-error")
            raise
        # ENG-001 (mirrored): bound the wait for the new layer's first buffer. If it
        # never arrives, abort rather than pin the pending swap forever (the current
        # overlay for this layer name keeps showing).
        entry["timeout_id"] = GLib.timeout_add_seconds(
            max(1, int(self.reload_timeout_s)),
            lambda name=layer.name: self._on_overlay_swap_timeout(name),
        )

    def _on_overlay_first_buffer(self, layer_name: str) -> Gst.PadProbeReturn:
        # Streaming thread: hand the commit to the main loop (no state changes here).
        GLib.idle_add(self._commit_overlay_swap, layer_name)
        return Gst.PadProbeReturn.REMOVE

    def _commit_overlay_swap(self, layer_name: str) -> bool:
        """Main-loop commit of one layer's swap: repoint ``self._overlay_layer_pads``/
        ``self._overlay_layer_elements`` at the prerolled new chain, then dispose the
        old one. A no-op if the swap was aborted/superseded before this fired.
        ``return False`` so the GLib idle source runs once."""
        entry = self._pending_overlay_swaps.get(layer_name)
        if entry is None:
            return False  # aborted or superseded before the first buffer landed
        if entry["timeout_id"] is not None:
            GLib.source_remove(entry["timeout_id"])  # committing — cancel the watchdog
        old_pad = self._overlay_layer_pads.get(layer_name)
        old_elements = self._overlay_layer_elements.get(layer_name, [])
        old_image_path = self._overlay_layer_image_paths.get(layer_name)
        self._overlay_layer_pads[layer_name] = entry["new_pad"]
        self._overlay_layer_elements[layer_name] = entry["new_elements"]
        self._overlay_layer_image_paths[layer_name] = entry["layer"].image_path
        del self._pending_overlay_swaps[layer_name]
        if old_pad is not None:
            # R3: the swap point -- the NEW layer's first buffer has just landed,
            # so the OLD chain (about to be disposed below) is provably off-air.
            # Delete its banner PNG only once ``_dispose_overlay_layer_pad`` has
            # unlinked/NULL'd/removed every element reading it (best-effort: never
            # raises, matches that method's disposal-hiccup contract).
            self._dispose_overlay_layer_pad(old_pad, old_elements)
            self._delete_stale_overlay_png(old_image_path)
        print(
            f"CTRL graphics-overlay layer {layer_name!r} reload committed "
            f"(elements={self._element_count()})",
            flush=True,
        )
        return False

    def _on_overlay_swap_timeout(self, layer_name: str) -> bool:
        """Watchdog: the new layer chain never produced a first buffer in time.
        Abort so the channel isn't wedged on a never-committing overlay swap; the
        current overlay for this layer name keeps showing and the next due change
        can retry."""
        if layer_name not in self._pending_overlay_swaps:
            return False  # already committed/aborted
        print(
            f"CTRL graphics-overlay reload for layer {layer_name!r} aborted: new layer "
            f"produced no buffer within {max(1, int(self.reload_timeout_s))}s; "
            "keeping current overlay",
            flush=True,
        )
        self._abort_pending_overlay_swap(layer_name, reason="timeout")
        return False  # one-shot

    def _abort_pending_overlay_swap(self, layer_name: str, *, reason: str) -> None:
        """Tear down the in-flight (uncommitted) swap for ``layer_name`` and clear
        its pending slot. The currently-shown layer for that name is untouched.
        Used by supersede, build-error, watchdog timeout, and async-error
        containment."""
        entry = self._pending_overlay_swaps.pop(layer_name, None)
        if entry is None:
            return
        if entry["probe_id"] is not None:
            with contextlib.suppress(Exception):  # probe may already have auto-removed
                entry["new_pad"].remove_probe(entry["probe_id"])
        if entry["timeout_id"] is not None and reason != "timeout":
            # 'timeout' means the watchdog source is firing now (auto-removed on return).
            with contextlib.suppress(Exception):
                GLib.source_remove(entry["timeout_id"])
        self._dispose_overlay_layer_pad(entry["new_pad"], entry["new_elements"])
        # R3: this chain never went on-air (superseded/build-error/timeout/removed
        # before its first buffer committed) -- its banner PNG is an orphan the
        # moment its elements are disposed above; delete it now rather than
        # leaking it until the next start()'s sweep.
        self._delete_stale_overlay_png(entry["layer"].image_path)

    def _remove_overlay_layer(self, layer_name: str) -> None:
        """Drop a layer no longer present in a reloaded graphics-overlay leg (the
        operator removed a layer, or turned the overlay off) — disposes its
        compositor pad + elements the same way ``_dispose_source_leg`` retires a
        source leg. A layer with a swap still settling is left alone (its own
        commit/abort path disposes whichever chain loses)."""
        if layer_name in self._pending_overlay_swaps:
            self._abort_pending_overlay_swap(layer_name, reason="removed")
        pad = self._overlay_layer_pads.pop(layer_name, None)
        elements = self._overlay_layer_elements.pop(layer_name, [])
        image_path = self._overlay_layer_image_paths.pop(layer_name, None)
        if pad is not None:
            self._dispose_overlay_layer_pad(pad, elements)
            self._delete_stale_overlay_png(image_path)

    def _dispose_overlay_layer_pad(self, pad: Gst.Pad, elements: list[Gst.Element]) -> None:
        """Tear down one now-inactive overlay layer chain: unlink from the
        compositor, release its request pad, then NULL + remove its elements.
        Best-effort — mirrors ``_dispose_source_leg``: a disposal hiccup is logged,
        never raised, so it can never take a live channel off air."""
        try:
            for element in elements:
                element.set_state(Gst.State.NULL)
            compositor = self._overlay_compositor
            if compositor is not None:
                peer = pad.get_peer()
                if peer is not None:
                    peer.unlink(pad)
                compositor.release_request_pad(pad)
            for element in elements:
                self.pipeline.remove(element)
        except Exception as exc:
            print(f"WARN: graphics-overlay layer disposal incomplete: {exc!r}", flush=True)

    def _delete_stale_overlay_png(self, image_path: str | None) -> None:
        """Delete an overlay layer's rendered banner PNG once its GStreamer chain
        is fully disposed (called only after ``_dispose_overlay_layer_pad`` has
        unlinked/NULL'd/removed every element that had it open).

        Restricted to filenames matching ``_STALE_BANNER_PNG_RE`` -- the exact
        per-call unique pattern ``bridge.graphics_overlay_leg_from_config``
        renders -- so this can never delete an operator-configured, persistent
        image (e.g. a future station-bug/logo layer's ``image_path``), only a
        file this module's own reload/swap path generated. Best-effort: a file
        still locked by a lingering process (Windows) fails to unlink and is
        logged, never raised -- disposal must never take a live channel off air
        (R3, 2026-08-31: round-1's per-uuid banner filename fix left nothing to
        delete the old ones, so a 24/7 station accumulated one PNG per
        start()/content-reload forever on the same volume as recordings/HLS/DB)."""
        if not image_path:
            return
        path = Path(image_path)
        if not _STALE_BANNER_PNG_RE.match(path.name):
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            print(
                f"WARN: failed to delete stale graphics-overlay banner PNG {path}: {exc!r}",
                flush=True,
            )

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
