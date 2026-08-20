# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contributor workflow router tests."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def _client(monkeypatch: MonkeyPatch, upload_dir: Path) -> TestClient:
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(upload_dir))
    return TestClient(create_app())


def _real_media(
    upload_dir: Path,
    name: str = "show-one.mov",
    content: bytes = b"real-video-bytes",
) -> dict[str, object]:
    """Write a REAL file inside *upload_dir* and describe it accurately.

    QA-3: store.create_submission now resolves ``upload_ref`` against the
    contributor upload directory and recomputes ``sha256``/``size_bytes``
    from the file on disk, so a fabricated path (like the old
    ``uploads/arts-center/show-one.mov`` placeholder) is rejected outright.
    """
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


def test_public_submission_flow_separates_contributor_from_operator_queue(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(monkeypatch, tmp_path)

    agreement = client.get("/api/public/contribute/agreements/current")
    created = client.post(
        "/api/public/contribute/submissions", json=_payload(_real_media(tmp_path))
    )

    assert agreement.status_code == 200
    assert agreement.json()["agreement_id"] == "community-media-submission"
    assert created.status_code == 201, created.text
    receipt = created.json()
    status = client.get(
        f"/api/public/contribute/submissions/{receipt['submission_id']}/status",
        params={"receipt_token": receipt["receipt_token"]},
    )
    queue = client.get("/api/staff/contribute/submissions", headers=_STAFF_HEADERS)

    assert status.status_code == 200
    assert status.json()["state"] == "submitted"
    assert queue.status_code == 200
    assert queue.json()["needs_operator_action"] == 1
    assert queue.json()["submissions"][0]["contributor"]["tier"] == "contributor"


def test_public_upload_endpoint_returns_media_reference(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/public/contribute/uploads",
        files={"file": ("program.mov", b"video-bytes", "video/quicktime")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "program.mov"
    assert payload["content_type"] == "video/quicktime"
    assert payload["size_bytes"] == len(b"video-bytes")
    assert len(payload["sha256"]) == 64
    assert (tmp_path / "program.mov").exists()


def test_public_status_requires_receipt_token(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/public/contribute/submissions", json=_payload(_real_media(tmp_path))
    ).json()

    response = client.get(
        f"/api/public/contribute/submissions/{created['submission_id']}/status",
        params={"receipt_token": "x" * 24},
    )

    assert response.status_code == 403


def test_staff_review_can_edit_accept_schedule_and_report(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/public/contribute/submissions", json=_payload(_real_media(tmp_path))
    ).json()

    accepted = client.post(
        f"/api/staff/contribute/submissions/{created['submission_id']}/review",
        headers=_STAFF_HEADERS,
        json={
            "action": "accept",
            "metadata_patch": {"title": "Edited Community Arts Magazine"},
            "broken_media_gate": {
                "state": "passed",
                "checked_at": "2026-05-31T18:05:00Z",
                "summary": "Video and audio probes passed.",
            },
        },
    )
    scheduled = client.post(
        f"/api/staff/contribute/submissions/{created['submission_id']}/review",
        headers=_STAFF_HEADERS,
        json={
            "action": "schedule",
            "schedule_handoff": {
                "channel_id": "public",
                "requested_start": "2026-06-01T18:00:00Z",
                "duration_seconds": 1800,
            },
        },
    )
    report = client.get("/api/staff/contribute/reports/producers", headers=_STAFF_HEADERS)
    outbox = client.get("/api/staff/contribute/notifications/outbox", headers=_STAFF_HEADERS)

    assert accepted.status_code == 200
    assert accepted.json()["title"] == "Edited Community Arts Magazine"
    assert scheduled.status_code == 200
    assert scheduled.json()["state"] == "scheduled"
    assert scheduled.json()["schedule_handoff"]["channel_id"] == "public"
    assert report.status_code == 200
    assert report.json()["rows"][0]["scheduled_count"] == 1
    assert outbox.status_code == 200
    assert [notice["state"] for notice in outbox.json()["notifications"]] == [
        "submitted",
        "accepted",
        "scheduled",
    ]


def test_contributor_openapi_exports_contracts(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    schema = client.get("/openapi.json").json()

    assert "/api/public/contribute/submissions" in schema["paths"]
    assert "/api/staff/contribute/submissions" in schema["paths"]
    assert "/api/staff/contribute/reports/producers" in schema["paths"]
    assert "/api/staff/contribute/notifications/outbox" in schema["paths"]
    assert "ContributorSubmissionCreate" in schema["components"]["schemas"]
    assert "ContributorReviewQueue" in schema["components"]["schemas"]
    assert "ContributorNotificationOutbox" in schema["components"]["schemas"]
    assert "ProducerActivityReport" in schema["components"]["schemas"]


def test_public_status_rate_limits_receipt_token_guessing(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Audit item #27 review: the status route verifies a receipt secret and
    had no rate limit anywhere on the path — the same gap the paywall
    verify/access routes already close. Wrong-token hammering must trip
    429 with Retry-After; the budget is per app instance so other tests
    are unaffected."""

    client = _client(monkeypatch, tmp_path)
    created = client.post(
        "/api/public/contribute/submissions", json=_payload(_real_media(tmp_path))
    ).json()

    url = f"/api/public/contribute/submissions/{created['submission_id']}/status"
    statuses = [
        client.get(url, params={"receipt_token": f"guess-{index:018d}xxxxxx"}).status_code
        for index in range(35)
    ]

    assert statuses[:30] == [403] * 30
    assert set(statuses[30:]) == {429}
    limited = client.get(url, params={"receipt_token": "x" * 24})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_create_submission_rejects_a_fabricated_upload_ref(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """QA-3: a client-supplied media reference that isn't a real upload
    inside the station's upload directory must be rejected with 422, not
    silently accepted into the operator review queue."""
    client = _client(monkeypatch, tmp_path)

    fabricated_media = {
        "upload_ref": "uploads/arts-center/show-one.mov",
        "filename": "show-one.mov",
        "content_type": "video/quicktime",
        "size_bytes": 1024,
        "sha256": "A" * 64,
    }

    response = client.post("/api/public/contribute/submissions", json=_payload(fabricated_media))

    assert response.status_code == 422, response.text


class _SlowReadDict(dict[str, int]):
    """A dict that sleeps on every read, to widen the read->write window.

    An earlier version of this test drove the real ``try_reserve`` at 16 threads
    and asserted no overshoot -- but an adversarial review showed the assertion
    held even with the lock REMOVED, because the unlocked critical section is
    only a few bytecode ops and CPython's GIL almost never interleaves it. The
    test proved nothing about the real method. This dict forces the interleave:
    the sleep sits between ``try_reserve``'s read and its write. WITH the lock
    the sleep happens while the lock is held, so threads serialise and no
    overshoot is possible; WITHOUT the lock the sleeps overlap, every thread
    reads the same stale total, and the ceiling is blown -- so this test now
    genuinely fails if the lock is ever removed (verified by hand: reverting
    ``try_reserve`` to a lockless snapshot-then-add makes it red).
    """

    def get(self, key: str, default: int = 0) -> int:  # type: ignore[override]
        # Read the underlying value NOW, then stall, so the caller acts on a
        # snapshot that is stale by the time it writes. The sleep must be AFTER
        # the read, not before: a sleep before the read just delays it until the
        # value is already fresh, which is why an earlier attempt did not race.
        value = super().get(key, default)
        time.sleep(0.01)
        return value


def test_upload_byte_budget_is_atomic_under_concurrency() -> None:
    """QA-2 race: concurrent reservations from one key cannot exceed the ceiling.

    Drives many threads at the REAL ``ContributorUploadByteBudget.try_reserve``,
    with its backing dict instrumented (:class:`_SlowReadDict`) to widen the
    check-then-act window so the race is actually reachable under the GIL. With
    the lock in place the reservations serialise and the committed total never
    exceeds the ceiling; without it they overshoot (see the class docstring).
    """
    from concurrent.futures import ThreadPoolExecutor

    from civiccast.contribute.router import ContributorUploadByteBudget

    ceiling = 10 * 1024
    chunk = 3 * 1024  # three fit (9 KiB); a fourth would exceed 10 KiB
    workers = 16

    budget = ContributorUploadByteBudget()
    budget._totals = _SlowReadDict()  # widen the read->write window
    barrier = threading.Barrier(workers)

    def reserve_once(_: int) -> bool:
        barrier.wait()  # release all threads into try_reserve together
        return budget.try_reserve("1.2.3.4", chunk, ceiling)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(reserve_once, range(workers)))

    committed = sum(1 for ok in results if ok) * chunk
    assert committed <= ceiling, (
        f"concurrent reservations reached {committed} bytes past a {ceiling}-byte "
        "ceiling -- the per-IP byte budget's check-and-increment is not atomic"
    )
    assert budget.total("1.2.3.4") == committed


def test_upload_per_ip_cumulative_budget_blocks_before_the_directory_ceiling(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """QA-2 part 3: a single address must not be able to consume the whole
    contributor-upload directory budget by itself. This must trip well
    BEFORE the (much larger) aggregate directory ceiling, from ONE address
    alone, even though the directory as a whole is nowhere near full."""
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_PER_IP_MAX_BYTES", str(10 * 1024))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR_MAX_BYTES", str(10 * 1024 * 1024))
    # rc18 re-gate PE-2/TE-1: the directory ceiling now reserves each upload's
    # worst case (the per-request max) up front, so the per-request max must be
    # <= the directory ceiling or every upload is refused before the per-IP
    # budget this test targets can trip. The default max (2 GiB) exceeds the
    # 10 MiB ceiling set here; pin it consistent with the ceiling.
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_MAX_UPLOAD_BYTES", str(1024 * 1024))
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_RATE_LIMIT", "100")
    client = _client(monkeypatch, tmp_path)

    chunk = b"x" * (4 * 1024)
    statuses = [
        client.post(
            "/api/public/contribute/uploads",
            files={"file": (f"clip-{i}.mov", chunk, "video/quicktime")},
        ).status_code
        for i in range(4)
    ]

    assert statuses[0] == 201, statuses
    assert statuses[1] == 201, statuses
    assert statuses[2] in {429, 507}, (
        f"a single address uploaded {3 * len(chunk)} bytes against a "
        f"{10 * 1024}-byte per-IP ceiling and was still accepted; statuses={statuses}"
    )
    dir_total = sum(f.stat().st_size for f in tmp_path.iterdir() if f.is_file())
    assert dir_total < 10 * 1024 * 1024, (
        "the per-IP budget must trip well before the aggregate directory "
        f"ceiling -- directory only holds {dir_total} bytes of a 10 MiB ceiling"
    )
