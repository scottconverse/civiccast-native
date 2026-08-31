# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S15 graphics-overlay operator control: EgressConfig -> PlayoutGraph.graphics_overlay.

Proves the end-to-end wiring for the next-pipeline-build slice: the operator's
``graphics_overlay_enabled`` + ``graphics_overlay_lower_third_text`` fields on
``EgressConfig`` flow through ``graphics_overlay_leg_from_config`` into a real
``GraphicsOverlayLeg``, and ``graph_from_config`` sets it on the built
``PlayoutGraph`` -- not asserted by inspection, exercised end to end.
"""

from __future__ import annotations

from pathlib import Path

from civiccast.egress.gst.bridge import graph_from_config, graphics_overlay_leg_from_config
from civiccast.egress.gst.graph import GraphicsOverlayLeg
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)


def _config(**overrides: object) -> EgressConfig:
    defaults: dict[str, object] = {
        "channel_id": "ch1",
        "enabled": True,
        "slate_message": "Please stand by",
        "sinks": [EgressSinkSpec(kind="udp-ts", label="head", uri="udp://10.0.0.9:5000")],
    }
    defaults.update(overrides)
    return EgressConfig(**defaults)  # type: ignore[arg-type]


def _plan() -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="ch1",
        segments=[EgressSourceSegment(label="clip1", path="/m/clip1.ts", duration_seconds=10)],
    )


def test_graphics_overlay_off_by_default(tmp_path: Path) -> None:
    """An unconfigured channel gets no leg -- byte-identical to before this field existed."""
    config = _config()
    assert config.graphics_overlay_enabled is False
    assert config.graphics_overlay_lower_third_text == ""
    assert graphics_overlay_leg_from_config(config, render_dir=tmp_path) is None


def test_graphics_overlay_enabled_but_blank_text_yields_no_leg(tmp_path: Path) -> None:
    config = _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="   ")
    assert graphics_overlay_leg_from_config(config, render_dir=tmp_path) is None


def test_graphics_overlay_leg_from_config_renders_banner_and_builds_leg(tmp_path: Path) -> None:
    config = _config(
        graphics_overlay_enabled=True,
        graphics_overlay_lower_third_text="Town Council - Live",
        canonical_profile=CanonicalProfile(width=1280, height=720),
    )
    leg = graphics_overlay_leg_from_config(config, render_dir=tmp_path)
    assert isinstance(leg, GraphicsOverlayLeg)
    assert len(leg.layers) == 1
    layer = leg.layers[0]
    assert layer.name == "lower_third"
    assert layer.width == 1280
    assert layer.ypos == 720 - 60  # banner pinned to the bottom of the canvas
    banner_path = Path(layer.image_path)
    assert banner_path.exists()
    assert banner_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # a real PNG was written


def test_graph_from_config_sets_graphics_overlay_when_enabled(tmp_path: Path) -> None:
    """The end-to-end proof: set the operator fields on EgressConfig, build a
    PlayoutGraph, and assert graphics_overlay is populated -- not inspected in
    isolation."""
    config = _config(
        graphics_overlay_enabled=True,
        graphics_overlay_lower_third_text="Breaking: Council votes tonight",
    )
    leg = graphics_overlay_leg_from_config(config, render_dir=tmp_path)
    graph = graph_from_config(config, _plan(), graphics_overlay=leg)
    assert graph.graphics_overlay is not None
    assert graph.graphics_overlay.layers[0].name == "lower_third"


def test_graph_from_config_graphics_overlay_none_by_default(tmp_path: Path) -> None:
    config = _config()
    graph = graph_from_config(config, _plan())
    assert graph.graphics_overlay is None


def test_graphics_overlay_leg_from_config_uses_a_unique_banner_filename_per_call(
    tmp_path: Path,
) -> None:
    """MAJOR fix (2026-08-30 audit): the banner PNG used to be written to a FIXED
    filename (``graphics-overlay-lower-third.png``). A concurrent build (a
    crash-relaunch racing a content-reload) could then read a partially-written
    PNG on that shared path and fail to decode -- crashing the whole worker at
    startup (engine.py's real GStreamer decode of the banner). ENG-005 mirrors
    ``strategy.reload_content``'s unique-per-reload graph filename: each call now
    gets its own ``uuid4``-suffixed path, so two concurrent renders can never
    clobber (or race-read) the same file."""
    first = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="First"),
        render_dir=tmp_path,
    )
    second = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="First"),
        render_dir=tmp_path,
    )
    assert first is not None and second is not None
    first_path = Path(first.layers[0].image_path)
    second_path = Path(second.layers[0].image_path)
    assert first_path != second_path, (
        "two renders (even with identical text) must land on distinct paths -- a "
        "fixed filename is exactly the race the ENG-005 pattern closes"
    )
    # Both files are real, independently readable PNGs -- neither call ever
    # touched the other's path, so there is no partial-write race between them.
    assert first_path.exists() and second_path.exists()
    assert first_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert second_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    banners = sorted((tmp_path).glob("graphics-overlay-lower-third.*.png"))
    assert len(banners) == 2, f"expected 2 unique-named banner PNGs, found {banners!r}"


def test_graphics_overlay_leg_rerenders_on_each_call_for_updated_text(tmp_path: Path) -> None:
    """A content-reload calls this again with fresh config -- proves a saved text
    change is picked up on the NEXT pipeline build (not hot on an already-live one;
    see the module docstring)."""
    first = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="First"),
        render_dir=tmp_path,
    )
    assert first is not None
    first_bytes = Path(first.layers[0].image_path).read_bytes()

    second = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="Second"),
        render_dir=tmp_path,
    )
    assert second is not None
    second_bytes = Path(second.layers[0].image_path).read_bytes()
    assert first_bytes != second_bytes
