# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.stream.config.select_ladder — the never-upscale rule.

Regression origin: Gate A's clerk loop uploaded a 640x360 clip and called
``POST /api/staff/assets/{id}/package``, which encoded the unfiltered
four-rung ladder — upscaling a 360p source to 1080p and 720p. Measured on
that clip, the two upscaled rungs were ~81% of the packaging wall time
(18.4s unfiltered vs 3.4s filtered), which is what pushed the request past
its callers' timeouts. These tests pin the selection rules so the upscaled
rungs can never come back.
"""

from __future__ import annotations

import pytest

from civiccast.stream.config import ABR_LADDER, RenditionConfig, select_ladder


def _names(ladder: tuple[RenditionConfig, ...]) -> list[str]:
    return [rendition.name for rendition in ladder]


def _heights(ladder: tuple[RenditionConfig, ...]) -> list[int]:
    return [rendition.height for rendition in ladder]


class TestNeverUpscales:
    @pytest.mark.parametrize(
        ("width", "height"),
        [(640, 360), (854, 480), (426, 240), (320, 180), (1280, 720), (1920, 1080), (3840, 2160)],
    )
    def test_no_rendition_is_taller_than_the_source(self, width: int, height: int) -> None:
        selected = select_ladder(source_width=width, source_height=height)
        assert selected, "selection must never be empty"
        assert max(_heights(selected)) <= height

    def test_gate_a_clip_drops_the_upscaled_rungs(self) -> None:
        """The exact regression case: a 640x360 source must not encode 1080p/720p."""
        selected = select_ladder(source_width=640, source_height=360)
        assert "1080p" not in _names(selected)
        assert "720p" not in _names(selected)
        assert "480p" not in _names(selected)
        assert _names(selected) == ["360p", "240p"]

    def test_between_rungs_pins_the_top_tier_to_the_source_resolution(self) -> None:
        selected = select_ladder(source_width=640, source_height=360)
        top = selected[0]
        assert (top.width, top.height) == (640, 360)
        # Bitrate/profile/codec string are inherited from the shortest rung
        # the source outgrew (480p), not invented.
        rung_480p = next(r for r in ABR_LADDER if r.name == "480p")
        assert top.video_bitrate_kbps == rung_480p.video_bitrate_kbps
        assert top.audio_bitrate_kbps == rung_480p.audio_bitrate_kbps
        assert top.h264_profile == rung_480p.h264_profile
        assert top.h264_codec_string == rung_480p.h264_codec_string


class TestExactAndOversizedSources:
    def test_source_matching_a_rung_keeps_that_rung_and_below(self) -> None:
        selected = select_ladder(source_width=1280, source_height=720)
        assert _names(selected) == ["720p", "480p", "240p"]

    def test_source_at_the_ladder_top_is_unchanged(self) -> None:
        assert select_ladder(source_width=1920, source_height=1080) == ABR_LADDER

    def test_source_above_the_ladder_top_is_capped_by_the_ladder_not_extended(self) -> None:
        """A 4K source still publishes at 1080p and below — the top rung is a
        deliberate product cap, not a function of the source."""
        assert select_ladder(source_width=3840, source_height=2160) == ABR_LADDER

    def test_source_below_every_rung_gets_a_single_source_resolution_variant(self) -> None:
        selected = select_ladder(source_width=320, source_height=180)
        assert len(selected) == 1
        assert (selected[0].width, selected[0].height) == (320, 180)
        assert selected[0].name == "180p"


class TestUnknownDimensionsFallBackToTheFullLadder:
    @pytest.mark.parametrize(
        ("width", "height"),
        [(None, None), (640, None), (None, 360), (0, 360), (640, 0), (-1, -1)],
    )
    def test_returns_the_full_ladder(self, width: int | None, height: int | None) -> None:
        """Never guess: an unreadable probe must not silently shrink the ladder."""
        assert select_ladder(source_width=width, source_height=height) == ABR_LADDER


class TestSelectionInvariants:
    @pytest.mark.parametrize("height", [180, 240, 360, 480, 540, 720, 900, 1080, 1440])
    def test_dimensions_stay_even_for_yuv420p(self, height: int) -> None:
        selected = select_ladder(source_width=height * 16 // 9 | 1, source_height=height | 1)
        for rendition in selected:
            assert rendition.width % 2 == 0
            assert rendition.height % 2 == 0

    @pytest.mark.parametrize("height", [180, 240, 360, 480, 540, 720, 900, 1080])
    def test_ordering_stays_highest_to_lowest(self, height: int) -> None:
        selected = select_ladder(source_width=height * 16 // 9, source_height=height)
        assert _heights(selected) == sorted(_heights(selected), reverse=True)

    @pytest.mark.parametrize("height", [180, 240, 360, 480, 540, 720, 900, 1080])
    def test_rendition_names_stay_unique(self, height: int) -> None:
        """Names become on-disk directory names and manifest URIs — a
        collision would have two renditions overwrite each other."""
        selected = select_ladder(source_width=height * 16 // 9, source_height=height)
        assert len(set(_names(selected))) == len(selected)

    def test_empty_ladder_is_returned_unchanged(self) -> None:
        assert select_ladder(source_width=640, source_height=360, ladder=()) == ()

    def test_name_collision_falls_back_to_source(self) -> None:
        """Defensive guard for a custom ladder (spec §8.2 makes the ladder
        per-channel configurable) whose rung names do not match their own
        heights. ``ABR_LADDER`` cannot trigger this; a station-configured
        ladder could, and two renditions sharing a name would overwrite each
        other's output directory."""
        misnamed = (
            RenditionConfig(
                name="1080p",
                width=1920,
                height=1080,
                video_bitrate_kbps=4500,
                audio_bitrate_kbps=128,
                h264_profile="high",
                h264_codec_string="avc1.640028",
            ),
            RenditionConfig(
                name="360p",  # deliberately mislabelled: this rung is 240 tall
                width=426,
                height=240,
                video_bitrate_kbps=350,
                audio_bitrate_kbps=64,
                h264_profile="baseline",
                h264_codec_string="avc1.42001e",
            ),
        )
        selected = select_ladder(source_width=640, source_height=360, ladder=misnamed)
        assert _names(selected) == ["source", "360p"]
        assert (selected[0].width, selected[0].height) == (640, 360)
