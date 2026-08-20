# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""NDI output planning contracts for cable workflows."""

from __future__ import annotations

import pytest

from civiccast.cable.ndi import (
    NdiOutputError,
    build_ndi_output_plan,
    check_ndi_runtime,
    detect_ndi_runtime,
    detect_ndi_sdk,
    detect_ndi_sender,
)
from civiccast.stream._ffmpeg import FfmpegNotFoundError, FfmpegResult


def test_build_ndi_output_plan_uses_realtime_file_to_ndi_args(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    media.write_bytes(b"mp4 bytes")

    plan = build_ndi_output_plan(
        source_media=media,
        ndi_name="  CivicCast   Council Room  ",
        muxer="libndi_newtek",
    )

    assert plan.status == "planned"
    assert plan.ndi_name == "CivicCast Council Room"
    assert plan.proof_boundary == "command-plan-and-runtime-readiness"
    assert plan.ffmpeg_args == [
        "-re",
        "-i",
        str(media),
        "-vf",
        "scale=1920x1080,fps=30000/1001",
        "-pix_fmt",
        "uyvy422",
        "-f",
        "libndi_newtek",
        "CivicCast Council Room",
    ]
    assert "receiver proof" in plan.next_step


def test_build_ndi_output_plan_fails_actionably_when_media_missing(tmp_path) -> None:
    with pytest.raises(NdiOutputError, match="source media is missing"):
        build_ndi_output_plan(
            source_media=tmp_path / "missing.mp4",
            ndi_name="CivicCast Council Room",
        )


def test_build_ndi_output_plan_rejects_unsafe_channel_name(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    media.write_bytes(b"mp4 bytes")

    with pytest.raises(NdiOutputError, match="control characters"):
        build_ndi_output_plan(source_media=media, ndi_name="Council\nRoom")


def test_check_ndi_runtime_passes_when_ffmpeg_lists_ndi_muxer() -> None:
    def fake_runner(args: list[str]) -> FfmpegResult:
        assert args == ["-hide_banner", "-muxers"]
        return FfmpegResult(returncode=0, stdout=" E libndi_newtek NDI output\n", stderr="")

    result = check_ndi_runtime(ffmpeg_runner=fake_runner, ndi_sender_detector=lambda: None)

    assert result.status == "ok"
    assert result.supported_muxer == "libndi_newtek"
    assert result.ffmpeg_detected is True
    assert isinstance(result.ndi_runtime_detected, bool)
    assert isinstance(result.ndi_sdk_detected, bool)
    assert isinstance(result.ndi_sender_detected, bool)


def test_check_ndi_runtime_blocks_when_muxer_missing() -> None:
    def fake_runner(args: list[str]) -> FfmpegResult:
        return FfmpegResult(returncode=0, stdout=" E mp4 MP4 muxer with NDI notes\n", stderr="")

    result = check_ndi_runtime(ffmpeg_runner=fake_runner, ndi_sender_detector=lambda: None)

    assert result.status == "ndi_muxer_missing"
    assert result.supported_muxer is None
    assert result.ffmpeg_detected is True
    assert "NDI output support" in result.next_step


def test_check_ndi_runtime_accepts_local_sender_when_muxer_missing(tmp_path, monkeypatch) -> None:
    sender = tmp_path / "civiccast-ndi-ffmpeg-sender.exe"
    sender.write_bytes(b"sender")
    monkeypatch.setenv("CIVICCAST_NDI_SENDER", str(sender))

    def fake_runner(args: list[str]) -> FfmpegResult:
        return FfmpegResult(returncode=0, stdout=" E mp4 MP4 muxer with NDI notes\n", stderr="")

    result = check_ndi_runtime(ffmpeg_runner=fake_runner)

    assert result.status == "ndi_sender_ready"
    assert result.supported_muxer is None
    assert result.ndi_sender_detected is True
    assert result.ndi_sender_path == sender
    assert "not an FFmpeg muxer build" in result.next_step


def test_check_ndi_runtime_blocks_when_ffmpeg_missing() -> None:
    def fake_runner(args: list[str]) -> FfmpegResult:
        raise FfmpegNotFoundError("missing")

    result = check_ndi_runtime(ffmpeg_runner=fake_runner, ndi_sender_detector=lambda: None)

    assert result.status == "runtime_unavailable"
    assert result.supported_muxer is None
    assert result.ffmpeg_detected is False
    assert "Install FFmpeg" in result.next_step


def test_ndi_sdk_detection_requires_header_and_import_library(tmp_path, monkeypatch) -> None:
    sdk = tmp_path / "NDI SDK"
    include = sdk / "Include"
    lib = sdk / "Lib" / "x64"
    include.mkdir(parents=True)
    lib.mkdir(parents=True)
    (include / "Processing.NDI.Lib.h").write_text("/* sdk header */", encoding="utf-8")
    monkeypatch.setenv("NDI_SDK_DIR", str(sdk))

    assert detect_ndi_sdk() is False

    (lib / "Processing.NDI.Lib.x64.lib").write_bytes(b"import lib")

    assert detect_ndi_sdk() is True


def test_ndi_runtime_detection_finds_runtime_dll(tmp_path, monkeypatch) -> None:
    runtime = tmp_path / "Runtime"
    runtime.mkdir()
    (runtime / "Processing.NDI.Lib.x64.dll").write_bytes(b"runtime")
    monkeypatch.setenv("NDI_RUNTIME_DIR", str(tmp_path))

    assert detect_ndi_runtime() is True


def test_ndi_sender_detection_finds_explicit_sender(tmp_path, monkeypatch) -> None:
    sender = tmp_path / "sender.exe"
    sender.write_bytes(b"sender")
    monkeypatch.setenv("CIVICCAST_NDI_SENDER", str(sender))

    assert detect_ndi_sender() == sender
