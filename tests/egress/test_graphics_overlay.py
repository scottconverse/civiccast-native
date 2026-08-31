# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Gi-free unit tests for the S15 graphics-overlay leg (``graph.GraphicsOverlayLeg`` /
``graphics_overlay.py``): the PNG writer, the built-in lower-third font rasterizer, the
station-bug+banner leg builder, and the graph JSON round-trip. These run everywhere
(no GStreamer/gi needed) — the real live-pipeline compositing proof (frames actually
produced, pixels actually changed) lives in ``test_gst_engine_wsl.py`` alongside the
other live-engine tests, gated the same way."""

from __future__ import annotations

import struct
import zlib

import pytest

from civiccast.egress.gst.graph import (
    GraphicsOverlayLayer,
    GraphicsOverlayLeg,
    PlayoutGraph,
    SourceLeg,
    graph_from_json,
    graph_to_json,
)
from civiccast.egress.gst.graphics_overlay import (
    render_lower_third_png,
    station_bug_and_lower_third_leg,
    write_rgba_png,
)

# --- PNG writer -----------------------------------------------------------------


def _decode_png_ihdr_and_pixels(path) -> tuple[int, int, bytes]:
    """Minimal, independent PNG reader (IHDR + concatenated IDAT, filter-none only)
    used ONLY to verify ``write_rgba_png``'s own output — deliberately not the same
    code path as the writer, so a bug in the writer can't hide from a matching bug in
    the checker."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    width = height = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", body[:10])
            assert depth == 8
            assert color_type == 6  # RGBA
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 8 + length + 4  # length + tag + data + crc
    assert width is not None and height is not None
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    pixels = bytearray()
    for y in range(height):
        row_start = y * (stride + 1)
        filter_type = raw[row_start]
        assert filter_type == 0, "writer only ever emits filter-none scanlines"
        pixels += raw[row_start + 1 : row_start + 1 + stride]
    return width, height, bytes(pixels)


def test_write_rgba_png_round_trips_exact_pixels(tmp_path) -> None:
    width, height = 4, 3
    rgba = b""
    for y in range(height):
        for x in range(width):
            rgba += bytes((x * 10, y * 10, 255, 128))
    path = tmp_path / "swatch.png"
    write_rgba_png(path, width, height, rgba)
    assert path.exists() and path.stat().st_size > 0
    got_w, got_h, got_pixels = _decode_png_ihdr_and_pixels(path)
    assert (got_w, got_h) == (width, height)
    assert got_pixels == rgba


def test_write_rgba_png_rejects_mismatched_buffer_length(tmp_path) -> None:
    with pytest.raises(ValueError, match="expected"):
        write_rgba_png(tmp_path / "bad.png", 4, 4, b"\x00" * 10)


# --- lower-third font rasterizer -------------------------------------------------


def test_render_lower_third_png_produces_requested_canvas_size(tmp_path) -> None:
    path = tmp_path / "lower_third.png"
    w, h = render_lower_third_png(path, "CIVICCAST", canvas_width=640, banner_height=60)
    assert (w, h) == (640, 60)
    got_w, got_h, _pixels = _decode_png_ihdr_and_pixels(path)
    assert (got_w, got_h) == (640, 60)


def test_render_lower_third_png_actually_draws_foreground_pixels(tmp_path) -> None:
    """The honesty check: a banner with text must contain foreground-colored pixels
    (not just the solid background bar) — proof the font rasterizer actually drew
    something, not just filled a rectangle."""
    path = tmp_path / "lower_third.png"
    fg = (255, 255, 255, 255)
    bg = (10, 20, 60, 200)
    render_lower_third_png(path, "ON AIR", canvas_width=400, banner_height=60, fg=fg, bg=bg)
    _w, _h, pixels = _decode_png_ihdr_and_pixels(path)
    fg_bytes = bytes(fg)
    bg_bytes = bytes(bg)
    found_fg = any(pixels[i : i + 4] == fg_bytes for i in range(0, len(pixels), 4))
    found_bg = any(pixels[i : i + 4] == bg_bytes for i in range(0, len(pixels), 4))
    assert found_fg, "banner has no foreground-colored pixel — the text never rendered"
    assert found_bg, "banner has no background bar pixel — the bar never rendered"


def test_render_lower_third_png_never_raises_on_unsupported_characters(tmp_path) -> None:
    """An operator can type anything into a banner field; a character outside the
    built-in font must render as a blank cell, never take the overlay down."""
    path = tmp_path / "lower_third.png"
    render_lower_third_png(path, "Meeting @ 7pm — Rm #3 (café)", canvas_width=500, banner_height=60)
    assert path.exists()


# --- station-bug + lower-third leg builder ----------------------------------------


@pytest.mark.parametrize(
    ("corner", "expect_left", "expect_top"),
    [
        ("top-left", True, True),
        ("top-right", False, True),
        ("bottom-left", True, False),
        ("bottom-right", False, False),
    ],
)
def test_station_bug_corner_placement(tmp_path, corner, expect_left, expect_top) -> None:
    logo = tmp_path / "logo.png"
    write_rgba_png(logo, 2, 2, b"\xff\x00\x00\xff" * 4)
    leg = station_bug_and_lower_third_leg(
        logo_path=logo,
        logo_corner=corner,
        logo_width=160,
        canvas_width=1280,
        canvas_height=720,
    )
    bug = next(layer for layer in leg.layers if layer.name == "station_bug")
    if expect_left:
        assert bug.xpos < 1280 // 2
    else:
        assert bug.xpos > 1280 // 2
    if expect_top:
        assert bug.ypos < 720 // 2
    else:
        assert bug.ypos > 720 // 2


def test_station_bug_and_lower_third_leg_builds_both_layers(tmp_path) -> None:
    logo = tmp_path / "logo.png"
    write_rgba_png(logo, 2, 2, b"\xff\x00\x00\xff" * 4)
    leg = station_bug_and_lower_third_leg(
        logo_path=logo,
        canvas_width=1280,
        canvas_height=720,
        banner_text="CIVICCAST — CITY COUNCIL",
    )
    names = {layer.name for layer in leg.layers}
    assert names == {"station_bug", "lower_third"}
    banner_path = tmp_path / "lower_third.png"
    assert banner_path.exists(), (
        "banner_text without an explicit banner_path renders alongside the logo"
    )
    lower_third = next(layer for layer in leg.layers if layer.name == "lower_third")
    assert lower_third.width == 1280
    assert lower_third.ypos == 720 - lower_third.height


def test_station_bug_without_banner_text_yields_a_single_layer(tmp_path) -> None:
    logo = tmp_path / "logo.png"
    write_rgba_png(logo, 2, 2, b"\xff\x00\x00\xff" * 4)
    leg = station_bug_and_lower_third_leg(logo_path=logo, canvas_width=1280, canvas_height=720)
    assert [layer.name for layer in leg.layers] == ["station_bug"]


def test_invalid_corner_raises() -> None:
    with pytest.raises(ValueError, match="logo_corner"):
        station_bug_and_lower_third_leg(
            logo_path="logo.png", logo_corner="middle", canvas_width=100, canvas_height=100
        )


# --- graph.py dataclass + JSON round-trip -----------------------------------------


def _demo_graph_with_overlay() -> PlayoutGraph:
    from civiccast.egress.gst.graph import ElementSpec

    return PlayoutGraph(
        sources=(
            SourceLeg(
                label="program",
                elements=(ElementSpec("videotestsrc"), ElementSpec("capsfilter")),
            ),
        ),
        encoder=(ElementSpec("videoconvert"),),
        mux=ElementSpec("mpegtsmux"),
        sinks=((ElementSpec("filesink", props={"location": "/tmp/x.ts"}),),),
        graphics_overlay=GraphicsOverlayLeg(
            layers=(
                GraphicsOverlayLayer(
                    name="station_bug",
                    image_path="/stations/bug.png",
                    xpos=24,
                    ypos=24,
                    width=160,
                    alpha=0.9,
                ),
                GraphicsOverlayLayer(
                    name="lower_third",
                    image_path="/stations/lower_third.png",
                    xpos=0,
                    ypos=660,
                    width=1280,
                    height=60,
                ),
            )
        ),
    )


def test_graphics_overlay_leg_requires_at_least_one_layer() -> None:
    with pytest.raises(ValueError, match="at least one layer"):
        GraphicsOverlayLeg(layers=())


def test_graphics_overlay_leg_rejects_duplicate_layer_names() -> None:
    layer = GraphicsOverlayLayer(name="dup", image_path="a.png")
    with pytest.raises(ValueError, match="unique"):
        GraphicsOverlayLeg(layers=(layer, layer))


def test_graphics_overlay_layer_rejects_out_of_range_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        GraphicsOverlayLayer(name="bug", image_path="a.png", alpha=1.5)


def test_playout_graph_graphics_overlay_defaults_to_none() -> None:
    """Byte-identical-when-disabled contract: existing graph construction (every
    pre-existing caller, none of which sets this field) must be unaffected."""
    from civiccast.egress.gst.graph import ElementSpec

    graph = PlayoutGraph(
        sources=(SourceLeg(label="p", elements=(ElementSpec("videotestsrc"),)),),
        encoder=(),
        mux=ElementSpec("mpegtsmux"),
        sinks=((ElementSpec("filesink"),),),
    )
    assert graph.graphics_overlay is None


def test_graphics_overlay_leg_json_round_trip() -> None:
    graph = _demo_graph_with_overlay()
    restored = graph_from_json(graph_to_json(graph))
    assert restored.graphics_overlay is not None
    assert restored.graphics_overlay == graph.graphics_overlay
    assert restored == graph


def test_graph_without_graphics_overlay_round_trips_as_none() -> None:
    from civiccast.egress.gst.graph import ElementSpec

    graph = PlayoutGraph(
        sources=(SourceLeg(label="p", elements=(ElementSpec("videotestsrc"),)),),
        encoder=(),
        mux=ElementSpec("mpegtsmux"),
        sinks=((ElementSpec("filesink"),),),
    )
    restored = graph_from_json(graph_to_json(graph))
    assert restored.graphics_overlay is None
