# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.stream.packager — VOD packager logic.

Unit tests mock ffmpeg calls. Integration tests (marked @pytest.mark.integration)
require ffmpeg installed and a real test video; those run in CI with ffmpeg
available and are skipped otherwise.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from civiccast.stream._ffmpeg import FfmpegNotFoundError
from civiccast.stream.packager import (
    PackagingError,
    SlateOnlyResult,
    VodPackageResult,
    _encode_rendition,
    pack_slate_fallback,
    pack_vod_asset,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_slate(output_dir: Path) -> Path:
    """Create a minimal slate playlist on disk without invoking ffmpeg."""
    slate_dir = output_dir / "slate"
    slate_dir.mkdir(parents=True, exist_ok=True)
    playlist = slate_dir / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:2.0,\nseg000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    # Create a stub segment so "playlist exists" checks pass.
    (slate_dir / "seg000.ts").write_bytes(b"\x00" * 16)
    return playlist


def _make_stub_rendition_playlist(output_dir: Path, name: str) -> Path:
    """Create a minimal variant playlist on disk without invoking ffmpeg."""
    rend_dir = output_dir / name
    rend_dir.mkdir(parents=True, exist_ok=True)
    playlist = rend_dir / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:2.0,\nseg000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    (rend_dir / "seg000.ts").write_bytes(b"\x00" * 16)
    return playlist


# ---------------------------------------------------------------------------
# PackagingError
# ---------------------------------------------------------------------------


class TestPackagingError:
    def test_carries_rendition_name(self) -> None:
        err = PackagingError("failed", rendition="720p", ffmpeg_stderr="err")
        assert err.rendition == "720p"
        assert err.ffmpeg_stderr == "err"
        assert "failed" in str(err)

    def test_optional_fields_default_to_none(self) -> None:
        err = PackagingError("oops")
        assert err.rendition is None
        assert err.ffmpeg_stderr is None


# ---------------------------------------------------------------------------
# pack_vod_asset — unit tests (mocked ffmpeg)
# ---------------------------------------------------------------------------


class TestPackVodAssetUnit:
    def _mock_successful_pack(self, tmp_path: Path, input_file: Path) -> VodPackageResult:
        """Simulate a successful pack by creating stub outputs before the packager checks."""

        def fake_generate_slate(output_dir: Path) -> Path:
            return _make_stub_slate(output_dir)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            from civiccast.stream.config import RenditionConfig

            assert isinstance(config, RenditionConfig)
            return _make_stub_rendition_playlist(output_dir, config.name)

        with (
            patch("civiccast.stream.packager.generate_slate", side_effect=fake_generate_slate),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
        ):
            return pack_vod_asset(input_file, tmp_path / "output")

    def test_raises_file_not_found_for_missing_input(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            pack_vod_asset(tmp_path / "nonexistent.mp4", tmp_path / "out")

    def test_raises_value_error_for_directory_input(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a file"):
            pack_vod_asset(tmp_path, tmp_path / "out")

    def test_returns_vod_package_result_on_success(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        result = self._mock_successful_pack(tmp_path, input_file)
        assert isinstance(result, VodPackageResult)

    def test_manifest_is_written_to_output_dir(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        result = self._mock_successful_pack(tmp_path, input_file)
        assert result.manifest_path.exists()
        assert result.manifest_path.name == "playlist.m3u8"

    def test_result_has_five_renditions(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        result = self._mock_successful_pack(tmp_path, input_file)
        assert len(result.renditions) == 5  # 4 content + slate

    def test_slate_is_last_rendition(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        result = self._mock_successful_pack(tmp_path, input_file)
        assert result.slate.config.name == "slate"
        assert result.renditions[-1].config.name == "slate"

    def test_manifest_contains_all_five_variants(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        result = self._mock_successful_pack(tmp_path, input_file)
        manifest_text = result.manifest_path.read_text(encoding="utf-8")
        assert manifest_text.count("#EXT-X-STREAM-INF:") == 5

    def test_slate_always_generated_before_content(self, tmp_path: Path) -> None:
        """Slate generation happens first — must not be blocked by content failure."""
        call_order: list[str] = []
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)

        def fake_generate_slate(output_dir: Path) -> Path:
            call_order.append("slate")
            return _make_stub_slate(output_dir)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            from civiccast.stream.config import RenditionConfig

            assert isinstance(config, RenditionConfig)
            call_order.append(f"encode:{config.name}")
            return _make_stub_rendition_playlist(output_dir, config.name)

        with (
            patch("civiccast.stream.packager.generate_slate", side_effect=fake_generate_slate),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
        ):
            pack_vod_asset(input_file, tmp_path / "output")

        assert call_order[0] == "slate"

    def test_propagates_ffmpeg_not_found(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)

        def fake_generate_slate(output_dir: Path) -> Path:
            return _make_stub_slate(output_dir)

        with (
            patch("civiccast.stream.packager.generate_slate", side_effect=fake_generate_slate),
            patch(
                "civiccast.stream.packager._encode_rendition",
                side_effect=FfmpegNotFoundError("no ffmpeg"),
            ),
            pytest.raises(FfmpegNotFoundError),
        ):
            pack_vod_asset(input_file, tmp_path / "output")

    def test_fractional_trim_window_passes_to_every_content_rendition(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        calls: list[dict[str, object]] = []

        def fake_generate_slate(output_dir: Path) -> Path:
            return _make_stub_slate(output_dir)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            from civiccast.stream.config import RenditionConfig

            assert isinstance(config, RenditionConfig)
            calls.append(kwargs)
            return _make_stub_rendition_playlist(output_dir, config.name)

        with (
            patch("civiccast.stream.packager.generate_slate", side_effect=fake_generate_slate),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
        ):
            pack_vod_asset(
                input_file,
                tmp_path / "output",
                trim_in_seconds=0.333,
                trim_out_seconds=1.5,
            )

        assert len(calls) == 4
        assert all(c["trim_in_seconds"] == 0.333 for c in calls)
        assert all(c["trim_out_seconds"] == 1.5 for c in calls)


class TestEncodeRenditionUnit:
    def test_fractional_trim_becomes_ffmpeg_seek_and_duration(self, tmp_path: Path) -> None:
        from civiccast.stream._ffmpeg import FfmpegResult
        from civiccast.stream.config import ABR_LADDER

        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)
        captured_args: list[str] = []

        def fake_run_ffmpeg(args: list[str], **kwargs: object) -> FfmpegResult:
            captured_args.extend(args)
            playlist = tmp_path / "out" / "240p" / "playlist.m3u8"
            playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
            return FfmpegResult(returncode=0, stdout="", stderr="")

        with patch("civiccast.stream.packager.run_ffmpeg", side_effect=fake_run_ffmpeg):
            _encode_rendition(
                input_file,
                tmp_path / "out",
                ABR_LADDER[-1],
                trim_in_seconds=0.333,
                trim_out_seconds=1.5,
            )

        assert captured_args[0:4] == ["-ss", "0.333", "-i", str(input_file)]
        assert "-t" in captured_args
        assert captured_args[captured_args.index("-t") + 1] == "1.167"


# ---------------------------------------------------------------------------
# pack_slate_fallback — unit tests
# ---------------------------------------------------------------------------


class TestPackSlateFallback:
    def test_returns_slate_only_result(self, tmp_path: Path) -> None:
        with patch(
            "civiccast.stream.packager.generate_slate",
            side_effect=lambda d: _make_stub_slate(d),
        ):
            result = pack_slate_fallback(tmp_path / "output")
        assert isinstance(result, SlateOnlyResult)

    def test_manifest_has_single_variant(self, tmp_path: Path) -> None:
        with patch(
            "civiccast.stream.packager.generate_slate",
            side_effect=lambda d: _make_stub_slate(d),
        ):
            result = pack_slate_fallback(tmp_path / "output")
        manifest_text = result.manifest_path.read_text(encoding="utf-8")
        assert manifest_text.count("#EXT-X-STREAM-INF:") == 1

    def test_does_not_regenerate_existing_slate(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        _make_stub_slate(output_dir)  # pre-existing slate

        generate_calls: list[int] = []

        def counting_generate(d: Path) -> Path:
            generate_calls.append(1)
            return _make_stub_slate(d)

        with patch("civiccast.stream.packager.generate_slate", side_effect=counting_generate):
            pack_slate_fallback(output_dir)

        assert generate_calls == []  # slate already existed — no regeneration

    def test_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "new_output"
        assert not output_dir.exists()

        with patch(
            "civiccast.stream.packager.generate_slate",
            side_effect=lambda d: _make_stub_slate(d),
        ):
            pack_slate_fallback(output_dir)

        assert output_dir.exists()
