#!/usr/bin/env python
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Spike the CivicCast egress continuity seam.

This is not the egress engine. It is the first proof harness for the cheapest
candidate strategy from docs/spec/2.0/channel-egress-engine-build-plan.md:
one FFmpeg process reads a pre-conformed concat plan and keeps one output open
while source boundaries advance.

The proof is intentionally honest. FileSink and loopback SRT are useful signals,
but they are not a real cable headend or representative downstream receiver.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CANONICAL_WIDTH = 1280
CANONICAL_HEIGHT = 720
CANONICAL_FPS = 30
CANONICAL_VIDEO_BITRATE = "3000k"
CANONICAL_AUDIO_BITRATE = "192k"
CANONICAL_AUDIO_RATE = 48_000


class FfmpegNotFoundError(RuntimeError):
    """ffmpeg binary not found on PATH."""


@dataclass(frozen=True)
class FfmpegResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ReceiverMetrics:
    output_path: str | None
    returncode: int | None
    measured_duration_seconds: float | None
    duration_within_tolerance: bool | None
    stderr_tail: str


@dataclass(frozen=True)
class BoundaryEvent:
    index: int
    source_label: str
    expected_start_seconds: float


@dataclass(frozen=True)
class ContinuitySpikeResult:
    passed: bool
    strategy: str
    sink_kind: str
    boundary_count: int
    expected_duration_seconds: float
    measured_duration_seconds: float | None
    duration_within_tolerance: bool
    ffmpeg_returncode: int
    output_path: str
    concat_plan_path: str
    boundary_events: list[BoundaryEvent]
    not_claimed: list[str]
    operator_action: str
    receiver_metrics: ReceiverMetrics | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def run_ffmpeg(args: list[str]) -> FfmpegResult:
    """Run ffmpeg without importing the full CivicCast package.

    This spike must run on a minimal clean tester where project dependencies are
    intentionally absent. Keep this wrapper local and dependency-free.
    """

    if shutil.which("ffmpeg") is None:
        raise FfmpegNotFoundError("ffmpeg not found on PATH")

    completed = subprocess.run(
        ["ffmpeg", "-y", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return FfmpegResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("build/egress-continuity-spike"),
        help="Directory for generated source assets, concat plan, output, and JSON.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional explicit JSON result path. Defaults under --output-dir.",
    )
    parser.add_argument(
        "--boundary-count",
        type=int,
        default=10,
        help="Number of source boundaries to cross. There will be boundary_count + 1 segments.",
    )
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=1.0,
        help="Duration of each generated segment.",
    )
    parser.add_argument(
        "--sink",
        choices=("file", "srt"),
        default="file",
        help="Output sink. Use file for CI/local proof; srt requires --srt-url.",
    )
    parser.add_argument(
        "--srt-url",
        default=None,
        help="SRT output URL for --sink srt. Do not include secrets in this URL.",
    )
    parser.add_argument(
        "--srt-receiver-url",
        default=None,
        help=(
            "Optional SRT receiver URL to start before the sender, e.g. "
            "srt://127.0.0.1:19001?mode=listener. Loopback is not headend proof."
        ),
    )
    parser.add_argument(
        "--srt-receiver-output",
        type=Path,
        default=None,
        help="Optional MPEG-TS file written by the SRT receiver for duration proof.",
    )
    parser.add_argument(
        "--srt-receiver-timeout-seconds",
        type=float,
        default=10.0,
        help="Seconds to wait for the optional SRT receiver to exit after the sender exits.",
    )
    parser.add_argument(
        "--srt-receiver-startup-seconds",
        type=float,
        default=1.0,
        help="Seconds to wait after starting the optional SRT receiver before starting the sender.",
    )
    parser.add_argument(
        "--keep-going-on-ffmpeg-missing",
        action="store_true",
        help="Write a failed JSON result instead of raising when ffmpeg/ffprobe is missing.",
    )
    return parser.parse_args()


def _require_gpl_ffmpeg() -> None:
    """This spike is EXPLICITLY SCOPED to GPL FFmpeg builds (terra round-3):
    its encode legs use libx264 + x264 presets, which the shipped LGPL pack
    deliberately does not carry. It targets a minimal clean tester with a
    distro/GPL ffmpeg, and stays dependency-free, so it cannot route through
    civiccast.stream._ffmpeg's resolver. Fail loud up front instead of
    mid-spike."""

    if shutil.which("ffmpeg") is None:
        raise FfmpegNotFoundError("ffmpeg not found on PATH")
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise FfmpegNotFoundError(f"could not run ffmpeg encoder probe: {exc}") from exc
    if probe.returncode != 0:
        raise FfmpegNotFoundError(
            f"ffmpeg encoder probe exited {probe.returncode}: {probe.stderr.strip()}"
        )
    if "libx264" not in (probe.stdout + probe.stderr):
        raise SystemExit(
            "egress-continuity-spike: this ffmpeg build has no libx264 encoder. "
            "The spike is scoped to GPL FFmpeg builds (distro ffmpeg on a clean "
            "tester); it cannot run against the shipped LGPL runtime pack. "
            "Install a GPL ffmpeg build or run it on a tester machine."
        )


def main() -> int:
    args = parse_args()
    json_output = args.json_output or args.output_dir / "egress-continuity-spike.json"
    try:
        _require_gpl_ffmpeg()
        result = run_spike(
            output_dir=args.output_dir,
            boundary_count=args.boundary_count,
            segment_seconds=args.segment_seconds,
            sink=args.sink,
            srt_url=args.srt_url,
            srt_receiver_url=args.srt_receiver_url,
            srt_receiver_output=args.srt_receiver_output,
            srt_receiver_timeout_seconds=args.srt_receiver_timeout_seconds,
            srt_receiver_startup_seconds=args.srt_receiver_startup_seconds,
        )
    except (FfmpegNotFoundError, FileNotFoundError) as exc:
        if not args.keep_going_on_ffmpeg_missing:
            raise
        result = failed_environment_result(
            output_dir=args.output_dir,
            boundary_count=args.boundary_count,
            reason=str(exc),
        )

    rendered = result.to_json()
    print(rendered)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result.passed else 1


def run_spike(
    *,
    output_dir: Path,
    boundary_count: int,
    segment_seconds: float,
    sink: str = "file",
    srt_url: str | None = None,
    srt_receiver_url: str | None = None,
    srt_receiver_output: Path | None = None,
    srt_receiver_timeout_seconds: float = 10.0,
    srt_receiver_startup_seconds: float = 1.0,
) -> ContinuitySpikeResult:
    if boundary_count < 1:
        raise ValueError("boundary_count must be at least 1")
    if segment_seconds <= 0:
        raise ValueError("segment_seconds must be positive")
    if sink == "srt" and not srt_url:
        raise ValueError("--srt-url is required for --sink srt")
    if sink == "srt" and _looks_secret_bearing(srt_url or ""):
        raise ValueError("SRT URL appears to include a secret; use a secret-free test URL")
    if srt_receiver_url and sink != "srt":
        raise ValueError("--srt-receiver-url is only valid with --sink srt")
    if srt_receiver_url and not srt_receiver_output:
        raise ValueError("--srt-receiver-output is required with --srt-receiver-url")
    if srt_receiver_url and _looks_secret_bearing(srt_receiver_url):
        raise ValueError("SRT receiver URL appears to include a secret; use a secret-free test URL")

    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    source_a = sources_dir / "source-a.ts"
    source_b = sources_dir / "source-b.ts"
    concat_plan = output_dir / "concat-plan.ffconcat"
    file_output = output_dir / "egress-continuity-output.ts"
    if file_output.exists():
        file_output.unlink()
    if srt_receiver_output is not None and srt_receiver_output.exists():
        srt_receiver_output.unlink()

    generate_conformed_source(
        source_a,
        label="A",
        color="0x2458A6",
        frequency_hz=440,
        segment_seconds=segment_seconds,
    )
    generate_conformed_source(
        source_b,
        label="B",
        color="0x1B7F5F",
        frequency_hz=660,
        segment_seconds=segment_seconds,
    )
    events = write_concat_plan(
        concat_plan,
        [source_a, source_b],
        boundary_count=boundary_count,
        segment_seconds=segment_seconds,
    )
    output_target = str(file_output) if sink == "file" else with_srt_default_linger(str(srt_url))
    expected_duration = (boundary_count + 1) * segment_seconds
    receiver_process: subprocess.Popen[str] | None = None
    receiver_metrics = None
    try:
        if srt_receiver_url and srt_receiver_output:
            receiver_process = start_srt_receiver(
                receiver_url=srt_receiver_url,
                output_path=srt_receiver_output,
            )
            time.sleep(max(0.0, srt_receiver_startup_seconds))

        encode_result = run_persistent_concat_encoder(
            concat_plan=concat_plan,
            output_target=output_target,
            sink=sink,
        )
    finally:
        if receiver_process is not None and srt_receiver_output is not None:
            receiver_metrics = collect_srt_receiver_metrics(
                receiver_process=receiver_process,
                output_path=srt_receiver_output,
                expected_duration=expected_duration,
                timeout_seconds=srt_receiver_timeout_seconds,
            )

    measured_duration = (
        probe_duration(file_output) if sink == "file" and file_output.exists() else None
    )
    if sink == "srt" and receiver_metrics is not None:
        measured_duration = receiver_metrics.measured_duration_seconds
    duration_ok = measured_duration is not None and abs(
        measured_duration - expected_duration
    ) <= max(1.0, expected_duration * 0.10)
    receiver_ok = (
        receiver_metrics is not None
        and receiver_metrics.returncode == 0
        and receiver_metrics.duration_within_tolerance is True
    )
    passed = encode_result.returncode == 0 and (duration_ok if sink == "file" else receiver_ok)
    operator_action = "Proceed to real-or-representative SRT receiver testing."
    if sink == "srt" and receiver_metrics is None:
        operator_action = (
            "Add an instrumented SRT receiver or use a real downstream receiver proof; "
            "sender-only SRT output is not accepted as continuity evidence."
        )
    elif not passed:
        operator_action = "Inspect ffmpeg output and do not accept Option A from this run."

    return ContinuitySpikeResult(
        passed=passed,
        strategy="concat-demuxer-single-ffmpeg-process",
        sink_kind=sink,
        boundary_count=boundary_count,
        expected_duration_seconds=round(expected_duration, 3),
        measured_duration_seconds=round(measured_duration, 3)
        if measured_duration is not None
        else None,
        duration_within_tolerance=duration_ok,
        ffmpeg_returncode=encode_result.returncode,
        output_path=output_target,
        concat_plan_path=str(concat_plan),
        boundary_events=events,
        not_claimed=[
            "This proof does not validate a real cable headend.",
            "This proof does not validate QAM modulation, SDI output, EAS, or CEA-708 captions.",
            "A FileSink or loopback SRT PASS is not equivalent to real downstream receiver proof.",
        ],
        operator_action=operator_action,
        receiver_metrics=receiver_metrics,
    )


def generate_conformed_source(
    output_path: Path,
    *,
    label: str,
    color: str,
    frequency_hz: int,
    segment_seconds: float,
) -> None:
    """Generate one already-conformed MPEG-TS source segment."""

    video = (
        f"color=c={color}:size={CANONICAL_WIDTH}x{CANONICAL_HEIGHT}:"
        f"rate={CANONICAL_FPS}:duration={segment_seconds}"
    )
    audio = (
        f"sine=frequency={frequency_hz}:sample_rate={CANONICAL_AUDIO_RATE}:"
        f"duration={segment_seconds}"
    )
    result = run_ffmpeg(
        [
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            video,
            "-f",
            "lavfi",
            "-i",
            audio,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            CANONICAL_VIDEO_BITRATE,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(CANONICAL_FPS),
            "-g",
            str(CANONICAL_FPS * 2),
            "-c:a",
            "aac",
            "-b:a",
            CANONICAL_AUDIO_BITRATE,
            "-ar",
            str(CANONICAL_AUDIO_RATE),
            "-ac",
            "2",
            "-metadata",
            f"title=CivicCast egress spike source {label}",
            "-shortest",
            "-f",
            "mpegts",
            str(output_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"source generation failed for {label}: {result.stderr[-800:]}")


def write_concat_plan(
    plan_path: Path,
    sources: list[Path],
    *,
    boundary_count: int,
    segment_seconds: float,
) -> list[BoundaryEvent]:
    """Write an ffconcat file and return the expected boundary events."""

    lines = ["ffconcat version 1.0"]
    events: list[BoundaryEvent] = []
    for index in range(boundary_count + 1):
        source = sources[index % len(sources)]
        lines.append(f"file '{source.resolve().as_posix()}'")
        if index > 0:
            events.append(
                BoundaryEvent(
                    index=index,
                    source_label=source.stem,
                    expected_start_seconds=round(index * segment_seconds, 3),
                )
            )
    plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return events


def run_persistent_concat_encoder(*, concat_plan: Path, output_target: str, sink: str):
    """Run one FFmpeg process that owns the output for the whole proof."""

    input_rate_args = ["-re"] if sink == "srt" else []
    output_args = ["-f", "mpegts", output_target]
    return run_ffmpeg(
        [
            "-hide_banner",
            *input_rate_args,
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_plan),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            CANONICAL_VIDEO_BITRATE,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(CANONICAL_FPS),
            "-g",
            str(CANONICAL_FPS * 2),
            "-c:a",
            "aac",
            "-b:a",
            CANONICAL_AUDIO_BITRATE,
            "-ar",
            str(CANONICAL_AUDIO_RATE),
            "-ac",
            "2",
            "-mpegts_flags",
            "+resend_headers",
            *output_args,
        ]
    )


def start_srt_receiver(*, receiver_url: str, output_path: Path) -> subprocess.Popen[str]:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FfmpegNotFoundError("ffmpeg not found on PATH")
    receiver_mode, receiver_input_url = split_srt_receiver_options(receiver_url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode_args = ["-mode", receiver_mode] if receiver_mode is not None else []
    return subprocess.Popen(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            *mode_args,
            "-i",
            receiver_input_url,
            "-c",
            "copy",
            "-f",
            "mpegts",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def split_srt_receiver_options(url: str) -> tuple[str | None, str]:
    """Move SRT receiver options out of the input URL when needed.

    Some Windows FFmpeg builds fail opening an SRT listener when `mode=listener`
    is present only in the input URL, but accept the equivalent `-mode listener`
    command option. The same builds reject receiver-side latency in the input
    URL. Keep the CLI URL contract stable and normalize internally.
    """

    parsed = urlsplit(url)
    if parsed.scheme.lower() != "srt":
        return None, url
    query = parse_qsl(parsed.query, keep_blank_values=True)
    mode = None
    kept_query: list[tuple[str, str]] = []
    for key, value in query:
        if key.lower() == "mode" and mode is None:
            mode = value
        elif key.lower() == "latency":
            continue
        else:
            kept_query.append((key, value))
    if mode is None:
        return None, url
    normalized_query = urlencode(kept_query)
    return mode, urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            normalized_query,
            parsed.fragment,
        )
    )


def with_srt_default_linger(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "srt":
        return url
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key.lower() == "linger" for key, _value in query):
        return url
    query.append(("linger", "5"))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def collect_srt_receiver_metrics(
    *,
    receiver_process: subprocess.Popen[str],
    output_path: Path,
    expected_duration: float,
    timeout_seconds: float,
) -> ReceiverMetrics:
    try:
        stdout, stderr = receiver_process.communicate(timeout=max(0.1, timeout_seconds))
    except subprocess.TimeoutExpired:
        receiver_process.terminate()
        try:
            stdout, stderr = receiver_process.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            receiver_process.kill()
            stdout, stderr = receiver_process.communicate()
        returncode = -999
        stderr = f"{stderr}\nreceiver timed out after sender exit"
    else:
        returncode = receiver_process.returncode

    measured_duration = probe_duration(output_path) if output_path.exists() else None
    duration_ok = measured_duration is not None and abs(
        measured_duration - expected_duration
    ) <= max(1.0, expected_duration * 0.10)
    combined_stderr = (stderr or "") + ("\n" + stdout if stdout else "")
    return ReceiverMetrics(
        output_path=str(output_path),
        returncode=returncode,
        measured_duration_seconds=round(measured_duration, 3)
        if measured_duration is not None
        else None,
        duration_within_tolerance=duration_ok,
        stderr_tail=combined_stderr[-1200:],
    )


def probe_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise FileNotFoundError("ffprobe not found on PATH")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        return float(completed.stdout.strip())
    except ValueError:
        return None


def failed_environment_result(
    *,
    output_dir: Path,
    boundary_count: int,
    reason: str,
) -> ContinuitySpikeResult:
    return ContinuitySpikeResult(
        passed=False,
        strategy="concat-demuxer-single-ffmpeg-process",
        sink_kind="file",
        boundary_count=boundary_count,
        expected_duration_seconds=0.0,
        measured_duration_seconds=None,
        duration_within_tolerance=False,
        ffmpeg_returncode=-1,
        output_path=str(output_dir / "egress-continuity-output.ts"),
        concat_plan_path=str(output_dir / "concat-plan.ffconcat"),
        boundary_events=[],
        not_claimed=[
            "This proof did not run because the local FFmpeg environment was incomplete.",
            "No headend, SRT, caption, EAS, SDI, or compliance claim is made.",
        ],
        operator_action=reason,
    )


def _looks_secret_bearing(url: str) -> bool:
    lowered = url.lower()
    return (
        "passphrase=" in lowered or "streamkey=" in lowered or ("://" in lowered and "@" in lowered)
    )


if __name__ == "__main__":
    sys.exit(main())
