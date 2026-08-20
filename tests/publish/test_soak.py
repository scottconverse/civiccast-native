# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Nightly publish-soak proof tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from civiccast.publish.soak import EXPECTED_SURFACE_IDS, run_publish_soak


def test_publish_soak_runs_every_three_tier_surface() -> None:
    result = run_publish_soak(iterations=3)

    assert result.status == "passed"
    assert result.iterations_requested == 3
    assert result.iterations_completed == 3
    assert result.tier_surface_ids == {
        "canonical": ["portal"],
        "archive": ["internet-archive", "local-nas-rsync", "local-nas-zfs"],
        "reach": ["youtube-live", "youtube-vod"],
        "audience": ["podcast", "subscriber-notifications"],
    }
    for iteration in result.iterations:
        assert iteration.ready is True
        assert iteration.dashboard_state == "archive_verified"
        assert iteration.canonical_public is True
        assert iteration.archive_verified is True
        assert iteration.succeeded_surface_ids == list(EXPECTED_SURFACE_IDS)
        assert iteration.verified_archive_hashes.keys() == {
            "internet-archive",
            "local-nas-rsync",
            "local-nas-zfs",
        }
        assert all(
            value.startswith("sha256:") for value in iteration.verified_archive_hashes.values()
        )
        assert iteration.audit_event_count == len(EXPECTED_SURFACE_IDS)


def test_publish_soak_script_writes_machine_readable_evidence(tmp_path: Path) -> None:
    output = tmp_path / "publish-soak-result.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_publish_soak.py",
            "--iterations",
            "2",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "publish-soak: PASS iterations=2" in completed.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert payload["iterations_completed"] == 2
    assert payload["iterations"][0]["asset_id"] == "nightly-publish-soak-001"
