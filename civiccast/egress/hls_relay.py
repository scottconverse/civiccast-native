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
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
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


class _Ffmpeg(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self, *, grace_seconds: float = 5.0) -> int | None: ...


@dataclass
class _Relay:
    source_uri: str  # the hls sink's original directory URI (identity + restart-on-change key)
    relay_uri: str  # the local udp:// the GStreamer branch actually writes to
    process: _Ffmpeg


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
    ) -> None:
        self._starter = starter or _default_starter
        self._base_port = base_port
        self._guard = Lock()
        self._relays: dict[str, _Relay] = {}
        self._unavailable_logged = False

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
            self._relays[key] = _Relay(source_uri=sink.uri, relay_uri=relay_uri, process=process)
            _LOG.info(
                "HLS relay up for %s (sink %r): %s -> %s.",
                channel_id,
                sink.label,
                relay_uri,
                sink.uri,
            )
            return relay_uri

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
