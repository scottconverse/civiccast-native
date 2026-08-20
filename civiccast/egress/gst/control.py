# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gi-free control-command parsing for the playout worker (Windows + WSL).

The per-channel worker reads newline-delimited commands from a control FIFO; this
parser is kept gi-free so it is unit-testable without GStreamer.

Two seamless mechanisms (both keep the persistent mux running — D-S1-6, never a
restart):

* ``swap <index>`` — switch the active source role among the *fixed* legs
  (program/slate/live). Drives the operator role controls (force-slate, live take).
* ``reload <path>`` — rebuild the *program* leg's content from a new serialized
  ``PlayoutGraph`` at ``<path>`` while output stays PLAYING. This is how the daemon
  applies a newly-due scheduled program without bouncing the encoder.
* ``caption <pts_ms> <dur_ms> <b64text>`` — push one timed-text caption cue into the
  live caption appsrc (S11a). The text is base64-encoded (the FIFO is newline-
  delimited and base64 has no spaces/newlines), so arbitrary caption text survives.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

ControlCommand = (
    tuple[Literal["swap"], int]
    | tuple[Literal["reload"], str]
    | tuple[Literal["stop"]]
    | tuple[Literal["caption"], int, int, str]
)

LIVE_CAPTION_LEAD_MS = 250


def install_unix_signal_handlers(
    glib: Any,
    *,
    signal_numbers: tuple[int, ...],
    quit_loop: Callable[[], None],
) -> bool:
    """Register GLib Unix-signal handlers only when the runtime provides them.

    PyGObject's native-Windows GLib binding has no ``unix_signal_add`` symbol.
    The worker is stopped through its named-pipe control channel on Windows, so
    skipping Unix signal registration there is intentional.  POSIX/WSL keeps
    the existing SIGINT/SIGTERM behavior.
    """

    unix_signal_add = getattr(glib, "unix_signal_add", None)
    if not callable(unix_signal_add):
        return False

    def _quit() -> bool:
        quit_loop()
        return False

    for signal_number in signal_numbers:
        unix_signal_add(glib.PRIORITY_DEFAULT, signal_number, _quit)
    return True


def align_live_caption_pts_ms(
    *,
    requested_pts_ms: int,
    running_time_ms: int,
    stream_position_ms: int = 0,
    lead_ms: int = LIVE_CAPTION_LEAD_MS,
) -> int:
    """Keep a live cue in the future even when ASR completed after its source PTS.

    Caption sidecars retain the source-audio timestamps.  The live appsrc cannot
    attach a cue to video buffers that already left the mux, so transport PTS is
    clamped to a small lead over the pipeline's current running time.  A cue
    already scheduled farther in the future keeps its original PTS.
    """

    if requested_pts_ms < 0 or running_time_ms < 0 or stream_position_ms < 0 or lead_ms < 0:
        raise ValueError("live caption timing values must be non-negative")
    return max(requested_pts_ms, running_time_ms + lead_ms, stream_position_ms)


def caption_gap_window_ms(
    *,
    stream_position_ms: int,
    running_time_ms: int,
) -> tuple[int, int] | None:
    """Return the next monotonic sparse-stream GAP window, if one is due."""

    if stream_position_ms < 0 or running_time_ms < 0:
        raise ValueError("live caption timing values must be non-negative")
    if running_time_ms <= stream_position_ms:
        return None
    return stream_position_ms, running_time_ms - stream_position_ms


def parse_control_line(line: str) -> ControlCommand | None:
    """Parse one control line; return a tuple, or None for blank/unknown.

    ``"swap <index>"`` → ``("swap", index)`` · ``"reload <path>"`` →
    ``("reload", path)`` · ``"stop"`` → ``("stop",)`` · ``"caption <pts_ms> <dur_ms>
    <b64text>"`` → ``("caption", pts_ms, dur_ms, b64text)``. The reload path is taken
    as the whole remainder of the line, so a path containing spaces is preserved.
    """
    parts = line.strip().split(None, 1)  # verb + remainder (at most one split)
    if not parts:
        return None
    verb = parts[0].lower()
    if verb == "swap" and len(parts) == 2 and parts[1].strip().isdigit():
        return ("swap", int(parts[1].strip()))
    if verb == "reload" and len(parts) == 2 and parts[1].strip():
        return ("reload", parts[1].strip())
    if verb == "caption" and len(parts) == 2:
        fields = parts[1].split()
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit() and fields[2]:
            return ("caption", int(fields[0]), int(fields[1]), fields[2])
        return None
    if verb == "stop" and len(parts) == 1:
        return ("stop",)
    return None
