# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: the public contributor upload must not be an open disk-fill surface.

GauntletGate QA-2 (Critical, 2026-07-21). ``POST /api/public/contribute/uploads``
had no auth dependency, no rate limiter, and no size ceiling. It streamed
``file.file.read(1024 * 1024)`` in an unbounded loop straight to disk, and it
touches no database, so it stayed reachable even on a station whose storage was
not configured. Its only guard rejected a zero-byte upload -- after the whole
file had already been written.

Public contributor upload is a deliberately internet-facing feature (community
producers submitting programming), so an anonymous caller could fill the
station's disk. The same file already fixed this class of gap for the sibling
status route under "Audit item #27", and civiccast/app.py already ships a
streamed body-size cap for public analytics; this route was simply missed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app
from civiccast.contribute.router import UPLOAD_RATE_LIMIT

# Small enough to exercise the ceiling without allocating gigabytes in a test.
TEST_CAP = 64 * 1024

UPLOAD_URL = "/api/public/contribute/uploads"


def _client(monkeypatch: MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    return TestClient(create_app())


def test_upload_over_the_size_cap_is_refused(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES", str(TEST_CAP))
    client = _client(monkeypatch)
    oversized = b"x" * (TEST_CAP + 1024)
    response = client.post(UPLOAD_URL, files={"file": ("huge.mov", oversized, "video/quicktime")})
    assert response.status_code == 413, (
        "An anonymous caller must not be able to write an unbounded file to the "
        f"station's disk; got {response.status_code}."
    )


def test_oversized_upload_does_not_leave_a_partial_file_behind(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    """Refusing late is still a disk-fill if the partial write survives."""
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES", str(TEST_CAP))
    client = _client(monkeypatch)
    oversized = b"x" * (TEST_CAP + 1024)
    client.post(UPLOAD_URL, files={"file": ("huge.mov", oversized, "video/quicktime")})
    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == [], f"partial upload left on disk: {leftovers}"


def test_upload_is_rate_limited_per_ip(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    client = _client(monkeypatch)
    small = b"tiny-but-valid"
    statuses = [
        client.post(
            UPLOAD_URL, files={"file": (f"clip-{i}.mov", small, "video/quicktime")}
        ).status_code
        for i in range(UPLOAD_RATE_LIMIT + 3)
    ]
    assert 429 in statuses, (
        f"{UPLOAD_RATE_LIMIT + 3} anonymous uploads in one window produced no 429; "
        f"statuses={statuses}"
    )


def test_a_normal_upload_still_works(monkeypatch: MonkeyPatch, tmp_path) -> None:
    """The guards must not break the legitimate contributor path."""
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path))
    client = _client(monkeypatch)
    response = client.post(
        UPLOAD_URL, files={"file": ("show.mov", b"real-media-bytes", "video/quicktime")}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "show.mov"
    assert body["size_bytes"] == len(b"real-media-bytes")
