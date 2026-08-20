# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for streaming overlay compositor planning."""

from __future__ import annotations

from pydantic import ValidationError

from civiccast.stream.overlays import (
    OVERLAY_Z_ORDER,
    OverlayCompositorRequest,
    OverlayGeometry,
    OverlayLayer,
    build_overlay_compositor_plan,
    default_squeezeback_lbar_layers,
    select_acceleration_mode,
)


def test_compositor_plan_orders_layers_and_uses_gpu_when_available() -> None:
    request = OverlayCompositorRequest(
        channel_id="gov-ch12",
        input_url="rtmp://127.0.0.1/live/gov-ch12",
        output_manifest_path="live/gov-ch12/overlay.m3u8",
        acceleration_preference="auto",
        layers=[
            OverlayLayer(
                layer_id="emergency",
                kind="emergency",
                label="Emergency alert",
                geometry=OverlayGeometry(
                    x_percent=0,
                    y_percent=0,
                    width_percent=100,
                    height_percent=12,
                ),
            ),
            *default_squeezeback_lbar_layers(),
            OverlayLayer(
                layer_id="bug",
                kind="bug",
                label="Station bug",
                geometry=OverlayGeometry(
                    x_percent=88,
                    y_percent=4,
                    width_percent=8,
                    height_percent=8,
                ),
                opacity=0.8,
            ),
        ],
    )

    plan = build_overlay_compositor_plan(
        request,
        ffmpeg_encoders_output="V..... h264_nvenc NVIDIA NVENC H.264 encoder",
    )

    assert [layer.kind for layer in plan.ordered_layers] == [
        "squeezeback",
        "l-bar",
        "bug",
        "emergency",
    ]
    assert plan.z_order == OVERLAY_Z_ORDER
    assert plan.acceleration_mode == "nvenc"
    assert plan.gpu_accelerated is True
    assert "h264_nvenc" in plan.ffmpeg_args
    assert "drawbox" in plan.filter_complex
    assert "scale=1306:778" in plan.filter_complex
    assert plan.proof_boundary == "overlay-compositor-command-planning-no-ffmpeg-execution"


def test_acceleration_selection_falls_back_to_cpu_when_gpu_encoder_is_absent() -> None:
    assert select_acceleration_mode("nvenc", ffmpeg_encoders_output="V..... libx264") == "cpu"
    assert select_acceleration_mode("vaapi", ffmpeg_encoders_output="V..... h264_vaapi") == "vaapi"


def test_overlay_geometry_must_fit_the_frame() -> None:
    try:
        OverlayGeometry(x_percent=80, y_percent=0, width_percent=25, height_percent=10)
    except ValidationError as exc:
        assert "exceeds output width" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected invalid geometry to fail")
