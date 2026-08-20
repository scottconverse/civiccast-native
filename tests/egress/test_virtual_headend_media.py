# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from civiccast.egress.models import CanonicalProfile
from civiccast.stream._ffmpeg import FfmpegResult
from tests.egress.virtual_headend_media import (
    VirtualHeadendMediaSpec,
    build_virtual_headend_media_args,
    default_virtual_headend_media_specs,
    generate_virtual_headend_media_set,
    nonconforming_virtual_headend_media_spec,
)


def _runner_that_creates_files(calls: list[list[str]]):
    def runner(args: list[str]) -> FfmpegResult:
        calls.append(args)
        Path(args[-1]).write_bytes(b"mpeg-ts")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return runner


def test_default_virtual_headend_media_specs_include_required_markers() -> None:
    specs = default_virtual_headend_media_specs(program_segments=2, duration_seconds=1.5)

    assert [spec.marker for spec in specs] == [
        "SEGMENT 001",
        "SEGMENT 002",
        "SLATE",
        "LIVE SOURCE",
        "EMERGENCY OVERLAY",
    ]
    assert specs[2].allow_freeze is True
    assert specs[2].allow_silence is True


def test_build_virtual_headend_media_args_encode_markers_and_canonical_profile(
    tmp_path: Path,
) -> None:
    profile = CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200)
    spec = VirtualHeadendMediaSpec(
        label="Program 001",
        marker="SEGMENT 001",
        duration_seconds=2.0,
        tone_hz=700,
    )

    args = build_virtual_headend_media_args(
        output_path=tmp_path / "segment.ts",
        spec=spec,
        profile=profile,
    )

    joined = " ".join(args)
    assert "testsrc2=size=640x360:rate=30:duration=2" in joined
    assert "sine=frequency=700:sample_rate=48000:duration=2" in joined
    assert "volume=4.0dB" in args
    assert "SEGMENT 001" in joined
    assert "%{pts\\:hms} %{n}" in joined
    assert "1200k" in args
    assert args[-3:] == ["-f", "mpegts", str(tmp_path / "segment.ts")]


def test_generate_virtual_headend_media_set_returns_source_plan_and_expected_timeline(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    profile = CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200)

    generated = generate_virtual_headend_media_set(
        channel_id="gov",
        output_dir=tmp_path / "media",
        profile=profile,
        specs=default_virtual_headend_media_specs(program_segments=2, duration_seconds=1.5),
        ffmpeg_runner=_runner_that_creates_files(calls),
    )

    assert generated.source_plan.channel_id == "gov"
    assert [segment.label for segment in generated.source_plan.segments] == [
        "Program 001",
        "Program 002",
        "Fallback slate",
        "Live source",
        "Emergency overlay",
    ]
    assert [window.marker for window in generated.expected_timeline] == [
        "SEGMENT 001",
        "SEGMENT 002",
        "SLATE",
        "LIVE SOURCE",
        "EMERGENCY OVERLAY",
    ]
    assert [window.start_seconds for window in generated.expected_timeline] == [
        0.0,
        1.5,
        3.0,
        4.5,
        6.0,
    ]
    assert all(path.exists() for path in generated.output_paths)
    assert len(calls) == 5
    assert len(generated.ffmpeg_args) == 5
    assert generated.marker_tones_hz[0] == ("SEGMENT 001", 700)


def test_generate_virtual_headend_media_set_uses_measured_segment_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    profile = CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200)

    monkeypatch.setattr(
        "tests.egress.virtual_headend_media.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="2.021334\n",
            stderr="",
        ),
    )

    generated = generate_virtual_headend_media_set(
        channel_id="gov",
        output_dir=tmp_path / "media",
        profile=profile,
        specs=default_virtual_headend_media_specs(program_segments=2, duration_seconds=2.0),
        ffmpeg_runner=_runner_that_creates_files(calls),
    )

    assert [window.start_seconds for window in generated.expected_timeline[:3]] == [
        0.0,
        2.021,
        4.043,
    ]
    assert generated.source_plan.segments[0].duration_seconds == 2.021334


def test_nonconforming_media_spec_uses_distinct_profile_id(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    profile = CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200)

    generated = generate_virtual_headend_media_set(
        channel_id="gov",
        output_dir=tmp_path / "media",
        profile=profile,
        specs=(nonconforming_virtual_headend_media_spec(),),
        ffmpeg_runner=_runner_that_creates_files(calls),
    )

    assert generated.expected_timeline[0].marker == "NONCONFORMING PROFILE"
    assert generated.expected_timeline[0].profile_id.startswith("854x480")
    assert "testsrc2=size=854x480" in " ".join(calls[0])


def test_generate_virtual_headend_media_set_fails_closed_on_ffmpeg_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Could not generate virtual-headend media"):
        generate_virtual_headend_media_set(
            channel_id="gov",
            output_dir=tmp_path / "media",
            profile=CanonicalProfile(),
            specs=(
                VirtualHeadendMediaSpec(
                    label="Program",
                    marker="SEGMENT 001",
                    duration_seconds=1,
                ),
            ),
            ffmpeg_runner=lambda _args: FfmpegResult(returncode=1, stdout="", stderr="boom"),
        )
