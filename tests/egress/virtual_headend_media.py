# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Deterministic E.2 test media generator.

This is test-only infrastructure for the virtual-headend gate. It creates
marker-rich MPEG-TS segments that the hostile analyzer can later verify.
"""

from __future__ import annotations

import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from civiccast.egress.models import CanonicalProfile, EgressSourcePlan, EgressSourceSegment
from civiccast.egress.runtime import FfmpegRunner
from civiccast.stream._ffmpeg import run_ffmpeg
from tests.egress.virtual_headend_gate import ExpectedOnAirWindow

TestMediaKind = Literal["program", "slate", "live", "cg"]


@dataclass(frozen=True)
class VirtualHeadendMediaSpec:
    """One deterministic media segment to generate for the E.2 gate."""

    label: str
    marker: str
    duration_seconds: float
    kind: TestMediaKind = "program"
    tone_hz: int = 880
    allow_freeze: bool = False
    allow_silence: bool = False
    nonconforming_profile: CanonicalProfile | None = None


@dataclass(frozen=True)
class GeneratedTestMediaSet:
    """Generated media plus the analyzer's expected output timeline."""

    source_plan: EgressSourcePlan
    expected_timeline: tuple[ExpectedOnAirWindow, ...]
    output_paths: tuple[Path, ...]
    ffmpeg_args: tuple[tuple[str, ...], ...]
    marker_tones_hz: tuple[tuple[str, int], ...] = ()


def default_virtual_headend_media_specs(
    *,
    program_segments: int = 3,
    duration_seconds: float = 2.0,
) -> tuple[VirtualHeadendMediaSpec, ...]:
    """Return a small deterministic program/slate/live/CG media set."""

    if program_segments < 1:
        raise ValueError("program_segments must be at least 1")
    specs: list[VirtualHeadendMediaSpec] = [
        VirtualHeadendMediaSpec(
            label=f"Program {index:03d}",
            marker=f"SEGMENT {index:03d}",
            duration_seconds=duration_seconds,
            tone_hz=660 + (index * 40),
        )
        for index in range(1, program_segments + 1)
    ]
    specs.extend(
        [
            VirtualHeadendMediaSpec(
                label="Fallback slate",
                marker="SLATE",
                duration_seconds=duration_seconds,
                kind="slate",
                tone_hz=330,
                allow_freeze=True,
                allow_silence=True,
            ),
            VirtualHeadendMediaSpec(
                label="Live source",
                marker="LIVE SOURCE",
                duration_seconds=duration_seconds,
                kind="live",
                tone_hz=990,
            ),
            VirtualHeadendMediaSpec(
                label="Emergency overlay",
                marker="EMERGENCY OVERLAY",
                duration_seconds=duration_seconds,
                kind="cg",
                tone_hz=1200,
            ),
        ]
    )
    return tuple(specs)


def nonconforming_virtual_headend_media_spec(
    *,
    duration_seconds: float = 2.0,
) -> VirtualHeadendMediaSpec:
    """Return the required profile-switch negative-control media spec."""

    return VirtualHeadendMediaSpec(
        label="Nonconforming profile switch",
        marker="NONCONFORMING PROFILE",
        duration_seconds=duration_seconds,
        tone_hz=1440,
        nonconforming_profile=CanonicalProfile(width=854, height=480, video_bitrate_kbps=1800),
    )


def generate_virtual_headend_media_set(
    *,
    channel_id: str,
    output_dir: Path,
    profile: CanonicalProfile,
    specs: tuple[VirtualHeadendMediaSpec, ...],
    ffmpeg_runner: FfmpegRunner = run_ffmpeg,
) -> GeneratedTestMediaSet:
    """Generate marker-rich media and return its source plan plus expected timeline."""

    if not specs:
        raise ValueError("at least one media spec is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    segments: list[EgressSourceSegment] = []
    expected: list[ExpectedOnAirWindow] = []
    output_paths: list[Path] = []
    captured_args: list[tuple[str, ...]] = []
    marker_tones_hz: list[tuple[str, int]] = []
    elapsed = 0.0
    for index, spec in enumerate(specs, start=1):
        active_profile = spec.nonconforming_profile or profile
        output_path = output_dir / f"{index:04d}-{_slug(spec.marker)}.ts"
        args = build_virtual_headend_media_args(
            output_path=output_path,
            spec=spec,
            profile=active_profile,
        )
        result = ffmpeg_runner(args)
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not generate virtual-headend media {spec.marker!r}: {result.stderr}"
            )
        measured_duration_seconds = _measure_media_duration_seconds(
            output_path,
            fallback_seconds=spec.duration_seconds,
        )
        segments.append(
            EgressSourceSegment(
                label=spec.label,
                path=str(output_path),
                duration_seconds=measured_duration_seconds,
                kind=spec.kind,
                source_ref=f"virtual-headend:{_slug(spec.marker)}",
            )
        )
        expected.append(
            ExpectedOnAirWindow(
                start_seconds=round(elapsed, 3),
                end_seconds=round(elapsed + measured_duration_seconds, 3),
                source_label=spec.label,
                marker=spec.marker,
                profile_id=_profile_id(active_profile),
                allow_freeze=spec.allow_freeze,
                allow_silence=spec.allow_silence,
            )
        )
        output_paths.append(output_path)
        captured_args.append(tuple(args))
        marker_tones_hz.append((spec.marker, spec.tone_hz))
        elapsed += measured_duration_seconds
    return GeneratedTestMediaSet(
        source_plan=EgressSourcePlan(channel_id=channel_id, segments=segments),
        expected_timeline=tuple(expected),
        output_paths=tuple(output_paths),
        ffmpeg_args=tuple(captured_args),
        marker_tones_hz=tuple(marker_tones_hz),
    )


def build_virtual_headend_media_args(
    *,
    output_path: Path,
    spec: VirtualHeadendMediaSpec,
    profile: CanonicalProfile,
) -> list[str]:
    """Build FFmpeg args for one deterministic E.2 media segment."""

    video_source = (
        f"testsrc2=size={profile.width}x{profile.height}:rate={profile.fps}:"
        f"duration={spec.duration_seconds}"
    )
    audio_source = (
        f"sine=frequency={spec.tone_hz}:sample_rate={profile.audio_sample_rate}:"
        f"duration={spec.duration_seconds}"
    )
    drawtext = (
        # Interpolates a caller-supplied marker, so ffmpeg's %{...} expansion
        # is disabled here for the same reason it is everywhere in civiccast/
        # (gate finding F-1).
        "drawtext=expansion=none:"
        f"text='{_escape_drawtext(spec.marker)}':"
        "x=48:y=48:"
        "fontsize=48:"
        "fontcolor=white:"
        "box=1:boxcolor=black@0.65,"
        # drawtext-expansion-required: this overlay burns a timecode and frame
        # counter into the fixture using ffmpeg's own %{pts}/%{n} expansion --
        # that expansion IS the feature here. The text is a fixed literal with
        # no caller input, so there is nothing to inject. Adding
        # expansion=none would render the literal string "%{pts:hms} %{n}".
        "drawtext="
        "text='%{pts\\:hms} %{n}':"
        "x=48:y=118:"
        "fontsize=28:"
        "fontcolor=yellow:"
        "box=1:boxcolor=black@0.45"
    )
    return [
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "lavfi",
        "-i",
        video_source,
        "-f",
        "lavfi",
        "-i",
        audio_source,
        "-t",
        _format_seconds(spec.duration_seconds),
        "-vf",
        f"{drawtext},format=yuv420p",
        "-c:v",
        profile.video_codec,
        "-b:v",
        f"{profile.video_bitrate_kbps}k",
        "-maxrate",
        f"{profile.video_bitrate_kbps}k",
        "-bufsize",
        f"{profile.video_bitrate_kbps * 2}k",
        "-g",
        str(profile.gop_size),
        "-r",
        str(profile.fps),
        "-af",
        "volume=4.0dB",
        "-c:a",
        profile.audio_codec,
        "-b:a",
        f"{profile.audio_bitrate_kbps}k",
        "-ar",
        str(profile.audio_sample_rate),
        "-ac",
        str(profile.audio_channels),
        "-f",
        profile.container,
        str(output_path),
    ]


def _profile_id(profile: CanonicalProfile) -> str:
    video_codec = "h264" if profile.video_codec == "libx264" else profile.video_codec
    audio_codec = "aac" if profile.audio_codec == "aac" else profile.audio_codec
    return (
        f"{profile.width}x{profile.height}-"
        f"{profile.fps}fps-{video_codec}-"
        f"{audio_codec}-{profile.audio_sample_rate}hz"
    )


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in slug.split("-") if part)


def _stable_seed(value: str) -> int:
    return zlib.crc32(value.encode("utf-8")) % 9999


def _escape_drawtext(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _format_seconds(value: float) -> str:
    return f"{value:g}"


def _measure_media_duration_seconds(path: Path, *, fallback_seconds: float) -> float:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return fallback_seconds
    if completed.returncode != 0:
        return fallback_seconds
    try:
        duration = float(completed.stdout.strip())
    except ValueError:
        return fallback_seconds
    return duration if duration > 0 else fallback_seconds
