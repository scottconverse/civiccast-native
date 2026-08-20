# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP tests for streaming overlay compositor planning."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.stream.router import get_ffmpeg_encoders_output


def _client() -> TestClient:
    # SEC-1 added Depends(require_any_role(...)) to overlay-compositor-plan
    # (meeting_operator/support_admin), so this needs the full app (central
    # bearer-token auth) plus a role-carrying token rather than a
    # bare-router FastAPI() instance. Same pattern as
    # tests/programlog/test_router.py: create_app() + dependency_overrides
    # for the DI seam + the deterministic all-roles "operator" token that
    # tests/conftest.py enables via CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN.
    app = create_app()
    app.dependency_overrides[get_ffmpeg_encoders_output] = lambda: (
        "V..... h264_vaapi H.264 VAAPI encoder"
    )
    return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})


def test_overlay_compositor_plan_preview_is_gpu_aware() -> None:
    response = _client().post(
        "/api/staff/stream/overlay-compositor-plan",
        json={
            "channel_id": "gov-ch12",
            "input_url": "rtmp://127.0.0.1/live/gov-ch12",
            "output_manifest_path": "live/gov-ch12/overlay.m3u8",
            "acceleration_preference": "auto",
            "layers": [
                {
                    "layer_id": "lbar",
                    "kind": "l-bar",
                    "label": "L-bar",
                    "geometry": {
                        "x_percent": 0,
                        "y_percent": 76,
                        "width_percent": 100,
                        "height_percent": 24,
                    },
                    "opacity": 0.9,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["acceleration_mode"] == "vaapi"
    assert body["gpu_accelerated"] is True
    assert body["ordered_layers"][0]["kind"] == "l-bar"
    assert "h264_vaapi" in body["ffmpeg_args"]
    assert body["proof_boundary"] == "overlay-compositor-command-planning-no-ffmpeg-execution"
