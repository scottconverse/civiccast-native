# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Live-HLS relay for the GStreamer engine: real segments + a real manifest.

DEFECT A (found live, staff-token repro): the GStreamer sink bridge
(``civiccast.egress.gst.bridge``) accepted the ``hls`` sink kind and crashed
the channel on ``start`` -- ``EgressSinkKind`` advertised it, the config API
accepted it with 200 OK, and ``sink_element_spec`` had no branch for it. This
module is the other half of the real fix: it makes an ``hls`` sink on the
GStreamer engine genuinely produce a servable manifest + segments.

**Why not a native GStreamer HLS element.** The task that opened this defect
assumed the shipped runtime carries ``hlssink2``. It does not — verified
empirically against the real installed closure
(``C:\\Program Files\\CivicCast (Native)\\runtime\\dependencies\\gstreamer\\lib\\gstreamer-1.0``):
``gst-inspect-1.0`` lists no ``hlssink``/``hlssink2``/``hlssink3`` element at
all (no ``gsthls*.dll`` is shipped) and no ``splitmuxsink``/``multifilesink``
(no ``gstmultifile.dll``). The only HLS-shaped element present is
``avmux_hls`` (gst-libav wrapping FFmpeg's HLS muxer, rank ``marginal``), and
a live pipeline test (``avmux_hls ! filesink``, both audio+video fed, run to
EOS) wrote **zero files** — gst-libav's generic muxer wrapper funnels all
output through one src pad and cannot drive FFmpeg's own multi-file segment
I/O, a known limitation of that wrapper. So no *pure* GStreamer element
chain can produce real HLS output with this runtime's plugin set; a branch
that just returns an ``ElementSpec`` naming one of those elements would look
fixed and still not serve residents anything.

**What actually works.** ``civiccast.egress.sinks.HlsSink`` already writes
correct, sliding-window live HLS (``playlist.m3u8`` + ``seg%09d.ts``, 2s
segments, a 12s/6-segment window) via FFmpeg's real ``-f hls`` muxer for the
legacy ffmpeg-concat engine, and ``civiccast.stream.media_router``'s
``/media/live/{channel_id}/...`` route already serves exactly that directory
layout (resolved from the channel's ``hls`` sink URI). That combination is
proven; this module makes the GStreamer engine land bytes there too, instead
of reinventing the muxer:

    GStreamer program mux (already-proven MPEG-TS branch)
        --> udp://127.0.0.1:<relay-port>            (an ordinary local-ts sink)
    HlsRelaySupervisor's supervised ffmpeg child
        -i udp://127.0.0.1:<relay-port> ! HlsSink.output_args()
        --> <hls sink's configured directory>/playlist.m3u8 + seg%09d.ts

``civiccast.stream.media_router`` needs no changes: it already reads the
channel's *configured* ``hls`` sink URI (the directory), not the internal
relay plumbing, so the rewritten in-memory ``local-ts`` sink this module
hands the graph builder is invisible to every reader except the graph.

Mirrors ``civiccast.egress.ts_relay.TsRelaySupervisor`` in shape (guarded
per-channel supervised co-process dict, idempotent ``apply``/``stop_channel``/
``stop_all``) so the two relays read the same at a glance.

**Beta.10 live finding (2026-09-23): process-alive != emitting.** A relay
ffmpeg child can stay a live pid while its ``playlist.m3u8`` stops advancing
(the live government channel froze at ``seg000001130.ts`` for minutes while
both the relay pid and the main encoder's ``CTRL output`` counters kept
running). ``is_alive`` alone cannot see that, so the daemon kept reporting the
``hls`` sink ``connected`` off the MAIN encoder's UDP progress. The progress
half below adds an mtime+segment-identity check and a bounded, opt-in
self-heal. It deliberately does NOT diagnose the upstream UDP starvation that
stops ffmpeg writing; it only makes a stalled-but-alive relay truthful and
recoverable.

**Beta.10 live finding (2026-09-24, U12): a (re)start can lock the sink to
audio-only.** The government relay was restarted mid-stream by the bounded
stall self-heal above (18:46:32, right after the channel cut to its fallback
slate for a schedule gap). From then on its newest segments probed as AUDIO
ONLY while the public/education relays stayed H264+AAC -- for hours, until the
channel itself was restarted; the same shape hit education at 13:39:35 and
government at 15:49:21 that day. Mechanism (reproduced with real ffmpeg
against a live UDP input): ffmpeg fixes its OUTPUT stream set at probe time,
so a child that starts while its input carries no video inside the probe
window builds an audio-only output and never adds video when video arrives.
The widened 6M probe only narrows the window in which that can happen; it
cannot remove it, and it does not notice that the result is unwatchable.

**The same lock runs the other way (coordinator audit, U12 fix).** An output
whose stream set is fixed at probe time can just as easily be fixed to
video-only: U13 measured the government relay's post-self-heal segments at
18:47:44-18:47:56 carrying TS PID 256 (video) and no PID 257 (audio) at all.
A municipal channel with picture and no sound fails acceptance exactly like
one with sound and no picture, so the rule below is symmetric over the stream
kinds the sink is configured to carry:

1. the relay's output mapping REQUIRES every kind the sink carries
   (:func:`_relay_map_args`), so a child that probes an input missing any of
   them fails fast instead of silently serving a half-program window -- and the
   supervisor's bounded restart then retries until the program is whole;
2. the post-(re)start verification (:meth:`HlsRelaySupervisor.
   maybe_restore_missing_streams`) requires BOTH a video and an audio stream in
   the newest served segment for a sink that carries both, and judges each kind
   it actually requires.

A sink that carries only one kind is judged only on that kind, and an
audio-only sink (``EgressSink.carries_video`` False) keeps its historical argv
and is never judged at all. Today every shipped sink carries both; the
``carries_video``/``carries_audio`` flags exist so a future one can say
otherwise (see ``civiccast/egress/sinks.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.sinks import HlsSink
from civiccast.stream._ffmpeg import FfmpegNotFoundError, FfmpegProcessHandle, start_ffmpeg

_LOG = logging.getLogger(__name__)

_PORT_BASE_ENV = "CIVICCAST_HLS_RELAY_BASE_PORT"
#: ffprobe binary name, resolved from PATH at probe time. Declared locally
#: rather than importing ``civiccast.stream._ffmpeg``'s private
#: ``_FFPROBE_EXECUTABLE``: this module already owns its own ffmpeg argv.
_FFPROBE_EXECUTABLE = "ffprobe"
_DEFAULT_PORT_BASE = 18_000
_PORT_RANGE = 500
_UDP_INPUT_ARGS = (
    "-fflags",
    "+genpts",
    # Widened start-time probe window (beta.10 HLS video-loss): with 2,000,000
    # a relay that starts while its loopback UDP TS is audio-only can lock to an
    # audio-only stream inventory and keep emitting AAC-only HLS even after
    # H.264 video arrives (isolated synthetic A/B: 2M -> AAC-only; 6M -> H264/AAC).
    # 6,000,000 is the smallest tested value that restores video; larger values
    # also work but increase time-to-first-segment. NOTE: this is proven only in
    # isolation on a synthetic delayed-video TS; it is NOT proof that live worker
    # loopback input was audio-only at relay start, nor that it fixes the live
    # symptom.
    "-analyzeduration",
    "6000000",
    "-probesize",
    "6000000",
)
#: How long a live relay may go with an UNCHANGED last segment + playlist
#: before the window is reported (and optionally healed) as stalled. The live
#: symptom was minutes, so 30s is far above a healthy 2s segment cadence and
#: every real muxer hiccup, while still bounding a visible freeze.
_DEFAULT_STALL_BOUND_S = 30.0


#: Output-stream mapping for a relay child (U12).
#:
#: ``-map 0:v:0`` (and ``-map 0:a:0`` for a sink that carries audio) is
#: deliberately NOT optional: ffmpeg fixes its output stream set at probe
#: time, so a child that starts while the loopback input is missing a kind
#: builds a half-program HLS output and never adds the missing kind when it
#: arrives (the live government symptom in both directions -- audio-only at
#: 18:46:32, video-only at 18:47:44-18:47:56). Requiring the map turns that
#: silent half-window into a prompt child failure -- measured against real
#: ffmpeg 8.1.1: ``Stream map '0:v:0' matches no streams`` + "Error opening
#: output files", exit -22, no window written -- which the supervisor's
#: bounded restore below then retries until the program is whole.
#:
#: With ANY ``-map`` present ffmpeg's default stream selection is disabled, so
#: every kind the sink carries must be named explicitly. A kind the sink does
#: not carry is left optional (``?``) so a one-kind input stays relay-able
#: instead of fatal, and an audio-only sink keeps the historical mapping-less
#: argv byte-for-byte. Proven with real ffmpeg in
#: ``tests/egress/test_hls_relay_video_lock.py``.
def _relay_map_args(*, carries_video: bool, carries_audio: bool) -> tuple[str, ...]:
    """The ``-map`` arguments that force this sink's required stream kinds."""
    if not carries_video:
        # Audio-only sink: the historical argv, no -map at all (and ffmpeg's
        # default selection still picks the audio stream).
        return ()
    if not carries_audio:
        # Video-only sink: audio stays optional so an audio-less input is
        # relay-able rather than fatal.
        return ("-map", "0:v:0", "-map", "0:a:0?")
    return ("-map", "0:v:0", "-map", "0:a:0")


#: U12 restart cadence for a relay that cannot carry the program's required
#: stream kinds. The first ``_STREAM_FAST_ATTEMPTS`` restarts are prompt (the
#: missing kind is usually a slate/source transition away), then the cadence
#: drops to ``_DEFAULT_STREAM_RETRY_SLOW_DELAY_S`` and each further attempt
#: logs at ERROR -- a sink that can never satisfy the requirement must not
#: restart-storm, but must keep trying and keep saying so.
_DEFAULT_STREAM_RETRY_DELAY_S = 5.0
_DEFAULT_STREAM_RETRY_SLOW_DELAY_S = 60.0
_STREAM_FAST_ATTEMPTS = 3
#: Bound on one segment's ffprobe (U12 verification). A served 2s segment is
#: read locally, so this only ever bounds a hung probe.
_SEGMENT_PROBE_TIMEOUT_S = 10.0


def hls_relay_uri_for(sink_uri: str, *, base_port: int | None = None) -> str:
    """Deterministic loopback URI for one hls sink's GStreamer->ffmpeg relay tap.

    Pure function of ``sink_uri`` (the sink's configured directory) so
    ``sink_element_spec`` (a pure, side-effect-free element-graph builder) and
    :class:`HlsRelaySupervisor` (which owns the actual relay subprocess) agree
    on the same port without sharing mutable state. Collisions are possible in
    principle (two channels' directories hashing to the same offset) but the
    500-port range makes that vanishingly unlikely for a station's channel
    count, and a collision would surface immediately as a health/proof
    mismatch rather than silently — same acceptable-risk posture as this
    codebase's other hash-derived allocations.
    """
    if base_port is not None:
        base = base_port
    else:
        base = int(os.environ.get(_PORT_BASE_ENV, "").strip() or _DEFAULT_PORT_BASE)
    digest = hashlib.sha256(sink_uri.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:2], "big") % _PORT_RANGE
    return f"udp://127.0.0.1:{base + offset}"


def _playlist_path_for(sink_uri: str) -> Path:
    """The manifest path this sink's relay writes (mirrors ``HlsSink``)."""
    sink = HlsSink(EgressSinkSpec(kind="hls", label="_progress", uri=sink_uri))
    return Path(sink.connect_target())


def _last_segment(path: Path) -> str | None:
    """The final ``.ts`` name in a playlist, or None if there is no window yet.

    This is the ONLY signal used for progress. Manifest SIZE is deliberately
    excluded: ``#EXT-X-MEDIA-SEQUENCE`` / ``PROGRAM-DATE-TIME`` / tag edits can
    change the byte count while the last segment stays identical, and treating
    that as progress would falsely reset the freshness clock on a frozen
    window (audit finding 1). ``mtime`` is excluded for the same reason.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    last_segment = ""
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.endswith(".ts"):
            last_segment = stripped
            break
    return last_segment or None


def _last_complete_segment(path: Path) -> str | None:
    """The newest segment of a playlist that has stopped growing, or None.

    ``_last_segment`` answers "which entry is the window's newest", which is what
    progress tracking wants. THIS answers "which entry is CLOSED", which is what
    MEASURING wants: on a live window the muxer publishes the final entry's name
    the moment it opens that file, so the final ``.ts`` is still being appended
    to and only its first packets are settled. The entry before it is therefore
    the newest COMPLETE one. Under ``#EXT-X-ENDLIST`` the window is closed and
    its final entry is itself complete -- which is also what a closed-window
    writer means by publishing the tag -- so that entry is used directly.

    Correct under either playlist-write behaviour: a writer that publishes an
    entry only once it is closed makes the second-to-last merely one segment
    older -- still a complete, measurable segment, just not the newest.

    Same "no answer" contract as its siblings below: an unreadable playlist, a
    window with no ``.ts`` entry yet, and a live window holding only ONE entry
    (that entry is the one being written) are all ``None`` -- ignorance, never a
    fault.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    closed = False
    segments: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#EXT-X-ENDLIST"):
            closed = True
        elif stripped.endswith(".ts"):
            segments.append(stripped)
    if not segments:
        return None
    if closed:
        return segments[-1]
    if len(segments) < 2:
        return None
    return segments[-2]


def _segment_stream_kinds(path: Path) -> frozenset[str] | None:
    """Which stream kinds (``video``/``audio``) does THIS served segment carry?

    Tri-state by presence (U12): a set is the answer ffprobe actually gave --
    possibly the empty set, which is itself a positive finding -- and ``None``
    means "no answer": the segment is not on disk yet (a window can name a
    segment ffmpeg is still closing), ffprobe is absent, or it failed/timed
    out. ``None`` never counts as a fault: the supervisor only restarts a
    relay on POSITIVE evidence that its output is missing a kind, so a broken
    or missing probe tool cannot itself become a restart source.

    A set rather than a bool because the requirement is symmetric over the
    kinds the sink carries: U13 measured a live relay serving video-only
    segments (TS PID 256, no PID 257), the mirror image of the audio-only
    lock, and a bool would have to be asked twice and conjoined.

    Set rather than the module-local reuse of
    ``civiccast.stream._ffmpeg.probe_video_dimensions`` (which answers ``None``
    for both "no video" and "could not tell") because the two must not be
    conflated here: one is the live fault, the other is ignorance.
    """
    if not path.is_file():
        return None
    if shutil.which(_FFPROBE_EXECUTABLE) is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [
                _FFPROBE_EXECUTABLE,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SEGMENT_PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    return frozenset(line.strip() for line in completed.stdout.splitlines() if line.strip())


def _seconds_from_pts_time(value: object) -> float | None:
    """One packet's ``pts_time`` as float seconds, or None if ffprobe gave none.

    ffprobe's JSON prints ``pts_time`` as a STRING (``"0.033367"``) and as
    ``"N/A"`` for a packet whose timestamp it could not express; neither the
    string form nor the unparsable one is a fault here.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _segment_first_packet_pts(path: Path) -> tuple[float, float] | None:
    """``(video_pts, audio_pts)`` of THIS segment's first packets, or None.

    BETA.10 U16 item B: the output-side A/V check measures the RELATIONSHIP
    between the two streams, so a one-kind segment is not a measurement at all
    -- a single kind has nothing to be out of step WITH. Every other outcome is
    also ``None``: the segment is not on disk, ffprobe is absent, the probe
    failed or timed out, its JSON did not parse, or a stream's first packet
    carried no usable timestamp. Same tri-state contract as
    ``_segment_stream_kinds``: ``None`` is ignorance, never a fault, and never
    on its own a reason to restart anything. The caller is responsible for the
    policy (how big a difference is a desync, how many probes in a row matter).

    Per kind this is the first packet, in file order, whose timestamp ffprobe
    could express: a first packet it could not timestamp is skipped rather than
    discarding the whole measurement, which cannot mask a desync of seconds
    (segments here are ~2s long and a late stream's first packet is the one the
    desync is measured from).

    ONE ffprobe call answers both kinds, because two calls could straddle a
    window roll and report two different segments' first packets as if they
    belonged together. That is why this asks for JSON rather than the flat
    ``csv`` of ``_segment_stream_kinds``: the answer pairs a stream identity
    with a timestamp, which a column-order-dependent csv would have to be read
    back positionally.
    """
    if not path.is_file():
        return None
    if shutil.which(_FFPROBE_EXECUTABLE) is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [
                _FFPROBE_EXECUTABLE,
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type:packet=stream_index,pts_time",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SEGMENT_PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None

    kinds: dict[int, str] = {}
    streams = payload.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            index = stream.get("index")
            kind = stream.get("codec_type")
            if isinstance(index, int) and isinstance(kind, str):
                kinds[index] = kind

    first: dict[str, float] = {}
    packets = payload.get("packets")
    if isinstance(packets, list):
        for packet in packets:
            if not isinstance(packet, dict):
                continue
            index = packet.get("stream_index")
            if not isinstance(index, int):
                continue
            kind = kinds.get(index)
            if kind not in {"video", "audio"} or kind in first:
                continue
            seconds = _seconds_from_pts_time(packet.get("pts_time"))
            if seconds is None:
                continue
            first[kind] = seconds

    if "video" not in first or "audio" not in first:
        return None
    return (first["video"], first["audio"])


def _sink_required_kinds(source_uri: str) -> frozenset[str]:
    """The stream kinds this ``hls`` sink's program must carry (U12).

    Empty means "never judged": an audio-only sink (``carries_video`` False)
    keeps its historical argv and the supervisor must not restart it for a
    stream it was never configured to carry. Otherwise the requirement is
    every kind the sink is declared to carry -- both video AND audio for every
    sink shipped today (see ``EgressSink`` in ``civiccast/egress/sinks.py``).
    """
    sink = HlsSink(EgressSinkSpec(kind="hls", label="_kinds", uri=source_uri))
    if not sink.carries_video:
        return frozenset()
    required = {"video"}
    if sink.carries_audio:
        required.add("audio")
    return frozenset(required)


def _describe_kinds(kinds: frozenset[str]) -> str:
    """Stable operator-facing wording for a kind set (``video+audio``, ``audio``)."""
    return "+".join(sorted(kinds))


class _Ffmpeg(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self, *, grace_seconds: float = 5.0) -> int | None: ...


@dataclass
class _Relay:
    source_uri: str  # the hls sink's original directory URI (identity + restart-on-change key)
    relay_uri: str  # the local udp:// the GStreamer branch actually writes to
    process: _Ffmpeg
    #: Last-observed last-segment NAME for THIS relay child, plus the monotonic
    #: time it was observed. Only the segment name counts as progress (audit
    #: finding 1); size/tag edits do not. Reset whenever the child is
    #: (re)started so a new child is never judged against its predecessor.
    progress_segment: str | None = None
    progress_at: float | None = None
    #: One-shot latch for the current stall episode. Set when a self-heal
    #: restart is attempted so a second poll in the same episode cannot spawn
    #: another child (no restart storm). It is cleared ONLY when the served
    #: window genuinely advances BEYOND the pre-heal baseline (audit finding 4):
    #: a frozen playlist left on disk must not read as progress just because the
    #: replacement child started, or the heal would re-arm every bound and
    #: become a restart storm.
    heal_attempted: bool = False
    #: The last-segment name observed at the moment a heal was attempted. The
    #: latch above clears only once progress moves past THIS value.
    heal_baseline_segment: str | None = None
    #: Monotonic time this child was spawned. The startup grace is measured
    #: from here -- NOT from ``progress_at`` -- so a relay that was healthy for
    #: a long time and then stalled is still healable (its grace is long past),
    #: while a just-(re)started child is never killed before it can write.
    started_at: float | None = None
    #: Monotonic time this child last had a readable playlist. Used by the
    #: never-emitted path (audit finding 3): a producing channel whose relay has
    #: never written a window past its startup grace must be reported unhealthy.
    first_seen_at: float | None = None
    #: U12 stream-carry watch. ``streams_verified`` latches once THIS child's
    #: newest served segment is measured to carry every kind its sink requires
    #: -- the check then stops (one ffprobe per child, not one per tick).
    #: ``streams_probed_segment`` remembers which segment name that probe
    #: looked at, so a static window is not re-probed every tick.
    #: ``stream_fault_attempts`` counts this (channel, sink)'s failed restarts
    #: across children; ``stream_retry_not_before`` is the monotonic time the
    #: next attempt may run (the backoff).
    streams_verified: bool = False
    streams_probed_segment: str | None = None
    stream_fault_attempts: int = 0
    stream_retry_not_before: float | None = None


class HlsRelaySupervisor:
    """Owns one channel-lifetime ffmpeg HLS-mux relay per (channel, hls sink).

    ``apply(config)`` is called from the daemon's ``_start``/``_try_content_reload``
    the same way ``TsRelaySupervisor.apply`` is (see ``civiccast.egress.daemon``):
    it ensures each configured ``hls`` sink has a live relay child, then returns
    a config where that sink is rewritten to an ordinary ``local-ts`` UDP sink
    aimed at the relay's loopback port — so the GStreamer graph builder
    (``civiccast.egress.gst.bridge.sink_element_spec``) never needs special
    hls wiring on the hot path; it just builds the udpsink it already knows
    how to build. The rewrite is in-memory only (never persisted back to the
    store), exactly like the TS relay's URI rewrite.
    """

    def __init__(
        self,
        *,
        starter: Callable[..., _Ffmpeg] | None = None,
        base_port: int | None = None,
        stall_bound_s: float | None = None,
        segment_probe: Callable[[Path], frozenset[str] | None] | None = None,
        stream_retry_delay_s: float | None = None,
        stream_retry_slow_delay_s: float | None = None,
    ) -> None:
        self._starter = starter or _default_starter
        self._base_port = base_port
        self._guard = Lock()
        self._relays: dict[str, _Relay] = {}
        self._unavailable_logged = False
        self._stall_bound_s = stall_bound_s if stall_bound_s is not None else _DEFAULT_STALL_BOUND_S
        # U12 seams, injected the same way ``starter`` is: the probe is a real
        # ffprobe by default, and the two delays default to the shipped cadence.
        self._segment_probe = segment_probe or _segment_stream_kinds
        self._stream_retry_delay_s = (
            stream_retry_delay_s
            if stream_retry_delay_s is not None
            else _DEFAULT_STREAM_RETRY_DELAY_S
        )
        self._stream_retry_slow_delay_s = (
            stream_retry_slow_delay_s
            if stream_retry_slow_delay_s is not None
            else _DEFAULT_STREAM_RETRY_SLOW_DELAY_S
        )
        # Monotonic clock, injectable for tests. Must be the SAME clock domain
        # the caller passes as ``now`` to note_progress/progress_stale/self-heal;
        # the daemon uses its own ``_monotonic`` for exactly that reason.
        self._clock: Callable[[], float] = time.monotonic

    def apply(self, config: EgressConfig, *, new_session: bool = False) -> EgressConfig:
        """Return a config whose ``hls`` sinks point at their channel-lifetime relay.

        Idempotent per (channel_id, sink.label): the relay is reused across
        repeated ``apply`` calls for the SAME worker session. A sink whose relay
        could not be started (ffmpeg missing) is returned UNCHANGED — still
        declared ``hls``, so ``sink_element_spec``'s own hls branch builds a
        udpsink to the same deterministic port; nothing is listening there, but
        the channel still starts (degraded: no live HLS, everything else on the
        channel keeps working) rather than crashing.

        BETA.10 U21: ``new_session=True`` means the caller is starting a GENUINE
        new worker session (first start, crash relaunch, output-desync guard
        restart, slate->program restart) and the channel's existing relay
        child(ren) are torn down before the sinks are walked, so the child that
        ends up serving the new session was spawned FOR it. Relay reuse is only
        safe while the writer it serves is the same writer: the relay's own
        timeline outlives its writer, so a child that was corrected for a
        previous session's PTS jump keeps serving that offset for as long as the
        child lives — which is exactly how a desync becomes permanent
        (education channel, 2026-09-25 00:51:26). The replacement is spawned on
        the SAME deterministic port (see :func:`hls_relay_uri_for`), so the
        config already handed to the engine graph stays valid across the rebind.

        ``new_session=False`` is the in-place reload path
        (``EgressDaemon._request_reload``): the worker is not being restarted,
        so its relay must not be either.
        """
        if new_session:
            # A separate critical section on purpose: ``self._guard`` is a plain
            # (non-reentrant) Lock, so the teardown must complete before
            # ``_ensure_relay`` below takes the lock for its own spawn.
            self._drop_channel_relays(config.channel_id)
        if not any(sink.kind == "hls" for sink in config.sinks):
            return config
        new_sinks: list[EgressSinkSpec] = []
        changed = False
        for sink in config.sinks:
            if sink.kind != "hls":
                new_sinks.append(sink)
                continue
            relay_uri = self._ensure_relay(config.channel_id, sink)
            if relay_uri is None:
                new_sinks.append(sink)
                continue
            changed = True
            new_sinks.append(sink.model_copy(update={"kind": "local-ts", "uri": relay_uri}))
        if not changed:
            return config
        return config.model_copy(update={"sinks": new_sinks})

    def _ensure_relay(self, channel_id: str, sink: EgressSinkSpec) -> str | None:
        key = f"{channel_id}|{sink.label}"
        relay_uri = hls_relay_uri_for(sink.uri, base_port=self._base_port)
        with self._guard:
            relay = self._relays.get(key)
            if relay is not None and relay.source_uri == sink.uri and relay.process.poll() is None:
                return relay.relay_uri
            if relay is not None:
                relay.process.terminate()
                self._relays.pop(key, None)
            return self._start_relay_locked(key, channel_id, sink, relay_uri)

    def _start_relay_locked(
        self, key: str, channel_id: str, sink: EgressSinkSpec, relay_uri: str
    ) -> str | None:
        """Spawn one relay child and register it. Caller MUST hold ``self._guard``.

        Every spawn path funnels through here so the process count for one
        (channel, sink) key is structurally bounded at one: the caller has
        already terminated any predecessor before reaching this helper.
        """
        hls_sink = HlsSink(sink)
        args = [
            *_UDP_INPUT_ARGS,
            "-i",
            f"{relay_uri}?overrun_nonfatal=1&fifo_size=50000000",
            # U12: the relay REQUIRES every stream kind this sink carries, so a
            # child that probes a loopback input missing any of them fails fast
            # instead of emitting a half-program (audio-only OR video-only) HLS
            # window forever. A one-kind or audio-only sink keeps today's argv.
            *_relay_map_args(
                carries_video=hls_sink.carries_video,
                carries_audio=hls_sink.carries_audio,
            ),
            *hls_sink.output_args(),
        ]
        try:
            process = self._starter(args)
        except FfmpegNotFoundError:
            if not self._unavailable_logged:
                self._unavailable_logged = True
                _LOG.error(
                    "HLS relay could not start for %s (sink %r -> %s): ffmpeg is not "
                    "available. The channel still starts, but no live HLS window is "
                    "served for this sink until ffmpeg is installed/repaired.",
                    channel_id,
                    sink.label,
                    sink.uri,
                )
            return None
        except OSError:
            _LOG.exception(
                "HLS relay failed to start for %s (sink %r -> %s); no live HLS window "
                "is served for this sink until the next start/reload.",
                channel_id,
                sink.label,
                sink.uri,
            )
            return None
        now = self._clock()
        self._relays[key] = _Relay(
            source_uri=sink.uri,
            relay_uri=relay_uri,
            process=process,
            progress_segment=None,
            progress_at=None,
            heal_attempted=False,
            heal_baseline_segment=None,
            started_at=now,
            first_seen_at=now,
        )
        _LOG.info(
            "HLS relay up for %s (sink %r): %s -> %s.",
            channel_id,
            sink.label,
            relay_uri,
            sink.uri,
        )
        return relay_uri

    def _respawn_locked(self, key: str, channel_id: str, relay: _Relay) -> _Relay | None:
        """Terminate one relay child and spawn its single replacement.

        Caller MUST hold ``self._guard``. Every restart path (the stall heal
        and the U12 video restore) funnels through here so the one-child-per-
        (channel, sink) invariant is structurally preserved. Returns the new
        :class:`_Relay`, or ``None`` when the replacement could not be spawned
        (ffmpeg gone) -- in which case the key is left untracked and the sink
        falls to the existing dead-relay/health path.
        """
        sink = EgressSinkSpec(kind="hls", label=key.split("|", 1)[1], uri=relay.source_uri)
        relay.process.terminate()
        self._relays.pop(key, None)
        relay_uri = hls_relay_uri_for(relay.source_uri, base_port=self._base_port)
        if self._start_relay_locked(key, channel_id, sink, relay_uri) is None:
            return None
        return self._relays.get(key)

    def _stream_retry_blocked(self, relay: _Relay, *, now: float) -> bool:
        """Is this relay inside the backoff window of its last stream attempt?"""
        return relay.stream_retry_not_before is not None and now < relay.stream_retry_not_before

    def _attempt_stream_restart(
        self, key: str, channel_id: str, relay: _Relay, *, now: float, reason: str
    ) -> bool:
        """Restart a child that cannot carry a required stream kind, bounded.

        Caller MUST hold ``self._guard``. Returns True when a replacement was
        spawned. The attempt count and the next-allowed time are carried onto
        the replacement (the counters belong to the (channel, sink) fault
        episode, not to one child), so a sink whose input never carries a
        required kind converges on one attempt per
        ``stream_retry_slow_delay_s`` -- logged at ERROR -- rather than a
        restart storm. The child that cannot carry the program is never left to
        serve: this is the "restart it again promptly (bounded, logged) until
        the program is whole" half of U12.
        """
        attempts = relay.stream_fault_attempts + 1
        delay = (
            self._stream_retry_delay_s
            if attempts <= _STREAM_FAST_ATTEMPTS
            else self._stream_retry_slow_delay_s
        )
        log = _LOG.warning if attempts <= _STREAM_FAST_ATTEMPTS else _LOG.error
        log(
            "HLS relay for %s (sink %r) %s; restarting the relay child to restore "
            "the missing stream (attempt %d; if it fails again the next attempt is "
            "in %.0fs).",
            channel_id,
            key.split("|", 1)[1],
            reason,
            attempts,
            delay,
        )
        replacement = self._respawn_locked(key, channel_id, relay)
        if replacement is None:
            _LOG.error(
                "HLS relay for %s (sink %r) could not be restarted after %s; the "
                "hls sink has no live window until the next start/reload succeeds.",
                channel_id,
                key.split("|", 1)[1],
                reason,
            )
            return False
        replacement.stream_fault_attempts = attempts
        replacement.stream_retry_not_before = now + delay
        return True

    def maybe_restore_missing_streams(
        self,
        channel_id: str,
        *,
        now: float,
        producing: bool,
        startup_grace_s: float,
    ) -> bool:
        """U12: make a relay carry every kind its sink requires, or restart it.

        Two fault shapes, one bounded recovery:

        * **the child exited.** The relay argv requires each kind the sink
          carries (:func:`_relay_map_args`), so a child that probed an input
          missing any of them exits immediately instead of serving a
          half-program window (measured: real ffmpeg 8.1.1, "Stream map
          '0:v:0' matches no streams", no window written). Before this method,
          nothing respawned it: a dead relay was only recovered by the
          channel's next full encoder start/reload, which for an ON_AIR
          channel can be hours -- the live government relay sat audio-only/
          dead from 18:46:32 until the channel was restarted.
        * **the child is alive but its newest served segment is missing a
          required kind.** The belt to that braces (a child can in principle
          still be emitting a half-program window if its argv did not require
          the kind, or if a mapped stream's packets never arrive): the segment
          is probed once per child, and a positive verdict -- no video, or no
          audio for a sink that carries audio -- restarts the child.

        Gating, deliberately asymmetric:

        * the EXITED shape is recovered regardless of ``producing`` -- there is
          no healthy child to protect, and a channel that is still starting is
          exactly when a half-program probe is most likely;
        * the ALIVE shape requires ``producing`` (the caller's own on-air
          evidence latch), the child's own ``startup_grace_s``, and a sink that
          requires at least one kind, mirroring :meth:`maybe_self_heal_stalled`:
          a STARTING/no-source channel legitimately has no window yet and must
          never be restarted for it.

        A sink that requires no kind (the audio-only historic argv) is never
        judged here: it keeps its output, and only the EXITED shape (an
        ordinary relay death) applies to it. Returns True when at least one
        replacement was spawned.
        """
        with self._guard:
            targets = [
                (key, relay)
                for key, relay in self._relays.items()
                if key.startswith(f"{channel_id}|")
            ]
            if not targets:
                return False
            restored = False
            for key, relay in targets:
                playlist = _playlist_path_for(relay.source_uri)
                if relay.process.poll() is not None:
                    if self._stream_retry_blocked(relay, now=now):
                        continue
                    restored |= self._attempt_stream_restart(
                        key,
                        channel_id,
                        relay,
                        now=now,
                        reason="exited without a live window",
                    )
                    continue
                if not producing or relay.streams_verified:
                    continue
                required = _sink_required_kinds(relay.source_uri)
                if not required:
                    continue
                anchor = relay.started_at if relay.started_at is not None else relay.first_seen_at
                if anchor is not None and now - anchor < startup_grace_s:
                    continue
                segment = _last_segment(playlist)
                if segment is None or segment == relay.streams_probed_segment:
                    continue
                kinds = self._segment_probe(playlist.parent / segment)
                relay.streams_probed_segment = segment
                if kinds is None:
                    # Cannot tell (segment still being written, ffprobe absent or
                    # unhappy): claim nothing and never restart on ignorance.
                    continue
                missing = required - kinds
                if not missing:
                    relay.streams_verified = True
                    relay.stream_fault_attempts = 0
                    relay.stream_retry_not_before = None
                    continue
                if self._stream_retry_blocked(relay, now=now):
                    continue
                restored |= self._attempt_stream_restart(
                    key,
                    channel_id,
                    relay,
                    now=now,
                    reason=(
                        f"is serving a window missing its {_describe_kinds(missing)} "
                        f"stream ({segment} carries only {_describe_kinds(kinds) or 'nothing'})"
                    ),
                )
            return restored

    def is_alive(self, channel_id: str) -> bool | None:
        """Liveness of this channel's relay child(ren) (MAJOR M1).

        Before this method existed, nothing polled the relay subprocess after
        ``_ensure_relay`` started it: a relay that died later (disk full,
        ``ffmpeg`` missing/removed mid-run, OOM-killed) stayed dead until the
        channel's NEXT full encoder start/reload happened to call ``apply()``
        again (which does self-heal by restarting a dead relay lazily) --
        for a long-running ON_AIR channel that can be hours or days, all the
        while the GStreamer program mux keeps muxing fine and
        ``civiccast.egress.health.build_default_sink_health`` keeps reporting
        the ``hls`` sink healthy from the MAIN encoder's UDP send progress
        alone, blind to whether anything is still listening on the relay's
        loopback port. Returns ``None`` when no relay is currently tracked
        for this channel (not using an ``hls`` sink, or a relay was never
        successfully started) -- callers must not treat that as "dead",
        only "not applicable". Returns ``True``/``False`` (all-tracked-relays
        alive / at least one exited) when this channel has at least one
        tracked relay.

        NOTE: this is process liveness ONLY. A relay that is alive but has
        stopped writing segments is still ``True`` here -- see
        :meth:`progress_stale` for the emitting check the daemon layers on top.
        """
        with self._guard:
            relays = [
                relay for key, relay in self._relays.items() if key.startswith(f"{channel_id}|")
            ]
            if not relays:
                return None
            return all(relay.process.poll() is None for relay in relays)

    def note_progress(self, channel_id: str, *, now: float) -> None:
        """Anchor/refresh this channel's per-relay progress baseline.

        Called by the daemon each tick. Idempotent and read-only with respect to
        the child process. Progress is the last segment NAME only (audit
        finding 1): a manifest whose size/tags changed but whose final ``.ts``
        is identical is NOT progress.

        The stall latch clears ONLY when the window advances past the segment
        recorded at the last heal attempt (audit finding 4). Otherwise a frozen
        playlist left on disk would read as "progress" the instant its
        replacement child starts, re-arming the heal every bound.
        """
        with self._guard:
            for key, relay in self._relays.items():
                if not key.startswith(f"{channel_id}|"):
                    continue
                segment = _last_segment(_playlist_path_for(relay.source_uri))
                if segment is None:
                    # No readable window yet: never treated as progress.
                    continue
                if segment != relay.progress_segment:
                    if relay.heal_attempted and segment != relay.heal_baseline_segment:
                        # Genuinely advanced beyond the pre-heal baseline: the
                        # episode is over and a future stall may heal again.
                        relay.heal_attempted = False
                        relay.heal_baseline_segment = None
                    relay.progress_segment = segment
                    relay.progress_at = now
                elif relay.progress_at is None:
                    # First observation of an already-static window: anchor the
                    # baseline without claiming progress.
                    relay.progress_at = now

    def progress_stale(self, channel_id: str, *, now: float) -> bool | None:
        """True when ANY live relay for this channel has stopped advancing.

        Returns ``None`` only when the question genuinely does not apply: no
        relay tracked for the channel, or every live relay has no readable
        window yet AND has not yet exceeded its startup grace while the caller
        has confirmed production (see :meth:`never_emitted`). Returns ``False``
        while every live relay is fresh.

        ANY-relay semantics (audit finding 2): with two HLS sinks, one stalled
        and one advancing, the stalled sink must still be reported, so the
        per-relay verdicts are OR-combined, never AND. A dead relay contributes
        nothing here -- that is :meth:`is_alive`'s signal.
        """
        with self._guard:
            relays = [
                relay for key, relay in self._relays.items() if key.startswith(f"{channel_id}|")
            ]
            if not relays:
                return None
            saw_live_without_window = False
            for relay in relays:
                if relay.process.poll() is not None:
                    continue
                if relay.progress_segment is None or relay.progress_at is None:
                    saw_live_without_window = True
                    continue
                if now - relay.progress_at > self._stall_bound_s:
                    return True
            if saw_live_without_window:
                return None
            # Every relay is alive with a window and none is stale.
            return False

    def never_emitted(self, channel_id: str, *, now: float, startup_grace_s: float) -> bool | None:
        """True when ANY live relay has produced NO window past its OWN grace.

        Audit finding 3: a relay that never writes its first ``playlist.m3u8``
        used to stay ``None`` (unknown) forever, so a producing channel whose
        relay never emitted was permanently invisible.

        Audit follow-up (any-sink fault): with two HLS sinks, an early version
        returned ``None`` as soon as ANY sibling had a window, hiding the sink
        that never emitted. This is per-sink and ANY-based, mirroring
        :meth:`progress_stale`: a single window-less live relay that is past
        ITS OWN startup grace is a fault even while a sibling is healthy. Each
        relay is judged against its own spawn time, so one young relay cannot
        mask an old, never-emitting sibling (or vice versa).

        Returns ``None`` only when no relay is tracked, or when every live
        relay without a window is still inside its own grace (legitimate
        STARTING/no-source), or when no live relay lacks a window.
        """
        with self._guard:
            relays = [
                relay for key, relay in self._relays.items() if key.startswith(f"{channel_id}|")
            ]
            if not relays:
                return None
            live = [relay for relay in relays if relay.process.poll() is None]
            if not live:
                return None
            for relay in live:
                if relay.progress_segment is not None:
                    continue  # this sink has a readable window
                anchor = relay.started_at if relay.started_at is not None else relay.first_seen_at
                if anchor is None or now - anchor >= startup_grace_s:
                    return True  # this sink never emitted and is past its grace
            return None

    def maybe_self_heal_stalled(
        self,
        channel_id: str,
        *,
        now: float,
        producing: bool,
        startup_grace_s: float,
    ) -> bool:
        """Restart a stalled-but-alive relay at most once per stall episode.

        Conservative by construction -- returns True only when ALL hold:
          * a relay is tracked and its child is still alive,
          * ``producing`` is True (the caller has confirmed the channel is
            actually emitting; a STARTING/no-source channel never heals),
          * the window has been unchanged for longer than ``stall_bound_s``,
          * the relay child has itself been running longer than
            ``startup_grace_s`` (a just-(re)started child is never killed),
          * no heal has already been attempted in THIS episode.

        The replacement is spawned through the same single-slot path as every
        other ``apply`` (predecessor terminated first), so one (channel, sink)
        can never accumulate more than one child. Restarting DOES break viewer
        continuity for that sink's window: the muxer restarts its segment
        numbering from whatever ffmpeg chooses, so this is a deliberate
        last-resort recovery, not a seamless splice -- the caller logs it.
        """
        with self._guard:
            targets = [
                (key, relay)
                for key, relay in self._relays.items()
                if key.startswith(f"{channel_id}|")
            ]
            if not targets:
                return False
            if not producing:
                return False
            healed = False
            for key, relay in targets:
                if relay.process.poll() is not None:
                    continue
                if relay.heal_attempted:
                    continue
                anchor = relay.started_at if relay.started_at is not None else relay.first_seen_at
                if anchor is not None and now - anchor < startup_grace_s:
                    continue
                if relay.progress_segment is None or relay.progress_at is None:
                    # Never emitted a window at all (audit finding 3): a
                    # producing channel past its grace. Recover it the same way
                    # a stalled window is recovered.
                    baseline_segment = None
                    reason = "has produced no live window"
                elif now - relay.progress_at > self._stall_bound_s:
                    baseline_segment = relay.progress_segment
                    reason = f"has served no new segment for {now - relay.progress_at:.1f}s"
                else:
                    continue
                _LOG.warning(
                    "HLS relay for %s (sink %r) %s; restarting the relay child to "
                    "re-establish its window (viewer discontinuity possible).",
                    channel_id,
                    key.split("|", 1)[1],
                    reason,
                )
                new_relay = self._respawn_locked(key, channel_id, relay)
                if new_relay is None:
                    # Could not respawn (ffmpeg gone): report no heal and leave
                    # the sink to the existing dead-relay/health path.
                    healed = False
                    continue
                # Keep the episode latched on the NEW relay (audit finding 4):
                # until the served window advances past the pre-heal baseline,
                # a frozen playlist left on disk must not clear the latch.
                new_relay.heal_attempted = True
                new_relay.heal_baseline_segment = baseline_segment
                new_relay.progress_segment = baseline_segment
                new_relay.progress_at = now
                healed = True
            return healed

    def _drop_channel_relays(self, channel_id: str) -> int:
        """Terminate and forget every relay child tracked for ``channel_id``.

        Returns how many children were torn down. The single teardown seam for
        two callers: :meth:`stop_channel` (the channel is stopping) and
        :meth:`apply` with ``new_session=True`` (the channel is starting a
        genuinely new worker session). ``terminate`` is synchronous and bounded
        (``FfmpegProcessHandle.terminate``), so when this returns the UDP port is
        released and a replacement started immediately after can bind it.
        """
        with self._guard:
            keys = [key for key in self._relays if key.startswith(f"{channel_id}|")]
            for key in keys:
                relay = self._relays.pop(key)
                relay.process.terminate()
        return len(keys)

    def stop_channel(self, channel_id: str) -> None:
        """Tear down a channel's HLS relay(s) (channel stop, not encoder relaunch)."""
        self._drop_channel_relays(channel_id)

    def stop_all(self) -> None:
        with self._guard:
            for relay in self._relays.values():
                relay.process.terminate()
            self._relays.clear()


def _default_starter(args: list[str]) -> FfmpegProcessHandle:
    return start_ffmpeg(args)
