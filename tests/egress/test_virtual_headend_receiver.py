# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

import pytest

from tests.egress.virtual_headend_gate import ExpectedOnAirWindow
from tests.egress.virtual_headend_receiver import (
    analyze_receiver_artifact,
    build_audio_tone_marker_reader,
    build_virtual_headend_receiver_args,
    expected_marker_reader,
    ffmpeg_success,
    profile_id_from_canonical_profile,
    run_virtual_headend_receiver_capture,
    samples_from_receiver_probe,
)


def _timeline() -> tuple[ExpectedOnAirWindow, ...]:
    profile_id = "640x360-30fps-h264-aac-48000hz"
    return (
        ExpectedOnAirWindow(
            start_seconds=0,
            end_seconds=2,
            source_label="Program 001",
            marker="SEGMENT 001",
            profile_id=profile_id,
        ),
        ExpectedOnAirWindow(
            start_seconds=2,
            end_seconds=4,
            source_label="Program 002",
            marker="SEGMENT 002",
            profile_id=profile_id,
        ),
    )


def _probe_json(*, pts: tuple[float, ...] = (0.0, 1.0, 2.0, 3.0)) -> dict[str, object]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 360,
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
            },
        ],
        "packets": [{"codec_type": "video", "pts_time": f"{value:.6f}"} for value in pts],
    }


def test_build_virtual_headend_receiver_args_normalizes_srt_listener_options(
    tmp_path: Path,
) -> None:
    args = build_virtual_headend_receiver_args(
        input_url="srt://127.0.0.1:19001?mode=listener&latency=200000",
        output_path=tmp_path / "receiver.ts",
        duration_seconds=12,
    )

    assert args[:5] == ["-hide_banner", "-mode", "listener", "-t", "12"]
    assert "srt://127.0.0.1:19001" in args
    assert "latency" not in " ".join(args)
    assert args[-3:] == ["-f", "mpegts", str(tmp_path / "receiver.ts")]


def test_build_virtual_headend_receiver_args_rejects_secret_bearing_url(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must not include secrets"):
        build_virtual_headend_receiver_args(
            input_url="srt://user:password@127.0.0.1:19001",
            output_path=tmp_path / "receiver.ts",
        )


def test_run_virtual_headend_receiver_capture_fails_closed_when_output_missing(
    tmp_path: Path,
) -> None:
    result = run_virtual_headend_receiver_capture(
        input_url=str(tmp_path / "sender.ts"),
        output_path=tmp_path / "receiver.ts",
        ffmpeg_runner=lambda _args: ffmpeg_success(),
    )

    assert result.status == "FAIL"
    assert result.blocker == "VIRTUAL_HEADEND_RECEIVER_OUTPUT_MISSING"


def test_run_virtual_headend_receiver_capture_passes_when_artifact_exists(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "receiver.ts"

    def runner(_args: list[str]):
        output_path.write_bytes(b"transport")
        return ffmpeg_success()

    result = run_virtual_headend_receiver_capture(
        input_url=str(tmp_path / "sender.ts"),
        output_path=output_path,
        ffmpeg_runner=runner,
    )

    assert result.status == "PASS"
    assert result.blocker is None
    assert output_path.exists()


def test_samples_from_receiver_probe_use_output_pts_and_marker_reader() -> None:
    samples = samples_from_receiver_probe(
        probe_json=_probe_json(),
        expected_timeline=_timeline(),
        marker_reader=expected_marker_reader,
    )

    assert [sample.pts_seconds for sample in samples] == [0.0, 1.0, 2.0, 3.0]
    assert [sample.marker for sample in samples] == [
        "SEGMENT 001",
        "SEGMENT 001",
        "SEGMENT 002",
        "SEGMENT 002",
    ]
    assert all(sample.profile_id == "640x360-30fps-h264-aac-48000hz" for sample in samples)


def test_analyze_receiver_artifact_passes_clean_output_timeline(tmp_path: Path) -> None:
    report = analyze_receiver_artifact(
        received_path=tmp_path / "receiver.ts",
        expected_timeline=_timeline(),
        marker_reader=expected_marker_reader,
        ffprobe_runner=lambda _args: json.dumps(_probe_json()),
    )

    assert report.status == "PASS"
    assert report.findings == ()


def test_analyze_receiver_artifact_rejects_output_pts_discontinuity(tmp_path: Path) -> None:
    report = analyze_receiver_artifact(
        received_path=tmp_path / "receiver.ts",
        expected_timeline=_timeline(),
        marker_reader=expected_marker_reader,
        ffprobe_runner=lambda _args: json.dumps(_probe_json(pts=(0.0, 1.0, 0.5))),
    )

    assert report.status == "FAIL"
    assert "OUTPUT_PTS_DISCONTINUITY" in {finding.code for finding in report.findings}


def test_analyze_receiver_artifact_rejects_output_gap(tmp_path: Path) -> None:
    report = analyze_receiver_artifact(
        received_path=tmp_path / "receiver.ts",
        expected_timeline=_timeline(),
        marker_reader=expected_marker_reader,
        ffprobe_runner=lambda _args: json.dumps(_probe_json(pts=(0.0, 1.0, 3.0))),
        max_output_gap_seconds=1.25,
    )

    assert report.status == "FAIL"
    assert "CONNECTION_DROP_OR_DEAD_AIR" in {finding.code for finding in report.findings}


def test_audio_tone_marker_reader_extracts_markers_from_received_audio(tmp_path: Path) -> None:
    def runner(args: list[str]):
        _write_marker_wav(Path(args[-1]), tones=(660, 700), sample_rate_hz=8000)
        return ffmpeg_success()

    reader = build_audio_tone_marker_reader(
        received_path=tmp_path / "receiver.ts",
        marker_tones_hz=(("SEGMENT 001", 660), ("SEGMENT 002", 700)),
        ffmpeg_runner=runner,
        sample_rate_hz=8000,
        window_seconds=0.5,
    )

    samples = samples_from_receiver_probe(
        probe_json=_probe_json(pts=(0.0, 1.0, 2.0, 3.0)),
        expected_timeline=_timeline(),
        marker_reader=reader,
    )

    assert [sample.marker for sample in samples] == [
        "SEGMENT 001",
        "SEGMENT 001",
        "SEGMENT 002",
        "SEGMENT 002",
    ]


def test_audio_tone_marker_reader_does_not_read_across_expected_boundary(
    tmp_path: Path,
) -> None:
    def runner(args: list[str]):
        _write_marker_wav(Path(args[-1]), tones=(660, 700), sample_rate_hz=8000)
        return ffmpeg_success()

    reader = build_audio_tone_marker_reader(
        received_path=tmp_path / "receiver.ts",
        marker_tones_hz=(("SEGMENT 001", 660), ("SEGMENT 002", 700)),
        ffmpeg_runner=runner,
        sample_rate_hz=8000,
        window_seconds=0.6,
    )

    samples = samples_from_receiver_probe(
        probe_json=_probe_json(pts=(0.0, 1.8, 2.0)),
        expected_timeline=_timeline(),
        marker_reader=reader,
    )

    assert [sample.marker for sample in samples] == [
        "SEGMENT 001",
        "SEGMENT 001",
        "SEGMENT 002",
    ]


def test_profile_id_from_canonical_profile_matches_ffprobe_observation_contract() -> None:
    from civiccast.egress.models import CanonicalProfile

    assert (
        profile_id_from_canonical_profile(
            CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200)
        )
        == "640x360-30fps-h264-aac-48000hz"
    )


def _write_marker_wav(
    path: Path,
    *,
    tones: tuple[int, ...],
    sample_rate_hz: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples: list[int] = []
    for tone_hz in tones:
        for index in range(sample_rate_hz * 2):
            value = math.sin(2.0 * math.pi * tone_hz * index / sample_rate_hz)
            samples.append(int(value * 24000))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
