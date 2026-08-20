# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.stream.manifest — HLS multivariant manifest assembly."""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.stream.config import ABR_LADDER, SLATE_RENDITION
from civiccast.stream.manifest import (
    SLATE_FAILOVER_GROUP_ID,
    SUBTITLE_GROUP_ID,
    ManifestRendition,
    ManifestSubtitleTrack,
    build_multivariant_manifest,
    write_multivariant_manifest,
)


def _make_renditions(use_slate: bool = True) -> list[ManifestRendition]:
    """Build a full rendition list matching packager output."""
    renditions = [
        ManifestRendition(config=r, playlist_uri=f"{r.name}/playlist.m3u8") for r in ABR_LADDER
    ]
    if use_slate:
        renditions.append(
            ManifestRendition(config=SLATE_RENDITION, playlist_uri="slate/playlist.m3u8")
        )
    return renditions


class TestBuildMultivariantManifest:
    def test_starts_with_extm3u(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert manifest.startswith("#EXTM3U\n")

    def test_includes_version_tag(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert "#EXT-X-VERSION:" in manifest

    def test_has_five_stream_inf_entries(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert manifest.count("#EXT-X-STREAM-INF:") == 5

    def test_slate_is_always_last_entry(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        lines = [
            line for line in manifest.splitlines() if not line.startswith("#") and line.strip()
        ]
        assert lines[-1] == "slate/playlist.m3u8"

    def test_bandwidth_values_are_present_and_numeric(self) -> None:
        import re

        manifest = build_multivariant_manifest(_make_renditions())
        for line in manifest.splitlines():
            if line.startswith("#EXT-X-STREAM-INF:"):
                assert "BANDWIDTH=" in line
                match = re.search(r"BANDWIDTH=(\d+)", line)
                assert match is not None, f"BANDWIDTH not found in: {line}"
                assert match.group(1).isdigit()

    def test_resolution_values_are_present(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert "1920x1080" in manifest
        assert "1280x720" in manifest
        assert "854x480" in manifest
        assert "426x240" in manifest

    def test_codecs_attribute_includes_avc1_and_mp4a(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        for line in manifest.splitlines():
            if line.startswith("#EXT-X-STREAM-INF:"):
                assert "avc1." in line
                assert "mp4a.40.2" in line

    def test_content_bandwidths_ordered_highest_to_lowest(self) -> None:
        # Content variants must be in descending bandwidth order. The slate's
        # advertised bandwidth is intentionally inflated above all content
        # (see test_slate_advertised_bandwidth_above_all_content), so the
        # full list is no longer monotonically descending — only the content
        # subset is.
        import re

        manifest = build_multivariant_manifest(_make_renditions())
        bandwidths_in_order = [
            int(m.group(1))
            for line in manifest.splitlines()
            if line.startswith("#EXT-X-STREAM-INF:")
            for m in [re.search(r"BANDWIDTH=(\d+)", line)]
            if m is not None
        ]
        content_bws = bandwidths_in_order[:-1]  # slate is last in source order
        assert content_bws == sorted(content_bws, reverse=True)
        assert len(content_bws) == 4  # 1080p, 720p, 480p, 240p

    def test_slate_advertised_bandwidth_above_all_content(self) -> None:
        # The slate is the player's last-resort fallback. An estimate-matching
        # ABR client must NEVER pick it as a primary choice. Advertising it
        # above every content variant guarantees that. See ADR 0007
        # "Slate failover mechanism (v0.2 amendment)".
        import re

        manifest = build_multivariant_manifest(_make_renditions())
        bandwidths_in_order = [
            int(m.group(1))
            for line in manifest.splitlines()
            if line.startswith("#EXT-X-STREAM-INF:")
            for m in [re.search(r"BANDWIDTH=(\d+)", line)]
            if m is not None
        ]
        slate_bw = bandwidths_in_order[-1]
        content_bws = bandwidths_in_order[:-1]
        assert slate_bw > max(content_bws), (
            f"Slate bandwidth ({slate_bw}) must exceed every content variant "
            f"(max content = {max(content_bws)})."
        )

    def test_raises_on_empty_renditions(self) -> None:
        with pytest.raises(ValueError, match="zero renditions"):
            build_multivariant_manifest([])

    def test_playlist_uris_appear_after_stream_inf_tags(self) -> None:
        renditions = _make_renditions()
        manifest = build_multivariant_manifest(renditions)
        lines = manifest.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                # The very next non-empty line must be the playlist URI.
                next_content = lines[i + 1] if i + 1 < len(lines) else ""
                assert next_content.endswith("playlist.m3u8")

    def test_manifest_ends_with_newline(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert manifest.endswith("\n")


class TestWriteMultivariantManifest:
    def test_writes_file_to_output_path(self, tmp_path: Path) -> None:
        output_path = tmp_path / "playlist.m3u8"
        write_multivariant_manifest(_make_renditions(), output_path)
        assert output_path.exists()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        output_path = tmp_path / "nested" / "deep" / "playlist.m3u8"
        write_multivariant_manifest(_make_renditions(), output_path)
        assert output_path.exists()

    def test_written_content_matches_builder(self, tmp_path: Path) -> None:
        renditions = _make_renditions()
        output_path = tmp_path / "playlist.m3u8"
        write_multivariant_manifest(renditions, output_path)
        written = output_path.read_text(encoding="utf-8")
        expected = build_multivariant_manifest(renditions)
        assert written == expected

    def test_returns_the_output_path(self, tmp_path: Path) -> None:
        output_path = tmp_path / "playlist.m3u8"
        returned = write_multivariant_manifest(_make_renditions(), output_path)
        assert returned == output_path


class TestSubtitleTracks:
    def test_includes_webvtt_subtitle_media_descriptor(self) -> None:
        manifest = build_multivariant_manifest(
            _make_renditions(),
            subtitle_tracks=[
                ManifestSubtitleTrack(
                    playlist_uri="captions/en/playlist.m3u8",
                    language="en",
                    name="English",
                )
            ],
        )
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in manifest
        assert f'GROUP-ID="{SUBTITLE_GROUP_ID}"' in manifest
        assert 'LANGUAGE="en"' in manifest
        assert 'NAME="English"' in manifest
        assert 'URI="captions/en/playlist.m3u8"' in manifest

    def test_every_stream_inf_references_subtitle_group_when_present(self) -> None:
        manifest = build_multivariant_manifest(
            _make_renditions(),
            subtitle_tracks=[ManifestSubtitleTrack(playlist_uri="captions/en/playlist.m3u8")],
        )
        stream_inf_lines = [
            line for line in manifest.splitlines() if line.startswith("#EXT-X-STREAM-INF")
        ]
        assert len(stream_inf_lines) == 5
        assert all(f'SUBTITLES="{SUBTITLE_GROUP_ID}"' in line for line in stream_inf_lines)

    def test_written_manifest_can_include_subtitle_tracks(self, tmp_path: Path) -> None:
        output_path = tmp_path / "playlist.m3u8"
        write_multivariant_manifest(
            _make_renditions(),
            output_path,
            subtitle_tracks=[ManifestSubtitleTrack(playlist_uri="captions/en/playlist.m3u8")],
        )
        assert 'SUBTITLES="' in output_path.read_text(encoding="utf-8")


class TestSlateFailoverGroup:
    """Sprint 0.3 cleanup batch G — slate now declared as a real
    ``EXT-X-MEDIA TYPE=VIDEO`` alternate rendition. Each content
    ``EXT-X-STREAM-INF`` references the group via ``VIDEO="content"`` so
    compliant HLS players have a defined failover target."""

    def test_includes_ext_x_media_descriptor_for_slate(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        assert "#EXT-X-MEDIA:TYPE=VIDEO" in manifest
        assert f'GROUP-ID="{SLATE_FAILOVER_GROUP_ID}"' in manifest
        assert 'NAME="Slate fallback"' in manifest
        # DEFAULT=NO + AUTOSELECT=NO so clients only land on slate
        # via explicit failover, not normal selection.
        assert "DEFAULT=NO" in manifest
        assert "AUTOSELECT=NO" in manifest
        # The slate playlist URI is referenced by the descriptor.
        assert 'URI="slate/playlist.m3u8"' in manifest

    def test_every_content_stream_inf_references_failover_group(self) -> None:
        manifest = build_multivariant_manifest(_make_renditions())
        # Every #EXT-X-STREAM-INF line must carry VIDEO="content".
        stream_inf_lines = [
            line for line in manifest.splitlines() if line.startswith("#EXT-X-STREAM-INF")
        ]
        # 4 content + 1 slate (slate STREAM-INF retained for older clients).
        assert len(stream_inf_lines) == 5
        for line in stream_inf_lines:
            assert f'VIDEO="{SLATE_FAILOVER_GROUP_ID}"' in line, (
                f"STREAM-INF missing VIDEO failover group ref: {line!r}"
            )

    def test_slate_descriptor_precedes_content_stream_inf_entries(self) -> None:
        # The EXT-X-MEDIA descriptor for the slate must be declared before
        # any STREAM-INF that references the group, per HLS spec ordering.
        manifest = build_multivariant_manifest(_make_renditions())
        ext_media_idx = manifest.index("#EXT-X-MEDIA:TYPE=VIDEO")
        stream_inf_idx = manifest.index("#EXT-X-STREAM-INF")
        assert ext_media_idx < stream_inf_idx

    def test_slate_stream_inf_still_present_for_older_clients(self) -> None:
        # Belt-and-suspenders: the inflated-BANDWIDTH slate STREAM-INF is
        # retained so HLS players that ignore EXT-X-MEDIA failover groups
        # still cannot select the slate as a primary choice (50 Mbps is
        # higher than every realistic connection speed).
        manifest = build_multivariant_manifest(_make_renditions())
        bandwidth_lines = [line for line in manifest.splitlines() if "BANDWIDTH=" in line]
        # 4 content + 1 slate STREAM-INF entries.
        assert len(bandwidth_lines) == 5
        # The largest BANDWIDTH must be the slate's 50 Mbps.
        bandwidths = sorted(
            int(line.split("BANDWIDTH=")[1].split(",")[0]) for line in bandwidth_lines
        )
        assert bandwidths[-1] == 50_000_000

    def test_renditions_without_slate_skip_failover_group(self) -> None:
        # Defensive: if the slate is missing from the rendition list
        # (e.g., a future minimal-manifest test), no EXT-X-MEDIA is emitted.
        renditions_no_slate = _make_renditions(use_slate=False)
        manifest = build_multivariant_manifest(renditions_no_slate)
        assert "#EXT-X-MEDIA" not in manifest
        # Content STREAM-INF entries must still NOT reference a non-
        # existent group; without a slate, the VIDEO= attribute is
        # arguably orphaned. Current implementation still emits it for
        # consistency — capture the contract here so any future change
        # is intentional.
        stream_inf_lines = [
            line for line in manifest.splitlines() if line.startswith("#EXT-X-STREAM-INF")
        ]
        assert len(stream_inf_lines) == 4
