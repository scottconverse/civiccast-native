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
"""

from __future__ import annotations

import hashlib
import logging
import os
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
_DEFAULT_PORT_BASE = 18_000
_PORT_RANGE = 500
_UDP_INPUT_ARGS = (
    "-fflags",
    "+genpts",
    "-analyzeduration",
    "2000000",
    "-probesize",
    "2000000",
)
#: How long a live relay may go with an UNCHANGED last segment + playlist
#: before the window is reported (and optionally healed) as stalled. The live
#: symptom was minutes, so 30s is far above a healthy 2s segment cadence and
#: every real muxer hiccup, while still bounding a visible freeze.
_DEFAULT_STALL_BOUND_S = 30.0


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
    ) -> None:
        self._starter = starter or _default_starter
        self._base_port = base_port
        self._guard = Lock()
        self._relays: dict[str, _Relay] = {}
        self._unavailable_logged = False
        self._stall_bound_s = stall_bound_s if stall_bound_s is not None else _DEFAULT_STALL_BOUND_S
        # Monotonic clock, injectable for tests. Must be the SAME clock domain
        # the caller passes as ``now`` to note_progress/progress_stale/self-heal;
        # the daemon uses its own ``_monotonic`` for exactly that reason.
        self._clock: Callable[[], float] = time.monotonic

    def apply(self, config: EgressConfig) -> EgressConfig:
        """Return a config whose ``hls`` sinks point at their channel-lifetime relay.

        Idempotent per (channel_id, sink.label): the relay is reused across
        encoder relaunches. A sink whose relay could not be started (ffmpeg
        missing) is returned UNCHANGED — still declared ``hls``, so
        ``sink_element_spec``'s own hls branch builds a udpsink to the same
        deterministic port; nothing is listening there, but the channel still
        starts (degraded: no live HLS, everything else on the channel keeps
        working) rather than crashing.
        """
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
        args = [
            *_UDP_INPUT_ARGS,
            "-i",
            f"{relay_uri}?overrun_nonfatal=1&fifo_size=50000000",
            *HlsSink(sink).output_args(),
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
                sink = EgressSinkSpec(kind="hls", label=key.split("|", 1)[1], uri=relay.source_uri)
                relay.process.terminate()
                self._relays.pop(key, None)
                relay_uri = hls_relay_uri_for(relay.source_uri, base_port=self._base_port)
                _LOG.warning(
                    "HLS relay for %s (sink %r) %s; restarting the relay child to "
                    "re-establish its window (viewer discontinuity possible).",
                    channel_id,
                    sink.label,
                    reason,
                )
                replacement = self._start_relay_locked(key, channel_id, sink, relay_uri)
                if replacement is None:
                    # Could not respawn (ffmpeg gone): report no heal and leave
                    # the sink to the existing dead-relay/health path.
                    healed = False
                    continue
                # Keep the episode latched on the NEW relay (audit finding 4):
                # until the served window advances past the pre-heal baseline,
                # a frozen playlist left on disk must not clear the latch.
                new_relay = self._relays.get(key)
                if new_relay is not None:
                    new_relay.heal_attempted = True
                    new_relay.heal_baseline_segment = baseline_segment
                    new_relay.progress_segment = baseline_segment
                    new_relay.progress_at = now
                healed = True
            return healed

    def stop_channel(self, channel_id: str) -> None:
        """Tear down a channel's HLS relay(s) (channel stop, not encoder relaunch)."""
        with self._guard:
            for key in [k for k in self._relays if k.startswith(f"{channel_id}|")]:
                relay = self._relays.pop(key)
                relay.process.terminate()

    def stop_all(self) -> None:
        with self._guard:
            for relay in self._relays.values():
                relay.process.terminate()
            self._relays.clear()


def _default_starter(args: list[str]) -> FfmpegProcessHandle:
    return start_ffmpeg(args)
