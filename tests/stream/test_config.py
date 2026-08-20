# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.stream.config — ABR ladder constants."""

from __future__ import annotations

from civiccast.stream.config import (
    ABR_LADDER,
    FFMPEG_MIN_VERSION,
    HLS_SEGMENT_DURATION,
    HLS_VERSION,
    SLATE_RENDITION,
    RenditionConfig,
)


class TestAbrLadder:
    def test_has_four_content_renditions(self) -> None:
        assert len(ABR_LADDER) == 4

    def test_renditions_are_ordered_highest_to_lowest_bandwidth(self) -> None:
        bandwidths = [r.bandwidth_bps for r in ABR_LADDER]
        assert bandwidths == sorted(bandwidths, reverse=True)

    def test_all_renditions_have_required_fields(self) -> None:
        for r in ABR_LADDER:
            assert r.name
            assert r.width > 0
            assert r.height > 0
            assert r.video_bitrate_kbps > 0
            assert r.audio_bitrate_kbps > 0
            assert r.h264_profile in ("high", "main", "baseline")
            assert r.h264_codec_string.startswith("avc1.")

    def test_1080p_uses_high_profile(self) -> None:
        r = ABR_LADDER[0]
        assert r.name == "1080p"
        assert r.h264_profile == "high"
        assert r.width == 1920
        assert r.height == 1080

    def test_240p_uses_baseline_profile(self) -> None:
        r = ABR_LADDER[-1]
        assert r.name == "240p"
        assert r.h264_profile == "baseline"

    def test_slate_real_bitrate_is_lowest(self) -> None:
        # The slate's REAL encoded bitrate is the smallest in the ladder
        # (cheap fallback, narrow networks). The advertised manifest
        # bandwidth is intentionally higher — see
        # test_slate_manifest_bandwidth_is_above_all_content below.
        min_content_bandwidth = min(r.bandwidth_bps for r in ABR_LADDER)
        assert SLATE_RENDITION.bandwidth_bps < min_content_bandwidth

    def test_slate_manifest_bandwidth_is_above_all_content(self) -> None:
        # ADR 0007 amendment: slate must never be picked as a primary
        # variant by an estimate-matching ABR client. Inflating the
        # advertised BANDWIDTH above all content guarantees that.
        max_content_advertised = max(r.manifest_bandwidth_bps for r in ABR_LADDER)
        assert SLATE_RENDITION.manifest_bandwidth_bps > max_content_advertised

    def test_slate_uses_baseline_profile(self) -> None:
        assert SLATE_RENDITION.h264_profile == "baseline"
        assert SLATE_RENDITION.name == "slate"

    def test_content_renditions_have_no_advertised_bandwidth_override(self) -> None:
        # Only the slate needs the override; content variants advertise
        # their real bitrate so ABR estimate-matching picks them correctly.
        for r in ABR_LADDER:
            assert r.advertised_bandwidth_bps_override is None
            assert r.manifest_bandwidth_bps == r.bandwidth_bps


class TestRenditionConfigProperties:
    def test_bandwidth_bps_is_sum_of_video_and_audio_kbps_times_1000(self) -> None:
        r = RenditionConfig(
            name="test",
            width=1280,
            height=720,
            video_bitrate_kbps=2500,
            audio_bitrate_kbps=128,
            h264_profile="main",
            h264_codec_string="avc1.4d401f",
        )
        assert r.bandwidth_bps == (2500 + 128) * 1000

    def test_resolution_str_format(self) -> None:
        r = RenditionConfig(
            name="test",
            width=1920,
            height=1080,
            video_bitrate_kbps=4500,
            audio_bitrate_kbps=128,
            h264_profile="high",
            h264_codec_string="avc1.640028",
        )
        assert r.resolution_str == "1920x1080"


class TestHlsConstants:
    def test_segment_duration_is_two_seconds(self) -> None:
        assert HLS_SEGMENT_DURATION == 2

    def test_hls_version_is_at_least_3(self) -> None:
        assert HLS_VERSION >= 3

    def test_ffmpeg_min_version_is_reasonable(self) -> None:
        major, _minor = FFMPEG_MIN_VERSION
        assert major >= 4
