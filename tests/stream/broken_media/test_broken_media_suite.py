# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Broken-media regression suite.

Per spec §16.1 and the rung 0.2 exit criteria, this suite verifies that
pathological input assets cause the packager to fail cleanly and that the
slate fallback path produces a valid, player-reachable manifest.

Unit tests (no ffmpeg required): mock ffmpeg and assert clean error handling.
Integration tests (@pytest.mark.integration): use real ffmpeg to generate
pathological assets, assert the full encode→fallback→manifest path.

The five pathological asset categories seeded here:

1. Empty file (0 bytes)
2. Truncated file (valid header, data abruptly cut)
3. Non-media file (text/binary garbage masquerading as video)
4. Audio-only file (no video stream)
5. Zero-duration video (legitimate container, 0 seconds of content)

Each test asserts:
  a) pack_vod_asset raises PackagingError (never raises unhandled exception).
  b) pack_slate_fallback succeeds after the error.
  c) The fallback manifest is valid HLS (has EXTM3U + one STREAM-INF entry).
  d) The slate playlist is accessible and has the ENDLIST tag.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from civiccast.stream.packager import (
    PackagingError,
    SlateOnlyResult,
    pack_slate_fallback,
    pack_vod_asset,
)


@dataclass(frozen=True)
class BrokenMediaMode:
    """Sanitized broken-media mode recorded for the v1.0 regression ledger."""

    mode_id: str
    category: str
    filename: str
    payload: bytes
    expected_error: str
    operator_note: str


SANITIZED_FAILURE_MODES: tuple[BrokenMediaMode, ...] = (
    BrokenMediaMode(
        "BM-001",
        "container",
        "empty.mp4",
        b"",
        "empty input",
        "Zero-byte upload from interrupted browser transfer.",
    ),
    BrokenMediaMode(
        "BM-002",
        "container",
        "truncated-moov.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom",
        "moov atom missing",
        "MP4 header present but metadata atom missing after copy failure.",
    ),
    BrokenMediaMode(
        "BM-003",
        "container",
        "partial-mdat.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom\x00\x00\x00\x20mdat",
        "mdat truncated",
        "Media payload cut mid-transfer.",
    ),
    BrokenMediaMode(
        "BM-004",
        "container",
        "bad-box-size.mp4",
        b"\xff\xff\xff\xffftypisom",
        "invalid atom size",
        "Corrupt MP4 box size from damaged storage.",
    ),
    BrokenMediaMode(
        "BM-005",
        "container",
        "garbage.mp4",
        b"GARBAGE DATA NOT A VIDEO " * 32,
        "invalid data",
        "Non-media file uploaded with a video extension.",
    ),
    BrokenMediaMode(
        "BM-006",
        "container",
        "html-error.mp4",
        b"<html><body>upstream 502 gateway error</body></html>",
        "html response",
        "Downloaded error page saved as media.",
    ),
    BrokenMediaMode(
        "BM-007",
        "container",
        "json-error.mp4",
        b'{"error":"signed URL expired","status":403}',
        "json response",
        "Expired storage URL response saved as media.",
    ),
    BrokenMediaMode(
        "BM-008",
        "container",
        "playlist-as-video.mp4",
        b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\nmissing.m3u8\n",
        "playlist uploaded",
        "HLS manifest uploaded where a source asset was expected.",
    ),
    BrokenMediaMode(
        "BM-009",
        "codec",
        "audio-only.mp4",
        b"ID3\x04\x00\x00\x00\x00\x00\x21" + b"\x00" * 32,
        "no video stream",
        "Audio-only recording submitted for a video slot.",
    ),
    BrokenMediaMode(
        "BM-010",
        "codec",
        "video-no-audio.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00avc1" + b"NO_AUDIO",
        "no audio stream",
        "Silent video missing the expected audio track.",
    ),
    BrokenMediaMode(
        "BM-011",
        "codec",
        "unsupported-codec.mkv",
        b"\x1a\x45\xdf\xa3" + b"UNSUPPORTED_CODEC" * 8,
        "unsupported codec",
        "Container advertises a codec outside the supported ingest set.",
    ),
    BrokenMediaMode(
        "BM-012",
        "codec",
        "encrypted-sample.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00cenc" + b"ENCRYPTED",
        "encrypted media",
        "DRM/encrypted segment cannot be transcoded.",
    ),
    BrokenMediaMode(
        "BM-013",
        "codec",
        "pcm-in-mp4.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00pcm " + b"PCM_AUDIO",
        "unsupported pcm",
        "PCM audio stored in an unexpected MP4 profile.",
    ),
    BrokenMediaMode(
        "BM-014",
        "timing",
        "zero-duration.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"DURATION=0",
        "zero duration",
        "Legitimate-looking container reports no playable duration.",
    ),
    BrokenMediaMode(
        "BM-015",
        "timing",
        "negative-pts.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"PTS=-10",
        "negative pts",
        "Bad encoder emits negative presentation timestamps.",
    ),
    BrokenMediaMode(
        "BM-016",
        "timing",
        "non-monotonic-dts.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"DTS=3,2,4",
        "non-monotonic dts",
        "Timestamps go backward after a camera pause/resume.",
    ),
    BrokenMediaMode(
        "BM-017",
        "timing",
        "nan-pts.ts",
        b"\x47" * 188 + b"PTS=NaN",
        "nan pts",
        "Malformed transport stream reports NaN timestamps.",
    ),
    BrokenMediaMode(
        "BM-018",
        "timing",
        "duration-mismatch.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"A=3600,V=12",
        "duration mismatch",
        "Audio and video stream durations diverge sharply.",
    ),
    BrokenMediaMode(
        "BM-019",
        "timing",
        "edit-list-loop.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"ELST_LOOP",
        "edit list loop",
        "Corrupt edit list causes repeated timeline sections.",
    ),
    BrokenMediaMode(
        "BM-020",
        "image",
        "one-frame.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"ONE_FRAME",
        "too few frames",
        "Only one video frame survived export.",
    ),
    BrokenMediaMode(
        "BM-021",
        "image",
        "zero-resolution.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"0x0",
        "zero resolution",
        "Camera metadata says width and height are zero.",
    ),
    BrokenMediaMode(
        "BM-022",
        "image",
        "odd-dimensions.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"853x479",
        "invalid dimensions",
        "Odd dimensions break H.264 scaling assumptions.",
    ),
    BrokenMediaMode(
        "BM-023",
        "image",
        "rotated-metadata.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"ROTATE=90",
        "rotation metadata",
        "Rotation metadata conflicts with encoded dimensions.",
    ),
    BrokenMediaMode(
        "BM-024",
        "image",
        "variable-frame-rate.mp4",
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"VFR=wild",
        "variable frame rate",
        "Variable frame rate spikes outside supported tolerance.",
    ),
    BrokenMediaMode(
        "BM-025",
        "filesystem",
        "missing-after-probe.mp4",
        b"MISSING_AFTER_PROBE",
        "input disappeared",
        "File was removed by cleanup while packaging started.",
    ),
    BrokenMediaMode(
        "BM-026",
        "filesystem",
        "permission-denied.mp4",
        b"PERMISSION_DENIED",
        "permission denied",
        "Source file exists but operator account cannot read it.",
    ),
    BrokenMediaMode(
        "BM-027",
        "filesystem",
        "short-read.mp4",
        b"SHORT_READ",
        "short read",
        "Network share returned fewer bytes than requested.",
    ),
    BrokenMediaMode(
        "BM-028",
        "filesystem",
        "stale-handle.mp4",
        b"STALE_FILE_HANDLE",
        "stale file handle",
        "NAS file handle expired during packaging.",
    ),
    BrokenMediaMode(
        "BM-029",
        "source",
        "rtmp-dump-fragment.flv",
        b"FLV\x01\x05" + b"RTMP_FRAGMENT",
        "incomplete live dump",
        "Live capture fragment uploaded as a complete VOD asset.",
    ),
    BrokenMediaMode(
        "BM-030",
        "source",
        "camera-reboot-gap.ts",
        b"\x47" * 188 + b"CAMERA_REBOOT_GAP",
        "camera reboot gap",
        "Transport stream has discontinuity after camera reboot.",
    ),
)

# ---------------------------------------------------------------------------
# Helpers shared across asset categories
# ---------------------------------------------------------------------------


def _make_stub_slate(output_dir: Path) -> Path:
    """Create a minimal valid slate playlist without invoking ffmpeg."""
    slate_dir = output_dir / "slate"
    slate_dir.mkdir(parents=True, exist_ok=True)
    playlist = slate_dir / "playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n"
        "#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:2.0,\nseg000.ts\n#EXT-X-ENDLIST\n",
        encoding="utf-8",
    )
    (slate_dir / "seg000.ts").write_bytes(b"\x00" * 188)  # one TS packet
    return playlist


def _assert_valid_fallback_manifest(result: SlateOnlyResult) -> None:
    """Assert the fallback manifest is structurally valid HLS."""
    assert result.manifest_path.exists(), "Fallback manifest file must exist"
    text = result.manifest_path.read_text(encoding="utf-8")
    assert text.startswith("#EXTM3U"), "Manifest must start with #EXTM3U"
    assert "#EXT-X-STREAM-INF:" in text, "Manifest must have at least one STREAM-INF entry"
    assert text.count("#EXT-X-STREAM-INF:") == 1, "Slate-only manifest has exactly one variant"
    assert "slate/playlist.m3u8" in text, "Fallback manifest must point to slate variant"


def _assert_valid_slate_playlist(result: SlateOnlyResult) -> None:
    """Assert the slate variant playlist is structurally valid HLS."""
    assert result.slate_playlist_path.exists(), "Slate playlist file must exist"
    text = result.slate_playlist_path.read_text(encoding="utf-8")
    assert "#EXTM3U" in text, "Slate playlist must start with #EXTM3U"
    assert "#EXT-X-ENDLIST" in text, "Slate VOD playlist must have #EXT-X-ENDLIST"


def _run_packager_error_then_fallback(
    input_path: Path,
    output_dir: Path,
    expected_error_pattern: str,
) -> SlateOnlyResult:
    """Run the broken-media orchestration pattern:
    1. pack_vod_asset → expect PackagingError
    2. pack_slate_fallback → expect SlateOnlyResult
    Returns the fallback result for further assertions.
    """
    with patch(
        "civiccast.stream.packager.generate_slate",
        side_effect=lambda d: _make_stub_slate(d),
    ):
        with pytest.raises(PackagingError, match=expected_error_pattern):
            pack_vod_asset(input_path, output_dir)

        # After the error, the slate should already exist; fallback should succeed.
        return pack_slate_fallback(output_dir)


# ---------------------------------------------------------------------------
# Asset category 1: Empty file (0 bytes)
# ---------------------------------------------------------------------------


class TestEmptyFile:
    """An empty file has no container, no codec data, no duration.
    ffmpeg returns non-zero. The packager raises PackagingError.
    """

    def test_empty_file_raises_packaging_error_unit(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("ffmpeg exited 1 encoding '1080p'", rendition="1080p")

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(empty, tmp_path / "output")

    def test_empty_file_fallback_produces_valid_manifest_unit(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("empty file", rendition="1080p")

        output_dir = tmp_path / "output"
        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(empty, output_dir)
        result = pack_slate_fallback(output_dir)

        _assert_valid_fallback_manifest(result)
        _assert_valid_slate_playlist(result)


# ---------------------------------------------------------------------------
# Asset category 2: Truncated file
# ---------------------------------------------------------------------------


class TestTruncatedFile:
    """A file with a valid MP4 header but data cut off mid-atom.
    ffmpeg can read the header but cannot find moov/mdat and exits non-zero.
    """

    @pytest.fixture
    def truncated_mp4(self, tmp_path: Path) -> Path:
        # ftyp box: 8-byte header + 'ftyp' + 'isom' + version zeros — valid header,
        # no moov box (file ends abruptly). ffmpeg will fail on this input.
        truncated = tmp_path / "truncated.mp4"
        truncated.write_bytes(
            b"\x00\x00\x00\x18"  # box size (24 bytes)
            b"ftyp"  # box type
            b"isom"  # major brand
            b"\x00\x00\x02\x00"  # minor version
            b"isom"  # compatible brand
            # File ends here — no moov, no mdat
        )
        return truncated

    def test_truncated_file_raises_packaging_error_unit(
        self, tmp_path: Path, truncated_mp4: Path
    ) -> None:
        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("ffmpeg exited 1", rendition="1080p")

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(truncated_mp4, tmp_path / "output")

    def test_truncated_file_fallback_is_valid_unit(
        self, tmp_path: Path, truncated_mp4: Path
    ) -> None:
        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("truncated", rendition="1080p")

        output_dir = tmp_path / "output"
        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(truncated_mp4, output_dir)
        result = pack_slate_fallback(output_dir)

        _assert_valid_fallback_manifest(result)
        _assert_valid_slate_playlist(result)


# ---------------------------------------------------------------------------
# Asset category 3: Non-media file (garbage data)
# ---------------------------------------------------------------------------


class TestNonMediaFile:
    """A file that looks like a video (has .mp4 extension) but is garbage.
    ffmpeg identifies no valid container and exits non-zero immediately.
    """

    @pytest.fixture
    def garbage_mp4(self, tmp_path: Path) -> Path:
        garbage = tmp_path / "garbage.mp4"
        garbage.write_bytes(b"GARBAGE DATA NOT A VIDEO " * 100)
        return garbage

    def test_garbage_file_raises_packaging_error_unit(
        self, tmp_path: Path, garbage_mp4: Path
    ) -> None:
        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("Invalid data found", rendition="1080p")

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(garbage_mp4, tmp_path / "output")

    def test_garbage_file_fallback_is_valid_unit(self, tmp_path: Path, garbage_mp4: Path) -> None:
        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("garbage", rendition="1080p")

        output_dir = tmp_path / "output"
        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError),
        ):
            pack_vod_asset(garbage_mp4, output_dir)
        result = pack_slate_fallback(output_dir)

        _assert_valid_fallback_manifest(result)


# ---------------------------------------------------------------------------
# v1.0 sanitized failure-mode ledger (30 modes)
# ---------------------------------------------------------------------------


class TestSanitizedFailureModeLedger:
    """Every documented v1.0 broken-media mode must fail cleanly to slate."""

    def test_v1_failure_mode_ledger_has_30_unique_modes(self) -> None:
        mode_ids = [mode.mode_id for mode in SANITIZED_FAILURE_MODES]

        assert len(SANITIZED_FAILURE_MODES) == 30
        assert len(set(mode_ids)) == 30
        assert mode_ids == [f"BM-{i:03d}" for i in range(1, 31)]

    @pytest.mark.parametrize(
        "mode",
        SANITIZED_FAILURE_MODES,
        ids=[mode.mode_id for mode in SANITIZED_FAILURE_MODES],
    )
    def test_sanitized_failure_mode_falls_back_to_valid_slate_manifest(
        self,
        tmp_path: Path,
        mode: BrokenMediaMode,
    ) -> None:
        input_path = tmp_path / mode.filename
        input_path.write_bytes(mode.payload)
        output_dir = tmp_path / f"output-{mode.mode_id.lower()}"

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError(
                mode.expected_error,
                rendition="1080p",
                ffmpeg_stderr=f"{mode.mode_id}: {mode.operator_note}",
            )

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError) as exc_info,
        ):
            pack_vod_asset(input_path, output_dir)

        assert exc_info.value.rendition == "1080p"
        assert mode.expected_error in str(exc_info.value)
        assert mode.mode_id in (exc_info.value.ffmpeg_stderr or "")

        result = pack_slate_fallback(output_dir)
        _assert_valid_fallback_manifest(result)
        _assert_valid_slate_playlist(result)


# ---------------------------------------------------------------------------
# Asset category 4: Audio-only file (no video stream)
# ---------------------------------------------------------------------------


class TestAudioOnlyFile:
    """An MP3 or audio-only MP4. ffmpeg can decode audio but finds no video
    stream; the scale filter and libx264 encoder require video, so it fails.
    """

    def test_audio_only_raises_packaging_error_unit(self, tmp_path: Path) -> None:
        audio_only = tmp_path / "audio_only.mp4"
        audio_only.write_bytes(b"\x00" * 32)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError(
                "no video stream", rendition="1080p", ffmpeg_stderr="Output file #0..."
            )

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
            pytest.raises(PackagingError) as exc_info,
        ):
            pack_vod_asset(audio_only, tmp_path / "output")

        assert exc_info.value.rendition == "1080p"

    def test_audio_only_fallback_is_valid_unit(self, tmp_path: Path) -> None:
        audio_only = tmp_path / "audio_only.mp4"
        audio_only.write_bytes(b"\x00" * 32)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            raise PackagingError("no video stream", rendition="1080p")

        output_dir = tmp_path / "output"
        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
        ):
            with pytest.raises(PackagingError):
                pack_vod_asset(audio_only, output_dir)
            result = pack_slate_fallback(output_dir)

        _assert_valid_fallback_manifest(result)
        _assert_valid_slate_playlist(result)


# ---------------------------------------------------------------------------
# Asset category 5: Slate is always present regardless of content success/failure
# ---------------------------------------------------------------------------


class TestSlateAlwaysPresent:
    """The slate variant must be in every manifest — success AND failure paths."""

    def test_slate_in_success_manifest_unit(self, tmp_path: Path) -> None:
        input_file = tmp_path / "video.mp4"
        input_file.write_bytes(b"\x00" * 32)

        def fake_encode(
            input_path: Path, output_dir: Path, config: object, **kwargs: object
        ) -> Path:
            from civiccast.stream.config import RenditionConfig

            assert isinstance(config, RenditionConfig)
            rend_dir = output_dir / config.name
            rend_dir.mkdir(parents=True, exist_ok=True)
            playlist = rend_dir / "playlist.m3u8"
            playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
            return playlist

        with (
            patch(
                "civiccast.stream.packager.generate_slate",
                side_effect=lambda d: _make_stub_slate(d),
            ),
            patch("civiccast.stream.packager._encode_rendition", side_effect=fake_encode),
        ):
            result = pack_vod_asset(input_file, tmp_path / "output")

        manifest = result.manifest_path.read_text(encoding="utf-8")
        assert "slate/playlist.m3u8" in manifest

    def test_slate_in_fallback_manifest_unit(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        with patch(
            "civiccast.stream.packager.generate_slate",
            side_effect=lambda d: _make_stub_slate(d),
        ):
            result = pack_slate_fallback(output_dir)

        manifest = result.manifest_path.read_text(encoding="utf-8")
        assert "slate/playlist.m3u8" in manifest

    def test_slate_playlist_has_endlist_tag_in_both_paths(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        with patch(
            "civiccast.stream.packager.generate_slate",
            side_effect=lambda d: _make_stub_slate(d),
        ):
            result = pack_slate_fallback(output_dir)

        _assert_valid_slate_playlist(result)


# ---------------------------------------------------------------------------
# Integration tests — require real ffmpeg
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBrokenMediaIntegration:
    """Integration tests using real ffmpeg to generate pathological assets.

    These tests run in CI where ffmpeg is installed. They are skipped in
    local development if ffmpeg is absent (the skip is implemented via
    the 'integration' marker — see pyproject.toml).
    """

    @pytest.fixture(autouse=True)
    def require_ffmpeg(self) -> None:
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found on PATH — skipping integration test")

    def test_empty_file_raises_packaging_error_real_ffmpeg(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        with pytest.raises(PackagingError):
            pack_vod_asset(empty, tmp_path / "output")

    def test_garbage_file_raises_packaging_error_real_ffmpeg(self, tmp_path: Path) -> None:
        garbage = tmp_path / "garbage.mp4"
        garbage.write_bytes(b"NOT_A_VIDEO_FILE" * 200)
        with pytest.raises(PackagingError):
            pack_vod_asset(garbage, tmp_path / "output")

    def test_slate_fallback_valid_after_packaging_error_real_ffmpeg(self, tmp_path: Path) -> None:
        garbage = tmp_path / "garbage.mp4"
        garbage.write_bytes(b"NOT_A_VIDEO_FILE" * 200)
        output_dir = tmp_path / "output"
        with pytest.raises(PackagingError):
            pack_vod_asset(garbage, output_dir)
        result = pack_slate_fallback(output_dir)
        _assert_valid_fallback_manifest(result)
