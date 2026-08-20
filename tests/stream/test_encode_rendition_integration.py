# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-ffmpeg integration tests for civiccast.stream.packager._encode_rendition.

The mock-based unit tests in test_packager.py cover orchestration shape but
cannot detect ffmpeg argument-construction bugs (commit 94abe97 had to fix
three such bugs that mocks missed). This module runs _encode_rendition
against a synthetic lavfi source and asserts the encoded outputs are real.

Skipped when ffmpeg is not on PATH so CI without ffmpeg stays green.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from civiccast.stream._ffmpeg import resolve_h264_encoder
from civiccast.stream.config import ABR_LADDER
from civiccast.stream.packager import _encode_rendition

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not on PATH — skipping real-ffmpeg integration tests.",
)


@pytest.fixture
def tiny_mp4(tmp_path: Path) -> Path:
    """Generate a 1-second 320x240 MP4 with audio via ffmpeg lavfi.

    Tiny enough to encode quickly but real enough that all ffmpeg argument
    paths fire (codec selection, profile, pix_fmt, HLS muxer).
    """
    import subprocess

    sample = tmp_path / "tiny.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=15:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(sample),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not generate test sample: {result.stderr[-500:]}")
    return sample


class TestEncodeRenditionIntegration:
    def test_240p_encodes_to_real_hls_segments(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # 240p is the cheapest rendition — fast to encode, exercises every
        # output argument the packager produces (scale filter, profile,
        # bitrate, HLS muxer).
        config_240p = ABR_LADDER[-1]
        assert config_240p.name == "240p"

        output_dir = tmp_path / "out"
        playlist = _encode_rendition(tiny_mp4, output_dir, config_240p)

        assert playlist.exists(), "playlist file must be created"
        assert playlist.suffix == ".m3u8"
        assert playlist.read_text(encoding="utf-8").startswith("#EXTM3U")

        segments = list(playlist.parent.glob("*.ts"))
        assert len(segments) >= 1, "must produce at least one segment"
        assert all(s.stat().st_size > 0 for s in segments), "segments must be non-empty"

    def test_fractional_trim_encodes_short_synthetic_clip(
        self, tiny_mp4: Path, tmp_path: Path
    ) -> None:
        config_240p = ABR_LADDER[-1]
        playlist = _encode_rendition(
            tiny_mp4,
            tmp_path / "out",
            config_240p,
            trim_in_seconds=0.333,
            trim_out_seconds=0.9,
        )

        contents = playlist.read_text(encoding="utf-8")
        extinf_values = [
            float(line.removeprefix("#EXTINF:").rstrip(","))
            for line in contents.splitlines()
            if line.startswith("#EXTINF:")
        ]
        assert extinf_values, contents
        assert 0 < sum(extinf_values) <= 0.9

    def test_encoded_playlist_declares_endlist(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # VOD playlists must end with EXT-X-ENDLIST. Without this, players
        # treat the stream as live and never reach the slate-fallback path.
        config = ABR_LADDER[-1]
        playlist = _encode_rendition(tiny_mp4, tmp_path / "out", config)
        assert "#EXT-X-ENDLIST" in playlist.read_text(encoding="utf-8")

    def test_encoded_segments_have_pix_fmt_yuv420p(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # Browsers reject h264 yuv444p in <video>. Confirm the encoder
        # output is yuv420p (regression guard for the bug fixed in 94abe97).
        import subprocess

        config = ABR_LADDER[-1]
        playlist = _encode_rendition(tiny_mp4, tmp_path / "out", config)
        first_segment = sorted(playlist.parent.glob("*.ts"))[0]

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=pix_fmt",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(first_segment),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # MPEG-TS containers can report the video stream more than once; we
        # only care that EVERY pix_fmt seen is yuv420p.
        pix_fmts = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        assert pix_fmts, f"ffprobe returned no pix_fmt: {result.stdout!r}"
        assert all(p == "yuv420p" for p in pix_fmts), f"expected all-yuv420p, got {pix_fmts!r}"

    def test_encoded_segments_have_correct_profile(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # 240p is configured h264 baseline. Confirm the encoder honored it.
        # Regression guard for the slate -profile:v argument-ordering bug.
        import subprocess

        config = ABR_LADDER[-1]
        assert config.h264_profile == "baseline"
        playlist = _encode_rendition(tiny_mp4, tmp_path / "out", config)
        first_segment = sorted(playlist.parent.glob("*.ts"))[0]

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=profile",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(first_segment),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # ffprobe returns "Constrained Baseline" for libx264 baseline output.
        assert "baseline" in result.stdout.strip().lower()

    def test_encoded_segments_have_aac_audio(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # Closes the ``-c:a aac`` coverage gap. Mock-based tests pass any
        # argv shape; real ffprobe is the only way to confirm the audio
        # stream actually came out as AAC at the configured bitrate.
        import subprocess

        config = ABR_LADDER[-1]
        playlist = _encode_rendition(tiny_mp4, tmp_path / "out", config)
        first_segment = sorted(playlist.parent.glob("*.ts"))[0]

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(first_segment),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "aac" in result.stdout.strip().lower(), (
            f"expected AAC audio, got {result.stdout.strip()!r}"
        )

    def test_scale_filter_produces_target_dimensions(self, tiny_mp4: Path, tmp_path: Path) -> None:
        # 240p config asserts 426x240. The scale filter pads to exact size,
        # so even with a 320x240 source the output dimensions must match
        # the rendition target. Closes the ``-vf scale=...`` coverage gap.
        import subprocess

        config = ABR_LADDER[-1]
        playlist = _encode_rendition(tiny_mp4, tmp_path / "out", config)
        first_segment = sorted(playlist.parent.glob("*.ts"))[0]

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=,:p=0",
                str(first_segment),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        # MPEG-TS may report the video stream more than once; assert the
        # first reported pair matches the rendition config.
        first_pair = result.stdout.strip().splitlines()[0]
        width_str, height_str = first_pair.split(",")
        assert int(width_str) == config.width, f"width: expected {config.width}, got {width_str}"
        assert int(height_str) == config.height, (
            f"height: expected {config.height}, got {height_str}"
        )

    @pytest.mark.parametrize(
        "rendition_index",
        [0, 1, 2, 3],
        ids=["1080p", "720p", "480p", "240p"],
    )
    def test_every_rendition_in_ladder_produces_valid_hls(
        self, tiny_mp4: Path, tmp_path: Path, rendition_index: int
    ) -> None:
        # Closes the "240p-only argv coverage" gap. Each ABR rendition has
        # a different profile / bitrate / dimensions; a per-rendition argv
        # bug (e.g., main-vs-high profile mismatch on 720p) only surfaces
        # if every rendition is exercised end-to-end.
        config = ABR_LADDER[rendition_index]
        output_dir = tmp_path / "out" / config.name
        playlist = _encode_rendition(tiny_mp4, output_dir, config)

        assert playlist.exists()
        contents = playlist.read_text(encoding="utf-8")
        assert contents.startswith("#EXTM3U")
        assert "#EXT-X-ENDLIST" in contents

        segments = list(playlist.parent.glob("*.ts"))
        assert len(segments) >= 1
        assert all(s.stat().st_size > 0 for s in segments)
