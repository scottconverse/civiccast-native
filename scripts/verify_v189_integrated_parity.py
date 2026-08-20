#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify v1.8.9 integrated parity contracts from tracked artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.json"
MATRIX_PATH = REPO_ROOT / "docs" / "spec" / "2.0" / "parity-evidence-matrix.json"

REQUIRED_GROUPS: dict[str, tuple[str, ...]] = {
    "app_platform": (
        "/api/public/app/config",
        "/api/public/app/channels/{channel_id}/live",
        "/api/public/app/channels/{channel_id}/catalog",
        "/api/public/app/channels/{channel_id}/schedule/epg",
        "/api/staff/app/config",
    ),
    "cg_bulletin_board": (
        "/api/public/cg/channels/{channel_id}/display",
        "/api/public/cg/channels/{channel_id}/render-plan",
        "/api/public/cg/channels/{channel_id}/stream.m3u8",
        "/api/staff/cg/channels/{channel_id}/bulletins",
    ),
    "contributor_workflow": (
        "/api/public/contribute/agreements/current",
        "/api/public/contribute/submissions",
        "/api/public/contribute/submissions/{submission_id}/status",
        "/api/staff/contribute/submissions",
        "/api/staff/contribute/submissions/{submission_id}/review",
    ),
    "gated_preroll_playback": (
        "/api/public/playback-policy/evaluate",
        "/api/staff/playback-policy/{subject_type}/{subject_id}",
        "/api/staff/playback-policy/viewer-tokens",
    ),
    "analytics_and_epg": (
        "/api/public/app/analytics/events",
        "/api/staff/analytics/reports/overview",
        "/api/public/app/channels/{channel_id}/schedule/epg/xlist",
        "/api/public/schedule/coming-up",
    ),
    "remote_ingest_relay": (
        "/api/staff/live/relay-configs",
        "/api/staff/live/relay-configs/{relay_config_id}",
        "/api/staff/live/relay-configs/{relay_config_id}/health",
    ),
    "broadcast_facility": (
        "/api/staff/facility/router-inventory",
        "/api/staff/facility/router-panel",
        "/api/staff/facility/router-take-plan",
        "/api/staff/facility/router-schedule-plan",
    ),
    "captions_and_overlays": (
        "/api/staff/captions/external-ingest",
        "/api/staff/captions/review-items",
        "/api/staff/stream/overlay-compositor-plan",
    ),
}


def verify_integrated_parity(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return a deterministic integrated parity verification summary."""

    openapi_path = root / OPENAPI_PATH.relative_to(REPO_ROOT)
    matrix_path = root / MATRIX_PATH.relative_to(REPO_ROOT)
    openapi = json.loads(openapi_path.read_text(encoding="utf-8"))
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    paths = set(openapi.get("paths", {}))

    group_results: dict[str, dict[str, Any]] = {}
    missing: dict[str, list[str]] = {}
    for group, required_paths in REQUIRED_GROUPS.items():
        absent = [path for path in required_paths if path not in paths]
        group_results[group] = {
            "status": "passed" if not absent else "failed",
            "required_paths": list(required_paths),
            "missing_paths": absent,
        }
        if absent:
            missing[group] = absent

    gap_count = len(matrix.get("gaps", []))
    statuses = sorted({gap.get("status") for gap in matrix.get("gaps", [])})
    matrix_ready = gap_count == 10 and all(
        status in matrix["allowed_statuses"] for status in statuses
    )

    return {
        "status": "passed" if not missing and matrix_ready else "failed",
        "openapi_path": str(openapi_path.relative_to(root)),
        "matrix_path": str(matrix_path.relative_to(root)),
        "gap_count": gap_count,
        "matrix_statuses": statuses,
        "groups": group_results,
        "missing": missing,
    }


def main() -> int:
    result = verify_integrated_parity()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
