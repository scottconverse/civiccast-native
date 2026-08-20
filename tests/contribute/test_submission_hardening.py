# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The public submission endpoint must not be an open review-queue-flood surface.

GauntletGate rc18 re-gate PE-1 (Critical). ``POST /api/public/contribute/submissions``
is the one public POST that had no per-IP rate limit -- ``/uploads`` and the status
route both close that gap, this one was missed. An unauthenticated caller could flood
the operator review queue as fast as it can send requests.

Second half of the same finding: ``upload_ref`` is validated real (QA-3 recomputes its
sha256 against a file inside the upload directory) but never marked consumed, so ONE
real uploaded file could be attached to unlimited submissions -- corrupting the
provenance the review queue exists to protect. A given upload must back at most one
submission.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app


def _client(monkeypatch: MonkeyPatch, upload_dir: Path) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(upload_dir))
    return TestClient(create_app())


def _real_media(upload_dir: Path, name: str, content: bytes) -> dict[str, object]:
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / name
    path.write_bytes(content)
    return {
        "upload_ref": str(path),
        "filename": name,
        "content_type": "video/quicktime",
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _payload(media: dict[str, object]) -> dict[str, object]:
    return {
        "contributor": {
            "account_id": "arts-center",
            "display_name": "Arts Center",
            "contact_email": "producer@example.test",
            "organization": "Arts Center",
        },
        "channel_id": "public",
        "title": "Community Arts Magazine",
        "description": "A half-hour program from local arts producers.",
        "tags": ["arts", "community"],
        "producer_name": "Producer One",
        "requested_air_date": "2026-05-31T18:00:00Z",
        "media": media,
        "agreements": [
            {
                "agreement_id": "community-media-submission",
                "version": "2026-05-31",
                "accepted_at": "2026-05-31T18:00:00Z",
                "accepted_by_name": "Producer One",
            }
        ],
        "notifications": [{"kind": "email", "target": "producer@example.test"}],
    }


def test_submissions_are_rate_limited_per_ip(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """PE-1: the public submission POST must trip 429 for a caller hammering it.

    Each submission gets its own real upload file so single-use (below) does not
    reject the request before the rate limiter is even consulted -- this test is
    about the rate limit alone.
    """
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_SUBMISSION_RATE_LIMIT", "3")
    client = _client(monkeypatch, tmp_path)

    statuses = []
    for index in range(5):
        media = _real_media(tmp_path, f"clip-{index}.mov", f"real-bytes-{index}".encode())
        statuses.append(
            client.post("/api/public/contribute/submissions", json=_payload(media)).status_code
        )

    assert statuses[:3] == [201, 201, 201], statuses
    assert 429 in statuses[3:], (
        f"5 anonymous submissions against a limit of 3 produced no 429; statuses={statuses}"
    )


def test_submission_rate_limit_sets_retry_after(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """A 429 without Retry-After is not an actionable answer to the contributor."""
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_SUBMISSION_RATE_LIMIT", "1")
    client = _client(monkeypatch, tmp_path)

    client.post(
        "/api/public/contribute/submissions",
        json=_payload(_real_media(tmp_path, "first.mov", b"first-bytes")),
    )
    limited = client.post(
        "/api/public/contribute/submissions",
        json=_payload(_real_media(tmp_path, "second.mov", b"second-bytes")),
    )

    assert limited.status_code == 429, limited.text
    assert int(limited.headers["Retry-After"]) > 0


def test_upload_ref_is_single_use(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """PE-1 part 2: one uploaded file must back at most one submission.

    The same real ``upload_ref`` attached to a second submission must be refused
    (409 Conflict), not silently accepted -- otherwise one upload forges unlimited
    queue entries and the provenance the queue records is meaningless.
    """
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_SUBMISSION_RATE_LIMIT", "100")
    client = _client(monkeypatch, tmp_path)
    media = _real_media(tmp_path, "reused.mov", b"one-and-only-upload")

    first = client.post("/api/public/contribute/submissions", json=_payload(media))
    second = client.post("/api/public/contribute/submissions", json=_payload(media))

    assert first.status_code == 201, first.text
    assert second.status_code == 409, (
        f"the same upload_ref was accepted for a second submission (status "
        f"{second.status_code}); an upload must be single-use"
    )


def test_a_distinct_upload_per_submission_still_works(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Single-use must not break the honest path: distinct uploads, distinct submissions."""
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_SUBMISSION_RATE_LIMIT", "100")
    client = _client(monkeypatch, tmp_path)

    first = client.post(
        "/api/public/contribute/submissions",
        json=_payload(_real_media(tmp_path, "one.mov", b"programme-one")),
    )
    second = client.post(
        "/api/public/contribute/submissions",
        json=_payload(_real_media(tmp_path, "two.mov", b"programme-two")),
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
