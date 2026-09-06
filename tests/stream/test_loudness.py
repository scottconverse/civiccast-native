# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 ITU-R BS.1770 / EBU R128 loudness compliance."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path


class TestLoudnessComplianceRealFfmpeg:
    def test_loudness_gate_uses_ffmpeg_wrapper_and_reports_minus_16_lufs(
        self,
        tmp_path: Path,
    ) -> None:
        loudness_module = import_module("civiccast.stream.loudness")

        result = loudness_module.check_streaming_loudness(
            media_path=tmp_path / "meeting.wav",
            target_lufs=-16.0,
            tolerance_lufs=1.0,
        )

        assert result.standard == "ITU-R BS.1770 / EBU R128"
        assert result.target_lufs == -16.0
        assert result.used_ffmpeg_wrapper is True
        assert result.status in {"ok", "failed"}
        assert result.status != "failed" or result.operator_action

    def test_loudness_gate_parses_integrated_lufs_from_ffmpeg(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        loudness_module = import_module("civiccast.stream.loudness")

        media = tmp_path / "meeting.wav"
        media.write_bytes(b"RIFFplaceholder")

        monkeypatch.setattr(loudness_module, "check_ffmpeg", lambda: ("7.0", True))
        monkeypatch.setattr(
            loudness_module,
            "run_ffmpeg",
            lambda _args: type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "Integrated loudness:\n    I:         -16.2 LUFS\n",
                },
            )(),
        )

        result = loudness_module.check_streaming_loudness(
            media_path=media,
            target_lufs=-16.0,
            tolerance_lufs=1.0,
        )

        assert result.status == "ok"
        assert result.measured_lufs == -16.2

    def test_loudness_probe_decodes_audio_only(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        """Item 66 follow-up (measured on HALO): an ebur128 pass on a 39-minute
        clip took 46.7s -- it decodes video too, since nothing told ffmpeg not
        to. ``-vn`` drops the video stream from the loudness probe entirely;
        it never changes the LUFS measurement (video frames never feed
        ebur128)."""
        loudness_module = import_module("civiccast.stream.loudness")

        media = tmp_path / "meeting.wav"
        media.write_bytes(b"RIFFplaceholder")

        captured: dict[str, list[str]] = {}

        def _fake_run_ffmpeg(args: list[str]):
            captured["args"] = args
            return type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "Integrated loudness:\n    I:         -16.2 LUFS\n",
                },
            )()

        monkeypatch.setattr(loudness_module, "check_ffmpeg", lambda: ("7.0", True))
        monkeypatch.setattr(loudness_module, "run_ffmpeg", _fake_run_ffmpeg)

        loudness_module.check_streaming_loudness(
            media_path=media,
            target_lufs=-16.0,
            tolerance_lufs=1.0,
        )

        assert "-vn" in captured["args"]


class TestCheckLoudnessGeneralized:
    """S11b: check_loudness parameterises the standard label + target so cable
    (ATSC A/85 -24 LKFS) and streaming (-16 LUFS) report their own regime."""

    def test_custom_standard_label_and_target_drive_the_report(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        loudness_module = import_module("civiccast.stream.loudness")
        media = tmp_path / "show.wav"
        media.write_bytes(b"RIFFplaceholder")

        monkeypatch.setattr(loudness_module, "check_ffmpeg", lambda: ("7.0", True))
        monkeypatch.setattr(
            loudness_module,
            "run_ffmpeg",
            lambda _args: type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "Integrated loudness:\n    I:         -10.0 LUFS\n",
                },
            )(),
        )

        result = loudness_module.check_loudness(
            media_path=media,
            target_lufs=-24.0,
            tolerance_lufs=2.0,
            standard_label="ATSC A/85 -24 LKFS (CALM Act)",
        )

        # -10 LUFS is well outside the -24 target tolerance.
        assert result.status == "failed"
        assert result.standard == "ATSC A/85 -24 LKFS (CALM Act)"
        assert result.target_lufs == -24.0
        # The remediation names the actual target (no hardcoded -16 / "stream").
        assert "-24 LUFS" in result.operator_action
        assert "stream" not in result.operator_action.lower()
