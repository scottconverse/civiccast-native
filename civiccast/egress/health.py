# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Health metric parsing for egress encoder logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from civiccast.egress.models import EgressConfig, EgressState


@dataclass(frozen=True)
class EgressEncoderMetrics:
    """Encoder metrics parsed from FFmpeg progress output."""

    encoder_fps: float | None = None
    encoder_bitrate_kbps: float | None = None
    dropped_frames: int | None = None


#: D44 (real-hardware tester run, 2026-09-05): how much of the tail of a worker
#: stderr log is scanned for the newest metrics. The daemon reads this file
#: on every ~2s health tick (twice per tick, from two call sites), and the log
#: grows for the whole life of the channel -- reading it whole meant re-reading
#: and re-regexing an ever-growing file forever, a cost that showed up as
#: control-plane CPU in a long soak. Only the newest values are wanted and an
#: ffmpeg progress line is ~100 bytes, so 64 KiB is hundreds of lines of
#: history: far more than enough to find the last parseable one.
_TAIL_BYTES = 64 * 1024

_FPS_RE = re.compile(r"\bfps=\s*(?P<value>[0-9]+(?:\.[0-9]+)?)")
_BITRATE_RE = re.compile(r"\bbitrate=\s*(?P<value>[0-9]+(?:\.[0-9]+)?)\s*(?P<unit>[kKmM]?bits/s)")
_DROP_RE = re.compile(r"\bdrop(?:_frames)?=\s*(?P<value>[0-9]+)")

#: Item 82 round-3 (PR #183 review, BLOCKER item 1): the ONLY genuine evidence
#: that a GStreamer worker's pipeline actually reached PLAYING -- printed by
#: ``civiccast.egress.gst.engine.GstPlayoutEngine._await_playing`` exactly
#: once, on the success path, never on a timeout. A stable, parsed contract
#: (not just a human-readable log line): the daemon's alive-poll health check
#: (``EgressDaemon._poll_process``) greps for it instead of trusting
#: wall-clock seconds since the worker was spawned, which also counts
#: interpreter start + ``import gi``/``Gst.init`` + graph build + the preroll
#: wait itself -- none of which is air, and none of which is bounded by the
#: worker's own ``preroll_timeout_s``.
_PLAYING_REACHED_RE = re.compile(r"^CTRL preroll: reached PLAYING")


def worker_reached_playing(path: Path, *, tail_bytes: int = _TAIL_BYTES) -> bool:
    """Return whether the worker's stderr log shows real evidence it reached
    the PLAYING state (see ``_PLAYING_REACHED_RE``) -- as opposed to merely
    having not exited yet, which proves nothing about whether it ever produced
    output. Only the last ``tail_bytes`` are scanned (D44 cost rationale,
    same as ``read_latest_ffmpeg_encoder_metrics``); the marker is a single
    short line printed once, so 64 KiB of tail comfortably covers a
    multi-minute-old worker's still-recent history. Missing/unreadable log
    -> False, same fail-closed default as no evidence at all."""

    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            if tail_bytes >= 0 and size > tail_bytes:
                handle.seek(size - tail_bytes)
            else:
                handle.seek(0)
            raw = handle.read()
    except OSError:
        return False
    return any(
        _PLAYING_REACHED_RE.match(line)
        for line in raw.decode("utf-8", errors="replace").splitlines()
    )


def parse_ffmpeg_encoder_metrics_line(line: str) -> EgressEncoderMetrics:
    """Parse one FFmpeg progress/status line into health metrics."""

    fps = _parse_float(_FPS_RE.search(line))
    bitrate = _parse_bitrate_kbps(_BITRATE_RE.search(line))
    dropped = _parse_int(_DROP_RE.search(line))
    return EgressEncoderMetrics(
        encoder_fps=fps,
        encoder_bitrate_kbps=bitrate,
        dropped_frames=dropped,
    )


def read_latest_ffmpeg_encoder_metrics(
    path: Path, *, tail_bytes: int = _TAIL_BYTES
) -> EgressEncoderMetrics:
    """Return the newest parseable FFmpeg metrics from a stderr log.

    Only the last ``tail_bytes`` of the file are read (D44) -- the newest
    values are all this returns, and the log is polled every couple of seconds
    for the whole life of a channel. A partial first line from cutting
    mid-line is harmless: it is parsed like any other line and simply
    contributes whichever fields survived the cut, and is superseded by every
    complete line after it.
    """

    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            if tail_bytes >= 0 and size > tail_bytes:
                handle.seek(size - tail_bytes)
            else:
                handle.seek(0)
            raw = handle.read()
    except OSError:
        # Missing, locked, or unreadable: no metrics, same as before.
        return EgressEncoderMetrics()
    latest = EgressEncoderMetrics()
    for line in raw.decode("utf-8", errors="replace").splitlines():
        parsed = parse_ffmpeg_encoder_metrics_line(line)
        latest = EgressEncoderMetrics(
            encoder_fps=parsed.encoder_fps
            if parsed.encoder_fps is not None
            else latest.encoder_fps,
            encoder_bitrate_kbps=parsed.encoder_bitrate_kbps
            if parsed.encoder_bitrate_kbps is not None
            else latest.encoder_bitrate_kbps,
            dropped_frames=parsed.dropped_frames
            if parsed.dropped_frames is not None
            else latest.dropped_frames,
        )
    return latest


def build_default_sink_health(
    *,
    config: EgressConfig,
    metrics: EgressEncoderMetrics,
    state: EgressState,
) -> dict[str, bool]:
    """Build conservative sink health when no transport-specific provider exists.

    External sinks need receiver or transport acknowledgement from a provider.
    Local file-like sinks can be treated as locally healthy once the encoder is
    configured, because they do not have a far-end connection to prove.

    Audit QA-004 (S8): the progress check is **state-aware**. A fire-and-forget UDP
    sink is judged "connected" by encoder progress ONLY when ``state == "ON_AIR"`` —
    then no progress is a real, observable stall (False). When the channel is idling
    on a slate (or otherwise not on air) the encoder emits no/stale fps/bitrate and
    there is no far-end to disprove, so the sink is healthy by default (True). Before
    this fix, a stale ``fps=0`` line on a slating channel flipped a TSDuck-clean UDP
    sink to ``False`` for hours, training operators to ignore the flag.
    """

    require_progress = state == "ON_AIR"
    metrics_available = metrics.encoder_fps is not None or metrics.encoder_bitrate_kbps is not None
    if require_progress:
        # On air: a UDP sink is connected iff the encoder is actually moving media;
        # on air with no measurable progress is a genuine problem worth surfacing.
        udp_ok = encoder_has_progress(metrics) if metrics_available else False
    else:
        # Idle on slate / not on air: no far-end to disprove → healthy by default.
        udp_ok = True
    health: dict[str, bool] = {}
    for sink in config.sinks:
        if sink.kind == "file":
            health[sink.label] = True
            continue
        if sink.kind == "local-ts" and urlsplit(sink.uri).scheme.lower() == "file":
            health[sink.label] = True
            continue
        health[sink.label] = False if sink.kind in {"srt", "rtmp", "sdi"} else udp_ok
    return health


def encoder_has_progress(metrics: EgressEncoderMetrics) -> bool:
    """Return whether FFmpeg metrics show active media movement."""

    return (
        metrics.encoder_fps is not None
        and metrics.encoder_fps > 0
        and metrics.encoder_bitrate_kbps is not None
        and metrics.encoder_bitrate_kbps > 0
    )


def _parse_float(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    return float(match.group("value"))


def _parse_int(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return int(match.group("value"))


def _parse_bitrate_kbps(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    value = float(match.group("value"))
    unit = match.group("unit").lower()
    if unit.startswith("mbits"):
        return value * 1000
    if unit.startswith("bits"):
        return value / 1000
    return value
