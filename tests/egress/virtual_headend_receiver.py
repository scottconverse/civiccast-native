# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Virtual-headend receiver artifact wiring for E.2.

This module is test-only. It records or inspects the receiver-side MPEG-TS
artifact and turns the received output timeline into analyzer samples.
"""

from __future__ import annotations

import json
import math
import struct
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from civiccast.egress.continuity import split_srt_receiver_options
from civiccast.egress.models import CanonicalProfile, uri_looks_secret_bearing
from civiccast.egress.runtime import FfmpegRunner
from civiccast.stream._ffmpeg import FfmpegResult, run_ffmpeg
from tests.egress.virtual_headend_gate import (
    ExpectedOnAirWindow,
    ObservedHeadendSample,
    VirtualHeadendReport,
    analyze_virtual_headend_output,
)


class FfprobeRunner(Protocol):
    def __call__(self, args: list[str]) -> str: ...


MarkerReader = Callable[[float, ExpectedOnAirWindow | None], str]


@dataclass(frozen=True)
class ReceiverCaptureResult:
    """Result of recording the virtual-headend receiver artifact."""

    status: str
    receiver_output_path: Path
    ffmpeg_returncode: int
    blocker: str | None
    ffmpeg_args: tuple[str, ...]


def build_virtual_headend_receiver_args(
    *,
    input_url: str,
    output_path: Path,
    duration_seconds: float | None = None,
) -> list[str]:
    """Build FFmpeg args that record the receiver-side MPEG-TS artifact."""

    if uri_looks_secret_bearing(input_url):
        raise ValueError("virtual-headend receiver URL must not include secrets")
    receiver_mode, receiver_input_url = split_srt_receiver_options(input_url)
    mode_args = ["-mode", receiver_mode] if receiver_mode is not None else []
    duration_args = ["-t", f"{duration_seconds:g}"] if duration_seconds is not None else []
    return [
        "-hide_banner",
        *mode_args,
        *duration_args,
        "-i",
        receiver_input_url,
        "-c",
        "copy",
        "-f",
        "mpegts",
        str(output_path),
    ]


def run_virtual_headend_receiver_capture(
    *,
    input_url: str,
    output_path: Path,
    duration_seconds: float | None = None,
    ffmpeg_runner: FfmpegRunner = run_ffmpeg,
) -> ReceiverCaptureResult:
    """Record the downstream artifact that the analyzer will judge."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    args = build_virtual_headend_receiver_args(
        input_url=input_url,
        output_path=output_path,
        duration_seconds=duration_seconds,
    )
    result = ffmpeg_runner(args)
    blocker = None
    if result.returncode != 0:
        blocker = "VIRTUAL_HEADEND_RECEIVER_FFMPEG_FAILED"
    elif not output_path.exists():
        blocker = "VIRTUAL_HEADEND_RECEIVER_OUTPUT_MISSING"
    return ReceiverCaptureResult(
        status="PASS" if blocker is None else "FAIL",
        receiver_output_path=output_path,
        ffmpeg_returncode=result.returncode,
        blocker=blocker,
        ffmpeg_args=tuple(args),
    )


def analyze_receiver_artifact(
    *,
    received_path: Path,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    marker_reader: MarkerReader,
    ffprobe_runner: FfprobeRunner,
    max_output_gap_seconds: float = 1.25,
) -> VirtualHeadendReport:
    """Run the hostile analyzer against one recorded receiver artifact."""

    samples = samples_from_receiver_probe(
        probe_json=json.loads(_run_receiver_ffprobe(received_path, ffprobe_runner=ffprobe_runner)),
        expected_timeline=expected_timeline,
        marker_reader=marker_reader,
    )
    return analyze_virtual_headend_output(
        expected_timeline=expected_timeline,
        samples=samples,
        max_output_gap_seconds=max_output_gap_seconds,
    )


def samples_from_receiver_probe(
    *,
    probe_json: dict[str, Any],
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    marker_reader: MarkerReader,
) -> tuple[ObservedHeadendSample, ...]:
    """Convert ffprobe output packets into analyzer samples on the output timeline."""

    profile_id = _profile_id_from_probe(probe_json)
    samples: list[ObservedHeadendSample] = []
    observations = [
        packet
        for packet in (probe_json.get("packets") or probe_json.get("frames") or [])
        if (packet.get("codec_type") or packet.get("media_type")) == "video"
        and (packet.get("pts_time") or packet.get("best_effort_timestamp_time")) is not None
    ]
    if not observations:
        return ()
    first_pts_seconds = float(
        observations[0].get("pts_time") or observations[0].get("best_effort_timestamp_time")
    )
    for packet in observations:
        pts_value = packet.get("pts_time") or packet.get("best_effort_timestamp_time")
        pts_seconds = round(float(pts_value) - first_pts_seconds, 6)
        expected = _expected_at(expected_timeline, pts_seconds)
        samples.append(
            ObservedHeadendSample(
                pts_seconds=pts_seconds,
                marker=marker_reader(pts_seconds, expected),
                profile_id=profile_id,
                connected=True,
            )
        )
    return tuple(samples)


def expected_marker_reader(
    pts_seconds: float,
    expected: ExpectedOnAirWindow | None,
) -> str:
    """Temporary marker seam for receiver wiring tests.

    Real OCR/audio-ID extraction replaces this seam. Keeping it explicit avoids
    pretending that ffprobe alone can see burned-in content markers.
    """

    if expected is None:
        return "UNKNOWN"
    return expected.marker


def build_audio_tone_marker_reader(
    *,
    received_path: Path,
    marker_tones_hz: tuple[tuple[str, int], ...],
    ffmpeg_runner: FfmpegRunner = run_ffmpeg,
    sample_rate_hz: int = 8000,
    window_seconds: float = 0.60,
) -> MarkerReader:
    """Build a marker reader from decoded receiver audio.

    The deterministic E.2 media generator assigns each marker a distinct sine
    tone. This reader decodes the received artifact and identifies the loudest
    expected tone near each output timestamp so the analyzer is judging media
    evidence, not schedule metadata alone.
    """

    if not marker_tones_hz:
        raise ValueError("marker_tones_hz is required for audio marker extraction")
    samples = _decode_audio_samples(
        received_path=received_path,
        sample_rate_hz=sample_rate_hz,
        ffmpeg_runner=ffmpeg_runner,
    )
    tone_map = dict(marker_tones_hz)

    def read_marker(pts_seconds: float, expected: ExpectedOnAirWindow | None) -> str:
        if expected is None:
            return "UNKNOWN"
        expected_tone = tone_map.get(expected.marker)
        if expected_tone is None:
            return "AUDIO_MARKER_MISSING_EXPECTED_TONE"
        window_start = max(expected.start_seconds, pts_seconds - (window_seconds / 2.0))
        window_end = min(expected.end_seconds, pts_seconds + (window_seconds / 2.0))
        if window_end <= window_start:
            window_start = pts_seconds
            window_end = min(expected.end_seconds, pts_seconds + window_seconds)
        window = _sample_window(
            samples=samples,
            sample_rate_hz=sample_rate_hz,
            start_seconds=window_start,
            window_seconds=max(0.0, window_end - window_start),
        )
        if not window:
            return "AUDIO_MARKER_UNREADABLE"
        detected_marker = _detect_audio_marker(
            samples=window,
            sample_rate_hz=sample_rate_hz,
            marker_tones_hz=marker_tones_hz,
        )
        return detected_marker or "AUDIO_MARKER_UNREADABLE"

    return read_marker


def _run_receiver_ffprobe(received_path: Path, *, ffprobe_runner: FfprobeRunner) -> str:
    return ffprobe_runner(
        [
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_packets",
            str(received_path),
        ]
    )


def _profile_id_from_probe(probe_json: dict[str, Any]) -> str:
    video = _first_stream(probe_json, "video")
    audio = _first_stream(probe_json, "audio")
    width = int(video.get("width", 0))
    height = int(video.get("height", 0))
    fps = _rate_to_int(str(video.get("r_frame_rate") or video.get("avg_frame_rate") or "0/1"))
    video_codec = str(video.get("codec_name") or "unknown-video")
    audio_codec = str(audio.get("codec_name") or "unknown-audio")
    audio_rate = int(audio.get("sample_rate") or 0)
    return f"{width}x{height}-{fps}fps-{video_codec}-{audio_codec}-{audio_rate}hz"


def profile_id_from_canonical_profile(profile: CanonicalProfile) -> str:
    """Return the analyzer profile ID expected for a canonical profile."""

    video_codec = "h264" if profile.video_codec == "libx264" else profile.video_codec
    audio_codec = "aac" if profile.audio_codec == "aac" else profile.audio_codec
    return (
        f"{profile.width}x{profile.height}-"
        f"{profile.fps}fps-{video_codec}-"
        f"{audio_codec}-{profile.audio_sample_rate}hz"
    )


def _first_stream(probe_json: dict[str, Any], codec_type: str) -> dict[str, Any]:
    for stream in probe_json.get("streams", []):
        if stream.get("codec_type") == codec_type:
            return stream
    return {}


def _rate_to_int(value: str) -> int:
    numerator, _slash, denominator = value.partition("/")
    try:
        den = int(denominator or "1")
        return round(int(numerator) / den) if den else 0
    except ValueError:
        return 0


def _decode_audio_samples(
    *,
    received_path: Path,
    sample_rate_hz: int,
    ffmpeg_runner: FfmpegRunner,
) -> tuple[float, ...]:
    with tempfile.TemporaryDirectory(prefix="civiccast-e2-audio-marker-") as tmp:
        wav_path = Path(tmp) / "receiver-marker.wav"
        result = ffmpeg_runner(
            [
                "-hide_banner",
                "-loglevel",
                "warning",
                "-i",
                str(received_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate_hz),
                "-f",
                "wav",
                str(wav_path),
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not decode receiver audio marker: {result.stderr}")
        with wave.open(str(wav_path), "rb") as wav:
            if wav.getsampwidth() != 2:
                raise RuntimeError("audio marker decoder expected 16-bit PCM")
            frames = wav.readframes(wav.getnframes())
    if not frames:
        return ()
    values = struct.unpack(f"<{len(frames) // 2}h", frames)
    return tuple(value / 32768.0 for value in values)


def _sample_window(
    *,
    samples: tuple[float, ...],
    sample_rate_hz: int,
    start_seconds: float,
    window_seconds: float,
) -> tuple[float, ...]:
    start = max(0, int(start_seconds * sample_rate_hz))
    end = min(len(samples), start + max(1, int(window_seconds * sample_rate_hz)))
    return samples[start:end]


def _detect_audio_marker(
    *,
    samples: tuple[float, ...],
    sample_rate_hz: int,
    marker_tones_hz: tuple[tuple[str, int], ...],
) -> str | None:
    if not samples:
        return None
    scored = (
        (marker, _goertzel_power(samples=samples, sample_rate_hz=sample_rate_hz, tone_hz=tone_hz))
        for marker, tone_hz in marker_tones_hz
    )
    marker, power = max(scored, key=lambda item: item[1])
    return marker if power > 0.0 else None


def _goertzel_power(
    *,
    samples: tuple[float, ...],
    sample_rate_hz: int,
    tone_hz: int,
) -> float:
    coefficient = 2.0 * math.cos(2.0 * math.pi * tone_hz / sample_rate_hz)
    q1 = 0.0
    q2 = 0.0
    for sample in samples:
        q0 = coefficient * q1 - q2 + sample
        q2 = q1
        q1 = q0
    return (q1 * q1) + (q2 * q2) - (q1 * q2 * coefficient)


def _expected_at(
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    pts_seconds: float,
) -> ExpectedOnAirWindow | None:
    return next(
        (window for window in expected_timeline if window.contains(pts_seconds)),
        None,
    )


def ffmpeg_success() -> FfmpegResult:
    return FfmpegResult(returncode=0, stdout="", stderr="")
