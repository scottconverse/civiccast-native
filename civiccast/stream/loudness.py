# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Streaming loudness compliance gate through the ffmpeg wrapper boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from civiccast.stream._ffmpeg import check_ffmpeg, run_ffmpeg


@dataclass(frozen=True)
class LoudnessGateResult:
    """ITU-R BS.1770 / EBU R128 loudness gate result."""

    status: str
    standard: str
    target_lufs: float
    used_ffmpeg_wrapper: bool
    measured_lufs: float | None
    operator_action: str


# The standard CivicCast has always reported; the default keeps every existing
# caller (streaming -16 LUFS) byte-for-byte the same.
DEFAULT_LOUDNESS_STANDARD = "ITU-R BS.1770 / EBU R128"


def _loudness_failure(
    *, standard: str, target_lufs: float, operator_action: str
) -> LoudnessGateResult:
    return LoudnessGateResult(
        status="failed",
        standard=standard,
        target_lufs=target_lufs,
        used_ffmpeg_wrapper=True,
        measured_lufs=None,
        operator_action=operator_action,
    )


def check_loudness(
    *,
    media_path: Path,
    target_lufs: float,
    tolerance_lufs: float,
    standard_label: str = DEFAULT_LOUDNESS_STANDARD,
    probe_start_seconds: float | None = None,
    probe_duration_seconds: float | None = None,
    threads: int | None = None,
) -> LoudnessGateResult:
    """Measure a media asset's integrated loudness and gate it against a target.

    ``target_lufs`` / ``standard_label`` are parameterised (S11b per-sink
    loudness): cable normalises to ATSC A/85 -24 LKFS, streaming to -16 LUFS,
    EBU R128 to -23 LUFS — all measured by the same ITU-R BS.1770 meter. The
    result reports the *destination's* standard instead of a single hardcoded
    one, and the remediation hint names the actual target.

    ``probe_start_seconds``/``probe_duration_seconds`` (item 66 round-3,
    Opus review): both ``None`` (every caller except the source preparer)
    measures the WHOLE file, unchanged. When given, they bound the probe to
    a window instead -- ``probe_start_seconds`` seeks (``-ss`` before
    ``-i``) and ``probe_duration_seconds`` limits (``-t`` after ``-i``),
    the same convention ``build_conform_source_args`` uses. This is a
    deliberate accuracy/speed trade the caller opts into; it does not
    change what a whole-file probe would report for material with uniform
    loudness, and it can differ for material that varies significantly
    across its length -- callers that need the whole-file measurement must
    leave both ``None``.

    ``threads`` (item 66 round-4, Opus review): caps the decode at that
    many threads (``-threads <N>``), same convention as
    ``build_conform_source_args``. Used by the source preparer's
    whole-file fallback probe (triggered when a bounded sample lands at
    the silence floor) so that synchronous fallback never runs fully
    unthrottled on the box.
    """

    if not media_path.exists():
        return _loudness_failure(
            standard=standard_label,
            target_lufs=target_lufs,
            operator_action=(
                f"Media file {media_path} is missing; render the release audio proof and "
                "rerun the loudness gate."
            ),
        )
    ffmpeg = check_ffmpeg()
    if ffmpeg is None:
        return _loudness_failure(
            standard=standard_label,
            target_lufs=target_lufs,
            operator_action=(
                "Install ffmpeg, verify it with civiccast doctor, then rerun loudness."
            ),
        )
    args = ["-hide_banner", "-nostats"]
    if probe_start_seconds is not None:
        args.extend(["-ss", f"{probe_start_seconds:g}"])
    args.extend(["-i", str(media_path)])
    # Item 66 follow-up (measured on HALO): the loudness gate only needs
    # the audio stream -- ``-vn`` drops video decode from the ebur128 pass
    # entirely. Measured 46.7s -> far less on a 39-min clip; unmeasured
    # exact delta here, but audio-only decode is strictly cheaper and never
    # changes the LUFS measurement (video frames never feed ebur128).
    args.append("-vn")
    if probe_duration_seconds is not None:
        args.extend(["-t", f"{probe_duration_seconds:g}"])
    if threads is not None:
        args.extend(["-threads", str(threads)])
    args.extend(["-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    result = run_ffmpeg(args)
    if result.returncode != 0:
        return _loudness_failure(
            standard=standard_label,
            target_lufs=target_lufs,
            operator_action="ffmpeg loudness analysis failed; inspect the media file and rerun.",
        )
    measured = _parse_integrated_lufs(result.stderr)
    if measured is None:
        return _loudness_failure(
            standard=standard_label,
            target_lufs=target_lufs,
            operator_action="ffmpeg did not report integrated LUFS; rerun with valid audio media.",
        )
    status = "ok" if abs(measured - target_lufs) <= tolerance_lufs else "failed"
    return LoudnessGateResult(
        status=status,
        standard=standard_label,
        target_lufs=target_lufs,
        used_ffmpeg_wrapper=True,
        measured_lufs=measured,
        operator_action="Loudness is within tolerance."
        if status == "ok"
        else f"Normalize audio to {target_lufs:g} LUFS and rerun the loudness gate.",
    )


def check_streaming_loudness(
    *,
    media_path: Path,
    target_lufs: float,
    tolerance_lufs: float,
    probe_start_seconds: float | None = None,
    probe_duration_seconds: float | None = None,
    threads: int | None = None,
) -> LoudnessGateResult:
    """Back-compat wrapper: gate streaming audio against its -16 LUFS target.

    Retained so existing callers (the source preparer, the FileSink/SRT
    continuity proofs, the CLI) and their test monkeypatches keep working while
    new per-sink callers use :func:`check_loudness` with a destination label.
    ``probe_start_seconds``/``probe_duration_seconds``/``threads`` forward to
    :func:`check_loudness` -- see its docstring (item 66 round-3: the source
    preparer bounds every probe to a window instead of the whole file;
    round-4: the whole-file fallback probe is thread-capped).
    """

    return check_loudness(
        media_path=media_path,
        target_lufs=target_lufs,
        tolerance_lufs=tolerance_lufs,
        probe_start_seconds=probe_start_seconds,
        probe_duration_seconds=probe_duration_seconds,
        threads=threads,
    )


def _parse_integrated_lufs(stderr: str) -> float | None:
    matches = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s+LUFS\b", stderr)
    if not matches:
        return None
    return float(matches[-1])
