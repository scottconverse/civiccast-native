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
import faulthandler
import json
import math
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Callable
from itertools import count, pairwise
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
    from civiccast.egress.gst.caption_flow import CaptionGapGate
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
    from caption_flow import CaptionGapGate  # type: ignore[import-not-found,no-redef]
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


# Item 88 (measured in sandbox run 17, soak-a6d7871-20260906-213332Z, Opus
# diagnosis): the caption-audio-tap fork must NEVER be able to take the
# channel off air. ``caption_audio_tap_queue`` used to be a plain (default,
# NON-leaky) queue: once the appsink callback's own blocking I/O (fixed in
# ``audio_tap.py`` -- see that module's docstring) fell behind, this queue
# filled, backpressure propagated upstream through the tee it forks from,
# and the mux's audio pad -- fed by the SAME tee -- starved, stopping real
# TS output. ``leaky=2`` (``GST_QUEUE_LEAK_DOWNSTREAM``) makes the queue
# drop its OLDEST buffered data instead of ever blocking the tee once it
# fills.
#
# Round-2 review correction: ``max-size-buffers=200`` below is NOT a
# "deeper" cap -- it is GStreamer's own stock ``queue`` default, kept
# explicit only for clarity and so the unit test in
# ``test_gst_engine_audio_tap_specs.py`` has a concrete value to assert
# against. The actual load-bearing change is ``max-size-time=0`` (disabling
# the stock 1-SECOND default): this tap's audio format (F32LE, 44.1 kHz,
# stereo, 8192-byte buffers measured live) takes ~4.6s to fill 200 buffers
# (~1.6 MB) -- comfortably under the stock 10 MB ``max-size-bytes`` default,
# which is INTENTIONALLY left untouched below as a memory guard of last
# resort (a future format change to much larger buffers should still leak
# rather than grow this queue unbounded). Left at its 1s stock default,
# ``max-size-time`` -- not buffer count or bytes -- would have been the
# FIRST limit reached (1s of buffering, not 4.6s), making the queue leak
# far sooner than intended and defeating the "real headroom for a
# slow-but-recovering consumer" this fix exists to provide. This queue
# should never actually leak in normal operation; it exists as the backstop
# of last resort once the writer-side fix (bounded, drop-oldest queue +
# off-streaming-thread I/O, see ``audio_tap.py``) is already in place.
_CAPTION_AUDIO_TAP_QUEUE_LEAK_DOWNSTREAM = 2
_CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_BUFFERS = 200  # GStreamer's own stock default
_CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_TIME = 0  # disables the stock 1s default -- the real fix
_CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_BYTES = 10_485_760  # GStreamer's own stock 10 MB default
_CAPTION_AUDIO_TAP_APPSINK_MAX_BUFFERS = 32


def _audio_tap_element_specs() -> tuple[ElementSpec, ...]:
    """The caption-audio-tap fork's element chain, source-tee to appsink.

    Pulled out as a pure, gi-free function (no ``Gst`` element is actually
    constructed here -- ``ElementSpec`` is a plain dataclass) so its element
    ordering and leaky/drop properties are unit-testable without a real
    GStreamer install. See the module-level comment above this function and
    ``audio_tap.py``'s docstring for why every property here is load-bearing
    for item 88."""
    return (
        ElementSpec(
            "queue",
            "caption_audio_tap_queue",
            props={
                "leaky": _CAPTION_AUDIO_TAP_QUEUE_LEAK_DOWNSTREAM,
                "max-size-buffers": _CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_BUFFERS,
                "max-size-time": _CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_TIME,
                "max-size-bytes": _CAPTION_AUDIO_TAP_QUEUE_MAX_SIZE_BYTES,
            },
        ),
        ElementSpec("audioconvert", "caption_audio_tap_convert"),
        ElementSpec("audioresample", "caption_audio_tap_resample"),
        ElementSpec(
            "capsfilter",
            "caption_audio_tap_caps",
            props={"caps": ("audio/x-raw,format=S16LE,rate=16000,channels=1,layout=interleaved")},
        ),
        ElementSpec(
            "appsink",
            "caption_audio_tap_sink",
            props={
                "emit-signals": True,
                "sync": False,
                "max-buffers": _CAPTION_AUDIO_TAP_APPSINK_MAX_BUFFERS,
                # Item 88: was ``False`` -- a non-dropping appsink is exactly
                # as capable of backing up the tee as the non-leaky queue
                # above was. ``drop=True`` bounds this sink's own contribution
                # to the same failure mode the queue fix addresses.
                "drop": True,
            },
        ),
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

# Item 84 (measured in sandbox run 15, soak-fcfcb81-20260906-183448Z, and in
# three seamless-OFF runs): every fresh worker printed
# ``CTRL preroll: reached PLAYING after 0.3s`` (a real, fast PLAYING
# transition -- ``_await_playing`` above is not wrong) immediately followed by
# ``CTRL stall: no output for 10s - quitting for daemon restart`` from
# ``_check_stall`` below. ``_arm_stall_watchdog`` arms that 10s bound the
# instant PLAYING is reached, but PLAYING (even NO_PREROLL) is not evidence a
# single buffer has actually crossed the mux -- under start-up load (a
# concurrent ``ffmpeg -threads 1 h264_mf + loudnorm`` conform, a ~10s
# synchronous content-reload source preparation on the automation thread,
# live caption-tap overload) the FIRST output buffer can legitimately take
# much longer than 10s even though the worker is perfectly healthy and would
# have produced output shortly after. There was no separate bound for
# "time to first output" -- only the post-first-buffer stall bound, applied
# from the moment PLAYING happened instead of from the moment output actually
# started.
#
# This gives "never produced a single buffer" its own, much more generous
# budget than "stopped producing buffers after already airing" -- the two are
# different failure modes (a genuinely wedged/dead pipeline vs one merely
# slow to warm up) and conflating them under one 10s bound killed healthy
# workers. 45s default -- comfortably covers the measured start-up
# contention above with margin; configurable via env var for ops tuning
# without a code change; clamped to [10, 120]s (see the module-level
# ``math.isfinite`` guard rationale on ``_resolve_preroll_timeout_s``, which
# this function mirrors exactly).
_DEFAULT_FIRST_OUTPUT_TIMEOUT_S = 45.0
_MIN_FIRST_OUTPUT_TIMEOUT_S = 10.0
_MAX_FIRST_OUTPUT_TIMEOUT_S = 120.0
_FIRST_OUTPUT_TIMEOUT_ENV_VAR = "CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S"

# Item 84c (measured in sandbox run 17, soak-a6d7871-20260906-213332Z, Opus
# diagnosis): the ``CTRL first-output: first buffer after 0.0s`` marker was a
# TAUTOLOGY, not evidence. The persistent output half's ``queue -> udpsink``
# sink chain is ASYNC (``sync=False``/async sink semantics on the UDP leg),
# so the pipeline cannot reach PLAYING at all before at least one buffer --
# typically PAT/PMT/SDT table buffers plus the very first media buffer --
# has already prerolled through the mux. ``_arm_stall_watchdog`` used to
# latch ``_first_output_seen = self._output_buffers > 0`` at arm time, which
# is true for essentially every worker that ever reaches PLAYING, marker
# text and all -- exactly the escalation-defeating symptom item 84c exists
# to close (a worker whose REAL media output later stalls still printed
# "first buffer after 0.0s" and looked like on-air evidence to the daemon).
#
# Fix: snapshot the counter at arm time (``_output_buffers_at_arm``) and
# require the count to exceed that snapshot by at least this many buffers,
# observed strictly AFTER arming, before crediting real first output. 2
# rather than 1 -- a single post-arm buffer could still be a trailing
# PAT/PMT/SDT table refresh (mpegtsmux re-emits them periodically,
# independent of media content) rather than genuine media flow; requiring a
# SECOND post-arm buffer is cheap insurance against exactly that coincidence
# without meaningfully delaying real on-air detection (media buffers advance
# far more often than table refreshes once a source is actually flowing).
_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM = 2

# Round-2 finding 4: the audio tap writer's OWN close budget on ``stop()``,
# deliberately independent of the pipeline teardown deadline it used to share.
# Closing a rolling WAV segment is a flush + header rewrite + rename of an
# already-open local file, so two seconds is generous for the work while still
# being far too short to reintroduce the unbounded-stop hazard ``teardown_
# timeout_s`` exists to prevent. Round-3 finding 10: the budget is CAPPED by
# ``teardown_timeout_s`` (``min(...)`` in ``stop()``), not floored by it -- an
# operator who deliberately configures a very fast stop gets that fast stop here
# too, rather than having this constant override it.
_AUDIO_TAP_CLOSE_TIMEOUT_S = 2.0

# Round-3 finding 1: ``stop()``'s OWN budget for letting an in-flight old-leg
# retirement finish, deliberately independent of the pipeline teardown deadline
# it must NOT be allowed to race. Retirement became asynchronous in this round --
# a commit publishes before the outgoing leg is disposed -- so a ``stop`` arriving
# moments after a rollover legitimately finds one in flight. Measured: letting the
# whole-pipeline ``set_state(NULL)`` run CONCURRENTLY with that retirement made a
# loaded three-worker rollover exit 70 ("pipeline did not reach NULL within
# teardown bound") with all six reloads committed and five of six legs retired --
# the two transitions were fighting over the same element locks. Joining the
# retirement FIRST, against this small dedicated budget, keeps them ordered, and
# ``teardown_timeout_s`` then still buys the pipeline transition its full bound.
_RETIREMENT_STOP_JOIN_S = 3.0

# Round-2 finding 3: how long ``_dispose_source_leg`` waits for ONE retiring
# element to actually reach NULL after ``set_state`` answered ASYNC. Source legs
# are bins, and a bin winding its children down returns ASYNC by contract, so a
# bounded wait -- not an immediate "incomplete cleanup" verdict -- is the correct
# reading of that return. Round-3 finding 3: this is a per-element CAP, never the
# leg's budget -- see ``_LEG_DISPOSAL_BUDGET_S``.
_LEG_NULL_ASYNC_WAIT_S = 2.0

# Round-3 finding 3: ONE deadline for the WHOLE leg's descent to NULL.
# ``_LEG_NULL_ASYNC_WAIT_S`` was being applied per element, twice (the attempt
# plus its retry). A production program leg is ~77 elements, so the arithmetic
# worst case was 77 x 2 x 2.0s = ~308s of retirement -- five minutes during which
# nothing about that leg was bounded in any useful sense. Every element of a leg,
# across both attempts, now draws down this single budget; an element that starts
# with no budget left is checked without waiting and handed to the orphan sweep.
# 8s is ~100x a healthy leg's measured disposal (0.078s on this repository's own
# supersede reproducer) and is spent entirely OFF the GLib loop.
_LEG_DISPOSAL_BUDGET_S = 8.0

# Round-3 finding 5: an element that has still not reached NULL when
# ``_LEG_DISPOSAL_BUDGET_S`` is spent is an ORPHAN -- possibly still running, no
# longer owned by any transaction. ``_dispose_source_leg`` used to run
# unlink/release/remove over it unconditionally and then forget it. It now gets
# one more bounded sweep against this budget; whatever survives that is recorded
# in ``_orphaned_leg_elements``, reported as an ERROR naming each element, and
# deliberately NOT handed to ``pipeline.remove`` (removing an element that is not
# at NULL is invalid and is how a "cleanup" becomes a crash).
_LEG_ORPHAN_RETRY_BUDGET_S = 4.0

# Round-3 finding 4: how long ``reload_program`` will wait, on the GLib loop, for
# an earlier leg's retirement thread to finish releasing ITS ``input-selector``
# request pads before requesting new ones on the same selector. Round 2 made
# retirement asynchronous without serialising it against the next transaction, so
# ``_abort_pending_reload("superseded")`` could return while its retirement thread
# was still inside ``release_request_pad`` and the very next statement in
# ``reload_program`` called ``request_pad_simple("sink_%u")`` on that same
# element -- concurrent request-pad mutation of one ``input-selector``.
#
# Round-3 review finding 3 (the round-3 cut sized this at 2.0s, "~25x a healthy
# ~0.08s disposal"): that sizing was against the HEALTHY case, but a disposal is
# allowed to take up to ``_LEG_DISPOSAL_BUDGET_S + _LEG_ORPHAN_RETRY_BUDGET_S``
# (12s) and still be within its own budget. A merely SLOW disposal (2-12s) was
# therefore turning the very next rollover into a refusal -- silent dead air on
# the FIFO path, a worker restart on the Windows path -- for a leg that was
# retiring correctly. The bound is now DERIVED from the two disposal budgets plus
# a scheduling margin, so a retirement that is inside its own bound can never
# trip the gate; only a retirement that has ALREADY overrun its bound can, and
# that one is abandoned (``_RETIREMENT_ABANDON_AFTER_S``) rather than waited on.
_SELECTOR_PAD_QUIESCE_MARGIN_S = 1.0
_SELECTOR_PAD_QUIESCE_TIMEOUT_S = (
    _LEG_DISPOSAL_BUDGET_S + _LEG_ORPHAN_RETRY_BUDGET_S + _SELECTOR_PAD_QUIESCE_MARGIN_S
)

# Round-3 review finding 2: a retirement thread that never returns (a
# ``set_state(NULL)`` blocked forever inside a streaming task) never runs
# ``_dispose_source_leg``'s ``finally``, so its claim on the selector-pad gate
# would otherwise stand forever and EVERY later ``reload_program`` would fail at
# the gate -- permanent dead air at the next rollover. A retirement that has held
# its claim longer than this is declared ABANDONED by the waiter: its claim is
# concluded, its elements are recorded as orphans (they stay locked in the
# pipeline until ``stop()`` unlocks them), an ERROR names them, and later reloads
# proceed. Equal to the gate's own bound: anything still in flight at that age
# has overrun the whole leg budget by the full margin.
_RETIREMENT_ABANDON_AFTER_S = _SELECTOR_PAD_QUIESCE_TIMEOUT_S


def _utc_stamp() -> str:
    """``HH:MM:SS.mmm`` in UTC, for the ``t=`` suffix on ``CTRL`` stderr lines.

    Round-3 review finding 4: the worker's stderr carried no clock at all, so a
    ``stage=old-leg-disposed`` line could not be placed against the daemon's own
    timestamped log or against the sandbox lane's CPU sampler. UTC so it lines up
    with the daemon's log regardless of the box's zone."""
    now = time.time()
    return f"{time.strftime('%H:%M:%S', time.gmtime(now))}.{int(now * 1000) % 1000:03d}"


def _ctrl_stderr(message: str) -> None:
    """Print one ``CTRL`` diagnostic line to stderr with a trailing UTC timestamp.

    The stamp goes at the END (`` t=HH:MM:SS.mmm``), never in front: every
    consumer of these lines anchors on ``^CTRL `` at column 0 -- the sandbox
    lane's ``WorkerStdoutParser.ps1`` (``^CTRL stall:``), ``health.py``'s
    ``_PLAYING_REACHED_RE`` / ``_FIRST_OUTPUT_RE``, and the daemon's
    ``_RELOAD_COMMIT_TIMEOUT_MARKER`` substring fold into ``last_error`` -- and
    none of them anchor on the line's end. Stdout ``CTRL`` lines (the settlement
    markers the lane counts with ``\\s*$``-anchored regexes) are deliberately NOT
    routed through here."""
    print(f"{message} t={_utc_stamp()}", file=sys.stderr, flush=True)


def _lock_retiring_element_state(element: object) -> None:
    """Pin one retiring element's state so the pipeline cannot re-PLAY it.

    Round 3, measured on the live native runtime (2 of 3 ``-k reload`` batch
    runs): a worker crashed at stop with ``rc=0xC0000005`` after GStreamer
    reported "Trying to dispose element videotestsrc0 / capsfilter1, but it is
    in PLAYING instead of the NULL state" -- and those were exactly the FIRST TWO
    elements of an old program leg whose retirement thread had already reported
    every one of its 25 elements at NULL. The mechanism: a ``GstBin`` re-applies
    its own state to EVERY unlocked child whenever it completes a state change
    of its own, and a live pipeline does complete one whenever a newly-added
    chain finishes an ASYNC preroll (here the graphics-overlay layer being
    swapped on the main loop while the program leg retired on its thread). The
    cascade landed between element 2 and element 3 of the retirement loop, set
    the two already-NULLed elements back to PLAYING, and the loop then removed
    them from the pipeline in that state -- a running source task on a disposed
    element. Round 2 never saw it only because its replacement stayed held
    (dark) across retirement, which happened to keep the two events apart.

    ``set_locked_state(True)`` is the GStreamer-sanctioned answer: a locked child
    is skipped by the bin's cascade, so once this leg's element is at NULL it
    stays there until it is removed. Best-effort by construction -- this runs on
    paths that must never raise a second error over the first."""
    with contextlib.suppress(Exception):
        element.set_locked_state(True)  # type: ignore[attr-defined]


def _element_label(element: object) -> str:
    """A human-usable name for one pipeline element, for orphan reporting.

    Round-3 finding 5: an ERROR that says "1 element did not reach NULL" is not
    actionable; one that names ``vdec_program_7`` is. Best-effort by construction
    -- this is called only from a path that is already reporting a problem, so it
    must never raise a second one."""
    for accessor in ("get_name", "get_factory"):
        with contextlib.suppress(Exception):
            value = getattr(element, accessor)()
            if accessor == "get_factory":
                value = value.get_name()
            if value:
                return str(value)
    return "<unnamed>"


def _drop_everything_probe(_pad: object, _info: object) -> object:
    """Round-2 finding 1: a pad probe that discards everything.

    Installed on an ABORTED reload leg's own src pads just before its hold probes
    are lifted, so that leg's data can never enter the ``input-selector`` at all.
    See ``_abort_pending_reload`` for why that matters."""
    return Gst.PadProbeReturn.DROP


# Item 84c addendum: how often ``_check_stall`` prints the
# ``CTRL output: <N> buffers (+<delta>) since PLAYING`` progress line -- a
# bounded, one-line-per-interval breadcrumb so the NEXT soak shows exactly
# when output stopped (sandbox run 17 had no such signal; the only evidence
# of the item 88 stall was TSDuck's after-the-fact silence and the eventual
# watchdog kill 10s later).
_OUTPUT_PROGRESS_INTERVAL_S = 5.0


def _resolve_first_output_timeout_s(explicit: float | None) -> float:
    """Resolve the time-to-FIRST-output bound: an explicit constructor value
    wins, else the ``CIVICCAST_GST_FIRST_OUTPUT_TIMEOUT_S`` env var, else the
    45s default -- always clamped to ``[10, 120]``s. Mirrors
    ``_resolve_preroll_timeout_s`` exactly, including the ``math.isfinite``
    guard against a NaN/inf value silently defeating the clamp (Python's
    ``min``/``max`` do not clamp NaN -- see that function's docstring for the
    full reasoning, which applies unchanged here)."""
    if explicit is not None:
        if not math.isfinite(explicit):
            _ctrl_stderr(
                f"CTRL first-output: ignoring non-finite first_output_timeout_s="
                f"{explicit!r}; using default {_DEFAULT_FIRST_OUTPUT_TIMEOUT_S}s"
            )
            return _DEFAULT_FIRST_OUTPUT_TIMEOUT_S
        return min(max(explicit, _MIN_FIRST_OUTPUT_TIMEOUT_S), _MAX_FIRST_OUTPUT_TIMEOUT_S)
    raw = os.environ.get(_FIRST_OUTPUT_TIMEOUT_ENV_VAR)
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = math.nan  # falls through to the non-finite branch below
        if not math.isfinite(parsed):
            _ctrl_stderr(
                f"CTRL first-output: ignoring non-finite {_FIRST_OUTPUT_TIMEOUT_ENV_VAR}="
                f"{raw!r}; using default {_DEFAULT_FIRST_OUTPUT_TIMEOUT_S}s"
            )
            return _DEFAULT_FIRST_OUTPUT_TIMEOUT_S
        return min(max(parsed, _MIN_FIRST_OUTPUT_TIMEOUT_S), _MAX_FIRST_OUTPUT_TIMEOUT_S)
    return _DEFAULT_FIRST_OUTPUT_TIMEOUT_S


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
            _ctrl_stderr(
                f"CTRL preroll: ignoring non-finite preroll_timeout_s={explicit!r}; "
                f"using default {_DEFAULT_PREROLL_TIMEOUT_S}s"
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
            _ctrl_stderr(
                f"CTRL preroll: ignoring non-finite {_PREROLL_TIMEOUT_ENV_VAR}={raw!r}; "
                f"using default {_DEFAULT_PREROLL_TIMEOUT_S}s"
            )
            return _DEFAULT_PREROLL_TIMEOUT_S
        return min(max(parsed, _MIN_PREROLL_TIMEOUT_S), _MAX_PREROLL_TIMEOUT_S)
    return _DEFAULT_PREROLL_TIMEOUT_S


# Item 85: bounds for the reload-commit watchdog (_arm_commit_watchdog). 3s
# floor -- below that the watchdog would fire on ordinary GStreamer scheduling
# jitter, not a real wedge; 120s ceiling -- an operator-configured value this
# item's own worker.py env override (CIVICCAST_RELOAD_COMMIT_TIMEOUT_S) could
# otherwise set arbitrarily high must still bound how long a genuinely wedged
# worker can sit unresponsive before the daemon ever finds out.
_DEFAULT_COMMIT_TIMEOUT_S = 15.0
_MIN_COMMIT_TIMEOUT_S = 3.0
_MAX_COMMIT_TIMEOUT_S = 120.0


def _resolve_commit_timeout_s(explicit: float) -> float:
    """Validate/clamp the reload-commit watchdog bound to
    ``[_MIN_COMMIT_TIMEOUT_S, _MAX_COMMIT_TIMEOUT_S]``, WARNING on stderr
    whenever the clamp actually changes the configured value -- unlike an
    earlier draft's ``max(1.0, self.commit_timeout_s)`` inline in
    ``_arm_commit_watchdog``, which silently floored an unreasonably low value
    with no operator-visible signal at all. Mirrors
    ``_resolve_preroll_timeout_s``'s non-finite guard (``math.isfinite``):
    Python's ``min``/``max`` do not clamp NaN (every comparison against NaN is
    False, so both keep their first argument), so a NaN here would otherwise
    reach ``threading.Timer`` as its ``interval`` and either raise or silently
    never fire, defeating the watchdog entirely."""
    if not math.isfinite(explicit):
        _ctrl_stderr(
            f"CTRL reload: ignoring non-finite commit_timeout_s={explicit!r}; "
            f"using default {_DEFAULT_COMMIT_TIMEOUT_S}s"
        )
        return _DEFAULT_COMMIT_TIMEOUT_S
    clamped = min(max(explicit, _MIN_COMMIT_TIMEOUT_S), _MAX_COMMIT_TIMEOUT_S)
    if clamped != explicit:
        _ctrl_stderr(
            f"CTRL reload: commit_timeout_s={explicit!r} out of bounds "
            f"[{_MIN_COMMIT_TIMEOUT_S}, {_MAX_COMMIT_TIMEOUT_S}]; clamped to {clamped}s"
        )
    return clamped


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
        first_output_timeout_s: float | None = None,
        commit_timeout_s: float = 15.0,
    ) -> None:
        prefer_cpu_decoders_by_default()
        Gst.init([])
        # Belt-and-suspenders with the env-var rank list above: demote by klass, from
        # the registry that really exists here, so a bundled hardware decoder nobody
        # added to the name list cannot win autoplug (Gate A T4 root cause).
        demoted = demote_hardware_decoders(Gst.Registry.get().get_feature_list(Gst.ElementFactory))
        if demoted:
            _ctrl_stderr(
                f"CTRL decode: demoted hardware decoders to CPU decode: {','.join(demoted)}"
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
        # Item 84: bounded wait for the FIRST output buffer past the mux,
        # counted separately from ``stall_timeout_s`` above (see
        # ``_arm_stall_watchdog``/``_check_stall`` and the module-level
        # comment above ``_DEFAULT_FIRST_OUTPUT_TIMEOUT_S`` for the measured
        # failure this closes -- PLAYING is not evidence of output, and
        # applying the 10s post-first-buffer stall bound from PLAYING instead
        # of from the first real buffer killed healthy workers under
        # start-up load).
        self.first_output_timeout_s = _resolve_first_output_timeout_s(first_output_timeout_s)
        # Item 84: latched True the first time ``_check_stall`` observes
        # ``_output_buffers`` advance -- selects which of the two budgets
        # above ``_check_stall`` measures against.
        self._first_output_seen = False
        # Item 84 Round-2 review BLOCKER: the moment ``_await_playing`` last
        # observed a real PLAYING transition (``time.monotonic()``, set only
        # on the success path) -- the reference point the NEW
        # ``CTRL first-output: first buffer after Ns pid=N`` marker's ``Ns``
        # is measured from. ``None`` until PLAYING is actually reached.
        self._playing_reached_at: float | None = None
        # Item 84 Round-2 review BLOCKER: latched True the FIRST time the
        # ``CTRL first-output: ...`` marker is printed (see
        # ``_maybe_print_first_output_marker``) so it never prints twice for
        # one run, independent of ``_first_output_seen``'s own re-arm-per-call
        # semantics (see ``_arm_stall_watchdog``).
        self._first_output_marker_printed = False
        # Item 85: bounds ``_commit_reload`` itself -- see ``_arm_commit_watchdog``
        # for why a plain ``GLib.timeout_add`` cannot do this job alone (the
        # measured wedge blocks the very thread that would run it). Validated/
        # clamped (with a stderr warning on an out-of-bounds or non-finite
        # value) by ``_resolve_commit_timeout_s`` -- never silently floored.
        self.commit_timeout_s = _resolve_commit_timeout_s(commit_timeout_s)
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
        self._caption_gap_gate = CaptionGapGate()
        self._caption_gap_probe: tuple[Any, int] | None = None
        self._caption_gap_heartbeat_id: int | None = None
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
        # Item 84c (measured in sandbox run 17, soak-a6d7871-20260906-213332Z):
        # the count of output buffers already observed AT ARM TIME -- see
        # ``_arm_stall_watchdog``/``_check_stall`` for why "first output" must
        # be measured against this snapshot, not against zero.
        self._output_buffers_at_arm = 0
        # Item 84c: last time ``_check_stall`` printed the
        # ``CTRL output: ...`` progress line (see ``_maybe_print_output_progress``).
        # 0.0 (never printed) rather than ``None`` so the first tick's
        # ``now - self._last_output_progress_print_t`` comparison is a plain
        # float subtraction with no None-guard needed.
        self._last_output_progress_print_t = 0.0
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
        self._reload_txn_counter = count(1)
        self._abort_retire_threads: list[threading.Thread] = []
        # Round-3 finding 4: retirement runs off the GLib loop and RELEASES this
        # pipeline's ``input-selector`` request pads while it does. The next
        # transaction REQUESTS pads on the same selectors. These two must never
        # overlap, so every retirement (commit path and abort path alike) counts
        # itself in here for the duration of ``_dispose_source_leg`` and
        # ``reload_program`` waits, bounded, for the count to reach zero before it
        # asks for a pad. See ``_await_selector_pads_quiet``.
        self._selector_pads_quiet = threading.Condition()
        self._selector_pad_retirements = 0
        # Round-3 review finding 2: one record per retirement still holding a
        # claim on the gate above -- the leg's elements and when it was announced
        # -- so ``_await_selector_pads_quiet`` can tell a retirement that is slow
        # (inside its 12s budget) from one that has overrun it and will never
        # conclude itself, and abandon only the latter. Guarded by
        # ``_selector_pads_quiet``.
        self._retirement_ledger: list[dict[str, Any]] = []
        # Round-3 finding 1: legs whose retirement is in flight AFTER their
        # replacement is already on air. A bus ERROR from one of these is a
        # message from a leg that is being torn down on purpose -- it must be
        # logged, never escalated to the fatal channel path, because the channel
        # it used to feed is by then being fed by the replacement.
        self._retiring_legs: list[list[Gst.Element]] = []
        # Round-3 finding 5: elements a retirement could not bring to NULL within
        # its bounds. They stay in the pipeline (``remove`` is only valid at NULL),
        # they are named in an ERROR line, and they are counted here so the leak
        # guard and any future diagnosis can see them.
        self._orphaned_leg_elements: list[Gst.Element] = []
        # Round-3 finding 1: old-leg retirements run behind their replacement, so
        # under a fast rollover cadence more than one can be in flight at once
        # (each is bounded at ``_LEG_DISPOSAL_BUDGET_S`` + ``_LEG_ORPHAN_RETRY_
        # BUDGET_S``). ``stop()`` must join ALL of them before the whole-pipeline
        # NULL transition, not only the newest; ``_reload_commit_thread`` stays
        # the newest for callers that only need that one.
        self._commit_retire_threads: list[threading.Thread] = []
        self._pending_reload: dict[str, Any] | None = None
        # A commit keeps its transaction in ``_pending_reload`` until old-leg
        # retirement and main-loop finalization both complete. Only the potentially
        # blocking retirement runs on this one background thread; all transaction
        # ownership stays on the GLib loop. An overlapping request is rejected so
        # the worker/strategy/daemon can restart from the complete newest graph.
        # The engine must not privately retain only the program half of a worker
        # graph after that worker has already advanced through its overlay call.
        self._reload_commit_thread: threading.Thread | None = None
        self._stopping = False
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
        caption_specs = leg.caption_source
        if caption_specs[0].factory == "appsrc":
            # Separate serialized GAP forwarding from appsrc's source task.
            # Queue limits count buffers, NOT serialized events; the admission
            # gate below separately bounds heartbeat GAPs to current + one queued.
            caption_specs = (
                caption_specs[0],
                ElementSpec(
                    "queue",
                    "caption_flow_queue",
                    {
                        "max-size-buffers": 200,
                        "max-size-bytes": 10_485_760,
                        "max-size-time": 1_000_000_000,
                        "leaky": 0,
                    },
                ),
                *caption_specs[1:],
            )
        cap_first, cap_last = self._build_chain(caption_specs)
        if cap_first.get_factory().get_name() == "appsrc":
            self.caption_appsrc = cap_first  # daemon pushes cues here (push_caption_cue)
            queue = self.pipeline.get_by_name("caption_flow_queue")
            if queue is None:
                raise RuntimeError("live caption forwarding queue was not built")
            pad = queue.get_static_pad("src")
            gate = self._caption_gap_gate

            def _entered_caption_downstream(_pad: Any, info: Any) -> Any:
                event = info.get_event()
                if event.type == Gst.EventType.GAP:
                    # This means entered the push, NOT consumed downstream. If
                    # that push blocks, only one additional GAP can wait behind it.
                    gate.entered_downstream(int(event.get_seqnum()))
                return Gst.PadProbeReturn.OK

            probe_id = pad.add_probe(Gst.PadProbeType.EVENT_DOWNSTREAM, _entered_caption_downstream)
            self._caption_gap_probe = (pad, probe_id)
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
        if self._send_live_caption_gap(0, LIVE_CAPTION_LEAD_MS) is not True:
            raise RuntimeError("failed to prime the live caption stream")
        self._caption_stream_position_ms = LIVE_CAPTION_LEAD_MS

    def _send_live_caption_gap(self, start_ms: int, duration_ms: int) -> bool | None:
        """Reserve before enqueue; None means a heartbeat is already waiting.

        appsrc.send_event accepts serialized GAPs into a private queue; True is
        not proof of delivery. Use Gst's assigned seqnum so a fast queue probe
        or a late send failure cannot clear a different heartbeat reservation.
        Cue buffers retain their existing path and are not counted by this gate.
        """
        appsrc = self.caption_appsrc
        if appsrc is None:
            return False
        event = Gst.Event.new_gap(start_ms * Gst.MSECOND, duration_ms * Gst.MSECOND)
        seqnum = int(event.get_seqnum())
        if not self._caption_gap_gate.reserve(seqnum):
            return None
        try:
            accepted = bool(appsrc.send_event(event))
        except Exception:
            self._caption_gap_gate.cancel(seqnum)
            raise
        if not accepted:
            self._caption_gap_gate.cancel(seqnum)
        return accepted

    def _advance_live_caption_gap(self) -> bool:
        """Keep sparse caption time moving when no caption buffer is present."""

        appsrc = self.caption_appsrc
        if appsrc is None or self._stopping:
            return False
        if self._caption_gap_gate.pending is not None:
            return True
        window = caption_gap_window_ms(
            stream_position_ms=self._caption_stream_position_ms,
            running_time_ms=self._pipeline_running_time_ms(),
        )
        if window is None:
            return True
        start_ms, duration_ms = window
        try:
            accepted = self._send_live_caption_gap(start_ms, duration_ms)
        except Exception as exc:
            accepted = False
            print(f"WARN: live caption GAP enqueue failed: {exc!r}", file=sys.stderr, flush=True)
        if accepted is None:
            return True
        if not accepted:
            self._error = ("caption-gap", "failed to advance live caption stream")
            if self._loop is not None:
                self._loop.quit()
            return False
        self._caption_stream_position_ms = start_ms + duration_ms
        return True

    def _arm_live_caption_gap_heartbeat(self) -> None:
        if self.caption_appsrc is not None and self._caption_gap_heartbeat_id is None:
            self._caption_gap_heartbeat_id = GLib.timeout_add(100, self._advance_live_caption_gap)

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
        specs = _audio_tap_element_specs()
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

    _SELECTOR_ISOLATION_QUEUE_PROPS: ClassVar[dict[str, object]] = {
        # Explicit GStreamer 1.28.5 queue defaults. A queue starts forwarding as
        # soon as data arrives; these are capacity bounds, not one second of added
        # latency. Non-leaky is load-bearing: station media must never be dropped.
        "max-size-buffers": 200,
        "max-size-bytes": 10_485_760,
        "max-size-time": 1_000_000_000,
        "leaky": 0,
    }

    def _make_selector_isolation_queue(self, name: str) -> Gst.Element:
        queue = self._make(ElementSpec("queue", name))
        for key, value in self._SELECTOR_ISOLATION_QUEUE_PROPS.items():
            queue.set_property(key, value)
        return queue

    def _build(self) -> None:
        # Output half (stays PLAYING): selector → encode chain → mux → sink(s).
        self.selector = self._make_selector("sel")
        video_isolation_queue = self._make_selector_isolation_queue(
            "program_video_selector_isolation"
        )
        self._link(self.selector, video_isolation_queue)
        prev = video_isolation_queue
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
            audio_isolation_queue = self._make_selector_isolation_queue(
                "program_audio_selector_isolation"
            )
            self._link(self.audio_selector, audio_isolation_queue)
            audio_prev = audio_isolation_queue
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
        (a caller here never got as far as linking anything to a selector).

        Round-3 review finding 1b: the earlier cut locked, NULLed and then called
        ``pipeline.remove`` on every element unconditionally, never checking that
        NULL was reached. ``gst_bin_remove_func`` (gstbin.c, GStreamer main; the
        bundled 1.28 runtime has the same function) does NOT change the removed
        child's state -- it clears the child's bus and clock, unlinks its pads and
        unparents it, and nothing more -- so removal can never bring an element to
        NULL, locked or not; and ``gst_element_dispose`` then rejects a non-NULL
        element on its final unref with the ``Trying to dispose element ... but it
        is in PLAYING instead of the NULL state`` critical that this round measured
        (``_lock_retiring_element_state``). Unlocking before removal would not help
        for the same reason. The correct sequence, applied identically to
        ``_dispose_source_leg``'s, is therefore: lock, NULL, CONFIRM NULL (bounded),
        remove only what is confirmed at NULL, and keep whatever is not as a locked,
        in-pipeline orphan that ``stop()`` unlocks before the whole-pipeline NULL."""
        deadline = time.monotonic() + _LEG_DISPOSAL_BUDGET_S
        removable: list[Gst.Element] = []
        orphans: list[Gst.Element] = []
        for element in elements:
            _lock_retiring_element_state(element)
            reached_null = False
            try:
                state_result = element.set_state(Gst.State.NULL)
                if state_result == Gst.StateChangeReturn.SUCCESS:
                    reached_null = True
                elif state_result == Gst.StateChangeReturn.ASYNC:
                    wait_s = max(0.0, min(_LEG_NULL_ASYNC_WAIT_S, deadline - time.monotonic()))
                    ret, state, _pending = element.get_state(int(wait_s * Gst.SECOND))
                    reached_null = bool(
                        ret in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.NO_PREROLL)
                        and state == Gst.State.NULL
                    )
            except Exception:
                reached_null = False
            (removable if reached_null else orphans).append(element)
        for element in removable:
            with contextlib.suppress(Exception):
                self.pipeline.remove(element)
        if orphans:
            self._orphaned_leg_elements.extend(orphans)
            named = ", ".join(_element_label(element) for element in orphans)
            print(
                f"ERROR: build-failure cleanup left {len(orphans)} element(s) above NULL "
                f"({named}). They stay in the pipeline, locked and NOT removed (remove() "
                "does not NULL a child; disposing one above NULL is a crash), and are "
                f"counted as orphans: {len(self._orphaned_leg_elements)} for this worker so far.",
                file=sys.stderr,
                flush=True,
            )

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
            if (
                self._pending_reload is not None
                and not self._pending_reload.get("commit_in_progress", False)
                and self._belongs_to_pending_reload(message.src)
            ):
                err, _debug = message.parse_error()
                # Round-2: name the element that actually failed. The round-1
                # trace recorded only the error text, which left the reviewer --
                # and this round -- unable to tell an errored NEW leg apart from a
                # shared element that ``_belongs_to_pending_reload`` merely
                # attributed to it. The source name makes the next occurrence
                # diagnosable instead of a guess.
                source_name = "unknown"
                with contextlib.suppress(Exception):
                    source_name = message.src.get_name()
                print(
                    "CTRL reload aborted: new program errored before commit "
                    f"(source={source_name}): {err}",
                    flush=True,
                )
                self._abort_pending_reload("error")
                return True
            # Round-3 finding 1: a leg whose retirement is still in flight has
            # already been REPLACED on air. Its errors are the noise of a
            # deliberate teardown (a decoder complaining as its pad goes away, a
            # source reporting the read it will never finish), and escalating them
            # to the fatal path would take a producing channel off air over the
            # corpse of the leg it just replaced -- exactly the failure mode this
            # round exists to close, arriving by the bus instead of by the
            # watchdog. Report and contain.
            if self._belongs_to_retiring_leg(message.src):
                err, _debug = message.parse_error()
                source_name = "unknown"
                with contextlib.suppress(Exception):
                    source_name = message.src.get_name()
                print(
                    "WARN: retiring reload leg errored during teardown "
                    f"(source={source_name}): {err}; the replacement stays on air",
                    file=sys.stderr,
                    flush=True,
                )
                return True
            # Once commit begins, the replacement is already selected and is no
            # longer safe to abort as an uncommitted leg. Its error follows the
            # ordinary fatal channel path below so supervisor recovery is truthful.
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
        # Item 84: arm unconditionally as long as EITHER budget is active --
        # before this fix a ``stall_timeout_s <= 0`` (an operator disabling the
        # post-first-buffer stall check entirely) also silently disabled the
        # first-output bound, which is a genuinely different, always-useful
        # check (a pipeline that never produces a single buffer at all).
        if self.stall_timeout_s <= 0 and self.first_output_timeout_s <= 0:
            return
        self._stall_last_count = self._output_buffers
        self._stall_last_advance_t = time.monotonic()
        # Item 84c (measured in sandbox run 17): a buffer WILL already have
        # crossed the mux by arm time on essentially every worker -- the
        # persistent output half's async sink chain means the pipeline
        # cannot even reach PLAYING before at least one buffer (PAT/PMT/SDT
        # tables + preroll) has prerolled through it. Treating "buffers > 0
        # at arm" as first-output evidence (the pre-84c behavior) was
        # therefore a TAUTOLOGY, not a real signal -- see the module-level
        # comment above ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM``. Snapshot the
        # count instead of latching evidence from it: real first output is
        # measured strictly AFTER this point, in ``_check_stall``.
        self._output_buffers_at_arm = self._output_buffers
        self._first_output_seen = False
        self._last_output_progress_print_t = self._stall_last_advance_t
        GLib.timeout_add_seconds(1, self._check_stall)

    def _maybe_print_first_output_marker(self) -> None:
        """Item 84 Round-2 review BLOCKER: print the pid-tagged
        ``CTRL first-output: first buffer after Ns pid=N`` marker exactly
        once, the moment the FIRST TS buffer/buffer-list is observed crossing
        the mux -- distinct from, and more meaningful than, the ``CTRL
        preroll: reached PLAYING`` marker.

        Measured escalation-cliff BLOCKER this closes: PLAYING (even
        NO_PREROLL) is not evidence output ever flowed, but
        ``EgressDaemon._observed_on_air_evidence`` used to credit the
        PLAYING marker alone as on-air evidence for the GStreamer strategy --
        a worker that reaches PLAYING on every single relaunch but never
        crosses ``first_output_timeout_s`` (at ANY configured value, 65s
        through the 120s clamp ceiling) got its crash-loop streak reset on
        every cycle by the ALIVE-poll path, and never escalated to fallback
        slate (streak pinned at 1) even though it never once produced real
        output. ``civiccast.egress.health.worker_produced_output`` greps for
        this exact marker, anchored to the same spawn offset and pid check as
        ``worker_reached_playing``, and the daemon's alive-poll evidence
        check now requires THIS marker (not PLAYING) for a GStreamer-strategy
        channel -- see ``EgressDaemon._observed_on_air_evidence``. No budget
        value can defeat escalation now: PLAYING alone is never sufficient."""
        if self._first_output_marker_printed:
            return
        self._first_output_marker_printed = True
        elapsed = (
            time.monotonic() - self._playing_reached_at
            if self._playing_reached_at is not None
            else 0.0
        )
        _ctrl_stderr(
            # ASCII only, stable prefix -- a parsed contract like the PLAYING
            # marker above, not just a human-readable log line (see
            # ``civiccast.egress.health.worker_produced_output``).
            f"CTRL first-output: first buffer after {elapsed:.1f}s pid={os.getpid()}"
        )

    def _maybe_print_output_progress(self, now: float) -> None:
        """Item 84c addendum: a bounded, at-most-one-line-per-5s progress
        breadcrumb -- the total output-buffer count and the delta observed
        since arm (PLAYING) time -- so the NEXT soak shows exactly when real
        output stops, instead of only the eventual stall-kill line 10s (or
        45s, before first output) later. Sandbox run 17 had no such signal:
        the only evidence of the item 88 stall was TSDuck's after-the-fact
        silence plus the watchdog kill."""
        if now - self._last_output_progress_print_t < _OUTPUT_PROGRESS_INTERVAL_S:
            return
        self._last_output_progress_print_t = now
        delta = self._output_buffers - self._output_buffers_at_arm
        _ctrl_stderr(f"CTRL output: {self._output_buffers} buffers (+{delta}) since PLAYING")

    def _check_stall(self) -> bool:
        """Quit the run loop on either of two DISTINCT budgets, measured from
        PLAYING (see ``_arm_stall_watchdog``, called immediately after
        ``_await_playing``):

        * Item 84: while no output buffer has crossed the mux yet, bound the
          wait against ``first_output_timeout_s`` (45s default, much more
          generous -- see the module-level comment above
          ``_DEFAULT_FIRST_OUTPUT_TIMEOUT_S``). PLAYING (even NO_PREROLL) is
          NOT evidence a buffer actually crossed the mux, so this is a
          separate, later piece of evidence than ``_await_playing`` ever had.
        * Once the first REAL buffer IS observed, fall back to the original
          S9-5 behavior unchanged: bound against ``stall_timeout_s`` (10s
          default) from the last observed advance, for a pipeline that aired
          fine and then silently stopped.

        Item 84c: "the first buffer IS observed" is no longer "any buffer
        past the arm-time snapshot" -- see ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_
        ARM`` and ``_arm_stall_watchdog`` for why a raw ``> 0`` check there
        was a tautology (the async output sink chain always prerolls at
        least one buffer before PLAYING is even reached). Real first output
        now requires the count to exceed the arm-time snapshot by at least
        ``_FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM`` buffers, all observed AFTER
        arming.

        A no-op while output is flowing either way (it resets the timer on
        every advance). The worker exits non-zero on either budget and the
        daemon restarts it to a known state."""
        now = time.monotonic()
        if self._output_buffers != self._stall_last_count:
            self._stall_last_count = self._output_buffers
            self._stall_last_advance_t = now
            if (
                not self._first_output_seen
                and self._output_buffers - self._output_buffers_at_arm
                >= _FIRST_OUTPUT_MIN_BUFFERS_AFTER_ARM
            ):
                self._first_output_seen = True
                self._maybe_print_first_output_marker()
            self._maybe_print_output_progress(now)
            return True  # output advancing — keep watching
        self._maybe_print_output_progress(now)
        elapsed = now - self._stall_last_advance_t
        if not self._first_output_seen:
            if self.first_output_timeout_s <= 0 or elapsed < self.first_output_timeout_s:
                return True
            # STDERR, not stdout (Gate A T4 visibility fix): the daemon reads the
            # worker's stderr tail into ``last_error`` when the child exits non-zero,
            # so the reason a channel bounced is on the operator's state row instead
            # of only in an uncollected stdout log.
            _ctrl_stderr(
                # ASCII only -- same reasoning as the stall message below (the
                # daemon folds this into the state row's last_error, written
                # to Postgres via a client_encoding that may not be UTF-8).
                f"CTRL first-output: no output within {int(self.first_output_timeout_s)}s "
                "of PLAYING - quitting for daemon restart"
            )
            # Distinct reason from ("stall", ...) below -- worker.py maps this
            # to its own exit code (GST_FIRST_OUTPUT_TIMEOUT_EXIT_CODE) so the
            # daemon's relaunch path can rate-limit it the same way it already
            # does GST_PREROLL_TIMEOUT_EXIT_CODE, instead of counting it as an
            # ordinary crash toward the fallback-slate streak.
            self._error = ("first-output-timeout", "no output buffers observed within bound")
            if self._loop is not None:
                self._loop.quit()
            return False  # one-shot: stop the watchdog
        if self.stall_timeout_s <= 0:
            # Post-first-buffer stall check disabled (operator opt-out) --
            # unchanged from the pre-item-84 semantics of ``stall_timeout_s <=
            # 0`` skipping the watchdog entirely, now scoped to just this
            # budget since the first-output budget above may still be active.
            return True
        if elapsed >= self.stall_timeout_s:
            # Round-3 finding 2: this watchdog no longer stands down for a commit.
            # Round 2 suspended it while ``commit_in_progress`` was set, which
            # stretched the worst-case dead air a viewer can see from
            # ``stall_timeout_s`` (10s) to ``commit_timeout_s`` (15s) on EVERY
            # wedge -- 50% more black. That trade only bought anything because a
            # round-2 commit kept the replacement leg held (dark) across old-leg
            # retirement. Round-3 finding 1 removed that: the replacement is on
            # air before retirement starts, so the only part of a commit that can
            # darken output is a handful of synchronous main-loop calls -- and
            # this check is itself a GLib timeout source on that same main loop,
            # so it cannot even run while they are executing. There is nothing
            # left to suspend for, and the commit watchdog still owns (and only
            # owns) that main-loop window. Worst-case dead air is back to
            # ``stall_timeout_s``.
            # STDERR, not stdout (Gate A T4 visibility fix): the daemon reads the
            # worker's stderr tail into ``last_error`` when the child exits non-zero,
            # so the reason a channel bounced is on the operator's state row instead
            # of only in an uncollected stdout log.
            _ctrl_stderr(
                # ASCII only: the daemon folds this line into the state row's
                # last_error, which is written to Postgres. A non-ASCII byte here
                # is re-read as U+FFFD (_child_stderr_tail reads errors="replace")
                # and a non-UTF8 client_encoding then fails the whole state write
                # -- see _child_stderr_tail's sanitiser and the T6 soak evidence
                # (soak-120-e502074-20260905).
                f"CTRL stall: no output for {int(self.stall_timeout_s)}s - quitting for daemon restart"
            )
            self._error = ("stall", "output stalled")  # → worker exits non-zero → restart
            if self._loop is not None:
                self._loop.quit()
            return False  # one-shot: stop the watchdog
        return True

    def _reset_stall_reference(self) -> None:
        """Start the post-first-output stall budget over at a commit boundary.

        A deferred (boundary-aligned) reload legitimately produces no output
        between the outgoing leg's last buffer and the replacement's first one, so
        part of the stall budget is normally already spent by the time a commit
        publishes. Handing the freshly-selected leg a FULL ``stall_timeout_s`` to
        resume output -- rather than whatever remained of the outgoing leg's
        budget -- is what keeps the watchdog measuring the new leg instead of the
        boundary. Round-3 finding 2: this is now the ONLY accommodation a commit
        gets from the stall watchdog; the watchdog itself never stands down, so
        the worst case a viewer can see stays ``stall_timeout_s``."""
        self._stall_last_advance_t = time.monotonic()

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
                _ctrl_stderr(
                    f"CTRL preroll: reached PLAYING after {time.monotonic() - started:.1f}s "
                    f"pid={os.getpid()}"
                )
                # Item 84 Round-2 review BLOCKER: the reference point the
                # NEW ``CTRL first-output: ...`` marker's ``Ns`` measures
                # from -- see ``_maybe_print_first_output_marker``. PLAYING
                # itself is deliberately NOT treated as on-air evidence
                # anywhere downstream; this timestamp only feeds that
                # marker's elapsed-time text.
                self._playing_reached_at = time.monotonic()
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
            _ctrl_stderr(
                f"CTRL preroll: still waiting for PLAYING after "
                f"{self.preroll_timeout_s - (deadline - now):.1f}s of "
                f"{self.preroll_timeout_s:.1f}s (get_state={result.value_nick}, "
                f"current={current.value_nick}, pending={pending.value_nick})"
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

    @staticmethod
    def _notify_reload_settled(
        callback: Callable[[bool, str | None], None] | None,
        committed: bool,
        reason: str | None,
    ) -> None:
        """Invoke one reload settlement callback without letting receipt I/O fail playout."""
        if callback is not None:
            with contextlib.suppress(Exception):
                callback(committed, reason)

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
        the prior leg is still uncommitted SUPERSEDES it. Once commit has selected a
        replacement, an overlap is explicitly rejected so the daemon can restart
        from the complete newest worker graph rather than queue only its program
        half.

        ``on_settled`` (item 4, honest ack): an optional ``(committed: bool,
        reason: str | None) -> None`` callback invoked EXACTLY ONCE for this
        specific call's reload -- with ``(True, None)`` from ``_commit_reload``, or
        ``(False, <reason>)`` from abort, failed commit cleanup, or stop. The reason
        is a stable diagnostic token such as ``timeout`` or ``cleanup-failed``. This is
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
        if getattr(self, "_stopping", False):
            self._notify_reload_settled(on_settled, False, "stopped")
            return
        if self._pending_reload is not None:
            if self._pending_reload.get("commit_in_progress", False):
                # The worker deserializes one graph, then calls reload_program()
                # before reload_graphics_overlay(). Privately saving only this
                # program leg would return control so that worker could advance the
                # corresponding overlay and ACK "armed" with no receipt binding the
                # delayed program request. Reject before building or mutating
                # anything. The worker reports an explicit error, strategy returns
                # False, and the daemon's existing fallback restarts from the
                # complete newest graph.
                raise RuntimeError("reload commit already in progress")
            # Supersede the still-settling reload with this newer one (never drop a
            # program change). The superseded leg is disposed before we build the new.
            print("CTRL reload superseding a still-settling reload", flush=True)
            self._abort_pending_reload("superseded")

        # Round-3 finding 4: MUST come before ``_link_leg_to_selectors`` below --
        # and therefore after the supersede above, which is one of the two things
        # that starts a retirement thread (a committed reload's own old-leg
        # retirement is the other). ``_abort_pending_reload`` returns as soon as
        # that thread has STARTED, so without this wait the very next statements
        # would call ``request_pad_simple("sink_%u")`` on an ``input-selector``
        # whose request pads another thread is concurrently releasing. Raising here
        # still satisfies this method's contract that a failure before the build
        # has committed no state: nothing has been instantiated or linked yet.
        #
        # Round-3 review finding 2: a refusal here used to be SILENT to the daemon
        # -- it happened before any transaction (and its ``on_settled``) existed,
        # so the FIFO path's reload-status sidecar was never written and the daemon
        # sat on its 960s settle deadline with the channel dark at the rollover.
        # Settle the caller with an ``aborted:`` reason FIRST, and print the
        # ``CTRL reload aborted:`` stdout marker the sandbox lane counts, then
        # raise for the dispatch path's own error report.
        try:
            self._await_selector_pads_quiet()
        except RuntimeError as exc:
            print(
                f"CTRL reload aborted: selector pads still held by a retiring leg; "
                f"keeping current program ({exc})",
                flush=True,
            )
            self._notify_reload_settled(on_settled, False, "selector-busy")
            raise

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
            # Round-2 finding 5: identifies THIS reload transaction. The boundary
            # probes live on the OUTGOING pads, which are the same pad objects
            # across successive transactions (``selector_sink_pads[0]`` until a
            # commit swaps it), so "is this pad one I am watching?" cannot tell a
            # superseded transaction's queued EOS from the current one's. Each
            # boundary probe therefore carries the id of the transaction that
            # installed it and ``_on_old_leg_eos`` compares it before settling.
            "txn_id": next(self._reload_txn_counter),
            "old_video_pad": old_video_pad,
            "old_audio_pad": old_audio_pad,
            "old_elements": old_elements,
            "new_elements": new_elements,
            "probe_id": None,
            "timeout_id": None,
            # Item 4 (honest ack): the caller's completion callback, if any --
            # invoked exactly once by ``_commit_reload`` or ``_abort_pending_reload``.
            "on_settled": on_settled,
            "commit_in_progress": False,
            "commit_watchdog": None,
            "commit_completed": None,
            "retirement_result": None,
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
            #   outgoing_eos_pads -- outgoing pads whose EOS callback has reached
            #                     the main loop (deduplicates queued callbacks).
            "new_src_pads": [pad for pad in (out_pad, audio_out_pad) if pad is not None],
            "hold_probes": [],
            "holds_awaited": 0,
            "boundary_probes": [],
            "outgoing_end": {},
            "outgoing_eos_pads": set(),
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
                        pending["txn_id"],
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

    def _on_outgoing_pad_data(
        self, pad: Gst.Pad, info: Gst.PadProbeInfo, txn_id: int
    ) -> Gst.PadProbeReturn:
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
            GLib.idle_add(self._on_old_leg_eos, pad, txn_id)
            return Gst.PadProbeReturn.DROP
        if event.type == Gst.EventType.SEGMENT and pending is not None:
            state = pending["outgoing_end"].setdefault(pad, {"end": None, "segment": None})
            state["segment"] = event.parse_segment()
        return Gst.PadProbeReturn.OK

    def _on_old_leg_eos(self, pad: Gst.Pad, txn_id: int) -> bool:
        """Main-loop: the first current outgoing stream reached its natural end.

        That first EOS is the A/V boundary and remains the cutover trigger. Waiting
        for both streams is not safe behind ``cccombiner``/``mpegtsmux``: a native
        three-worker counterexample reached video EOS on one channel, then stopped
        output and never delivered audio EOS. The commit switches both selectors at
        the first boundary. Native diagnostics separately identify whether the
        subsequent retirement blocks in an element state transition
        or in selector request-pad release.

        Commit if the new leg is already ready; otherwise just record the boundary
        -- the reload was triggered well before this point specifically so the new
        leg should already be ready, but if the schedule/preparer ran unexpectedly
        long the commit still waits for genuine readiness rather than switching to
        a leg with nothing buffered yet.

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
        # ``idle_add`` outlives the streaming-thread callback that queued it. A
        # superseding reload can replace ``_pending_reload`` before this runs; an
        # EOS from that older leg must never settle the new transaction (including
        # an immediate reload, whose expected set is empty).
        #
        # Round-2 finding 5: the pad identity alone cannot make that distinction.
        # The boundary probes sit on the OUTGOING pads, and those are the SAME pad
        # objects from one transaction to the next (``selector_sink_pads[0]`` is
        # only replaced when a commit swaps it), so a stale queued EOS from a
        # superseded transaction passed the old ``pad in expected`` test and
        # settled the transaction that replaced it. Compare the transaction id the
        # probe captured when it was installed instead; the pad-membership test
        # stays as the second half of the same guard.
        if txn_id != pending["txn_id"]:
            return False
        expected = {outgoing_pad for outgoing_pad, _probe_id in pending["boundary_probes"]}
        if pad not in expected:
            return False
        seen = pending["outgoing_eos_pads"]
        if pad in seen:
            return False
        seen.add(pad)
        stream = "video" if pad is pending["old_video_pad"] else "audio"
        _ctrl_stderr(
            "CTRL reload: outgoing EOS observed "
            f"stream={stream} ({len(seen & expected)}/{len(expected)} stream(s))"
        )
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
        if (
            pending is None
            or pending.get("commit_in_progress", False)
            or not pending["switch_at_end_of_current"]
        ):
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

    def _arm_commit_watchdog(self) -> tuple[threading.Timer, threading.Event]:
        """Item 85 (sandbox runs 12/14/15): ``_commit_reload`` must never be able to
        hang the worker forever. Seven soaks recorded the SAME wedge: the last line
        either worker ever printed was "boundary switch rebased...", then nothing --
        the process stayed alive but the pipe control reader stopped answering.
        Later physical traces localized it to synchronous old-leg disposal; see
        ``_commit_reload`` for the selector-lock/caption-GAP cycle and its repair.
        This watchdog remains the independent last-resort bound and live-stack
        evidence if any commit path wedges again -- see ``faulthandler`` below.

        A ``GLib.timeout_add_seconds`` source is USELESS as the sole guard here: if
        the wedge is (as measured) the GLib main-loop thread itself blocked inside a
        synchronous GStreamer call, the main loop never gets a turn to run ANY of
        its own timeout sources -- the same thread is stuck. Only a real OS-level
        thread, independent of the GLib loop, is guaranteed to fire regardless of
        what either retirement or main-loop finalization is doing. It remains armed
        until ``_finish_reload_commit`` completes cleanup, hold release, logging, and
        settlement; a commit that finishes in time never prints from this thread or
        calls ``os._exit``.

        Returns ``(timer, completed)``: ``completed`` is a ``threading.Event`` the
        caller sets (in its ``finally``, BEFORE calling ``timer.cancel()``) the
        moment the commit genuinely finishes. ``Timer.cancel()`` alone cannot
        close the race where the timer's own thread has ALREADY started running
        ``_on_commit_wedged`` (past the cancel-event check inside ``Timer.run``)
        at the exact moment the commit finishes -- cancelling at that point is a
        no-op, and without this second flag the watchdog would still dump a stack
        and force-exit a worker that had, in fact, just committed cleanly.
        ``_on_commit_wedged`` re-checks ``completed`` as its very first action and
        returns immediately, exiting nothing, if it is set.

        Deliberately does NOT attempt ANY pipeline teardown before exiting (no
        ``set_state(Gst.State.NULL)``, unlike a graceful ``stop()``): a downward
        state transition takes GStreamer's internal per-element ``STREAM_LOCK``,
        which is exactly the lock a genuinely wedged streaming thread already
        holds -- attempting it here would either do nothing (if the lock is free,
        in which case it wasn't a real wedge) or itself block this watchdog
        thread indefinitely, defeating the one guarantee this method exists to
        provide. ``os._exit`` is called unconditionally (in a ``finally``)
        immediately after the diagnostic dump, with no attempt at a clean exit in
        between -- the exit must fire even if the dump or the print themselves
        raise (e.g. a closed/unusable stderr).

        No ``WORKER_RESULT`` receipt is ever emitted on this path, BY DESIGN: the
        whole reason this watchdog exists is that the main thread that would
        normally build and print that receipt is presumed stuck forever, and
        ``os._exit`` bypasses every remaining line of Python on this process,
        including the one that would print it. A caller reading this worker's
        exit (e.g. ``civiccast.native.installed_gstreamer_smoke.
        require_clean_worker_result``) must treat
        ``GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE`` as its own distinct, receipt-less
        signal, not as a missing-receipt failure of some other kind."""
        completed = threading.Event()

        def _on_commit_wedged() -> None:
            if completed.is_set():
                return  # the commit finished; cancel() lost the race, this didn't
            try:
                # FIRST: dump every thread's live Python stack to stderr -- this
                # is the actual deliverable that localizes the wedge on the next
                # soak that reproduces it (round 1 of this item shipped a
                # hypothesis about where it was without this proof; review
                # rejected that hypothesis and asked for the instrument instead
                # of another guess).
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                _ctrl_stderr(
                    "CTRL reload: commit did not finish within "
                    f"{self.commit_timeout_s:.0f}s - quitting for daemon restart"
                )
            finally:
                # Unconditional: the exit must happen even if stderr itself is
                # unusable (a closed fd, a broken pipe) and the dump/print above
                # raised -- this watchdog's one job is to guarantee the process
                # goes away, not to guarantee a clean diagnostic first.
                os._exit(int(GST_RELOAD_COMMIT_TIMEOUT_EXIT_CODE))

        # self.commit_timeout_s is already validated/clamped by
        # _resolve_commit_timeout_s in __init__ -- no inline floor needed here.
        timer = threading.Timer(self.commit_timeout_s, _on_commit_wedged)
        timer.daemon = True
        timer.start()
        return timer, completed

    def _commit_reload(self) -> bool:
        """Put the replacement on air, then retire the outgoing leg behind it.

        A no-op if the reload was aborted/superseded before this fired. ``return
        False`` keeps the GLib timeout/idle source one-shot.

        Round-3 finding 1 -- THE ORDER IS THE FIX. Round 2 switched the selector,
        retired the old leg on a worker thread, and only released the replacement's
        hold probes afterwards, in ``_finish_reload_commit``. Output was therefore
        dark for the entire length of old-leg retirement: the outgoing leg had
        stopped, the incoming leg was still held, and the mux had nothing to
        forward. Under CPU load (a box pinned at 100%) that retirement outran the
        15s commit watchdog in 4 of 24 measured runs, every one with the same
        signature -- ``stage=switching-selector``, the output counter flatlining,
        then ``commit did not finish within 15s`` and ``os._exit``. A slow teardown
        of an already-replaced leg was killing a channel that had a perfectly good
        replacement ready to play.

        The commit now has two clearly separated halves:

        * ON AIR (this method, on the GLib main loop, watchdog-covered): rebase and
          switch the selector, release the replacement's holds, declare the commit
          finished, settle the caller. Every one of these is a bounded,
          synchronous, local call, and together they are the ONLY part of a commit
          that can darken output -- which is precisely the window
          ``_arm_commit_watchdog`` now covers, and nothing more.
        * BEHIND IT (``_start_old_leg_retirement``, on a worker thread, no
          watchdog): NULL, unlink and remove the outgoing leg, and only then drop
          the outgoing pads' EOS-drop probes. Output is already flowing from the
          replacement while this runs, so its slowness cannot darken anything, and
          its failure is reported (never fatal): a bus error from a retiring leg is
          contained in ``_on_bus``, an element that will not reach NULL is bounded
          and recorded as an orphan by ``_dispose_source_leg``, and neither path
          quits the loop.

        The boundary probes staying installed across retirement is load-bearing and
        was measured, not assumed: an earlier round-3 revision dropped them in the
        on-air half, one statement before the hold release, and three-worker
        rollovers then failed with unclean teardowns and GStreamer
        "trying to dispose element ... instead of the NULL state" criticals -- the
        retiring leg's late audio EOS reaching the mux, exactly what
        ``_on_outgoing_pad_data``'s own docstring says that probe exists to stop.

        Item 85 history: the round-2 ordering existed because releasing the
        replacement's holds while old request-pad release was in flight was thought
        to race ``input-selector``'s active-pad reader lock against its writer lock.
        Round 3 keeps the two apart the other way round -- and keeps them apart for
        the NEXT transaction too, which is what ``_await_selector_pads_quiet``
        (finding 4) serialises -- while never leaving the mux unfed. The bounded
        queues immediately downstream of the selectors, which were part of that
        same measured combination, are unchanged.

        Staged stderr prints (``stage=switching-selector`` / ``holds-released`` /
        ``committed``, then ``old-leg-disposed`` from the retirement thread) show
        exactly where any future regression stalls, and the commit watchdog still
        dumps every thread's live Python stack before force-exiting if the on-air
        half ever wedges."""
        pending = self._pending_reload
        if pending is None or pending.get("commit_in_progress", False):
            return False  # aborted or superseded before the first buffer landed
        pending["commit_in_progress"] = True
        try:
            watchdog, completed = self._arm_commit_watchdog()
        except Exception as exc:
            pending["commit_in_progress"] = False
            print(f"ERROR: reload commit watchdog did not start: {exc!r}", flush=True)
            self._abort_pending_reload("commit-watchdog-start")
            return False
        pending["commit_watchdog"] = watchdog
        pending["commit_completed"] = completed
        try:
            self._begin_reload_commit(pending)
            published = self._finish_reload_commit(pending)
        except Exception as exc:
            # The selector switch is the first thing ``_begin_reload_commit`` does
            # after its own validation, so a raise here means either nothing was
            # switched (the outgoing leg is still on air and must NOT be retired)
            # or the switch itself failed. Either way: publish nothing, retire
            # nothing, release the replacement's holds so no streaming thread stays
            # parked, and tell the caller the truth. The daemon restarts from the
            # newest complete graph.
            self._finish_commit_watchdog(pending)
            self._pending_reload = None
            pending["commit_in_progress"] = False
            for pad, probe_id in pending["boundary_probes"]:
                with contextlib.suppress(Exception):
                    pad.remove_probe(probe_id)
            self._release_hold_probes(pending)
            print(
                f"ERROR: reload commit failed before the replacement went live: {exc!r}",
                file=sys.stderr,
                flush=True,
            )
            self._notify_reload_settled(pending["on_settled"], False, "commit-failed")
            self._reset_stall_reference()
            return False
        if not published:
            # Round-3 review finding 5: retire the outgoing leg ONLY behind a
            # commit that actually published. ``_finish_reload_commit`` declines
            # when the transaction is no longer current (``stop()`` dropped it
            # between the two on-air steps); the whole-pipeline teardown then
            # owns every element, and starting a retirement thread against it
            # would race that teardown for the same elements' locks. The watchdog
            # is disarmed here too (idempotent) so a declined publish can never
            # be followed by a force-exit.
            self._finish_commit_watchdog(pending)
            print(
                "WARN: reload commit switched but did not publish (transaction no longer "
                "current); the outgoing leg is left to the whole-pipeline teardown",
                file=sys.stderr,
                flush=True,
            )
            return False
        self._start_old_leg_retirement(pending)
        return False

    def _begin_reload_commit(self, pending: dict[str, Any]) -> None:
        """First on-air step: rebase the replacement and switch the selector(s)."""
        for timeout_key in ("timeout_id", "defer_timeout_id"):
            if pending[timeout_key] is not None:
                with contextlib.suppress(Exception):
                    GLib.source_remove(pending[timeout_key])
        new_video_pad = pending["new_video_pad"]
        new_audio_pad = pending["new_audio_pad"]
        selector = self.selector
        if selector is None:
            raise RuntimeError("video selector disappeared during reload commit")
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
        _ctrl_stderr("CTRL reload diagnostic: stage=switching-selector")
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

    def _finish_reload_commit(self, pending: dict[str, Any]) -> bool:
        """Second on-air step: let the replacement flow and publish the commit.

        Round-3 finding 1: this used to run AFTER old-leg retirement, off a
        ``GLib.idle_add`` from the retirement thread, which is what made the dark
        window as long as a teardown. It is now called synchronously from
        ``_commit_reload``, immediately after the selector switch, so the gap
        between "the outgoing leg stopped" and "the incoming leg is flowing" is a
        few main-loop statements. Retirement has not started yet and its outcome no
        longer gates -- or can fail -- the commit.

        Returns True when THIS call published the commit, False when it declined
        because ``pending`` is no longer the current transaction. Round-3 review
        finding 5: ``_commit_reload`` starts old-leg retirement only on True. This
        is no longer scheduled as a GLib source anywhere (the round-3 ordering
        calls it synchronously), so the old ``return False`` one-shot contract no
        longer applies -- the return value is the publish verdict."""
        if self._pending_reload is not pending or not pending.get("commit_in_progress", False):
            return False
        # The outgoing pads' EOS-drop probes deliberately STAY installed here and
        # are removed by the retirement thread once the old leg is actually
        # disposed. See ``_on_outgoing_pad_data``: the retiring leg can still emit
        # an EOS (the audio stream typically ends a beat after video) right up
        # until it is unlinked and NULLed, and an EOS from an outgoing pad in that
        # window takes the whole channel off air. Round 3 measured that exactly --
        # removing them here, one statement before the holds are released, made
        # three-worker rollovers fail with unclean teardowns and GStreamer
        # "trying to dispose element ... instead of the NULL state" criticals.
        self._release_hold_probes(pending)
        print("CTRL reload: holds released", flush=True)
        _ctrl_stderr("CTRL reload diagnostic: stage=holds-released")
        # Round-3 finding 1: the element count moved to the retirement line below,
        # because at THIS point the outgoing leg is still in the pipeline by
        # design. ``CTRL reload committed`` stays exactly where every existing
        # evidence consumer looks for it (stdout, one line, settlement marker); the
        # sandbox stdout parser has always accepted it with or without the count.
        print("CTRL reload committed", flush=True)
        _ctrl_stderr("CTRL reload diagnostic: stage=committed")
        self._pending_reload = None
        # Disarm BEFORE the callback: the watchdog exists to bound the window in
        # which output can be dark, and output is flowing as of the hold release
        # above. A slow ``on_settled`` (the worker's pipe write) is not that
        # window and must never be able to force-exit a committed channel.
        self._finish_commit_watchdog(pending)
        self._reset_stall_reference()
        # Item 4 (honest ack): tell the caller the reload actually landed. Fired
        # last, and guarded so a callback failure can never re-wedge a reload that
        # has, in every other respect, already committed cleanly.
        self._notify_reload_settled(pending["on_settled"], True, None)
        return True

    def _start_old_leg_retirement(self, pending: dict[str, Any]) -> None:
        """Retire the already-replaced outgoing leg off the GLib loop.

        Round-3 finding 1: everything this touches is off air before it starts, so
        nothing here is allowed to end the run. A retirement that is slow, that
        errors, or that cannot bring an element to NULL is reported -- loudly,
        naming the element -- and the channel keeps playing the replacement. The
        commit watchdog is already disarmed by the time this runs; the stall
        watchdog, unsuspended (finding 2), remains the one escalation that can take
        this channel down, and it does so only on the evidence that actually
        matters: output stopped."""
        old_elements = pending["old_elements"]
        # Round-3 review finding 4: the instrument. Every retirement line below
        # carries how long the retirement took from THIS point, so a slow leg
        # (inside its 12s budget) and a wedged one (the ERROR line) are both
        # measurable against the daemon's clock, not inferred from line order.
        retirement_started = time.monotonic()
        # Round-3 finding 4 (closing the gap the first round-3 cut left open):
        # the retirement must be VISIBLE -- counted against the selector-pad gate
        # and listed for bus-error containment -- before this method returns,
        # not merely once the worker thread gets scheduled and reaches
        # ``_dispose_source_leg``. ``thread.start()`` returns as soon as the OS
        # thread exists, and on a loaded box the main loop can run the next
        # ``reload_program`` (and its ``request_pad_simple``) before that thread
        # has executed a single statement. Announce here, on the calling thread;
        # ``_dispose_source_leg`` concludes it in its ``finally``.
        self._announce_retirement(old_elements)

        def _retire() -> None:
            try:
                retired, detail = self._dispose_source_leg(
                    pending["old_video_pad"],
                    pending["old_audio_pad"],
                    old_elements,
                    announced=True,
                )
            except Exception as exc:  # defensive: disposal returns a failure result
                retired, detail = False, f"unexpected retirement error: {exc!r}"
            # Only NOW may the outgoing pads' EOS-drop probes go -- the leg they
            # guard is unlinked and at NULL, so it can no longer emit the late EOS
            # that would otherwise reach the mux and end the run.
            for pad, probe_id in pending["boundary_probes"]:
                with contextlib.suppress(Exception):  # may already have auto-removed
                    pad.remove_probe(probe_id)
            element_count = self._element_count()
            elapsed = time.monotonic() - retirement_started
            if retired:
                # Element count proves disposal reclaimed (the leak test asserts it
                # is flat across many reloads -- a dispose leak would grow it). It
                # is reported HERE, not on the commit line, because the outgoing
                # leg is still in the pipeline when the commit publishes.
                print(f"CTRL reload: old leg disposed (elements={element_count})", flush=True)
                _ctrl_stderr(
                    f"CTRL reload diagnostic: stage=old-leg-disposed elements={element_count} "
                    f"elapsed={elapsed:.3f}s"
                )
                return
            print(
                f"ERROR: reload retired the old leg incompletely: {detail}; the replacement "
                f"stays on air (elements={element_count} elapsed={elapsed:.3f}s). A retirement "
                "problem that really does stop output is the stall watchdog's to escalate, "
                "with better evidence.",
                file=sys.stderr,
                flush=True,
            )

        # Round-3 review finding 2b: the retirement is ALREADY announced above, so
        # from here every failure -- constructing the thread as much as starting
        # it -- must end in ``_retire()`` running (which concludes the claim in
        # ``_dispose_source_leg``'s ``finally``) rather than propagating out of
        # ``_commit_reload`` with the gate held and the boundary probes installed.
        thread: threading.Thread | None = None
        try:
            thread = threading.Thread(
                target=_retire, name="civiccast-reload-retirement", daemon=True
            )
            self._reload_commit_thread = thread
            self._commit_retire_threads = [t for t in self._commit_retire_threads if t.is_alive()]
            self._commit_retire_threads.append(thread)
            thread.start()
        except Exception as exc:
            # A thread that will not start must not leak the leg. Retiring inline
            # on the main loop is the lesser problem than never cleaning up: the
            # replacement is already on air, so a blocking teardown here delays the
            # loop but does not darken output, and the stall watchdog still owns a
            # real outage.
            self._reload_commit_thread = None
            if thread is not None and thread in self._commit_retire_threads:
                self._commit_retire_threads.remove(thread)
            print(
                f"WARN: reload old-leg retirement running inline; "
                f"worker thread did not start: {exc!r}",
                file=sys.stderr,
                flush=True,
            )
            _retire()

    @staticmethod
    def _finish_commit_watchdog(pending: dict[str, Any]) -> None:
        completed = pending.get("commit_completed")
        watchdog = pending.get("commit_watchdog")
        if completed is not None:
            # Set BEFORE cancel(): closes Timer.cancel()'s already-running race.
            completed.set()
        if watchdog is not None:
            watchdog.cancel()

    def _on_reload_timeout(self) -> bool:
        """Watchdog: the new reload leg never produced a first buffer in time. Abort so
        the channel isn't wedged on a never-committing reload; the old program keeps
        playing and the next due program can retry."""
        if self._pending_reload is None or self._pending_reload.get("commit_in_progress", False):
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
        if pending.get("commit_in_progress", False):
            # The replacement is already selected; aborting it would tear down
            # active media. Commit failure/stop owns recovery from this point.
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
        # Round-2 finding 1, half one: DETACH BEFORE RELEASE. Lifting the holds
        # lets this leg's streaming threads run again, and until now they ran
        # straight into the input-selector on a pad that is still INACTIVE. That
        # is a state the selector was never configured for: the class docstring on
        # ``_SELECTOR_PROPS`` says in as many words that the deferred switch "never
        # relies on" ``sync-streams`` because a held leg "pushes nothing at all
        # while inactive" -- which stops being true the moment an abort releases
        # it. On the commit path the same release happens only AFTER the pad has
        # been made active, so the two paths were releasing into two very
        # different selector states. Dropping this leg's data at its own src pads
        # keeps the abort path's promise structural rather than incidental: the
        # retiring leg cannot perturb the selector because nothing of it ever
        # reaches the selector.
        self._detach_leg_from_selectors(pending)
        self._release_hold_probes(pending)
        if pending["timeout_id"] is not None and reason != "timeout":
            # 'timeout' means the watchdog source is firing now (auto-removed on return).
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["timeout_id"])
        if pending["defer_timeout_id"] is not None:
            with contextlib.suppress(Exception):
                GLib.source_remove(pending["defer_timeout_id"])
        # Round-2 finding 1, half two: RETIRE OFF THE LOOP, exactly as the commit
        # path already does. ``_abort_pending_reload`` runs on the GLib main loop
        # (bus handler, watchdog, or supersede), and ``_dispose_source_leg`` calls
        # ``set_state(NULL)``, which BLOCKS until the leg's streaming threads are
        # joined. On a healthy leg that is fast -- measured at 0.078s on this
        # repository's own supersede reproducer -- but the leg being aborted on the
        # "error" path is by definition not healthy, and a NULL that blocks there
        # would take the main loop with it: no stall watchdog, no commit watchdog,
        # no control-plane reader, on a channel that is otherwise still on air.
        # Retiring on a worker thread makes that whole class impossible. Item 3's
        # result tuple is consumed and reported there rather than discarded.
        self._start_aborted_leg_retirement(
            reason,
            pending["new_video_pad"],
            pending["new_audio_pad"],
            pending["new_elements"],
        )
        # Item 4 (honest ack): tell the caller this reload did NOT land, and why --
        # ``reason`` is one of "error"/"timeout"/"superseded"/"build-error"/
        # "selector-missing" (the strings each call site above passes). Fired
        # without waiting on retirement: the reload's OUTCOME is already decided,
        # and blocking an honest ack behind cleanup is what item 4 fixed.
        self._notify_reload_settled(pending["on_settled"], False, reason)

    @staticmethod
    def _detach_leg_from_selectors(pending: dict[str, Any]) -> None:
        """Drop everything an aborted leg produces, at the leg's OWN src pads.

        Must run BEFORE ``_release_hold_probes``: once the holds are gone the
        leg's streaming threads are free, and this probe is what keeps their
        output out of the selector. Best-effort per pad -- a leg must never stay
        wedged because one probe could not be installed."""
        # ``.get`` deliberately: an abort is a SAFETY path reached from the bus
        # handler and the watchdogs, so it must degrade rather than raise if a
        # transaction was recorded without its src pads.
        for pad in pending.get("new_src_pads") or ():
            with contextlib.suppress(Exception):
                pad.add_probe(
                    Gst.PadProbeType.BUFFER
                    | Gst.PadProbeType.BUFFER_LIST
                    | Gst.PadProbeType.EVENT_DOWNSTREAM,
                    _drop_everything_probe,
                )

    def _start_aborted_leg_retirement(
        self,
        reason: str,
        video_pad: Gst.Pad,
        audio_pad: Gst.Pad | None,
        elements: list[Gst.Element],
    ) -> None:
        """Retire an aborted leg on a worker thread; see ``_abort_pending_reload``.

        Round-3 finding 4: the retirement is announced on THIS thread, before the
        worker starts, so ``_abort_pending_reload("superseded")`` returning is
        already enough for the next ``reload_program`` to see it at the
        selector-pad gate. See ``_start_old_leg_retirement``."""
        self._announce_retirement(elements)

        def _retire() -> None:
            try:
                retired, detail = self._dispose_source_leg(
                    video_pad, audio_pad, elements, announced=True
                )
            except Exception as exc:  # defensive: disposal returns a failure result
                retired, detail = False, f"unexpected abort retirement error: {exc!r}"
            if not retired:
                print(
                    f"WARN: aborted reload leg ({reason}) did not retire cleanly: {detail}",
                    file=sys.stderr,
                    flush=True,
                )

        # Round-3 review finding 2b: construction inside the ``try`` too -- the
        # retirement is already announced, so a raise anywhere from here must end
        # in the inline ``_retire()`` that concludes it, never propagate.
        thread: threading.Thread | None = None
        try:
            self._abort_retire_threads = [t for t in self._abort_retire_threads if t.is_alive()]
            thread = threading.Thread(target=_retire, name="cc-abort-retire", daemon=True)
            self._abort_retire_threads.append(thread)
            thread.start()
        except Exception as exc:
            # A thread that will not start must not leak the leg: fall back to the
            # in-line retirement this method exists to move OFF the loop. The
            # blocking risk is the lesser problem versus never cleaning up at all.
            if thread is not None and thread in self._abort_retire_threads:
                self._abort_retire_threads.remove(thread)
            print(
                f"WARN: aborted reload leg ({reason}) retiring inline; "
                f"worker thread did not start: {exc!r}",
                file=sys.stderr,
                flush=True,
            )
            _retire()

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

    def _belongs_to_retiring_leg(self, src: object) -> bool:
        """True if ``src`` (a bus-message source) is an element of a leg whose
        retirement is currently in flight, or nested under one.

        Round-3 finding 1: retirement now runs BEHIND an already-on-air
        replacement, so these messages describe a teardown in progress, not a
        channel in trouble. ``_on_bus`` uses this to report them instead of
        quitting the loop. Mirrors ``_belongs_to_pending_reload``, which answers
        the same question for the leg that has not gone on air yet."""
        if src is None:
            return False
        # Snapshot: this list is appended to and removed from by retirement
        # threads while the main loop reads it.
        legs = list(self._retiring_legs)
        if not legs:
            return False
        node = src
        while node is not None:
            for elements in legs:
                if node in elements:
                    return True
            node = node.get_parent() if hasattr(node, "get_parent") else None
        return False

    def _announce_retirement(self, elements: list[Gst.Element]) -> None:
        """Make one leg's retirement visible before anything of it runs.

        Round-3 findings 1 and 4. Two things must be able to see a retirement for
        the WHOLE time it could touch the pipeline: ``_on_bus`` (so the leg's
        teardown errors are contained, not fatal) and ``_await_selector_pads_quiet``
        (so the next transaction's ``request_pad_simple`` never overlaps this
        leg's ``release_request_pad``). "The whole time" starts when the thread
        is created, not when it is first scheduled -- so the two starters call
        this on the calling thread and pass ``announced=True`` to
        ``_dispose_source_leg``, whose ``finally`` calls ``_conclude_retirement``.
        A direct caller of ``_dispose_source_leg`` (tests, the inline fallback)
        is announced by that method itself."""
        self._retiring_legs.append(elements)
        with self._selector_pads_quiet:
            self._selector_pad_retirements += 1
            self._retirement_ledger.append(
                {"elements": elements, "started": time.monotonic(), "abandoned": False}
            )

    def _conclude_retirement(self, elements: list[Gst.Element]) -> None:
        """Undo ``_announce_retirement``; wakes any ``reload_program`` waiting.

        Round-3 review finding 2: a retirement the waiter has already ABANDONED
        (``_abandon_overdue_retirements_locked``) had its claim on the gate
        concluded then; a thread that finally does return must not conclude it a
        second time and drive the count negative."""
        with self._selector_pads_quiet:
            record = next(
                (entry for entry in self._retirement_ledger if entry["elements"] is elements),
                None,
            )
            if record is not None:
                self._retirement_ledger.remove(record)
            if record is None or not record["abandoned"]:
                self._selector_pad_retirements -= 1
            self._selector_pads_quiet.notify_all()
        with contextlib.suppress(ValueError):
            self._retiring_legs.remove(elements)

    def _abandon_overdue_retirements_locked(self, now: float) -> float | None:
        """Conclude the claim of every retirement older than the abandon bound.

        Round-3 review finding 2. Called with ``_selector_pads_quiet`` HELD. A
        retirement whose thread never returns (``set_state(NULL)`` blocked forever
        inside a streaming task) never reaches ``_dispose_source_leg``'s
        ``finally``, so without this every later ``reload_program`` would fail at
        the gate forever -- permanent dead air at the next rollover. Once a
        retirement has held its claim for ``_RETIREMENT_ABANDON_AFTER_S`` (the
        whole leg budget plus margin) it has, by construction, already overrun
        every bound ``_dispose_source_leg`` applies to itself; its claim is
        concluded here, its elements are recorded as orphans (state-locked and
        still in the pipeline; ``stop()`` unlocks them before the whole-pipeline
        NULL), and an ERROR names them. The leg STAYS listed in
        ``_retiring_legs``: a bus ERROR from an abandoned, off-air leg is still a
        teardown message, not a channel failure.

        Returns the monotonic time at which the youngest surviving claim will
        become overdue, or None when nothing is still claimed."""
        next_due: float | None = None
        for record in list(self._retirement_ledger):
            if record["abandoned"]:
                continue
            age = now - record["started"]
            if age < _RETIREMENT_ABANDON_AFTER_S:
                due = record["started"] + _RETIREMENT_ABANDON_AFTER_S
                next_due = due if next_due is None else min(next_due, due)
                continue
            record["abandoned"] = True
            self._selector_pad_retirements -= 1
            elements = record["elements"]
            self._orphaned_leg_elements.extend(elements)
            named = ", ".join(_element_label(element) for element in elements) or "-"
            print(
                f"ERROR: reload leg retirement abandoned after {age:.1f}s (bound "
                f"{_RETIREMENT_ABANDON_AFTER_S:.0f}s): its thread never returned from "
                f"disposal. {len(elements)} element(s) stay locked in the pipeline as "
                f"orphans ({named}); {len(self._orphaned_leg_elements)} orphan(s) for this "
                "worker so far. Later reloads proceed; stop() reports the orphans.",
                file=sys.stderr,
                flush=True,
            )
        return next_due

    def _await_selector_pads_quiet(self) -> None:
        """Block, bounded, until no retirement still holds selector request pads.

        Round-3 finding 4. ``_dispose_source_leg`` runs on a worker thread and
        calls ``release_request_pad`` on this pipeline's ``input-selector``
        elements; ``_link_leg_to_selectors`` runs on the GLib loop and calls
        ``request_pad_simple("sink_%u")`` on those same elements. Round 2 made the
        first asynchronous without serialising it against the second, so
        ``_abort_pending_reload("superseded")`` -- which returns as soon as the
        retirement THREAD has started, not when it has finished -- was immediately
        followed by a pad request racing that thread's release.

        Round-3 review finding 3: the bound is ``_SELECTOR_PAD_QUIESCE_TIMEOUT_S``,
        DERIVED from the leg's own disposal budgets (8s + 4s) plus a margin -- not
        the 2s the first round-3 cut sized against a healthy ~0.08s disposal. A
        retirement that is slow but inside its own budget is waited for, never
        refused; the wait costs the GLib loop that long in the worst case and
        nothing at all in the normal one (the count is usually already zero). It
        does not darken output: the streaming threads that feed the mux are not
        this thread.

        Round-3 review finding 2: a retirement that has held its claim past
        ``_RETIREMENT_ABANDON_AFTER_S`` is abandoned (its claim concluded, its
        elements recorded as orphans, an ERROR printed) instead of being waited
        on, so a retirement thread that never returns can block exactly one later
        reload for the bound and none after it. Exceeding the bound with a claim
        still outstanding (a retirement announced by a caller other than the two
        starters, or a count set without a ledger record) raises, which
        ``reload_program`` settles as ``aborted:selector-busy`` and reports BEFORE
        building or mutating anything."""
        deadline = time.monotonic() + _SELECTOR_PAD_QUIESCE_TIMEOUT_S
        with self._selector_pads_quiet:
            while True:
                now = time.monotonic()
                next_due = self._abandon_overdue_retirements_locked(now)
                if self._selector_pad_retirements <= 0:
                    return
                remaining = deadline - now
                if remaining <= 0:
                    raise RuntimeError(
                        "a retiring reload leg still holds this pipeline's input-selector "
                        f"request pads after {_SELECTOR_PAD_QUIESCE_TIMEOUT_S:.1f}s; refusing "
                        "to request new selector pads into that race"
                    )
                wait_s = remaining
                if next_due is not None:
                    wait_s = min(wait_s, max(0.0, next_due - now))
                self._selector_pads_quiet.wait(wait_s)

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
        video_pad: Gst.Pad | None,
        audio_pad: Gst.Pad | None,
        elements: list[Gst.Element],
        *,
        announced: bool = False,
    ) -> tuple[bool, str | None]:
        """NULL, unlink/release, and remove a now-inactive source leg.

        Runs on a retirement worker thread, always BEHIND a leg that is already on
        air (round-3 finding 1), so nothing here is on the critical path for
        output. Every step is best-effort so one failure cannot prevent the
        remaining cleanup, and the explicit result is load-bearing for the honest
        retirement log line: a partial retirement is never reported as clean.

        Policy, applied identically on the commit path and the abort path:

        * ``set_state(NULL)`` returning ASYNC is NOT a failure. These legs are
          bins; see ``_null_retiring_element``. Wait for it, bounded.
        * Round-3 finding 3: the whole leg's descent to NULL -- every element,
          both attempts -- is bounded by ONE deadline, ``_LEG_DISPOSAL_BUDGET_S``.
          Round 2 applied ``_LEG_NULL_ASYNC_WAIT_S`` per element, so a real
          77-element leg had an arithmetic worst case near five minutes.
        * Round-3 finding 5: an element still above NULL when that budget is spent
          gets one more bounded sweep (``_LEG_ORPHAN_RETRY_BUDGET_S``); whatever
          survives is an ORPHAN. Orphans are counted in ``_orphaned_leg_elements``,
          named in an ERROR line, and NEVER passed to ``pipeline.remove`` --
          removing an element that is not at NULL is invalid, and round 2 did it
          unconditionally, leaving a possibly-running element detached from the
          pipeline with nothing watching it at all.
        * A failed unlink or a failed ``pipeline.remove`` is logged as a WARNING
          and does NOT fail the retirement. The leg is already at NULL and off air
          by that point; the cost is bookkeeping, not airtime.
        * Nothing here kills a channel that is still producing. A retirement
          problem that DOES take the channel off air stops the mux, and the stall
          watchdog already owns that escalation with far better evidence than a
          disposal return code can carry.

        Item 85 history: a round-1 hypothesis reordered this to unlink/release
        BEFORE ``set_state(Gst.State.NULL)``, with FLUSH_START/FLUSH_STOP
        bracketing the unlink, on the theory that a streaming thread parked inside
        input-selector's own wait needed waking before its element could be safely
        NULLed. REVERTED after review: releasing/unlinking the selector's request
        pad before the retiring leg's OWN elements reach NULL races that leg's
        still-live streaming thread into pushing into a pad that no longer has a
        peer -- ``GST_FLOW_NOT_LINKED``, a FATAL flow error on this leg's own
        source pad, not a benign no-op. And ``FLUSH_START`` sent directly to the
        selector's sink pad does not reach (and cannot unblock) a thread blocked
        further upstream in this leg's OWN elements; ``flush_stop(True)``
        immediately after re-opens the exact race window it was meant to close.
        The NULL-then-release ordering below is therefore unchanged."""
        failures: list[str] = []
        warnings: list[str] = []
        # Round-3 findings 1 and 4: this retirement is announced for the whole
        # time it could touch the pipeline (see ``_announce_retirement``). The
        # thread starters announce BEFORE their thread exists, so the count is
        # already right by the time the starter returns; a direct caller is
        # announced here.
        if not announced:
            self._announce_retirement(elements)
        try:
            deadline = time.monotonic() + _LEG_DISPOSAL_BUDGET_S
            unsettled: list[tuple[int, Gst.Element]] = []
            for index, element in enumerate(elements):
                if not self._null_retiring_element(element, index + 1, failures, deadline):
                    unsettled.append((index + 1, element))
            orphans = self._sweep_unsettled_elements(unsettled, failures)
            orphan_ids = {id(element) for _index, element in orphans}
            for stream, selector, pad in (
                ("video", self.selector, video_pad),
                ("audio", self.audio_selector, audio_pad),
            ):
                if selector is None or pad is None:
                    continue
                try:
                    peer = pad.get_peer()
                    if peer is not None and peer.unlink(pad) is False:
                        warnings.append(f"selector-unlink-failed:{stream}")
                    selector.release_request_pad(pad)
                except Exception as exc:
                    warnings.append(f"selector-release-error:{stream}:{exc!r}")
            for index, element in enumerate(elements):
                if id(element) in orphan_ids:
                    # Round-3 finding 5: an element above NULL is not removable.
                    # It stays in the pipeline, tracked and reported below.
                    continue
                try:
                    if self.pipeline.remove(element) is False:
                        warnings.append(f"element-remove-failed:{index + 1}")
                except Exception as exc:
                    warnings.append(f"element-remove-error:{index + 1}:{exc!r}")
        finally:
            self._conclude_retirement(elements)
        if orphans:
            self._orphaned_leg_elements.extend(element for _index, element in orphans)
            named = ", ".join(f"{index}:{_element_label(element)}" for index, element in orphans)
            print(
                f"ERROR: reload leg disposal left {len(orphans)} element(s) above NULL after "
                f"{_LEG_DISPOSAL_BUDGET_S + _LEG_ORPHAN_RETRY_BUDGET_S:.0f}s ({named}). They stay "
                "in the pipeline, NOT removed (remove() is only valid at NULL), and are counted "
                f"as orphans: {len(self._orphaned_leg_elements)} for this worker so far. The "
                "channel keeps playing its replacement; the stall watchdog owns a real outage.",
                file=sys.stderr,
                flush=True,
            )
        if warnings:
            # Reported, never fatal. See the policy note in the docstring -- an
            # unlink/remove hiccup on a leg that is already at NULL leaks
            # bookkeeping, not airtime, and the element-count assertion in the leak
            # test is what actually guards that.
            print(f"WARN: leg disposal incomplete: {'; '.join(warnings)}", flush=True)
        if failures:
            reason = "; ".join(failures)
            print(f"WARN: leg disposal did not reach NULL: {reason}", flush=True)
            return False, reason
        return True, None

    def _null_retiring_element(
        self,
        element: Gst.Element,
        index: int,
        failures: list[str],
        deadline: float,
    ) -> bool:
        """Bring ONE element of a retiring leg to NULL, inside the LEG's deadline.

        Returns True when the element genuinely reached NULL. Returns False when it
        did not; a hard error is recorded in ``failures`` immediately, while a
        merely-unsettled element is left for ``_sweep_unsettled_elements`` to give
        one last bounded chance and to record as an orphan if it still will not go.

        ASYNC is the case the original code got wrong. A ``set_state(NULL)`` is
        synchronous for a plain element, but these legs are BINS
        (``decodebin``/``uridecodebin`` and friends), and a bin whose children are
        still winding down legitimately returns ASYNC on a downward transition.
        Treating that as "incomplete cleanup" made an ordinary, correct retirement
        report failure. Wait for it instead.

        Round-3 finding 3: the wait is ``_LEG_NULL_ASYNC_WAIT_S`` OR whatever is
        left of the leg-wide ``deadline``, whichever is smaller. The per-element
        constant is a cap on one element; it is not, and never was, a licence for
        each of 77 elements to spend it.

        The element's state is LOCKED before the first ``set_state(NULL)`` so the
        pipeline's own state cascade cannot set it back to PLAYING behind this
        loop's back; see ``_lock_retiring_element_state`` for the measured crash."""
        _lock_retiring_element_state(element)
        for attempt in (1, 2):
            try:
                state_result = element.set_state(Gst.State.NULL)
            except Exception as exc:
                failures.append(f"element-null-error:{index}:{exc!r}")
                return False
            if state_result == Gst.StateChangeReturn.SUCCESS:
                return True
            if state_result == Gst.StateChangeReturn.ASYNC:
                wait_s = max(0.0, min(_LEG_NULL_ASYNC_WAIT_S, deadline - time.monotonic()))
                try:
                    ret, state, _pending = element.get_state(int(wait_s * Gst.SECOND))
                except Exception as exc:
                    failures.append(f"element-null-getstate-error:{index}:{exc!r}")
                    return False
                if (
                    ret
                    in (
                        Gst.StateChangeReturn.SUCCESS,
                        Gst.StateChangeReturn.NO_PREROLL,
                    )
                    and state == Gst.State.NULL
                ):
                    return True
                detail = f"async-unsettled:{getattr(ret, 'value_nick', ret)}"
            else:
                detail = getattr(state_result, "value_nick", str(state_result))
            if attempt == 1 and time.monotonic() < deadline:
                print(
                    f"WARN: retiring element {index} did not reach NULL ({detail}); retrying once",
                    flush=True,
                )
                continue
            break
        return False

    def _sweep_unsettled_elements(
        self, unsettled: list[tuple[int, Gst.Element]], failures: list[str]
    ) -> list[tuple[int, Gst.Element]]:
        """Round-3 finding 5: last bounded chance, then call it an orphan.

        Every element handed here has already failed the leg-wide NULL budget. One
        more ``set_state(NULL)`` plus a bounded ``get_state`` -- all of them
        sharing ``_LEG_ORPHAN_RETRY_BUDGET_S``, not one budget each -- separates
        "slow" from "stuck". Whatever is still above NULL afterwards is returned as
        an orphan so the caller can record it, report it by name, and keep it out
        of ``pipeline.remove``."""
        if not unsettled:
            return []
        deadline = time.monotonic() + _LEG_ORPHAN_RETRY_BUDGET_S
        orphans: list[tuple[int, Gst.Element]] = []
        for index, element in unsettled:
            wait_s = max(0.0, deadline - time.monotonic())
            _lock_retiring_element_state(element)
            try:
                state_result = element.set_state(Gst.State.NULL)
                if state_result == Gst.StateChangeReturn.SUCCESS:
                    continue
                if state_result != Gst.StateChangeReturn.ASYNC:
                    # A FAILURE (or NO_PREROLL, which is meaningless downward) is a
                    # refusal, not a slow transition. Waiting on ``get_state`` after
                    # one would read a cached state that says nothing about the
                    # refusal -- exactly the misread that let a refusing element be
                    # reported as cleanly retired.
                    failures.append(
                        f"element-null-incomplete:{index}:"
                        f"{getattr(state_result, 'value_nick', str(state_result))}"
                    )
                    orphans.append((index, element))
                    continue
                ret, state, _pending = element.get_state(int(wait_s * Gst.SECOND))
            except Exception as exc:
                failures.append(f"element-null-error:{index}:{exc!r}")
                orphans.append((index, element))
                continue
            if (
                ret in (Gst.StateChangeReturn.SUCCESS, Gst.StateChangeReturn.NO_PREROLL)
                and state == Gst.State.NULL
            ):
                continue
            failures.append(
                f"element-null-incomplete:{index}:async-unsettled:{getattr(ret, 'value_nick', ret)}"
            )
            orphans.append((index, element))
        return orphans

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
                # Same cascade hazard as a retiring program leg: a program-leg
                # preroll completing on another thread must not re-PLAY a layer
                # element between its NULL here and its removal below.
                _lock_retiring_element_state(element)
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
        """Time-bounded teardown, including any reload-retirement thread.

        Returns True iff that thread ended and the pipeline reached NULL within one
        shared ``teardown_timeout_s`` budget. Both ``set_state(NULL)`` and its
        confirming ``get_state`` run on a daemon teardown thread: native evidence
        proves the state-change call itself can block in a streaming task, so merely
        putting a timeout on the later ``get_state`` cannot bound this method.
        With ``force_exit_on_hang``
        (worker-process model), an incomplete transition triggers ``os._exit(70)``
        (nonzero = forced kill, so the supervisor doesn't read it as a clean exit)
        so the process can never hang on stuck live-source streaming threads.

        Item 88 Round-2 review BLOCKER: ``RollingWavSegmentWriter.close()`` is
        itself bounded now (a wedged disk cannot make IT hang forever either --
        see ``audio_tap.py``'s own docstring), so calling it here, BEFORE the
        ``force_exit_on_hang`` escape below, can no longer defeat this method's
        own bounded-teardown contract the way an earlier, unconditionally-
        blocking ``close()`` could have."""
        self._stopping = True
        deadline = time.monotonic() + self.teardown_timeout_s

        # Stop admissions before removing the downstream probe: a late probe
        # cannot reopen the terminal gate. The callback itself holds only gate,
        # not engine state or a lock across any GStreamer call.
        gate = getattr(self, "_caption_gap_gate", None)
        if gate is not None:
            gate.close()
        heartbeat_id = getattr(self, "_caption_gap_heartbeat_id", None)
        if heartbeat_id is not None:
            with contextlib.suppress(Exception):
                GLib.source_remove(heartbeat_id)
            self._caption_gap_heartbeat_id = None
        probe = getattr(self, "_caption_gap_probe", None)
        if probe is not None:
            with contextlib.suppress(Exception):
                probe[0].remove_probe(probe[1])
            self._caption_gap_probe = None

        pending = self._pending_reload
        if pending is not None and not pending.get("commit_in_progress", False):
            # Do not synchronously dispose a still-prerolling leg here. Release its
            # probes and let the whole-pipeline NULL below own teardown under the
            # same bound.
            self._pending_reload = None
            if pending["probe_id"] is not None:
                with contextlib.suppress(Exception):
                    pending["new_video_pad"].remove_probe(pending["probe_id"])
            for pad, probe_id in pending["boundary_probes"]:
                with contextlib.suppress(Exception):
                    pad.remove_probe(probe_id)
            self._release_hold_probes(pending)
            for timeout_key in ("timeout_id", "defer_timeout_id"):
                if pending[timeout_key] is not None:
                    with contextlib.suppress(Exception):
                        GLib.source_remove(pending[timeout_key])
            self._notify_reload_settled(pending["on_settled"], False, "stopped")
        elif pending is not None:
            # Round-3 finding 1 makes this window vanishingly small -- a commit's
            # on-air half is a handful of synchronous main-loop statements, and
            # ``stop()`` runs on that same loop -- but keep it correct: the caller
            # gets a terminal result, the transaction is dropped, and the
            # process-wide commit watchdog is disarmed so a bounded stop that has
            # already reported failure cannot be followed by a force-exit.
            callback = pending["on_settled"]
            pending["on_settled"] = None
            self._pending_reload = None
            self._finish_commit_watchdog(pending)
            self._notify_reload_settled(callback, False, "stopped")

        # Round-3 finding 1: a committed reload no longer has a main-loop
        # finalizer waiting on its retirement thread -- the commit publishes
        # itself synchronously and the thread only tears the old leg down. What
        # DOES have to happen here is ordering: an old-leg retirement that is
        # still running must finish (or be given a fair, bounded chance to)
        # BEFORE the whole-pipeline NULL transition starts, or the two race each
        # other for the same elements' locks and neither lands inside its bound.
        # Measured under load: without this join a three-worker rollover that had
        # committed all six reloads still exited 70 at stop.
        join_deadline = time.monotonic() + min(
            _RETIREMENT_STOP_JOIN_S, max(0.0, self.teardown_timeout_s)
        )
        for retirement_thread in self._commit_retire_threads:
            if retirement_thread.is_alive():
                retirement_thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self._commit_retire_threads):
            print(
                "WARN: an old reload leg was still retiring at stop; the "
                "whole-pipeline teardown below takes it from here",
                file=sys.stderr,
                flush=True,
            )
        # Round-3 review finding 1: orphans -- elements a retirement (or an
        # abandoned retirement, or a build-failure cleanup) could not confirm at
        # NULL -- were left state-LOCKED inside the pipeline, and a locked child is
        # skipped by the bin's own state change (gstbin.c
        # ``gst_bin_element_set_state``: "element is locked, return previous
        # return"), so the whole-pipeline NULL below would report SUCCESS with a
        # still-running element inside it, ``stop()`` would return True, and the
        # process would then dispose that element above NULL. Unlock every orphan
        # HERE, before the transition, so the pipeline's descent takes them with
        # it; after the transition each is NULLed directly, best-effort and
        # inside the same bounded thread, and any still not confirmed at NULL is
        # folded into ``clean`` below. Snapshot: the list can still be appended to
        # by an in-flight retirement thread.
        orphans = list(self._orphaned_leg_elements)
        for element in orphans:
            with contextlib.suppress(Exception):
                element.set_locked_state(False)

        # The pipeline transition gets its OWN full budget, measured from here --
        # the join above is not taken out of it, for the same reason the audio tap
        # writer stopped being handed the leftover of somebody else's deadline.
        deadline = time.monotonic() + self.teardown_timeout_s

        transition: dict[str, object] = {"result": None, "error": None, "orphans_settled": False}

        def _settle_orphans() -> None:
            """Best-effort direct NULL for each orphan, after the pipeline's own
            descent; bounded because it runs inside the joined thread below."""
            unsettled: list[str] = []
            for element in orphans:
                try:
                    state_result = element.set_state(Gst.State.NULL)
                    if state_result != Gst.StateChangeReturn.SUCCESS:
                        remaining = max(0.0, deadline - time.monotonic())
                        _ret, state, _pending = element.get_state(int(remaining * Gst.SECOND))
                        if state != Gst.State.NULL:
                            unsettled.append(_element_label(element))
                except Exception as exc:
                    unsettled.append(f"{_element_label(element)}:{exc!r}")
            transition["orphans_unsettled"] = unsettled
            transition["orphans_settled"] = not unsettled

        def _set_pipeline_null() -> None:
            try:
                state_result = self.pipeline.set_state(Gst.State.NULL)
                if state_result == Gst.StateChangeReturn.FAILURE:
                    transition["result"] = state_result
                    return
                remaining = max(0.0, deadline - time.monotonic())
                result, _current, _pending = self.pipeline.get_state(int(remaining * Gst.SECOND))
                transition["result"] = result
            except Exception as exc:
                transition["error"] = repr(exc)
            finally:
                if orphans:
                    _settle_orphans()
                else:
                    transition["orphans_settled"] = True

        transition_thread: threading.Thread | None = None
        try:
            transition_thread = threading.Thread(
                target=_set_pipeline_null,
                name="civiccast-pipeline-null",
                daemon=True,
            )
            transition_thread.start()
            transition_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        except Exception as exc:
            transition["error"] = repr(exc)
        transition_clean = bool(
            transition_thread is not None
            and not transition_thread.is_alive()
            and transition["result"] == Gst.StateChangeReturn.SUCCESS
        )
        if not transition_clean:
            detail = transition["error"] or "transition exceeded teardown budget"
            print(
                f"WARN: pipeline did not reach NULL within teardown bound: {detail}",
                file=sys.stderr,
                flush=True,
            )
        for retirement_thread in self._commit_retire_threads:
            if retirement_thread.is_alive():
                retirement_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        # Round-2 finding 1: aborted legs now retire on their own worker threads
        # (``_start_aborted_leg_retirement``). Give them the same bounded chance to
        # finish before the process goes away, so an abort taken moments before
        # stop still releases its selector pads instead of being reported as an
        # unclean teardown. Bounded by the same deadline as everything else here.
        for abort_thread in self._abort_retire_threads:
            if abort_thread.is_alive():
                abort_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        aborts_clean = not any(thread.is_alive() for thread in self._abort_retire_threads)
        if not aborts_clean:
            print(
                "WARN: an aborted reload leg was still retiring at stop",
                file=sys.stderr,
                flush=True,
            )
        retirement_clean = not any(thread.is_alive() for thread in self._commit_retire_threads)
        # Round-3 review finding 1: orphans outstanding are part of the verdict.
        # A stop that leaves an element above NULL is not a clean teardown, and
        # ``WORKER_RESULT``'s ``teardown_clean`` (built from this return) must say
        # so, whatever the pipeline's own transition reported.
        orphans_clean = bool(transition.get("orphans_settled", False))
        if orphans:
            unsettled = transition.get("orphans_unsettled")
            print(
                f"WARN: {len(orphans)} orphaned reload-leg element(s) were unlocked for the "
                "teardown; "
                + (
                    "all confirmed at NULL"
                    if orphans_clean
                    else "still above NULL: "
                    + (", ".join(unsettled) if isinstance(unsettled, list) else "unconfirmed")
                ),
                file=sys.stderr,
                flush=True,
            )
        clean = bool(transition_clean and retirement_clean and aborts_clean and orphans_clean)
        if self.audio_tap_writer is not None:
            # Round-2 finding 4: this used to be handed the LEFTOVER of the shared
            # teardown deadline. By this point the pipeline-NULL transition and the
            # retirement join above have usually consumed all of it, so the tap
            # writer was routinely closed with timeout=0.0 -- reported "abandoned",
            # and the final caption WAV chunk (the one covering the last seconds of
            # the meeting, which is exactly the material an operator is most likely
            # to need) was lost on an otherwise clean stop. Flushing a WAV chunk is
            # a short, local, disk-bound operation that has nothing to do with how
            # long the GStreamer teardown took, so give it its own small bounded
            # budget instead of the remainder of somebody else's.
            tap_deadline = min(_AUDIO_TAP_CLOSE_TIMEOUT_S, self.teardown_timeout_s)
            tap_status = self.audio_tap_writer.close(timeout=max(0.0, tap_deadline))
            if tap_status == "abandoned":
                print(
                    "WARN: caption audio tap writer did not drain before teardown "
                    f"({self.teardown_timeout_s}s bound); abandoning it in the "
                    "background -- a trailing caption segment may be lost",
                    file=sys.stderr,
                    flush=True,
                )
            self.audio_tap_writer = None
        if not clean and force_exit_on_hang:
            os._exit(70)  # nonzero: a forced kill, not a clean exit (audit MINOR)
        return clean
