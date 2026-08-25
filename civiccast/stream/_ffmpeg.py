# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Thin typed wrapper around the ffmpeg subprocess.

All ffmpeg invocations in civiccast.stream go through ``run_ffmpeg`` here.
Direct ``subprocess`` calls to ffmpeg from other modules are forbidden
(per ADR 0007 compliance section). This module is the single seam for
version checks, argument construction, and stderr parsing.

Sprint 0.2: ``progress_callback`` is called with each line after the process
completes (not in real time). Real-time streaming wires up at Sprint 0.3
when the operator UI needs live progress. The signature is forward-compatible.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final

from civiccast.stream.config import FFMPEG_MIN_VERSION

__all__ = [
    "FfmpegError",
    "FfmpegNotFoundError",
    "FfmpegProcessHandle",
    "FfmpegResult",
    "H264EncoderUnavailableError",
    "check_ffmpeg",
    "probe_ffmpeg_encoders",
    "resolve_h264_encoder",
    "run_ffmpeg",
    "start_ffmpeg",
    "verify_h264_encoder_usable",
]

_FFMPEG_EXECUTABLE = "ffmpeg"
#: Policy order: hardware first, then Windows Media Foundation, then the
#: royalty-free software encoder, then libx264 (GPL) strictly last. libx264 is
#: reachable ONLY when the probed binary itself carries it -- a station running
#: a full GPL ffmpeg build (WSL line, distro ffmpeg, CI). The pinned native
#: LGPL pack does not carry libx264, so native-line resolution can never
#: select it; the no-GPL constraint on the SHIPPED pack is enforced by the
#: pack builder and runtime_licenses, not by refusing a station's own encoder.
_H264_ENCODER_PRIORITY = ("h264_nvenc", "h264_mf", "libopenh264", "libx264")
_H264_REQUEST_NAMES = frozenset({"h264", "libx264"})
_VIDEO_CODEC_OPTIONS = frozenset({"-c:v", "-codec:v", "-vcodec"})
_ENCODER_LINE = re.compile(r"^\s*[VAS][A-Z.]{5}\s+([^\s=]+)")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FfmpegNotFoundError(RuntimeError):
    """ffmpeg binary not found on PATH."""


class FfmpegError(RuntimeError):
    """ffmpeg subprocess returned a non-zero exit code."""

    def __init__(self, message: str, returncode: int, stderr: str) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class H264EncoderUnavailableError(RuntimeError):
    """The selected FFmpeg binary has no CivicCast-supported H.264 encoder."""


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FfmpegResult:
    """Result of a completed ffmpeg subprocess call."""

    returncode: int
    stdout: str
    stderr: str


@dataclass
class FfmpegProcessHandle:
    """Handle for a running ffmpeg subprocess."""

    process: subprocess.Popen[str]
    _stdout_file: object | None = None
    _stderr_file: object | None = None

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        return self.process.poll()

    def terminate(self, *, grace_seconds: float = 5.0) -> int | None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=grace_seconds)
        self.close()
        return self.process.returncode

    def close(self) -> None:
        for file_obj in (self._stdout_file, self._stderr_file):
            if file_obj is not None and hasattr(file_obj, "close"):
                file_obj.close()


# ---------------------------------------------------------------------------
# Binary and encoder discovery
# ---------------------------------------------------------------------------


def _ffmpeg_path() -> str:
    path = shutil.which(_FFMPEG_EXECUTABLE)
    if path is None:
        raise FfmpegNotFoundError(
            "ffmpeg not found on PATH. Install or repair the bundled FFmpeg "
            "runtime and verify it with 'civiccast doctor'."
        )
    return path


def _parse_ffmpeg_encoders(output: str) -> frozenset[str]:
    """Parse encoder names from `ffmpeg -hide_banner -encoders` output."""

    return frozenset(
        match.group(1)
        for line in output.splitlines()
        if (match := _ENCODER_LINE.match(line)) is not None
    )


def probe_ffmpeg_encoders(ffmpeg_path: str) -> frozenset[str]:
    """Ask the exact FFmpeg executable which encoders it actually registers."""

    completed = subprocess.run(  # noqa: S603
        [ffmpeg_path, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        raise FfmpegError(
            f"FFmpeg encoder probe failed for {ffmpeg_path!r}.",
            completed.returncode,
            completed.stderr,
        )
    return _parse_ffmpeg_encoders(completed.stdout + "\n" + completed.stderr)


EncoderProbe = Callable[[str], Collection[str]]
EncoderUsabilityCheck = Callable[[str, str], bool]


def verify_h264_encoder_usable(ffmpeg_path: str, encoder: str) -> bool:
    """Prove the encoder can actually initialize, not merely that it is listed.

    ``-encoders`` reports what the build was COMPILED with; it says nothing
    about the runtime. h264_nvenc appears on any nvenc-enabled build but dies
    at init without an NVIDIA driver (``Cannot load libcuda.so.1`` -- caught
    live on CI), and h264_mf can fail on Windows images without the codec
    pack. A one-frame null encode is the only honest answer.
    """

    try:
        completed = subprocess.run(  # noqa: S603
            [
                ffmpeg_path,
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=64x64:rate=1",
                "-frames:v",
                "1",
                "-an",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0


@cache
def _resolve_h264_encoder_cached(
    ffmpeg_path: str, probe: EncoderProbe, verify: EncoderUsabilityCheck
) -> str:
    available = frozenset(probe(ffmpeg_path))
    unusable: list[str] = []
    for encoder in _H264_ENCODER_PRIORITY:
        if encoder not in available:
            continue
        if verify(ffmpeg_path, encoder):
            return encoder
        unusable.append(encoder)

    probed = ", ".join(sorted(available)) or "<none>"
    priority = ", ".join(_H264_ENCODER_PRIORITY)
    failed = (
        f" Advertised but failed the one-frame usability check: [{', '.join(unusable)}]."
        if unusable
        else ""
    )
    raise H264EncoderUnavailableError(
        f"No usable H.264 encoder for FFmpeg binary {ffmpeg_path!r}. "
        f"Probed encoders: [{probed}]. Supported encoders, in policy order: "
        f"[{priority}].{failed}"
    )


def resolve_h264_encoder(
    *,
    ffmpeg_path: str | None = None,
    probe: EncoderProbe = probe_ffmpeg_encoders,
    verify: EncoderUsabilityCheck = verify_h264_encoder_usable,
) -> str:
    """Resolve H.264 by policy order, verified usable, cached per exact binary."""

    return _resolve_h264_encoder_cached(ffmpeg_path or _ffmpeg_path(), probe, verify)


#: How each resolvable encoder spells the canonical H.264 profile names that
#: RenditionConfig uses (baseline/main/high). Measured against the pinned pack
#: binary (evidence 12): h264_mf rejects EVERY named value of the generic
#: -profile option, so the option must be omitted and MF's own default rules;
#: libopenh264 has no plain "baseline" constant -- only constrained_baseline.
_H264_PROFILE_DIALECTS: Final[dict[str, dict[str, str | None]]] = {
    "h264_mf": {"baseline": None, "main": None, "high": None},
    "libopenh264": {"baseline": "constrained_baseline"},
}


def _codec_option_stream_specifier(option: str) -> str | None:
    """The stream specifier of a video-codec option: ``v`` for -c:v/-codec:v/
    -vcodec, ``v:N`` for the qualified forms, None for anything else."""

    if option in _VIDEO_CODEC_OPTIONS:
        return "v"
    match = re.fullmatch(r"-(?:c|codec):(v(?::\d+)?)", option)
    return match.group(1) if match else None


def _resolve_video_encoder_args(args: list[str], ffmpeg_path: str) -> list[str]:
    """Resolve declarative/legacy H.264 codec values immediately before spawn,
    and translate ``-profile:v[:N]`` into the resolved encoder's dialect
    (dropping it where the encoder accepts no named profiles).

    A profile option is translated ONLY when its stream specifier matches a
    codec option this pass resolved (``-profile:v`` pairs with ``-c:v`` /
    ``-vcodec``; ``-profile:v:1`` pairs with ``-c:v:1``), so profiles that
    belong to streams we did not touch pass through unchanged. Known limit of
    flat-argv processing: two OUTPUT FILES that reuse the same unqualified
    specifier with different codecs cannot be told apart here — no CivicCast
    call site emits that shape (single output, unqualified options)."""

    resolved = list(args)
    encoder: str | None = None
    resolved_specifiers: set[str] = set()
    for index, option in enumerate(resolved[:-1]):
        specifier = _codec_option_stream_specifier(option)
        if specifier and resolved[index + 1].strip().lower() in _H264_REQUEST_NAMES:
            encoder = resolve_h264_encoder(ffmpeg_path=ffmpeg_path)
            resolved[index + 1] = encoder
            resolved_specifiers.add(specifier)

    dialect = _H264_PROFILE_DIALECTS.get(encoder or "")
    if not dialect or not resolved_specifiers:
        return resolved

    translated: list[str] = []
    index = 0
    while index < len(resolved):
        option = resolved[index]
        profile_match = re.fullmatch(r"-profile:(v(?::\d+)?)", option)
        if (
            profile_match
            and profile_match.group(1) in resolved_specifiers
            and index + 1 < len(resolved)
        ):
            requested = resolved[index + 1].strip().lower()
            if requested in dialect:
                spelling = dialect[requested]
                if spelling is not None:
                    translated.extend([option, spelling])
                index += 2
                continue
        translated.append(option)
        index += 1
    return translated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_DEFAULT_TIMEOUT_SECONDS = 6 * 3600  # generous: won't kill a legitimate large concat/transcode.


def run_ffmpeg(
    args: list[str],
    *,
    progress_callback: Callable[[str], None] | None = None,
    timeout: float | None = _DEFAULT_TIMEOUT_SECONDS,
    lower_priority: bool = False,
) -> FfmpegResult:
    """Run ffmpeg with the given argument list.

    ``args`` must NOT include the 'ffmpeg' binary name — only the arguments
    after it. This keeps call sites readable and prevents accidental
    shell=True injection.

    Raises ``FfmpegNotFoundError`` if the ffmpeg binary is absent.
    Does NOT raise on non-zero exit — callers inspect ``returncode``.

    ``timeout`` (seconds) bounds the subprocess so a hung/stuck ffmpeg
    (corrupt input, disk contention, etc.) cannot block the calling thread
    forever. Defaults to a generous ceiling that a legitimate call is not
    expected to hit; pass ``None`` for no timeout, or a smaller value for a
    caller with tighter latency needs. Raises ``subprocess.TimeoutExpired``
    on expiry — callers that run under a shared lock or need per-job error
    handling should catch it explicitly (see
    ``civiccast.recording.runtime._finalize_segments``).

    ``lower_priority`` starts the subprocess at Windows' BELOW_NORMAL
    priority class (same ``getattr(subprocess, ..., 0)`` degrade-to-0
    pattern :func:`start_ffmpeg` already uses for ``CREATE_NO_WINDOW``, so
    it is a harmless no-op on non-Windows/test platforms). Default is
    ``False`` — unattended background work (S7's media lifecycle worker)
    opts in explicitly; real-time/latency-sensitive callers (live egress,
    the VOD packager answering an operator's HTTP request) must keep
    running at the process's normal priority, so this must never become a
    blanket default here.
    """
    ffmpeg_path = _ffmpeg_path()
    resolved_args = _resolve_video_encoder_args(args, ffmpeg_path)

    # -y: overwrite output files without prompting (required for idempotent runs).
    # Security: shell=False (the default); args is an explicit list, never a string.
    cmd = [ffmpeg_path, "-y", *resolved_args]

    creationflags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if lower_priority else 0

    completed = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=creationflags,
    )

    if progress_callback is not None:
        for line in completed.stderr.splitlines():
            progress_callback(line)

    return FfmpegResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def start_ffmpeg(
    args: list[str],
    *,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
) -> FfmpegProcessHandle:
    """Start ffmpeg without waiting for it to exit."""

    ffmpeg_path = _ffmpeg_path()
    resolved_args = _resolve_video_encoder_args(args, ffmpeg_path)

    if stdout_path is not None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
    if stderr_path is not None:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("a", encoding="utf-8") if stdout_path else None
    stderr_file = stderr_path.open("a", encoding="utf-8") if stderr_path else None
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(  # noqa: S603
        [ffmpeg_path, "-y", *resolved_args],
        stdout=stdout_file or subprocess.DEVNULL,
        stderr=stderr_file or subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    return FfmpegProcessHandle(
        process=process,
        _stdout_file=stdout_file,
        _stderr_file=stderr_file,
    )


def check_ffmpeg() -> tuple[str, bool] | None:
    """Return (version_string, is_supported) or None if ffmpeg is not found.

    Called by ``civiccast doctor`` (Sprint 0.2 extension per ADR 0007)
    to report the detected ffmpeg version and warn if it's outside the
    supported range.  Returns None when ffmpeg is not on PATH at all.
    """
    if shutil.which(_FFMPEG_EXECUTABLE) is None:
        return None

    result = run_ffmpeg(["-version"])
    if result.returncode != 0:
        return None

    version_str = _parse_ffmpeg_version(result.stdout + "\n" + result.stderr)
    if version_str is None:
        return "unknown", True  # found but version not parseable — don't block

    return version_str, _version_is_supported(version_str)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_ffmpeg_version(output: str) -> str | None:
    """Extract the version token from 'ffmpeg -version' output."""
    match = re.search(r"ffmpeg version\s+(\S+)", output, re.IGNORECASE)
    return match.group(1) if match else None


def _version_is_supported(version_str: str) -> bool:
    """True if version_str is >= FFMPEG_MIN_VERSION.

    Handles build-tag prefixes like 'n6.1.1', 'N-107442-g...', '4.4.2-0ubuntu...'.
    Unknown formats are treated as supported so doctor warns but doesn't hard-block.
    """
    # Drop any leading non-digit prefix.
    clean = re.sub(r"^[^\d]*", "", version_str)
    # Strip any trailing build metadata after the first '-' or '+'.
    clean = re.split(r"[-+]", clean)[0]
    parts = clean.split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor) >= FFMPEG_MIN_VERSION
    except ValueError:
        return True
