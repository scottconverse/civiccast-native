# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""RED contract tests for the on-air multi-zone board compositor (slice CG-1).

The compositor turns a ResolvedBoard (template geometry + zones + feed items)
plus one airable bulletin into ffmpeg args for a single composed board segment,
routed through the ADR-0007 wrapper (args never include the binary). Rotation of
the primary zone across bulletins is the caller's job (one segment per bulletin,
matching the existing filler plan mechanics).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.cg.board_resolver import ResolvedBoard
from civiccast.cg.models import (
    CgBulletinSubmission,
    CgTemplate,
    CgTemplateZone,
    CgZone,
    MultiZoneCgSnapshot,
)
from civiccast.egress.board_compositor import (
    board_segment_cache_key,
    build_board_preview_args,
    build_board_segment_args,
)

NOW = datetime(2026, 8, 5, 19, 30, 15, tzinfo=UTC)


def _template() -> CgTemplate:
    return CgTemplate(
        template_id="tpl-board-v1",
        label="Fullscreen board with ticker",
        regions=[
            CgTemplateZone(region="main", zone_kind="primary", order=0),
            CgTemplateZone(region="lower", zone_kind="ticker", order=1),
            CgTemplateZone(region="side", zone_kind="schedule", order=2),
            CgTemplateZone(region="bug", zone_kind="logo", order=3),
        ],
    )


def _zones(
    *,
    ticker_items: list[dict] | None = None,
    ticker_degraded: bool = False,
    schedule_clock: bool = False,
    logo_asset: str | None = "asset://logo-lpm",
) -> list[CgZone]:
    items = (
        ticker_items
        if ticker_items is not None
        else [
            {"item_id": "n1", "title": "Council meeting tonight 7pm"},
            {"item_id": "n2", "title": "Road closure on Main St"},
        ]
    )
    ticker_content: dict = {"items": items}
    if ticker_degraded:
        ticker_content = {"items": [], "degraded": True}
    schedule_content: dict = (
        {"mode": "clock"}
        if schedule_clock
        else {
            "items": [
                {"time": "18:30", "title": "Planning Board"},
                {"time": "19:00", "title": "City Council"},
                {"time": "21:00", "title": "Parks Update"},
                {"time": "23:00", "title": "Late Replay"},
            ]
        }
    )
    return [
        CgZone(zone_id="z-primary", kind="primary", source="manual", content={}),
        CgZone(zone_id="z-ticker", kind="ticker", source="feed_adapter", content=ticker_content),
        CgZone(zone_id="z-schedule", kind="schedule", source="schedule", content=schedule_content),
        CgZone(
            zone_id="z-logo",
            kind="logo",
            source="image",
            content={"image_asset_ref": logo_asset},
        ),
    ]


def _board(
    *,
    zones: list[CgZone] | None = None,
    template: CgTemplate | None = None,
    degraded: list[str] | None = None,
) -> ResolvedBoard:
    tpl = template or _template()
    snapshot = MultiZoneCgSnapshot(
        snapshot_id="snap-1",
        generated_at=NOW,
        channel_id="ch-1",
        template=tpl,
        zones=zones or _zones(),
        hls_render_path="cg/ch-1/board.m3u8",
        portal_render_path="cg/ch-1/board.html",
        proof_boundary="test-boundary",
    )
    return ResolvedBoard(
        board_id="board-1",
        snapshot=snapshot,
        degraded_zone_ids=degraded or [],
    )


def _bulletin(
    submission_id: str = "b-1", title: str = "Food drive Saturday"
) -> CgBulletinSubmission:
    return CgBulletinSubmission(
        submission_id=submission_id,
        organization="Longmont Rotary",
        submitter_label="J. Alvarez",
        title=title,
        message="Drop off canned goods at the library, 9am to noon.",
        target_zone_kind="primary",
        state="accepted",
        approved_by_operator="op-1",
    )


def _args(**overrides) -> list[str]:
    params: dict = {
        "board": _board(),
        "bulletin": _bulletin(),
        "width": 1280,
        "height": 720,
        "frame_rate": 30,
        "background_color": "#102030",
        "station_short_name": "LPM",
        "segment_seconds": 12.0,
        "out_path": Path("/tmp/board-seg.ts"),
        "include_text": True,
        "now": NOW,
        "image_resolver": lambda ref: None,
    }
    params.update(overrides)
    return build_board_segment_args(**params)


def _preview_args(**overrides) -> list[str]:
    params: dict = {
        "board": _board(),
        "bulletin": _bulletin(),
        "width": 1280,
        "height": 720,
        "frame_rate": 30,
        "background_color": "#102030",
        "station_short_name": "LPM",
        "out_path": Path("/tmp/board-preview.png"),
        "include_text": True,
        "now": NOW,
        "image_resolver": lambda ref: None,
    }
    params.update(overrides)
    return build_board_preview_args(**params)


def _joined(args: list[str]) -> str:
    return " ".join(args)


class TestSegmentArgs:
    def test_background_covers_frame_with_branding_color(self) -> None:
        joined = _joined(_args())
        assert "color=c=#102030" in joined or "color=c=0x102030" in joined
        assert "1280x720" in joined
        assert "ffmpeg" not in joined.split()[0:1]  # ADR 0007: wrapper prepends binary

    def test_output_is_mpegts_at_out_path(self) -> None:
        args = _args()
        assert "-f" in args and "mpegts" in args
        assert args[-1].endswith("board-seg.ts")

    def test_primary_zone_renders_the_bulletin(self) -> None:
        joined = _joined(_args())
        assert "Food drive Saturday" in joined
        assert "Longmont Rotary" in joined

    def test_ticker_zone_scrolls_feed_items(self) -> None:
        joined = _joined(_args())
        assert "Council meeting tonight 7pm" in joined
        assert "Road closure on Main St" in joined
        # a crawl needs a time-driven x expression, not a static placement
        assert "mod(" in joined and "t*" in joined

    def test_ticker_item_title_is_capped_before_drawtext(self) -> None:
        # Gate finding F-5 (cosmetic/defensive): an unbounded feed-item title
        # would otherwise scroll a single, ever-longer line forever.
        overlong = "X" * 200
        zones = _zones(ticker_items=[{"item_id": "n1", "title": overlong}])
        joined = _joined(_args(board=_board(zones=zones)))

        assert overlong not in joined
        assert "X" * 119 + "…" in joined

    def test_schedule_zone_caps_at_three_upcoming(self) -> None:
        joined = _joined(_args())
        # drawtext escapes ':' so the time may appear as 18\:30 in the filter
        assert ("18:30" in joined or r"18\:30" in joined) and "Planning Board" in joined
        assert "City Council" in joined and "Parks Update" in joined
        assert "Late Replay" not in joined

    def test_logo_zone_overlays_resolved_image(self) -> None:
        resolved = Path("/tmp/assets/logo.png")
        args = _args(image_resolver=lambda ref: resolved if ref == "asset://logo-lpm" else None)
        assert any(str(resolved) in a for a in args)
        assert "overlay=" in _joined(args)

    def test_unresolvable_image_zone_renders_without_extra_input(self) -> None:
        args = _args(image_resolver=lambda ref: None)
        assert not any(a.endswith(".png") for a in args)

    def test_font_missing_degradation_drops_all_text(self) -> None:
        joined = _joined(_args(include_text=False))
        assert "drawtext" not in joined

    def test_degraded_ticker_renders_empty_not_crashing(self) -> None:
        zones = _zones(ticker_degraded=True)
        args = _args(board=_board(zones=zones, degraded=["z-ticker"]))
        joined = _joined(args)
        assert "Council meeting tonight 7pm" not in joined
        assert "-f" in args  # still a valid render


class TestDrawtextEscapingIsShared:
    """Gate finding F-3: board_compositor must use the ONE shared escaping
    implementation (civiccast.egress.source_plan._escape_drawtext), not its
    own drifted copy. A prior audit found two independent implementations
    that had already diverged once in call order.
    """

    def test_board_compositor_imports_the_shared_escape_function(self) -> None:
        from civiccast.egress import board_compositor, source_plan

        assert board_compositor._escape_drawtext is source_plan._escape_drawtext

    def test_primary_zone_text_escapes_backslash_quote_and_colon(self) -> None:
        bulletin = _bulletin(title=r"Mayor's \ update: 5pm")
        joined = _joined(_args(bulletin=bulletin))
        assert r"Mayor\'s \\ update\: 5pm" in joined


class TestPreviewArgs:
    def test_preview_emits_png_output_format(self) -> None:
        joined = _joined(_preview_args())
        assert "-f" in joined
        assert "image2" in joined
        assert "-vcodec" in joined
        assert "png" in joined
        assert "-pix_fmt" in joined
        assert "rgb24" in joined

    def test_preview_renders_single_frame_only(self) -> None:
        args = _preview_args()
        assert "-frames:v" in args
        frame_i = args.index("-frames:v")
        assert args[frame_i + 1] == "1"

    def test_preview_is_not_mpegts_segment(self) -> None:
        args = _preview_args()
        assert not ("mpegts" in args and "-f" in args and args[args.index("-f") + 1] == "mpegts")
        assert args[-1].endswith("board-preview.png")


class TestCacheKey:
    def _key(self, **overrides) -> str:
        params: dict = {
            "board": _board(),
            "bulletin": _bulletin(),
            "background_color": "#102030",
            "station_short_name": "LPM",
            "segment_seconds": 12.0,
            "width": 1280,
            "height": 720,
            "frame_rate": 30,
            "now": NOW,
        }
        params.update(overrides)
        return board_segment_cache_key(**params)

    def test_stable_for_identical_inputs(self) -> None:
        assert self._key() == self._key()

    def test_changes_with_bulletin(self) -> None:
        assert self._key() != self._key(bulletin=_bulletin("b-2", "Blood drive Sunday"))

    def test_changes_with_feed_items(self) -> None:
        other = _board(zones=_zones(ticker_items=[{"item_id": "n9", "title": "New item"}]))
        assert self._key() != self._key(board=other)

    def test_changes_with_template(self) -> None:
        tpl = _template().model_copy(update={"template_id": "tpl-board-v2"})
        other = _board(template=tpl)
        assert self._key() != self._key(board=other)

    def test_changes_with_branding_color(self) -> None:
        assert self._key() != self._key(background_color="#000000")

    def test_no_clock_zone_ignores_wall_time(self) -> None:
        later = NOW.replace(minute=45)
        assert self._key() == self._key(now=later)

    def test_clock_zone_buckets_by_minute(self) -> None:
        clock_board = _board(zones=_zones(schedule_clock=True))
        same_minute = NOW.replace(second=50)
        next_minute = NOW.replace(minute=31, second=5)
        assert self._key(board=clock_board, now=NOW) == self._key(
            board=clock_board, now=same_minute
        )
        assert self._key(board=clock_board, now=NOW) != self._key(
            board=clock_board, now=next_minute
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
