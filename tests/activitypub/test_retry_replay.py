# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Operator replay surface for dead-lettered ActivityPub deliveries (Beta B2).

A dead-lettered delivery told the operator a follower never heard about a
recording and offered no recourse. The replay endpoint grants a fresh attempt
budget and re-queues the row for the retry worker; the staff list endpoint
makes the queue (including dead letters) visible at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from civiccast.activitypub.models import DeliveryRetryRecord
from civiccast.activitypub.remote import DeliveryResult
from civiccast.activitypub.retry_worker import ActivityPubRetrySettings, ActivityPubRetryWorker
from civiccast.app import create_app

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def _store(client: TestClient):  # type: ignore[no-untyped-def]
    return client.app.state.store_bundle.activitypub_store()  # type: ignore[attr-defined]


def _seed_retry(client: TestClient, *, state: str, attempts: int = 8) -> str:
    record = DeliveryRetryRecord(
        retry_id="apr-replay-test",
        activity_id="https://station.example/activities/publish-9",
        inbox_url="https://town.example/users/resident/inbox",
        activity={"type": "Create"},
        state=state,  # type: ignore[arg-type]
        attempts=attempts,
        next_attempt_at=None if state != "pending" else _NOW,
        last_status_code=503,
        last_error="remote error",
        created_at=_NOW,
        updated_at=_NOW,
    )
    _store(client).enqueue_delivery_retry(record)
    return record.retry_id


class TestListEndpoint:
    def test_lists_the_retry_queue_including_dead_letters(self, client: TestClient) -> None:
        _seed_retry(client, state="dead_letter")

        response = client.get("/api/staff/activitypub/delivery-retries")

        assert response.status_code == 200, response.text
        rows = response.json()["delivery_retries"]
        assert [row["retry_id"] for row in rows] == ["apr-replay-test"]
        assert rows[0]["state"] == "dead_letter"
        assert rows[0]["last_status_code"] == 503


class TestReplayEndpoint:
    def test_replay_requeues_a_dead_letter_and_worker_delivers_it(self, client: TestClient) -> None:
        retry_id = _seed_retry(client, state="dead_letter")

        response = client.post(f"/api/staff/activitypub/delivery-retries/{retry_id}/replay")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "pending"
        assert body["attempts"] == 0
        assert body["next_attempt_at"] is not None

        class OkClient:
            def deliver(self, *, inbox_url: str, activity: dict) -> DeliveryResult:  # type: ignore[type-arg]
                return DeliveryResult(
                    inbox_url=inbox_url,
                    status_code=202,
                    response_body="",
                    delivered_at=_NOW,
                )

        worker = ActivityPubRetryWorker(
            _store(client),
            OkClient(),
            settings=ActivityPubRetrySettings(
                mode="inline", poll_seconds=60, backoff_seconds=0, max_attempts=8
            ),
        )
        # Replay sets next_attempt_at to its own wall-clock moment; scan just
        # after that (not a hardcoded constant, which is only "due" within a
        # narrow wall-clock window).
        scan_at = datetime.fromisoformat(body["next_attempt_at"]) + timedelta(minutes=1)
        worker.run_once(now=scan_at)
        rows = _store(client).list_delivery_retries()
        assert rows[0].state == "delivered"

    def test_replay_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.post("/api/staff/activitypub/delivery-retries/missing/replay")
        assert response.status_code == 404

    @pytest.mark.parametrize("state", ["pending", "delivered"])
    def test_replay_conflicts_unless_dead_letter(self, client: TestClient, state: str) -> None:
        retry_id = _seed_retry(client, state=state, attempts=1)
        response = client.post(f"/api/staff/activitypub/delivery-retries/{retry_id}/replay")
        assert response.status_code == 409
        assert state in response.text

    def test_replay_requires_auth(self, client: TestClient) -> None:
        retry_id = _seed_retry(client, state="dead_letter")
        response = client.post(
            f"/api/staff/activitypub/delivery-retries/{retry_id}/replay",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401
