# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contributor uploads must be bounded in AGGREGATE, not just per request.

GauntletGate rc18 QA-2 (Critical). The rc17-era fix put a real 2 GiB ceiling on
each ``POST /api/public/contribute/uploads`` call and a real 10/hour per-IP
window on the route. Both work. Neither bounds the TOTAL.

Every accepted upload lands under ``default_contributor_upload_dir()`` and
nothing deletes it, expires it, or requires it to be attached to a submission.
At the shipped defaults a single unauthenticated, un-rotated source address can
place roughly 480 GB per day on a station's disk, indefinitely, with no alert.
CivicCast's own pitch targets commodity hardware and small self-hosted
stations, so that fills a typical disk in days -- no botnet, no authentication,
just patience.

The gate found day-old files still sitting in that directory from a previous
test run, which is the defect demonstrating itself.

This adds the missing aggregate bound: once the upload directory as a whole
exceeds its ceiling, new uploads are refused with an actionable 507 instead of
being written. It deliberately does NOT delete anything -- see the router
comment for why an age-based sweep is the wrong instrument here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def upload_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    upload_dir = tmp_path / "contributor-uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(upload_dir))
    # Small ceilings so the test stays fast and does not write gigabytes.
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES", str(64 * 1024))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR_MAX_BYTES", str(128 * 1024))
    yield upload_dir
    for key in (
        "CIVICCAST_CONTRIBUTOR_UPLOAD_DIR",
        "CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES",
        "CIVICCAST_CONTRIBUTOR_UPLOAD_DIR_MAX_BYTES",
    ):
        os.environ.pop(key, None)


def _client() -> TestClient:
    from civiccast.app import create_app

    return TestClient(create_app())


def _upload(client: TestClient, name: str, size: int):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/public/contribute/uploads",
        files={"file": (name, b"\0" * size, "video/mp4")},
    )


def test_uploads_are_refused_once_the_directory_ceiling_is_reached(
    upload_env: Path,
) -> None:
    client = _client()

    # Pre-fill the directory past its ceiling, as accumulated uploads would.
    (upload_env / "already-there.bin").write_bytes(b"\0" * (130 * 1024))

    response = _upload(client, "one-more.mp4", 1024)

    assert response.status_code == 507, (
        f"Upload returned {response.status_code} with the contributor upload "
        "directory already over its ceiling. Unbounded accumulation is the "
        "whole finding: a per-request cap does not stop a patient caller."
    )
    detail = response.json()["detail"].lower()
    assert "storage" in detail or "capacity" in detail
    assert not (upload_env / "one-more.mp4").exists(), (
        "The refused upload was still written to disk."
    )


def test_a_normal_upload_still_succeeds_under_the_ceiling(upload_env: Path) -> None:
    """The bound must not break the contributors it exists to serve."""

    client = _client()
    response = _upload(client, "programme.mp4", 2048)

    assert response.status_code == 201, response.text
    assert (upload_env / "programme.mp4").exists()


def test_the_ceiling_counts_what_is_already_on_disk_not_just_this_request(
    upload_env: Path,
) -> None:
    """Aggregate, not per-call: several small uploads must add up."""

    client = _client()
    for index in range(3):
        _upload(client, f"clip-{index}.mp4", 50 * 1024)

    total = sum(f.stat().st_size for f in upload_env.iterdir() if f.is_file())
    assert total <= 128 * 1024 + 50 * 1024, (
        f"Directory grew to {total} bytes against a 128 KiB ceiling; the "
        "aggregate bound is not being enforced across requests."
    )
