# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Production server-side media probe for the live go-on-air pre-flight.

Bug B2: ``civiccast.live.preflight.PreflightEvaluator``'s ``live_source``
check requires a ``source_probe`` callable (see that module's docstring
and ``SourceProbe`` type alias). Without one, the check fails CLOSED with
``REASON_LIVE_SOURCE_NOT_PROBED`` -- correct behavior for an evaluator
that must never silently claim media is arriving when nobody checked.
But the only ``source_probe`` implementation anywhere in this tree was
``civiccast.installer.service._probe_sample_rehearsal_media``, wired
*only* into the installer's private System Health rehearsal, which
validates a local recorded sample file, not a live feed. ``civiccast.
app._resolve_preflight_evaluator`` -- the constructor used by every real
station's running service -- built ``PreflightEvaluator(_session_factory)``
with no probe at all. Net effect: a correctly configured RTMP/RTSP/SRT/NDI
source on a real station could never pass the live_source check, so
go-on-air always 409'd from the product UI (spec §12 station-acceptance:
"schedules a day and commits to air; interrupts with live and returns
safely" -- unreachable without this).

This module is that real probe. It asks ``ffprobe`` to open the
configured :class:`~civiccast.live.models.LiveSource`'s endpoint and
confirms CivicCast can actually see a video or audio stream before the
station commits to air -- the same "does media actually arrive" contract
the rehearsal probe already enforces for its local sample file, extended
to the live network sources the product ships.

Bounded timeout is load-bearing: :func:`probe_live_source` runs inline in
the ``POST /go-on-air`` HTTP request path
(``civiccast.live.router.go_on_air`` -> ``PreflightEvaluator.evaluate``).
An encoder that never answers must not hang that request forever, so the
subprocess is killed at ``timeout_seconds`` wall-clock regardless of what
the target protocol's own timeout options do or don't honor.
``CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS`` overrides the default
(read by :func:`build_source_probe`, not by :func:`probe_live_source`
itself, which always requires an explicit value from its caller).

Known limitation, stated plainly rather than silently glossed over:
:attr:`~civiccast.live.models.LiveSource.credentials_handle` (the OS
credential store reference described in spec §15) is not resolved here.
No credential-resolution helper exists anywhere in this codebase yet (an
authenticated source's URL never carries embedded credentials --
``civiccast.installer.service._source_setup_endpoint`` rejects those at
setup time -- and nothing reads ``credentials_handle`` back out). A
source that requires authentication will fail this probe with whatever
protocol-level auth error the encoder returns; this module does not
pretend to authenticate on the operator's behalf. Wiring the credential
store into the probe is a separate, larger change.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civiccast.live.models import LiveSource

__all__ = [
    "DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS",
    "SourceProbeFn",
    "build_source_probe",
    "probe_live_source",
]

SourceProbeFn = Callable[["LiveSource"], "tuple[bool, str | None]"]

_FFPROBE_EXECUTABLE = "ffprobe"
_NDI_DEMUXER = "libndi_newtek"

#: Wall-clock ceiling for a single probe when the caller (or the
#: ``CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS`` env var) doesn't
#: specify one. Long enough for a real encoder to hand back its first
#: frames over SRT/RTMP on a LAN; short enough that an operator staring
#: at the "Go on air" button gets an answer, not a hang.
DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS = 8.0

# Bounds ffprobe's own stream analysis so a source that DOES connect but
# never stabilizes (e.g. a stalled encoder handshake) can't consume the
# whole timeout budget just forming its answer. Belt-and-suspenders with
# the subprocess-level timeout below, which is the authoritative bound.
_PROBE_ANALYZEDURATION_US = "5000000"  # 5s of analysis
_PROBE_PROBESIZE_BYTES = "5000000"  # 5 MB

# Truncate ffprobe stderr in the operator-facing message -- enough to be
# actionable ("Connection refused", "401 Unauthorized"), not enough to
# dump a raw protocol trace into a 409 body.
_MAX_DETAIL_CHARS = 400


def _timeout_from_env(default: float) -> float:
    raw = os.environ.get("CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _describe(source: LiveSource) -> str:
    return f"{source.source_type} source {source.name!r} ({source.live_source_id})"


def _build_probe_command(source: LiveSource) -> list[str] | None:
    """Return the full ffprobe argv for ``source``, or ``None`` if this
    source type/endpoint shape has no probe path yet (fails closed)."""
    endpoint = source.endpoint_url.strip()
    if not endpoint:
        return None

    base = [
        _FFPROBE_EXECUTABLE,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "-analyzeduration",
        _PROBE_ANALYZEDURATION_US,
        "-probesize",
        _PROBE_PROBESIZE_BYTES,
    ]

    if source.source_type == "ndi":
        name = endpoint.removeprefix("ndi://").strip()
        if not name:
            return None
        return [*base, "-f", _NDI_DEMUXER, "-i", name]

    if source.source_type in ("rtmp", "rtsp", "srt"):
        return [*base, "-i", endpoint]

    return None


def probe_live_source(
    source: LiveSource,
    *,
    timeout_seconds: float,
) -> tuple[bool, str | None]:
    """Probe whether ``source`` is currently delivering media.

    Returns ``(True, message)`` when ffprobe found at least one usable
    video or audio stream; ``(False, message)`` on every other outcome
    (ffprobe missing, unsupported source shape, timeout, non-zero exit,
    unparseable output, or a response with no media streams). ``message``
    always names the source so a 409 detail built from it is actionable.
    This function never raises for probe-outcome reasons -- the boolean
    is the contract, matching ``civiccast.live.preflight.SourceProbe``.
    """
    label = _describe(source)

    if shutil.which(_FFPROBE_EXECUTABLE) is None:
        return False, (
            f"Cannot probe {label}: ffprobe is not installed on this station. "
            "Install ffmpeg (which ships ffprobe) and verify with 'civiccast doctor'."
        )

    cmd = _build_probe_command(source)
    if cmd is None:
        return False, (
            f"Cannot probe {label}: source type {source.source_type!r} with endpoint "
            f"{source.endpoint_url!r} is not recognized by the server-side probe."
        )

    try:
        completed = subprocess.run(  # noqa: S603 -- fixed executable name, no shell, argv built above
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return False, (
            f"{label} did not respond within {timeout_seconds:.0f}s. Confirm the encoder is "
            f"powered on and reachable at {source.endpoint_url!r}, then run pre-flight again."
        )
    except OSError as exc:
        return False, f"Could not start ffprobe to check {label}: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-_MAX_DETAIL_CHARS:]
        return False, (
            f"{label} did not respond to a server-side media probe"
            + (f": {detail}" if detail else ".")
        )

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False, f"{label} probe returned unreadable output; treating it as unavailable."

    streams = data.get("streams") if isinstance(data, dict) else None
    streams = streams if isinstance(streams, list) else []
    has_video = any(isinstance(s, dict) and s.get("codec_type") == "video" for s in streams)
    has_audio = any(isinstance(s, dict) and s.get("codec_type") == "audio" for s in streams)

    if not has_video and not has_audio:
        return False, f"{label} answered the probe but sent no video or audio stream."

    kinds = " + ".join(
        kind for kind, present in (("video", has_video), ("audio", has_audio)) if present
    )
    return True, f"{label} is delivering {kinds}; server-side media probe passed."


def build_source_probe(
    *,
    timeout_seconds: float | None = None,
) -> SourceProbeFn:
    """Build the ``SourceProbe`` callable ``PreflightEvaluator`` expects.

    ``civiccast.app._resolve_preflight_evaluator`` calls this with no
    arguments so every real station gets a real probe;
    ``CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS`` (default
    :data:`DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS`) tunes it without a code
    change. Tests and the installer's rehearsal path pass their own probe
    (or ``source_probe_override``) instead of calling this.
    """
    resolved_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else _timeout_from_env(DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS)
    )

    def _probe(source: LiveSource) -> tuple[bool, str | None]:
        return probe_live_source(source, timeout_seconds=resolved_timeout)

    return _probe
