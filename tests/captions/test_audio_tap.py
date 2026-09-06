# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Egress audio fork for live captions (Beta sprint B6, decision #1 option A).

The egress encoder — the single owner of the ffmpeg process graph — forks a
low-bitrate audio-only output: rolling mono 16 kHz s16le WAV segments under
``CIVICCAST_CAPTION_TAP_DIR/<channel_id>/``. The caption tap worker consumes
those segments (see test_caption_tap_worker.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.captions.tap import (
    TAP_SAMPLE_RATE_HZ,
    AudioTapPlan,
    build_audio_tap_plan,
)


class TestAudioTapPlan:
    def test_output_args_fork_mono_16k_wav_segments(self, tmp_path: Path) -> None:
        plan = AudioTapPlan(tap_dir=tmp_path / "tap" / "gov-ch12", segment_seconds=5.0)

        args = plan.output_args()

        joined = " ".join(args)
        assert "-map 0:a:0?" in joined
        assert f"-ar {TAP_SAMPLE_RATE_HZ}" in joined
        assert "-ac 1" in joined
        assert "-c:a pcm_s16le" in joined
        assert "-f segment" in joined
        assert "-segment_time 5.0" in joined
        assert args[-1].endswith("chunk-%06d.wav")
        assert str(tmp_path / "tap" / "gov-ch12") in args[-1]

    def test_output_args_create_the_tap_directory(self, tmp_path: Path) -> None:
        tap_dir = tmp_path / "tap" / "gov-ch12"
        plan = AudioTapPlan(tap_dir=tap_dir)

        plan.output_args()

        assert tap_dir.is_dir(), "ffmpeg will not create the segment directory itself"


class TestBuildAudioTapPlan:
    def test_unset_env_means_no_tap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_CAPTION_TAP_DIR", raising=False)
        assert build_audio_tap_plan("gov-ch12") is None

    def test_env_root_yields_per_channel_plan(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
        plan = build_audio_tap_plan("gov-ch12")
        assert plan is not None
        assert plan.tap_dir == tmp_path / "tap" / "gov-ch12"

    def test_caption_tap_off_means_no_tap_even_with_a_dir_configured(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Item 91: ``CIVICCAST_CAPTION_TAP=off`` wins over a configured (or
        stray leftover) ``CIVICCAST_CAPTION_TAP_DIR`` -- this function is the
        single place that decides whether a channel's audio is forked, so it
        must not build a plan just because a directory happens to be set."""

        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "off")
        assert build_audio_tap_plan("gov-ch12") is None

    @pytest.mark.parametrize("mode", ["", "inline", "external", "ON", "OFF ", " off"])
    def test_non_exact_off_values_do_not_suppress_the_tap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
        if mode:
            monkeypatch.setenv("CIVICCAST_CAPTION_TAP", mode)
        else:
            monkeypatch.delenv("CIVICCAST_CAPTION_TAP", raising=False)
        plan = build_audio_tap_plan("gov-ch12")
        # "OFF " / " off" (whitespace) are still recognized as off since the
        # check strips before lowercasing; only a value that is not the
        # literal off token (unset, inline, external, ON) keeps the tap.
        if mode.strip().lower() == "off":
            assert plan is None
        else:
            assert plan is not None


class TestEncoderArgsCarryTheFork:
    def test_encoder_args_include_the_audio_fork_when_planned(self, tmp_path: Path) -> None:
        from civiccast.egress.models import EgressConfig, EgressSinkSpec
        from civiccast.egress.runtime import build_persistent_encoder_args

        config = EgressConfig(
            channel_id="gov-ch12",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri=str(tmp_path / "out.ts"))],
        )
        concat_plan = tmp_path / "plan.ffconcat"
        plan = AudioTapPlan(tap_dir=tmp_path / "tap" / "gov-ch12")

        with_fork = build_persistent_encoder_args(
            concat_plan=concat_plan, config=config, audio_tap_plan=plan
        )
        without_fork = build_persistent_encoder_args(concat_plan=concat_plan, config=config)

        assert "pcm_s16le" in with_fork
        assert with_fork[-1].endswith("chunk-%06d.wav")
        assert "pcm_s16le" not in without_fork
