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

from civiccast.egress.gst.bridge import (
    graph_from_config,
    graphics_overlay_leg_from_config,
    sweep_stale_lower_third_banners,
)
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


def test_graphics_overlay_leg_from_config_default_sweep_stale_off_leaves_old_banners(
    tmp_path: Path,
) -> None:
    """``sweep_stale`` defaults False -- ``reload_content()``'s call site must NOT
    sweep (its freshly-rendered banner races the still-live OLD one in a different
    process; only the worker's own swap-commit may delete that one). Every other
    pre-existing call in this module/its tests uses the default, so this pins that
    the default never starts silently deleting files out from under a caller that
    didn't ask for it."""
    first = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="First"),
        render_dir=tmp_path,
    )
    second = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=True, graphics_overlay_lower_third_text="Second"),
        render_dir=tmp_path,
    )
    assert first is not None and second is not None
    assert Path(first.layers[0].image_path).exists(), "sweep_stale=False must never delete"
    assert Path(second.layers[0].image_path).exists()
    banners = sorted(tmp_path.glob("graphics-overlay-lower-third.*.png"))
    assert len(banners) == 2


def test_graphics_overlay_leg_from_config_sweep_stale_true_deletes_leftovers_from_start(
    tmp_path: Path,
) -> None:
    """R3 fix: ``start()``'s call site passes ``sweep_stale=True`` -- a fresh
    ``start()`` always launches a brand-new worker process, so any OLDER banner
    file already in this channel's dir was written by a worker that has, by
    definition, already exited; nothing there can be live. Proves repeated
    start()-style calls (a crash-relaunch loop, or the same channel started many
    times) never accumulate banner PNGs -- only the CURRENT call's banner survives
    each time."""
    config = lambda text: _config(  # noqa: E731
        graphics_overlay_enabled=True, graphics_overlay_lower_third_text=text
    )
    paths: list[Path] = []
    for i in range(5):
        leg = graphics_overlay_leg_from_config(
            config(f"cycle {i}"), render_dir=tmp_path, sweep_stale=True
        )
        assert leg is not None
        current = Path(leg.layers[0].image_path)
        paths.append(current)
        banners = sorted(tmp_path.glob("graphics-overlay-lower-third.*.png"))
        assert banners == [current], (
            f"cycle {i}: expected only the current banner {current} on disk, "
            f"found {banners!r} -- old start()-cycle banners are accumulating"
        )
    # Every earlier cycle's banner is gone; only the last one remains.
    for stale in paths[:-1]:
        assert not stale.exists()
    assert paths[-1].exists()


def test_graphics_overlay_leg_from_config_sweep_stale_true_with_overlay_off_clears_all(
    tmp_path: Path,
) -> None:
    """An operator can turn the overlay OFF between two start()s (e.g. disable it,
    then restart the channel). The next ``start()`` sweep must still clear any
    leftover banner from when it was ON -- there is no ``keep`` path once the leg
    itself is ``None``."""
    leftover = tmp_path / f"graphics-overlay-lower-third.{'a' * 32}.png"
    leftover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    leg = graphics_overlay_leg_from_config(
        _config(graphics_overlay_enabled=False), render_dir=tmp_path, sweep_stale=True
    )
    assert leg is None
    assert not leftover.exists()


def test_sweep_stale_lower_third_banners_ignores_a_nonexistent_dir(tmp_path: Path) -> None:
    """A channel that has never rendered a banner has no render_dir yet -- the
    sweep must be a no-op, never raise, and never create the directory."""
    missing = tmp_path / "never-created"
    sweep_stale_lower_third_banners(missing, keep=None)
    assert not missing.exists()


def test_sweep_stale_lower_third_banners_never_touches_a_differently_named_file(
    tmp_path: Path,
) -> None:
    """Only the exact per-call generated pattern is swept -- an operator-configured
    persistent image (e.g. a station-bug/logo, or the fixed-name ``lower_third.png``
    the separate ``station_bug_and_lower_third_leg`` helper writes) must never be
    touched by this sweep."""
    logo = tmp_path / "station-logo.png"
    logo.write_bytes(b"logo")
    fixed_name_banner = tmp_path / "lower_third.png"
    fixed_name_banner.write_bytes(b"fixed")
    sweep_stale_lower_third_banners(tmp_path, keep=None)
    assert logo.exists()
    assert fixed_name_banner.exists()


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
